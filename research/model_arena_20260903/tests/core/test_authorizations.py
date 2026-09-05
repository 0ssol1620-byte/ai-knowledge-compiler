"""The authorization gate (ARENA_CONTRACT 11.4) must fail closed.

Every test here asks one question: can a paid phase start? The interesting
answers are the refusals. A receipt for another campaign, a receipt that
expired, a receipt scoped to a different model and a directory holding one
file the loader cannot parse must all end with *no* authorization -- or with
an exception, never with a quiet "probably fine".
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from arena.constants import CAMPAIGN_ID
from arena.core.authorizations import (
    AuthorizationError,
    format_timestamp,
    load_authorizations,
    parse_authorization,
    select_authorization,
)

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)


def _receipt(**overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schema": "tavonel.arena.authorization-receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "phase": "phase1_canary",
        "authorized_by": "founder",
        "authorized_at": format_timestamp(NOW - timedelta(hours=1)),
        "expires_at": format_timestamp(NOW + timedelta(days=1)),
        "max_usd": 100.0,
        "model_keys": "*",
        "statement": "Founder authorized the phase 1 canary on 2026-09-03.",
    }
    record.update(overrides)
    return record


def _write(directory: Path, name: str, record: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    return path


def _load(directory: Path) -> tuple[Any, ...]:
    return load_authorizations(directory, campaign_id=CAMPAIGN_ID)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def test_a_valid_receipt_is_selected(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    chosen = select_authorization(
        _load(tmp_path),
        phase="phase1_canary",
        model_key="paddleocr_vl_1_6",
        now=NOW,
        required_usd=42.0,
    )
    assert chosen is not None
    assert chosen.max_usd == 100.0
    assert chosen.model_keys is None
    record = chosen.to_record()
    assert record["campaign_id"] == CAMPAIGN_ID
    assert record["model_keys"] == "*"
    assert record["sha256"] == chosen.sha256


def test_the_receipt_sha256_is_the_file_bytes(tmp_path: Path) -> None:
    import hashlib

    path = _write(tmp_path, "canary.json", _receipt())
    parsed = parse_authorization(path, campaign_id=CAMPAIGN_ID)
    assert parsed.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def test_a_receipt_for_another_campaign_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "other.json", _receipt(campaign_id="SOME-OTHER-CAMPAIGN"))
    with pytest.raises(AuthorizationError, match="campaign_id"):
        parse_authorization(path, campaign_id=CAMPAIGN_ID)
    with pytest.raises(AuthorizationError, match="campaign_id"):
        _load(tmp_path)


def test_a_malformed_file_in_the_directory_raises(tmp_path: Path) -> None:
    """Fail closed: one unreadable file blocks the whole directory."""

    _write(tmp_path, "good.json", _receipt())
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(AuthorizationError, match="not valid UTF-8 JSON"):
        _load(tmp_path)


def test_a_schema_violation_raises(tmp_path: Path) -> None:
    _write(tmp_path, "bad.json", _receipt(phase="phase9_unknown"))
    with pytest.raises(AuthorizationError, match="schema violation"):
        _load(tmp_path)


def test_a_negative_budget_receipt_raises(tmp_path: Path) -> None:
    _write(tmp_path, "bad.json", _receipt(max_usd=0))
    with pytest.raises(AuthorizationError, match="schema violation"):
        _load(tmp_path)


def test_expiry_before_authorization_raises(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "bad.json",
        _receipt(expires_at=format_timestamp(NOW - timedelta(days=2))),
    )
    with pytest.raises(AuthorizationError, match="expires_at must be after"):
        _load(tmp_path)


def test_a_missing_directory_returns_no_receipts(tmp_path: Path) -> None:
    assert _load(tmp_path / "does-not-exist") == ()


def test_a_file_where_a_directory_belongs_raises(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "authorizations"
    not_a_dir.write_text("{}", encoding="utf-8")
    with pytest.raises(AuthorizationError, match="is not a directory"):
        _load(not_a_dir)


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------


def test_an_expired_receipt_is_excluded(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "expired.json",
        _receipt(
            authorized_at=format_timestamp(NOW - timedelta(days=3)),
            expires_at=format_timestamp(NOW - timedelta(hours=1)),
        ),
    )
    receipts = _load(tmp_path)
    assert receipts[0].is_expired(NOW)
    assert (
        select_authorization(
            receipts,
            phase="phase1_canary",
            model_key="paddleocr_vl_1_6",
            now=NOW,
            required_usd=1.0,
        )
        is None
    )


def test_a_post_dated_receipt_does_not_cover_today(tmp_path: Path) -> None:
    """11.5 D32: authorized_at <= now. A future receipt has not been given yet."""

    _write(
        tmp_path,
        "future.json",
        _receipt(
            authorized_at=format_timestamp(NOW + timedelta(hours=1)),
            expires_at=format_timestamp(NOW + timedelta(days=2)),
        ),
    )
    receipts = _load(tmp_path)
    assert receipts[0].is_not_yet_valid(NOW)
    assert not receipts[0].is_expired(NOW)
    assert not receipts[0].covers(phase="phase1_canary", model_key="glm_ocr", now=NOW)
    assert (
        select_authorization(
            receipts,
            phase="phase1_canary",
            model_key="glm_ocr",
            now=NOW,
            required_usd=1.0,
        )
        is None
    )


def test_a_post_dated_receipt_starts_covering_at_its_own_timestamp(tmp_path: Path) -> None:
    """The bound is inclusive: at authorized_at the receipt is live."""

    starts = NOW + timedelta(hours=1)
    _write(tmp_path, "future.json", _receipt(authorized_at=format_timestamp(starts)))
    receipt = _load(tmp_path)[0]
    def covers(now: datetime) -> bool:
        return receipt.covers(phase="phase1_canary", model_key="glm_ocr", now=now)

    assert not covers(starts - timedelta(seconds=1))
    assert covers(starts)
    assert covers(starts + timedelta(hours=1))


def test_a_post_dated_receipt_is_not_selected_over_a_valid_one(tmp_path: Path) -> None:
    """A larger future budget must not outrank the receipt that is actually live."""

    _write(tmp_path, "live.json", _receipt(max_usd=10.0))
    _write(
        tmp_path,
        "future.json",
        _receipt(
            max_usd=900.0,
            authorized_at=format_timestamp(NOW + timedelta(days=1)),
            expires_at=format_timestamp(NOW + timedelta(days=3)),
        ),
    )
    chosen = select_authorization(
        _load(tmp_path),
        phase="phase1_canary",
        model_key="glm_ocr",
        now=NOW,
        required_usd=5.0,
    )
    assert chosen is not None
    assert chosen.max_usd == 10.0


def test_is_not_yet_valid_refuses_a_naive_now(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    with pytest.raises(AuthorizationError):
        _load(tmp_path)[0].is_not_yet_valid(datetime(2026, 9, 3, 12, 0, 0))


def test_a_receipt_without_an_expiry_never_expires(tmp_path: Path) -> None:
    _write(tmp_path, "forever.json", _receipt(expires_at=None))
    receipts = _load(tmp_path)
    assert not receipts[0].is_expired(NOW + timedelta(days=3650))


def test_a_model_scoped_receipt_does_not_cover_another_model(tmp_path: Path) -> None:
    _write(tmp_path, "scoped.json", _receipt(model_keys=["paddleocr_vl_1_6"]))
    receipts = _load(tmp_path)
    assert receipts[0].covers(phase="phase1_canary", model_key="paddleocr_vl_1_6", now=NOW)
    assert not receipts[0].covers(phase="phase1_canary", model_key="olmocr2", now=NOW)
    assert (
        select_authorization(
            receipts,
            phase="phase1_canary",
            model_key="olmocr2",
            now=NOW,
            required_usd=1.0,
        )
        is None
    )


def test_a_model_scoped_receipt_does_not_cover_a_campaign_wide_action(tmp_path: Path) -> None:
    _write(tmp_path, "scoped.json", _receipt(model_keys=["paddleocr_vl_1_6"]))
    receipts = _load(tmp_path)
    assert not receipts[0].covers(phase="phase1_canary", model_key=None, now=NOW)
    assert (
        select_authorization(
            receipts, phase="phase1_canary", model_key=None, now=NOW, required_usd=1.0
        )
        is None
    )


def test_a_star_receipt_covers_any_model_and_a_campaign_wide_action(tmp_path: Path) -> None:
    _write(tmp_path, "star.json", _receipt())
    receipts = _load(tmp_path)
    for model_key in ("paddleocr_vl_1_6", "olmocr2", None):
        assert receipts[0].covers(phase="phase1_canary", model_key=model_key, now=NOW)


def test_a_receipt_below_the_required_budget_is_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "small.json", _receipt(max_usd=10.0))
    receipts = _load(tmp_path)
    assert (
        select_authorization(
            receipts,
            phase="phase1_canary",
            model_key="paddleocr_vl_1_6",
            now=NOW,
            required_usd=10.01,
        )
        is None
    )
    assert (
        select_authorization(
            receipts,
            phase="phase1_canary",
            model_key="paddleocr_vl_1_6",
            now=NOW,
            required_usd=10.0,
        )
        is not None
    )


def test_the_largest_budget_wins(tmp_path: Path) -> None:
    _write(tmp_path, "a-small.json", _receipt(max_usd=25.0))
    _write(tmp_path, "b-large.json", _receipt(max_usd=250.0))
    _write(tmp_path, "c-medium.json", _receipt(max_usd=80.0))
    chosen = select_authorization(
        _load(tmp_path),
        phase="phase1_canary",
        model_key="paddleocr_vl_1_6",
        now=NOW,
        required_usd=10.0,
    )
    assert chosen is not None
    assert chosen.max_usd == 250.0


def test_a_receipt_for_another_phase_is_excluded(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    assert (
        select_authorization(
            _load(tmp_path),
            phase="phase2_full_run",
            model_key="paddleocr_vl_1_6",
            now=NOW,
            required_usd=1.0,
        )
        is None
    )


def test_an_unknown_phase_raises(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    receipts = _load(tmp_path)
    with pytest.raises(AuthorizationError, match="unknown phase"):
        receipts[0].covers(phase="phase0_free_lunch", model_key=None, now=NOW)


def test_a_negative_required_amount_raises(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    with pytest.raises(AuthorizationError, match="required_usd"):
        select_authorization(
            _load(tmp_path),
            phase="phase1_canary",
            model_key=None,
            now=NOW,
            required_usd=-1.0,
        )


def test_a_naive_now_raises(tmp_path: Path) -> None:
    _write(tmp_path, "canary.json", _receipt())
    receipts = _load(tmp_path)
    with pytest.raises(AuthorizationError, match="timezone-aware"):
        receipts[0].covers(
            phase="phase1_canary",
            model_key=None,
            now=datetime(2026, 9, 3, 12, 0, 0),
        )


# --------------------------------------------------------------------------
# the receipt is a campaign record like any other
# --------------------------------------------------------------------------


def test_the_receipt_validates_against_the_registered_schema(tmp_path: Path) -> None:
    from arena.core.receipts import AuthorizationReceiptRecord, validate

    record = _receipt()
    validate(record, "authorization-receipt")
    parsed = AuthorizationReceiptRecord.model_validate(record)
    assert parsed.to_record() == {**record, "notes": None}
