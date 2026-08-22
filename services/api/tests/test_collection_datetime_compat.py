from datetime import UTC, datetime, timedelta, timezone

import pytest
from akc_api.collection_api import _elapsed_seconds, _wire_utc


@pytest.mark.parametrize(
    ("started_at", "completed_at"),
    [
        (
            datetime(2026, 8, 3, 1, 2, 3),
            datetime(2026, 8, 3, 1, 2, 8, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 3, 1, 2, 3, tzinfo=UTC),
            datetime(2026, 8, 3, 1, 2, 8),
        ),
        (
            datetime(2026, 8, 3, 10, 2, 3, tzinfo=timezone(timedelta(hours=9))),
            datetime(2026, 8, 3, 1, 2, 8, tzinfo=UTC),
        ),
    ],
)
def test_elapsed_seconds_normalizes_sqlite_and_postgres_timestamps(
    started_at: datetime,
    completed_at: datetime,
) -> None:
    assert _elapsed_seconds(started_at, completed_at) == 5.0


def test_elapsed_seconds_clamps_clock_regression() -> None:
    started_at = datetime(2026, 8, 3, 1, 2, 8, tzinfo=UTC)
    completed_at = datetime(2026, 8, 3, 1, 2, 3)

    assert _elapsed_seconds(started_at, completed_at) == 0.0


def test_wire_utc_restores_explicit_offset_after_sqlite_round_trip() -> None:
    persisted = datetime(2026, 8, 3, 1, 2, 3)

    assert _wire_utc(persisted).isoformat() == "2026-08-03T01:02:03+00:00"
