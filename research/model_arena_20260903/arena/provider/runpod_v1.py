"""RunPod REST **v1** pods client — the bootstrap-mode creation path (D2).

ARENA_CONTRACT section 11 D2, verified on 2026-09-03: REST v2's
``CreatePodRequest`` carries only ``args`` ("arguments passed to the container
entrypoint"), so it cannot override an image ENTRYPOINT. A bootstrap pod on
``vllm/vllm-openai`` (whose ENTRYPOINT is the vLLM server) therefore cannot be
created through v2 at all. REST v1 -- deprecated but live for this campaign's
key -- accepts ``dockerEntrypoint`` and ``dockerStartCmd`` on
``PodCreateInput``, and that is the only reason this module exists.

Consequences that are contract, not taste:

- **Bootstrap only.** Baked images keep v2 (:mod:`arena.provider.runpod_pods`).
  This client refuses a baked spec so the two paths cannot drift into each
  other by accident.
- **One start command element.** ``dockerStartCmd`` is
  ``[render_start_cmd(model_key, bundle_sha256)]`` -- exactly one string, from
  lane B2's template, with the bundle digest pinned inside it. A tampered or
  wrong bundle never starts.
- **The presigned URL is never written down whole.** The redacted payload
  reduces ``ARENA_BUNDLE_URL`` to ``host/object-key``: enough to audit which
  object a pod was pointed at, with no signature to replay.
- **Explicit User-Agent.** Cloudflare in front of the RunPod APIs answers 403
  (error 1010) to the default Python ``urllib`` agent. Every request here sets
  one.
- **The host CUDA floor is sent, not assumed.** ``allowedCudaVersions`` carries
  the versions the runtime's base image can run on. Without it RunPod placed a
  CUDA 12.9 image on a host reporting 12.8 and the pod died in
  ``torch._C._cuda_init`` with error 804, already billing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType, TracebackType
from typing import Any, Final, Self
from urllib.parse import urlsplit

import httpx

from arena.constants import CAMPAIGN_ID
from arena.provider.runpod_pods import (
    CAMPAIGN_ENV_KEY,
    REDACTED_ENV_KEYS,
    PodSpec,
    PriceSnapshot,
    ProviderReceipt,
    RunPodClientError,
    RunPodProtocolError,
    _is_request_rejected,
    _optional_string,
    _require_int,
    _require_list,
    _require_mapping,
    _require_pod_id,
    _require_string,
    is_campaign_pod_name,
)
from arena.provider.safety import canonical_sha256, timestamp_slug, utc_now_iso, write_json_atomic
from arena.provider.secrets import Secret

__all__ = [
    "MANAGEMENT_BASE_URL_V1",
    "USER_AGENT",
    "PodV1",
    "RunPodV1Client",
    "bundle_url_reference",
    "render_start_cmd",
    "v1_create_payload",
    "v1_redacted_payload",
]

MANAGEMENT_BASE_URL_V1: Final = "https://rest.runpod.io/v1"

# Cloudflare returns 403 error 1010 to the default Python User-Agent on the
# RunPod hosts (observed 2026-09-03). This value is sent on every request.
USER_AGENT: Final = f"tavonel-arena/1 (+{CAMPAIGN_ID})"

DESIRED_STATUSES: Final = ("RUNNING", "EXITED", "TERMINATED")
# v1 answers a successful DELETE with 204 No Content and a stop with 200; some
# deployments answer either with 202 Accepted. All three mean the request was
# taken, and none of them is a refusal (observed 2026-09-03: a 204 delete was
# logged as "delete_pod refused" while the pod was already gone).
TEARDOWN_STATUSES: Final = (200, 202, 204)
LIVE_DESIRED_STATUSES: Final = frozenset({"RUNNING"})
# ARENA_CONTRACT 11.5 D29: a plain -c shell, not a login shell. Nothing in
# the start command needs a profile sourced, and a login shell can reset the
# image PATH out from under the runtime the base image installed.
BOOTSTRAP_ENTRYPOINT: Final = ("/bin/bash", "-c")


def render_start_cmd(model_key: str, bundle_sha256: str) -> str:
    """Lane B2's ``arena.worker.bundle.render_start_cmd``, called verbatim.

    B1 never writes the start command itself (ARENA_CONTRACT section 11.3(1):
    "B2 owns the text"). If B2's function is not importable the create refuses
    rather than substituting a locally invented script -- a bootstrap command
    this lane made up would install a runtime nobody reviewed.
    """

    try:
        from arena.worker import bundle
    except ImportError as exc:  # pragma: no cover - lane B2 owns the module
        raise RunPodClientError(
            "arena.worker.bundle is not importable; the bootstrap start command "
            "comes from lane B2 and is never improvised here"
        ) from exc
    renderer = getattr(bundle, "render_start_cmd", None)
    if renderer is None:
        raise RunPodClientError(
            "arena.worker.bundle.render_start_cmd is absent (ARENA_CONTRACT 11.3(1)); "
            "lane B2 owns the bootstrap start command text"
        )
    command = renderer(model_key, bundle_sha256)
    if not isinstance(command, str) or not command.strip():
        raise RunPodClientError("render_start_cmd did not return a non-empty command string")
    if bundle_sha256 not in command:
        raise RunPodClientError(
            "the rendered start command does not pin the bundle sha256; refusing to start "
            "a pod that would accept any bundle"
        )
    return command


def bundle_url_reference(url: str) -> str:
    """``host/object-key`` for a presigned URL. Receipt-safe by construction.

    The query string holds the signature, so it is dropped entirely; what
    remains identifies which object a pod was pointed at, which is exactly what
    an audit needs and exactly what a replay cannot use.
    """

    parts = urlsplit(url)
    if not parts.hostname:
        raise RunPodClientError("a presigned bundle URL must carry a host")
    key = parts.path.lstrip("/")
    return f"{parts.hostname}/{key}" if key else parts.hostname


def v1_create_payload(
    spec: PodSpec,
    *,
    gpu_type_ids: Sequence[str],
    start_command: str,
) -> dict[str, object]:
    """``PodCreateInput`` for a bootstrap pod (ARENA_CONTRACT section 11 D2).

    ``gpu_type_ids`` is whichever slice of the spec's priority list this request
    is for -- ``gpuTypePriority`` is ``custom``, so v1 rents in the order given.
    :meth:`RunPodV1Client.create_pod` walks the list one entry at a time so the
    pod that answered names its own GPU type; a dry run shows the whole list in
    one payload, which is the request the provider would rent from.
    """

    if spec.runtime_mode != "bootstrap":
        raise RunPodClientError("REST v1 is the bootstrap path; a baked image is created on v2")
    if not gpu_type_ids:
        raise RunPodClientError("at least one gpuTypeId is required")
    unknown = [gpu for gpu in gpu_type_ids if gpu not in spec.gpu_type_ids]
    if unknown:
        raise RunPodClientError(f"gpu types {unknown} are not in the spec's priority list")
    if not start_command.strip():
        raise RunPodClientError("a bootstrap pod needs a start command")
    payload: dict[str, object] = {
        "name": spec.name,
        "imageName": spec.image_name,
        "gpuTypeIds": list(gpu_type_ids),
        "gpuTypePriority": "custom",
        "gpuCount": spec.gpu_count,
        "cloudType": spec.cloud_type,
        "containerDiskInGb": spec.container_disk_gb,
        "volumeInGb": spec.volume_gb,
        "volumeMountPath": spec.network_volume_path,
        "ports": list(spec.ports),
        "env": spec.env(),
        "dockerEntrypoint": list(BOOTSTRAP_ENTRYPOINT),
        "dockerStartCmd": [start_command],
    }
    if spec.allowed_cuda_versions:
        # ``PodCreateInput.allowedCudaVersions`` (OpenAPI snapshot 2026-09-03):
        # "a list of acceptable CUDA versions on the Pod. If not set, any CUDA
        # version is acceptable." Unset is what put pod 3xag0y00rgoj4n's CUDA
        # 12.9 image on a host reporting 12.8. The key is omitted only when the
        # spec carries no constraint at all, never sent empty -- an empty list
        # states the same "any host will do" the incident was caused by.
        payload["allowedCudaVersions"] = list(spec.allowed_cuda_versions)
    if spec.data_center_ids:
        payload["dataCenterIds"] = list(spec.data_center_ids)
        payload["dataCenterPriority"] = "custom"
    if spec.network_volume_id is not None:
        payload["networkVolumeId"] = spec.network_volume_id
    return payload


def v1_redacted_payload(
    spec: PodSpec,
    *,
    gpu_type_ids: Sequence[str],
    start_command: str,
) -> dict[str, object]:
    """The payload as it is written into a receipt and the pod ledger."""

    payload = v1_create_payload(spec, gpu_type_ids=gpu_type_ids, start_command=start_command)
    payload["env"] = _redact_env(spec)
    return payload


def _redact_env(spec: PodSpec) -> dict[str, str]:
    redacted: dict[str, str] = {}
    for key, value in sorted(spec.env().items()):
        if key == "ARENA_BUNDLE_URL":
            redacted[key] = bundle_url_reference(value)
        elif key in REDACTED_ENV_KEYS:
            redacted[key] = "<redacted>"
        else:
            redacted[key] = value
    return redacted


@dataclass(frozen=True, slots=True)
class PodV1:
    """One pod as REST v1 reports it. ``desiredStatus``, not ``status``."""

    pod_id: str
    name: str
    desired_status: str
    image: str
    cost_usd_per_hour: float
    data_center_id: str | None
    gpu_type_id: str | None
    gpu_count: int
    machine_id: str | None
    last_started_at: str | None
    container_disk_gb: int | None
    volume_gb: int | None
    docker_entrypoint: tuple[str, ...]
    docker_start_cmd_element_count: int
    env: Mapping[str, str]
    # The host's CUDA version as the v1 record reports it. The 2026-09-03
    # OpenAPI snapshot documents no such field on ``Pod``, but the live record
    # for pod 3xag0y00rgoj4n carried ``cudaVersion: "12.8"`` -- the value that
    # explained the CUDA 804 death. It is read where it is found and left
    # ``None`` when it is not; nothing is inferred from the GPU type. It is
    # last and defaulted because it is the one v1 field the contract does not
    # promise, and every existing construction predates it.
    cuda_version: str | None = None

    @property
    def campaign_id(self) -> str | None:
        return self.env.get(CAMPAIGN_ENV_KEY)

    @property
    def model_key(self) -> str | None:
        return self.env.get("ARENA_MODEL_KEY")

    @property
    def is_live(self) -> bool:
        return self.desired_status in LIVE_DESIRED_STATUSES

    def belongs_to(self, campaign_id: str) -> bool:
        """D24: the campaign env tag **or** the arena pod-name prefix."""

        return self.campaign_id == campaign_id or is_campaign_pod_name(self.name)

    def to_summary(self) -> dict[str, object]:
        """Receipt-safe projection. Env values are dropped; only names remain.

        ``dockerStartCmd`` is reported as an element *count*, never as text: a
        pod created by another operator can carry anything in there, and this
        summary is written to disk.
        """

        return {
            "provider_api_version": "v1",
            "pod_id": self.pod_id,
            "name": self.name,
            "desired_status": self.desired_status,
            "image": self.image,
            "cost_usd_per_hour": self.cost_usd_per_hour,
            "data_center_id": self.data_center_id,
            "gpu_type_id": self.gpu_type_id,
            "gpu_count": self.gpu_count,
            "cuda_version": self.cuda_version,
            "machine_id": self.machine_id,
            "last_started_at": self.last_started_at,
            "container_disk_gb": self.container_disk_gb,
            "volume_gb": self.volume_gb,
            "docker_entrypoint": list(self.docker_entrypoint),
            "docker_start_cmd_elements": self.docker_start_cmd_element_count,
            "env_names": sorted(self.env),
            "campaign_id": self.campaign_id,
            "model_key": self.model_key,
        }


#: D60: after a 5xx on create, how long to wait before the second re-list by
#: name. A pod the provider did create usually lists within seconds; the pause
#: keeps the walk from renting a duplicate behind a slow-to-appear one.
AMBIGUOUS_CREATE_RECHECK_SECONDS: Final = 10.0


class RunPodV1Client:
    """REST v1 pods. Bootstrap creation, plus read/stop/delete on either API."""

    def __init__(
        self,
        *,
        key: Secret,
        execute: bool = False,
        base_url: str = MANAGEMENT_BASE_URL_V1,
        campaign_id: str = CAMPAIGN_ID,
        receipts_dir: Path | None = None,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        ambiguous_recheck_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not base_url.startswith("https://"):
            raise RunPodClientError("the provider base URL must be https")
        self._key = key
        self.execute = execute
        self.base_url = base_url.rstrip("/")
        self.campaign_id = campaign_id
        self.receipts_dir = receipts_dir
        self._receipts: list[ProviderReceipt] = []
        self._ambiguous_recheck_sleep = ambiguous_recheck_sleep
        self._http: httpx.Client | None = None
        if execute:
            self._http = httpx.Client(
                timeout=httpx.Timeout(timeout_seconds),
                follow_redirects=False,
                transport=transport,
            )

    def __repr__(self) -> str:
        return f"RunPodV1Client(base_url={self.base_url!r}, execute={self.execute})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._http is not None:
            self._http.close()
            self._http = None

    @property
    def receipts(self) -> tuple[ProviderReceipt, ...]:
        return tuple(self._receipts)

    # ---------------------------------------------------------------- reads

    def list_pods(self) -> tuple[PodV1, ...] | ProviderReceipt:
        url = f"{self.base_url}/pods"
        if not self.execute:
            return self._dry("list_pods", "GET", url, None)
        body, _ = self._request("GET", url, expected_status=200)
        pods = tuple(_parse_pod_v1(item) for item in _pod_list(body))
        self._record("list_pods", "GET", url, None, 200, {"pod_count": len(pods)})
        return pods

    def get_pod(
        self,
        pod_id: str,
        *,
        persist_receipt: bool | Callable[[PodV1 | None], bool] = True,
    ) -> PodV1 | ProviderReceipt | None:
        """Read one pod.

        ``persist_receipt`` may be ``False``, or a predicate taking the pod the
        read produced (``None`` for a 404). Either way the receipt is still
        *built*, so the secret guard still runs over it; only the keeping is
        skipped. A predicate is what lets the caller decide with the answer in
        hand without paying for a second request.

        This exists for the readiness poll: it reads the pod every twenty
        seconds for up to forty-five minutes, and 136 identical
        ``desired_status: RUNNING`` receipts on disk bury the handful that
        record an actual change. See the driver for the policy.
        """

        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}"
        if not self.execute:
            return self._dry("get_pod", "GET", url, None, persist=_keep(persist_receipt, None))
        body, _ = self._request("GET", url, expected_status=200, allow_not_found=True)
        if body is None:
            self._record(
                "get_pod",
                "GET",
                url,
                None,
                404,
                {"pod_id": pod_id, "present": False},
                persist=_keep(persist_receipt, None),
            )
            return None
        pod = _parse_pod_v1(body)
        self._record(
            "get_pod",
            "GET",
            url,
            None,
            200,
            pod.to_summary(),
            persist=_keep(persist_receipt, pod),
        )
        return pod

    # --------------------------------------------------------------- writes

    def create_pod(
        self,
        spec: PodSpec,
        *,
        price_snapshot: PriceSnapshot | None = None,
    ) -> PodV1 | ProviderReceipt:
        """Create one bootstrap pod, or adopt the live pod with the same name.

        The GPU priority list is walked one type at a time, exactly as the v2
        client does, and each attempt is receipted. v1 *can* take the whole
        list with ``gpuTypePriority: "custom"`` and rent in order, and that is
        still what a dry run shows; but once ``allowedCudaVersions`` filters
        the hosts, how deep the provider's own walk goes is not something the
        OpenAPI document states. Walking here makes the fallback observable
        instead of assumed, and leaves the created pod's GPU type named in a
        receipt rather than inferred from the priority list.

        Between attempts the pod list is re-read, so a rejected request can
        never leave a pod behind that a later attempt duplicates. A 5xx or a
        transport failure is ambiguous -- the pod may exist and be billing --
        so it is answered by two re-lists by name (the second after a bounded
        pause, D60) and the walk continues only when both find nothing; the
        next attempt re-lists again before it sends. Real evidence for D60:
        hpd_parsing 2026-09-03 got HTTP 500 twice on the first, out-of-stock
        pool entry and never reached the A100 entries behind it.
        """

        if spec.runtime_mode != "bootstrap":
            raise RunPodClientError(
                "REST v1 creation is the bootstrap path only; a baked image goes through "
                "arena.provider.runpod_pods (REST v2)"
            )
        if spec.bundle_sha256 is None:
            raise RunPodClientError("a bootstrap pod needs the bundle sha256 to pin its start cmd")
        url = f"{self.base_url}/pods"
        command = render_start_cmd(spec.model_key, spec.bundle_sha256)
        redacted = v1_redacted_payload(
            spec, gpu_type_ids=spec.gpu_type_ids, start_command=command
        )
        if price_snapshot is not None:
            # MP section 13.2: quote the exact price row on the decision.
            price_snapshot.row(spec.gpu_type_ids[0])
        if not self.execute:
            return self._dry(
                "create_pod",
                "POST",
                url,
                redacted,
                extra={
                    "provider_api_version": "v1",
                    "gpu_priority": list(spec.gpu_type_ids),
                    "docker_start_cmd_elements": 1,
                    "bundle_sha256": spec.bundle_sha256,
                    "price_snapshot_sha256": (
                        None if price_snapshot is None else price_snapshot.snapshot_sha256()
                    ),
                },
            )

        existing = self._find_existing(spec.name)
        if existing is not None:
            self._record(
                "create_pod", "POST", url, None, None, {"adopted": True, **existing.to_summary()}
            )
            return existing

        last_error: RunPodClientError | None = None
        for index, gpu_type_id in enumerate(spec.gpu_type_ids):
            if index > 0:
                # Confirm the rejected attempt really created nothing.
                adopted = self._find_existing(spec.name)
                if adopted is not None:
                    self._record(
                        "create_pod",
                        "POST",
                        url,
                        None,
                        None,
                        {"adopted": True, "attempt": index + 1, **adopted.to_summary()},
                    )
                    return adopted
            attempted = (gpu_type_id,)
            payload = v1_create_payload(spec, gpu_type_ids=attempted, start_command=command)
            attempt_redacted = v1_redacted_payload(
                spec, gpu_type_ids=attempted, start_command=command
            )
            try:
                body, _ = self._request("POST", url, expected_status=201, payload=payload)
            except RunPodClientError as exc:
                # A rejected request creates nothing; an *ambiguous* one (5xx,
                # transport failure) may have created a pod that is already
                # billing (ARENA_CONTRACT 11.5 D24). Both are answered the same
                # way -- re-list by name and campaign -- because one read is far
                # cheaper than either a duplicate pod or an orphan.
                adopted = self._find_existing(spec.name)
                if adopted is not None:
                    self._record(
                        "create_pod",
                        "POST",
                        url,
                        None,
                        None,
                        {
                            "adopted": True,
                            "attempt": index + 1,
                            "adopted_after": (
                                "rejected create"
                                if _is_request_rejected(exc)
                                else "ambiguous create"
                            ),
                            **adopted.to_summary(),
                        },
                    )
                    return adopted
                ambiguous = not _is_request_rejected(exc)
                if ambiguous:
                    # D60: give a pod the provider may have created time to list,
                    # then look once more before renting from the next pool entry.
                    self._ambiguous_recheck_sleep(AMBIGUOUS_CREATE_RECHECK_SECONDS)
                    adopted = self._find_existing(spec.name)
                    if adopted is not None:
                        self._record(
                            "create_pod",
                            "POST",
                            url,
                            None,
                            None,
                            {
                                "adopted": True,
                                "attempt": index + 1,
                                "adopted_after": "ambiguous create, second re-list",
                                **adopted.to_summary(),
                            },
                        )
                        return adopted
                self._record(
                    "create_pod",
                    "POST",
                    url,
                    None,
                    None,
                    {
                        "created": False,
                        "attempt": index + 1,
                        "gpu_type_ids": list(attempted),
                        "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                        "refused": str(exc),
                        "ambiguous": ambiguous,
                        "re_listed_by_name": 2 if ambiguous else 1,
                    },
                )
                last_error = exc
                continue
            pod = _parse_pod_v1(body)
            self._record(
                "create_pod",
                "POST",
                url,
                attempt_redacted,
                201,
                {
                    "adopted": False,
                    "created": True,
                    "attempt": index + 1,
                    "gpu_type_ids": list(attempted),
                    "allowed_cuda_versions": list(spec.allowed_cuda_versions),
                    "bundle_sha256": spec.bundle_sha256,
                    "price_snapshot_sha256": (
                        None if price_snapshot is None else price_snapshot.snapshot_sha256()
                    ),
                    **pod.to_summary(),
                },
            )
            return pod
        if last_error is not None:
            raise last_error
        raise RunPodClientError("the GPU priority list is empty; nothing was attempted")

    def stop_pod(self, pod_id: str) -> ProviderReceipt | None:
        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}/stop"
        if not self.execute:
            return self._dry("stop_pod", "POST", url, None)
        _, status = self._request(
            "POST", url, expected_status=TEARDOWN_STATUSES, payload={}, allow_empty=True
        )
        self._record("stop_pod", "POST", url, None, status, {"pod_id": pod_id})
        return None

    def delete_pod(self, pod_id: str) -> ProviderReceipt | None:
        _require_pod_id(pod_id)
        url = f"{self.base_url}/pods/{pod_id}"
        if not self.execute:
            return self._dry("delete_pod", "DELETE", url, None)
        _, status = self._request(
            "DELETE",
            url,
            expected_status=TEARDOWN_STATUSES,
            allow_empty=True,
            allow_not_found=True,
        )
        self._record("delete_pod", "DELETE", url, None, status, {"pod_id": pod_id})
        return None

    # -------------------------------------------------------------- internals

    def _find_existing(self, name: str) -> PodV1 | None:
        """The live pod with this name, or ``None``; a foreign one refuses.

        Same rule as REST v2: our name plus another campaign's env tag is
        ambiguous, and neither adopting nor duplicating is safe (D24).
        """

        listed = self.list_pods()
        if isinstance(listed, ProviderReceipt):  # pragma: no cover - execute guarded above
            return None
        for pod in listed:
            if pod.name != name or not pod.is_live:
                continue
            if pod.campaign_id == self.campaign_id:
                return pod
            raise RunPodClientError(
                f"a live pod named {name!r} already exists but carries campaign "
                f"{pod.campaign_id!r}, not {self.campaign_id!r}; refusing to adopt it or to "
                "create a second pod under the same name (ARENA_CONTRACT 11.5 D24)"
            )
        return None

    def campaign_pods(self, *, live_only: bool = False) -> tuple[PodV1, ...]:
        """Every pod this campaign owns by env tag or by name prefix (D24).

        ``live_only`` follows v1's ``desiredStatus``: only ``RUNNING`` is live.
        Cleanup deliberately does **not** use it -- D20 counts an ``EXITED``
        pod as not cleaned up until it is gone from the listing entirely.
        """

        listed = self.list_pods()
        if isinstance(listed, ProviderReceipt):
            return ()
        return tuple(
            pod
            for pod in listed
            if pod.belongs_to(self.campaign_id) and (pod.is_live or not live_only)
        )

    def _headers(self) -> dict[str, str]:
        # The single audited place the key is revealed.
        return {
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Authorization": f"Bearer {self._key.reveal()}",
        }

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected_status: int | tuple[int, ...],
        payload: Mapping[str, object] | None = None,
        allow_not_found: bool = False,
        allow_empty: bool = False,
    ) -> tuple[object | None, int]:
        """Send one request; return the parsed body and the status that carried it.

        The status comes back because more than one code can mean success:
        v1 answers ``DELETE /pods/{id}`` with **204 No Content**, and the first
        live run recorded that as ``delete_pod refused`` while the pod was in
        fact already gone. Accepting only one code turned a successful teardown
        into a receipt that says the opposite.
        """

        if not self.execute or self._http is None:
            raise RunPodClientError("provider access is disabled; pass execute=True")
        accepted = (expected_status,) if isinstance(expected_status, int) else expected_status
        headers = self._headers()
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            response = self._http.request(method, url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise RunPodClientError(
                f"RunPod v1 transport failure for {method} {url}: {type(exc).__name__}"
            ) from None
        if allow_not_found and response.status_code == 404:
            return None, 404
        if response.status_code not in accepted:
            raise RunPodClientError(
                f"RunPod v1 returned HTTP {response.status_code} for {method} {url}; body withheld"
            )
        if allow_empty and not response.content.strip():
            return None, response.status_code
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        if content_type != "application/json":
            raise RunPodProtocolError(f"RunPod v1 {method} {url} did not return application/json")
        try:
            parsed: object = response.json()
        except ValueError:
            raise RunPodProtocolError(f"RunPod v1 {method} {url} returned invalid JSON") from None
        return parsed, response.status_code

    def _dry(
        self,
        action: str,
        method: str,
        url: str,
        payload: object | None,
        *,
        extra: Mapping[str, object] | None = None,
        persist: bool = True,
    ) -> ProviderReceipt:
        summary: dict[str, object] = {"provider_api_version": "v1", "would_send": payload}
        if extra:
            summary.update(dict(extra))
        receipt = ProviderReceipt(
            action=action,
            method=method,
            url=url,
            mode="dry_run",
            request_sha256=canonical_sha256({"method": method, "url": url, "payload": payload}),
            ts=utc_now_iso(),
            status_code=None,
            summary=MappingProxyType(summary),
        )
        self._append(receipt, persist=persist)
        return receipt

    def _record(
        self,
        action: str,
        method: str,
        url: str,
        payload: object | None,
        status_code: int | None,
        summary: Mapping[str, object],
        *,
        persist: bool = True,
    ) -> ProviderReceipt:
        merged: dict[str, object] = {"provider_api_version": "v1"}
        merged.update(dict(summary))
        receipt = ProviderReceipt(
            action=action,
            method=method,
            url=url,
            mode="live",
            request_sha256=canonical_sha256({"method": method, "url": url, "payload": payload}),
            ts=utc_now_iso(),
            status_code=status_code,
            summary=MappingProxyType(merged),
        )
        self._append(receipt, persist=persist)
        return receipt

    def _append(self, receipt: ProviderReceipt, *, persist: bool = True) -> None:
        record = receipt.to_dict()  # raises SecretLeak before anything is kept
        if not persist:
            # The guard above still ran; only the keeping is skipped.
            return
        self._receipts.append(receipt)
        if self.receipts_dir is not None:
            short = receipt.request_sha256[:12]
            target = self.receipts_dir / f"v1-{receipt.action}-{timestamp_slug()}-{short}.json"
            write_json_atomic(target, record, context=f"provider receipt v1 {receipt.action}")


def _keep(decision: bool | Callable[[PodV1 | None], bool], pod: PodV1 | None) -> bool:
    return bool(decision(pod)) if callable(decision) else bool(decision)


# ------------------------------------------------------------------ parsing


def _pod_list(body: object) -> list[Any]:
    """v1 ``GET /pods`` answers with an array; some deployments wrap it."""

    if isinstance(body, list):
        return body
    raw = _require_mapping(body, "listPodsV1")
    for key in ("pods", "data"):
        value = raw.get(key)
        if isinstance(value, list):
            return value
    raise RunPodProtocolError("listPodsV1 is neither an array nor an object carrying pods/data")


def _parse_pod_v1(value: object) -> PodV1:
    raw = _require_mapping(value, "podV1")
    desired = _require_string(raw, "desiredStatus", "podV1")
    if desired not in DESIRED_STATUSES:
        raise RunPodProtocolError(f"podV1.desiredStatus {desired!r} is outside the pinned v1 enum")
    # ARENA_CONTRACT 11.5 D24: no env means the record cannot say whose pod
    # this is. That is a protocol error, not an empty environment.
    if "env" not in raw or raw.get("env") is None:
        raise RunPodProtocolError(
            "podV1 record carries no env; campaign membership and model key cannot be "
            "established from it (ARENA_CONTRACT 11.5 D24)"
        )
    env: dict[str, str] = {}
    for key, item in _require_mapping(raw.get("env"), "podV1.env").items():
        if not isinstance(key, str) or not isinstance(item, str):
            raise RunPodProtocolError("podV1.env must map strings to strings")
        env[key] = item
    gpu_raw = raw.get("gpu")
    gpu_type_id: str | None = None
    gpu_count = 0
    if isinstance(gpu_raw, Mapping):
        gpu_type_id = _optional_string(gpu_raw, "id", "podV1.gpu")
        count = gpu_raw.get("count")
        gpu_count = count if isinstance(count, int) and not isinstance(count, bool) else 0
    machine_raw = raw.get("machine")
    data_center_id: str | None = None
    machine_id = _optional_string(raw, "machineId", "podV1")
    cuda_version = _optional_string(raw, "cudaVersion", "podV1")
    if isinstance(machine_raw, Mapping):
        data_center_id = _optional_string(machine_raw, "dataCenterId", "podV1.machine")
        if gpu_type_id is None:
            gpu_type_id = _optional_string(machine_raw, "gpuTypeId", "podV1.machine")
        if cuda_version is None:
            cuda_version = _optional_string(machine_raw, "cudaVersion", "podV1.machine")
    cost = raw.get("costPerHr", raw.get("adjustedCostPerHr"))
    return PodV1(
        pod_id=_require_string(raw, "id", "podV1"),
        name=_require_string(raw, "name", "podV1"),
        desired_status=desired,
        image=_optional_string(raw, "image", "podV1") or "",
        cost_usd_per_hour=_coerce_rate(cost),
        data_center_id=data_center_id,
        gpu_type_id=gpu_type_id,
        gpu_count=gpu_count,
        cuda_version=cuda_version,
        machine_id=machine_id,
        last_started_at=_optional_string(raw, "lastStartedAt", "podV1"),
        container_disk_gb=(
            _require_int(raw, "containerDiskInGb", "podV1")
            if raw.get("containerDiskInGb") is not None
            else None
        ),
        volume_gb=(
            _require_int(raw, "volumeInGb", "podV1") if raw.get("volumeInGb") is not None else None
        ),
        docker_entrypoint=tuple(
            str(item) for item in _require_list(raw.get("dockerEntrypoint", []), "podV1.entrypoint")
        ),
        docker_start_cmd_element_count=len(
            _require_list(raw.get("dockerStartCmd", []), "podV1.dockerStartCmd")
        ),
        env=MappingProxyType(env),
    )


def _coerce_rate(value: object) -> float:
    """v1 reports ``costPerHr`` as a number or a currency-formatted string."""

    if isinstance(value, bool) or value is None:
        raise RunPodProtocolError("podV1.costPerHr is missing")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            raise RunPodProtocolError("podV1.costPerHr is not a number") from None
    raise RunPodProtocolError("podV1.costPerHr is not a number")
