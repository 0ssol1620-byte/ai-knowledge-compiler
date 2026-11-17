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
from benchmark.u06_equivalence.harness import compile_pair, judge

ROOT = Path(__file__).resolve().parents[2]
TENANT = "tenant-foundation-pilot"
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
# judge's source as of 55a9a38 (WO-D12-12); this work order may not change it.
JUDGE_SHA256 = "3f47cdb8e66eccaf47aa66416d9c667c26c6991a988d8065b719b3c5d854875c"
# today's (55a9a38) runner on `_manifest`: results.jsonl, and summary.json with the four
# environment values (git sha, manifest sha, python, host) blanked.
OFF_RESULTS_SHA256 = "d5ba07add23a62b5699d2e32b45ee4006d83720117b64de97225a84db3081764"
OFF_SUMMARY_SHA256 = "78dc960b843b281a6135101348cac44ae312bd8dd2bf6537ed6a9dad93e0ec12"


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
        assert (row["status"] == "not exercised") == (exercised == 0), name
        assert "pass" not in row["status"]
        assert "declared_documents_exercised" not in off[name]
    assert any(row["declared_documents_exercised"] for row in cand.values())
    assert any(row["status"] == "not exercised" for row in cand.values())
    # D12-D12b, per case: declared -> equal_or_hold (refused, so held), undeclared -> hold
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
        declared = bool(row["touched_declared_paths"])
        assert row["expected"] == ("equal_or_hold" if declared else "hold")
        assert set(row["touched_declared_paths"]) <= {"refused:D-MISSING"}
    assert all(
        r["expected"] == "hold"
        for r in _jsonl(out / "faults.off.jsonl")
        if r["fault_class"] == "duplicate_region_text"
    )
    block = summary["by_construction"]
    assert (
        block["faults.candidate.duplicate_region_text.declared_documents_exercised"]["value"] == 0
    )
    unmet = [
        (a, n)
        for a in ("off", "candidate")
        for n, r in summary["faults"][a].items()
        if r["expectation_not_met"]
    ]
    assert code == (1 if unmet else 0)


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


def test_faults_no_pair_supports_refuse_the_run_before_writing(tmp_path: Path) -> None:
    single = _sec("400-IS", [(f"Revenues-{Q1}m-1-USD", _row("Revenues", 1, Q1))])
    with pytest.raises(ValueError, match="applies to none of the base pairs"):
        _run(
            tmp_path,
            "--fact-key-mode",
            "candidate",
            "--faults",
            "16",
            cases=[("c", "s", (single,), (single,))],
        )
    assert not (tmp_path / "out").exists()
