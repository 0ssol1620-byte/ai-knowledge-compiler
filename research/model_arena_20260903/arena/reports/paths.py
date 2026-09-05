"""Every path this lane reads or writes, in one place (ARENA_CONTRACT section 8).

``ReportPaths`` only ever reads from the campaign root and only ever writes
under the ``--out`` directory the CLI is given, which is why the two live on
separate dataclasses: nothing here can accidentally write into ``runs/`` or
``scores/`` no matter what a caller passes.

The read side is the closed list the lane brief names: ``scores/**``,
``runs/*/receipts/*.json``, ``runs/*/run-summary.json``,
``cost/pod_ledger.jsonl``, ``failures/errors.jsonl``, ``tavonel/**``,
``model_registry.json``, ``evaluator_registry.json``, ``campaign_manifest.json``,
``receipts/canary-*.json``, ``receipts/opus-*.json`` and (for the evidence
manifest only) ``receipts/environment_receipts/*``, ``receipts/provider_receipts/*``
and ``evidence/cleanup_receipt.json``, all of which sit inside the tree the
controller and Opus lanes already document as generated, gitignored output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.constants import NAMESPACE_ROOT

__all__ = ["OutputPaths", "SourcePaths"]


@dataclass(frozen=True, slots=True)
class SourcePaths:
    """Read-only view of the campaign root this lane consumes."""

    root: Path

    @classmethod
    def default(cls) -> SourcePaths:
        return cls(root=NAMESPACE_ROOT)

    @property
    def scores_dir(self) -> Path:
        return self.root / "scores"

    def model_scores_dir(self, model_key: str) -> Path:
        return self.scores_dir / model_key

    def benchmark_scores_dir(self, model_key: str, benchmark: str) -> Path:
        return self.model_scores_dir(model_key) / benchmark

    def summary_json(self, model_key: str, benchmark: str) -> Path:
        return self.benchmark_scores_dir(model_key, benchmark) / "summary.json"

    def per_case_jsonl(self, model_key: str, benchmark: str) -> Path:
        return self.benchmark_scores_dir(model_key, benchmark) / "per_case.jsonl"

    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    def receipts_dir(self, model_key: str) -> Path:
        return self.runs_dir / model_key / "receipts"

    def run_summary_json(self, model_key: str) -> Path:
        return self.runs_dir / model_key / "run-summary.json"

    @property
    def cost_dir(self) -> Path:
        return self.root / "cost"

    @property
    def pod_ledger(self) -> Path:
        return self.cost_dir / "pod_ledger.jsonl"

    @property
    def failures_dir(self) -> Path:
        return self.root / "failures"

    @property
    def errors_log(self) -> Path:
        return self.failures_dir / "errors.jsonl"

    @property
    def tavonel_dir(self) -> Path:
        return self.root / "tavonel"

    @property
    def route_decisions_root(self) -> Path:
        return self.tavonel_dir / "route_decisions"

    def route_decisions_dir(self, variant_dir_name: str) -> Path:
        return self.route_decisions_root / variant_dir_name

    @property
    def adaptive_replay_root(self) -> Path:
        return self.tavonel_dir / "adaptive_replay"

    def replay_manifest(self, variant_dir_name: str) -> Path:
        return self.adaptive_replay_root / variant_dir_name / "manifest.jsonl"

    def replay_summary(self, variant_dir_name: str) -> Path:
        return self.adaptive_replay_root / variant_dir_name / "replay-summary.json"

    @property
    def recovery_jobs_dir(self) -> Path:
        return self.tavonel_dir / "recovery_jobs"

    @property
    def recovery_plan(self) -> Path:
        return self.recovery_jobs_dir / "plan.jsonl"

    @property
    def disagreement_pairs(self) -> Path:
        return self.tavonel_dir / "disagreement" / "pairs.jsonl"

    @property
    def tavonel_cost_dir(self) -> Path:
        return self.tavonel_dir / "cost"

    def variant_cost_json(self, variant_dir_name: str) -> Path:
        return self.tavonel_cost_dir / f"{variant_dir_name}.json"

    @property
    def model_registry_json(self) -> Path:
        return self.root / "model_registry.json"

    @property
    def evaluator_registry_json(self) -> Path:
        return self.root / "evaluator_registry.json"

    @property
    def campaign_manifest_json(self) -> Path:
        return self.root / "campaign_manifest.json"

    @property
    def receipts_dir_root(self) -> Path:
        return self.root / "receipts"

    def glob_canary_receipts(self) -> list[Path]:
        return sorted(self.receipts_dir_root.glob("canary-*.json"))

    def glob_opus_receipts(self) -> list[Path]:
        return sorted(self.receipts_dir_root.glob("opus-*.json"))

    @property
    def environment_receipts_dir(self) -> Path:
        return self.receipts_dir_root / "environment_receipts"

    @property
    def provider_receipts_dir(self) -> Path:
        return self.receipts_dir_root / "provider_receipts"

    @property
    def cleanup_receipt_json(self) -> Path:
        return self.root / "evidence" / "cleanup_receipt.json"


@dataclass(frozen=True, slots=True)
class OutputPaths:
    """Where this lane writes. Always a caller-supplied ``--out`` directory."""

    reports_dir: Path
    evidence_dir: Path

    @classmethod
    def under(cls, out_dir: Path) -> OutputPaths:
        return cls(reports_dir=out_dir, evidence_dir=out_dir.parent / "evidence")

    def report(self, filename: str) -> Path:
        return self.reports_dir / filename

    def evidence(self, filename: str) -> Path:
        return self.evidence_dir / filename
