"""Score provenance - masterplan section 45.

    score
      -> evaluator version
      -> normalized output
      -> raw model output
      -> inference receipt
      -> model revision
      -> runtime image
      -> source SHA

:func:`build_provenance` produces the object every ``summary.json`` carries
(ARENA_CONTRACT section 3.11). :func:`verify_chain` walks the links for real:
it re-reads the bytes and compares them against the hashes the frozen manifest
and the page receipt recorded, so a broken link is found rather than assumed
away. A value that cannot be established is ``null`` beside the reason it is
absent - never a plausible-looking default.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.scoring import SCORING_LANE_VERSION, jsonio
from arena.scoring.errors import ProvenanceError
from arena.scoring.evaluators import LAYOUT_REVISION, EvaluatorLane
from arena.scoring.outputs import OutputRow, OutputSet, SourceIndex
from arena.scoring.paths import ScoringPaths

__all__ = [
    "CHAIN_SCHEMA",
    "CaseChain",
    "ChainReport",
    "build_provenance",
    "verify_chain",
    "write_chain",
]

CHAIN_SCHEMA: Final = "tavonel.arena.provenance-chain.v1"

_CHAIN_STEPS: Final = (
    "score_row",
    "normalized_output",
    "raw_output",
    "inference_receipt",
    "model_revision",
    "runtime_image",
    "source_sha",
)


def _unique_receipt_field(paths: ScoringPaths, output_set: OutputSet, field: str) -> str | None:
    values: set[str] = set()
    for row in output_set.rows:
        if row.receipt_path is None or not jsonio.io_path(row.receipt_path).is_file():
            continue
        document = jsonio.read_json(row.receipt_path)
        if not isinstance(document, Mapping):
            continue
        value = document.get(field)
        if isinstance(value, str) and value:
            values.add(value)
        if len(values) > 1:
            return None
    return next(iter(values)) if len(values) == 1 else None


def _normalization_revision(
    paths: ScoringPaths, output_set: OutputSet
) -> tuple[str | None, str]:
    """The canonicalisation that produced the markdown the evaluator scored."""

    if output_set.model_key is None:
        return None, (
            "a TAVONEL composite mixes canonicalisers from several models; the "
            "normalization revision of each page is the one recorded in that page's "
            "own model summary"
        )
    source = paths.canonicalizer_source(output_set.model_key)
    if not jsonio.io_path(source).is_file():
        return None, f"runtimes/{output_set.model_key}/canonical.py is not on disk at {source}"
    return jsonio.sha256_file(source), f"sha256 of {source}"


def build_provenance(
    paths: ScoringPaths,
    output_set: OutputSet,
    lane: EvaluatorLane,
    *,
    qa_report_sha256: str | None = None,
) -> dict[str, Any]:
    """ARENA_CONTRACT section 3.11's provenance object, plus what made it."""

    marker = output_set.marker or {}
    model_revision = marker.get("model_revision")
    if not isinstance(model_revision, str) or not model_revision:
        model_revision = _unique_receipt_field(paths, output_set, "model_revision")
    image_digest = marker.get("runtime_image_digest")
    if not isinstance(image_digest, str) or not image_digest:
        image_digest = _unique_receipt_field(paths, output_set, "runtime_image_digest")

    normalization, normalization_reason = _normalization_revision(paths, output_set)
    absent: list[dict[str, str]] = []
    if model_revision is None:
        absent.append(
            {
                "field": "model_revision",
                "reason": (
                    "no frozen marker and no single model_revision across the page "
                    "receipts (expected for a composite, which draws from several models)"
                ),
            }
        )
    if image_digest is None:
        absent.append(
            {
                "field": "runtime_image_digest",
                "reason": "no frozen marker and no single runtime_image_digest on the receipts",
            }
        )
    if normalization is None:
        absent.append({"field": "normalization_revision", "reason": normalization_reason})

    return {
        "campaign_id": CAMPAIGN_ID,
        "model_key": output_set.model_key,
        "variant": output_set.variant,
        "output_set_kind": output_set.kind,
        "model_revision": model_revision,
        "runtime_image_digest": image_digest,
        "frozen_manifest_sha256": output_set.manifest_sha256,
        "normalization_revision": normalization,
        "normalization_revision_source": normalization_reason,
        "evaluator_repository": lane.repository,
        "evaluator_revision": lane.revision,
        "evaluator_revision_source": lane.revision_source,
        "evaluator_lane": lane.lane,
        "evaluator_checkout": str(lane.checkout_dir),
        "evaluator_notes": list(lane.notes),
        "layout_revision": LAYOUT_REVISION,
        "scoring_lane_version": SCORING_LANE_VERSION,
        "qa_report_sha256": qa_report_sha256,
        "absent_fields": absent,
        "scored_at": jsonio.utc_now_iso(),
    }


