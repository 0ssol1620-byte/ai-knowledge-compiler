"""The joined-E2E Core constructor opts into customer data only on the disposable runner."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from akc_product_core.api import create_product_core_app
from fastapi.testclient import TestClient

MODULE = Path(__file__).resolve().parents[1] / "e2e" / "joined" / "core_synthetic_app.py"
RELEASE = "sha256:" + "b" * 64
SECRET = "joined-e2e-unit-test-hmac-secret-32-bytes-minimum"


def _module():
    spec = importlib.util.spec_from_file_location("core_synthetic_app", MODULE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = {
        "TAVONEL_JOINED_E2E_SYNTHETIC_ONLY": "1",
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "TAVONEL_JOINED_CORE_HMAC": SECRET,
        "TAVONEL_JOINED_CORE_RELEASE_DIGEST": RELEASE,
        "TAVONEL_JOINED_CORE_JOURNAL": str(tmp_path / "journal.sqlite3"),
    }
    env.update(overrides)
    return {key: value for key, value in env.items() if value}


@pytest.mark.parametrize(
    "override",
    [
        {"TAVONEL_JOINED_E2E_SYNTHETIC_ONLY": ""},
        {"TAVONEL_JOINED_E2E_SYNTHETIC_ONLY": "true"},
        {"GITHUB_ACTIONS": ""},
        {"RUNNER_ENVIRONMENT": "self-hosted"},
    ],
)
def test_refuses_outside_the_disposable_opted_in_runner(
    tmp_path: Path, override: dict[str, str]
) -> None:
    with pytest.raises(RuntimeError, match="TAVONEL_JOINED_E2E_SYNTHETIC_ONLY"):
        _module().create_synthetic_test_app(_env(tmp_path, **override))


def test_opted_in_runner_gets_customer_data_enabled_core(tmp_path: Path) -> None:
    app = _module().create_synthetic_test_app(_env(tmp_path))
    with TestClient(app) as client:
        health = client.get("/health").json()
    assert health["customerDataEnabled"] is True
    assert health["coreReleaseDigest"] == RELEASE


def test_production_constructor_default_is_unchanged() -> None:
    app = create_product_core_app(hmac_secret=SECRET.encode(), core_release_digest=RELEASE)
    with TestClient(app) as client:
        assert client.get("/health").json()["customerDataEnabled"] is False
