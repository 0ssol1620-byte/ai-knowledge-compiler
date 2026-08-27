#!/usr/bin/env python3
"""The four-rung freeze ladder for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2.

    freeze_migration_closure_v2.py protocol      # rung 1: the contract
    freeze_migration_closure_v2.py universe      # rung 2: the candidate universe
    freeze_migration_closure_v2.py scorer        # rung 3: scorer + acceptance
    freeze_migration_closure_v2.py exclusions    # rung 4: the exclusion policy
    freeze_migration_closure_v2.py gate          # what the runner must pass

V1 froze two things and the discipline was observed firing (INC-V2-042 is why it
existed at all). Two later problems were out of reach of those two freezes:

* **INC-V2-046** — the exclusion behaviour that decided which pairs left the
  universe was settled inside the freeze code while the freeze was running. The
  decision it reached was right. That it was reached while looking at the data is
  the part rung 4 fixes: an exclusion rule settled after seeing the data is,
  from the outside, indistinguishable from one settled because of the data.
* **INC-V2-048** — a condition read the more comfortable of two available
  measurements, and nothing had pinned which measurement the acceptance semantics
  were entitled to read. Rung 3 pins the scorer modules and the acceptance block
  by digest, so a drift between the declaration and the code that implements it
  is a refusal rather than a green report.

**Ordering is a chain of references, not a comparison of timestamps.** Each rung
records the RUN ID of the rung before it, and `require_execution_preconditions`
re-verifies every link against the receipts currently on disk, recomputes every
pinned digest, and re-derives the collision groups. A reader is never asked to
compare two wall-clock stamps and believe the answer.

This tool reads V1's protocol (to compare invariant bodies) and V1's frozen
universe receipt (for lineage ids, to subtract them). It reads **no V1 verdict,
count or violated case**, and it opens **no V1 file for writing**. It runs no
change predicate and opens no canonical document. The one production symbol it
may touch is `akc_cir.semantic_diff.ChangeKind`'s name table, and only to refuse
a quarantine record kind that production does not actually emit.

**No SFI3 artifact is opened, listed or fetched.**
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, ROOT, canonical_json, canonical_sha, git_head, now, sha_file
from evidence import SCHEMA as RECEIPT_ENVELOPE_SCHEMA

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1.yaml"
V1_PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"

#: V1's universe receipt stem. Read for its lineage ids and for nothing else.
V1_UNIVERSE_STEM = "identity-change-migration-closure-universe"

#: The sentinel a draft carries where the repair has not yet declared something.
#: The protocol freeze refuses while any remains, so the hole cannot be sealed.
SENTINEL = "PENDING_REPAIR_DECLARATION"

NONE_DECLARED = "NONE_DECLARED_BY_PRODUCTION"

#: The rung order lives in the protocol's `freeze.order` and in the chain of
#: `require_*` preconditions below, and in no third place. A restated order here
#: would be a second home for the decision and would drift from the first.


class FreezeRefused(RuntimeError):
    """A rung's precondition is not met. Never worked around here."""


# --------------------------------------------------------------------------
# workspace
#
# Every path the ladder reads is a field, so the whole ladder can be exercised
# against a temporary tree. A gate that can only be run against the one real
# receipts directory cannot be shown to come back red without writing evidence,
# and evidence written to prove a test is not evidence.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Workspace:
    root: Path = ROOT
    protocol: Path = PROTOCOL
    v1_protocol: Path = V1_PROTOCOL
    #: where V2's own receipts are written and read
    receipts: Path = NS / "receipts"
    #: where the receipts of earlier work are read from (V1's universe, SFI2)
    prior_receipts: Path = NS / "receipts"
    #: the two acquisition artifacts whose `admitted` rows are the 538
    retrospective_cohorts: tuple[Path, ...] = (
        NS / "artifacts" / "development" / "sfi1" / "sfi1_acquisition.json",
        NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json",
    )
    #: None means "read the declared path out of the protocol"
    manifest: Path | None = None


def _rel(path: Path, root: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(root)).replace("\\", "/")
    except ValueError:
        return Path(path).resolve().as_posix()


# --------------------------------------------------------------------------
# receipts
#
# Same envelope as `evidence.write_immutable`: run-specific path, refuses to
# overwrite, self-hashed, carrying the tool and protocol digests. The one
# difference is that the directory is a parameter.
# --------------------------------------------------------------------------


def _new_run_id(tool: Path, protocol: Path, stem: str, body: dict[str, Any]) -> str:
    """A run id that is unique per RUNG, not merely per second.

    `evidence.new_run_id` seeds on the tool digest, the protocol digest, the
    wall clock to the second, and the pid. Four rungs frozen from one process
    inside one second therefore share an id -- which was fine while a stem had
    one receipt, and is not fine here, because rungs 2, 3 and 4 each record the
    run id of the rung before them and the gate verifies those links. Two rungs
    with the same id would let a stale receipt satisfy a link it does not
    belong to. The stem and the receipt body go into the seed so that they
    cannot collide.
    """
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    seed = "|".join(
        [
            sha_file(tool),
            sha_file(protocol) if protocol.is_file() else "no-protocol",
            stamp,
            str(os.getpid()),
            stem,
            canonical_sha(body),
        ]
    )
    return stamp + "-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]


def runs_of(stem: str, receipts: Path) -> list[Path]:
    return sorted(receipts.glob(f"{stem}--*.json"))


def latest_receipt(stem: str, receipts: Path) -> dict[str, Any] | None:
    runs = runs_of(stem, receipts)
    if not runs:
        return None
    body: dict[str, Any] = json.loads(runs[-1].read_text(encoding="utf-8"))
    body["_receipt_path"] = runs[-1].as_posix()
    return body


def write_receipt(
    stem: str, body: dict[str, Any], ws: Workspace, run_id: str | None = None
) -> dict[str, str]:
    """Write one immutable receipt into `ws.receipts` and say where it went."""
    tool = Path(__file__).resolve()
    if run_id is None:
        run_id = _new_run_id(tool, ws.protocol, stem, body)
    target = ws.receipts / f"{stem}--{run_id}.json"
    if target.exists():  # pragma: no cover -- run ids carry the pid and the clock
        raise FreezeRefused(f"{target.name} already exists; receipts are never overwritten")

    envelope = dict(body)
    envelope["provenance"] = {
        "schema": RECEIPT_ENVELOPE_SCHEMA,
        "run_id": run_id,
        "generated_at": now(),
        "tool": _rel(tool, ws.root),
        "tool_sha256": sha_file(tool),
        "protocol": _rel(ws.protocol, ws.root),
        "protocol_sha256": sha_file(ws.protocol),
        "receipt_stem": stem,
        "immutable": True,
    }
    bare = {key: value for key, value in envelope.items() if key != "receipt_sha256"}
    envelope["receipt_sha256"] = canonical_sha(bare)

    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False))
        handle.write("\n")
    return {
        "run_id": run_id,
        "receipt": _rel(target, ws.root),
        "receipt_sha256": envelope["receipt_sha256"],
    }


# --------------------------------------------------------------------------
# the protocol
# --------------------------------------------------------------------------


def load_protocol(path: Path = PROTOCOL) -> dict[str, Any]:
    import yaml

    body: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return body


def stem_for(protocol: dict[str, Any], rung: str) -> str:
    stems = protocol["freeze"]["stems"]
    if rung not in stems:
        raise FreezeRefused(f"the protocol declares no freeze stem for rung {rung!r}")
    return str(stems[rung])


#: The blocks that together are the ACCEPTANCE SEMANTICS. Rung 3 pins their
#: canonical digest so that a change to the grading rule is reported as a change
#: to the grading rule rather than as "the protocol moved".
ACCEPTANCE_BLOCKS: tuple[str, ...] = (
    "invariants",
    "pass_rule",
    "vacuity_rule",
    "facet_channels",
    "unresolved_fail_closed",
    "predeclared_ignored_facets",
)


def acceptance_digest(protocol: dict[str, Any]) -> str:
    missing = [block for block in ACCEPTANCE_BLOCKS if block not in protocol]
    if missing:
        raise FreezeRefused(f"the protocol declares no {missing} block; acceptance is not pinnable")
    return canonical_sha({block: protocol[block] for block in ACCEPTANCE_BLOCKS})


def exclusion_policy_digest(protocol: dict[str, Any]) -> str:
    if "exclusion_policy" not in protocol:
        raise FreezeRefused(
            "the protocol declares no exclusion_policy. An exclusion rule that is "
            "not declared before the universe freeze is INC-V2-046 again."
        )
    return canonical_sha(protocol["exclusion_policy"])


# --------------------------------------------------------------------------
# rung 1 checks
# --------------------------------------------------------------------------


def unresolved_sentinels(path: Path) -> list[str]:
    """Every line of the protocol still carrying the draft sentinel."""
    return [
        f"line {number}: {line.strip()}"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if SENTINEL in line and not line.lstrip().startswith("#")
    ]


