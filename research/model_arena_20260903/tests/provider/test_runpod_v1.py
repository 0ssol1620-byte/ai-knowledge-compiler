"""REST v1 bootstrap creation: payload shape, redaction, start command (D2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from arena.constants import CAMPAIGN_ID
from arena.provider import runpod_v1
from arena.provider.runpod_pods import PodSpec, PriceSnapshot, ProviderReceipt, RunPodClientError
from arena.provider.runpod_v1 import (
    AMBIGUOUS_CREATE_RECHECK_SECONDS,
    MANAGEMENT_BASE_URL_V1,
    USER_AGENT,
    RunPodV1Client,
    bundle_url_reference,
    v1_create_payload,
    v1_redacted_payload,
)
from arena.provider.secrets import Secret
from tests.provider.conftest import (
    FAKE_RUNPOD_VALUE,
    RecordingTransport,
    gpu_payload,
    json_response,
)

BUNDLE_SHA = "c" * 64
SIGNED_URL = (
    "https://fakeaccount.eu.r2.cloudflarestorage.com/tavonel-arena-20260903/"
    "bundles/glm_ocr/arena-bundle.tar.gz"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeefdeadbeefdeadbeef"
)


def _bootstrap_spec(**overrides: object) -> PodSpec:
    base: dict[str, object] = {
        "name": "arena-glm-ocr-w0-20260903v1",
        "image_name": "vllm/vllm-openai:v0.11.0@sha256:" + "e" * 64,
        "gpu_type_ids": ("NVIDIA GeForce RTX 4090", "NVIDIA A40"),
        "model_key": "glm_ocr",
        "model_revision": "a" * 40,
        "runtime_mode": "bootstrap",
        "image_digest": "sha256:" + "b" * 64,
        "cloud_type": "SECURE",
        "container_disk_gb": 80,
        "volume_gb": 60,
        "max_lifetime_hours": 2,
        "worker_token": Secret("arena-fake-bearer-value-0000000000", label="ARENA_WORKER_TOKEN"),
        "bundle_url": Secret(SIGNED_URL, label="ARENA_BUNDLE_URL"),
        "bundle_sha256": BUNDLE_SHA,
    }
    base.update(overrides)
    return PodSpec(**base)  # type: ignore[arg-type]


def _fake_start_cmd(model_key: str, bundle_sha256: str) -> str:
    return (
        "set -euo pipefail; mkdir -p /opt/arena; "
        'curl -fsSL --retry 5 --max-time 900 "$ARENA_BUNDLE_URL" -o /tmp/arena-bundle.tar.gz; '
        f'echo "{bundle_sha256}  /tmp/arena-bundle.tar.gz" | sha256sum -c -; '
        "tar -xzf /tmp/arena-bundle.tar.gz -C /opt/arena; "
        f"exec bash /opt/arena/bootstrap.sh  # {model_key}"
    )


@pytest.fixture
def start_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    # Lane B2 owns arena.worker.bundle.render_start_cmd and may land after this
    # lane; the seam is patched by name so these tests never wait on it.
    monkeypatch.setattr(runpod_v1, "render_start_cmd", _fake_start_cmd, raising=False)


def _pod_v1_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "pod1v1abcdef",
        "name": "arena-glm-ocr-w0-20260903v1",
        "desiredStatus": "RUNNING",
        "image": "vllm/vllm-openai:v0.11.0",
        "costPerHr": 0.69,
        "containerDiskInGb": 80,
        "volumeInGb": 60,
        "volumeMountPath": "/workspace",
        "dockerEntrypoint": ["/bin/bash", "-c"],
        "dockerStartCmd": ["set -euo pipefail; ..."],
        "env": {"ARENA_CAMPAIGN_ID": CAMPAIGN_ID, "ARENA_MODEL_KEY": "glm_ocr"},
        "gpu": {"id": "NVIDIA GeForce RTX 4090", "count": 1},
        "machine": {"dataCenterId": "EU-RO-1", "gpuTypeId": "NVIDIA GeForce RTX 4090"},
        "machineId": "s194cr8pls2z",
        "lastStartedAt": "2026-09-03T12:00:00Z",
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ payload


def test_payload_has_the_fields_d2_names(start_cmd: None) -> None:
    spec = _bootstrap_spec()
    payload = v1_create_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=_fake_start_cmd("glm_ocr", BUNDLE_SHA)
    )
    assert payload["name"] == spec.name
    assert payload["imageName"] == spec.image_name
    assert payload["gpuTypeIds"] == list(spec.gpu_type_ids)
    assert payload["gpuCount"] == 1
    assert payload["cloudType"] == "SECURE"
    assert payload["containerDiskInGb"] == 80
    assert payload["volumeInGb"] == 60
    assert payload["volumeMountPath"] == "/workspace"
    assert payload["ports"] == ["8000/http"]
    assert payload["dockerEntrypoint"] == ["/bin/bash", "-c"]  # D29: no login shell
    start = payload["dockerStartCmd"]
    assert isinstance(start, list)
    assert len(start) == 1  # exactly one element, per D2
    assert BUNDLE_SHA in start[0]


def test_data_center_ids_are_optional(start_cmd: None) -> None:
    command = _fake_start_cmd("glm_ocr", BUNDLE_SHA)
    spec = _bootstrap_spec()
    assert "dataCenterIds" not in v1_create_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=command
    )
    pinned = _bootstrap_spec(data_center_ids=("EU-RO-1",))
    payload = v1_create_payload(pinned, gpu_type_ids=pinned.gpu_type_ids, start_command=command)
    assert payload["dataCenterIds"] == ["EU-RO-1"]


def test_a_baked_spec_has_no_v1_payload() -> None:
    baked = _bootstrap_spec(runtime_mode="baked", bundle_url=None, bundle_sha256=None)
    with pytest.raises(RunPodClientError, match="bootstrap path"):
        v1_create_payload(baked, gpu_type_ids=baked.gpu_type_ids, start_command="true")


# ---------------------------------------------------------------- redaction


def test_redacted_payload_reduces_the_presigned_url_to_host_and_key() -> None:
    spec = _bootstrap_spec()
    payload = v1_redacted_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=_fake_start_cmd("glm_ocr", BUNDLE_SHA)
    )
    env = payload["env"]
    assert isinstance(env, dict)
    assert env["ARENA_BUNDLE_URL"] == (
        "fakeaccount.eu.r2.cloudflarestorage.com/"
        "tavonel-arena-20260903/bundles/glm_ocr/arena-bundle.tar.gz"
    )
    assert env["ARENA_WORKER_TOKEN"] == "<redacted>"  # noqa: S105 - the marker, not a secret
    body = json.dumps(payload)
    assert "X-Amz-Signature" not in body
    assert "arena-fake-bearer-value" not in body


def test_bundle_url_reference_drops_the_query() -> None:
    assert bundle_url_reference(SIGNED_URL).endswith("arena-bundle.tar.gz")
    assert "?" not in bundle_url_reference(SIGNED_URL)
    with pytest.raises(RunPodClientError):
        bundle_url_reference("not-a-url")


# ------------------------------------------------------------ start command


def test_a_start_command_that_does_not_pin_the_digest_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arena.worker.bundle as bundle_module

    monkeypatch.setattr(
        bundle_module,
        "render_start_cmd",
        lambda key, digest: "exec bash /opt/arena/bootstrap.sh",
        raising=False,
    )
    with pytest.raises(RunPodClientError, match="does not pin the bundle sha256"):
        runpod_v1.render_start_cmd("glm_ocr", BUNDLE_SHA)


def test_a_missing_b2_renderer_is_reported_not_improvised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arena.worker.bundle as bundle_module

    monkeypatch.delattr(bundle_module, "render_start_cmd", raising=False)
    with pytest.raises(RunPodClientError, match="lane B2"):
        runpod_v1.render_start_cmd("glm_ocr", BUNDLE_SHA)


# -------------------------------------------------------------------- client


def test_dry_run_opens_no_socket_and_writes_a_receipt(
    runpod_key: Secret, tmp_path: Path, start_cmd: None
) -> None:
    client = RunPodV1Client(key=runpod_key, execute=False, receipts_dir=tmp_path)
    receipt = client.create_pod(_bootstrap_spec())
    assert isinstance(receipt, ProviderReceipt)
    assert receipt.mode == "dry_run"
    assert receipt.url == f"{MANAGEMENT_BASE_URL_V1}/pods"
    assert receipt.summary["provider_api_version"] == "v1"
    body = (next(iter(tmp_path.glob("v1-create_pod-*.json")))).read_text(encoding="utf-8")
    assert "X-Amz-Signature" not in body
    assert FAKE_RUNPOD_VALUE not in body


def test_create_sends_the_bearer_and_an_explicit_user_agent(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        return json_response(201, _pod_v1_payload())

    transport: RecordingTransport = transport_factory(handler)
    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport)
    try:
        pod = client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    assert pod.pod_id == "pod1v1abcdef"
    assert pod.desired_status == "RUNNING"
    assert pod.data_center_id == "EU-RO-1"
    create = transport.requests[-1]
    assert create.headers["user-agent"] == USER_AGENT
    assert create.headers["authorization"] == f"Bearer {FAKE_RUNPOD_VALUE}"
    sent = json.loads(create.content.decode("utf-8"))
    assert len(sent["dockerStartCmd"]) == 1
    assert sent["dockerEntrypoint"] == ["/bin/bash", "-c"]  # D29
    # The wire payload carries the real secrets; the receipt does not.
    assert sent["env"]["ARENA_BUNDLE_URL"] == SIGNED_URL
    assert "X-Amz-Signature" not in json.dumps([receipt.to_dict() for receipt in client.receipts])


def test_an_existing_live_pod_is_adopted_not_duplicated(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    posts: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [_pod_v1_payload()])
        posts.append(request)
        return json_response(201, _pod_v1_payload(id="pod2duplicate"))

    transport: RecordingTransport = transport_factory(handler)
    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport)
    try:
        pod = client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    assert pod.pod_id == "pod1v1abcdef"
    assert posts == []  # nothing paid was created


def test_an_unknown_desired_status_is_a_protocol_error(
    runpod_key: Secret, transport_factory: Any
) -> None:
    transport: RecordingTransport = transport_factory(
        lambda request: json_response(200, [_pod_v1_payload(desiredStatus="SLEEPING")])
    )
    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport)
    try:
        with pytest.raises(RunPodClientError, match="desiredStatus"):
            client.list_pods()
    finally:
        client.close()


def test_create_quotes_the_price_row(runpod_key: Secret, tmp_path: Path, start_cmd: None) -> None:
    from arena.provider.runpod_pods import _parse_gpu_type

    snapshot = PriceSnapshot(
        captured_at="2026-09-03T12:00:00Z",
        rows=(_parse_gpu_type(gpu_payload()),),
    )
    client = RunPodV1Client(key=runpod_key, execute=False, receipts_dir=tmp_path)
    receipt = client.create_pod(_bootstrap_spec(), price_snapshot=snapshot)
    assert isinstance(receipt, ProviderReceipt)
    assert receipt.summary["price_snapshot_sha256"] == snapshot.snapshot_sha256()


# ------------------------------------------------------------------ teardown


def _teardown_client(
    runpod_key: Secret, transport_factory: Any, status: int, *, body: bytes = b""
) -> tuple[RunPodV1Client, RecordingTransport]:
    transport: RecordingTransport = transport_factory(
        lambda request: httpx.Response(status, content=body)
    )
    return RunPodV1Client(key=runpod_key, execute=True, transport=transport), transport


@pytest.mark.parametrize("status", [200, 202, 204])
def test_a_delete_answered_with_no_content_is_a_success_not_a_refusal(
    runpod_key: Secret, transport_factory: Any, status: int
) -> None:
    """The 2026-09-03 live run: v1 answered DELETE with 204 and the client
    recorded ``delete_pod refused`` while the pod was in fact already gone."""

    client, transport = _teardown_client(runpod_key, transport_factory, status)
    try:
        assert client.delete_pod("uskidtgack3e3z") is None
    finally:
        client.close()
    sent = transport.requests[-1]
    assert sent.method == "DELETE"
    assert sent.url.path == "/v1/pods/uskidtgack3e3z"
    receipt = client.receipts[-1]
    assert receipt.action == "delete_pod"
    assert receipt.status_code == status  # the real code, not a hard-coded 200


@pytest.mark.parametrize("status", [200, 202, 204])
def test_a_stop_answered_with_no_content_is_also_a_success(
    runpod_key: Secret, transport_factory: Any, status: int
) -> None:
    client, _ = _teardown_client(runpod_key, transport_factory, status)
    try:
        assert client.stop_pod("uskidtgack3e3z") is None
    finally:
        client.close()
    assert client.receipts[-1].status_code == status


def test_a_delete_the_provider_actually_refuses_is_still_an_error(
    runpod_key: Secret, transport_factory: Any
) -> None:
    """Widening the accepted codes must not swallow a real failure."""

    client, _ = _teardown_client(runpod_key, transport_factory, 500, body=b"upstream said no")
    try:
        with pytest.raises(RunPodClientError, match="HTTP 500"):
            client.delete_pod("uskidtgack3e3z")
    finally:
        client.close()


def test_a_delete_of_a_pod_that_is_already_gone_is_not_an_error(
    runpod_key: Secret, transport_factory: Any
) -> None:
    client, _ = _teardown_client(runpod_key, transport_factory, 404)
    try:
        assert client.delete_pod("uskidtgack3e3z") is None
    finally:
        client.close()
    assert client.receipts[-1].status_code == 404


# --------------------------------------------------- host CUDA floor + walk


def test_the_payload_carries_the_allowed_cuda_versions(start_cmd: None) -> None:
    """The constraint pod 3xag0y00rgoj4n died for want of reaches the wire."""

    spec = _bootstrap_spec(allowed_cuda_versions=("12.9", "13.0"))
    payload = v1_create_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=_fake_start_cmd("glm_ocr", BUNDLE_SHA)
    )
    assert payload["allowedCudaVersions"] == ["12.9", "13.0"]


def test_no_constraint_omits_the_key_rather_than_sending_an_empty_list(
    start_cmd: None,
) -> None:
    """An empty allowedCudaVersions means "any host", which is the incident."""

    spec = _bootstrap_spec()
    payload = v1_create_payload(
        spec, gpu_type_ids=spec.gpu_type_ids, start_command=_fake_start_cmd("glm_ocr", BUNDLE_SHA)
    )
    assert "allowedCudaVersions" not in payload


def test_a_cuda_version_that_is_not_major_minor_is_refused() -> None:
    with pytest.raises(RunPodClientError, match=r"major\.minor"):
        _bootstrap_spec(allowed_cuda_versions=("12.9.1",))


def test_the_pod_record_keeps_the_host_cuda_version_when_it_carries_one(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    """v1's OpenAPI does not document cudaVersion; the live record carried it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        return json_response(201, _pod_v1_payload(cudaVersion="12.8"))

    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport_factory(handler))
    try:
        pod = client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    assert pod.cuda_version == "12.8"
    assert pod.to_summary()["cuda_version"] == "12.8"


