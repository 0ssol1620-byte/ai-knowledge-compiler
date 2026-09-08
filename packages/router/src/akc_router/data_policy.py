"""Data-policy filtering of the candidate route set (blueprint 2026-09-08 §27).

§27: the candidate set is filtered by data policy *before* planning, not
apologised for afterwards. No silent egress in private mode; a detected secret
removes the external routes; an external adjudicator is never a default route.
"""

from __future__ import annotations

from collections.abc import Iterable

from akc_cir import ContractModel

from .models import DataPolicy, ProcessingMode, Route

#: Routes whose execution leaves the tenant boundary. `models.RouterContext`
#: already refuses to mark these ready in private mode; this is the same fact
#: applied to a candidate set. A new external route is added here too.
EXTERNAL_ROUTES: frozenset[Route] = frozenset({Route.MISTRAL_FALLBACK})


class PolicyFilterResult(ContractModel):
    """The permitted candidate set plus why anything was removed."""

    permitted_routes: tuple[Route, ...]
    removed_routes: tuple[Route, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """No permitted route left. The caller fails closed; it does not relax policy."""
        return not self.permitted_routes


def filter_candidate_routes(
    candidates: Iterable[Route],
    policy: DataPolicy,
    *,
    mode: ProcessingMode = ProcessingMode.BALANCED,
    secret_detected: bool = False,
) -> PolicyFilterResult:
    """Filter a candidate route set by data policy (§27).

    An external route survives only when the tenant policy allows external APIs,
    the mode is not private, private processing is not requested, and no secret
    was detected in the content.
    """
    ordered = tuple(dict.fromkeys(candidates))
    reasons: list[str] = []
    if mode is ProcessingMode.PRIVATE:
        reasons.append("private_mode")
    if policy.private_processing:
        reasons.append("private_processing")
    if not policy.external_api_allowed:
        reasons.append("external_api_not_permitted")
    if secret_detected:
        reasons.append("secret_detected")

    if not reasons:
        return PolicyFilterResult(permitted_routes=ordered)

    permitted = tuple(route for route in ordered if route not in EXTERNAL_ROUTES)
    removed = tuple(route for route in ordered if route in EXTERNAL_ROUTES)
    return PolicyFilterResult(
        permitted_routes=permitted,
        removed_routes=removed,
        reason_codes=tuple(reasons) if removed else (),
    )


__all__ = ["EXTERNAL_ROUTES", "PolicyFilterResult", "filter_candidate_routes"]
