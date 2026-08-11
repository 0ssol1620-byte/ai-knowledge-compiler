"""The broker client's refusals, and Gate 1's idle-versus-starved distinction.

The database half is proven in ``infra/postgres/shadow_validate_dual_plane.py``
against real policies and a real ``SECURITY DEFINER`` function. What is asserted
here is the part that has to hold without a database: the client refuses a
broker whose return surface changed, and the detector never pages on an idle
queue however long it stays idle.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from akc_security.claim_broker import (
    BROKER_RETURN_COLUMNS,
    ClaimBrokerContractViolation,
    ClaimHealth,
    ClaimStarvationDetector,
    claim_backlog,
    claim_via_broker,
)
from akc_security.tenant_context import TenantContextMissing

NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
BROKER = "akc_claim_url_fetch_task"
WORKER = "url-fetcher-7"


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Mappings:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def first(self) -> dict[str, Any] | None:
        return self._row


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def mappings(self) -> _Mappings:
        return _Mappings(self._row)


class _FakeHandle:
    def __init__(self, row: dict[str, Any] | None = None, depth: int = 0) -> None:
        self.dialect = _Dialect("postgresql")
        self.statements: list[str] = []
        self.settings: dict[str, str] = {}
        self._row = row
        self._depth = depth

    def _record(self, statement: Any, parameters: dict[str, Any] | None) -> None:
        self.statements.append(str(statement))
        if parameters and "name" in parameters and "set_config" in str(statement):
            self.settings[str(parameters["name"])] = str(parameters.get("value", ""))

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> _Result:
        self._record(statement, parameters)
        return _Result(self._row)

    async def scalar(self, statement: Any, parameters: dict[str, Any] | None = None) -> Any:
        self._record(statement, parameters)
        # enter_control_plane_context probes the tenant GUC first.
        if "current_setting" in str(statement):
            return None
        return self._depth


def _grant(**overrides: Any) -> dict[str, Any]:
    row = {
        "claim_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "project_id": uuid.uuid4(),
        "lease_token": uuid.uuid4(),
        "lease_expires_at": NOW + timedelta(minutes=5),
    }
    row.update(overrides)
    return row


async def test_a_grant_becomes_a_claim_owned_by_this_worker() -> None:
    row = _grant()
    handle = _FakeHandle(row)

    claim = await claim_via_broker(
        handle, function=BROKER, worker_id=WORKER, lease_seconds=300
    )

    assert claim is not None
    assert claim.claim_id == row["claim_id"]
    assert claim.lease_token == row["lease_token"]
    # The broker granted this lease to this caller, so ownership is not a
    # comparison — it is who was handed the token.
    assert claim.claimed_by == WORKER


async def test_no_claimable_row_is_not_an_error() -> None:
    handle = _FakeHandle(None)
    assert await claim_via_broker(
        handle, function=BROKER, worker_id=WORKER, lease_seconds=300
    ) is None


async def test_a_broker_that_returns_more_than_five_columns_is_refused() -> None:
    """Founder decision F-1 fixed the surface. This is that decision, enforced."""

    handle = _FakeHandle(_grant(canonical_url="https://leaked.invalid/"))
    with pytest.raises(ClaimBrokerContractViolation):
        await claim_via_broker(
            handle, function=BROKER, worker_id=WORKER, lease_seconds=300
        )


async def test_a_broker_that_drops_a_column_is_refused() -> None:
    row = _grant()
    del row["project_id"]
    handle = _FakeHandle(row)
    with pytest.raises(ClaimBrokerContractViolation):
        await claim_via_broker(
            handle, function=BROKER, worker_id=WORKER, lease_seconds=300
        )


@pytest.mark.parametrize(
    "function",
    [
        "url_fetch_tasks",
        "akc_claim_url; DROP TABLE url_fetch_tasks; --",
        "akc_claim_url_fetch_task(1); SELECT 1",
        'akc_claim"_task',
        "",
    ],
)
async def test_a_function_name_that_is_not_a_broker_is_refused(function: str) -> None:
    """The identifier is interpolated, so it is not taken as free text."""

    handle = _FakeHandle(_grant())
    with pytest.raises(TenantContextMissing):
        await claim_via_broker(
            handle, function=function, worker_id=WORKER, lease_seconds=300
        )
    assert handle.statements == []


@pytest.mark.parametrize("lease_seconds", [0, -1])
async def test_a_nonsense_lease_is_refused(lease_seconds: int) -> None:
    handle = _FakeHandle(_grant())
    with pytest.raises(TenantContextMissing):
        await claim_via_broker(
            handle, function=BROKER, worker_id=WORKER, lease_seconds=lease_seconds
        )


async def test_a_missing_worker_identity_is_refused() -> None:
    handle = _FakeHandle(_grant())
    with pytest.raises(TenantContextMissing):
        await claim_via_broker(
            handle, function=BROKER, worker_id="", lease_seconds=300
        )


async def test_the_backlog_probes_declare_the_same_purpose() -> None:
    handle = _FakeHandle(depth=7)
    assert await claim_backlog(handle, function=BROKER) == (7, 7)
    assert handle.settings["app.control_plane"] == "claim"


async def test_the_return_surface_is_the_one_the_registry_names() -> None:
    assert BROKER_RETURN_COLUMNS == (
        "claim_id",
        "tenant_id",
        "project_id",
        "lease_token",
        "lease_expires_at",
    )


# --- Gate 1: four empty polls that mean four different things ----------------


def test_an_idle_queue_never_alerts_however_long_it_stays_idle() -> None:
    """The test that decides whether the detector survives contact with ops.

    A detector that eventually pages on an empty queue is one that gets muted,
    and a muted detector is worse than none — it is the appearance of coverage.
    """

    detector = ClaimStarvationDetector(threshold=3)
    for _ in range(500):
        observation = detector.observe(
            claimed=False, backlog_depth=0, claimable_depth=0
        )
        assert observation.health is ClaimHealth.IDLE
        assert observation.alert is False


def test_a_fully_leased_queue_never_alerts() -> None:
    """The case one probe cannot see, and the reason 0036 exists.

    Backlog is large and none of it is claimable because other workers hold it
    all. With only the claimable count this is indistinguishable from row-level
    security hiding the queue — and it would page forever on healthy operation.
    """

    detector = ClaimStarvationDetector(threshold=2)
    for _ in range(50):
        observation = detector.observe(
            claimed=False, backlog_depth=400, claimable_depth=0
        )
        assert observation.health is ClaimHealth.BLOCKED
        assert observation.alert is False


def test_rls_starvation_fires_a_real_alert() -> None:
    """The synthetic negative test the arming gate is written around.

    Claimable work exists — the privileged probe can see it — and this worker
    claims nothing, repeatedly. That is the only shape that pages.
    """

    detector = ClaimStarvationDetector(threshold=3)
    healths = [
        detector.observe(claimed=False, backlog_depth=12, claimable_depth=12).health
        for _ in range(3)
    ]
    assert healths == [
        ClaimHealth.CONTENDED,
        ClaimHealth.CONTENDED,
        ClaimHealth.STARVED,
    ]
    final = detector.observe(claimed=False, backlog_depth=12, claimable_depth=12)
    assert final.alert is True
    assert final.consecutive_zero_polls == 4


def test_losing_one_race_against_another_worker_is_not_starvation() -> None:
    detector = ClaimStarvationDetector(threshold=3)
    assert detector.observe(
        claimed=False, backlog_depth=1, claimable_depth=1
    ).health is ClaimHealth.CONTENDED
    assert detector.observe(
        claimed=True, backlog_depth=1, claimable_depth=0
    ).health is ClaimHealth.HEALTHY


def test_a_successful_claim_clears_the_run() -> None:
    detector = ClaimStarvationDetector(threshold=2)
    for _ in range(2):
        detector.observe(claimed=False, backlog_depth=5, claimable_depth=5)
    assert detector.consecutive_zero_polls == 2
    healthy = detector.observe(claimed=True, backlog_depth=5, claimable_depth=4)
    assert healthy.health is ClaimHealth.HEALTHY
    assert detector.consecutive_zero_polls == 0
    assert detector.observe(
        claimed=False, backlog_depth=5, claimable_depth=5
    ).health is ClaimHealth.CONTENDED


def test_a_queue_that_drains_to_empty_stops_alerting() -> None:
    """Starvation is a statement about now, not a latch."""

    detector = ClaimStarvationDetector(threshold=1)
    assert detector.observe(
        claimed=False, backlog_depth=3, claimable_depth=3
    ).alert is True
    assert detector.observe(
        claimed=False, backlog_depth=0, claimable_depth=0
    ).alert is False


def test_backlog_appearing_mid_run_does_not_backdate_the_alert() -> None:
    """An idle stretch followed by backlog is not instantly starvation."""

    detector = ClaimStarvationDetector(threshold=3)
    for _ in range(10):
        detector.observe(claimed=False, backlog_depth=0, claimable_depth=0)
    observation = detector.observe(claimed=False, backlog_depth=4, claimable_depth=4)
    assert observation.health is ClaimHealth.STARVED, (
        "ten empty polls already exceeded the threshold, so the first poll that "
        "sees claimable backlog is the eleventh consecutive failure to claim — "
        "the counter measures this worker's inability to claim, not how long "
        "backlog has existed"
    )


def test_a_threshold_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one poll"):
        ClaimStarvationDetector(threshold=0)
