"""Data containers and constants for the Health Scan report (blueprint §5.2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

ENGINE_ID = "akc-health-scan"
ENGINE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0"
HEURISTIC_LABEL = "heuristic"
LABEL_POLICY = (
    "every finding is labeled 'heuristic': derived from local filesystem "
    "analysis only; no network/cloud calls and no LLM calls are made"
)


@dataclass
class HealthReport:
    """Full §5.2 output. Each section dict carries ``label: 'heuristic'``."""

    schema_version: str = SCHEMA_VERSION
    engine: str = ENGINE_ID
    engine_version: str = ENGINE_VERSION
    generated_at_utc: str = ""
    root_path: str = ""
    label_policy: str = LABEL_POLICY
    duration_ms: int = 0
    config: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, Any] = field(default_factory=dict)
    duplicates: dict[str, Any] = field(default_factory=dict)
    identity_collisions: dict[str, Any] = field(default_factory=dict)
    conflicting_candidates: dict[str, Any] = field(default_factory=dict)
    stale_references: dict[str, Any] = field(default_factory=dict)
    unresolved_dates: dict[str, Any] = field(default_factory=dict)
    sensitive_exposure: dict[str, Any] = field(default_factory=dict)
    projection_readiness: dict[str, Any] = field(default_factory=dict)
    estimated_compile_work: dict[str, Any] = field(default_factory=dict)

    SECTION_NAMES = (
        "sources",
        "duplicates",
        "identity_collisions",
        "conflicting_candidates",
        "stale_references",
        "unresolved_dates",
        "sensitive_exposure",
        "projection_readiness",
        "estimated_compile_work",
    )

    def sections(self) -> dict[str, dict[str, Any]]:
        return {name: getattr(self, name) for name in self.SECTION_NAMES}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
