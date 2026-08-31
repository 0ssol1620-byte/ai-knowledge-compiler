"""Tests for the rq-01 qualification session driver.

Covers two things:

1. The `QualificationPodSpec.container_registry_auth_id` /
   `requires_registry_auth` addition in `qualification_pod.py`
   (`provider_payload()` backward compatibility, fail-closed validation,
   format checks, and that `redacted_identity()` never carries more than the
   opaque ID).
2. The new `run_qualification_session.py` driver: the locked budget wrapper,
   the watchdog-checked readiness poll, the delete -> 404-absence-proof
   helper, unconditional teardown, and the orphan-name scan.

Every test uses `httpx.MockTransport` (or no transport at all, for the pure
dataclass tests). None of these tests perform real network I/O, spend real
money, or touch a real GPU or credential.
"""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest

from benchmark.v6.contracts import ContractError
from infra.runpod.v6 import run_qualification_session as rqs_module
from infra.runpod.v6.qualification_pod import (
    QualificationPodSpec,
    RunPodQualificationClient,
)
from infra.runpod.v6.run_qualification_session import (
    LockedAuthorizedSpendBudget,
    QualificationSession,
    QualificationSessionError,
    assert_no_orphaned_qualification_pods,
    run_qualification_session,
)

FAKE_API_KEY = "fake-test-key-not-a-real-runpod-credential"
PRIVATE_IMAGE_MINERU = (
    "ghcr.io/0ssol1620-byte/ai-knowledge-compiler/mineru-3.4.4-vlm-c1@sha256:" + "b" * 64
)


def _spec(**overrides: Any) -> QualificationPodSpec:
    fields: dict[str, Any] = {
        "name": "folynta-qualification-ovis-20260804",
        "image_name": "ghcr.io/example/ovis@sha256:" + "a" * 64,
        "gpu_type": "NVIDIA A40",
        "public_key": "ssh-ed25519 AAAATEST test",
        "allocation_id": "qualify-ovis",
        "maximum_hourly_rate_usd": Decimal("0.50"),
        "maximum_runtime_hours": Decimal("4"),
    }
    fields.update(overrides)
    return QualificationPodSpec(**fields)


def _session_spec(**overrides: Any) -> QualificationPodSpec:
    fields: dict[str, Any] = {
        "name": "folynta-qualification-session-test",
        "image_name": "ghcr.io/example/qual@sha256:" + "a" * 64,
        "gpu_type": "NVIDIA A40",
        "public_key": "ssh-ed25519 AAAATEST test",
        "allocation_id": "qualify-session-test",
        "maximum_hourly_rate_usd": Decimal("0.50"),
        "maximum_runtime_hours": Decimal("4"),
    }
    fields.update(overrides)
    return QualificationPodSpec(**fields)


