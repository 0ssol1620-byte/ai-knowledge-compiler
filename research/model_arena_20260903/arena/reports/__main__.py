"""Entry point: ``python -m arena.reports``."""

from __future__ import annotations

import sys

from arena.reports.cli import main

if __name__ == "__main__":
    sys.exit(main())
