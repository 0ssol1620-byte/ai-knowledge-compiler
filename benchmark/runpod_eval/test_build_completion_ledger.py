from __future__ import annotations

from pathlib import Path

import pytest
from build_completion_ledger import (
    build_ledger,
    load_delivered,
    load_retry_rounds,
    load_roster,
    parse_retry_plan_args,
    summarise_recovery,
)


def _retry_plan(tmp_path: Path, name: str, cases: list[tuple[str, str]]) -> Path:
    path = tmp_path / f"{name}.json"
    path.write_text(
        __import__("json").dumps(
            {
                "failed_input_count": len(cases),
                "failures": [
                    {"benchmark_id": suite, "case_id": case} for suite, case in cases
                ],
                "receipt_sha256": f"sha256:{name}",
            }
        ),
        encoding="utf-8",
    )
    return path


def _plan(*entries: tuple[str, str, int]) -> dict:
    suites: dict[str, dict] = {}
    for benchmark_id, case_id, worker in entries:
        suite = suites.setdefault(
            benchmark_id, {"benchmark_id": benchmark_id, "shards": {}}
        )
        shard = suite["shards"].setdefault(
            worker,
            {"worker_index": worker, "shard_id": f"shard-{worker}", "inputs": []},
        )
        shard["inputs"].append(
            {
                "case_id": case_id,
                "document_id": f"{benchmark_id}:{case_id}",
                "input_relative_path": f"inputs/{case_id}.pdf",
            }
        )
    return {
        "total_input_count": len(entries),
        "suites": [
            {"benchmark_id": s["benchmark_id"], "shards": list(s["shards"].values())}
            for s in suites.values()
        ],
    }


def _write(root: Path, suite: str, case: str, text: str) -> None:
    target = root / suite / "markdown-repeat-1"
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{case}.md").write_text(text, encoding="utf-8")


def test_roster_carries_assignment_for_every_planned_case() -> None:
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    entry = roster[("parsebench", "parsebench-a")]
    assert entry["assigned_worker_index"] == 0
    assert entry["source_relative_path"] == "inputs/parsebench-a.pdf"


def test_plan_whose_declared_total_disagrees_with_its_shards_is_rejected() -> None:
    plan = _plan(("parsebench", "parsebench-a", 0))
    plan["total_input_count"] = 99
    with pytest.raises(ValueError, match="declares 99"):
        load_roster(plan)


def test_a_case_planned_twice_is_rejected() -> None:
    plan = _plan(("parsebench", "parsebench-a", 0))
    plan["suites"][0]["shards"][0]["inputs"].append(
        {"case_id": "parsebench-a", "document_id": "x", "input_relative_path": "y"}
    )
    with pytest.raises(ValueError, match="two shards"):
        load_roster(plan)


