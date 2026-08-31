"""Tests for the builder session driver's paid-capacity safety properties.

Every test here corresponds to a failure measured against the live RunPod API
on 2026-08-31 and recorded in
``infra/runpod/v6/qualification/rq-01/KNOWN_ISSUES.md``. They exist to prove
the mitigations actually fire, not merely that the happy path runs: each one
would pass trivially against a driver with no safety logic at all if it only
asserted success, so each asserts the *refusal* or the *cleanup* instead.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6 import run_builder_session as rbs
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.builder_pod import (
    BuilderPodError,
    BuilderPodSpec,
    RunPodBuilderClient,
)

_BASE_IMAGE = "ubuntu@sha256:" + "3" * 64
_PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAItest builder@test"


def _spec(name: str = "folynta-builder-test-target") -> BuilderPodSpec:
    return rbs.build_builder_spec(
        name=name,
        base_image_digest=_BASE_IMAGE,
        gpu_type="NVIDIA GeForce RTX 4090",
        public_key=_PUBLIC_KEY,
        allocation_id="test-allocation",
        maximum_hourly_rate_usd="1.00",
        maximum_runtime_hours="3",
        container_disk_gb=300,
    )


class _StubClient:
    """Minimal stand-in for RunPodBuilderClient's delete/get surface."""

    def __init__(self, *, existing: list[str]) -> None:
        self.existing = list(existing)
        self.deleted: list[str] = []

    def delete(self, pod_id: str) -> dict[str, object]:
        self.deleted.append(pod_id)
        if pod_id in self.existing:
            self.existing.remove(pod_id)
        return {"pod_id": pod_id}

    def get(self, pod_id: str) -> dict[str, object]:
        if pod_id in self.existing:
            return {"id": pod_id}
        raise BuilderPodError("RunPod GET failed with status 404")


def test_absence_is_proven_only_by_a_404() -> None:
    client = _StubClient(existing=["pod-1"])
    receipt = rbs.delete_and_prove_absence(client, "pod-1")
    assert receipt["observation"] == "GET_404_NOT_FOUND"
    assert receipt["absence_proven"] is True
    assert client.deleted == ["pod-1"]


def test_absence_is_not_proven_when_the_pod_still_reads_back() -> None:
    """A delete that the provider ignores must not be reported as absence."""

    class _IgnoresDelete(_StubClient):
        def delete(self, pod_id: str) -> dict[str, object]:
            self.deleted.append(pod_id)
            return {"pod_id": pod_id}  # provider acknowledges but keeps the Pod

    client = _IgnoresDelete(existing=["pod-1"])
    receipt = rbs.delete_and_prove_absence(client, "pod-1")
    assert receipt["observation"] == "GET_STILL_RETURNS_POD"
    assert receipt["absence_proven"] is False


def test_absence_is_not_proven_by_a_non_404_error() -> None:
    """A 500 on read-back proves nothing and must not count as absence.

    Without this case, `absence_proven` could be hardcoded to True and the
    suite would still pass: the 404 path and the still-returns path would both
    be satisfied by a constant. Here the read-back fails for a reason that is
    NOT evidence the Pod is gone, so a constant True is provably wrong.
    """

    class _ReadBackErrors(_StubClient):
        def get(self, pod_id: str) -> dict[str, object]:
            raise BuilderPodError("RunPod GET failed with status 500")

    client = _ReadBackErrors(existing=["pod-1"])
    receipt = rbs.delete_and_prove_absence(client, "pod-1")
    assert receipt["observation"] == "GET_FAILED_NOT_404"
    assert receipt["absence_proven"] is False



def test_ambiguous_create_reconciles_the_orphan_it_could_not_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """INC-RUNPOD-03: HTTP 500 can still create a Pod.

    ``create`` raises without ever returning the id, so the session must find
    the orphan by name and delete it. Without that reconciliation the Pod bills
    unattended.
    """

    spec = _spec()
    orphan_id = "orphan-from-500"
    client = _StubClient(existing=[orphan_id])

    def _create(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise BuilderPodError("RunPod POST failed with status 500")

    client.create = _create  # type: ignore[attr-defined]
    monkeypatch.setattr(
        rbs, "find_pods_by_name", lambda *, api_key, name: [orphan_id]
    )

    budget = AuthorizedSpendBudget(campaign_id="test", hard_cap_usd=Decimal("50"))
    with pytest.raises(BuilderPodError):
        rbs.open_builder_session(
            client=client,  # type: ignore[arg-type]
            spec=spec,
            budget=budget,
            receipts_dir=tmp_path,
            api_key="test-key",
        )

    assert client.deleted == [orphan_id], "the orphan was not reconciled"
    written = list(tmp_path.glob("builder-orphan-*.json"))
    assert written, "no reconciliation receipt was written"


def test_a_pod_that_never_starts_is_refused_rather_than_waited_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """INC-RUNPOD-02: uptimeInSeconds stays 0 while the Pod bills.

    verify_ready keeps failing (no public IP is ever assigned), so a driver
    that only trusted `desiredStatus` would poll until its timeout. The zombie
    check must cut that short with a distinct error.
    """

    spec = _spec()

    class _NeverReady:
        def verify_ready(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            raise BuilderPodError("RunPod builder public IP is unavailable")

    monkeypatch.setattr(rbs, "resolve_gpu_name_via_graphql", lambda **_: "RTX 4090")
    monkeypatch.setattr(rbs, "read_uptime_seconds", lambda **_: 0)

    ticks = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0])
    with pytest.raises(rbs.BuilderSessionError) as excinfo:
        rbs._poll_until_ready(
            _NeverReady(),  # type: ignore[arg-type]
            spec,
            pod_id="pod-zombie",
            timeout_seconds=10_000.0,
            api_key="test-key",
            clock=lambda: next(ticks),
            sleeper=lambda _seconds: None,
        )
    assert "uptimeInSeconds=0" in str(excinfo.value)
    assert "INC-RUNPOD-02" in str(excinfo.value)


