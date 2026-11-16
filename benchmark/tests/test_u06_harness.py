"""U06 harness: normalization, verdicts and negative controls (synthetic documents)."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from akc_cir.identity import document_version_id, source_id
from akc_cir.models import BBox1000, BlockType
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreRegion,
)

from benchmark.u06_equivalence import run as u06_run
from benchmark.u06_equivalence.harness import compile_pair, judge, run_case
from benchmark.u06_equivalence.normalize import NormalizationAmbiguous, normalize

TENANT = "tenant-foundation-pilot"
NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _doc(native_id: str, *texts: str) -> ProductCoreDocument:
    src = source_id(tenant_id=TENANT, connector_type="foundation-r2", native_id=native_id)
    digest = _sha("\n".join(texts))
    return ProductCoreDocument(
        native_id=native_id,
        connector_type="foundation-r2",
        source_id=src,
        source_version_id=document_version_id(source=src, content_sha256=digest),
        immutable_object_key=f"immutable/{TENANT}/w/{native_id}/{digest[7:]}/source.pdf",
        ocr_object_key=f"immutable/{TENANT}/w/{native_id}/{digest[7:]}/ocr.json",
        content_sha256=digest,
        title=f"Document {native_id}",
        source_filename=f"{native_id}.pdf",
        page_count=1,
        regions=tuple(
            ProductCoreRegion(
                region_id=f"region-{native_id}-{i}",
                page_index0=0,
                page_number1=1,
                order=i,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=BBox1000((100, 120 + i, 900, 240 + i)),
                confidence=0.99,
                authority="regulatory_filing",
            )
            for i, text in enumerate(texts)
        ),
    )


A = _doc("filing-a", "Revenue is 100 million won.")
B = _doc("policy-b", "The board approved the policy.")


def test_an_added_source_is_equal() -> None:
    result = run_case((A,), (A, B), requested_at=NOW)
    assert result.verdict == "EQUAL"
    assert result.phantom == 0


def test_an_unchanged_pair_holds_on_the_compilers_own_equivalence_check() -> None:
    # FINDING, not a feature: `retrieval/global` hashes `identity_state` ("new" in A, "matched"
    # in the incremental), so carrying it over an unchanged revision fails the compiler's check.
    # The harness must say HOLD, never EQUAL, and never hide it. Fixing it is the compiler's WO.
    result = run_case((A, B), (A, B), requested_at=NOW)
    assert result.verdict == "HOLD"
    assert "EQUIVALENCE_FAILED" in result.hold_reasons


def test_a_unit_with_a_different_logical_id_normalizes_equal_to_cold() -> None:
    # Same text, new region ids -> the incremental and cold logical/claim ids differ, so equality
    # holds only if normalization rewrites them to unit and claim keys.
    e1 = _doc("filing-e", "Mercury Systems reported revenue of 100 million won in 2025.")
    renamed = e1.model_copy(
        update={
            "regions": tuple(
                r.model_copy(update={"region_id": r.region_id + "-x"}) for r in e1.regions
            )
        }
    )
    incremental, cold = compile_pair((e1,), (renamed,), requested_at=NOW)
    assert {u.logical_id for u in incremental.candidate.units} != {
        u.logical_id for u in cold.candidate.units
    }
    assert normalize(incremental) == normalize(cold)


def test_a_stale_non_claim_object_is_phantom_even_under_hold() -> None:
    e1 = _doc(
        "filing-e",
        "Mercury Systems reported revenue of 100 million won in 2025.",
        "Mercury Systems acquired Venus Labs.",
    )
    moved = e1.model_copy(
        update={
            "page_count": 2,
            "regions": tuple(
                r.model_copy(update={"page_index0": 1, "page_number1": 2}) for r in e1.regions
            ),
        }
    )
    incremental, cold = compile_pair((e1,), (moved,), requested_at=NOW)
    clean = judge(incremental, cold)
    assert clean.verdict == "HOLD" and clean.phantom == 0
    model = copy.deepcopy(incremental.candidate.canonical_knowledge_model)
    stale = copy.deepcopy(next(o for o in model["objects"] if o["kind"] == "entity"))
    stale["stableId"] = stale["payload"]["entityId"] = "entity_stale"
    stale["payload"]["canonicalName"] = "Stale Corp"
    model["objects"].append(stale)
    result = judge(_with_model(incremental, model), cold)
    assert result.verdict == "HOLD"
    assert result.phantom >= 1


def test_an_unresolved_identity_is_hold_not_equal() -> None:
    edited = _doc("filing-a", "Revenue is 120 million won.")
    result = run_case((A, B), (edited, B), requested_at=NOW)
    assert result.verdict == "HOLD"
    assert "IDENTITY_UNRESOLVED" in result.hold_reasons
    assert result.review_reasons[0].startswith("IDENTITY_AMBIGUOUS:")


def test_a_removed_source_leaves_no_phantom_fact() -> None:
    result = run_case((A, B), (A,), requested_at=NOW)
    assert result.phantom == 0
    assert result.verdict != "DIVERGED"


def test_a_tampered_carried_artifact_hash_makes_the_case_hold() -> None:
    def tamper(previous: PreviousWorldSnapshot) -> PreviousWorldSnapshot:
        hashes = dict(previous.artifact_hashes)
        hashes[sorted(hashes)[0]] = "sha256:" + "0" * 64
        return previous.model_copy(update={"artifact_hashes": hashes})

    result = run_case((A,), (A, B), requested_at=NOW, tamper_previous=tamper)
    assert result.verdict == "HOLD"
    assert "EQUIVALENCE_FAILED" in result.hold_reasons


def _with_model(response: ProductCoreCompileResponse, model: Any) -> ProductCoreCompileResponse:
    candidate = response.candidate.model_copy(update={"canonical_knowledge_model": model})
    return response.model_copy(update={"candidate": candidate})


def test_an_injected_extra_claim_is_diverged_and_phantom() -> None:
    incremental, cold = compile_pair((A,), (A, B), requested_at=NOW)
    model = copy.deepcopy(incremental.candidate.canonical_knowledge_model)
    extra = copy.deepcopy(next(o for o in model["objects"] if o["kind"] == "claim"))
    extra["stableId"] = extra["payload"]["claimId"] = "claim_phantom"
    extra["payload"]["text"] = "Profit tripled."
    model["objects"].append(extra)
    result = judge(_with_model(incremental, model), cold)
    assert result.verdict == "DIVERGED"
    assert result.phantom >= 1
    assert result.only_incremental["assertions"] >= 1


def test_duplicate_anchors_are_ambiguous_not_equal() -> None:
    incremental, cold = compile_pair((A,), (A, B), requested_at=NOW)
    first = incremental.candidate.units[0]
    units = (
        first,
        first.model_copy(update={"logical_id": "ku_dup"}),
        *incremental.candidate.units[1:],
    )
    candidate = incremental.candidate.model_copy(update={"units": units})
    broken = incremental.model_copy(update={"candidate": candidate})
    with pytest.raises(NormalizationAmbiguous):
        normalize(broken)
    result = judge(broken, cold)
    assert result.verdict == "HOLD"
    assert "NORMALIZATION_AMBIGUOUS" in result.hold_reasons


def _write_manifest(tmp_path: Path, sha: str | None = None) -> Path:
    def ref(name: str, docs: tuple[ProductCoreDocument, ...]) -> dict[str, str]:
        data = json.dumps([json.loads(d.model_dump_json(by_alias=True)) for d in docs]).encode()
        (tmp_path / name).write_bytes(data)
        return {"path": name, "sha256": sha or hashlib.sha256(data).hexdigest()}

    manifest = {
        "requested_at": NOW.isoformat(),
        "cases": [
            {
                "case_id": "c1",
                "stratum": "added",
                "before": ref("before.json", (A,)),
                "after": ref("after.json", (A, B)),
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_run_writes_a_summary_for_a_verified_manifest(tmp_path: Path) -> None:
    out = tmp_path / "out"
    assert u06_run.main(["--manifest", str(_write_manifest(tmp_path)), "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text())
    assert summary["equal"] == 1 and summary["phantom_total"] == 0
    assert summary["per_stratum"]["added"]["equal"] == 1


def test_run_refuses_a_manifest_hash_mismatch(tmp_path: Path) -> None:
    out = tmp_path / "out"
    manifest = _write_manifest(tmp_path, sha="0" * 64)
    assert u06_run.main(["--manifest", str(manifest), "--out", str(out)]) == 2
    assert not out.exists()
