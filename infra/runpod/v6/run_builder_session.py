"""Drive one temporary RunPod builder Pod through create -> ready -> delete.

`builder_pod.RunPodBuilderClient` owns the provider contract (spend reservation,
GPU/name/rate drift rejection, receipts). It does not own a session loop: nothing
in it polls for readiness, and nothing guarantees the Pod is torn down when the
caller raises. This module supplies exactly those two properties, mirroring the
delete-then-prove-absence and watchdog behaviour that
`confirmatory_pod_controller` already applies to confirmatory runs, and which
`PAID_EXECUTION_REQUEST.md` section 11 records as missing from the qualification
path.

It deliberately does NOT build anything. The image build runs over SSH against
the ready Pod and is driven separately, so that a build failure and a provider
lifecycle failure stay distinguishable in the receipts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable

import httpx

from benchmark.v6.contracts import ContractError, canonical_sha256
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget
from infra.runpod.v6.builder_pod import (
    BuilderPodError,
    BuilderPodSpec,
    RunPodBuilderClient,
)

_POLL_INTERVAL_SECONDS = 10.0
_READY_TIMEOUT_SECONDS = 900.0
# How long a Pod may report uptimeInSeconds == 0 before it is treated as a
# non-starting (billing) zombie rather than one that is merely still booting.
# A healthy Pod on this provider reaches a positive uptime well inside this
# window; the INC-RUNPOD-02 Pod sat at 0 for 23.6 hours.
_ZOMBIE_GRACE_SECONDS = 180.0
_GRAPHQL_URL = "https://api.runpod.io/graphql"



class BuilderSessionError(ContractError):
    """The builder session could not be completed."""


def resolve_gpu_name_via_graphql(*, api_key: str, pod_id: str) -> str:
    """Read a Pod's GPU display name from the GraphQL API.

    The REST Pod payload this project's builder client reads
    (``rest.runpod.io/v1/pods``) has been observed returning ``machine: {}``
    with no ``gpu`` key for a freshly created, RUNNING Pod -- measured on
    Pod ``xzir8ordp03tvt`` on 2026-08-31, which reported RUNNING with a public
    IP and an SSH port mapping while carrying no GPU identity at all. Because
    ``RunPodBuilderClient.verify_ready`` refuses any Pod whose GPU it cannot
    match against the requested type's alias set, that empty payload makes the
    readiness check fail forever while the Pod bills.

    The GraphQL API returns the same Pod's ``machine.gpuDisplayName``
    (e.g. ``RTX 4090``), which is already a member of the alias sets in
    ``builder_pod._GPU_ALIASES``. ``verify_ready`` accepts that value through
    its ``verified_gpu_name`` argument and records
    ``gpu_identity_source: graphql_cross_check`` in the receipt, so the GPU is
    still positively identified -- this widens the source of the identity, it
    does not waive the check. An empty string is returned when GraphQL also
    has no identity, which keeps ``verify_ready`` failing closed.
    """

    request = httpx.Request(
        "POST",
        _GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "query": "query { myself { pods { id machine { gpuDisplayName } } } }"
        },
    )
    with httpx.Client(timeout=30.0) as client:
        response = client.send(request)
    if response.status_code != 200:
        return ""
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("errors"):
        return ""
    myself = (payload.get("data") or {}).get("myself") or {}
    for pod in myself.get("pods") or []:
        if str(pod.get("id", "")) != pod_id:
            continue
        machine = pod.get("machine")
        if isinstance(machine, dict):
            return str(machine.get("gpuDisplayName", "")).strip()
    return ""



@dataclass(frozen=True, slots=True)
class BuilderSession:
    pod_id: str
    public_ip: str
    ssh_port: int
    create_receipt: dict[str, Any]
    ready_receipt: dict[str, Any]


def _poll_until_ready(
    client: RunPodBuilderClient,
    spec: BuilderPodSpec,
    *,
    pod_id: str,
    timeout_seconds: float,
    api_key: str | None = None,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> dict[str, Any]:
    """Poll verify_ready until it succeeds or the deadline passes.

    verify_ready raises while the Pod is still provisioning (no public IP, not
    RUNNING yet). Those raises are expected and are retried; the deadline is the
    only thing that ends the loop unsuccessfully, so a Pod can never be polled
    indefinitely while billing.

    When ``api_key`` is supplied, each attempt first tries to resolve the GPU
    identity over GraphQL and passes it as ``verified_gpu_name``. This covers
    the observed case where the REST payload carries no GPU identity at all;
    see :func:`resolve_gpu_name_via_graphql`. The value is only ever an extra
    identity *source* -- verify_ready still matches it against the requested
    GPU type's alias set and still fails closed on a mismatch or an empty
    value.
    """

    deadline = clock() + timeout_seconds
    last_error: Exception | None = None
    zombie_deadline = clock() + _ZOMBIE_GRACE_SECONDS
    while clock() < deadline:
        verified_gpu_name: str | None = None
        if api_key:
            try:
                verified_gpu_name = resolve_gpu_name_via_graphql(
                    api_key=api_key, pod_id=pod_id
                ) or None
            except Exception:  # noqa: BLE001 - cross-check is best-effort
                verified_gpu_name = None

            # INC-RUNPOD-02: a Pod whose container never starts stays
            # `RUNNING` and bills forever. Once past the grace window, a
            # still-zero uptime is treated as a hard failure rather than
            # something to keep waiting on.
            if clock() > zombie_deadline:
                uptime = read_uptime_seconds(api_key=api_key, pod_id=pod_id)
                if uptime == 0:
                    raise BuilderSessionError(
                        "builder Pod is billing with uptimeInSeconds=0 after "
                        f"{_ZOMBIE_GRACE_SECONDS:.0f}s: its container is not "
                        "starting (see INC-RUNPOD-02); refusing to keep waiting"
                    )
        try:
            return client.verify_ready(
                spec, pod_id=pod_id, verified_gpu_name=verified_gpu_name
            )
        except (BuilderPodError, ContractError) as exc:
            last_error = exc
            sleeper(_POLL_INTERVAL_SECONDS)
    raise BuilderSessionError(
        f"builder Pod did not become ready within {timeout_seconds:.0f}s: {last_error}"
    )


def delete_and_prove_absence(
    client: RunPodBuilderClient, pod_id: str
) -> dict[str, Any]:
    """Delete the Pod, then require a 404 on read-back as proof of absence.

    The delete call's own return value is not trusted: only a subsequent
    404 counts as evidence the paid resource is gone.
    """

    receipt: dict[str, Any] = {
        "schema": "folynta.runpod-builder-absence.v1",
        "pod_id": pod_id,
        "delete_requested": True,
    }
    try:
        client.delete(pod_id)
        receipt["delete_error"] = None
    except Exception as exc:  # noqa: BLE001 - recorded, then absence is still probed
        receipt["delete_error"] = type(exc).__name__

    try:
        client.get(pod_id)
    except Exception as exc:  # noqa: BLE001 - a 404 here is the success path
        message = str(exc)
        receipt["observation"] = (
            "GET_404_NOT_FOUND" if "404" in message else "GET_FAILED_NOT_404"
        )
        receipt["absence_proven"] = "404" in message
    else:
        receipt["observation"] = "GET_STILL_RETURNS_POD"
        receipt["absence_proven"] = False

    receipt["receipt_sha256"] = canonical_sha256(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    return receipt


def read_uptime_seconds(*, api_key: str, pod_id: str) -> int | None:
    """Return a Pod's `runtime.uptimeInSeconds`, or None when unknown.

    Guards against the failure mode recorded as INC-RUNPOD-02 in
    ``infra/runpod/v6/qualification/rq-01/KNOWN_ISSUES.md``: Pod
    ``tcmo7xom13m2ch`` reported ``desiredStatus: RUNNING`` for ~23.6 hours,
    billing $0.74/hr the whole time, while its container never started once
    (``uptimeInSeconds: 0``). Its host's NVIDIA driver did not satisfy the
    image's ``cuda>=12.8`` requirement, so ``runc`` failed in its prestart
    hook and crash-looped -- and RunPod bills the rented GPU regardless.

    ``desiredStatus`` is therefore a statement of intent, not evidence that
    anything is running. A readiness check that trusts it will wait forever
    on a Pod like that. Only a positive uptime is evidence.

    None is returned when the field is absent (the Pod may be too young to
    report one yet), which callers must treat as "not yet proven", never as
    success.
    """

    request = httpx.Request(
        "POST",
        _GRAPHQL_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "query": "query { myself { pods { id runtime { uptimeInSeconds } } } }"
        },
    )
    with httpx.Client(timeout=30.0) as client:
        response = client.send(request)
    if response.status_code != 200:
        return None
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("errors"):
        return None
    myself = (payload.get("data") or {}).get("myself") or {}
    for pod in myself.get("pods") or []:
        if str(pod.get("id", "")) != pod_id:
            continue
        runtime = pod.get("runtime")
        if isinstance(runtime, dict) and runtime.get("uptimeInSeconds") is not None:
            return int(runtime["uptimeInSeconds"])
        return None
    return None


def find_pods_by_name(*, api_key: str, name: str) -> list[str]:
    """Return the ids of every existing Pod carrying exactly ``name``.

    This is the reconciliation half of the ambiguous-write problem that
    ``RunPodBuilderClient.create`` documents but cannot solve alone: it raises
    on an unexpected status and never learns the id of a Pod the provider may
    still have created, so the caller is left billing for a Pod it cannot name.

    Measured on 2026-08-31 against ``rest.runpod.io/v1/pods``: an identical
    create request returned HTTP 500 while creating Pod ``net5nm21hawfox``, and
    a repeat of the same request returned 201. The 500 body was a complete,
    valid Pod object. A create failure therefore proves nothing about whether
    paid capacity exists, and the only sound recovery is to list the inventory
    and match on the requested name.
    """

    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            "https://rest.runpod.io/v1/pods",
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if response.status_code != 200:
        raise BuilderSessionError(
            f"could not list Pods for reconciliation (status {response.status_code})"
        )
    payload = response.json()
    pods = payload if isinstance(payload, list) else payload.get("data") or []
    return [
        str(pod["id"])
        for pod in pods
        if isinstance(pod, dict) and str(pod.get("name", "")) == name and pod.get("id")
    ]


def reconcile_orphans_by_name(
    client: RunPodBuilderClient,
    *,
    api_key: str,
    name: str,
    receipts_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Delete every Pod matching ``name`` and prove each one's absence.

    Called after an ambiguous create failure. Deliberately NOT a retry: it
    only removes paid capacity that may have been created, and never issues a
    second create.
    """

    receipts: list[dict[str, Any]] = []
    for pod_id in find_pods_by_name(api_key=api_key, name=name):
        receipt = delete_and_prove_absence(client, pod_id)
        receipt["reconciliation"] = "ambiguous_create_orphan"
        receipts.append(receipt)
        if receipts_dir is not None:
            _write_receipt(
                receipts_dir, f"builder-orphan-{pod_id}.json", receipt
            )
    return receipts


