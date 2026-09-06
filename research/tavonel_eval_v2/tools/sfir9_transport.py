#!/usr/bin/env python3
"""The network behaviour SFIR9 is permitted to have, declared and narrowed.

This is not a re-export of `sfir8_transport`. SFIR8 is a development instrument
and its transport is deliberately more capable than a confirmatory study should
be: it will fetch any URL it is handed, it will hand back a canonical address it
resolved, and it leaves the decision of what to do at a rate limit to the caller.
A confirmatory study must not have decisions left to the caller, because the
caller is the person hoping for a particular result.

**So the surface is declared, and the declaration is the contract.** One scheme,
one host, one method. Redirects followed explicitly, hop by hop, never by the
library. A canonical address adopted only after the numeric repository id has
been proved. Three request counters that are never added together. A rate window
that closes a segment rather than triggering a wait the protocol did not
authorize. Everything SFIR8 can additionally do is unreachable from here --
`declared_surface()` is what SFIR9 may do, and a behaviour absent from it is
absent from the study.

**What is reused is bytes, not authority.** The upstream SFIR8 modules are pinned
by SHA-256 and by Git blob id, and their working-tree bytes must equal their
committed bytes or this module refuses to run. That is a *fresh prospective
freeze of the current implementation*, not a claim that SFIR8's results carry
over. No SFIR8 receipt is a prerequisite of any SFIR9 pass, and the SFIR8
quiet-window observation of a zero accounting delta guarantees nothing here.

**Hash equality is not origin equality.** A module can hash correctly and still
be imported from a shared dirty tree, an editable install, or another worktree --
which is how a `.pth` file silently substituted an implementation earlier in this
study. So the runtime `__file__` of every upstream module is checked against the
frozen checkout, and a mismatch is `REFUSED_IMPORT_ORIGIN_MISMATCH` even when
every digest agrees.

**No scientific quantity reaches this module.** Transport may know where to send
a request, which repository answered, what the provider charged, and whether it
can continue. It may not know how many candidates a root yielded, what the
capacity threshold is, or whether a repository looks promising. A transport that
schedules differently once results start arriving is a transport that selects its
own evidence.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import subprocess
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sfir9_protocol as protocol

SCHEMA = "tavonel.sfir9.transport.v1"

# --------------------------------------------------------------- the surface

#: The only scheme, host and method SFIR9 may use. Anything else is refused
#: before a socket is opened, so a typo cannot quietly measure something else.
ALLOWED_SCHEME = "https"
ALLOWED_HOST = "api.github.com"
ALLOWED_METHOD = "GET"

#: A redirect chain longer than this is a loop, not a rename.
MAX_HOPS_PER_LOGICAL_REQUEST = 4

#: Header names that can carry credential material. Never serialized, never
#: returned, never digested -- not even as a digest, which would still confirm a
#: guess.
SECRET_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})

#: Scientific quantities. None may be passed into transport, and a mapping
#: carrying one refuses rather than being filtered: its presence means a caller
#: is trying to make the network layer result-aware.
FORBIDDEN_TRANSPORT_INPUTS = frozenset(
    {
        "candidate_count",
        "candidate_identities",
        "capacity_threshold",
        "c_f",
        "q_f",
        "document_eligibility",
        "lineage_yield",
        "tree_usefulness",
        "repository_popularity",
        "source_rank",
        "completion_status",
    }
)

# --------------------------------------------------------------- refusal codes

IMPORT_ORIGIN = "REFUSED_IMPORT_ORIGIN_MISMATCH"
UPSTREAM_BYTES = "REFUSED_UPSTREAM_BYTES_MISMATCH"
UPSTREAM_HASH = "REFUSED_UPSTREAM_HASH_MISMATCH"
IDENTITY_MISMATCH = "REFUSED_REPOSITORY_IDENTITY_MISMATCH"
DISALLOWED_TARGET = "REFUSED_DISALLOWED_TARGET"
UNPROVEN_IDENTITY = "REFUSED_CANONICAL_ADOPTION_WITHOUT_IDENTITY_PROOF"
SCIENTIFIC_INPUT = "REFUSED_SCIENTIFIC_INPUT_TO_TRANSPORT"
REDIRECT_UNRESOLVED = "REFUSED_REDIRECT_WITHOUT_TARGET"

#: Not a refusal. A rate window that cannot be waited out inside the protocol's
#: fail-safes ends the segment; the study continues in the next one.
SEGMENT_CLOSE_RATE_WINDOW = "SEGMENT_COMPLETE_RATE_WINDOW"

#: An observed difference between the provider's own counter and the sum of the
#: per-request charges. Recorded, never attributed.
UNATTRIBUTED = "UNATTRIBUTED_PROVIDER_ACCOUNTING_DELTA"


class TransportRefused(RuntimeError):
    """A refusal carrying the code that names it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# ------------------------------------------------------- upstream byte binding


