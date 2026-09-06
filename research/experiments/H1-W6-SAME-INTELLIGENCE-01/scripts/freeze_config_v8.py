#!/usr/bin/env python3
"""Write the v8 config freeze: the holdout lock.

`W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md` §7. After this receipt exists,
development-side tuning is over. Every hash, parameter, threshold and rule that
determines the holdout result is pinned here, so that nothing can be adjusted
once holdout numbers are visible --- which is the difference between a
confirmatory run and a run that merely calls itself one.

**Three fields are founder decisions and this script will not invent them.**
They are required arguments with no defaults:

- `--model-id`, `--model-version` and `--decoding` --- the protocol pins "the
  same frozen model" without naming one. Everything is built against an
  injectable interface; the identity is not code's to choose.
- `--raw-context-budget-policy` --- the development run measured RAW losing the
  oracle to truncation on 0.5763 of questions under the shared budget. Until this
  is chosen, a context-window effect would be reported as a representation
  effect.
- `--separability-disposition` --- `before_after_separable_share` is 1.0 by
  construction of the v8 admission rule. It must be declared a generator
  integrity check or replaced with an independent metric, never cited as
  difficulty evidence.

A default on any of these would let the freeze happen by accident, with the
decision recorded as though it had been made.

The script refuses to overwrite an existing freeze. Re-running verifies instead,
the same way the v7 seal does: a freeze that can be rewritten is not a lock.
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
FREEZE = RECEIPTS / "v8-config-freeze.json"

PINNED_SOURCES = ("arms_v8.py", "scoring_v8.py", "build_question_set_v8.py",
                  "taint_gate_v8.py", "residual_overlap_v8.py",
                  "entity_conditioned_gate_v8.py", "run_arms_dev_v8.py",
                  "preflight_holdout_v8.py", "gate_question_set_v7.py",
                  "build_question_set_v2.py",
                  # the confirmatory path: the runner, the client that carries the
                  # prompt contract and decoding, the holdout selector, and the
                  # off-pod and on-pod halves of the runtime attestation
                  "run_arms_holdout_v8.py", "vllm_model_v8.py",
                  "build_holdout_manifest_v8.py", "attest_runtime_v8.py",
                  "pod_attest_qwen3_6.py", "model_identity_v8.py")

RAW_BUDGET_POLICIES = ("SHARED_BUDGET_RAW_IS_BUDGET_LIMITED",
                       "RAW_GETS_WHOLE_DOCUMENT_BUDGET")
SEPARABILITY_DISPOSITIONS = ("GENERATOR_INTEGRITY_CHECK_ONLY",
                             "REPLACED_BY_INDEPENDENT_METRIC")

#: Founder decision of 2026-08-20. The model is pinned by attestation from the
#: live runtime, never by name: two runtimes serving the same name can differ in
#: checkpoint, tokenizer, quantization and serving stack. The expected revision
#: comes from the candidate registry through `model_identity_v8`, never from a
#: constant here --- a copy would be a second source of truth.
def _load_identity() -> Any:
    import importlib.util
    path = Path(__file__).resolve().parent / "model_identity_v8.py"
    spec = importlib.util.spec_from_file_location("w6_identity_freeze", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["w6_identity_freeze"] = module
    spec.loader.exec_module(module)
    return module


IDENTITY = _load_identity()
EXPECTED_MODEL = IDENTITY.EXPECTED_REPOSITORY
REQUIRED_ATTESTATION_FIELDS = IDENTITY.REQUIRED_ATTESTATION_FIELDS

#: The decoding contract, identical for all four arms.
FROZEN_DECODING = {"temperature": 0.0, "max_tokens": 256, "tools": "off",
                   "system_contract": "identical across RAW, BASIC_RAG, "
                                      "BASIC_RAG_PLUS and TAVONEL"}


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _arm_constant(name: str, filename: str) -> Any:
    """Read a constant out of a pinned source, rather than restating it here.

    Restating it would put the value in two places, and the freeze would go on
    reporting the old one after the source changed --- which is the failure the
    freeze exists to prevent.
    """
    import importlib.util
    path = HERE / filename
    spec = importlib.util.spec_from_file_location(f"w6_freeze_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, name)


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def display(path: Path) -> str:
    """Repo-relative when it can be, absolute otherwise.

    `relative_to` raises for a path outside the repository, which made an
    earlier script die on a temporary output directory. A progress message must
    not be able to fail the run it is reporting on.
    """
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build(*, model_id: str, model_version: str, decoding: dict[str, Any],
          raw_policy: str, separability: str, attestation: dict[str, Any],
          model_context_tokens: int) -> dict[str, Any]:
    """Assemble the freeze from what is on disk plus the three decisions."""
    arms = HERE / "arms_v8.py"
    source = arms.read_text(encoding="utf-8")

    def constant(name: str, cast: Any) -> Any:
        for line in source.splitlines():
            if line.startswith(f"{name} = "):
                return cast(line.split("=", 1)[1].strip())
        raise SystemExit(f"{name} not found in arms_v8.py")

    residual = read_json(RECEIPTS / "v8-residual-calibration-dev-2026-08-19.json")
    taint = read_json(RECEIPTS / "v8-structural-taint-gate-dev-2026-08-19.json")
    gate = read_json(RECEIPTS / "v8-entity-conditioned-gate-on-v8-questions-dev-2026-08-19.json")
    arm_run = read_json(RECEIPTS / "v8-development-arm-run-2026-08-19.json")
    seal = read_json(RECEIPTS / "v7-development-seal-2026-08-19.json")
    question_set = read_json(RECEIPTS / "question-set-v8-dev-2026-08-19.json")

    freeze: dict[str, Any] = {
        "schema": "tavonel.w6-v8-config-freeze.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "frozen_at": datetime.now(UTC).isoformat(),
        "protocol": "W6_V8_CONFIRMATORY_PROTOCOL_2026-08-19.md",
        "protocol_sha256": file_sha256(PROTOCOL),
        "holdout_status": "UNOPENED",
        "meaning": (
            "development-side tuning ends here. Any change to a pinned value after this "
            "receipt exists makes the run development, not confirmatory."
        ),

        "arm_source_hashes": {name: file_sha256(HERE / name) for name in PINNED_SOURCES
                              if (HERE / name).exists()},

        "model_identity": {"name": model_id, "version": model_version,
                           "revision": attestation["checkpoint_revision"],
                           "is_real_model": True},
        "model_identity_chain": {
            "candidate_registry_expected_revision":
                IDENTITY.expected_identity().get("expected_revision"),
            "live_attested_revision": attestation["checkpoint_revision"],
            "equality_enforced_by": "model_identity_v8.reconcile",
            "note": "the candidate registry carries the expected revision and the runtime "
                    "registry is qualified against it; the source register's model card is "
                    "family evidence and pins nothing",
        },
        "model_attestation": attestation,
        "model_attestation_note": (
            "captured from the live runtime. A model name pins nothing; the checkpoint "
            "revision, model-file manifest, tokenizer, serving runtime and image digest "
            "are what make the run reproducible. There is no fallback model: an "
            "unattestable runtime fails the preflight as MODEL_RUNTIME_NOT_READY."
        ),
        "model_context_tokens": model_context_tokens,
        "decoding": decoding,

        "generator": {
            "admission_rule": "value-token inequality, markup normalized",
            "admission_rule_note": (
                "cases excluded as markup-only fail the frozen v8 value-change eligibility "
                "representation and independently match the development markup-only "
                "diagnostic. That is not a proof that they are non-semantic, and the "
                "4-reject / 3-admit admission control is detector liveness, not "
                "classification accuracy."
            ),
            "development_question_set_sha256": question_set.get("receipt_sha256"),
        },

        "leakage": {
            "structural_taint_gate_sha256": taint.get("receipt_sha256"),
            "residual_median_ceiling": residual.get("frozen_residual_median_ceiling"),
            "residual_p90_ceiling": residual.get("frozen_residual_p90_ceiling"),
            "calibration_rule": residual.get("calibration_rule"),
        },

        "retrieval": {
            "top_k": constant("TOP_K", int),
            "context_budget_tokens": constant("CONTEXT_BUDGET_TOKENS", int),
            "bm25_k1": 1.5, "bm25_b": 0.75,
            "chunking": "section units, minimum 20 content tokens",
            "basic_rag_plus": {
                "method": "RM3 pseudo-relevance feedback",
                "feedback_docs": constant("RM3_FEEDBACK_DOCS", int),
                "feedback_terms": constant("RM3_FEEDBACK_TERMS", int),
                "original_weight": constant("RM3_ORIGINAL_WEIGHT", float),
                "note": "a retrieval improvement, not an intelligence one: deterministic, "
                        "no model, no external resource, no metadata TAVONEL lacks",
            },
            "entity_routing": "stage 0 deterministic subject to document namespace, "
                              "identical for every arm",
        },

        "raw_context_budget_policy": raw_policy,
        "raw_context_budget_policy_evidence": {
            "development_truncation_rate": 0.8701,
            "development_oracle_lost_to_truncation": 0.5763,
            "why_it_had_to_be_decided": (
                "under a shared budget RAW answers most questions from evidence that no "
                "longer contains the answer, so its floor is set by context budget rather "
                "than by knowledge representation"
            ),
        },

        "baseline_validity_gate": {
            "criteria": list((gate.get("criteria") or {}).keys()),
            "bounds": {name: {"floor": c.get("floor"), "ceiling": c.get("ceiling")}
                       for name, c in (gate.get("criteria") or {}).items()},
        },
        "before_after_separable_share_disposition": separability,
        "before_after_separable_share_note": (
            "1.0 on development data is tautological: the generator admits on the same "
            "value-token comparison the gate measures. It is not independent difficulty "
            "evidence and is not cited as such."
        ),

        "scoring": {
            "normalizer": "scoring_v8.normalize, markup dropped, thousands separators "
                          "flattened, numerals kept",
            "primary_endpoint": "revision-sensitive answer correctness",
            "primary_comparison": "TAVONEL vs BASIC_RAG",
            "raw_role": "floor, not comparator",
            "separate_outcomes": ["answer_correct", "evidence_correct",
                                  "right_answer_stale_evidence", "temporal_correct",
                                  "stale_answer", "provenance_localized",
                                  "unsupported_assertion", "abstention_appropriate"],
        },

        "statistics": {
            "pairing": "by question",
            "primary_test": "exact binomial McNemar on discordant pairs",
            "interval": "Newcombe score interval for paired proportions",
            "always_reported": ["absolute_effect", "paired_difference_ci95",
                                "discordant_pairs", "concordant_pairs", "n_pairs"],
            "multiplicity": "Holm-Bonferroni over the 7 secondary endpoints",
            "reporting_rule": "a p-value is never reported alone",
        },

        "exclusions": {
            "before_scoring_only": True,
            "rule": "a question is excluded only if its gold answer cannot be established "
                    "from the frozen text, and only before any arm is scored",
            "development_exclusion_classes": (question_set.get("excluded") or {}),
        },

        "prompt_contract": {
            "system": _arm_constant("SYSTEM_CONTRACT", "vllm_model_v8.py"),
            "user_template": _arm_constant("USER_TEMPLATE", "vllm_model_v8.py"),
            "abstention_token": _arm_constant("ABSTENTION_TOKEN", "vllm_model_v8.py"),
            "chat_template_kwargs": _arm_constant("CHAT_TEMPLATE_KWARGS",
                                                  "vllm_model_v8.py"),
            "reasoning_preamble": "disabled",
            "reasoning_preamble_evidence": (
                "receipts/v8-runtime-feasibility-2026-08-20.json finding W6-V8-RUNTIME-01: "
                "measured on the live runtime before this freeze, the checkpoint's default "
                "chat template emits a reasoning preamble that had not reached an answer at "
                "the frozen 256-token limit, while the same runtime with the preamble "
                "disabled returned a bare value in 6 completion tokens. Applied identically "
                "to all four arms, so it changes the shared model contract and not the "
                "variable under test. The result may not be described as measuring this "
                "model with reasoning enabled."
            ),
            "identical_across_arms": True,
            "why_it_is_pinned": (
                "the scorer counts an answer correct only when its normalized token set "
                "equals the gold value's, so a contract that invited a sentence would "
                "score a correct answer wrong. That is a property of the frozen scorer, "
                "not something to adjust once holdout numbers are visible."
            ),
        },

        "cohorts": {
            "primary": {"class": "revision_sensitive", "cap": 200,
                        "order": "question_id, ascending"},
            "control": {"class": "simple_retrieval", "cap": 150,
                        "order": "question_id, ascending",
                        "why": "attributes whose value did not change. An arm that wins "
                               "the primary by always preferring the later revision shows "
                               "no advantage here."},
            "selection_note": "caps and order are fixed here, before any holdout question "
                              "exists, so no cohort can be chosen on an outcome",
        },

        "holdout_acquisition": {
            "minimum_primary_questions": 60,
            "minimum_primary_articles": 20,
            "minimum_controls": 40,
            "source": "PROTOCOL_V2 section 1 minimums, carried forward unchanged from "
                      "receipts/v7-endpoint-sufficiency-2026-08-19.json rather than "
                      "re-chosen for v8",
            "cohort_size": 750,
            "max_cohorts": 6,
            "before_cutoff": "2023-06-30T23:59:59Z",
            "after_cutoff": "2026-06-30T23:59:59Z",
            "minimum_separation_days": 1095,
            "stop_condition": "stop at the first cohort boundary where all three minimums "
                              "are met; the acquisition constants are the frozen v3 ones "
                              "and are not re-tuned for the holdout",
        },

        "holdout_selection_rule": {
            "source": "the 6,237 titles of the frozen manifest that v7 never touched",
            "development_titles_excluded": len(
                (seal.get("development_titles_excluded_from_v8") or {}).get("titles") or []),
            "order": "deterministic manifest or hash order, never selection on an outcome",
            "disjointness": "article level; v7 title overlap must be 0, verified against "
                            "the seal",
        },

        "stop_rule": {
            "gates_pass": "run the four arms, report the endpoint and its statistics",
            "gates_fail": "report endpoint NOT_RUN or the failed pre-arm gate, as measured",
            "no_reflex_v9": "a v8 gate failure does not authorize an immediate v9",
            "negative_result": "A, B, C, D and E are all valid and all reported as measured",
        },

        "development_controls_at_freeze": {
            "fairness": (arm_run.get("controls") or {}).get("fairness", {}).get("separates"),
            "scoring": (arm_run.get("controls") or {}).get("scoring", {}).get("separates"),
            "statistics": (arm_run.get("controls") or {}).get("statistics",
                                                              {}).get("separates"),
            "taint_gate_live": taint.get("gate_is_live"),
            "residual_controls": (residual.get("positive_controls") or {}).get("separates"),
        },
    }
    freeze["receipt_sha256"] = canonical_sha256(freeze)
    return freeze


def verify(existing: dict[str, Any]) -> dict[str, Any]:
    """Re-check a freeze that already exists. Never rewrite it."""
    drift = []
    for name, digest in (existing.get("arm_source_hashes") or {}).items():
        path = HERE / name
        if not path.exists():
            drift.append({"source": name, "state": "MISSING"})
        elif file_sha256(path) != digest:
            drift.append({"source": name, "state": "CHANGED", "frozen": digest,
                          "observed": file_sha256(path)})
    body = {k: v for k, v in existing.items() if k != "receipt_sha256"}
    return {"drift": drift, "intact": not drift,
            "receipt_hash_matches": canonical_sha256(body) == existing.get("receipt_sha256")}


def main() -> int:
    ap = argparse.ArgumentParser(description="write or verify the v8 config freeze")
    ap.add_argument("--model-id", help="the frozen model's identifier (founder decision)")
    ap.add_argument("--model-version", help="version or hash of that model")
    ap.add_argument("--decoding", help="JSON decoding config, e.g. "
                                       '{\"temperature\": 0.0, \"max_tokens\": 256}')
    ap.add_argument("--attestation", type=Path,
                    help="path to a JSON attestation captured from the live runtime, "
                         f"carrying {', '.join(REQUIRED_ATTESTATION_FIELDS)}")
    ap.add_argument("--model-context-tokens", type=int,
                    help="the attested context window; RAW needs it under option B")
    ap.add_argument("--raw-context-budget-policy", choices=RAW_BUDGET_POLICIES)
    ap.add_argument("--separability-disposition", choices=SEPARABILITY_DISPOSITIONS)
    ap.add_argument("--output", type=Path, default=FREEZE)
    args = ap.parse_args()

    if args.output.exists():
        existing = read_json(args.output)
        result = verify(existing)
        print(f"a freeze already exists, frozen at {existing.get('frozen_at')}")
        print(f"sources checked: {len(existing.get('arm_source_hashes') or {})}   "
              f"drift: {len(result['drift'])}")
        for item in result["drift"]:
            print(f"  {item['state']}: {item['source']}")
        print("FREEZE INTACT" if result["intact"] and result["receipt_hash_matches"]
              else "FREEZE BROKEN")
        return 0 if result["intact"] and result["receipt_hash_matches"] else 1

    missing = [name for name, value in (
        ("--model-id", args.model_id), ("--model-version", args.model_version),
        ("--decoding", args.decoding), ("--attestation", args.attestation),
        ("--model-context-tokens", args.model_context_tokens),
        ("--raw-context-budget-policy", args.raw_context_budget_policy),
        ("--separability-disposition", args.separability_disposition)) if not value]
    if missing:
        print("refusing to write a config freeze: these are decisions, not defaults.")
        for name in missing:
            print(f"  missing {name}")
        print("A default here would record a decision that nobody made.")
        return 2

    if args.model_id != EXPECTED_MODEL:
        print(f"MODEL_RUNTIME_NOT_READY: the decision pins {EXPECTED_MODEL}, "
              f"not {args.model_id}. There is no fallback model.")
        return 3
    if not args.attestation.exists():
        print(f"MODEL_RUNTIME_NOT_READY: no attestation at {args.attestation}")
        return 3
    attestation = read_json(args.attestation)
    absent = [f for f in REQUIRED_ATTESTATION_FIELDS if not attestation.get(f)]
    if absent:
        print("MODEL_RUNTIME_NOT_READY: the attestation is incomplete.")
        for name in absent:
            print(f"  missing {name}")
        print("A name pins nothing. Capture these from the live runtime; do not "
              "substitute another model.")
        return 3

    chain = IDENTITY.reconcile(attestation)
    if chain["state"] != "MODEL_IDENTITY_RECONCILED":
        print(f"{chain['state']}: {chain['why']}")
        if chain["state"] == "MODEL_IDENTITY_MISMATCH":
            print(f"  candidate registry expects {chain.get('expected_revision')}")
            print(f"  the live runtime attested {chain.get('attested_revision')}")
        print(f"  {chain['action']}")
        return 4

    freeze = build(attestation=attestation,
                   model_context_tokens=args.model_context_tokens,
                   model_id=args.model_id, model_version=args.model_version,
                   decoding=json.loads(args.decoding),
                   raw_policy=args.raw_context_budget_policy,
                   separability=args.separability_disposition)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(freeze, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"froze {len(freeze['arm_source_hashes'])} sources")
    print(f"model: {freeze['model_identity']['name']} {freeze['model_identity']['version']}")
    print(f"attested fields: {len(REQUIRED_ATTESTATION_FIELDS)}   "
          f"context window: {freeze['model_context_tokens']}")
    print(f"identity chain: expected == attested == frozen "
          f"({attestation['checkpoint_revision']})")
    print(f"raw budget policy: {freeze['raw_context_budget_policy']}")
    print(f"separability: {freeze['before_after_separable_share_disposition']}")
    print(f"wrote {display(args.output)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