def test_a_record_without_a_cuda_version_reports_none_rather_than_guessing(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        return json_response(201, _pod_v1_payload())

    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport_factory(handler))
    try:
        pod = client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    assert pod.cuda_version is None


def test_a_capacity_refusal_walks_to_the_next_pool_entry(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    """The first GPU may have no host on an allowed CUDA version; the second may."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        sent = json.loads(request.content.decode("utf-8"))
        if sent["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090"]:
            return json_response(400, {"error": "no machines available"})
        return json_response(
            201,
            _pod_v1_payload(
                gpu={"id": "NVIDIA A40", "count": 1},
                machine={"dataCenterId": "EU-RO-1", "gpuTypeId": "NVIDIA A40"},
                cudaVersion="12.9",
            ),
        )

    transport: RecordingTransport = transport_factory(handler)
    spec = _bootstrap_spec(allowed_cuda_versions=("12.9", "13.0"))
    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport)
    try:
        pod = client.create_pod(spec)
    finally:
        client.close()

    assert not isinstance(pod, ProviderReceipt)
    assert pod.gpu_type_id == "NVIDIA A40"
    creates = [
        json.loads(request.content.decode("utf-8"))
        for request in transport.requests
        if request.method == "POST"
    ]
    # One request per pool entry, in priority order, each carrying the floor.
    assert [sent["gpuTypeIds"] for sent in creates] == [
        ["NVIDIA GeForce RTX 4090"],
        ["NVIDIA A40"],
    ]
    assert all(sent["allowedCudaVersions"] == ["12.9", "13.0"] for sent in creates)
    # And every attempt is on the receipt trail, refusals included.
    attempts = [receipt.summary for receipt in client.receipts if receipt.action == "create_pod"]
    assert [attempt.get("attempt") for attempt in attempts] == [1, 2]
    assert attempts[0]["created"] is False
    assert attempts[1]["created"] is True
    assert attempts[1]["gpu_type_ids"] == ["NVIDIA A40"]


def test_the_walk_stops_when_every_pool_entry_refuses(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        return json_response(400, {"error": "no machines available"})

    transport: RecordingTransport = transport_factory(handler)
    client = RunPodV1Client(key=runpod_key, execute=True, transport=transport)
    try:
        with pytest.raises(RunPodClientError, match="HTTP 400"):
            client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    creates = [request for request in transport.requests if request.method == "POST"]
    assert len(creates) == 2  # both pool entries, then the refusal propagates


def test_an_ambiguous_create_walks_on_after_two_re_lists(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    """D60: a 5xx is re-listed twice (the second after a pause); nothing there, walk on.

    Real evidence: hpd_parsing 2026-09-03 got HTTP 500 twice on its first,
    out-of-stock pool entry and never reached the A100 entries behind it.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, [])
        sent = json.loads(request.content.decode("utf-8"))
        if sent["gpuTypeIds"] == ["NVIDIA GeForce RTX 4090"]:
            return json_response(500, {"error": "upstream"})
        return json_response(
            201,
            _pod_v1_payload(
                gpu={"id": "NVIDIA A40", "count": 1},
                machine={"dataCenterId": "EU-RO-1", "gpuTypeId": "NVIDIA A40"},
                cudaVersion="12.9",
            ),
        )

    pauses: list[float] = []
    transport: RecordingTransport = transport_factory(handler)
    client = RunPodV1Client(
        key=runpod_key, execute=True, transport=transport, ambiguous_recheck_sleep=pauses.append
    )
    try:
        pod = client.create_pod(_bootstrap_spec())
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    assert pod.gpu_type_id == "NVIDIA A40"
    assert pauses == [AMBIGUOUS_CREATE_RECHECK_SECONDS]
    creates = [request for request in transport.requests if request.method == "POST"]
    assert len(creates) == 2
    attempts = [receipt.summary for receipt in client.receipts if receipt.action == "create_pod"]
    assert attempts[0]["created"] is False
    assert attempts[0]["ambiguous"] is True
    assert attempts[0]["re_listed_by_name"] == 2
    assert attempts[1]["created"] is True
    # pre-create list, re-list after the 500, second re-list after the pause,
    # and the next attempt's own re-list before it sends
    lists = [request for request in transport.requests if request.method == "GET"]
    assert len(lists) == 4


