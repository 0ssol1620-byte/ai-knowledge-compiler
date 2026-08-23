"""The identity transition ledger keeps history the way §15.5 demands.

Three properties are load-bearing and each gets its own section: appended
entries replay into the identity map they were written from; anything that
edits, reorders, skips or truncates the recorded history is refused loudly;
and a resolver asked to keep its decisions writes exactly one entry per
decided transition -- and nothing for an abstention.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timezone
from pathlib import Path

import akc_cir.identity_ledger as identity_ledger
import pytest
from akc_cir.identity import (
    LogicalIdentityResolver,
    LogicalMatch,
    LogicalUnitFingerprint,
)
from akc_cir.identity_ledger import (
    GENESIS_DIGEST,
    IdentityLedger,
    IdentityStatus,
    LedgerDecisionRecorder,
    LedgerEntry,
    LedgerKind,
    LedgerTamperedError,
    replay,
)

REPOSITORY = Path(__file__).resolve().parents[2]

_TS = datetime(2026, 8, 23, 12, 0, 0, tzinfo=UTC)

SRC = "src_acme_warranty"


def _entry(
    seq: int,
    logical_id: str = "ku_warranty",
    kind: LedgerKind = LedgerKind.NEW,
    *,
    prior_ids: tuple[str, ...] = (),
    evidence_refs: tuple[str, ...] = ("ev_1",),
    note: str = "",
) -> LedgerEntry:
    return LedgerEntry(
        seq=seq,
        ts_utc=_TS,
        logical_id=logical_id,
        kind=kind,
        prior_ids=prior_ids,
        evidence_refs=evidence_refs,
        note=note,
    )


def _unit(
    logical_id: str,
    *,
    path: tuple[str, ...] = ("Warranty", "Coverage"),
    anchor: str = "4.2 Exceptions",
    text: str = "The warranty covers parts and labour for two years from delivery.",
    neighbours: tuple[str, ...] = ("4.1 Scope", "4.3 Claims"),
    lineage: str = SRC,
    identifier: str = "4.2",
    style: str = "body 10pt indent-0",
) -> LogicalUnitFingerprint:
    return LogicalUnitFingerprint.of(
        logical_id=logical_id,
        document_path=path,
        anchor=anchor,
        text=text,
        source_lineage=lineage,
        explicit_identifier=identifier,
        geometry_style=style,
        neighbour_anchors=neighbours,
    )


def _lines(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# --------------------------------------------------------------------------
# Append → replay equivalence: the map comes back from the transitions alone
# --------------------------------------------------------------------------


def test_appended_entries_replay_to_the_expected_identity_map(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.record(logical_id="ku_warranty", kind=LedgerKind.NEW)
    ledger.record(logical_id="ku_shipping", kind=LedgerKind.NEW)
    # The two identities merge; ku_warranty survives.
    ledger.record(
        logical_id="ku_warranty", kind=LedgerKind.MERGE, prior_ids=("ku_shipping",)
    )
    # The survivor later splits in two.
    ledger.record(
        logical_id="ku_split_a", kind=LedgerKind.SPLIT, prior_ids=("ku_warranty",)
    )
    ledger.record(
        logical_id="ku_split_b", kind=LedgerKind.SPLIT, prior_ids=("ku_warranty",)
    )
    # And one of the successors retires.
    ledger.record(logical_id="ku_split_b", kind=LedgerKind.RETIRE)

    states = ledger.replay()

    assert states["ku_shipping"].status is IdentityStatus.ABSORBED
    assert states["ku_shipping"].absorbed_into == "ku_warranty"
    assert states["ku_warranty"].status is IdentityStatus.ABSORBED
    assert states["ku_warranty"].lineage == ("ku_shipping",)
    assert states["ku_split_a"].status is IdentityStatus.ACTIVE
    assert states["ku_split_a"].lineage == ("ku_warranty",)
    assert states["ku_split_b"].status is IdentityStatus.RETIRED
    assert states["ku_split_b"].lineage == ("ku_warranty",)
    assert states["ku_split_a"].first_seq == 4
    assert states["ku_split_b"].transitions == 2


def test_reopening_the_ledger_yields_identical_entries_and_map(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    first = IdentityLedger(path)
    first.record(logical_id="ku_a", kind=LedgerKind.NEW)
    first.record(
        logical_id="ku_b", kind=LedgerKind.MATCH, prior_ids=("ku_a",), note="kept"
    )

    reopened = IdentityLedger(path)

    assert reopened.entries() == first.entries()
    assert len(reopened) == 2
    assert reopened.replay() == first.replay()
    assert reopened.replay()["ku_a"].status is IdentityStatus.ACTIVE


def test_replay_is_a_pure_function_of_the_entries() -> None:
    entries = [
        _entry(1, "ku_a"),
        _entry(2, "ku_b", LedgerKind.MERGE, prior_ids=("ku_a",)),
    ]
    assert replay(entries) == replay(list(entries))
    assert list(replay(iter(entries))) == ["ku_a", "ku_b"]


def test_a_match_records_the_continued_prior_in_lineage(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.record(logical_id="ku_new_home", kind=LedgerKind.NEW)
    ledger.record(
        logical_id="ku_new_home", kind=LedgerKind.MATCH, prior_ids=("ku_old_name",)
    )

    states = ledger.replay()

    assert states["ku_new_home"].status is IdentityStatus.ACTIVE
    assert states["ku_new_home"].lineage == ("ku_old_name",)


def test_retiring_and_then_matching_again_reads_active_again(tmp_path: Path) -> None:
    """Replay is mechanical: the last transition touching an id wins."""
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.record(logical_id="ku_x", kind=LedgerKind.NEW)
    ledger.record(logical_id="ku_x", kind=LedgerKind.RETIRE)
    ledger.record(logical_id="ku_x", kind=LedgerKind.MATCH, prior_ids=("ku_x",))

    assert ledger.replay()["ku_x"].status is IdentityStatus.ACTIVE


# --------------------------------------------------------------------------
# Append-time refusals: seq reuse, reverse appends and skipped numbers
# --------------------------------------------------------------------------


def test_a_used_seq_is_refused(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.append(_entry(1))

    with pytest.raises(ValueError, match="append-only"):
        ledger.append(_entry(1))


def test_an_out_of_order_seq_is_refused(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.append(_entry(1))
    ledger.append(_entry(2))
    ledger.append(_entry(3))

    with pytest.raises(ValueError, match="behind the head"):
        ledger.append(_entry(2))


def test_a_skipped_seq_is_refused(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    ledger.append(_entry(1))

    with pytest.raises(ValueError, match="skips ahead"):
        ledger.append(_entry(3))
    assert len(ledger) == 1, "a refused append must not have been written"


def test_each_entry_is_one_fsynced_line_with_a_chained_digest(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    for seq in (1, 2, 3):
        ledger.append(_entry(seq, f"ku_{seq}"))

    records = _lines(path)
    assert len(records) == 3
    previous = GENESIS_DIGEST
    for record in records:
        digest = record.pop("digest")
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert identity_ledger._chain_digest(previous, record) == digest
        previous = digest
    assert ledger.last_digest == previous != GENESIS_DIGEST


# --------------------------------------------------------------------------
# Tamper detection: edited, replaced, gapped and truncated histories fail
# --------------------------------------------------------------------------


def test_replacing_a_middle_record_is_caught_at_that_line(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    for seq in (1, 2, 3):
        ledger.append(_entry(seq, f"ku_{seq}"))

    lines = path.read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[1])
    forged["logical_id"] = "ku_impostor"
    lines[1] = json.dumps(forged)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperedError) as excinfo:
        IdentityLedger(path)
    assert excinfo.value.seq == 2
    assert "digest" in excinfo.value.reason


def test_a_rehashed_replacement_still_breaks_the_chain_link(tmp_path: Path) -> None:
    """An attacker who recomputes the forged record's own digest gets no further:
    the next record is still chained to the digest the original had."""
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    for seq in (1, 2, 3):
        ledger.append(_entry(seq, f"ku_{seq}"))

    lines = path.read_text(encoding="utf-8").splitlines()
    real_previous = json.loads(lines[0])["digest"]
    forged = json.loads(lines[1])
    forged.pop("digest")
    forged["logical_id"] = "ku_impostor"
    entry = LedgerEntry.from_payload(forged)
    payload = dict(entry.payload)
    payload["digest"] = identity_ledger._chain_digest(real_previous, entry.payload)
    lines[1] = identity_ledger._canonical(payload)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperedError) as excinfo:
        IdentityLedger(path)
    assert excinfo.value.seq == 3, "the failure must surface at the broken link"


def test_a_gap_on_disk_fails_verification(tmp_path: Path) -> None:
    """Records 1, 2 then 4: every digest valid, the numbering still lies."""
    path = tmp_path / "ledger.jsonl"
    records: list[dict] = []
    previous = GENESIS_DIGEST
    for seq in (1, 2, 4):
        entry = _entry(seq, f"ku_{seq}")
        payload = dict(entry.payload)
        digest = identity_ledger._chain_digest(previous, payload)
        payload["digest"] = digest
        records.append(payload)
        previous = digest
    path.write_text(
        "".join(identity_ledger._canonical(record) + "\n" for record in records),
        encoding="utf-8",
    )

    with pytest.raises(LedgerTamperedError) as excinfo:
        IdentityLedger(path)
    assert excinfo.value.seq == 4
    assert "expected seq 3" in excinfo.value.reason


def test_truncation_is_detected_by_verify(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    for seq in (1, 2, 3):
        ledger.append(_entry(seq, f"ku_{seq}"))

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:2]) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperedError, match="removed or added outside"):
        ledger.verify()


def test_an_edited_note_fails_verification(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    ledger.append(_entry(1, note="original"))
    ledger.append(_entry(2, note="untouched"))

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["note"] = "rewritten by someone else"
    lines[0] = identity_ledger._canonical({**record})
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperedError) as excinfo:
        IdentityLedger(path)
    assert excinfo.value.seq == 1


def test_a_blank_or_garbage_line_fails_verification(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    ledger.append(_entry(1))

    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(LedgerTamperedError, match="blank line"):
        ledger.verify()

    path.write_text(
        path.read_text(encoding="utf-8").rstrip("\n") + "\nnot-json\n",
        encoding="utf-8",
    )
    with pytest.raises(LedgerTamperedError, match="not valid JSON"):
        ledger.verify()


def test_an_unknown_field_in_a_record_fails_verification(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = IdentityLedger(path)
    ledger.append(_entry(1))

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record.pop("digest")
    payload = dict(LedgerEntry.from_payload(record).payload)
    payload["extra"] = "smuggled"
    # A well-formed digest field: it must be the unknown *field* that trips
    # verification here, not a missing one.
    payload["digest"] = GENESIS_DIGEST
    lines[0] = identity_ledger._canonical(payload)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerTamperedError, match="shape mismatch"):
        IdentityLedger(path)


def test_verify_passes_on_an_untouched_ledger(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    for seq in (1, 2, 3):
        kind = LedgerKind.NEW if seq == 1 else LedgerKind.MATCH
        ledger.append(_entry(seq, f"ku_{seq}", kind, prior_ids=("ku_1",)))

    ledger.verify()  # must not raise
    IdentityLedger(ledger.path).verify()


# --------------------------------------------------------------------------
# Recording resolver decisions
# --------------------------------------------------------------------------


def test_resolve_records_a_match(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(ledger, note="compile 42")
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty")]
    incoming = _unit(
        "ku_pending",
        text="The warranty covers parts and labour for three years from delivery.",
    )

    decision = resolver.resolve(incoming, previous, recorder=recorder)

    assert decision.match is LogicalMatch.MATCHED
    assert len(ledger) == 1
    entry = ledger.entries()[0]
    assert entry.seq == 1
    assert entry.kind is LedgerKind.MATCH
    assert entry.logical_id == decision.logical_id == "ku_warranty"
    assert entry.prior_ids == ("ku_warranty",)
    assert entry.note == "compile 42"


def test_resolve_records_new_below_the_floor(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(ledger)
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_warranty")]
    incoming = _unit(
        "ku_seed",
        path=("Shipping", "Carriers"),
        anchor="9.1 Carrier selection",
        text="Shipments are tendered to the carrier with the earliest pickup window.",
        neighbours=("9.0 Overview", "9.2 Rates"),
        identifier="9.1",
        style="body 10pt indent-1",
    )

    decision = resolver.resolve(incoming, previous, seed_logical_id=None, recorder=recorder)

    assert decision.match is LogicalMatch.NEW
    entry = ledger.entries()[0]
    assert entry.kind is LedgerKind.NEW
    assert entry.logical_id == decision.logical_id
    assert entry.prior_ids == ()


def test_ambiguous_decisions_write_nothing(tmp_path: Path) -> None:
    """An abstention transitions nothing, so it produces no entry."""
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(ledger)
    resolver = LogicalIdentityResolver()
    previous = [_unit("ku_left"), _unit("ku_right")]

    decision = resolver.resolve(_unit("ku_pending"), previous, recorder=recorder)

    assert decision.match is LogicalMatch.AMBIGUOUS
    assert len(ledger) == 0
    assert not ledger.path.exists() or ledger.path.read_text(encoding="utf-8") == ""


def test_the_empty_corpus_new_is_recorded(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(ledger)

    decision = LogicalIdentityResolver().resolve(
        _unit("ku_first"), [], recorder=recorder
    )

    assert decision.match is LogicalMatch.NEW
    entry = ledger.entries()[0]
    assert entry.kind is LedgerKind.NEW
    assert entry.logical_id == "ku_first"


def test_decisions_are_identical_with_and_without_a_recorder(tmp_path: Path) -> None:
    resolver = LogicalIdentityResolver()
    incoming = _unit("ku_pending", text="Covers parts, labour and carriage.")
    previous = [_unit("ku_warranty")]

    bare = resolver.resolve(incoming, previous)
    (tmp_path / "ledger.jsonl").touch()
    recorded = resolver.resolve(
        incoming,
        previous,
        recorder=LedgerDecisionRecorder(IdentityLedger(tmp_path / "ledger.jsonl")),
    )

    assert bare == recorded


def test_decide_pair_records_directly(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(ledger)
    resolver = LogicalIdentityResolver()
    partner = _unit("ku_warranty")
    incoming = _unit("ku_pending")
    score, signals, missing = resolver.score_pair(partner, incoming)

    decision = resolver.decide_pair(
        incoming=incoming,
        partner=partner,
        score=score,
        signals=signals,
        missing=missing,
        runner_up=0.0,
        runner_up_id=None,
        seed_logical_id=None,
        recorder=recorder,
    )

    assert decision.match is LogicalMatch.MATCHED
    assert ledger.entries()[0].kind is LedgerKind.MATCH


def test_a_failing_recorder_raises_out_of_resolve(tmp_path: Path) -> None:
    """Half-recorded history is worse than none: failures propagate."""

    class ExplodingRecorder:
        def record_identity_decision(self, **_: object) -> None:
            raise RuntimeError("disk on fire")

    with pytest.raises(RuntimeError, match="disk on fire"):
        LogicalIdentityResolver().resolve(
            _unit("ku_first"), [], recorder=ExplodingRecorder()  # type: ignore[arg-type]
        )


def test_recorder_evidence_refs_land_on_the_entry(tmp_path: Path) -> None:
    ledger = IdentityLedger(tmp_path / "ledger.jsonl")
    recorder = LedgerDecisionRecorder(
        ledger, evidence_refs=("dv_1/ev_9",), clock=lambda: _TS
    )

    LogicalIdentityResolver().resolve(_unit("ku_first"), [], recorder=recorder)

    entry = ledger.entries()[0]
    assert entry.evidence_refs == ("dv_1/ev_9",)
    assert entry.ts_utc == _TS


# --------------------------------------------------------------------------
# Entry validation
# --------------------------------------------------------------------------


def test_a_naive_timestamp_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        LedgerEntry(
            seq=1,
            ts_utc=datetime(2026, 8, 23, 12, 0, 0),
            logical_id="ku_a",
            kind=LedgerKind.NEW,
        )


def test_a_non_utc_offset_is_refused() -> None:
    from datetime import timedelta

    with pytest.raises(ValueError, match="UTC"):
        LedgerEntry(
            seq=1,
            ts_utc=datetime(2026, 8, 23, 21, 0, 0, tzinfo=timezone(timedelta(hours=9))),
            logical_id="ku_a",
            kind=LedgerKind.NEW,
        )


def test_an_entry_round_trips_through_its_payload() -> None:
    entry = _entry(
        7,
        "ku_b",
        LedgerKind.MERGE,
        prior_ids=("ku_a1", "ku_a2"),
        evidence_refs=("ev_1", "ev_2"),
        note="merged",
    )

    restored = LedgerEntry.from_payload(entry.payload)

    assert restored == entry


def test_logical_ids_are_validated() -> None:
    with pytest.raises(ValueError, match="logical_id"):
        _entry(1, logical_id="   ")
    with pytest.raises(ValueError, match="prior_ids member"):
        _entry(1, kind=LedgerKind.MERGE, prior_ids=("",))


# --------------------------------------------------------------------------
# Migration slot integrity
# --------------------------------------------------------------------------


def test_the_identity_ledger_migration_owns_slot_0038_and_chains_from_the_head() -> None:
    path = REPOSITORY / "migrations" / "versions" / "0038_identity_ledger.py"
    source = path.read_text(encoding="utf-8")
    compile(source, str(path), "exec")  # syntax must hold even without alembic

    revision = re.search(r'^revision(?::\s*str)?\s*=\s*"([^"]+)"', source, re.M)
    down_revision = re.search(r'^down_revision\s*=\s*"([^"]+)"', source, re.M)
    assert revision and revision.group(1) == "0038_identity_ledger"
    assert down_revision
    # The slot chains onto the head that existed before it...
    assert down_revision.group(1) == "0037_gpu_post_claim_authorization"
    # ...and becomes the single head itself.
    assert _current_head_revision() == "0038_identity_ledger"


def _current_head_revision() -> str:
    from test_migration_graph import REVISION, VERSIONS, _graph

    _, parents = _graph()
    parented = {parent for parent in parents.values() if parent is not None}
    files: dict[str, str] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        found = REVISION.search(path.read_text(encoding="utf-8"))
        assert found
        files[found.group(1)] = path.name
    heads = [revision for revision in files if revision not in parented]
    assert len(heads) == 1
    return heads[0]


def test_the_whole_migration_graph_stays_single_chained() -> None:
    """The guard the 0023 fork earned: my slot may not fork it again."""
    from test_migration_graph import _graph

    files, parents = _graph()
    children: dict[object, list[str]] = {}
    for child_revision, parent in parents.items():
        children.setdefault(parent, []).append(str(child_revision))
    forks = {parent: kids for parent, kids in children.items() if parent and len(kids) > 1}
    assert forks == {}
    parented = {parent for parent in parents.values() if parent is not None}
    assert sum(1 for revision in files if revision not in parented) == 1
