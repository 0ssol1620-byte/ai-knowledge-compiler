"""SFI1 acquisition frame and executor. Fixtures only — no network, no cohort.

Every test here runs against a synthetic lineage list written into `tmp_path`.
Nothing fetches, nothing canonicalises, nothing classifies and nothing touches a
real cohort lineage, because the two demoted predecessor studies were demoted
for exactly that: an execution against real lineages spends their held-out
property whether or not its numbers are kept.

The one place a real artifact is read is the spent-set derivation, which reads
SFH1's receipts. Reading a predecessor's published receipt costs nothing; it is
the reason the exclusion is derived rather than hand-copied.
"""

from __future__ import annotations

import ast
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition"):
    if str(NS / _sub) not in sys.path:
        sys.path.insert(0, str(NS / _sub))
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import sfi1_worker as worker  # noqa: E402
import sources_sfi1 as frame_module  # noqa: E402

# --- fixtures -----------------------------------------------------------------


def _lineage(lineage_id: str, family: str = "git_docs") -> dict[str, Any]:
    return {
        "lineage_id": lineage_id,
        "family": family,
        "suffix": ".md",
        "licence": "MIT",
    }


def _write_frame(path: Path, lineages: list[dict[str, Any]]) -> Path:
    path.write_text(
        json.dumps({"lineage_count": len(lineages), "lineages": lineages}),
        encoding="utf-8",
    )
    return path


# --- 1. disjoint from SFH1's spent set ----------------------------------------


def test_the_sfi1_frame_is_disjoint_from_everything_sfh1_spent(tmp_path: Path) -> None:
    """Computed on both sides. Neither list is written down in this test.

    The candidate frame is built out of the spent lineages *themselves*, which
    is the adversarial case: if the exclusion works the intersection is
    necessarily empty, and if it does not this fails rather than passing because
    a fixture happened to avoid the overlap.
    """
    spent = frame_module.spent_lineages()
    assert spent, "the spent set is empty; the derivation read nothing"

    listing = _write_frame(
        tmp_path / "frame.json",
        [_lineage(lineage_id) for lineage_id in sorted(spent)]
        + [_lineage("git:fresh/repo:docs/never-seen.md")],
    )
    built = frame_module.build_frame(listing, spent=spent)
    eligible = {row["lineage_id"] for row in built["lineages"]}

    assert eligible & spent == set()
    assert eligible == {"git:fresh/repo:docs/never-seen.md"}
    assert len(built["dropped"]) == len(spent)


def test_the_spent_set_is_derived_from_artifacts_not_written_down() -> None:
    """The derivation must actually consume SFH1's receipts.

    A hand-copied list would still make the disjointness test pass, so this
    checks the mechanism: the receipts on disk name a frame, that frame's
    lineage ids must all be in the spent set, and there must be many more of
    them than any human would paste into a literal.
    """
    receipts = sorted((NS / "receipts").glob("sfh1-source-faithfulness--*.json"))
    assert receipts, "no SFH1 receipt on disk; the derivation cannot be checked"

    spent = frame_module.spent_lineages()
    walked_whole_frames = 0
    for receipt_path in receipts:
        body = json.loads(receipt_path.read_text(encoding="utf-8"))
        block = body["frame"]
        if body["lineages_considered"] < block["candidates"]:
            continue
        walked_whole_frames += 1
        listing = frame_module.ROOT / block["source"]
        body = json.loads(listing.read_text(encoding="utf-8"))
        ids = {row["lineage_id"] for row in body["lineages"]}
        assert ids <= spent

    assert walked_whole_frames >= 1
    assert len(spent) > 1000, "SFH1 walked thousands of lineages; the spent set must show it"


# --- 2. the forensic diagnostic cases are excluded ----------------------------


def test_the_four_forensic_diagnostic_cases_are_excluded(tmp_path: Path) -> None:
    listing = _write_frame(
        tmp_path / "frame.json",
        [
            _lineage(lineage_id, "encyclopedia_wikipedia")
            for lineage_id in frame_module.FORENSIC_LINEAGES
        ]
        + [_lineage("git:fresh/repo:docs/new.md", "git_docs")],
    )
    built = frame_module.build_frame(listing, spent=frozenset())
    assert [row["lineage_id"] for row in built["lineages"]] == ["git:fresh/repo:docs/new.md"]
    assert {row["code"] for row in built["dropped"]} == {frame_module.FORENSIC}
    assert len(built["dropped"]) == 4

    #: The four cases are named in the module and the reason is stated there.
    assert set(frame_module.FORENSIC_LINEAGES) == {
        "wikipedia:en:Three Villages",
        "wikipedia:en:Monteceneri",
        "wikipedia:en:Locarno",
        "git:pnpm/pnpm.io:docs/cli/change.md",
    }
    assert "certify the repair" in frame_module.__doc__