@dataclass(frozen=True, slots=True)
class CaseChain:
    case_key: str
    steps: tuple[dict[str, Any], ...]

    @property
    def ok(self) -> bool:
        return all(step["ok"] for step in self.steps)

    def to_record(self) -> dict[str, Any]:
        return {"case_key": self.case_key, "ok": self.ok, "steps": list(self.steps)}


@dataclass(frozen=True, slots=True)
class ChainReport:
    key: str
    benchmark: str
    checked: int
    ok: int
    failures: tuple[CaseChain, ...]
    evaluator_link: dict[str, Any]
    provenance: Mapping[str, Any]

    @property
    def passed(self) -> bool:
        return bool(self.evaluator_link["ok"]) and self.checked > 0 and not self.failures

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": CHAIN_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "key": self.key,
            "benchmark": self.benchmark,
            "generated_at": jsonio.utc_now_iso(),
            "passed": self.passed,
            "chain": list(_CHAIN_STEPS),
            "cases_checked": self.checked,
            "cases_ok": self.ok,
            "failure_count": len(self.failures),
            "failures": [item.to_record() for item in self.failures],
            "evaluator_link": self.evaluator_link,
            "provenance": dict(self.provenance),
        }


def _step(name: str, ok: bool, detail: str, **extra: Any) -> dict[str, Any]:
    return {"step": name, "ok": ok, "detail": detail, **extra}


def _walk_case(
    row: OutputRow,
    *,
    scored_case_keys: set[str],
    source_index: SourceIndex,
    expected_model_revision: str | None,
    expected_image_digest: str | None,
) -> CaseChain:
    steps: list[dict[str, Any]] = []

    steps.append(
        _step(
            "score_row",
            row.case_key in scored_case_keys,
            "per_case.jsonl carries a row for this case_key",
        )
    )

    for name, path, recorded in (
        ("normalized_output", row.canonical_path, row.canonical_sha256),
        ("raw_output", row.raw_path, row.raw_sha256),
    ):
        if path is None or recorded is None:
            steps.append(
                _step(name, False, "the frozen manifest records no path or hash for this file")
            )
            continue
        if not jsonio.io_path(path).is_file():
            steps.append(_step(name, False, f"file is absent at {path}"))
            continue
        digest = jsonio.sha256_file(path)
        steps.append(
            _step(
                name,
                digest == recorded,
                "bytes on disk hash to the value the frozen manifest recorded",
                recorded=recorded,
                recomputed=digest,
            )
        )

    receipt: Mapping[str, Any] | None = None
    if row.receipt_path is not None and jsonio.io_path(row.receipt_path).is_file():
        loaded = jsonio.read_json(row.receipt_path)
        if isinstance(loaded, Mapping):
            receipt = loaded
    steps.append(
        _step(
            "inference_receipt",
            receipt is not None,
            "the page receipt is on disk and is a JSON object",
            path=str(row.receipt_path) if row.receipt_path is not None else None,
        )
    )
    if receipt is None:
        return CaseChain(case_key=row.case_key, steps=tuple(steps))

    observed_revision = receipt.get("model_revision")
    steps.append(
        _step(
            "model_revision",
            isinstance(observed_revision, str)
            and bool(observed_revision)
            and (expected_model_revision is None or observed_revision == expected_model_revision),
            "the receipt names the model revision the output set was frozen at",
            receipt=observed_revision,
            expected=expected_model_revision,
        )
    )
    observed_digest = receipt.get("runtime_image_digest")
    steps.append(
        _step(
            "runtime_image",
            isinstance(observed_digest, str)
            and bool(observed_digest)
            and (expected_image_digest is None or observed_digest == expected_image_digest),
            "the receipt names the runtime image the output set was frozen at",
            receipt=observed_digest,
            expected=expected_image_digest,
        )
    )
    source = source_index.get(row.case_key)
    observed_source = receipt.get("source_sha256")
    steps.append(
        _step(
            "source_sha",
            source is not None and observed_source == source.input_png_sha256,
            "the receipt's source hash is the staged input hash for this case_key",
            receipt=observed_source,
            source_manifest=None if source is None else source.input_png_sha256,
        )
    )
    return CaseChain(case_key=row.case_key, steps=tuple(steps))