def invariant_delta(protocol: dict[str, Any], v1: dict[str, Any]) -> dict[str, Any]:
    """Compare V2's invariant bodies against V1's, canonically.

    The founder's ruling is that V2 reuses the same substantive eight invariants
    unless a change is genuinely required by the repair's semantics, and that any
    change is recorded as an explicit protocol delta written before execution.
    This is that check, and it is a comparison rather than a promise: a body that
    differs and is not declared refuses, and a body declared as changed that is
    in fact identical also refuses -- a delta entry that describes no change is a
    pre-authorisation for an edit nobody has made yet.
    """
    ours = protocol.get("invariants") or {}
    theirs = v1.get("invariants") or {}
    delta = protocol.get("protocol_delta") or {}
    declared = delta.get("changed_invariants") or {}

    added = sorted(set(ours) - set(theirs))
    removed = sorted(set(theirs) - set(ours))
    differing = sorted(
        name
        for name in set(ours) & set(theirs)
        if canonical_json(ours[name]) != canonical_json(theirs[name])
    )

    problems: list[str] = []
    for name in added:
        problems.append(f"INVARIANT ADDED and not declared in protocol_delta: {name}")
    for name in removed:
        problems.append(
            f"INVARIANT REMOVED: {name}. V2 reuses the V1 eight; removing one narrows "
            "the closure and no repair semantics can justify that here."
        )
    for name in differing:
        entry = declared.get(name)
        if not isinstance(entry, dict):
            problems.append(f"INVARIANT CHANGED and not declared in protocol_delta: {name}")
            continue
        for key in ("change", "repair_semantics_reason"):
            if not str(entry.get(key) or "").strip():
                problems.append(f"protocol_delta[{name}] carries no {key}")
    for name in sorted(set(declared) - set(differing)):
        problems.append(
            f"protocol_delta declares {name} as changed, but its body is identical to "
            "V1's. A delta that describes no change pre-authorises an edit nobody "
            "has made."
        )
    return {
        "v1_protocol_sha256": None,  # filled by the caller, which knows the path
        "added": added,
        "removed": removed,
        "changed": differing,
        "unchanged": sorted((set(ours) & set(theirs)) - set(differing)),
        "problems": problems,
    }


def _observe_production_unresolved_record() -> set[str]:
    """RUN production and return the record kinds it actually emits for an
    unsettled identity.

    A table lookup proves a name exists in an enum. It does not prove production
    ever emits it, and an enum member nothing emits would make INVARIANT_6(e)
    look for nothing, find nothing, and report clean -- which is exactly the
    vacuity this study has paid for twice (INC-V2-036, INC-V2-044). So this
    executes the repaired path on a fixture built to force an AMBIGUOUS decision
    and reports what came back.
    """
    sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
    sys.path.insert(0, str(NS))
    sys.path.insert(0, str(NS / "compiler"))
    try:
        import compiler.channel_cases as cc
        import selective_build as engine
        from akc_cir.semantic_diff import ChangeKind, DiffLevel, diff_documents
    except Exception as error:  # pragma: no cover -- hard dependencies
        raise FreezeRefused(f"cannot exercise the production diff path: {error}") from error

    #: A restructure that forces the resolver into its review band, which is the
    #: shape INC-V2-047 is about. Built from production canonicalisation, not
    #: from a hand-written record.
    before = cc.document(
        cc.markdown(cc.BODY_ALPHA, cc.BODY_BETA), "v1", source_id="freeze:quarantine-probe"
    )
    after = cc.document(cc.markdown(cc.BODY_BETA), "v2", source_id="freeze:quarantine-probe")
    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)
    diff = diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=tuple(before_units),
        after_units=tuple(after_units),
        source=after["source_id"],
    )
    del ChangeKind
    #: `diff.unresolved` -- NOT `diff.changes`. Asking whether the declared kind
    #: appears anywhere in the change list is the wrong question and it passed a
    #: value that must never pass: `unit_removed` IS emitted on this probe, so an
    #: "is it among the emitted kinds" test accepted it. Declaring a definite
    #: outcome as the quarantine channel would let INVARIANT_6(e) be satisfied by
    #: the very statement the repair exists to suppress -- a unit reported removed
    #: would count as evidence that its unresolved identity was made visible.
    #: Production's own UNRESOLVED channel mapping is the authority on which kinds
    #: speak for an unsettled identity, so that is what is read.
    return {change.kind.value for change in diff.unresolved}


def check_quarantine_channel(protocol: dict[str, Any]) -> dict[str, Any]:
    """Refuse any quarantine record kind production does not ACTUALLY emit.

    V2R1 strengthens the abandoned V2 draft's version in two ways, both required
    by founder ruling.

    First, NONE_DECLARED_BY_PRODUCTION is no longer an acceptable answer. It was
    a real answer while the repair was still landing and production genuinely had
    no typed quarantine record. Production now emits one, so declaring otherwise
    would hand INVARIANT_6(e) a weaker obligation than the system can bear.

    Second, the check is an EXECUTION rather than a table lookup. The V2 version
    verified the declared name was a member of `ChangeKind`, which proves the
    name exists and nothing else. A member nothing emits would still make (e)
    vacuous. So production is run and the emitted kinds observed.
    """
    declared = (protocol.get("quarantine_channel") or {}).get("production_record")

    if declared == NONE_DECLARED:
        raise FreezeRefused(
            f"quarantine_channel.production_record={NONE_DECLARED!r} is refused by "
            "V2R1. Production DOES emit a typed, visible unresolved record, and "
            "declaring otherwise would give INVARIANT_6(e) a weaker obligation than "
            "the system can actually bear."
        )
    if not isinstance(declared, str) or not declared:
        raise FreezeRefused(
            "quarantine_channel.production_record is not declared. It must be the "
            "exact record kind the repaired diff emits for an unsettled identity."
        )

    sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))
    try:
        from akc_cir.semantic_diff import ChangeKind
    except Exception as error:  # pragma: no cover -- akc_cir is a hard dependency
        raise FreezeRefused(f"cannot read production's ChangeKind table: {error}") from error

    known = {member.value for member in ChangeKind}
    if declared not in known:
        raise FreezeRefused(
            f"quarantine_channel.production_record={declared!r} is not a ChangeKind "
            "value. Naming a record kind that does not exist would make "
            "INVARIANT_6(e) look for nothing and report clean."
        )

    emitted = _observe_production_unresolved_record()
    if declared not in emitted:
        raise FreezeRefused(
            f"quarantine_channel.production_record={declared!r} is a real ChangeKind "
            "but the repaired production path did not emit it ON THE UNRESOLVED "
            "CHANNEL for a probe built to force an unsettled identity. Observed "
            f"unresolved kinds: {sorted(emitted)}. A declared record production "
            "never emits for an unsettled identity makes INVARIANT_6(e) vacuous, "
            "and a DEFINITE outcome declared here would let (e) be satisfied by the "
            "very statement the repair exists to suppress."
        )

    return {
        "production_record": declared,
        "verified_against_production": True,
        "verification": (
            "executed the repaired diff path and observed the kinds emitted on "
            "production's UNRESOLVED channel"
        ),
        "observed_unresolved_kinds": sorted(emitted),
    }


# --------------------------------------------------------------------------
# rung 0 -- the acquisition frame
#
# NEW IN V2R1, and not a renumbering of anything V2 had. V1 and the abandoned V2
# both drew from a cache that already existed on disk, so the earliest thing
# either could pin was the protocol. V2R1 ACQUIRES its material, which means the
# rules deciding WHAT to acquire have to be sealed before any content exists --
# otherwise selection could be steered, consciously or not, by what the sources
# started returning. Rung 0 is the obligation that fresh acquisition creates.
# --------------------------------------------------------------------------

FRAME_MODULE = NS / "acquisition" / "sources_v2r1.py"


def _load_frame() -> Any:
    sys.path.insert(0, str(NS / "acquisition"))
    try:
        import sources_v2r1
    except Exception as error:  # pragma: no cover -- the frame is a hard dependency
        raise FreezeRefused(f"cannot load the acquisition frame: {error}") from error
    return sources_v2r1


def freeze_acquisition_frame(ws: Workspace | None = None) -> dict[str, Any]:
    """Seal the frame BEFORE any V2R1 fetch happens."""
    ws = ws or Workspace()
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "acquisition_frame")

    frame = _load_frame()
    module_digest = sha_file(FRAME_MODULE)
    declaration = frame.frame_declaration()
    declaration_digest = frame.frame_digest()

    existing = latest_receipt(stem, ws.receipts)
    if existing is not None:
        if existing.get("frame_module_sha256") == module_digest:
            return {
                "state": "ALREADY_FROZEN",
                "receipt": existing["_receipt_path"],
                "frame_module_sha256": module_digest,
            }
        raise FreezeRefused(
            "the acquisition frame is already frozen at a different digest. A "
            "frozen frame is not amended in place -- amending it after acquisition "
            "begins is exactly the steering this rung exists to prevent.\n"
            f"  frozen:  {existing.get('frame_module_sha256')}\n"
            f"  current: {module_digest}"
        )

    #: The frame must not have been used yet. A frame sealed after the fetches it
    #: authorises is a record of what was done, not a constraint on what may be.
    already_acquired = ws.root / "artifacts" / "development" / "v2r1_corpus"
    if already_acquired.exists() and any(already_acquired.iterdir()):
        raise FreezeRefused(
            f"{_rel(already_acquired, ws.root)} already holds acquired material. The "
            "frame is sealed BEFORE acquisition; sealing it afterwards would record "
            "what was done rather than constrain what may be done."
        )

    #: Sufficiency lives in the protocol AND in the frame. They must agree, or
    #: one of them is decorative.
    sufficiency = protocol.get("cohort_sufficiency") or {}
    if sufficiency.get("minimum_admitted_pairs") != frame.FLOOR:
        raise FreezeRefused(
            "the protocol's minimum_admitted_pairs and the frame's FLOOR disagree "
            f"({sufficiency.get('minimum_admitted_pairs')} vs {frame.FLOOR}). Two "
            "declarations of the same gate that differ means one of them is not the "
            "gate."
        )
    if sufficiency.get("minimum_families") != frame.FAMILIES_REQUIRED:
        raise FreezeRefused(
            "the protocol's minimum_families and the frame's FAMILIES_REQUIRED "
            f"disagree ({sufficiency.get('minimum_families')} vs "
            f"{frame.FAMILIES_REQUIRED})."
        )
    if list(sufficiency.get("target_families") or ()) != list(frame.FAMILIES):
        raise FreezeRefused(
            "the protocol's target_families and the frame's FAMILIES disagree "
            f"({sufficiency.get('target_families')} vs {list(frame.FAMILIES)})."
        )

    #: Over-selection must actually over-select. A PRIMARY_TARGET at or below the
    #: FLOOR leaves no room for attrition, which would force a choice between
    #: padding after measurement and an INSUFFICIENT_COHORT stop the frame made
    #: inevitable rather than honest.
    if frame.PRIMARY_TARGET <= frame.FLOOR:
        raise FreezeRefused(
            f"PRIMARY_TARGET={frame.PRIMARY_TARGET} does not over-select against "
            f"FLOOR={frame.FLOOR}. Over-selection happens before any outcome exists; "
            "without it, attrition can only be answered by padding afterwards."
        )
    if sum(frame.FAMILY_QUOTA.values()) != frame.PRIMARY_TARGET:
        raise FreezeRefused(
            "the family quotas do not sum to PRIMARY_TARGET "
            f"({sum(frame.FAMILY_QUOTA.values())} vs {frame.PRIMARY_TARGET})."
        )

    body = {
        "rung": 0,
        "protocol_id": protocol["protocol_id"],
        "frame_module": _rel(FRAME_MODULE, ws.root),
        "frame_module_sha256": module_digest,
        "frame_declaration_digest": declaration_digest,
        "frame_declaration": declaration,
        "sealed_before_acquisition": True,
        "why_rung_0_exists": (
            "V2R1 acquires its own material, so the rules deciding what to acquire "
            "are sealed before any content exists. V1 and the abandoned V2 drew from "
            "an existing cache and had no equivalent obligation."
        ),
    }
    return {"state": "FROZEN", "rung": 0, **write_receipt(stem, body, ws)}


