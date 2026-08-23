"""The receipt of what an answer consumed — and the append-only ledger of them.

Mission §9. Every time a consumer (an MCP tool call, an API route, an ask) is
served from a compiled world, *what* it was served is decided twice: once when
it happens, and again later whenever anyone asks "what did that answer actually
see?". The first deciding is easy and forgettable; the second is impossible
unless the first one was written down. This module writes it down.

A :class:`ConsumptionReceipt` names the consumption precisely: who consumed,
through which tool, against which ``world_state_id``, which claims and evidence
were in play, under which permission snapshot and which policy revision, with
what outcome and the hash of the artifact that was served back. ``mint()``
seals those declared fields into one sha256 content digest — change a single
field and the mint changes, so two records can only agree by recording the
same consumption.

A :class:`ConsumptionLedger` keeps the receipts append-only on disk, one JSON
line per receipt, flushed and ``fsync``-ed before ``append`` returns. Each line
chains through ``seq`` and ``prev_digest`` onto everything recorded before it,
rooted at the genesis digest, so editing, reordering, deleting or skipping any
historical line breaks every link after it and fails loudly at open — the same
tamper-evidence the identity transition ledger gives §15.5. Nothing updates,
nothing deletes; the queries (:meth:`ConsumptionLedger.query_claims_before_stale`,
:meth:`ConsumptionLedger.query_world_consumers`) answer from history alone,
which is exactly why a claim that has since gone stale still shows every past
consumption of it.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from pathlib import Path

__all__ = [
    "GENESIS_DIGEST",
    "ConsumerType",
    "ConsumptionLedger",
    "ConsumptionOutcome",
    "ConsumptionReceipt",
    "LedgerTamperedError",
    "RecordedReceipt",
]

#: The digest every chain starts from. A first record chained to anything
#: else was not written by this module.
GENESIS_DIGEST = "0" * 64

_SEPARATOR = "\x1e"

_LEDGER_FILENAME = "consumption-ledger.jsonl"


class ConsumerType(StrEnum):
    """The four kinds of consumer a receipt can name. Values are wire spelling."""

    MCP = "mcp"
    API = "api"
    ASK = "ask"
    TEST = "test"


class ConsumptionOutcome(StrEnum):
    """§22.3's closed outcome set, as the consumer experienced it."""

    CURRENT = "CURRENT"
    STALE = "STALE"
    CONFLICT = "CONFLICT"
    UNRESOLVED = "UNRESOLVED"
    NOT_AUTHORIZED = "NOT_AUTHORIZED"


