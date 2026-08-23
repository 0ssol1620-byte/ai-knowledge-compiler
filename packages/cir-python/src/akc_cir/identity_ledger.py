"""The identity transition ledger — an append-only record of who became what.

`akc_cir.identity` decides, for every unit in a new version, whether it
continues an old identity or starts a new one. Those decisions are answers,
not history: overwrite the corpus state and nothing can later say *when* a
clause stopped being §4.2 and became §4.3, or which two identities were merged
to produce this one. Temporal queries, audits and post-hoc reviews all need
the transitions themselves, in order, unmodified.

This module keeps them, and three properties carry the weight:

**Append-only, durably.** Every append is one JSON line flushed and
``fsync``-ed before ``append`` returns. A crash may lose the entry that was
being written; it can never leave a half-written line that reads as valid,
because a partial line is not valid JSON and fails verification like any
other edit.

**Tamper-evident.** Each stored record carries ``digest`` -- the sha256 of its
canonical payload chained to the previous record's digest, with the chain
rooted at 64 zero bits. Replacing, editing or reordering any historical
record breaks every digest after it: re-opening the file (or calling
``verify``) fails loudly and names the offending sequence number instead of
silently replaying a rewritten history. The append path refuses outright what
needs no digest to detect -- a seq that already exists (reuse) or one that
jumps past the head (a skipped number) -- because either would forge an
ordering the rest of the ledger is supposed to guarantee.

**Replayable.** :func:`replay` folds entries back into the current identity
map: which logical ids are live, which were absorbed into what, retired, with
the lineage each accumulated. The map is a pure function of the entries, so
"what does the world look like now" answers identically from the original run
and from a restored copy of the ledger.

The kinds are the five transitions §15.5 names:

* ``NEW`` -- an identity begins.
* ``MATCH`` -- an incoming unit continues an existing identity.
* ``MERGE`` -- prior identities are absorbed into the surviving one.
* ``SPLIT`` -- this identity is one successor of a prior that divided; a
  split into k successors is k entries sharing the original as their prior.
* ``RETIRE`` -- an identity leaves the active world without a successor.

An ``AMBIGUOUS`` resolver outcome is deliberately absent from that list: an
abstention transitions nothing, so it produces no entry.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

from akc_cir.identity import (
    IdentityDecisionRecorder,
    LogicalIdentityDecision,
    LogicalMatch,
    LogicalUnitFingerprint,
)

__all__ = [
    "GENESIS_DIGEST",
    "IdentityLedger",
    "IdentityState",
    "IdentityStatus",
    "LedgerDecisionRecorder",
    "LedgerEntry",
    "LedgerKind",
    "LedgerTamperedError",
    "replay",
]

#: The digest every chain starts from. A first record chained to anything
#: else was not written by this module.
GENESIS_DIGEST = "0" * 64

_SEPARATOR = "\x1e"

_UTC = UTC


class LedgerKind(StrEnum):
    """§15.5's five transitions. Values are the wire spelling."""

    MATCH = "MATCH"
    NEW = "NEW"
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    RETIRE = "RETIRE"


def _utc_now() -> datetime:
    return datetime.now(_UTC)