def test_a_healthy_pod_is_not_misread_as_a_zombie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The zombie guard must not fire when the container really is up."""

    spec = _spec()
    ready_receipt = {"public_ip": "10.0.0.1", "ssh_port": 22, "gpu": "RTX 4090"}

    class _ReadyOnSecondPoll:
        def __init__(self) -> None:
            self.calls = 0

        def verify_ready(self, *_args: object, **_kwargs: object) -> dict[str, object]:
            self.calls += 1
            if self.calls == 1:
                raise BuilderPodError("RunPod builder Pod is not running")
            return ready_receipt

    monkeypatch.setattr(rbs, "resolve_gpu_name_via_graphql", lambda **_: "RTX 4090")
    monkeypatch.setattr(rbs, "read_uptime_seconds", lambda **_: 42)

    ticks = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0, 1000.0])
    result = rbs._poll_until_ready(
        _ReadyOnSecondPoll(),  # type: ignore[arg-type]
        spec,
        pod_id="pod-healthy",
        timeout_seconds=10_000.0,
        api_key="test-key",
        clock=lambda: next(ticks),
        sleeper=lambda _seconds: None,
    )
    assert result is ready_receipt


def test_gpu_identity_falls_back_to_graphql_when_rest_is_empty() -> None:
    """INC-RUNPOD-02's sibling: REST returned `machine: {}` for a live Pod.

    The GraphQL cross-check supplies the identity verify_ready needs. A Pod id
    that GraphQL does not know must yield "" so the caller still fails closed.
    """

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "myself": {
                        "pods": [
                            {"id": "known", "machine": {"gpuDisplayName": "RTX 4090"}}
                        ]
                    }
                }
            },
        )

    transport = httpx.MockTransport(_handler)
    original = httpx.Client

    class _PatchedClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    httpx.Client = _PatchedClient  # type: ignore[misc]
    try:
        assert (
            rbs.resolve_gpu_name_via_graphql(api_key="k", pod_id="known")
            == "RTX 4090"
        )
        assert rbs.resolve_gpu_name_via_graphql(api_key="k", pod_id="absent") == ""
    finally:
        httpx.Client = original  # type: ignore[misc]


def test_builder_spec_rejects_a_mutable_image_tag() -> None:
    """The builder must pin its base image by digest, never by tag."""

    with pytest.raises(ContractError):
        rbs.build_builder_spec(
            name="folynta-builder-test-target",
            base_image_digest="ubuntu:24.04",
            gpu_type="NVIDIA GeForce RTX 4090",
            public_key=_PUBLIC_KEY,
            allocation_id="test-allocation",
            maximum_hourly_rate_usd="1.00",
            maximum_runtime_hours="3",
        )


def test_builder_spec_rejects_an_unsupported_gpu() -> None:
    with pytest.raises(ContractError):
        rbs.build_builder_spec(
            name="folynta-builder-test-target",
            base_image_digest=_BASE_IMAGE,
            gpu_type="NVIDIA H100 PCIe",
            public_key=_PUBLIC_KEY,
            allocation_id="test-allocation",
            maximum_hourly_rate_usd="1.00",
            maximum_runtime_hours="3",
        )


def test_reconciliation_refuses_to_guess_when_the_inventory_is_unreadable() -> None:
    """A failed list must raise, not silently report "no orphans found"."""

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    transport = httpx.MockTransport(_handler)
    original = httpx.Client

    class _PatchedClient(original):  # type: ignore[misc,valid-type]
        def __init__(self, *args: object, **kwargs: object) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    httpx.Client = _PatchedClient  # type: ignore[misc]
    try:
        with pytest.raises(rbs.BuilderSessionError):
            rbs.find_pods_by_name(api_key="k", name="folynta-builder-test-target")
    finally:
        httpx.Client = original  # type: ignore[misc]


def test_unused_client_import_is_available() -> None:
    """Guards the module's public surface against an accidental rename."""

    assert issubclass(RunPodBuilderClient, object)
