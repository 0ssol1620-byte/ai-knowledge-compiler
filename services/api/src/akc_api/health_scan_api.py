"""Health Scan API — authenticated exposure of the local workspace analyzer.

The desktop client owns a workspace on the local disk and asks the control
plane to run blueprint §5.2 analysis over it. This surface is deliberately
thin transport:

* Authentication is mandatory — a real session (cookie or bearer), exactly
  like every other mutating route; there is no anonymous scanning.
* The API reads *this host's* disk, so the caller never picks an arbitrary
  path: the canonical (symlink-resolved) workspace must lie inside a root the
  operator listed in ``AKC_HEALTH_SCAN_ROOTS``, else 403. No roots configured
  means every scan is refused. The check runs before any existence probe so
  the endpoint is not a filesystem oracle outside the allowlist.
* Production refuses this route until workspaces are bound to tenant identity.
  The local CLI remains available for real health scans.
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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from akc_api.security import Principal, get_principal
from akc_api.settings import Settings

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


def _allowed_workspace(requested: str, roots: tuple[str, ...]) -> str | None:
    """Canonical ``requested`` if it is, or lies under, an allowlisted root."""
    if not os.path.isabs(requested):
        return None
    try:
        candidate = os.path.realpath(requested)
    except (OSError, ValueError):  # e.g. an embedded NUL byte
        return None
    for root in roots:
        # Prefix match plus a separator (or end) boundary, so ``/data/ws``
        # never admits ``/data/ws-other``.
        if candidate.startswith(root) and candidate[len(root) : len(root) + 1] in ("", os.sep):
            return candidate
    return None


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
    request: Request,
) -> dict[str, Any]:
    """Analyze a local workspace and return the full §5.2 report JSON.

    The heavy filesystem work runs in the worker threadpool (sync handler),
    keeping the event loop responsive while digests are computed.
    """
    settings: Settings = request.app.state.settings
    if settings.env == "production":
        raise HTTPException(
            status_code=403,
            detail={"code": "WORKSPACE_NOT_ALLOWED"},
        )
    allowed = _allowed_workspace(payload.workspace_path, settings.health_scan_root_paths)
    if allowed is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "WORKSPACE_NOT_ALLOWED"},
        )
    resolved = Path(allowed)
    if not resolved.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"code": "WORKSPACE_NOT_FOUND"},
        )
    config = HealthScanConfig()
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
