"""Every gate in the V2 four-rung freeze ladder, proven able to come back RED.

This study's most-repeated defect is a check that reports a clean result because
it is watching nothing. INC-V2-036 is the guard whose failure was structurally
impossible; INC-V2-044 is the guard whose success was; INC-V2-048 is the guard
that read the more comfortable of two measurements. All three reported a fixed
answer and none of them was a measurement.

So every test below injects a violation and asserts the ladder refuses. The
green direction is asserted too, in exactly one place, because a suite that could
only ever see red would prove that the refusals fire and nothing about whether
they can ever be satisfied -- which is the same defect wearing the other mask.

Nothing here writes into the real receipts directory, opens a V1 file for
writing, runs a change predicate, or reads any SFI3 artifact. The whole ladder is
exercised against a temporary tree, which is why `Workspace` takes every path as
a field.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]

import freeze_migration_closure_v2 as ladder  # noqa: E402

REAL_V2 = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2.yaml"
REAL_V1 = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"

#: A ChangeKind production actually emits, standing in for whatever the repair
#: names its quarantine record. Never a guessed string -- a guessed record kind
#: would make INVARIANT_6(e) look for nothing and report clean.
A_REAL_CHANGE_KIND = "identity_unresolved"


# --------------------------------------------------------------------------
# a temporary tree that the whole ladder can be run against
# --------------------------------------------------------------------------


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _side(
    root: Path,
    lineage: str,
    side: str,
    *,
    raw_ok: bool = True,
    raw_digest_recorded: bool = True,
    canonical_recorded: str | None = None,
    canonical_convention: str | None = None,
) -> dict[str, Any]:
    """One side of a candidate pair, in the enumerating lane's declared shape.

    `raw_sha256_recorded` is what acquisition wrote down; the freeze recomputes
    the bytes and compares. `canonical_sha256_recorded` is usually absent,
    because the historical acquisition manifests never recorded one.
    """
    raw = root / "payloads" / f"{lineage}.{side}.raw"
    canonical = root / "payloads" / f"{lineage}.{side}.canonical.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(f"{lineage}/{side}/raw".encode())
    canonical.write_text(
        json.dumps({"units": [{"text": f"{lineage} {side}"}]}), encoding="utf-8"
    )
    entry: dict[str, Any] = {
        "raw_path": raw.relative_to(root).as_posix(),
        "canonical_path": canonical.relative_to(root).as_posix(),
        "canonical_sha256_recorded": canonical_recorded,
        "canonical_digest_convention": canonical_convention,
    }
    if raw_digest_recorded:
        entry["raw_sha256_recorded"] = (
            _sha(raw.read_bytes()) if raw_ok else _sha(b"not these bytes")
        )
    return entry


def _row(root: Path, lineage: str, **overrides: Any) -> dict[str, Any]:
    row = {
        "lineage_id": lineage,
        "family": "git_docs",
        "before_version": "v1",
        "after_version": "v2",
        "before": _side(root, lineage, "before"),
        "after": _side(root, lineage, "after"),
    }
    row.update(overrides)
    return row


def _protocol_for(root: Path, *, scorer_modules: list[str]) -> Path:
    """The real V2 protocol, with the draft sentinel resolved and a real scorer.

    The invariant bodies survive the round trip untouched, so the delta check
    against V1 is exercised on the real declaration rather than on a stand-in.
    """
    text = REAL_V2.read_text(encoding="utf-8").replace(ladder.SENTINEL, A_REAL_CHANGE_KIND)
    body = yaml.safe_load(text)
    body["scorer_acceptance"]["scorer"]["modules"] = scorer_modules
    body["manifest_contract"]["path"] = "manifest.json"
    target = root / "protocols" / "ICMC_V2.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return target


def stage(tmp_path: Path, rows: list[dict[str, Any]] | None = None) -> ladder.Workspace:
    """A complete, self-contained tree the four rungs can be climbed in."""
    root = tmp_path
    (root / "scorer").mkdir(parents=True, exist_ok=True)
    for name in ("alpha.py", "beta.py"):
        (root / "scorer" / name).write_text(f"# stand-in scorer module {name}\n", encoding="utf-8")
    protocol = _protocol_for(root, scorer_modules=["scorer/alpha.py", "scorer/beta.py"])

    prior = root / "prior"
    prior.mkdir(parents=True, exist_ok=True)
    (prior / "sfi2-native-provenance--20260823T000000Z-aaaaaaaaaaaa.json").write_text(
        json.dumps(
            {
                "rebuild": {
                    "E5_confirmed_selective_stale_escape": {
                        "confirmed": [{"lineage_id": "confirmed-14-a"}]
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (prior / f"{ladder.V1_UNIVERSE_STEM}--20260825T000853Z-bbbbbbbbbbbb.json").write_text(
        json.dumps({"pairs": [{"lineage_id": "v1-universe-a"}]}), encoding="utf-8"
    )

    for name, lineage in (("sfi1.json", "retro-538-a"), ("sfi2.json", "retro-538-b")):
        (root / name).write_text(json.dumps({"admitted": [{"lineage_id": lineage}]}), "utf-8")

    if rows is None:
        rows = default_rows(root)
    (root / "manifest.json").write_text(json.dumps({"documents": rows}), encoding="utf-8")

    return ladder.Workspace(
        root=root,
        protocol=protocol,
        v1_protocol=REAL_V1,
        receipts=root / "receipts",
        prior_receipts=prior,
        retrospective_cohorts=(root / "sfi1.json", root / "sfi2.json"),
        manifest=root / "manifest.json",
    )


def default_rows(root: Path) -> list[dict[str, Any]]:
    """Three clean pairs, and one row for every declared exclusion reason."""
    clean = [_row(root, f"clean-{index}") for index in range(3)]
    duplicate = _row(root, "clean-0")
    retro = [_row(root, "retro-538-a"), _row(root, "retro-538-b")]
    confirmed = _row(root, "confirmed-14-a")
    from_v1 = _row(root, "v1-universe-a")
    # Two distinct documents whose truncated cache slug is the same. BOTH
    # payloads verify -- the collision must be found structurally, by key.
    collide = [
        _row(root, "collide-a", cache_slug="shared-truncated-slug"),
        _row(root, "collide-b", cache_slug="shared-truncated-slug"),
    ]
    mismatch = _row(root, "digest-mismatch")
    mismatch["before"] = _side(root, "digest-mismatch", "before", raw_ok=False)
    absent = _row(root, "digest-absent")
    absent["after"] = _side(root, "digest-absent", "after", raw_digest_recorded=False)
    malformed = _row(root, "malformed", family="")
    return [*clean, duplicate, *retro, confirmed, from_v1, *collide, mismatch, absent, malformed]


def climb(ws: ladder.Workspace, upto: str = "exclusions") -> None:
    """Freeze rungs in order, stopping after `upto`."""
    for rung in ("protocol", "universe", "scorer", "exclusions"):
        ladder.STAGES[rung](ws)
        if rung == upto:
            return


def edit_protocol(ws: ladder.Workspace, mutate) -> None:
    body = yaml.safe_load(ws.protocol.read_text(encoding="utf-8"))
    mutate(body)
    ws.protocol.write_text(yaml.safe_dump(body, sort_keys=False, allow_unicode=True), "utf-8")


# ==========================================================================
# the four freezes -- executing without each of them refuses
# ==========================================================================


def test_gate_refuses_without_the_protocol_freeze(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "rung 1 is missing" in str(error.value)


def test_gate_refuses_without_the_universe_freeze(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "rung 2 is missing" in str(error.value)


def test_gate_refuses_without_the_scorer_and_acceptance_freeze(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "rung 3 is missing" in str(error.value)


def test_gate_refuses_without_the_exclusion_freeze(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="scorer")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "rung 4 is missing" in str(error.value)


def test_the_rungs_refuse_out_of_order(tmp_path: Path) -> None:
    """Ordering is a precondition, not a convention -- so it is checked upward too."""
    ws = stage(tmp_path)
    with pytest.raises(ladder.FreezeRefused):
        ladder.freeze_universe(ws)
    with pytest.raises(ladder.FreezeRefused):
        ladder.freeze_scorer(ws)
    with pytest.raises(ladder.FreezeRefused):
        ladder.freeze_exclusions(ws)


# ==========================================================================
# digest pinning -- a thing edited after its freeze refuses
# ==========================================================================


def test_a_protocol_edited_after_its_freeze_refuses_on_digest_mismatch(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws)
    ladder.require_execution_preconditions(ws)  # green before the edit

    ws.protocol.write_text(
        ws.protocol.read_text(encoding="utf-8") + "\nan_edit_made_after_the_freeze: true\n",
        encoding="utf-8",
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "changed since it was frozen" in str(error.value)


def test_a_frozen_protocol_is_never_re_sealed_in_place(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    ws.protocol.write_text(
        ws.protocol.read_text(encoding="utf-8") + "\nlater_edit: true\n", encoding="utf-8"
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_protocol(ws)
    assert "already frozen at a different digest" in str(error.value)


def test_a_scorer_module_edited_after_rung_3_refuses(tmp_path: Path) -> None:
    """INC-V2-048: a protocol digest cannot see the grading CODE move."""
    ws = stage(tmp_path)
    climb(ws)
    (ws.root / "scorer" / "alpha.py").write_text("# drifted\n", encoding="utf-8")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "scorer module has changed" in str(error.value)


def test_rung_3_refuses_a_scorer_module_that_does_not_exist(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    (ws.root / "scorer" / "beta.py").unlink()
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_scorer(ws)
    assert "declared scorer module is absent" in str(error.value)


def test_acceptance_semantics_changed_after_rung_3_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws)
    protocol_receipt = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "protocol"), ws.receipts
    )
    universe = ladder.require_frozen_universe(ws, protocol_receipt)

    edit_protocol(ws, lambda body: body["pass_rule"]["requires_all_of"].append("something new"))
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_frozen_scorer(ws, protocol_receipt, universe)
    assert "ACCEPTANCE SEMANTICS have changed" in str(error.value)


# ==========================================================================
# the exclusion policy -- rung 4
# ==========================================================================


def test_an_exclusion_policy_changed_after_its_freeze_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws)
    protocol_receipt = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "protocol"), ws.receipts
    )
    universe = ladder.require_frozen_universe(ws, protocol_receipt)
    scorer = ladder.require_frozen_scorer(ws, protocol_receipt, universe)

    edit_protocol(
        ws,
        lambda body: body["exclusion_policy"]["collision_detection"]["collision_keys"].remove(
            "cache_slug"
        ),
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_frozen_exclusions(ws, protocol_receipt, universe, scorer)
    assert "EXCLUSION POLICY has changed" in str(error.value)

    # and the whole gate refuses too, because the policy lives in the protocol
    with pytest.raises(ladder.FreezeRefused):
        ladder.require_execution_preconditions(ws)


def test_a_realised_exclusion_set_changed_after_its_freeze_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws)
    protocol_receipt = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "protocol"), ws.receipts
    )
    universe = ladder.require_frozen_universe(ws, protocol_receipt)
    scorer = ladder.require_frozen_scorer(ws, protocol_receipt, universe)

    tampered = copy.deepcopy(universe)
    tampered["exclusions"]["rows"] = [
        row for row in tampered["exclusions"]["rows"] if row["reason"] != "PAYLOAD_DIGEST_MISMATCH"
    ]
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_frozen_exclusions(ws, protocol_receipt, tampered, scorer)
    assert "REALISED EXCLUSION SET has changed" in str(error.value)


# ==========================================================================
# collisions
# ==========================================================================


def test_a_collision_is_detected_structurally_although_both_members_verify(
    tmp_path: Path,
) -> None:
    """A collision whose members happen to verify is still ambiguous provenance."""
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    groups = universe["collision_groups"]
    assert len(groups) == 1
    assert groups[0]["members"] == ["collide-a", "collide-b"]

    excluded = {row["lineage_id"]: row for row in universe["exclusions"]["rows"]}
    for member in ("collide-a", "collide-b"):
        assert excluded[member]["reason"] == "CACHE_KEY_COLLISION_GROUP"
    kept = {row["lineage_id"] for row in universe["pairs"]}
    assert not kept & {"collide-a", "collide-b"}


def test_a_collision_group_with_only_the_failing_member_excluded_is_rejected(
    tmp_path: Path,
) -> None:
    """Keeping the member that still verifies is choosing the convenient reading."""
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    protocol = ladder.load_protocol(ws.protocol)
    universe = ladder.latest_receipt(ladder.stem_for(protocol, "universe"), ws.receipts)

    partial = copy.deepcopy(universe)
    partial["exclusions"]["rows"] = [
        row for row in partial["exclusions"]["rows"] if row["lineage_id"] != "collide-b"
    ]
    # the frozen-pair shape, not the manifest-row shape: a survivor has already
    # been through verification, so it carries recomputed digests
    survivor = copy.deepcopy(partial["pairs"][0])
    survivor["lineage_id"] = "collide-b"
    partial["pairs"] = sorted([*partial["pairs"], survivor], key=lambda row: row["lineage_id"])
    partial["universe_sha256"] = ladder.universe_digest(partial["pairs"])

    problems = ladder.verify_collision_groups_whole(partial)
    assert problems and "partially excluded" in problems[0]

    # and it is refused where it matters: at the gate, from a receipt on disk
    for key in ("_receipt_path", "provenance", "receipt_sha256"):
        partial.pop(key, None)
    ladder.write_receipt(
        ladder.stem_for(protocol, "universe"),
        partial,
        ws,
        run_id="29991231T235959Z-ffffffffffff",
    )
    protocol_receipt = ladder.latest_receipt(ladder.stem_for(protocol, "protocol"), ws.receipts)
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_frozen_universe(ws, protocol_receipt)
    assert "not wholly excluded" in str(error.value)


def test_collision_groups_merge_through_a_shared_row(tmp_path: Path) -> None:
    """A row may not be excluded under one key and kept under another."""
    root = tmp_path
    rows = [_row(root, "clean-0"), _row(root, "a"), _row(root, "b"), _row(root, "c")]
    rows[1]["cache_slug"] = "shared"
    rows[2]["cache_slug"] = "shared"
    # c shares b's cached payload path, so {a,b} and {b,c} are one ambiguity
    rows[3]["before"] = dict(rows[2]["before"])
    ws = stage(tmp_path, rows=rows)
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    assert len(universe["collision_groups"]) == 1
    assert universe["collision_groups"][0]["members"] == ["a", "b", "c"]
    assert {row["lineage_id"] for row in universe["pairs"]} == {"clean-0"}


# ==========================================================================
# the invariant set must be the V1 eight, or carry a recorded delta
# ==========================================================================


def _freeze_protocol_expecting_refusal(ws: ladder.Workspace) -> str:
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_protocol(ws)
    return str(error.value)


def test_an_added_invariant_without_a_recorded_delta_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)

    def mutate(body: dict[str, Any]) -> None:
        body["invariants"]["INVARIANT_9_something_new"] = {"statement": "new"}

    edit_protocol(ws, mutate)
    assert "INVARIANT ADDED and not declared" in _freeze_protocol_expecting_refusal(ws)


def test_a_removed_invariant_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    edit_protocol(ws, lambda body: body["invariants"].pop("INVARIANT_7_only_predeclared_ignores"))
    assert "INVARIANT REMOVED" in _freeze_protocol_expecting_refusal(ws)


def test_a_changed_invariant_without_a_recorded_delta_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)

    def mutate(body: dict[str, Any]) -> None:
        body["invariants"]["INVARIANT_4_changed_facet_resolves_typed_or_failclosed"][
            "population"
        ] = "every unresolved facet as well"

    edit_protocol(ws, mutate)
    problems = _freeze_protocol_expecting_refusal(ws)
    assert "INVARIANT CHANGED and not declared" in problems
    assert "INVARIANT_4" in problems


def test_a_delta_entry_with_no_repair_semantics_reason_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)

    def mutate(body: dict[str, Any]) -> None:
        body["protocol_delta"]["changed_invariants"][
            "INVARIANT_6_ambiguous_identity_stays_unresolved"
        ]["repair_semantics_reason"] = ""

    edit_protocol(ws, mutate)
    assert "carries no repair_semantics_reason" in _freeze_protocol_expecting_refusal(ws)


def test_a_delta_that_describes_no_change_refuses(tmp_path: Path) -> None:
    """A delta entry for an unchanged invariant pre-authorises an edit nobody made."""
    ws = stage(tmp_path)

    def mutate(body: dict[str, Any]) -> None:
        body["protocol_delta"]["changed_invariants"][
            "INVARIANT_2_identity_fold_remains_identity_only"
        ] = {"change": "none, really", "repair_semantics_reason": "reserved for later"}

    edit_protocol(ws, mutate)
    assert "pre-authorises an edit nobody" in _freeze_protocol_expecting_refusal(ws)


def test_the_real_v2_protocol_carries_the_v1_eight_with_two_declared_deltas() -> None:
    v2 = ladder.load_protocol(REAL_V2)
    v1 = ladder.load_protocol(REAL_V1)
    delta = ladder.invariant_delta(v2, v1)
    assert delta["problems"] == []
    assert delta["added"] == [] and delta["removed"] == []
    assert delta["changed"] == [
        "INVARIANT_6_ambiguous_identity_stays_unresolved",
        "INVARIANT_8_sfi2_cases_cannot_certify",
    ]
    assert len(delta["unchanged"]) == 6


def test_invariant_4_is_carried_from_v1_byte_for_byte() -> None:
    """The founder accepted INVARIANT_4 as V1 read it. It is not broadened here."""
    v2 = ladder.load_protocol(REAL_V2)
    v1 = ladder.load_protocol(REAL_V1)
    key = "INVARIANT_4_changed_facet_resolves_typed_or_failclosed"
    assert v2["invariants"][key] == v1["invariants"][key]


def test_invariant_6_gains_the_silence_clause_and_keeps_zero_tolerance() -> None:
    v2 = ladder.load_protocol(REAL_V2)
    body = v2["invariants"]["INVARIANT_6_ambiguous_identity_stays_unresolved"]
    assert "TOTAL ACCOUNTING" in body["executable_meaning"]
    assert "zero_tolerance" in body
    assert "(d)" in body["violation"] and "(e)" in body["violation"]


def test_the_nine_v1_violating_cases_are_not_an_ignore_list() -> None:
    """Nothing V1 observed may enter what V2 grades by.

    The prose may — and does — name the 1.10% figure in order to say it is not a
    threshold. What must be clean is the ACCEPTANCE SEMANTICS: the blocks rung 3
    pins are the ones a result is graded against, and a number or a case id in
    there would be a criterion fitted to an outcome.
    """
    v2 = ladder.load_protocol(REAL_V2)
    graded = json.dumps({block: v2[block] for block in ladder.ACCEPTANCE_BLOCKS})
    assert "1.10" not in graded
    assert "u:aad22330ba59cb2db5271716" not in graded
    assert "ecfr:40:141:141.153" not in graded
    for family, ignored in v2["predeclared_ignored_facets"]["by_family"].items():
        assert ignored == [], family
    # and the whole file names no violating case anywhere, prose included
    assert "u:aad22330ba59cb2db5271716" not in REAL_V2.read_text(encoding="utf-8")


# ==========================================================================
# the draft sentinel, and the quarantine channel
# ==========================================================================


def test_the_real_protocol_still_refuses_because_the_repair_has_not_declared_yet(
    tmp_path: Path,
) -> None:
    """The hole is loud. It cannot be frozen past, and no receipt is written."""
    ws = stage(tmp_path)
    ws.protocol.write_text(REAL_V2.read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_protocol(ws)
    assert "draft sentinels" in str(error.value)
    assert not list(ws.receipts.glob("*.json")) if ws.receipts.exists() else True


def test_a_quarantine_record_kind_production_does_not_emit_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    edit_protocol(
        ws,
        lambda body: body["quarantine_channel"].update(
            {"production_record": "identity_quarantined"}
        ),
    )
    assert "not a ChangeKind" in _freeze_protocol_expecting_refusal(ws)


def test_none_declared_by_production_is_an_accepted_answer(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    edit_protocol(
        ws,
        lambda body: body["quarantine_channel"].update(
            {"production_record": ladder.NONE_DECLARED}
        ),
    )
    frozen = ladder.freeze_protocol(ws)
    assert frozen["state"] == "FROZEN"


# ==========================================================================
# the manifest, which another lane owns
# ==========================================================================


def test_an_absent_manifest_refuses_rather_than_enumerating_a_second_universe(
    tmp_path: Path,
) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    (ws.root / "manifest.json").unlink()
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    assert "manifest is absent" in str(error.value)


def test_a_manifest_of_an_unexpected_shape_refuses_and_prints_what_it_expected(
    tmp_path: Path,
) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    (ws.root / "manifest.json").write_text(json.dumps({"rowz": []}), encoding="utf-8")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    message = str(error.value)
    assert "none of the accepted row keys" in message
    assert "expected row fields" in message


def test_a_row_that_cannot_be_named_refuses_rather_than_being_dropped(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    rows = json.loads((ws.root / "manifest.json").read_text(encoding="utf-8"))["documents"]
    rows.append({"family": "git_docs"})
    (ws.root / "manifest.json").write_text(json.dumps({"documents": rows}), encoding="utf-8")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    assert "carries no lineage identity" in str(error.value)


def test_an_empty_universe_refuses_rather_than_passing_vacuously(tmp_path: Path) -> None:
    root = tmp_path
    ws = stage(tmp_path, rows=[_row(root, "retro-538-a")])
    climb(ws, upto="protocol")
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    assert "vacuous" in str(error.value)


# ==========================================================================
# disjointness and digest recomputation
# ==========================================================================


def test_every_exclusion_reason_is_named_counted_and_from_the_closed_set(
    tmp_path: Path,
) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    protocol = ladder.load_protocol(ws.protocol)
    universe = ladder.latest_receipt(ladder.stem_for(protocol, "universe"), ws.receipts)
    closed = set(
        protocol["exclusion_policy"]["every_exclusion_is_named_and_counted"][
            "reasons_are_a_closed_set"
        ]
    )
    reasons = {row["reason"] for row in universe["exclusions"]["rows"]}
    assert reasons <= closed
    assert reasons == {
        "DUPLICATE_LINEAGE_ALREADY_TAKEN_FROM_AN_EARLIER_MANIFEST",
        "CACHE_KEY_COLLISION_GROUP",
        "NOT_DISJOINT_FROM_THE_538_PAIR_RETROSPECTIVE_COHORT",
        "NOT_DISJOINT_FROM_THE_14_CONFIRMED_SFI2_LINEAGES",
        "NOT_DISJOINT_FROM_THE_V1_FROZEN_UNIVERSE",
        "MANIFEST_ROW_MALFORMED",
        "RECORDED_DIGEST_ABSENT",
        "PAYLOAD_DIGEST_MISMATCH",
    }
    assert sum(universe["exclusions"]["by_reason"].values()) == len(
        universe["exclusions"]["rows"]
    )
    assert {row["lineage_id"] for row in universe["pairs"]} == {
        "clean-0",
        "clean-1",
        "clean-2",
    }


def test_a_v1_universe_lineage_cannot_enter_v2(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    excluded = {row["lineage_id"]: row["reason"] for row in universe["exclusions"]["rows"]}
    assert excluded["v1-universe-a"] == "NOT_DISJOINT_FROM_THE_V1_FROZEN_UNIVERSE"


def test_an_absent_v1_universe_receipt_refuses_rather_than_assuming_novelty(
    tmp_path: Path,
) -> None:
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    for path in ws.prior_receipts.glob(f"{ladder.V1_UNIVERSE_STEM}--*.json"):
        path.unlink()
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    assert "cannot prove its universe is NEW" in str(error.value)


def test_a_recorded_canonical_digest_that_reconciles_with_nothing_is_excluded(
    tmp_path: Path,
) -> None:
    """A recorded digest that cannot be reconciled is louder than none at all."""
    root = tmp_path
    rows = [_row(root, "clean-0"), _row(root, "canonical-drifted")]
    # acquisition recorded a canonical digest that reconciles with nothing on disk
    rows[1]["after"]["canonical_sha256_recorded"] = _sha(b"a digest from acquisition")
    ws = stage(tmp_path, rows=rows)
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    excluded = {row["lineage_id"]: row for row in universe["exclusions"]["rows"]}
    assert excluded["canonical-drifted"]["reason"] == "PAYLOAD_DIGEST_MISMATCH"
    assert "reconciles with no convention" in excluded["canonical-drifted"]["detail"]


def test_a_side_with_no_recorded_canonical_digest_is_pinned_but_not_called_verified(
    tmp_path: Path,
) -> None:
    """The historical manifests never recorded one. That gap is counted, not hidden."""
    ws = stage(tmp_path)
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    verification = universe["canonical_verification"]
    assert verification["sides_verified_against_acquisition"] == 0
    assert verification["sides_pinned_only_because_acquisition_recorded_none"] == 6
    for pair in universe["pairs"]:
        for side in ("before", "after"):
            assert pair[side]["canonical_verified_against_acquisition"] is False
            # pinned all the same: the digest is there and the gate recomputes it
            assert pair[side]["canonical_sha256"].startswith("sha256:")


def test_a_recomputed_raw_digest_is_never_compared_against_itself(tmp_path: Path) -> None:
    """`raw_sha256` means two different things in two producers. Only one key is read."""
    root = tmp_path
    row = _row(root, "recomputed-only")
    # the enumerator's recomputed value, offered under the ambiguous key
    row["before"]["raw_sha256"] = _sha(
        (root / row["before"]["raw_path"]).read_bytes()
    )
    del row["before"]["raw_sha256_recorded"]
    ws = stage(tmp_path, rows=[_row(root, "clean-0"), row])
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    excluded = {item["lineage_id"]: item for item in universe["exclusions"]["rows"]}
    assert excluded["recomputed-only"]["reason"] == "RECORDED_DIGEST_ABSENT"


def test_the_enumerators_own_exclusions_are_carried_into_the_receipt(
    tmp_path: Path,
) -> None:
    """Total accounting from raw candidates to frozen universe stays readable."""
    ws = stage(tmp_path)
    manifest = json.loads((ws.root / "manifest.json").read_text(encoding="utf-8"))
    manifest["excluded"] = [{"lineage_id": "dropped-upstream", "category": "BURNED"}]
    manifest["exclusion_categories"] = [{"category": "BURNED", "rows": 1}]
    (ws.root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    climb(ws, upto="universe")
    universe = ladder.latest_receipt(
        ladder.stem_for(ladder.load_protocol(ws.protocol), "universe"), ws.receipts
    )
    upstream = universe["upstream_exclusions"]
    assert upstream["rows_the_enumerator_dropped"] == 1
    assert upstream["enumerator_category_counts"] == [{"category": "BURNED", "rows": 1}]
    assert upstream["re_derived_independently_by_this_rung"] is True


def test_a_tampered_universe_content_digest_refuses(tmp_path: Path) -> None:
    ws = stage(tmp_path)
    climb(ws)
    protocol = ladder.load_protocol(ws.protocol)
    universe = ladder.latest_receipt(ladder.stem_for(protocol, "universe"), ws.receipts)
    tampered = copy.deepcopy(universe)
    tampered["pairs"] = tampered["pairs"][:1]
    for key in ("_receipt_path", "provenance", "receipt_sha256"):
        tampered.pop(key, None)
    ladder.write_receipt(
        ladder.stem_for(protocol, "universe"),
        tampered,
        ws,
        run_id="29991231T235959Z-ffffffffffff",
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "content digest does not match" in str(error.value)


# ==========================================================================
# the green direction
# ==========================================================================


def test_the_full_ladder_climbs_and_the_gate_reports_ready(tmp_path: Path) -> None:
    """Without this, the suite would prove the refusals fire and nothing else."""
    ws = stage(tmp_path)
    climb(ws)
    ready = ladder.require_execution_preconditions(ws)

    assert ready["state"] == "READY"
    assert [row["name"] for row in ready["chain"]] == [
        "protocol",
        "universe",
        "scorer_acceptance",
        "exclusions",
    ]
    # four DISTINCT run ids. Four rungs frozen inside one second from one
    # process must not share an id: rungs 2-4 each record the id of the rung
    # before them, and identical ids would let a stale receipt satisfy a link it
    # does not belong to. This assertion caught exactly that.
    assert len({row["run_id"] for row in ready["chain"]}) == 4
    assert ready["pair_count"] == 3
    assert ready["collision_groups"] == 1
    assert ready["already_measured"] == []
    assert ready["measurement_stem"] == "identity-change-migration-closure-v2"


def test_the_chain_is_references_not_timestamps(tmp_path: Path) -> None:
    """Each rung names the run id of the one before it, and a break refuses."""
    ws = stage(tmp_path)
    climb(ws)
    protocol = ladder.load_protocol(ws.protocol)
    universe = ladder.latest_receipt(ladder.stem_for(protocol, "universe"), ws.receipts)
    scorer = ladder.latest_receipt(ladder.stem_for(protocol, "scorer_acceptance"), ws.receipts)
    exclusions = ladder.latest_receipt(ladder.stem_for(protocol, "exclusions"), ws.receipts)

    assert scorer["universe_freeze_run_id"] == universe["provenance"]["run_id"]
    assert exclusions["scorer_freeze_run_id"] == scorer["provenance"]["run_id"]

    broken = copy.deepcopy(scorer)
    broken["universe_freeze_run_id"] = "20200101T000000Z-000000000000"
    for key in ("_receipt_path", "provenance", "receipt_sha256"):
        broken.pop(key, None)
    ladder.write_receipt(
        ladder.stem_for(protocol, "scorer_acceptance"),
        broken,
        ws,
        run_id="29991231T235959Z-ffffffffffff",
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.require_execution_preconditions(ws)
    assert "chain is broken between rung 2 and rung 3" in str(error.value)


# ==========================================================================
# the CLI contract the runner depends on
# ==========================================================================


@pytest.mark.parametrize("stage_name", ["protocol", "universe", "scorer", "exclusions", "gate"])
def test_the_cli_exits_4_on_the_real_tree_because_nothing_is_frozen(
    stage_name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refusal is an exit code, not a printed warning. No receipt is written."""
    before = sorted((NS / "receipts").glob("identity-change-migration-closure-v2-*.json"))
    assert ladder.main([stage_name]) == 4
    assert json.loads(capsys.readouterr().out)["state"] == "REFUSED"
    after = sorted((NS / "receipts").glob("identity-change-migration-closure-v2-*.json"))
    assert before == after


