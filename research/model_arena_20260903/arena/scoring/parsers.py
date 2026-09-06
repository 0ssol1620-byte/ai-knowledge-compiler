"""Turn each evaluator's raw output into ``summary.json`` and ``per_case.jsonl``.

The metric names are the evaluator's. Nothing here renames, rescales,
averages across benchmarks or invents a headline number: masterplan section 28
keeps benchmarks apart, and a metric an evaluator does not publish is recorded
in ``missing_metrics`` with the reason it is absent. OmniDocBench, for
instance, publishes no single "overall" figure - so this lane publishes none
either, rather than inventing one out of four edit distances.

``per_case.jsonl`` exists so lane E1 can join an oracle or a correlation on
``case_key``. Every row therefore carries ``case_key`` and ``sample_id``. A
per-case number the evaluator reports against a location this campaign cannot
resolve to a ``case_key`` is not guessed into a row; it is listed in the
summary's ``unjoined_locations``.

An evaluator that did not produce output is written as
``{"status": "EVALUATOR_BLOCKED"}`` with the stderr tail (ARENA_CONTRACT
section 3.11). It is never written as zeros.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID
from arena.scoring import jsonio
from arena.scoring.errors import EvaluatorBlockedError, InputError
from arena.scoring.evaluators import LAYOUT_REVISION, PARSEBENCH_GROUPS
from arena.scoring.outputs import SourceIndex

__all__ = [
    "PER_CASE_SCHEMA",
    "SUMMARY_SCHEMA",
    "MissingMetric",
    "ParsedScore",
    "blocked_summary",
    "build_summary",
    "parse_raw",
]

SUMMARY_SCHEMA: Final = "tavonel.arena.score-summary.v1"
PER_CASE_SCHEMA: Final = "tavonel.arena.score-case.v1"

_OMNIDOC_PREFIX: Final = "markdown_quick_match"
_ELEMENT_SUFFIX: Final = re.compile(r"_\[\d+\]$")

#: ParseBench's five published dimensions and the evaluator group that carries
#: each one. Recorded as a map so a reader can follow a leaderboard column back
#: to a report file; the numbers themselves are never renamed.
PARSEBENCH_DIMENSION_GROUP: Final = {
    "tables": "table",
    "charts": "chart",
    "content_faithfulness": "text_content",
    "semantic_formatting": "text_formatting",
    "visual_grounding": "layout",
}


@dataclass(frozen=True, slots=True)
class MissingMetric:
    name: str
    reason: str

    def to_record(self) -> dict[str, Any]:
        return {"name": self.name, "value": None, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class ParsedScore:
    benchmark: str
    metrics: Mapping[str, Any]
    per_category: Mapping[str, Any]
    missing_metrics: tuple[MissingMetric, ...]
    counts: Mapping[str, Any]
    per_case: tuple[dict[str, Any], ...]
    unjoined_locations: tuple[dict[str, Any], ...]
    evaluator_artifacts: Mapping[str, str] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# case_key lookups
# ---------------------------------------------------------------------------


def _stem_index(source_index: SourceIndex, benchmark: str) -> dict[str, str]:
    """``<source stem>`` -> ``case_key`` for one benchmark."""

    index: dict[str, str] = {}
    for row in source_index.by_benchmark(benchmark):
        stem = Path(row.source_relative_path).stem
        if stem in index:
            raise InputError(
                f"two {benchmark} cases share the source stem {stem!r}: "
                f"{index[stem]} and {row.case_key}"
            )
        index[stem] = row.case_key
    return index


def _parsebench_index(source_index: SourceIndex) -> dict[str, str]:
    """``<category>/<stem>`` -> ``case_key``; this is ParseBench's ``test_id``."""

    index: dict[str, str] = {}
    for row in source_index.by_benchmark("parsebench"):
        path = Path(row.source_relative_path)
        test_id = f"{path.parent.name}/{path.stem}"
        if test_id in index:
            raise InputError(f"two ParseBench cases share the test id {test_id!r}")
        index[test_id] = row.case_key
    return index


def _olmocr_index(source_index: SourceIndex) -> dict[str, str]:
    """``<path under bench_data/pdfs>`` -> ``case_key``."""

    index: dict[str, str] = {}
    prefix = "bench_data/pdfs/"
    for row in source_index.by_benchmark("olmocr"):
        relative = row.source_relative_path
        if not relative.startswith(prefix):
            raise InputError(
                f"olmOCR case {row.case_key} has source path {relative!r} outside "
                "bench_data/pdfs"
            )
        index[relative[len(prefix) :]] = row.case_key
    return index


