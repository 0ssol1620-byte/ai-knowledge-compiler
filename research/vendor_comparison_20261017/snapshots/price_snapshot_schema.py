"""Schema of ``<vendor>.price_snapshot.json`` (COMPETITOR-PROTOCOL §2.1-2.2, §7 AT-3).

Field names follow the Model Arena snapshot
``research/model_arena_20260903/arena/opus/price_snapshot.json`` (``schema``, ``currency``,
``captured_at``, ``source``, ``quoted_text``, ``unit``, ``prices``, ``warnings``). Every quoted
row additionally binds one row of ``competitor-protocol-receipts/WEB-RECEIPTS-MANIFEST.json``:
``file``, ``url``, ``sha256`` and ``fetched_at`` (the manifest's ``downloaded_utc``).

A price row carries the number exactly as the vendor page states it (``value`` in ``unit``);
a conversion such as "$1 buys 100 credits" -> USD per credit happens in code, never in the file.
``captured_at`` must equal the oldest ``fetched_at`` in the file, so freshness cannot be
overstated. Loading checks shape only; binding to the saved bytes, freshness and FD-1 are
``validate``'s job.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA = "tavonel.vendor_comparison.price_snapshot.v1"
SNAPSHOT_DIR = Path(__file__).parent
SUFFIX = ".price_snapshot.json"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class SnapshotError(ValueError):
    """The file is not a well-formed price snapshot."""


@dataclass(frozen=True)
class Receipt:
    """One quoted sentence and the WEB-RECEIPTS-MANIFEST row of the page it was read from."""

    file: str  # relative to the receipts root, e.g. competitor-protocol-receipts/web/x.html
    url: str
    sha256: str
    fetched_at: datetime
    quoted_text: str


@dataclass(frozen=True)
class PriceRow:
    name: str
    value: Decimal
    unit: str
    receipt: Receipt


@dataclass(frozen=True)
class PriceSnapshot:
    vendor: str
    arm_id: str
    price_point: str
    currency: str
    captured_at: datetime
    manifest_file: str
    manifest_sha256: str
    prices: tuple[PriceRow, ...]
    conditions: tuple[Receipt, ...]  # quoted facts that fix the price point but carry no number
    terms: Receipt
    snapshot_sha256: str  # sha256 of the snapshot file's bytes

    @property
    def receipts(self) -> tuple[Receipt, ...]:
        return (*(row.receipt for row in self.prices), *self.conditions, self.terms)

    def price(self, name: str) -> Decimal:
        for row in self.prices:
            if row.name == name:
                return row.value
        raise KeyError(f"{self.vendor}: no price row {name!r}")


def _text(data: Mapping[str, Any], key: str, where: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SnapshotError(f"{where}: '{key}' must be a non-empty string")
    return value


def _sha256(data: Mapping[str, Any], key: str, where: str) -> str:
    value = _text(data, key, where)
    if not _SHA256.fullmatch(value):
        raise SnapshotError(f"{where}: '{key}' is not a lowercase hex sha256")
    return value


def parse_utc(value: object, where: str) -> datetime:
    """An ISO-8601 timestamp that names its offset; a naive time is refused, not assumed UTC."""
    if not isinstance(value, str):
        raise SnapshotError(f"{where}: timestamp must be a string")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise SnapshotError(f"{where}: {value!r} is not ISO-8601") from exc
    if moment.tzinfo is None:
        raise SnapshotError(f"{where}: {value!r} has no UTC offset")
    return moment


def _object(data: object, where: str) -> Mapping[str, Any]:
    if not isinstance(data, dict):
        raise SnapshotError(f"{where}: must be an object")
    return data


def _receipt(data: Mapping[str, Any], where: str) -> Receipt:
    return Receipt(
        file=_text(data, "file", where),
        url=_text(data, "url", where),
        sha256=_sha256(data, "sha256", where),
        fetched_at=parse_utc(data.get("fetched_at"), f"{where}.fetched_at"),
        quoted_text=_text(data, "quoted_text", where),
    )


def _price(data: Mapping[str, Any], where: str) -> PriceRow:
    value = data.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise SnapshotError(f"{where}: 'value' must be a positive number, as quoted")
    return PriceRow(
        name=_text(data, "name", where),
        value=Decimal(str(value)),
        unit=_text(data, "unit", where),
        receipt=_receipt(data, where),
    )


def _rows(data: Mapping[str, Any], key: str, where: str) -> list[Mapping[str, Any]]:
    rows = data.get(key)
    if not isinstance(rows, list):
        raise SnapshotError(f"{where}: '{key}' must be a list")
    return [_object(row, f"{where}.{key}[{i}]") for i, row in enumerate(rows)]


def load(path: Path) -> PriceSnapshot:
    raw = path.read_bytes()
    where = path.name
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise SnapshotError(f"{where}: not JSON ({exc})") from exc
    data = _object(parsed, where)
    if data.get("schema") != SCHEMA:
        raise SnapshotError(f"{where}: schema is not {SCHEMA}")
    prices = tuple(
        _price(row, f"{where}.prices[{i}]") for i, row in enumerate(_rows(data, "prices", where))
    )
    if not prices:
        raise SnapshotError(f"{where}: 'prices' is empty")
    if len({row.name for row in prices}) != len(prices):
        raise SnapshotError(f"{where}: price names repeat")
    manifest = _object(data.get("manifest"), f"{where}.manifest")
    snapshot = PriceSnapshot(
        vendor=_text(data, "vendor", where),
        arm_id=_text(data, "arm_id", where),
        price_point=_text(data, "price_point", where),
        currency=_text(data, "currency", where),
        captured_at=parse_utc(data.get("captured_at"), f"{where}.captured_at"),
        manifest_file=_text(manifest, "file", f"{where}.manifest"),
        manifest_sha256=_sha256(manifest, "sha256", f"{where}.manifest"),
        prices=prices,
        conditions=tuple(
            _receipt(row, f"{where}.conditions[{i}]")
            for i, row in enumerate(_rows(data, "conditions", where))
        ),
        terms=_receipt(_object(data.get("terms"), f"{where}.terms"), f"{where}.terms"),
        snapshot_sha256=hashlib.sha256(raw).hexdigest(),
    )
    oldest = min(receipt.fetched_at for receipt in snapshot.receipts)
    if snapshot.captured_at != oldest:
        raise SnapshotError(
            f"{where}: captured_at {snapshot.captured_at.isoformat()} is not the oldest "
            f"fetched_at {oldest.isoformat()}"
        )
    return snapshot


def load_all(directory: Path = SNAPSHOT_DIR) -> dict[str, PriceSnapshot]:
    """Every ``<vendor>.price_snapshot.json`` in ``directory``, keyed by vendor."""
    out: dict[str, PriceSnapshot] = {}
    for path in sorted(directory.glob("*" + SUFFIX)):
        snapshot = load(path)
        if path.name != snapshot.vendor + SUFFIX:
            raise SnapshotError(f"{path.name}: names vendor {snapshot.vendor!r}")
        out[snapshot.vendor] = snapshot
    return out
