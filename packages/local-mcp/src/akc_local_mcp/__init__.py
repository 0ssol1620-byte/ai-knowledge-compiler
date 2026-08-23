"""`akc-local-mcp` — read-only MCP view over locally published world states.

An offline desktop scenario: no `services/api`, no database — just the JSON
files the compiler published into a world-state directory. The server exposes
exactly ten read-only tools (`get_current_truth`, `get_evidence`,
`search_world`, `ask_as_of`, `get_entity`, `get_claim`, `get_change`,
`trace_impact`, `get_world`, `compare_worlds`) and two read-only resources
(worlds index, per-world manifest). It cannot write anything; the
forbidden-tool list lives in `akc_local_mcp.server`.

Every answer is world-stamped: it names the world id and manifest hash it was
computed against, its `built_at` freshness, and explicit limitations. Every
question that cannot be grounded in the published world is answered UNRESOLVED
(Contract A, fail-closed): missing world state, unknown topic/claim/entity/
change/node, no world at the asked date, or zero search hits are refusals with
reasons — never silent successes.
"""

from __future__ import annotations

from .server import build_server, main
from .settings import LocalMcpSettings
from .store import (
    ChangeRecord,
    ChangeSummary,
    ClaimDiff,
    ClaimFieldChange,
    ClaimRecord,
    DependencyEdgeRecord,
    EntityRecord,
    EvidenceRecord,
    LocalWorldStore,
    StoreError,
    TopicRecord,
    UnknownWorldError,
    WorldDiff,
    WorldDocumentError,
    WorldManifest,
    WorldSnapshot,
)
from .tools import (
    ReasonCode,
    ToolResponse,
    WorldRef,
    ask_as_of,
    compare_worlds,
    get_change,
    get_claim,
    get_current_truth,
    get_entity,
    get_evidence,
    get_world,
    search_world,
    trace_impact,
)

__all__ = [
    "ChangeRecord",
    "ChangeSummary",
    "ClaimDiff",
    "ClaimFieldChange",
    "ClaimRecord",
    "DependencyEdgeRecord",
    "EntityRecord",
    "EvidenceRecord",
    "LocalMcpSettings",
    "LocalWorldStore",
    "ReasonCode",
    "StoreError",
    "ToolResponse",
    "TopicRecord",
    "UnknownWorldError",
    "WorldDiff",
    "WorldDocumentError",
    "WorldManifest",
    "WorldRef",
    "WorldSnapshot",
    "ask_as_of",
    "build_server",
    "compare_worlds",
    "get_change",
    "get_claim",
    "get_current_truth",
    "get_entity",
    "get_evidence",
    "get_world",
    "main",
    "search_world",
    "trace_impact",
]

__version__ = "0.2.0"
