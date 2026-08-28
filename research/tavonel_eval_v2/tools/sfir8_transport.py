#!/usr/bin/env python3
"""A transport that follows redirects itself, and records every hop it takes.

SFIR7 let `urllib` follow redirects. That is one line of convenience and it cost
four runs: each redirect was a real request GitHub charged for and our counter
never saw, and no receipt anywhere recorded that an address had moved mid-request.
Automatic following is off here. The instrument issues the request, reads the
`Location`, and issues the next one, writing an evidence atom for each.

**Three layers, kept apart at every level.** One logical request may be several
network hops, and the provider may charge differently from either. SFIR8 measured
that renamed addresses cost two and unrenamed one, with three of thirty-six
observations charged above their observed hops. Any of those layers can be the
one that binds, so none of them is inferred from another.

**Canonical address resolution, once per root.** When a root's catalogue address
redirects and the numeric repository id matches what the roster froze, the live
canonical address is adopted for the rest of that root's traversal. Otherwise
every one of a root's requests pays the redirect toll again -- SFIR7 spent 790
extra charges that way. This is not a cohort change: the repository is identified
by `host_uuid` and that is what is checked. A redirect leading to a *different*
numeric id is refused, not adopted, and the root does not proceed.

**No credential material is ever recorded.** Authorization headers are set and
never read back into an atom. Header names that could carry them are not stored
at all.

Development instrument. SFIR8 produces no capacity claim.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_ID = "SOURCE_FACT_IR_INSTRUMENT_CALIBRATION_V8"

#: A redirect chain longer than this is a loop or a misconfiguration, not a
#: rename. Derived from GitHub's own behaviour -- a renamed repository is one
#: hop -- with headroom for an org rename layered on a repo rename.
MAX_HOPS_PER_LOGICAL_REQUEST = 4

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

#: Never recorded, under any circumstances.
_SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


class RedirectRefused(RuntimeError):
    """A redirect could not be followed safely."""


class IdentityRefused(RuntimeError):
    """The address resolved to a repository the roster did not select."""


@dataclass(frozen=True, slots=True)
class HopAtom:
    """One network hop, as evidence. Every field is observed, none inferred."""

    logical_request_id: str
    hop_index: int
    requested_url: str
    status: int
    redirect_target_digest: str | None
    response_body_sha256: str | None
    provider_remaining_before: int | None
    provider_remaining_after: int | None
    provider_charge_delta: int | None
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
            "provider_charge_delta": self.provider_charge_delta,
            "provider_request_id": self.provider_request_id,
        }


@dataclass
class LogicalRequest:
    """What one call to `get` cost, across all three layers."""

    logical_request_id: str
    url: str
    final_url: str
    status: int
    body: Any = None
    atoms: list[HopAtom] = field(default_factory=list)

    @property
    def network_hops(self) -> int:
        return len(self.atoms)

    @property
    def provider_charged(self) -> int | None:
        deltas = [
            a.provider_charge_delta for a in self.atoms if a.provider_charge_delta is not None
        ]
        return sum(deltas) if deltas else None

    @property
    def redirected(self) -> bool:
        return any(a.redirect_target_digest for a in self.atoms)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand the redirect back instead of following it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ManualRedirectTransport:
    """Issues every hop itself so every hop can be evidence."""

    USER_AGENT = "TAVONEL-SFIR8-manual-redirect/1.0"

    #: The handler installed on every opener. Reported, not asserted: if this
    #: is ever changed to one that follows redirects, `totals()` says so instead
    #: of continuing to claim otherwise.
    REDIRECT_HANDLER = _NoRedirect

    def __init__(self, *, max_hops: int = MAX_HOPS_PER_LOGICAL_REQUEST) -> None:
        self.max_hops = max_hops
        self.requests: list[LogicalRequest] = []
        self._remaining: int | None = None
        self._sequence = 0
        #: catalogue address -> canonical live address, once resolved
        self.canonical: dict[str, str] = {}

    # -- counting ---------------------------------------------------------

    def totals(self) -> dict[str, Any]:
        charged = [r.provider_charged for r in self.requests if r.provider_charged is not None]
        return {
            "logical_requests": len(self.requests),
            "network_hops": sum(r.network_hops for r in self.requests),
            "provider_charged": sum(charged),
            "requests_with_provider_accounting": len(charged),
            "requests_that_redirected": sum(1 for r in self.requests if r.redirected),
            "automatic_redirect_following": self.follows_redirects_automatically(),
        }

    def follows_redirects_automatically(self) -> bool:
        """Whether the installed handler would follow a 3xx without us."""
        handler = self.REDIRECT_HANDLER()
        return handler.redirect_request(None, None, 301, "Moved", None, "https://x/") is not None

    def atoms(self) -> list[dict[str, Any]]:
        return [atom.as_dict() for request in self.requests for atom in request.atoms]

    # -- fetching ---------------------------------------------------------

    def get(self, url: str) -> LogicalRequest:
        self._sequence += 1
        logical_id = f"lr-{self._sequence:06d}"
        record = LogicalRequest(
            logical_request_id=logical_id, url=url, final_url=url, status=0
        )
        current = url
        for hop_index in range(self.max_hops):
            before = self._remaining
            status, headers, body, location = self._one_hop(current)
            after = _header_int(headers, "x-ratelimit-remaining")
            self._remaining = after if after is not None else before
            record.atoms.append(
                HopAtom(
                    logical_request_id=logical_id,
                    hop_index=hop_index,
                    requested_url=current,
                    status=status,
                    redirect_target_digest=_digest_text(location) if location else None,
                    response_body_sha256=_digest_bytes(body) if body is not None else None,
                    provider_remaining_before=before,
                    provider_remaining_after=after,
                    provider_charge_delta=(
                        before - after if before is not None and after is not None else None
                    ),
                    provider_request_id=_header_str(headers, "x-github-request-id"),
                )
            )
            if status in _REDIRECT_STATUSES:
                if not location:
                    raise RedirectRefused(
                        f"{current} answered {status} with no Location. A redirect "
                        "without a target cannot be followed and must not be guessed."
                    )
                current = urllib.parse.urljoin(current, location)
                continue
            record.status = status
            record.final_url = current
            record.body = _parse(body)
            self.requests.append(record)
            return record
        raise RedirectRefused(
            f"{url} exceeded {self.max_hops} hops without reaching a final response. "
            "A chain that long is a loop or a misconfiguration, not a rename."
        )

    def _one_hop(self, url: str) -> tuple[int, Any, bytes | None, str | None]:
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310
        opener = urllib.request.build_opener(self.REDIRECT_HANDLER())
        try:
            with opener.open(request, timeout=60) as response:
                status = int(getattr(response, "status", 200) or 200)
                body = response.read()
                return status, response.headers, body, response.headers.get("Location")
        except urllib.error.HTTPError as error:
            body = error.read() if hasattr(error, "read") else None
            return int(error.code), error.headers, body, (
                error.headers.get("Location") if error.headers else None
            )

    # -- identity ---------------------------------------------------------

    def resolve_canonical_address(self, address: str, expected_uuid: str) -> dict[str, Any]:
        """Follow the catalogue address once, check identity, adopt the live name.

        The check is the point. A redirect is only followed to a repository whose
        numeric id is the one the roster froze; anything else is refused before
        a single tree request is issued. Adopting a redirect target without that
        check is precisely the hazard INC-V2-108 recorded -- HTTP 200, real
        repository, wrong one.
        """
        record = self.get(f"https://api.github.com/repos/{address}")
        if record.status != 200 or not isinstance(record.body, dict):
            raise IdentityRefused(
                f"{address}: metadata answered HTTP {record.status}, so identity "
                "cannot be established and the root is not traversed."
            )
        observed = record.body.get("id")
        if observed is None:
            raise IdentityRefused(f"{address}: the host returned no repository id")
        if str(observed) != str(expected_uuid):
            raise IdentityRefused(
                f"{address}: the roster selected repository {expected_uuid} and this "
                f"address now serves repository {observed}. The redirect target is "
                "NOT adopted; a matching path is not a matching repository."
            )
        canonical = record.body.get("full_name")
        if not isinstance(canonical, str) or canonical.count("/") != 1:
            raise IdentityRefused(f"{address}: the host returned no usable canonical name")
        self.canonical[address] = canonical
        return {
            "catalogue_address": address,
            "canonical_address": canonical,
            "renamed": canonical.casefold() != address.casefold(),
            "expected_repository_id": str(expected_uuid),
            "observed_repository_id": str(observed),
            "identity_verified": True,
            "hops_spent_resolving": record.network_hops,
            "provider_charged_resolving": record.provider_charged,
            "why_the_canonical_address_is_used_afterwards": (
                "the repository is identified by its numeric id, which the redirect "
                "preserved. Continuing to address it by its 2020 name would pay the "
                "redirect toll on every request of the traversal -- SFIR7 spent 790 "
                "extra provider charges that way -- without changing which repository "
                "is measured."
            ),
        }

    def address_for(self, catalogue_address: str) -> str:
        """The address to send traversal requests to. Canonical if resolved."""
        return self.canonical.get(catalogue_address, catalogue_address)


def _parse(raw: bytes | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _digest_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _header_int(headers: Any, name: str) -> int | None:
    value = _header_str(headers, name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _header_str(headers: Any, name: str) -> str | None:
    if headers is None or name.casefold() in _SECRET_HEADERS:
        return None
    value = headers.get(name)
    return str(value) if value is not None else None
