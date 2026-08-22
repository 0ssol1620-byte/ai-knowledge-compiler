# akc-local-mcp

Read-only MCP server over **locally published world states** — the offline
desktop scenario: no `services/api`, no database, just the JSON files the
compiler published into a world-state directory.

## Surface (exhaustive, read-only)

| Kind | Name | Reads |
| --- | --- | --- |
| tool | `get_current_truth` | one topic's compiled truth + its claims |
| tool | `get_evidence` | one claim's evidence chain |
| tool | `search_world` | substring search across topics and claims |
| resource | `worlds://index` | every world that declares a readable manifest |
| resource | `worlds://{world_id}/manifest` | one world's published manifest |

**No write tools exist and none may be added.** The forbidden list (knowledge
writes, world-state publish/rollback, ingestion, entity writes, recompilation,
billing/admin) is normative and lives in the module docstring of
`src/akc_local_mcp/server.py`. Masterplan v5 PART 16 restricts MCP to
*Read-only*; Write MCP is PHASE 20 and GATED.

## Fail-closed (Contract A)

When the world-state directory is missing, no world is `ACTIVE`, a claim or
topic does not exist, or a search finds nothing, tools answer

```json
{"status": "UNRESOLVED", "reason": {"code": "..."}, "message": "..."}
```

instead of guessing. `UNRESOLVED` never silently becomes `CURRENT`
(`docs/architecture/canonical-ir.md`). Successful answers carry the
`world.manifest_hash` they were computed against, so any answer is checkable
against the files on disk.

## World-state directory layout

```
<world-state-dir>/
  <world_id>/manifest.json   akc.local-world-manifest/1 — the citable pointer
  <world_id>/state.json      akc.local-world-state/1    — topics, claims, evidence
```

`packages/local-mcp/tests/fixtures/world-state/atlas-demo/` is a working
sample (manifest hash and artifact hashes are real SHA-256 values over the
fixture state file).

## Running

```bash
uv sync --group local-mcp
AKC_LOCAL_MCP_WORLD_STATE_DIR=/path/to/world-state uv run --group local-mcp python -m akc_local_mcp
```

Claude Desktop-style client config:

```json
{
  "mcpServers": {
    "akc-local-mcp": {
      "command": "python",
      "args": ["-m", "akc_local_mcp"],
      "env": {"AKC_LOCAL_MCP_WORLD_STATE_DIR": "D:/path/to/world-state"}
    }
  }
}
```

A missing directory is not a startup error: the server boots and answers
`UNRESOLVED` (`WORLD_STATE_UNAVAILABLE`) until a world is published.

## Verification

```bash
uv run --group local-mcp pytest packages/local-mcp/tests -q   # unit + stdio roundtrip
uv run --group local-mcp ruff check packages/local-mcp
uv run --group local-mcp ruff format --check packages/local-mcp
uv run --group local-mcp mypy packages/local-mcp/src
```

The stdio roundtrip test boots the real server in a subprocess and performs an
`initialize` handshake, `tools/list`, `resources/list`,
`resources/templates/list` and two `tools/call` requests over stdin/stdout.