# --- 3. order_key is deterministic and salt-dependent -------------------------


def test_order_key_is_deterministic_and_salt_dependent() -> None:
    lineage_id = "git:example/one:docs/a.md"
    assert frame_module.order_key(lineage_id) == frame_module.order_key(lineage_id)
    assert frame_module.order_key(lineage_id, ":other") != frame_module.order_key(lineage_id)


def test_a_different_salt_produces_a_different_frame_order(tmp_path: Path) -> None:
    listing = _write_frame(
        tmp_path / "frame.json",
        [_lineage(f"git:example/repo:docs/{index}.md") for index in range(40)],
    )
    house = [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset())["lineages"]
    ]
    other = [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset(), salt=":sfi-v2")["lineages"]
    ]
    assert sorted(house) == sorted(other)
    assert house != other
    #: Same salt, same order, run twice — the order is a property of the salt
    #: and the ids, not of the filesystem or the dict iteration.
    assert house == [
        row["lineage_id"]
        for row in frame_module.build_frame(listing, spent=frozenset())["lineages"]
    ]


# --- 4. quotas are declared constants with a basis, not derived from outcome --


def test_the_sampling_constants_are_literals() -> None:
    literal = frame_module.sampling_constants_are_literal()
    assert literal == {name: True for name in literal}, literal
    assert set(literal) >= {
        "FAMILY_QUOTA",
        "FAMILY_SHARE",
        "PRIMARY_TARGET",
        "FLOOR",
        "MAX_PAYLOAD_BYTES",
    }


def test_the_quotas_are_read_only_and_carry_a_declared_basis() -> None:
    with pytest.raises(TypeError):
        frame_module.FAMILY_QUOTA["git_docs"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        frame_module.FAMILY_SHARE["git_docs"] = 1.0  # type: ignore[index]

    basis = frame_module.QUOTA_BASIS
    assert basis["basis"]
    assert "pass yield" in basis["explicitly_not_basis"]
    assert "outcome" in basis["explicitly_not_basis"]
    assert "forbidden" in basis["redistribution"]
    assert set(frame_module.FAMILY_QUOTA) == set(frame_module.FAMILY_SHARE)
    assert sum(frame_module.FAMILY_QUOTA.values()) == frame_module.PRIMARY_TARGET
    assert len(frame_module.FAMILY_QUOTA) == frame_module.FAMILIES_REQUIRED


def test_no_sampling_constant_is_computed_from_an_outcome() -> None:
    """The quotas must not reference an outcome-bearing name anywhere.

    Checked structurally: the module is parsed, the assignments for the sampling
    constants are located, and every identifier and string inside them is
    compared against the vocabulary an outcome is reported in. A literal cannot
    reference anything, so this only ever fires if someone replaces one with a
    computation — which is the failure the founder rule names.
    """
    outcome_words = (
        "verdict",
        "gates",
        "summary",
        "by_state",
        "result_digest",
        "pass_yield",
        "admitted",
        "receipt",
    )
    names = (
        "FAMILY_QUOTA",
        "FAMILY_SHARE",
        "PRIMARY_TARGET",
        "FLOOR",
        "FAMILIES_REQUIRED",
        "MAX_PAYLOAD_BYTES",
    )
    tree = ast.parse(Path(frame_module.__file__).read_text(encoding="utf-8"))
    checked = 0
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        )
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in names:
                continue
            checked += 1
            for child in ast.walk(node.value):
                if isinstance(child, ast.Name):
                    assert child.id == "MappingProxyType", child.id
                if isinstance(child, ast.Attribute):
                    pytest.fail(f"{target.id} reads an attribute: {ast.dump(child)}")
                if isinstance(child, ast.Constant) and isinstance(child.value, str):
                    lowered = child.value.lower()
                    for word in outcome_words:
                        assert word not in lowered, f"{target.id} mentions {word!r}"
    assert checked == len(names)


