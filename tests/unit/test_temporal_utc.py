from datetime import UTC, datetime, timedelta, timezone

import pytest
from akc_cir.temporal import TemporalFact, TemporalSource, TemporalTimeline, replay_context

NAIVE = datetime(2026, 1, 1)
AWARE = datetime(2026, 1, 1, tzinfo=UTC)


def test_a_naive_recorded_at_is_refused() -> None:
    with pytest.raises(ValueError, match="recorded_at must be timezone-aware"):
        TemporalFact("a", "v", recorded_at=NAIVE)


def test_a_naive_valid_from_is_refused() -> None:
    with pytest.raises(ValueError, match="valid_from must be timezone-aware"):
        TemporalFact("a", "v", valid_from=NAIVE, temporal_source=TemporalSource.EXPLICIT)


def test_a_naive_query_moment_is_refused() -> None:
    tl = TemporalTimeline([TemporalFact("a", "v", recorded_at=AWARE)])
    with pytest.raises(ValueError, match="valid_at must be timezone-aware"):
        tl.as_of(valid_at=NAIVE)
    with pytest.raises(ValueError, match="known_at must be timezone-aware"):
        tl.as_of(known_at=NAIVE)
    with pytest.raises(ValueError, match="at must be timezone-aware"):
        replay_context(tl, at=NAIVE)


def test_a_non_utc_aware_moment_compares_correctly() -> None:
    kst = timezone(timedelta(hours=9))
    fact = TemporalFact("a", "v", recorded_at=datetime(2026, 1, 1, 9, tzinfo=kst))
    tl = TemporalTimeline([fact])
    assert tl.as_of(known_at=AWARE).facts == (fact,)
    assert tl.as_of(known_at=AWARE - timedelta(seconds=1)).facts == ()


def test_none_stays_allowed_everywhere() -> None:
    fact = TemporalFact("a", "v")
    tl = TemporalTimeline([fact])
    assert tl.as_of().facts == (fact,)
