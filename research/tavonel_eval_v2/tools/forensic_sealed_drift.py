#!/usr/bin/env python3
"""INC-V2-001 provenance forensic. Read-only.

Answers one question per drifted binding: can the bytes the receipt pinned be
found anywhere, and does the evidence say the change was an intentional
amendment or an accidental modification?

Nothing here re-seals, repairs, restores or writes a superseding receipt. It
writes one file, its own findings receipt, and reads everything else.

Sources searched, in the order a recovery would prefer them:

1. the git object database, including objects no branch reaches, since a blob
   survives there after the working tree has moved on;
2. archive files in the tree (the submission ZIP and the benchmark review ZIP);
3. backup and shadow directories left by tooling;
4. every other file in the working tree, in case the original bytes still exist
   under a different name.

Classification is evidence-led. "Intentional amendment" is only claimed when
something in the repository records the change; otherwise the finding is stated
as unexplained, and an artifact whose pinned bytes cannot be found anywhere is
placed in evidence quarantine rather than described as recoverable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    NS,
    ROOT,
    canonical_sha,
    git,
    now,
    rel,
    sha_bytes,
    sha_file,
    write_hashed,
)

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".next", ".mypy_cache"}
#: Files larger than this are not hashed. Recorded, never skipped silently.
SIZE_CAP_BYTES = 256 * 1024 * 1024
# Any single member read into one buffer is capped far lower; the bytes being
# looked for are receipts and manifests, none of which approach this.
STREAM_CAP_BYTES = 64 * 1024 * 1024
GIT_SKIPPED: list[dict[str, int]] = []
NEWLINE = b"\n"
WORKTREE_SKIPPED: list[str] = []
#: Receipts whose own declared digest does not recompute. Recovery here means
#: finding a byte sequence that both parses and self-verifies.
SELF_HASH_SUSPECTS = (
    "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-dev-2026-08-19.json",
    "research/experiments/H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v8-holdout.json",
)


def git_blobs() -> dict[str, list[str]]:
    """sha256 of every blob in the object database -> git object ids.

    Streamed. An earlier version bought the whole object store into one bytes
    object and exhausted memory on this repository; the index it was building is
    small, but the buffer it built it from was not.
    """
    listing = subprocess.run(
        [
            "git",
            "cat-file",
            "--batch-all-objects",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ids: list[str] = []
    oversized = 0
    for line in listing.stdout.splitlines():
        parts = line.split()
        if len(parts) != 3 or parts[1] != "blob":
            continue
        if int(parts[2]) > STREAM_CAP_BYTES:
            oversized += 1
            continue
        ids.append(parts[0])
    GIT_SKIPPED.append({"oversized_blobs": oversized, "cap_bytes": STREAM_CAP_BYTES})
    if not ids:
        return {}

    index: dict[str, list[str]] = {}
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    assert process.stdin and process.stdout

    def feed() -> None:
        try:
            for object_id in ids:
                process.stdin.write(object_id.encode() + NEWLINE)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    writer = threading.Thread(target=feed, daemon=True)
    writer.start()

    out = process.stdout
    while True:
        header = out.readline()
        if not header:
            break
        parts = header.decode(errors="replace").split()
        if len(parts) < 3:
            continue
        object_id, size = parts[0], int(parts[2])
        digest = hashlib.sha256()
        remaining = size
        while remaining:
            block = out.read(min(remaining, 1 << 20))
            if not block:
                break
            digest.update(block)
            remaining -= len(block)
        out.read(1)  # trailing newline
        index.setdefault("sha256:" + digest.hexdigest(), []).append(object_id)
    writer.join(timeout=5)
    process.wait(timeout=30)
    return index


def archive_entries() -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for archive in sorted(ROOT.rglob("*.zip")):
        if any(part in SKIP_DIRS for part in archive.parts):
            continue
        try:
            with zipfile.ZipFile(archive) as bundle:
                for entry in bundle.infolist():
                    if entry.is_dir() or entry.file_size > STREAM_CAP_BYTES:
                        continue
                    # streamed, not bundle.read(): a single compressed member can
                    # expand far beyond what one buffer can hold
                    digest = hashlib.sha256()
                    with bundle.open(entry) as member:
                        for block in iter(lambda: member.read(1 << 20), b""):
                            digest.update(block)
                    index.setdefault("sha256:" + digest.hexdigest(), []).append(
                        rel(archive) + "!" + entry.filename
                    )
        except (zipfile.BadZipFile, OSError):
            continue
    return index


def worktree_files() -> dict[str, list[str]]:
    # os.walk with the skip list applied to dirnames, so a pruned directory is
    # never descended into. Path.rglob has no way to prune, and on this tree it
    # spends its time inside dependency directories that cannot hold the bytes
    # being looked for.
    index: dict[str, list[str]] = {}
    skipped: list[str] = []
    for parent, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for name in filenames:
            path = Path(parent) / name
            try:
                if path.stat().st_size > SIZE_CAP_BYTES:
                    # Hashed nothing, so say so. The largest byte sequence being
                    # looked for is a few megabytes, but a silent skip would
                    # still read as "searched and not found".
                    skipped.append(rel(path))
                    continue
                index.setdefault(sha_file(path), []).append(rel(path))
            except (OSError, ValueError):
                continue
    WORKTREE_SKIPPED.extend(sorted(skipped))
    return index


def amendment_evidence(target: str) -> dict[str, Any]:
    """Does anything in the repository record why this file changed?"""
    name = Path(target).name
    stem = name.rsplit(".", 1)[0]
    siblings = sorted(
        rel(path)
        for path in (ROOT / target).parent.glob("*")
        if path.is_file() and path.name != name and stem.split("-")[0] in path.name
    )
    amendment_like = [
        path
        for path in siblings
        if any(token in Path(path).name.lower() for token in ("amend", "supersed", "v2", "revised"))
    ]
    log = git("log", "--oneline", "-5", "--", target)
    return {
        "sibling_files": siblings[:12],
        "amendment_named_sibling": amendment_like,
        "tracked_in_git": bool(git("ls-files", "--", target)),
        "git_log_tail": log.splitlines()[:5],
    }


def classify(recovered: bool, evidence: dict[str, Any], generated: bool) -> tuple[str, str]:
    if not recovered:
        return (
            "EVIDENCE_QUARANTINE",
            "the pinned bytes were not found in the object database, in any archive, "
            "in any backup directory, or anywhere in the working tree. The binding "
            "cannot be re-established from what this machine holds.",
        )
    if evidence["amendment_named_sibling"]:
        return (
            "INTENTIONAL_AMENDMENT_UNRECORDED",
            "a sibling file names an amendment, so the change was probably deliberate, "
            "but no receipt binds the current bytes, so the amendment was never sealed.",
        )
    if generated:
        return (
            "ACCIDENTAL_REGENERATION",
            "the file is a tool output. The pinned bytes exist, and nothing records a "
            "decision to change them, so the most consistent reading is that the "
            "generator was re-run after the receipt was written.",
        )
    return (
        "ACCIDENTAL_MODIFICATION",
        "the pinned bytes exist and nothing in the repository records a reason for the change.",
    )


def is_generated(target: str, body: bytes | None) -> bool:
    if body is None:
        return False
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if not isinstance(document, dict):
        return False
    return any(key in document for key in ("generated_at", "schema", "produced_at", "verified_at"))


def self_hash_recovery(index: dict[str, dict[str, list[str]]]) -> list[dict[str, Any]]:
    """For the two receipts whose declared digest fails, look for a version that verifies."""
    findings: list[dict[str, Any]] = []
    for target in SELF_HASH_SUSPECTS:
        path = ROOT / target
        current = path.read_bytes() if path.is_file() else b""
        declared = None
        try:
            document = json.loads(current.decode("utf-8"))
            declared = document.get("receipt_sha256")
        except (UnicodeDecodeError, json.JSONDecodeError):
            document = None
        recovered_from: list[str] = []
        if declared:
            for source, mapping in index.items():
                for digest, locations in mapping.items():
                    if digest == declared:
                        recovered_from.extend(source + ":" + item for item in locations)
        findings.append(
            {
                "path": target,
                "declared_receipt_sha256": declared,
                "current_file_sha256": sha_bytes(current) if current else None,
                "a_version_whose_bytes_equal_the_declared_digest_exists": bool(recovered_from),
                "found_at": recovered_from[:10],
                "note": (
                    "The declared value is a canonical digest over the document, not over "
                    "the file bytes, so a byte match is not expected. Its absence is "
                    "reported rather than treated as proof either way; what is established "
                    "is only that the declared digest does not recompute over the document "
                    "now on disk."
                ),
                "state": "UNRESOLVED_ENCODING_OR_DRIFT",
            }
        )
    return findings


def run(verification: Path, output: Path) -> int:
    report = json.loads(verification.read_text(encoding="utf-8"))
    drifts = report["unexplained_drift"]

    index = {
        "git_object_database": git_blobs(),
        "archive": archive_entries(),
        "worktree": worktree_files(),
    }
    counts = {name: len(mapping) for name, mapping in index.items()}

    findings: list[dict[str, Any]] = []
    for row in drifts:
        target = row["resolved"]
        pinned = row["expected"]
        locations: list[str] = []
        recovered_bytes: bytes | None = None
        for source, mapping in index.items():
            for where in mapping.get(pinned, ()):
                locations.append(source + ":" + where)
        if index["git_object_database"].get(pinned):
            object_id = index["git_object_database"][pinned][0]
            blob = subprocess.run(
                ["git", "cat-file", "blob", object_id],
                cwd=ROOT,
                capture_output=True,
                check=False,
            )
            recovered_bytes = blob.stdout
        evidence = amendment_evidence(target)
        generated = is_generated(
            target, (ROOT / target).read_bytes() if (ROOT / target).is_file() else None
        )
        state, reason = classify(bool(locations), evidence, generated)
        findings.append(
            {
                "path": target,
                "pinned_by": row["receipt"],
                "pinned_sha256": pinned,
                "current_sha256": row["worktree"],
                "recovered": bool(locations),
                "recovered_from": locations[:10],
                "recovered_bytes_available": recovered_bytes is not None,
                "looks_generated": generated,
                "amendment_evidence": evidence,
                "classification": state,
                "reason": reason,
                "action_taken": "NONE — read-only forensic",
            }
        )

    quarantined = [item for item in findings if item["classification"] == "EVIDENCE_QUARANTINE"]
    body: dict[str, Any] = {
        "schema": "tavonel.v2.inc_v2_001_provenance_forensic.v1",
        "incident": "INC-V2-001",
        "generated_at": now(),
        "git_head": git("rev-parse", "HEAD"),
        "read_only": True,
        "nothing_re_sealed": True,
        "nothing_restored": True,
        "no_superseding_receipt_written": True,
        "input_receipt": rel(verification),
        "input_receipt_sha256": sha_bytes(verification.read_bytes()),
        "sources_searched": {
            "git_object_database": "every blob reachable or not, via git cat-file --batch-all-objects",
            "archive": "every .zip in the working tree",
            "worktree": "every file in the working tree outside " + ", ".join(sorted(SKIP_DIRS)),
        },
        "distinct_digests_indexed": counts,
        "worktree_files_too_large_to_hash": WORKTREE_SKIPPED,
        "drift_count": len(findings),
        "recovered_count": sum(1 for item in findings if item["recovered"]),
        "quarantined_count": len(quarantined),
        "quarantine": [item["path"] for item in quarantined],
        "findings": findings,
        "self_hash_findings": self_hash_recovery(index),
        "gpu_seconds": 0,
        "external_gpu_cost_usd": 0.0,
    }
    body["findings_sha256"] = canonical_sha(findings)
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {
                "drift": len(findings),
                "recovered": body["recovered_count"],
                "quarantined": body["quarantined_count"],
                "receipt": rel(output),
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--verification",
        type=Path,
        default=NS / "receipts" / "p0-sealed-evidence-verification.json",
    )
    parser.add_argument(
        "--output", type=Path, default=NS / "receipts" / "inc-v2-001-provenance-forensic.json"
    )
    args = parser.parse_args()
    return run(args.verification, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
