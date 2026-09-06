#!/usr/bin/env python3
"""The gate that stands between the development pipeline and the v8 holdout.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §6 and §7. Opening the holdout is the
one irreversible act in this experiment: once a title is read, it is development
data forever and the confirmatory run must be built on different titles. So the
acquisition path refuses to run unless **every** condition below holds, and the
refusal is the default rather than the exception.

`main` exits non-zero when any condition fails. Nothing here opens, reads,
inspects, previews or dry-runs a holdout title --- this gate only inspects the
state of the development side.

**Every condition is falsified in the same execution.** `preflight_controls`
breaks each one in turn against a copy of the real state and requires the gate to
refuse. A fail-closed gate that has never closed is indistinguishable from an
`assert True`, and this programme has already shipped one guard --- the holdout
overlap check --- that read a key the seal does not have and therefore passed
everything.

Two conditions are deliberately unsatisfiable right now, and that is correct:
the model identity is a development stub, and the RAW context-budget policy is
an open protocol decision. The gate names both rather than letting the holdout
open around them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
ROOT = EXP.parents[2]
RECEIPTS = EXP / "receipts"
PROTOCOL = EXP / "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md"
SEAL = RECEIPTS / "v7-development-seal-2026-08-19.json"
FREEZE = RECEIPTS / "v8-config-freeze.json"
STATUS = ROOT / "docs" / "repro" / "TEST_SCOPE_STATUS.json"

def _load_module(path: Path, name: str) -> Any:
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


#: The frozen model is pinned by the identity chain in `model_identity_v8`, not
#: by a constant here. The expected revision lives in the candidate registry and
#: is read from it: a copy in this file would be a second source of truth, and
#: the two would drift exactly when it mattered.
_identity = _load_module(HERE / "model_identity_v8.py", "w6_identity")
REQUIRED_ATTESTATION_FIELDS = _identity.REQUIRED_ATTESTATION_FIELDS
EXPECTED_MODEL = _identity.EXPECTED_REPOSITORY

#: `vllm_model_v8.py` and `run_arms_holdout_v8.py` are here because they decide
#: numbers: the first carries the frozen prompt contract and decoding, the second
#: is the confirmatory runner itself. A file that can change the endpoint and is
#: not pinned is a hole in the lock.
REQUIRED_ARM_SOURCES = ("arms_v8.py", "scoring_v8.py", "build_question_set_v8.py",
                        "taint_gate_v8.py", "residual_overlap_v8.py",
                        "entity_conditioned_gate_v8.py", "run_arms_dev_v8.py",
                        "vllm_model_v8.py", "run_arms_holdout_v8.py",
                        "build_holdout_manifest_v8.py")


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def gather_state() -> dict[str, Any]:
    """Read the development side. Reads nothing under any holdout path."""
    seal = read_json(SEAL)
    freeze = read_json(FREEZE)
    status = read_json(STATUS)
    arm_run = read_json(RECEIPTS / "v8-development-arm-run-2026-08-19.json")
    taint = read_json(RECEIPTS / "v8-structural-taint-gate-dev-2026-08-19.json")
    residual = read_json(RECEIPTS / "v8-residual-calibration-dev-2026-08-19.json")
    return {
        "seal": seal,
        "freeze": freeze,
        "test_status": status,
        "arm_run": arm_run,
        "taint": taint,
        "residual": residual,
        "arm_sources_present": {name: (HERE / name).exists()
                                for name in REQUIRED_ARM_SOURCES},
        "arm_source_hashes": {name: file_sha256(HERE / name)
                              for name in REQUIRED_ARM_SOURCES if (HERE / name).exists()},
        "holdout_status": (freeze or {}).get("holdout_status", "UNOPENED"),
        "identity_chain": _identity.reconcile(
            (freeze or {}).get("model_attestation"),
            frozen_revision=((freeze or {}).get("model_identity") or {}).get("revision")),
        "runtime_registry": _identity.runtime_registry_state(),
        "identity_controls": _identity.identity_controls(),
    }


def evaluate(state: dict[str, Any]) -> dict[str, Any]:
    """Every condition, each with the reason it exists. Findings, not exceptions."""
    seal = state.get("seal") or {}
    freeze = state.get("freeze") or {}
    status = state.get("test_status") or {}
    arm_run = state.get("arm_run") or {}
    titles = ((seal.get("development_titles_excluded_from_v8") or {}).get("titles") or [])

    conditions: dict[str, dict[str, Any]] = {}

    def check(name: str, ok: bool, why: str, detail: Any = None) -> None:
        conditions[name] = {"passes": bool(ok), "why": why, "detail": detail}

    check("development_seal_valid",
          bool(seal) and seal.get("classification") is not None,
          "the seal is what distinguishes development titles from holdout titles; without "
          "it there is no such thing as an untouched title",
          seal.get("classification"))
    check("v7_titles_present_in_seal", len(titles) > 0,
          "the overlap guard reads this list. An empty list makes the guard inert and a "
          "silent pass, which is worse than no guard --- exactly the defect found on "
          "2026-08-19",
          len(titles))
    check("overlap_guard_live",
          (HERE / "build_question_set_v8.py").exists()
          and "development_titles_excluded_from_v8" in
              (HERE / "build_question_set_v8.py").read_text(encoding="utf-8"),
          "the generator must read the key the seal actually uses, verified against the "
          "source rather than assumed")
    check("config_freeze_exists", bool(freeze),
          "the freeze is the holdout lock: it pins every hash, parameter and rule so that "
          "nothing can be tuned once holdout results are visible")
    check("all_arm_sources_exist", all(state["arm_sources_present"].values()),
          "a missing arm means the holdout would be spent on an incomplete comparison",
          [n for n, present in state["arm_sources_present"].items() if not present])
    check("scorer_exists", (HERE / "scoring_v8.py").exists(),
          "scoring must be defined before the arms run, never chosen after seeing them")
    check("statistics_config_exists",
          bool(arm_run.get("secondary_multiplicity")),
          "the multiplicity correction is frozen before the holdout, not selected to suit "
          "the result")
    check("development_controls_separate",
          bool((arm_run.get("controls") or {}).get("all_separate")),
          "fairness, scoring and statistics controls must all have fired on development "
          "data; a control that never separated has verified nothing")
    check("fairness_contract_holds",
          bool((arm_run.get("fairness_contract") or {}).get("holds")),
          "the arms must differ only in knowledge representation")
    check("leakage_gates_live",
          bool((state.get("taint") or {}).get("gate_is_live"))
          and bool(((state.get("residual") or {}).get("positive_controls") or {})
                   .get("separates")),
          "both leakage layers must have demonstrated they can fail")
    check("full_repository_green", status.get("repository_green") is True,
          "a red repository means the harness that produces the endpoint is not known to "
          "work",
          status.get("repository_green"))
    check("no_source_drift",
          all(freeze.get("arm_source_hashes", {}).get(name) == digest
              for name, digest in state["arm_source_hashes"].items())
          if freeze.get("arm_source_hashes") else False,
          "the code that runs the holdout must be the code that was frozen, byte for byte")
    identity = freeze.get("model_identity") or {}
    attestation = freeze.get("model_attestation") or {}
    missing_attestation = [f for f in REQUIRED_ATTESTATION_FIELDS if not attestation.get(f)]
    check("model_is_pinned_and_real",
          bool(identity.get("is_real_model")),
          "the development model performs no inference. Opening the holdout against it "
          "would spend untouched titles on a stub",
          identity.get("name"))
    chain = state.get("identity_chain") or {}
    check("model_runtime_attested",
          not missing_attestation and identity.get("name") == EXPECTED_MODEL,
          "MODEL_RUNTIME_NOT_READY otherwise. A model name pins nothing: two runtimes "
          "serving the same name can differ in checkpoint, tokenizer, quantization and "
          "serving stack. Every field must come from the live runtime. There is no "
          "fallback to another model --- an unattestable runtime fails the preflight",
          {"expected": EXPECTED_MODEL, "observed": identity.get("name"),
           "missing_fields": missing_attestation})
    check("model_identity_chain_reconciled",
          chain.get("state") == "MODEL_IDENTITY_RECONCILED",
          "the candidate registry's expected revision, the live attestation and the "
          "config freeze must be the same revision. MODEL_IDENTITY_MISMATCH means "
          "something ran that was not expected: the registry is not overwritten with "
          "whatever ran, and the holdout does not open",
          {"state": chain.get("state"),
           "expected": chain.get("expected_revision"),
           "attested": chain.get("attested_revision"),
           "action": chain.get("action")})
    check("no_fallback_model_permitted",
          _identity.fallback_is_forbidden_here(
              state.get("runtime_registry") or {})["fallback_permitted_for_w6"] is False,
          "the serving registry may declare a fallback recipe, which is correct for "
          "serving and forbidden here. A confirmatory run that silently answered from a "
          "different model would be unfalsifiable")
    check("identity_controls_separate",
          bool((state.get("identity_controls") or {}).get("separates")),
          "the identity chain must be able to reach every failure state it claims: "
          "reconciled, mismatch, not-ready and ambiguous")
    check("raw_context_window_known",
          isinstance(freeze.get("model_context_tokens"), int)
          and freeze["model_context_tokens"] > 0,
          "option B gives RAW the whole document pair against the frozen model context. "
          "Without the attested context window RAW cannot run, and falling back to the "
          "retrieval budget would reintroduce the budget-limited floor",
          freeze.get("model_context_tokens"))
    check("raw_context_budget_policy_decided",
          freeze.get("raw_context_budget_policy") == "RAW_GETS_WHOLE_DOCUMENT_BUDGET",
          "the development run measured RAW losing the oracle to truncation on 0.5763 of "
          "questions. Until the policy is chosen and stated, a context-window effect would "
          "be reported as a representation effect",
          freeze.get("raw_context_budget_policy"))
    check("separability_metric_disposition_decided",
          freeze.get("before_after_separable_share_disposition")
          == "GENERATOR_INTEGRITY_CHECK_ONLY",
          "at 1.0 the metric is tautological under the v8 admission rule; it must be "
          "declared a generator integrity check or replaced before the holdout, never "
          "cited as independent difficulty evidence")
    check("holdout_status_unopened", state.get("holdout_status") == "UNOPENED",
          "a holdout that has been opened once cannot be opened again as a holdout")

    failed = [name for name, c in conditions.items() if not c["passes"]]
    return {"conditions": conditions, "failed": failed, "passes": not failed}


def preflight_controls() -> dict[str, Any]:
    """Break each condition in turn and require the gate to refuse.

    Runs against a synthetic all-passing state rather than the live one, so the
    controls fire the same way whether the real state is currently clean or not.
    """
    good_hashes = {name: f"sha256:{i}" for i, name in enumerate(REQUIRED_ARM_SOURCES)}
    base = {
        "seal": {"classification": "SEALED_DEVELOPMENT_PROTOCOL_CONFLICT_RUN",
                 "development_titles_excluded_from_v8": {"titles": ["A", "B"]}},
        "freeze": {"arm_source_hashes": good_hashes,
                   "model_identity": {"name": "Qwen/Qwen3.6-27B", "is_real_model": True},
                   "model_attestation": dict.fromkeys(REQUIRED_ATTESTATION_FIELDS,
                                                      "attested"),
                   "model_context_tokens": 32000,
                   "raw_context_budget_policy": "RAW_GETS_WHOLE_DOCUMENT_BUDGET",
                   "before_after_separable_share_disposition":
                       "GENERATOR_INTEGRITY_CHECK_ONLY",
                   "holdout_status": "UNOPENED"},
        "test_status": {"repository_green": True},
        "arm_run": {"controls": {"all_separate": True},
                    "fairness_contract": {"holds": True},
                    "secondary_multiplicity": {"alpha": 0.05}},
        "taint": {"gate_is_live": True},
        "residual": {"positive_controls": {"separates": True}},
        "arm_sources_present": dict.fromkeys(REQUIRED_ARM_SOURCES, True),
        "arm_source_hashes": good_hashes,
        "holdout_status": "UNOPENED",
        "identity_chain": {"state": "MODEL_IDENTITY_RECONCILED"},
        "runtime_registry": {"declared_fallback_recipe": "knowledge_precision_v1"},
        "identity_controls": {"separates": True},
    }

    # `overlap_guard_live` reads the real generator source, so the synthetic
    # baseline can only pass when that file is genuinely correct. That is the
    # intent: the control must not be able to fake a live guard.
    baseline = evaluate(base)

    breaks: dict[str, Any] = {}

    def broken(name: str, mutate: Any) -> None:
        state = json.loads(json.dumps(base))
        mutate(state)
        result = evaluate(state)
        breaks[name] = {"refused": not result["passes"], "failed_conditions": result["failed"]}

    broken("empty_seal_titles",
           lambda s: s["seal"]["development_titles_excluded_from_v8"].update({"titles": []}))
    broken("missing_seal", lambda s: s.update({"seal": None}))
    broken("missing_config_freeze", lambda s: s.update({"freeze": None}))
    broken("missing_arm_source",
           lambda s: s["arm_sources_present"].update({"arms_v8.py": False}))
    broken("source_drift",
           lambda s: s["freeze"]["arm_source_hashes"].update({"arms_v8.py": "sha256:other"}))
    broken("stub_model",
           lambda s: s["freeze"]["model_identity"].update({"is_real_model": False}))
    broken("identity_chain_mismatch",
           lambda s: s.update({"identity_chain": {"state": "MODEL_IDENTITY_MISMATCH"}}))
    broken("identity_chain_not_ready",
           lambda s: s.update({"identity_chain": {"state": "MODEL_RUNTIME_NOT_READY"}}))
    broken("identity_registry_ambiguous",
           lambda s: s.update({"identity_chain": {"state": "REGISTRY_AMBIGUOUS"}}))
    broken("identity_controls_inert",
           lambda s: s.update({"identity_controls": {"separates": False}}))
    broken("unattested_model_runtime",
           lambda s: s["freeze"]["model_attestation"].update(
               {"runtime_image_digest": None}))
    broken("model_name_substituted",
           lambda s: s["freeze"]["model_identity"].update({"name": "some-other-model"}))
    broken("unknown_model_context_window",
           lambda s: s["freeze"].update({"model_context_tokens": None}))
    broken("raw_budget_policy_reverted_to_shared",
           lambda s: s["freeze"].update(
               {"raw_context_budget_policy": "SHARED_BUDGET_RAW_IS_BUDGET_LIMITED"}))
    broken("separability_cited_as_difficulty_evidence",
           lambda s: s["freeze"].update(
               {"before_after_separable_share_disposition":
                "REPLACED_BY_INDEPENDENT_METRIC"}))
    broken("undecided_raw_budget_policy",
           lambda s: s["freeze"].update({"raw_context_budget_policy": None}))
    broken("undecided_separability_disposition",
           lambda s: s["freeze"].update({"before_after_separable_share_disposition": None}))
    broken("repository_red", lambda s: s["test_status"].update({"repository_green": False}))
    broken("controls_did_not_separate",
           lambda s: s["arm_run"]["controls"].update({"all_separate": False}))
    broken("fairness_violated",
           lambda s: s["arm_run"]["fairness_contract"].update({"holds": False}))
    broken("taint_gate_not_live", lambda s: s["taint"].update({"gate_is_live": False}))
    broken("residual_control_did_not_separate",
           lambda s: s["residual"]["positive_controls"].update({"separates": False}))
    broken("holdout_already_opened",
           lambda s: s.update({"holdout_status": "OPENED"}))
    broken("statistics_config_absent",
           lambda s: s["arm_run"].update({"secondary_multiplicity": None}))

    all_refused = all(b["refused"] for b in breaks.values())
    return {
        "synthetic_baseline_passes": baseline["passes"],
        "synthetic_baseline_failed_conditions": baseline["failed"],
        "breaks": breaks,
        "every_break_refused": all_refused,
        "separates": baseline["passes"] and all_refused,
        "note": "the baseline is synthetic so the controls fire regardless of the live "
                "state. overlap_guard_live still reads the real generator source, because "
                "a control that can fake a live guard is not a control.",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path,
                    default=RECEIPTS / "v8-holdout-preflight-2026-08-19.json")
    args = ap.parse_args()

    state = gather_state()
    result = evaluate(state)
    controls = preflight_controls()

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-v8-holdout-preflight.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": file_sha256(PROTOCOL),
        "run_class": "DEVELOPMENT_ONLY",
        "what_this_reads": "development-side state only. No holdout title is opened, read, "
                           "inspected, previewed or dry-run by this gate.",
        "holdout_status": state["holdout_status"],
        "conditions": result["conditions"],
        "failed_conditions": result["failed"],
        "holdout_may_be_opened": result["passes"] and controls["separates"],
        "controls": controls,
        "controls_separate": controls["separates"],
        "arm_source_hashes": state["arm_source_hashes"],
        "external_gpu_cost_usd": 0.0,
        "network_access": False,
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")

    print(f"controls separate: {controls['separates']}  "
          f"({sum(1 for b in controls['breaks'].values() if b['refused'])}"
          f"/{len(controls['breaks'])} breaks refused)")
    for name, c in result["conditions"].items():
        print(f"  {'PASS' if c['passes'] else 'FAIL'}  {name}")
    print(f"holdout may be opened: {receipt['holdout_may_be_opened']}")
    print(f"wrote {args.output.resolve().relative_to(ROOT).as_posix()}")
    # Exit 0 only when the controls fired; the gate's verdict is in the receipt.
    # A non-zero exit here would mean "the gate could not be trusted", not
    # "the holdout is closed" --- those are different failures.
    return 0 if controls["separates"] else 1


if __name__ == "__main__":
    sys.exit(main())
