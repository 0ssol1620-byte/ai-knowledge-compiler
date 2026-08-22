"""Run the read-only local MCP server on stdio: `python -m akc_local_mcp`."""

from __future__ import annotations

from .server import main

if __name__ == "__main__":
    main()
