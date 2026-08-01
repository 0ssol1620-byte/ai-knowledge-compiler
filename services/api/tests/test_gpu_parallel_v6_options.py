from __future__ import annotations

import uuid
from collections.abc import Callable

import pytest
from akc_api.gpu_jobs import GpuInvocationSpec

TENANT_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
JOB_ID = uuid.UUID("00000000-0000-4000-8000-000000000002")
PROJECT_ID = uuid.UUID("00000000-0000-4000-8000-000000000003")
DOCUMENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000004")
COLLECTION_ID = uuid.UUID("00000000-0000-4000-8000-000000000005")
SHARD_ID = uuid.UUID("00000000-0000-4000-8000-000000000006")
ATTEMPT_ID = uuid.UUID("00000000-0000-4000-8000-000000000007")
DOCUMENT_VERSION_ID = f"{DOCUMENT_ID}:v1"
OUTPUT_KEY = f"tenants/{TENANT_ID}/derived/gpu/parallel-v6.json"
MODEL_REVISION = "f" * 40
IMAGE_DIGEST = "sha256:" + ("9" * 64)
ADAPTER_VERSION = "parallel-adapter-1.0.0"


def _envelope() -> dict[str, object]:
    return {
        "schema_version": "parallel-v6-output-admission-1.0",
        "issuer": "akc-api",
        "tenant_id": str(TENANT_ID),
        "collection_id": str(COLLECTION_ID),
        "processing_job_id": str(JOB_ID),
        "document_id": str(DOCUMENT_ID),
        "document_version_id": DOCUMENT_VERSION_ID,
        "shard_id": str(SHARD_ID),
        "attempt_id": str(ATTEMPT_ID),
        "expected_input_sha256": "e" * 64,
        "expected_shard_input_sha256": "d" * 64,
        "expected_request_sha256": "c" * 64,
        "expected_output_object_key": OUTPUT_KEY,
        "expected_model_revision": MODEL_REVISION,
        "expected_runtime_image_digest": IMAGE_DIGEST,
        "expected_adapter_version": ADAPTER_VERSION,
    }


def _spec(mutator: Callable[[dict[str, object]], None] | None = None) -> GpuInvocationSpec:
    envelope = _envelope()
    if mutator is not None:
        mutator(envelope)
    return GpuInvocationSpec(
        tenant_id=TENANT_ID,
        job_id=JOB_ID,
        project_id=PROJECT_ID,
        document_id=DOCUMENT_ID,
        document_version_id=DOCUMENT_VERSION_ID,
        provider_key="paddleocr_vl_1_6",
        endpoint_id="parser-accurate",
        idempotency_key="parallel-v6-job-1",
        input_bucket="source",
        input_object_key=f"tenants/{TENANT_ID}/source/input.bin",
        input_sha256="sha256:" + ("e" * 64),
        output_object_key=OUTPUT_KEY,
        model_revision=MODEL_REVISION,
        runtime_image_digest=IMAGE_DIGEST,
        adapter_version=ADAPTER_VERSION,
        options={"parallel_v6": envelope},
    )


def test_parallel_v6_envelope_is_bound_to_the_gpu_request() -> None:
    invocation = _spec()

    assert invocation.options["parallel_v6"] == _envelope()
    assert invocation.request_manifest["input_sha256"] == "e" * 64


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value.__setitem__("tenant_id", str(PROJECT_ID)),
        lambda value: value.__setitem__("expected_input_sha256", "0" * 64),
        lambda value: value.__setitem__("expected_output_object_key", "other"),
        lambda value: value.__setitem__("unexpected", "field"),
        lambda value: value.__setitem__("shard_id", "{" + str(SHARD_ID) + "}"),
    ],
)
def test_parallel_v6_envelope_drift_fails_closed(
    mutator: Callable[[dict[str, object]], None],
) -> None:
    with pytest.raises(ValueError, match="parallel_v6"):
        _spec(mutator)
