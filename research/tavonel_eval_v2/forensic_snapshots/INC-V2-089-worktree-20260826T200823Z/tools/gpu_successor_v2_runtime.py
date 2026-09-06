#!/usr/bin/env python3
"""Fail-closed control plane for the SFIR4-bound GPU successor V2 study."""

from __future__ import annotations

import base64
import hashlib
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

from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget

STUDY_ID = "SOURCE_FACT_PROPAGATION_MODEL_V2"
WORKER_BUNDLE_SCHEMA = "tavonel.v2.gpu_successor_worker_bundle.v2"
TERMINAL_ENVELOPE_SCHEMA = "tavonel.v2.gpu_successor_terminal_envelope.v1"
INNER_SECONDS = 20_700.0
INNER_USD = Decimal("38")


class V2RuntimeError(RuntimeError):
    """A paid or scientific V2 transition could not be proven safe."""


class ObjectTransport(Protocol):
    def put_if_absent(self, key: str, body: bytes, sha256: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def worker_grants(self, **kwargs: Any) -> dict[str, Any]: ...


class ProviderTransport(Protocol):
    def create(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def list_by_name(self, name: str) -> list[dict[str, Any]]: ...
    def snapshot(self, resource_id: str) -> dict[str, Any] | None: ...
    def delete_and_finalize(self, resource_id: str) -> dict[str, Any]: ...


def sha_bytes(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise V2RuntimeError(f"{label} is not sha256:<64 hex>")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise V2RuntimeError(f"{label} is not sha256:<64 hex>") from error
    return value


def load_v2_bundle(path: Path, expected_sha256: str) -> dict[str, Any]:
    if not path.is_file() or sha_file(path) != _sha(expected_sha256, "bundle file pin"):
        raise V2RuntimeError("exact V2 worker bundle is absent or drifted")
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise V2RuntimeError("V2 worker bundle is unreadable") from error
    if body.get("schema") != WORKER_BUNDLE_SCHEMA or body.get("study_id") != STUDY_ID:
        raise V2RuntimeError("V1 or foreign worker bundle refused")
    for field in (
        "bundle_sha256",
        "entrypoint_sha256",
        "scorer_sha256",
        "model_revision_sha256",
        "tokenizer_sha256",
        "facts_digest",
    ):
        _sha(body.get(field), field)
    facts = {key: value for key, value in body.items() if key != "facts_digest"}
    if canonical_sha(facts) != body["facts_digest"]:
        raise V2RuntimeError("V2 worker bundle facts digest drifted")
    try:
        Ed25519PublicKey.from_public_bytes(
            base64.b64decode(body["terminal_public_key_b64"], validate=True)
        )
    except (KeyError, TypeError, ValueError) as error:
        raise V2RuntimeError("V2 terminal public key is invalid") from error
    return {**body, "manifest_file_sha256": sha_file(path)}


def verify_terminal(envelope: dict[str, Any], bundle: dict[str, Any]) -> dict[str, Any]:
    if envelope.get("schema") != TERMINAL_ENVELOPE_SCHEMA or envelope.get("status") != "completed":
        raise V2RuntimeError("authenticated completed terminal envelope is required")
    signed = {key: value for key, value in envelope.items() if key != "signature_b64"}
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(bundle["terminal_public_key_b64"], validate=True)
        )
        public.verify(
            base64.b64decode(envelope["signature_b64"], validate=True),
            json.dumps(signed, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(),
        )
    except (KeyError, TypeError, ValueError, InvalidSignature) as error:
        raise V2RuntimeError("terminal authentication failed") from error
    expected = {
        key: bundle[key]
        for key in (
            "bundle_sha256",
            "entrypoint_sha256",
            "scorer_sha256",
            "model_revision_sha256",
            "tokenizer_sha256",
            "vllm_version",
        )
    }
    if envelope.get("runtime_attestation") != expected:
        raise V2RuntimeError("terminal runtime attestation drifted")
    _sha(envelope.get("input_sha256"), "terminal input")
    _sha(envelope.get("output_sha256"), "terminal output")
    key = envelope.get("output_key")
    if not isinstance(key, str) or envelope["output_sha256"][7:] not in key:
        raise V2RuntimeError("terminal output key is not content-addressed")
    return envelope


@dataclass(frozen=True, slots=True)
class V2Limits:
    maximum_seconds: float = INNER_SECONDS
    maximum_cost_usd: Decimal = INNER_USD
    poll_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 0 < self.maximum_seconds <= INNER_SECONDS:
            raise V2RuntimeError("V2 time cap exceeds 5.75 hours")
        if not Decimal("0") < self.maximum_cost_usd <= INNER_USD:
            raise V2RuntimeError("V2 spend cap exceeds 38 USD")
        if not 0 < self.poll_seconds <= 5:
            raise V2RuntimeError("V2 polling must be within five seconds")


class V2Controller:
    def __init__(
        self,
        *,
        provider: ProviderTransport,
        objects: ObjectTransport,
        ledger: EvidenceLedger,
        budget: AuthorizedSpendBudget,
        limits: V2Limits | None = None,
        clock: Callable[[], float] = monotonic,
        wait: Callable[[float], None] = sleep,
    ) -> None:
        self.provider, self.objects, self.ledger, self.budget = provider, objects, ledger, budget
        self.limits, self.clock, self.wait = limits or V2Limits(), clock, wait

    @staticmethod
    def _usage(snapshot: dict[str, Any]) -> dict[str, float]:
        seconds, cost = snapshot.get("gpu_seconds"), snapshot.get("cost_usd")
        if (
            isinstance(seconds, bool)
            or isinstance(cost, bool)
            or not isinstance(seconds, (int, float))
            or not isinstance(cost, (int, float))
            or seconds < 0
            or cost < 0
        ):
            raise V2RuntimeError("provider usage evidence is absent or invalid")
        return {"gpu_seconds": float(seconds), "cost_usd": float(cost)}

    def execute(
        self, *, spec: dict[str, Any], input_path: Path, bundle: dict[str, Any], output_path: Path
    ) -> dict[str, Any]:
        authority = spec.get("execution_authority", {})
        for prefix in ("sfir4_acceptance", "four_link_acceptance", "protocol_freeze"):
            path, expected = (
                Path(str(authority.get(prefix + "_path", ""))),
                authority.get(prefix + "_sha256"),
            )
            if not path.is_file() or sha_file(path) != _sha(expected, prefix):
                raise V2RuntimeError(f"exact {prefix} authority drifted")
        input_body, input_sha = input_path.read_bytes(), sha_file(input_path)
        if input_sha != spec.get("materialized_input_sha256"):
            raise V2RuntimeError("materialized input drifted")
        identity = canonical_sha(
            {
                "study_id": STUDY_ID,
                "input": input_sha,
                "bundle": bundle["bundle_sha256"],
                "model": spec.get("model_pin_sha256"),
            }
        )
        suffix, name = identity[7:23], "gpu-successor-v2-" + identity[7:23]
        input_key = f"gpu-successor-v2/inputs/{input_sha[7:]}.json"
        status_key = f"gpu-successor-v2/status/{suffix}.json"
        output_prefix = f"gpu-successor-v2/outputs/{suffix}"
        self.objects.put_if_absent(input_key, input_body, input_sha)
        reservation = "gpu-successor-v2-" + suffix
        if reservation not in self.budget.report()["reservations"]:
            self.budget.reserve(
                allocation_id=reservation, maximum_cost_usd=self.limits.maximum_cost_usd
            )
        grants = self.objects.worker_grants(
            input_key=input_key, status_key=status_key, output_prefix=output_prefix, expires=20_700
        )
        request = {
            **spec,
            "name": name,
            "input_sha256": input_sha,
            "worker_bundle": bundle,
            "worker_transport": grants,
        }
        run_intent = self.ledger.latest("resource.v2.create.intent.v1")
        if run_intent and run_intent.payload.get("run_identity") != identity:
            raise V2RuntimeError("durable V2 create intent belongs to another run")
        if not run_intent:
            self.ledger.append(
                "resource.v2.create.intent.v1",
                {"run_identity": identity, "name": name, "request_sha256": canonical_sha(request)},
            )
        ack = self.ledger.latest("resource.v2.create.acknowledged.v1")
        matches = self.provider.list_by_name(name)
        if ack and ack.payload.get("run_identity") == identity:
            ack_id = str(ack.payload.get("resource_id", ""))
            matches = [row for row in matches if str(row.get("id")) == ack_id]
        resource: dict[str, Any] | None = matches[0] if len(matches) == 1 else None
        if not matches:
            try:
                candidate = self.provider.create(request)
                if candidate.get("name") == name and candidate.get("id"):
                    resource = candidate
                else:
                    matches = self.provider.list_by_name(name)
            except Exception as error:
                matches = self.provider.list_by_name(name)
                if len(matches) != 1:
                    for row in matches:
                        if row.get("id"):
                            self.provider.delete_and_finalize(str(row["id"]))
                    raise V2RuntimeError(
                        "ambiguous V2 create could not be reconciled and was cleaned up"
                    ) from error
        if resource is None:
            if len(matches) != 1:
                for row in matches:
                    if row.get("id"):
                        self.provider.delete_and_finalize(str(row["id"]))
                raise V2RuntimeError("ambiguous V2 resources were cleaned up")
            resource = matches[0]
        resource_id = str(resource.get("id", ""))
        if not resource_id or resource.get("name") != name:
            raise V2RuntimeError("provider resource identity drifted after durable reconciliation")
        self.ledger.append(
            "resource.v2.create.acknowledged.v1",
            {"resource_id": resource_id, "run_identity": identity, "name": name},
        )
        started, terminal, output_sha = self.clock(), None, None
        final_usage: dict[str, Any] | None = None
        try:
            while terminal is None:
                snapshot = self.provider.snapshot(resource_id)
                if snapshot is None:
                    raise V2RuntimeError("provider resource disappeared before terminal proof")
                usage = self._usage(snapshot)
                if (
                    self.clock() - started >= self.limits.maximum_seconds
                    or usage["gpu_seconds"] >= self.limits.maximum_seconds
                ):
                    raise V2RuntimeError("V2 live GPU-time kill switch fired")
                if Decimal(str(usage["cost_usd"])) >= self.limits.maximum_cost_usd:
                    raise V2RuntimeError("V2 live dollar kill switch fired")
                try:
                    candidate = json.loads(self.objects.get(status_key))
                except (KeyError, FileNotFoundError):
                    self.wait(self.limits.poll_seconds)
                    continue
                except json.JSONDecodeError as error:
                    raise V2RuntimeError("terminal status is malformed") from error
                terminal = verify_terminal(candidate, bundle)
                if terminal["input_sha256"] != input_sha or not terminal["output_key"].startswith(
                    output_prefix + "/"
                ):
                    raise V2RuntimeError("terminal envelope escaped its V2 run binding")
            output = self.objects.get(terminal["output_key"])
            output_sha = sha_bytes(output)
            if output_sha != terminal["output_sha256"]:
                raise V2RuntimeError("retrieved V2 output digest drifted")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(output)
        finally:
            final_usage = self.provider.delete_and_finalize(resource_id)
            if (
                final_usage.get("provider_absent") is not True
                or final_usage.get("source") != "provider_predelete_usage_with_delete_absence"
            ):
                raise V2RuntimeError("final provider billing and absence proof are required")
            usage = self._usage(final_usage)
            if (
                usage["gpu_seconds"] > self.limits.maximum_seconds
                or Decimal(str(usage["cost_usd"])) > self.limits.maximum_cost_usd
            ):
                raise V2RuntimeError("final provider usage exceeded the V2 inner cap")
            self.budget.settle(
                allocation_id=reservation, actual_cost_usd=Decimal(str(usage["cost_usd"]))
            )
            self.ledger.append(
                "endpoint.v2.provider_absent.v1",
                {"resource_id": resource_id, "run_identity": identity, "final_usage": usage},
            )
        return {
            "status": "completed",
            "resource_id": resource_id,
            "input_sha256": input_sha,
            "output_sha256": output_sha,
            "output_path": str(output_path.resolve()),
            "actual_usage": self._usage(final_usage),
            "provider_absent": True,
            "budget": self.budget.report(),
        }


__all__ = [
    "INNER_SECONDS",
    "INNER_USD",
    "STUDY_ID",
    "V2Controller",
    "V2Limits",
    "V2RuntimeError",
    "load_v2_bundle",
    "verify_terminal",
]
