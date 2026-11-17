"""A logical id belongs to one current unit (WO-D12-9, finding F-D12-2).

The class: a logical id claimed by more than one current unit of a compile - by inheritance from
the matcher, or by a seed - is never shared. A NEW claimant is held unresolved; anything still
duplicated after that (a malformed previous world) is refused by name, `LogicalIdCollision`.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, datetime

import pytest
from akc_product_core.compiler import LogicalIdCollision, ProductCoreCompiler
from akc_product_core.contracts import (
    PreviousWorldSnapshot,
    ProductCoreCompileResponse,
    ProductCoreDocument,
)

from benchmark.revision_pairs.to_product_core import make_doc
from benchmark.u06_equivalence.harness import _request, compile_pair, run_case

AT = datetime(2026, 1, 1, tzinfo=UTC)
NET_INCOME = "Net income for fiscal 2024 was 100 million USD."
REVENUE = "Revenue for fiscal 2024 was 900 million USD."
ASSETS = "Total assets at the end of fiscal 2025 were 5,000 million USD."
RELEASE = "sha256:" + "a" * 64


def _doc(parts: list[tuple[str, str]], native_id: str = "doc-1") -> ProductCoreDocument:
    return make_doc(
        connector="synthetic",
        native_id=native_id,
        title="Synthetic statement",
        parts=parts,
        key_prefix="syn",
        version="v1",
    ).model_copy(update={"source_id": None, "source_version_id": None})


# receipts/WO-LPC-R3/diag2/synthetic_dup_logical.py: the fact at TagA-ctx1 moves to TagA-ctx2 and
# unrelated text takes TagA-ctx1. The moved unit inherits the old id; TagA-ctx1's seed is that id.
BEFORE = _doc([("TagA-ctx1", NET_INCOME), ("TagB-ctx1", REVENUE)])
AFTER = _doc([("TagA-ctx1", ASSETS), ("TagA-ctx2", NET_INCOME), ("TagB-ctx1", REVENUE)])


def _compile(
    documents: list[ProductCoreDocument], previous: PreviousWorldSnapshot | None = None
) -> ProductCoreCompileResponse:
    request = _request(
        documents,
        request_id="req-unique",
        previous=previous,
        requested_at=AT,
        tenant_id="tenant-foundation-pilot",
        workspace_id="workspace-foundation-pilot",
        collection_id="collection-unique",
    )
    return ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256="sha256:" + hashlib.sha256(b"unique").hexdigest()
    )


def _snapshot(response: ProductCoreCompileResponse) -> PreviousWorldSnapshot:
    return PreviousWorldSnapshot(
        world_state_id=response.candidate.world_state_id,
        manifest_digest=response.candidate.manifest_digest,
        units=response.candidate.units,
        artifact_hashes=response.candidate.artifact_hashes,
    )


def test_a_new_seed_equal_to_an_inherited_id_is_held_and_the_pair_is_hold() -> None:
    # On ae4edbb this raised KeyError in _package_projection (two current units, one id).
    result = run_case([BEFORE], [AFTER], requested_at=AT)

    assert result.verdict == "HOLD"
    assert result.hold_reasons == ("IDENTITY_UNRESOLVED",)
    assert not any(reason.startswith("COMPILE_ERROR:") for reason in result.hold_reasons)

    before = _compile([BEFORE])
    incremental, _ = compile_pair([BEFORE], [AFTER], requested_at=AT)
    old_id = {u.anchor: u.logical_id for u in before.candidate.units}["TagA-ctx1"]
    units = {u.anchor: u for u in incremental.candidate.units}
    assert units["TagA-ctx2"].identity_state == "matched"
    assert units["TagA-ctx2"].logical_id == old_id
    assert units["TagA-ctx1"].identity_state == "unresolved"
    assert units["TagA-ctx1"].logical_id.startswith("ku_unresolved_")
    assert units["TagB-ctx1"].identity_state == "matched"
    assert len({u.logical_id for u in incremental.candidate.units}) == 3
    assert any(
        r.startswith("IDENTITY_AMBIGUOUS:") and r.endswith(":TagA-ctx1")
        for r in incremental.candidate.review_reasons
    )


def test_two_anchors_that_normalise_alike_are_both_held_not_shared() -> None:
    # The seed folds case and punctuation of the anchor: "Fact-1" and "fact.1" seed one id.
    response = _compile([_doc([("Fact-1", NET_INCOME), ("fact.1", REVENUE)])])

    states = {u.anchor: u.identity_state for u in response.candidate.units}
    assert states == {"Fact-1": "unresolved", "fact.1": "unresolved"}
    assert len({u.logical_id for u in response.candidate.units}) == 2
    assert response.status == "review_required"


def test_distinct_seeds_in_a_cold_compile_stay_new() -> None:
    # The class boundary: no shared id, no hold.
    response = _compile([AFTER])

    assert {u.identity_state for u in response.candidate.units} == {"new"}
    assert not any(r.startswith("IDENTITY_AMBIGUOUS:") for r in response.candidate.review_reasons)


def test_a_previous_world_that_gives_two_units_one_id_is_refused_by_name() -> None:
    first = _doc([("TagA-ctx1", NET_INCOME)], native_id="doc-1")
    second = _doc([("TagB-ctx1", REVENUE)], native_id="doc-2")
    snapshot = _snapshot(_compile([first, second]))
    shared = snapshot.units[0].logical_id
    forged = snapshot.model_copy(
        update={
            "units": (
                snapshot.units[0],
                snapshot.units[1].model_copy(update={"logical_id": shared}),
            )
        }
    )

    with pytest.raises(LogicalIdCollision) as raised:
        _compile([first, second], previous=forged)

    assert raised.value.logical_ids == [shared]
    assert isinstance(raised.value, ValueError)
    for text in (NET_INCOME, REVENUE):
        assert text not in str(raised.value)


def test_a_matched_and_an_unresolved_unit_sharing_evidence_leave_it_unresolved() -> None:
    # Reviewer note on ae4edbb: TagB-ctx1 now repeats TagA-ctx1's text (no box, same page), so
    # both share one evidence id. One unit is matched, one unresolved: the shared object is
    # UNRESOLVED (any, not all), while each claim keeps its own unit's state and region.
    before = _compile([_doc([("TagA-ctx1", NET_INCOME), ("TagB-ctx1", REVENUE)])])
    after = _compile(
        [_doc([("TagA-ctx1", NET_INCOME), ("TagB-ctx1", NET_INCOME)])], previous=_snapshot(before)
    )

    states = {u.anchor: u.identity_state for u in after.candidate.units}
    assert states == {"TagA-ctx1": "matched", "TagB-ctx1": "unresolved"}
    objects = after.candidate.canonical_knowledge_model["objects"]
    evidence = [o for o in objects if o["kind"] == "evidence"]
    assert len(evidence) == 1
    assert evidence[0]["verificationState"] == "unresolved"
    assert [r["nativeObjectId"] for r in evidence[0]["sourceRefs"]] == ["TagA-ctx1", "TagB-ctx1"]
    anchor_by_logical = {u.logical_id: u.anchor for u in after.candidate.units}
    claims = {
        anchor_by_logical[o["payload"]["logicalId"]]: o for o in objects if o["kind"] == "claim"
    }
    assert claims["TagA-ctx1"]["verificationState"] == "verified_with_warning"
    assert claims["TagB-ctx1"]["verificationState"] == "unresolved"
    for anchor, claim in claims.items():
        assert [r["nativeObjectId"] for r in claim["sourceRefs"]] == [anchor]


def test_logical_ids_of_current_units_are_unique_after_every_compile() -> None:
    for response in (
        _compile([AFTER]),
        _compile([AFTER], previous=_snapshot(_compile([BEFORE]))),
    ):
        held = Counter(u.logical_id for u in response.candidate.units)
        assert max(held.values()) == 1
