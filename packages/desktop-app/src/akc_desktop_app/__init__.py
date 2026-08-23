"""akc_desktop_app — Personal Pro desktop entry point (§17 packaging basis).

Single CLI, ``akc-desktop``, that wires the existing local pieces together:

- ``init``      register a workspace, generate watcher + MCP client configs,
                suggest the Health Scan, and start time-to-first-world logging.
- ``serve``     run the desktop-watcher in background threads while the
                read-only local MCP server speaks stdio on the main thread.
- ``status``    report registered workspaces, published worlds, artifacts.
- ``uninstall`` remove ONLY the artifacts this CLI generated (everything lives
                under the Tavonel home, never inside user workspaces).

Heavy optional dependencies (``watchdog`` via akc_desktop_watcher, ``mcp``
via akc_local_mcp) are imported lazily so ``init``/``status``/``uninstall``
work on a bare interpreter.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
