#!/usr/bin/env python3
"""Build the sole GPU successor V2 universe from an exact SFIR4 PASS.

This module deliberately does not import an SFIR4 implementation at import
time.  SFIR4 is developed in a separate authority namespace, so its verifier
is either injected by the caller or loaded explicitly as ``sfir4_acceptance``.
If that verifier is absent, the route is closed.  A JSON document that merely
says PASS is never accepted as a substitute for the verifier.

The universe is fresh by construction: its only source is the acquisition
artifact bound by the exact SFIR4 acceptance path and digest.  No SFI3/SFIR1-3
manifest, receipt search, latest pointer, or historical four-link result is
read by this module.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("tools", "source_fact_ir", "endpoint"):
    _path = str(NS / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_successor_cohort as eligibility_v1  # noqa: E402
import gpu_successor_v2_prompt_schema as prompt_schema  # noqa: E402
from common import canonical_sha, rel, sha_file  # noqa: E402
from evidence import ReceiptExists, write_immutable  # noqa: E402

MANIFEST_SCHEMA = "tavonel.v2.gpu_successor_v2.cohort_manifest.v1"
STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V2"
PROTOCOL_ID = "GPU_SUCCESSOR_STUDY_V2"
RECEIPT_STEM = "gpu-successor-v2-universe"
AUTHORITY_RUN_ID = "SFIR4_GPU_SUCCESSOR_UNIVERSE_V2"
FLOOR = 450
QUESTION_SELECTION_RULE = "GPU_SUCCESSOR_V2_ONE_HASH_SELECTED_QUESTION_PER_LINEAGE_V1"

Verifier = Callable[[Path], dict[str, Any]]


class V2AuthorityRefused(RuntimeError):
    """The requested bytes are not the exact SFIR4-authorized universe."""


def _relative(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return str(path.resolve())


def _resolve(recorded: str, *, label: str) -> Path:
    candidates = (ROOT / recorded, Path(recorded))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise V2AuthorityRefused(f"{label} names absent file {recorded!r}")


def load_verifier(module_name: str) -> Verifier:
    """Load the explicitly named SFIR4 adapter; no module name is inferred."""
    if not module_name:
        raise V2AuthorityRefused("an explicit SFIR4 acceptance module is required")
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        raise V2AuthorityRefused(
            f"SFIR4 acceptance verifier module {module_name!r} is unavailable"
        ) from error
    verifier = getattr(module, "verify", None)
    if not callable(verifier):
        raise V2AuthorityRefused(
            f"SFIR4 acceptance module {module_name!r} exposes no callable verify(path)"
        )
    return verifier


def verify_sfir4_authority(
    *,
    acceptance_path: Path,
    acceptance_sha256: str,
    acquisition_path: Path,
    expected_protocol_id: str,
    expected_acquisition_schema: str,
    verifier: Verifier | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve one exact PASS chain, with no discovery or inferred defaults."""
    if not acceptance_path.is_file():
        raise V2AuthorityRefused("the explicitly named SFIR4 acceptance is absent")
    actual_acceptance_sha = sha_file(acceptance_path)
    if actual_acceptance_sha != acceptance_sha256:
        raise V2AuthorityRefused(
            f"SFIR4 acceptance digest mismatch: expected {acceptance_sha256}, "
            f"observed {actual_acceptance_sha}"
        )
    if not expected_protocol_id or not expected_acquisition_schema:
        raise V2AuthorityRefused(
            "expected SFIR4 protocol id and acquisition schema must be explicit"
        )

    if verifier is None:
        raise V2AuthorityRefused(
            "no SFIR4 acceptance verifier was injected; raw PASS JSON is never authority"
        )
    try:
        held = verifier(acceptance_path)
    except Exception as error:
        raise V2AuthorityRefused(f"SFIR4 acceptance verifier refused: {error}") from error
    if not isinstance(held, dict):
        raise V2AuthorityRefused("SFIR4 verifier did not return an acceptance mapping")
    if held.get("state") != "ACCEPTED" or held.get("verdict") != "PASS":
        raise V2AuthorityRefused("SFIR4 acceptance is not ACCEPTED/PASS")
    if held.get("protocol_id") != expected_protocol_id:
        raise V2AuthorityRefused(
            f"SFIR4 protocol is {held.get('protocol_id')!r}, not {expected_protocol_id!r}"
        )

    recorded_acquisition = held.get("acquisition")
    recorded_digest = held.get("acquisition_sha256")
    if not recorded_acquisition or not recorded_digest:
        raise V2AuthorityRefused("SFIR4 acceptance omits exact acquisition path or digest")
    accepted_acquisition = _resolve(str(recorded_acquisition), label="SFIR4 acceptance")
    if acquisition_path.resolve() != accepted_acquisition:
        raise V2AuthorityRefused("requested acquisition is not the exact artifact SFIR4 accepted")
    if sha_file(accepted_acquisition) != recorded_digest:
        raise V2AuthorityRefused("the SFIR4-accepted acquisition bytes moved")

    acquisition = json.loads(accepted_acquisition.read_text(encoding="utf-8"))
    if acquisition.get("schema") != expected_acquisition_schema:
        raise V2AuthorityRefused(
            f"acquisition schema is {acquisition.get('schema')!r}, not "
            f"{expected_acquisition_schema!r}"
        )
    if acquisition.get("protocol_id") != expected_protocol_id:
        raise V2AuthorityRefused(
            "acquisition protocol_id does not match the exact accepted SFIR4 protocol"
        )
    return held, acquisition


