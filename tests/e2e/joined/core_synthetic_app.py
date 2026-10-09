"""Synthetic-test constructor of Product Core v2 for the joined E2E workflow only.

Foundation sends ``privacyPolicy: approved_customer_data`` once its customer-data gate admits a
workspace, so the joined proof needs a Core that accepts that policy. Production keeps
``allow_customer_data=False`` (``akc_product_core.__main__``, the Dockerfile and ``vercel.json``
are untouched and their guards still hold). This module is the one place the flag is turned on,
and it refuses to build unless it is inside the disposable GitHub-hosted runner with the explicit
synthetic-only opt-in. The bytes it compiles are a synthetic PDF the harness generated; no
customer data exists in that job.

Run from tests/e2e/joined:
    python -m uvicorn --factory core_synthetic_app:create_synthetic_test_app
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from akc_product_core.api import create_product_core_app
from fastapi import FastAPI

SYNTHETIC_OPT_IN = "TAVONEL_JOINED_E2E_SYNTHETIC_ONLY"


def create_synthetic_test_app(env: Mapping[str, str] = os.environ) -> FastAPI:
    disposable = (
        env.get("GITHUB_ACTIONS") == "true" and env.get("RUNNER_ENVIRONMENT") == "github-hosted"
    )
    if env.get(SYNTHETIC_OPT_IN) != "1" or not disposable:
        raise RuntimeError(
            f"{SYNTHETIC_OPT_IN}=1 on a GitHub-hosted runner is required; "
            "this app accepts customer-data routes"
        )
    app: FastAPI = create_product_core_app(
        hmac_secret=env["TAVONEL_JOINED_CORE_HMAC"].encode(),
        core_release_digest=env["TAVONEL_JOINED_CORE_RELEASE_DIGEST"],
        allow_customer_data=True,
        journal_path=Path(env["TAVONEL_JOINED_CORE_JOURNAL"]),
    )
    return app
