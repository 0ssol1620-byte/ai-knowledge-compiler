"""Resolve `evaluator_registry.json` (ARENA_CONTRACT section 3.8).

Upstream heads are re-verified with `git ls-remote` against the official
repositories. Dataset identity comes from `benchmark/benchmark-registry.lock.yaml`,
which is read-only for this lane. Ground-truth paths are recorded as paths only:
this file is the evaluator plane's map, and nothing in the inference plane may
read it.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

import yaml

from arena.constants import (
    BENCHMARK_KEYS,
    BENCHMARK_REGISTRY_LOCK,
    CAMPAIGN_ID,
    REPO_ROOT,
)
from arena.constants import HISTORICAL_EVALUATOR_PINS as HISTORICAL_PINS
from arena.registry.errors import RegistryError, SourceUnavailableError
from arena.registry.models import HEX40

EVALUATOR_REGISTRY_SCHEMA_ID: Final = "tavonel.arena.evaluator-registry.v1"
EVALUATOR_RECORD_SCHEMA_ID: Final = "tavonel.arena.evaluator-registry-record.v1"

#: benchmark key -> id used inside benchmark-registry.lock.yaml
LOCK_BENCHMARK_ID: Final = {
    "parsebench": "parsebench",
    "omnidoc": "omnidocbench",
    "olmocr": "olmocr-bench",
}

#: benchmark key -> directory under benchmark/datasets/acquired/public-core
ACQUIRED_DIR: Final = {
    "parsebench": "parsebench",
    "omnidoc": "omnidocbench",
    "olmocr": "olmocr-bench",
}

_ACQUIRED_ROOT = "benchmark/datasets/acquired/public-core"

#: Ground-truth files and directories observed in the acquired tree on 2026-09-03.
GT_PATHS: Final = {
    "omnidoc": (
        f"{_ACQUIRED_ROOT}/omnidocbench/OmniDocBench.json",
        f"{_ACQUIRED_ROOT}/omnidocbench/with_mask.json",
        f"{_ACQUIRED_ROOT}/omnidocbench/images",
    ),
    "parsebench": (
        f"{_ACQUIRED_ROOT}/parsebench/eval.yaml",
        f"{_ACQUIRED_ROOT}/parsebench/chart.jsonl",
        f"{_ACQUIRED_ROOT}/parsebench/layout.jsonl",
        f"{_ACQUIRED_ROOT}/parsebench/table.jsonl",
        f"{_ACQUIRED_ROOT}/parsebench/text_content.jsonl",
        f"{_ACQUIRED_ROOT}/parsebench/text_formatting.jsonl",
        f"{_ACQUIRED_ROOT}/parsebench/docs",
    ),
    "olmocr": (
        f"{_ACQUIRED_ROOT}/olmocr-bench/eval.yaml",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/arxiv_math.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/headers_footers.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/long_tiny_text.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/multi_column.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/old_scans.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/old_scans_math.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/table_tests.jsonl",
        f"{_ACQUIRED_ROOT}/olmocr-bench/bench_data/pdfs",
    ),
}

EVALUATOR_REPOSITORIES: Final = {
    "parsebench": "https://github.com/run-llama/ParseBench.git",
    "omnidoc": "https://github.com/opendatalab/OmniDocBench.git",
    "olmocr": "https://github.com/jina-ai/olmocr-bench.git",
}

#: ARENA_CONTRACT section 11.5 D31. Traced on 2026-09-03 with read-only api.github.com
#: calls; the full evidence, including the mirror's five-commit history, is
#: ``receipts/registry-updates/evaluator-olmocr-provenance.json``. These fields are
#: additive: they record where the mirror came from. They do not repoint ``repository``
#: and they do not touch any pin, because the historical pin
#: ``cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c`` exists ONLY in the mirror (GitHub answers
#: 422 for it in allenai/olmocr), so repointing would destroy the lane it defines.
OLMOCR_PROVENANCE: Final = {
    "upstream_source": "https://github.com/allenai/olmocr (tree olmocr/bench)",
    "upstream_source_license": "Apache-2.0",
    "upstream_relationship": "content_extraction_not_github_fork",
    "provenance_receipt": "receipts/registry-updates/evaluator-olmocr-provenance.json",
    "provenance_note": (
        "jina-ai/olmocr-bench reports fork=false with no parent, and its only substantive "
        "commit says 'Extract olmocr/bench from allenai/olmocr, fix imports for standalone "
        "use'. The upstream is Apache-2.0; this mirror ships no LICENSE file. An upstream "
        "licence is not a grant from the mirror, and neither settles patent FTO. The "
        "historical pin exists only in this mirror, which is why the repository is kept."
    ),
}

#: The olmOCR toolkit is not an evaluator, but its revision pins the prompt and
#: the renderer that olmocr2 uses, so it is resolved and recorded alongside.
OLMOCR_TOOLKIT_REPOSITORY: Final = "https://github.com/allenai/olmocr.git"

#: Heads observed by the orchestrator on 2026-09-03 and re-verified by this lane.
OBSERVED_HEADS: Final = {
    "parsebench": "45298128406f5bcc3942ccf97c618af15289770c",
    "omnidoc": "193627ae9e97d89188468ed1ee3b7a856ff76044",
    "olmocr": "cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c",
    "_olmocr_toolkit": "f7cfe4c22098b154c76b6ec950d1c0a464eecf8d",
}


class GitRefResolver(Protocol):
    def head(self, repository_url: str) -> str: ...


class LiveGitRefResolver:
    """`git ls-remote <url> HEAD`. Read-only; clones nothing."""

    def __init__(self, timeout_seconds: float = 60.0) -> None:
        self._timeout = timeout_seconds

    def head(self, repository_url: str) -> str:
        git = shutil.which("git")
        if git is None:
            raise SourceUnavailableError(
                "git is not on PATH; evaluator heads cannot be verified and the registry "
                "refuses to record an unverified pin"
            )
        try:
            completed = subprocess.run(
                # S603 is suppressed because the executable is resolved by
                # shutil.which and every argument is a fixed literal or a
                # repository URL from EVALUATOR_REPOSITORIES; no shell is used.
                [git, "ls-remote", repository_url, "HEAD"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise SourceUnavailableError(
                f"git ls-remote {repository_url} failed"
            ) from error
        first_line = completed.stdout.strip().splitlines()
        if not first_line:
            raise SourceUnavailableError(f"git ls-remote {repository_url} returned nothing")
        sha = first_line[0].split()[0].strip()
        if not HEX40.match(sha):
            raise SourceUnavailableError(
                f"git ls-remote {repository_url} returned {sha!r}, not a 40-hex commit id"
            )
        return sha


class RecordedGitRefResolver:
    """Replays recorded heads for offline runs."""

    def __init__(self, heads: dict[str, str]) -> None:
        self._heads = dict(heads)

    def head(self, repository_url: str) -> str:
        sha = self._heads.get(repository_url)
        if sha is None:
            raise SourceUnavailableError(f"no recorded head for {repository_url}")
        return sha


@dataclass(frozen=True, slots=True)
class MainPinDecision:
    revision: str
    rationale: str
    historical_lane_required: bool


_PARSEBENCH_DIFF_SUMMARY: dict[str, Any] = {
    "range": "1d460294b3b9c57fb3fa944dc17a9c044c24d1e5..45298128406f5bcc3942ccf97c618af15289770c",
    "commits": 24,
    "files_changed": 62,
    "insertions": 5532,
    "deletions": 658,
    "method": (
        "git clone --filter=blob:none into a TEMP directory, then git log --oneline, "
        "git diff --stat and a focused read of evaluation/, data/download.py and cli.py"
    ),
    "scoring_semantics_changed": True,
    "scoring_changes": [
        {
            "commit": "34b7345",
            "title": "Make LLM normalization off by default (#107)",
            "effect": (
                "LLAMACLOUD_BENCH_LLM_NORMALIZATION defaulted to 'judge' at 1d460294 and "
                "defaults to 'off' at 45298128. The chart group's rule_pass_rate_judge "
                "path is no longer taken unless opted in, so chart numbers move and the "
                "evaluator no longer calls a paid Anthropic API to produce a score."
            ),
        },
        {
            "commit": "516624d",
            "title": "Canonicalize tables for Text Content evaluation (#97)",
            "effect": (
                "ParseEvaluator now runs canonicalize_tables_for_text_content() on the "
                "markdown before rule execution when test_case.group == 'text_content'. "
                "Text Content numbers move for any output whose tables are formatted "
                "differently from the reference rendering."
            ),
        },
        {
            "commit": "f291112 + 1ae8b30",
            "title": "Formatting-rule fixes (#89, #90)",
            "effect": (
                "items_to_markdown no longer doubles heading/formula delimiters and a "
                "formatting-rule match is kept inside one span. Text Formatting numbers "
                "move for outputs that previously tripped either defect."
            ),
        },
    ],
    "dataset_contract_changed": False,
    "dataset_contract_note": (
        "data/download.py still resolves DATASET_REPO='llamaindex/ParseBench' with the "
        "same snapshot_download call and the same is_dataset_ready validation, so the "
        "dataset revision pinned in benchmark-registry.lock.yaml (2805a1d9) remains "
        "valid for both pins. ParseBench has no eval.yaml of its own; the eval.yaml in "
        "the acquired tree is the TAVONEL-side task map and is untouched by this diff."
    ),
    "cli_contract_changed": False,
    "cli_contract_note": (
        "`parse-bench evaluation run --output_dir OUTPUT_DIR` is unchanged. 45298128 adds "
        "a `version` subcommand, publishes the package to PyPI with per-provider extras, "
        "and walks up for .env instead of assuming a repo checkout. The lock's entrypoint "
        "still works from a checkout, and `pip install \"parse-bench[runners]\"` now works too."
    ),
    "dependency_note": (
        "markdown2 floor raised to 2.5.5 because 2.5.4 rendered '*'/'_' runs inside "
        "table cells differently and moved 12 of 2078 LiteParse outputs between "
        "environments. Pin the evaluator environment, not just the revision."
    ),
    "historical_lane_risk": (
        "At 1d460294 chart scoring defaults to the Claude LLM judge, and "
        "JudgeNormalizer builds an anthropic.Anthropic client at construction while "
        "its per-call path swallows failures with `except Exception: "
        "logger.warning(\"Anthropic API call failed\")`. Running the historical lane "
        "without a working ANTHROPIC_API_KEY therefore produces a number that LOOKS "
        "like a judge-normalized score and is not one. Lane E2 must either supply a "
        "key and record the call count, or set "
        "LLAMACLOUD_BENCH_LLM_NORMALIZATION=off on the historical lane too and say so "
        "in the score provenance. Silence is not an acceptable third option."
    ),
    "provider_additions_note": (
        "Most of the diff volume is new inference providers (Amazon Nova, GLM, "
        "Infinity-Parser2 alignment, rakedoc, florin, oi-parser) and their tests. The "
        "arena does not use ParseBench's inference side at all - it scores frozen "
        "outputs - so those files do not affect this campaign."
    ),
}


def _parsebench_decision(upstream_head: str) -> MainPinDecision:
    return MainPinDecision(
        revision=upstream_head,
        rationale=(
            "New pin for the main leaderboard, historical lane kept. Masterplan section "
            "1.1 says to re-check upstream at campaign start and freeze once. The diff "
            "from 1d460294 does change scoring semantics in two places (chart LLM "
            "normalization now off by default; text_content tables canonicalized before "
            "rule execution), but it does not break the contract this campaign depends "
            "on: the dataset repository, revision and loader are unchanged, and the "
            "`parse-bench evaluation run --output_dir` entrypoint is unchanged. Both "
            "changes move the newer revision toward determinism - 1d460294 called a paid "
            "Anthropic LLM judge by default, which is not a reproducible evaluator and "
            "would put an API-dependent number into a published claim. Because the two "
            "changes DO move chart and text_content scores, the 1d460294 historical lane "
            "is mandatory for any comparison against the 2026-08 FOLYNTA campaign, and "
            "no report may place a 45298128 number beside a 1d460294 number without "
            "naming the lane."
        ),
        historical_lane_required=True,
    )


def _unchanged_decision(benchmark: str, upstream_head: str) -> MainPinDecision:
    return MainPinDecision(
        revision=upstream_head,
        rationale=(
            f"Upstream HEAD for {benchmark} is identical to the historical pin "
            f"{HISTORICAL_PINS[benchmark]}, so the new main pin and the historical pin "
            "are the same revision. There is nothing to compare and no second lane to "
            "run: results on this benchmark are directly comparable with the 2026-08 "
            "FOLYNTA campaign at the evaluator level. Dataset revision and evaluator "
            "environment still have to match, and that is checked separately."
        ),
        historical_lane_required=False,
    )


def load_benchmark_lock(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Read `benchmark/benchmark-registry.lock.yaml` into {lock_id: entry}."""
    lock_path = path or BENCHMARK_REGISTRY_LOCK
    if not lock_path.is_file():
        raise RegistryError(f"benchmark registry lock not found at {lock_path}")
    raw = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RegistryError(f"{lock_path} did not parse into a mapping")
    entries = raw.get("benchmarks")
    if not isinstance(entries, list):
        raise RegistryError(f"{lock_path} has no 'benchmarks' list")
    by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            by_id[entry["id"]] = entry
    return by_id


