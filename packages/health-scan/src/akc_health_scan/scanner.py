"""scan(root_path, config) -> HealthReport — orchestrates all §5.2 sections."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from . import (
    conflicts,
    dates,
    duplicates,
    identity,
    readiness,
    references,
    sensitive,
)
from .config import HealthScanConfig
from .inventory import FileRecord, compute_digests, iter_files
from .models import HEURISTIC_LABEL, LABEL_POLICY, HealthReport


def scan(root_path: str | Path, config: HealthScanConfig | None = None) -> HealthReport:
    cfg = config or HealthScanConfig()
    root = Path(root_path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"health scan root is not a directory: {root}")

    started = time.perf_counter()
    records = iter_files(root, cfg)
    digests, skipped_hashing = compute_digests(records, cfg)

    sources = {
        "label": HEURISTIC_LABEL,
        "discovered_files": len(records),
        "artifact_count": len(records),
        "by_extension": _by_extension(records),
        "source_candidate_count": sum(
            1 for r in records if r.suffix in cfg.source_suffixes
        ),
        "excluded_dir_names": sorted(cfg.excluded_dir_names),
        "skipped_hashing": skipped_hashing,
        "note": "filesystem-derived counts; classification by file extension only",
    }

    report = HealthReport(
        generated_at_utc=datetime.now(UTC).isoformat(timespec="seconds"),
        root_path=str(root),
        label_policy=LABEL_POLICY,
        duration_ms=int((time.perf_counter() - started) * 1000),
        config=cfg.echo(),
        sources=sources,
        duplicates=duplicates.analyze(records, digests, cfg, skipped_hashing),
        identity_collisions=identity.analyze(records),
        conflicting_candidates=conflicts.analyze(records, digests),
        stale_references=references.analyze(records, cfg),
        unresolved_dates=dates.analyze(records, cfg),
        sensitive_exposure=sensitive.analyze(records, cfg),
        projection_readiness=readiness.analyze_readiness(records, cfg),
        estimated_compile_work=readiness.analyze_estimate(records, cfg),
    )
    report.duration_ms = int((time.perf_counter() - started) * 1000)
    return report


def _by_extension(records: list[FileRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.suffix] = counts.get(record.suffix, 0) + 1
    return dict(sorted(counts.items()))
