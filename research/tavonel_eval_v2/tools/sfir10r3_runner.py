#!/usr/bin/env python3
"""SFIR10R3 roster generation and resumable capacity census.

This file is part of the prospective instrument and must be committed and frozen
before partition three is opened.  It intentionally prints no partial candidate
counts, C, Q, or per-root yields.  Durable state exists for resumption; scientific
interpretation happens only after the census is terminal and sealed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import urllib.parse
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
TOOLS = NS / "tools"
sys.path.insert(0, str(TOOLS))

import sfir8_frontier as frontier_module  # noqa: E402
import sfir9_cohort_input as cohort_input  # noqa: E402
import sfir9_selection as predecessor_selection  # noqa: E402
import sfir10r3_protocol as protocol  # noqa: E402
import sfir10r3_transport as transport_module  # noqa: E402

FREEZE_RECEIPT = NS / "receipts/sfir10r3-instrument-freeze.json"
INPUT_RECEIPT = NS / "receipts/sfir10r3-cohort-input-binding.json"
ROSTER_RECEIPT = NS / "receipts/sfir10r3-cohort-roster.json"
SFIR9_ROSTER = NS / "receipts/sfir9-cohort-roster.json"
RUNTIME = NS / "runtime/sfir10r3"
STATE_FILE = RUNTIME / "state.json"
ACTIVE_SEGMENT_FILE = RUNTIME / "active-segment.json"
SEGMENTS_DIR = NS / "receipts/sfir10r3-segments"
CENSUS_RECEIPT = NS / "receipts/sfir10r3-capacity-census.json"
SCORE_RECEIPT = NS / "receipts/sfir10r3-capacity-score.json"
ACCEPTANCE_RECEIPT = NS / "receipts/sfir10r3-capacity-acceptance.json"
TERMINAL_UNPROVEN = NS / "receipts/sfir10r3-terminal-unproven.json"

UNSTARTED = "UNSTARTED"
ACTIVE = "ACTIVE"
EXHAUSTED = "FRONTIER_EXHAUSTED"
STOPPED = "STOPPED_BEFORE_EXHAUSTION"
REFUSED = "REPOSITORY_IDENTITY_REFUSED"
TERMINAL = frozenset({EXHAUSTED, STOPPED, REFUSED})


class RunnerRefused(RuntimeError):
    pass


class ResumeIdentityStopped(RuntimeError):
    """A previously seeded root can no longer be re-attested to the same identity."""


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RunnerRefused(f"required artifact absent: {path.relative_to(NS)}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_once(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RunnerRefused(f"immutable artifact already exists: {path.relative_to(NS)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n")


def verify_freeze() -> dict[str, Any]:
    freeze = _read(FREEZE_RECEIPT)
    body = {k: v for k, v in freeze.items() if k != "freeze_digest"}
    if _digest(body) != freeze.get("freeze_digest"):
        raise RunnerRefused("SFIR10R3 freeze digest does not recompute")
    if freeze.get("protocol_digest") != protocol.Protocol().freeze().digest():
        raise RunnerRefused("live SFIR10R3 protocol does not match the frozen protocol digest")
    instrument_commit = freeze.get("instrument_commit")
    if not isinstance(instrument_commit, str) or not instrument_commit:
        raise RunnerRefused("SFIR10R3 freeze carries no instrument commit")
    for component in freeze.get("components", []):
        relative = component.get("relative_path")
        expected = component.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise RunnerRefused("SFIR10R3 freeze carries a malformed component binding")
        path = REPO / relative
        if not path.is_file():
            raise RunnerRefused(f"frozen component is absent: {relative}")
        working = path.read_bytes()
        observed = "sha256:" + hashlib.sha256(working).hexdigest()
        if observed != expected:
            raise RunnerRefused(f"frozen component moved after freeze: {relative}")
        committed = subprocess.run(  # noqa: S603 - fixed git argv + frozen relative path
            ["git", "show", f"{instrument_commit}:{relative}"],  # noqa: S607
            cwd=REPO,
            capture_output=True,
            check=False,
        )
        if committed.returncode != 0 or committed.stdout != working:
            raise RunnerRefused(
                f"working bytes no longer equal the instrument commit for {relative}"
            )
    return freeze


def verify_input_binding() -> tuple[dict[str, Any], dict[str, Any]]:
    recorded = _read(INPUT_RECEIPT)
    body = {k: v for k, v in recorded.items() if k != "successor_binding_digest"}
    if _digest(body) != recorded.get("successor_binding_digest"):
        raise RunnerRefused("SFIR10 input binding digest does not recompute")
    # Re-derive the underlying binding, including the full 10+ GB hash.  A roster
    # generated from bytes it did not re-check is not the cohort the freeze names.
    fresh = cohort_input.binding(namespace=NS, repository_root=REPO)
    if fresh["binding_digest"] != recorded.get("underlying_binding_digest"):
        raise RunnerRefused("catalogue/readers/frame no longer re-derive to the bound input")
    return recorded, fresh


def _eligible_rows(
    binding: dict[str, Any], tally: Counter[str], parser_tally: Counter[str]
) -> Iterator[dict[str, Any]]:
    import sfir7_catalog_parser as parser
    import sfir7_frame as frame
    import sfir7_projection as projection

    predicates = tuple(
        frame.EligibilityPredicate(
            field=row["field"], op=row["op"], value=row["value"], why="inherited from SFIR7"
        )
        for row in binding["inherited_frame"]["predicates"]
    )
    member = Path(binding["member_verification"]["path"])
    yielded = [0]
    for record, reason in parser.stream_records(member, yielded):
        if record is None:
            parser_tally[reason] += 1
            continue
        projected, sidecar = projection.project(record)
        verdict = "ELIGIBLE"
        for predicate in predicates:
            if not frame._evaluate(predicate, projected):
                verdict = f"REJECTED_{predicate.field}_{predicate.op}"
                break
        tally[verdict] += 1
        if verdict != "ELIGIBLE" or not sidecar.host_uuid:
            if verdict == "ELIGIBLE" and not sidecar.host_uuid:
                tally["ELIGIBLE_BUT_NO_HOST_UUID"] += 1
            continue
        yield {
            "host_uuid": str(sidecar.host_uuid),
            "record_id": str(projected.record_id),
            "name_with_owner": sidecar.name_with_owner,
            "source_rank": int(projected.catalog_rank_value),
        }
    tally["ROWS_READ"] = yielded[0]


def _spent_host_uuids() -> frozenset[str]:
    """Study-history only: identities looked at by SFIR7/8 or exposed in SFIR9."""
    import sfir7_roots

    spent = {str(row["host_uuid"]) for row in sfir7_roots.frozen_roster()}
    prior = _read(SFIR9_ROSTER)
    spent.update(str(row["host_uuid"]) for row in prior["roster"]["entries"])
    return frozenset(spent)


def _selection_rule() -> predecessor_selection.FrozenSelection:
    def term(name: str, value: int, rationale: str) -> predecessor_selection.EnvelopeTerm:
        return predecessor_selection.EnvelopeTerm(
            name=name,
            value=value,
            source=predecessor_selection.EXTERNAL,
            rationale=rationale,
        )

    envelope = predecessor_selection.ExecutionEnvelope(
        permitted_rate_windows=term(
            "permitted_rate_windows",
            protocol.PERMITTED_RATE_WINDOWS,
            "prospectively frozen SFIR10R3 protocol",
        ),
        usable_charge_per_window=term(
            "usable_charge_per_window",
            protocol.USABLE_CHARGE_PER_WINDOW,
            "prospectively frozen SFIR10R3 protocol",
        ),
        per_root_charge_allowance=term(
            "per_root_charge_allowance",
            protocol.PER_ROOT_CHARGE_ALLOWANCE,
            "prospectively frozen SFIR10R3 protocol",
        ),
    )
    return predecessor_selection.FrozenSelection(
        salt=protocol.SELECTION_SALT,
        partition_count=protocol.PARTITION_COUNT,
        partition_index=protocol.PARTITION_INDEX,
        envelope=envelope,
        spent_host_uuids=_spent_host_uuids(),
    )


def generate_roster() -> dict[str, Any]:
    if ROSTER_RECEIPT.exists():
        raise RunnerRefused("SFIR10R3 cohort already opened; roster generation is once-only")
    freeze = verify_freeze()
    recorded_input, fresh_binding = verify_input_binding()

    tally: Counter[str] = Counter()
    parser_tally: Counter[str] = Counter()
    selection = predecessor_selection.select(
        _eligible_rows(fresh_binding, tally, parser_tally), _selection_rule()
    )
    # A short roster is still an interpretable feasibility result; it is sealed
    # as selected rather than regenerated with another partition.
    roster_state = "SEALED_SHORT_ROSTER" if selection["roster_is_short"] else "SEALED"

    rows = []
    for ordinal, row in enumerate(selection["roster"], start=1):
        rows.append(
            {
                "selection_ordinal": ordinal,
                "record_id": str(row["record_id"]),
                "host_uuid": str(row["host_uuid"]),
                "catalogue_address": row["name_with_owner"],
                "source_rank": int(row["source_rank"]),
            }
        )
    roster_body = {
        "schema": "tavonel.sfir10r3.cohort_roster.v1",
        "study_id": protocol.PROTOCOL_ID,
        "state": roster_state,
        "protocol_digest": protocol.Protocol().freeze().digest(),
        "freeze_digest": freeze["freeze_digest"],
        "input_binding_digest": recorded_input["successor_binding_digest"],
        "selection_digest": selection["selection_digest"],
        "partition": {
            "count": protocol.PARTITION_COUNT,
            "index": protocol.PARTITION_INDEX,
            "predecessor_index": protocol.PREDECESSOR_PARTITION_INDEX,
            "salt_digest": protocol.salt_digest(),
        },
        "n": protocol.derive_n(),
        "entry_count": len(rows),
        "entries": rows,
        "spent_exclusion": selection["exclusions"],
        "accounting": {
            "rows_read": tally.pop("ROWS_READ", 0),
            "unreadable": dict(sorted(parser_tally.items())),
            "eligibility_dispositions": dict(sorted(tally.items())),
            "eligible_in_partition": selection["eligible_in_partition"],
        },
        "what_this_does_not_establish": "capacity, C, Q, or any model/compiler endpoint",
    }
    report = {**roster_body, "roster_seal": _digest(roster_body)}
    _write_once(ROSTER_RECEIPT, report)
    return report


def verify_roster() -> dict[str, Any]:
    report = _read(ROSTER_RECEIPT)
    body = {k: v for k, v in report.items() if k != "roster_seal"}
    if _digest(body) != report.get("roster_seal"):
        raise RunnerRefused("SFIR10R3 roster seal does not recompute")
    if report.get("protocol_digest") != protocol.Protocol().freeze().digest():
        raise RunnerRefused("roster belongs to a different protocol")
    entries = report.get("entries", [])
    if [r.get("selection_ordinal") for r in entries] != list(range(1, len(entries) + 1)):
        raise RunnerRefused("roster ordinals are not contiguous")
    if len({r.get("host_uuid") for r in entries}) != len(entries):
        raise RunnerRefused("duplicate repository identity in roster")
    if protocol.REQUIRE_FULL_ROSTER and len(entries) != protocol.derive_n():
        raise RunnerRefused(
            f"sealed roster has {len(entries)} roots, not the prospectively required "
            f"{protocol.derive_n()}; a short cohort is a feasibility result and is not censused"
        )
    return report


def _initial_state(roster: dict[str, Any], freeze: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "tavonel.sfir10r3.runtime_state.v1",
        "study_id": protocol.PROTOCOL_ID,
        "protocol_digest": protocol.Protocol().freeze().digest(),
        "freeze_digest": freeze["freeze_digest"],
        "roster_seal": roster["roster_seal"],
        "windows_used": 0,
        "current_ordinal": 1,
        "root_states": {str(r["selection_ordinal"]): UNSTARTED for r in roster["entries"]},
        "root_provider_charges": {str(r["selection_ordinal"]): 0 for r in roster["entries"]},
        "segment_chain_head": "GENESIS",
        "measurement_unproven": False,
    }


def _load_state(roster: dict[str, Any], freeze: dict[str, Any]) -> dict[str, Any]:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        state = _initial_state(roster, freeze)
        _save_state(state)
        return state
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    if (
        state.get("roster_seal") != roster["roster_seal"]
        or state.get("freeze_digest") != freeze["freeze_digest"]
    ):
        raise RunnerRefused("runtime state belongs to a different frozen roster/instrument")
    return state


def _save_state(state: dict[str, Any]) -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_bytes(json.dumps(state, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    temp.replace(STATE_FILE)


def _write_active_segment(
    *,
    state: dict[str, Any],
    segment_index: int,
    preflight: transport_module.AccountingSanityPreflight,
) -> None:
    body = {
        "schema": "tavonel.sfir10r3.active_segment.v1",
        "study_id": protocol.PROTOCOL_ID,
        "segment_index": segment_index,
        "protocol_digest": state["protocol_digest"],
        "freeze_digest": state["freeze_digest"],
        "roster_seal": state["roster_seal"],
        "accounting_sanity_preflight": preflight.as_dict(),
        "state_digest_before_requests": _digest(state),
        "what_presence_means": (
            "a segment may have issued cohort requests and has not yet completed the "
            "sealed accounting handoff"
        ),
    }
    _write_once(ACTIVE_SEGMENT_FILE, {**body, "active_digest": _digest(body)})


def _recover_closed_active_segment(state: dict[str, Any]) -> dict[str, Any] | None:
    """Recover only if an interrupted process already sealed the whole segment."""
    if not ACTIVE_SEGMENT_FILE.is_file():
        return None
    marker = json.loads(ACTIVE_SEGMENT_FILE.read_text(encoding="utf-8"))
    marker_body = {key: value for key, value in marker.items() if key != "active_digest"}
    if _digest(marker_body) != marker.get("active_digest"):
        return _terminal_unproven("active-segment marker digest does not recompute", state)
    segment_index = int(marker.get("segment_index", -1))
    segment_path = SEGMENTS_DIR / f"segment-{segment_index:02d}.json"
    if not segment_path.is_file():
        return _terminal_unproven(
            "an earlier segment left an active marker without a sealed segment receipt; "
            "request accounting after a crash cannot be reconstructed",
            state,
        )
    segment = json.loads(segment_path.read_text(encoding="utf-8"))
    segment_body = {key: value for key, value in segment.items() if key != "segment_digest"}
    if _digest(segment_body) != segment.get("segment_digest"):
        return _terminal_unproven("sealed segment digest does not recompute", state)
    if segment.get("roster_seal") != state["roster_seal"]:
        return _terminal_unproven("sealed segment belongs to a different roster", state)
    reconciliation = segment.get("provider_reconciliation", {})
    if reconciliation.get("accounting_is_conservative") is not True:
        return _terminal_unproven("sealed segment provider accounting is not conservative", state)
    if reconciliation.get("capacity_evidence_publishable") is not True:
        return _terminal_unproven("sealed segment cannot support capacity evidence", state)
    operational = segment.get("operational_state")
    if not isinstance(operational, dict):
        return _terminal_unproven("sealed segment lacks reconstructible operational state", state)
    for key in ("windows_used", "current_ordinal", "root_states", "root_provider_charges"):
        if key not in operational:
            return _terminal_unproven(f"sealed segment operational state lacks {key}", state)
        state[key] = operational[key]
    state["segment_chain_head"] = segment["segment_digest"]
    _save_state(state)
    ACTIVE_SEGMENT_FILE.unlink()
    return {
        "status": "RECOVERED_ALREADY_SEALED_SEGMENT",
        "segment_index": segment_index,
        "scientific_counts_disclosed": False,
    }


def _root_db(ordinal: int) -> Path:
    return RUNTIME / f"root-{ordinal:03d}.sqlite"


class RootStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.frontier = frontier_module.Frontier(
            path, working_storage_bytes=protocol.DECLARED_WORKING_STORAGE_BYTES
        )
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sfir10r3_candidates ("
            "seq INTEGER PRIMARY KEY AUTOINCREMENT, repository_numeric_id TEXT NOT NULL, "
            "path TEXT NOT NULL, blob_sha TEXT NOT NULL, "
            "UNIQUE(repository_numeric_id,path,blob_sha))"
        )
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS sfir10r3_root_snapshot ("
            "singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
            "repository_numeric_id TEXT NOT NULL, canonical_address TEXT NOT NULL, "
            "default_branch TEXT NOT NULL, root_commit_sha TEXT NOT NULL, "
            "root_tree_sha TEXT NOT NULL)"
        )
        self.db.commit()

    def close(self) -> None:
        self.db.commit()
        self.db.close()
        self.frontier.close()

    def __enter__(self) -> RootStore:
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False

    def add_candidate(self, repository_numeric_id: str, path: str, blob_sha: str) -> None:
        self.db.execute(
            "INSERT OR IGNORE INTO sfir10r3_candidates"
            "(repository_numeric_id,path,blob_sha) VALUES (?,?,?)",
            (repository_numeric_id, path, blob_sha),
        )
        self.db.commit()

    def candidates(self) -> list[tuple[str, str, str]]:
        return [
            (str(row[0]), str(row[1]), str(row[2]))
            for row in self.db.execute(
                "SELECT repository_numeric_id,path,blob_sha FROM sfir10r3_candidates ORDER BY seq"
            )
        ]

    def candidate_digest(self) -> str:
        return _digest([list(row) for row in self.candidates()])

    def snapshot(self) -> dict[str, str] | None:
        row = self.db.execute(
            "SELECT repository_numeric_id,canonical_address,default_branch,"
            "root_commit_sha,root_tree_sha FROM sfir10r3_root_snapshot WHERE singleton=1"
        ).fetchone()
        if row is None:
            return None
        return {
            "repository_numeric_id": str(row[0]),
            "canonical_address_at_seed": str(row[1]),
            "default_branch_at_seed": str(row[2]),
            "root_commit_sha": str(row[3]),
            "root_tree_sha": str(row[4]),
        }

    def record_snapshot(
        self,
        *,
        repository_numeric_id: str,
        canonical_address: str,
        default_branch: str,
        root_commit_sha: str,
        root_tree_sha: str,
    ) -> None:
        existing = self.snapshot()
        proposed = {
            "repository_numeric_id": str(repository_numeric_id),
            "canonical_address_at_seed": canonical_address,
            "default_branch_at_seed": default_branch,
            "root_commit_sha": root_commit_sha,
            "root_tree_sha": root_tree_sha,
        }
        if existing is not None:
            if existing != proposed:
                raise RunnerRefused(
                    "root snapshot is immutable once seeded; attempted reseed would mix revisions"
                )
            return
        self.db.execute(
            "INSERT INTO sfir10r3_root_snapshot"
            "(singleton,repository_numeric_id,canonical_address,default_branch,"
            "root_commit_sha,root_tree_sha) VALUES (1,?,?,?,?,?)",
            (
                str(repository_numeric_id),
                canonical_address,
                default_branch,
                root_commit_sha,
                root_tree_sha,
            ),
        )
        self.db.commit()


def _terminal_state(state: dict[str, Any]) -> bool:
    return all(value in TERMINAL for value in state["root_states"].values())


def _mark_remaining_stopped(state: dict[str, Any]) -> None:
    for key, value in list(state["root_states"].items()):
        if value not in TERMINAL:
            state["root_states"][key] = STOPPED


def _seed_or_attest(
    *,
    store: RootStore,
    client: transport_module.Transport,
    root: dict[str, Any],
) -> tuple[str, str]:
    existing = store.snapshot()
    try:
        resolution = client.resolve_canonical_address(root["catalogue_address"], root["host_uuid"])
    except transport_module.IdentityRefused as exc:
        if existing is not None:
            raise ResumeIdentityStopped(
                "a previously seeded root can no longer be re-attested; its prior "
                "candidates remain a lower bound and the root is STOPPED"
            ) from exc
        raise
    canonical = resolution["canonical_address"]
    repository_id = resolution["observed_repository_id"]
    if existing is not None:
        if existing["repository_numeric_id"] != repository_id:
            raise ResumeIdentityStopped(
                "the re-attested numeric id differs from the immutable seeded snapshot"
            )
        return canonical, repository_id
    branch = resolution.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise transport_module.TransportStop("verified repository metadata has no default branch")
    encoded = urllib.parse.quote(branch, safe="")
    response = client.get(f"https://api.github.com/repos/{canonical}/commits/{encoded}")
    commit_sha = response.body.get("sha")
    tree_sha = ((response.body.get("commit") or {}).get("tree") or {}).get("sha")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise transport_module.TransportStop("default-branch head has no usable commit sha")
    if not isinstance(tree_sha, str) or not tree_sha:
        raise transport_module.TransportStop("default-branch head has no usable tree sha")
    store.record_snapshot(
        repository_numeric_id=repository_id,
        canonical_address=canonical,
        default_branch=branch,
        root_commit_sha=commit_sha,
        root_tree_sha=tree_sha,
    )
    store.frontier.enqueue(
        root_id=str(root["host_uuid"]), path="", tree_sha=tree_sha, depth=0, parent_path=None
    )
    return canonical, repository_id


def _run_root(
    *,
    store: RootStore,
    client: transport_module.Transport,
    root: dict[str, Any],
) -> str:
    canonical, repository_id = _seed_or_attest(store=store, client=client, root=root)
    while True:
        entry = store.frontier.dequeue()
        if entry is None:
            return EXHAUSTED
        try:
            response = client.get(
                f"https://api.github.com/repos/{canonical}/git/trees/{entry.tree_sha}"
            )
        except (transport_module.SegmentClose, transport_module.MeasurementUnproven):
            store.frontier.release(entry)
            raise
        except transport_module.TransportStop:
            store.frontier.release(entry)
            return STOPPED

        tree = response.body.get("tree")
        if not isinstance(tree, list):
            store.frontier.release(entry)
            return STOPPED
        try:
            for item in tree:
                if not isinstance(item, dict):
                    raise transport_module.TransportStop("tree entry is not an object")
                name, kind, sha = item.get("path"), item.get("type"), item.get("sha")
                if not isinstance(name, str) or not isinstance(sha, str):
                    raise transport_module.TransportStop("tree entry lacks path/sha")
                path = f"{entry.path}/{name}" if entry.path else name
                if kind == "tree":
                    store.frontier.enqueue(
                        root_id=str(root["host_uuid"]),
                        path=path,
                        tree_sha=sha,
                        depth=entry.depth + 1,
                        parent_path=entry.path or None,
                    )
                elif kind == "blob" and path.lower().endswith(
                    tuple(x.lower() for x in protocol.CANDIDATE_EXTENSIONS)
                ):
                    store.add_candidate(repository_id, path, sha.lower())
        except frontier_module.WorkingStorageExhausted:
            store.frontier.release(entry)
            return STOPPED
        except transport_module.TransportStop:
            store.frontier.release(entry)
            return STOPPED
        store.frontier.complete(entry)


def _write_segment_receipt(
    *,
    state: dict[str, Any],
    window: transport_module.RateWindow,
    client: transport_module.Transport,
    reconciliation: dict[str, Any],
    segment_index: int,
    stop_reason: str,
    preflight: transport_module.AccountingSanityPreflight,
) -> str:
    body = {
        "schema": "tavonel.sfir10r3.segment.v1",
        "study_id": protocol.PROTOCOL_ID,
        "segment_index": segment_index,
        "protocol_digest": state["protocol_digest"],
        "freeze_digest": state["freeze_digest"],
        "roster_seal": state["roster_seal"],
        "previous_segment_digest": state["segment_chain_head"],
        "stop_reason": stop_reason,
        "accounting_sanity_preflight": preflight.as_dict(),
        "window": window.as_dict(),
        "transport": client.receipt(),
        "provider_reconciliation": reconciliation,
        "operational_state": {
            "windows_used": state["windows_used"],
            "current_ordinal": state["current_ordinal"],
            "root_states": state["root_states"],
            "root_provider_charges": state["root_provider_charges"],
        },
        "scientific_counts_disclosed": False,
    }
    digest = _digest(body)
    _write_once(
        SEGMENTS_DIR / f"segment-{segment_index:02d}.json", {**body, "segment_digest": digest}
    )
    return digest


def _terminal_unproven(reason: str, state: dict[str, Any]) -> dict[str, Any]:
    state["measurement_unproven"] = True
    _save_state(state)
    body = {
        "schema": "tavonel.sfir10r3.terminal_unproven.v1",
        "study_id": protocol.PROTOCOL_ID,
        "reason": reason,
        "protocol_digest": state["protocol_digest"],
        "freeze_digest": state["freeze_digest"],
        "roster_seal": state["roster_seal"],
        "windows_used": state["windows_used"],
        "what_this_means": "no PASS or FAIL may be sealed from this cohort",
    }
    report = {**body, "terminal_digest": _digest(body)}
    if not TERMINAL_UNPROVEN.exists():
        _write_once(TERMINAL_UNPROVEN, report)
    return report


def run_segment() -> dict[str, Any]:
    if CENSUS_RECEIPT.exists() or SCORE_RECEIPT.exists() or ACCEPTANCE_RECEIPT.exists():
        raise RunnerRefused("SFIR10 census already reached a terminal sealed result")
    if TERMINAL_UNPROVEN.exists():
        raise RunnerRefused("SFIR10 already terminated MEASUREMENT_UNPROVEN")
    freeze = verify_freeze()
    roster = verify_roster()
    state = _load_state(roster, freeze)

    recovery = _recover_closed_active_segment(state)
    if recovery is not None:
        if TERMINAL_UNPROVEN.exists():
            return recovery
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    if _terminal_state(state):
        return finalize(roster=roster, state=state)
    if state["windows_used"] >= protocol.PERMITTED_RATE_WINDOWS:
        _mark_remaining_stopped(state)
        _save_state(state)
        return finalize(roster=roster, state=state)

    preflight = transport_module.accounting_sanity_preflight()
    window = preflight.after
    segment_index = state["windows_used"] + 1
    _write_active_segment(state=state, segment_index=segment_index, preflight=preflight)
    client = transport_module.Transport(window=window)
    stop_reason = "ROSTER_TERMINAL"

    try:
        entries = roster["entries"]
        while state["current_ordinal"] <= len(entries):
            ordinal = int(state["current_ordinal"])
            key = str(ordinal)
            if state["root_states"][key] in TERMINAL:
                state["current_ordinal"] += 1
                continue
            root = entries[ordinal - 1]
            state["root_states"][key] = ACTIVE
            client.begin_root(root["host_uuid"], state["root_provider_charges"][key])
            try:
                with RootStore(_root_db(ordinal)) as store:
                    result = _run_root(store=store, client=client, root=root)
            except ResumeIdentityStopped:
                result = STOPPED
            except transport_module.IdentityRefused:
                result = REFUSED
            except (transport_module.TransportStop, frontier_module.WorkingStorageExhausted):
                result = STOPPED
            state["root_provider_charges"][key] = client.root_charged
            state["root_states"][key] = result
            state["current_ordinal"] += 1
            _save_state(state)
        stop_reason = "ROSTER_TERMINAL"
    except transport_module.SegmentClose as exc:
        ordinal = min(int(state["current_ordinal"]), len(roster["entries"]))
        if ordinal >= 1:
            state["root_provider_charges"][str(ordinal)] = client.root_charged
        stop_reason = f"SEGMENT_COMPLETE_RATE_WINDOW: {exc}"
    except transport_module.MeasurementUnproven as exc:
        return _terminal_unproven(str(exc), state)

    try:
        after = transport_module.read_rate_window()
        reconciliation = client.reconcile(after)
    except transport_module.MeasurementUnproven as exc:
        return _terminal_unproven(str(exc), state)

    state["windows_used"] = segment_index
    segment_digest = _write_segment_receipt(
        state=state,
        window=window,
        client=client,
        reconciliation=reconciliation,
        segment_index=segment_index,
        stop_reason=stop_reason,
        preflight=preflight,
    )
    state["segment_chain_head"] = segment_digest
    _save_state(state)
    ACTIVE_SEGMENT_FILE.unlink()

    if _terminal_state(state):
        return finalize(roster=roster, state=state)
    if state["windows_used"] >= protocol.PERMITTED_RATE_WINDOWS:
        _mark_remaining_stopped(state)
        _save_state(state)
        return finalize(roster=roster, state=state)
    return {
        "status": "SEGMENT_SEALED_NEEDS_LATER_PROVIDER_WINDOW",
        "segment_index": segment_index,
        "windows_remaining": protocol.PERMITTED_RATE_WINDOWS - state["windows_used"],
        "scientific_counts_disclosed": False,
    }


def _root_candidates(ordinal: int) -> list[tuple[str, str, str]]:
    path = _root_db(ordinal)
    if not path.exists():
        return []
    with RootStore(path) as store:
        return store.candidates()


def _root_evidence(ordinal: int) -> tuple[list[tuple[str, str, str]], dict[str, str] | None]:
    path = _root_db(ordinal)
    if not path.exists():
        return [], None
    with RootStore(path) as store:
        return store.candidates(), store.snapshot()


def _validate_root_evidence(
    *, status: str, candidates: list[tuple[str, str, str]], snapshot: dict[str, str] | None
) -> None:
    if status == REFUSED and (candidates or snapshot is not None):
        raise RunnerRefused("identity-refused root carries post-attestation evidence")
    if status in {EXHAUSTED, STOPPED} and snapshot is None:
        raise RunnerRefused("counted root carries no immutable revision snapshot")


def _capacity_interpretation(
    *, lower_bound: int, exhausted: int, stopped: int, refused: int
) -> dict[str, Any]:
    counted = exhausted + stopped
    complete = stopped == 0 and counted > 0
    exact = lower_bound if complete else None
    quota = protocol.quota_for(lower_bound)
    criterion_met = protocol.meets_criterion(lower_bound)
    if criterion_met:
        verdict = "CAPACITY_CRITERION_MET"
        rationale = "the certain lower bound already meets the frozen criterion"
    elif complete:
        verdict = "CAPACITY_CRITERION_NOT_MET"
        rationale = (
            "at least one root was measured, every counted root exhausted, and the exact "
            "total is below the frozen criterion"
        )
    else:
        verdict = "MEASURED_NOT_SEALABLE"
        if stopped:
            rationale = (
                "the lower bound is below criterion while stopped roots leave the exact "
                "total unknown"
            )
        elif refused and counted == 0:
            rationale = (
                "every root was refused before measurement; no counted population exists, "
                "so zero is not an exact capacity measurement"
            )
        else:
            rationale = "the frozen completeness contract does not establish an exact total"
    return {
        "counted": counted,
        "complete": complete,
        "exact": exact,
        "quota": quota,
        "criterion_met": criterion_met,
        "verdict": verdict,
        "rationale": rationale,
    }


def _segment_evidence(state: dict[str, Any]) -> list[dict[str, Any]]:
    expected_count = int(state["windows_used"])
    records: list[dict[str, Any]] = []
    previous = "GENESIS"
    for index in range(1, expected_count + 1):
        path = SEGMENTS_DIR / f"segment-{index:02d}.json"
        if not path.is_file():
            raise RunnerRefused(f"sealed segment {index} is absent")
        raw = path.read_bytes()
        row = json.loads(raw.decode("utf-8"))
        body = {key: value for key, value in row.items() if key != "segment_digest"}
        if _digest(body) != row.get("segment_digest"):
            raise RunnerRefused(f"segment {index} digest does not recompute")
        if row.get("segment_index") != index:
            raise RunnerRefused(f"segment {index} records a different ordinal")
        if row.get("previous_segment_digest") != previous:
            raise RunnerRefused(f"segment {index} does not extend the sealed predecessor")
        if row.get("roster_seal") != state["roster_seal"]:
            raise RunnerRefused(f"segment {index} belongs to a different roster")
        reconciliation = row.get("provider_reconciliation", {})
        if reconciliation.get("accounting_is_conservative") is not True:
            raise RunnerRefused(f"segment {index} provider accounting is not conservative")
        if reconciliation.get("capacity_evidence_publishable") is not True:
            raise RunnerRefused(f"segment {index} cannot support capacity evidence")
        records.append(
            {
                "relative_path": path.relative_to(NS).as_posix(),
                "file_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "segment_digest": row["segment_digest"],
                "total_unattributed_extra": int(reconciliation.get("total_unattributed_extra", 0)),
                "provider_cost_claim_publishable": bool(
                    reconciliation.get("provider_cost_claim_publishable", False)
                ),
                "capacity_evidence_publishable": True,
            }
        )
        previous = row["segment_digest"]
    if expected_count == 0 and state["segment_chain_head"] != "GENESIS":
        raise RunnerRefused("zero-window census carries a non-genesis segment-chain head")
    if expected_count and previous != state["segment_chain_head"]:
        raise RunnerRefused("runtime segment-chain head differs from the sealed segment chain")
    extras = sorted(SEGMENTS_DIR.glob("segment-*.json"))
    if len(extras) != expected_count:
        raise RunnerRefused(
            f"segment directory contains {len(extras)} receipts, expected {expected_count}"
        )
    return records


def finalize(*, roster: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if state.get("measurement_unproven"):
        raise RunnerRefused("measurement is unproven and cannot be scored")
    if not _terminal_state(state):
        raise RunnerRefused("cannot seal a census while a root is non-terminal")
    if CENSUS_RECEIPT.exists() or SCORE_RECEIPT.exists() or ACCEPTANCE_RECEIPT.exists():
        raise RunnerRefused("terminal receipts already exist; no rescore/reseal")

    pool: set[tuple[str, str, str]] = set()
    per_root = []
    for root in roster["entries"]:
        ordinal = int(root["selection_ordinal"])
        status = state["root_states"][str(ordinal)]
        candidates, snapshot = _root_evidence(ordinal)
        _validate_root_evidence(status=status, candidates=candidates, snapshot=snapshot)
        pool.update(candidates)
        per_root.append(
            {
                "selection_ordinal": ordinal,
                "host_uuid": str(root["host_uuid"]),
                "disposition": status,
                "candidate_count": len(candidates),
                "candidate_digest": _digest([list(row) for row in candidates]),
                "minimum_attributable_charges": state["root_provider_charges"][str(ordinal)],
                "revision_snapshot": snapshot,
            }
        )

    lower_bound = len(pool)
    stopped = sum(row["disposition"] == STOPPED for row in per_root)
    refused = sum(row["disposition"] == REFUSED for row in per_root)
    exhausted = sum(row["disposition"] == EXHAUSTED for row in per_root)
    interpretation = _capacity_interpretation(
        lower_bound=lower_bound,
        exhausted=exhausted,
        stopped=stopped,
        refused=refused,
    )
    complete = interpretation["complete"]
    exact = interpretation["exact"]
    segment_evidence = _segment_evidence(state)

    census_body = {
        "schema": "tavonel.sfir10r3.capacity_census.v1",
        "study_id": protocol.PROTOCOL_ID,
        "protocol_digest": state["protocol_digest"],
        "freeze_digest": state["freeze_digest"],
        "roster_seal": roster["roster_seal"],
        "windows_used": state["windows_used"],
        "segment_chain_head": state["segment_chain_head"],
        "segments": segment_evidence,
        "roots": per_root,
        "candidate_pool": [list(row) for row in sorted(pool)],
        "pool_digest": _digest(sorted([list(row) for row in pool])),
        "capacity_lower_bound": lower_bound,
        "capacity_exact": exact,
        "census_complete": complete,
        "roots_exhausted": exhausted,
        "roots_stopped": stopped,
        "roots_refused": refused,
    }
    census = {**census_body, "census_seal": _digest(census_body)}
    _write_once(CENSUS_RECEIPT, census)

    quota = interpretation["quota"]
    verdict = interpretation["verdict"]
    rationale = interpretation["rationale"]
    score_body = {
        "schema": "tavonel.sfir10r3.capacity_score.v1",
        "study_id": protocol.PROTOCOL_ID,
        "protocol_digest": state["protocol_digest"],
        "roster_seal": roster["roster_seal"],
        "census_seal": census["census_seal"],
        "capacity": {
            "certain_lower_bound": lower_bound,
            "exact_count": exact,
            "quota_from_lower_bound": quota,
        },
        "completeness": {
            "roster_size": len(roster["entries"]),
            "counted": interpretation["counted"],
            "exhausted": exhausted,
            "stopped": stopped,
            "refused": refused,
            "census_complete": complete,
        },
        "verdict": verdict,
        "why": rationale,
    }
    score = {**score_body, "score_digest": _digest(score_body)}
    _write_once(SCORE_RECEIPT, score)

    accounting_conservative = len(segment_evidence) == state["windows_used"]
    provider_cost_claim_publishable = all(
        row["provider_cost_claim_publishable"] for row in segment_evidence
    )
    total_unattributed_extra = sum(row["total_unattributed_extra"] for row in segment_evidence)
    root_charge_clean = all(
        row["minimum_attributable_charges"] <= protocol.PER_ROOT_CHARGE_ALLOWANCE
        for row in per_root
    )
    acceptance_body = {
        "schema": "tavonel.sfir10r3.capacity_acceptance.v1",
        "study_id": protocol.PROTOCOL_ID,
        "protocol_digest": state["protocol_digest"],
        "freeze_digest": state["freeze_digest"],
        "roster_seal": roster["roster_seal"],
        "census_seal": census["census_seal"],
        "score_digest": score["score_digest"],
        "criteria": {
            "all_roots_terminal": True,
            "provider_accounting_conservative": accounting_conservative,
            "root_charge_envelope_respected": root_charge_clean,
            "window_count_within_envelope": state["windows_used"]
            <= protocol.PERMITTED_RATE_WINDOWS,
            "sealed_segment_count_matches_windows_used": len(segment_evidence)
            == state["windows_used"],
            "no_measurement_unproven": True,
            "score_is_sealable": verdict != "MEASURED_NOT_SEALABLE",
        },
        "claim_scope": {
            "capacity_result_publishable_if_accepted": True,
            "provider_cost_claim_publishable": provider_cost_claim_publishable,
            "total_unattributed_provider_extra": total_unattributed_extra,
            "exact_provider_cost_not_required_for_capacity": True,
        },
    }
    accepted = all(acceptance_body["criteria"].values())
    acceptance = {
        **acceptance_body,
        "accepted": accepted,
        "result_publishable": accepted,
        "provider_cost_result_publishable": accepted and provider_cost_claim_publishable,
        "acceptance_digest": _digest(acceptance_body),
    }
    _write_once(ACCEPTANCE_RECEIPT, acceptance)
    return {
        "status": "TERMINAL",
        "verdict": verdict,
        "accepted": accepted,
        "capacity_lower_bound": lower_bound,
        "capacity_exact": exact,
        "quota": quota,
        "census_seal": census["census_seal"],
        "acceptance_digest": acceptance["acceptance_digest"],
    }


def status() -> dict[str, Any]:
    result: dict[str, Any] = {
        "freeze": FREEZE_RECEIPT.exists(),
        "input_binding": INPUT_RECEIPT.exists(),
        "roster": ROSTER_RECEIPT.exists(),
        "runtime_state": STATE_FILE.exists(),
        "terminal_unproven": TERMINAL_UNPROVEN.exists(),
        "census": CENSUS_RECEIPT.exists(),
        "score": SCORE_RECEIPT.exists(),
        "acceptance": ACCEPTANCE_RECEIPT.exists(),
    }
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        result["windows_used"] = state["windows_used"]
        result["current_ordinal"] = state["current_ordinal"]
    result["scientific_counts_disclosed"] = False
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SFIR10 prospective runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("generate-roster")
    sub.add_parser("run-segment")
    sub.add_parser("status")
    args = parser.parse_args(argv)
    try:
        if args.command == "generate-roster":
            report = generate_roster()
            print(
                json.dumps(
                    {
                        "status": report["state"],
                        "entry_count": report["entry_count"],
                        "roster_seal": report["roster_seal"],
                        "scientific_counts_disclosed": False,
                    },
                    sort_keys=True,
                )
            )
        elif args.command == "run-segment":
            print(json.dumps(run_segment(), sort_keys=True))
        else:
            print(json.dumps(status(), sort_keys=True))
        return 0
    except transport_module.SegmentNotReady as exc:
        print(
            json.dumps(
                {
                    "status": "SEGMENT_NOT_STARTED",
                    "reason": str(exc),
                    "scientific_counts_disclosed": False,
                },
                sort_keys=True,
            )
        )
        return 2
    except RunnerRefused as exc:
        print(f"REFUSED {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
