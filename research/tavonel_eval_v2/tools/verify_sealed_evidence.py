#!/usr/bin/env python3
"""P0 step 1 -- verify pre-existing sealed evidence without touching it.

Read-only by construction: the only file this script writes is its own receipt
under ``research/tavonel_eval_v2/receipts/``. It never opens a sealed file for
writing and never calls git in a mode that mutates the working tree.

Three independent checks per sealed receipt:

1. self-hash   -- the receipt's own digest field recomputed over the remaining
                  keys, using the canonical encoding the sealing scripts used.
2. bindings    -- every (path, sha256) binding the receipt carries, resolved
                  against the current working tree.
3. head drift  -- for a binding whose bytes differ from the working tree, whether
                  the *committed* bytes at HEAD match instead. This separates
                  "the sealed evidence is corrupt" from "the sealed evidence is
                  reproducible from HEAD but the working tree has moved on",
                  which are different findings with different consequences.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    NS,
    ROOT,
    canonical_sha,
    git_head,
    now,
    rel,
    sha_bytes,
    sha_file,
    worktree_dirty_paths,
    write_hashed,
)

SHA_PREFIX = "sha256:"


def sealed_receipt_files() -> list[Path]:
    """The sealed corpus this project must never rewrite."""
    found: list[Path] = []
    found.extend(sorted((ROOT / "docs" / "evidence").glob("*.json")))
    found.extend(sorted((ROOT / "docs" / "ip" / "receipts").glob("*.json")))
    exp = ROOT / "research" / "experiments"
    if exp.is_dir():
        found.extend(sorted(exp.glob("*/receipts/*.json")))
        found.extend(sorted(exp.glob("*/manifest.json")))
        found.extend(sorted(exp.glob("*/*/*manifest*.json")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in found:
        resolved = path.resolve()
        if resolved not in seen and resolved.is_file():
            seen.add(resolved)
            unique.append(resolved)
    return unique


def is_sha(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(SHA_PREFIX) and len(value) == 71


def looks_like_path(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and "\n" not in value
        and ("/" in value or value.endswith((".py", ".json", ".md", ".yaml", ".yml")))
    )


def bindings_in(node: Any, trail: str = "") -> Iterator[tuple[str, str, str]]:
    """Yield (json_pointer, repo_relative_path, expected_sha256)."""
    if isinstance(node, dict):
        for key, value in node.items():
            here = trail + "/" + key
            if (
                isinstance(value, dict)
                and value
                and all(is_sha(item) for item in value.values())
                and all(looks_like_path(name) for name in value)
            ):
                for name, digest in value.items():
                    yield here + "/" + name, name, digest
                continue
            if is_sha(value) and key.endswith("sha256"):
                stem = key[: -len("sha256")]
                # A receipt may carry two digests for the same neighbour: the
                # canonical digest of the referenced *document* and the digest
                # of its *bytes on disk*. Only the second binds to a file, so
                # when both are present the document digest is not a binding.
                if stem + "file_sha256" in node:
                    yield from bindings_in(value, here)
                    continue
                for candidate in (stem + "path", stem.rstrip("_"), stem + "file"):
                    sibling = node.get(candidate)
                    if looks_like_path(sibling):
                        yield here, sibling, value
                        break
            yield from bindings_in(value, here)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from bindings_in(item, trail + "/" + str(index))


#: Field names the sealing scripts in this repository use for a receipt's own
#: digest. A ``*_sha256`` key outside this set is a reference to some other
#: artifact, not a self-hash, and a receipt carrying only such keys has simply
#: not declared one -- which is NOT_APPLICABLE, not a failure.
SELF_HASH_FIELDS = (
    "receipt_sha256",
    "seal_sha256",
    "manifest_sha256",
    "self_sha256",
    "document_sha256",
    "record_sha256",
)


def self_hash_result(document: dict[str, Any]) -> dict[str, Any]:
    declared = [key for key in SELF_HASH_FIELDS if is_sha(document.get(key))]
    for key in declared:
        bare = {name: value for name, value in document.items() if name != key}
        if canonical_sha(bare) == document[key]:
            return {"state": "PASS", "field": key}
    if not declared:
        return {"state": "NOT_APPLICABLE", "field": None, "reason": "no self-hash field declared"}
    return {"state": "FAIL", "field": declared[0], "declared": declared}


def is_external(value: str) -> bool:
    """A binding that names something outside this working tree.

    Container-internal absolute paths (``/opt/folynta/...``) and Windows drive
    paths are recorded by runtime-qualification receipts. They are real
    bindings, just not ones a repository checkout can resolve, so they are
    reported in their own bucket rather than counted as corruption.
    """
    return value.startswith("/") or (len(value) > 1 and value[1] == ":")


def anchor_dirs(receipt: Path) -> list[Path]:
    """Directories a receipt's relative bindings may be written against."""
    dirs = [ROOT, receipt.parent, receipt.parent.parent]
    try:
        parts = receipt.resolve().relative_to(ROOT).parts
    except ValueError:
        parts = ()
    if len(parts) >= 3 and parts[0] == "research" and parts[1] == "experiments":
        experiment = ROOT / parts[0] / parts[1] / parts[2]
        dirs.extend([experiment, experiment / "scripts"])
    unique: list[Path] = []
    for item in dirs:
        if item.is_dir() and item not in unique:
            unique.append(item)
    return unique


