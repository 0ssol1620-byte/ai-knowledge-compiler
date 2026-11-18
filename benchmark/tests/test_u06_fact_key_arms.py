"""WO-D12-13: the U06 harness and runner on both arms (off, candidate) through the real keyed path.

Every manifest here is synthetic (SEC-shaped rows built in this file, no corpus). Every test goes
through `run.main`, `compile_pair` and the real `ProductCoreCompiler`; nothing is faked.
"""

from __future__ import annotations

import ast
import hashlib
import inspect
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import akc_product_core.fact_keys as fact_keys
import pytest
from akc_cir.identity import document_version_id, source_id
from akc_product_core import ProductCoreCompiler
from akc_product_core.contracts import ProductCoreDocument, ProductCoreRegion

from benchmark.u06_equivalence import declarations, harness
from benchmark.u06_equivalence import run as u06_run
from benchmark.u06_equivalence.declarations import DECLARATIONS, SEC_FSDS
from benchmark.u06_equivalence.faults import generate
from benchmark.u06_equivalence.harness import CaseResult, compile_pair, judge

ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-foundation-pilot"
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
# judge's source as of 55a9a38 (WO-D12-12); this work order may not change it.
JUDGE_SHA256 = "3f47cdb8e66eccaf47aa66416d9c667c26c6991a988d8065b719b3c5d854875c"
# today's (55a9a38) runner on `_manifest`: results.jsonl, and summary.json with the four
# environment values (git sha, manifest sha, python, host) blanked. Re-derived once (WO-D10-1A)
# from the Windows pins d5ba07ad…1764 / 78dc960b…ec12 by the one change the writer made, CRLF ->
# LF; b89c25e9…00a4 is what the Linux runner wrote in CI run 44245132548 before the fix.
OFF_RESULTS_SHA256 = "b89c25e90cff9712ce24c494b54ea86535be8dab0d0defc96698c065fa2100a4"
OFF_SUMMARY_SHA256 = "8f54d00abc9628484ba02130190f929666b4f744db16fd1025077ce5cdd9d9ee"


def _row(label: str, value: int, end: str, quarters: int = 1) -> str:
    return (
        f"{label}: {value} USD, period ending {end[:4]}-{end[4:6]} "
        f"(month as rounded by FSDS), {quarters} quarters."
    )


def _doc(
    native: str, connector: str, parts: Sequence[tuple[str | None, str]], *, title: str = ""
) -> ProductCoreDocument:
    src = source_id(tenant_id=TENANT, connector_type=connector, native_id=native)
    body = "\n".join(f"{key}|{text}" for key, text in parts) + title
    digest = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    return ProductCoreDocument(
        native_id=native,
        connector_type=connector,
        source_id=src,
        source_version_id=document_version_id(source=src, content_sha256=digest),
        immutable_object_key=f"{connector}/{digest[7:]}/{native}.json",
        ocr_object_key=f"{connector}/{digest[7:]}/{native}.txt",
        content_sha256=digest,
        title=title or f"{native} (template-rendered from FSDS)",
        source_filename=f"{native}.json",
        page_count=1,
        regions=tuple(
            ProductCoreRegion(
                region_id=key or f"region-{order}",
                page_index0=0,
                page_number1=1,
                order=order,
                text=text,
                native_object_id=key,
                authority="official",
            )
            for order, (key, text) in enumerate(parts)
        ),
    )


def _sec(native: str, parts: Sequence[tuple[str, str]]) -> ProductCoreDocument:
    return _doc(native, "sec-fsds", parts)


Q1, Q2 = "20240331", "20240630"
ROLL_BEFORE = _sec(
    "100-IS",
    [
        (f"Revenues-{Q1}m-1-USD", _row("Revenues", 1000, Q1)),
        (f"NetIncomeLoss-{Q1}m-1-USD", _row("Net income", 100, Q1)),
        (f"CostOfRevenue-{Q1}m-1-USD", _row("Cost of revenue", 600, Q1)),
    ],
)
ROLL_AFTER = _sec(
    "100-IS",
    [
        (f"Revenues-{Q2}m-1-USD", _row("Revenues", 1100, Q2)),
        (f"NetIncomeLoss-{Q2}m-1-USD", _row("Net income", 120, Q2)),
        (f"CostOfRevenue-{Q2}m-1-USD", _row("Cost of revenue", 650, Q2)),
    ],
)
RESTATE_BEFORE = _sec(
    "200-BS",
    [
        (f"Assets-{Q1}m-0-USD", _row("Total assets", 5000, Q1, 0)),
        (f"Liabilities-{Q1}m-0-USD", _row("Total liabilities", 3000, Q1, 0)),
    ],
)
RESTATE_AFTER = _sec(
    "200-BS",
    [
        (f"Assets-{Q1}m-0-USD", _row("Total assets", 5000, Q1, 0)),
        (f"Liabilities-{Q1}m-0-USD", _row("Total liabilities", 3000, Q1, 0) + " Restated."),
    ],
)


def _year(tag: str, end: str, value: int) -> tuple[str, str]:
    return f"{tag}-{end}m-4-USD", _row(tag, value, end, 4)