def _canonical(payload: dict[str, object]) -> str:
    """The byte-exact spelling a digest is taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _chain_digest(previous_digest: str, payload: dict[str, object]) -> str:
    body = _SEPARATOR.join((previous_digest, _canonical(payload)))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One identity transition, exactly as §15.5 spells it.

    ``seq`` is 1-based and gap-free over a ledger; the store assigns or
    enforces it, never trusts it. ``ts_utc`` must be timezone-aware UTC --
    a local wall-clock timestamp would make two ledgers disagree about
    ordering the sequence numbers already settle. ``prior_ids`` names what
    the transition supersedes: the continued id for ``MATCH``, the absorbed
    ids for ``MERGE``, the divided original for ``SPLIT``.
    """

    seq: int
    ts_utc: datetime
    logical_id: str
    kind: LedgerKind
    prior_ids: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.seq, bool) or not isinstance(self.seq, int):
            raise ValueError(f"seq must be an integer, got {type(self.seq).__name__}")
        if self.seq < 1:
            raise ValueError(f"seq numbers start at 1, got {self.seq}")
        if not isinstance(self.ts_utc, datetime):
            raise ValueError("ts_utc must be a datetime")
        offset = self.ts_utc.utcoffset()
        if offset is None:
            raise ValueError("ts_utc must be timezone-aware")
        if offset != timedelta(0):
            raise ValueError(
                f"ts_utc must be UTC, got offset {offset}; "
                "convert before recording so two ledgers agree"
            )
        logical_id = _require_id("logical_id", self.logical_id)
        object.__setattr__(self, "logical_id", logical_id)
        object.__setattr__(self, "kind", LedgerKind(self.kind))
        object.__setattr__(self, "prior_ids", _require_ids("prior_ids", self.prior_ids))
        object.__setattr__(
            self, "evidence_refs", _require_ids("evidence_refs", self.evidence_refs)
        )
        if not isinstance(self.note, str):
            raise ValueError("note must be a string")

    @property
    def payload(self) -> dict[str, object]:
        """The canonical field dict a record stores and a digest covers."""
        return {
            "seq": self.seq,
            "ts_utc": self.ts_utc.isoformat(),
            "logical_id": self.logical_id,
            "kind": self.kind.value,
            "prior_ids": list(self.prior_ids),
            "evidence_refs": list(self.evidence_refs),
            "note": self.note,
        }

    @classmethod
    def from_payload(cls, payload: object) -> LedgerEntry:
        """Rebuild an entry from its stored dict, rejecting anything else.

        Unknown fields are refused rather than ignored: a record carrying a
        field this version does not understand is not a record this version
        wrote, and replaying it silently would be exactly the tampering the
        digest chain exists to catch.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"a record must be a JSON object, got {type(payload).__name__}")
        expected = {
            "seq",
            "ts_utc",
            "logical_id",
            "kind",
            "prior_ids",
            "evidence_refs",
            "note",
        }
        present = set(payload)
        missing = sorted(expected - present)
        unknown = sorted(present - expected)
        if missing or unknown:
            raise ValueError(
                f"record shape mismatch (missing={missing}, unknown={unknown})"
            )
        raw_ts = payload["ts_utc"]
        if not isinstance(raw_ts, str):
            raise ValueError("ts_utc must be an ISO-8601 string")
        try:
            ts_utc = datetime.fromisoformat(raw_ts)
        except ValueError as exc:
            raise ValueError(f"ts_utc is not ISO-8601: {raw_ts!r}") from exc
        try:
            kind = LedgerKind(payload["kind"])
        except ValueError as exc:
            raise ValueError(f"unknown ledger kind: {payload['kind']!r}") from exc
        seq = payload["seq"]
        prior_ids = payload["prior_ids"]
        evidence_refs = payload["evidence_refs"]
        note = payload["note"]
        if isinstance(seq, bool) or not isinstance(seq, int):
            raise ValueError(f"seq must be an integer, got {type(seq).__name__}")
        if not isinstance(prior_ids, list) or not isinstance(evidence_refs, list):
            raise ValueError("prior_ids and evidence_refs must be JSON arrays")
        if not all(isinstance(item, str) for item in prior_ids):
            raise ValueError("prior_ids must be strings")
        if not all(isinstance(item, str) for item in evidence_refs):
            raise ValueError("evidence_refs must be strings")
        if not isinstance(note, str):
            raise ValueError("note must be a string")
        return cls(
            seq=seq,
            ts_utc=ts_utc,
            logical_id=payload["logical_id"],
            kind=kind,
            prior_ids=tuple(prior_ids),
            evidence_refs=tuple(evidence_refs),
            note=note,
        )


def _require_id(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} is required")
    return stripped


def _require_ids(name: str, values: Sequence[object]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for value in values:
        cleaned.append(_require_id(f"{name} member", value))
    return tuple(cleaned)


class LedgerTamperedError(RuntimeError):
    """The ledger on disk no longer matches the history it recorded.

    Raised on open and by :meth:`IdentityLedger.verify` when a record's
    content no longer matches its digest, the digest chain has a broken link,
    the sequence numbers skip, repeat or run backwards, or a line is not the
    record that was written. ``seq`` is the offending sequence number where
    one could be read and ``None`` otherwise.
    """

    def __init__(self, path: Path | str, seq: int | None, reason: str) -> None:
        self.path = str(path)
        self.seq = seq
        self.reason = reason
        where = f"seq {seq}" if seq is not None else "unreadable seq"
        super().__init__(f"identity ledger {path} failed verification ({where}): {reason}")


class IdentityLedger:
    """The append-only JSONL store for one ledger file.

    Open it over a path; an existing file is read back and verified before
    anything else may happen, so corruption surfaces at open rather than at
    whatever query trusted it later::

        ledger = IdentityLedger(base / "tenant-a.identity-ledger.jsonl")
        ledger.record(logical_id="ku_warranty", kind=LedgerKind.NEW)

    Appends take an internal lock, write one canonical line, flush and
    ``fsync`` before returning. Nothing updates or deletes; the only way a
    historical line changes is outside this class, and that is precisely
    what :meth:`verify` and re-opening exist to detect.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._entries: list[LedgerEntry] = []
        self._digests: list[str] = []
        self._lock = threading.Lock()
        if self._path.exists():
            self._entries, self._digests = self._read_and_verify()

    # -- reading -----------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def next_seq(self) -> int:
        return len(self._entries) + 1

    @property
    def last_digest(self) -> str:
        """The head digest; the genesis digest while the ledger is empty."""
        return self._digests[-1] if self._digests else GENESIS_DIGEST

    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(tuple(self._entries))

    def replay(self) -> dict[str, IdentityState]:
        """The current identity map, restored from this ledger's entries."""
        return replay(self._entries)

    def verify(self) -> None:
        """Re-read the file from disk and hold it against the chain.

        Fails on any content/digest mismatch, broken linkage, malformed
        line, or sequence anomaly -- and on the disk file no longer matching
        what this handle appended, which is how a truncated or externally
        extended ledger gets caught rather than adopted.
        """
        with self._lock:
            entries, _ = self._read_and_verify()
            if len(entries) != len(self._entries):
                raise LedgerTamperedError(
                    self._path,
                    None,
                    f"the file holds {len(entries)} records but this handle "
                    f"appended {len(self._entries)} (records removed or added "
                    "outside this handle)",
                )
            for position, (on_disk, in_memory) in enumerate(
                zip(entries, self._entries, strict=True), start=1
            ):
                if on_disk != in_memory:
                    raise LedgerTamperedError(
                        self._path,
                        on_disk.seq,
                        f"record {position} on disk differs from the record "
                        "this handle appended",
                    )

    # -- appending ---------------------------------------------------------

    def append(self, entry: LedgerEntry) -> LedgerEntry:
        """Append one entry; its ``seq`` must be exactly the next number.

        Anything else is a forgery attempt against the ordering and is
        refused before a byte is written: a used or lower ``seq`` is reuse or
        a reverse append, a higher one skips a number that was never
        assigned.
        """
        with self._lock:
            return self._append_locked(entry)

    def record(
        self,
        *,
        logical_id: str,
        kind: LedgerKind,
        prior_ids: Sequence[str] = (),
        evidence_refs: Sequence[str] = (),
        note: str = "",
        ts_utc: datetime | None = None,
    ) -> LedgerEntry:
        """Build the next entry with the current UTC time and append it."""
        with self._lock:
            entry = LedgerEntry(
                seq=len(self._entries) + 1,
                ts_utc=ts_utc if ts_utc is not None else _utc_now(),
                logical_id=logical_id,
                kind=kind,
                prior_ids=tuple(prior_ids),
                evidence_refs=tuple(evidence_refs),
                note=note,
            )
            return self._append_locked(entry)

    def _append_locked(self, entry: LedgerEntry) -> LedgerEntry:
        expected = len(self._entries) + 1
        if entry.seq < expected:
            raise ValueError(
                f"seq {entry.seq} is already recorded or behind the head "
                f"({len(self._entries)}); the ledger is append-only"
            )
        if entry.seq > expected:
            raise ValueError(
                f"seq {entry.seq} skips ahead of the head; expected "
                f"{expected} next and no number may go unassigned"
            )
        digest = _chain_digest(self.last_digest, entry.payload)
        record = dict(entry.payload)
        record["digest"] = digest
        parent = self._path.parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(_canonical(record) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._entries.append(entry)
        self._digests.append(digest)
        return entry

    # -- verification ------------------------------------------------------

    def _read_and_verify(self) -> tuple[list[LedgerEntry], list[str]]:
        text = self._path.read_text(encoding="utf-8")
        lines = text.splitlines()
        entries: list[LedgerEntry] = []
        digests: list[str] = []
        previous = GENESIS_DIGEST
        for position, raw in enumerate(lines, start=1):
            stripped = raw.strip()
            if not stripped:
                raise LedgerTamperedError(
                    self._path, None, f"blank line at line {position}"
                )
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise LedgerTamperedError(
                    self._path, None, f"line {position} is not valid JSON ({exc.msg})"
                ) from exc
            if not isinstance(record, dict):
                raise LedgerTamperedError(
                    self._path, None, f"line {position} is not a JSON object"
                )
            stored_digest = record.pop("digest", None)
            if not isinstance(stored_digest, str) or not stored_digest:
                raise LedgerTamperedError(
                    self._path,
                    None,
                    f"line {position} carries no digest; it was not written here",
                )
            try:
                entry = LedgerEntry.from_payload(record)
            except ValueError as exc:
                seq = record.get("seq") if isinstance(record.get("seq"), int) else None
                raise LedgerTamperedError(
                    self._path, seq, f"line {position}: {exc}"
                ) from exc
            if _chain_digest(previous, entry.payload) != stored_digest:
                raise LedgerTamperedError(
                    self._path,
                    entry.seq,
                    f"stored digest does not match the record's content at "
                    f"line {position} (edited or replaced)",
                )
            expected_seq = len(entries) + 1
            if entry.seq != expected_seq:
                raise LedgerTamperedError(
                    self._path,
                    entry.seq,
                    f"expected seq {expected_seq} at line {position}, found "
                    f"{entry.seq} (gap, reuse, or reorder)",
                )
            previous = stored_digest
            entries.append(entry)
            digests.append(stored_digest)
        return entries, digests


# ---------------------------------------------------------------------------
# Replay — the current identity map from the transitions alone
# ---------------------------------------------------------------------------


class IdentityStatus(StrEnum):
    """Where an identity stands after the entries are folded in."""

    ACTIVE = "ACTIVE"
    ABSORBED = "ABSORBED"
    RETIRED = "RETIRED"


@dataclass(frozen=True, slots=True)
class IdentityState:
    """One identity as the ledger left it.

    ``status`` is mechanical: the last transition touching an id wins, so an
    id retired and later matched again reads ACTIVE again -- the ledger says
    what happened, and this map reports exactly that. ``lineage`` collects
    every distinct prior id the identity's transitions named, in first-seen
    order. For ``ABSORBED`` ids, ``absorbed_into`` points at the survivor;
    a split original absorbed into several successors points at whichever
    successor's entry came last, and each successor's own lineage still
    names the original.
    """

    logical_id: str
    status: IdentityStatus
    first_seq: int
    last_seq: int
    transitions: int
    lineage: tuple[str, ...] = ()
    absorbed_into: str | None = None


@dataclass(slots=True)
class _MutableState:
    logical_id: str
    status: IdentityStatus = IdentityStatus.ACTIVE
    first_seq: int = 0
    last_seq: int = 0
    transitions: int = 0
    lineage: list[str] = field(default_factory=list)
    absorbed_into: str | None = None

    def freeze(self) -> IdentityState:
        return IdentityState(
            logical_id=self.logical_id,
            status=self.status,
            first_seq=self.first_seq,
            last_seq=self.last_seq,
            transitions=self.transitions,
            lineage=tuple(self.lineage),
            absorbed_into=self.absorbed_into,
        )


def replay(entries: Iterable[LedgerEntry]) -> dict[str, IdentityState]:
    """Fold transitions into the current identity map, keyed by logical id.

    Every id that is ever a transition *subject* appears in the result, in
    first-appearance order. ``NEW`` founds or re-founds an identity as ACTIVE;
    ``MATCH`` continues one and records its (non-self) priors as lineage;
    ``MERGE``/``SPLIT`` make the subject ACTIVE and mark each prior -- the
    subject itself excluded, founded on the spot if unknown -- ABSORBED into
    it; ``RETIRE`` makes the subject RETIRED. The fold is a pure function of
    its input, which is what lets a restored ledger answer for the live one.
    """
    states: dict[str, _MutableState] = {}

    def state_for(logical_id: str, *, seq: int) -> _MutableState:
        existing = states.get(logical_id)
        if existing is None:
            existing = _MutableState(logical_id=logical_id, first_seq=seq)
            states[logical_id] = existing
        return existing

    for entry in entries:
        subject = state_for(entry.logical_id, seq=entry.seq)
        subject.last_seq = entry.seq
        subject.transitions += 1
        priors = [pid for pid in entry.prior_ids if pid != entry.logical_id]
        if entry.kind is LedgerKind.RETIRE:
            subject.status = IdentityStatus.RETIRED
            subject.absorbed_into = None
            continue
        subject.status = IdentityStatus.ACTIVE
        subject.absorbed_into = None
        for pid in priors:
            if pid not in subject.lineage:
                subject.lineage.append(pid)
        if entry.kind in (LedgerKind.MERGE, LedgerKind.SPLIT):
            for pid in priors:
                absorbed = state_for(pid, seq=entry.seq)
                absorbed.status = IdentityStatus.ABSORBED
                absorbed.absorbed_into = entry.logical_id

    return {logical_id: state.freeze() for logical_id, state in states.items()}


# ---------------------------------------------------------------------------
# Recording resolver decisions
# ---------------------------------------------------------------------------


class LedgerDecisionRecorder(IdentityDecisionRecorder):
    """The reference :class:`IdentityDecisionRecorder`: decisions to entries.

    MATCHED becomes ``MATCH`` with the decision's candidates as priors, NEW
    becomes ``NEW``, and AMBIGUOUS is dropped -- an abstention is not a
    transition. Evidence refs and the note are per-recorder context (a
    document version, a compile run), since neither lives on a decision::

        recorder = LedgerDecisionRecorder(ledger, note=f"compile {run_id}")
        decision = resolver.resolve(incoming, previous, recorder=recorder)
    """

    def __init__(
        self,
        ledger: IdentityLedger,
        *,
        note: str = "",
        evidence_refs: Sequence[str] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._ledger = ledger
        self._note = note
        self._evidence_refs = tuple(evidence_refs)
        self._clock = clock if clock is not None else _utc_now

    @property
    def ledger(self) -> IdentityLedger:
        return self._ledger

    def record_identity_decision(
        self,
        *,
        decision: LogicalIdentityDecision,
        incoming: LogicalUnitFingerprint,
        partner: LogicalUnitFingerprint | None = None,
    ) -> None:
        """Map one decision onto the ledger; nothing is written for AMBIGUOUS.

        ``incoming`` and ``partner`` are accepted for protocol parity and for
        richer subclasses -- the mapping below needs only the decision. The
        entry lands at the head of ``self.ledger`` when one was written.
        """
        if decision.match is LogicalMatch.AMBIGUOUS:
            return
        if decision.logical_id is None:
            raise ValueError(
                f"a decided outcome must carry a logical id, got match="
                f"{decision.match!r} with logical_id=None"
            )
        if decision.match is LogicalMatch.MATCHED:
            kind = LedgerKind.MATCH
            prior_ids: tuple[str, ...] = decision.candidates
        elif decision.match is LogicalMatch.NEW:
            kind = LedgerKind.NEW
            prior_ids = ()
        else:
            raise ValueError(f"unrecognised identity outcome: {decision.match!r}")
        self._ledger.record(
            logical_id=decision.logical_id,
            kind=kind,
            prior_ids=prior_ids,
            evidence_refs=self._evidence_refs,
            note=self._note,
            ts_utc=self._clock(),
        )
