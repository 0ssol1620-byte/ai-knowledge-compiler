"""Cleanup verification — masterplan section 15.14, ARENA_CONTRACT 11.5 D20.

The rule the previous campaign broke: "삭제 요청을 보냈다" is not cleanup.

Three things follow from that, and all three are the reason this module is not
one ``list_pods`` call:

- **Both APIs.** Bootstrap pods are created through REST v1 and baked pods
  through v2 (D2). A pod created on v1 that v2 does not return is still
  billing. So both listings are read, and a pod is cleaned up only when it is
  gone from *both*.
- **Both witnesses of ownership.** A pod is this campaign's if its
  ``ARENA_CAMPAIGN_ID`` env says so **or** if its name carries the
  ``arena-…-20260903v1`` shape (D24). A pod whose env the provider dropped
  must not become somebody else's problem.
- **EXITED is not gone.** RunPod keeps a stopped pod's record, and its disk,
  until the pod is deleted. D20 counts an ``EXITED`` pod as not cleaned up
  until it disappears from both listings entirely.

``verify_cleanup`` only observes. ``clean_up_campaign`` observes *and* deletes,
and is the one the ``cleanup-verify --execute`` command runs. A dry run lists
what it would delete and touches nothing.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from arena.constants import CAMPAIGN_ID
from arena.provider.runpod_pods import Pod, ProviderReceipt, RunPodClientError, RunPodPodsClient
from arena.provider.runpod_v1 import PodV1, RunPodV1Client
from arena.provider.safety import utc_now_iso, write_json_atomic

__all__ = [
    "DEFAULT_ATTEMPTS",
    "DEFAULT_POLL_SECONDS",
    "CleanupError",
    "CleanupResult",
    "ObservedPod",
    "clean_up_campaign",
    "verify_cleanup",
]

DEFAULT_ATTEMPTS: Final = 10
DEFAULT_POLL_SECONDS: Final = 15.0


class CleanupError(RuntimeError):
    """Cleanup could not be verified."""


@dataclass(frozen=True, slots=True)
class ObservedPod:
    """One campaign pod as one API version reported it."""

    pod_id: str
    name: str
    status: str
    api_version: str
    matched_by: str  # "campaign_env" | "name_prefix"

    def to_dict(self) -> dict[str, object]:
        return {
            "pod_id": self.pod_id,
            "name": self.name,
            "status": self.status,
            "provider_api_version": self.api_version,
            "matched_by": self.matched_by,
        }


@dataclass(frozen=True, slots=True)
class CleanupResult:
    verified: bool
    attempts: int
    running_pod_count: int
    observed: tuple[str, ...]
    mode: str
    checked_at: str
    notes: tuple[str, ...] = field(default_factory=tuple)
    deleted: tuple[str, ...] = field(default_factory=tuple)
    delete_failures: tuple[str, ...] = field(default_factory=tuple)
    remaining: tuple[ObservedPod, ...] = field(default_factory=tuple)
    apis_read: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.cleanup_receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "verified": self.verified,
            "attempts": self.attempts,
            "running_pod_count": self.running_pod_count,
            "running_pod_ids": list(self.observed),
            "mode": self.mode,
            "checked_at": self.checked_at,
            "apis_read": list(self.apis_read),
            "deleted_pod_ids": list(self.deleted),
            "delete_failures": list(self.delete_failures),
            "remaining_pods": [pod.to_dict() for pod in self.remaining],
            "exited_counts_as_not_cleaned": True,
            "notes": list(self.notes),
        }


def _observe(
    *,
    v2_client: RunPodPodsClient | None,
    v1_client: RunPodV1Client | None,
    campaign_id: str,
) -> tuple[tuple[ObservedPod, ...], tuple[str, ...], tuple[str, ...]]:
    """Every campaign pod visible on either API, plus which APIs answered."""

    seen: dict[tuple[str, str], ObservedPod] = {}
    apis: list[str] = []
    problems: list[str] = []

    if v2_client is not None and v2_client.execute:
        try:
            listed = v2_client.list_pods()
        except RunPodClientError as exc:
            problems.append(f"REST v2 listing failed: {exc}")
        else:
            apis.append("v2")
            if not isinstance(listed, ProviderReceipt):
                for pod in listed:
                    if not pod.belongs_to(campaign_id):
                        continue
                    seen[(pod.pod_id, "v2")] = _from_v2(pod, campaign_id)

    if v1_client is not None and v1_client.execute:
        try:
            listed_v1 = v1_client.list_pods()
        except RunPodClientError as exc:
            problems.append(f"REST v1 listing failed: {exc}")
        else:
            apis.append("v1")
            if not isinstance(listed_v1, ProviderReceipt):
                for pod_v1 in listed_v1:
                    if not pod_v1.belongs_to(campaign_id):
                        continue
                    seen[(pod_v1.pod_id, "v1")] = _from_v1(pod_v1, campaign_id)

    return tuple(seen.values()), tuple(apis), tuple(problems)


def _from_v2(pod: Pod, campaign_id: str) -> ObservedPod:
    return ObservedPod(
        pod_id=pod.pod_id,
        name=pod.name,
        status=pod.status,
        api_version="v2",
        matched_by="campaign_env" if pod.campaign_id == campaign_id else "name_prefix",
    )


def _from_v1(pod: PodV1, campaign_id: str) -> ObservedPod:
    return ObservedPod(
        pod_id=pod.pod_id,
        name=pod.name,
        status=pod.desired_status,
        api_version="v1",
        matched_by="campaign_env" if pod.campaign_id == campaign_id else "name_prefix",
    )


def clean_up_campaign(
    *,
    receipt_path: Path,
    v2_client: RunPodPodsClient | None = None,
    v1_client: RunPodV1Client | None = None,
    campaign_id: str = CAMPAIGN_ID,
    max_attempts: int = DEFAULT_ATTEMPTS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] | None = None,
    delete: bool = True,
    poll: bool | None = None,
) -> CleanupResult:
    """List both APIs, delete every campaign pod, re-read until none remain.

    ``delete=False`` is the dry-run shape: it reports what it would delete and
    sends no write. ``verified`` is only ever ``True`` when a live listing
    actually came back empty on every API that answered -- a dry run cannot
    verify cleanup and never claims to.

    ``poll`` separates the two things ``delete=False`` was doing. A
    ``cleanup-verify`` dry run wants one listing and a report (``poll=False``);
    ``verify_cleanup`` is section 15.14's *re-read until zero pods* and keeps
    listing while a pod that was already asked to stop finishes disappearing
    (``poll=True``). Neither ever sends a write. The default follows ``delete``,
    which is what every existing caller meant.
    """

    if max_attempts < 1:
        raise CleanupError("cleanup verification needs at least one attempt")
    keep_polling = delete if poll is None else poll
    pause = sleep or _default_sleep
    live = (v2_client is not None and v2_client.execute) or (
        v1_client is not None and v1_client.execute
    )
    if not live:
        result = CleanupResult(
            verified=False,
            attempts=0,
            running_pod_count=-1,
            observed=(),
            mode="dry_run",
            checked_at=utc_now_iso(),
            notes=("dry run: the provider was not read, so cleanup is unverified",),
        )
        write_json_atomic(receipt_path, result.to_dict(), context="cleanup receipt")
        return result

    notes: list[str] = []
    deleted: list[str] = []
    failures: list[str] = []
    remaining: tuple[ObservedPod, ...] = ()
    apis: tuple[str, ...] = ()
    attempts = 0

    while attempts < max_attempts:
        attempts += 1
        remaining, apis, problems = _observe(
            v2_client=v2_client, v1_client=v1_client, campaign_id=campaign_id
        )
        notes.extend(problems)
        if problems:
            # An API that did not answer cannot witness "no pods". Refuse to
            # call that verified even if the other API came back empty.
            notes.append(
                "at least one API listing failed; cleanup cannot be verified from a "
                "partial view of the account"
            )
            break
        if not remaining:
            result = CleanupResult(
                verified=True,
                attempts=attempts,
                running_pod_count=0,
                observed=(),
                mode="live",
                checked_at=utc_now_iso(),
                notes=tuple(notes),
                deleted=tuple(deleted),
                delete_failures=tuple(failures),
                apis_read=apis,
            )
            write_json_atomic(receipt_path, result.to_dict(), context="cleanup receipt")
            return result

        exited = [pod for pod in remaining if pod.status in {"EXITED", "TERMINATED"}]
        notes.append(
            f"attempt {attempts}: {len(remaining)} campaign pod(s) still listed "
            f"({len(exited)} EXITED/TERMINATED, which is not cleaned up until the record "
            "is gone from both listings)"
        )
        if delete:
            for pod in remaining:
                try:
                    _delete(pod, v2_client=v2_client, v1_client=v1_client)
                except RunPodClientError as exc:
                    failures.append(f"{pod.pod_id} ({pod.api_version}): {exc}")
                else:
                    if pod.pod_id not in deleted:
                        deleted.append(pod.pod_id)
        elif not keep_polling:
            notes.append("dry run: no delete was sent")
            break
        if attempts < max_attempts:
            pause(poll_seconds)

    result = CleanupResult(
        verified=False,
        attempts=attempts,
        running_pod_count=len(remaining),
        observed=tuple(pod.pod_id for pod in remaining),
        mode="live",
        checked_at=utc_now_iso(),
        notes=(*notes, "cleanup NOT verified: campaign pods are still listed"),
        deleted=tuple(deleted),
        delete_failures=tuple(failures),
        remaining=remaining,
        apis_read=apis,
    )
    write_json_atomic(receipt_path, result.to_dict(), context="cleanup receipt")
    return result


def _delete(
    pod: ObservedPod,
    *,
    v2_client: RunPodPodsClient | None,
    v1_client: RunPodV1Client | None,
) -> None:
    """Stop then delete, on the API that reported the pod.

    Stop first because a pod deleted mid-inference can leave the provider
    reporting it for another polling interval; a stop that fails is not fatal
    -- the delete is what actually ends the billing, and it is attempted
    either way.
    """

    if pod.api_version == "v2" and v2_client is not None:
        with contextlib.suppress(RunPodClientError):
            v2_client.stop_pod(pod.pod_id)
        v2_client.delete_pod(pod.pod_id)
        return
    if pod.api_version == "v1" and v1_client is not None:
        with contextlib.suppress(RunPodClientError):
            v1_client.stop_pod(pod.pod_id)
        v1_client.delete_pod(pod.pod_id)
        return
    raise CleanupError(
        f"pod {pod.pod_id} was listed on REST {pod.api_version} but no client for that "
        "version was supplied"
    )


def verify_cleanup(
    client: RunPodPodsClient,
    *,
    receipt_path: Path,
    campaign_id: str = CAMPAIGN_ID,
    max_attempts: int = DEFAULT_ATTEMPTS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] | None = None,
    v1_client: RunPodV1Client | None = None,
) -> CleanupResult:
    """Observe only: poll until no campaign pod is listed. Deletes nothing."""

    return clean_up_campaign(
        receipt_path=receipt_path,
        v2_client=client,
        v1_client=v1_client,
        campaign_id=campaign_id,
        max_attempts=max_attempts,
        poll_seconds=poll_seconds,
        sleep=sleep,
        delete=False,
        poll=True,
    )


def _campaign_live_pods(pods: Sequence[Pod], campaign_id: str) -> tuple[Pod, ...]:
    return tuple(pod for pod in pods if pod.is_live and pod.belongs_to(campaign_id))


def _default_sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
