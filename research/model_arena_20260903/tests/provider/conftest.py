"""Shared fixtures for the provider tests. No network, no credentials."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import httpx
import pytest
from arena.provider.secrets import Secret

# Deliberately implausible values: nothing here resembles a real credential,
# and no test writes any of them into a receipt.
FAKE_RUNPOD_VALUE = "runpodfake000000000000000000000000000000000000000"
FAKE_R2_ACCESS = "r2fakeaccess00000000000000000000"
FAKE_R2_SECRET = "r2fakesecret" + "0" * 52
FAKE_ENDPOINT = "https://fakeaccount.eu.r2.cloudflarestorage.com"


@pytest.fixture
def credential_file(tmp_path: Path) -> Path:
    """A stand-in for D:\\Github_API.txt with the same block structure."""

    path = tmp_path / "fake_credentials.txt"
    path.write_text(
        "\n".join(
            [
                "Github: ghfake0000000000000000000000000000000000",
                f"Runpod_A: {FAKE_RUNPOD_VALUE.replace('runpod', 'runpoda')}",
                f"Runpod_B: {FAKE_RUNPOD_VALUE}",
                "Cloudflare R2:",
                "Account API Token: {",
                "Token value: accountfaketoken0000000000000000000000000000000000000",
                f"Access Key ID: {FAKE_R2_ACCESS}",
                f"Secret Access Key: {FAKE_R2_SECRET}",
                f"Use jurisdiction-specific endpoints for S3 clients: {FAKE_ENDPOINT}",
                "}",
                "User API Tokens: {",
                "Token value: userfaketoken000000000000000000000000000000000000000",
                f"Access Key ID: {FAKE_R2_ACCESS.replace('access', 'accessu')[:32]}",
                f"Secret Access Key: {FAKE_R2_SECRET.replace('secret', 'secretu')[:64]}",
                "Use jurisdiction-specific endpoints for S3 clients: "
                "https://fakeaccount.us.r2.cloudflarestorage.com",
                "}",
                "Toss API: {",
                "Client ID: tossfakeclientid0000000000000000",
                "}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def runpod_key() -> Secret:
    return Secret(FAKE_RUNPOD_VALUE, label="Runpod_B")


@pytest.fixture
def worker_bearer_secret() -> Secret:
    return Secret("arena-fake-bearer-value-0000000000", label="ARENA_WORKER_TOKEN")


class RecordingTransport(httpx.BaseTransport):
    """An httpx transport that answers from a handler and records requests."""

    def __init__(self, handler: Callable[[httpx.Request], httpx.Response]) -> None:
        self._handler = handler
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self._handler(request)


def json_response(status_code: int, payload: Mapping[str, object] | list[object]) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=json.dumps(payload).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def pod_payload(
    *,
    pod_id: str = "pod_test0001",
    name: str = "arena-paddleocr-vl-1-6-w0-20260903v1",
    status: str = "RUNNING",
    env: Mapping[str, str] | None = None,
    cost: float = 0.34,
) -> dict[str, object]:
    return {
        "id": pod_id,
        "name": name,
        "status": status,
        "actions": ["stop", "terminate"],
        "image": "runpod/pytorch:1.0.2",
        "args": "",
        "disk": 80,
        "mounts": {},
        "ports": ["8000/http"],
        "env": dict(env or {}),
        "registry": None,
        "cloud": "COMMUNITY",
        "dataCenterId": "US-TX-3",
        "cudaVersion": "12.8",
        "ssh": {},
        "template": None,
        "cost": cost,
        "locked": False,
        "runtime": {"uptime": 120, "gpus": [{"utilizationPercent": 91}]},
        "createdAt": "2026-09-03T10:00:00Z",
        "startedAt": "2026-09-03T10:01:00Z",
        "globalNetworking": {},
        "gpu": {"id": "NVIDIA GeForce RTX 4090", "count": 1, "vcpuCount": 8, "memory": 32},
    }


def gpu_payload(
    gpu_id: str = "NVIDIA GeForce RTX 4090",
    *,
    secure: float | None = 0.44,
    community: float | None = 0.34,
) -> dict[str, object]:
    price: dict[str, object] = {}
    if secure is not None:
        price["secure"] = secure
    if community is not None:
        price["community"] = community
    return {
        "id": gpu_id,
        "name": gpu_id.replace("NVIDIA GeForce ", ""),
        "pool": "ADA_24",
        "manufacturer": "NVIDIA",
        "memory": 24,
        "secure": True,
        "community": True,
        "price": price,
        "maxCount": {"secure": 8, "community": 4},
    }


@pytest.fixture
def transport_factory() -> Iterator[Callable[..., RecordingTransport]]:
    created: list[RecordingTransport] = []

    def make(handler: Callable[[httpx.Request], httpx.Response]) -> RecordingTransport:
        transport = RecordingTransport(handler)
        created.append(transport)
        return transport

    yield make
    created.clear()