def test_the_payload_bound_publishes_its_basis_and_its_insensitivity() -> None:
    low, high = frame_module.MAX_PAYLOAD_INSENSITIVE_RANGE
    assert low < frame_module.MAX_PAYLOAD_BYTES < high
    assert high >= 3 * low, "an insensitivity claim over less than a 3x range is not much of one"
    assert "distribution" in frame_module.MAX_PAYLOAD_BASIS
    assert "outcome" in frame_module.MAX_PAYLOAD_NOT_BASIS
    assert 0.0 < frame_module.MAX_PAYLOAD_EXCLUDED_FRACTION_IN_SFH1 < 0.1


def test_the_unexercised_family_is_declared_rather_than_absent() -> None:
    """A family that is not in the frame must say so and say why."""
    assert "sec_edgar" not in frame_module.FAMILY_QUOTA
    assert "sec_edgar" in frame_module.UNEXERCISED_FAMILIES
    assert frame_module.SEC_ROOTS == ()
    assert "CIK" in frame_module.UNEXERCISED_FAMILIES["sec_edgar"]


# --- 5. the reducer is order-independent --------------------------------------


def _fake_result(lineage: dict[str, Any], code: str | None = None) -> dict[str, Any]:
    if code is not None:
        return {"code": code}
    return {
        "code": None,
        "family": lineage["family"],
        "lineage_id": lineage["lineage_id"],
        "suffix": lineage["suffix"],
        "after_version": "b",
        "before_version": "a",
        "adjacent": True,
    }


def test_the_reducer_is_order_independent(tmp_path: Path) -> None:
    lineages = [
        _lineage(f"git:example/repo:docs/{index}.md", "git_docs") for index in range(30)
    ] + [
        _lineage(f"ecfr:9:381:381.{index}", "regulation_ecfr") for index in range(20)
    ]
    listing = _write_frame(tmp_path / "frame.json", lineages)
    ordered = frame_module.build_frame(listing, spent=frozenset())["lineages"]

    base = {
        lineage["lineage_id"]: _fake_result(
            lineage, code="TOO_FEW_REVISIONS" if index % 7 == 0 else None
        )
        for index, lineage in enumerate(ordered)
    }
    expected = worker.reduction_digest(worker.reduce_results(ordered, base))

    generator = random.Random(20260823)  # noqa: S311 - shuffling a fixture, not a key
    for _ in range(8):
        items = list(base.items())
        generator.shuffle(items)
        shuffled = dict(items)
        reduced = worker.reduce_results(ordered, shuffled)
        assert worker.reduction_digest(reduced) == expected
        assert [row["lineage_id"] for row in reduced["admitted"]] == [
            row["lineage_id"] for row in worker.reduce_results(ordered, base)["admitted"]
        ]


def test_the_reducer_admits_in_frozen_order_not_arrival_order(tmp_path: Path) -> None:
    """The quota decides *which* lineages are admitted, so the order must bind."""
    lineages = [
        _lineage(f"git:example/repo:docs/{index}.md", "git_docs") for index in range(200)
    ]
    listing = _write_frame(tmp_path / "frame.json", lineages)
    ordered = frame_module.build_frame(listing, spent=frozenset())["lineages"]
    results = {lineage["lineage_id"]: _fake_result(lineage) for lineage in ordered}

    reduced = worker.reduce_results(ordered, results)
    quota = frame_module.FAMILY_QUOTA["git_docs"]
    assert len(reduced["admitted"]) == quota
    assert [row["lineage_id"] for row in reduced["admitted"]] == [
        lineage["lineage_id"] for lineage in ordered[:quota]
    ]


# --- 6. the worker refuses to run with no extractors --------------------------


class _EmptyRegistry:
    @staticmethod
    def registered_kinds() -> tuple[str, ...]:
        return ()

    @staticmethod
    def unclaimed_kinds() -> tuple[str, ...]:
        return ("CONTENT_TEXT",)


def test_require_extractors_refuses_an_empty_registry(monkeypatch: Any) -> None:
    monkeypatch.setattr(worker, "ir", _EmptyRegistry)
    with pytest.raises(worker.ExtractorsMissing) as raised:
        worker.require_extractors()
    assert "empty registry" in str(raised.value)
    assert "false pass" in str(raised.value)


