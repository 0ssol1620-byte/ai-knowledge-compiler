#!/usr/bin/env python3
"""Bind historical development claims to their actual repository artifacts.

This does not promote historical results to confirmatory evidence.  It only
proves that a Paper 2 development statement points at the exact artifact bytes
that the existing public claims pack already approved and hashed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_PACK = REPO / "docs" / "evidence" / "folynta-public-claims-pack.json"
DEFAULT_REPOSITORY = REPO
DEFAULT_OUTPUT = HERE / "receipts" / "public-development-evidence-binding.json"
SCHEMA = "tavonel.recovery.public_development_evidence_binding.v1"


class EvidenceBindingRefused(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_digest(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _as_list(value: Any, *, field: str, claim_id: str) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    raise EvidenceBindingRefused(f"claim {claim_id!r} has invalid {field}")


def _resolve_artifact(repository_root: Path, declared: str) -> Path:
    candidate = Path(declared)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise EvidenceBindingRefused(f"unsafe evidence path: {declared!r}")
    resolved = (repository_root / candidate).resolve()
    root = repository_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise EvidenceBindingRefused(f"evidence escapes repository root: {declared!r}") from error
    return resolved


def bind_claims(pack_path: Path, repository_root: Path) -> dict[str, Any]:
    if not pack_path.is_file():
        raise EvidenceBindingRefused(f"claims pack absent: {pack_path}")
    if not repository_root.is_dir():
        raise EvidenceBindingRefused(f"repository root absent: {repository_root}")

    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    claims = pack.get("claims")
    if not isinstance(claims, list) or not claims:
        raise EvidenceBindingRefused("claims pack has no claims")

    bound: list[dict[str, Any]] = []
    for claim in claims:
        if not isinstance(claim, dict) or claim.get("status") != "approved":
            continue
        claim_id = str(claim.get("id", ""))
        if not claim_id:
            raise EvidenceBindingRefused("approved claim has no id")
        evidence = _as_list(claim.get("evidence"), field="evidence", claim_id=claim_id)
        expected = _as_list(
            claim.get("evidence_sha256"), field="evidence_sha256", claim_id=claim_id
        )
        if len(evidence) != len(expected):
            raise EvidenceBindingRefused(
                f"claim {claim_id!r} evidence/digest cardinality mismatch"
            )

        items: list[dict[str, str]] = []
        for declared, expected_sha in zip(evidence, expected, strict=True):
            if not expected_sha.startswith("sha256:") or len(expected_sha) != 71:
                raise EvidenceBindingRefused(
                    f"claim {claim_id!r} has non-sha256 evidence pin"
                )
            path = _resolve_artifact(repository_root, declared)
            if not path.is_file():
                raise EvidenceBindingRefused(
                    f"claim {claim_id!r} evidence absent: {declared}"
                )
            observed = sha256_file(path)
            if observed != expected_sha:
                raise EvidenceBindingRefused(
                    f"claim {claim_id!r} evidence digest mismatch: {declared}"
                )
            items.append(
                {
                    "declared_path": declared,
                    "sha256": observed,
                }
            )
        bound.append(
            {
                "claim_id": claim_id,
                "status": "HISTORICAL_DEVELOPMENT_ONLY",
                "artifacts": items,
            }
        )

    if not bound:
        raise EvidenceBindingRefused("no approved claims were bound")

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "evidence_class": "MEASURED_HISTORICAL_DEVELOPMENT",
        "confirmatory_eligible": False,
        "claims_pack": {
            "path": pack_path.relative_to(REPO).as_posix()
            if pack_path.is_relative_to(REPO)
            else str(pack_path),
            "sha256": sha256_file(pack_path),
        },
        "repository_root": repository_root.relative_to(REPO).as_posix()
        if repository_root.is_relative_to(REPO)
        else str(repository_root),
        "approved_claims_bound": len(bound),
        "claims": sorted(bound, key=lambda item: item["claim_id"]),
        "interpretation": (
            "This receipt binds existing approved historical claims to their exact artifact "
            "bytes. It does not make the historical corpus fresh or confirmatory."
        ),
    }
    payload["binding_digest"] = canonical_digest(payload)
    return payload


def write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise EvidenceBindingRefused(f"binding receipt already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--repository", type=Path, default=DEFAULT_REPOSITORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    payload = bind_claims(args.pack, args.repository)
    if not args.verify_only:
        write_once(args.output, payload)
    print(
        json.dumps(
            {
                "approved_claims_bound": payload["approved_claims_bound"],
                "binding_digest": payload["binding_digest"],
                "confirmatory_eligible": payload["confirmatory_eligible"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
