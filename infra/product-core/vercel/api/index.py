"""Vercel ASGI entrypoint for the staged Product-Core v2 bundle."""

from __future__ import annotations

import sys
from pathlib import Path

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "vendor"
sys.path.insert(0, str(VENDOR_ROOT))

from akc_product_core.__main__ import app  # noqa: E402,F401
