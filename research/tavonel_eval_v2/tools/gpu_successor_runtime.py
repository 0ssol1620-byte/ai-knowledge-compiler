#!/usr/bin/env python3
"""Auditable control plane for the frozen GPU successor worker.

Provider and object-store operations are injected.  Production can bind the
RunPod and R2 adapters; tests bind in-memory transports and can never spend.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Protocol

from common import canonical_sha, sha_file
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from gpu_successor_preflight import CAP_GPU_HOURS, CAP_USD, STUDY_ID

from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget

WORKER_BUNDLE_SCHEMA = "tavonel.v2.gpu_successor_worker_bundle.v1"
TERMINAL_ENVELOPE_SCHEMA = "tavonel.v2.gpu_successor_terminal_envelope.v1"
_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class RuntimeControlError(RuntimeError):
    """A paid or scientific transition could not be proven safe."""


class ObjectTransport(Protocol):
    def put_if_absent(self, key: str, body: bytes, sha256: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class ProviderTransport(Protocol):
    def create(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def list_by_name(self, name: str) -> list[dict[str, Any]]: ...
    def snapshot(self, resource_id: str) -> dict[str, Any] | None: ...
    def delete(self, resource_id: str) -> None: ...


def _sha_bytes(body: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(body).hexdigest()


def _require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise RuntimeControlError(f"{label} is not sha256:<64 hex>")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise RuntimeControlError(f"{label} is not sha256:<64 hex>") from error
    return value


def load_worker_bundle(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    """Validate the frozen worker/scorer/runtime/authentication manifest."""
    if not path.is_file():
        raise RuntimeControlError("frozen worker bundle manifest is absent")
    actual_file_sha = sha_file(path)
    if expected_sha256 is not None and actual_file_sha != _require_sha(
        expected_sha256, "worker bundle manifest pin"
    ):
        raise RuntimeControlError("worker bundle manifest file hash drifted")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeControlError("worker bundle manifest is unreadable") from error
    if body.get("schema") != WORKER_BUNDLE_SCHEMA or body.get("study_id") != STUDY_ID:
        raise RuntimeControlError("worker bundle manifest names the wrong schema or study")
    required_sha = (
        "bundle_sha256",
        "entrypoint_sha256",
        "scorer_sha256",
        "model_revision_sha256",
        "tokenizer_sha256",
    )
    for key in required_sha:
        _require_sha(body.get(key), key)
    if (
        not isinstance(body.get("entrypoint"), list)
        or not body["entrypoint"]
        or any(not isinstance(part, str) or not part for part in body["entrypoint"])
    ):
        raise RuntimeControlError("worker entrypoint is not a frozen argv array")
    if not isinstance(body.get("vllm_version"), str) or not body["vllm_version"]:
        raise RuntimeControlError("worker bundle has no exact vLLM version")
    try:
        public_key = base64.b64decode(body.get("terminal_public_key_b64", ""), validate=True)
        Ed25519PublicKey.from_public_bytes(public_key)
    except (ValueError, TypeError) as error:
        raise RuntimeControlError("worker terminal Ed25519 public key is invalid") from error
    facts = {key: value for key, value in body.items() if key != "facts_digest"}
    if body.get("facts_digest") != canonical_sha(facts):
        raise RuntimeControlError("worker bundle facts_digest does not match its contents")
    return {**body, "manifest_file_sha256": actual_file_sha}


def verify_terminal_envelope(envelope: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    """Authenticate completion and exact model/tokenizer/vLLM attestation."""
    if envelope.get("schema") != TERMINAL_ENVELOPE_SCHEMA:
        raise RuntimeControlError("terminal status schema is not recognized")
    signature_b64 = envelope.get("signature_b64")
    signed = {key: value for key, value in envelope.items() if key != "signature_b64"}
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(bundle["terminal_public_key_b64"], validate=True)
        )
        payload = json.dumps(
            signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        public.verify(signature, payload)
    except (InvalidSignature, ValueError, TypeError) as error:
        raise RuntimeControlError("terminal status authentication failed") from error
    if envelope.get("status") not in _TERMINAL:
        raise RuntimeControlError("worker status is not terminal")
    if envelope.get("status") != "completed":
        raise RuntimeControlError(f"worker terminated as {envelope.get('status')}")
    attestation = envelope.get("runtime_attestation")
    expected = {
        "bundle_sha256": bundle["bundle_sha256"],
        "entrypoint_sha256": bundle["entrypoint_sha256"],
        "scorer_sha256": bundle["scorer_sha256"],
        "model_revision_sha256": bundle["model_revision_sha256"],
        "tokenizer_sha256": bundle["tokenizer_sha256"],
        "vllm_version": bundle["vllm_version"],
    }
    if attestation != expected:
        raise RuntimeControlError("runtime model/tokenizer/vLLM attestation drifted")
    _require_sha(envelope.get("input_sha256"), "terminal input_sha256")
    _require_sha(envelope.get("output_sha256"), "terminal output_sha256")
    if not isinstance(envelope.get("output_key"), str) or not envelope["output_key"]:
        raise RuntimeControlError("terminal envelope has no output object key")
    if envelope["output_sha256"][7:] not in envelope["output_key"]:
        raise RuntimeControlError("terminal output object key is not content-addressed")
    return envelope


@dataclass(frozen=True, slots=True)
class RuntimeLimits:
    maximum_seconds: float = CAP_GPU_HOURS * 3600.0
    maximum_cost_usd: Decimal = Decimal(str(CAP_USD))
    poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.maximum_seconds <= CAP_GPU_HOURS * 3600.0:
            raise RuntimeControlError("runtime time limit exceeds the frozen cap")
        if not Decimal("0") < self.maximum_cost_usd <= Decimal(str(CAP_USD)):
            raise RuntimeControlError("runtime dollar limit exceeds the frozen cap")
        if self.poll_seconds <= 0:
            raise RuntimeControlError("poll interval must be positive")


class GpuSuccessorController:
    """One resumable, reservation-first, content-addressed execution."""

    def __init__(
        self,
        *,
        provider: ProviderTransport,
        objects: ObjectTransport,
        ledger: EvidenceLedger,
        budget: AuthorizedSpendBudget,
        limits: RuntimeLimits | None = None,
        clock: Callable[[], float] = monotonic,
        wait: Callable[[float], None] = sleep,
    ) -> None:
        self.provider = provider
        self.objects = objects
        self.ledger = ledger
        self.budget = budget
        self.limits = limits or RuntimeLimits()
        self.clock = clock
        self.wait = wait
        self._active_resource_id: str | None = None

    def abort(self) -> None:
        """Best-effort external watchdog hook for the currently active resource."""
        resource_id = self._active_resource_id
        if resource_id is not None:
            self.provider.delete(resource_id)

    def execute(
        self,
        *,
        spec: dict[str, Any],
        input_path: Path,
        bundle: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any]:
        authority = spec.get("execution_authority") or {}
        if (
            authority.get("fresh_study_acceptance") is not True
            or authority.get("four_link_acceptance") is not True
        ):
            raise RuntimeControlError("fresh study and four-link acceptances are both required")
        _require_sha(authority.get("fresh_study_acceptance_sha256"), "fresh study acceptance")
        _require_sha(authority.get("four_link_acceptance_sha256"), "four-link acceptance")
        for label, path_key, sha_key in (
            (
                "fresh study acceptance",
                "fresh_study_acceptance_path",
                "fresh_study_acceptance_sha256",
            ),
            (
                "four-link acceptance",
                "four_link_acceptance_path",
                "four_link_acceptance_sha256",
            ),
        ):
            path = Path(str(authority.get(path_key, "")))
            if not path.is_file() or sha_file(path) != authority[sha_key]:
                raise RuntimeControlError(f"exact {label} receipt path/hash drifted")
        input_body = input_path.read_bytes()
        input_sha = _sha_bytes(input_body)
        if input_sha != spec.get("input_contract", {}).get("materialized_file_sha256"):
            raise RuntimeControlError("execution input differs from the accepted materialized file")
        run_identity = canonical_sha(
            {
                "study_id": STUDY_ID,
                "input_sha256": input_sha,
                "worker_bundle_sha256": bundle["bundle_sha256"],
                "model_pin_sha256": spec.get("model_pin_sha256"),
            }
        )
        suffix = run_identity[7:23]
        name = f"gpu-successor-{suffix}"
        input_key = f"gpu-successor/inputs/{input_sha[7:]}.json"
        status_key = f"gpu-successor/status/{suffix}.json"
        output_prefix = f"gpu-successor/outputs/{suffix}"
        self.objects.put_if_absent(input_key, input_body, input_sha)
        self.ledger.append(
            "artifact.input.uploaded.v1",
            {"object_key": input_key, "input_sha256": input_sha, "run_identity": run_identity},
        )

        reservation_id = f"gpu-successor-{suffix}"
        if reservation_id not in self.budget.report()["reservations"]:
            self.budget.reserve(
                allocation_id=reservation_id,
                maximum_cost_usd=self.limits.maximum_cost_usd,
            )
        worker_grants_fn = getattr(self.objects, "worker_grants", None)
        worker_transport = (
            worker_grants_fn(
                input_key=input_key,
                status_key=status_key,
                output_prefix=output_prefix,
            )
            if callable(worker_grants_fn)
            else {}
        )
        resource = self._create_or_reconcile(
            name=name,
            request={
                **spec,
                "name": name,
                "input_object_key": input_key,
                "input_sha256": input_sha,
                "status_object_key": status_key,
                "output_object_prefix": output_prefix + "/",
                "worker_bundle": bundle,
                "worker_transport": worker_transport,
            },
            run_identity=run_identity,
        )
        resource_id = str(resource["id"])
        self._active_resource_id = resource_id
        started = self.clock()
        terminal: dict[str, Any] | None = None
        usage: dict[str, float] = {"gpu_seconds": 0.0, "cost_usd": 0.0}
        try:
            while terminal is None:
                snapshot = self.provider.snapshot(resource_id)
                if snapshot is None:
                    raise RuntimeControlError("provider resource disappeared before terminal proof")
                usage = self._usage(snapshot)
                elapsed = self.clock() - started
                if (
                    elapsed >= self.limits.maximum_seconds
                    or usage["gpu_seconds"] >= self.limits.maximum_seconds
                ):
                    raise RuntimeControlError("live GPU-time kill switch fired")
                if Decimal(str(usage["cost_usd"])) >= self.limits.maximum_cost_usd:
                    raise RuntimeControlError("live dollar kill switch fired")
                try:
                    status_body = self.objects.get(status_key)
                except (KeyError, FileNotFoundError):
                    self.wait(self.limits.poll_seconds)
                    continue
                try:
                    candidate = json.loads(status_body)
                except json.JSONDecodeError as error:
                    raise RuntimeControlError("terminal status object is malformed") from error
                terminal = verify_terminal_envelope(candidate, bundle)
                if terminal["input_sha256"] != input_sha:
                    raise RuntimeControlError("terminal status binds a different input")
                if not terminal["output_key"].startswith(output_prefix + "/"):
                    raise RuntimeControlError(
                        "terminal output escaped the run-scoped object prefix"
                    )
            output_body = self.objects.get(terminal["output_key"])
            if _sha_bytes(output_body) != terminal["output_sha256"]:
                raise RuntimeControlError("retrieved output failed its content digest")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(output_body)
            self.ledger.append(
                "artifact.output.retrieved.v1",
                {
                    "object_key": terminal["output_key"],
                    "output_sha256": terminal["output_sha256"],
                    "terminal_envelope_sha256": canonical_sha(terminal),
                },
            )
        finally:
            self._delete_and_prove_absent(resource_id, run_identity)
            self._active_resource_id = None
            actual = Decimal(str(usage["cost_usd"]))
            self.budget.settle(allocation_id=reservation_id, actual_cost_usd=actual)
        return {
            "status": "completed",
            "resource_id": resource_id,
            "input_sha256": input_sha,
            "output_path": str(output_path.resolve()),
            "output_sha256": terminal["output_sha256"],
            "actual_usage": usage,
            "provider_absent": True,
            "budget": self.budget.report(),
        }

    def _create_or_reconcile(
        self, *, name: str, request: dict[str, Any], run_identity: str
    ) -> dict[str, Any]:
        intent = self.ledger.latest("resource.create.intent.v1")
        ack = self.ledger.latest("resource.create.acknowledged.v1")
        if intent is None:
            self.ledger.append(
                "resource.create.intent.v1",
                {
                    "name": name,
                    "run_identity": run_identity,
                    "request_sha256": canonical_sha(request),
                },
            )
        elif intent.payload.get("run_identity") != run_identity:
            raise RuntimeControlError("durable create intent belongs to another run")
        if ack is not None:
            resource_id = str(ack.payload.get("resource_id", ""))
            snapshot = self.provider.snapshot(resource_id)
            if snapshot is None:
                raise RuntimeControlError("acknowledged resource is absent before execution")
            return snapshot
        matches = self.provider.list_by_name(name)
        if len(matches) > 1:
            raise RuntimeControlError("ambiguous create reconciliation found multiple resources")
        if len(matches) == 1:
            resource = matches[0]
        else:
            try:
                resource = self.provider.create(request)
            except Exception as error:
                matches = self.provider.list_by_name(name)
                if len(matches) != 1:
                    raise RuntimeControlError(
                        "ambiguous provider create could not be reconciled"
                    ) from error
                resource = matches[0]
        resource_id = str(resource.get("id", ""))
        if not resource_id or resource.get("name") != name:
            raise RuntimeControlError("provider create identity drifted")
        self.ledger.append(
            "resource.create.acknowledged.v1",
            {"resource_id": resource_id, "name": name, "run_identity": run_identity},
        )
        return resource

    @staticmethod
    def _usage(snapshot: dict[str, Any]) -> dict[str, float]:
        seconds = snapshot.get("gpu_seconds")
        cost = snapshot.get("cost_usd")
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
            raise RuntimeControlError("live provider snapshot has no numeric gpu_seconds")
        if isinstance(cost, bool) or not isinstance(cost, (int, float)):
            raise RuntimeControlError("live provider snapshot has no numeric cost_usd")
        if seconds < 0 or cost < 0:
            raise RuntimeControlError("live provider usage is negative")
        return {"gpu_seconds": float(seconds), "cost_usd": float(cost)}

    def _delete_and_prove_absent(self, resource_id: str, run_identity: str) -> None:
        self.ledger.append(
            "resource.delete.intent.v1",
            {"resource_id": resource_id, "run_identity": run_identity},
        )
        self.provider.delete(resource_id)
        if self.provider.snapshot(resource_id) is not None:
            raise RuntimeControlError("provider resource remains after delete acknowledgement")
        self.ledger.append(
            "endpoint.provider_absent.v1",
            {"endpoint_id": resource_id, "absence_basis": "provider_read_after_delete"},
        )


__all__ = [
    "TERMINAL_ENVELOPE_SCHEMA",
    "WORKER_BUNDLE_SCHEMA",
    "GpuSuccessorController",
    "ObjectTransport",
    "ProviderTransport",
    "RuntimeControlError",
    "RuntimeLimits",
    "load_worker_bundle",
    "verify_terminal_envelope",
]
