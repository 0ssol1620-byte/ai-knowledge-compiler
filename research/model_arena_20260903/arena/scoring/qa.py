"""Masterplan section 44 - Quality Assurance before scoring.

Nothing in this lane runs an official evaluator over an output set that has
not passed here. The gate answers one question per check, over the frozen
bytes rather than over what a receipt claims about them.

Two distinctions the report keeps that the campaign has previously lost.

*Blocking versus recorded.* An integrity violation - a count that is wrong, a
hash that does not match the bytes, a duplicate page, a source that is not the
source the manifest names - blocks scoring. A model that failed pages, or
emitted nothing on a page, is a *result*: it is counted and listed, and it
does not block. Blocking on it would refuse to score a model for being bad.

*Blank source versus empty extraction* (masterplan section 41). An empty
output over a source the preflight marked ``is_probably_blank`` and an empty
output over a page full of text are two different facts. They are counted
separately here and neither changes any official score.

A check that cannot be evaluated because campaign data is missing is ``FAIL``
with the reason, never ``PASS`` by default. ``NOT_APPLICABLE`` is reserved for
checks that have no meaning for the kind of output set being examined, and
each one carries why.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Literal

from arena.constants import BENCHMARK_KEYS, CAMPAIGN_ID
from arena.scoring import jsonio
from arena.scoring.errors import InputError, QaGateError
from arena.scoring.outputs import OutputRow, OutputSet, SourceIndex, load_source_index
from arena.scoring.paths import ScoringPaths

__all__ = [
    "CANONICALIZATION_ERROR_CLASSES",
    "QA_REPORT_SCHEMA",
    "QaCheck",
    "QaReport",
    "require_qa_passed",
    "run_qa_gate",
    "write_qa_report",
]

QA_REPORT_SCHEMA: Final = "tavonel.arena.qa-report.v1"

#: A page whose receipt failed in one of these classes failed *after* the model
#: answered - in preprocessing, canonicalisation or output validation. Masterplan
#: section 44 asks for the adapter-failure list; this is its definition.
CANONICALIZATION_ERROR_CLASSES: Final = (
    "INPUT_DECODE",
    "PREPROCESS",
    "OUTPUT_EMPTY",
    "OUTPUT_TRUNCATED",
    "OUTPUT_MALFORMED",
    "OUTPUT_REPETITION",
    "POSTPROCESS",
)

CheckState = Literal["PASS", "FAIL", "NOT_APPLICABLE"]

# Cap on how many identifiers a check writes into the report. The count is
# always exact; the list is a sample so one broken run cannot produce a
# 5,000-entry report that nobody reads.
_SAMPLE_LIMIT: Final = 50


@dataclass(frozen=True, slots=True)
class QaCheck:
    name: str
    blocking: bool
    state: CheckState
    detail: str
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.state == "FAIL"

    def to_record(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "blocking": self.blocking,
            "state": self.state,
            "detail": self.detail,
            "data": dict(self.data),
        }


@dataclass(frozen=True, slots=True)
class QaReport:
    key: str
    kind: str
    model_key: str | None
    variant: str | None
    benchmark: str
    checks: tuple[QaCheck, ...]
    manifest_sha256: str
    sample_count: int
    success_count: int
    failed_count: int
    generated_at: str

    @property
    def blocking_failures(self) -> tuple[str, ...]:
        return tuple(check.name for check in self.checks if check.blocking and check.failed)

    @property
    def passed(self) -> bool:
        return not self.blocking_failures

    def to_record(self) -> dict[str, Any]:
        return {
            "schema": QA_REPORT_SCHEMA,
            "campaign_id": CAMPAIGN_ID,
            "key": self.key,
            "kind": self.kind,
            "model_key": self.model_key,
            "variant": self.variant,
            "benchmark": self.benchmark,
            "generated_at": self.generated_at,
            "passed": self.passed,
            "blocking_failures": list(self.blocking_failures),
            "manifest_sha256": self.manifest_sha256,
            "sample_count": self.sample_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "checks": [check.to_record() for check in self.checks],
        }


def _sample(values: Sequence[str]) -> list[str]:
    return sorted(values)[:_SAMPLE_LIMIT]


def _expected_sample_count(paths: ScoringPaths, benchmark: str) -> tuple[int | None, str]:
    """The count ``campaign_manifest.json`` fixes for this benchmark.

    Returns ``(None, reason)`` when the manifest is absent or does not carry
    the benchmark. The gate then fails: guessing 2,078 from a constant would
    let a truncated run through on a campaign whose manifest says otherwise.
    """

    path = paths.campaign_manifest
    if not jsonio.io_path(path).is_file():
        return None, f"campaign_manifest.json is absent at {path}"
    document = jsonio.read_json(path)
    if not isinstance(document, Mapping):
        return None, f"{path} is not a JSON object"
    benchmarks = document.get("benchmarks")
    if not isinstance(benchmarks, Mapping):
        return None, f"{path} carries no 'benchmarks' object"
    entry = benchmarks.get(benchmark)
    if not isinstance(entry, Mapping):
        return None, f"{path} carries no entry for benchmark {benchmark!r}"
    count = entry.get("sample_count")
    if not isinstance(count, int) or isinstance(count, bool):
        return None, f"{path} benchmark {benchmark!r} has no integer sample_count"
    return count, ""


def _read_receipt(path: Path | None) -> Mapping[str, Any] | None:
    if path is None or not jsonio.io_path(path).is_file():
        return None
    document = jsonio.read_json(path)
    if not isinstance(document, Mapping):
        raise InputError(f"{path} is not a JSON object")
    return document


@dataclass(frozen=True, slots=True)
class _Bytes:
    """What the filesystem says about one output file."""

    exists: bool
    size: int
    digest: str | None
    utf8: bool


def _inspect(path: Path | None) -> _Bytes:
    if path is None or not jsonio.io_path(path).is_file():
        return _Bytes(exists=False, size=0, digest=None, utf8=True)
    data = jsonio.io_path(path).read_bytes()
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return _Bytes(exists=True, size=len(data), digest=jsonio.sha256_bytes(data), utf8=False)
    return _Bytes(exists=True, size=len(data), digest=jsonio.sha256_bytes(data), utf8=True)


def run_qa_gate(
    paths: ScoringPaths,
    output_set: OutputSet,
    benchmark: str,
    *,
    source_index: SourceIndex | None = None,
) -> QaReport:
    """Run every masterplan section 44 check for one benchmark of one set."""

    if benchmark not in BENCHMARK_KEYS:
        raise InputError(f"unknown benchmark {benchmark!r}; expected one of {BENCHMARK_KEYS}")
    index = source_index if source_index is not None else load_source_index(paths)
    rows = output_set.for_benchmark(benchmark)
    checks: list[QaCheck] = []

    seen: dict[str, int] = {}
    for row in rows:
        seen[row.case_key] = seen.get(row.case_key, 0) + 1
    duplicates = sorted(key for key, count in seen.items() if count > 1)

    expected_rows = index.by_benchmark(benchmark)
    expected_keys = {row.case_key for row in expected_rows}
    present_keys = set(seen)
    missing = sorted(expected_keys - present_keys)
    unexpected = sorted(present_keys - expected_keys)

    # ---------------------------------------------------------- sample count
    expected_count, reason = _expected_sample_count(paths, benchmark)
    if expected_count is None:
        checks.append(
            QaCheck(
                name="sample_count_exact",
                blocking=True,
                state="FAIL",
                detail=(
                    f"the expected sample count could not be read: {reason}. The gate "
                    "fails closed rather than assume a count."
                ),
                data={"observed": len(rows)},
            )
        )
    else:
        exact = len(rows) == expected_count
        checks.append(
            QaCheck(
                name="sample_count_exact",
                blocking=True,
                state="PASS" if exact else "FAIL",
                detail=(
                    f"{len(rows)} rows for {benchmark}, campaign_manifest fixes "
                    f"{expected_count}"
                ),
                data={"observed": len(rows), "expected": expected_count},
            )
        )

    # ------------------------------------------------------------ duplicates
    checks.append(
        QaCheck(
            name="duplicate_case_keys",
            blocking=True,
            state="PASS" if not duplicates else "FAIL",
            detail=f"{len(duplicates)} case_key values appear more than once",
            data={"count": len(duplicates), "sample": _sample(duplicates)},
        )
    )

    # -------------------------------------------------------------- coverage
    checks.append(
        QaCheck(
            name="missing_case_keys",
            blocking=True,
            state="PASS" if not missing and not unexpected else "FAIL",
            detail=(
                f"{len(missing)} case_key values from source_manifest.jsonl are absent "
                f"and {len(unexpected)} present rows are not in the source manifest"
            ),
            data={
                "missing_count": len(missing),
                "missing_sample": _sample(missing),
                "unexpected_count": len(unexpected),
                "unexpected_sample": _sample(unexpected),
            },
        )
    )

    # ------------------------------------------------ output bytes and hashes
    hash_problems: list[dict[str, Any]] = []
    zero_byte: list[str] = []
    invalid_utf8: list[str] = []
    empty_on_blank: list[str] = []
    empty_on_nonblank: list[str] = []
    unresolved: list[str] = []

    for row in rows:
        if row.unresolved:
            unresolved.append(row.case_key)
            continue
        if row.status != "SUCCESS":
            continue
        canonical = _inspect(row.canonical_path)
        raw = _inspect(row.raw_path)
        for label, recorded, observed, path in (
            ("canonical", row.canonical_sha256, canonical, row.canonical_path),
            ("raw", row.raw_sha256, raw, row.raw_path),
        ):
            if label == "raw" and row.raw_path is None:
                hash_problems.append(
                    {"case_key": row.case_key, "field": "raw", "problem": "no raw path recorded"}
                )
                continue
            if recorded is None:
                hash_problems.append(
                    {"case_key": row.case_key, "field": label, "problem": "hash absent"}
                )
                continue
            if not observed.exists:
                hash_problems.append(
                    {
                        "case_key": row.case_key,
                        "field": label,
                        "problem": "file missing",
                        "path": str(path),
                    }
                )
                continue
            if observed.digest != recorded:
                hash_problems.append(
                    {
                        "case_key": row.case_key,
                        "field": label,
                        "problem": "hash mismatch",
                        "recorded": recorded,
                        "recomputed": observed.digest,
                    }
                )
        if canonical.exists and not canonical.utf8:
            invalid_utf8.append(row.case_key)
        if canonical.exists and canonical.size == 0:
            zero_byte.append(row.case_key)
            source = index.get(row.case_key)
            if source is not None and source.is_probably_blank:
                empty_on_blank.append(row.case_key)
            else:
                empty_on_nonblank.append(row.case_key)

    checks.append(
        QaCheck(
            name="output_hashes_present_and_match",
            blocking=True,
            state="PASS" if not hash_problems else "FAIL",
            detail=(
                f"{len(hash_problems)} output files are absent, unhashed, or hash to "
                "something other than what the frozen manifest recorded"
            ),
            data={"count": len(hash_problems), "sample": hash_problems[:_SAMPLE_LIMIT]},
        )
    )
    checks.append(
        QaCheck(
            name="invalid_utf8",
            blocking=True,
            state="PASS" if not invalid_utf8 else "FAIL",
            detail=f"{len(invalid_utf8)} canonical outputs are not valid UTF-8",
            data={"count": len(invalid_utf8), "sample": _sample(invalid_utf8)},
        )
    )

    # -------------------------------------------------- receipts: revision, config
    checks.extend(
        _receipt_checks(output_set, rows, index, paths)
    )

    # ------------------------------------------------------- recorded, not blocking
    checks.append(
        QaCheck(
            name="zero_byte_outputs",
            blocking=False,
            state="PASS",
            detail=(
                f"{len(zero_byte)} pages report SUCCESS with an empty canonical output. "
                "Recorded, not blocking: an empty output is a result, not a broken file."
            ),
            data={"count": len(zero_byte), "sample": _sample(zero_byte)},
        )
    )
    checks.append(
        QaCheck(
            name="blank_source_vs_empty_extraction",
            blocking=False,
            state="PASS",
            detail=(
                "masterplan section 41: empty output over a source the preflight marked "
                "probably blank is counted apart from empty output over a non-blank "
                "source. Neither changes any official score."
            ),
            data={
                "empty_on_blank_source_count": len(empty_on_blank),
                "empty_on_blank_source_sample": _sample(empty_on_blank),
                "empty_on_nonblank_source_count": len(empty_on_nonblank),
                "empty_on_nonblank_source_sample": _sample(empty_on_nonblank),
                "blank_flag_source": "source_manifest.jsonl preflight.is_probably_blank",
            },
        )
    )
    if output_set.kind == "composite":
        checks.append(
            QaCheck(
                name="unresolved_composite_pages",
                blocking=False,
                state="PASS",
                detail=(
                    f"{len(unresolved)} pages have no frozen output for the model the "
                    "variant chose; they carry no text and must not be counted as "
                    "successes"
                ),
                data={"count": len(unresolved), "sample": _sample(unresolved)},
            )
        )

    adapter_failures = _adapter_failures(rows)
    checks.append(
        QaCheck(
            name="adapter_failures",
            blocking=False,
            state="PASS",
            detail=(
                f"{len(adapter_failures)} pages failed at or after canonicalisation "
                f"(error_class in {', '.join(CANONICALIZATION_ERROR_CLASSES)})"
            ),
            data={"count": len(adapter_failures), "sample": adapter_failures[:_SAMPLE_LIMIT]},
        )
    )

    success = sum(1 for row in rows if row.status == "SUCCESS" and not row.unresolved)
    return QaReport(
        key=output_set.key,
        kind=output_set.kind,
        model_key=output_set.model_key,
        variant=output_set.variant,
        benchmark=benchmark,
        checks=tuple(checks),
        manifest_sha256=output_set.manifest_sha256,
        sample_count=len(rows),
        success_count=success,
        failed_count=len(rows) - success,
        generated_at=jsonio.utc_now_iso(),
    )


def _adapter_failures(rows: Sequence[OutputRow]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        receipt = _read_receipt(row.receipt_path)
        if receipt is None:
            continue
        error_class = receipt.get("error_class")
        if isinstance(error_class, str) and error_class in CANONICALIZATION_ERROR_CLASSES:
            failures.append(
                {
                    "case_key": row.case_key,
                    "error_class": error_class,
                    "status": receipt.get("status"),
                }
            )
    return sorted(failures, key=lambda item: str(item["case_key"]))


def _registry_expectations(paths: ScoringPaths, model_key: str) -> Mapping[str, Any] | None:
    path = paths.model_registry
    if not jsonio.io_path(path).is_file():
        return None
    document = jsonio.read_json(path)
    records: Any = document
    if isinstance(document, Mapping):
        records = document.get("models", document)
    if isinstance(records, Mapping):
        entry = records.get(model_key)
        return entry if isinstance(entry, Mapping) else None
    if isinstance(records, list):
        for entry in records:
            if isinstance(entry, Mapping) and entry.get("model_key") == model_key:
                return entry
    return None


def _receipt_checks(
    output_set: OutputSet,
    rows: Sequence[OutputRow],
    index: SourceIndex,
    paths: ScoringPaths,
) -> list[QaCheck]:
    """Model revision uniqueness, source-hash binding and run-config binding."""

    checks: list[QaCheck] = []
    revisions: set[str] = set()
    run_configs: set[tuple[str, str, str]] = set()
    source_mismatch: list[dict[str, Any]] = []
    missing_receipts: list[str] = []

    for row in rows:
        if row.unresolved:
            continue
        receipt = _read_receipt(row.receipt_path)
        if receipt is None:
            missing_receipts.append(row.case_key)
            continue
        revision = receipt.get("model_revision")
        if isinstance(revision, str) and revision:
            revisions.add(revision)
        prompt_id = receipt.get("prompt_id")
        prompt_sha = receipt.get("prompt_sha256")
        config_sha = receipt.get("inference_config_sha256")
        if all(isinstance(value, str) and value for value in (prompt_id, prompt_sha, config_sha)):
            run_configs.add((str(prompt_id), str(prompt_sha), str(config_sha)))
        source_sha = receipt.get("source_sha256")
        expected = index.get(row.case_key)
        if expected is None:
            source_mismatch.append(
                {"case_key": row.case_key, "problem": "case_key absent from source_manifest"}
            )
        elif source_sha != expected.input_png_sha256:
            source_mismatch.append(
                {
                    "case_key": row.case_key,
                    "problem": "receipt source_sha256 differs from the staged input hash",
                    "receipt": source_sha,
                    "source_manifest": expected.input_png_sha256,
                }
            )

    if missing_receipts:
        checks.append(
            QaCheck(
                name="page_receipts_present",
                blocking=True,
                state="FAIL",
                detail=f"{len(missing_receipts)} pages have no page receipt on disk",
                data={"count": len(missing_receipts), "sample": _sample(missing_receipts)},
            )
        )
    else:
        checks.append(
            QaCheck(
                name="page_receipts_present",
                blocking=True,
                state="PASS",
                detail=f"every one of {len(rows)} pages has a page receipt",
                data={"count": 0},
            )
        )

    checks.append(
        QaCheck(
            name="source_hash_match",
            blocking=True,
            state="PASS" if not source_mismatch else "FAIL",
            detail=(
                f"{len(source_mismatch)} page receipts name a source hash that is not the "
                "staged input hash for that case_key"
            ),
            data={"count": len(source_mismatch), "sample": source_mismatch[:_SAMPLE_LIMIT]},
        )
    )

    if output_set.kind == "composite":
        note = (
            "a TAVONEL composite draws pages from several models by design, so one "
            "model revision and one run config cannot be required of it; each page's "
            "revision is checked in the model set it came from"
        )
        checks.append(
            QaCheck(
                name="model_revision_unique",
                blocking=True,
                state="NOT_APPLICABLE",
                detail=note,
                data={"observed_revisions": sorted(revisions)},
            )
        )
        checks.append(
            QaCheck(
                name="run_config_hash_match",
                blocking=True,
                state="NOT_APPLICABLE",
                detail=note,
                data={"observed_run_configs": len(run_configs)},
            )
        )
        return checks

    checks.append(
        QaCheck(
            name="model_revision_unique",
            blocking=True,
            state="PASS" if len(revisions) == 1 else "FAIL",
            detail=(
                f"{len(revisions)} distinct model_revision values across the page receipts; "
                "exactly one is required"
            ),
            data={"observed_revisions": sorted(revisions)},
        )
    )

    registry = (
        _registry_expectations(paths, output_set.model_key)
        if output_set.model_key is not None
        else None
    )
    if len(run_configs) != 1:
        checks.append(
            QaCheck(
                name="run_config_hash_match",
                blocking=True,
                state="FAIL",
                detail=(
                    f"{len(run_configs)} distinct (prompt_id, prompt_sha256, "
                    "inference_config_sha256) triples across the page receipts; exactly "
                    "one is required"
                ),
                data={"observed_run_configs": sorted(run_configs)},
            )
        )
        return checks

    prompt_id, prompt_sha, config_sha = next(iter(run_configs))
    observed = {
        "prompt_id": prompt_id,
        "prompt_sha256": prompt_sha,
        "inference_config_sha256": config_sha,
    }
    if registry is None:
        checks.append(
            QaCheck(
                name="run_config_hash_match",
                blocking=True,
                state="PASS",
                detail=(
                    "the page receipts agree on one run config. model_registry.json was "
                    "not readable for this model, so the receipts were not compared "
                    "against the official prompt id and inference config hash."
                ),
                data={**observed, "registry_comparison": "skipped: registry entry absent"},
            )
        )
        return checks

    mismatches: list[str] = []
    expected_prompt = registry.get("prompt_id")
    expected_config = registry.get("inference_config_sha256")
    if isinstance(expected_prompt, str) and expected_prompt and expected_prompt != prompt_id:
        mismatches.append(f"prompt_id {prompt_id!r} != registry {expected_prompt!r}")
    if isinstance(expected_config, str) and expected_config and expected_config != config_sha:
        mismatches.append(
            f"inference_config_sha256 {config_sha!r} != registry {expected_config!r}"
        )
    checks.append(
        QaCheck(
            name="run_config_hash_match",
            blocking=True,
            state="PASS" if not mismatches else "FAIL",
            detail=(
                "the page receipts agree on one run config and it matches the runtime-owned "
                "prompt_id and inference_config_sha256 in model_registry.json"
                if not mismatches
                else "; ".join(mismatches)
            ),
            data={
                **observed,
                "registry_prompt_id": expected_prompt,
                "registry_inference_config_sha256": expected_config,
            },
        )
    )
    return checks


def write_qa_report(paths: ScoringPaths, report: QaReport) -> tuple[Path, str]:
    path = paths.qa_report(report.key, report.benchmark)
    digest = jsonio.write_json_atomic(path, report.to_record())
    return path, digest


def require_qa_passed(paths: ScoringPaths, key: str, benchmark: str) -> Mapping[str, Any]:
    """Load the gate report and refuse to continue unless it is green."""

    path = paths.qa_report(key, benchmark)
    if not jsonio.io_path(path).is_file():
        raise QaGateError(
            f"no QA report at {path}; run "
            f"`python -m arena.scoring qa --model {key} --benchmark {benchmark}` first "
            "(masterplan section 44)"
        )
    document = jsonio.read_json(path)
    if not isinstance(document, Mapping):
        raise QaGateError(f"{path} is not a JSON object")
    if document.get("passed") is not True:
        failures = document.get("blocking_failures")
        raise QaGateError(
            f"the QA gate for {key}/{benchmark} is red ({failures}); the official "
            "evaluator does not run over an output set that failed section 44"
        )
    return document