def _sample_ids(source_index: SourceIndex) -> dict[str, str]:
    return {key: row.sample_id for key, row in source_index.rows.items()}


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------


def parse_raw(
    benchmark: str, raw_root: Path, *, source_index: SourceIndex
) -> ParsedScore:
    if benchmark == "omnidoc":
        return _parse_omnidoc(raw_root, source_index)
    if benchmark == "parsebench":
        return _parse_parsebench(raw_root, source_index)
    if benchmark == "olmocr":
        return _parse_olmocr(raw_root, source_index)
    raise InputError(f"unknown benchmark {benchmark!r}")


def _require_file(path: Path, what: str) -> Path:
    if not jsonio.io_path(path).is_file():
        raise EvaluatorBlockedError(
            f"{what} is absent at {path}; the evaluator produced no result to parse"
        )
    return path


def _read_object(path: Path, what: str) -> Mapping[str, Any]:
    document = jsonio.read_json(_require_file(path, what))
    if not isinstance(document, Mapping):
        raise EvaluatorBlockedError(f"{what} at {path} is not a JSON object")
    return document


# ---------------------------------------------------------------------------
# OmniDocBench
# ---------------------------------------------------------------------------

_OMNIDOC_ELEMENTS: Final = ("text_block", "display_formula", "table", "reading_order")


def _parse_omnidoc(raw_root: Path, source_index: SourceIndex) -> ParsedScore:
    step_dir = raw_root / "end2end"
    metric_path = step_dir / f"{_OMNIDOC_PREFIX}_metric_result.json"
    result = _read_object(metric_path, "OmniDocBench metric_result.json")

    metrics: dict[str, Any] = {}
    per_category: dict[str, Any] = {}
    for element in _OMNIDOC_ELEMENTS:
        block = result.get(element)
        if not isinstance(block, Mapping):
            continue
        overall = block.get("all")
        if isinstance(overall, Mapping):
            metrics[element] = dict(overall)
        page = block.get("page")
        if isinstance(page, Mapping):
            per_category[element] = {
                str(metric): dict(values)
                for metric, values in page.items()
                if isinstance(values, Mapping)
            }

    missing = [
        MissingMetric(
            name="overall",
            reason=(
                "OmniDocBench's metric_result.json publishes no single overall figure. "
                "Combining its four edit distances and TEDS into one number would be "
                "this campaign's invention, not the evaluator's metric."
            ),
        )
    ]
    for element in _OMNIDOC_ELEMENTS:
        if element not in metrics:
            missing.append(
                MissingMetric(
                    name=element,
                    reason=f"metric_result.json carries no '{element}' block",
                )
            )

    per_case, unjoined = _omnidoc_per_case(step_dir, source_index)
    match_debug = result.get("match_debug")
    counts = {
        "page_count": (
            match_debug.get("page_count") if isinstance(match_debug, Mapping) else None
        ),
        "per_case_rows": len(per_case),
    }
    artifacts = {
        path.name: jsonio.sha256_file(path)
        for path in sorted(step_dir.glob(f"{_OMNIDOC_PREFIX}_*"))
        if jsonio.io_path(path).is_file()
    }
    return ParsedScore(
        benchmark="omnidoc",
        metrics=metrics,
        per_category=per_category,
        missing_metrics=tuple(missing),
        counts=counts,
        per_case=per_case,
        unjoined_locations=unjoined,
        evaluator_artifacts=artifacts,
        notes=(
            "table TEDS below zero is reported as the evaluator produced it. "
            "OmniDocBench computes TEDS as 1 - APTED_distance / max(n_nodes) and the "
            "distance can exceed the node count; clamping would silently improve a "
            "published number.",
            "match_debug is carried through so a page the matcher timed out on is "
            "visible rather than averaged away.",
        ),
    )


_OMNIDOC_PER_PAGE: Final = (
    ("text_block_per_page_edit.json", "text_block", "Edit_dist"),
    ("display_formula_per_page_edit.json", "display_formula", "Edit_dist"),
    ("table_per_page_edit.json", "table", "Edit_dist"),
    ("reading_order_per_page_edit.json", "reading_order", "Edit_dist"),
)


