"""Run the desktop CLI: ``python -m akc_desktop_app`` (same as ``akc-desktop``)."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