def test_placeholder_predictions_do_not_count_as_delivered(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-a", "real content")
    _write(baseline, "parsebench", "parsebench-b", "")
    delivered = load_delivered([baseline])
    assert set(delivered) == {("parsebench", "parsebench-a")}


def test_recovery_tree_closes_the_gap_and_is_credited(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    recovery = tmp_path / "collected-operational-retry"
    _write(baseline, "parsebench", "parsebench-a", "baseline content")
    _write(baseline, "parsebench", "parsebench-b", "")
    _write(recovery, "parsebench", "parsebench-b", "recovered content")

    roster = load_roster(
        _plan(("parsebench", "parsebench-a", 0), ("parsebench", "parsebench-b", 0))
    )
    ledger = build_ledger(
        roster,
        load_delivered([baseline, recovery]),
        baseline_root_name="collected-full",
    )
    assert ledger["resolved_cases"] == 2
    assert ledger["unresolved_cases"] == 0
    assert ledger["delivered_by_baseline_run"] == 1
    assert ledger["delivered_by_operational_recovery"] == 1
    assert ledger["completion_fraction"] == 1.0


def test_unresolved_cases_are_itemised_with_their_assignment(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-a", "content")
    roster = load_roster(
        _plan(("parsebench", "parsebench-a", 0), ("parsebench", "parsebench-lost", 2))
    )
    ledger = build_ledger(
        roster, load_delivered([baseline]), baseline_root_name="collected-full"
    )
    assert ledger["unresolved_cases"] == 1
    lost = ledger["unresolved_case_detail"][0]
    assert lost["case_id"] == "parsebench-lost"
    assert lost["assigned_worker_index"] == 2
    assert lost["source_relative_path"] == "inputs/parsebench-lost.pdf"


def test_delivered_case_missing_from_the_plan_is_an_error(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-stray", "content")
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    with pytest.raises(ValueError, match="absent from the campaign plan"):
        build_ledger(roster, load_delivered([baseline]), baseline_root_name="collected-full")


def test_same_case_in_two_recovery_trees_is_counted_once(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    first = tmp_path / "recovery-one"
    second = tmp_path / "recovery-two"
    _write(baseline, "parsebench", "parsebench-a", "")
    _write(first, "parsebench", "parsebench-a", "recovered once")
    _write(second, "parsebench", "parsebench-a", "recovered again")
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    ledger = build_ledger(
        roster,
        load_delivered([baseline, first, second]),
        baseline_root_name="collected-full",
    )
    assert ledger["resolved_cases"] == 1
    assert ledger["delivered_by_operational_recovery"] == 1


def test_recovery_is_not_credited_for_a_case_the_baseline_already_delivered(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "collected-full"
    recovery = tmp_path / "collected-operational-retry"
    # The baseline produced this case; a later round happens to hold a copy too.
    _write(baseline, "parsebench", "parsebench-a", "baseline content")
    _write(recovery, "parsebench", "parsebench-a", "duplicate copy")
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    ledger = build_ledger(
        roster,
        load_delivered([baseline, recovery]),
        baseline_root_name="collected-full",
    )
    assert ledger["delivered_by_baseline_run"] == 1
    assert ledger["delivered_by_operational_recovery"] == 0


def test_recovery_rate_uses_the_broken_cases_as_denominator(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    recovery = tmp_path / "collected-operational-retry"
    # Three cases broke; recovery saved two of them. The fourth never broke.
    _write(baseline, "parsebench", "parsebench-fine", "baseline content")
    for case in ("parsebench-a", "parsebench-b", "parsebench-c"):
        _write(baseline, "parsebench", case, "")
    _write(recovery, "parsebench", "parsebench-a", "rescued")
    _write(recovery, "parsebench", "parsebench-b", "rescued")

    roster = load_roster(
        _plan(
            ("parsebench", "parsebench-fine", 0),
            ("parsebench", "parsebench-a", 0),
            ("parsebench", "parsebench-b", 0),
            ("parsebench", "parsebench-c", 0),
        )
    )
    rounds = load_retry_rounds(
        [
            (
                "round-1",
                _retry_plan(
                    tmp_path,
                    "r1",
                    [
                        ("parsebench", "parsebench-a"),
                        ("parsebench", "parsebench-b"),
                        ("parsebench", "parsebench-c"),
                    ],
                ),
            )
        ]
    )
    ledger = build_ledger(
        roster,
        load_delivered([baseline, recovery]),
        baseline_root_name="collected-full",
        retry_rounds=rounds,
    )
    outcome = ledger["recovery_outcome"]
    # Denominator is 3 broken cases, not the 4-case corpus.
    assert outcome["cases_that_needed_recovery"] == 3
    assert outcome["cases_recovered"] == 2
    assert outcome["recovery_rate_on_cases_that_needed_it"] == pytest.approx(2 / 3)
    assert outcome["cases_attempted_but_never_recovered"] == 1


def test_cases_needing_a_second_round_are_counted(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    second = tmp_path / "collected-round2"
    _write(baseline, "parsebench", "parsebench-a", "")
    _write(second, "parsebench", "parsebench-a", "rescued on the second try")
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    rounds = load_retry_rounds(
        [
            ("round-1", _retry_plan(tmp_path, "r1", [("parsebench", "parsebench-a")])),
            ("round-2", _retry_plan(tmp_path, "r2", [("parsebench", "parsebench-a")])),
        ]
    )
    ledger = build_ledger(
        roster,
        load_delivered([baseline, second]),
        baseline_root_name="collected-full",
        retry_rounds=rounds,
    )
    outcome = ledger["recovery_outcome"]
    assert outcome["cases_requiring_more_than_one_round"] == 1
    assert outcome["per_round"][0]["cases_attempted"] == 1
    assert outcome["cases_recovered"] == 1


def test_unresolved_case_that_no_round_attempted_is_reported_separately(
    tmp_path: Path,
) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-attempted", "")
    _write(baseline, "parsebench", "parsebench-ignored", "")
    roster = load_roster(
        _plan(
            ("parsebench", "parsebench-attempted", 0),
            ("parsebench", "parsebench-ignored", 0),
        )
    )
    rounds = load_retry_rounds(
        [("round-1", _retry_plan(tmp_path, "r1", [("parsebench", "parsebench-attempted")]))]
    )
    ledger = build_ledger(
        roster,
        load_delivered([baseline]),
        baseline_root_name="collected-full",
        retry_rounds=rounds,
    )
    outcome = ledger["recovery_outcome"]
    assert outcome["cases_attempted_but_never_recovered"] == 1
    assert outcome["cases_unresolved_and_never_attempted"] == 1
    ignored = outcome["unresolved_and_never_attempted_detail"][0]
    assert ignored["case_id"] == "parsebench-ignored"


def test_retry_plan_whose_declared_count_disagrees_is_rejected(tmp_path: Path) -> None:
    import json as _json

    path = tmp_path / "bad.json"
    path.write_text(
        _json.dumps(
            {
                "failed_input_count": 5,
                "failures": [{"benchmark_id": "parsebench", "case_id": "parsebench-a"}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="declares 5"):
        load_retry_rounds([("round-1", path)])


def test_retry_plan_attempting_an_unplanned_case_is_rejected(tmp_path: Path) -> None:
    roster = load_roster(_plan(("parsebench", "parsebench-a", 0)))
    rounds = load_retry_rounds(
        [("round-1", _retry_plan(tmp_path, "r1", [("parsebench", "parsebench-ghost")]))]
    )
    with pytest.raises(ValueError, match="absent from the plan"):
        summarise_recovery(rounds, {}, roster)


def test_retry_plan_argument_requires_label_and_path() -> None:
    # The path is never opened here; only the LABEL=PATH split is under test.
    argument = "round-1=plans/a.json"
    assert parse_retry_plan_args([argument]) == [("round-1", Path("plans/a.json"))]
    with pytest.raises(ValueError, match="LABEL=PATH"):
        parse_retry_plan_args(["plans/a.json"])


def test_per_suite_counts_add_up(tmp_path: Path) -> None:
    baseline = tmp_path / "collected-full"
    _write(baseline, "parsebench", "parsebench-a", "content")
    _write(baseline, "omnidocbench", "omnidocbench-a", "content")
    roster = load_roster(
        _plan(
            ("parsebench", "parsebench-a", 0),
            ("parsebench", "parsebench-missing", 0),
            ("omnidocbench", "omnidocbench-a", 1),
        )
    )
    ledger = build_ledger(
        roster, load_delivered([baseline]), baseline_root_name="collected-full"
    )
    suites = ledger["cases_by_suite"]
    assert suites["parsebench"] == {"planned": 2, "resolved": 1, "unresolved": 1}
    assert suites["omnidocbench"] == {"planned": 1, "resolved": 1, "unresolved": 0}
    total_planned = sum(s["planned"] for s in suites.values())
    assert total_planned == ledger["planned_cases"]