def resolve_binding(value: str, anchors: list[Path]) -> Path | None:
    for anchor in anchors:
        candidate = (anchor / value).resolve()
        if candidate.is_file():
            return candidate
    return None


def head_blob_sha(repo_path: str) -> str | None:
    out = subprocess.run(
        ["git", "show", "HEAD:" + repo_path],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if out.returncode != 0:
        return None
    return sha_bytes(out.stdout)


def verify(output: Path) -> int:
    receipts = sealed_receipt_files()
    per_file: list[dict[str, Any]] = []
    totals = {
        "receipts": 0,
        "self_hash_pass": 0,
        "self_hash_fail": 0,
        "self_hash_not_applicable": 0,
        "bindings": 0,
        "bindings_match": 0,
        "bindings_external": 0,
        "bindings_missing": 0,
        "bindings_mismatch_worktree_head_ok": 0,
        "bindings_superseded": 0,
        "bindings_mismatch_unexplained": 0,
    }
    head_cache: dict[str, str | None] = {}
    bucket = {
        "PASS": "self_hash_pass",
        "FAIL": "self_hash_fail",
        "NOT_APPLICABLE": "self_hash_not_applicable",
    }

    for path in receipts:
        totals["receipts"] += 1
        raw = path.read_bytes()
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            per_file.append(
                {
                    "receipt": rel(path),
                    "receipt_file_sha256": sha_bytes(raw),
                    "parse": "UNREADABLE: " + type(error).__name__,
                }
            )
            continue

        self_hash = (
            self_hash_result(document)
            if isinstance(document, dict)
            else {"state": "NOT_APPLICABLE", "field": None}
        )
        totals[bucket[self_hash["state"]]] += 1

        anchors = anchor_dirs(path)
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for pointer, repo_path, expected in bindings_in(document):
            key = (repo_path, expected)
            if key in seen:
                continue
            seen.add(key)
            totals["bindings"] += 1
            if is_external(repo_path):
                totals["bindings_external"] += 1
                rows.append(
                    {
                        "pointer": pointer,
                        "path": repo_path,
                        "expected": expected,
                        "state": "EXTERNAL_TO_REPOSITORY",
                    }
                )
                continue
            target = resolve_binding(repo_path, anchors)
            if target is None:
                totals["bindings_missing"] += 1
                rows.append(
                    {
                        "pointer": pointer,
                        "path": repo_path,
                        "expected": expected,
                        "state": "MISSING",
                        "searched": [rel(item) for item in anchors],
                    }
                )
                continue
            actual = sha_file(target)
            if actual == expected:
                totals["bindings_match"] += 1
                continue
            tracked_path = rel(target)
            if tracked_path not in head_cache:
                head_cache[tracked_path] = head_blob_sha(tracked_path)
            at_head = head_cache[tracked_path]
            drift = at_head == expected
            state = "WORKTREE_DRIFT_HEAD_MATCHES" if drift else "MISMATCH_UNEXPLAINED"
            totals[
                "bindings_mismatch_worktree_head_ok" if drift else "bindings_mismatch_unexplained"
            ] += 1
            rows.append(
                {
                    "pointer": pointer,
                    "path": repo_path,
                    "resolved": tracked_path,
                    "expected": expected,
                    "worktree": actual,
                    "head": at_head,
                    "tracked_at_head": at_head is not None,
                    "state": state,
                }
            )

        per_file.append(
            {
                "receipt": rel(path),
                "receipt_file_sha256": sha_bytes(raw),
                "self_hash": self_hash,
                "binding_count": len(seen),
                "findings": rows,
            }
        )

    # Second pass. A file whose bytes no longer match one receipt is not
    # automatically corrupt: an amendment supersedes an earlier seal, and the
    # amending receipt binds the *current* bytes. Corruption is the case where
    # no receipt anywhere in scope binds what is on disk now, so nothing
    # records why the bytes changed.
    bound_digests: set[str] = set()
    for path in receipts:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for _, _, digest in bindings_in(document):
            bound_digests.add(digest)

    unexplained: list[dict[str, Any]] = []
    for entry in per_file:
        for row in entry.get("findings", []):
            if row.get("state") != "MISMATCH_UNEXPLAINED":
                continue
            if row.get("worktree") in bound_digests:
                row["state"] = "SUPERSEDED_BY_LATER_RECEIPT"
                row["note"] = (
                    "another receipt in scope binds the current bytes; this receipt "
                    "pins the pre-amendment revision"
                )
                totals["bindings_mismatch_unexplained"] -= 1
                totals["bindings_superseded"] += 1
            else:
                unexplained.append({"receipt": entry["receipt"], **row})

    dirty = worktree_dirty_paths()
    sealed_corrupt = (
        totals["self_hash_fail"] > 0
        or totals["bindings_missing"] > 0
        or totals["bindings_mismatch_unexplained"] > 0
    )

    body: dict[str, Any] = {
        "schema": "tavonel.v2.p0.sealed_evidence_verification.v1",
        "generated_at": now(),
        "git_head": git_head(),
        "worktree_dirty_path_count": len(dirty),
        "worktree_clean": not dirty,
        "scope": [
            "docs/evidence/*.json",
            "docs/ip/receipts/*.json",
            "research/experiments/*/receipts/*.json",
            "research/experiments/*/manifest.json",
            "research/experiments/*/*/*manifest*.json",
        ],
        "totals": totals,
        "sealed_evidence_corrupt": sealed_corrupt,
        "unexplained_drift": unexplained,
        "self_hash_failures": [
            entry["receipt"]
            for entry in per_file
            if entry.get("self_hash", {}).get("state") == "FAIL"
        ],
        "sealed_evidence_reproducible_from_head": totals["bindings_mismatch_unexplained"] == 0,
        "verdict": "FAIL" if sealed_corrupt else "PASS",
        "files": per_file,
        "read_only": True,
        "external_gpu_cost_usd": 0.0,
    }
    write_hashed(output, body, "receipt_sha256")
    print(
        json.dumps(
            {"verdict": body["verdict"], "totals": totals, "receipt": rel(output)},
            sort_keys=True,
        )
    )
    return 0 if body["verdict"] == "PASS" else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=NS / "receipts" / "p0-sealed-evidence-verification.json",
    )
    return verify(parser.parse_args().output)


if __name__ == "__main__":
    raise SystemExit(main())