def _omnidoc_per_case(
    step_dir: Path, source_index: SourceIndex
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    stems = _stem_index(source_index, "omnidoc")
    sample_ids = _sample_ids(source_index)
    rows: dict[str, dict[str, Any]] = {}
    unjoined: list[dict[str, Any]] = []

    def bucket(case_key: str) -> dict[str, Any]:
        return rows.setdefault(
            case_key,
            {
                "schema": PER_CASE_SCHEMA,
                "campaign_id": CAMPAIGN_ID,
                "benchmark": "omnidoc",
                "case_key": case_key,
                "sample_id": sample_ids.get(case_key),
                "metrics": {},
                "table_teds": [],
            },
        )

    for filename, element, metric in _OMNIDOC_PER_PAGE:
        path = step_dir / f"{_OMNIDOC_PREFIX}_{filename}"
        if not jsonio.io_path(path).is_file():
            continue
        payload = jsonio.read_json(path)
        if not isinstance(payload, Mapping):
            continue
        for location, value in payload.items():
            case_key = _omnidoc_case_key(str(location), stems)
            if case_key is None:
                unjoined.append({"artifact": path.name, "location": str(location)})
                continue
            bucket(case_key)["metrics"][f"{element}.{metric}"] = value

    teds_path = step_dir / f"{_OMNIDOC_PREFIX}_table_per_table_TEDS.json"
    if jsonio.io_path(teds_path).is_file():
        payload = jsonio.read_json(teds_path)
        if isinstance(payload, Mapping):
            for location, value in payload.items():
                case_key = _omnidoc_case_key(str(location), stems)
                if case_key is None:
                    unjoined.append({"artifact": teds_path.name, "location": str(location)})
                    continue
                if isinstance(value, Mapping):
                    entry = {"location": str(location), **dict(value)}
                    table_rows = bucket(case_key)["table_teds"]
                    if isinstance(table_rows, list):
                        table_rows.append(entry)

    ordered = tuple(rows[key] for key in sorted(rows))
    return ordered, tuple(unjoined)


def _omnidoc_case_key(location: str, stems: Mapping[str, str]) -> str | None:
    name = _ELEMENT_SUFFIX.sub("", location)
    return stems.get(Path(name).stem)


# ---------------------------------------------------------------------------
# ParseBench
# ---------------------------------------------------------------------------


def _parse_parsebench(raw_root: Path, source_index: SourceIndex) -> ParsedScore:
    lookup = _parsebench_index(source_index)
    sample_ids = _sample_ids(source_index)
    metrics: dict[str, Any] = {}
    per_category: dict[str, Any] = {}
    missing: list[MissingMetric] = []
    per_case: list[dict[str, Any]] = []
    unjoined: list[dict[str, Any]] = []
    artifacts: dict[str, str] = {}
    total_examples = 0
    failed_examples = 0
    rule_pass = 0
    rule_fail = 0

    for group, product_type in PARSEBENCH_GROUPS:
        report_path = raw_root / group / "_evaluation_report.json"
        if not jsonio.io_path(report_path).is_file():
            missing.append(
                MissingMetric(
                    name=group,
                    reason=f"the {group} evaluation report is absent at {report_path}",
                )
            )
            continue
        report = _read_object(report_path, f"ParseBench {group} report")
        artifacts[f"{group}/_evaluation_report.json"] = jsonio.sha256_file(report_path)
        aggregate = report.get("aggregate_metrics")
        metrics[group] = {
            "product_type": product_type,
            "total_examples": report.get("total_examples"),
            "successful": report.get("successful"),
            "failed": report.get("failed"),
            "aggregate_metrics": dict(aggregate) if isinstance(aggregate, Mapping) else None,
        }
        total_examples += _int(report.get("total_examples"))
        failed_examples += _int(report.get("failed"))

        results = report.get("per_example_results")
        if not isinstance(results, Sequence):
            continue
        for entry in results:
            if not isinstance(entry, Mapping):
                continue
            test_id = str(entry.get("test_id") or "")
            case_key = lookup.get(test_id)
            if case_key is None:
                unjoined.append(
                    {"artifact": f"{group}/_evaluation_report.json", "test_id": test_id}
                )
                continue
            values, passed, failed = _parsebench_metrics(entry)
            rule_pass += passed
            rule_fail += failed
            per_case.append(
                {
                    "schema": PER_CASE_SCHEMA,
                    "campaign_id": CAMPAIGN_ID,
                    "benchmark": "parsebench",
                    "case_key": case_key,
                    "sample_id": sample_ids.get(case_key),
                    "group": group,
                    "test_id": test_id,
                    "success": entry.get("success"),
                    "error": entry.get("error"),
                    "metrics": values,
                    "rule_pass_count": passed,
                    "rule_fail_count": failed,
                }
            )
        per_category[group] = {
            "example_count": report.get("total_examples"),
            "failed": report.get("failed"),
        }

    missing.append(
        MissingMetric(
            name="overall",
            reason=(
                "ParseBench's _evaluation_report.json is per group. The published "
                "leaderboard 'Overall' column is produced by ParseBench's own "
                "leaderboard tooling, not by the evaluation report, so this campaign "
                "does not compute one."
            ),
        )
    )
    counts = {
        "total_examples": total_examples,
        "failed_examples": failed_examples,
        "rule_pass_count": rule_pass,
        "rule_fail_count": rule_fail,
        "per_case_rows": len(per_case),
    }
    return ParsedScore(
        benchmark="parsebench",
        metrics=metrics,
        per_category=per_category,
        missing_metrics=tuple(missing),
        counts=counts,
        per_case=tuple(sorted(per_case, key=lambda row: (str(row["case_key"]), str(row["group"])))),
        unjoined_locations=tuple(unjoined),
        evaluator_artifacts=artifacts,
        notes=(
            "one row per (case_key, group): text_content and text_formatting score the "
            "same page against different rules, so a page has two rows.",
            f"dimension to group map: {PARSEBENCH_DIMENSION_GROUP}",
            f"evaluator input built by {LAYOUT_REVISION}",
        ),
    )


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parsebench_metrics(entry: Mapping[str, Any]) -> tuple[dict[str, Any], int, int]:
    values: dict[str, Any] = {}
    passed = 0
    failed = 0
    metrics = entry.get("metrics")
    if not isinstance(metrics, Sequence):
        return values, passed, failed
    for metric in metrics:
        if not isinstance(metric, Mapping):
            continue
        name = metric.get("metric_name")
        if isinstance(name, str) and name:
            values[name] = metric.get("value")
        metadata = metric.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        rules = metadata.get("rule_results")
        if not isinstance(rules, Sequence):
            continue
        for rule in rules:
            if not isinstance(rule, Mapping):
                continue
            if rule.get("passed") is True:
                passed += 1
            else:
                failed += 1
    return values, passed, failed


# ---------------------------------------------------------------------------
# olmOCR-Bench
# ---------------------------------------------------------------------------


def _parse_olmocr(raw_root: Path, source_index: SourceIndex) -> ParsedScore:
    path = raw_root / "benchmark" / "official-result.json"
    result = _read_object(path, "olmOCR official result")
    lookup = _olmocr_index(source_index)
    sample_ids = _sample_ids(source_index)

    errors = result.get("candidate_errors")
    if isinstance(errors, Sequence) and not isinstance(errors, str) and len(errors) > 0:
        raise EvaluatorBlockedError(
            "olmOCR reported candidate validation errors; no score is recorded",
            stderr_tail=str(list(errors)[:5]),
        )

    per_jsonl = result.get("per_jsonl")
    type_breakdown = result.get("type_breakdown")
    metrics = {
        "overall_score": result.get("overall_score"),
        "overall_score_definition": result.get("overall_score_definition"),
        "test_count": result.get("test_count"),
    }
    per_category = {
        "per_jsonl": dict(per_jsonl) if isinstance(per_jsonl, Mapping) else {},
        "type_breakdown": dict(type_breakdown) if isinstance(type_breakdown, Mapping) else {},
    }
    missing: list[MissingMetric] = []
    if result.get("overall_score") is None:
        missing.append(
            MissingMetric(
                name="overall_score",
                reason="no rule file produced a pass rate, so the evaluator computed no mean",
            )
        )

    rows: dict[str, dict[str, Any]] = {}
    unjoined: list[dict[str, Any]] = []
    tests = result.get("tests")
    if isinstance(tests, Sequence):
        for test in tests:
            if not isinstance(test, Mapping):
                continue
            pdf = str(test.get("pdf") or "")
            case_key = lookup.get(pdf)
            if case_key is None:
                unjoined.append({"artifact": path.name, "pdf": pdf, "test_id": test.get("test_id")})
                continue
            row = rows.setdefault(
                case_key,
                {
                    "schema": PER_CASE_SCHEMA,
                    "campaign_id": CAMPAIGN_ID,
                    "benchmark": "olmocr",
                    "case_key": case_key,
                    "sample_id": sample_ids.get(case_key),
                    "tests": [],
                },
            )
            test_rows = row["tests"]
            if isinstance(test_rows, list):
                test_rows.append(
                    {
                        "test_id": test.get("test_id"),
                        "type": test.get("type"),
                        "source_jsonl": test.get("source_jsonl"),
                        "page": test.get("page"),
                        "passed": test.get("passed"),
                        "explanation": test.get("explanation"),
                    }
                )
    for row in rows.values():
        entries = row["tests"]
        total = len(entries) if isinstance(entries, list) else 0
        passed = (
            sum(1 for item in entries if item.get("passed") is True)
            if isinstance(entries, list)
            else 0
        )
        row["test_count"] = total
        row["passed_count"] = passed
        row["pass_rate"] = (passed / total) if total else None

    counts = {
        "test_count": result.get("test_count"),
        "pdf_count": result.get("pdf_count"),
        "per_case_rows": len(rows),
    }
    return ParsedScore(
        benchmark="olmocr",
        metrics=metrics,
        per_category=per_category,
        missing_metrics=tuple(missing),
        counts=counts,
        per_case=tuple(rows[key] for key in sorted(rows)),
        unjoined_locations=tuple(unjoined),
        evaluator_artifacts={path.name: jsonio.sha256_file(path)},
        notes=(
            "the overall score is the mean of the per-jsonl pass rates, which is how "
            "benchmark.py aggregates; it is not the flat pass rate over all tests.",
            "a page's pass_rate is over that page's own rules and is not comparable "
            "across pages with different rule counts.",
        ),
    )


# ---------------------------------------------------------------------------
# summary documents
# ---------------------------------------------------------------------------


def build_summary(
    parsed: ParsedScore,
    *,
    key: str,
    provenance: Mapping[str, Any],
    qa_report_sha256: str,
) -> dict[str, Any]:
    return {
        "schema": SUMMARY_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "key": key,
        "benchmark": parsed.benchmark,
        "status": "SCORED",
        "metrics": dict(parsed.metrics),
        "per_category": dict(parsed.per_category),
        "missing_metrics": [item.to_record() for item in parsed.missing_metrics],
        "counts": dict(parsed.counts),
        "unjoined_locations": list(parsed.unjoined_locations),
        "evaluator_artifacts_sha256": dict(parsed.evaluator_artifacts),
        "qa_report_sha256": qa_report_sha256,
        "notes": list(parsed.notes),
        "provenance": dict(provenance),
    }


def blocked_summary(
    *,
    key: str,
    benchmark: str,
    provenance: Mapping[str, Any],
    reason: str,
    stderr_tail: str,
    returncode: int | None = None,
    timed_out: bool = False,
    qa_report_sha256: str | None = None,
) -> dict[str, Any]:
    """The record for an evaluator that did not produce a result.

    ``metrics`` is ``null``. A blocked evaluator is an operational failure, and
    writing it as ``0.0`` would make a broken run indistinguishable from a
    model that scored nothing (masterplan section 16).
    """

    return {
        "schema": SUMMARY_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "key": key,
        "benchmark": benchmark,
        "status": "EVALUATOR_BLOCKED",
        "metrics": None,
        "per_category": None,
        "missing_metrics": [],
        "counts": {},
        "blocked_reason": reason,
        "blocked_returncode": returncode,
        "blocked_timed_out": timed_out,
        "stderr_tail": stderr_tail,
        "qa_report_sha256": qa_report_sha256,
        "provenance": dict(provenance),
    }


def blocked_from_error(
    error: EvaluatorBlockedError,
    *,
    key: str,
    benchmark: str,
    provenance: Mapping[str, Any],
    qa_report_sha256: str | None = None,
) -> dict[str, Any]:
    return blocked_summary(
        key=key,
        benchmark=benchmark,
        provenance=provenance,
        reason=str(error),
        stderr_tail=error.stderr_tail,
        returncode=error.returncode,
        timed_out=error.timed_out,
        qa_report_sha256=qa_report_sha256,
    )
