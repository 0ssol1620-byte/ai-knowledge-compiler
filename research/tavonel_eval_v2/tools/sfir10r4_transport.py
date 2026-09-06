#!/usr/bin/env python3
"""SFIR10R4 GitHub transport with conservative shared-token accounting.

The transport distinguishes the minimum charge attributable to this instrument
(one per observed network hop) from the total decrement seen in GitHub's shared
core-rate counter. Extra decrement is recorded as external interference. It is
never credited to traversal yield and automatically withholds exact provider-
cost claims, while scientifically valid response bodies remain usable.
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

import sfir10r4_protocol as protocol

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


class WindowRollover(SegmentClose):
    """The provider moved to a new reset epoch; the boundary response is discarded."""

    def __init__(self, boundary: dict[str, Any]) -> None:
        self.boundary = dict(boundary)
        super().__init__(
            "provider rate window rolled over; boundary response discarded and request must replay"
        )


class SegmentNotReady(RuntimeError):
    """A full declared provider window is not currently available."""


class MeasurementUnproven(RuntimeError):
    """Accounting/timing evidence is insufficient to seal a scientific result."""


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
class AccountingSanityPreflight:
    before: RateWindow
    after: RateWindow
    requests: int
    request_ids_digest: str
    per_response_observed_delta_sum: int
    global_observed_delta: int
    unattributed_extra: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
            "requests": self.requests,
            "request_ids_digest": self.request_ids_digest,
            "minimum_attributable_charges": self.requests,
            "per_response_observed_delta_sum": self.per_response_observed_delta_sum,
            "global_observed_delta": self.global_observed_delta,
            "unattributed_extra": self.unattributed_extra,
            "all_positive_deltas": True,
            "request_ids_unique": True,
            "cohort_contact": False,
            "claims_credential_exclusivity": False,
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
    provider_observed_delta: int
    minimum_attributable_charge: int
    unattributed_extra: int
    provider_request_id: str

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
            "provider_observed_delta": self.provider_observed_delta,
            "minimum_attributable_charge": self.minimum_attributable_charge,
            "unattributed_extra": self.unattributed_extra,
            "provider_request_id": self.provider_request_id,
        }


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    final_url: str
    body: dict[str, Any]
    network_hops: int
    minimum_attributable_charged: int
    observed_provider_decrement: int

    @property
    def provider_charged(self) -> int:
        """Compatibility alias: R3 uses only the minimum attributable charge."""
        return self.minimum_attributable_charged


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
    """Read the core rate-window witness at a segment boundary."""
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
            f"provider remaining={window.remaining}, below the frozen segment start floor "
            f"{protocol.USABLE_CHARGE_PER_WINDOW}; no cohort request sent"
        )


def _preflight_one(opener: Any = None) -> Any:
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS GitHub endpoint
        protocol.ACCOUNTING_PREFLIGHT_ENDPOINT,
        headers=_headers(),
    )
    try:
        active = opener or urllib.request.urlopen
        with active(request, timeout=30) as response:
            response.read()
            return response.headers
    except Exception as exc:
        raise SegmentNotReady(
            f"accounting sanity preflight transport failed: {type(exc).__name__}: {exc}"
        ) from exc


def accounting_sanity_preflight(
    *,
    rate_opener: Any = None,
    request_opener: Any = None,
) -> AccountingSanityPreflight:
    """Prove accounting headers are usable without claiming credential exclusivity."""
    before = read_rate_window(rate_opener)
    minimum_before = protocol.USABLE_CHARGE_PER_WINDOW + protocol.ACCOUNTING_PREFLIGHT_REQUESTS
    if before.remaining < minimum_before:
        raise SegmentNotReady(
            f"provider remaining={before.remaining}, below preflight+segment floor "
            f"{minimum_before}; no cohort request sent"
        )

    previous = before.remaining
    request_ids: list[str] = []
    observed_sum = 0
    for _ in range(protocol.ACCOUNTING_PREFLIGHT_REQUESTS):
        headers = _preflight_one(request_opener)
        try:
            remaining = _int_header(headers, "x-ratelimit-remaining")
            reset = _int_header(headers, "x-ratelimit-reset")
        except MeasurementUnproven as exc:
            raise SegmentNotReady(str(exc)) from exc
        request_id = headers.get("x-github-request-id") if headers is not None else None
        if remaining is None or reset is None:
            raise SegmentNotReady("accounting sanity preflight lacks required rate headers")
        if reset != before.reset_epoch:
            raise SegmentNotReady("accounting sanity preflight crossed a provider reset epoch")
        if protocol.ACCOUNTING_PREFLIGHT_REQUIRE_REQUEST_ID and not request_id:
            raise SegmentNotReady("accounting sanity preflight response lacks request id")
        delta = previous - remaining
        if delta < protocol.ACCOUNTING_PREFLIGHT_MIN_DELTA_EACH_RESPONSE:
            raise SegmentNotReady(
                f"accounting sanity preflight observed non-positive/too-small delta {delta}"
            )
        observed_sum += delta
        previous = remaining
        if request_id:
            request_ids.append(str(request_id))

    if (
        protocol.ACCOUNTING_PREFLIGHT_REQUIRE_UNIQUE_REQUEST_IDS
        and len(set(request_ids)) != protocol.ACCOUNTING_PREFLIGHT_REQUESTS
    ):
        raise SegmentNotReady("accounting sanity preflight request ids are not unique")

    after = read_rate_window(rate_opener)
    if after.reset_epoch != before.reset_epoch:
        raise SegmentNotReady("accounting sanity preflight reconciliation crossed reset epoch")
    remaining_delta = before.remaining - after.remaining
    used_delta = after.used - before.used
    if remaining_delta < 0 or used_delta < 0 or remaining_delta != used_delta:
        raise SegmentNotReady(
            "accounting sanity preflight global used/remaining deltas do not reconcile"
        )
    if remaining_delta < observed_sum or observed_sum < protocol.ACCOUNTING_PREFLIGHT_REQUESTS:
        raise SegmentNotReady(
            "accounting sanity preflight global delta does not dominate observed request deltas"
        )
    require_full_window(after)
    return AccountingSanityPreflight(
        before=before,
        after=after,
        requests=protocol.ACCOUNTING_PREFLIGHT_REQUESTS,
        request_ids_digest=_sha("\n".join(request_ids).encode("utf-8")),
        per_response_observed_delta_sum=observed_sum,
        global_observed_delta=remaining_delta,
        unattributed_extra=remaining_delta - protocol.ACCOUNTING_PREFLIGHT_REQUESTS,
    )


class Transport:
    """GET-only client enforcing the frozen minimum-attributable request envelope."""

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
        # Compatibility names below always mean minimum attributable R3 charges.
        self.provider_charged = 0
        self.root_charged = int(root_charges_already_spent)
        self.observed_provider_decrement_sum = 0
        self.unattributed_response_extra = 0
        self.current_root: str | None = None
        self.previous_remaining = window.remaining
        self.close_before_next = False
        self.rollover_boundary: dict[str, Any] | None = None
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
                "another worst-case logical request would exceed the declared minimum-attributable "
                "window budget"
            )
        if (
            self.current_root is not None
            and self.root_charged + reserve > protocol.PER_ROOT_CHARGE_ALLOWANCE
        ):
            raise TransportStop(
                "another worst-case logical request would exceed the root's cumulative "
                "minimum-attributable charge allowance"
            )

    def _one_hop(self, url: str) -> tuple[int, Any, bytes, str | None]:
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
        request_id = headers.get("x-github-request-id") if headers is not None else None
        if protocol.REQUIRE_RATE_REMAINING_HEADER and remaining is None:
            raise MeasurementUnproven("a cohort response carried no x-ratelimit-remaining")
        if protocol.REQUIRE_RATE_RESET_HEADER and reset is None:
            raise MeasurementUnproven("a cohort response carried no x-ratelimit-reset")
        if protocol.REQUIRE_PROVIDER_REQUEST_ID and not request_id:
            raise MeasurementUnproven("a cohort response carried no x-github-request-id")
        assert remaining is not None and reset is not None and request_id is not None
        if reset != self.window.reset_epoch:
            boundary = {
                "old_reset_epoch": self.window.reset_epoch,
                "new_reset_epoch": reset,
                "status": status,
                "requested_url": url,
                "response_body_sha256": _sha(raw),
                "provider_request_id": str(request_id),
                "new_window_remaining": remaining,
                "retry_after_seconds": retry_after,
                "scientific_body_consumed": False,
                "minimum_attributable_charge_credited": 0,
            }
            self.rollover_boundary = boundary
            raise WindowRollover(boundary)
        observed_delta = self.previous_remaining - remaining
        if observed_delta < protocol.MINIMUM_ATTRIBUTABLE_CHARGE_PER_NETWORK_HOP:
            raise MeasurementUnproven(
                f"per-response provider delta is {observed_delta}; "
                "a positive hop charge is unproven"
            )
        minimum_charge = protocol.MINIMUM_ATTRIBUTABLE_CHARGE_PER_NETWORK_HOP
        extra = observed_delta - minimum_charge
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
            provider_observed_delta=observed_delta,
            minimum_attributable_charge=minimum_charge,
            unattributed_extra=extra,
            provider_request_id=str(request_id),
        )
        self.previous_remaining = remaining
        self.network_hops += 1
        self.provider_charged += minimum_charge
        self.root_charged += minimum_charge
        self.observed_provider_decrement_sum += observed_delta
        self.unattributed_response_extra += extra
        self.hops.append(hop)
        return hop

    def get(self, url: str) -> Response:
        self._reserve()
        require_target(url)
        self.logical_requests += 1
        logical_id = self.logical_requests
        current = url
        minimum_before = self.provider_charged
        observed_before = self.observed_provider_decrement_sum
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
                    "minimum_attributable_charged": self.provider_charged - minimum_before,
                    "observed_provider_decrement": (
                        self.observed_provider_decrement_sum - observed_before
                    ),
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
                minimum_attributable_charged=self.provider_charged - minimum_before,
                observed_provider_decrement=self.observed_provider_decrement_sum - observed_before,
            )

        raise TransportStop(
            f"logical request exceeded the frozen {protocol.MAX_HOPS_PER_LOGICAL_REQUEST}-hop bound"
        )

    def resolve_canonical_address(self, address: str, expected_uuid: str) -> dict[str, Any]:
        response = self.get(f"https://api.github.com/repos/{address}")
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
            "minimum_attributable_charged_resolving": response.minimum_attributable_charged,
            "observed_provider_decrement_resolving": response.observed_provider_decrement,
            "network_hops_resolving": response.network_hops,
        }

    def totals(self) -> dict[str, int]:
        return {
            "logical_requests": self.logical_requests,
            "network_hops": self.network_hops,
            "minimum_attributable_charged": self.provider_charged,
            "per_response_observed_provider_decrement": self.observed_provider_decrement_sum,
            "per_response_unattributed_extra": self.unattributed_response_extra,
        }

    def _rollover_reconciliation(self, after: RateWindow) -> dict[str, Any]:
        """Seal accepted old-window work without consuming the rollover response body."""
        remaining_delta = self.window.remaining - self.previous_remaining
        if remaining_delta < 0:
            raise MeasurementUnproven("old-window remaining delta became negative before rollover")
        if remaining_delta < self.observed_provider_decrement_sum:
            raise MeasurementUnproven(
                "old-window counter delta is smaller than chained accepted response deltas"
            )
        if remaining_delta < self.provider_charged:
            raise MeasurementUnproven(
                "old-window counter delta is smaller than minimum attributable accepted hops"
            )
        tail_extra = remaining_delta - self.observed_provider_decrement_sum
        total_unattributed = self.unattributed_response_extra + tail_extra
        if total_unattributed != remaining_delta - self.provider_charged:
            raise MeasurementUnproven("rollover conservative accounting identity does not close")
        boundary = self.rollover_boundary or {
            "old_reset_epoch": self.window.reset_epoch,
            "new_reset_epoch": after.reset_epoch,
            "source": "segment_end_rate_window_witness",
            "scientific_body_consumed": False,
            "minimum_attributable_charge_credited": 0,
        }
        return {
            "global_before": self.window.as_dict(),
            "global_after": after.as_dict(),
            "global_observed_provider_delta": None,
            "provider_used_delta": None,
            "old_window_observed_delta_through_last_accepted_response": remaining_delta,
            "minimum_attributable_charges": self.provider_charged,
            "per_response_observed_provider_delta": self.observed_provider_decrement_sum,
            "per_response_unattributed_extra": self.unattributed_response_extra,
            "tail_unattributed_extra": tail_extra,
            "total_unattributed_extra_before_boundary": total_unattributed,
            "rollover_boundary": boundary,
            "boundary_response_scientific_consumption": False,
            "boundary_response_charge_credited_to_old_window": False,
            "accounting_is_conservative": True,
            "exact_provider_cost_attribution": False,
            "provider_cost_claim_publishable": False,
            "capacity_evidence_publishable": True,
            "replay_required_under_fresh_segment": True,
        }

    def reconcile(self, after: RateWindow) -> dict[str, Any]:
        if after.reset_epoch != self.window.reset_epoch:
            return self._rollover_reconciliation(after)
        remaining_delta = self.window.remaining - after.remaining
        used_delta = after.used - self.window.used
        if remaining_delta < 0 or used_delta < 0 or remaining_delta != used_delta:
            raise MeasurementUnproven(
                "provider global used/remaining deltas are negative or do not reconcile"
            )
        if remaining_delta < self.observed_provider_decrement_sum:
            raise MeasurementUnproven(
                "global provider delta is smaller than the chained per-response observed delta"
            )
        if remaining_delta < self.provider_charged:
            raise MeasurementUnproven(
                "global provider delta is smaller than the instrument's minimum attributable hops"
            )
        tail_extra = remaining_delta - self.observed_provider_decrement_sum
        total_unattributed = self.unattributed_response_extra + tail_extra
        if total_unattributed != remaining_delta - self.provider_charged:
            raise MeasurementUnproven("conservative accounting identity does not close")
        exact_cost = total_unattributed == 0
        return {
            "global_before": self.window.as_dict(),
            "global_after": after.as_dict(),
            "global_observed_provider_delta": remaining_delta,
            "provider_used_delta": used_delta,
            "minimum_attributable_charges": self.provider_charged,
            "per_response_observed_provider_delta": self.observed_provider_decrement_sum,
            "per_response_unattributed_extra": self.unattributed_response_extra,
            "tail_unattributed_extra": tail_extra,
            "total_unattributed_extra": total_unattributed,
            "accounting_is_conservative": True,
            "exact_provider_cost_attribution": exact_cost,
            "provider_cost_claim_publishable": exact_cost,
            "capacity_evidence_publishable": True,
        }

    def receipt(self) -> dict[str, Any]:
        return {
            "schema": "tavonel.sfir10r4.transport.v1",
            "protocol_digest": protocol.Protocol().freeze().digest(),
            "logical_requests": list(self.request_log),
            "hops": [hop.as_dict() for hop in self.hops],
            "counters": self.totals(),
            "current_root_minimum_attributable_charges": self.root_charged,
            "rollover_boundary": self.rollover_boundary,
            "credential_value_serialized": False,
            "secret_headers_serialized": False,
            "credential_environment_names": ["GITHUB_TOKEN", "GH_TOKEN"],
            "allowed_scheme": ALLOWED_SCHEME,
            "allowed_host": ALLOWED_HOST,
        }
