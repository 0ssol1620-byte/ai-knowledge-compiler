"""Raw readers for every input this lane is allowed to touch.

Every function here is a thin, defensive wrapper around one file or one glob:
it returns whatever JSON/JSONL is on disk, or an explicit "why not" when it is
absent. Nothing here interprets a field's meaning — that is :mod:`metrics` and
:mod:`tavonel_data`. Keeping the split means a table generator never has to
know whether a number came from a page receipt or a pod ledger row; it asks
the aggregation layer, which asks these readers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from arena.reports.common import read_json_optional, read_jsonl_optional
from arena.reports.paths import SourcePaths

__all__ = [
    "CampaignSources",
    "load_campaign_sources",
]


@dataclass(frozen=True, slots=True)
class ScoreSource:
    """Everything read for one ``(model_key, benchmark)`` scoring cell."""

    summary: dict[str, Any] | None
    summary_reason: str | None
    per_case: list[dict[str, Any]] | None
    per_case_reason: str | None


@dataclass(frozen=True, slots=True)
class ModelRunSource:
    """Everything read for one model's ``runs/<model_key>/`` tree."""

    receipts: list[dict[str, Any]]
    run_summary: dict[str, Any] | None
    run_summary_reason: str | None
    canary_receipt: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class VariantSource:
    """Everything read for one TAVONEL variant."""

    route_decisions: list[dict[str, Any]]
    route_frozen: dict[str, Any] | None
    replay_manifest: list[dict[str, Any]]
    replay_summary: dict[str, Any] | None
    cost: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class CampaignSources:
    """Every raw input the report generators may read, loaded once."""

    root_exists: bool
    scores: dict[tuple[str, str], ScoreSource] = field(default_factory=dict)
    runs: dict[str, ModelRunSource] = field(default_factory=dict)
    pod_ledger: list[dict[str, Any]] = field(default_factory=list)
    pod_ledger_reason: str | None = None
    errors: list[dict[str, Any]] = field(default_factory=list)
    errors_reason: str | None = None
    model_registry: dict[str, Any] | None = None
    model_registry_reason: str | None = None
    evaluator_registry: dict[str, Any] | None = None
    evaluator_registry_reason: str | None = None
    campaign_manifest: dict[str, Any] | None = None
    campaign_manifest_reason: str | None = None
    canary_receipts_by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    opus_receipts: list[dict[str, Any]] = field(default_factory=list)
    recovery_plan: list[dict[str, Any]] = field(default_factory=list)
    recovery_plan_reason: str | None = None
    disagreement_pairs: list[dict[str, Any]] = field(default_factory=list)
    disagreement_pairs_reason: str | None = None
    variants: dict[str, VariantSource] = field(default_factory=dict)
    environment_receipts: list[str] = field(default_factory=list)
    provider_receipts: list[str] = field(default_factory=list)
    cleanup_receipt: dict[str, Any] | None = None
    cleanup_receipt_reason: str | None = None


def _load_scores(
    paths: SourcePaths, models: tuple[str, ...], benchmarks: tuple[str, ...]
) -> dict[tuple[str, str], ScoreSource]:
    out: dict[tuple[str, str], ScoreSource] = {}
    for model_key in models:
        for benchmark in benchmarks:
            summary, summary_reason = read_json_optional(paths.summary_json(model_key, benchmark))
            per_case, per_case_reason = read_jsonl_optional(
                paths.per_case_jsonl(model_key, benchmark)
            )
            if summary is not None and not isinstance(summary, dict):
                summary, summary_reason = None, "summary.json is not a JSON object"
            out[(model_key, benchmark)] = ScoreSource(
                summary=summary,
                summary_reason=summary_reason,
                per_case=per_case,
                per_case_reason=per_case_reason,
            )
    return out


def _load_runs(paths: SourcePaths, models: tuple[str, ...]) -> dict[str, ModelRunSource]:
    out: dict[str, ModelRunSource] = {}
    for model_key in models:
        receipts: list[dict[str, Any]] = []
        receipts_dir = paths.receipts_dir(model_key)
        if receipts_dir.is_dir():
            for receipt_path in sorted(receipts_dir.glob("*.json")):
                payload, reason = read_json_optional(receipt_path)
                if isinstance(payload, dict):
                    receipts.append(payload)
                elif reason is None:
                    receipts.append({"_load_error": f"{receipt_path.name} is not an object"})
        run_summary, run_summary_reason = read_json_optional(paths.run_summary_json(model_key))
        if run_summary is not None and not isinstance(run_summary, dict):
            run_summary, run_summary_reason = None, "run-summary.json is not a JSON object"
        canary_payload: dict[str, Any] | None = None
        canary_path = paths.receipts_dir_root / f"canary-{model_key}.json"
        loaded, _ = read_json_optional(canary_path)
        if isinstance(loaded, dict):
            canary_payload = loaded
        out[model_key] = ModelRunSource(
            receipts=receipts,
            run_summary=run_summary,
            run_summary_reason=run_summary_reason,
            canary_receipt=canary_payload,
        )
    return out


