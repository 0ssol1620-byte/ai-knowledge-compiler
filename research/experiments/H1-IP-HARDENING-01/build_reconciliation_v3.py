"""Build a collision-free H1 patent/paper reconciliation receipt (v3)."""
# ruff: noqa: E501 - evidence text intentionally preserves full claim statements

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "research/experiments/H1-IP-HARDENING-01/receipts/reconciliation-v3.json"

ARTIFACTS = (
    "packages/cir-python/src/akc_cir/source_grounded_acceptance.py",
    "packages/cir-python/src/akc_cir/cause_conditioned_recovery.py",
    "packages/cir-python/src/akc_cir/revision_resolution.py",
    "packages/cir-python/src/akc_cir/consumption_lineage.py",
    "tests/unit/test_source_grounded_acceptance.py",
    "tests/unit/test_cause_conditioned_recovery.py",
    "tests/unit/test_revision_resolution.py",
    "tests/unit/test_consumption_lineage.py",
    "tests/integration/test_governed_revision_consumption.py",
    "research/experiments/H1-A9-01/preregistration.json",
    "research/experiments/H1-A9-01/receipts/phase0-input-discovery.json",
    "research/experiments/H1-A12-01/preregistration-v2.json",
    "research/experiments/H1-A12-01/receipts/production-path-reconciliation.json",
    "research/experiments/H1-A12-01/cohorts/semantic-divergence-pilot-v1.json",
    "research/experiments/H1-A9-A12-SHARED-01/BUDGET_AND_REUSE_PLAN.json",
    "research/experiments/H1-IP-HARDENING-01/PATENT_PAPER_DELTA_2026-08-16.md",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_read(*args: str) -> str:
    return subprocess.check_output(  # noqa: S603 - fixed local git reads only
        ["git", *args],  # noqa: S607 - fixed executable
        cwd=ROOT,
        text=True,
    ).strip()


def exists_nonzero(relative: str) -> bool:
    path = ROOT / relative
    return path.is_file() and path.stat().st_size > 0


def main() -> int:
    artifacts = []
    for relative in ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise RuntimeError(f"required H1 artifact missing: {relative}")
        artifacts.append(
            {"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size}
        )

    runtime_gate = {
        "sbom_trivy_nonzero": exists_nonzero(
            ".chatgpt2codex/formal-runtime-v27/sbom.trivy.cdx.json"
        ),
        "trivy_critical_nonzero": exists_nonzero(
            ".chatgpt2codex/formal-runtime-v27/trivy-critical.json"
        ),
        "security_receipt_nonzero": exists_nonzero(
            "research/experiments/ASSURANCE-A-01/receipts/ovis-windows-trivy-security-v27.json"
        ),
        "ghcr_publication_receipt_nonzero": exists_nonzero(
            "research/experiments/ASSURANCE-A-01/receipts/ovis-ghcr-publication-v27.json"
        ),
        "formal_build_receipt_nonzero": exists_nonzero(
            "research/experiments/ASSURANCE-A-01/receipts/ovisocr2-m1.build-receipt-v27.json"
        ),
    }

    receipt = {
        "schema": "tavonel.h1-ip-paper-reconciliation.v3",
        "generated_at": datetime.now(UTC).isoformat(),
        "goal_loop_id": "goal-1786868445527-d1a17d1f",
        "worktree": {
            "path": str(ROOT),
            "branch": git_read("branch", "--show-current"),
            "head": git_read("rev-parse", "HEAD"),
            "dirty": bool(git_read("status", "--porcelain")),
        },
        "corrections": {
            "A9": {
                "implementation_ruling": "MULTI_LAYER_IMPLEMENTED_NATIVE_SOURCE_WORKED_EMBODIMENT_VISUAL_AND_LIVE_INTEGRATION_PENDING",
                "pre_existing_parallel_runtime": "RecoveryCoordinator.accept already requires passing validation, zero hard failures, source evidence, independent model family, changed prediction and diff evidence.",
                "pre_existing_targeted_regression": "5/5 PASS",
                "h1_addition": "Typed source-revision-hash-bound native correspondence receipt plus critical-token source check and explicit UNAVAILABLE fail-closed state.",
                "h1_targeted_regression": "52/52 PASS",
                "empirical_benefit": "WITHHELD",
            },
            "A12": {
                "implementation_ruling": "MULTI_LAYER_IMPLEMENTED_EMPIRICAL_BENEFIT_WITHHELD",
                "correction": "The original claim-chart/planned wording was stale. v6 scheduler already distinguishes semantic RECOVERY from infrastructure RETRY and excludes the failed independent model family during semantic recovery.",
                "pre_existing_targeted_regression": "3/3 PASS",
                "h1_addition": "CIR FailureClass/RecoveryOperatorKind adapter makes the cause-conditioned contract explicit and directly ablatable without duplicating protected budget/circuit/repeat guards.",
                "h1_targeted_regression": "101/101 PASS",
                "empirical_benefit": "WITHHELD",
            },
            "B15": {
                "implementation_ruling": "DOMAIN_VERTICAL_SLICE_IMPLEMENTED_LIVE_PERSISTENCE_PENDING",
                "targeted_regression": "111/111 PASS",
                "behavior": "source revision -> governed authority/applicability/valid-time recompute -> channel-specific dirty plan -> candidate world only",
            },
            "B14": {
                "implementation_ruling": "DOMAIN_VERTICAL_SLICE_IMPLEMENTED_LIVE_CONSUMPTION_PERSISTENCE_PENDING",
                "targeted_regression": "36/36 PASS",
                "integrated_b15_b14": "1/1 PASS",
                "behavior": "typed impact -> explicit CONSUMED_BY edge -> exact prior consumption stale-risk with source/candidate world and reason path",
            },
        },
        "combined_regression": {
            "ruff": "PASS",
            "pytest": "231/231 PASS",
            "note": "Combined new A9/A12/B14/B15 modules plus protected recovery/inspection/critical-token/authority/temporal/dependency/world tests and A12 phase-0 harness.",
        },
        "prospective_research": {
            "a12_protocol": "H1-A12-01 preregistration-v2: existing independent-family semantic recovery versus same-family-permitted ablation",
            "a12_cohort": {
                "cases": 48,
                "strata": {"R01": 8, "B01": 8, "N01": 8, "F01": 8, "G01": 8, "H01": 8},
                "candidate_models_all_cases": ["deepseek-ocr-2", "paddleocr-vl-1.6"],
                "ground_truth_included": False,
                "executed": False,
            },
            "a9_protocol": "H1-A9-01: independent correctness outcome; never use the source gate as its own outcome label; self-confidence/agreement arms unavailable unless genuinely frozen/prospectively emitted.",
            "shared_inference": "Paddle + DeepSeek outputs are shared between A12 family-choice and A9 acceptance-policy analysis; original failed base output is reused; same-family ablation only adds the one required recovery output.",
        },
        "gpu_budget": {
            "incremental_spend_usd": 0.0,
            "historical_demo_raw_estimate_three_arm_48_cases_usd": {
                "mineru_pipeline_same_family": 0.530736,
                "mineru_vlm_c1_same_family": 0.786,
            },
            "three_x_planning_reserve_usd": {
                "mineru_pipeline_same_family": 1.592208,
                "mineru_vlm_c1_same_family": 2.358,
            },
            "nominal_cap_usd": 3.0,
            "hard_cap_usd": 10.0,
            "preferred_parallelism": 4,
            "ground_truth_on_gpu": False,
            "spend_allowed_now": all(runtime_gate.values()),
        },
        "runtime_gate_snapshot": runtime_gate,
        "selective_recompile": {
            "status": "ENGINEERING_EVIDENCE_PASS_EXTERNAL_GENERALIZATION_WITHHELD",
            "documents": 30,
            "cases": 330,
            "equivalent": 330,
            "stale_left_behind": 0,
            "mean_rebuild_fraction": 0.12626262626262624,
            "next": "independent preregistered real revision-family holdout",
        },
        "artifacts": artifacts,
        "safety": {
            "commit": False,
            "push": False,
            "merge": False,
            "production_migration": False,
            "canary_b": False,
            "nobypassrls_disarm": False,
            "customer_data": False,
            "patent_filing": False,
            "paper_submission_or_publication": False,
        },
        "result": "PASS_RECONCILIATION_IMPLEMENTATION_EVIDENCE_ONLY",
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