def test_require_extractors_refuses_a_missing_ir(monkeypatch: Any) -> None:
    monkeypatch.setattr(worker, "ir", None)
    monkeypatch.setattr(worker, "_IR_IMPORT_ERROR", "ModuleNotFoundError: source_fact_ir")
    with pytest.raises(worker.ExtractorsMissing):
        worker.require_extractors()


def test_the_cli_refuses_rather_than_running_with_no_extractors(monkeypatch: Any) -> None:
    monkeypatch.setattr(worker, "ir", _EmptyRegistry)
    monkeypatch.setattr(worker, "require_frozen_protocol", lambda *_a, **_k: None)
    with pytest.raises(worker.ExtractorsMissing):
        worker.main([])


def test_the_cli_refuses_to_acquire_before_the_protocol_freeze(tmp_path: Any) -> None:
    with pytest.raises(RuntimeError) as raised:
        worker.require_frozen_protocol(tmp_path / "never-frozen.yaml")
    assert "spends their held-out property" in str(raised.value)


def test_evaluate_refuses_before_it_fetches_anything(monkeypatch: Any) -> None:
    """The refusal must precede acquisition, not follow it."""
    monkeypatch.setattr(worker, "ir", _EmptyRegistry)

    def _must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("evaluate reached the network with no extractors registered")

    with pytest.raises(worker.ExtractorsMissing):
        worker.evaluate(
            _lineage("git:example/one:docs/a.md"),
            _must_not_run,
            revisions_for=_must_not_run,
        )


# --- 7. every non-admitted lineage carries a failure code ---------------------


def test_every_frame_exclusion_carries_a_declared_failure_code(tmp_path: Path) -> None:
    spent = frozenset({"git:spent/repo:docs/old.md"})
    listing = _write_frame(
        tmp_path / "frame.json",
        [
            _lineage("git:spent/repo:docs/old.md", "git_docs"),
            _lineage("wikipedia:en:Locarno", "encyclopedia_wikipedia"),
            _lineage("sec:0000000000:10-K", "sec_edgar"),
            _lineage("git:fresh/repo:docs/new.md", "git_docs"),
        ],
    )
    built = frame_module.build_frame(listing, spent=spent)

    assert len(built["lineages"]) + len(built["dropped"]) == 4
    assert {row["code"] for row in built["dropped"]} == {
        frame_module.SPENT,
        frame_module.FORENSIC,
        frame_module.UNDECLARED_FAMILY,
    }
    for row in built["dropped"]:
        assert row["code"] in frame_module.FAILURE_CODES
        assert row["lineage_id"]


def test_every_reducer_rejection_carries_a_declared_failure_code(tmp_path: Path) -> None:
    lineages = [
        _lineage(f"git:example/repo:docs/{index}.md", "git_docs") for index in range(600)
    ]
    listing = _write_frame(tmp_path / "frame.json", lineages)
    ordered = frame_module.build_frame(listing, spent=frozenset())["lineages"]

    codes = ["TOO_FEW_REVISIONS", "PAYLOAD_UNAVAILABLE", "PAYLOAD_TOO_LARGE_TO_CLASSIFY", None]
    results = {
        lineage["lineage_id"]: _fake_result(lineage, code=codes[index % len(codes)])
        for index, lineage in enumerate(ordered)
    }
    reduced = worker.reduce_results(ordered, results)

    assert len(reduced["admitted"]) + len(reduced["rejected"]) == reduced["considered"]
    assert reduced["considered"] == len(ordered)
    for row in reduced["rejected"]:
        assert row["code"] in frame_module.FAILURE_CODES
    #: the quota must be one of the reasons, or this fixture proved nothing
    assert worker.BEYOND_QUOTA in {row["code"] for row in reduced["rejected"]}


def test_the_worker_codes_every_way_a_lineage_can_fail() -> None:
    """Every code the executor can emit is declared in the frame module."""
    emitted = {
        worker.LISTING_FAIL,
        worker.TOO_FEW,
        worker.NO_DIFF,
        worker.PAYLOAD_FAIL,
        worker.TOO_LARGE,
        worker.EMPTY_CANON,
        worker.NO_FACTS,
        worker.BEYOND_QUOTA,
    }
    assert emitted <= set(frame_module.FAILURE_CODES)


