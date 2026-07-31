"""Fail-closed public benchmark orchestration for Structara.

The inference side consumes only source pages and immutable CIR. Ground truth is
introduced only after predictions have been frozen and is never accepted by an
adapter or parser-facing command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "benchmark" / "benchmark-registry.lock.yaml"
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
HEX_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
GT_MARKERS = ("ground_truth", "ground-truth", "groundtruth", "labels", "answer_key")
CRITICAL_CODES = {
    "critical_numeric_mutation",
    "critical_sign_mutation",
    "critical_decimal_mutation",
    "critical_unit_mutation",
    "critical_row_omission",
    "critical_unsupported_row",
    "page_omission",
    "duplicate_output",
    "evidence_loss",
    "silent_omission",
    "output_corruption",
    "false_verified",
    "unresolved_detection_miss",
}


class PublicSuiteError(RuntimeError):
    """A benchmark contract failed closed."""


@dataclass(frozen=True)
class DatasetIdentity:
    repository: str
    revision: str
    manifest_sha256: str
    file_count: int
    total_bytes: int


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicSuiteError(f"{path}: JSON object required")
    return value


def _load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise PublicSuiteError("public benchmark registry schema_version=1.0 required")
    benchmarks = value.get("benchmarks")
    if not isinstance(benchmarks, list) or not benchmarks:
        raise PublicSuiteError("public benchmark registry requires benchmark entries")
    ids: set[str] = set()
    for item in benchmarks:
        if not isinstance(item, dict):
            raise PublicSuiteError("benchmark registry entries must be objects")
        benchmark_id = str(item.get("id", ""))
        if SAFE_ID.fullmatch(benchmark_id) is None or benchmark_id in ids:
            raise PublicSuiteError(f"invalid or duplicate benchmark id: {benchmark_id}")
        ids.add(benchmark_id)
        evaluator = item.get("evaluator")
        dataset = item.get("dataset")
        if not isinstance(evaluator, dict) or not isinstance(dataset, dict):
            raise PublicSuiteError(f"{benchmark_id}: evaluator and dataset are required")
        if HEX_REVISION.fullmatch(str(evaluator.get("commit", ""))) is None:
            raise PublicSuiteError(f"{benchmark_id}: immutable evaluator commit required")
        if HEX_REVISION.fullmatch(str(dataset.get("revision", ""))) is None:
            raise PublicSuiteError(f"{benchmark_id}: immutable dataset revision required")
        if SHA256.fullmatch(str(dataset.get("manifest_sha256", ""))) is None:
            raise PublicSuiteError(f"{benchmark_id}: dataset manifest digest required")
        if int(dataset.get("file_count", 0)) < 1 or int(dataset.get("total_bytes", 0)) < 1:
            raise PublicSuiteError(f"{benchmark_id}: dataset size manifest required")
        if item.get("required") is not True:
            raise PublicSuiteError(f"{benchmark_id}: Public Core entries must be required")
    required_ids = {"omnidocbench", "parsebench", "olmocr-bench"}
    if ids != required_ids:
        raise PublicSuiteError(f"Public Core must contain exactly {sorted(required_ids)}")
    return value


def _get_json(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise PublicSuiteError("metadata endpoint must be an absolute HTTPS URL")
    request = urllib.request.Request(  # noqa: S310 - HTTPS validated immediately above.
        url,
        headers={"Accept": "application/json", "User-Agent": "structara-public-suite/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            value = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise PublicSuiteError(f"metadata fetch failed: {url}") from exc
    if not isinstance(value, dict):
        raise PublicSuiteError(f"metadata endpoint returned a non-object: {url}")
    return value


def _dataset_identity(repository: str, revision: str) -> DatasetIdentity:
    value = _get_json(
        f"https://huggingface.co/api/datasets/{repository}/revision/{revision}?blobs=true"
    )
    if value.get("sha") != revision:
        raise PublicSuiteError(f"{repository}: dataset revision changed")
    siblings = value.get("siblings")
    if not isinstance(siblings, list) or not siblings:
        raise PublicSuiteError(f"{repository}: dataset file manifest is unavailable")
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for item in siblings:
        if not isinstance(item, dict) or not isinstance(item.get("rfilename"), str):
            raise PublicSuiteError(f"{repository}: malformed dataset file manifest")
        size = int(item.get("size", 0))
        lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
        files.append(
            {
                "path": item["rfilename"],
                "blob_id": item.get("blobId"),
                "size": size,
                "lfs_sha256": lfs.get("sha256"),
            }
        )
        total_bytes += size
    files.sort(key=lambda item: item["path"])
    return DatasetIdentity(
        repository=repository,
        revision=revision,
        manifest_sha256=_digest(_canonical_bytes(files)),
        file_count=len(files),
        total_bytes=total_bytes,
    )


def _github_commit(repository_url: str, commit: str) -> str:
    prefix = "https://github.com/"
    if not repository_url.startswith(prefix) or not repository_url.endswith(".git"):
        raise PublicSuiteError("evaluator repository must be a canonical GitHub HTTPS URL")
    slug = repository_url[len(prefix) : -4]
    value = _get_json(f"https://api.github.com/repos/{slug}/commits/{commit}")
    resolved = str(value.get("sha", ""))
    if resolved != commit:
        raise PublicSuiteError(f"{slug}: evaluator commit cannot be resolved exactly")
    return resolved


def verify_registry(*, registry_path: Path, online: bool) -> dict[str, Any]:
    registry = _load_registry(registry_path)
    checks: list[dict[str, Any]] = []
    for benchmark in registry["benchmarks"]:
        dataset = benchmark["dataset"]
        check: dict[str, Any] = {
            "benchmark_id": benchmark["id"],
            "evaluator_commit": benchmark["evaluator"]["commit"],
            "dataset_revision": dataset["revision"],
            "status": "lock_validated",
        }
        if online:
            check["evaluator_commit"] = _github_commit(
                benchmark["evaluator"]["repository"],
                benchmark["evaluator"]["commit"],
            )
            actual = _dataset_identity(dataset["repository"], dataset["revision"])
            expected = DatasetIdentity(
                repository=dataset["repository"],
                revision=dataset["revision"],
                manifest_sha256=dataset["manifest_sha256"],
                file_count=int(dataset["file_count"]),
                total_bytes=int(dataset["total_bytes"]),
            )
            if actual != expected:
                raise PublicSuiteError(
                    f"{benchmark['id']}: dataset manifest differs from the lock"
                )
            check["status"] = "remote_manifest_verified"
            check["dataset_manifest_sha256"] = actual.manifest_sha256
        checks.append(check)
    return {
        "ok": True,
        "suite_id": registry["suite_id"],
        "registry_sha256": _digest(registry_path.read_bytes()),
        "online": online,
        "checks": checks,
    }


def _bbox(block: dict[str, Any]) -> list[int] | None:
    direct = block.get("bbox1000")
    if isinstance(direct, list) and len(direct) == 4:
        return [int(value) for value in direct]
    refs = block.get("source_refs") or block.get("sourceRefs")
    if isinstance(refs, list) and refs:
        value = refs[0].get("bbox1000") if isinstance(refs[0], dict) else None
        if isinstance(value, list) and len(value) == 4:
            return [int(coordinate) for coordinate in value]
    return None


def _block_text(block: dict[str, Any]) -> str:
    for key in ("markdown", "normalized_text", "normalizedText", "raw_text", "rawText"):
        value = block.get(key)
        if isinstance(value, str) and value:
            return value
    table = block.get("table")
    if isinstance(table, dict) and isinstance(table.get("cells"), list):
        return "\n".join(
            str(
                cell.get("normalized_text")
                or cell.get("normalizedText")
                or cell.get("raw_text")
                or cell.get("rawText")
                or ""
            )
            for cell in table["cells"]
            if isinstance(cell, dict)
        )
    return str(block.get("formula_latex") or block.get("formulaLatex") or "")


def _page_blocks(cir: dict[str, Any], page_index: int) -> list[dict[str, Any]]:
    blocks = cir.get("blocks")
    if not isinstance(blocks, list):
        raise PublicSuiteError("CIR blocks must be an array")
    selected: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        refs = block.get("source_refs") or block.get("sourceRefs")
        if not isinstance(refs, list) or not refs:
            continue
        first = refs[0] if isinstance(refs[0], dict) else {}
        candidate = first.get("page_index0", first.get("pageIndex0"))
        if candidate == page_index:
            selected.append(block)
    selected.sort(key=lambda item: (int(item.get("order", 0)), str(item.get("id", ""))))
    return selected


def adapt_cir(cir: dict[str, Any], *, benchmark_id: str, page_index: int) -> dict[str, Any]:
    if benchmark_id not in {"omnidocbench", "parsebench", "olmocr-bench"}:
        raise PublicSuiteError(f"unsupported public benchmark adapter: {benchmark_id}")
    blocks = _page_blocks(cir, page_index)
    markdown = "\n\n".join(text for block in blocks if (text := _block_text(block)))
    if benchmark_id == "olmocr-bench":
        return {"page": page_index + 1, "markdown": markdown}
    normalized_blocks = [
        {
            "id": str(block.get("id", "")),
            "type": str(block.get("type", "unknown")),
            "text": _block_text(block),
            "bbox1000": _bbox(block),
            "order": index,
            "formula_latex": block.get("formula_latex") or block.get("formulaLatex"),
            "table": block.get("table"),
        }
        for index, block in enumerate(blocks)
    ]
    if benchmark_id == "parsebench":
        return {
            "page_index": page_index,
            "markdown": markdown,
            "elements": normalized_blocks,
            "finish_reason": "stop" if markdown or normalized_blocks else "empty",
        }
    return {
        "page_info": {"page_no": page_index, "height": 1000, "width": 1000},
        "markdown": markdown,
        "layout_dets": normalized_blocks,
    }


def freeze_predictions(*, input_dir: Path, output_manifest: Path, candidate: str) -> dict[str, Any]:
    if SAFE_ID.fullmatch(candidate) is None:
        raise PublicSuiteError("candidate must be a safe immutable identifier")
    root = input_dir.resolve(strict=True)
    if not root.is_dir():
        raise PublicSuiteError("prediction input must be a directory")
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        lowered = relative.casefold()
        if any(marker in lowered for marker in GT_MARKERS):
            raise PublicSuiteError(f"prediction archive contains a GT-like path: {relative}")
        payload = path.read_bytes()
        files.append({"path": relative, "size": len(payload), "sha256": _digest(payload)})
        try:
            path.chmod(path.stat().st_mode & ~stat.S_IWRITE)
        except OSError as exc:
            raise PublicSuiteError(f"failed to freeze prediction: {relative}") from exc
    if not files:
        raise PublicSuiteError("prediction archive is empty")
    manifest = {
        "schema_version": "1.0",
        "candidate": candidate,
        "frozen_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "prediction_root": str(root),
        "files": files,
        "archive_sha256": _digest(_canonical_bytes(files)),
        "ground_truth_present": False,
        "immutable": True,
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    output_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def audit_isolation(*, inference_manifest: Path, ground_truth_root: Path) -> dict[str, Any]:
    manifest = _load_json(inference_manifest)
    if manifest.get("immutable") is not True or manifest.get("ground_truth_present") is not False:
        raise PublicSuiteError("prediction manifest is not an immutable GT-free archive")
    prediction_root = Path(str(manifest.get("prediction_root", ""))).resolve(strict=True)
    gt_root = ground_truth_root.resolve(strict=True)
    if (
        prediction_root == gt_root
        or prediction_root in gt_root.parents
        or gt_root in prediction_root.parents
    ):
        raise PublicSuiteError("prediction and ground-truth roots must be disjoint")
    for name, value in os.environ.items():
        lowered = name.casefold()
        if (
            any(marker.replace("-", "_") in lowered for marker in GT_MARKERS)
            and value
            and Path(value).exists()
        ):
            raise PublicSuiteError(f"inference environment exposes GT-like variable: {name}")
    current_files: list[dict[str, Any]] = []
    for path in sorted(prediction_root.rglob("*")):
        if path.is_file():
            payload = path.read_bytes()
            current_files.append(
                {
                    "path": path.relative_to(prediction_root).as_posix(),
                    "size": len(payload),
                    "sha256": _digest(payload),
                }
            )
    actual = _digest(_canonical_bytes(current_files))
    if actual != manifest.get("archive_sha256"):
        raise PublicSuiteError("prediction archive changed after freeze")
    return {
        "ok": True,
        "prediction_archive_sha256": actual,
        "prediction_root": str(prediction_root),
        "ground_truth_root_sha256": _digest(str(gt_root).encode()),
        "root_paths_disjoint": True,
        "ground_truth_in_prediction": False,
        "prediction_immutable": True,
    }


def critical_evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    runtime_failures = 0
    missing_pages = 0
    for record in records:
        case_id = str(record.get("case_id", ""))
        if not case_id:
            raise PublicSuiteError("critical evaluator record requires case_id")
        if record.get("runtime_failure") is True:
            runtime_failures += 1
        if record.get("missing_prediction") is True:
            missing_pages += 1
        codes = record.get("error_codes", [])
        if not isinstance(codes, list) or any(not isinstance(code, str) for code in codes):
            raise PublicSuiteError(f"{case_id}: error_codes must be a string array")
        critical = sorted(set(codes) & CRITICAL_CODES)
        if critical:
            failures.append({"case_id": case_id, "critical_codes": critical})
    return {
        "schema_version": "1.0",
        "case_count": len(records),
        "runtime_failure_count": runtime_failures,
        "missing_prediction_count": missing_pages,
        "critical_failure_count": len(failures),
        "critical_failures": failures,
        "gate_passed": runtime_failures == 0 and missing_pages == 0 and not failures,
    }


def compare_runs(candidate: dict[str, Any], incumbent: dict[str, Any]) -> dict[str, Any]:
    for field in ("benchmark_id", "dataset_revision", "evaluator_commit", "environment_sha256"):
        if candidate.get(field) != incumbent.get(field):
            raise PublicSuiteError(f"candidate/incumbent mismatch: {field}")
    candidate_metrics = candidate.get("metrics")
    incumbent_metrics = incumbent.get("metrics")
    if not isinstance(candidate_metrics, dict) or not isinstance(incumbent_metrics, dict):
        raise PublicSuiteError("candidate and incumbent metrics are required")
    overall_candidate = float(candidate_metrics.get("official_overall"))
    overall_incumbent = float(incumbent_metrics.get("official_overall"))
    dimensions = sorted((set(candidate_metrics) | set(incumbent_metrics)) - {"official_overall"})
    regressions: dict[str, float] = {}
    for key in dimensions:
        if key.endswith(("latency_ms", "cost_usd")):
            continue
        if key not in candidate_metrics or key not in incumbent_metrics:
            raise PublicSuiteError(f"missing comparison dimension: {key}")
        delta = float(candidate_metrics[key]) - float(incumbent_metrics[key])
        if delta < -0.01:
            regressions[key] = delta
    candidate_critical = int(candidate.get("critical_failure_count", -1))
    incumbent_critical = int(incumbent.get("critical_failure_count", -1))
    gate = (
        overall_candidate >= overall_incumbent
        and not regressions
        and candidate_critical == 0
        and incumbent_critical >= 0
        and int(candidate.get("runtime_failure_count", -1)) == 0
        and int(candidate.get("missing_prediction_count", -1)) == 0
        and candidate.get("gt_leakage_count") == 0
    )
    return {
        "benchmark_id": candidate["benchmark_id"],
        "candidate": candidate.get("candidate"),
        "incumbent": incumbent.get("candidate"),
        "official_overall_delta": overall_candidate - overall_incumbent,
        "dimension_regressions": regressions,
        "critical_failure_delta": candidate_critical - incumbent_critical,
        "gate_passed": gate,
    }


def evaluate_reproducibility(
    runs: list[dict[str, Any]], *, max_metric_span: float = 0.005
) -> dict[str, Any]:
    """Require three identical-environment runs with bounded metric drift."""
    if len(runs) != 3:
        raise PublicSuiteError("reproducibility gate requires exactly three runs")
    if max_metric_span < 0:
        raise PublicSuiteError("max metric span must be non-negative")
    identity_fields = (
        "benchmark_id",
        "candidate",
        "dataset_revision",
        "evaluator_commit",
        "environment_sha256",
    )
    reference = runs[0]
    for index, run in enumerate(runs[1:], start=2):
        for field in identity_fields:
            if run.get(field) != reference.get(field):
                raise PublicSuiteError(f"run {index} reproducibility mismatch: {field}")
    metric_names: set[str] | None = None
    metric_values: dict[str, list[float]] = {}
    run_gates: list[bool] = []
    for index, run in enumerate(runs, start=1):
        metrics = run.get("metrics")
        if not isinstance(metrics, dict) or not metrics:
            raise PublicSuiteError(f"run {index}: metrics are required")
        names = set(metrics)
        if metric_names is None:
            metric_names = names
        elif names != metric_names:
            raise PublicSuiteError(f"run {index}: metric set differs")
        for name, value in metrics.items():
            if name.endswith(("latency_ms", "cost_usd")):
                continue
            metric_values.setdefault(name, []).append(float(value))
        run_gates.append(
            int(run.get("runtime_failure_count", -1)) == 0
            and int(run.get("missing_prediction_count", -1)) == 0
            and int(run.get("critical_failure_count", -1)) == 0
            and run.get("gt_leakage_count") == 0
        )
    spans = {
        name: max(values) - min(values) for name, values in sorted(metric_values.items())
    }
    unstable = {
        name: span for name, span in spans.items() if span > max_metric_span
    }
    return {
        "schema_version": "1.0",
        "benchmark_id": reference.get("benchmark_id"),
        "candidate": reference.get("candidate"),
        "repetitions": 3,
        "max_metric_span": max_metric_span,
        "metric_spans": spans,
        "unstable_metrics": unstable,
        "all_run_gates_passed": all(run_gates),
        "gate_passed": all(run_gates) and not unstable,
    }


def sign_report(report: dict[str, Any], *, key_path: Path | None) -> dict[str, Any]:
    payload = _canonical_bytes(report)
    result = dict(report)
    result["report_sha256"] = _digest(payload)
    if key_path is None:
        result["signature"] = None
        result["signature_status"] = "unsigned_external_key_required"
        return result
    openssl = shutil.which("openssl")
    if openssl is None:
        raise PublicSuiteError("openssl is required to sign a report")
    completed = subprocess.run(
        [openssl, "dgst", "-sha256", "-sign", str(key_path)],
        input=payload,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise PublicSuiteError("report signing failed")
    import base64

    result["signature"] = base64.b64encode(completed.stdout).decode("ascii")
    result["signature_status"] = "signed"
    return result


def _write_json(path: Path | None, value: dict[str, Any]) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(encoded, end="")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise PublicSuiteError(f"{path}:{number}: JSON object required")
        records.append(value)
    if not records:
        raise PublicSuiteError("critical evaluator input is empty")
    return records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    commands = parser.add_subparsers(dest="command", required=True)

    verify = commands.add_parser("verify-registry")
    verify.add_argument("--online", action="store_true")
    verify.add_argument("--output", type=Path)

    adapt = commands.add_parser("adapt")
    adapt.add_argument("--benchmark", required=True)
    adapt.add_argument("--cir", type=Path, required=True)
    adapt.add_argument("--page-index", type=int, required=True)
    adapt.add_argument("--output", type=Path, required=True)

    freeze = commands.add_parser("freeze")
    freeze.add_argument("--predictions", type=Path, required=True)
    freeze.add_argument("--candidate", required=True)
    freeze.add_argument("--output", type=Path, required=True)

    isolation = commands.add_parser("audit-isolation")
    isolation.add_argument("--prediction-manifest", type=Path, required=True)
    isolation.add_argument("--ground-truth-root", type=Path, required=True)
    isolation.add_argument("--output", type=Path)

    critical = commands.add_parser("critical-evaluate")
    critical.add_argument("--records", type=Path, required=True)
    critical.add_argument("--output", type=Path, required=True)

    compare = commands.add_parser("compare")
    compare.add_argument("--candidate", type=Path, required=True)
    compare.add_argument("--incumbent", type=Path, required=True)
    compare.add_argument("--output", type=Path, required=True)

    reproducibility = commands.add_parser("reproducibility")
    reproducibility.add_argument("--run", type=Path, action="append", required=True)
    reproducibility.add_argument("--max-metric-span", type=float, default=0.005)
    reproducibility.add_argument("--output", type=Path, required=True)

    report = commands.add_parser("report")
    report.add_argument("--input", type=Path, required=True)
    report.add_argument("--signing-key", type=Path)
    report.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "verify-registry":
            result = verify_registry(registry_path=args.registry, online=args.online)
            _write_json(args.output, result)
        elif args.command == "adapt":
            _load_registry(args.registry)
            if args.page_index < 0:
                raise PublicSuiteError("page index must be non-negative")
            _write_json(
                args.output,
                adapt_cir(
                    _load_json(args.cir),
                    benchmark_id=args.benchmark,
                    page_index=args.page_index,
                ),
            )
        elif args.command == "freeze":
            _write_json(
                args.output,
                freeze_predictions(
                    input_dir=args.predictions,
                    output_manifest=args.output,
                    candidate=args.candidate,
                ),
            )
        elif args.command == "audit-isolation":
            _write_json(
                args.output,
                audit_isolation(
                    inference_manifest=args.prediction_manifest,
                    ground_truth_root=args.ground_truth_root,
                ),
            )
        elif args.command == "critical-evaluate":
            _write_json(args.output, critical_evaluate(_read_jsonl(args.records)))
        elif args.command == "compare":
            _write_json(
                args.output,
                compare_runs(_load_json(args.candidate), _load_json(args.incumbent)),
            )
        elif args.command == "reproducibility":
            _write_json(
                args.output,
                evaluate_reproducibility(
                    [_load_json(path) for path in args.run],
                    max_metric_span=args.max_metric_span,
                ),
            )
        elif args.command == "report":
            _write_json(args.output, sign_report(_load_json(args.input), key_path=args.signing_key))
        else:  # pragma: no cover
            parser.error("unsupported command")
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, PublicSuiteError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