def missing_gt_paths(benchmark: str, *, repo_root: Path | None = None) -> list[str]:
    """Ground-truth paths recorded for ``benchmark`` that are not on this host.

    `benchmark/datasets/acquired/` is git-ignored, so an empty result proves the
    corpus is here and a non-empty one proves nothing about the campaign - only
    about this machine. The registry records the observation either way rather
    than asserting a path exists because it was written down.
    """
    root = repo_root or REPO_ROOT
    return [path for path in GT_PATHS[benchmark] if not (root / path).exists()]


def build_evaluator_record(
    benchmark: str,
    *,
    lock_entry: dict[str, Any],
    upstream_head: str,
    decision: MainPinDecision,
    resolved_at: str,
) -> dict[str, Any]:
    evaluator = lock_entry.get("evaluator")
    dataset = lock_entry.get("dataset")
    if not isinstance(evaluator, dict) or not isinstance(dataset, dict):
        raise RegistryError(f"lock entry for {benchmark} is missing evaluator/dataset blocks")
    missing = missing_gt_paths(benchmark)

    record: dict[str, Any] = {
        "schema": EVALUATOR_RECORD_SCHEMA_ID,
        "benchmark": benchmark,
        "repository": EVALUATOR_REPOSITORIES[benchmark],
        "historical_pin": HISTORICAL_PINS[benchmark],
        "upstream_head_at_start": upstream_head,
        "upstream_head_verified_at": resolved_at,
        "upstream_head_verification_method": "git ls-remote <repository> HEAD",
        "main_pin": decision.revision,
        "main_pin_rationale": decision.rationale,
        "historical_lane_required": decision.historical_lane_required,
        "moved_since_historical_pin": upstream_head != HISTORICAL_PINS[benchmark],
        "entrypoint": evaluator.get("entrypoint"),
        "dataset_repository": dataset.get("repository"),
        "dataset_revision": dataset.get("revision"),
        "dataset_manifest_sha256": dataset.get("manifest_sha256"),
        "dataset_license": dataset.get("license"),
        "dataset_redistribution": dataset.get("redistribution"),
        "gt_paths": list(GT_PATHS[benchmark]),
        "gt_paths_present_on_resolution_host": not missing,
        "gt_paths_missing_on_resolution_host": missing,
        "gt_paths_note": (
            "benchmark/datasets/acquired/ is git-ignored, so absence here means the "
            "corpus is not on this machine, not that the campaign is broken. Lane E2 "
            "gates on it before any evaluator runs."
        ),
        "license": evaluator.get("license"),
        "lock_source": "benchmark/benchmark-registry.lock.yaml",
        "frozen": False,
        "frozen_note": (
            "The orchestrator flips frozen to true. Once frozen, no field in this record "
            "changes for the life of the campaign (ARENA_CONTRACT section 3.8)."
        ),
    }
    if benchmark == "parsebench":
        record["upstream_diff_summary"] = _PARSEBENCH_DIFF_SUMMARY
    if benchmark == "olmocr":
        record["license_note"] = (
            "The evaluator mirror jina-ai/olmocr-bench has no LICENSE file "
            "(benchmark-registry.lock.yaml records 'upstream-license-file-absent') and "
            "the dataset allenai/olmOCR-bench is license-review-required. Readable is "
            "not reusable: scores may be produced for internal analysis, and neither the "
            "evaluator nor the dataset may be redistributed until that review clears."
        )
        record.update(OLMOCR_PROVENANCE)
    return record