def test_a_pod_that_appears_on_the_second_re_list_is_adopted_not_duplicated(
    runpod_key: Secret, transport_factory: Any, start_cmd: None
) -> None:
    """D60 keeps D24's promise: a 5xx that did create a pod never rents a second one."""
    gets = {"count": 0}
    spec = _bootstrap_spec()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            gets["count"] += 1
            if gets["count"] >= 3:
                return json_response(
                    200,
                    [
                        _pod_v1_payload(
                            name=spec.name,
                            gpu={"id": "NVIDIA GeForce RTX 4090", "count": 1},
                            machine={
                                "dataCenterId": "EU-RO-1",
                                "gpuTypeId": "NVIDIA GeForce RTX 4090",
                            },
                            cudaVersion="12.9",
                        )
                    ],
                )
            return json_response(200, [])
        return json_response(500, {"error": "upstream"})

    transport: RecordingTransport = transport_factory(handler)
    client = RunPodV1Client(
        key=runpod_key, execute=True, transport=transport, ambiguous_recheck_sleep=lambda _: None
    )
    try:
        pod = client.create_pod(spec)
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    creates = [request for request in transport.requests if request.method == "POST"]
    assert len(creates) == 1
    adoption = [
        receipt.summary for receipt in client.receipts if receipt.summary.get("adopted") is True
    ]
    assert adoption and adoption[-1]["adopted_after"] == "ambiguous create, second re-list"
