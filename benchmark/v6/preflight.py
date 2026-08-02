"""Offline preflight for v6 benchmark and RunPod orchestration contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from infra.runpod.v6.orchestration import PoolRegistry

from .contracts import ContractError, canonical_sha256
from .registry import CandidateRegistry

_PUBLIC_CORE_IDS = {"omnidocbench", "parsebench", "olmocr-bench"}
_EXTERNAL_BLOCKERS = (
    "EXACT_MODEL_ARTIFACT_RUNTIME_IDENTITIES_PENDING",
    "MANDATORY_EXTERNAL_PUBLIC_PRIVATE_ROBUSTNESS_RUNS_NOT_EXECUTED",
    "EXACT_THREE_SAME_ENVIRONMENT_REPEATS_NOT_EXECUTED",
    "ACTUAL_RUNPOD_COST_AND_SPEEDUP_NOT_MEASURED",
    "TEMPORARY_ENDPOINT_CLEANUP_RECEIPTS_MISSING",
    "SIGNED_EXTERNAL_EVIDENCE_MISSING",
    "LICENSE_DECISIONS_PENDING",
    "CHAMPION_MATRIX_UNRESOLVED",
)


def run_local_preflight(repo_root: Path) -> dict[str, object]:
    repo_root = repo_root.resolve(strict=True)
    registry_path = repo_root / "benchmark/v6/candidate-registry.yaml"
    pool_path = repo_root / "infra/runpod/v6/pool-registry.yaml"
    public_registry_path = repo_root / "benchmark/benchmark-registry.lock.yaml"
    dataset_registry_path = repo_root / "benchmark/v6/dataset-registry.lock.yaml"
    champion_path = repo_root / "benchmark/v6/champion-matrix.yaml"
    champion_schema_path = repo_root / "benchmark/v6/schemas/champion-matrix.schema.json"

    candidates = CandidateRegistry.load(registry_path)
    pools = PoolRegistry.load(pool_path)
    public_registry = _read_yaml_mapping(public_registry_path)
    dataset_registry = _read_yaml_mapping(dataset_registry_path)
    champion = _read_yaml_mapping(champion_path)
    champion_schema = json.loads(champion_schema_path.read_text(encoding="utf-8"))
    _validate_champion_matrix(champion, champion_schema)

    public_rows = public_registry.get("benchmarks")
    if not isinstance(public_rows, list):
        raise ContractError("public benchmark registry has no benchmark rows")
    public_ids = {
        str(row.get("id"))
        for row in public_rows
        if isinstance(row, Mapping) and bool(row.get("required"))
    }
    if public_ids != _PUBLIC_CORE_IDS:
        raise ContractError(f"public-core suite mismatch: {sorted(public_ids)}")
    policy = public_registry.get("policy")
    if not isinstance(policy, Mapping) or policy.get("repetitions") != 3:
        raise ContractError("public benchmark registry must require exactly three repetitions")
    if policy.get("ground_truth_inference_access") != "forbidden":
        raise ContractError("public benchmark registry must forbid inference GT access")
    _validate_dataset_registry(dataset_registry, public_rows)

    pool_candidates = {candidate_id for pool in pools.pools for candidate_id in pool.candidate_ids}
    unknown_pool_candidates = sorted(
        candidate_id
        for candidate_id in pool_candidates
        if candidate_id not in {candidate.candidate_id for candidate in candidates.candidates}
    )
    if unknown_pool_candidates:
        raise ContractError(f"RunPod pool references unknown candidates: {unknown_pool_candidates}")
    if any(pool.enabled for pool in pools.pools):
        raise ContractError(
            "local contract may not enable a pool before external identity receipts"
        )

    champion_rows = champion.get("champions")
    if not isinstance(champion_rows, Mapping) or not champion_rows:
        raise ContractError("champion matrix template is missing page classes")
    premature = sorted(
        str(page_class)
        for page_class, row in champion_rows.items()
        if isinstance(row, Mapping) and row.get("primary") is not None
    )
    if premature:
        raise ContractError(f"champions selected without external evidence: {premature}")

    schema_paths = sorted((repo_root / "benchmark/v6/schemas").glob("*.schema.json"))
    schema_paths.extend(sorted((repo_root / "infra/runpod/v6/schemas").glob("*.schema.json")))
    for schema_path in schema_paths:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

    result: dict[str, object] = {
        "schema_version": "6.0.0",
        "local_contract_gate": "pass",
        "production_gate": "reject",
        "production_evidence": False,
        "paid_endpoints_created_by_preflight": 0,
        "external_runs_completed_by_preflight": 0,
        "candidate_count": len(candidates.candidates),
        "required_candidate_count": len(candidates.required_ids),
        "model_revisions_pinned_count": sum(
            candidate.model_revision_pinned for candidate in candidates.candidates
        ),
        "required_model_revisions_pinned_count": sum(
            candidates.get(candidate_id).model_revision_pinned
            for candidate_id in candidates.required_ids
        ),
        "required_candidates_promotion_eligible": len(candidates.required_ids)
        - len(candidates.externally_blocked_required_ids),
        "model_pool_count": len(pools.pools),
        "public_core_suites": sorted(public_ids),
        "public_core_required_repetitions": 3,
        "schema_count": len(schema_paths),
        "external_blockers": list(_EXTERNAL_BLOCKERS),
        "artifact_hashes": {
            "candidate_registry": _file_sha256(registry_path),
            "pool_registry": _file_sha256(pool_path),
            "public_benchmark_registry": _file_sha256(public_registry_path),
            "v6_dataset_registry": _file_sha256(dataset_registry_path),
            "champion_matrix_template": _file_sha256(champion_path),
        },
    }
    result["preflight_sha256"] = canonical_sha256(result)
    return result


def _read_yaml_mapping(path: Path) -> Mapping[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ContractError(f"cannot read YAML contract {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ContractError(f"YAML contract must be an object: {path}")
    return value


def _file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_champion_matrix(
    champion: Mapping[str, Any], schema: Mapping[str, Any]
) -> None:
    try:
        jsonschema.Draft202012Validator(schema).validate(dict(champion))
    except jsonschema.ValidationError as exc:
        location = ".".join(str(part) for part in exc.absolute_path) or "root"
        raise ContractError(
            f"champion matrix schema violation at {location}: {exc.message}"
        ) from exc
    claimed = champion.get("matrix_sha256")
    material = dict(champion)
    material.pop("matrix_sha256", None)
    if claimed != canonical_sha256(material):
        raise ContractError("champion matrix canonical digest mismatch")
    rows = champion.get("champions")
    if not isinstance(rows, Mapping):
        raise ContractError("champion matrix rows are missing")
    for page_class, raw in rows.items():
        if not isinstance(raw, Mapping):
            raise ContractError(f"champion row is not an object: {page_class}")
        primary = raw.get("primary")
        status = raw.get("status")
        evidence = raw.get("evidence_sha256")
        if primary is None and (status != "unresolved" or evidence is not None):
            raise ContractError(f"unresolved champion row is internally inconsistent: {page_class}")
        if primary is not None and (status != "production" or not isinstance(evidence, str)):
            raise ContractError(f"production champion row lacks signed evidence: {page_class}")


def _validate_dataset_registry(
    dataset_registry: Mapping[str, Any],
    public_rows: list[object],
) -> None:
    if dataset_registry.get("schema_version") != "6.0.0":
        raise ContractError("v6 dataset registry schema_version must be 6.0.0")
    policy = dataset_registry.get("policy")
    if not isinstance(policy, Mapping):
        raise ContractError("v6 dataset registry policy is missing")
    if policy.get("inference_ground_truth_access") != "forbidden":
        raise ContractError("v6 dataset registry must forbid inference GT access")
    if policy.get("public_core_repetitions") != 3:
        raise ContractError("v6 dataset registry must require exactly three public repeats")
    locked_rows = dataset_registry.get("public_core")
    if not isinstance(locked_rows, list):
        raise ContractError("v6 dataset registry public_core is missing")
    existing_by_id = {str(row.get("id")): row for row in public_rows if isinstance(row, Mapping)}
    for locked in locked_rows:
        if not isinstance(locked, Mapping):
            raise ContractError("v6 dataset registry rows must be mappings")
        benchmark_id = str(locked.get("id"))
        existing = existing_by_id.get(benchmark_id)
        if existing is None:
            raise ContractError(f"v6 dataset missing from public registry: {benchmark_id}")
        evaluator = existing.get("evaluator")
        dataset = existing.get("dataset")
        if not isinstance(evaluator, Mapping) or not isinstance(dataset, Mapping):
            raise ContractError(f"public registry identity incomplete: {benchmark_id}")
        expected = {
            "evaluator_commit": evaluator.get("commit"),
            "dataset_revision": dataset.get("revision"),
            "dataset_manifest_sha256": dataset.get("manifest_sha256"),
        }
        actual = {key: locked.get(key) for key in expected}
        if actual != expected or locked.get("repetitions") != 3:
            raise ContractError(f"v6 dataset identity drift: {benchmark_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    args = parser.parse_args()
    result = run_local_preflight(args.repo_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