def _sequential_handler(
    responses: list[tuple[int, dict[str, Any] | None]],
) -> tuple[Any, list[httpx.Request]]:
    calls: list[httpx.Request] = []
    state = {"index": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        index = state["index"]
        state["index"] += 1
        status, body = responses[index]
        if body is None:
            return httpx.Response(status)
        return httpx.Response(status, headers={"content-type": "application/json"}, json=body)

    return handler, calls


# --------------------------------------------------------------------------
# Part A: QualificationPodSpec.container_registry_auth_id
# --------------------------------------------------------------------------


def test_provider_payload_unchanged_when_auth_id_absent() -> None:
    spec = _spec()
    payload = spec.provider_payload()
    assert "containerRegistryAuthId" not in payload
    assert payload == {
        "name": spec.name,
        "imageName": spec.image_name,
        "cloudType": "SECURE",
        "computeType": "GPU",
        "gpuTypeIds": [spec.gpu_type],
        "gpuTypePriority": "availability",
        "gpuCount": 1,
        "containerDiskInGb": spec.container_disk_gb,
        "volumeInGb": spec.volume_gb,
        "volumeMountPath": "/workspace",
        "ports": ["22/tcp"],
        "supportPublicIp": True,
        "interruptible": False,
        "allowedCudaVersions": list(spec.allowed_cuda_versions),
        "env": {
            "PUBLIC_KEY": spec.public_key,
            "FOLYNTA_IMAGE_DIGEST": spec.image_name,
            "FOLYNTA_QUALIFICATION_ONLY": "1",
        },
    }


def test_provider_payload_includes_registry_auth_id_when_set() -> None:
    spec = _spec(container_registry_auth_id="runpod-auth-abc123")
    payload = spec.provider_payload()
    assert payload["containerRegistryAuthId"] == "runpod-auth-abc123"
    # Every other key is untouched.
    without_auth = {k: v for k, v in payload.items() if k != "containerRegistryAuthId"}
    assert without_auth == _spec().provider_payload()


def test_requires_registry_auth_without_id_raises_before_network() -> None:
    with pytest.raises(ContractError, match="container_registry_auth_id"):
        _spec(
            image_name=PRIVATE_IMAGE_MINERU,
            requires_registry_auth=True,
            container_registry_auth_id=None,
        )


def test_requires_registry_auth_with_empty_id_raises() -> None:
    with pytest.raises(ContractError, match="malformed"):
        _spec(
            image_name=PRIVATE_IMAGE_MINERU,
            requires_registry_auth=True,
            container_registry_auth_id="",
        )


def test_requires_registry_auth_with_id_constructs_and_payload_carries_it() -> None:
    spec = _spec(
        image_name=PRIVATE_IMAGE_MINERU,
        requires_registry_auth=True,
        container_registry_auth_id="runpod-auth-abc123",
    )
    assert spec.provider_payload()["containerRegistryAuthId"] == "runpod-auth-abc123"


def test_container_registry_auth_id_rejects_whitespace() -> None:
    with pytest.raises(ContractError, match="malformed"):
        _spec(container_registry_auth_id="has space")


def test_container_registry_auth_id_rejects_overlong_value() -> None:
    with pytest.raises(ContractError, match="malformed"):
        _spec(container_registry_auth_id="x" * 300)


def test_redacted_identity_carries_only_the_auth_id_never_a_credential() -> None:
    spec = _spec(container_registry_auth_id="runpod-auth-abc123")
    redacted = spec.redacted_identity()
    assert redacted["containerRegistryAuthId"] == "runpod-auth-abc123"
    serialized = json.dumps(redacted, sort_keys=True, default=str)
    # The ID appears exactly once, as itself -- nothing else in the redacted
    # identity references or duplicates it, and no credential value exists
    # anywhere in this class to leak in the first place.
    assert serialized.count("runpod-auth-abc123") == 1
    assert '"PUBLIC_KEY": "redacted"' in serialized


# --------------------------------------------------------------------------
# Part B: LockedAuthorizedSpendBudget
# --------------------------------------------------------------------------


def _bounded(operation: Callable[[], Any], *, seconds: float = 5.0) -> Any:
    """Run one budget call on a daemon thread and fail fast if it blocks.

    The failure mode this wrapper exists for is a *deadlock*, not a wrong
    answer: a called-directly `LockedAuthorizedSpendBudget` method that
    blocks against its own lock hangs the test run forever instead of
    failing it, and a non-daemon thread parked on a lock also stops the
    interpreter from exiting. Every budget-lock call in this section is
    therefore routed through here, so a regression surfaces as a named
    assertion failure in bounded time. The operations below are still
    strictly sequential -- one at a time, joined before the next -- so
    running them off the main thread changes nothing about what is asserted.
    """

    outcome: dict[str, Any] = {}

    def runner() -> None:
        try:
            outcome["value"] = operation()
        except BaseException as exc:  # re-raised on the calling thread below
            outcome["error"] = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout=seconds)
    if thread.is_alive():
        raise AssertionError(
            f"budget operation did not complete within {seconds}s -- "
            "LockedAuthorizedSpendBudget is deadlocked"
        )
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def test_locked_budget_reserve_does_not_self_deadlock_on_reentrant_dispatch() -> None:
    """Regression: one `reserve()` re-enters this class's own locked properties.

    `AuthorizedSpendBudget.reserve()` reads `self.remaining_usd`, and
    `remaining_usd` reads `self.reserved_usd` / `self.settled_usd`. On a
    `LockedAuthorizedSpendBudget` those attribute lookups dispatch back into
    the lock-taking overrides *on the same thread that already holds the
    lock* from the outer `reserve()`. With a non-reentrant `threading.Lock`
    that is an unconditional self-deadlock on the very first `reserve()`,
    with no second thread involved at all.
    """

    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-reentrancy", hard_cap_usd="10")
    reservation = _bounded(lambda: budget.reserve(allocation_id="reentrant", maximum_cost_usd="1"))
    assert reservation.maximum_cost_usd == Decimal("1.000000")
    # report() reads all three overridden properties in a single call.
    assert _bounded(budget.report)["remaining_usd"] == "9.000000"