def _nothing_has_been_measured(ws: Workspace) -> tuple[bool, list[str]]:
    """Is the study still entirely upstream of any outcome-bearing data?

    Two conditions, BOTH machine-checkable, neither a judgement:

      * no V2R1 acquisition artifact exists, so no revision content has been
        fetched, parsed, diffed or scored;
      * no rung after the protocol has frozen, so nothing downstream has taken a
        dependency on the current frame.

    This exists to answer one narrow question honestly. The rule against
    amending a frozen rung is there to stop a frame being reshaped by what the
    data turned out to look like. When there IS no data, that specific harm is
    not merely unlikely, it is impossible -- and the check says so by testing
    the world rather than by trusting a claim about intent.

    It is deliberately NOT a general amend path. It cannot be reached once a
    single pair has been acquired, and it names every receipt it supersedes.
    """
    blocking: list[str] = []

    corpus = ws.root / "research" / "tavonel_eval_v2" / "artifacts" / "development" / "v2r1_corpus"
    if corpus.exists() and any(corpus.iterdir()):
        blocking.append(f"acquired material exists at {_rel(corpus, ws.root)}")

    protocol = load_protocol(ws.protocol)
    for rung in ("universe", "scorer_acceptance", "exclusions", "measurement"):
        #: No silent skip. A rung whose stem cannot be read is a rung this guard
        #: cannot see, and a guard that cannot see a rung must not report the
        #: study clean -- that would weaken the check in exactly the direction
        #: that makes superseding easier.
        try:
            stem = stem_for(protocol, rung)
        except Exception as error:
            blocking.append(f"cannot read the stem for rung {rung!r}: {error}")
            continue
        if latest_receipt(stem, ws.receipts) is not None:
            blocking.append(f"rung {rung!r} has already frozen")

    return (not blocking), blocking


def supersede_frame(ws: Workspace | None = None) -> dict[str, Any]:
    """Replace an incomplete frame BEFORE any acquisition, naming what it voids.

    WHY THIS EXISTS, recorded rather than smoothed over. The first V2R1 frame was
    frozen without declaring its source repositories, CFR parts or issuer sets.
    Founder ruling section 7 requires those predeclared, and without them the
    traversal is underdetermined: the rules said HOW to walk the sources but not
    WHICH sources, so acquisition could still have reached for convenient
    material. That was an error, and it was caught before a single fetch.

    The superseded receipt is never deleted or rewritten. It is named here, and
    the new receipt records that it supersedes it and why.
    """
    ws = ws or Workspace()
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "acquisition_frame")

    clean, blocking = _nothing_has_been_measured(ws)
    if not clean:
        raise FreezeRefused(
            "the frame may not be superseded: this study is no longer upstream of "
            "outcome-bearing data, so replacing the frame now could reshape "
            "selection around what the data turned out to look like.\n  " + "\n  ".join(blocking)
        )

    prior = latest_receipt(stem, ws.receipts)
    if prior is None:
        raise FreezeRefused("there is no frozen frame to supersede. Use the `frame` rung instead.")

    frame = _load_frame()
    module_digest = sha_file(FRAME_MODULE)
    if prior.get("frame_module_sha256") == module_digest:
        raise FreezeRefused(
            "the frame on disk is identical to the frozen one. There is nothing to "
            "supersede, and writing a second receipt for the same content would "
            "make the chain longer without making it truer."
        )

    declaration = frame.frame_declaration()
    required_roots = ("source_roots",)
    missing = [key for key in required_roots if key not in declaration]
    if missing:
        raise FreezeRefused(
            "the replacement frame still does not declare "
            f"{', '.join(missing)}. Superseding an incomplete frame with another "
            "incomplete frame is not a correction."
        )

    body = {
        "rung": 0,
        "rung_name": "acquisition_frame",
        "protocol_id": protocol["protocol_id"],
        "frame_module": _rel(FRAME_MODULE, ws.root),
        "frame_module_sha256": module_digest,
        "frame_declaration_digest": frame.frame_digest(),
        "frame_declaration": declaration,
        "sealed_before_acquisition": True,
        "supersedes": {
            "receipt": prior.get("_receipt_path"),
            "run_id": prior.get("run_id"),
            "frame_module_sha256": prior.get("frame_module_sha256"),
            "why": (
                "the superseded frame declared families, quotas and traversal rules "
                "but no source repositories, CFR parts or issuer sets. Founder ruling "
                "section 7 requires those predeclared; without them the traversal was "
                "underdetermined and acquisition could still have reached for "
                "convenient material."
            ),
            "preserved": True,
            "voided_before_any_acquisition": True,
        },
        "permitted_because": (
            "no V2R1 acquisition artifact existed and no rung after the protocol had "
            "frozen, both checked mechanically rather than asserted"
        ),
    }
    return {"state": "FROZEN_SUPERSEDING", "rung": 0, **write_receipt(stem, body, ws)}


def require_frozen_frame(ws: Workspace) -> dict[str, Any]:
    """Rung 1 refuses unless rung 0 landed and still matches disk."""
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "acquisition_frame")
    receipt = latest_receipt(stem, ws.receipts)
    if receipt is None:
        raise FreezeRefused(
            "the acquisition frame is not frozen. Rung 0 comes first: V2R1 acquires "
            "its material, so the frame that decides what to acquire is pinned "
            "before anything is fetched."
        )
    current = sha_file(FRAME_MODULE)
    if receipt.get("frame_module_sha256") != current:
        raise FreezeRefused(
            "the acquisition frame changed after it was frozen.\n"
            f"  frozen:  {receipt.get('frame_module_sha256')}\n  current: {current}"
        )
    return receipt


# --------------------------------------------------------------------------
# rung 1
# --------------------------------------------------------------------------


