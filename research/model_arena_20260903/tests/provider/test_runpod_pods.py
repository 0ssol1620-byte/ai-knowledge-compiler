"""RunPod v2 client: dry runs, strict parsing, idempotent create, no leaks."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from arena.constants import CAMPAIGN_ID
from arena.provider.runpod_pods import (
    BillingWindow,
    PodSpec,
    PriceSnapshot,
    ProviderReceipt,
    RunPodClientError,
    RunPodPodsClient,
    RunPodProtocolError,
    pod_name,
)
from arena.provider.secrets import Secret
from tests.provider.conftest import (
    FAKE_RUNPOD_VALUE,
    RecordingTransport,
    gpu_payload,
    json_response,
    pod_payload,
)


def _spec(**overrides: object) -> PodSpec:
    base: dict[str, object] = {
        "name": pod_name("paddleocr_vl_1_6", 0),
        "image_name": "ghcr.io/example/arena-paddle:1.0",
        "gpu_type_ids": ("NVIDIA GeForce RTX 4090", "NVIDIA A40"),
        "model_key": "paddleocr_vl_1_6",
        "model_revision": "a" * 40,
        "runtime_mode": "baked",
        "image_digest": "sha256:" + "b" * 64,
        "worker_token": Secret("arena-fake-bearer-value-0000000000", label="ARENA_WORKER_TOKEN"),
    }
    base.update(overrides)
    return PodSpec(**base)  # type: ignore[arg-type]


def test_pod_name_follows_the_contract() -> None:
    assert pod_name("mineru_vlm", 3) == "arena-mineru-vlm-w3-20260903v1"
    with pytest.raises(RunPodClientError):
        pod_name("Not A Key", 0)


def test_dry_run_opens_no_socket_and_writes_a_receipt(runpod_key: Secret, tmp_path: Path) -> None:
    client = RunPodPodsClient(key=runpod_key, execute=False, receipts_dir=tmp_path)
    receipt = client.create_pod(_spec())
    assert isinstance(receipt, ProviderReceipt)
    assert receipt.mode == "dry_run"
    assert receipt.method == "POST"
    files = list(tmp_path.glob("create_pod-*.json"))
    assert len(files) == 1
    body = files[0].read_text(encoding="utf-8")
    assert "<redacted>" in body
    assert "arena-fake-bearer-value" not in body
    assert FAKE_RUNPOD_VALUE not in body


def test_dry_run_payload_carries_the_full_env_names_only(runpod_key: Secret) -> None:
    client = RunPodPodsClient(key=runpod_key, execute=False)
    receipt = client.create_pod(_spec())
    assert isinstance(receipt, ProviderReceipt)
    payload = receipt.summary["would_send"]
    assert isinstance(payload, dict)
    env = payload["env"]
    assert isinstance(env, dict)
    # The literal below is the redaction marker, not a credential.
    assert env["ARENA_WORKER_TOKEN"] == "<redacted>"  # noqa: S105
    assert env["ARENA_CAMPAIGN_ID"] == CAMPAIGN_ID
    assert env["ARENA_MAX_POD_AGE_HOURS"] == "6"


def test_v2_refuses_to_create_a_bootstrap_pod(runpod_key: Secret) -> None:
    """D2: v2 has only ``args`` and cannot override an image ENTRYPOINT."""

    spec = _spec(
        runtime_mode="bootstrap",
        bundle_url=Secret(
            "https://fake.r2.example/bundle.tgz?X-Amz-Signature=deadbeefdeadbeef",
            label="ARENA_BUNDLE_URL",
        ),
        bundle_sha256="e" * 64,
    )
    with pytest.raises(RunPodClientError, match="runpod_v1"):
        spec.to_payload(spec.gpu_type_ids[0])
    client = RunPodPodsClient(key=runpod_key, execute=False)
    with pytest.raises(RunPodClientError, match="baked-image pods only"):
        client.create_pod(spec)


def test_v2_payload_carries_no_args_for_a_baked_image(runpod_key: Secret) -> None:
    payload = _spec().to_payload("NVIDIA GeForce RTX 4090")
    assert "args" not in payload
    assert json.dumps(payload, default=str)  # serializable shape, no Secret objects


def test_bootstrap_without_a_bundle_url_is_refused() -> None:
    with pytest.raises(RunPodClientError, match="bootstrap mode requires a presigned"):
        _spec(runtime_mode="bootstrap")


def test_bootstrap_without_a_bundle_digest_is_refused() -> None:
    with pytest.raises(RunPodClientError, match="bundle_sha256"):
        _spec(
            runtime_mode="bootstrap",
            bundle_url=Secret("https://fake.r2.example/bundle.tgz", label="ARENA_BUNDLE_URL"),
        )


def test_network_volume_requires_a_pinned_data_center() -> None:
    with pytest.raises(RunPodClientError, match="data center"):
        _spec(network_volume_id="vol_abc")
    spec = _spec(network_volume_id="vol_abc", data_center_ids=("EU-RO-1",))
    payload = spec.to_payload("NVIDIA GeForce RTX 4090")
    assert payload["mounts"] == {"network": [{"volumeId": "vol_abc", "path": "/workspace"}]}


def test_list_pods_parses_and_records(runpod_key: Secret, tmp_path: Path) -> None:
    transport = RecordingTransport(lambda _: json_response(200, {"pods": [pod_payload()]}))
    client = RunPodPodsClient(
        key=runpod_key, execute=True, receipts_dir=tmp_path, transport=transport
    )
    pods = client.list_pods()
    assert not isinstance(pods, ProviderReceipt)
    assert len(pods) == 1
    assert pods[0].pod_id == "pod_test0001"
    assert pods[0].is_live
    assert pods[0].gpu_utilization_percent == pytest.approx(91.0)
    assert transport.requests[0].headers["Authorization"].startswith("Bearer ")
    client.close()


def test_unknown_pod_status_is_a_protocol_error(runpod_key: Secret) -> None:
    bad = pod_payload()
    bad["status"] = "SOMETHING_NEW"
    transport = RecordingTransport(lambda _: json_response(200, {"pods": [bad]}))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    with pytest.raises(RunPodProtocolError, match="outside the pinned v2 enum"):
        client.list_pods()
    client.close()


def test_non_json_response_is_a_protocol_error(runpod_key: Secret) -> None:
    transport = RecordingTransport(lambda _: httpx.Response(200, text="<html>nope</html>"))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    with pytest.raises(RunPodProtocolError, match="application/json"):
        client.list_pods()
    client.close()


def test_http_error_body_is_withheld(runpod_key: Secret) -> None:
    transport = RecordingTransport(
        lambda _: json_response(500, {"detail": f"echoed {FAKE_RUNPOD_VALUE}"})
    )
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    with pytest.raises(RunPodClientError) as caught:
        client.list_pods()
    assert FAKE_RUNPOD_VALUE not in str(caught.value)
    assert "body withheld" in str(caught.value)
    client.close()


def test_create_pod_adopts_an_existing_campaign_pod(runpod_key: Secret) -> None:
    spec = _spec()
    existing = pod_payload(name=spec.name, env={"ARENA_CAMPAIGN_ID": CAMPAIGN_ID})
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "GET":
            return json_response(200, {"pods": [existing]})
        raise AssertionError("create must not be called when a live pod already exists")

    client = RunPodPodsClient(key=runpod_key, execute=True, transport=RecordingTransport(handler))
    pod = client.create_pod(spec)
    assert not isinstance(pod, ProviderReceipt)
    assert pod.pod_id == "pod_test0001"
    assert calls == ["GET /v2/pods"]
    client.close()


def test_create_pod_refuses_a_same_name_pod_from_another_campaign(runpod_key: Secret) -> None:
    """D24: the campaign name prefix is a second witness of ownership.

    A live pod already wearing this campaign's pod name is never duplicated.
    Adopting it would send our pages to a worker another campaign configured;
    creating alongside it would rent a second GPU under one name. The refusal
    is the only outcome that costs nothing and hides nothing.
    """

    spec = _spec()
    other = pod_payload(name=spec.name, env={"ARENA_CAMPAIGN_ID": "SOME-OTHER-CAMPAIGN"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, {"pods": [other]})
        raise AssertionError("create must not be called when the name is already taken")

    client = RunPodPodsClient(key=runpod_key, execute=True, transport=RecordingTransport(handler))
    try:
        with pytest.raises(RunPodClientError) as excinfo:
            client.create_pod(spec)
    finally:
        client.close()
    assert "SOME-OTHER-CAMPAIGN" in str(excinfo.value)
    assert "D24" in str(excinfo.value)


def test_create_pod_falls_through_the_gpu_priority_list_on_rejection(
    runpod_key: Secret,
) -> None:
    spec = _spec()
    attempts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, {"pods": []})
        body = json.loads(request.content.decode("utf-8"))
        gpu = body["gpu"]["id"]
        attempts.append(gpu)
        if gpu == "NVIDIA GeForce RTX 4090":
            return json_response(422, {"detail": "no capacity"})
        return json_response(201, pod_payload(pod_id="pod_a40", name=spec.name))

    client = RunPodPodsClient(key=runpod_key, execute=True, transport=RecordingTransport(handler))
    pod = client.create_pod(spec)
    assert not isinstance(pod, ProviderReceipt)
    assert attempts == ["NVIDIA GeForce RTX 4090", "NVIDIA A40"]
    client.close()


def test_create_pod_stops_on_an_ambiguous_server_error(runpod_key: Secret) -> None:
    """A 5xx might mean the pod exists. Trying the next GPU could double-spend."""

    spec = _spec()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, {"pods": []})
        return json_response(503, {"detail": "upstream"})

    client = RunPodPodsClient(key=runpod_key, execute=True, transport=RecordingTransport(handler))
    with pytest.raises(RunPodClientError, match="HTTP 503"):
        client.create_pod(spec)
    client.close()


def test_catalog_snapshot_is_written_and_hashed(runpod_key: Secret, tmp_path: Path) -> None:
    transport = RecordingTransport(
        lambda _: json_response(
            200, {"gpus": [gpu_payload(), gpu_payload("NVIDIA A40", community=0.35)]}
        )
    )
    client = RunPodPodsClient(
        key=runpod_key, execute=True, receipts_dir=tmp_path, transport=transport
    )
    snapshot = client.catalog_gpus()
    assert isinstance(snapshot, PriceSnapshot)
    assert len(snapshot.rows) == 2
    assert snapshot.path is not None
    assert snapshot.path.name.startswith("catalog-")
    row = snapshot.row("NVIDIA GeForce RTX 4090")
    assert row.price_community_usd_per_hour == pytest.approx(0.34)
    assert len(row.row_sha256()) == 64
    cheapest = snapshot.cheapest(["NVIDIA GeForce RTX 4090", "NVIDIA A40"], "COMMUNITY")
    assert cheapest is not None
    assert cheapest.gpu_type_id == "NVIDIA GeForce RTX 4090"
    client.close()


def test_price_snapshot_reports_a_missing_gpu_row(runpod_key: Secret) -> None:
    transport = RecordingTransport(lambda _: json_response(200, {"gpus": [gpu_payload()]}))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    snapshot = client.catalog_gpus()
    assert isinstance(snapshot, PriceSnapshot)
    with pytest.raises(RunPodClientError, match="absent from the price snapshot"):
        snapshot.row("NVIDIA H100 PCIe")
    client.close()


def test_billing_window_validation() -> None:
    with pytest.raises(RunPodClientError, match="mutually exclusive"):
        BillingWindow(last_n=5, start_time="2026-09-01T00:00:00Z")
    with pytest.raises(RunPodClientError, match="bucketSize"):
        BillingWindow(bucket_size="fortnight")
    assert BillingWindow().to_params() == {"bucketSize": "hour", "lastN": 24}


def test_billing_pods_parses_metadata(runpod_key: Secret) -> None:
    payload = {
        "records": [
            {
                "podId": "pod_test0001",
                "startTime": "2026-09-03T10:00:00Z",
                "endTime": "2026-09-03T11:00:00Z",
                "totalAmount": 0.34,
                "gpuAmount": 0.3,
                "cpuAmount": 0.0,
                "diskAmount": 0.04,
            }
        ],
        "metadata": {
            "query": {},
            "recordCount": 1,
            "uniquePodCount": 1,
            "totals": {
                "totalAmount": 0.34,
                "gpuAmount": 0.3,
                "cpuAmount": 0.0,
                "diskAmount": 0.04,
            },
        },
    }
    transport = RecordingTransport(lambda _: json_response(200, payload))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    billing = client.billing_pods(BillingWindow())
    assert not isinstance(billing, ProviderReceipt)
    assert billing["record_count"] == 1
    assert billing["total_amount_usd"] == pytest.approx(0.34)
    client.close()


def test_delete_pod_expects_no_body(runpod_key: Secret) -> None:
    transport = RecordingTransport(lambda _: httpx.Response(204))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    assert client.delete_pod("pod_test0001") is None
    assert transport.requests[0].method == "DELETE"
    client.close()


def test_stop_pod_uses_the_action_endpoint(runpod_key: Secret) -> None:
    transport = RecordingTransport(
        lambda _: json_response(200, pod_payload(status="EXITED", cost=0.0))
    )
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    pod = client.stop_pod("pod_test0001")
    assert not isinstance(pod, ProviderReceipt)
    assert pod is not None
    assert pod.status == "EXITED"
    assert transport.requests[0].url.path == "/v2/pods/pod_test0001/action"
    assert json.loads(transport.requests[0].content) == {"action": "stop"}
    client.close()


def test_writes_are_refused_without_execute(runpod_key: Secret) -> None:
    client = RunPodPodsClient(key=runpod_key, execute=False)
    for result in (client.delete_pod("pod_x"), client.stop_pod("pod_x")):
        assert isinstance(result, ProviderReceipt)
        assert result.mode == "dry_run"


def test_no_receipt_ever_carries_the_api_key(runpod_key: Secret, tmp_path: Path) -> None:
    transport = RecordingTransport(lambda _: json_response(200, {"pods": [pod_payload()]}))
    client = RunPodPodsClient(
        key=runpod_key, execute=True, receipts_dir=tmp_path, transport=transport
    )
    client.list_pods()
    client.close()
    for path in tmp_path.rglob("*.json"):
        content = path.read_text(encoding="utf-8")
        assert FAKE_RUNPOD_VALUE not in content
        assert "Authorization" not in content
        assert json.loads(content)["key_withheld"] is True


def test_a_zero_rate_is_an_absent_price_not_a_free_gpu(runpod_key: Secret) -> None:
    """Observed live on 2026-09-03: the catalog reports 0.0 for a tier it does
    not offer, plus a placeholder row whose id is literally "unknown". Treating
    either as a price would put a $0 line into a cost projection.
    """

    payload = {
        "gpus": [
            gpu_payload("unknown", secure=0.0, community=0.0),
            gpu_payload("NVIDIA A100-SXM4-40GB", secure=0.0, community=1.0),
            gpu_payload("NVIDIA GeForce RTX 4090", secure=0.74, community=0.34),
        ]
    }
    transport = RecordingTransport(lambda _: json_response(200, payload))
    client = RunPodPodsClient(key=runpod_key, execute=True, transport=transport)
    snapshot = client.catalog_gpus()
    assert isinstance(snapshot, PriceSnapshot)

    assert snapshot.row("unknown").rate_for("COMMUNITY") is None
    assert snapshot.row("NVIDIA A100-SXM4-40GB").rate_for("SECURE") is None
    assert snapshot.row("NVIDIA A100-SXM4-40GB").rate_for("COMMUNITY") == pytest.approx(1.0)

    # The raw value is preserved verbatim in the snapshot; only the rate lookup
    # refuses to call it a price.
    assert snapshot.row("unknown").price_community_usd_per_hour == pytest.approx(0.0)

    cheapest = snapshot.cheapest(
        ["unknown", "NVIDIA A100-SXM4-40GB", "NVIDIA GeForce RTX 4090"], "COMMUNITY"
    )
    assert cheapest is not None
    assert cheapest.gpu_type_id == "NVIDIA GeForce RTX 4090"
    assert [row.gpu_type_id for row in snapshot.priced_rows("SECURE")] == [
        "NVIDIA GeForce RTX 4090"
    ]
    client.close()


# --------------------------------------------------- host CUDA floor (v2)


def test_the_v2_payload_carries_the_cuda_floor_inside_the_gpu_block() -> None:
    """v2's CreateGpuConfig holds it, so it is unrepresentable on a CPU pod."""

    spec = _spec(allowed_cuda_versions=("12.8", "12.9", "13.0"))
    payload = spec.to_payload("NVIDIA GeForce RTX 4090")
    assert payload["gpu"] == {
        "id": "NVIDIA GeForce RTX 4090",
        "count": 1,
        "allowedCudaVersions": ["12.8", "12.9", "13.0"],
    }
    assert "allowedCudaVersions" not in payload


