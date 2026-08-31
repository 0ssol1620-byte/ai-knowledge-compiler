"""Bounded qualification-pod session driver: budget lock + watchdog + teardown.

``qualification_pod.py`` supplies a create / verify_ready / get / delete
client for exactly one already-known pod, but nothing there enforces two
safety properties this round needs:

1. ``AuthorizedSpendBudget.reserve()`` / ``settle()`` / ``release()`` are
   unlocked check-then-act over plain dicts -- correct for a single session,
   but a real race if two sessions ever reserve concurrently against the
   same instance.
2. ``maximum_runtime_hours`` only ever fed a cost-ceiling calculation; nothing
   turned it into an actual wall-clock deadline that forces teardown, and
   ``delete()`` never verified the pod was actually gone afterward.

This module supplies both, self-contained. It deliberately does not import
``infra.runpod.v6.confirmatory_pod_controller`` -- a different, out-of-scope
module for a later, separate, not-yet-approved phase -- even though the
create -> ready -> teardown-in-``finally`` shape here rhymes with the
lifecycle pattern there.

Credential handling: this module never creates, fetches, holds, or logs a
raw RunPod container-registry credential. A caller obtains a
``container_registry_auth_id`` out of band -- by calling RunPod's
``create-container-registry-auth`` API/MCP tool exactly once with the real
username/token, which returns an opaque resource ID -- and passes only that
ID in here as a field already set on the ``QualificationPodSpec`` it
supplies. No code path below creates, stores, reads from the environment, or
prints any credential value; only that opaque ID ever moves through this
module.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any, Final

from benchmark.v6.contracts import ContractError
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget, BudgetReservation
from infra.runpod.v6.qualification_pod import (
    QualificationPodError,
    QualificationPodSpec,
    RunPodQualificationClient,
)

_ABSENCE_STATUS_RE: Final = re.compile(r"status (\d+)")
_ORPHAN_NAME_RE: Final = re.compile(r"^folynta-qualification-")


class QualificationSessionError(ContractError):
    """Watchdog timeout, unproven pod absence, or other session-level failure."""


# --------------------------------------------------------------------------
# Locked budget
# --------------------------------------------------------------------------


class LockedAuthorizedSpendBudget(AuthorizedSpendBudget):
    """``AuthorizedSpendBudget``, with every call serialized behind one lock.

    ``authorized_budget.py`` itself is never modified -- this wraps it from
    the outside by subclassing and re-acquiring a lock owned here around each
    call to the parent implementation. One instance of this class should back
    one qualification campaign for the life of the process (e.g.
    ``LockedAuthorizedSpendBudget(campaign_id="rq-01",
    hard_cap_usd=Decimal("50"))``); that construction choice belongs to the
    caller, not to this module.

    The lock is a ``threading.RLock`` and must stay one. The parent's
    ``reserve()`` reads ``self.remaining_usd``, and ``remaining_usd`` reads
    ``self.reserved_usd``/``self.settled_usd`` -- attribute lookups that
    dispatch back through *this* subclass, because ``self`` is a
    ``LockedAuthorizedSpendBudget``. So one outer ``reserve()`` re-enters the
    overridden properties on the same thread while already holding the lock.
    A plain ``threading.Lock`` has no owner and would block that thread
    against itself forever; ``RLock`` tracks the owning thread and a
    recursion count, so the re-entry is a counter bump. Cross-thread mutual
    exclusion is identical either way -- a second thread still blocks at the
    outermost acquire -- so the check-then-act in the parent's ``reserve()``
    stays atomic and the hard cap cannot be over-committed.
    """

    def __init__(self, *, campaign_id: str, hard_cap_usd: Decimal | str) -> None:
        super().__init__(campaign_id=campaign_id, hard_cap_usd=hard_cap_usd)
        self._session_lock = threading.RLock()

    @property
    def reserved_usd(self) -> Decimal:
        with self._session_lock:
            return super().reserved_usd

    @property
    def settled_usd(self) -> Decimal:
        with self._session_lock:
            return super().settled_usd

    @property
    def remaining_usd(self) -> Decimal:
        with self._session_lock:
            return super().remaining_usd

    def reserve(
        self, *, allocation_id: str, maximum_cost_usd: Decimal | str
    ) -> BudgetReservation:
        with self._session_lock:
            return super().reserve(allocation_id=allocation_id, maximum_cost_usd=maximum_cost_usd)

    def release(self, allocation_id: str) -> None:
        with self._session_lock:
            super().release(allocation_id)

    def settle(self, *, allocation_id: str, actual_cost_usd: Decimal | str) -> None:
        with self._session_lock:
            super().settle(allocation_id=allocation_id, actual_cost_usd=actual_cost_usd)

    def report(self) -> dict[str, object]:
        with self._session_lock:
            return super().report()


# --------------------------------------------------------------------------
# Watchdog-checked readiness poll
# --------------------------------------------------------------------------


def _poll_until_ready(
    spec: QualificationPodSpec,
    client: RunPodQualificationClient,
    *,
    pod_id: str,
    deadline_monotonic: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    poll_interval_seconds: float,
    max_poll_attempts: int,
    verified_gpu_name: str | None,
) -> dict[str, Any]:
    """Poll ``client.verify_ready`` until it succeeds or the deadline passes.

    ``max_poll_attempts`` is a hard safety bound on top of the deadline check
    so a misconfigured ``clock``/deadline pair cannot spin forever even if
    the deadline comparison itself is somehow never satisfied.
    """

    attempts = 0
    last_error: QualificationPodError | None = None
    while attempts < max_poll_attempts:
        attempts += 1
        try:
            return client.verify_ready(spec, pod_id=pod_id, verified_gpu_name=verified_gpu_name)
        except QualificationPodError as exc:
            last_error = exc
        if clock() >= deadline_monotonic:
            raise QualificationSessionError(
                "qualification pod watchdog deadline exceeded while waiting for readiness"
            ) from last_error
        sleep(poll_interval_seconds)
    raise QualificationSessionError(
        "qualification pod readiness poll exhausted its maximum attempt bound"
    ) from last_error


# --------------------------------------------------------------------------
# Delete -> get -> expect-404 absence proof
# --------------------------------------------------------------------------


def _absence_status_code(error: QualificationPodError) -> int | None:
    match = _ABSENCE_STATUS_RE.search(str(error))
    return int(match.group(1)) if match else None


def _delete_and_prove_absence(client: RunPodQualificationClient, pod_id: str) -> dict[str, Any]:
    """Delete ``pod_id``, then require a 404 GET as loud proof it is gone.

    A non-404 error response, or a ``get()`` that succeeds (the pod is still
    present), is never swallowed -- both raise :class:`QualificationSessionError`
    rather than being treated as an implicit pass.
    """

    client.delete(pod_id)
    try:
        client.get(pod_id)
    except QualificationPodError as exc:
        status = _absence_status_code(exc)
        if status != 404:
            raise QualificationSessionError(
                f"qualification pod absence is unproven after delete: {exc}"
            ) from exc
        return {"pod_id": pod_id, "observation": "GET_404_NOT_FOUND"}
    else:
        raise QualificationSessionError(
            "qualification pod still present after delete; absence is unproven"
        )


def _release_if_reserved(budget: LockedAuthorizedSpendBudget, allocation_id: str) -> str:
    """Best-effort release of a reservation that may or may not exist.

    ``RunPodQualificationClient.create()`` calls ``budget.reserve()`` as its
    very first act, before any network I/O. If ``create()`` later raises --
    e.g. the name/GPU/rate drift checks it does internally, each of which it
    already handles by calling its own ``delete()`` before raising -- the
    reservation it made is still outstanding, but this driver never
    observed the create receipt to learn the allocation id from it. The
    allocation id is always ``spec.allocation_id`` regardless, so this
    releases it if present and treats "no such reservation" (``create()``
    failed *before* reserving -- e.g. the hard cap was already exhausted) as
    an expected no-op rather than an error.
    """

    try:
        budget.release(allocation_id)
        return "released"
    except ContractError as exc:
        if "unknown budget reservation" in str(exc):
            return "not_reserved"
        raise


def _coerce_runtime_hours(value: Decimal | str, *, ceiling: Decimal) -> Decimal:
    hours = value if isinstance(value, Decimal) else Decimal(str(value))
    if hours <= 0:
        raise ContractError("session maximum_runtime_hours must be positive")
    if hours > ceiling:
        raise ContractError(
            "session maximum_runtime_hours exceeds the qualification spec's own ceiling"
        )
    return hours


# --------------------------------------------------------------------------
# Session: create -> verify_ready -> [caller's on-pod work] -> teardown
# --------------------------------------------------------------------------


class QualificationSession:
    """Context manager guaranteeing unconditional teardown of one pod.

    ``__enter__`` performs budget-gated ``create`` and watchdog-checked
    ``verify_ready``, then returns the readiness receipt (pod connection
    info) for the caller's own on-pod work -- SSH exec and whatever it runs
    there live entirely outside this module. ``__exit__`` always tears the
    pod down (delete -> 404-absence-proof -> budget settle-or-release),
    regardless of how the ``with`` block exits: success, an exception raised
    by the caller's on-pod work, or the watchdog deadline having elapsed
    while that work ran. A cleanup failure is recorded and raised rather
    than swallowed, and it never silently hides the caller's own exception
    (Python's exception chaining preserves both).

    Known limitation: the watchdog can only be checked *before* and *after*
    the caller's on-pod work runs (and inside the readiness poll loop) --
    this module cannot preempt a hung, synchronous on-pod callback mid-flight
    without a separate thread/timeout mechanism, which is out of scope here.
    """

    def __init__(
        self,
        spec: QualificationPodSpec,
        *,
        client: RunPodQualificationClient,
        budget: LockedAuthorizedSpendBudget,
        maximum_runtime_hours: Decimal | str,
        verified_gpu_name: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        poll_interval_seconds: float = 5.0,
        max_poll_attempts: int = 1000,
    ) -> None:
        self.spec = spec
        self.client = client
        self.budget = budget
        self.maximum_runtime_hours = maximum_runtime_hours
        self.verified_gpu_name = verified_gpu_name
        self.clock = clock
        self.sleep = sleep
        self.poll_interval_seconds = poll_interval_seconds
        self.max_poll_attempts = max_poll_attempts

        self.pod_id: str | None = None
        self.create_receipt: dict[str, Any] | None = None
        self.ready_receipt: dict[str, Any] | None = None
        self.cleanup: dict[str, Any] = {
            "delete_acknowledged": False,
            "absence_proven": False,
            "absence_observation": None,
            "dangling_reservation_outcome": None,
            "cleanup_failed": False,
            "cleanup_error": None,
        }
        self._deadline_monotonic: float | None = None
        self._torn_down = False

    def __enter__(self) -> dict[str, Any]:
        runtime_hours = _coerce_runtime_hours(
            self.maximum_runtime_hours, ceiling=self.spec.maximum_runtime_hours
        )
        self._deadline_monotonic = self.clock() + float(runtime_hours) * 3600.0
        try:
            self.create_receipt = self.client.create(self.spec, budget=self.budget)
            self.pod_id = self.create_receipt["pod_id"]
            self.ready_receipt = _poll_until_ready(
                self.spec,
                self.client,
                pod_id=self.pod_id,
                deadline_monotonic=self._deadline_monotonic,
                clock=self.clock,
                sleep=self.sleep,
                poll_interval_seconds=self.poll_interval_seconds,
                max_poll_attempts=self.max_poll_attempts,
                verified_gpu_name=self.verified_gpu_name,
            )
        except BaseException:
            self._teardown()
            raise
        return self.ready_receipt

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> None:
        watchdog_exceeded = (
            self._deadline_monotonic is not None and self.clock() >= self._deadline_monotonic
        )
        self._teardown()
        if watchdog_exceeded and exc is None:
            raise QualificationSessionError(
                "qualification session watchdog deadline exceeded during on-pod work"
            )
        # Returning None (rather than True) never suppresses the caller's
        # own exception.

    def _teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True

        if self.pod_id is not None:
            try:
                self.cleanup["absence_observation"] = _delete_and_prove_absence(
                    self.client, self.pod_id
                )
                self.cleanup["delete_acknowledged"] = True
                self.cleanup["absence_proven"] = True
            except Exception as exc:  # cleanup must never hide its own failure
                self.cleanup["cleanup_failed"] = True
                self.cleanup["cleanup_error"] = f"delete/absence: {exc}"

            try:
                if not self.cleanup["cleanup_failed"]:
                    self.budget.settle(
                        allocation_id=self.spec.allocation_id,
                        actual_cost_usd=self.spec.maximum_cost_usd,
                    )
                else:
                    self.budget.release(self.spec.allocation_id)
            except Exception as exc:  # see comment above
                self.cleanup["cleanup_failed"] = True
                previous = self.cleanup["cleanup_error"]
                budget_error = f"budget: {exc}"
                self.cleanup["cleanup_error"] = (
                    f"{previous}; {budget_error}" if previous else budget_error
                )
        else:
            # create() never returned a receipt -- it may have failed before
            # reserving (no-op to release) or after (a dangling reservation
            # this driver never directly observed). Either way, resolve it.
            try:
                self.cleanup["dangling_reservation_outcome"] = _release_if_reserved(
                    self.budget, self.spec.allocation_id
                )
            except Exception as exc:
                self.cleanup["cleanup_failed"] = True
                self.cleanup["cleanup_error"] = f"budget: {exc}"

        if self.cleanup["cleanup_failed"]:
            raise QualificationSessionError(f"TEARDOWN_FAILED: {self.cleanup['cleanup_error']}")

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "folynta.runpod-qualification-session.v1",
            "pod_id": self.pod_id,
            "create_receipt": self.create_receipt,
            "ready_receipt": self.ready_receipt,
            "cleanup": self.cleanup,
        }


def run_qualification_session(
    spec: QualificationPodSpec,
    *,
    client: RunPodQualificationClient,
    budget: LockedAuthorizedSpendBudget,
    maximum_runtime_hours: Decimal | str,
    on_pod_work: Callable[[dict[str, Any]], Any] | None = None,
    verified_gpu_name: str | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    poll_interval_seconds: float = 5.0,
    max_poll_attempts: int = 1000,
) -> dict[str, Any]:
    """Callback-style convenience wrapper around :class:`QualificationSession`.

    Equivalent to::

        with QualificationSession(...) as ready_receipt:
            result = on_pod_work(ready_receipt) if on_pod_work else None

    but returns a single receipt dict instead of requiring the caller to
    manage the context manager directly. Teardown is unconditional either
    way -- this adds no additional safety, only convenience.
    """

    session = QualificationSession(
        spec,
        client=client,
        budget=budget,
        maximum_runtime_hours=maximum_runtime_hours,
        verified_gpu_name=verified_gpu_name,
        clock=clock,
        sleep=sleep,
        poll_interval_seconds=poll_interval_seconds,
        max_poll_attempts=max_poll_attempts,
    )
    on_pod_result_present = False
    with session as ready_receipt:
        if on_pod_work is not None:
            on_pod_work(ready_receipt)
            on_pod_result_present = True
    receipt = session.receipt()
    receipt["on_pod_result_present"] = on_pod_result_present
    return receipt


# --------------------------------------------------------------------------
# Account-wide orphan scan
# --------------------------------------------------------------------------


def assert_no_orphaned_qualification_pods(pod_records: Iterable[Mapping[str, Any]]) -> None:
    """Assert none of the given pod records is a leftover qualification pod.

    Gap, stated plainly: ``RunPodQualificationClient`` exposes only
    ``create``/``verify_ready``/``get``/``delete``/``close`` for one
    already-known pod id -- it has no account-wide "list every pod"
    capability, and this module does not invent one. The caller supplies the
    records. Two existing sources already produce them:
    ``infra.runpod.v6.pod_client.RunPodPodClient.list_pods()`` (a ``GET /pods``
    that ``pod_cli.py`` already drives as its ``inventory`` operation), or
    the RunPod MCP ``list-pods`` tool. Wiring either one into this round's
    teardown path is a deliberate non-goal here -- this function only
    asserts that none of the records it is handed matches the
    ``folynta-qualification-`` name prefix this round's pods use, so nothing
    calls it automatically and an orphan scan happens only when a caller
    chooses to run one.
    """

    orphans = sorted(
        str(record.get("name", ""))
        for record in pod_records
        if _ORPHAN_NAME_RE.match(str(record.get("name", "")))
    )
    if orphans:
        raise QualificationSessionError(
            f"orphaned qualification pod(s) still present on the account: {orphans}"
        )


__all__ = [
    "LockedAuthorizedSpendBudget",
    "QualificationSession",
    "QualificationSessionError",
    "assert_no_orphaned_qualification_pods",
    "run_qualification_session",
]
