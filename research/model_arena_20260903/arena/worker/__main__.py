"""``python -m arena.worker`` — same entry point as ``python -m arena.worker.server``."""

from __future__ import annotations

from arena.worker.server import main

if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