Y = ("20211231", "20221231", "20231231", "20241231")
# a 10-K drops its two oldest columns and adds a new one: today the new row is offered to both
# gone rows and is held; under the key it is NEW and both gone rows are REMOVED.
TENK_BEFORE = _sec(
    "300-IS", [_year("Revenues", y, v) for y, v in zip(Y[:3], (900, 1000, 1100), strict=True)]
)
TENK_AFTER = _sec(
    "300-IS", [_year("Revenues", y, v) for y, v in zip(Y[2:], (1100, 1200), strict=True)]
)
# a declared document with a region that carries no key: refused (D-MISSING), today's path.
UNKEYED_AFTER = _doc(
    "200-BS",
    "sec-fsds",
    [*((r.native_object_id, r.text) for r in RESTATE_AFTER.regions), (None, "Unkeyed note.")],
)
PLAIN_A = _doc("filing-a", "foundation-r2", [(None, "Revenue is 100 million won.")])
PLAIN_B = _doc("policy-b", "foundation-r2", [(None, "The board approved the policy.")])

CASES: list[tuple[str, str, tuple[ProductCoreDocument, ...], tuple[ProductCoreDocument, ...]]] = [
    ("c-roll", "sec_successor", (ROLL_BEFORE,), (ROLL_AFTER,)),
    ("c-restate", "sec_amendment", (RESTATE_BEFORE,), (RESTATE_AFTER,)),
    ("c-10k", "sec_successor", (TENK_BEFORE,), (TENK_AFTER,)),
    ("c-unkeyed", "sec_amendment", (RESTATE_BEFORE,), (UNKEYED_AFTER,)),
    ("c-plain", "undeclared", (PLAIN_A,), (PLAIN_A, PLAIN_B)),
    ("c-mixed", "sec_successor", (ROLL_BEFORE, PLAIN_A), (ROLL_AFTER, PLAIN_A, PLAIN_B)),
]