def test_the_v2_payload_omits_the_key_when_there_is_no_constraint() -> None:
    payload = _spec().to_payload("NVIDIA GeForce RTX 4090")
    assert payload["gpu"] == {"id": "NVIDIA GeForce RTX 4090", "count": 1}


def test_a_capacity_refusal_is_receipted_before_the_walk_moves_on(
    runpod_key: Secret,
) -> None:
    """Without a receipt for the refusal, the walk leaves no trail to read."""

    spec = _spec(allowed_cuda_versions=("12.9", "13.0"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return json_response(200, {"pods": []})
        body = json.loads(request.content.decode("utf-8"))
        assert body["gpu"]["allowedCudaVersions"] == ["12.9", "13.0"]
        if body["gpu"]["id"] == "NVIDIA GeForce RTX 4090":
            return json_response(422, {"detail": "no capacity"})
        return json_response(201, pod_payload(pod_id="pod_a40", name=spec.name))

    client = RunPodPodsClient(key=runpod_key, execute=True, transport=RecordingTransport(handler))
    try:
        pod = client.create_pod(spec)
    finally:
        client.close()
    assert not isinstance(pod, ProviderReceipt)
    attempts = [receipt.summary for receipt in client.receipts if receipt.action == "create_pod"]
    assert [attempt.get("attempt") for attempt in attempts] == [1, 2]
    assert attempts[0]["created"] is False
    assert attempts[0]["gpu_type_ids"] == ["NVIDIA GeForce RTX 4090"]
    assert attempts[1]["created"] is True
    assert attempts[1]["gpu_type_ids"] == ["NVIDIA A40"]