def _load_variants(
    paths: SourcePaths, variant_dir_names: dict[str, str]
) -> dict[str, VariantSource]:
    out: dict[str, VariantSource] = {}
    for variant, dir_name in variant_dir_names.items():
        decisions_dir = paths.route_decisions_dir(dir_name)
        decisions: list[dict[str, Any]] = []
        frozen: dict[str, Any] | None = None
        if decisions_dir.is_dir():
            for decision_path in sorted(decisions_dir.glob("*.json")):
                if decision_path.name == "FROZEN.json":
                    loaded, _ = read_json_optional(decision_path)
                    frozen = loaded if isinstance(loaded, dict) else None
                    continue
                payload, _ = read_json_optional(decision_path)
                if isinstance(payload, dict):
                    decisions.append(payload)
        manifest_rows, _ = read_jsonl_optional(paths.replay_manifest(dir_name))
        summary, _ = read_json_optional(paths.replay_summary(dir_name))
        cost, _ = read_json_optional(paths.variant_cost_json(dir_name))
        out[variant] = VariantSource(
            route_decisions=decisions,
            route_frozen=frozen,
            replay_manifest=manifest_rows or [],
            replay_summary=summary if isinstance(summary, dict) else None,
            cost=cost if isinstance(cost, dict) else None,
        )
    return out


def load_campaign_sources(
    paths: SourcePaths,
    *,
    models: tuple[str, ...],
    benchmarks: tuple[str, ...],
    variant_dir_names: dict[str, str],
) -> CampaignSources:
    """Read every input file this lane may touch, once, tolerating absence."""

    pod_ledger, pod_ledger_reason = read_jsonl_optional(paths.pod_ledger)
    errors, errors_reason = read_jsonl_optional(paths.errors_log)
    model_registry, model_registry_reason = read_json_optional(paths.model_registry_json)
    if model_registry is not None and not isinstance(model_registry, dict):
        model_registry, model_registry_reason = None, "model_registry.json is not a JSON object"
    evaluator_registry, evaluator_registry_reason = read_json_optional(
        paths.evaluator_registry_json
    )
    if evaluator_registry is not None and not isinstance(evaluator_registry, dict):
        evaluator_registry = None
        evaluator_registry_reason = "evaluator_registry.json is not a JSON object"
    campaign_manifest, campaign_manifest_reason = read_json_optional(paths.campaign_manifest_json)
    if campaign_manifest is not None and not isinstance(campaign_manifest, dict):
        campaign_manifest = None
        campaign_manifest_reason = "campaign_manifest.json is not an object"

    opus_receipts: list[dict[str, Any]] = []
    for opus_path in paths.glob_opus_receipts():
        payload, _ = read_json_optional(opus_path)
        if isinstance(payload, dict):
            opus_receipts.append(payload)

    recovery_plan, recovery_plan_reason = read_jsonl_optional(paths.recovery_plan)
    disagreement_pairs, disagreement_pairs_reason = read_jsonl_optional(paths.disagreement_pairs)

    cleanup_receipt, cleanup_receipt_reason = read_json_optional(paths.cleanup_receipt_json)
    if cleanup_receipt is not None and not isinstance(cleanup_receipt, dict):
        cleanup_receipt, cleanup_receipt_reason = None, "cleanup_receipt.json is not an object"

    environment_receipts = (
        sorted(p.name for p in paths.environment_receipts_dir.iterdir() if p.is_file())
        if paths.environment_receipts_dir.is_dir()
        else []
    )
    provider_receipts = (
        sorted(p.name for p in paths.provider_receipts_dir.iterdir() if p.is_file())
        if paths.provider_receipts_dir.is_dir()
        else []
    )

    canary_receipts_by_model: dict[str, dict[str, Any]] = {}
    for model_key in models:
        payload, _ = read_json_optional(paths.receipts_dir_root / f"canary-{model_key}.json")
        if isinstance(payload, dict):
            canary_receipts_by_model[model_key] = payload

    return CampaignSources(
        root_exists=paths.root.is_dir(),
        scores=_load_scores(paths, models, benchmarks),
        runs=_load_runs(paths, models),
        pod_ledger=pod_ledger or [],
        pod_ledger_reason=pod_ledger_reason,
        errors=errors or [],
        errors_reason=errors_reason,
        model_registry=model_registry,
        model_registry_reason=model_registry_reason,
        evaluator_registry=evaluator_registry,
        evaluator_registry_reason=evaluator_registry_reason,
        campaign_manifest=campaign_manifest,
        campaign_manifest_reason=campaign_manifest_reason,
        canary_receipts_by_model=canary_receipts_by_model,
        opus_receipts=opus_receipts,
        recovery_plan=recovery_plan or [],
        recovery_plan_reason=recovery_plan_reason,
        disagreement_pairs=disagreement_pairs or [],
        disagreement_pairs_reason=disagreement_pairs_reason,
        variants=_load_variants(paths, variant_dir_names),
        environment_receipts=environment_receipts,
        provider_receipts=provider_receipts,
        cleanup_receipt=cleanup_receipt,
        cleanup_receipt_reason=cleanup_receipt_reason,
    )
