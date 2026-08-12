"""EXP-0103 fixture build — queries, gold evidence, cross-tenant probes.

    .venv/Scripts/python.exe research/experiments/EXP-0103/scripts/build_fixture.py

**This builds the dataset. It does not run the experiment.** Contract C's
challenger -- intent-driven granularity plus score-distribution adaptive-k -- is
not implemented, no retrieval is executed, and no metric in Contract C's list is
measured here. The approved execution order puts EXP-0101 first and this round
stops at fixture readiness, which `metrics/fixture-readiness.json` states as a
readiness verdict rather than a result.

`metrics/` therefore holds a readiness record and no measurements, and
`normalized/`, `tables/` and `figures/` are deliberately absent: there is
nothing yet to normalise, tabulate or plot, and creating them empty would
suggest otherwise.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EXPERIMENT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "absorption" / "src"))

from akc_absorption.retrieval_fixture import (  # noqa: E402
    FIXTURE_VERSION,
    RetrievalIntent,
    UnitGranularity,
    VersionState,
    build_retrieval_fixture,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # LF explicitly -- see the note in EXP-0101's run_experiment._write_json.
        newline="\n",
    )


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"
    return result.stdout.strip()


def main() -> int:
    fixture = build_retrieval_fixture()
    _write_json(EXPERIMENT / "raw" / "retrieval-fixture.json", fixture.as_record())

    by_granularity: dict[str, int] = {item.value: 0 for item in UnitGranularity}
    for unit in fixture.units:
        by_granularity[unit.granularity.value] += 1
    by_intent: dict[str, int] = {item.value: 0 for item in RetrievalIntent}
    for query in fixture.queries:
        by_intent[query.intent.value] += 1

    superseded = sum(
        1 for unit in fixture.units if unit.version_state is VersionState.SUPERSEDED
    )
    version_sensitive = sum(
        1
        for query in fixture.queries
        if len(query.version_correct_unit_ids) < len(query.gold_unit_ids)
    )
    forbidden_total = sum(len(probe.forbidden_unit_ids) for probe in fixture.probes)

    _write_json(
        EXPERIMENT / "metrics" / "fixture-readiness.json",
        {
            "experiment": "EXP-0103",
            "status": "FIXTURE_ONLY - no retrieval executed, no Contract C metric measured",
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
            "role": {
                "this_fixture": "DEVELOPMENT_AND_CALIBRATION",
                "may_be_used_for": [
                    "building the retriever",
                    "choosing K_MIN / K_MAX and the cutoff estimator",
                    "debugging and unit tests",
                ],
                "may_not_be_used_for": [
                    "any reported result",
                    "any comparison between CURRENT, baseline and challenger",
                    "any public number",
                ],
                "evidence_fixture": (
                    "The public structured-filing arm is the holdout and the "
                    "evidence. It is unbuilt. See "
                    "docs/research/EXP-0103_STRUCTURED_FILING_DATASET_CONTRACT.md."
                ),
                "why": (
                    "These units are generated, so a query's lexical overlap with "
                    "its own gold evidence is cleaner than any real corpus. "
                    "Calibrating here and reporting here would produce a number "
                    "nobody can defend. Contract 0.9 also applies to the holdout: "
                    "fitting a threshold after seeing its labels burns it."
                ),
            },
            "retrieval_start_gate": {
                "status": "BLOCKED",
                "reason": (
                    "Founder directive 2026-08-12: close the missing dataset arm "
                    "first. Order is SEC XBRL extraction -> OpenDART extraction -> "
                    "query/gold generation -> cross-tenant probe validation -> "
                    "frozen manifest -> CURRENT vs baseline vs challenger."
                ),
                "blocking_precondition": "INTAKE-0103",
            },
            "fixture_version": FIXTURE_VERSION,
            "manifest_sha256": fixture.manifest_sha256,
            "counts": {
                "units": len(fixture.units),
                "queries": len(fixture.queries),
                "unauthorized_probes": len(fixture.probes),
                "forbidden_unit_assertions": forbidden_total,
                "tenants": len({unit.tenant_id for unit in fixture.units}),
                "units_by_granularity": by_granularity,
                "queries_by_intent": by_intent,
                "superseded_units": superseded,
                "version_sensitive_queries": version_sensitive,
                "critical_queries": sum(1 for query in fixture.queries if query.critical),
            },
            "ready": {
                "recall_at_budget": "gold evidence exists for every query",
                "critical_evidence_recall": "critical queries flagged",
                "version_correct_recall": (
                    f"{version_sensitive} queries have a superseded alternative"
                ),
                "unauthorized_candidate_rate": (
                    f"{len(fixture.probes)} probes, each naming units the asker "
                    "must never be offered, crossed over every ordered tenant pair"
                ),
                "granularity_selection": (
                    "every fact is stated at cell, row and claim granularity, so "
                    "choosing the wrong one is observable"
                ),
            },
            "not_built": {
                "unexercised_intents": sorted(
                    name for name, count in by_intent.items() if count == 0
                ),
                "unexercised_granularities": sorted(
                    name for name, count in by_granularity.items() if count == 0
                ),
                "unexercised_note": (
                    "ENTITY, RELATION and IMPACT need an entity or dependency "
                    "graph over the units, and PARAGRAPH needs prose units that "
                    "are neither a claim nor a section. Neither exists in this "
                    "fixture, so those intent classes are declared and untested "
                    "rather than covered."
                ),
                "sec_xbrl_and_opendart_truth": (
                    "queries_from_structured_facts is implemented and exercised by "
                    "a unit test, and NO filing extract exists in this repository, "
                    "so nothing has been run through it. Contract C's first "
                    "dataset arm is unbuilt."
                ),
                "visual_page_lane": "excluded from this batch by Contract C",
                "context_token_and_latency_metrics": (
                    "require a running retriever; none is implemented here"
                ),
                "downstream_qa_accuracy": (
                    "requires one frozen LLM and an API credential; credential-gated"
                ),
            },
            "external_validity_warning": (
                "The units are generated, not filings. Lexical overlap between a "
                "query and its gold evidence is therefore cleaner than any real "
                "corpus, and an adaptive-k cutoff estimated from this score "
                "distribution should not be assumed to transfer."
            ),
        },
    )

    _write_json(
        EXPERIMENT / "manifest.json",
        {
            "experiment": "EXP-0103",
            "contract": "docs/research/ABSORPTION_EXPERIMENT_CONTRACTS_BATCH1.md, Contract C",
            "dataset_contract": (
                "docs/research/EXP-0103_STRUCTURED_FILING_DATASET_CONTRACT.md"
            ),
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
            "role": "DEVELOPMENT_AND_CALIBRATION - not the evidence fixture",
            "scope_this_round": "fixture only",
            "corpus_manifest_sha256": fixture.manifest_sha256,
            "git_commit": _git_commit(),
            "config_sha256": "sha256:"
            + hashlib.sha256(
                json.dumps({"fixture_version": FIXTURE_VERSION}, sort_keys=True).encode(
                    "utf-8"
                )
            ).hexdigest(),
            "seeds": "sha256 over seed strings; no PRNG",
            "model_registry_ids": [],
            "prompt_receipt_sha256": [],
            "split_definition": (
                "None yet. Contract C 0.9 holdout hygiene applies the moment a "
                "threshold is fitted; nothing is fitted here, so no holdout has "
                "been spent and the whole fixture is still available as one."
            ),
            "unpopulated_directories": {
                "normalized": "nothing to normalise until retrieval runs",
                "tables": "no measurement to tabulate",
                "figures": "no measurement to plot",
            },
        },
    )

    entries: list[dict[str, str]] = []
    for path in sorted(EXPERIMENT.rglob("*")):
        if not path.is_file() or path.name == "receipts.json":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(
            {
                "path": path.relative_to(EXPERIMENT).as_posix(),
                "sha256": f"sha256:{digest}",
                "bytes": str(path.stat().st_size),
            }
        )
    _write_json(
        EXPERIMENT / "receipts" / "receipts.json",
        {
            "experiment": "EXP-0103",
            "note": (
                "Fixture receipts. No number in this directory is a measurement of "
                "a retrieval system; they are counts of what the fixture contains."
            ),
            "artifacts": entries,
        },
    )
    print(
        f"EXP-0103 fixture: {len(fixture.units)} units, {len(fixture.queries)} queries, "
        f"{len(fixture.probes)} probes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
