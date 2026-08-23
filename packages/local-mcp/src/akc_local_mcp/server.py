"""The stdio MCP server: exactly three read-only tools, two read-only resources.

READ-ONLY BY CONSTRUCTION — FORBIDDEN TOOL LIST
-----------------------------------------------
This server serves an offline desktop scenario over local JSON files, and it
must never grow a way to change what it serves. The following are prohibited
here, permanently, and must never be registered as MCP tools by any future
change to this package:

- ``knowledge.write`` / ``knowledge.update`` / ``knowledge.delete`` /
  ``knowledge.publish`` / ``knowledge.approve`` — compiled truth is produced by
  the compiler pipeline, never edited through MCP.
- ``world_state.create`` / ``world_state.stage`` / ``world_state.publish`` /
  ``world_state.promote`` / ``world_state.rollback`` / ``world_state.delete``
  — publishing a world state is atomic pipeline work (masterplan invariant 13);
  a chat side channel may not move the pointer.
- any document/source ingestion or upload (``document.ingest``,
  ``source.upload``, connector triggers).
- entity writes (merge/split/override), recompilation triggers,
  ``knowledge.diff``-application, staleness marking.
- credit/billing mutations, auth/ACL/admin changes of any kind.

Masterplan v5 PART 16 restricts MCP to *Read-only*; Write/Decision-Replay MCP
is PHASE 20 and GATED. This module implements only the read half. The tool
surface below is exhaustive: three tools (`get_current_truth`, `get_evidence`,
`search_world`) and two resources (`worlds://index`,
`worlds://{world_id}/manifest`), all backed by `LocalWorldStore`, which exposes
no mutating method.

Every answer carries the manifest hash of the world it was computed against;
every refusal is an explicit UNRESOLVED (Contract A) rather than a guess.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from .settings import LocalMcpSettings
from .store import LocalWorldStore
from .tools import (
    TOOL_SCOPE_GUARD,
    ReasonCode,
    ToolResponse,
    get_current_truth,
    get_evidence,
    search_world,
)


def _outside_scope(tool_name: str) -> str:
    """UNRESOLVED answer for a dispatch attempt outside the declared scope."""
    return _to_json(
        ToolResponse.unresolved(
            ReasonCode.INVALID_INPUT,
            f"tool {tool_name!r} is not part of the declared read-only tool scope",
        )
    )

__all__ = ["build_server", "main"]

SERVER_NAME = "akc-local-mcp"

_INSTRUCTIONS = (
    "Read-only view over one locally published world state (offline desktop "
    "mode; no services/api process). Prefer get_current_truth for a topic's "
    "compiled answer, get_evidence to audit a specific claim, search_world to "
    "locate topics and claims. Every response names the world manifest hash it "
    "was computed from. When a question cannot be grounded in the published "
    "world the tools answer status=UNRESOLVED with a reason code: treat that "
    "as 'not answerable from published state', never as confirmation."
)


def _to_json(response: ToolResponse) -> str:
    return json.dumps(response.to_dict(), ensure_ascii=False, indent=2, sort_keys=False)


def build_server(settings: LocalMcpSettings | None = None) -> FastMCP:
    """Assemble the FastMCP server. No tool here mutates anything."""
    resolved = settings or LocalMcpSettings()
    store = LocalWorldStore(resolved.world_state_dir)
    server: FastMCP = FastMCP(name=SERVER_NAME, instructions=_INSTRUCTIONS)

    @server.tool(name="get_current_truth")
    def get_current_truth_tool(topic: str) -> str:
        """Return the current-truth record for one topic, with its claims.

        Answers CURRENT (with the topic, its claims and their evidence) or
        UNRESOLVED with a reason code when no ACTIVE world exists or the topic
        does not match exactly/uniquely.
        """
        if not TOOL_SCOPE_GUARD.authorize("get_current_truth"):
            return _outside_scope("get_current_truth")
        return _to_json(get_current_truth(store, topic))

    @server.tool(name="get_evidence")
    def get_evidence_tool(claim_id: str) -> str:
        """Return one claim's evidence chain from the ACTIVE world.

        Answers CURRENT (claim plus its evidence items) or UNRESOLVED when the
        claim id is unknown to the published world.
        """
        if not TOOL_SCOPE_GUARD.authorize("get_evidence"):
            return _outside_scope("get_evidence")
        return _to_json(get_evidence(store, claim_id))

    @server.tool(name="search_world")
    def search_world_tool(query: str, limit: int = 10) -> str:
        """Search topics and claims by case-insensitive substring.

        Returns matching entries (kind, id, matched field, snippet) capped at
        `limit`, or UNRESOLVED (NO_MATCHES) when nothing matches.
        """
        if not TOOL_SCOPE_GUARD.authorize("search_world"):
            return _outside_scope("search_world")
        return _to_json(search_world(store, query, limit=limit))

    @server.resource("worlds://index")
    def worlds_index() -> str:
        """List every world directory that declares a readable manifest."""
        manifests = store.list_worlds()
        payload = {
            "worlds": [manifest.to_dict() for manifest in manifests],
            "root": str(store.root),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    @server.resource("worlds://{world_id}/manifest")
    def world_manifest(world_id: str) -> str:
        """Read one world's published manifest verbatim."""
        manifest = store.load_manifest(world_id)
        return json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2)

    return server


def main() -> None:
    """Entry point: run the server on stdio (default transport)."""
    build_server().run()
