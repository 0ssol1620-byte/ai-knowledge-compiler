#!/usr/bin/env python3
"""SFIR10 transport: every rate decision is fed by observed response evidence.

Unlike SFIR9, this module both acquires the provider fields and owns the frozen
control flow that consumes them.  It never turns HTTP failure into an empty body:
a request either returns a validated JSON response or raises a typed operational
stop before traversal can mistake the stop for frontier exhaustion.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import sfir10_protocol as protocol

ALLOWED_SCHEME = "https"
ALLOWED_HOST = "api.github.com"
REDIRECT_STATUSES = frozenset({301, 302, 307, 308})
SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


class TransportStop(RuntimeError):
    """This root cannot be called exact; traversal must record STOPPED."""


class IdentityRefused(RuntimeError):
    """The roster identity could not be established; the root was never measured."""


class SegmentClose(RuntimeError):
    """The current provider window ended; durable state may resume later."""


class SegmentNotReady(RuntimeError):
    """A full declared provider window is not currently available."""


class MeasurementUnproven(RuntimeError):
    """Accounting or timing evidence is insufficient to seal a scientific result."""


@dataclass(frozen=True, slots=True)
class RateWindow:
    limit: int
    remaining: int
    used: int
    reset_epoch: int

    def as_dict(self) -> dict[str, int]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "used": self.used,
            "reset_epoch": self.reset_epoch,
        }


@dataclass(frozen=True, slots=True)
class Hop:
    logical_request_id: int
    hop_index: int
    requested_url: str
    status: int
    redirect_target_digest: str | None
    response_body_sha256: str
    provider_remaining_before: int
    provider_remaining_after: int
    provider_reset_epoch: int
    retry_after_seconds: int | None
    provider_charge_delta: int
    provider_request_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "logical_request_id": self.logical_request_id,
            "hop_index": self.hop_index,
            "requested_url": self.requested_url,
            "status": self.status,
            "redirect_target_digest": self.redirect_target_digest,
            "response_body_sha256": self.response_body_sha256,
            "provider_remaining_before": self.provider_remaining_before,
            "provider_remaining_after": self.provider_remaining_after,
            "provider_reset_epoch": self.provider_reset_epoch,
            "retry_after_seconds": self.retry_after_seconds,
            "provider_charge_delta": self.provider_charge_delta,
            "provider_request_id": self.provider_request_id,
        }


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    final_url: str
    body: dict[str, Any]
    network_hops: int
    provider_charged: int


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def _headers() -> dict[str, str]:
    result = {
        "User-Agent": "tavonel-sfir10/1.0",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _token()
    if token:
        result["Authorization"] = f"Bearer {token}"
    return result


def _int_header(headers: Any, name: str) -> int | None:
    value = headers.get(name) if headers is not None else None
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise MeasurementUnproven(f"{name}={value!r} is not an integer") from exc


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def require_target(url: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME or parts.hostname != ALLOWED_HOST:
        raise TransportStop(
            f"SFIR10 permits only {ALLOWED_SCHEME}://{ALLOWED_HOST}; refused {url!r}"
        )


def read_rate_window(opener: Any = None) -> RateWindow:
    """The one uncharged observation permitted at a segment boundary."""
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS GitHub endpoint
        protocol.RATE_LIMIT_ENDPOINT, headers=_headers()
    )
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            core = json.load(response)["resources"]["core"]
    except Exception as exc:
        raise SegmentNotReady(f"cannot read the provider window: {exc}") from exc
    return RateWindow(
        limit=int(core["limit"]),
        remaining=int(core["remaining"]),
        used=int(core["used"]),
        reset_epoch=int(core["reset"]),
    )


def require_full_window(window: RateWindow) -> None:
    if window.remaining < protocol.USABLE_CHARGE_PER_WINDOW:
        raise SegmentNotReady(
            f"provider remaining={window.remaining}, below the prospectively frozen "
            f"segment start floor {protocol.USABLE_CHARGE_PER_WINDOW}; no cohort request sent"
        )


class Transport:
    """GET-only, one-host client with cumulative segment/root charge enforcement."""

    def __init__(
        self,
        *,
        window: RateWindow,
        root_charges_already_spent: int = 0,
        opener: Any = None,
    ) -> None:
        require_full_window(window)
        self.window = window
        self._opener = opener
        self.logical_requests = 0
        self.network_hops = 0
        self.provider_charged = 0
        self.root_charged = int(root_charges_already_spent)
        self.current_root: str | None = None
        self.previous_remaining = window.remaining
        self.close_before_next = False
        self.hops: list[Hop] = []
        self.request_log: list[dict[str, Any]] = []

    def begin_root(self, host_uuid: str, cumulative_charges: int) -> None:
        self.current_root = str(host_uuid)
        self.root_charged = int(cumulative_charges)

    def _reserve(self) -> None:
        if self.close_before_next:
            raise SegmentClose("the previous response exhausted or closed the provider window")
        reserve = protocol.REQUEST_RESERVATION_CHARGES
        if self.provider_charged + reserve > protocol.USABLE_CHARGE_PER_WINDOW:
            raise SegmentClose(
                "another worst-case logical request would exceed the declared "
                "provider-window budget"
            )
        if (
            self.current_root is not None
            and self.root_charged + reserve > protocol.PER_ROOT_CHARGE_ALLOWANCE
        ):
            raise TransportStop(
                "another worst-case logical request would exceed the root's cumulative "
                "provider-charge allowance"
            )

    def _one_hop(self, url: str) -> tuple[int, Any, bytes, str | None]:
        # `get()` validates the URL immediately before this call; only HTTPS
        # api.github.com can reach `_one_hop`.
        request = urllib.request.Request(url, headers=_headers())  # noqa: S310
        opener = self._opener or urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=60) as response:
                return (
                    int(getattr(response, "status", 200) or 200),
                    response.headers,
                    response.read(),
                    response.headers.get("Location"),
                )
        except urllib.error.HTTPError as error:
            raw = error.read() if hasattr(error, "read") else b""
            return (
                int(error.code),
                error.headers,
                raw,
                error.headers.get("Location") if error.headers else None,
            )
        except Exception as exc:
            raise TransportStop(f"network request failed: {type(exc).__name__}: {exc}") from exc

    def _observe_hop(
        self,
        *,
        logical_id: int,
        hop_index: int,
        url: str,
        status: int,
        headers: Any,
        raw: bytes,
        location: str | None,
    ) -> Hop:
        remaining = _int_header(headers, "x-ratelimit-remaining")
        reset = _int_header(headers, "x-ratelimit-reset")
        retry_after = _int_header(headers, "retry-after")
        if protocol.REQUIRE_RATE_REMAINING_HEADER and remaining is None:
            raise MeasurementUnproven("a cohort response carried no x-ratelimit-remaining")
        if protocol.REQUIRE_RATE_RESET_HEADER and reset is None:
            raise MeasurementUnproven("a cohort response carried no x-ratelimit-reset")
        assert remaining is not None and reset is not None
        if reset != self.window.reset_epoch:
            raise MeasurementUnproven(
                f"provider reset epoch changed mid-segment ({self.window.reset_epoch} -> {reset}); "
                "the request cannot be attributed to exactly one frozen window"
            )
        delta = self.previous_remaining - remaining
        if delta < 0 or delta > 1:
            raise MeasurementUnproven(
                f"per-response provider delta is {delta}; exclusive attribution is not established"
            )
        hop = Hop(
            logical_request_id=logical_id,
            hop_index=hop_index,
            requested_url=url,
            status=status,
            redirect_target_digest=_digest_text(location) if location else None,
            response_body_sha256=_sha(raw),
            provider_remaining_before=self.previous_remaining,
            provider_remaining_after=remaining,
            provider_reset_epoch=reset,
            retry_after_seconds=retry_after,
            provider_charge_delta=delta,
            provider_request_id=headers.get("x-github-request-id") if headers is not None else None,
        )
        self.previous_remaining = remaining
        self.network_hops += 1
        self.provider_charged += delta
        self.root_charged += delta
        self.hops.append(hop)
        return hop

    def get(self, url: str) -> Response:
        self._reserve()
        require_target(url)
        self.logical_requests += 1
        logical_id = self.logical_requests
        current = url
        charged_before = self.provider_charged
        hop_count = 0

        for hop_index in range(protocol.MAX_HOPS_PER_LOGICAL_REQUEST):
            require_target(current)
            status, headers, raw, location = self._one_hop(current)
            hop_count += 1
            hop = self._observe_hop(
                logical_id=logical_id,
                hop_index=hop_index,
                url=current,
                status=status,
                headers=headers,
                raw=raw,
                location=location,
            )

            if status in REDIRECT_STATUSES:
                if not location:
                    raise TransportStop(f"HTTP {status} redirect carried no Location")
                current = urllib.parse.urljoin(current, location)
                require_target(current)
                continue

            self.request_log.append(
                {
                    "logical_request_id": logical_id,
                    "requested_url": url,
                    "final_url": current,
                    "status": status,
                    "network_hops": hop_count,
                    "provider_charged": self.provider_charged - charged_before,
                    "response_body_sha256": hop.response_body_sha256,
                }
            )

            if status in protocol.RATE_LIMIT_HTTP_STATUSES:
                if (
                    hop.provider_remaining_after == 0
                    or hop.retry_after_seconds is not None
                    or status == 429
                ):
                    raise SegmentClose(
                        f"HTTP {status} is a provider rate stop; traversal never receives its body"
                    )
                raise TransportStop(
                    f"HTTP {status} with quota remaining is an operational refusal, "
                    "not an empty tree"
                )
            if status != 200:
                raise TransportStop(f"HTTP {status} is not a successful traversal response")

            try:
                parsed = json.loads(raw.decode("utf-8"))
            except Exception as exc:
                raise TransportStop("HTTP 200 response is not valid JSON") from exc
            if not isinstance(parsed, dict):
                raise TransportStop("HTTP 200 response is not a JSON object")

            if hop.provider_remaining_after == 0 or hop.retry_after_seconds is not None:
                self.close_before_next = True

            return Response(
                status=200,
                final_url=current,
                body=parsed,
                network_hops=hop_count,
                provider_charged=self.provider_charged - charged_before,
            )

        raise TransportStop(
            f"logical request exceeded the frozen {protocol.MAX_HOPS_PER_LOGICAL_REQUEST}-hop bound"
        )

    def resolve_canonical_address(self, address: str, expected_uuid: str) -> dict[str, Any]:
        try:
            response = self.get(f"https://api.github.com/repos/{address}")
        except (SegmentClose, MeasurementUnproven):
            raise
        except TransportStop as exc:
            raise IdentityRefused(
                f"{address!r}: repository identity could not be established: {exc}"
            ) from exc
        observed = response.body.get("id")
        if observed is None or str(observed) != str(expected_uuid):
            raise IdentityRefused(
                f"roster selected repository {expected_uuid}, but {address!r} serves {observed!r}"
            )
        canonical = response.body.get("full_name")
        if not isinstance(canonical, str) or canonical.count("/") != 1:
            raise IdentityRefused("verified metadata has no usable canonical address")
        branch = response.body.get("default_branch")
        return {
            "catalogue_address": address,
            "canonical_address": canonical,
            "expected_repository_id": str(expected_uuid),
            "observed_repository_id": str(observed),
            "identity_verified": True,
            "default_branch": branch if isinstance(branch, str) and branch else None,
            "provider_charged_resolving": response.provider_charged,
            "network_hops_resolving": response.network_hops,
        }

    def totals(self) -> dict[str, int]:
        return {
            "logical_requests": self.logical_requests,
            "network_hops": self.network_hops,
            "provider_charged": self.provider_charged,
        }

    def reconcile(self, after: RateWindow) -> dict[str, Any]:
        if after.reset_epoch != self.window.reset_epoch:
            raise MeasurementUnproven(
                "the provider window reset before the segment's end witness; provider "
                "accounting is not comparable"
            )
        observed_delta = after.used - self.window.used
        unattributed = observed_delta - self.provider_charged
        if unattributed != 0:
            raise MeasurementUnproven(
                f"provider used delta={observed_delta}, per-response sum={self.provider_charged}, "
                f"unattributed={unattributed}"
            )
        return {
            "global_before": self.window.as_dict(),
            "global_after": after.as_dict(),
            "provider_used_delta": observed_delta,
            "per_response_provider_charge_sum": self.provider_charged,
            "unattributed_provider_accounting_delta": unattributed,
            "accounting_is_complete": True,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "tavonel.sfir10.transport.v1",
            "protocol_digest": protocol.Protocol().freeze().digest(),
            "logical_requests": list(self.request_log),
            "hops": [hop.as_dict() for hop in self.hops],
            "counters": self.totals(),
            "current_root_provider_charges": self.root_charged,
            "credential_value_serialized": False,
            "secret_headers_serialized": False,
            "credential_environment_names": ["GITHUB_TOKEN", "GH_TOKEN"],
            "allowed_scheme": ALLOWED_SCHEME,
            "allowed_host": ALLOWED_HOST,
        }
