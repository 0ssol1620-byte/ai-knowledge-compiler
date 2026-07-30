"""Run a reproducible benchmark lane and emit immutable-style score records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.evaluators.masterplan_metrics import EVALUATOR_VERSION
from benchmark.evaluators.metrics import score_case, utility
from benchmark.runners.base import build_provider_payload, deterministic_local_mock
from benchmark.runners.native import run as run_native
from benchmark.runners.registry import EXTERNAL_RUNNERS

_SAFE_ARTIFACT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
_IMMUTABLE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: JSON object required")
            records.append(value)
    return records


def parser_output_validator(manifest_path: Path) -> Draft202012Validator:
    repository_root = manifest_path.resolve().parent.parent
    schema_root = repository_root / "benchmark" / "schemas"
    page_schema = json.loads(
        (schema_root / "page-ground-truth.schema.json").read_text(encoding="utf-8")
    )
    output_schema = json.loads(
        (schema_root / "parser-output.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(
        page_schema["$id"],
        Resource.from_contents(page_schema),
    )
    return Draft202012Validator(output_schema, registry=registry)


def persist_raw_result(
    output: dict[str, Any],
    *,
    raw_output_dir: Path,
    benchmark_case_id: str,
) -> str:
    provider = str(output.get("provider", "unknown"))
    if (
        _SAFE_ARTIFACT_ID.fullmatch(benchmark_case_id) is None
        or _SAFE_ARTIFACT_ID.fullmatch(provider) is None
    ):
        raise ValueError("benchmark case/provider cannot form a safe artifact path")
    encoded = (
        json.dumps(
            output,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    case_dir = raw_output_dir.resolve() / benchmark_case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    target = case_dir / f"{provider}.json"
    target.write_bytes(encoded)
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("benchmark/manifest.yaml"))
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument(
        "--provider",
        choices=["local_mock", "native_pdf", "native_document", *sorted(EXTERNAL_RUNNERS)],
        default="local_mock",
    )
    parser.add_argument(
        "--corpus-root",
        type=Path,
        help="Approved local corpus root; mandatory for the real native lane.",
    )
    parser.add_argument(
        "--raw-output-dir",
        type=Path,
        help="Private raw provider artifact directory; mandatory for non-mock lanes.",
    )
    parser.add_argument(
        "--endpoint",
        help="Exact HTTPS endpoint for an explicitly selected external benchmark provider.",
    )
    parser.add_argument(
        "--model-revision",
        help="Exact immutable provider revision expected in every response.",
    )
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly permit the allowlisted external benchmark endpoint.",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    with args.manifest.open("r", encoding="utf-8") as handle:
        manifest = yaml.safe_load(handle)
    is_native = args.provider in {"native_pdf", "native_document"}
    is_external = args.provider in EXTERNAL_RUNNERS
    if is_native:
        if args.corpus_root is None:
            parser.error("--corpus-root is required for the native parser lane")
        if args.raw_output_dir is None:
            parser.error("--raw-output-dir is required for every non-mock lane")
    if is_external:
        if args.raw_output_dir is None:
            parser.error("--raw-output-dir is required for every non-mock lane")
        if not args.endpoint:
            parser.error("--endpoint is required for an external provider")
        if not args.model_revision:
            parser.error("--model-revision is required for an external provider")
        if _IMMUTABLE_REVISION.fullmatch(args.model_revision) is None:
            parser.error("--model-revision must be a 40-64 character lowercase hex revision")
        if not args.allow_network:
            parser.error("--allow-network is required for an external provider")
    validator = parser_output_validator(args.manifest)
    started = utc_now()
    records = []
    for case in load_jsonl(args.ground_truth):
        if args.provider == "local_mock":
            output = deterministic_local_mock(case)
        elif is_native:
            output = run_native(case, corpus_root=args.corpus_root)
        else:
            runner = EXTERNAL_RUNNERS[args.provider]
            provider_payload = build_provider_payload(
                case,
                corpus_root=args.corpus_root,
            )
            output = runner(
                provider_payload,
                endpoint=args.endpoint,
                revision=args.model_revision,
                allow_network=args.allow_network,
            )
            if output.get("benchmark_case_id") != case.get("benchmark_case_id"):
                raise ValueError(
                    f"{case['benchmark_case_id']}: provider returned a mismatched case id"
                )
        validation_errors = sorted(
            validator.iter_errors(output),
            key=lambda error: list(error.path),
        )
        if validation_errors:
            messages = "; ".join(error.message for error in validation_errors[:5])
            raise ValueError(
                f"{case['benchmark_case_id']}: parser output contract failed: {messages}"
            )
        raw_result_sha256 = (
            persist_raw_result(
                output,
                raw_output_dir=args.raw_output_dir,
                benchmark_case_id=str(case["benchmark_case_id"]),
            )
            if args.raw_output_dir is not None
            else None
        )
        metrics, hard_failures = score_case(case, output, output.get("metrics"))
        finished = utc_now()
        reproducibility = {
            "started_at": started,
            "finished_at": finished,
            "input_sha256": canonical_sha256(case),
            "prompt_schema_version": "benchmark-contract-1.0",
            "hardware_profile": "local_contract",
            "cold_or_warm": "warm",
            "retry_history": [],
        }
        if raw_result_sha256 is not None:
            reproducibility["raw_result_sha256"] = raw_result_sha256
        if output.get("source_sha256"):
            reproducibility["source_sha256"] = f"sha256:{output['source_sha256']}"
        records.append(
            {
                "benchmark_id": manifest["benchmark_id"],
                "evaluator_version": EVALUATOR_VERSION,
                "corpus_version": manifest["corpus_version"],
                "benchmark_case_id": case["benchmark_case_id"],
                "provider": output["provider"],
                "model_revision": output["model_revision"],
                "claim_class": (
                    "contract_test" if case.get("is_synthetic") is True else "internal_result"
                ),
                "is_synthetic": bool(case.get("is_synthetic")),
                "metrics": metrics,
                "utility": utility(metrics),
                "hard_failures": sorted(set(hard_failures)),
                "reproducibility": reproducibility,
            }
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"wrote {len(records)} benchmark records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