def test_locked_budget_sequential_reserve_respects_remaining_cap() -> None:
    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-test", hard_cap_usd="10")
    _bounded(lambda: budget.reserve(allocation_id="a", maximum_cost_usd="6"))
    assert _bounded(lambda: budget.remaining_usd) == Decimal("4.000000")
    with pytest.raises(ContractError, match="hard cap would be exceeded"):
        _bounded(lambda: budget.reserve(allocation_id="b", maximum_cost_usd="5"))
    # A second, smaller reservation that does fit still succeeds -- the
    # rejected attempt above must not have partially mutated state.
    _bounded(lambda: budget.reserve(allocation_id="c", maximum_cost_usd="4"))
    assert _bounded(lambda: budget.remaining_usd) == Decimal("0.000000")


def test_locked_budget_concurrent_reserve_never_exceeds_cap() -> None:
    """The real regression test for the unlocked check-then-act race.

    20 threads each try to reserve exactly $3 against a $10 cap. Serialized
    behind the lock, exactly 3 can ever fit (9 <= 10; a 4th would be 12 > 10)
    -- regardless of thread scheduling order. An unlocked
    check-then-act implementation could let more than 3 succeed on an
    unlucky interleaving; this must not.
    """

    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-thread-test", hard_cap_usd="10")
    successes: list[int] = []
    successes_lock = threading.Lock()

    def worker(index: int) -> None:
        try:
            budget.reserve(allocation_id=f"thread-{index}", maximum_cost_usd="3")
        except ContractError:
            return
        with successes_lock:
            successes.append(index)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(20)]
    for thread in threads:
        thread.start()
    # One shared deadline across all 20 joins, not a per-thread timeout:
    # under a deadlock every thread is stuck, so per-thread timeouts would
    # serialize into 20x the wait before this test could report. Daemon
    # threads (above) also keep a stuck one from blocking interpreter exit.
    deadline = time.monotonic() + 5.0
    for thread in threads:
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
    still_running = [index for index, thread in enumerate(threads) if thread.is_alive()]
    assert not still_running, f"reserve() deadlocked on thread(s) {still_running}"

    assert len(successes) == 3
    assert budget.reserved_usd == Decimal("9.000000")
    assert budget.reserved_usd <= budget.hard_cap_usd


# --------------------------------------------------------------------------
# Part B: delete -> get -> expect-404 absence proof
# --------------------------------------------------------------------------


def test_delete_and_prove_absence_success() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [(202, None), (404, None)]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        result = rqs_module._delete_and_prove_absence(client, "qualsessabsence1")
    finally:
        client.close()

    assert result == {"pod_id": "qualsessabsence1", "observation": "GET_404_NOT_FOUND"}
    assert len(calls) == 2
    assert calls[0].method == "DELETE"
    assert calls[1].method == "GET"


def test_delete_and_prove_absence_raises_when_pod_still_present() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (202, None),
        (200, {"id": "qualsessabsence2", "name": "x", "desiredStatus": "RUNNING"}),
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(QualificationSessionError, match="unproven"):
            rqs_module._delete_and_prove_absence(client, "qualsessabsence2")
    finally:
        client.close()
    assert len(calls) == 2


