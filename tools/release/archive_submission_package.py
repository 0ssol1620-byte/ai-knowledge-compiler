#!/usr/bin/env python3
"""Zip the hand-over package, test the archive, and hash it.

Three steps, and the middle one is the point. A zip that was written without
error is not a zip that extracts: `ZipFile.testzip()` reads every member and
checks its CRC, and the extraction check below unpacks the whole archive to a
temporary directory and compares it against the package's own hash manifest.
The archive is the artifact that actually travels, so it is the one whose
contents must be proven rather than assumed.

The digest goes in a separate `.sha256` file. A checksum inside the archive it
describes cannot be used to detect that the archive was altered.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "submission" / "TAVONEL_FINAL_SUBMISSION_PACKAGE_2026-08-20"
ARCHIVE = PACKAGE.with_suffix(".zip")
DIGEST = Path(str(ARCHIVE) + ".sha256")
RECEIPT = ROOT / "docs" / "ip" / "receipts" / "submission-archive-2026-08-20.json"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_archive() -> list[str]:
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    names: list[str] = []
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(PACKAGE.rglob("*")):
            if not path.is_file():
                continue
            arc = f"{PACKAGE.name}/{path.relative_to(PACKAGE).as_posix()}"
            zf.write(path, arc)
            names.append(arc)
    return names


def test_archive(names: list[str]) -> list[str]:
    """Open, CRC-test, extract, and verify the extracted tree against the manifest."""
    problems: list[str] = []
    with zipfile.ZipFile(ARCHIVE) as zf:
        broken = zf.testzip()
        if broken is not None:
            problems.append(f"CRC failure on {broken}")
        listed = sorted(i.filename for i in zf.infolist() if not i.is_dir())
        if listed != sorted(names):
            problems.append(
                f"archive contents differ from what was written: "
                f"{len(listed)} entries vs {len(names)}")

        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            extracted = Path(tmp) / PACKAGE.name
            manifest = extracted / "HASH_MANIFEST.sha256"
            if not manifest.is_file():
                problems.append("extracted archive has no hash manifest")
                return problems
            ok = 0
            for line in manifest.read_text(encoding="utf-8").splitlines():
                digest, _, rel = line.partition("  ")
                target = extracted / rel
                if not target.is_file():
                    problems.append(f"extracted archive is missing {rel}")
                elif sha(target) != digest:
                    problems.append(f"extracted archive fails its own hash for {rel}")
                else:
                    ok += 1
            print(f"extracted and verified: {ok} files against the package manifest")
    return problems


def main() -> int:
    if not PACKAGE.is_dir():
        print(f"no package at {PACKAGE}")
        return 1

    names = build_archive()
    problems = test_archive(names)

    digest = sha(ARCHIVE)
    # `sha256sum -c` format, LF only, so the standard tool can check it.
    with DIGEST.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"{digest}  {ARCHIVE.name}\n")

    receipt: dict[str, Any] = {
        "schema": "tavonel.submission-archive.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "archive": ARCHIVE.name,
        "archive_bytes": ARCHIVE.stat().st_size,
        "archive_sha256": digest,
        "digest_file": DIGEST.name,
        "entries": len(names),
        "archive_test": "PASS" if not problems else "FAIL",
        "problems": problems,
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")

    print(f"archive: {ARCHIVE.relative_to(ROOT).as_posix()}")
    print(f"entries: {len(names)}")
    print(f"bytes:   {ARCHIVE.stat().st_size:,}")
    print(f"sha256:  {digest}")
    print(f"digest file: {DIGEST.relative_to(ROOT).as_posix()}")
    print(f"archive test: {'PASS' if not problems else 'FAIL'}")
    for p in problems:
        print(f"  - {p}")
    return 1 if problems else 0


def control() -> int:
    """Corrupt a copy of the archive and confirm the test refuses it."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / ARCHIVE.name
        shutil.copy2(ARCHIVE, copy)
        raw = bytearray(copy.read_bytes())
        raw[len(raw) // 2] ^= 0xFF
        copy.write_bytes(raw)
        try:
            with zipfile.ZipFile(copy) as zf:
                broken = zf.testzip()
            fired = broken is not None
        except zipfile.BadZipFile:
            fired = True
    print(f"control - a flipped byte is rejected by the archive test: {fired}")
    return 0 if fired else 1


if __name__ == "__main__":
    sys.exit(control() if "--control" in sys.argv else main())
