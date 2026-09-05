"""Every path lane E2 reads or writes, derived from one root.

Tests point :class:`ScoringPaths` at a temporary tree, which is why nothing
here reaches for ``NAMESPACE_ROOT`` at call time. The repository root is a
separate field because the evaluator clones and the ground-truth tree live
outside the campaign namespace and must never be written to.

Layout owned by this lane (ARENA_CONTRACT sections 1 and 3.11)::

    scores/_evaluators/<benchmark>/<revision>/     campaign-owned checkout
    scores/<key>/qa-<benchmark>.json               masterplan section 44 gate
    scores/<key>/<benchmark>/evaluator_input/      prepared evaluator input
    scores/<key>/<benchmark>/evaluator_raw/        captured evaluator output
    scores/<key>/<benchmark>/summary.json          official metrics + provenance
    scores/<key>/<benchmark>/per_case.jsonl        rows joinable on case_key
    scores/<key>/scores.json                       one model, every benchmark
    scores/<key>/provenance-chain.json             masterplan section 45 walk

``<key>`` is a model key, or a TAVONEL variant directory name when the output
set being scored is a composite.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from arena.constants import EVALUATOR_CACHE_ROOT, NAMESPACE_ROOT, REPO_ROOT

__all__ = ["EVALUATOR_CACHE_DIR", "ScoringPaths"]

#: benchmark key -> directory under ``benchmark/cache`` holding the pinned
#: upstream clone. Cloning reads from it; nothing ever writes into it.
EVALUATOR_CACHE_DIR = {
    "parsebench": "parsebench",
    "omnidoc": "omnidoc",
    "olmocr": "olmocr",
}


@dataclass(frozen=True, slots=True)
class ScoringPaths:
    """Resolved locations under one campaign root."""

    root: Path
    repo_root: Path

    @classmethod
    def default(cls) -> ScoringPaths:
        return cls(root=NAMESPACE_ROOT, repo_root=REPO_ROOT)

    # ---------------------------------------------------------- campaign inputs
    @property
    def source_manifest(self) -> Path:
        return self.root / "source_manifest.jsonl"

    @property
    def campaign_manifest(self) -> Path:
        return self.root / "campaign_manifest.json"

    @property
    def model_registry(self) -> Path:
        return self.root / "model_registry.json"

    @property
    def evaluator_registry(self) -> Path:
        return self.root / "evaluator_registry.json"

    @property
    def runs(self) -> Path:
        return self.root / "runs"

    @property
    def frozen_outputs(self) -> Path:
        return self.root / "frozen_outputs"

    @property
    def tavonel(self) -> Path:
        return self.root / "tavonel"

    @property
    def runtimes(self) -> Path:
        return self.root / "runtimes"

    def canonicalizer_source(self, model_key: str) -> Path:
        return self.runtimes / model_key / "canonical.py"

    def frozen_manifest(self, model_key: str) -> Path:
        return self.frozen_outputs / model_key / "manifest.jsonl"

    def frozen_marker(self, model_key: str) -> Path:
        return self.frozen_outputs / model_key / "FROZEN.json"

    def receipt_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "receipts" / f"{case_key}.json"

    def raw_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "raw" / f"{case_key}.raw.txt"

    def canonical_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "canonical" / f"{case_key}.md"

    def elements_path(self, model_key: str, case_key: str) -> Path:
        return self.runs / model_key / "canonical" / f"{case_key}.elements.json"

    # ------------------------------------------------- TAVONEL composite inputs
    def composite_dir(self, variant: str) -> Path:
        return self.tavonel / "adaptive_replay" / variant

    def composite_manifest(self, variant: str) -> Path:
        return self.composite_dir(variant) / "manifest.jsonl"

    def composite_canonical(self, variant: str, case_key: str) -> Path:
        return self.composite_dir(variant) / "canonical" / f"{case_key}.md"

    # -------------------------------------------------------------- lane output
    @property
    def scores(self) -> Path:
        return self.root / "scores"

    @property
    def evaluator_checkouts(self) -> Path:
        return self.scores / "_evaluators"

    def evaluator_checkout(self, benchmark: str, revision: str) -> Path:
        return self.evaluator_checkouts / benchmark / revision

    def score_dir(self, key: str) -> Path:
        return self.scores / key

    def qa_report(self, key: str, benchmark: str) -> Path:
        return self.score_dir(key) / f"qa-{benchmark}.json"

    def benchmark_dir(self, key: str, benchmark: str) -> Path:
        return self.score_dir(key) / benchmark

    def evaluator_input(self, key: str, benchmark: str) -> Path:
        return self.benchmark_dir(key, benchmark) / "evaluator_input"

    def evaluator_raw(self, key: str, benchmark: str) -> Path:
        return self.benchmark_dir(key, benchmark) / "evaluator_raw"

    def summary(self, key: str, benchmark: str) -> Path:
        return self.benchmark_dir(key, benchmark) / "summary.json"

    def per_case(self, key: str, benchmark: str) -> Path:
        return self.benchmark_dir(key, benchmark) / "per_case.jsonl"

    def scores_json(self, key: str) -> Path:
        return self.score_dir(key) / "scores.json"

    def provenance_chain(self, key: str) -> Path:
        return self.score_dir(key) / "provenance-chain.json"

    # ------------------------------------------------------- read-only sources
    @property
    def evaluator_cache_root(self) -> Path:
        """``benchmark/cache``. Read only - a clone source, never a worktree."""

        if self.repo_root == REPO_ROOT:
            return EVALUATOR_CACHE_ROOT
        return self.repo_root / "benchmark" / "cache"

    def evaluator_cache(self, benchmark: str) -> Path:
        return self.evaluator_cache_root / EVALUATOR_CACHE_DIR[benchmark]

    def repo_relative(self, relative_posix: str) -> Path:
        """Resolve a repository-relative POSIX path (``gt_paths`` entries)."""

        return self.repo_root.joinpath(*relative_posix.split("/"))
