"""Entry point for `python -m arena.registry`."""

from __future__ import annotations

import sys

from arena.registry.cli import main

if __name__ == "__main__":
    sys.exit(main())
