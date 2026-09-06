#!/usr/bin/env python3
"""Freeze the GPU successor study and runtime declarations as one bundle.

The two YAML files are intentionally kept as authored declarations.  A GPU
preflight is allowed to treat their bytes as frozen only when the caller names
this module's immutable receipt *and* its exact file SHA-256.  No glob, latest
pointer, or newest-wins lookup exists in this module.

This is a CPU-only administrative operation.  It does not load a model, touch
the network, provision hardware, or authorize a GPU run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, canonical_sha, rel, sha_file
from evidence import SCHEMA as IMMUTABLE_ENVELOPE_SCHEMA
from evidence import write_immutable

STUDY_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V1.yaml"
RUNTIME_PROTOCOL = NS / "protocols" / "GPU_SUCCESSOR_RUNTIME_V1.yaml"
STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V1"
STEM = "gpu-successor-protocol-bundle-freeze"
SCHEMA = "tavonel.v2.gpu_successor_protocol_bundle_freeze.v1"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class FreezeRefused(RuntimeError):
    """The declarations or their named immutable freeze are not trustworthy."""


def _safe_rel(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return str(path)


def _load_protocol(path: Path, *, expected_schema: str, expected_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise FreezeRefused(f"protocol not found: {_safe_rel(path)}")
    body = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(body, dict):
        raise FreezeRefused(f"protocol did not parse to a mapping: {_safe_rel(path)}")
    if body.get("schema") != expected_schema:
        raise FreezeRefused(
            f"{_safe_rel(path)} schema drift: {body.get('schema')!r} != {expected_schema!r}"
        )
    if body.get("protocol_id") != expected_id:
        raise FreezeRefused(
            f"{_safe_rel(path)} protocol_id drift: {body.get('protocol_id')!r} != {expected_id!r}"
        )
    if body.get("study_id") != STUDY_ID:
        raise FreezeRefused(
            f"{_safe_rel(path)} study_id drift: {body.get('study_id')!r} != {STUDY_ID!r}"
        )
    return body


def build_freeze(
    study_path: Path = STUDY_PROTOCOL,
    runtime_path: Path = RUNTIME_PROTOCOL,
) -> dict[str, Any]:
    study = _load_protocol(
        study_path,
        expected_schema="tavonel.v2.protocol.gpu_successor_study.v1",
        expected_id="GPU_SUCCESSOR_STUDY_V1",
    )
    runtime = _load_protocol(
        runtime_path,
        expected_schema="tavonel.v2.protocol.gpu_successor_runtime.v1",
        expected_id="GPU_SUCCESSOR_RUNTIME_V1",
    )
    return {
        "schema": SCHEMA,
        "study_id": STUDY_ID,
        "freeze_complete": True,
        "specifications": {
            "study": {
                "path": _safe_rel(study_path.resolve()),
                "sha256": sha_file(study_path),
                "schema": study["schema"],
                "protocol_id": study["protocol_id"],
                "authored_status": study.get("status"),
            },
            "runtime": {
                "path": _safe_rel(runtime_path.resolve()),
                "sha256": sha_file(runtime_path),
                "schema": runtime["schema"],
                "protocol_id": runtime["protocol_id"],
                "authored_status": runtime.get("status"),
            },
        },
        "binding_rule": (
            "both specification paths and hashes are conjunctive. The preflight must "
            "consume this exact immutable receipt path plus its file SHA-256 and must "
            "re-hash both specifications before reporting the freeze gate green."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def _normalise_expected_sha(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.lower()
    return value if value.startswith("sha256:") else "sha256:" + value


def verify_freeze(
    receipt_path: Path | None,
    expected_file_sha256: str | None,
    *,
    study_path: Path = STUDY_PROTOCOL,
    runtime_path: Path = RUNTIME_PROTOCOL,
) -> dict[str, Any]:
    """Verify one explicitly named receipt and the two files it froze.

    Returns a gate-shaped report rather than searching for an alternative on
    failure.  The expected digest is the receipt *file* SHA, not the receipt's
    internal canonical content digest; both are checked independently.
    """
    expected = _normalise_expected_sha(expected_file_sha256)
    if receipt_path is None or expected is None:
        return {
            "passed": False,
            "receipt": _safe_rel(receipt_path) if receipt_path is not None else None,
            "expected_file_sha256": expected,
            "why": "exact protocol-freeze receipt path and file SHA-256 are both required",
        }
    if not SHA256_PATTERN.fullmatch(expected):
        return {
            "passed": False,
            "receipt": _safe_rel(receipt_path),
            "expected_file_sha256": expected,
            "why": "expected protocol-freeze file SHA-256 is malformed",
        }
    if not receipt_path.is_file():
        return {
            "passed": False,
            "receipt": _safe_rel(receipt_path),
            "expected_file_sha256": expected,
            "why": "named protocol-freeze receipt is not on disk",
        }
    actual = sha_file(receipt_path)
    if actual != expected:
        return {
            "passed": False,
            "receipt": _safe_rel(receipt_path),
            "expected_file_sha256": expected,
            "actual_file_sha256": actual,
            "why": "protocol-freeze receipt file SHA-256 drift",
        }
    try:
        body = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "passed": False,
            "receipt": _safe_rel(receipt_path),
            "expected_file_sha256": expected,
            "why": f"protocol-freeze receipt is unreadable: {error}",
        }
    provenance = body.get("provenance") if isinstance(body, dict) else None
    checks = {
        "schema": body.get("schema") == SCHEMA if isinstance(body, dict) else False,
        "study_id": body.get("study_id") == STUDY_ID if isinstance(body, dict) else False,
        "freeze_complete": body.get("freeze_complete") is True if isinstance(body, dict) else False,
        "immutable_envelope": isinstance(provenance, dict)
        and provenance.get("schema") == IMMUTABLE_ENVELOPE_SCHEMA
        and provenance.get("immutable") is True
        and provenance.get("receipt_stem") == STEM,
        "canonical_receipt_digest": isinstance(body, dict)
        and body.get("receipt_sha256")
        == canonical_sha({key: value for key, value in body.items() if key != "receipt_sha256"}),
    }
    specs = body.get("specifications") if isinstance(body, dict) else None
    current = {"study": study_path, "runtime": runtime_path}
    expected_protocol_ids = {
        "study": "GPU_SUCCESSOR_STUDY_V1",
        "runtime": "GPU_SUCCESSOR_RUNTIME_V1",
    }
    expected_schemas = {
        "study": "tavonel.v2.protocol.gpu_successor_study.v1",
        "runtime": "tavonel.v2.protocol.gpu_successor_runtime.v1",
    }
    for name, path in current.items():
        frozen = specs.get(name) if isinstance(specs, dict) else None
        checks[f"{name}_path"] = isinstance(frozen, dict) and frozen.get("path") == _safe_rel(
            path.resolve()
        )
        checks[f"{name}_sha256"] = (
            isinstance(frozen, dict) and path.is_file() and frozen.get("sha256") == sha_file(path)
        )
        checks[f"{name}_protocol_id"] = (
            isinstance(frozen, dict) and frozen.get("protocol_id") == expected_protocol_ids[name]
        )
        checks[f"{name}_schema"] = (
            isinstance(frozen, dict) and frozen.get("schema") == expected_schemas[name]
        )
    passed = all(checks.values())
    return {
        "passed": passed,
        "receipt": _safe_rel(receipt_path),
        "expected_file_sha256": expected,
        "actual_file_sha256": actual,
        "checks": checks,
        "why": None if passed else "protocol-freeze receipt or a frozen specification drifted",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, default=STUDY_PROTOCOL)
    parser.add_argument("--runtime", type=Path, default=RUNTIME_PROTOCOL)
    args = parser.parse_args()
    try:
        body = build_freeze(args.study, args.runtime)
    except FreezeRefused as error:
        print(json.dumps({"error": str(error)}, indent=2))
        return 2
    written = write_immutable(
        STEM,
        body,
        tool=Path(__file__).resolve(),
        protocol=None,
    )
    print(json.dumps({**written, "freeze_complete": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