def freeze_protocol(ws: Workspace | None = None) -> dict[str, Any]:
    ws = ws or Workspace()
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "protocol")
    digest = sha_file(ws.protocol)

    #: The chain is a chain of REFERENCES, not a comparison of two wall-clock
    #: stamps a reader is trusted to check. A timestamp proves what a receipt
    #: claims about itself; a refusal proves what the next step was able to do.
    frame_receipt = require_frozen_frame(ws)

    existing = latest_receipt(stem, ws.receipts)
    if existing is not None:
        if existing.get("protocol_sha256") == digest:
            return {
                "state": "ALREADY_FROZEN",
                "receipt": existing["_receipt_path"],
                "protocol_sha256": digest,
            }
        raise FreezeRefused(
            "this protocol is already frozen at a different digest. A frozen "
            "protocol is not amended in place; a genuinely necessary change is a "
            "new protocol id with its own freeze chain.\n"
            f"  frozen:  {existing.get('protocol_sha256')}\n  current: {digest}"
        )

    sentinels = unresolved_sentinels(ws.protocol)
    if sentinels:
        raise FreezeRefused(
            "the protocol still carries draft sentinels and cannot be sealed. Each "
            "one is a declaration the repair has not made yet, and sealing over it "
            "would freeze a hole:\n  " + "\n  ".join(sentinels)
        )

    v1 = load_protocol(ws.v1_protocol)
    delta = invariant_delta(protocol, v1)
    delta["v1_protocol_sha256"] = sha_file(ws.v1_protocol)
    if delta["problems"]:
        raise FreezeRefused(
            "the invariant set does not match V1's eight with a recorded delta:\n  "
            + "\n  ".join(delta["problems"])
        )

    quarantine = check_quarantine_channel(protocol)

    body = {
        "schema": "tavonel.v2.protocol_freeze.v3",
        "rung": 1,
        "rung_name": "protocol",
        "protocol_path": _rel(ws.protocol, ws.root),
        "protocol_sha256": digest,
        "protocol_id": protocol["protocol_id"],
        "git_head": git_head(),
        "frozen_before_any_result": True,
        "frozen_before_any_candidate_pair_was_read": True,
        "invariant_delta_against_v1": delta,
        "prior_rung": {
            "rung": 0,
            "rung_name": "acquisition_frame",
            "run_id": _run_id_of(frame_receipt),
            "receipt": frame_receipt.get("_receipt_path"),
            "frame_module_sha256": frame_receipt.get("frame_module_sha256"),
        },
        "quarantine_channel": quarantine,
        "acceptance_semantics_sha256": acceptance_digest(protocol),
        "exclusion_policy_sha256": exclusion_policy_digest(protocol),
        "what_this_seals": (
            "the same eight structural acceptance criteria as V1, with two declared "
            "strengthenings; the facet channel declaration; the empty "
            "predeclared-ignore declaration; the exclusion policy; the manifest "
            "contract; and the fixture battery -- all before the universe is frozen "
            "and before any candidate pair is read"
        ),
        "v1_is_not_touched": {
            "v1_protocol_sha256": delta["v1_protocol_sha256"],
            "read_for": "invariant body comparison only",
            "opened_for_writing": False,
            "v1_verdict_read": False,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    return {"state": "FROZEN", "protocol_sha256": digest, **write_receipt(stem, body, ws)}


def _run_id_of(receipt: dict[str, Any] | None) -> str | None:
    """A receipt's run id, which lives under `provenance`, not at the top level.

    INC-V2-057: the first version of the chain-link check read
    `receipt.get("run_id")`, which is absent from every stored body. Both sides
    of the comparison were therefore None, None == None held, and a broken chain
    reported clean. A guard comparing two absences is a check that can only
    return one answer -- INC-V2-044's shape, written by the same hand that had
    just audited for it. Callers must treat a None here as UNKNOWN and refuse,
    never as "matches".
    """
    if receipt is None:
        return None
    return (receipt.get("provenance") or {}).get("run_id") or receipt.get("run_id")


def supersede_protocol(ws: Workspace | None = None) -> dict[str, Any]:
    """Re-seal rung 1 against the frame currently in force.

    Needed only because rung 0 was superseded. The protocol FILE is unchanged --
    what changed is the frame it points at -- so this is not an amendment of
    frozen semantics; it is repairing a reference that a supersession below it
    invalidated. Guarded exactly as `supersede_frame` is: reachable only while no
    acquisition artifact exists and no rung after the protocol has frozen.
    """
    ws = ws or Workspace()
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "protocol")

    clean, blocking = _nothing_has_been_measured(ws)
    if not clean:
        raise FreezeRefused(
            "the protocol may not be re-sealed: this study is no longer upstream "
            "of outcome-bearing data.\n  " + "\n  ".join(blocking)
        )

    prior = latest_receipt(stem, ws.receipts)
    if prior is None:
        raise FreezeRefused("there is no frozen protocol to supersede.")

    frame_receipt = require_frozen_frame(ws)
    recorded = (prior.get("prior_rung") or {}).get("run_id")
    in_force = _run_id_of(frame_receipt)
    same_link = recorded is not None and in_force is not None and recorded == in_force
    if same_link and prior.get("protocol_sha256") == sha_file(ws.protocol):
        raise FreezeRefused(
            "the protocol already references the frame in force and its file is "
            "unchanged. There is nothing to repair, and a second receipt would "
            "lengthen the chain without making it truer."
        )

    digest = sha_file(ws.protocol)
    file_changed = prior.get("protocol_sha256") != digest
    #: A protocol FILE change is permitted here, and ONLY here, and ONLY while
    #: `_nothing_has_been_measured` holds. That is not a softening of the
    #: no-amendment rule; it is the rule's actual boundary made explicit.
    #:
    #: The rule exists to stop a protocol being reshaped by what the data turned
    #: out to look like. Before any acquisition there IS no data, so that harm is
    #: impossible rather than unlikely -- and the guard proves it by testing the
    #: world, not by trusting a claim about intent. The moment one pair lands,
    #: this path is unreachable and a genuinely necessary change becomes what the
    #: protocol says it becomes: a new protocol id with its own chain.
    #:
    #: Both digests are recorded either way, so a reader can see exactly what
    #: moved rather than take "unchanged" on trust.

    body = {
        "schema": "tavonel.v2.protocol_freeze.v3",
        "rung": 1,
        "rung_name": "protocol",
        "protocol_path": _rel(ws.protocol, ws.root),
        "protocol_sha256": digest,
        "protocol_id": protocol["protocol_id"],
        "git_head": git_head(),
        "frozen_before_any_result": True,
        "frozen_before_any_candidate_pair_was_read": True,
        "quarantine_channel": check_quarantine_channel(protocol),
        "acceptance_semantics_sha256": acceptance_digest(protocol),
        "exclusion_policy_sha256": exclusion_policy_digest(protocol),
        "prior_rung": {
            "rung": 0,
            "rung_name": "acquisition_frame",
            "run_id": in_force,
            "receipt": frame_receipt.get("_receipt_path"),
            "frame_module_sha256": frame_receipt.get("frame_module_sha256"),
        },
        "supersedes": {
            "receipt": prior.get("_receipt_path"),
            "run_id": _run_id_of(prior),
            "superseded_protocol_sha256": prior.get("protocol_sha256"),
            "protocol_file_changed": file_changed,
            "why": (
                "rung 0 was superseded to add the source roots the first frame "
                "omitted, and the derived draft additionally pointed its "
                "manifest_contract at the ABANDONED V2 enumeration -- which would "
                "have had this study read another study's manifest or write into "
                "preserved evidence. Both corrections were made before any "
                "acquisition existed."
            ),
            "permitted_because": (
                "no V2R1 acquisition artifact existed and no rung after the protocol "
                "had frozen, both checked mechanically. This path is unreachable "
                "once a single pair has landed."
            ),
            "preserved": True,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    return {"state": "FROZEN_SUPERSEDING", "rung": 1, **write_receipt(stem, body, ws)}


def require_frozen_protocol(ws: Workspace) -> dict[str, Any]:
    protocol = load_protocol(ws.protocol)
    receipt = latest_receipt(stem_for(protocol, "protocol"), ws.receipts)
    if receipt is not None:
        #: The LINK, not just this rung's own digest. Rung 1 records the run id
        #: of the frame it was sealed against; if the frame has since been
        #: superseded, that reference points at a document no longer in force and
        #: the chain is broken even though every individual receipt is intact.
        #: Checking only each rung's own digest would miss it entirely -- which is
        #: the difference between a chain of references and a pile of receipts.
        frame_stem = stem_for(protocol, "acquisition_frame")
        current_frame = latest_receipt(frame_stem, ws.receipts)
        recorded = (receipt.get("prior_rung") or {}).get("run_id")
        in_force = _run_id_of(current_frame)
        if current_frame is not None and (recorded is None or in_force is None):
            raise FreezeRefused(
                "the frame link cannot be verified: one side has no run id, and two "
                "absences must never be read as a match. Re-seal rung 1 against the "
                f"frame in force.\n  protocol recorded: {recorded}\n"
                f"  frame in force:    {in_force}"
            )
        if current_frame is not None and recorded != in_force:
            raise FreezeRefused(
                "the protocol was frozen against a frame that is no longer in "
                "force. Rung 1 must be sealed again against the current frame "
                "before anything downstream may proceed.\n"
                f"  protocol was sealed against frame run {recorded}\n"
                f"  frame in force is             {in_force}"
            )
    if receipt is None:
        raise FreezeRefused(
            "rung 1 is missing: the V2 protocol has not been frozen. Run "
            "`freeze_migration_closure_v2.py protocol` first -- freezing after "
            "measuring is INC-V2-042."
        )
    current = sha_file(ws.protocol)
    if receipt.get("protocol_sha256") != current:
        raise FreezeRefused(
            "the V2 protocol has changed since it was frozen.\n"
            f"  frozen:  {receipt.get('protocol_sha256')}\n"
            f"  current: {current}\n"
            "A frozen protocol is never re-sealed in place."
        )
    return receipt


# --------------------------------------------------------------------------
# rung 2 — the candidate universe
# --------------------------------------------------------------------------


def _manifest_path(ws: Workspace, protocol: dict[str, Any]) -> Path:
    if ws.manifest is not None:
        return ws.manifest
    declared = str(protocol["manifest_contract"]["path"])
    return ws.root / declared


def _rows_from_manifest(body: Any, contract: dict[str, Any], where: Path) -> list[dict[str, Any]]:
    aliases = list(contract["accepted_row_key_aliases"])
    primary = str(contract["rows_key"])
    if not isinstance(body, dict):
        raise FreezeRefused(
            f"{where.name} is not a JSON object. Expected an object carrying one of "
            f"{aliases} as a list of candidate rows."
        )
    present = [key for key in aliases if key in body]
    if len(present) > 1 and primary not in present:
        raise FreezeRefused(
            f"{where.name} carries more than one accepted row key {present} and none of "
            f"them is the declared primary {primary!r}. Which list is the candidate "
            "universe would be a guess, and this tool never guesses a key."
        )
    for key in [primary, *aliases] if primary in body else aliases:
        if key in body:
            rows = body[key]
            if not isinstance(rows, list):
                raise FreezeRefused(f"{where.name}[{key!r}] is not a list")
            return rows
    raise FreezeRefused(
        f"{where.name} carries none of the accepted row keys {aliases}.\n"
        f"  found top-level keys: {sorted(body)}\n"
        "  expected row fields: " + ", ".join(contract["required_row_fields"]) + "\n"
        "  expected side fields: " + ", ".join(contract["required_side_fields"]) + "\n"
        "The manifest is written by the enumerating lane; this tool never guesses a "
        "key and never enumerates a universe of its own."
    )


def _lineage_id(row: Any, contract: dict[str, Any]) -> str:
    if not isinstance(row, dict):
        raise FreezeRefused(f"a candidate row is not an object: {row!r}")
    for key in contract["accepted_lineage_id_aliases"]:
        value = row.get(key)
        if value:
            return str(value)
    raise FreezeRefused(
        f"a candidate row carries no lineage identity under any of "
        f"{list(contract['accepted_lineage_id_aliases'])}: keys={sorted(row)}. A row "
        "that cannot be named cannot be excluded by name, so the freeze refuses "
        "rather than dropping it."
    )


def _collision_key_values(row: dict[str, Any], keys: list[str]) -> list[tuple[str, str]]:
    """The (key, value) pairs this row claims. Missing values claim nothing."""
    found: list[tuple[str, str]] = []
    for key in keys:
        if "." in key:
            side, leaf = key.split(".", 1)
            container = row.get(side)
            value = container.get(leaf) if isinstance(container, dict) else None
        else:
            value = row.get(key)
        if isinstance(value, str) and value:
            found.append((key, value))
    return found


def collision_groups(
    rows: list[dict[str, Any]], contract: dict[str, Any], keys: list[str]
) -> list[dict[str, Any]]:
    """Every group of rows that share a cache key while carrying different lineages.

    STRUCTURAL, not symptomatic. A collision whose members happen to verify is
    still ambiguous provenance: the manifest records one document's digest beside
    a cache slot two documents wrote to, and nothing on disk says which write
    survived. Detecting only via a failing digest would silently admit exactly
    the collisions that overwrote a payload with byte-identical content.

    Groups that overlap through a shared row are MERGED, so a row cannot be
    excluded under one key and kept under another.
    """
    parent: dict[str, str] = {}

    def find(item: str) -> str:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    claims: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        lineage = _lineage_id(row, contract)
        parent.setdefault(lineage, lineage)
        for claim in _collision_key_values(row, keys):
            claims.setdefault(claim, []).append(lineage)

    colliding: dict[tuple[str, str], list[str]] = {}
    for claim, lineages in claims.items():
        distinct = sorted(set(lineages))
        if len(distinct) > 1:
            colliding[claim] = distinct
            for other in distinct[1:]:
                union(distinct[0], other)

    grouped: dict[str, dict[str, Any]] = {}
    for (key, value), lineages in sorted(colliding.items()):
        root = find(lineages[0])
        entry = grouped.setdefault(root, {"group_id": root, "keys": [], "members": set()})
        entry["keys"].append({"key": key, "value": value, "lineages": lineages})
        entry["members"].update(lineages)

    return [
        {
            "group_id": f"collision:{entry['group_id']}",
            "keys": entry["keys"],
            "members": sorted(entry["members"]),
        }
        for entry in sorted(grouped.values(), key=lambda item: item["group_id"])
    ]


def verify_collision_groups_whole(universe: dict[str, Any]) -> list[str]:
    """Every member of every collision group must have left the universe.

    Checked three times -- when the universe is built, when rung 4 pins it, and
    at the execution gate -- so a hand-edited receipt is caught before a
    measurement reads it. Returns the problems; empty means whole.
    """
    kept = {row["lineage_id"] for row in universe.get("pairs", ())}
    excluded = {row["lineage_id"]: row for row in universe.get("exclusions", {}).get("rows", ())}
    problems: list[str] = []
    for group in universe.get("collision_groups", ()):
        survivors = sorted(member for member in group["members"] if member in kept)
        unnamed = sorted(member for member in group["members"] if member not in excluded)
        if survivors:
            problems.append(
                f"{group['group_id']} is partially excluded: {survivors} survived. When a "
                "collision makes provenance ambiguous the ENTIRE group leaves -- keeping "
                "the member that still verifies is choosing the convenient reading of an "
                "ambiguity."
            )
        if unnamed:
            problems.append(
                f"{group['group_id']} has members excluded without being named: {unnamed}"
            )
    return problems


def _prior_lineage_ids(ws: Workspace) -> dict[str, Any]:
    """The three lineage id sets V2's universe must be disjoint from."""
    retrospective: set[str] = set()
    sources: list[dict[str, Any]] = []
    for path in ws.retrospective_cohorts:
        if not path.is_file():
            raise FreezeRefused(
                f"retrospective cohort artifact absent: {_rel(path, ws.root)}. "
                "Disjointness cannot be proven against a cohort that is not on disk, "
                "and an unprovable disjointness is not an assumed one."
            )
        admitted = json.loads(path.read_text(encoding="utf-8"))["admitted"]
        here = {str(row["lineage_id"]) for row in admitted}
        retrospective |= here
        sources.append(
            {
                "artifact": _rel(path, ws.root),
                "artifact_sha256": sha_file(path),
                "admitted_pairs": len(admitted),
                "distinct_lineages": len(here),
            }
        )

    candidates = sorted(ws.prior_receipts.glob("sfi2-native-provenance--*.json"))
    if not candidates:
        raise FreezeRefused(
            "no sfi2-native-provenance receipt present; the 14 confirmed lineages "
            "cannot be excluded by name."
        )
    confirmed_source = candidates[-1]
    confirmed_body = json.loads(confirmed_source.read_text(encoding="utf-8"))
    confirmed_rows = confirmed_body["rebuild"]["E5_confirmed_selective_stale_escape"]["confirmed"]
    confirmed = {str(row["lineage_id"]) for row in confirmed_rows}

    v1_runs = sorted(ws.prior_receipts.glob(f"{V1_UNIVERSE_STEM}--*.json"))
    if not v1_runs:
        raise FreezeRefused(
            "V1's frozen universe receipt is not on disk, so V2 cannot prove its "
            "universe is NEW. The ruling requires a new universe; an unprovable "
            "novelty is not an assumed one."
        )
    v1_source = v1_runs[-1]
    v1_body = json.loads(v1_source.read_text(encoding="utf-8"))
    v1_ids = {str(row["lineage_id"]) for row in v1_body.get("pairs", ())}

    return {
        "retrospective_538": frozenset(retrospective),
        "confirmed_14": frozenset(confirmed),
        "v1_universe": frozenset(v1_ids),
        "meta": {
            "retrospective_538": {"sources": sources, "distinct_lineages": len(retrospective)},
            "confirmed_14": {
                "source_receipt": _rel(confirmed_source, ws.root),
                "source_receipt_sha256": sha_file(confirmed_source),
                "distinct_lineages": len(confirmed),
                "read_for": "disjointness proof only; never a numerator or a denominator",
            },
            "v1_universe": {
                "source_receipt": _rel(v1_source, ws.root),
                "source_receipt_sha256": sha_file(v1_source),
                "distinct_lineages": len(v1_ids),
                "read_for": (
                    "lineage ids only. No V1 verdict, count or violated case is read, "
                    "and V1's FAIL is neither re-opened nor re-interpreted."
                ),
            },
        },
    }


def _verify_side(
    row: dict[str, Any], side: str, ws: Workspace, contract: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Recompute BOTH digests for one side. Returns (entry, reason, detail).

    The RAW digest is compared against what acquisition recorded, read only from
    `raw_sha256_recorded`. It is deliberately not aliased to `raw_sha256`: that
    key means "what acquisition wrote down" in the historical cohort manifests
    and "what the enumerator just recomputed" in the V2 enumeration, and
    comparing a recomputation against itself would report every side verified.

    The CANONICAL digest is recomputed for every side and pinned. Where
    acquisition recorded one it must reconcile; where acquisition recorded none
    -- which is the common case, because the historical manifests never did --
    the side is pinned but NOT called verified, and the counts are reported
    separately. See the protocol's `canonical_digest_availability`, declared
    before this freeze rather than discovered during it.
    """
    entry = row.get(side)
    if not isinstance(entry, dict):
        return None, "MANIFEST_ROW_MALFORMED", f"{side} side is not an object"

    missing = [key for key in contract["required_side_fields"] if not entry.get(key)]
    if missing:
        return None, "MANIFEST_ROW_MALFORMED", f"{side} side is missing {missing}"

    raw = ws.root / entry["raw_path"]
    canonical = ws.root / entry["canonical_path"]
    if not raw.is_file():
        return None, "PAYLOAD_MISSING", f"cached payload missing: {entry['raw_path']}"
    if not canonical.is_file():
        return None, "PAYLOAD_MISSING", f"canonical document missing: {entry['canonical_path']}"

    # The one enforcement site for the recorded-digest rule. It is deliberately
    # NOT also listed in `required_side_fields`: a guard that only ever fires
    # because an earlier guard fires first cannot be shown to work, which is
    # INC-V2-036 wearing a different hat.
    raw_key = str(contract["recorded_raw_digest_key"])
    recorded_raw = entry.get(raw_key)
    if not recorded_raw:
        return (
            None,
            "RECORDED_DIGEST_ABSENT",
            f"{side} side carries no `{raw_key}`. The recorded digest is never "
            "aliased to `raw_sha256`, which means the recomputed value in one "
            "producer and the recorded value in another; comparing a recomputation "
            "against itself would report every side verified.",
        )
    raw_digest = "sha256:" + hashlib.sha256(raw.read_bytes()).hexdigest()
    if raw_digest != recorded_raw:
        return (
            None,
            "PAYLOAD_DIGEST_MISMATCH",
            f"{side} raw payload changed since acquisition: {entry['raw_path']} "
            f"(recorded {recorded_raw}, on disk {raw_digest})",
        )

    canonical_digest = sha_file(canonical)
    recorded_canonical = entry.get(str(contract["recorded_canonical_digest_key"]))
    convention = entry.get(str(contract["canonical_digest_convention_key"]))
    if recorded_canonical:
        if not convention and recorded_canonical != canonical_digest:
            return (
                None,
                "PAYLOAD_DIGEST_MISMATCH",
                f"{side} canonical document carries a recorded digest that reconciles "
                f"with no convention: {entry['canonical_path']} (recorded "
                f"{recorded_canonical}, file digest {canonical_digest})",
            )
        verified = True
    else:
        verified = False

    return (
        {
            "raw_path": entry["raw_path"],
            "raw_sha256": raw_digest,
            "raw_verified_against_acquisition": True,
            "canonical_path": entry["canonical_path"],
            "canonical_sha256": canonical_digest,
            "canonical_sha256_recorded": recorded_canonical,
            "canonical_digest_convention": convention,
            "canonical_verified_against_acquisition": verified,
        },
        None,
        None,
    )


def build_universe(ws: Workspace, protocol: dict[str, Any]) -> dict[str, Any]:
    """Select, prove disjoint, verify, and name every exclusion.

    No closure measurement happens here, nothing imports a change predicate, and
    no canonical document is parsed -- it is hashed, not read.
    """
    contract = protocol["manifest_contract"]
    policy = protocol["exclusion_policy"]
    named = policy["every_exclusion_is_named_and_counted"]
    allowed_reasons = set(named["reasons_are_a_closed_set"])
    keys = list(policy["collision_detection"]["collision_keys"])

    manifest = _manifest_path(ws, protocol)
    if not manifest.is_file():
        raise FreezeRefused(
            f"the candidate universe manifest is absent: {_rel(manifest, ws.root)}. It is "
            "written by the enumerating lane; this tool refuses rather than enumerating "
            "a second universe of its own."
        )
    body = json.loads(manifest.read_text(encoding="utf-8"))
    rows = _rows_from_manifest(body, contract, manifest)
    if not rows:
        raise FreezeRefused(f"{manifest.name} declares no candidate rows")

    prior = _prior_lineage_ids(ws)
    groups = collision_groups(rows, contract, keys)
    in_a_group = {member: group["group_id"] for group in groups for member in group["members"]}

    pairs: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def drop(lineage: str, reason: str, detail: str) -> None:
        if reason not in allowed_reasons:  # pragma: no cover -- reasons are literals here
            raise FreezeRefused(
                f"exclusion reason {reason!r} is not in the frozen closed set. A label "
                "invented while a freeze runs is the thing the predeclaration prevents."
            )
        exclusions.append(
            {
                "lineage_id": lineage,
                "reason": reason,
                "detail": detail,
                "collision_group": in_a_group.get(lineage),
            }
        )

    for row in rows:
        lineage = _lineage_id(row, contract)

        if lineage in seen:
            drop(
                lineage,
                "DUPLICATE_LINEAGE_ALREADY_TAKEN_FROM_AN_EARLIER_MANIFEST",
                "this lineage was already taken from an earlier row",
            )
            continue
        seen.add(lineage)

        if lineage in in_a_group:
            drop(
                lineage,
                "CACHE_KEY_COLLISION_GROUP",
                f"member of {in_a_group[lineage]}; the entire group leaves because one "
                "member holds the wrong bytes and nothing on disk says which",
            )
            continue

        if lineage in prior["retrospective_538"]:
            drop(
                lineage,
                "NOT_DISJOINT_FROM_THE_538_PAIR_RETROSPECTIVE_COHORT",
                "present in the 538-pair retrospective safety regression",
            )
            continue
        if lineage in prior["confirmed_14"]:
            drop(
                lineage,
                "NOT_DISJOINT_FROM_THE_14_CONFIRMED_SFI2_LINEAGES",
                "a confirmed SFI2 development fixture cannot certify its own repair",
            )
            continue
        if lineage in prior["v1_universe"]:
            drop(
                lineage,
                "NOT_DISJOINT_FROM_THE_V1_FROZEN_UNIVERSE",
                "V1 already measured this pair; V2 runs on a NEW universe",
            )
            continue

        malformed = [
            key
            for key in contract["required_row_fields"]
            if key not in ("lineage_id",) and row.get(key) in (None, "")
        ]
        if malformed:
            drop(lineage, "MANIFEST_ROW_MALFORMED", f"row is missing {malformed}")
            continue

        before, before_reason, before_detail = _verify_side(row, "before", ws, contract)
        after, after_reason, after_detail = _verify_side(row, "after", ws, contract)
        if before is None or after is None:
            drop(
                lineage,
                before_reason or after_reason or "MANIFEST_ROW_MALFORMED",
                before_detail or after_detail or "unverifiable",
            )
            continue

        pairs.append(
            {
                "lineage_id": lineage,
                "family": row["family"],
                "before_version": row["before_version"],
                "after_version": row["after_version"],
                "before": before,
                "after": after,
            }
        )

    pairs.sort(key=lambda item: (item["lineage_id"], item["before_version"], item["after_version"]))
    exclusions.sort(key=lambda item: (item["lineage_id"], item["reason"]))

    counts: dict[str, int] = {}
    for row in exclusions:
        counts[row["reason"]] = counts.get(row["reason"], 0) + 1

    kept = {row["lineage_id"] for row in pairs}
    for name, ids in (
        ("the 538-pair retrospective cohort", prior["retrospective_538"]),
        ("the 14 confirmed SFI2 lineages", prior["confirmed_14"]),
        ("V1's frozen universe", prior["v1_universe"]),
    ):
        overlap = sorted(kept & ids)
        if overlap:  # pragma: no cover -- the filter above removes them
            raise FreezeRefused(
                f"disjointness from {name} violated after filtering, which means the "
                f"filter and the proof disagree: {overlap}"
            )

    if not pairs:
        raise FreezeRefused(
            "the frozen universe would be empty. A closure over zero pairs is vacuous "
            "and this protocol fails it rather than passing it."
        )

    families: dict[str, int] = {}
    for row in pairs:
        families[row["family"]] = families.get(row["family"], 0) + 1

    universe = {
        "schema": "tavonel.v2.identity_change_migration_closure.universe.v2",
        "rung": 2,
        "rung_name": "universe",
        "protocol_id": protocol["protocol_id"],
        "selection_rule": protocol["cohort"]["selection_rule"],
        "path_taken": protocol["cohort"]["path_taken"],
        "manifest": {
            "path": _rel(manifest, ws.root),
            "sha256": sha_file(manifest),
            "rows": len(rows),
            "written_by": contract["owner_tool"],
            "not_written_by_this_lane": True,
        },
        "pair_count": len(pairs),
        "families": dict(sorted(families.items())),
        "canonical_verification": {
            "rule": (
                "every canonical document is re-hashed and the digest is pinned. A "
                "side whose acquisition never recorded a canonical digest is pinned "
                "but NOT verified against acquisition, and is counted here rather "
                "than reported as if it were verified."
            ),
            "sides_verified_against_acquisition": sum(
                int(row[side]["canonical_verified_against_acquisition"])
                for row in pairs
                for side in ("before", "after")
            ),
            "sides_pinned_only_because_acquisition_recorded_none": sum(
                int(not row[side]["canonical_verified_against_acquisition"])
                for row in pairs
                for side in ("before", "after")
            ),
        },
        "upstream_exclusions": {
            "decided_by": contract["owner_tool"],
            "not_re_decided_here": True,
            "re_derived_independently_by_this_rung": True,
            "manifest_sha256": sha_file(manifest),
            "rows_the_enumerator_dropped": len(body.get(contract["upstream_excluded_key"], ())),
            "enumerator_category_counts": body.get(contract["upstream_exclusion_summary_key"], []),
        },
        "collision_groups": groups,
        "collision_policy": {
            "detection": "structural, by cache key, before any digest is recomputed",
            "collision_keys": keys,
            "whole_group_leaves": True,
        },
        "exclusions": {
            "count": len(exclusions),
            "by_reason": dict(sorted(counts.items())),
            "closed_reason_set": sorted(allowed_reasons),
            "rows": exclusions,
        },
        "disjointness": {
            "from_the_538_pair_retrospective_cohort": {"holds": True, "overlap": []},
            "from_the_14_confirmed_sfi2_lineages": {"holds": True, "overlap": []},
            "from_the_v1_frozen_universe": {"holds": True, "overlap": []},
            "sources": prior["meta"],
        },
        "sfi3": {"opened": False, "listed": False, "fetched": False},
        "network": "none",
        "universe_sha256": universe_digest(pairs),
        "pairs": pairs,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }

    problems = verify_collision_groups_whole(universe)
    if problems:  # pragma: no cover -- the builder excludes whole groups
        raise FreezeRefused("collision groups are not wholly excluded:\n  " + "\n  ".join(problems))
    return universe


def universe_digest(pairs: list[dict[str, Any]]) -> str:
    return canonical_sha(
        [
            [
                row["lineage_id"],
                row["before"]["raw_sha256"],
                row["after"]["raw_sha256"],
                row["before"]["canonical_sha256"],
                row["after"]["canonical_sha256"],
            ]
            for row in pairs
        ]
    )


def freeze_universe(ws: Workspace | None = None) -> dict[str, Any]:
    ws = ws or Workspace()
    receipt = require_frozen_protocol(ws)
    protocol = load_protocol(ws.protocol)
    body = build_universe(ws, protocol)
    body["protocol_freeze_receipt"] = receipt["_receipt_path"]
    body["protocol_freeze_run_id"] = receipt["provenance"]["run_id"]
    body["protocol_sha256"] = receipt["protocol_sha256"]
    written = write_receipt(stem_for(protocol, "universe"), body, ws)
    return {
        "state": "FROZEN",
        "pair_count": body["pair_count"],
        "excluded": body["exclusions"]["by_reason"],
        "collision_groups": len(body["collision_groups"]),
        "universe_sha256": body["universe_sha256"],
        **written,
    }


MEASUREMENT_GLOB = "identity-change-migration-closure-v2r1--*.json"


def _nothing_has_been_scored(ws: Workspace) -> tuple[bool, list[str]]:
    """Has any V2R1 OUTCOME been read yet?

    A weaker condition than `_nothing_has_been_measured`, and deliberately so.
    That one asks whether any material has been acquired; this one asks whether
    any material has been SCORED. The distinction matters because the two guard
    different things.

    Rung 0 and rung 1 protect SELECTION, so they must shut as soon as data
    exists -- once you can see the corpus, you could choose around it. Rung 3
    pins the universe, and re-sealing it is only dangerous once an OUTCOME has
    been observed, because that is the first moment a change could be steered by
    a result. Before that, a universe that cannot be measured at all is simply
    broken, and refusing to fix it would not protect anything -- it would only
    guarantee the closure fails for a reason that has nothing to do with the
    question being asked.
    """
    blocking = [path.name for path in sorted((ws.receipts).glob(MEASUREMENT_GLOB))]
    return (not blocking), blocking


def supersede_universe(ws: Workspace | None = None) -> dict[str, Any]:
    """Re-seal rung 3 against a re-derived universe, before any outcome is read.

    WHY THIS WAS NEEDED, on the record rather than smoothed away. The first V2R1
    eCFR canonicalisation invented its own unit shape -- `heading_path`, no
    `heading`, no `text_sha256` -- which `selective_build.snapshots` cannot read.
    All 106 eCFR pairs in the first frozen universe were therefore unmeasurable
    and would have failed as a block for a reason unrelated to the migration:
    the same trap INC-V2-053 records against INVARIANT_6(d), arriving from a
    different direction.

    Repairing it required re-deriving canonical documents, which changes the
    per-side canonical digests and therefore the universe digest, so rung 3 has
    to be sealed again. This path exists so that happens ONCE, loudly, naming
    what it replaces -- rather than by quietly deleting a receipt.

    It refuses the moment a measurement receipt exists.

    The body is `build_universe`'s OWN output plus the link fields, exactly as
    `freeze_universe` assembles it. The first version of this function rebuilt
    the receipt by hand and produced one that looked complete, lacked the
    `exclusions` block a later rung reads, and failed only when that rung ran --
    a second implementation of the same structure, drifting, which is the defect
    this module keeps warning about.
    """
    ws = ws or Workspace()
    protocol = load_protocol(ws.protocol)
    stem = stem_for(protocol, "universe")

    clean, blocking = _nothing_has_been_scored(ws)
    if not clean:
        raise FreezeRefused(
            "the universe may not be re-sealed: V2R1 has already been SCORED, and "
            "from that moment a change to the universe could be steered by the "
            "result.\n  " + "\n  ".join(blocking)
        )

    prior = latest_receipt(stem, ws.receipts)
    if prior is None:
        raise FreezeRefused("there is no frozen universe to supersede; use `universe`.")

    receipt = require_frozen_protocol(ws)
    body = build_universe(ws, protocol)
    if not body.get("pairs"):
        raise FreezeRefused(
            "the replacement universe would be empty. A closure over zero pairs is "
            "vacuous and this protocol fails it rather than passing it."
        )

    body["protocol_freeze_receipt"] = receipt["_receipt_path"]
    body["protocol_freeze_run_id"] = receipt["provenance"]["run_id"]
    body["protocol_sha256"] = receipt["protocol_sha256"]

    #: A no-op is refused, but "no-op" means BOTH the content and the chain link
    #: are already right. Comparing the digest alone would refuse to repair a
    #: receipt whose payload was correct and whose link to rung 1 was written
    #: under the wrong key -- a refusal to fix a broken chain because the content
    #: had not moved.
    if (
        body["universe_sha256"] == prior.get("universe_sha256")
        and prior.get("protocol_freeze_run_id") == body["protocol_freeze_run_id"]
        and "exclusions" in prior
    ):
        raise FreezeRefused(
            "the re-derived universe is identical to the frozen one, already names "
            "the protocol freeze in force, and is structurally complete. There is "
            "nothing to supersede."
        )

    body["supersedes"] = {
        "receipt": prior.get("_receipt_path"),
        "run_id": _run_id_of(prior),
        "superseded_universe_sha256": prior.get("universe_sha256"),
        "superseded_pair_count": prior.get("pair_count"),
        "why": (
            "the first eCFR canonicalisation emitted a unit shape production's "
            "`selective_build.snapshots` cannot read, making 106 eCFR pairs "
            "unmeasurable. Canonical documents were re-derived from the sources and "
            "the universe digest moved with them."
        ),
        "permitted_because": (
            "no V2R1 measurement receipt existed, checked mechanically. This path "
            "shuts the moment an outcome has been read."
        ),
        "preserved": True,
    }

    written = write_receipt(stem, body, ws)
    return {
        "state": "FROZEN_SUPERSEDING",
        "rung": 3,
        "pair_count": body["pair_count"],
        "excluded": body["exclusions"]["by_reason"],
        "collision_groups": len(body["collision_groups"]),
        "universe_sha256": body["universe_sha256"],
        **written,
    }


def require_frozen_universe(ws: Workspace, protocol_receipt: dict[str, Any]) -> dict[str, Any]:
    protocol = load_protocol(ws.protocol)
    universe = latest_receipt(stem_for(protocol, "universe"), ws.receipts)
    if universe is None:
        raise FreezeRefused(
            "rung 2 is missing: the candidate universe has not been frozen. Measuring "
            "against an unfrozen universe is how a cohort gets chosen by its result."
        )
    if universe.get("protocol_sha256") != protocol_receipt["protocol_sha256"]:
        raise FreezeRefused("the frozen universe was built against a different protocol digest")
    if universe.get("protocol_freeze_run_id") != protocol_receipt["provenance"]["run_id"]:
        raise FreezeRefused(
            "the frozen universe does not name the current protocol freeze run. The "
            "ladder is a chain of references; a broken link is a refusal."
        )
    if universe.get("universe_sha256") != universe_digest(universe.get("pairs", [])):
        raise FreezeRefused(
            "the frozen universe's content digest does not match the pairs it carries"
        )
    problems = verify_collision_groups_whole(universe)
    if problems:
        raise FreezeRefused("collision groups are not wholly excluded:\n  " + "\n  ".join(problems))
    return universe


# --------------------------------------------------------------------------
# rung 3 — the scorer and the acceptance semantics
# --------------------------------------------------------------------------


def freeze_scorer(ws: Workspace | None = None, *, superseding: bool = False) -> dict[str, Any]:
    ws = ws or Workspace()
    protocol_receipt = require_frozen_protocol(ws)
    protocol = load_protocol(ws.protocol)
    universe = require_frozen_universe(ws, protocol_receipt)

    stem = stem_for(protocol, "scorer_acceptance")
    prior = latest_receipt(stem, ws.receipts)
    if prior is not None and not superseding:
        raise FreezeRefused("rung 3 is already frozen; a frozen rung is never re-sealed")

    modules: list[dict[str, str]] = []
    for declared in protocol["scorer_acceptance"]["scorer"]["modules"]:
        path = ws.root / declared
        if not path.is_file():
            raise FreezeRefused(
                f"the declared scorer module is absent: {declared}. The acceptance "
                "semantics cannot be frozen around a scorer that has not been written."
            )
        modules.append({"path": declared, "sha256": sha_file(path)})

    body = {
        "schema": "tavonel.v2.scorer_acceptance_freeze.v1",
        "rung": 3,
        "rung_name": "scorer_acceptance",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_receipt["protocol_sha256"],
        "protocol_freeze_run_id": protocol_receipt["provenance"]["run_id"],
        "universe_freeze_receipt": universe["_receipt_path"],
        "universe_freeze_run_id": universe["provenance"]["run_id"],
        "universe_sha256": universe["universe_sha256"],
        "scorer_modules": modules,
        "acceptance_blocks": list(ACCEPTANCE_BLOCKS),
        "acceptance_semantics_sha256": acceptance_digest(protocol),
        "why": (
            "INC-V2-048. A condition drifted from the declaration it implemented and "
            "reported the more comfortable of two measurements. A protocol digest "
            "cannot see a scorer module move; this rung can."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    if prior is not None:
        if (
            prior.get("universe_freeze_run_id") == body["universe_freeze_run_id"]
            and prior.get("acceptance_semantics_sha256") == body["acceptance_semantics_sha256"]
            and [m["sha256"] for m in prior.get("scorer_modules", [])]
            == [m["sha256"] for m in modules]
        ):
            raise FreezeRefused(
                "the scorer freeze already names the universe in force and pins the "
                "same modules and acceptance semantics. There is nothing to supersede."
            )
        body["supersedes"] = {
            "receipt": prior.get("_receipt_path"),
            "run_id": _run_id_of(prior),
            "superseded_universe_freeze_run_id": prior.get("universe_freeze_run_id"),
            "why": (
                "rung 3 was re-sealed after the eCFR canonicalisation repair, which "
                "left this receipt naming a universe no longer in force. The scorer "
                "modules and the acceptance semantics are unchanged; only the link "
                "moved."
            ),
            "permitted_because": ("no V2R1 measurement receipt existed, checked mechanically"),
            "preserved": True,
        }
    state = "FROZEN_SUPERSEDING" if prior is not None else "FROZEN"
    return {"state": state, "modules": len(modules), **write_receipt(stem, body, ws)}


def supersede_scorer(ws: Workspace | None = None) -> dict[str, Any]:
    """Re-seal rung 4 when the universe below it was re-sealed.

    Same mechanical guard as `supersede_universe`: reachable only while no V2R1
    measurement receipt exists. The scorer CODE and the acceptance semantics are
    unchanged here -- what moved is the link to rung 3 -- and the receipt records
    both so a reader can tell a relinking from a semantics change.
    """
    ws = ws or Workspace()
    clean, blocking = _nothing_has_been_scored(ws)
    if not clean:
        raise FreezeRefused(
            "the scorer freeze may not be re-sealed: V2R1 has already been "
            "SCORED.\n  " + "\n  ".join(blocking)
        )
    return freeze_scorer(ws, superseding=True)


def require_frozen_scorer(
    ws: Workspace, protocol_receipt: dict[str, Any], universe: dict[str, Any]
) -> dict[str, Any]:
    protocol = load_protocol(ws.protocol)
    receipt = latest_receipt(stem_for(protocol, "scorer_acceptance"), ws.receipts)
    if receipt is None:
        raise FreezeRefused(
            "rung 3 is missing: the scorer and the acceptance semantics have not been "
            "frozen. Without it a scorer module can move between the universe freeze "
            "and the measurement and nothing would notice -- that is INC-V2-048."
        )
    if receipt.get("universe_freeze_run_id") != universe["provenance"]["run_id"]:
        raise FreezeRefused(
            "the scorer freeze does not name the current universe freeze run; the "
            "ladder chain is broken between rung 2 and rung 3"
        )
    current = acceptance_digest(protocol)
    if receipt.get("acceptance_semantics_sha256") != current:
        raise FreezeRefused(
            "the ACCEPTANCE SEMANTICS have changed since they were frozen.\n"
            f"  frozen:  {receipt.get('acceptance_semantics_sha256')}\n"
            f"  current: {current}\n"
            "The grading rule is not adjusted after the universe is known."
        )
    for module in receipt.get("scorer_modules", ()):
        path = ws.root / module["path"]
        if not path.is_file():
            raise FreezeRefused(f"a frozen scorer module has disappeared: {module['path']}")
        if sha_file(path) != module["sha256"]:
            raise FreezeRefused(
                f"a frozen scorer module has changed since rung 3: {module['path']}\n"
                f"  frozen:  {module['sha256']}\n  current: {sha_file(path)}"
            )
    return receipt


# --------------------------------------------------------------------------
# rung 4 — the exclusion policy and the realised exclusion set
# --------------------------------------------------------------------------


def realised_exclusions(universe: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (
            {
                "lineage_id": row["lineage_id"],
                "reason": row["reason"],
                "collision_group": row.get("collision_group"),
            }
            for row in universe.get("exclusions", {}).get("rows", ())
        ),
        key=lambda row: (row["lineage_id"], row["reason"]),
    )


def freeze_exclusions(ws: Workspace | None = None) -> dict[str, Any]:
    ws = ws or Workspace()
    protocol_receipt = require_frozen_protocol(ws)
    protocol = load_protocol(ws.protocol)
    universe = require_frozen_universe(ws, protocol_receipt)
    scorer = require_frozen_scorer(ws, protocol_receipt, universe)

    stem = stem_for(protocol, "exclusions")
    if latest_receipt(stem, ws.receipts) is not None:
        raise FreezeRefused("rung 4 is already frozen; a frozen rung is never re-sealed")

    rows = realised_exclusions(universe)
    body = {
        "schema": "tavonel.v2.exclusion_freeze.v1",
        "rung": 4,
        "rung_name": "exclusions",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_receipt["protocol_sha256"],
        "universe_freeze_run_id": universe["provenance"]["run_id"],
        "scorer_freeze_receipt": scorer["_receipt_path"],
        "scorer_freeze_run_id": scorer["provenance"]["run_id"],
        "exclusion_policy_sha256": exclusion_policy_digest(protocol),
        "realised_exclusions_sha256": canonical_sha(rows),
        "realised_exclusion_count": len(rows),
        "by_reason": universe["exclusions"]["by_reason"],
        "collision_groups": universe["collision_groups"],
        "collision_groups_wholly_excluded": True,
        "realised_exclusions": rows,
        "no_post_freeze_change": (
            "after this rung neither the policy nor the realised set may change. A "
            "policy edit and a set edit fail separately and are named separately, so "
            "neither can be explained away as the other."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    return {"state": "FROZEN", "exclusions": len(rows), **write_receipt(stem, body, ws)}


def require_frozen_exclusions(
    ws: Workspace,
    protocol_receipt: dict[str, Any],
    universe: dict[str, Any],
    scorer: dict[str, Any],
) -> dict[str, Any]:
    protocol = load_protocol(ws.protocol)
    receipt = latest_receipt(stem_for(protocol, "exclusions"), ws.receipts)
    if receipt is None:
        raise FreezeRefused(
            "rung 4 is missing: the exclusion policy and the realised exclusion set "
            "have not been frozen. INC-V2-046 is what an unpinned exclusion rule "
            "costs -- a rule settled while looking at the data cannot be told apart "
            "from a rule settled because of the data."
        )
    if receipt.get("scorer_freeze_run_id") != scorer["provenance"]["run_id"]:
        raise FreezeRefused(
            "the exclusion freeze does not name the current scorer freeze run; the "
            "ladder chain is broken between rung 3 and rung 4"
        )
    if receipt.get("universe_freeze_run_id") != universe["provenance"]["run_id"]:
        raise FreezeRefused("the exclusion freeze does not name the current universe freeze run")
    current_policy = exclusion_policy_digest(protocol)
    if receipt.get("exclusion_policy_sha256") != current_policy:
        raise FreezeRefused(
            "the EXCLUSION POLICY has changed since it was frozen.\n"
            f"  frozen:  {receipt.get('exclusion_policy_sha256')}\n"
            f"  current: {current_policy}\n"
            "V1 changed its verification behaviour after its freeze and recorded it "
            "honestly. Predeclaring is what makes that impossible to do silently."
        )
    current_rows = realised_exclusions(universe)
    if receipt.get("realised_exclusions_sha256") != canonical_sha(current_rows):
        raise FreezeRefused(
            "the REALISED EXCLUSION SET has changed since it was frozen. Which pairs "
            "left the universe is pinned; it is not re-derived at measurement time."
        )
    problems = verify_collision_groups_whole(universe)
    if problems:
        raise FreezeRefused("collision groups are not wholly excluded:\n  " + "\n  ".join(problems))
    return receipt


# --------------------------------------------------------------------------
# the execution gate
# --------------------------------------------------------------------------


def require_execution_preconditions(ws: Workspace | None = None) -> dict[str, Any]:
    """The four rungs, in order, each verified against what is on disk NOW.

    The V2 runner calls this before it reads a single pair, and exits non-zero on
    the refusal. Every rung is checked for presence, for digest agreement with
    the file it pins, and for its link to the rung before it. Nothing here trusts
    a timestamp and nothing here can be satisfied by a receipt alone.
    """
    ws = ws or Workspace()
    protocol_receipt = require_frozen_protocol(ws)
    universe = require_frozen_universe(ws, protocol_receipt)
    scorer = require_frozen_scorer(ws, protocol_receipt, universe)
    exclusions = require_frozen_exclusions(ws, protocol_receipt, universe, scorer)
    protocol = load_protocol(ws.protocol)

    sentinels = unresolved_sentinels(ws.protocol)
    if sentinels:  # pragma: no cover -- rung 1 refuses first, this is belt and braces
        raise FreezeRefused("the frozen protocol still carries draft sentinels: " + str(sentinels))

    return {
        "state": "READY",
        "protocol_id": protocol["protocol_id"],
        "protocol_sha256": protocol_receipt["protocol_sha256"],
        "chain": [
            {"rung": 1, "name": "protocol", "run_id": protocol_receipt["provenance"]["run_id"]},
            {"rung": 2, "name": "universe", "run_id": universe["provenance"]["run_id"]},
            {"rung": 3, "name": "scorer_acceptance", "run_id": scorer["provenance"]["run_id"]},
            {"rung": 4, "name": "exclusions", "run_id": exclusions["provenance"]["run_id"]},
        ],
        "universe_sha256": universe["universe_sha256"],
        "pair_count": universe["pair_count"],
        "exclusion_count": exclusions["realised_exclusion_count"],
        "collision_groups": len(universe["collision_groups"]),
        "acceptance_semantics_sha256": scorer["acceptance_semantics_sha256"],
        "exclusion_policy_sha256": exclusions["exclusion_policy_sha256"],
        "measurement_stem": stem_for(protocol, "measurement"),
        "already_measured": [
            path.name for path in runs_of(stem_for(protocol, "measurement"), ws.receipts)
        ],
    }


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

STAGES = {
    "protocol": freeze_protocol,
    "universe": freeze_universe,
    "frame": freeze_acquisition_frame,
    "supersede-frame": supersede_frame,
    "supersede-protocol": supersede_protocol,
    "supersede-universe": supersede_universe,
    "supersede-scorer": supersede_scorer,
    "scorer": freeze_scorer,
    "exclusions": freeze_exclusions,
    "gate": require_execution_preconditions,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=tuple(STAGES))
    args = parser.parse_args(argv)
    try:
        result = STAGES[args.stage]()
    except FreezeRefused as error:
        print(json.dumps({"state": "REFUSED", "rung": args.stage, "why": str(error)}, indent=1))
        return 4
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
