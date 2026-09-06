"""Verify the public Product-Core v2 boundary without exposing credentials."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from akc_cir.base import canonical_json
from akc_cir.models import BBox1000, BlockType
from akc_product_core.auth import sign_product_core_request
from akc_product_core.contracts import (
    ProductCoreCompileRequest,
    ProductCoreCompileResponse,
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _request(request_id: str, privacy_policy: str) -> ProductCoreCompileRequest:
    text = "2025 revenue was 100 million won. TAVONEL Research Institute reported it."
    digest = _sha256(text)
    return ProductCoreCompileRequest(
        request_id=request_id,
        idempotency_key=f"deployment-smoke-{request_id}",
        tenant_id="tenant-deployment-smoke",
        workspace_id="workspace-deployment-smoke",
        collection_id="collection-deployment-smoke",
        requested_at=datetime.now(tz=UTC),
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement="high_assurance",
            max_cost_credits=10,
            max_latency_ms=90_000,
            privacy_policy=privacy_policy,
        ),
        documents=(
            ProductCoreDocument(
                native_id="public-smoke-document",
                connector_type="foundation-r2",
                immutable_object_key=(
                    "immutable/tenant-deployment-smoke/workspace-deployment-smoke/"
                    f"public-smoke-document/{digest[7:]}/source.pdf"
                ),
                ocr_object_key=(
                    "immutable/tenant-deployment-smoke/workspace-deployment-smoke/"
                    f"public-smoke-document/{digest[7:]}/ocr.json"
                ),
                content_sha256=digest,
                title="Public deployment smoke document",
                source_filename="public-smoke-document.pdf",
                page_count=1,
                regions=(
                    ProductCoreRegion(
                        region_id="region-public-smoke-document",
                        page_index0=0,
                        page_number1=1,
                        order=0,
                        block_type=BlockType.PARAGRAPH,
                        text=text,
                        bbox1000=BBox1000((100, 120, 900, 240)),
                        confidence=0.99,
                        authority="regulatory_filing",
                    ),
                ),
            ),
        ),
    )


def _body_and_headers(
    request: ProductCoreCompileRequest, secret: bytes
) -> tuple[bytes, dict[str, str]]:
    body = canonical_json(
        request.model_dump(mode="json", by_alias=True, exclude_none=True)
    ).encode()
    timestamp = int(datetime.now(tz=UTC).timestamp())
    return body, {
        "content-type": "application/json",
        **sign_product_core_request(
            body=body,
            request_id=request.request_id,
            timestamp=timestamp,
            secret=secret,
        ),
    }


def main() -> None:
    base_url = _required_env("TAVONEL_PRODUCT_CORE_URL").rstrip("/")
    secret = _required_env("TAVONEL_PRODUCT_CORE_HMAC").encode()
    expected_release = _required_env("TAVONEL_CORE_RELEASE_DIGEST")

    with httpx.Client(base_url=base_url, timeout=90.0) as client:
        health_response = client.get("/health")
        health_response.raise_for_status()
        health = health_response.json()
        if health != {
            "status": "ok",
            "runtime": "tavonel-python-core-v2",
            "coreReleaseDigest": expected_release,
            "matchingPolicy": "legacy",
            "candidatePromotion": False,
            "customerDataEnabled": False,
        }:
            raise RuntimeError("Product-Core health contract does not match the release")

        unsigned = client.post("/v2/compile", content=b"{}")
        if unsigned.status_code != 401:
            raise RuntimeError(f"unsigned request returned {unsigned.status_code}, expected 401")

        request_id = f"smoke-{uuid4()}"
        compile_body, compile_headers = _body_and_headers(
            _request(request_id, "foundation_synthetic_only"), secret
        )
        compile_response = client.post(
            "/v2/compile", content=compile_body, headers=compile_headers
        )
        compile_response.raise_for_status()
        result = ProductCoreCompileResponse.model_validate(compile_response.json())
        if result.status != "completed" or result.candidate.lifecycle != "candidate":
            raise RuntimeError("synthetic canary did not produce a reviewable candidate")
        if result.receipt.candidate_promotion is not False:
            raise RuntimeError("deployment attempted to promote a candidate")
        if result.receipt.core_release_digest != expected_release:
            raise RuntimeError("compile receipt does not match the deployed release")
        if len(result.artifacts) != 5 or len(result.candidate.package.files) < 15:
            raise RuntimeError("compile output is missing required artifacts")

        customer_id = f"customer-block-{uuid4()}"
        customer_body, customer_headers = _body_and_headers(
            _request(customer_id, "approved_customer_data"), secret
        )
        customer_response = client.post(
            "/v2/compile", content=customer_body, headers=customer_headers
        )
        if customer_response.status_code != 403 or customer_response.json().get("code") != (
            "CORE_CUSTOMER_DATA_DISABLED"
        ):
            raise RuntimeError("customer-data compile was not rejected fail-closed")

    print(
        json.dumps(
            {
                "status": result.status,
                "runtime": result.runtime,
                "lifecycle": result.candidate.lifecycle,
                "candidatePromotion": result.receipt.candidate_promotion,
                "releaseDigestMatched": True,
                "artifacts": len(result.artifacts),
                "packageFiles": len(result.candidate.package.files),
                "unsignedRequestStatus": unsigned.status_code,
                "customerDataRequestStatus": customer_response.status_code,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