@dataclass(frozen=True, slots=True)
class UpstreamModule:
    """One SFIR8 implementation file, pinned by content and by commit."""

    module: str
    relative_path: str
    sha256: str
    git_blob_id: str


#: The current SFIR8 implementation, frozen prospectively for SFIR9. These are
#: the bytes SFIR9 executes. They are not evidence, and nothing SFIR8 concluded
#: with them is imported along with them.
UPSTREAM_MODULES = (
    UpstreamModule(
        module="sfir8_transport",
        relative_path="research/tavonel_eval_v2/tools/sfir8_transport.py",
        sha256="sha256:e534a3535e4c10216d6a751224d6bd96f7c4ca6850a5708cb62226f890dba9ca",
        git_blob_id="d47762b2adcc14f3f9f6c8842bde6c8f799ae375",
    ),
    UpstreamModule(
        module="sfir8_traversal",
        relative_path="research/tavonel_eval_v2/tools/sfir8_traversal.py",
        sha256="sha256:130b11048eb1db5ddd6945a6848ea8400cb8cbde00d89e7ab2cf0af44ab7f3f4",
        git_blob_id="776618b0ad4311e9232c546bb9cd772fb43a3d56",
    ),
    UpstreamModule(
        module="sfir8_frontier",
        relative_path="research/tavonel_eval_v2/tools/sfir8_frontier.py",
        sha256="sha256:7482faa9109cf698591b309a4a4697924465e017b62c075daf31205c9f7b9991",
        git_blob_id="bb989b16fc2866ed148aa6daafdd56096f35e6c2",
    ),
    UpstreamModule(
        module="sfir8_checkpoint",
        relative_path="research/tavonel_eval_v2/tools/sfir8_checkpoint.py",
        sha256="sha256:de75744c738bf8a31f04abea27f1d0738e1ac0963fc691533648bac687def842",
        git_blob_id="879e74da07673fcb83f388d016fe493a950801a3",
    ),
    UpstreamModule(
        module="sfir8_hop_accounting",
        relative_path="research/tavonel_eval_v2/tools/sfir8_hop_accounting.py",
        sha256="sha256:3a40bfd78f3410aa2e049889c4f3562c9754a8a53d68e960f0e62da92eb4d9ad",
        git_blob_id="79f43d4c72d15334fb711e0566029a9546c93d8a",
    ),
    UpstreamModule(
        module="sfir8_provider_accounting",
        relative_path="research/tavonel_eval_v2/tools/sfir8_provider_accounting.py",
        sha256="sha256:549e8f57b6832edc5b670309dd5a8a228502cac3bfead45727fd7f75d8264c1e",
        git_blob_id="199db22fb0e68ab86c7ee9341af013f81eb0966d",
    ),
)


