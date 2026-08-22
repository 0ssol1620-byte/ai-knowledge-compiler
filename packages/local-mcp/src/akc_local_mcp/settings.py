"""Configuration for the local MCP server.

One setting matters: where the published world states live. The server is an
offline desktop component — it reads whatever JSON the compiler published into
`world_state_dir` and never contacts `services/api`.

Set it with the ``AKC_LOCAL_MCP_WORLD_STATE_DIR`` environment variable (the
usual way MCP clients such as Claude Desktop pass per-server configuration) or
rely on the default, a ``world-state`` directory under the current working
directory. A missing directory is not a startup error: tools answer UNRESOLVED
(fail-closed) instead of pretending there is nothing wrong.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LocalMcpSettings"]


class LocalMcpSettings(BaseSettings):
    """Where to find published world states."""

    model_config = SettingsConfigDict(env_prefix="AKC_LOCAL_MCP_")

    world_state_dir: Path = Path("world-state")
