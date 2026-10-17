"""Run-time refusal for a vendor price and terms snapshot (COMPETITOR-PROTOCOL §7 AT-3).

    python -m research.vendor_comparison_20261017.snapshots.validate --receipts-root ROOT \
        [--fd1-receipt FD1.json] [--now 2026-10-20T00:00:00Z] [--vendor reducto ...]

``ROOT`` is the directory that holds ``competitor-protocol-receipts/``. ``check`` returns every
reason a snapshot cannot back a vendor run, grouped; a snapshot passes only when all are empty:

``fd1``
    The founder's FD-1 receipt exists, records ``"decision": "FD-1"``, is not SYNTHETIC, and its
    ``terms_sha256[vendor]`` equals the snapshot's terms page sha256. Terms that changed after
    FD-1 need a new FD-1, so a different sha256 refuses; no FD-1 receipt refuses.
``binding``
    The manifest file hashes to the sha256 the snapshot recorded; every quoted row is a row of
    that manifest (file, url, sha256, ``fetched_at`` = ``downloaded_utc``); every saved page
    still hashes to it; every ``quoted_text`` occurs in the page's text.
``freshness``
    Every bound page was fetched at most 7 days before ``now`` (VENDOR-COMPARISON-PREREG
    ``fixed_conditions.time_window_days``) and not after it.

``now`` is an argument: only ``main`` reads the wall clock. Arm approval and the FD-2 spend cap
are checked by ``run.py``'s execute gate, not here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from .price_snapshot_schema import PriceSnapshot, SnapshotError, load_all, parse_utc

MAX_AGE = timedelta(days=7)
EXIT_OK, EXIT_REFUSED = 0, 3

_ENTITIES = (
    (r"&nbsp;", " "),
    (r"&amp;", "&"),
    (r"&#x27;|&#39;|&rsquo;", "'"),
    (r"&quot;|&ldquo;|&rdquo;", '"'),
    (r"&lt;", "<"),
    (r"&gt;", ">"),
)


def page_text(raw: bytes) -> str:
    """``competitor-protocol-receipts/html2txt.js`` in Python: the manifest's reading method."""
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|h[1-6]|tr|section)>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in _ENTITIES:
        text = re.sub(entity, char, text)
    lines = (re.sub(r"\s+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fd1_problems(snapshot: PriceSnapshot, fd1_receipt: Path | None) -> list[str]:
    if fd1_receipt is None:
        return ["FD-1 receipt absent: none was given"]
    if not fd1_receipt.is_file():
        return [f"FD-1 receipt absent: {fd1_receipt} does not exist"]
    try:
        data = json.loads(fd1_receipt.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"FD-1 receipt is not readable JSON: {exc}"]
    if not isinstance(data, dict) or data.get("decision") != "FD-1":
        return [f"{fd1_receipt.name} does not record decision FD-1"]
    if (
        fd1_receipt.name.upper().startswith("SYNTHETIC")
        or "SYNTHETIC" in str(data.get("label", "")).upper()
    ):
        return [f"{fd1_receipt.name} is SYNTHETIC, not a founder decision"]
    recorded = data.get("terms_sha256")
    sha = recorded.get(snapshot.vendor) if isinstance(recorded, dict) else None
    if not isinstance(sha, str) or not sha:
        return [f"FD-1 receipt records no terms_sha256 for {snapshot.vendor}"]
    if sha != snapshot.terms.sha256:
        return [
            f"terms changed since FD-1: {snapshot.terms.file} is {snapshot.terms.sha256}, "
            f"FD-1 recorded {sha}; a new FD-1 decision is required"
        ]
    return []


def binding_problems(snapshot: PriceSnapshot, receipts_root: Path) -> list[str]:
    manifest_path = receipts_root / snapshot.manifest_file
    if not manifest_path.is_file():
        return [f"manifest absent: {manifest_path}"]
    raw = manifest_path.read_bytes()
    if _sha256(raw) != snapshot.manifest_sha256:
        return [f"manifest sha256 is {_sha256(raw)}, snapshot recorded {snapshot.manifest_sha256}"]
    base = PurePosixPath(snapshot.manifest_file).parent
    manifest: dict[str, Any] = {str(base / row["file"]): row for row in json.loads(raw)["rows"]}
    problems: list[str] = []
    texts: dict[str, str] = {}
    for receipt in snapshot.receipts:
        row = manifest.get(receipt.file)
        if row is None:
            problems.append(f"{receipt.file}: not a row of {snapshot.manifest_file}")
            continue
        for key, ours in (("url", receipt.url), ("sha256", receipt.sha256)):
            if row.get(key) != ours:
                problems.append(f"{receipt.file}: {key} {ours!r}, manifest has {row.get(key)!r}")
        try:
            downloaded = parse_utc(row.get("downloaded_utc"), "downloaded_utc")
        except SnapshotError as exc:
            problems.append(f"{receipt.file}: manifest {exc}")
        else:
            if downloaded != receipt.fetched_at:
                problems.append(
                    f"{receipt.file}: fetched_at {receipt.fetched_at.isoformat()}, "
                    f"manifest downloaded_utc {row.get('downloaded_utc')}"
                )
        if receipt.file not in texts:
            page = receipts_root / receipt.file
            if not page.is_file():
                problems.append(f"{receipt.file}: saved page absent")
                continue
            body = page.read_bytes()
            if _sha256(body) != receipt.sha256:
                problems.append(f"{receipt.file}: saved bytes hash to {_sha256(body)}")
                continue
            texts[receipt.file] = page_text(body)
        if receipt.quoted_text not in texts[receipt.file]:
            problems.append(f"{receipt.file}: quoted_text not found: {receipt.quoted_text!r}")
    return problems


def freshness_problems(snapshot: PriceSnapshot, now: datetime) -> list[str]:
    if now.tzinfo is None:
        raise ValueError("now must name its UTC offset")
    problems: list[str] = []
    age = now - snapshot.captured_at
    if age > MAX_AGE:
        problems.append(
            f"stale: oldest page fetched {snapshot.captured_at.isoformat()} is {age} old at "
            f"{now.isoformat()} (limit {MAX_AGE.days} days); re-fetch every page and rebuild"
        )
    newest = max(receipt.fetched_at for receipt in snapshot.receipts)
    if newest > now:
        problems.append(
            f"fetched_at {newest.isoformat()} is after now {now.isoformat()}: "
            "the clock or the receipt is wrong"
        )
    return problems


def check(
    snapshot: PriceSnapshot, *, now: datetime, fd1_receipt: Path | None, receipts_root: Path
) -> dict[str, list[str]]:
    return {
        "fd1": fd1_problems(snapshot, fd1_receipt),
        "binding": binding_problems(snapshot, receipts_root),
        "freshness": freshness_problems(snapshot, now),
    }


def main(argv: Sequence[str] | None = None) -> int:
    snapshots = load_all()
    parser = argparse.ArgumentParser(description="Refuse a stale or unbound price snapshot.")
    parser.add_argument("--receipts-root", type=Path, required=True)
    parser.add_argument("--fd1-receipt", type=Path)
    parser.add_argument("--now", help="ISO-8601 time with offset (default: the wall clock)")
    parser.add_argument("--vendor", action="append", choices=sorted(snapshots))
    args = parser.parse_args(argv)
    now = datetime.now(UTC) if args.now is None else parse_utc(args.now, "--now")
    results = []
    for vendor in args.vendor or sorted(snapshots):
        snapshot = snapshots[vendor]
        problems = check(
            snapshot, now=now, fd1_receipt=args.fd1_receipt, receipts_root=args.receipts_root
        )
        results.append(
            {
                "vendor": vendor,
                "arm_id": snapshot.arm_id,
                "price_point": snapshot.price_point,
                "snapshot_sha256": snapshot.snapshot_sha256,
                "captured_at": snapshot.captured_at.isoformat(),
                "terms_sha256": snapshot.terms.sha256,
                "verdict": "REFUSED" if any(problems.values()) else "PASS",
                "problems": problems,
            }
        )
    report = {
        "schema": "tavonel.vendor_comparison.snapshot_check.v1",
        "now": now.isoformat(),
        "max_age_days": MAX_AGE.days,
        "fd1_receipt": None if args.fd1_receipt is None else str(args.fd1_receipt),
        "vendor_calls": 0,
        "results": results,
    }
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return EXIT_REFUSED if any(r["verdict"] == "REFUSED" for r in results) else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
