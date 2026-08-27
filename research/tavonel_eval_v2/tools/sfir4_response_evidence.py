"""Observed-response evidence for the SFIR4 capacity census.

What the probe recorded before this module::

    refs.append(url)                    # a list of strings
    ...
    "response_ref_count": len(refs)
    def _response_size(value): return len(json.dumps(value, ...))

Three separate problems, all of which look like evidence:

1. A URL is a record of what was *asked for*, not of what came back. Nothing in
   the receipt distinguished a request that returned the expected tree from one
   that returned something else with the same status.
2. ``_response_size`` re-serialises the **parsed** object. That number is a
   property of ``json.dumps`` -- key order, separators, escaping -- not of the
   bytes that crossed the wire. It was reported beside real bounds as though it
   were a measurement of the response. ``_http_json`` had the actual bytes in
   ``raw`` and dropped them.
3. A flat list carries no order that survives being rewritten. Reordering or
   deleting entries produces a list that is indistinguishable from a correct
   one.

This module records, per request: the exact immutable target asked for, the
sha-256 of the bytes actually received, both the declared and the observed
length, the position in a global sequence, and the root the request belongs to.
The sequence is bound by a hash chain, so dropping or reordering any observation
changes the head and the arithmetic stops reconciling.

CREDENTIALS ARE NEVER RECORDED. Headers are not stored at all -- the GitHub
token lives in an ``Authorization`` header, and the way to guarantee it is not
in an artifact is to have no code path that could put it there.
:func:`assert_credential_free` additionally refuses a URL that carries userinfo
or a secret-looking query parameter, so a credential moved into a URL by a
future edit fails closed rather than being sealed into a receipt.

SYNTHESISED OBSERVATIONS ARE MARKED. Tests inject a fetcher that returns parsed
JSON with no bytes behind it. Such an observation is recorded with
``observed_bytes: false`` and a digest over the canonical encoding, and
:meth:`ResponseLedger.require_all_observed` refuses. Without that, a test double
could manufacture evidence that a receipt would present as live.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any, Final

SCHEMA: Final[str] = "tavonel.sfir4.response_evidence.v1"
CHAIN_SEED: Final[bytes] = b"tavonel.sfir4.response_chain.v1"

#: How a request ended. A failure is still a request and still consumes budget.
OUTCOMES: Final[frozenset[str]] = frozenset({"RESPONSE", "HTTP_ERROR", "TRANSPORT_ERROR"})

#: Query parameter names that must never appear in a recorded URL.
_SECRET_PARAMS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "client_secret",
        "key",
        "password",
        "private_token",
        "secret",
        "session",
        "signature",
        "token",
    }
)
_BEARERISH: Final[re.Pattern[str]] = re.compile(
    r"(gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|bearer\s)", re.IGNORECASE
)


class ResponseEvidenceRefused(RuntimeError):
    """The evidence cannot be recorded truthfully, so it is not recorded."""


def assert_credential_free(url: str) -> None:
    """Refuse a URL that could carry a secret into an artifact."""
    if not isinstance(url, str) or not url:
        raise ResponseEvidenceRefused("response URL is not a non-empty string")
    parsed = urllib.parse.urlparse(url)
    if "@" in parsed.netloc:
        raise ResponseEvidenceRefused("response URL carries userinfo")
    if _BEARERISH.search(url):
        raise ResponseEvidenceRefused("response URL looks like it carries a token")
    for name, _ in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if name.casefold() in _SECRET_PARAMS:
            raise ResponseEvidenceRefused(
                f"response URL carries a secret-looking parameter {name!r}"
            )


@dataclass(frozen=True, slots=True)
class ResponseObservation:
    """One request and what actually came back from it."""

    sequence: int
    family: str
    root_id: str
    purpose: str
    url: str
    #: RESPONSE when a body was read; HTTP_ERROR or TRANSPORT_ERROR when the
    #: request completed without one. Failures stay in the chain because they
    #: are part of the request arithmetic the bounds are checked against.
    outcome: str
    status: int
    content_digest: str
    declared_length: int | None
    observed_length: int
    observed_bytes: bool

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))


def digest_bytes(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def digest_parsed(value: object) -> str:
    """A digest for an observation with no bytes behind it.

    Always paired with ``observed_bytes=False``. It is a stable identifier for a
    synthesised response, never a claim about anything that crossed a wire.
    """
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "synthesized-sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ResponseLedger:
    """Append-only, hash-chained record of every metadata response observed."""

    def __init__(self) -> None:
        self._observations: list[ResponseObservation] = []
        self._head: str = "sha256:" + hashlib.sha256(CHAIN_SEED).hexdigest()

    def __len__(self) -> int:
        return len(self._observations)

    @property
    def head(self) -> str:
        """The chain head. Changes if any observation is added, dropped or moved."""
        return self._head

    def record(
        self,
        *,
        family: str,
        root_id: str,
        purpose: str,
        url: str,
        status: int,
        content_digest: str,
        observed_length: int,
        declared_length: int | None,
        observed_bytes: bool,
        outcome: str = "RESPONSE",
    ) -> ResponseObservation:
        assert_credential_free(url)
        if outcome not in OUTCOMES:
            raise ResponseEvidenceRefused(f"unknown response outcome {outcome!r}")
        if outcome != "RESPONSE" and observed_bytes:
            raise ResponseEvidenceRefused("a failed request cannot carry an observed body")
        if observed_length < 0:
            raise ResponseEvidenceRefused("observed length is negative")
        if declared_length is not None and declared_length != observed_length:
            raise ResponseEvidenceRefused(
                "declared and observed response lengths disagree; "
                f"declared {declared_length}, observed {observed_length}"
            )
        if observed_bytes and not content_digest.startswith("sha256:"):
            raise ResponseEvidenceRefused("an observed response carries a synthesised digest")
        if not observed_bytes and not content_digest.startswith("synthesized-sha256:"):
            raise ResponseEvidenceRefused("a synthesised response claims an observed digest")

        observation = ResponseObservation(
            sequence=len(self._observations),
            family=family,
            root_id=root_id,
            purpose=purpose,
            url=url,
            outcome=outcome,
            status=status,
            content_digest=content_digest,
            declared_length=declared_length,
            observed_length=observed_length,
            observed_bytes=observed_bytes,
        )
        self._observations.append(observation)
        self._head = (
            "sha256:"
            + hashlib.sha256(
                self._head.encode("ascii") + b"\0" + observation.canonical().encode("utf-8")
            ).hexdigest()
        )
        return observation

    def observations(self) -> tuple[ResponseObservation, ...]:
        return tuple(self._observations)

    def for_root(self, root_id: str) -> tuple[ResponseObservation, ...]:
        return tuple(o for o in self._observations if o.root_id == root_id)

    def require_all_observed(self) -> None:
        """Refuse unless every observation has real bytes behind it.

        The live census calls this before sealing. A run driven by an injected
        fetcher cannot pass it, which is the point: a receipt must not be able
        to present synthesised responses as live ones.
        """
        synthetic = [
            o.sequence
            for o in self._observations
            if o.outcome == "RESPONSE" and not o.observed_bytes
        ]
        if synthetic:
            raise ResponseEvidenceRefused(
                f"{len(synthetic)} of {len(self._observations)} responses were "
                f"synthesised, not observed; first at sequence {synthetic[0]}"
            )

    def root_arithmetic(self, root_id: str) -> dict[str, Any]:
        rows = self.for_root(root_id)
        return {
            "requests": len(rows),
            "first_sequence": rows[0].sequence if rows else None,
            "last_sequence": rows[-1].sequence if rows else None,
            "observed_bytes_total": sum(row.observed_length for row in rows),
            "responses": sum(1 for row in rows if row.outcome == "RESPONSE"),
            "failures": sum(1 for row in rows if row.outcome != "RESPONSE"),
            "all_observed": all(row.observed_bytes for row in rows if row.outcome == "RESPONSE"),
            "response_digests": [row.content_digest for row in rows],
            "distinct_response_digests": len({row.content_digest for row in rows}),
        }

    def proof(self) -> dict[str, Any]:
        """The receipt-recordable statement, with reconciling arithmetic.

        ``per_root`` request counts sum to ``global.requests``. A dropped or
        duplicated observation breaks that sum and the chain head at once.
        """
        by_root: dict[str, int] = defaultdict(int)
        for observation in self._observations:
            by_root[observation.root_id] += 1
        per_root = {root: self.root_arithmetic(root) for root in sorted(by_root)}
        total = len(self._observations)
        return {
            "schema": SCHEMA,
            "chain_seed": CHAIN_SEED.decode("ascii"),
            "chain_head": self._head,
            "global": {
                "requests": total,
                "roots": len(per_root),
                "observed_bytes_total": sum(o.observed_length for o in self._observations),
                "responses": sum(1 for o in self._observations if o.outcome == "RESPONSE"),
                "failures": sum(1 for o in self._observations if o.outcome != "RESPONSE"),
                "all_observed": all(
                    o.observed_bytes for o in self._observations if o.outcome == "RESPONSE"
                ),
                "sequence_is_dense": [o.sequence for o in self._observations] == list(range(total)),
            },
            "per_root": per_root,
            "per_root_requests_sum": sum(row["requests"] for row in per_root.values()),
            "observations": [asdict(o) for o in self._observations],
            "records_no_headers": (
                "Request headers are never stored. The GitHub token is carried "
                "in an Authorization header and there is no code path that "
                "writes a header into an artifact."
            ),
            "what_a_digest_means": (
                "sha256: the response bytes were read and hashed. "
                "synthesized-sha256: no bytes existed; the value identifies an "
                "injected object and is not evidence of a network response."
            ),
        }


def verify_chain(proof: dict[str, Any]) -> bool:
    """Recompute the chain head from the recorded observations.

    An independent reader calls this. It is the reason the sequence cannot be
    edited after the fact without the edit being detectable.
    """
    head = "sha256:" + hashlib.sha256(CHAIN_SEED).hexdigest()
    for index, row in enumerate(proof.get("observations", [])):
        if row.get("sequence") != index:
            return False
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":"))
        head = (
            "sha256:"
            + hashlib.sha256(head.encode("ascii") + b"\0" + canonical.encode("utf-8")).hexdigest()
        )
    return head == proof.get("chain_head")


def recompute_proof_arithmetic(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Rebuild every aggregate in ``proof`` from its own ``observations``.

    Written because ``verify_chain`` reads ONLY ``observations``: it proves the
    recorded sequence was not edited, and says nothing whatever about the
    ``global`` and ``per_root`` blocks sitting beside it. A reader that checked
    the chain and then believed those blocks was checking a signature on one
    document and quoting a different one.

    The gap was not theoretical. A block with ``observations: []`` and a
    hand-written ``global`` claiming 1000 observed requests recomputed its chain
    head correctly -- the head of an empty chain is just ``sha256(CHAIN_SEED)``,
    a public unkeyed constant anyone can compute -- and passed every downstream
    assertion, certifying a census in which no request was ever made.
    """
    observations = proof.get("observations")
    if not isinstance(observations, list):
        raise ResponseEvidenceRefused("response evidence carries no observation list")

    by_root: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in observations:
        if not isinstance(row, Mapping):
            raise ResponseEvidenceRefused("response evidence carries a malformed observation")
        by_root[str(row.get("root_id"))].append(row)

    def arithmetic(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        return {
            "requests": len(rows),
            "first_sequence": rows[0].get("sequence") if rows else None,
            "last_sequence": rows[-1].get("sequence") if rows else None,
            "observed_bytes_total": sum(int(r.get("observed_length") or 0) for r in rows),
            "responses": sum(1 for r in rows if r.get("outcome") == "RESPONSE"),
            "failures": sum(1 for r in rows if r.get("outcome") != "RESPONSE"),
            "all_observed": all(
                bool(r.get("observed_bytes")) for r in rows if r.get("outcome") == "RESPONSE"
            ),
            "response_digests": [r.get("content_digest") for r in rows],
            "distinct_response_digests": len({r.get("content_digest") for r in rows}),
        }

    per_root = {root: arithmetic(by_root[root]) for root in sorted(by_root)}
    total = len(observations)
    return {
        "global": {
            "requests": total,
            "roots": len(per_root),
            "observed_bytes_total": sum(int(r.get("observed_length") or 0) for r in observations),
            "responses": sum(1 for r in observations if r.get("outcome") == "RESPONSE"),
            "failures": sum(1 for r in observations if r.get("outcome") != "RESPONSE"),
            "all_observed": all(
                bool(r.get("observed_bytes"))
                for r in observations
                if r.get("outcome") == "RESPONSE"
            ),
            "sequence_is_dense": [r.get("sequence") for r in observations] == list(range(total)),
        },
        "per_root": per_root,
        "per_root_requests_sum": sum(row["requests"] for row in per_root.values()),
    }


def require_observed_census(proof: Mapping[str, Any]) -> dict[str, Any]:
    """Fail-closed: this proof describes requests that were actually made.

    ``verify_chain`` is necessary and nowhere near sufficient. This is what a
    sealing caller must use instead, and it refuses on each of the four ways a
    census can fail to be one:

    1. the chain does not recompute -- an observation was added, dropped or
       moved;
    2. there are no observations at all -- an empty chain has a well-known head
       and certifies nothing;
    3. a recorded aggregate disagrees with the observations it claims to
       summarise -- the ``global``/``per_root`` blocks are recomputed here and
       compared field by field, so editing them is exactly as detectable as
       editing an observation;
    4. any response was synthesised. This is tested twice, deliberately, on two
       independent signals: the ``observed_bytes`` flag AND the digest prefix.
       ``digest_parsed`` writes ``synthesized-sha256:``; a forger who flips only
       the boolean leaves the prefix behind, and one who rewrites only the
       prefix leaves the boolean.

    ``ResponseLedger.require_all_observed`` covers (4) for a ledger still held
    in memory. It cannot be reached by a reader holding only a JSON file, which
    is the position every sealing caller is actually in -- and, as the audit
    that produced this function found, it had zero call sites anywhere.
    """
    if not isinstance(proof, Mapping):
        raise ResponseEvidenceRefused("response evidence is not a mapping")
    if proof.get("schema") != SCHEMA:
        raise ResponseEvidenceRefused("response evidence schema moved")
    if not verify_chain(dict(proof)):
        raise ResponseEvidenceRefused("response evidence chain does not recompute")

    observations = proof.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ResponseEvidenceRefused(
            "response evidence records no observations; an empty chain has a "
            "publicly computable head and is not evidence that any request was made"
        )

    recomputed = recompute_proof_arithmetic(proof)
    for key in ("global", "per_root", "per_root_requests_sum"):
        if proof.get(key) != recomputed[key]:
            raise ResponseEvidenceRefused(
                f"response evidence {key!r} does not match the observations it "
                "summarises; the recorded arithmetic was not derived from this chain"
            )

    synthetic = [
        row.get("sequence")
        for row in observations
        if row.get("outcome") == "RESPONSE"
        and (
            not row.get("observed_bytes")
            or not str(row.get("content_digest", "")).startswith("sha256:")
        )
    ]
    if synthetic:
        raise ResponseEvidenceRefused(
            f"{len(synthetic)} of {len(observations)} responses were synthesised, "
            f"not observed; first at sequence {synthetic[0]}. A simulated census "
            "is not a live one"
        )
    return recomputed
