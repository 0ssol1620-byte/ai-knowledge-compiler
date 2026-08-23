"""akc-health-scan: local-only Health Scan analyzer (blueprint §5.2)."""

from __future__ import annotations

from .config import HealthScanConfig
from .models import ENGINE_ID, ENGINE_VERSION, SCHEMA_VERSION, HealthReport
from .scanner import scan

__version__ = ENGINE_VERSION
__all__ = [
    "ENGINE_ID",
    "ENGINE_VERSION",
    "SCHEMA_VERSION",
    "HealthReport",
    "HealthScanConfig",
    "scan",
    "__version__",
]
