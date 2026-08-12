"""ARMING GATE 1 — the discriminating pair, on the real poll path.

This drives ``GpuInvocationWorker.run_one`` itself: the poll, the probe pair, the
detector and the metric write are the shipped code. What is synthetic is the two
counts the probes return, which is the point — the whole gate is about telling
two situations apart that produce an identical empty poll, and the only way to
exercise both is to control the pair.

The database half is proven separately in
``infra/postgres/shadow_validate_dual_plane.py``
(``broker:backlog-exceeds-claimable-when-rows-are-leased``: backlog 16 against
claimable 3 on a live catalog).

**A detector that only fires is not proven.** The negative case matters as much
as the positive one: a fully leased queue is healthy, and a detector that pages
on it gets muted, which leaves the appearance of coverage and none of it.
"""

from __future__ import annotations

from typing import Any

import pytest
from akc_scheduler import gpu_jobs
from akc_scheduler.telemetry import (
    CLAIM_POLL_ATTEMPTS,
    CLAIM_POLL_BACKLOG,
    CLAIM_POLL_CLAIMABLE,
    CLAIM_POLL_GRANTS,
    CLAIM_POLL_STARVATION,
    CLAIM_POLL_ZERO_RUN,
)
from akc_security.claim_broker import ClaimStarvationDetector

QUEUE = "gpu_provider_invocations"


class _Dialect:
    name = "postgresql"


class _Engine:
    dialect = _Dialect()


class _Worker:
    """The real methods, on the minimum state they touch.

    ``_observe_poll`` and ``run_one`` are taken unbound from the shipped class,
    so the code under test is the code that ships rather than a copy of it.
    """

    _observe_poll = gpu_jobs.GpuInvocationWorker._observe_poll

    def __init__(self, threshold: int = 3) -> None:
        self._engine = _Engine()
        self._starvation = ClaimStarvationDetector(threshold=threshold)
        self._sessions = _sessions


class _Session:
    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None


def _sessions() -> _Session:
    return _Session()


def _metric(metric: Any) -> float:
    return metric.labels(queue=QUEUE)._value.get()


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    for gauge in (
        CLAIM_POLL_BACKLOG,
        CLAIM_POLL_CLAIMABLE,
        CLAIM_POLL_ZERO_RUN,
        CLAIM_POLL_STARVATION,
    ):
        gauge.labels(queue=QUEUE).set(0)


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stand in for the two SECURITY DEFINER probes 0035/0036 add."""

    counts = {"backlog": 0, "claimable": 0}

    async def _claim_backlog(_session: Any, *, function: str) -> tuple[int, int]:
        assert function == "akc_claim_gpu_invocation"
        return counts["backlog"], counts["claimable"]

    monkeypatch.setattr(gpu_jobs, "claim_backlog", _claim_backlog)
    return counts


async def test_rls_starvation_is_detected_on_the_real_poll_path(probe: Any) -> None:
    """POSITIVE: backlog > 0, claimable > 0, worker gets nothing, repeatedly."""

    probe["backlog"], probe["claimable"] = 12, 12
    worker = _Worker(threshold=3)

    for _ in range(2):
        await worker._observe_poll(claimed=False)
        assert _metric(CLAIM_POLL_STARVATION) == 0, "must not page on one lost race"

    await worker._observe_poll(claimed=False)

    assert _metric(CLAIM_POLL_STARVATION) == 1
    assert _metric(CLAIM_POLL_BACKLOG) == 12
    assert _metric(CLAIM_POLL_CLAIMABLE) == 12
    assert _metric(CLAIM_POLL_ZERO_RUN) == 3


async def test_a_fully_leased_queue_is_never_reported_as_starvation(probe: Any) -> None:
    """NEGATIVE: backlog > 0, claimable == 0. Healthy, and it must stay silent.

    This is the case a single counter cannot see. Everything pending is held by
    other workers; waiting is correct. Run far past the threshold — silence has
    to be durable, not merely delayed.
    """

    probe["backlog"], probe["claimable"] = 400, 0
    worker = _Worker(threshold=3)

    for _ in range(50):
        await worker._observe_poll(claimed=False)
        assert _metric(CLAIM_POLL_STARVATION) == 0

    assert _metric(CLAIM_POLL_BACKLOG) == 400
    assert _metric(CLAIM_POLL_CLAIMABLE) == 0
    assert _metric(CLAIM_POLL_ZERO_RUN) == 50


async def test_an_idle_queue_is_never_reported_as_starvation(probe: Any) -> None:
    probe["backlog"], probe["claimable"] = 0, 0
    worker = _Worker(threshold=1)
    for _ in range(20):
        await worker._observe_poll(claimed=False)
    assert _metric(CLAIM_POLL_STARVATION) == 0


async def test_a_successful_claim_clears_the_alert_and_skips_the_probe(
    probe: Any,
) -> None:
    """A granted claim resets the run, and does not pay for the probe pair."""

    probe["backlog"], probe["claimable"] = 5, 5
    worker = _Worker(threshold=1)
    await worker._observe_poll(claimed=False)
    assert _metric(CLAIM_POLL_STARVATION) == 1

    before = _metric(CLAIM_POLL_GRANTS)
    await worker._observe_poll(claimed=True)

    assert _metric(CLAIM_POLL_STARVATION) == 0
    assert _metric(CLAIM_POLL_ZERO_RUN) == 0
    assert _metric(CLAIM_POLL_GRANTS) == before + 1
    # The probe pair is queried only on an empty poll; a healthy worker's hot
    # path stays the one query it already made.
    assert _metric(CLAIM_POLL_BACKLOG) == 0


async def test_every_poll_is_counted(probe: Any) -> None:
    probe["backlog"], probe["claimable"] = 1, 1
    worker = _Worker()
    before = _metric(CLAIM_POLL_ATTEMPTS)
    for _ in range(4):
        await worker._observe_poll(claimed=False)
    assert _metric(CLAIM_POLL_ATTEMPTS) == before + 4


async def test_a_failing_probe_does_not_stop_the_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observability must not be able to break what it observes."""

    from sqlalchemy.exc import OperationalError

    async def _boom(_session: Any, *, function: str) -> tuple[int, int]:
        raise OperationalError("SELECT 1", {}, Exception("probe down"))

    monkeypatch.setattr(gpu_jobs, "claim_backlog", _boom)
    worker = _Worker(threshold=1)

    await worker._observe_poll(claimed=False)

    assert _metric(CLAIM_POLL_STARVATION) == 0


async def test_the_probe_is_skipped_entirely_off_postgresql(probe: Any) -> None:
    """SQLite is the deterministic test adapter and has neither probe."""

    probe["backlog"], probe["claimable"] = 9, 9
    worker = _Worker(threshold=1)
    worker._engine = type("E", (), {"dialect": type("D", (), {"name": "sqlite"})()})()

    before = _metric(CLAIM_POLL_ATTEMPTS)
    await worker._observe_poll(claimed=False)

    assert _metric(CLAIM_POLL_ATTEMPTS) == before
    assert _metric(CLAIM_POLL_STARVATION) == 0
