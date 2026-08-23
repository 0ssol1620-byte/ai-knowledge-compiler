"""Health Scan API — authenticated exposure of the local workspace analyzer.

The desktop client owns a workspace on the local disk and asks the control
plane to run blueprint §5.2 analysis over it. This surface is deliberately
thin transport:

* Authentication is mandatory — a real session (cookie or bearer), exactly
  like every other mutating route; there is no anonymous scanning.
* A path guard maps a missing workspace to 404 before any work starts.
* A file-count guard refuses oversized trees with 413 so a single request
  cannot pin a worker hashing an unbounded corpus.
* The analyzer's report is returned verbatim: every finding keeps its
  ``"label": "heuristic"`` because this endpoint performs no classification
  of its own and must never launder heuristics into verdicts.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any

from akc_health_scan import HealthScanConfig, scan
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from akc_api.security import Principal, get_principal

router = APIRouter(prefix="/v1/health-scan", tags=["health-scan"])

PrincipalDep = Annotated[Principal, Depends(get_principal)]

#: Scan requests above this many discoverable files fail fast with 413
#: instead of tying up a worker. The walk that enforces it prunes the same
#: excluded directories the analyzer prunes, so tooling/vendor folders never
#: push a normal repository over the limit.
MAX_WORKSPACE_FILES = 5000


class HealthScanRequest(BaseModel):
    """Body of POST /v1/health-scan/scan."""

    workspace_path: str = Field(
        min_length=1,
        description="Absolute path to a local workspace directory to analyze.",
    )


def _count_files(root: Path, config: HealthScanConfig) -> int:
    """Count files under ``root``, stopping once the request is doomed."""
    total = 0
    for _dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in config.excluded_dir_names]
        total += len(filenames)
        if total > MAX_WORKSPACE_FILES:
            return total
    return total


@router.post("/scan")
def scan_workspace(
    payload: HealthScanRequest,
    principal: PrincipalDep,
) -> dict[str, Any]:
    """Analyze a local workspace and return the full §5.2 report JSON.

    The heavy filesystem work runs in the worker threadpool (sync handler),
    keeping the event loop responsive while digests are computed.
    """
    root = Path(payload.workspace_path)
    if not root.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"code": "WORKSPACE_NOT_FOUND"},
        )
    config = HealthScanConfig()
    resolved = root.resolve()
    discovered = _count_files(resolved, config)
    if discovered > MAX_WORKSPACE_FILES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "WORKSPACE_TOO_LARGE",
                "max_workspace_files": MAX_WORKSPACE_FILES,
            },
        )
    return scan(resolved, config).to_dict()