def sha256_of(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def git_blob_id_of(raw: bytes) -> str:
    """Git's own object name for these bytes, computed without invoking git.

    Recomputing it here rather than asking git means the pin is checkable in an
    environment that has the files but not the repository -- an isolated frozen
    checkout, for instance, which is where the re-run before freeze happens.
    """
    header = f"blob {len(raw)}\0".encode()
    return hashlib.sha1(header + raw).hexdigest()  # noqa: S324 - git's format


def _git_committed_bytes(repository_root: Path, relative_path: str) -> bytes:
    # `git` from PATH, with a literal argument vector; the only interpolated
    # value is a relative path taken from this module's own frozen manifest, not
    # from a caller. Recorded rather than suppressed silently.
    result = subprocess.run(  # noqa: S603
        ["git", "cat-file", "blob", f"HEAD:{relative_path}"],  # noqa: S607
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise TransportRefused(
            UPSTREAM_BYTES,
            f"{relative_path} is not committed at HEAD, so there is nothing to "
            "compare the working tree against. An uncommitted implementation "
            "cannot be frozen.",
        )
    return result.stdout


def verify_upstream_binding(
    *,
    repository_root: Path,
    import_origins: dict[str, str],
    read_committed_bytes: Callable[[Path, str], bytes] = _git_committed_bytes,
) -> dict[str, Any]:
    """Pin the upstream bytes four ways, and refuse on any disagreement.

    Content hash, Git blob id, committed-versus-working byte equality, and the
    runtime import origin. The fourth is not implied by the first three: a file
    can hash correctly on disk while the interpreter loads a different copy of
    it, which is exactly what a stray `.pth` did earlier in this study.
    """
    records: list[dict[str, Any]] = []
    expected_directory = (repository_root / "research/tavonel_eval_v2/tools").resolve()

    for pinned in UPSTREAM_MODULES:
        path = (repository_root / pinned.relative_path).resolve()
        working = path.read_bytes()
        observed_sha = sha256_of(working)
        observed_blob = git_blob_id_of(working)

        if observed_sha != pinned.sha256:
            raise TransportRefused(
                UPSTREAM_HASH,
                f"{pinned.relative_path} hashes to {observed_sha} and the manifest "
                f"pins {pinned.sha256}. The implementation SFIR9 froze is not the "
                "implementation on disk.",
            )
        if observed_blob != pinned.git_blob_id:
            raise TransportRefused(
                UPSTREAM_HASH,
                f"{pinned.relative_path} has Git blob id {observed_blob} and the "
                f"manifest pins {pinned.git_blob_id}.",
            )

        committed = read_committed_bytes(repository_root, pinned.relative_path)
        if committed != working:
            raise TransportRefused(
                UPSTREAM_BYTES,
                f"{pinned.relative_path} differs between the commit and the working "
                f"tree ({len(committed)} committed bytes, {len(working)} on disk). "
                "A freeze that records a commit while executing something else "
                "records the wrong thing.",
            )

        origin = import_origins.get(pinned.module)
        if origin is None:
            raise TransportRefused(
                IMPORT_ORIGIN,
                f"{pinned.module} was never imported, so its origin is unknown. An "
                "unchecked origin is not a passing origin.",
            )
        resolved = Path(origin).resolve()
        if resolved.parent != expected_directory or resolved.name != path.name:
            raise TransportRefused(
                IMPORT_ORIGIN,
                f"{pinned.module} resolves to {resolved}, outside the frozen "
                f"checkout at {expected_directory}. A shared tree, another "
                "worktree or an editable install can serve bytes that hash "
                "correctly and are still not the ones this study froze.",
            )

        records.append(
            {
                "module": pinned.module,
                "relative_path": pinned.relative_path,
                "sha256": observed_sha,
                "git_blob_id": observed_blob,
                "working_tree_bytes": len(working),
                "committed_bytes_equal_working_bytes": True,
                "import_origin": str(resolved),
                "import_origin_inside_frozen_checkout": True,
            }
        )

    return {
        "schema": SCHEMA,
        "upstream_modules": records,
        "manifest_digest": _manifest_digest(records),
        "protocol_digest_at_binding_time": protocol.Protocol().digest(),
        "what_is_reused": (
            "the current implementation bytes, newly frozen for SFIR9. Not SFIR8's "
            "conclusions: no SFIR8 receipt is a prerequisite of any SFIR9 pass, and "
            "the zero accounting delta SFIR8 observed in a quiet window guarantees "
            "nothing about SFIR9."
        ),
        "why_origin_is_checked_as_well_as_hash": (
            "a correct hash on disk does not establish that the interpreter loaded "
            "that file. A `.pth` entry substituted an implementation earlier in this "
            "study while every digest still agreed."
        ),
    }


def _manifest_digest(records: list[dict[str, Any]]) -> str:
    material = "".join(f"{r['module']}:{r['sha256']}:{r['git_blob_id']}" for r in records)
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def import_origins() -> dict[str, str]:
    """Where the interpreter actually loaded each upstream module from.

    Read at runtime from the imported module objects rather than derived from a
    path this module computed, because the question being asked is what Python
    did, not what we intended it to do.
    """
    origins: dict[str, str] = {}
    for pinned in UPSTREAM_MODULES:
        module = importlib.import_module(pinned.module)
        origin = getattr(module, "__file__", None)
        if origin is not None:
            origins[pinned.module] = origin
    return origins


# ------------------------------------------------------- the declared surface


def declared_surface() -> dict[str, Any]:
    """Exactly what SFIR9 may do on the network. Absent means forbidden."""
    return {
        "schema": SCHEMA,
        "allowed_scheme": ALLOWED_SCHEME,
        "allowed_host": ALLOWED_HOST,
        "allowed_method": ALLOWED_METHOD,
        "redirect_policy": {
            "automatic_following": False,
            "followed_by": "the instrument, one hop at a time",
            "max_hops_per_logical_request": MAX_HOPS_PER_LOGICAL_REQUEST,
            "every_hop_is_an_evidence_atom": True,
            "a_redirect_without_a_location_is_refused": REDIRECT_UNRESOLVED,
            "where_that_refusal_lives": (
                "the frozen upstream, which raises before returning a record. A "
                "second check here could never fire, and a guard placed where its "
                "failure is impossible is not a guard (INC-V2-036)."
            ),
        },
        "canonical_address_adoption_rule": (
            "adopted only after the observed numeric repository id equals the "
            "frozen host_uuid. Until then every request uses the catalogue address."
        ),
        "numeric_repository_id_attestation_rule": (
            "the metadata response's `id` is compared with the roster's host_uuid. "
            "A mismatch is " + IDENTITY_MISMATCH + " and the root is not traversed."
        ),
        "accounting": {
            "logical_requests": "what the traversal asked for; governs traversal bounds",
            "network_hops": "responses actually received; diagnostic only",
            "provider_charged_requests": "what the provider says it deducted; the "
            "only counter comparable with a provider budget",
            "the_three_are_never_summed_together": True,
        },
        "rate_window": {
            "observed_from": ["x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"],
            "retry_wait_fail_safe_seconds": protocol.RETRY_WAIT_SECONDS,
            "cumulative_wait_fail_safe_seconds": protocol.TOTAL_WAIT_SECONDS,
            "beyond_the_fail_safe": SEGMENT_CLOSE_RATE_WINDOW,
            "polling_to_discover_whether_the_limit_lifted": False,
        },
        "segment_close_condition": SEGMENT_CLOSE_RATE_WINDOW,
        "checkpoint_handoff": "explicit typed handoff; no reading of checkpoint storage",
        "forbidden_transport_inputs": sorted(FORBIDDEN_TRANSPORT_INPUTS),
        "protocol_digest": protocol.Protocol().digest(),
    }


def surface_digest() -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(declared_surface(), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    )


def require_permitted_target(url: str) -> None:
    """Scheme and host, checked before a socket is opened."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != ALLOWED_SCHEME:
        raise TransportRefused(
            DISALLOWED_TARGET,
            f"{url!r} uses scheme {parts.scheme!r}; SFIR9 permits only "
            f"{ALLOWED_SCHEME!r}.",
        )
    if parts.hostname != ALLOWED_HOST:
        raise TransportRefused(
            DISALLOWED_TARGET,
            f"{url!r} addresses host {parts.hostname!r}; SFIR9 permits only "
            f"{ALLOWED_HOST!r}. A redirect that leaves the permitted host is not "
            "followed, whatever it claims to be.",
        )


def require_no_scientific_input(mapping: Any, where: str) -> None:
    """Refuse, rather than filter, a scientific quantity offered to transport."""
    present = FORBIDDEN_TRANSPORT_INPUTS.intersection(mapping or {})
    if present:
        raise TransportRefused(
            SCIENTIFIC_INPUT,
            f"{where} was given {sorted(present)}. Transport may know where to send "
            "a request, which repository answered, what the provider charged and "
            "whether it can continue -- nothing about what the study is finding. A "
            "transport that schedules differently once results arrive selects its "
            "own evidence.",
        )


# ----------------------------------------------------------- rate-window policy

CONTINUE = "CONTINUE"
WAIT = "WAIT"


@dataclass(frozen=True, slots=True)
class WaitDecision:
    """What to do at a rate limit. Computed from headers, never from a probe."""

    action: str
    seconds: int
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"action": self.action, "seconds": self.seconds, "reason": self.reason}


def plan_wait(
    *,
    remaining: int | None,
    reset_epoch: int | None,
    retry_after: int | None,
    now_epoch: int,
    cumulative_waited_seconds: int,
) -> WaitDecision:
    """Decide from what the provider already told us.

    The provider reports `remaining` and `reset` on every response, so the state
    of the rate window is known without asking. Sending a request to find out
    whether the limit has lifted spends a charge to learn something already in
    hand, and a loop of such requests is how a fail-safe becomes decorative.

    The two fail-safes come from `sfir9_protocol` rather than being restated
    here. A duplicate literal is a second authority, and a second authority can
    be raised on its own when a run is going badly.
    """
    if retry_after is None and (remaining is None or remaining > 0):
        return WaitDecision(CONTINUE, 0, "the window has requests remaining")

    if retry_after is not None:
        needed = max(0, int(retry_after))
        source = "Retry-After"
    elif reset_epoch is None:
        return WaitDecision(
            SEGMENT_CLOSE_RATE_WINDOW,
            0,
            "the window is exhausted and no reset time was reported, so the wait "
            "cannot be bounded and must not be guessed",
        )
    else:
        needed = max(0, int(reset_epoch) - int(now_epoch))
        source = "x-ratelimit-reset"

    if needed > protocol.RETRY_WAIT_SECONDS:
        return WaitDecision(
            SEGMENT_CLOSE_RATE_WINDOW,
            0,
            f"{source} asks for {needed}s and the per-retry fail-safe is "
            f"{protocol.RETRY_WAIT_SECONDS}s. The segment closes rather than the "
            "fail-safe widening.",
        )
    if cumulative_waited_seconds + needed > protocol.TOTAL_WAIT_SECONDS:
        return WaitDecision(
            SEGMENT_CLOSE_RATE_WINDOW,
            0,
            f"{cumulative_waited_seconds}s already waited and {source} asks for "
            f"{needed}s more, past the cumulative fail-safe of "
            f"{protocol.TOTAL_WAIT_SECONDS}s.",
        )
    return WaitDecision(WAIT, needed, f"{source} bounds the wait at {needed}s")


# ------------------------------------------------------------------- evidence


@dataclass(frozen=True, slots=True)
class Hop:
    """One network hop. Every field observed; no credential material, ever."""

    logical_request_id: str
    hop_index: int
    requested_url: str
    status: int
    redirect_location_digest: str | None
    response_body_sha256: str | None
    provider_remaining: int | None
    provider_reset_epoch: int | None
    provider_request_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "logical_request_id": self.logical_request_id,
            "hop_index": self.hop_index,
            "requested_url": self.requested_url,
            "status": self.status,
            "redirect_location_digest": self.redirect_location_digest,
            "response_body_sha256": self.response_body_sha256,
            "provider_remaining": self.provider_remaining,
            "provider_reset_epoch": self.provider_reset_epoch,
            "provider_request_id": self.provider_request_id,
        }


@dataclass(frozen=True, slots=True)
class Counters:
    """Three counts that are never added together.

    They are separate fields rather than a dict with three keys so that a caller
    cannot iterate and sum them by accident, and separate names rather than one
    `requests` so that a reader must say which one they mean.
    """

    logical_requests: int
    network_hops: int
    provider_charged_requests: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "logical_requests": self.logical_requests,
            "network_hops": self.network_hops,
            "provider_charged_requests": self.provider_charged_requests,
            "why_they_are_kept_apart": (
                "a logical request may be several hops, and the provider may charge "
                "differently from either. SFIR7 bounded logical requests and was "
                "billed for hops; the two differed by 790 on renamed addresses "
                "alone. Equal values on one run do not make them one quantity."
            ),
        }


@dataclass(frozen=True, slots=True)
class RootIdentity:
    """A root whose numeric id has been proved, or one whose has not."""

    catalogue_address: str
    host_uuid: str
    observed_numeric_id: str | None = None
    canonical_address: str | None = None
    verified: bool = False

    def address_to_use(self) -> str:
        """Canonical only once proved. Otherwise the catalogue address."""
        if self.verified and self.canonical_address:
            return self.canonical_address
        return self.catalogue_address

    def as_dict(self) -> dict[str, Any]:
        return {
            "catalogue_address": self.catalogue_address,
            "host_uuid": self.host_uuid,
            "observed_numeric_id": self.observed_numeric_id,
            "canonical_address": self.canonical_address,
            "identity_verified": self.verified,
            "renamed": bool(
                self.verified
                and self.canonical_address
                and self.canonical_address.casefold() != self.catalogue_address.casefold()
            ),
        }


@dataclass(frozen=True, slots=True)
class TransportHandoff:
    """The typed contract between transport and the checkpoint chain.

    Explicit fields rather than a reference to checkpoint storage. Reading the
    other component's database would couple the two to a schema neither owns, and
    the coupling would survive a change to that schema silently.
    """

    protocol_digest: str
    roster_digest: str
    selection_digest: str
    current_root_host_uuid: str | None
    canonical_address: str | None
    frontier_digest: str
    visited_digest: str
    candidate_accumulator_digest: str
    logical_request_count: int
    network_hop_count: int
    provider_charged_count: int
    provider_remaining: int | None
    provider_reset_epoch: int | None
    previous_segment_digest: str
    disposition: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "protocol_digest": self.protocol_digest,
            "roster_digest": self.roster_digest,
            "selection_digest": self.selection_digest,
            "current_root_host_uuid": self.current_root_host_uuid,
            "canonical_address": self.canonical_address,
            "frontier_digest": self.frontier_digest,
            "visited_digest": self.visited_digest,
            "candidate_accumulator_digest": self.candidate_accumulator_digest,
            "logical_request_count": self.logical_request_count,
            "network_hop_count": self.network_hop_count,
            "provider_charged_count": self.provider_charged_count,
            "provider_remaining": self.provider_remaining,
            "provider_reset_epoch": self.provider_reset_epoch,
            "previous_segment_digest": self.previous_segment_digest,
            "disposition": self.disposition,
        }

    def digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
        )


#: The fields the handoff carries that SFIR8's checkpoint did not. They are the
#: reason SFIR9 does not simply pass an SFIR8 checkpoint around: a segment that
#: cannot name the protocol and selection it belongs to could be resumed under a
#: different one.
HANDOFF_FIELDS_SFIR8_LACKED = ("protocol_digest", "selection_digest")


# ------------------------------------------------------------------ the client


class Sfir9Transport:
    """The permitted surface, and nothing else.

    Hop mechanics are delegated to the frozen SFIR8 implementation; every gate is
    owned here. The upstream object is held privately and never returned, so a
    caller cannot reach the wider behaviour by asking for it.
    """

    def __init__(
        self,
        *,
        upstream: Any,
        roster_digest: str,
        selection_digest: str,
        clock: Callable[[], int] | None = None,
        sleeper: Callable[[int], None] | None = None,
    ) -> None:
        self._upstream = upstream
        self.roster_digest = roster_digest
        self.selection_digest = selection_digest
        self._clock = clock or (lambda: 0)
        self._sleep = sleeper or (lambda _seconds: None)

        self.hops: list[Hop] = []
        self.logical_requests: list[dict[str, Any]] = []
        self.roots: dict[str, RootIdentity] = {}
        self.cumulative_waited_seconds = 0
        self.segment_closed: str | None = None
        self.wait_decisions: list[dict[str, Any]] = []
        self._provider_remaining: int | None = None
        self._provider_reset: int | None = None
        self._charges: list[int] = []

    # -- gates ------------------------------------------------------------

    def _require_open(self) -> None:
        if self.segment_closed is not None:
            raise TransportRefused(
                DISALLOWED_TARGET,
                f"the segment closed with {self.segment_closed} and a closed segment "
                "issues no further requests. Sending one to see whether the limit "
                "lifted is the polling loop the fail-safe exists to prevent.",
            )

    # -- fetching ---------------------------------------------------------

    def get(self, url: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """One logical request, gated, delegated, and recorded hop by hop."""
        self._require_open()
        require_permitted_target(url)
        require_no_scientific_input(context, "Sfir9Transport.get context")

        record = self._upstream.get(url)
        logical_id = record.logical_request_id
        charge = record.provider_charged

        for atom in record.atoms:
            require_permitted_target(atom.requested_url)
            self.hops.append(
                Hop(
                    logical_request_id=logical_id,
                    hop_index=atom.hop_index,
                    requested_url=atom.requested_url,
                    status=atom.status,
                    redirect_location_digest=atom.redirect_target_digest,
                    response_body_sha256=atom.response_body_sha256,
                    provider_remaining=atom.provider_remaining_after,
                    provider_reset_epoch=self._provider_reset,
                    provider_request_id=atom.provider_request_id,
                )
            )
            if atom.provider_remaining_after is not None:
                self._provider_remaining = atom.provider_remaining_after

        if charge is not None:
            self._charges.append(charge)

        entry = {
            "logical_request_id": logical_id,
            "requested_url": url,
            "final_url": record.final_url,
            "status": record.status,
            "network_hops": record.network_hops,
            "provider_charged": charge,
            "body": record.body,
        }
        self.logical_requests.append(entry)
        return entry

    def observe_rate_window(
        self, *, remaining: int | None, reset_epoch: int | None, retry_after: int | None
    ) -> WaitDecision:
        """Act on what the provider already reported. Never send a probe."""
        self._provider_remaining = remaining
        self._provider_reset = reset_epoch
        decision = plan_wait(
            remaining=remaining,
            reset_epoch=reset_epoch,
            retry_after=retry_after,
            now_epoch=self._clock(),
            cumulative_waited_seconds=self.cumulative_waited_seconds,
        )
        self.wait_decisions.append(decision.as_dict())
        if decision.action == WAIT:
            self.cumulative_waited_seconds += decision.seconds
            self._sleep(decision.seconds)
        elif decision.action == SEGMENT_CLOSE_RATE_WINDOW:
            self.segment_closed = SEGMENT_CLOSE_RATE_WINDOW
        return decision

    # -- identity ---------------------------------------------------------

    def attest_root(self, *, catalogue_address: str, host_uuid: str) -> RootIdentity:
        """Prove the numeric id before adopting anything the redirect offered."""
        # No open-segment check here: every path out of this method goes through
        # `get`, which has one. A second copy would be unreachable by construction.
        url = f"https://{ALLOWED_HOST}/repos/{catalogue_address}"
        require_permitted_target(url)
        entry = self.get(url)

        body = entry["body"]
        if entry["status"] != 200 or not isinstance(body, dict):
            raise TransportRefused(
                IDENTITY_MISMATCH,
                f"{catalogue_address}: metadata answered HTTP {entry['status']}, so "
                "the numeric id is unknown and the root is not traversed.",
            )
        observed = body.get("id")
        if observed is None or str(observed) != str(host_uuid):
            raise TransportRefused(
                IDENTITY_MISMATCH,
                f"{catalogue_address}: the roster froze repository {host_uuid} and "
                f"this address serves {observed}. The redirect target is not "
                "adopted; a matching path is not a matching repository.",
            )
        canonical = body.get("full_name")
        if not isinstance(canonical, str) or canonical.count("/") != 1:
            raise TransportRefused(
                IDENTITY_MISMATCH,
                f"{catalogue_address}: no usable canonical name was returned, so "
                "there is nothing to adopt.",
            )

        identity = RootIdentity(
            catalogue_address=catalogue_address,
            host_uuid=str(host_uuid),
            observed_numeric_id=str(observed),
            canonical_address=canonical,
            verified=True,
        )
        self.roots[catalogue_address] = identity
        return identity

    def address_for(self, catalogue_address: str) -> str:
        """The address traversal requests go to. Refuses before the id is proved."""
        identity = self.roots.get(catalogue_address)
        if identity is None or not identity.verified:
            raise TransportRefused(
                UNPROVEN_IDENTITY,
                f"{catalogue_address} has no proved numeric id, so no address may be "
                "used for it yet. Adopting a redirect target before the proof is how "
                "a study measures the wrong repository and reports HTTP 200.",
            )
        return identity.address_to_use()

    # -- accounting -------------------------------------------------------

    def counters(self) -> Counters:
        return Counters(
            logical_requests=len(self.logical_requests),
            network_hops=len(self.hops),
            provider_charged_requests=sum(self._charges),
        )

    def reconcile_provider(self, *, window_used_delta: int | None) -> dict[str, Any]:
        """Compare the provider's own counter with the per-request charge sum."""
        charge_sum = sum(self._charges)
        unattributed = (
            None if window_used_delta is None else window_used_delta - charge_sum
        )
        return {
            "per_request_provider_charge_sum": charge_sum,
            "provider_window_used_delta": window_used_delta,
            UNATTRIBUTED: unattributed,
            "accounting_is_complete": unattributed == 0,
            "what_a_nonzero_delta_does_not_establish": (
                "its cause. A secondary limit, a provider-side charge the headers do "
                "not expose, and another process holding the same credential all "
                "produce identical arithmetic."
            ),
            "sfir8_observation_is_not_a_guarantee": (
                "SFIR8 observed a zero delta in a quiet window. That is evidence "
                "about SFIR8's window and guarantees nothing about this one."
            ),
        }

    # -- handoff ----------------------------------------------------------

    def handoff(
        self,
        *,
        protocol_digest: str,
        frontier_digest: str,
        visited_digest: str,
        candidate_accumulator_digest: str,
        previous_segment_digest: str,
        current_root_host_uuid: str | None = None,
        canonical_address: str | None = None,
        disposition: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> TransportHandoff:
        require_no_scientific_input(extra, "Sfir9Transport.handoff")
        counters = self.counters()
        return TransportHandoff(
            protocol_digest=protocol_digest,
            roster_digest=self.roster_digest,
            selection_digest=self.selection_digest,
            current_root_host_uuid=current_root_host_uuid,
            canonical_address=canonical_address,
            frontier_digest=frontier_digest,
            visited_digest=visited_digest,
            candidate_accumulator_digest=candidate_accumulator_digest,
            logical_request_count=counters.logical_requests,
            network_hop_count=counters.network_hops,
            provider_charged_count=counters.provider_charged_requests,
            provider_remaining=self._provider_remaining,
            provider_reset_epoch=self._provider_reset,
            previous_segment_digest=previous_segment_digest,
            disposition=disposition or self.segment_closed or "SEGMENT_OPEN",
        )

    # -- receipt ----------------------------------------------------------

    def receipt(self) -> dict[str, Any]:
        """Everything observed. No header material appears anywhere in it."""
        return {
            "schema": SCHEMA,
            "surface_digest": surface_digest(),
            "counters": self.counters().as_dict(),
            "hops": [hop.as_dict() for hop in self.hops],
            "logical_requests": [
                {k: v for k, v in entry.items() if k != "body"}
                for entry in self.logical_requests
            ],
            "roots": {k: v.as_dict() for k, v in self.roots.items()},
            "wait_decisions": self.wait_decisions,
            "cumulative_waited_seconds": self.cumulative_waited_seconds,
            "segment_closed": self.segment_closed,
            "credential_headers_never_recorded": sorted(SECRET_HEADERS),
        }
