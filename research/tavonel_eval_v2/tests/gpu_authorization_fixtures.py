"""Real acceptance artefacts for the GPU authorization tests.

The preflight and the launcher both bind to two acceptance receipts. Testing
either one against a monkeypatched verifier would produce a gate that agrees
with itself, so these helpers build receipts that the genuine
`sfi3_acceptance.verify` and `four_link_acceptance.verify` accept, on disk,
under a temporary ROOT.

Nothing here reads held-out SFI3 material. The SFI3 measurement is a fixture
with the shape of a clean run -- eight primaries MET, E8 clear -- and the
four-link cohort is synthetic. These are the inputs a green route must accept;
the red directions live in the test files that import this one.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "source_fact_ir")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import four_link_acceptance as fla  # noqa: E402
import four_link_gate as gate  # noqa: E402
import ir  # noqa: E402
import sfi3_acceptance as acc  # noqa: E402

# ---------------------------------------------------------------------------
# SFI3


def sfi3_endpoints() -> dict[str, Any]:
    """Eight primaries MET and exercised; E8 clear without positive credit."""
    block: dict[str, Any] = {
        name: {"verdict": acc.MET, "violations": 0, "pairs_exercising": 12, "why": None}
        for name in acc.PRIMARY_ENDPOINTS
    }
    block[acc.VETO_ENDPOINT] = {
        "verdict": acc.VETO_CLEAR,
        "violations": 0,
        "pairs_exercising": 0,
        "natural_gate_power": False,
        "stages_checked": list(acc.STAGES_REQUIRED),
        "stages_missing": [],
        "cases": [],
    }
    return block


def land_sfi3_acceptance(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    verdict: str = "PASS",
    endpoints: dict[str, Any] | None = None,
) -> Path:
    """Write a verifiable SFI3 acceptance receipt; return its path.

    `monkeypatch` repoints `sfi3_acceptance.ROOT` at `tmp_path`, because the
    acceptance resolves every binding relative to the repository root and this
    material is not in the repository.
    """
    monkeypatch.setattr(acc, "ROOT", tmp_path)
    receipts = tmp_path / "receipts"
    receipts.mkdir(exist_ok=True)
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    protocol_dir = tmp_path / "research/tavonel_eval_v2/protocols"
    protocol_dir.mkdir(parents=True, exist_ok=True)

    protocol = protocol_dir / "SOURCE_FACT_IR_HELDOUT_V3.yaml"
    protocol.write_text("# fixture protocol\n", encoding="utf-8")
    freeze = receipts / "sfi3-freeze.json"
    freeze.write_text(
        json.dumps({"provenance": {"run_id": "20260909T000000Z-sfi3freeze0"}}),
        encoding="utf-8",
    )
    acquisition = tmp_path / "artifacts" / "sfi3-acquisition.json"
    acquisition.write_text(json.dumps({"admitted": []}), encoding="utf-8")

    body = {
        "schema": acc.MEASUREMENT_SCHEMA,
        "protocol": "research/tavonel_eval_v2/protocols/SOURCE_FACT_IR_HELDOUT_V3.yaml",
        "protocol_sha256": acc._sha_file(protocol),
        "protocol_freeze_receipt": "receipts/sfi3-freeze.json",
        "split": acc.REQUIRED_SPLIT,
        "acquisition": "artifacts/sfi3-acquisition.json",
        "acquisition_sha256": acc._sha_file(acquisition),
        "provenance": {"run_id": "20260910T000000Z-sfi3measure0"},
        "cohort_gates": {
            "pairs_scored": 240,
            "pairs_required": acc.COHORT_FLOOR_PAIRS,
            "pairs_met": True,
            "families": ["git_docs", "regulation_ecfr", "sec_edgar"],
            "families_required": acc.FAMILIES_REQUIRED,
            "families_met": True,
        },
        "endpoints": endpoints if endpoints is not None else sfi3_endpoints(),
        "verdict": verdict,
    }
    measurement = receipts / "sfi3-score.json"
    measurement.write_text(json.dumps(body), encoding="utf-8")

    path = tmp_path / "receipts" / acc.AUTHORITY_NAME
    monkeypatch.setattr(acc, "AUTHORITY_PATH", path)
    # Tests deliberately need both valid and invalid authorities.  Build the
    # immutable envelope directly so an invalid measurement can be landed and
    # then refused by the consumer (production `seal()` correctly refuses to
    # create such an authority at all).
    draft = {
        "schema": acc.SCHEMA,
        "protocol_id": acc.ACCEPTED_PROTOCOL_ID,
        "protocol": body["protocol"],
        "protocol_sha256": body["protocol_sha256"],
        "protocol_freeze_receipt": body["protocol_freeze_receipt"],
        "protocol_freeze_run_id": "20260909T000000Z-sfi3freeze0",
        "protocol_freeze_sha256": acc._sha_file(freeze),
        "measurement_receipt": "receipts/sfi3-score.json",
        "measurement_run_id": body["provenance"]["run_id"],
        "measurement_sha256": acc._sha_file(measurement),
        "acquisition": body["acquisition"],
        "acquisition_sha256": body["acquisition_sha256"],
        "authority": {
            "single_immutable_authority": True,
            "path": "receipts/" + acc.AUTHORITY_NAME,
            "alternate_receipts_accepted": False,
            "newest_wins": False,
        },
        "provenance": {
            "schema": "tavonel.v2.immutable_receipt_envelope.v1",
            "run_id": "sfi3-acceptance-fixture",
            "immutable": True,
            "receipt_stem": acc.STEM,
        },
    }
    draft["receipt_sha256"] = acc.canonical_sha(draft)
    path.write_text(json.dumps(draft), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# four-link


def _candidate(index: int) -> dict[str, Any]:
    return {
        "fact_id": f"fact-{index}",
        "kind": ir.REFERENCE_TARGET,
        "state": ir.REPRESENTED,
        "witness": {
            "construct": "md-inline-link",
            "byte_start": 100,
            "byte_end": 140,
            "excerpt": "[load rule](../operations/rule-configuration.md#load-rules)",
            "unit_path": ["git:fixture/repo:doc.md", "Section"],
        },
        "representation": {"normalized": "../operations/rule-configuration.md#load-rules"},
        "policy_ref": None,
        "reason": None,
        "extra": {},
    }


def land_four_link_acceptance(
    tmp_path: Path,
    monkeypatch: Any,
    *,
    count: int = 8,
    floor: int = 5,
) -> tuple[Path, Path]:
    """Write a manifest, its gate receipt and a verifiable acceptance.

    Returns `(manifest_path, acceptance_path)`. The floor is lowered on the
    module rather than in the artefact: `ACCEPTED_FLOOR` is deliberately read
    from the GPU declaration and never from the thing being gated, so a test
    cohort of eight has to move the declaration to be legible at all.
    """
    monkeypatch.setattr(fla, "ROOT", tmp_path)
    monkeypatch.setattr(fla, "ACCEPTED_FLOOR", floor)

    candidates = [_candidate(index) for index in range(count)]
    manifest = tmp_path / "successor_manifest.json"
    facts_digest = "sha256:" + hashlib.sha256(
        json.dumps(candidates, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    manifest.write_text(
        json.dumps(
            {
                "schema": "tavonel.v2.successor_cohort_manifest.v1",
                "facts": candidates,
                "eligible_count": count,
                "facts_digest": facts_digest,
                "source_sfi3_acceptance": {
                    "protocol_id": "SOURCE_FACT_IR_HELDOUT_V3",
                    "verdict": "PASS",
                },
                "provenance": {
                    "receipt_stem": "successor-candidate-universe",
                    "run_id": "SFI3_SUCCESSOR_UNIVERSE_V1",
                    "immutable": True,
                },
            }
        ),
        encoding="utf-8",
    )

    receipt = gate.gate(candidates, floor=floor)
    receipt["manifest"] = str(manifest)
    receipt["manifest_sha256"] = fla._sha_file(manifest)
    receipt_path = tmp_path / "four-link-gate.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    acceptance = {
        "schema": fla.SCHEMA,
        "manifest": str(manifest),
        "manifest_sha256": fla._sha_file(manifest),
        "gate_receipt": str(receipt_path),
        "gate_receipt_sha256": fla._sha_file(receipt_path),
        "facts_key": "facts",
        "eligible_count": receipt["by_state"][gate.STATE_ELIGIBLE],
        "floor": receipt["floor"],
        "provenance": {
            "receipt_stem": fla.STEM,
            "run_id": fla.AUTHORITY_RUN_ID,
            "immutable": True,
        },
    }
    path = tmp_path / "four-link-acceptance.json"
    path.write_text(json.dumps(acceptance), encoding="utf-8")
    return manifest, path
