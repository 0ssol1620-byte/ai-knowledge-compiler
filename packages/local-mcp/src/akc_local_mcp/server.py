"""The stdio MCP server: ten read-only tools, two read-only resources.

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
surface below is exhaustive: ten tools (`get_current_truth`, `get_evidence`,
`search_world`, `ask_as_of`, `get_entity`, `get_claim`, `get_change`,
`trace_impact`, `get_world`, `compare_worlds`) and two resources
(`worlds://index`, `worlds://{world_id}/manifest`), all backed by
`LocalWorldStore`, which exposes no mutating method.

Every answer carries the manifest hash of the world it was computed against
(plus its `built_at` freshness and explicit limitations — world-stamped);
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
    "Read-only view over locally published world states (offline desktop mode; "
    "no services/api process). Prefer get_current_truth for a topic's compiled "
    "answer, get_evidence/get_claim to audit a claim, search_world to locate "
    "topics and claims, ask_as_of for what was true at a past date, "
    "get_entity/get_change for direct lookups, trace_impact for blast radius, "
    "get_world/compare_worlds to inspect or diff worlds. Every response names "
    "the world it came from (world_state_id + manifest hash + built_at "
    "freshness) under an explicit limitations list. When a question cannot be "
    "grounded in published state the tools answer status=UNRESOLVED with a "
    "reason code: treat that as 'not answerable from published state', never "
    "as confirmation."
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

    @server.tool(name="ask_as_of")
    def ask_as_of_tool(topic: str, as_of_date: str) -> str:
        """Answer a topic's truth as it stood at a past date.

        Reads the world timeline on disk and serves the newest publishable
        world (ACTIVE or SUPERSEDED) built on or before `as_of_date`
        (`YYYY-MM-DD` includes the whole day; a full ISO timestamp is exact).
        UNRESOLVED (NO_WORLD_AT_DATE) when nothing publishable existed yet.
        """
        return _to_json(ask_as_of(store, topic, as_of_date))

    @server.tool(name="get_entity")
    def get_entity_tool(entity_id: str) -> str:
        """Return one resolved entity with its claims from the ACTIVE world.

        Matches by exact entity id, or uniquely by name or alias. UNRESOLVED
        when the world records no entities or none matches exactly/uniquely.
        """
        return _to_json(get_entity(store, entity_id))

    @server.tool(name="get_claim")
    def get_claim_tool(claim_id: str) -> str:
        """Return one claim's compiled record (text, status, evidence).

        Answers CURRENT for a known claim id; UNRESOLVED otherwise.
        """
        return _to_json(get_claim(store, claim_id))

    @server.tool(name="get_change")
    def get_change_tool(change_id: str | None = None, source_path: str | None = None) -> str:
        """Look up one recorded source change by change_id or by source_path.

        Provide exactly one selector. Several changes citing the same
        source_path are refused with instructions to query by change_id.
        """
        return _to_json(get_change(store, change_id, source_path=source_path))

    @server.tool(name="trace_impact")
    def trace_impact_tool(
        entity_or_claim_id: str, direction: str = "downstream", max_depth: int | None = None
    ) -> str:
        """Walk the dependency graph from one node.

        direction=downstream answers 'what stops being current if this
        changes'; direction=upstream answers 'what was this built from'. Every
        affected node carries the path that reached it.
        """
        return _to_json(trace_impact(store, entity_or_claim_id, direction, max_depth=max_depth))

    @server.tool(name="get_world")
    def get_world_tool(world_id: str | None = None) -> str:
        """Summarize one world's manifest and composition.

        Omit world_id for the ACTIVE world; pass an id (SUPERSEDED included)
        to inspect a specific published state.
        """
        return _to_json(get_world(store, world_id))

    @server.tool(name="compare_worlds")
    def compare_worlds_tool(world_a: str, world_b: str) -> str:
        """Diff two worlds' claims: added in B, removed from A, values changed.

        Value changes are reported field by field (before → after). B is the
        newer side of the comparison.
        """
        return _to_json(compare_worlds(store, world_a, world_b))

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
