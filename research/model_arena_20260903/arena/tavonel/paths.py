"""Campaign output layout as seen by lane E1 (ARENA_CONTRACT sections 1, 3, 8).

Every path this lane reads or writes is derived here so a test can point the
whole package at a temporary tree, and so nothing constructs a path to a
directory the lane does not own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.constants import NAMESPACE_ROOT
from arena.tavonel.variants import variant_dir_name


@dataclass(frozen=True, slots=True)
class ArenaPaths:
    """Resolved locations under one campaign output root."""

    root: Path

    @classmethod
    def default(cls) -> ArenaPaths:
        return cls(root=NAMESPACE_ROOT)

    # ---- inputs this lane reads (contract section 8: frozen outputs only) ----

    @property
    def source_manifest(self) -> Path:
        return self.root / "source_manifest.jsonl"

    @property
    def model_registry(self) -> Path:
        return self.root / "model_registry.json"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def frozen_outputs(self) -> Path:
        return self.root / "frozen_outputs"

    @property
    def scores(self) -> Path:
        return self.root / "scores"

    @property
    def cost_ledger(self) -> Path:
        return self.root / "cost" / "pod_ledger.jsonl"

    def model_run_dir(self, model_key: str) -> Path:
        return self.runs / model_key

    def raw_text_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "raw" / f"{case_key}.raw.txt"

    def canonical_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "canonical" / f"{case_key}.md"

    def receipt_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "receipts" / f"{case_key}.json"

    def receipts_dir(self, model_key: str) -> Path:
        return self.runs / model_key / "receipts"

    def frozen_manifest(self, model_key: str) -> Path:
        return self.frozen_outputs / model_key / "manifest.jsonl"

    def model_scores(self, model_key: str) -> Path:
        return self.scores / model_key / "scores.json"

    # ---- outputs this lane owns ----

    @property
    def tavonel(self) -> Path:
        return self.root / "tavonel"

    def signals_dir(self, model_key: str) -> Path:
        return self.tavonel / "signals" / model_key

    def signals_path(self, model_key: str, case_key: str) -> Path:
        return self.signals_dir(model_key) / f"{case_key}.json"

    def route_decisions_dir(self, variant: str) -> Path:
        return self.tavonel / "route_decisions" / variant_dir_name(variant)

    def route_decision_path(self, variant: str, case_key: str) -> Path:
        return self.route_decisions_dir(variant) / f"{case_key}.json"

    def route_frozen_path(self, variant: str) -> Path:
        return self.route_decisions_dir(variant) / "FROZEN.json"

    def replay_dir(self, variant: str) -> Path:
        return self.tavonel / "adaptive_replay" / variant_dir_name(variant)

    def replay_manifest(self, variant: str) -> Path:
        return self.replay_dir(variant) / "manifest.jsonl"

    def replay_summary(self, variant: str) -> Path:
        return self.replay_dir(variant) / "replay-summary.json"

    def replay_canonical_dir(self, variant: str) -> Path:
        return self.replay_dir(variant) / "canonical"

    def replay_canonical_path(self, variant: str, case_key: str) -> Path:
        return self.replay_canonical_dir(variant) / f"{case_key}.md"

    @property
    def recovery_jobs_dir(self) -> Path:
        return self.tavonel / "recovery_jobs"

    @property
    def recovery_plan(self) -> Path:
        return self.recovery_jobs_dir / "plan.jsonl"

    def variant_recovery_plan(self, variant: str) -> Path:
        return self.recovery_jobs_dir / variant_dir_name(variant) / "plan.jsonl"

    @property
    def disagreement_dir(self) -> Path:
        return self.tavonel / "disagreement"

    @property
    def disagreement_pairs(self) -> Path:
        return self.disagreement_dir / "pairs.jsonl"

    @property
    def disagreement_correlation(self) -> Path:
        return self.disagreement_dir / "correlation.json"

    @property
    def cost_dir(self) -> Path:
        return self.tavonel / "cost"

    def variant_cost_path(self, variant: str) -> Path:
        return self.cost_dir / f"{variant_dir_name(variant)}.json"


__all__ = ["ArenaPaths"]