def test_delete_and_prove_absence_raises_on_non_404_error() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [(202, None), (500, None)]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(QualificationSessionError, match="unproven"):
            rqs_module._delete_and_prove_absence(client, "qualsessabsence3")
    finally:
        client.close()
    assert len(calls) == 2


# --------------------------------------------------------------------------
# Part B: watchdog deadline during the readiness poll
# --------------------------------------------------------------------------


def test_watchdog_deadline_during_readiness_poll_triggers_teardown_not_infinite_loop() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (
            201,
            {
                "id": "qualsess-watchdog",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.4,
            },
        ),
        (
            200,
            {
                "id": "qualsess-watchdog",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "PROVISIONING",
            },
        ),
        (202, None),  # delete
        (404, None),  # absence proof
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-watchdog-test", hard_cap_usd="10")
    # First clock() call computes the deadline (0.0 + 1h = 3600.0); the
    # second is the poll loop's post-failure deadline check, which must
    # observe the deadline as already passed -- forcing teardown instead of
    # a second poll attempt (which this transport has no response queued
    # for, so an infinite/extra-poll bug would surface as a MockTransport
    # exhaustion error rather than a clean watchdog message).
    clock_values = iter([0.0, 999_999.0])
    try:
        with pytest.raises(QualificationSessionError, match="watchdog"):
            run_qualification_session(
                _session_spec(),
                client=client,
                budget=budget,
                maximum_runtime_hours=Decimal("1"),
                clock=lambda: next(clock_values),
                sleep=lambda _seconds: None,
            )
    finally:
        client.close()

    assert len(calls) == 4
    assert calls[0].method == "POST"
    assert calls[1].method == "GET"
    assert calls[2].method == "DELETE"
    assert calls[3].method == "GET"
    assert budget.reserved_usd == Decimal("0")
    assert budget.settled_usd == _session_spec().maximum_cost_usd


# --------------------------------------------------------------------------
# Part B: teardown always runs, even when the caller's on-pod work raises
# --------------------------------------------------------------------------


def test_teardown_always_runs_when_on_pod_work_raises() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (
            201,
            {
                "id": "qualsess-cb",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.4,
            },
        ),
        (
            200,
            {
                "id": "qualsess-cb",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.4,
                "publicIp": "10.0.0.5",
                "portMappings": {"22": 12345},
            },
        ),
        (202, None),  # delete
        (404, None),  # absence proof
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-cb-test", hard_cap_usd="10")

    def failing_on_pod_work(_ready_receipt: dict[str, Any]) -> None:
        raise RuntimeError("smoke failure")

    try:
        with pytest.raises(RuntimeError, match="smoke failure"):
            run_qualification_session(
                _session_spec(allocation_id="qualify-cb-test"),
                client=client,
                budget=budget,
                maximum_runtime_hours=Decimal("1"),
                on_pod_work=failing_on_pod_work,
                verified_gpu_name="NVIDIA A40",
                clock=lambda: 0.0,
                sleep=lambda _seconds: None,
            )
    finally:
        client.close()

    assert len(calls) == 4
    assert calls[2].method == "DELETE"
    assert calls[3].method == "GET"
    assert budget.reserved_usd == Decimal("0")
    assert budget.settled_usd == _session_spec().maximum_cost_usd


