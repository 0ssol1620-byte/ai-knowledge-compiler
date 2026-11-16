from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from akc_retrieval import EvidenceHit, RetrievalQuery
from akc_retrieval.packets import (
    EvidenceItem,
    EvidencePacket,
    PacketCoverage,
    build_evidence_packet,
)
from akc_retrieval.temporal import TemporalAdmission

FUTURE = datetime.now(UTC) + timedelta(hours=1)
QUERY = RetrievalQuery(
    tenant_id=uuid.uuid4(),
    project_ids=(uuid.uuid4(),),
    vector=(1.0,) * 32,
    known_at=datetime(2026, 3, 1, tzinfo=UTC),
)


def _hit(**metadata: str) -> EvidenceHit:
    return EvidenceHit(
        stable_id="s1",
        project_id=uuid.uuid4(),
        media_kind="text",
        score=0.9,
        vector_score=0.8,
        evidence_block_ids=(uuid.uuid4(),),
        source_hash="b" * 64,
        metadata=dict(metadata),
    )


def _adm(reason: str) -> TemporalAdmission:
    return TemporalAdmission(admitted=reason == "admitted", reason=reason)  # type: ignore[arg-type]


def _build(hits, admissions, expires_at=FUTURE):
    return build_evidence_packet(
        hits,
        admissions,
        world_id="w",
        snapshot_id="sn",
        query=QUERY,
        access_epoch=3,
        expires_at=expires_at,
    )


def test_a_packet_carries_no_score_fields() -> None:
    names = set(EvidencePacket.model_fields) | set(EvidenceItem.model_fields)
    names |= set(PacketCoverage.model_fields)
    assert not [n for n in names if "score" in n or n in {"rank", "metadata", "features"}]
    packet = _build([_hit()], [_adm("admitted")])
    assert "0.9" not in packet.model_dump_json()


def test_coverage_counts_each_exclusion_reason() -> None:
    adms = [
        _adm("admitted"),
        _adm("excluded_known_after"),
        _adm("excluded_known_after"),
        _adm("excluded_unrecorded"),
    ]
    cov = _build([_hit()], adms).coverage
    assert (cov.admitted, cov.excluded_known_after, cov.excluded_unrecorded) == (1, 2, 1)
    assert cov.excluded_not_valid == 0


def test_an_unknown_locator_stays_none() -> None:
    item = _build([_hit()], [_adm("admitted")]).items[0]
    assert item.source_locator is None and item.valid_from is None
    located = _build([_hit(document_id="d1", source_type="pdf")], [_adm("admitted")]).items[0]
    assert located.source_locator == "d1/pdf"


def test_a_naive_expiry_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _build([], [], expires_at=datetime(2999, 1, 1))


def test_an_expired_packet_is_refused_at_build() -> None:
    with pytest.raises(ValueError, match="expired"):
        _build([], [], expires_at=datetime(2020, 1, 1, tzinfo=UTC))


def test_hits_not_matching_admissions_are_refused() -> None:
    with pytest.raises(ValueError, match="does not match"):
        _build([_hit()], [_adm("excluded_not_valid")])