def verify_chain(
    paths: ScoringPaths,
    output_set: OutputSet,
    lane: EvaluatorLane,
    benchmark: str,
    *,
    source_index: SourceIndex,
    sample_size: int | None = None,
    failure_sample: int = 25,
) -> ChainReport:
    """Walk every link from a score row back to the source page's sha256."""

    summary_path = paths.summary(output_set.key, benchmark)
    per_case_path = paths.per_case(output_set.key, benchmark)
    if not jsonio.io_path(summary_path).is_file():
        raise ProvenanceError(
            f"no summary at {summary_path}; score the benchmark before walking its chain"
        )
    summary = jsonio.read_json(summary_path)
    if not isinstance(summary, Mapping):
        raise ProvenanceError(f"{summary_path} is not a JSON object")

    recorded = summary.get("provenance")
    recorded_revision = (
        recorded.get("evaluator_revision") if isinstance(recorded, Mapping) else None
    )
    evaluator_link = _step(
        "evaluator_version",
        recorded_revision == lane.revision,
        "summary.json's provenance names the evaluator revision this lane resolves to",
        summary=recorded_revision,
        lane=lane.revision,
    )

    scored: set[str] = set()
    if jsonio.io_path(per_case_path).is_file():
        for record in jsonio.read_jsonl(per_case_path):
            case_key = record.get("case_key")
            if isinstance(case_key, str):
                scored.add(case_key)

    provenance = build_provenance(paths, output_set, lane)
    expected_revision = provenance.get("model_revision")
    expected_digest = provenance.get("runtime_image_digest")

    rows: Sequence[OutputRow] = [
        row for row in output_set.for_benchmark(benchmark) if row.has_output
    ]
    if sample_size is not None:
        rows = rows[:sample_size]

    chains = [
        _walk_case(
            row,
            scored_case_keys=scored,
            source_index=source_index,
            expected_model_revision=(
                expected_revision if isinstance(expected_revision, str) else None
            ),
            expected_image_digest=expected_digest if isinstance(expected_digest, str) else None,
        )
        for row in rows
    ]
    failures = tuple(chain for chain in chains if not chain.ok)
    return ChainReport(
        key=output_set.key,
        benchmark=benchmark,
        checked=len(chains),
        ok=len(chains) - len(failures),
        failures=failures[:failure_sample],
        evaluator_link=evaluator_link,
        provenance=provenance,
    )


def write_chain(paths: ScoringPaths, report: ChainReport) -> tuple[Path, str]:
    path = paths.provenance_chain(report.key)
    existing: dict[str, Any] = {}
    if jsonio.io_path(path).is_file():
        loaded = jsonio.read_json(path)
        if isinstance(loaded, Mapping):
            existing = dict(loaded)
    benchmarks = existing.get("benchmarks")
    document: dict[str, Any] = {
        "schema": CHAIN_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "key": report.key,
        "generated_at": jsonio.utc_now_iso(),
        "benchmarks": dict(benchmarks) if isinstance(benchmarks, Mapping) else {},
    }
    document["benchmarks"][report.benchmark] = report.to_record()
    document["passed"] = all(
        entry.get("passed") is True
        for entry in document["benchmarks"].values()
        if isinstance(entry, Mapping)
    )
    digest = jsonio.write_json_atomic(path, document)
    return path, digest