# --- 8. frame_digest is stable and changes when the frame changes -------------


def test_frame_digest_is_stable_across_runs(tmp_path: Path) -> None:
    listing = _write_frame(
        tmp_path / "frame.json",
        [_lineage(f"git:example/repo:docs/{index}.md") for index in range(25)],
    )
    first = frame_module.frame_digest(
        frame_module.build_frame(listing, spent=frozenset())["lineages"]
    )
    second = frame_module.frame_digest(
        frame_module.build_frame(listing, spent=frozenset())["lineages"]
    )
    assert first == second


def test_frame_digest_changes_when_the_frame_changes(tmp_path: Path) -> None:
    rows = [_lineage(f"git:example/repo:docs/{index}.md") for index in range(25)]
    base = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "a.json", rows), spent=frozenset()
        )["lineages"]
    )

    added = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(
                tmp_path / "b.json", [*rows, _lineage("git:example/repo:docs/extra.md")]
            ),
            spent=frozenset(),
        )["lineages"]
    )
    assert added != base

    removed = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "c.json", rows), spent=frozenset({rows[0]["lineage_id"]})
        )["lineages"]
    )
    assert removed != base

    reordered = frame_module.frame_digest(
        frame_module.build_frame(
            _write_frame(tmp_path / "d.json", rows), spent=frozenset(), salt=":sfi-v2"
        )["lineages"]
    )
    assert reordered != base, "the digest must pin the order, not only the membership"


def test_quota_digest_pins_the_sampling_constants() -> None:
    assert frame_module.quota_digest() == frame_module.quota_digest()
    assert frame_module.quota_digest().startswith("sha256:")


# --- the frame is refused, never silently empty -------------------------------


def test_an_unsealed_frame_raises_rather_than_returning_nothing(tmp_path: Path) -> None:
    with pytest.raises(frame_module.FrameNotFrozen) as raised:
        frame_module.build_frame(tmp_path / "not-sealed.json", spent=frozenset())
    assert "Refusing to return an empty frame" in str(raised.value)


def test_the_frame_report_acquires_nothing(tmp_path: Path) -> None:
    """The dry-run report must be buildable from the declaration alone."""
    listing = _write_frame(
        tmp_path / "frame.json",
        [
            _lineage("git:example/one:docs/a.md", "git_docs"),
            _lineage("ecfr:9:381:381.1", "regulation_ecfr"),
            _lineage("wikipedia:en:Example", "encyclopedia_wikipedia"),
            _lineage("sec:0000000000:10-K", "sec_edgar"),
        ],
    )
    report = worker.frame_report(listing)
    assert report["eligible"] == 3
    assert report["family_composition"] == {
        "git_docs": 1,
        "regulation_ecfr": 1,
        "encyclopedia_wikipedia": 1,
    }
    assert report["dropped_by_code"] == {frame_module.UNDECLARED_FAMILY: 1}

    #: no outcome vocabulary may appear anywhere in a frame report
    serialized = json.dumps(report).lower()
    for word in ("verdict", "\"gates\"", "silent_drop", "result_digest", "by_state"):
        assert word not in serialized


def test_the_dry_run_never_invents_a_lineage_count(capsys: Any, monkeypatch: Any) -> None:
    """With the expansion unsealed the dry run reports the declaration and says so.

    The failure this guards against is the opposite of a traceback: a frame
    report that silently prints `eligible: 0` reads like a measured empty
    cohort. The unsealed report has no `eligible` key at all, and the exit code
    keeps the state visible to a caller that only checks the status.
    """
    def _unsealed(*_args: Any, **_kwargs: Any) -> Any:
        raise frame_module.FrameNotFrozen("not sealed")

    monkeypatch.setattr(worker, "frame_report", _unsealed)
    assert worker.main(["--dry-run"]) == 3

    report = json.loads(capsys.readouterr().out)
    #: `sealed` is not asserted. The expansion was unsealed when this test was
    #: written and is sealed now, and neither is the property under test: what
    #: must hold either way is that a report which could not build a cohort
    #: omits the count rather than printing zero.
    assert "eligible" not in report
    assert "family_composition" not in report
    assert report["spent_exclusion"]["lineages"] > 1000
    assert report["family_quota"] == dict(frame_module.FAMILY_QUOTA)