def resolve_evaluators(
    resolver: GitRefResolver,
    *,
    lock_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_at = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    lock = load_benchmark_lock(lock_path)
    evaluators: dict[str, Any] = {}

    for benchmark in BENCHMARK_KEYS:
        lock_entry = lock.get(LOCK_BENCHMARK_ID[benchmark])
        if lock_entry is None:
            raise RegistryError(
                f"benchmark-registry.lock.yaml has no entry {LOCK_BENCHMARK_ID[benchmark]!r}"
            )
        head = resolver.head(EVALUATOR_REPOSITORIES[benchmark])
        if not HEX40.match(head):
            raise SourceUnavailableError(f"{benchmark} head {head!r} is not a 40-hex commit id")
        decision = (
            _parsebench_decision(head)
            if head != HISTORICAL_PINS[benchmark]
            else _unchanged_decision(benchmark, head)
        )
        if head != HISTORICAL_PINS[benchmark] and benchmark != "parsebench":
            raise RegistryError(
                f"{benchmark} upstream head {head} differs from the historical pin "
                f"{HISTORICAL_PINS[benchmark]}, but only ParseBench has a reviewed "
                "diff. Review the diff and write a rationale before pinning."
            )
        evaluators[benchmark] = build_evaluator_record(
            benchmark,
            lock_entry=lock_entry,
            upstream_head=head,
            decision=decision,
            resolved_at=resolved_at,
        )

    toolkit_head = resolver.head(OLMOCR_TOOLKIT_REPOSITORY)
    if not HEX40.match(toolkit_head):
        raise SourceUnavailableError(f"olmOCR toolkit head {toolkit_head!r} is not 40-hex")

    return {
        "schema": EVALUATOR_REGISTRY_SCHEMA_ID,
        "campaign_id": CAMPAIGN_ID,
        "generated_at": resolved_at,
        "evaluator_count": len(evaluators),
        "evaluators": evaluators,
        "olmocr_toolkit": {
            "repository": OLMOCR_TOOLKIT_REPOSITORY,
            "revision": toolkit_head,
            "role": (
                "Not an evaluator. It pins the prompt builder and the page renderer that "
                "the olmocr2 model runtime uses, so it is frozen with the evaluators."
            ),
            "license": "Apache-2.0",
        },
    }


__all__ = [
    "ACQUIRED_DIR",
    "EVALUATOR_RECORD_SCHEMA_ID",
    "EVALUATOR_REGISTRY_SCHEMA_ID",
    "EVALUATOR_REPOSITORIES",
    "GT_PATHS",
    "OBSERVED_HEADS",
    "OLMOCR_PROVENANCE",
    "OLMOCR_TOOLKIT_REPOSITORY",
    "GitRefResolver",
    "LiveGitRefResolver",
    "MainPinDecision",
    "RecordedGitRefResolver",
    "build_evaluator_record",
    "load_benchmark_lock",
    "missing_gt_paths",
    "resolve_evaluators",
]