def test_teardown_runs_on_clean_success_too() -> None:
    responses: list[tuple[int, dict[str, Any] | None]] = [
        (
            201,
            {
                "id": "qualsess-ok",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.4,
            },
        ),
        (
            200,
            {
                "id": "qualsess-ok",
                "name": "folynta-qualification-session-test",
                "desiredStatus": "RUNNING",
                "adjustedCostPerHr": 0.4,
                "publicIp": "10.0.0.6",
                "portMappings": {"22": 12346},
            },
        ),
        (202, None),
        (404, None),
    ]
    handler, calls = _sequential_handler(responses)
    client = RunPodQualificationClient(api_key=FAKE_API_KEY, transport=httpx.MockTransport(handler))
    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-ok-test", hard_cap_usd="10")

    seen: dict[str, Any] = {}

    def on_pod_work(ready_receipt: dict[str, Any]) -> None:
        seen["ready"] = ready_receipt

    try:
        receipt = run_qualification_session(
            _session_spec(allocation_id="qualify-ok-test"),
            client=client,
            budget=budget,
            maximum_runtime_hours=Decimal("1"),
            on_pod_work=on_pod_work,
            verified_gpu_name="NVIDIA A40",
            clock=lambda: 0.0,
            sleep=lambda _seconds: None,
        )
    finally:
        client.close()

    assert len(calls) == 4
    assert seen["ready"]["ssh_port"] == 12346
    assert receipt["on_pod_result_present"] is True
    assert receipt["cleanup"]["delete_acknowledged"] is True
    assert receipt["cleanup"]["absence_proven"] is True
    assert receipt["cleanup"]["cleanup_failed"] is False
    assert budget.settled_usd == _session_spec().maximum_cost_usd
    assert budget.reserved_usd == Decimal("0")


def test_session_rejects_runtime_hours_exceeding_the_specs_own_ceiling() -> None:
    budget = LockedAuthorizedSpendBudget(campaign_id="rq-01-ceiling-test", hard_cap_usd="10")
    client = RunPodQualificationClient(
        api_key=FAKE_API_KEY, transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    try:
        with (
            pytest.raises(ContractError, match="exceeds the qualification spec's own ceiling"),
            QualificationSession(
                _session_spec(maximum_runtime_hours=Decimal("2")),
                client=client,
                budget=budget,
                maximum_runtime_hours=Decimal("3"),
            ),
        ):
            pass
    finally:
        client.close()
    # Rejected before any network call and before any reservation.
    assert budget.reserved_usd == Decimal("0")


# --------------------------------------------------------------------------
# Part B: orphan scan
# --------------------------------------------------------------------------


def test_orphan_scan_fails_loudly_on_leftover_qualification_pod() -> None:
    records = [{"name": "folynta-qualification-abandoned-1"}, {"name": "some-other-pod"}]
    with pytest.raises(QualificationSessionError, match="orphaned"):
        assert_no_orphaned_qualification_pods(records)


def test_orphan_scan_passes_on_clean_list() -> None:
    records = [{"name": "some-other-pod"}, {"name": "another-pod"}]
    assert_no_orphaned_qualification_pods(records)  # must not raise


# --------------------------------------------------------------------------
# Secret-leakage static check over the new driver module's own source
# --------------------------------------------------------------------------

# Reproduced from benchmark/tests/v6/test_runtime_qualification_secrets.py
# (that file's FORBIDDEN_PATTERN, itself reproduced from
# research/tavonel_recovery_eval_v1/runpod_qualification.py's _redacted_json).
_FORBIDDEN_PATTERN = re.compile(r"(?i)(bearer\s+|runpod_b|api[_-]?key|authorization)")
_FORBIDDEN_MARKERS = ("os.environ", "getenv", "GITHUB_TOKEN", "RUNPOD_API_KEY")


def test_driver_module_source_has_no_credential_shaped_pattern() -> None:
    source = Path(rqs_module.__file__).read_text(encoding="utf-8")
    matches = list(_FORBIDDEN_PATTERN.finditer(source))
    if matches:
        line_numbers = sorted({source.count("\n", 0, m.start()) + 1 for m in matches})
        pytest.fail(f"forbidden credential-shaped pattern at line(s) {line_numbers}")


def test_driver_module_never_reads_environment_or_a_named_secret() -> None:
    source = Path(rqs_module.__file__).read_text(encoding="utf-8")
    for marker in _FORBIDDEN_MARKERS:
        assert marker not in source, f"unexpected marker {marker!r} in run_qualification_session.py"


def test_driver_module_has_no_cli_entry_point() -> None:
    source = Path(rqs_module.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__"' not in source
    assert "import argparse" not in source
