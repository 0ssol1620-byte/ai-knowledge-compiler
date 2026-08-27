"""The contract-consistency gate: the protocol's prose and the executable
semantics must be the same state machine, or the freeze refuses.

Founder ruling section 10. V2R2's protocol described its obligations in prose
that read as perfectly reasonable, and the code implemented something that could
not be satisfied. Nothing compared the two. This file does.

It compares in BOTH directions -- every declared row must exist in the
executable table, and every executable row must be declared -- because a
one-directional check passes when the code grows a state the protocol never
mentioned, which is the state nobody has reasoned about.

The pre-existing INC-V2-047 compatibility contract is pinned by digest here.
That the rule V2R2 violated was already on disk, in those words, before V2R2 ran
is what makes the adjudication something other than an outcome-conditioned
relaxation.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest
import yaml

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import root_identity as ri  # noqa: E402
import v2r3_state_table as table  # noqa: E402

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.yaml"
COMPAT = NS / "docs" / "COMPAT_IDENTITY_UNCERTAINTY_QUARANTINE.md"
COMPAT_SHA = "sha256:655fd3d85eebec5209a2489290b34a8ca9d6c4cff8f1ac39e8504e4447f1b101"


@pytest.fixture(scope="module")
def protocol() -> dict:
    return yaml.safe_load(PROTOCOL.read_text(encoding="utf-8"))


def _executable_rows() -> dict[tuple[str, str, bool], object]:
    return {(r.side, r.resolver_state, r.quarantined): r for r in table.reachable_rows()}


def _declared_key(row: dict) -> list[tuple[str, str, bool]]:
    """One declared row expands to every executable key it claims.

    `quarantined: any` is a real declaration -- an AMBIGUOUS unit is unresolved
    whether or not a quarantine also holds it -- so it expands to both, and a
    reader who wrote `any` meaning "I did not think about it" gets two rows
    checked rather than none.
    """
    side = row["side"]
    #: A before-side row has no resolver decision of its own -- it is defined by
    #: NOT having been consumed by one -- and the executable table spells that
    #: absence `UNCONSUMED` rather than leaving it null.
    state = row.get("resolver_state", "UNCONSUMED")
    q = row["quarantined"]
    flags = [True, False] if q == "any" else [bool(q)]
    return [(side, state, flag) for flag in flags]


def test_the_protocol_is_valid_yaml_and_names_itself(protocol: dict) -> None:
    assert protocol["protocol_id"] == "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"
    assert protocol["status"] == "DRAFT_NOT_FROZEN"


def test_every_declared_row_matches_the_executable_table(protocol: dict) -> None:
    executable = _executable_rows()
    declared = protocol["effective_identity_disposition"]["rows"]
    checked = 0
    for name, row in sorted(declared.items()):
        for key in _declared_key(row):
            assert key in executable, f"row {name} declares unreachable state {key}"
            actual = executable[key]
            assert actual.effective.value == row["effective"], (
                f"row {name} {key}: protocol says {row['effective']}, "
                f"code says {actual.effective.value}"
            )
            assert sorted(actual.required) == sorted(row["requires"]), (
                f"row {name} {key}: required differs"
            )
            assert sorted(actual.forbidden) == sorted(row["forbids"]), (
                f"row {name} {key}: forbidden differs"
            )
            checked += 1
    assert checked == len(executable), "a declared row was checked twice or not at all"


def test_every_executable_row_is_declared(protocol: dict) -> None:
    """The direction a one-way check misses: code that grew a state the protocol
    never mentioned is code nobody reasoned about."""
    declared: set[tuple[str, str, bool]] = set()
    for row in protocol["effective_identity_disposition"]["rows"].values():
        declared.update(_declared_key(row))
    undeclared = sorted(set(_executable_rows()) - declared)
    assert undeclared == [], f"reachable states with no declared row: {undeclared}"


def test_the_declared_realised_state_is_the_state_the_checker_reports(
    protocol: dict,
) -> None:
    report = table.check_contract()
    declared = protocol["contract_consistency_gate"]["realised_state_at_declaration"]
    assert declared["state"] == report["state"] == "SATISFIABLE"
    assert declared["reachable_rows"] == report["reachable_rows"]


def test_row_b_is_the_v2r2_contradiction_and_the_protocol_says_so(
    protocol: dict,
) -> None:
    row = protocol["effective_identity_disposition"]["rows"]["B"]
    assert row["resolver_state"] == "NEW" and row["quarantined"] is True
    assert row["requires"] == ["identity_unresolved"]
    assert "unit_added" in row["forbids"]
    assert "unit_added" not in row["requires"]


def test_row_c_keeps_a_genuine_addition_definite(protocol: dict) -> None:
    """Over-quarantine is a defect too. Without this the protocol could satisfy
    every other assertion here by declaring everything unresolved."""
    row = protocol["effective_identity_disposition"]["rows"]["C"]
    assert row["requires"] == ["unit_added"]
    assert row["effective"] == "EFFECTIVE_NEW"


def test_the_compatibility_contract_is_present_at_the_pinned_digest(
    protocol: dict,
) -> None:
    """The rule V2R2 violated was on disk, in those words, before V2R2 ran."""
    actual = "sha256:" + hashlib.sha256(COMPAT.read_bytes()).hexdigest()
    assert actual == COMPAT_SHA
    assert COMPAT_SHA.split(":", 1)[1] in protocol["contract_consistency_gate"][
        "prose_and_code_must_agree"
    ]


def test_the_contract_forbids_what_the_rows_forbid() -> None:
    """Clause 2 of the contract and rows A/B/D/F have to be the same rule.

    Read from the contract text rather than restated, so an edit to the contract
    that this protocol did not follow shows up here instead of in a measurement.
    """
    body = COMPAT.read_text(encoding="utf-8")
    assert "Not `UNIT_ADDED`" in body
    assert "not `UNIT_REMOVED`" in body
    assert "not `MODIFIED_CLAIM`" in body
    after_unresolved = [
        r
        for r in table.reachable_rows()
        if r.side == "after" and r.effective.value == "EFFECTIVE_UNRESOLVED"
    ]
    #: Rows A(quarantined and not), B and D. Counted rather than sampled: a
    #: `next()` inside the loop would check the same row three times and report
    #: three passes.
    assert len(after_unresolved) == 4
    for row in after_unresolved:
        assert "unit_added" in row.forbidden
        assert "identity_unresolved" in row.required
    before_row = next(
        r
        for r in table.reachable_rows()
        if r.side == "before_unconsumed" and r.quarantined
    )
    assert {"unit_removed", "modified_claim"} <= set(before_row.forbidden)
    assert "identity_unresolved" in before_row.required


def test_the_frame_the_protocol_names_is_the_frame_on_disk(protocol: dict) -> None:
    import sources_v2r3

    assert protocol["cohort"]["frame"].endswith("sources_v2r3.py")
    assert protocol["protocol_id"] == sources_v2r3.PROTOCOL_ID
    assert protocol["cohort_sufficiency"]["minimum_admitted_pairs"] == sources_v2r3.FLOOR
    assert (
        protocol["cohort_sufficiency"]["minimum_families"]
        == sources_v2r3.FAMILIES_REQUIRED
    )


#: Frames declared AFTER V2R3. `realised_at_declaration` is, by its own name, a
#: fact about the moment V2R3 declared, so re-deriving it has to be done over the
#: modules that existed THEN. Recomputing it over today's tree drifts the instant
#: a successor lands: V2R4's frame added 86 identities and turned 875 into 961
#: without a single V2R3 number changing.
#:
#: Disjointness is a different question and stays LIVE below -- V2R3's roots must
#: still clash with nothing, successors included, and that assertion is stronger
#: than the frozen one it replaces rather than weaker.
FRAMES_DECLARED_AFTER_V2R3 = frozenset({"sources_v2r3r1", "sources_v2r4"})


def test_the_declared_root_counts_are_the_counts_on_disk(protocol: dict) -> None:
    import sources_v2r3

    declared = protocol["root_normalisation"]["realised_at_declaration"]
    at_declaration = ri.prior_root_identities(
        exclude_modules={"sources_v2r3", *FRAMES_DECLARED_AFTER_V2R3}
    )
    mine = ri.read_module_roots("sources_v2r3")

    assert len(at_declaration["modules_read"]) == declared["prior_modules_read"]
    assert at_declaration["identity_count"] == declared["prior_identities"]
    assert at_declaration["by_family"] == declared["by_family"]
    assert at_declaration["unverifiable_count"] == declared["unverifiable"] == 0
    assert len(mine["identities"]) == declared["v2r3_roots_declared"]
    assert mine["unverifiable"] == []

    #: Live, against every frame that exists today. A successor that declared one
    #: of V2R3's roots would turn this red even though the frozen counts above
    #: still reconcile.
    live = ri.prior_root_identities(exclude_modules={"sources_v2r3"})
    assert len(mine["identities"] & live["identities"]) == declared["clashes_with_prior"] == 0
    assert live["unverifiable_count"] == 0
    #: Capacity has to cover the quota, or a family is short by construction
    #: rather than by what the sources turned out to hold.
    caps = sources_v2r3.CONTAINER_CAP
    assert len(sources_v2r3.GIT_ROOTS) * caps["git_docs"] >= sources_v2r3.FAMILY_QUOTA["git_docs"]
    assert (
        len(sources_v2r3.ECFR_ROOTS) * caps["regulation_ecfr"]
        >= sources_v2r3.FAMILY_QUOTA["regulation_ecfr"]
    )


def test_the_sec_start_is_above_every_spent_cik() -> None:
    """Container disjointness for the family that is declared as a rule."""
    import glob
    import json
    import re

    import sources_v2r3

    start = sources_v2r3.SEC_ISSUER_RULE["start_after_cik"]
    highest = 0
    for stem in (
        "identity-change-migration-closure-v2r1-universe",
        "identity-change-migration-closure-v2r2-universe",
    ):
        receipts = sorted(glob.glob(str(NS / "receipts" / f"{stem}--*.json")))
        if not receipts:
            continue
        body = json.loads(Path(receipts[-1]).read_text(encoding="utf-8"))
        for row in body.get("pairs", ()):
            match = re.match(r"sec:(\d+):", row["lineage_id"])
            if match:
                highest = max(highest, int(match.group(1)))
    if not highest:
        pytest.skip("no spent SEC lineages are present in this checkout")
    assert start >= highest, f"start_after_cik {start} is not above spent CIK {highest}"


def test_the_spent_universes_are_named_in_the_exclusion_policy(protocol: dict) -> None:
    policy = protocol["exclusion_policy"]
    assert "v2r1_spent_universe" in policy
    assert "v2r2_spent_universe" in policy
    assert "270" in policy["v2r2_spent_universe"]["what"]


def test_the_execution_block_forbids_a_preview(protocol: dict) -> None:
    execution = protocol["execution"]
    assert execution["scored_once"] is True
    assert "no preview" in execution["no_preview"]
    assert execution["gpu_seconds"] == 0
    assert len(execution["preconditions_that_must_all_be_PROVEN_before_the_single_run"]) >= 8
