"""Exactly-three RunPod coordinator with crash-safe dispatch accounting."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from infra.runpod.v6.client import (
    BillingHistory,
    BillingQuery,
    DryRunReceipt,
    EndpointSummary,
    ProviderAbsenceReceipt,
    QueueJob,
    RunPodV2Client,
    make_idempotency_key,
)
from infra.runpod.v6.orchestration import SpendGuard, SpendState

from .contracts import ContractError, canonical_sha256, require_sha256
from .ledger import EvidenceLedger, LedgerEvent
from .repeats import EXACT_REPEAT_COUNT, RepeatRun, validate_repeat_plan

_TERMINAL_JOB_STATES: Final = frozenset(
    {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}
)
_BILLABLE_FINAL_STATES: Final = frozenset(
    {"verified", "authority_verified", "cross_model_verified", "auto_repaired"}
)
_NON_BILLABLE_FINAL_STATES: Final = frozenset({"unresolved", "quarantined", "failed"})
_PROVIDER_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class AmbiguousDispatchError(ContractError):
    """A provider write may have succeeded but has no durable acknowledgement."""


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    logical_work_id: str
    idempotency_key: str
    input_sha256: str
    provider_job_id: str | None
    status: str
    recovered: bool
    dry_run_receipt_sha256: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "logical_work_id": self.logical_work_id,
            "idempotency_key": self.idempotency_key,
            "input_sha256": self.input_sha256,
            "provider_job_id": self.provider_job_id,
            "status": self.status,
            "recovered": self.recovered,
            "dry_run_receipt_sha256": self.dry_run_receipt_sha256,
        }


class ExactThreeRunPodCoordinator:
    """Bind one exact-three repeat cohort to one endpoint and evidence ledger.

    Provider writes are preceded by an immutable intent.  If a process dies
    after the write but before its acknowledgement is recorded, the next resume
    hard-stops instead of resubmitting the paid job.
    """

    def __init__(
        self,
        *,
        runs: Sequence[RepeatRun],
        endpoint_id: str,
        client: RunPodV2Client,
        ledger: EvidenceLedger,
        spend_guard: SpendGuard,
    ) -> None:
        validation = validate_repeat_plan(runs)
        self.runs = tuple(sorted(runs, key=lambda item: item.repeat_index))
        self.cohort_id = self.runs[0].cohort_id
        self.endpoint_id = endpoint_id
        if not _PROVIDER_ID_RE.fullmatch(endpoint_id):
            raise ContractError("coordinator endpoint_id is not a valid provider resource ID")
        self.client = client
        self.ledger = ledger
        self.spend_guard = spend_guard
        self.plan_sha256 = str(validation["plan_sha256"])
        self.run_tag = make_run_tag(self.runs)
        if ledger.cohort_id != self.cohort_id or ledger.run_tag != self.run_tag:
            raise ContractError("coordinator cohort/run tag differs from its evidence ledger")
        if spend_guard.run_id != self.cohort_id:
            raise ContractError("SpendGuard run_id must equal the exact-three cohort_id")
        report = spend_guard.report()
        if any(
            report[key] != 0
            for key in ("dispatch_count", "accepted_count", "settled_work_count")
        ) or report["provider_cost_usd"] != "0":
            raise ContractError("SpendGuard must be empty; coordinator restores it from the ledger")
        self._freeze_or_verify_plan()
        self._restore_spend_guard()
        self._validate_dispatch_cardinality()

    def dispatch_exact_three(
        self, inputs_by_run: Mapping[str, Mapping[str, object]]
    ) -> tuple[DispatchOutcome, ...]:
        expected_ids = {run.run_id for run in self.runs}
        if set(inputs_by_run) != expected_ids:
            raise ContractError("dispatch inputs must cover exactly the three planned run IDs")
        if any(not inputs_by_run[run.run_id] for run in self.runs):
            raise ContractError("every exact-three run requires a non-empty input object")
        self._require_not_stopped()
        if self.client.execute:
            return self._dispatch_execute(inputs_by_run)
        dispatches = self._dispatch_events_by_work()
        intents = self._intent_events_by_key()
        outcomes: list[DispatchOutcome] = []
        for run in self.runs:
            input_payload = inputs_by_run[run.run_id]
            if not input_payload:
                raise ContractError(f"{run.run_id} input must be a non-empty object")
            input_sha = canonical_sha256(
                {
                    "logical_work_id": run.run_id,
                    "candidate_id": run.candidate_id,
                    "benchmark_id": run.benchmark_id,
                    "environment_sha256": run.environment_sha256,
                    "input": dict(input_payload),
                }
            )
            idempotency_key = make_idempotency_key(
                {
                    "run_tag": self.run_tag,
                    "logical_work_id": run.run_id,
                    "input_sha256": input_sha,
                }
            )
            existing = dispatches.get(run.run_id)
            if existing is not None:
                if (
                    existing.payload.get("idempotency_key") != idempotency_key
                    or existing.payload.get("input_sha256") != input_sha
                ):
                    self._hard_stop("RESUME_INPUT_OR_IDEMPOTENCY_DRIFT")
                    raise ContractError(
                        "resumed input differs from the dispatched immutable intent"
                    )
                outcomes.append(_outcome_from_dispatch(existing, recovered=True))
                continue
            intent = intents.get(idempotency_key)
            if intent is not None:
                self._hard_stop("AMBIGUOUS_PROVIDER_DISPATCH")
                raise AmbiguousDispatchError(
                    "dispatch intent has no provider acknowledgement; reconcile before resuming"
                )
            result = self.client.run_job(
                self.endpoint_id,
                input_payload,
                run_tag=self.run_tag,
                idempotency_key=idempotency_key,
            )
            if isinstance(result, DryRunReceipt):
                receipt = result.to_dict()
                receipt_sha = str(receipt["receipt_sha256"])
                self._append_dry_run_once(
                    logical_work_id=run.run_id,
                    idempotency_key=idempotency_key,
                    input_sha256=input_sha,
                    receipt_sha256=receipt_sha,
                )
                outcomes.append(
                    DispatchOutcome(
                        logical_work_id=run.run_id,
                        idempotency_key=idempotency_key,
                        input_sha256=input_sha,
                        provider_job_id=None,
                        status="DRY_RUN",
                        recovered=False,
                        dry_run_receipt_sha256=receipt_sha,
                    )
                )
                continue

        if len(outcomes) != EXACT_REPEAT_COUNT:
            self._hard_stop("EXACT_THREE_DRY_RUN_CARDINALITY_VIOLATION")
            raise ContractError("dry-run planning did not produce exactly three outcomes")
        return tuple(outcomes)

    def _dispatch_execute(
        self, inputs_by_run: Mapping[str, Mapping[str, object]]
    ) -> tuple[DispatchOutcome, ...]:
        dispatches = self._dispatch_events_by_work()
        intents = self._intent_events_by_key()
        outcomes: list[DispatchOutcome] = []
        for run in self.runs:
            input_payload = inputs_by_run[run.run_id]
            input_sha = canonical_sha256(
                {
                    "logical_work_id": run.run_id,
                    "candidate_id": run.candidate_id,
                    "benchmark_id": run.benchmark_id,
                    "environment_sha256": run.environment_sha256,
                    "input": dict(input_payload),
                }
            )
            idempotency_key = make_idempotency_key(
                {
                    "run_tag": self.run_tag,
                    "logical_work_id": run.run_id,
                    "input_sha256": input_sha,
                }
            )
            existing = dispatches.get(run.run_id)
            if existing is not None:
                if (
                    existing.payload.get("idempotency_key") != idempotency_key
                    or existing.payload.get("input_sha256") != input_sha
                ):
                    self._hard_stop("RESUME_INPUT_OR_IDEMPOTENCY_DRIFT")
                    raise ContractError("resumed input differs from an acknowledged dispatch")
                outcomes.append(_outcome_from_dispatch(existing, recovered=True))
                continue
            if idempotency_key in intents:
                self._hard_stop("AMBIGUOUS_PROVIDER_DISPATCH")
                raise AmbiguousDispatchError(
                    "dispatch intent has no provider acknowledgement; reconcile before resuming"
                )
            self.ledger.append(
                "job.dispatch.intent.v1",
                {
                    "logical_work_id": run.run_id,
                    "repeat_index": run.repeat_index,
                    "idempotency_key": idempotency_key,
                    "input_sha256": input_sha,
                    "environment_sha256": run.environment_sha256,
                    "endpoint_id": self.endpoint_id,
                },
            )
            try:
                result = self.client.run_job(
                    self.endpoint_id,
                    input_payload,
                    run_tag=self.run_tag,
                    idempotency_key=idempotency_key,
                )
            except Exception as exc:
                self.ledger.append(
                    "job.dispatch.ambiguous.v1",
                    {
                        "logical_work_id": run.run_id,
                        "idempotency_key": idempotency_key,
                        "input_sha256": input_sha,
                        "error_class": type(exc).__name__,
                    },
                )
                self._hard_stop("AMBIGUOUS_PROVIDER_DISPATCH")
                raise
            if not isinstance(result, QueueJob):
                self._hard_stop("EXECUTE_MODE_RETURNED_DRY_RUN_RECEIPT")
                raise ContractError("execute-mode queue call returned no provider job")
            self.spend_guard.dispatch(
                idempotency_key=idempotency_key,
                logical_work_id=run.run_id,
                provider_job_id=result.job_id,
                attempt_kind="primary",
            )
            event = self.ledger.append(
                "job.dispatched.v1",
                {
                    "logical_work_id": run.run_id,
                    "repeat_index": run.repeat_index,
                    "idempotency_key": idempotency_key,
                    "input_sha256": input_sha,
                    "provider_job_id": result.job_id,
                    "initial_status": result.status,
                    "provider_response_sha256": result.response_sha256,
                    "endpoint_id": self.endpoint_id,
                },
            )
            outcomes.append(_outcome_from_dispatch(event, recovered=False))
        if len(self._dispatch_events_by_work()) != EXACT_REPEAT_COUNT:
            self._hard_stop("EXACT_THREE_DISPATCH_CARDINALITY_VIOLATION")
            raise ContractError("provider dispatch did not settle at exactly three primary jobs")
        return tuple(outcomes)

    def refresh_statuses(self) -> tuple[QueueJob | DryRunReceipt, ...]:
        self._require_not_stopped()
        dispatches = self._dispatch_events_by_work()
        if len(dispatches) != EXACT_REPEAT_COUNT:
            raise ContractError("status refresh requires three acknowledged dispatches")
        results: list[QueueJob | DryRunReceipt] = []
        for run in self.runs:
            dispatch = dispatches[run.run_id]
            provider_job_id = _event_string(dispatch, "provider_job_id")
            result = self.client.job_status(self.endpoint_id, provider_job_id)
            results.append(result)
            if isinstance(result, QueueJob):
                self.ledger.append(
                    "job.status.observed.v1",
                    {
                        "logical_work_id": run.run_id,
                        "provider_job_id": provider_job_id,
                        "status": result.status,
                        "output_sha256": result.output_sha256,
                        "provider_response_sha256": result.response_sha256,
                    },
                )
        return tuple(results)

    def accept_completed(
        self,
        *,
        logical_work_id: str,
        job: QueueJob,
        validation_receipt_sha256: str,
        final_integrity_state: str,
        user_charge_usd: Decimal | str,
    ) -> None:
        self._require_not_stopped()
        require_sha256(validation_receipt_sha256, "validation_receipt_sha256")
        if final_integrity_state not in _BILLABLE_FINAL_STATES:
            raise ContractError("only verified final states can be accepted and charged")
        dispatch = self._dispatch_events_by_work().get(logical_work_id)
        if dispatch is None or _event_string(dispatch, "provider_job_id") != job.job_id:
            raise ContractError("completed job is not the dispatch for this logical work")
        if job.endpoint_id != self.endpoint_id or job.status != "COMPLETED":
            raise ContractError("only a COMPLETED job from the bound endpoint may be accepted")
        output_sha = job.output_sha256
        if output_sha is None:
            raise ContractError("completed job has no immutable output")
        acceptance_payload = {
            "logical_work_id": logical_work_id,
            "provider_job_id": job.job_id,
            "output_sha256": output_sha,
            "validation_receipt_sha256": validation_receipt_sha256,
            "final_integrity_state": final_integrity_state,
        }
        accepted = next(
            (
                event
                for event in self.ledger.iter_type("job.accepted.v1")
                if event.payload.get("logical_work_id") == logical_work_id
            ),
            None,
        )
        if accepted is not None and dict(accepted.payload) != acceptance_payload:
            self._hard_stop("DUPLICATE_ACCEPTANCE_DRIFT")
            raise ContractError("logical work already has a different accepted result")
        if accepted is None:
            self.spend_guard.accept_verified_result(
                logical_work_id=logical_work_id, provider_job_id=job.job_id
            )
            self.ledger.append("job.accepted.v1", acceptance_payload)

        amount = _money(user_charge_usd)
        existing_charge = next(
            (
                event
                for event in self.ledger.iter_type("user.charge.settled.v1")
                if event.payload.get("logical_work_id") == logical_work_id
            ),
            None,
        )
        if existing_charge is not None:
            same_charge = (
                existing_charge.payload.get("provider_job_id") == job.job_id
                and existing_charge.payload.get("final_integrity_state")
                == final_integrity_state
                and _money(_event_string(existing_charge, "amount_usd")) == amount
                and existing_charge.payload.get("accepted_only") is True
            )
            if same_charge:
                return
            self._hard_stop("DUPLICATE_USER_CHARGE_DRIFT")
            raise ContractError("logical work already has a different user charge")
        self.spend_guard.settle_user_charge(
            logical_work_id=logical_work_id,
            amount_usd=amount,
            final_integrity_state=final_integrity_state,
        )
        self.ledger.append(
            "user.charge.settled.v1",
            {
                "logical_work_id": logical_work_id,
                "provider_job_id": job.job_id,
                "amount_usd": str(amount),
                "final_integrity_state": final_integrity_state,
                "accepted_only": True,
            },
        )

    def finalize_nonbillable(
        self,
        *,
        logical_work_id: str,
        final_integrity_state: str,
        failure_receipt_sha256: str,
    ) -> None:
        self._require_not_stopped()
        if final_integrity_state not in _NON_BILLABLE_FINAL_STATES:
            raise ContractError("nonbillable finalization requires unresolved/quarantined/failed")
        require_sha256(failure_receipt_sha256, "failure_receipt_sha256")
        payload = {
            "logical_work_id": logical_work_id,
            "amount_usd": "0",
            "final_integrity_state": final_integrity_state,
            "failure_receipt_sha256": failure_receipt_sha256,
        }
        existing = next(
            (
                event
                for event in self.ledger.iter_type("user.nonbillable.finalized.v1")
                if event.payload.get("logical_work_id") == logical_work_id
            ),
            None,
        )
        if existing is not None:
            if dict(existing.payload) == payload:
                return
            self._hard_stop("NONBILLABLE_FINALIZATION_DRIFT")
            raise ContractError("logical work already has a different nonbillable finalization")
        self.spend_guard.settle_user_charge(
            logical_work_id=logical_work_id,
            amount_usd="0",
            final_integrity_state=final_integrity_state,
        )
        self.ledger.append("user.nonbillable.finalized.v1", payload)

    def collect_provider_billing(
        self, query: BillingQuery, *, cause: str = "planned"
    ) -> BillingHistory | DryRunReceipt:
        result = self.client.billing_history(query)
        if isinstance(result, BillingHistory):
            self.record_provider_billing(result, cause=cause)
        return result

    def record_provider_billing(self, history: BillingHistory, *, cause: str) -> None:
        self._require_not_stopped()
        require_sha256(history.response_sha256, "billing.response_sha256")
        if any(
            event.payload.get("provider_response_sha256") == history.response_sha256
            for event in self.ledger.iter_type("provider.billing.recorded.v1")
        ):
            self._hard_stop("DUPLICATE_PROVIDER_BILLING_RECEIPT")
            raise ContractError("provider billing receipt was already recorded")
        state = self.spend_guard.record_provider_cost(
            amount_usd=history.provider_total_usd, cause=cause
        )
        self.ledger.append(
            "provider.billing.recorded.v1",
            {
                "endpoint_id": self.endpoint_id,
                "provider_amount_usd": str(history.provider_total_usd),
                "provider_response_sha256": history.response_sha256,
                "cause": cause,
                "user_charge_usd": "0",
                "spend_state": state.value,
            },
        )
        if state is SpendState.HARD_STOP_RUNAWAY:
            self._hard_stop("PROVIDER_COST_RUNAWAY")

    def cleanup_endpoint(
        self,
        *,
        artifacts_uploaded: bool,
        evidence_receipt_sha256: str,
        grace_window_elapsed: bool,
    ) -> ProviderAbsenceReceipt | DryRunReceipt:
        require_sha256(evidence_receipt_sha256, "evidence_receipt_sha256")
        if not artifacts_uploaded or not grace_window_elapsed:
            raise ContractError("cleanup requires uploaded artifacts and elapsed grace window")
        terminal = self.ledger.latest("endpoint.provider_absent.v1")
        if terminal is not None:
            return self._absence_from_event(terminal, evidence_receipt_sha256)
        self._require_not_stopped()
        nonterminal = {
            logical: status
            for logical, status in self._latest_job_statuses().items()
            if status not in _TERMINAL_JOB_STATES
        }
        if nonterminal:
            raise ContractError("cleanup cannot drain while acknowledged jobs are non-terminal")
        if not self.client.execute:
            drain_key = make_idempotency_key({"run_tag": self.run_tag, "action": "drain"})
            drained = self.client.drain_endpoint(
                self.endpoint_id, run_tag=self.run_tag, idempotency_key=drain_key
            )
            if not isinstance(drained, DryRunReceipt):
                raise ContractError("dry-run cleanup unexpectedly reached the provider")
            if self.ledger.latest("endpoint.cleanup.dry_run.v1") is None:
                self.ledger.append(
                    "endpoint.cleanup.dry_run.v1",
                    {
                        "endpoint_id": self.endpoint_id,
                        "action": "drain-delete-verify-absence",
                        "request_receipt_sha256": drained.to_dict()["receipt_sha256"],
                        "evidence_receipt_sha256": evidence_receipt_sha256,
                    },
                )
            return drained

        drained_event = self.ledger.latest("endpoint.drained.v1")
        delete_intent = self.ledger.latest("endpoint.delete.intent.v1")
        delete_ack = self.ledger.latest("endpoint.delete.acknowledged.v1")

        # An interrupted delete is never replayed automatically.  First prove
        # whether the provider already removed the endpoint.
        if delete_intent is not None and delete_ack is None:
            presence = self.client.get_endpoint(self.endpoint_id, allow_absent=True)
            if presence is None:
                interrupted_absence = ProviderAbsenceReceipt(
                    self.endpoint_id, "GET_404_NOT_FOUND", _now_from_provider_check()
                )
                return self._record_provider_absence(
                    interrupted_absence, evidence_receipt_sha256
                )
            self._hard_stop("AMBIGUOUS_ENDPOINT_DELETE")
            raise ContractError(
                "delete intent has no acknowledgement and endpoint remains present; "
                "reconcile manually"
            )

        if drained_event is None:
            drain_key = make_idempotency_key({"run_tag": self.run_tag, "action": "drain"})
            drained = self.client.drain_endpoint(
                self.endpoint_id, run_tag=self.run_tag, idempotency_key=drain_key
            )
            if isinstance(drained, DryRunReceipt):
                raise ContractError("execute cleanup unexpectedly returned a dry-run drain")
            if not isinstance(drained, EndpointSummary) or drained.workers.maximum != 0:
                raise ContractError("provider drain did not set maximum workers to zero")
            self.ledger.append(
                "endpoint.drained.v1",
                {
                    "endpoint_id": self.endpoint_id,
                    "provider_response_sha256": drained.response_sha256,
                    "artifacts_uploaded": True,
                    "evidence_receipt_sha256": evidence_receipt_sha256,
                    "grace_window_elapsed": True,
                },
            )
        elif drained_event.payload.get("evidence_receipt_sha256") != evidence_receipt_sha256:
            self._hard_stop("CLEANUP_EVIDENCE_RECEIPT_DRIFT")
            raise ContractError("cleanup evidence receipt differs from the persisted drain")

        if delete_ack is None:
            delete_key = make_idempotency_key({"run_tag": self.run_tag, "action": "delete"})
            if delete_intent is None:
                self.ledger.append(
                    "endpoint.delete.intent.v1",
                    {
                        "endpoint_id": self.endpoint_id,
                        "idempotency_key": delete_key,
                        "evidence_receipt_sha256": evidence_receipt_sha256,
                    },
                )
            acknowledgement = self.client.delete_endpoint(
                self.endpoint_id,
                confirmation_endpoint_id=self.endpoint_id,
                run_tag=self.run_tag,
                idempotency_key=delete_key,
            )
            if isinstance(acknowledgement, DryRunReceipt):
                raise ContractError("execute cleanup unexpectedly returned a dry-run delete")
            ack = acknowledgement.to_dict()
            self.ledger.append(
                "endpoint.delete.acknowledged.v1",
                {
                    "endpoint_id": self.endpoint_id,
                    "acknowledgement_sha256": ack["acknowledgement_sha256"],
                    "evidence_receipt_sha256": evidence_receipt_sha256,
                },
            )

        confirmed_absence = self.client.verify_endpoint_absent(self.endpoint_id)
        if isinstance(confirmed_absence, DryRunReceipt):
            raise ContractError("execute cleanup unexpectedly returned a dry-run absence check")
        return self._record_provider_absence(confirmed_absence, evidence_receipt_sha256)

    def _record_provider_absence(
        self, absence: ProviderAbsenceReceipt, evidence_receipt_sha256: str
    ) -> ProviderAbsenceReceipt:
        receipt = absence.to_dict()
        self.ledger.append(
            "endpoint.provider_absent.v1",
            {
                "endpoint_id": self.endpoint_id,
                "observation": absence.observation,
                "observed_at": absence.observed_at,
                "evidence_receipt_sha256": evidence_receipt_sha256,
                "provider_absence_receipt_sha256": receipt["receipt_sha256"],
            },
        )
        return absence

    def _absence_from_event(
        self, event: LedgerEvent, evidence_receipt_sha256: str
    ) -> ProviderAbsenceReceipt:
        if event.payload.get("evidence_receipt_sha256") != evidence_receipt_sha256:
            raise ContractError("terminal cleanup receipt is bound to different evidence")
        absence = ProviderAbsenceReceipt(
            endpoint_id=_event_string(event, "endpoint_id"),
            observation=_event_string(event, "observation"),
            observed_at=_event_string(event, "observed_at"),
        )
        expected = event.payload.get("provider_absence_receipt_sha256")
        if absence.to_dict()["receipt_sha256"] != expected:
            raise ContractError("terminal provider absence receipt hash mismatch")
        return absence

    def report(self) -> dict[str, object]:
        spend = self.spend_guard.report()
        dispatch_count = len(self._dispatch_events_by_work())
        terminal_absence = self.ledger.latest("endpoint.provider_absent.v1")
        value: dict[str, object] = {
            "schema_version": "6.0.0",
            "cohort_id": self.cohort_id,
            "run_tag": self.run_tag,
            "endpoint_id": self.endpoint_id,
            "plan_sha256": self.plan_sha256,
            "required_repeat_count": EXACT_REPEAT_COUNT,
            "acknowledged_primary_dispatch_count": dispatch_count,
            "provider_cost_usd": spend["provider_cost_usd"],
            "user_charge_usd": spend["user_charge_usd"],
            "accepted_only_billing": True,
            "provider_spend_separate_from_user_billing": True,
            "spend_state": spend["state"],
            "terminal_provider_absence": terminal_absence is not None,
            "ledger_terminal_sha256": self.ledger.terminal_sha256(),
        }
        value["report_sha256"] = canonical_sha256(value)
        return value

    def _freeze_or_verify_plan(self) -> None:
        events = self.ledger.replay()
        plan = next((item for item in events if item.event_type == "cohort.plan.frozen.v1"), None)
        if plan is None:
            if events:
                raise ContractError("non-empty ledger is missing its first frozen cohort plan")
            self.ledger.append(
                "cohort.plan.frozen.v1",
                {
                    "plan_sha256": self.plan_sha256,
                    "endpoint_id": self.endpoint_id,
                    "environment_sha256": self.runs[0].environment_sha256,
                    "logical_work_ids": [run.run_id for run in self.runs],
                    "repeat_indexes": [run.repeat_index for run in self.runs],
                    "exact_repeat_count": EXACT_REPEAT_COUNT,
                },
            )
            return
        if plan.sequence != 1:
            raise ContractError("frozen cohort plan must be the first ledger event")
        if (
            plan.payload.get("plan_sha256") != self.plan_sha256
            or plan.payload.get("endpoint_id") != self.endpoint_id
            or plan.payload.get("logical_work_ids") != [run.run_id for run in self.runs]
        ):
            raise ContractError("resumed coordinator differs from the frozen cohort plan")

    def _restore_spend_guard(self) -> None:
        for event in self.ledger.replay():
            if event.event_type == "job.dispatched.v1":
                self.spend_guard.dispatch(
                    idempotency_key=_event_string(event, "idempotency_key"),
                    logical_work_id=_event_string(event, "logical_work_id"),
                    provider_job_id=_event_string(event, "provider_job_id"),
                    attempt_kind="primary",
                )
            elif event.event_type == "job.accepted.v1":
                self.spend_guard.accept_verified_result(
                    logical_work_id=_event_string(event, "logical_work_id"),
                    provider_job_id=_event_string(event, "provider_job_id"),
                )
            elif event.event_type == "user.charge.settled.v1":
                self.spend_guard.settle_user_charge(
                    logical_work_id=_event_string(event, "logical_work_id"),
                    amount_usd=_event_string(event, "amount_usd"),
                    final_integrity_state=_event_string(event, "final_integrity_state"),
                )
            elif event.event_type == "user.nonbillable.finalized.v1":
                self.spend_guard.settle_user_charge(
                    logical_work_id=_event_string(event, "logical_work_id"),
                    amount_usd="0",
                    final_integrity_state=_event_string(event, "final_integrity_state"),
                )
            elif event.event_type == "provider.billing.recorded.v1":
                self.spend_guard.record_provider_cost(
                    amount_usd=_event_string(event, "provider_amount_usd"),
                    cause=_event_string(event, "cause"),
                )
            elif event.event_type == "safety.hard_stop.v1":
                self.spend_guard.hard_stop(_event_string(event, "reason"))

    def _validate_dispatch_cardinality(self) -> None:
        dispatches = self._dispatch_events_by_work()
        allowed = {run.run_id for run in self.runs}
        if not set(dispatches).issubset(allowed) or len(dispatches) > EXACT_REPEAT_COUNT:
            self._hard_stop("DISPATCH_CARDINALITY_OR_MEMBERSHIP_VIOLATION")
            raise ContractError("ledger contains work outside the exact-three cohort")

    def _dispatch_events_by_work(self) -> dict[str, LedgerEvent]:
        result: dict[str, LedgerEvent] = {}
        for event in self.ledger.iter_type("job.dispatched.v1"):
            logical = _event_string(event, "logical_work_id")
            if logical in result:
                raise ContractError("logical work has duplicate provider dispatches")
            result[logical] = event
        return result

    def _intent_events_by_key(self) -> dict[str, LedgerEvent]:
        return {
            _event_string(event, "idempotency_key"): event
            for event in self.ledger.iter_type("job.dispatch.intent.v1")
        }

    def _latest_job_statuses(self) -> dict[str, str]:
        statuses = {
            logical: _event_string(event, "initial_status")
            for logical, event in self._dispatch_events_by_work().items()
        }
        for event in self.ledger.iter_type("job.status.observed.v1"):
            statuses[_event_string(event, "logical_work_id")] = _event_string(event, "status")
        return statuses

    def _append_dry_run_once(
        self,
        *,
        logical_work_id: str,
        idempotency_key: str,
        input_sha256: str,
        receipt_sha256: str,
    ) -> None:
        for event in self.ledger.iter_type("job.dispatch.dry_run.v1"):
            if (
                event.payload.get("logical_work_id") == logical_work_id
                and event.payload.get("idempotency_key") == idempotency_key
                and event.payload.get("input_sha256") == input_sha256
            ):
                return
        self.ledger.append(
            "job.dispatch.dry_run.v1",
            {
                "logical_work_id": logical_work_id,
                "idempotency_key": idempotency_key,
                "input_sha256": input_sha256,
                "dry_run_receipt_sha256": receipt_sha256,
            },
        )

    def _require_not_stopped(self) -> None:
        if self.spend_guard.state is SpendState.HARD_STOP_RUNAWAY:
            raise ContractError("coordinator runaway hard stop is active")

    def _hard_stop(self, reason: str) -> None:
        self.spend_guard.hard_stop(reason)
        if any(
            event.payload.get("reason") == reason
            for event in self.ledger.iter_type("safety.hard_stop.v1")
        ):
            return
        self.ledger.append("safety.hard_stop.v1", {"reason": reason})


def make_run_tag(runs: Sequence[RepeatRun]) -> str:
    validate_repeat_plan(runs)
    cohort_id = runs[0].cohort_id
    tag = f"v6-{cohort_id}"
    if len(tag) > 128:
        tag = "v6-cohort-" + canonical_sha256([run.to_dict() for run in runs]).split(":", 1)[1][
            :32
        ]
    return tag


def _outcome_from_dispatch(event: LedgerEvent, *, recovered: bool) -> DispatchOutcome:
    return DispatchOutcome(
        logical_work_id=_event_string(event, "logical_work_id"),
        idempotency_key=_event_string(event, "idempotency_key"),
        input_sha256=_event_string(event, "input_sha256"),
        provider_job_id=_event_string(event, "provider_job_id"),
        status=_event_string(event, "initial_status"),
        recovered=recovered,
    )


def _event_string(event: LedgerEvent, key: str) -> str:
    value = event.payload.get(key)
    if not isinstance(value, str) or not value:
        raise ContractError(f"{event.event_type}.{key} must be a non-empty string")
    return value


def _now_from_provider_check() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _money(value: Decimal | str) -> Decimal:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ContractError("money value must be a finite decimal") from exc
    if not amount.is_finite():
        raise ContractError("money value must be finite")
    return amount
