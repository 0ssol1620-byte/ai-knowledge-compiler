"""`akc-local-mcp` — read-only MCP view over locally published world states.

An offline desktop scenario: no `services/api`, no database — just the JSON
files the compiler published into a world-state directory. The server exposes
exactly three read-only tools (`get_current_truth`, `get_evidence`,
`search_world`) and two read-only resources (worlds index, per-world manifest).
It cannot write anything; the forbidden-tool list lives in
`akc_local_mcp.server`.

Every answer names the manifest hash it was computed against. Every question
that cannot be grounded in the published world is answered UNRESOLVED
(Contract A, fail-closed): missing world state, unknown topic, unknown claim,
or zero search hits are refusals with reasons — never silent successes.
"""

from __future__ import annotations

from .server import build_server, main
from .settings import LocalMcpSettings
from .store import (
    ClaimRecord,
    EvidenceRecord,
    LocalWorldStore,
    StoreError,
    TopicRecord,
    UnknownWorldError,
    WorldDocumentError,
    WorldManifest,
    WorldSnapshot,
)
from .tools import (
    ReasonCode,
    ToolResponse,
    WorldRef,
    get_current_truth,
    get_evidence,
    search_world,
)

__all__ = [
    "ClaimRecord",
    "EvidenceRecord",
    "LocalMcpSettings",
    "LocalWorldStore",
    "ReasonCode",
    "StoreError",
    "ToolResponse",
    "TopicRecord",
    "UnknownWorldError",
    "WorldDocumentError",
    "WorldManifest",
    "WorldRef",
    "WorldSnapshot",
    "build_server",
    "get_current_truth",
    "get_evidence",
    "main",
    "search_world",
]

__version__ = "0.1.0"