def _canonical(payload: dict[str, object]) -> str:
    """The byte-exact spelling a digest is taken over."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _require_utc(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{name} must be a datetime")
    offset = value.utcoffset()
    if offset is None:
        raise ValueError(f"{name} must be timezone-aware")
    if offset != timedelta(0):
        raise ValueError(
            f"{name} must be UTC, got offset {offset}; "
            "convert before recording so ledgers on two machines agree"
        )
    return value


def _require_str(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {type(value).__name__}")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{name} is required")
    return stripped


def _require_str_tuple(name: str, value: Sequence[object]) -> tuple[str, ...]:
    cleaned: list[str] = []
    for member in value:
        cleaned.append(_require_str(f"{name} member", member))
    return tuple(cleaned)


@dataclass(frozen=True, slots=True)
class ConsumptionReceipt:
    """What one consumption consumed, sealed at the moment it happened.

    ``requested_at`` is timezone-aware UTC — a local wall-clock stamp would make
    two ledgers disagree about ordering that the ledger's sequence numbers
    already settle. ``permission_snapshot_ref`` points at the permission state
    the disclosure decision was made against, not a copy of it; ``policy_revision``
    names the revision that governed, so replay can hold the answer against the
    policy *as it was known then*. ``model_identity`` is optional because not
    every consumer routes through a model, and "none" is information too.
    """

    receipt_id: str
    consumer_type: ConsumerType
    consumer_id: str
    request_id: str
    query_tool: str
    requested_at: datetime
    world_state_id: str
    claim_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    permission_snapshot_ref: str
    policy_revision: str
    outcome: ConsumptionOutcome
    response_artifact_hash: str
    model_identity: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _require_str("receipt_id", self.receipt_id))
        try:
            consumer_type = ConsumerType(self.consumer_type)
        except ValueError as exc:
            raise ValueError(
                f"consumer_type must be one of {[member.value for member in ConsumerType]}, "
                f"got {self.consumer_type!r}"
            ) from exc
        object.__setattr__(self, "consumer_type", consumer_type)
        object.__setattr__(self, "consumer_id", _require_str("consumer_id", self.consumer_id))
        object.__setattr__(self, "request_id", _require_str("request_id", self.request_id))
        object.__setattr__(self, "query_tool", _require_str("query_tool", self.query_tool))
        _require_utc("requested_at", self.requested_at)
        object.__setattr__(
            self, "world_state_id", _require_str("world_state_id", self.world_state_id)
        )
        object.__setattr__(self, "claim_ids", _require_str_tuple("claim_ids", self.claim_ids))
        object.__setattr__(
            self, "evidence_ids", _require_str_tuple("evidence_ids", self.evidence_ids)
        )
        object.__setattr__(
            self,
            "permission_snapshot_ref",
            _require_str("permission_snapshot_ref", self.permission_snapshot_ref),
        )
        object.__setattr__(
            self, "policy_revision", _require_str("policy_revision", self.policy_revision)
        )
        try:
            outcome = ConsumptionOutcome(self.outcome)
        except ValueError as exc:
            raise ValueError(f"unknown consumption outcome: {self.outcome!r}") from exc
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(
            self,
            "response_artifact_hash",
            _require_str("response_artifact_hash", self.response_artifact_hash),
        )
        if self.model_identity is not None:
            object.__setattr__(
                self, "model_identity", _require_str("model_identity", self.model_identity)
            )

    @property
    def payload(self) -> dict[str, object]:
        """The canonical field dict a record stores and a mint covers."""
        return {
            "receipt_id": self.receipt_id,
            "consumer_type": self.consumer_type.value,
            "consumer_id": self.consumer_id,
            "request_id": self.request_id,
            "query_tool": self.query_tool,
            "requested_at": self.requested_at.isoformat(),
            "world_state_id": self.world_state_id,
            "claim_ids": list(self.claim_ids),
            "evidence_ids": list(self.evidence_ids),
            "permission_snapshot_ref": self.permission_snapshot_ref,
            "policy_revision": self.policy_revision,
            "outcome": self.outcome.value,
            "response_artifact_hash": self.response_artifact_hash,
            "model_identity": self.model_identity,
        }

    @classmethod
    def from_payload(cls, payload: object) -> ConsumptionReceipt:
        """Rebuild a receipt from its stored dict, rejecting anything else.

        Unknown fields are refused rather than ignored: a record carrying a
        field this version does not understand is not a record this version
        wrote, and accepting it silently would be exactly the tampering the
        digest chain exists to catch.
        """
        if not isinstance(payload, dict):
            raise ValueError(f"a receipt must be a JSON object, got {type(payload).__name__}")
        expected = {
            "receipt_id",
            "consumer_type",
            "consumer_id",
            "request_id",
            "query_tool",
            "requested_at",
            "world_state_id",
            "claim_ids",
            "evidence_ids",
            "permission_snapshot_ref",
            "policy_revision",
            "outcome",
            "response_artifact_hash",
            "model_identity",
        }
        present = set(payload)
        missing = sorted(expected - present)
        unknown = sorted(present - expected)
        if missing or unknown:
            raise ValueError(
                f"receipt shape mismatch (missing={missing}, unknown={unknown})"
            )
        raw_requested_at = payload["requested_at"]
        if not isinstance(raw_requested_at, str):
            raise ValueError("requested_at must be an ISO-8601 string")
        try:
            requested_at = datetime.fromisoformat(raw_requested_at)
        except ValueError as exc:
            raise ValueError(f"requested_at is not ISO-8601: {raw_requested_at!r}") from exc
        for list_field in ("claim_ids", "evidence_ids"):
            if not isinstance(payload[list_field], list):
                raise ValueError(f"{list_field} must be a JSON array")
        model_identity = payload["model_identity"]
        if model_identity is not None and not isinstance(model_identity, str):
            raise ValueError("model_identity must be a string or null")
        return cls(
            receipt_id=payload["receipt_id"],
            consumer_type=payload["consumer_type"],
            consumer_id=payload["consumer_id"],
            request_id=payload["request_id"],
            query_tool=payload["query_tool"],
            requested_at=requested_at,
            world_state_id=payload["world_state_id"],
            claim_ids=tuple(payload["claim_ids"]),
            evidence_ids=tuple(payload["evidence_ids"]),
            permission_snapshot_ref=payload["permission_snapshot_ref"],
            policy_revision=payload["policy_revision"],
            outcome=payload["outcome"],
            response_artifact_hash=payload["response_artifact_hash"],
            model_identity=model_identity,
        )

    def mint(self) -> str:
        """The sha256 content digest this receipt contributes to the chain.

        Deterministic over exactly the declared fields: the same consumption
        recorded twice mints the same digest, and any edited field — a swapped
        claim id, a shifted timestamp — mints a different one.
        """
        return hashlib.sha256(_canonical(self.payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RecordedReceipt:
    """One receipt at its position in the chain.

    ``seq`` is 1-based and gap-free over a ledger; the store assigns it and
    never trusts it. ``prev_digest`` is the digest of the record appended just
    before this one (the genesis digest for the first), and ``digest`` commits
    to all three: everything before it, this position, and the receipt itself.
    """

    seq: int
    prev_digest: str
    digest: str
    receipt: ConsumptionReceipt


def _link_digest(prev_digest: str, seq: int, receipt_mint: str) -> str:
    body = _SEPARATOR.join((prev_digest, str(seq), receipt_mint))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class LedgerTamperedError(RuntimeError):
    """The ledger on disk no longer matches the history it recorded.

    Raised on open and by :meth:`ConsumptionLedger.verify` when a receipt's
    content no longer matches its digest, the chain has a broken link, the
    sequence numbers skip, repeat or run backwards, or a line is not the
    record that was written. ``seq`` is the offending sequence number where
    one could be read and ``None`` otherwise.
    """

    def __init__(self, path: Path | str, seq: int | None, reason: str) -> None:
        self.path = str(path)
        self.seq = seq
        self.reason = reason
        where = f"seq {seq}" if seq is not None else "unreadable seq"
        super().__init__(f"consumption ledger {path} failed verification ({where}): {reason}")


class ConsumptionLedger:
    """The append-only JSONL store of consumption receipts for one directory.

    Open it over a directory; the ledger lives at ``consumption-ledger.jsonl``
    inside it, and an existing file is read back and verified before anything
    else may happen, so corruption surfaces at open rather than at whatever
    query trusted it later::

        ledger = ConsumptionLedger(runtime_dir / "ledger")
        ledger.append(receipt)

    Appends take an internal lock, write one canonical line, flush and
    ``fsync`` before returning. Nothing updates or deletes; the only way a
    historical line changes is outside this class, and that is precisely what
    :meth:`verify` and re-opening exist to detect.
    """

    FILENAME = _LEDGER_FILENAME

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        self._dir = Path(directory)
        self._path = self._dir / _LEDGER_FILENAME
        self._records: list[RecordedReceipt] = []
        self._lock = threading.Lock()
        self._dir.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            self._records = self._read_and_verify()

    # -- reading -----------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    @property
    def next_seq(self) -> int:
        return len(self._records) + 1

    @property
    def last_digest(self) -> str:
        """The head digest; the genesis digest while the ledger is empty."""
        return self._records[-1].digest if self._records else GENESIS_DIGEST

    def entries(self) -> tuple[RecordedReceipt, ...]:
        return tuple(self._records)

    def __len__(self) -> int:
        return len(self._records)

    def __iter__(self) -> Iterator[RecordedReceipt]:
        return iter(tuple(self._records))

    # -- appending ---------------------------------------------------------

    def append(self, receipt: ConsumptionReceipt) -> RecordedReceipt:
        """Seal one receipt at the head of the chain and durably record it.

        The sequence number is assigned here, which is what makes a skipped or
        reused number impossible on the append path: there is nothing a caller
        can pass. A gap appearing on disk therefore means someone rewrote the
        file, and :meth:`_read_and_verify` refuses it at open.
        """
        with self._lock:
            seq = len(self._records) + 1
            prev_digest = self.last_digest
            digest = _link_digest(prev_digest, seq, receipt.mint())
            record = {
                "seq": seq,
                "prev_digest": prev_digest,
                "digest": digest,
                "receipt": receipt.payload,
            }
            parent = self._path.parent
            if str(parent):
                parent.mkdir(parents=True, exist_ok=True)
            with open(self._path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(_canonical(record) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            recorded = RecordedReceipt(
                seq=seq, prev_digest=prev_digest, digest=digest, receipt=receipt
            )
            self._records.append(recorded)
            return recorded

    # -- verification ------------------------------------------------------

    def verify(self) -> None:
        """Re-read the file from disk and hold it against the chain.

        Fails on any content/digest mismatch, broken linkage, malformed line,
        or sequence anomaly — and on the disk file no longer matching what
        this handle appended, which is how a truncated or externally extended
        ledger gets caught rather than adopted.
        """
        with self._lock:
            records = self._read_and_verify()
            if len(records) != len(self._records):
                raise LedgerTamperedError(
                    self._path,
                    None,
                    f"the file holds {len(records)} records but this handle "
                    f"appended {len(self._records)} (records removed or added "
                    "outside this handle)",
                )
            for position, (on_disk, in_memory) in enumerate(
                zip(records, self._records, strict=True), start=1
            ):
                if on_disk != in_memory:
                    raise LedgerTamperedError(
                        self._path,
                        on_disk.seq,
                        f"record {position} on disk differs from the record "
                        "this handle appended",
                    )

    def _read_and_verify(self) -> list[RecordedReceipt]:
        text = self._path.read_text(encoding="utf-8")
        lines = text.splitlines()
        records: list[RecordedReceipt] = []
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
            stored_digest = record.get("digest")
            prev_digest = record.get("prev_digest")
            seq = record.get("seq")
            receipt_payload = record.get("receipt")
            if not isinstance(stored_digest, str) or not stored_digest:
                raise LedgerTamperedError(
                    self._path,
                    None,
                    f"line {position} carries no digest; it was not written here",
                )
            if isinstance(seq, bool) or not isinstance(seq, int):
                raise LedgerTamperedError(
                    self._path, None, f"line {position} has no usable seq"
                )
            try:
                receipt = ConsumptionReceipt.from_payload(receipt_payload)
            except ValueError as exc:
                raise LedgerTamperedError(
                    self._path, seq if isinstance(seq, int) else None, f"line {position}: {exc}"
                ) from exc
            if _link_digest(str(prev_digest), seq, receipt.mint()) != stored_digest:
                raise LedgerTamperedError(
                    self._path,
                    seq,
                    f"stored digest does not match the record's content at "
                    f"line {position} (edited or replaced)",
                )
            if prev_digest != previous:
                raise LedgerTamperedError(
                    self._path,
                    seq,
                    f"broken chain at line {position}: prev_digest does not match "
                    "the previous record's digest",
                )
            expected_seq = len(records) + 1
            if seq != expected_seq:
                raise LedgerTamperedError(
                    self._path,
                    seq,
                    f"expected seq {expected_seq} at line {position}, found "
                    f"{seq} (gap, reuse, or reorder)",
                )
            previous = stored_digest
            records.append(
                RecordedReceipt(
                    seq=seq, prev_digest=str(prev_digest), digest=stored_digest, receipt=receipt
                )
            )
        return records

    # -- queries -----------------------------------------------------------

    def query_claims_before_stale(
        self, claim_id: str, *, as_of: datetime
    ) -> tuple[ConsumptionReceipt, ...]:
        """Every recorded consumption of ``claim_id`` up to ``as_of``.

        Answers from history alone: the claim may have gone stale, been
        superseded or vanished from the current world entirely since, and the
        consumptions still show — that permanence is what the ledger is for.
        Results are in ledger (chronological) order.
        """
        _require_str("claim_id", claim_id)
        _require_utc("as_of", as_of)
        return tuple(
            record.receipt
            for record in self._records
            if claim_id in record.receipt.claim_ids
            and record.receipt.requested_at <= as_of
        )

    def query_world_consumers(self, world_state_id: str) -> tuple[ConsumptionReceipt, ...]:
        """Every receipt served from ``world_state_id``, in ledger order.

        Each receipt carries its consumer, so this answers "who read this
        world, when, through what, and with what outcome"; project onto
        ``consumer_type``/``consumer_id`` for the bare consumer list.
        """
        _require_str("world_state_id", world_state_id)
        return tuple(
            record.receipt
            for record in self._records
            if record.receipt.world_state_id == world_state_id
        )