def build_manifest(
    *,
    acquisition: dict[str, Any],
    acquisition_path: Path,
    acceptance: dict[str, Any],
    acceptance_path: Path,
    acceptance_sha256: str,
    expected_protocol_id: str,
    expected_acquisition_schema: str,
) -> dict[str, Any]:
    """Build a deterministic V2 candidate universe from SFIR4 admitted rows."""
    facts: list[dict[str, Any]] = []
    excluded = dict.fromkeys(eligibility_v1.EXCLUSION_REASONS, 0)
    admitted = acquisition.get("admitted")
    if not isinstance(admitted, list):
        raise V2AuthorityRefused("SFIR4 acquisition carries no admitted list")
    for row in admitted:
        if not isinstance(row, dict):
            raise V2AuthorityRefused("SFIR4 admitted row is not a mapping")
        eligible, row_excluded = eligibility_v1.eligible_facts_for_row(row)
        facts.extend(eligible)
        for reason, count in row_excluded.items():
            excluded[reason] += count

    facts.sort(
        key=lambda fact: (
            str(fact.get("kind")),
            str(fact.get("fact_id")),
            str(fact.get("lineage_id")),
            str(fact.get("current_revision")),
        )
    )
    by_lineage: dict[str, list[dict[str, Any]]] = {}
    for fact in facts:
        lineage_id = fact.get("lineage_id")
        if not isinstance(lineage_id, str) or not lineage_id:
            raise V2AuthorityRefused("eligible fact has no exact lineage_id")
        by_lineage.setdefault(lineage_id, []).append(fact)
    selected: list[dict[str, Any]] = []
    selection_rows: list[dict[str, str]] = []
    for lineage_id, candidates in sorted(by_lineage.items()):
        ranked = [
            (
                canonical_sha(
                    {
                        "rule": QUESTION_SELECTION_RULE,
                        "lineage_id": lineage_id,
                        "fact_id": fact.get("fact_id"),
                        "kind": fact.get("kind"),
                    }
                ),
                fact,
            )
            for fact in candidates
        ]
        selection_hash, chosen = min(ranked, key=lambda row: row[0])
        selected.append(chosen)
        selection_rows.append(
            {
                "lineage_id": lineage_id,
                "fact_id": str(chosen.get("fact_id")),
                "selection_sha256": selection_hash,
            }
        )
    paired = list(zip(selected, selection_rows, strict=True))
    paired.sort(
        key=lambda pair: canonical_sha(
            {
                "rule": "GPU_SUCCESSOR_V2_EXACT_450_LINEAGE_SAMPLE_V1",
                "lineage_id": pair[0].get("lineage_id"),
            }
        )
    )
    paired = paired[:FLOOR]
    selected = [pair[0] for pair in paired]
    selection_rows = [pair[1] for pair in paired]
    selected_and_rows = sorted(
        zip(selected, selection_rows, strict=True),
        key=lambda pair: (str(pair[0].get("lineage_id")), str(pair[0].get("fact_id"))),
    )
    selected = [pair[0] for pair in selected_and_rows]
    selection_rows = [pair[1] for pair in selected_and_rows]
    eligible_count = len(selected)
    return {
        "schema": MANIFEST_SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "study_id": STUDY_ID,
        "authority_generation": "V2_FRESH_FROM_SFIR4_ONLY",
        "source_acquisition_schema": expected_acquisition_schema,
        "source_sfir4_protocol_id": expected_protocol_id,
        "source_sfir4_acceptance": {
            "path": _relative(acceptance_path),
            "sha256": acceptance_sha256,
            "state": acceptance["state"],
            "verdict": acceptance["verdict"],
            "protocol_id": acceptance["protocol_id"],
        },
        "source_acquisition_artifact": {
            "path": _relative(acquisition_path),
            "sha256": sha_file(acquisition_path),
            "schema": acquisition["schema"],
            "protocol_id": acquisition["protocol_id"],
        },
        "lineages_considered": len(admitted),
        "raw_eligible_fact_count": len(facts),
        "question_selection_rule": QUESTION_SELECTION_RULE,
        "question_selection": selection_rows,
        "question_selection_digest": canonical_sha(selection_rows),
        "eligible_count": eligible_count,
        "floor": FLOOR,
        "feasible": eligible_count == FLOOR,
        "excluded": excluded,
        "excluded_total": sum(excluded.values()),
        "facts": selected,
        "facts_digest": canonical_sha(selected),
        "prompt_schema_digest": prompt_schema.schema_digest(),
        "historical_authority_reuse": False,
        "rule": (
            "Only this exact immutable V2 manifest may proceed. SFI3 and SFIR1-3 "
            "authorities, prior manifests, latest pointers, padding, replacement "
            "sampling, more than one question per lineage, and a floor below 450 "
            "are ineligible."
        ),
    }


