"""Orchestrate every MP section 29 report file from one call.

:func:`build_reports` is the single entry point both the CLI and the tests
use. It loads every input once (:mod:`arena.reports.loaders`), then calls one
generator per output file, writing CSV/Markdown under ``--out`` and, when
``with_evidence`` is set, the evidence bundle under the sibling ``evidence/``
directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.constants import BENCHMARK_KEYS, MODEL_KEYS
from arena.reports.common import write_csv, write_text
from arena.reports.evidence import DodItem, build_evidence
from arena.reports.loaders import CampaignSources, load_campaign_sources
from arena.reports.narrative import build_executive_summary_ko, build_methodology
from arena.reports.paths import OutputPaths, SourcePaths
from arena.reports.tables_core import (
    build_benchmark_breakdown,
    build_cost_report,
    build_document_type_breakdown,
    build_failure_taxonomy,
    build_gpu_resource_report,
    build_latency_report,
    build_leaderboard,
    build_reliability_report,
    build_runtime_failures,
    leaderboard_markdown,
)
from arena.reports.tables_tavonel import (
    build_model_disagreement,
    build_opus_subscription_report,
    build_pareto_frontier,
    build_recovery_report,
    build_tavonel_ablation,
    build_tavonel_routes,
)
from arena.reports.variant_ids import VARIANT_IDS, variant_dir_name

__all__ = ["BuildResult", "build_reports"]


@dataclass(frozen=True, slots=True)
class BuildResult:
    reports_written: tuple[str, ...]
    evidence_written: tuple[str, ...] = ()
    dod_checklist: tuple[DodItem, ...] = field(default_factory=tuple)


def build_reports(
    *,
    source_root: SourcePaths | None = None,
    out_dir_name: str = "reports",
    with_evidence: bool = False,
    models: tuple[str, ...] = MODEL_KEYS,
    benchmarks: tuple[str, ...] = BENCHMARK_KEYS,
    variant_ids: tuple[str, ...] = VARIANT_IDS,
) -> BuildResult:
    """Load every input once and write every masterplan section 29 file."""

    source_paths = source_root or SourcePaths.default()
    out = OutputPaths.under(source_paths.root / out_dir_name)
    variant_dir_names = {variant: variant_dir_name(variant) for variant in variant_ids}

    sources: CampaignSources = load_campaign_sources(
        source_paths,
        models=models,
        benchmarks=benchmarks,
        variant_dir_names=variant_dir_names,
    )

    written: list[str] = []

    leaderboard = build_leaderboard(sources, models)
    write_csv(out.report("leaderboard.csv"), leaderboard)
    write_text(out.report("LEADERBOARD.md"), leaderboard_markdown(leaderboard))
    written += ["leaderboard.csv", "LEADERBOARD.md"]

    write_csv(
        out.report("benchmark_breakdown.csv"),
        build_benchmark_breakdown(sources, models, benchmarks),
    )
    written.append("benchmark_breakdown.csv")

    document_type_breakdown = build_document_type_breakdown(sources, models, benchmarks)
    write_csv(out.report("document_type_breakdown.csv"), document_type_breakdown)
    written.append("document_type_breakdown.csv")

    write_csv(out.report("latency_report.csv"), build_latency_report(sources, models))
    written.append("latency_report.csv")

    write_csv(out.report("gpu_resource_report.csv"), build_gpu_resource_report(sources, models))
    written.append("gpu_resource_report.csv")

    write_csv(out.report("cost_report.csv"), build_cost_report(sources, models))
    written.append("cost_report.csv")

    write_csv(out.report("reliability_report.csv"), build_reliability_report(sources, models))
    written.append("reliability_report.csv")

    write_csv(out.report("failure_taxonomy.csv"), build_failure_taxonomy(sources))
    written.append("failure_taxonomy.csv")

    write_csv(out.report("runtime_failures.csv"), build_runtime_failures(sources, models))
    written.append("runtime_failures.csv")

    write_csv(out.report("tavonel_ablation.csv"), build_tavonel_ablation(sources))
    written.append("tavonel_ablation.csv")

    tavonel_routes = build_tavonel_routes(sources)
    write_csv(out.report("tavonel_routes.csv"), tavonel_routes)
    written.append("tavonel_routes.csv")

    write_csv(out.report("recovery_report.csv"), build_recovery_report(sources))
    written.append("recovery_report.csv")

    write_csv(
        out.report("opus_subscription_report.csv"), build_opus_subscription_report(sources)
    )
    written.append("opus_subscription_report.csv")

    write_csv(out.report("model_disagreement.csv"), build_model_disagreement(sources))
    written.append("model_disagreement.csv")

    write_csv(
        out.report("pareto_frontier.csv"), build_pareto_frontier(sources, models, benchmarks)
    )
    written.append("pareto_frontier.csv")

    write_text(
        out.report("executive_summary_ko.md"),
        build_executive_summary_ko(
            leaderboard=leaderboard,
            document_type_breakdown=document_type_breakdown,
            tavonel_routes=tavonel_routes,
        ),
    )
    written.append("executive_summary_ko.md")

    write_text(
        out.report("methodology.md"),
        build_methodology(evaluator_registry=sources.evaluator_registry),
    )
    written.append("methodology.md")

    dod_checklist: tuple[DodItem, ...] = ()
    evidence_written: tuple[str, ...] = ()
    if with_evidence:
        checklist = build_evidence(
            sources,
            source_paths,
            out,
            models=models,
            benchmarks=benchmarks,
            variant_ids=variant_ids,
        )
        dod_checklist = tuple(checklist)
        evidence_written = tuple(
            sorted(p.name for p in out.evidence_dir.glob("*") if p.is_file())
        )

    return BuildResult(
        reports_written=tuple(written),
        evidence_written=evidence_written,
        dod_checklist=dod_checklist,
    )
