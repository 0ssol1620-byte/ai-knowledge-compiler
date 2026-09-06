"""Entry point: ``python -m arena.controller``."""

from __future__ import annotations

import sys

from arena.controller.cli import main

if __name__ == "__main__":
    sys.exit(main())
