"""Source-declared dates and the bitemporal view of a compile (WO-D12-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from akc_cir.temporal import TemporalPolicy, TemporalSource
from akc_product_core import ProductCoreCompiler
from akc_product_core.temporal_view import timeline_from_compile
from pydantic import ValidationError

from tests.unit.test_product_core_bridge import RELEASE, _document, _request, _sha

PUBLISHED = datetime(2026, 1, 1, tzinfo=UTC)
FROM = datetime(2026, 2, 1, tzinfo=UTC)
TO = datetime(2026, 12, 31, tzinfo=UTC)


def _compile(document):
    request = _request((document,), request_id="compile-temporal")
    response = ProductCoreCompiler(core_release_digest=RELEASE).compile(
        request, input_sha256=_sha("temporal")
    )
    return request, response


def _dated(**fields):
    return _document("filing-a", "Revenue is 100 million won.").model_copy(update=fields)


def test_a_claim_from_a_document_with_declared_validity_is_explicit() -> None:
    request, response = _compile(_dated(available_at=PUBLISHED, valid_from=FROM, valid_to=TO))
    timeline, available = timeline_from_compile(request, response)

    answer = timeline.as_of(valid_at=datetime(2026, 6, 1, tzinfo=UTC))
    assert answer.values == ("Revenue is 100 million won.",)
    fact = answer.facts[0]
    assert fact.temporal_source is TemporalSource.EXPLICIT
    assert (fact.valid_from, fact.valid_to) == (FROM, TO)
    assert fact.recorded_at == request.requested_at
    assert list(available.values()) == [PUBLISHED]
    assert not timeline.as_of(valid_at=datetime(2027, 1, 1, tzinfo=UTC)).facts


def test_a_claim_without_declared_dates_is_unknown_and_excluded_by_default() -> None:
    request, response = _compile(_dated())
    timeline, _ = timeline_from_compile(request, response)

    answer = timeline.as_of(valid_at=datetime(2026, 6, 1, tzinfo=UTC))
    assert answer.facts == ()
    assert answer.excluded_unknown
    included = timeline.as_of(
        valid_at=datetime(2026, 6, 1, tzinfo=UTC), policy=TemporalPolicy.INCLUDE_UNKNOWN
    )
    assert included.facts[0].temporal_source is TemporalSource.UNKNOWN


def test_known_at_before_the_compile_excludes_every_claim() -> None:
    request, response = _compile(_dated(valid_from=FROM))
    timeline, _ = timeline_from_compile(request, response)

    before = request.requested_at - timedelta(seconds=1)
    assert timeline.as_of(known_at=before).facts == ()
    assert len(timeline.as_of(known_at=request.requested_at).facts) == len(timeline)


def test_available_at_is_reported_not_invented() -> None:
    request, response = _compile(_dated(valid_from=FROM))
    _, available = timeline_from_compile(request, response)

    assert available
    assert set(available.values()) == {None}


def test_a_naive_declared_date_is_refused() -> None:
    for field in ("available_at", "valid_from", "valid_to"):
        with pytest.raises(ValidationError, match="timezone-aware"):
            _dated_validated(**{field: datetime(2026, 1, 1)})


def test_an_inverted_declared_window_is_refused() -> None:
    with pytest.raises(ValidationError, match="validTo precedes validFrom"):
        _dated_validated(valid_from=TO, valid_to=FROM)


def test_a_non_utc_aware_date_is_accepted() -> None:
    kst = timezone(timedelta(hours=9))
    assert _dated_validated(valid_from=datetime(2026, 2, 1, tzinfo=kst)).valid_from is not None


def test_omitting_the_new_fields_leaves_the_candidate_bytes_unchanged() -> None:
    plain = _document("filing-a", "Revenue is 100 million won.")
    dated = _dated_validated(available_at=PUBLISHED, valid_from=FROM, valid_to=TO)

    _, without = _compile(plain)
    _, with_dates = _compile(dated)
    assert without.receipt.output_sha256 == with_dates.receipt.output_sha256
    assert "availableAt" not in plain.model_dump(mode="json", by_alias=True, exclude_none=True)


def _without_ids(**fields):
    base = _document("filing-a", "Revenue is 100 million won.")
    data = base.model_dump(by_alias=True)
    data.pop("sourceId", None)
    data.pop("sourceVersionId", None)
    data.update(fields)
    return type(base).model_validate(data)


def test_a_document_without_source_ids_still_maps_to_its_claims() -> None:
    document = _without_ids(availableAt=PUBLISHED, validFrom=FROM, validTo=TO)
    assert document.source_id is None and document.source_version_id is None
    request, response = _compile(document)
    timeline, available = timeline_from_compile(request, response)

    assert {
        f.temporal_source for f in timeline.as_of(valid_at=datetime(2026, 6, 1, tzinfo=UTC)).facts
    } == {TemporalSource.EXPLICIT}
    assert set(available.values()) == {PUBLISHED}


def test_a_claim_with_no_matching_request_document_is_refused() -> None:
    request, response = _compile(_without_ids(validFrom=FROM))
    orphaned = request.model_copy(update={"documents": ()})
    with pytest.raises(ValueError, match="no matching request document"):
        timeline_from_compile(orphaned, response)


def _dated_validated(**fields):
    base = _document("filing-a", "Revenue is 100 million won.")
    camel = {"available_at": "availableAt", "valid_from": "validFrom", "valid_to": "validTo"}
    return type(base).model_validate(
        {**base.model_dump(by_alias=True), **{camel[key]: value for key, value in fields.items()}}
    )
