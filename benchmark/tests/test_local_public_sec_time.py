"""WO-LPC-2T: two-witness acceptance time. Synthetic values only."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, datetime

from benchmark.local_public.sec_time import accepted_at, bulk_index
from benchmark.retrieval_baselines.metrics import parse_moment

W1_SUMMER = "2025-08-29 16:05:00.0"  # EDT = 20:05 UTC


def test_bulk_utc_agrees():
    got = accepted_at(W1_SUMMER, "2025-08-29T20:05:22.000Z")
    assert got == datetime(2025, 8, 29, 20, 5, 22, tzinfo=UTC)


def test_bulk_eastern_mislabelled_z():
    got = accepted_at(W1_SUMMER, "2025-08-29T16:05:22.000Z")
    assert got == datetime(2025, 8, 29, 20, 5, 22, tzinfo=UTC)


def test_four_hour_disagreement_is_none():
    assert accepted_at(W1_SUMMER, "2025-08-30T00:05:22.000Z") is None
    assert accepted_at(W1_SUMMER, "2025-08-29T12:05:22.000Z") is None


def test_missing_witness_is_none():
    assert accepted_at(W1_SUMMER, None) is None
    assert accepted_at("", "2025-08-29T20:05:22.000Z") is None
    assert accepted_at("garbage", "2025-08-29T20:05:22.000Z") is None
    assert accepted_at(W1_SUMMER, "garbage") is None


def test_dst_boundaries():
    # EST (before March change): 09:30 ET = 14:30 UTC
    assert accepted_at("2025-03-07 09:30:00.0", "2025-03-07T14:30:10.000Z") == datetime(
        2025, 3, 7, 14, 30, 10, tzinfo=UTC
    )
    # EDT (after March change): 09:30 ET = 13:30 UTC
    assert accepted_at("2025-03-10 09:30:00.0", "2025-03-10T13:30:10.000Z") == datetime(
        2025, 3, 10, 13, 30, 10, tzinfo=UTC
    )
    # Eastern-mislabelled on each side of November
    assert accepted_at("2025-10-31 09:30:00.0", "2025-10-31T09:30:10.000Z") == datetime(
        2025, 10, 31, 13, 30, 10, tzinfo=UTC
    )
    assert accepted_at("2025-11-03 09:30:00.0", "2025-11-03T09:30:10.000Z") == datetime(
        2025, 11, 3, 14, 30, 10, tzinfo=UTC
    )


def test_never_naive_and_round_trips():
    got = accepted_at(W1_SUMMER, "2025-08-29T16:05:22.000Z")
    assert got is not None and got.tzinfo is not None and got.utcoffset() is not None
    assert parse_moment(got.isoformat(), field="t") == got


def test_bulk_index_reads_recent_and_older_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "CIK0000000001.json",
            json.dumps(
                {
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000000001-25-000001", "0000000001-25-000002"],
                            "acceptanceDateTime": ["2025-08-29T20:05:22.000Z", ""],
                        }
                    }
                }
            ),
        )
        z.writestr(
            "CIK0000000001-submissions-001.json",
            json.dumps(
                {
                    "accessionNumber": ["0000000001-20-000003"],
                    "acceptanceDateTime": ["2020-01-02T21:00:00.000Z"],
                }
            ),
        )
        z.writestr("readme.txt", "x")
    with zipfile.ZipFile(buf) as z:
        idx = bulk_index(z)
    assert idx == {
        "0000000001-25-000001": "2025-08-29T20:05:22.000Z",
        "0000000001-20-000003": "2020-01-02T21:00:00.000Z",
    }