def _manifest(tmp_path: Path, cases: Sequence[tuple[str, str, Any, Any]] = CASES) -> Path:
    def ref(name: str, docs: Sequence[ProductCoreDocument]) -> dict[str, str]:
        data = json.dumps([json.loads(d.model_dump_json(by_alias=True)) for d in docs]).encode()
        (tmp_path / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    manifest = {
        "requested_at": NOW.isoformat(),
        "cases": [
            {
                "case_id": cid,
                "stratum": stratum,
                "before": ref(f"{cid}-b.json", before),
                "after": ref(f"{cid}-a.json", after),
            }
            for cid, stratum, before, after in cases
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def _blank_environment(summary: bytes) -> bytes:
    return re.sub(rb'("(?:git_sha|manifest_sha256|python|host)": )"[^"]*"', rb'\1"-"', summary)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _run(tmp_path: Path, *flags: str, cases: Sequence[Any] = CASES) -> tuple[int, Path]:
    out = tmp_path / "out"
    code = u06_run.main(["--manifest", str(_manifest(tmp_path, cases)), "--out", str(out), *flags])
    return code, out


# --------------------------------------------------------------------------- unchanged surfaces


def test_judge_is_byte_identical_to_wo_d12_12() -> None:
    source = inspect.getsource(harness)
    node = next(
        n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == "judge"
    )
    segment = ast.get_source_segment(source, node)
    assert segment is not None and _sha(segment.encode("utf-8")) == JUDGE_SHA256


@pytest.mark.parametrize("flags", [(), ("--fact-key-mode", "off")])
def test_without_the_new_flags_the_run_is_todays_byte_for_byte(
    tmp_path: Path, flags: tuple[str, ...]
) -> None:
    code, out = _run(tmp_path, *flags)
    assert code == 0
    assert sorted(p.name for p in out.iterdir()) == ["results.jsonl", "summary.json"]
    assert _sha((out / "results.jsonl").read_bytes()) == OFF_RESULTS_SHA256
    assert _sha(_blank_environment((out / "summary.json").read_bytes())) == OFF_SUMMARY_SHA256


@pytest.mark.parametrize(
    "flags", [(), ("--fact-key-mode", "candidate", "--faults", "8", "--fault-seed", "1")]
)
def test_every_file_the_runner_writes_has_the_same_bytes_on_every_platform(
    tmp_path: Path, flags: tuple[str, ...]
) -> None:
    # WO-D10-1A: a text-mode write turned every "\n" into "\r\n" on Windows, so the same run
    # pinned one digest there and another on the Linux runner. Every artifact is LF only.
    _, out = _run(tmp_path, *flags)
    written = sorted(out.iterdir())
    assert len(written) == (2 if not flags else 5)
    for path in written:
        data = path.read_bytes()
        assert b"\n" in data and b"\r" not in data, path.name


def test_compile_pair_passes_mode_and_declarations_through() -> None:
    off = compile_pair((ROLL_BEFORE,), (ROLL_AFTER,), requested_at=NOW)
    on = compile_pair(
        (ROLL_BEFORE,),
        (ROLL_AFTER,),
        requested_at=NOW,
        fact_key_mode="candidate",
        fact_key_declarations=DECLARATIONS,
    )
    assert {r.receipt.matching_policy for r in off} == {"legacy"}
    assert {r.receipt.matching_policy for r in on} == {"fact_key_v1"}
    kinds = {str(c["kind"]) for c in on[0].candidate.diff["changes"]}  # type: ignore[attr-defined]
    assert "modified_claim" not in kinds and judge(*on).verdict == "EQUAL"
    # the compiler's own refusals reach the caller unchanged; the harness adds no default
    with pytest.raises(ValueError, match="needs at least one declaration"):
        compile_pair((ROLL_BEFORE,), (ROLL_AFTER,), requested_at=NOW, fact_key_mode="candidate")
    with pytest.raises(ValueError, match="must be off or candidate"):
        compile_pair((ROLL_BEFORE,), (ROLL_AFTER,), requested_at=NOW, fact_key_mode="shadow")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- declaration


def test_the_declaration_imports_the_pinned_pattern_and_cites_the_adapter_line() -> None:
    assert SEC_FSDS.key_pattern is fact_keys.SEC_FSDS_KEY_PATTERN
    assert SEC_FSDS.collision_suffix is fact_keys.SEC_FSDS_COLLISION_SUFFIX
    assert DECLARATIONS == (SEC_FSDS,) and SEC_FSDS.connector_type == "sec-fsds"
    source = inspect.getsource(declarations)
    assert "\\d" not in source and "[A-Za-z" not in source  # not restated
    assert SEC_FSDS.evidence_sha256 == declarations.STEP0_KEYED_SHA256
    assert "assigned_by=adapter_from_source_fields" in SEC_FSDS.evidence_ref
    assert f"sec_pairs.py:129-131 @ {declarations.SEC_PAIRS_COMMIT}" in SEC_FSDS.evidence_ref
    # the cited lines still build the key and its collision suffix; if they move, re-cite
    lines = (ROOT / "benchmark/local_public/sec_pairs.py").read_text(encoding="utf-8").splitlines()
    assert "f\"{r['tag']}-{ddate}m-{q}-{r['uom']}\"" in lines[128]
    assert "f\"{rid}-l{p['line']}\"" in lines[130]


# --------------------------------------------------------------------------- both arms


def test_candidate_runs_both_arms_and_reports_transitions_and_by_construction(
    tmp_path: Path,
) -> None:
    code, out = _run(tmp_path, "--fact-key-mode", "candidate")
    assert code == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["results.candidate.jsonl", "results.off.jsonl", "summary.json"]
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    off, cand = summary["arms"]["off"], summary["arms"]["candidate"]

    # the off arm is today's run, case by case (the default run's lines plus counts)
    (tmp_path / "today").mkdir()
    today = _run(tmp_path / "today")[1]
    expected_rows = _jsonl(today / "results.jsonl")
    off_rows = _jsonl(out / "results.off.jsonl")
    assert [{k: v for k, v in r.items() if k != "counts"} for r in off_rows] == expected_rows
    today_summary = json.loads((today / "summary.json").read_text(encoding="utf-8"))
    assert {k: off[k] for k in u06_run.summarize([])} == {
        k: today_summary[k] for k in u06_run.summarize([])
    }

    # per arm: proven equal / declined, and the counts the arms differ on
    assert (off["equal"], off["hold"], cand["equal"], cand["hold"]) == (5, 1, 6, 0)
    assert off["reading"] == "5 of 6 pairs proven equal, 1 declined"
    assert cand["reading"] == "6 of 6 pairs proven equal, 0 declined"
    assert off["counts"]["cross_key_matched"] >= 6  # roll (3) + mixed (3); 10-K row held
    assert off["counts"]["modified_claim_cross_key"] >= 6
    assert cand["counts"]["cross_key_matched"] == 0
    assert cand["counts"]["declared_documents_keyed"] == 4  # roll, restate, 10-K, mixed
    assert cand["counts"]["declared_documents_refused:D-MISSING"] == 1  # unkeyed
    # the five path counters are written, zeros included
    paths = {k: v for k, v in cand["counts"].items() if k.startswith("declared_documents_")}
    assert paths == {
        "declared_documents_keyed": 4,
        "declared_documents_unchanged": 0,
        "declared_documents_no_previous": 0,
        "declared_documents_refused:D-MISSING": 1,
        "declared_documents_refused:D-DUP": 0,
    }
    # off has no declarations, so it carries no keyed-document figures at all (not zeros)
    assert not [k for k in off["counts"] if "keyed" in k or k.startswith("declared_")]
    assert summary["transitions"]["all"] == {"EQUAL->EQUAL": 5, "HOLD->EQUAL": 1}
    assert summary["transitions"]["per_stratum"]["sec_successor"]["HOLD->EQUAL"] == 1
    rows = {r["case_id"]: r for r in _jsonl(out / "results.candidate.jsonl")}
    assert rows["c-10k"]["verdict"] == "EQUAL" and rows["c-10k"]["counts"]["units_new"] == 1
    assert any(
        r.startswith("IDENTITY_FACT_KEY_REFUSED:") for r in rows["c-unkeyed"]["review_reasons"]
    )

    # what is true by construction is named as such, and held
    assert summary["by_construction_held"] is True
    block = summary["by_construction"]
    assert block["candidate.cross_key_matched_on_keyed_documents"]["value"] == 0
    assert all(item["value"] == item["expected"] == 0 for item in block.values())
    assert all(item["status"] == "held" for item in block.values())
    assert block["candidate.cross_key_matched_on_keyed_documents"]["denominator"] == {
        "declared_documents_keyed": 4
    }
    assert summary["declarations"][0]["assigned_by"] == "adapter_from_source_fields"
    for written in out.iterdir():
        text = written.read_text(encoding="utf-8")
        assert "accuracy" not in text.lower() and "pass" not in text.lower()
        assert "period ending" not in text  # no document text


def _whole_document(incoming: Any, previous: Any) -> tuple[list[Any], list[int | None]]:
    """A broken keyed path for the negative control: keyed units offered to every previous unit."""
    from akc_cir.identity import assign_one_to_one

    decisions = assign_one_to_one(list(incoming), list(previous))
    index = {unit.logical_id: j for j, unit in enumerate(previous)}
    return decisions, [index.get(d.logical_id or "") for d in decisions]


def test_a_keyed_path_that_pairs_across_keys_fails_the_run_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import akc_product_core.compiler as compiler

    monkeypatch.setattr(compiler, "keyed_decisions", _whole_document)
    code, out = _run(tmp_path, "--fact-key-mode", "candidate", cases=CASES[:1])
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert code == 1 and summary["by_construction_held"] is False
    block = summary["by_construction"]
    assert block["candidate.cross_key_matched_on_keyed_documents"]["value"] == 3
    assert block["candidate.modified_claim_cross_key_on_keyed_documents"]["value"] == 3


class _CandidateRaises(ProductCoreCompiler):
    def __init__(self, **kwargs: Any) -> None:
        if kwargs.get("fact_key_mode") == "candidate":
            raise ValueError("Revenues: 1000 USD")  # document-like text must not be written
        super().__init__(**kwargs)


def test_a_figure_no_case_measured_is_none_and_does_not_hold(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "ProductCoreCompiler", _CandidateRaises)
    code, out = _run(tmp_path, "--fact-key-mode", "candidate", cases=CASES[:2])
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    cand = summary["arms"]["candidate"]
    assert code == 1 and cand["cases_without_counts"] == 2 and cand["counts"] == {}
    assert cand["hold_by_reason"] == {"COMPILE_ERROR:ValueError": 2}
    block = summary["by_construction"]
    assert block["candidate.cross_key_matched_on_keyed_documents"]["value"] is None
    assert block["candidate.cross_key_matched_on_keyed_documents"]["status"] == "not exercised"
    assert summary["by_construction_held"] is False
    assert summary["transitions"]["all"] == {"EQUAL->HOLD": 2}
    for written in out.iterdir():
        assert "1000 USD" not in written.read_text(encoding="utf-8")


def test_a_refusal_on_a_document_the_rule_calls_ineligible_stops_the_count() -> None:
    seen: list[Any] = []

    def keep(previous: Any) -> Any:
        seen.append(previous)
        return previous

    incremental, _ = compile_pair(
        (RESTATE_BEFORE,),
        (UNKEYED_AFTER,),
        requested_at=NOW,
        tamper_previous=keep,
        fact_key_mode="candidate",
        fact_key_declarations=DECLARATIONS,
    )
    assert u06_run._paths(seen[0], incremental, (UNKEYED_AFTER,), DECLARATIONS, TENANT) == {
        UNKEYED_AFTER.source_id: "refused:D-MISSING"
    }
    unchanged = UNKEYED_AFTER.model_copy(update={"content_sha256": RESTATE_BEFORE.content_sha256})
    with pytest.raises(RuntimeError, match="eligibility rule calls unchanged"):
        u06_run._paths(seen[0], incremental, (unchanged,), DECLARATIONS, TENANT)


# --------------------------------------------------------------------------- faults on both arms


def test_faults_run_on_both_arms_and_a_class_without_a_keyed_document_is_not_exercised(
    tmp_path: Path,
) -> None:
    # one undeclared pair with non-ASCII text, so the NFC/NFD class has something to change
    cafe = _doc("menu-c", "foundation-r2", [(None, "Café policy is active now.")])
    cases = [*CASES, ("c-cafe", "undeclared", (PLAIN_A,), (PLAIN_A, cafe))]
    flags = ("--fact-key-mode", "candidate", "--faults", "48", "--fault-seed", "3")
    code, out = _run(tmp_path, *flags, cases=cases)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert (summary["fault_cases"], summary["fault_seed"]) == (48, 3)
    off, cand = summary["faults"]["off"], summary["faults"]["candidate"]
    assert len(off) == len(cand) == 16
    for name, row in cand.items():
        assert row["cases"] == 3 == off[name]["cases"]
        exercised = row["declared_documents_exercised"]
        assert row["status"].startswith("not exercised") == (exercised == 0), name
        assert "pass" not in row["status"]
        assert "declared_documents_exercised" not in off[name]
    assert any(row["declared_documents_exercised"] for row in cand.values())
    assert any(row["status"] == "not exercised" for row in cand.values())
    # D12-D13r: one expectation for the duplicate class, declared or not
    dup = [
        r
        for r in _jsonl(out / "faults.candidate.jsonl")
        if r["fault_class"] == "duplicate_region_text"
    ]
    assert {bool(r["touched_declared_paths"]) for r in dup} == {True, False}
    # one fault changes one document: an edited document's two versions are one source, never two
    for row in _jsonl(out / "faults.candidate.jsonl"):
        if row["fault_class"] != "revert_to_before":
            assert sum(row["touched_declared_paths"].values()) <= 1, row["fault_class"]
    for row in dup:
        assert row["expected"] == "equal_or_hold"
        assert set(row["touched_declared_paths"]) <= {"refused:D-MISSING"}
    for arm in ("off", "candidate"):
        for row in _jsonl(out / f"faults.{arm}.jsonl"):
            assert row["expected"] == "equal_or_hold"
            assert row["outcome"] in OUTCOMES
            # the two lineage columns are reported for every class
            assert row["abstention_lost"] is None or row["abstention_lost"] >= 0
    block = summary["by_construction"]
    assert (
        block["faults.candidate.duplicate_region_text.declared_documents_exercised"]["value"] == 0
    )
    unmet = [
        (a, n)
        for a in ("off", "candidate")
        for n, r in summary["faults"][a].items()
        if r["expectation_not_met"] or r["joined"]
    ]
    assert code == (1 if unmet else 0)
    lines = {arm: _jsonl(out / f"faults.{arm}.jsonl") for arm in ("off", "candidate")}
    _assert_held_cases_are_not_exercise(summary, lines)


OUTCOMES = {"expectation_met", "expectation_not_met", "joined", "parent_already_held"}


def _faults_run(
    tmp_path: Path, cases: Sequence[Any], n: int = 16
) -> tuple[int, dict[str, Any], dict[str, list[dict[str, Any]]]]:
    flags = ("--fact-key-mode", "candidate", "--faults", str(n), "--fault-seed", "1")
    code, out = _run(tmp_path, *flags, cases=cases)
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    lines = {arm: _jsonl(out / f"faults.{arm}.jsonl") for arm in ("off", "candidate")}
    return code, summary, lines


def _dup(lines: list[dict[str, Any]]) -> dict[str, Any]:
    (row,) = [r for r in lines if r["fault_class"] == "duplicate_region_text"]
    return row


# WO-D12-16 Step 0's shape: on c-10k the new row ties between the two gone rows and is held; the
# appended duplicate takes one of them, the tie guard no longer fires, and both join across keys.
TENK_UNDECLARED = tuple(
    (_doc("300-IS", "foundation-r2", [(r.native_object_id, r.text) for r in doc.regions]),)
    for doc in (TENK_BEFORE, TENK_AFTER)
)


def test_the_c10k_shape_is_joined_in_both_arms_and_the_run_exits_1(tmp_path: Path) -> None:
    code, summary, lines = _faults_run(tmp_path, [("c-10k", "sec_successor", *CASES[2][2:])])
    assert code == 1
    off, cand = _dup(lines["off"]), _dup(lines["candidate"])
    # off: the parent abstained (HOLD); the case is EQUAL and the abstention is gone
    assert summary["arms"]["off"]["hold"] == 1 and off["verdict"] == "EQUAL"
    assert off["outcome"] == "joined" and off["abstention_lost"] == 1
    assert off["joins_added"] == {"cross_key_matched": 2, "modified_claim_cross_key": 2}
    # candidate: the parent is keyed (EQUAL, nothing held, so no abstention to lose); the '-dup'
    # key refuses the document (D-MISSING, F-D12-8) and the legacy joins come back
    assert summary["arms"]["candidate"]["equal"] == 1 and cand["verdict"] == "EQUAL"
    assert cand["touched_declared_paths"] == {"refused:D-MISSING": 1}
    assert cand["outcome"] == "joined" and cand["abstention_lost"] == 0
    assert cand["joins_added"] == {"cross_key_matched": 2, "modified_claim_cross_key": 2}
    for arm in ("off", "candidate"):
        row = summary["faults"][arm]["duplicate_region_text"]
        assert (row["joined"], row["expectation_met"]) == (1, 0)
        assert "joined in 1 of 1 cases" in row["status"]
    # a joined case is evaluated, so its declared document counts as touched (not as keyed)
    row = summary["faults"]["candidate"]["duplicate_region_text"]
    assert (row["declared_documents_touched"], row["declared_documents_exercised"]) == (1, 0)
    assert row["touched_declared_paths"] == {"refused:D-MISSING": 1}
    _assert_held_cases_are_not_exercise(summary, lines)
    # the joined case is the only reason for exit 1: nothing else failed
    assert summary["by_construction_held"] is True
    assert not any(
        r["diverged"] or r["phantom"] or r["expectation_not_met"]
        for arm in ("off", "candidate")
        for r in summary["faults"][arm].values()
    )
    # a class that applies to no pair of this base is named, with no case
    na = [n for n, r in summary["faults"]["off"].items() if r["status"] == "not_applicable"]
    assert "delete_source" in na and summary["faults"]["candidate"]["delete_source"]["cases"] == 0
    assert summary["fault_cases"] == 16 - len(na) and summary["fault_cases_requested"] == 16


def test_the_c10k_shape_without_a_declaration_loses_an_abstention_in_both_arms(
    tmp_path: Path,
) -> None:
    _, summary, lines = _faults_run(tmp_path, [("c-10k-u", "undeclared", *TENK_UNDECLARED)])
    for arm in ("off", "candidate"):
        assert summary["arms"][arm]["hold_by_reason"] == {"IDENTITY_UNRESOLVED": 1}
        row = _dup(lines[arm])
        assert row["outcome"] == "joined" and row["abstention_lost"] == 1, arm


def test_a_duplicate_that_loses_no_abstention_and_adds_no_join_is_met(tmp_path: Path) -> None:
    code, summary, lines = _faults_run(tmp_path, [CASES[0]])  # c-roll
    off = _dup(lines["off"])
    assert off["verdict"] == "EQUAL" and off["outcome"] == "expectation_met"
    assert off["abstention_lost"] == 0
    assert off["joins_added"] == {"cross_key_matched": 0, "modified_claim_cross_key": 0}
    # the same case on the candidate arm is refused (D-MISSING): its three rows join across keys
    cand = _dup(lines["candidate"])
    assert cand["touched_declared_paths"] == {"refused:D-MISSING": 1}
    assert cand["outcome"] == "joined"
    assert cand["joins_added"] == {"cross_key_matched": 3, "modified_claim_cross_key": 3}
    assert summary["faults"]["candidate"]["duplicate_region_text"]["expectation_met"] == 0
    assert code == 1


def test_a_case_held_for_its_parents_reason_is_parent_already_held_not_met(
    tmp_path: Path,
) -> None:
    # c-10k on the off arm is HOLD (IDENTITY_UNRESOLVED); a rename changes nothing the matcher sees
    _, summary, lines = _faults_run(tmp_path, [("c-10k", "sec_successor", *CASES[2][2:])])
    row = summary["faults"]["off"]["source_rename_same_content"]
    assert (row["cases"], row["parent_already_held"], row["expectation_met"]) == (1, 1, 0)
    assert row["status"] == "not exercised; 1 parent_already_held"  # both things (ruling C)
    for line in lines["off"]:
        if line["outcome"] == "parent_already_held":
            assert line["verdict"] == "HOLD"
            assert set(line["hold_reasons"]) <= {"IDENTITY_UNRESOLVED"}
    _assert_held_cases_are_not_exercise(summary, lines)


def _assert_held_cases_are_not_exercise(
    summary: dict[str, Any], lines: dict[str, list[dict[str, Any]]]
) -> None:
    """Every figure that is a denominator of "met" or of a by-construction entry is the sum over
    the evaluated cases (`joined` included) of the case lines; a `parent_already_held` case is
    counted only in its own columns. Read against the run's own per-case output."""
    held = "parent_already_held"
    for arm in ("off", "candidate"):
        for name, row in summary["faults"][arm].items():
            mine = [line for line in lines[arm] if line["fault_class"] == name]
            evaluated = [line for line in mine if line["outcome"] != held]
            n_held = len(mine) - len(evaluated)
            assert (row["cases"], row[held]) == (len(mine), n_held), (arm, name)
            assert row["expectation_met"] + row["expectation_not_met"] + row["joined"] == len(
                evaluated
            )
            if row["status"] == "not_applicable":
                assert not mine
                continue
            exercised = sum(line["touched_declared_paths"].get("keyed", 0) for line in evaluated)
            joined = f"; joined in {row['joined']} of {len(mine)} cases" if row["joined"] else ""
            assert row["status"].endswith(joined), (arm, name)
            if not evaluated or (arm == "candidate" and not exercised):
                tail = f"; {n_held} {held}" if n_held else ""
                assert row["status"] == "not exercised" + tail + joined, (arm, name, row["status"])
            else:
                assert row["status"].startswith(
                    f"expectation met in {row['expectation_met']} of {len(evaluated)} cases"
                )
            if arm == "off":
                assert "declared_documents_exercised" not in row
                continue
            paths: Counter[str] = Counter()
            for line in evaluated:
                paths.update(line["touched_declared_paths"])
            assert row["touched_declared_paths"] == dict(sorted(paths.items())), name
            assert row["declared_documents_touched"] == sum(paths.values()), name
            assert row["declared_documents_exercised"] == exercised, name
            assert row[f"{held}_declared_documents_touched"] == sum(
                sum(line["touched_declared_paths"].values())
                for line in mine
                if line["outcome"] == held
            ), name
    block = summary["by_construction"]
    keyed = summary["arms"]["candidate"]["counts"].get("declared_documents_keyed", 0) + sum(
        line["declared_documents_keyed"] or 0
        for line in lines["candidate"]
        if line["outcome"] != held
    )
    denominator = block["candidate.fact_key_disagreements"]["denominator"]
    assert denominator == {"declared_documents_keyed": keyed}
    dup = summary["faults"]["candidate"].get("duplicate_region_text")
    if dup is not None:
        figure = block["faults.candidate.duplicate_region_text.declared_documents_exercised"]
        assert figure["denominator"] == {
            "declared_documents_touched": dup["declared_documents_touched"]
        }


# The reviewer's probe (r20): a pair HOLD on the off and candidate arm for an undeclared 10-K's
# tie, with a keyed document beside it, and a plain pair. Faults that touch the keyed document
# of the held pair are parent_already_held; before WO-D12-16r's closing round they made six
# classes "exercised" ("met in 2 of 2 cases, 1 parent_already_held") over no keyed evaluated case.
HELD_BESIDE_KEYED = [
    ("p-held", "mixed", (TENK_UNDECLARED[0][0], ROLL_BEFORE), (TENK_UNDECLARED[1][0], ROLL_AFTER)),
    ("p-plain", "undeclared", (PLAIN_A,), (PLAIN_A, PLAIN_B)),
]


@pytest.mark.parametrize("n", [32, 64])
def test_a_class_exercised_only_by_parent_held_cases_is_not_exercised(
    tmp_path: Path, n: int
) -> None:
    _, summary, lines = _faults_run(tmp_path, HELD_BESIDE_KEYED, n=n)
    _assert_held_cases_are_not_exercise(summary, lines)
    cand = summary["faults"]["candidate"]
    only_held = [
        name
        for name, row in cand.items()
        if row["parent_already_held_declared_documents_touched"]
        and not row["declared_documents_exercised"]
        and any(
            line["touched_declared_paths"].get("keyed")
            for line in lines["candidate"]
            if line["fault_class"] == name and line["outcome"] == "parent_already_held"
        )
    ]
    assert only_held  # the probe's shape is on this base
    for name in only_held:
        assert cand[name]["status"].startswith("not exercised; "), name
        assert "met in" not in cand[name]["status"], name


def test_without_a_keyed_document_every_by_construction_figure_is_not_exercised(
    tmp_path: Path,
) -> None:
    code, out = _run(tmp_path, "--fact-key-mode", "candidate", cases=[CASES[4]])  # c-plain
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert code == 1 and summary["by_construction_held"] is False
    for item in summary["by_construction"].values():
        assert item["status"] == "not exercised" and item["value"] in (0, None)
    counts = summary["arms"]["candidate"]["counts"]
    assert counts["declared_documents_keyed"] == 0  # written as a zero, not missing


@pytest.mark.parametrize(
    ("flags", "message"),
    [
        (("--faults", "8"), "needs --fact-key-mode candidate"),
        (("--fact-key-mode", "candidate", "--faults", "-1"), "must be >= 0"),
        (("--fact-key-mode", "shadow"), "invalid choice"),
    ],
)
def test_bad_flags_are_refused_before_anything_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], flags: tuple[str, ...], message: str
) -> None:
    with pytest.raises(SystemExit) as raised:
        _run(tmp_path, *flags)
    assert raised.value.code == 2 and message in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def _measured(states: dict[tuple[str, str], str], cross: int = 0) -> Any:
    counts = {"cross_key_matched": cross, "modified_claim_cross_key": cross}
    return (CASE_EQUAL, counts, {}, states)


def test_lineage_counts_only_anchors_the_fault_did_not_touch() -> None:
    """The real `_lineage` on real documents: the parent held the anchor, the case matched it."""
    assert PLAIN_A.source_id is not None
    key = (PLAIN_A.source_id, "region-0")
    edited = _doc("filing-a", "foundation-r2", [(None, "Revenue is 101 million won.")])
    parent, case = _measured({key: "unresolved"}), _measured({key: "matched"}, cross=2)
    same = u06_run._lineage(parent, case, (PLAIN_A,), (PLAIN_A,), TENANT)
    assert same == {
        "abstention_lost": 1,
        "joins_added": {"cross_key_matched": 2, "modified_claim_cross_key": 2},
    }
    touched = u06_run._lineage(parent, case, (PLAIN_A,), (edited,), TENANT)
    assert touched is not None and touched["abstention_lost"] == 0  # the fault edited it
    fewer = u06_run._lineage(
        _measured({key: "matched"}, cross=3), case, (PLAIN_A,), (PLAIN_A,), TENANT
    )
    assert fewer is not None and fewer["joins_added"]["cross_key_matched"] == 0  # never negative
    raised = (CASE_HOLD, None, None, None)
    assert u06_run._lineage(raised, case, (PLAIN_A,), (PLAIN_A,), TENANT) is None
    with pytest.raises(RuntimeError, match="no incremental unit"):
        u06_run._lineage(_measured({}), case, (PLAIN_A,), (PLAIN_A,), TENANT)


CASE_HOLD = CaseResult(verdict="HOLD", hold_reasons=("IDENTITY_UNRESOLVED",))
CASE_EQUAL = CaseResult(verdict="EQUAL")
CASE_NEW_HOLD = CaseResult(verdict="HOLD", hold_reasons=("EQUIVALENCE_FAILED",))
CASE_DIVERGED = CaseResult(verdict="DIVERGED")
CLEAN = {"abstention_lost": 0, "joins_added": {"cross_key_matched": 0, "x": 0}}
LOST = {"abstention_lost": 1, "joins_added": {"cross_key_matched": 0, "x": 0}}
JOIN = {"abstention_lost": 0, "joins_added": {"cross_key_matched": 0, "x": 1}}


@pytest.mark.parametrize(
    ("fault_class", "result", "parent", "lineage", "outcome"),
    [
        ("duplicate_region_text", CASE_EQUAL, CASE_EQUAL, CLEAN, "expectation_met"),
        ("duplicate_region_text", CASE_EQUAL, CASE_HOLD, LOST, "joined"),  # abstention alone
        ("duplicate_region_text", CASE_EQUAL, CASE_EQUAL, JOIN, "joined"),  # join alone
        ("duplicate_region_text", CASE_HOLD, CASE_HOLD, LOST, "joined"),  # never hidden by a hold
        ("duplicate_region_text", CASE_HOLD, CASE_HOLD, None, "parent_already_held"),
        ("duplicate_region_text", CASE_EQUAL, CASE_EQUAL, None, "expectation_not_met"),
        ("duplicate_region_text", CASE_DIVERGED, CASE_EQUAL, JOIN, "expectation_not_met"),
        ("duplicate_region_text", CASE_NEW_HOLD, CASE_HOLD, CLEAN, "expectation_met"),
        ("whitespace_only", CASE_EQUAL, CASE_HOLD, LOST, "expectation_met"),  # columns only
        ("whitespace_only", CASE_HOLD, CASE_HOLD, None, "parent_already_held"),
        ("whitespace_only", CASE_DIVERGED, CASE_EQUAL, CLEAN, "expectation_not_met"),
    ],
)
def test_the_outcome_of_a_fault_case(
    fault_class: str, result: Any, parent: Any, lineage: Any, outcome: str
) -> None:
    case = next(
        c
        for c in generate([((PLAIN_A,), (PLAIN_A, PLAIN_B))], n=16, seed=1)
        if c.fault_class == fault_class
    )
    assert u06_run._outcome(case, result, parent, lineage) == outcome


def test_a_class_no_pair_supports_is_not_applicable_and_the_run_goes_on(tmp_path: Path) -> None:
    single = _sec("400-IS", [(f"Revenues-{Q1}m-1-USD", _row("Revenues", 1, Q1))])
    flags = ("--fact-key-mode", "candidate", "--faults", "16")
    code, out = _run(tmp_path, *flags, cases=[("c", "s", (single,), (single,))])
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    for arm in ("off", "candidate"):
        row = summary["faults"][arm]["delete_source"]
        assert (row["cases"], row["expectation_met"], row["status"]) == (0, 0, "not_applicable")
    assert len(summary["faults"]["off"]) == 16
    na = sum(r["status"] == "not_applicable" for r in summary["faults"]["off"].values())
    assert summary["fault_cases"] == 16 - na  # not redistributed to other classes
    assert code == 1  # the unchanged pair keys nothing: by_construction is not exercised


def _bad_base(tmp_path: Path, how: str) -> Path:
    path = _manifest(tmp_path, CASES[:1])
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if how == "not json":
        path.write_text("{not json", encoding="utf-8")
        return path
    if how == "nested too deep":  # json raises RecursionError, not ValueError
        deep = "[" * 100_000 + "]" * 100_000
        path.write_text(f'{{"requested_at": "{NOW.isoformat()}", "cases": {deep}}}', "utf-8")
        return path
    if how == "document nested too deep":
        data = ("[" * 100_000 + "]" * 100_000).encode()
        (tmp_path / "deep.json").write_bytes(data)
        manifest["cases"][0]["after"] = {"path": "deep.json", "sha256": _sha(data)}
    if how == "tenant not a string":
        manifest["tenant_id"] = 5
    if how == "no requested_at":
        del manifest["requested_at"]
    elif how == "naive requested_at":
        manifest["requested_at"] = "2026-08-29T12:00:00"
    elif how == "no stratum":
        del manifest["cases"][0]["stratum"]
    elif how == "no cases":
        manifest["cases"] = []
    elif how == "missing file":
        manifest["cases"][0]["after"]["path"] = "absent.json"
    elif how == "invalid document":
        data = json.dumps([{"nativeId": "x", "title": "Revenues: 1000 USD"}]).encode()
        (tmp_path / "bad.json").write_bytes(data)
        manifest["cases"][0]["after"] = {"path": "bad.json", "sha256": _sha(data)}
    elif how == "no regions anywhere":
        (tmp_path / "empty.json").write_bytes(b"[]")
        empty = {"path": "empty.json", "sha256": _sha(b"[]")}
        manifest["cases"][0]["before"] = manifest["cases"][0]["after"] = empty
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "how",
    [
        "not json",
        "no requested_at",
        "naive requested_at",
        "no stratum",
        "no cases",
        "missing file",
        "invalid document",
        "no regions anywhere",
        "nested too deep",
        "document nested too deep",
        "tenant not a string",
    ],
)
@pytest.mark.parametrize("mode", ["off", "candidate"])
def test_an_unusable_base_exits_2_with_nothing_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], how: str, mode: str
) -> None:
    manifest = _bad_base(tmp_path, how)
    flags = ["--fact-key-mode", mode] + (["--faults", "16"] if mode == "candidate" else [])
    out = tmp_path / "out"
    assert u06_run.main(["--manifest", str(manifest), "--out", str(out), *flags]) == 2
    err = capsys.readouterr().err
    assert err.startswith("REFUSED: unusable base (") and "1000 USD" not in err
    assert not out.exists()