def build_authorized_manifest(
    *,
    acquisition_path: Path,
    acceptance_path: Path,
    acceptance_sha256: str,
    expected_protocol_id: str,
    expected_acquisition_schema: str,
    verifier: Verifier | None = None,
) -> dict[str, Any]:
    held, acquisition = verify_sfir4_authority(
        acceptance_path=acceptance_path,
        acceptance_sha256=acceptance_sha256,
        acquisition_path=acquisition_path,
        expected_protocol_id=expected_protocol_id,
        expected_acquisition_schema=expected_acquisition_schema,
        verifier=verifier,
    )
    return build_manifest(
        acquisition=acquisition,
        acquisition_path=acquisition_path,
        acceptance=held,
        acceptance_path=acceptance_path,
        acceptance_sha256=acceptance_sha256,
        expected_protocol_id=expected_protocol_id,
        expected_acquisition_schema=expected_acquisition_schema,
    )


def seal(**kwargs: Any) -> dict[str, str]:
    manifest = build_authorized_manifest(**kwargs)
    protocol = NS / "protocols" / "GPU_SUCCESSOR_STUDY_V2.yaml"
    try:
        return write_immutable(
            RECEIPT_STEM,
            manifest,
            tool=Path(__file__).resolve(),
            protocol=protocol,
            run_id=AUTHORITY_RUN_ID,
            pointer=False,
        )
    except ReceiptExists as error:
        raise V2AuthorityRefused(
            "the immutable GPU successor V2 universe already exists; a second is forbidden"
        ) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acquisition", type=Path)
    parser.add_argument("--sfir4-acceptance", type=Path, required=True)
    parser.add_argument("--sfir4-acceptance-sha256", required=True)
    parser.add_argument("--sfir4-acceptance-module", required=True)
    parser.add_argument("--sfir4-protocol-id", required=True)
    parser.add_argument("--sfir4-acquisition-schema", required=True)
    args = parser.parse_args(argv)
    try:
        verifier = load_verifier(args.sfir4_acceptance_module)
        written = seal(
            acquisition_path=args.acquisition,
            acceptance_path=args.sfir4_acceptance,
            acceptance_sha256=args.sfir4_acceptance_sha256,
            expected_protocol_id=args.sfir4_protocol_id,
            expected_acquisition_schema=args.sfir4_acquisition_schema,
            verifier=verifier,
        )
    except V2AuthorityRefused as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    print(json.dumps({"state": "FROZEN", **written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