def open_builder_session(
    *,
    client: RunPodBuilderClient,
    spec: BuilderPodSpec,
    budget: AuthorizedSpendBudget,
    receipts_dir: Path | None = None,
    ready_timeout_seconds: float = _READY_TIMEOUT_SECONDS,
    api_key: str | None = None,
) -> BuilderSession:
    """Create a builder Pod and return it only once it is verifiably ready.

    On any failure after creation the Pod is deleted and its absence proven
    before the error propagates, so an aborted session cannot leave paid
    capacity running.
    """

    try:
        create_receipt = client.create(spec, budget=budget)
    except BaseException:
        # An ambiguous create: the provider may have created paid capacity even
        # though the call raised (measured: HTTP 500 alongside a real Pod). The
        # id is unknown here, so reconcile by the requested name and delete
        # anything that matched. This removes capacity; it never re-creates it.
        if api_key:
            reconcile_orphans_by_name(
                client, api_key=api_key, name=spec.name, receipts_dir=receipts_dir
            )
        raise

    pod_id = str(create_receipt["pod_id"])

    try:
        ready_receipt = _poll_until_ready(
            client,
            spec,
            pod_id=pod_id,
            timeout_seconds=ready_timeout_seconds,
            api_key=api_key,
        )
    except BaseException:
        absence = delete_and_prove_absence(client, pod_id)
        if receipts_dir is not None:
            _write_receipt(receipts_dir, f"builder-absence-{pod_id}.json", absence)
        raise

    if receipts_dir is not None:
        _write_receipt(receipts_dir, f"builder-create-{pod_id}.json", create_receipt)
        _write_receipt(receipts_dir, f"builder-ready-{pod_id}.json", ready_receipt)

    return BuilderSession(
        pod_id=pod_id,
        public_ip=str(ready_receipt.get("public_ip", "")),
        ssh_port=int(ready_receipt.get("ssh_port", 0) or 0),
        create_receipt=create_receipt,
        ready_receipt=ready_receipt,
    )


def _write_receipt(directory: Path, name: str, payload: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def build_builder_spec(
    *,
    name: str,
    base_image_digest: str,
    gpu_type: str,
    public_key: str,
    allocation_id: str,
    maximum_hourly_rate_usd: Decimal | str,
    maximum_runtime_hours: Decimal | str,
    container_disk_gb: int = 300,
) -> BuilderPodSpec:
    return BuilderPodSpec(
        name=name,
        image_name=base_image_digest,
        gpu_type=gpu_type,
        public_key=public_key,
        allocation_id=allocation_id,
        maximum_hourly_rate_usd=Decimal(str(maximum_hourly_rate_usd)),
        maximum_runtime_hours=Decimal(str(maximum_runtime_hours)),
        container_disk_gb=container_disk_gb,
    )
