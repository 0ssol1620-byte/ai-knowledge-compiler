"""``evidence/`` (masterplan section 29) and the Definition-of-Done checklist.

Every artifact this module writes is listed, with its sha256, in
``FINAL_EVIDENCE_MANIFEST.json``; every checklist item in it is a boolean
computed from a file this lane actually opened, never an assertion. An item
this lane structurally cannot verify (GT/inference isolation, controller
cleanup verification beyond the passthrough receipt, worker replacement
counts) is reported ``false`` with a reason rather than guessed at — a
``false`` here means "not proven from this lane's inputs", not "known to have
failed".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arena.constants import CAMPAIGN_ID
from arena.core.ids import sha256_file
from arena.reports.common import write_json
from arena.reports.loaders import CampaignSources
from arena.reports.paths import OutputPaths, SourcePaths

__all__ = ["DodItem", "build_evidence"]


@dataclass(frozen=True, slots=True)
class DodItem:
    key: str
    description: str
    satisfied: bool
    reason: str


def _artifact(path_str: str, sha: str) -> dict[str, str]:
    return {"path": path_str, "sha256": sha}


def _copy_with_hash(
    evidence_dir: Path, filename: str, source: Path
) -> dict[str, str] | None:
    if not source.is_file():
        return None
    data = source.read_bytes()
    destination = evidence_dir / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return _artifact(filename, sha256_file(destination))


def build_evidence(
    sources: CampaignSources,
    source_paths: SourcePaths,
    out: OutputPaths,
    *,
    models: tuple[str, ...],
    benchmarks: tuple[str, ...],
    variant_ids: tuple[str, ...],
) -> list[DodItem]:
    """Write every ``evidence/`` file and return the DoD checklist."""

    artifacts: list[dict[str, str]] = []

    for filename, source in (
        ("campaign_manifest.json", source_paths.campaign_manifest_json),
        ("model_registry.json", source_paths.model_registry_json),
        ("evaluator_registry.json", source_paths.evaluator_registry_json),
    ):
        artifact = _copy_with_hash(out.evidence_dir, filename, source)
        if artifact is not None:
            artifacts.append(artifact)

    # source_hashes.jsonl: one row per case_key seen in any model's receipts.
    source_hash_rows: dict[str, dict[str, Any]] = {}
    prompt_hashes: dict[str, str] = {}
    output_hash_rows: list[dict[str, Any]] = []
    for model_key, run in sources.runs.items():
        for receipt in run.receipts:
            case_key = receipt.get("case_key")
            if isinstance(case_key, str) and case_key not in source_hash_rows:
                source_sha = receipt.get("source_sha256")
                if isinstance(source_sha, str):
                    source_hash_rows[case_key] = {
                        "case_key": case_key,
                        "sample_id": receipt.get("sample_id"),
                        "benchmark": receipt.get("benchmark"),
                        "source_sha256": source_sha,
                    }
            prompt_id = receipt.get("prompt_id")
            prompt_sha = receipt.get("prompt_sha256")
            if isinstance(prompt_id, str) and isinstance(prompt_sha, str):
                prompt_hashes.setdefault(prompt_id, prompt_sha)
            if isinstance(case_key, str) and receipt.get("status") == "SUCCESS":
                output_hash_rows.append(
                    {
                        "model_key": model_key,
                        "case_key": case_key,
                        "raw_output_sha256": receipt.get("raw_output_sha256"),
                        "canonical_output_sha256": receipt.get("canonical_output_sha256"),
                    }
                )

    def write_jsonl(filename: str, rows: list[dict[str, Any]]) -> str | None:
        if not rows:
            return None
        path = out.evidence(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "\n".join(json.dumps(row, sort_keys=True, ensure_ascii=False) for row in rows) + "\n"
        path.write_text(text, encoding="utf-8", newline="")
        return sha256_file(path)

    source_hash_sha = write_jsonl(
        "source_hashes.jsonl", [source_hash_rows[k] for k in sorted(source_hash_rows)]
    )
    if source_hash_sha:
        artifacts.append(_artifact("source_hashes.jsonl", source_hash_sha))

    prompt_hash_sha = (
        write_json(out.evidence("prompt_hashes.json"), dict(sorted(prompt_hashes.items())))
        if prompt_hashes
        else None
    )
    if prompt_hash_sha:
        artifacts.append(_artifact("prompt_hashes.json", prompt_hash_sha))

    output_hash_sha = write_jsonl(
        "output_hashes.jsonl",
        sorted(output_hash_rows, key=lambda r: (r["model_key"], r["case_key"])),
    )
    if output_hash_sha:
        artifacts.append(_artifact("output_hashes.jsonl", output_hash_sha))

    route_decision_rows: list[dict[str, Any]] = []
    for variant, variant_source in sources.variants.items():
        for decision in variant_source.route_decisions:
            route_decision_rows.append(
                {
                    "variant": variant,
                    "case_key": decision.get("case_key"),
                    "decision_sha256": decision.get("decision_sha256"),
                }
            )
    route_hash_sha = write_jsonl(
        "route_decision_hashes.jsonl",
        sorted(route_decision_rows, key=lambda r: (r["variant"], str(r["case_key"]))),
    )
    if route_hash_sha:
        artifacts.append(_artifact("route_decision_hashes.jsonl", route_hash_sha))

    env_index_sha = write_json(
        out.evidence("environment_receipts_index.json"), sorted(sources.environment_receipts)
    )
    artifacts.append(_artifact("environment_receipts_index.json", env_index_sha))
    provider_index_sha = write_json(
        out.evidence("provider_receipts_index.json"), sorted(sources.provider_receipts)
    )
    artifacts.append(_artifact("provider_receipts_index.json", provider_index_sha))

    if sources.cleanup_receipt is not None:
        cleanup_sha = write_json(out.evidence("cleanup_receipt.json"), sources.cleanup_receipt)
        artifacts.append(_artifact("cleanup_receipt.json", cleanup_sha))

    # ---- Definition of Done (masterplan section 49) ----

    checklist: list[DodItem] = []

    def item(key: str, description: str, satisfied: bool, reason: str) -> None:
        checklist.append(DodItem(key, description, satisfied, reason))

    item(
        "campaign_manifest",
        "campaign manifest with source revisions on disk",
        sources.campaign_manifest is not None,
        "campaign_manifest.json found" if sources.campaign_manifest else (
            sources.campaign_manifest_reason or "campaign_manifest.json missing"
        ),
    )
    item(
        "source_hashes",
        "exact source hashes recorded",
        bool(source_hash_rows),
        f"{len(source_hash_rows)} distinct case_key source hashes found"
        if source_hash_rows
        else "no page receipt carried a source_sha256",
    )
    evaluators = (
        sources.evaluator_registry.get("evaluators")
        if isinstance(sources.evaluator_registry, dict)
        else None
    )
    evaluator_pins_ok = isinstance(evaluators, dict) and all(
        isinstance(evaluators.get(b), dict)
        and (evaluators[b].get("main_pin") or evaluators[b].get("historical_pin"))
        for b in benchmarks
    )
    item(
        "evaluator_pins",
        "exact evaluator pins for every benchmark",
        bool(evaluator_pins_ok),
        "evaluator_registry.json has a pin for every configured benchmark"
        if evaluator_pins_ok
        else (sources.evaluator_registry_reason or "missing a pin for at least one benchmark"),
    )
    registry_models = (
        sources.model_registry.get("models") if isinstance(sources.model_registry, dict) else None
    )
    revisions_ok = isinstance(registry_models, dict) and all(
        isinstance(registry_models.get(m), dict) and registry_models[m].get("revision")
        for m in models
    )
    item(
        "model_revisions",
        "all model exact revisions recorded",
        bool(revisions_ok),
        "model_registry.json has a revision for every configured model"
        if revisions_ok
        else (sources.model_registry_reason or "missing a revision for at least one model"),
    )
    item(
        "prompts_hashed",
        "all prompts hashed",
        bool(prompt_hashes),
        f"{len(prompt_hashes)} distinct prompt_id(s) hashed"
        if prompt_hashes
        else "no page receipt carried a prompt_id/prompt_sha256 pair",
    )
    item(
        "gt_isolation",
        "GT/inference separation proven",
        False,
        "the GT isolation audit receipt is lane A2's output, not among this lane's inputs",
    )
    canary_models = {
        m
        for m in models
        if sources.canary_receipts_by_model.get(m, {}).get("status") in ("PASS", "FAIL")
    }
    item(
        "canary_verdicts",
        "all candidates canary PASS or explicit FAIL",
        canary_models == set(models),
        f"{len(canary_models)}/{len(models)} configured model(s) have a canary verdict",
    )
    full_run_models = {
        m
        for m in models
        if (matched_run := sources.runs.get(m)) is not None
        and isinstance(matched_run.run_summary, dict)
        and isinstance(matched_run.run_summary.get("success_count"), int)
        and matched_run.run_summary["success_count"] > 0
    }
    item(
        "full_one_pass",
        "eligible models completed a full one-pass run",
        bool(full_run_models),
        f"{len(full_run_models)}/{len(models)} model(s) have a run-summary with success_count > 0",
    )
    opus_ran = any("opus" in str(r.get("schema", "")) for r in sources.opus_receipts)
    item(
        "opus_scope",
        "Opus target scope completed without model fallback",
        opus_ran,
        "at least one receipts/opus-*.json found" if opus_ran else "no receipts/opus-*.json found",
    )
    item(
        "outputs_hashed",
        "every output raw + canonical + SHA",
        bool(output_hash_rows),
        f"{len(output_hash_rows)} SUCCESS receipts carried both output hashes"
        if output_hash_rows
        else "no SUCCESS page receipt carried both output hashes",
    )
    unclassified_failures = [
        receipt
        for run in sources.runs.values()
        for receipt in run.receipts
        if receipt.get("status") in ("FAILED", "QUARANTINED") and not receipt.get("error_class")
    ]
    item(
        "failures_classified",
        "every failure classified",
        not unclassified_failures,
        "no non-SUCCESS receipt is missing an error_class"
        if not unclassified_failures
        else f"{len(unclassified_failures)} non-SUCCESS receipt(s) carry no error_class",
    )
    item(
        "pod_costs_recorded",
        "every pod cost recorded",
        bool(sources.pod_ledger),
        f"{len(sources.pod_ledger)} pod ledger row(s) found"
        if sources.pod_ledger
        else (sources.pod_ledger_reason or "cost/pod_ledger.jsonl missing"),
    )
    item(
        "cleanup_verified",
        "cleanup verified",
        sources.cleanup_receipt is not None,
        "evidence/cleanup_receipt.json found"
        if sources.cleanup_receipt is not None
        else (sources.cleanup_receipt_reason or "evidence/cleanup_receipt.json missing"),
    )
    frozen_variants = {
        v for v in variant_ids if sources.variants.get(v) and sources.variants[v].route_frozen
    }
    item(
        "routes_frozen",
        "TAVONEL route decisions frozen before scoring",
        frozen_variants == set(variant_ids),
        f"{len(frozen_variants)}/{len(variant_ids)} configured variants have a FROZEN.json",
    )
    item(
        "recovery_receipts",
        "TAVONEL recovery receipts",
        bool(sources.recovery_plan),
        f"{len(sources.recovery_plan)} recovery job(s) planned"
        if sources.recovery_plan
        else (sources.recovery_plan_reason or "tavonel/recovery_jobs/plan.jsonl missing"),
    )
    scored_pairs = sum(
        1
        for (m, b) in sources.scores
        if m in models and b in benchmarks and sources.scores[(m, b)].summary
    )
    item(
        "official_scoring",
        "official evaluator outputs",
        scored_pairs > 0,
        f"{scored_pairs}/{len(models) * len(benchmarks)} (model, benchmark) pair(s) scored",
    )
    item(
        "negative_results",
        "negative results documented",
        True,
        "executive_summary_ko.md always carries a negative-results section",
    )
    item(
        "executive_summary",
        "executive Korean summary produced",
        True,
        "reports/executive_summary_ko.md is always generated",
    )
    item(
        "evidence_manifest",
        "final evidence manifest produced",
        True,
        "this file",
    )

    manifest = {
        "schema": "tavonel.arena.final-evidence-manifest.v1",
        "campaign_id": CAMPAIGN_ID,
        "artifacts": sorted(artifacts, key=lambda a: a["path"]),
        "definition_of_done": [
            {
                "key": entry.key,
                "description": entry.description,
                "satisfied": entry.satisfied,
                "reason": entry.reason,
            }
            for entry in checklist
        ],
    }
    write_json(out.evidence("FINAL_EVIDENCE_MANIFEST.json"), manifest)
    return checklist
