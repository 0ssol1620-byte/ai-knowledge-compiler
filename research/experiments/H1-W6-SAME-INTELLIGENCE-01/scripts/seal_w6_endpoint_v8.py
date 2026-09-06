#!/usr/bin/env python3
"""Seal the W6 v8 endpoint. One immutable index over everything that produced it.

The arm-run receipt already carries the numbers. This binds them to the things
that make the numbers checkable a year from now: the config freeze, the model
attestation, the corpus root hash, the question-set digest, every gate receipt,
the source digests, the timestamps and the measured cost.

**It refuses to overwrite.** Re-running verifies instead, the same way the config
freeze and the v7 development seal do. A seal that can be rewritten after the
result is read is not a seal, and the whole point of this endpoint is that its
protocol was fixed before its numbers existed.

**Any outcome is sealable.** A confirmatory run in which TAVONEL wins, one in
which it does not, one in which nothing separates, and one in which a pre-arm
gate refused and no arm ran, are all valid results and all get the same
treatment. `--outcome-class` names which of them this is, and the seal records it
verbatim rather than inferring it from the numbers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
RECEIPTS = EXP / "receipts"
SEAL = RECEIPTS / "v8-endpoint-seal.json"

OUTCOME_CLASSES = (
    "TAVONEL_BETTER_ON_PRIMARY",
    "PRIMARY_INDISTINGUISHABLE_SECONDARY_DIFFERS",
    "NO_MEASURABLE_DIFFERENCE",
    "TAVONEL_WORSE",
    "CONFIRMATORY_PRE_ARM_GATE_FAILURE_ENDPOINT_NOT_RUN",
)

#: Every receipt the endpoint depends on. A missing one is a refusal: an index
#: that silently omits a gate cannot show the gate was passed rather than skipped.
BOUND_RECEIPTS = {
    "config_freeze": "v8-config-freeze.json",
    "runtime_attestation": "v8-runtime-attestation.json",
    "model_attestation": "v8-model-attestation.json",
    "runtime_feasibility": "v8-runtime-feasibility-2026-08-20.json",
    "holdout_preflight": "v8-holdout-preflight-2026-08-19.json",
    "development_seal": "v7-development-seal-2026-08-19.json",
    "holdout_title_manifest": "holdout-manifest-v8.json",
    "acquisition": "acquisition-v8-holdout.json",
    "acquisition_completion": "acquisition-v8-holdout-completion.json",
    "acquisition_integrity": "v8-holdout-acquisition-integrity.json",
}

#: Present only when the arms actually ran. Named separately so a gate-failure
#: seal is not silently missing something it should have had.
ARM_RECEIPTS = {
    "question_set": "question-set-v8-holdout.json",
    "taint_gate": "v8-taint-gate-holdout.json",
    "residual_overlap": "v8-residual-overlap-holdout.json",
    "entity_conditioned_gate": "v8-entity-conditioned-gate-holdout.json",
    "baseline_validity": "v8-baseline-validity-holdout.json",
    "arm_run": "v8-holdout-arm-run.json",
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def bind(names: dict[str, str], *, required: bool) -> tuple[dict[str, Any], list[str]]:
    bound: dict[str, Any] = {}
    missing: list[str] = []
    for key, filename in names.items():
        path = RECEIPTS / filename
        if not path.exists():
            missing.append(filename)
            if required:
                continue
            bound[key] = {"file": filename, "present": False}
            continue
        bound[key] = {"file": filename, "present": True, "sha256": file_sha256(path)}
    return bound, missing


def build(*, outcome_class: str, arms_ran: bool, pod: dict[str, Any],
          note: str) -> dict[str, Any]:
    bound, missing = bind(BOUND_RECEIPTS, required=True)
    if missing:
        raise SystemExit("cannot seal: missing required receipts: " + ", ".join(missing))

    arm_bound, arm_missing = bind(ARM_RECEIPTS, required=not arms_ran)
    if arms_ran and arm_missing:
        raise SystemExit("cannot seal an arm run: missing " + ", ".join(arm_missing))

    integrity = read_json(RECEIPTS / BOUND_RECEIPTS["acquisition_integrity"])
    attestation = read_json(RECEIPTS / BOUND_RECEIPTS["model_attestation"])
    freeze = read_json(RECEIPTS / BOUND_RECEIPTS["config_freeze"])
    arm_run = (read_json(RECEIPTS / ARM_RECEIPTS["arm_run"])
               if arms_ran and (RECEIPTS / ARM_RECEIPTS["arm_run"]).exists() else None)

    seal: dict[str, Any] = {
        "schema": "tavonel.w6-v8-endpoint-seal.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "sealed_at": datetime.now(UTC).isoformat(),
        "run_class": "HOLDOUT_CONFIRMATORY",
        "outcome_class": outcome_class,
        "outcome_class_note": note,
        "arms_ran": arms_ran,
        "negative_result_policy": (
            "TAVONEL winning, TAVONEL not winning, nothing separating and a pre-arm gate "
            "refusing are all valid outcomes of this protocol. The benchmark is not "
            "iterated until one of them appears, and this seal is written whichever it is."
        ),
        "holdout_reuse_rule": (
            "these titles are development data from this point forward. No threshold, "
            "template, retriever or decoding parameter may be tuned against them and the "
            "endpoint may not be recomputed on this holdout."
        ),
        "identity": {
            "model_repository": attestation.get("repository"),
            "checkpoint_revision": attestation.get("checkpoint_revision"),
            "model_file_manifest_sha256": attestation.get("model_file_manifest_sha256"),
            "tokenizer_hash": attestation.get("tokenizer_hash"),
            "quantization": attestation.get("quantization"),
            "serving_runtime": attestation.get("serving_runtime"),
            "serving_runtime_version": attestation.get("serving_runtime_version"),
            "runtime_image_digest": attestation.get("runtime_image_digest"),
            "model_attestation": attestation.get("model_attestation"),
            "decoding": freeze.get("decoding"),
            "wording_boundary": (
                "the reasoning preamble is disabled in all four arms. This result may not "
                "be described as measuring this model with reasoning enabled; the preamble "
                "finding is a runtime observation under a 256-token budget with this "
                "checkpoint's default chat template, not a conclusion about the model's "
                "reasoning capability."
            ),
        },
        "corpus": {
            "root_hash": integrity.get("corpus_root_hash"),
            "pairs_verified": integrity.get("pairs_verified"),
            "eligible_records": integrity.get("eligible_records"),
            "excluded_records": integrity.get("excluded_records"),
            "integrity_gate_passed": integrity.get("passes"),
        },
        "receipts": bound,
        "arm_receipts": arm_bound,
        "pod": pod,
        "source_hashes": {name: file_sha256(HERE / name) for name in sorted(
            p.name for p in HERE.glob("*_v8.py"))},
    }
    if arm_run is not None:
        seal["endpoint"] = {
            "arm_run_sha256": arm_run.get("receipt_sha256"),
            "question_set_sha256": arm_run.get("question_set_sha256"),
            "primary": arm_run.get("primary"),
            "control_cohort": arm_run.get("control_cohort"),
            "controls_all_separate": (arm_run.get("controls") or {}).get("all_separate"),
            "model_usage_total": arm_run.get("model_usage_total"),
            "started_at": arm_run.get("started_at"),
            "generated_at": arm_run.get("generated_at"),
        }
    seal["receipt_sha256"] = canonical_sha256(seal)
    return seal


def verify(existing: dict[str, Any]) -> int:
    body = {k: v for k, v in existing.items() if k != "receipt_sha256"}
    intact = canonical_sha256(body) == existing.get("receipt_sha256")
    drift: list[str] = []
    for group in ("receipts", "arm_receipts"):
        for key, entry in (existing.get(group) or {}).items():
            if not entry.get("present"):
                continue
            path = RECEIPTS / entry["file"]
            if not path.exists() or file_sha256(path) != entry.get("sha256"):
                drift.append(f"{group}.{key}")
    print(f"a seal already exists, sealed at {existing.get('sealed_at')}")
    print(f"outcome class: {existing.get('outcome_class')}")
    print(f"self-hash intact: {intact}   bound-receipt drift: {len(drift)}")
    for name in drift:
        print(f"  DRIFT {name}")
    print("SEAL INTACT" if intact and not drift else "SEAL BROKEN")
    return 0 if intact and not drift else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcome-class", choices=OUTCOME_CLASSES)
    parser.add_argument("--note", default="",
                        help="what the outcome class means for this run, in one sentence")
    parser.add_argument("--arms-ran", action="store_true")
    parser.add_argument("--pod-id")
    parser.add_argument("--pod-gpu")
    parser.add_argument("--pod-cost-per-hour-usd", type=float)
    parser.add_argument("--measured-gpu-cost-usd", type=float)
    parser.add_argument("--output", type=Path, default=SEAL)
    args = parser.parse_args()

    if args.output.exists():
        return verify(read_json(args.output))

    if not args.outcome_class:
        raise SystemExit(
            "--outcome-class is required to write a seal. It is not inferred from the "
            "numbers: naming the outcome is a decision, and a seal that guessed it would "
            "be a seal that could be argued with later.")

    pod = {"pod_id": args.pod_id, "gpu": args.pod_gpu,
           "cost_per_hour_usd": args.pod_cost_per_hour_usd,
           "measured_gpu_cost_usd": args.measured_gpu_cost_usd}
    seal = build(outcome_class=args.outcome_class, arms_ran=args.arms_ran,
                 pod=pod, note=args.note)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"sealed {seal['outcome_class']}   arms_ran={seal['arms_ran']}")
    print(f"corpus root: {seal['corpus']['root_hash']}")
    print(f"model: {seal['identity']['model_repository']} "
          f"{seal['identity']['checkpoint_revision']}")
    print(f"bound receipts: {len(seal['receipts'])}   "
          f"arm receipts: {len(seal['arm_receipts'])}")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