def test_v1_is_never_opened_for_writing() -> None:
    """The one thing V2 reads V1 for is lineage ids, and it never writes."""
    source = (NS / "tools" / "freeze_migration_closure_v2.py").read_text(encoding="utf-8")
    for forbidden in ("write_text", "unlink", "rmtree", "os.remove"):
        assert forbidden not in source, forbidden
    assert "V1_UNIVERSE_STEM" in source


def test_a_manifest_carrying_two_row_keys_and_neither_primary_refuses(
    tmp_path: Path,
) -> None:
    """Which list is the candidate universe would be a guess. This tool never guesses."""
    ws = stage(tmp_path)
    climb(ws, upto="protocol")
    rows = json.loads((ws.root / "manifest.json").read_text(encoding="utf-8"))["documents"]
    (ws.root / "manifest.json").write_text(
        json.dumps({"documents": rows, "candidates": rows[:1]}), encoding="utf-8"
    )
    with pytest.raises(ladder.FreezeRefused) as error:
        ladder.freeze_universe(ws)
    assert "more than one accepted row key" in str(error.value)


def test_lane_cs_real_manifest_parses_under_the_declared_contract() -> None:
    """Shape compatibility with the enumerating lane, checked without writing anything.

    This reads Lane C's manifest and asserts only that the declared contract can
    READ it: the rows key resolves, every lineage id resolves, and every side is
    classifiable. It asserts nothing about the content -- at the time of writing
    the manifest is the enumerator's own fixture output, so a content assertion
    would be an assertion about a fixture.
    """
    ws = ladder.Workspace()
    contract = ladder.load_protocol(ws.protocol)["manifest_contract"]
    manifest = ws.root / contract["path"]
    if not manifest.is_file():
        pytest.skip("the enumerating lane has not left a manifest yet")
    body = json.loads(manifest.read_text(encoding="utf-8"))
    rows = ladder._rows_from_manifest(body, contract, manifest)
    assert rows, "the manifest declares no candidate rows"
    for row in rows:
        assert ladder._lineage_id(row, contract)
        for side in ("before", "after"):
            entry, reason, _ = ladder._verify_side(row, side, ws, contract)
            assert (entry is None) != (reason is None)
            if reason is not None:
                assert reason in set(
                    ladder.load_protocol(ws.protocol)["exclusion_policy"][
                        "every_exclusion_is_named_and_counted"
                    ]["reasons_are_a_closed_set"]
                )
