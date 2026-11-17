"""WO-D12-5 tests. Base pairs here are synthetic test fixtures, not corpus data."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from akc_cir.identity import document_version_id, source_id
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import ProductCoreDocument, ProductCoreRoute

from benchmark.u06_equivalence import run
from benchmark.u06_equivalence.faults import (
    FAULT_CLASSES,
    LINEAGE_CLASS,
    generate,
    main,
    manifest,
    not_applicable,
)

SHA = "a" * 64
TENANT = "tenant-x"


def _doc(native: str, texts: list[str]) -> ProductCoreDocument:
    sid = source_id(tenant_id=TENANT, connector_type="upload", native_id=native)
    sha = "sha256:" + SHA
    return ProductCoreDocument.model_validate(
        {
            "nativeId": native,
            "connectorType": "upload",
            "sourceId": sid,
            "sourceVersionId": document_version_id(source=sid, content_sha256=sha),
            "immutableObjectKey": f"o/{SHA}/{native}.pdf",
            "ocrObjectKey": f"o/{SHA}/{native}.json",
            "contentSha256": sha,
            "title": f"Doc {native}",
            "sourceFilename": f"{native}.pdf",
            "pageCount": 2,
            "regions": [
                {
                    "regionId": f"{native}-r{i}",
                    "pageIndex0": i % 2,
                    "pageNumber1": i % 2 + 1,
                    "order": i,
                    "text": t,
                }
                for i, t in enumerate(texts)
            ],
        }
    )


@cache
def _pairs():
    texts = [
        "Revenue was 120 dollars in 2024",
        "Café policy is active now",
        "한글 문서 입니다",
        "Approved by the board",
    ]
    return [
        ((_doc(f"a{k}", texts),), (_doc(f"a{k}", texts[::-1]), _doc(f"b{k}", texts)))
        for k in range(3)
    ]


def test_generation_is_deterministic_for_a_seed():
    one = generate(_pairs(), n=160, seed=7)
    assert one == generate(_pairs(), n=160, seed=7)
    assert manifest(one, 7) != manifest(generate(_pairs(), n=160, seed=8), 8)


def test_every_class_is_represented_at_least_sixty_times_in_1000():
    cases = generate(_pairs(), n=1000, seed=1)
    assert len(cases) == 1000 and len({c.case_id for c in cases}) == 1000
    counts = dict.fromkeys(FAULT_CLASSES, 0)
    for c in cases:
        counts[c.fault_class] += 1
    assert len(counts) == 16 and min(counts.values()) >= 60


def test_every_case_is_contract_valid():
    for c in generate(_pairs(), n=320, seed=3):
        for d in (*c.before_docs, *c.after_docs):
            ProductCoreDocument.model_validate(d.model_dump())
            # the compiler's identity rule: a supplied version id must be the derived one
            assert d.source_version_id is None or d.source_version_id == document_version_id(
                source=d.source_id, content_sha256=d.content_sha256
            )
            # object keys stay content-addressed to the (recomputed) hash
            assert d.content_sha256.removeprefix("sha256:") in d.immutable_object_key.split("/")


def test_every_case_is_labelled_generated():
    for c in generate(_pairs(), n=64, seed=2):
        assert (c.provenance, c.generator, c.generator_version) == ("generated", "u06-faults", "1")
        # D12-D13r: one verdict expectation for every class; the runner adds the lineage rule
        assert c.expected == "equal_or_hold"
    assert LINEAGE_CLASS == "duplicate_region_text" and LINEAGE_CLASS in FAULT_CLASSES


# WO-D12-16r: the faults output on this base (n=1000, seed=1) as the CLI writes it, before the
# change (a37c374), and with every `expected` removed (the same before and after).
MANIFEST_SHA256_A37C374 = "2a73c7341227727a7a1369585bf43e79b89095c1725d1cdfca08bf8cf44a13bc"
MANIFEST_WITHOUT_EXPECTED_SHA256 = (
    "1b620a3ad7bd748b880cdd502347f2f5b9f72dd1bff8f4019a1629912cf3855c"
)


def _sha_json(data: Any) -> str:
    return hashlib.sha256((json.dumps(data, indent=2, sort_keys=True) + "\n").encode()).hexdigest()


def test_the_faults_output_on_this_base_moves_only_by_the_duplicate_expectation(
    tmp_path: Path,
) -> None:
    def wire(docs: Any) -> list[Any]:
        return [d.model_dump(by_alias=True, mode="json") for d in docs]

    pairs = tmp_path / "pairs.json"
    pairs.write_text(
        json.dumps([{"before": wire(b), "after": wire(a)} for b, a in _pairs()]), encoding="utf-8"
    )
    assert main(["--pairs", str(pairs), "--out", str(tmp_path)]) == 0  # n=1000, seed=1
    written = json.loads((tmp_path / "faults_manifest.json").read_text(encoding="utf-8"))
    assert "notApplicable" not in written and written["caseCount"] == 1000
    # every class applies here, so nothing was skipped and nothing redistributed
    stripped = json.loads(json.dumps(written))
    for case in stripped["cases"]:
        case.pop("expected")
    assert _sha_json(stripped) == MANIFEST_WITHOUT_EXPECTED_SHA256
    # the one difference from a37c374: the duplicate class's expectation, nothing else
    restored = json.loads(json.dumps(written))
    for case in restored["cases"]:
        if case["faultClass"] == "duplicate_region_text":
            assert case["expected"] == "equal_or_hold"
            case["expected"] = "hold"
    assert _sha_json(restored) == MANIFEST_SHA256_A37C374


def _one_doc_pair() -> list[
    tuple[tuple[ProductCoreDocument, ...], tuple[ProductCoreDocument, ...]]
]:
    doc = _doc("solo", ["Revenue"])  # one document, one region, one word, ASCII
    return [((doc,), (doc,))]


def test_a_class_that_applies_to_no_pair_is_not_applicable_and_its_cases_are_not_redistributed(
    tmp_path: Path,
) -> None:
    cases = generate(_one_doc_pair(), n=32, seed=1)
    skipped = not_applicable(cases, 32)
    assert "delete_source" in skipped and "swap_two_regions_text" in skipped
    assert "duplicate_region_text" not in skipped
    assert {c.fault_class for c in cases}.isdisjoint(skipped)
    assert len(cases) == 32 - 2 * len(skipped)  # each skipped class loses its two indices
    # ids keep their index: case i is still class i mod 16
    order = list(FAULT_CLASSES)
    assert all(c.fault_class == order[int(c.case_id[-4:]) % 16] for c in cases)
    assert not_applicable(cases, 3) == sorted({"delete_source", "reorder_regions"} & set(skipped))
    assert not_applicable(cases, 0) == [] and not_applicable(cases, -5) == []
    # the CLI names them instead of refusing or dropping them silently
    pairs = tmp_path / "pairs.json"
    wire = [d.model_dump(by_alias=True, mode="json") for d in _one_doc_pair()[0][0]]
    pairs.write_text(json.dumps([{"before": wire, "after": wire}]), encoding="utf-8")
    assert main(["--pairs", str(pairs), "--out", str(tmp_path), "--n", "32"]) == 0
    written = json.loads((tmp_path / "faults_manifest.json").read_text(encoding="utf-8"))
    assert written["notApplicable"] == skipped and written["caseCount"] == len(cases)


def test_revert_to_before_has_identical_documents():
    cases = [c for c in generate(_pairs(), n=160, seed=4) if c.fault_class == "revert_to_before"]
    assert cases and all(c.before_docs == c.after_docs for c in cases)


def test_a_rename_keeps_the_content_hash_and_a_text_edit_changes_it():
    by = {c.fault_class: c for c in generate(_pairs(), n=32, seed=5)}
    ren = by["source_rename_same_content"]
    renamed = [d for d in ren.after_docs if d.source_filename.endswith(".renamed")]
    assert len(renamed) == 1
    base = next(d for _b, a in _pairs() for d in a if d.native_id == renamed[0].native_id)
    assert renamed[0].regions == base.regions
    assert renamed[0].content_sha256 == base.content_sha256
    wsp = by["whitespace_only"]
    assert wsp.after_docs != wsp.before_docs


def test_a_base_pair_with_no_regions_is_refused():
    with pytest.raises(ValueError, match="no regions"):
        generate([((), ())], n=16, seed=1)
    with pytest.raises(ValueError, match="no base pairs"):
        generate([], n=16, seed=1)


def test_cli_writes_a_manifest(tmp_path):
    def wire(docs):
        return [d.model_dump(by_alias=True, mode="json") for d in docs]

    pairs = tmp_path / "pairs.json"
    pairs.write_text(
        json.dumps([{"before": wire(b), "after": wire(a)} for b, a in _pairs()]), encoding="utf-8"
    )
    assert main(["--pairs", str(pairs), "--out", str(tmp_path), "--n", "32", "--seed", "9"]) == 0
    m = json.loads((tmp_path / "faults_manifest.json").read_text(encoding="utf-8"))
    assert (m["caseCount"], m["seed"], m["provenance"]) == (32, 9, "generated")


def test_every_after_side_compiles_cold_duplicates_included() -> None:
    comp = ProductCoreCompiler(core_release_digest="sha256:" + "b" * 64)
    compiled = set()
    for c in generate(_pairs(), n=160, seed=1):
        if not c.after_docs:
            continue  # empty cannot form a request
        compiled.add(c.fault_class)
        req = ProductCoreCompileRequest(
            request_id=c.case_id,
            idempotency_key="i" + c.case_id,
            tenant_id=TENANT,
            workspace_id="workspace-x",
            collection_id="collection-x",
            requested_at=datetime(2026, 11, 16, tzinfo=UTC),
            route=ProductCoreRoute(
                operation_class="initial_compile",
                quality_requirement="standard",
                max_cost_credits=1,
                max_latency_ms=60000,
                privacy_policy="foundation_synthetic_only",
            ),
            documents=c.after_docs,
        )
        comp.compile(req, input_sha256="sha256:" + "c" * 64)
    assert "duplicate_region_text" in compiled


def test_on_this_base_every_parent_is_held_so_the_duplicate_class_is_never_met(
    tmp_path: Path,
) -> None:
    """The diagnosis of WO-D12-16: this base 'met' `hold` only because its three parent pairs
    are HOLD before any fault. Through the real runner the class is `parent_already_held`."""

    def ref(name: str, docs: Any) -> dict[str, str]:
        data = json.dumps([json.loads(d.model_dump_json(by_alias=True)) for d in docs]).encode()
        (tmp_path / name).write_bytes(data)
        return {"path": name, "sha256": hashlib.sha256(data).hexdigest()}

    manifest = {
        "requested_at": "2026-11-16T00:00:00+00:00",
        "cases": [
            {
                "case_id": f"r{k}",
                "stratum": "repo",
                "before": ref(f"{k}b", b),
                "after": ref(f"{k}a", a),
            }
            for k, (b, a) in enumerate(_pairs())
        ],
    }
    (tmp_path / "m.json").write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "out"
    flags = ["--fact-key-mode", "candidate", "--faults", "16", "--fault-seed", "1"]
    code = run.main(["--manifest", str(tmp_path / "m.json"), "--out", str(out), *flags])
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert code == 1  # no declared document: the by-construction figures are not exercised
    for arm in ("off", "candidate"):
        assert summary["arms"][arm]["hold"] == 3
        dup = summary["faults"][arm]["duplicate_region_text"]
        assert (dup["cases"], dup["parent_already_held"], dup["expectation_met"]) == (1, 1, 0)
        assert dup["joined"] == 0 and "met in" not in dup["status"]
    assert summary["faults"]["off"]["duplicate_region_text"]["status"] == "parent_already_held"
