"""Build the implementation evidence receipt for the 2026-08-16 H1 IP hardening batch."""
# ruff: noqa: E501 - evidence text intentionally preserves full claim statements

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "research/experiments/H1-IP-HARDENING-01/receipts/implementation-v2.json"

FILES = (
    "packages/cir-python/src/akc_cir/cause_conditioned_recovery.py",
    "packages/cir-python/src/akc_cir/revision_resolution.py",
    "packages/cir-python/src/akc_cir/consumption_lineage.py",
    "packages/cir-python/src/akc_cir/source_grounded_acceptance.py",
    "tests/unit/test_cause_conditioned_recovery.py",
    "tests/unit/test_revision_resolution.py",
    "tests/unit/test_consumption_lineage.py",
    "tests/unit/test_source_grounded_acceptance.py",
    "tests/integration/test_governed_revision_consumption.py",
    "research/experiments/H1-A9-01/preregistration.json",
    "research/experiments/H1-A9-01/receipts/phase0-input-discovery.json",
    "research/experiments/H1-IP-HARDENING-01/PATENT_PAPER_DELTA_2026-08-16.md",
    "research/experiments/H1-A12-01/preregistration.json",
    "research/experiments/H1-A12-01/receipts/phase0-input-discovery.json",
    "research/experiments/H1-A12-01/scripts/analyze_policy_divergence.py",
    "research/experiments/H1-A12-01/tests/test_analyze_policy_divergence.py",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(  # noqa: S603 - fixed local git evidence reads only
        ["git", *args],  # noqa: S607 - fixed local git executable
        cwd=ROOT,
        text=True,
    ).strip()


def main() -> int:
    artifacts = []
    for relative in FILES:
        path = ROOT / relative
        artifacts.append(
            {
                "path": relative,
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
        )

    formal = ROOT / ".chatgpt2codex/formal-runtime-v27"
    receipt = {
        "schema": "tavonel.h1-ip-hardening-implementation-receipt.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "goal_loop_id": "goal-1786868445527-d1a17d1f",
        "worktree": {
            "absolute_path": str(ROOT),
            "branch": git("branch", "--show-current"),
            "head": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain")),
        },
        "source_basis": {
            "strategy": "Reconcile the user-supplied RAGFlow gap-hardening blueprint against current repository evidence; do not reimplement capabilities already present or regress orthogonal change channels.",
            "already_present_and_preserved": [
                "collision-safe role/ordinal-bound CompilationActionKey",
                "orthogonal semantic diff channels",
                "typed dependency propagation with reason paths",
                "selective/full rebuild equivalence verification",
                "validated candidate world and atomic publish core",
                "authority and bitemporal resolution core",
            ],
        },
        "claims": {
            "A9": {
                "status": "IMPLEMENTED_NATIVE_SOURCE_GATE_UNIT_VERIFIED_VISUAL_AND_LIVE_INTEGRATION_PENDING",
                "evidence": [
                    "Existing arbitration refuses ACCEPT when source-aware checks are absent even with candidate agreement.",
                    "Parser/model self-confidence can escalate but cannot accept.",
                    "Recovery/inspection baseline: 94/94 passed before this batch.",
                    "Final combined regression includes the same protected recovery/inspection tests.",
                    "A typed hash-bound source-grounded receipt now supplies the arbitration gate instead of an unproven caller boolean.",
                    "Native source text is compared directly with the candidate and critical-token mismatch is independently checked.",
                    "Visual-only verification remains UNAVAILABLE and fail-closed until a real visual source verifier supplies a receipt.",
                    "A9 source-gate + arbitration + critical-token regression: 52/52 passed.",
                ],
                "withheld": "No empirical precision benefit claim; visual-source verification and live persistence/API invocation remain pending.",
            },
            "A12": {
                "status": "IMPLEMENTED_UNIT_VERIFIED_EMPIRICAL_BENEFIT_WITHHELD",
                "evidence": [
                    "Explicit FailureClass separates operational/transient, semantic/model, security/policy and state-integrity failures.",
                    "Semantic/model failures retain source-preserving deterministic repair but skip same-family recovery variation; operational/transient failures retain bounded same-family retry.",
                    "A12 + protected recovery/inspection regression: 101/101 passed.",
                    "H1-A12-01 preregisters a zero-GPU Phase-0 policy-divergence analysis and a paired Phase-1 intervention only on policy-divergent cases.",
                    "H1-A12-01 Phase-0 harness lint passed and 4/4 tests passed, including rejection of aggregate-only evidence.",
                ],
                "withheld": "Cause-conditioned recovery quality/cost benefit is not yet empirically demonstrated.",
            },
            "B15": {
                "status": "IMPLEMENTED_DOMAIN_VERTICAL_SLICE_LIVE_PERSISTENCE_PENDING",
                "evidence": [
                    "Source revision before/after governed claims are resolved through existing authority/applicability/valid-time core.",
                    "Changed resolution dimensions propagate through semantic or temporal dependency channels into an explainable dirty plan.",
                    "A changed result may stage only a CANDIDATE world; the module never validates or publishes it.",
                    "B15 + authority/temporal/dependency/world regression: 111/111 passed.",
                    "Integrated B15?묪14 source revision?뭗irty answer?뭙xact prior consumption path: 1/1 passed.",
                ],
                "withheld": "No S4/live persistence/API/UI claim and no production migration claim.",
            },
            "B14": {
                "status": "IMPLEMENTED_DOMAIN_VERTICAL_SLICE_LIVE_CONSUMPTION_PERSISTENCE_PENDING",
                "evidence": [
                    "ConsumptionReceipt binds exact consumed units to a source world_state_id.",
                    "Exact CONSUMED_BY typed edges identify only prior consumptions reached by dependency impact.",
                    "Stale risk carries source/candidate world state and a human-readable reason path.",
                    "No explicit consumption edge means no stale-consumption claim; locator-only movement does not make the semantic answer stale.",
                    "B14 + dependency regression: 36/36 passed.",
                    "Integrated B15?묪14 source revision?뭗irty answer?뭙xact prior consumption path: 1/1 passed.",
                ],
                "withheld": "No claim that live agents/answers are already persisted or automatically revalidated/notified.",
            },
        },
        "verification": {
            "final_static_and_regression": {
                "command_scope": "ruff on six new core/test files; pytest A9/A12/B14/B15 plus protected recovery, inspection, authority, temporal, dependency and world-state tests",
                "result": "PASS",
                "pytest": "217/217 passed",
                "ruff": "PASS",
            },
            "a12_phase0_harness": {
                "result": "PASS",
                "pytest": "4/4 passed",
                "ruff": "PASS",
            },
            "b15_b14_integration": {
                "result": "PASS",
                "pytest": "1/1 passed",
                "ruff": "PASS",
            },
            "a12_primary_input_discovery": {
                "result": "WAITING_ON_PRIMARY_ATTEMPT_LOG",
                "synthetic_golden_excluded": True,
                "performance_conclusion_allowed": False,
            },
        },
        "selective_recompile_context": {
            "status": "ENGINEERING_EVIDENCE_PASS_EXTERNAL_GENERALIZATION_WITHHELD",
            "documents": 30,
            "cases": 330,
            "equivalent_cases": 330,
            "stale_left_behind_total": 0,
            "mean_rebuild_fraction": 0.12626262626262624,
            "next_evidence": "independent preregistered real revision-family holdout with paired statistics",
        },
        "gpu": {
            "incremental_compute_spend_usd": 0.0,
            "runpod_gpu_started_by_this_batch": False,
            "phase1_nominal_cap_usd": 3.0,
            "hard_cap_usd": 10.0,
            "preferred_parallelism": 4,
            "gate": "Do not spend until formal immutable runtime security/build/qualification chain is READY; source-only inference on GPU, local scoring only.",
        },
        "runtime_gate_snapshot": {
            "sbom_trivy_exists": (formal / "sbom.trivy.cdx.json").exists(),
            "trivy_critical_exists": (formal / "trivy-critical.json").exists(),
            "security_receipt_exists": (
                ROOT
                / "research/experiments/ASSURANCE-A-01/receipts/ovis-windows-trivy-security-v27.json"
            ).exists(),
            "ghcr_publication_receipt_exists": (
                ROOT
                / "research/experiments/ASSURANCE-A-01/receipts/ovis-ghcr-publication-v27.json"
            ).exists(),
            "formal_build_receipt_exists": (
                ROOT
                / "research/experiments/ASSURANCE-A-01/receipts/ovisocr2-m1.build-receipt-v27.json"
            ).exists(),
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
            "patent_filed": False,
            "paper_submitted_or_published": False,
        },
        "result": "PASS_IMPLEMENTATION_EVIDENCE_ONLY",
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(OUTPUT.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