# Every field the loader reads, and values of every wrong type, including what the JSON parser
# turns into a RecursionError (nesting), a non-finite float or an int no string field takes.
FIELDS: list[tuple[str | int, ...]] = [
    (),
    ("requested_at",),
    ("tenant_id",),
    ("workspace_id",),
    ("collection_id",),
    ("cases",),
    ("cases", 0),
    ("cases", 0, "case_id"),
    ("cases", 0, "stratum"),
    ("cases", 0, "before"),
    ("cases", 0, "after", "path"),
    ("cases", 0, "after", "sha256"),
]
DEEP = "@@deep@@"
HOSTILE: list[Any] = [None, 0, 10**400, 1.5, float("nan"), float("inf"), True, [], {}, [[]], DEEP]


@pytest.mark.parametrize("field", FIELDS, ids=lambda f: "/".join(map(str, f)) or "root")
@pytest.mark.parametrize("mode", ["off", "candidate"])
def test_any_field_of_the_wrong_type_is_an_unusable_base(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], field: tuple[str | int, ...], mode: str
) -> None:
    """Property over the loader: whatever wrong-typed value replaces whichever field, the run
    exits 2 with nothing written and no document text echoed; it never raises and never turns a
    bad base into a measured HOLD."""
    path = _manifest(tmp_path, CASES[:1])
    original = json.loads(path.read_text(encoding="utf-8"))
    flags = ["--fact-key-mode", mode] + (["--faults", "16"] if mode == "candidate" else [])
    for k, value in enumerate(HOSTILE):
        manifest = json.loads(json.dumps(original))
        if field:
            *parents, last = field
            node: Any = manifest
            for step in parents:
                node = node[step]
            node[last] = value
        else:
            manifest = value
        text = json.dumps(manifest).replace(f'"{DEEP}"', "[" * 100_000 + "]" * 100_000)
        path.write_text(text, encoding="utf-8")
        out = tmp_path / f"out-{k}"
        code = u06_run.main(["--manifest", str(path), "--out", str(out), *flags])
        assert code == 2, (field, value)
        assert capsys.readouterr().err.startswith("REFUSED: "), (field, value)
        assert not out.exists(), (field, value)
