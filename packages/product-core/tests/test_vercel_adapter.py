from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
ADAPTER = ROOT / "infra" / "product-core" / "vercel"


def test_vercel_adapter_preserves_product_core_release_contract() -> None:
    config = json.loads((ADAPTER / "vercel.json").read_text(encoding="utf-8"))
    entrypoint = (ADAPTER / "api" / "index.py").read_text(encoding="utf-8")
    requirements = (ADAPTER / "requirements.txt").read_text(encoding="utf-8")

    assert config["regions"] == ["hnd1"]
    assert config["functions"]["api/index.py"]["maxDuration"] == 300
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
    assert "akc_product_core.__main__ import app" in entrypoint
    assert "fastapi==0.140.13" in requirements
    assert "jsonschema==4.26.0" in requirements
    assert "TAVONEL_CORE_ALLOW_CUSTOMER_DATA" not in config
