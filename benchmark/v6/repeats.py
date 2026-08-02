"""Exactly-three same-environment repeat planning and isolation validation."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .contracts import ContractError, EnvironmentIdentity, canonical_sha256, require_sha256

EXACT_REPEAT_COUNT = 3


@dataclass(frozen=True, slots=True)
class RepeatRun:
    cohort_id: str
    run_id: str
    repeat_index: int
    candidate_id: str
    benchmark_id: str
    environment_sha256: str
    repeat_root: Path
    prediction_root: Path
    log_root: Path
    official_result_root: Path
    critical_result_root: Path

    def to_dict(self) -> dict[str, object]:
        return {
            "cohort_id": self.cohort_id,
            "run_id": self.run_id,
            "repeat_index": self.repeat_index,
            "candidate_id": self.candidate_id,
            "benchmark_id": self.benchmark_id,
            "environment_sha256": self.environment_sha256,
            "repeat_root": self.repeat_root.as_posix(),
            "prediction_root": self.prediction_root.as_posix(),
            "log_root": self.log_root.as_posix(),
            "official_result_root": self.official_result_root.as_posix(),
            "critical_result_root": self.critical_result_root.as_posix(),
        }


def build_exact_repeat_plan(
    *,
    base_root: Path,
    benchmark_id: str,
    environment: EnvironmentIdentity,
) -> tuple[RepeatRun, ...]:
    if not benchmark_id.strip():
        raise ContractError("benchmark_id is required")
    root = base_root.resolve(strict=False)
    cohort_seed = {
        "benchmark_id": benchmark_id,
        "candidate_id": environment.candidate_id,
        "environment_sha256": environment.environment_sha256,
    }
    cohort_id = "cohort-" + canonical_sha256(cohort_seed).split(":", 1)[1][:24]
    runs: list[RepeatRun] = []
    for repeat_index in range(1, EXACT_REPEAT_COUNT + 1):
        repeat_root = root / cohort_id / f"run-{repeat_index}"
        digest = hashlib.sha256(f"{cohort_id}\0{repeat_index}".encode()).hexdigest()[:24]
        runs.append(
            RepeatRun(
                cohort_id=cohort_id,
                run_id=f"run-{digest}",
                repeat_index=repeat_index,
                candidate_id=environment.candidate_id,
                benchmark_id=benchmark_id,
                environment_sha256=environment.environment_sha256,
                repeat_root=repeat_root,
                prediction_root=repeat_root / "predictions",
                log_root=repeat_root / "logs",
                official_result_root=repeat_root / "official-results",
                critical_result_root=repeat_root / "critical-results",
            )
        )
    validate_repeat_plan(runs)
    return tuple(runs)


def materialize_repeat_plan(runs: Sequence[RepeatRun]) -> None:
    """Create isolated roots and an immutable contract sentinel for each run."""

    validate_repeat_plan(runs)
    for run in runs:
        for path in (
            run.prediction_root,
            run.log_root,
            run.official_result_root,
            run.critical_result_root,
        ):
            path.mkdir(parents=True, exist_ok=False)
        sentinel = run.repeat_root / "repeat-contract.json"
        sentinel.write_text(
            _pretty_json({**run.to_dict(), "contract_sha256": canonical_sha256(run.to_dict())}),
            encoding="utf-8",
        )


def validate_repeat_plan(runs: Sequence[RepeatRun]) -> dict[str, object]:
    if len(runs) != EXACT_REPEAT_COUNT:
        raise ContractError("public-core cohorts require exactly three repeats")
    if {run.repeat_index for run in runs} != {1, 2, 3}:
        raise ContractError("repeat indexes must be exactly {1, 2, 3}")
    for field in ("cohort_id", "candidate_id", "benchmark_id", "environment_sha256"):
        values = {getattr(run, field) for run in runs}
        if len(values) != 1:
            raise ContractError(f"all repeats must share {field}")
    require_sha256(runs[0].environment_sha256, "environment_sha256")
    if len({run.run_id for run in runs}) != EXACT_REPEAT_COUNT:
        raise ContractError("repeat run IDs must be unique")
    if len({run.repeat_root.resolve(strict=False) for run in runs}) != EXACT_REPEAT_COUNT:
        raise ContractError("repeat roots must be unique")

    all_artifact_roots: list[Path] = []
    for run in runs:
        repeat_root = run.repeat_root.resolve(strict=False)
        roots = (
            run.prediction_root,
            run.log_root,
            run.official_result_root,
            run.critical_result_root,
        )
        resolved = tuple(path.resolve(strict=False) for path in roots)
        if len(set(resolved)) != len(resolved):
            raise ContractError(f"artifact roots overlap within {run.run_id}")
        if any(repeat_root not in path.parents for path in resolved):
            raise ContractError(f"artifact root escapes repeat root for {run.run_id}")
        all_artifact_roots.extend(resolved)
    if len(set(all_artifact_roots)) != len(all_artifact_roots):
        raise ContractError("prediction/log/result roots may not be shared across repeats")

    return {
        "gate": "G2_REPEAT_ISOLATION",
        "passed": True,
        "repeat_count": EXACT_REPEAT_COUNT,
        "environment_sha256": runs[0].environment_sha256,
        "isolated_predictions": True,
        "isolated_logs": True,
        "plan_sha256": canonical_sha256([run.to_dict() for run in runs]),
    }


def _pretty_json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
