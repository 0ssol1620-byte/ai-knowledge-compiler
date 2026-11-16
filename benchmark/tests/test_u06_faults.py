"""WO-D12-5 tests. Base pairs here are synthetic test fixtures, not corpus data."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import cache

import pytest
from akc_cir.identity import document_version_id, source_id
from akc_product_core import ProductCoreCompiler, ProductCoreCompileRequest
from akc_product_core.contracts import ProductCoreDocument, ProductCoreRoute

from benchmark.u06_equivalence.faults import FAULT_CLASSES, generate, main, manifest

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
        assert c.expected == (
            "hold" if c.fault_class == "duplicate_region_text" else "equal_or_hold"
        )


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


def test_every_non_duplicate_after_side_compiles_cold():
    comp = ProductCoreCompiler(core_release_digest="sha256:" + "b" * 64)
    for c in generate(_pairs(), n=160, seed=1):
        if c.fault_class == "duplicate_region_text" or not c.after_docs:
            continue  # duplicate text is a Core "hold" by design; empty cannot form a request
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
