"""Candidate contract tests. Synthetic cases, not public quality measurements."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "core-v3" / "src"))

from akc_core_v3.projection_update import (  # noqa: E402
    compile_source_bound_update,
    source_bound_snapshots,
)
from akc_core_v3.projections import DIRECTORY, ProjectionPolicy, plan_artifacts  # noqa: E402
from akc_core_v3.sources import CanonicalUnit, ResolvedSource, SourceDocument  # noqa: E402


def unit() -> CanonicalUnit:
    return CanonicalUnit(
        logical_id="ku_payment",
        document_id="doc_agreement",
        document_title="Agreement",
        section="4. Payment",
        explicit_identifier="4.1",
        text="Payment is due within thirty days.",
        page_number1=10,
        bbox1000=(100, 100, 800, 200),
        evidence_id="evidence-payment",
        region_id="region-payment",
        authority="contractual",
    )


def resolved(*units: CanonicalUnit) -> ResolvedSource:
    payload = json.dumps([asdict(item) for item in units], sort_keys=True).encode()
    sha = hashlib.sha256(payload).hexdigest()
    document = SourceDocument(
        document_id="doc_agreement",
        title="Agreement",
        version_key=sha,
        source_immutable_key=f"fixture/{sha}",
        ocr_object_key=f"fixture/{sha}.json",
        page_count=12,
        text="\n".join(item.text for item in units),
        input_sha256=sha,
        regions=(),
    )
    return ResolvedSource(documents=(document,), units=units, facts=(), source_sha256=sha)


def update(before: ResolvedSource, after: ResolvedSource) -> Any:
    return compile_source_bound_update(
        before=before,
        after=after,
        previous_hashes=plan_artifacts(before).full_rebuild(),
        source_lineage="fixture:agreement",
    )


def test_profile_changes_only_sensitivity_not_existing_artifact_bytes() -> None:
    source = resolved(unit())
    old = plan_artifacts(source)
    new = plan_artifacts(source, policy=ProjectionPolicy.SOURCE_BOUND)
    assert old.artifacts == new.artifacts
    assert old.bodies() == new.bodies()
    assert old.full_rebuild() == new.full_rebuild()
    assert "locator" not in old.sensitivity["claim:ku_payment"]
    assert "locator" in new.sensitivity["claim:ku_payment"]
    assert "locator" in new.sensitivity["summary:doc_agreement"]
    assert "locator" in new.sensitivity["collection:ontology"]


@pytest.mark.parametrize(
    "change",
    [
        {"page_number1": 11},
        {"bbox1000": (100, 110, 800, 220)},
        {"region_id": "region-payment-new"},
        {"evidence_id": "evidence-payment-new"},
        {"authority": "official"},
        {"text": "Payment is due within forty-five days."},
        {"section": "5. Payment"},
        {"document_title": "Revised Agreement"},
    ],
)
def test_every_observed_body_change_is_reflected_in_candidate(change: dict[str, Any]) -> None:
    before = resolved(unit())
    after = resolved(replace(unit(), **change))
    result = update(before, after)
    assert result.equivalence.equivalent
    assert result.equivalence.stale_left_behind == ()
    assert result.candidate_hashes == plan_artifacts(after).full_rebuild()


def test_page_move_updates_claim_summary_and_ontology_and_keeps_directory() -> None:
    result = update(resolved(unit()), resolved(replace(unit(), page_number1=11)))
    assert {"claim:ku_payment", "summary:doc_agreement", "collection:ontology"} <= set(
        result.rebuilt
    )
    assert DIRECTORY in result.carried


def test_text_amendment_does_not_rebuild_structure_only_directory() -> None:
    result = update(
        resolved(unit()), resolved(replace(unit(), text="Payment is due within sixty days."))
    )
    assert DIRECTORY in result.carried
    assert "claim:ku_payment" in result.rebuilt


def test_unchanged_source_reuses_every_artifact() -> None:
    source = resolved(unit())
    result = update(source, source)
    assert result.rebuilt == {}
    assert len(result.carried) == len(plan_artifacts(source).artifacts)


def test_added_unit_updates_directory_using_explicit_precise_policy() -> None:
    added = replace(
        unit(),
        logical_id="ku_law",
        section="5. Law",
        explicit_identifier="5.1",
        text="Applicable law is specified in the agreement.",
        region_id="region-law",
        evidence_id="evidence-law",
    )
    result = update(resolved(unit()), resolved(unit(), added))
    assert DIRECTORY in result.rebuilt
    assert result.equivalence.equivalent


def test_removed_unit_does_not_survive_in_candidate() -> None:
    result = update(resolved(unit()), resolved())
    assert "claim:ku_payment" not in result.candidate_hashes
    assert result.equivalence.equivalent


def test_unknown_profile_is_not_silently_legacy() -> None:
    with pytest.raises(ValueError, match="explicit ProjectionPolicy"):
        plan_artifacts(resolved(unit()), policy="typo")  # type: ignore[arg-type]


def test_caller_must_assert_real_source_lineage() -> None:
    source = resolved(unit())
    with pytest.raises(ValueError, match="SOURCE_LINEAGE_REQUIRED"):
        compile_source_bound_update(
            before=source,
            after=source,
            previous_hashes=plan_artifacts(source).full_rebuild(),
            source_lineage=" ",
        )


def test_tampered_previous_artifact_is_never_carried_forward() -> None:
    source = resolved(unit())
    hashes = plan_artifacts(source).full_rebuild()
    hashes["claim:ku_payment"] = "tampered"
    with pytest.raises(ValueError, match="PREVIOUS_ARTIFACT_BINDING_MISMATCH"):
        compile_source_bound_update(
            before=source, after=source, previous_hashes=hashes, source_lineage="fixture:agreement"
        )


def test_equal_source_digest_cannot_hide_changed_witness() -> None:
    before = resolved(unit())
    after = replace(resolved(replace(unit(), page_number1=11)), source_sha256=before.source_sha256)
    with pytest.raises(ValueError, match="SOURCE_BOUND_EQUIVALENCE_REFUSED"):
        update(before, after)


def test_snapshot_has_observed_authority_and_witness_without_identity_geometry() -> None:
    source = resolved(unit())
    snapshot = source_bound_snapshots(source)[0]
    assert snapshot.authority == unit().authority
    assert snapshot.visual_fingerprint
    assert snapshot.geometry_style == unit().snapshot().geometry_style
    assert snapshot.evidence_id == unit().evidence_id
