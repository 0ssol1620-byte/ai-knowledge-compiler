#!/usr/bin/env python3
"""Accept a four-link gate only for the exact immutable SFIR4-bound V2 universe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "source_fact_ir"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
if str(NS) not in sys.path:
    sys.path.insert(0, str(NS))

import build_gpu_successor_v2_cohort as v2  # noqa: E402
import four_link_gate as gate  # noqa: E402
import four_link_validator as validator  # noqa: E402
from common import rel, sha_file  # noqa: E402
from evidence import ReceiptExists, write_immutable  # noqa: E402

SCHEMA = "tavonel.v2.gpu_successor_v2.four_link_acceptance.v1"
STEM = "gpu-successor-v2-four-link-acceptance"
AUTHORITY_RUN_ID = "GPU_SUCCESSOR_V2_FOUR_LINK_ACCEPTANCE"
FLOOR = 450


class V2FourLinkRefused(RuntimeError):
    """The four-link proof does not authorize the exact V2 manifest."""


def _resolve(recorded: str) -> Path:
    for candidate in (ROOT / recorded, Path(recorded)):
        if candidate.is_file():
            return candidate.resolve()
    raise V2FourLinkRefused(f"named artifact is absent: {recorded!r}")


def _relative(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return str(path.resolve())


def _require_v2_manifest(manifest: dict[str, Any]) -> None:
    provenance = manifest.get("provenance") or {}
    if manifest.get("schema") != v2.MANIFEST_SCHEMA:
        raise V2FourLinkRefused("manifest is not a GPU successor V2 universe")
    if manifest.get("protocol_id") != v2.PROTOCOL_ID:
        raise V2FourLinkRefused("manifest is not bound to GPU_SUCCESSOR_STUDY_V2")
    if manifest.get("authority_generation") != "V2_FRESH_FROM_SFIR4_ONLY":
        raise V2FourLinkRefused("manifest does not declare a fresh SFIR4-only universe")
    if manifest.get("historical_authority_reuse") is not False:
        raise V2FourLinkRefused("manifest permits historical authority reuse")
    if provenance.get("receipt_stem") != v2.RECEIPT_STEM:
        raise V2FourLinkRefused("manifest is not the V2 immutable-universe receipt")
    if provenance.get("run_id") != v2.AUTHORITY_RUN_ID or not provenance.get("immutable"):
        raise V2FourLinkRefused("manifest is not the single immutable V2 authority")
    source = manifest.get("source_sfir4_acceptance") or {}
    acquisition = manifest.get("source_acquisition_artifact") or {}
    if source.get("state") != "ACCEPTED" or source.get("verdict") != "PASS":
        raise V2FourLinkRefused("manifest is not bound to an SFIR4 PASS")
    if source.get("protocol_id") != manifest.get("source_sfir4_protocol_id"):
        raise V2FourLinkRefused("SFIR4 acceptance protocol binding moved")
    if acquisition.get("protocol_id") != manifest.get("source_sfir4_protocol_id"):
        raise V2FourLinkRefused("SFIR4 acquisition protocol binding moved")
    if acquisition.get("schema") != manifest.get("source_acquisition_schema"):
        raise V2FourLinkRefused("SFIR4 acquisition schema binding moved")
    acceptance_path = _resolve(str(source.get("path")))
    acquisition_path = _resolve(str(acquisition.get("path")))
    if sha_file(acceptance_path) != source.get("sha256"):
        raise V2FourLinkRefused("SFIR4 acceptance bytes moved after universe freeze")
    if sha_file(acquisition_path) != acquisition.get("sha256"):
        raise V2FourLinkRefused("SFIR4 acquisition bytes moved after universe freeze")


def verify(
    acceptance: dict[str, Any], *, launch_manifest_sha256: str | None = None
) -> dict[str, Any]:
    if acceptance.get("schema") != SCHEMA:
        raise V2FourLinkRefused("not a GPU successor V2 four-link acceptance")
    required = (
        "manifest",
        "manifest_sha256",
        "gate_receipt",
        "gate_receipt_sha256",
        "facts_key",
        "eligible_count",
        "floor",
    )
    missing = [name for name in required if acceptance.get(name) in (None, "")]
    if missing:
        raise V2FourLinkRefused(f"acceptance omits bindings: {missing}")

    manifest_path = _resolve(str(acceptance["manifest"]))
    manifest_digest = sha_file(manifest_path)
    if manifest_digest != acceptance["manifest_sha256"]:
        raise V2FourLinkRefused("accepted V2 manifest bytes moved")
    if launch_manifest_sha256 is not None and launch_manifest_sha256 != manifest_digest:
        raise V2FourLinkRefused("launch manifest is not byte-identical to accepted manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _require_v2_manifest(manifest)

    facts_key = str(acceptance["facts_key"])
    candidates = manifest.get(facts_key)
    if not isinstance(candidates, list) or not candidates:
        raise V2FourLinkRefused("V2 manifest has no candidate list")
    if manifest.get("floor") != FLOOR or manifest.get("eligible_count") != FLOOR:
        raise V2FourLinkRefused("V2 universe is not exactly 450 lineages")

    gate_path = _resolve(str(acceptance["gate_receipt"]))
    if sha_file(gate_path) != acceptance["gate_receipt_sha256"]:
        raise V2FourLinkRefused("four-link gate receipt bytes moved")
    receipt = json.loads(gate_path.read_text(encoding="utf-8"))
    if receipt.get("schema") != gate.SCHEMA or receipt.get("verdict") != "READY":
        raise V2FourLinkRefused("four-link gate is not READY")
    if receipt.get("manifest_sha256") != manifest_digest:
        raise V2FourLinkRefused("four-link gate binds a different manifest")
    if receipt.get("floor") != FLOOR or acceptance["floor"] != FLOOR:
        raise V2FourLinkRefused("four-link floor is not exactly 450")
    if len(receipt.get("records") or []) != len(candidates):
        raise V2FourLinkRefused("four-link gate did not classify every candidate")

    try:
        independent = validator.validate(receipt, facts_key=facts_key)
    except validator.ValidationRefused as error:
        raise V2FourLinkRefused(f"independent four-link validator refused: {error}") from error
    eligible = independent["eligible_count"]
    if eligible != FLOOR or eligible != acceptance["eligible_count"]:
        raise V2FourLinkRefused("independent eligible count is not exactly 450")
    return {
        "state": "ACCEPTED",
        "verdict": "PASS",
        "manifest": _relative(manifest_path),
        "manifest_sha256": manifest_digest,
        "gate_receipt": _relative(gate_path),
        "gate_receipt_sha256": sha_file(gate_path),
        "facts_key": facts_key,
        "eligible_count": eligible,
        "floor": FLOOR,
        "source_sfir4_acceptance": manifest["source_sfir4_acceptance"],
        "source_acquisition_artifact": manifest["source_acquisition_artifact"],
        "validator_schema": independent["schema"],
    }


def build(*, manifest_path: Path, gate_receipt_path: Path) -> dict[str, Any]:
    receipt = json.loads(gate_receipt_path.read_text(encoding="utf-8"))
    draft = {
        "schema": SCHEMA,
        "manifest": _relative(manifest_path),
        "manifest_sha256": sha_file(manifest_path),
        "gate_receipt": _relative(gate_receipt_path),
        "gate_receipt_sha256": sha_file(gate_receipt_path),
        "facts_key": "facts",
        "eligible_count": (receipt.get("by_state") or {}).get(gate.STATE_ELIGIBLE),
        "floor": FLOOR,
    }
    return {**draft, **verify(draft)}


def seal(*, manifest_path: Path, gate_receipt_path: Path) -> dict[str, str]:
    body = build(manifest_path=manifest_path, gate_receipt_path=gate_receipt_path)
    protocol = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V2.yaml"
    try:
        return write_immutable(
            STEM,
            body,
            tool=Path(__file__).resolve(),
            protocol=protocol,
            run_id=AUTHORITY_RUN_ID,
            pointer=False,
        )
    except ReceiptExists as error:
        raise V2FourLinkRefused("V2 four-link acceptance already exists") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--gate-receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        written = seal(manifest_path=args.manifest, gate_receipt_path=args.gate_receipt)
    except V2FourLinkRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    print(json.dumps({"state": "ACCEPTED", **written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
