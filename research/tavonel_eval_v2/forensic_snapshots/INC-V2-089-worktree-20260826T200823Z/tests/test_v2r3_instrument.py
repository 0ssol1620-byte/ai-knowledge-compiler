"""The V2R3 instrument's own guards: independence, satisfiability, roots.

Three things are proved here that no measurement can prove about itself:

  * the expected-side quarantine oracle does not import production's
    implementation of the same rule (founder ruling section 6);
  * the executable state table is total and satisfiable (section 7);
  * root identities are read from every historical source-module shape, and an
    unreadable shape blocks rather than being assumed disjoint (section 11).

Plus the two spent corpora as DEVELOPMENT regressions (section 9). Their results
certify nothing about V2R3 and may never become positive confirmatory evidence.
"""

from __future__ import annotations

import ast
import glob
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "tools"),
    str(NS / "acquisition"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import root_identity as ri  # noqa: E402
import selective_build as engine  # noqa: E402
import v2r3_effective_identity as eff  # noqa: E402
import v2r3_invariant6 as inv6  # noqa: E402
import v2r3_state_table as table  # noqa: E402
from akc_cir.semantic_diff import ChangeKind, DiffLevel, diff_documents  # noqa: E402
from v2r3_quarantine_oracle import build_oracle_quarantine  # noqa: E402

ORACLE = NS / "tools" / "v2r3_quarantine_oracle.py"
FORBIDDEN_IMPORTS = ("akc_cir.identity_quarantine", "akc_cir.semantic_diff")
DECLARED = "identity_unresolved"


# ---------------------------------------------------------------------------
# section 6 — independence, proved by AST
# ---------------------------------------------------------------------------
def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, at any nesting depth.

    Walks the whole tree rather than the top level, because a function-local
    `import akc_cir.identity_quarantine` would be just as much of a tautology
    and a top-level-only scan would miss it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_the_oracle_does_not_import_production_quarantine_or_diff() -> None:
    """Using production's `build_quarantine` as the expected side would compare
    production to itself, and a comparison that can only agree is not a
    measurement."""
    imported = _imported_modules(ORACLE)
    offending = sorted(
        name
        for name in imported
        for forbidden in FORBIDDEN_IMPORTS
        if name == forbidden or name.startswith(forbidden + ".")
    )
    assert offending == [], (
        f"{ORACLE.name} imports {offending}, which makes the expected side a copy "
        "of the thing being measured"
    )


def test_the_ast_guard_can_actually_go_red() -> None:
    """A guard that cannot fire is not a guard (INC-V2-036)."""
    source = "import akc_cir.identity_quarantine\nfrom akc_cir.semantic_diff import x\n"
    tree = ast.parse(source)
    names = {
        alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any(f in names for f in FORBIDDEN_IMPORTS)


def test_the_resolver_is_allowed_and_is_the_only_production_dependency() -> None:
    """`assign_one_to_one` may be used to OBTAIN decisions -- the property under
    test is their integration with the quarantine and the diff, not a second
    proof of the resolver algorithm."""
    imported = _imported_modules(ORACLE)
    akc = sorted(n for n in imported if n.startswith("akc_cir"))
    assert akc == ["akc_cir.identity"], akc


def test_the_oracle_implements_all_four_contract_sub_clauses() -> None:
    built = build_oracle_quarantine(
        #: The selected candidate is deliberately NOT in the declared tuple. A
        #: resolver that selected outside what it declared is exactly the case a
        #: clause-1a-only reading would miss, and when the two overlap the
        #: earlier reason wins and 1b becomes untestable.
        unsettled_decisions=[("u:amb", ("u:c2",), "u:sel"), ("u:onboth", (), None)],
        definite_matches=[("u:m", "u:c2")],
        before_ids=frozenset({"u:sel", "u:c2", "u:onboth", "u:m"}),
    )
    reasons = {i: built.reason_for(i) for i in sorted(built.ids)}
    assert reasons["u:c2"] == "declared_candidate_of_an_unsettled_decision"
    assert reasons["u:sel"] == "selected_candidate_of_an_unsettled_decision"
    assert reasons["u:onboth"] == "before_side_unit_sharing_the_unsettled_incoming_id"
    assert reasons["u:m"] == "definitely_matched_to_an_already_quarantined_member"


def test_an_empty_candidate_never_becomes_a_member() -> None:
    """An empty id names nothing, so admitting it would create a member no
    record could make visible and leave contract clause 3 unsatisfiable for it."""
    built = build_oracle_quarantine(
        unsettled_decisions=[("u:amb", ("", "u:real"), None)],
        definite_matches=[],
        before_ids=frozenset({"u:real"}),
    )
    assert built.ids == frozenset({"u:real"})


def test_the_transitive_clause_runs_to_fixpoint() -> None:
    """A chain, so a single pass would leave the tail unquarantined."""
    built = build_oracle_quarantine(
        unsettled_decisions=[("u:amb", ("u:c",), None)],
        definite_matches=[("u:m2", "u:m1"), ("u:m1", "u:c")],
        before_ids=frozenset({"u:c", "u:m1", "u:m2"}),
    )
    assert {"u:c", "u:m1", "u:m2"} <= built.ids


def test_oracle_and_production_quarantine_agree_on_the_spent_corpora() -> None:
    """DEVELOPMENT contract parity only. This is NOT the measurement oracle.

    Founder ruling section 6 is explicit: production parity may not be the
    expected side. It is checked here, separately and on spent material, because
    two independent readings of one contract that disagree mean one of them
    misread it -- and finding that out is worth a development test even though
    it can never certify anything.
    """
    from akc_cir.identity_quarantine import build_quarantine

    rows = _spent_pairs("identity-change-migration-closure-v2r2-universe")
    if not rows:
        pytest.skip("the spent V2R2 universe is not present in this checkout")

    compared = 0
    for lineage in ("ecfr:47:20:20.19", "ecfr:7:3560:3560.105", "ecfr:7:3560:3560.102"):
        row = rows.get(lineage)
        if row is None:
            continue
        before_units, after_units, _, _, source = _units(row)
        from akc_cir.identity import LogicalIdentityResolver, assign_one_to_one
        from v2r3_quarantine_oracle import decisions_to_oracle_inputs

        decisions = assign_one_to_one(
            [u.fingerprint(source_lineage=source) for u in after_units],
            [u.fingerprint(source_lineage=source) for u in before_units],
            resolver=LogicalIdentityResolver(),
        )
        before_ids = frozenset(u.logical_id for u in before_units)
        unsettled, definite = decisions_to_oracle_inputs(after_units, decisions, before_ids)

        mine = build_oracle_quarantine(
            unsettled_decisions=unsettled, definite_matches=definite, before_ids=before_ids
        ).ids
        theirs = frozenset(
            build_quarantine(
                unsettled_decisions=unsettled,
                definite_matches=definite,
                before_ids=before_ids,
            ).members
        )
        assert mine == theirs, sorted(mine ^ theirs)[:6]
        assert mine, "an empty quarantine would make this parity check vacuous"
        compared += 1
    assert compared == 3


# ---------------------------------------------------------------------------
# section 7 — the state table
# ---------------------------------------------------------------------------
def test_the_contract_is_total_and_satisfiable() -> None:
    report = table.check_contract()
    assert report["state"] == "SATISFIABLE"
    assert report["reachable_rows"] == 8


def test_every_reachable_row_yields_exactly_one_disposition() -> None:
    seen: dict[tuple[str, str, bool], set[str]] = {}
    for row in table.reachable_rows():
        seen.setdefault((row.side, row.resolver_state, row.quarantined), set()).add(
            row.effective.value
        )
    assert all(len(v) == 1 for v in seen.values()), seen
    assert len(seen) == 8


def test_no_reachable_row_requires_and_forbids_the_same_record() -> None:
    for row in table.reachable_rows():
        assert not (set(row.required) & set(row.forbidden)), row


def test_new_plus_quarantined_is_the_v2r2_contradiction_and_is_gone() -> None:
    row = next(r for r in table.reachable_rows() if r.resolver_state == "NEW" and r.quarantined)
    assert row.effective.value == "EFFECTIVE_UNRESOLVED"
    assert "unit_added" not in row.required
    assert "unit_added" in row.forbidden
    assert "identity_unresolved" in row.required


def test_a_genuine_addition_is_still_required_to_be_definite() -> None:
    """The fix must not be a blanket surrender: over-quarantine is its own
    defect and would destroy the diff's usefulness."""
    row = next(
        r for r in table.reachable_rows() if r.resolver_state == "NEW" and not r.quarantined
    )
    assert row.required == ("unit_added",)
    removal = next(
        r for r in table.reachable_rows() if r.side == "before_unconsumed" and not r.quarantined
    )
    assert removal.required == ("unit_removed",)


def test_the_satisfiability_gate_can_go_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reintroduce V2R2's contradiction and the gate must refuse.

    Without this the gate is a function that has only ever returned SATISFIABLE,
    which is indistinguishable from one that always will.
    """
    broken = dict(table.OBLIGATIONS)
    broken[table.Effective.UNRESOLVED] = {
        "required": (ChangeKind.UNIT_ADDED, table.UNRESOLVED_RECORD),
        "forbidden": (ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED),
    }
    monkeypatch.setattr(table, "OBLIGATIONS", broken)
    with pytest.raises(table.ContractBroken, match="CONTRACT_BROKEN"):
        table.check_contract()


def test_compose_never_produces_a_contradiction() -> None:
    """Satisfiability by construction, asserted rather than assumed."""
    kinds = (ChangeKind.UNIT_ADDED, ChangeKind.UNIT_REMOVED, table.UNRESOLVED_RECORD)
    for a_req in ((), (kinds[0],)):
        for a_forb in ((), kinds):
            for b_req in ((), (kinds[1],)):
                for b_forb in ((), kinds):
                    required, forbidden = table.compose(
                        [
                            (frozenset(a_req), frozenset(a_forb)),
                            (frozenset(b_req), frozenset(b_forb)),
                        ]
                    )
                    assert not (required & forbidden)


# ---------------------------------------------------------------------------
# section 11 — root identity normalisation
# ---------------------------------------------------------------------------
def test_every_historical_source_module_is_readable() -> None:
    report = ri.prior_root_identities()
    assert report["unverifiable_count"] == 0, report["unverifiable"]
    assert all(info["importable"] for info in report["per_module"].values())
    assert report["identity_count"] > 800


def test_all_four_families_are_normalised() -> None:
    report = ri.prior_root_identities()
    assert set(report["by_family"]) == {"ecfr", "git", "sec", "wikipedia"}


def test_every_historical_tuple_shape_normalises() -> None:
    """The dict shape, the five-tuple shape, the three-tuple shape, the bare
    string and the rule mapping -- one reader for all of them, because ad-hoc
    parsing per enumerator is how 7 CFR 273 was missed."""
    assert ri.canonical_identity(
        "git", {"owner": "o", "repo": "r", "prefix": "docs/", "license": "MIT"}
    ) == ("git", "o", "r", "docs")
    assert ri.canonical_identity("git", ("o", "r", "docs", "main", "MIT")) == (
        "git",
        "o",
        "r",
        "docs",
    )
    assert ri.canonical_identity("ecfr", ("7", "273", "subject")) == ("ecfr", "7", "273")
    assert ri.canonical_identity("ecfr", ("07", 273, "subject")) == ("ecfr", "7", "273")
    assert ri.canonical_identity("wikipedia", "Category:Cities") == (
        "wikipedia",
        "Category:Cities",
    )
    assert ri.canonical_identity("sec", {"universe": "u", "start_after_cik": 1, "forms": ["10-K"]})[
        0
    ] == "sec"


def test_an_unreadable_shape_is_unverifiable_never_disjoint() -> None:
    for family, entry in (
        ("git", ("only-one",)),
        ("git", {"repo": "r"}),
        ("ecfr", ("7",)),
        ("wikipedia", ""),
        ("sec", {}),
    ):
        assert ri.canonical_identity(family, entry) == ri.UNVERIFIABLE


def test_the_normaliser_catches_the_root_v2r2_missed() -> None:
    """7 CFR 273: SFI1-spent and a VBC1 declared root, admitted into V2R2's
    frame because the pre-declaration scan matched one tuple shape."""
    prior = ri.prior_root_identities(exclude_modules={"sources_v2r2"})
    assert ("ecfr", "7", "273") in prior["identities"]

    import sources_v2r2

    mine = {ri.canonical_identity("ecfr", e) for e in sources_v2r2.ECFR_ROOTS}
    assert mine & prior["identities"] == {("ecfr", "7", "273")}


# ---------------------------------------------------------------------------
# section 9 — the two spent corpora as DEVELOPMENT regressions
# ---------------------------------------------------------------------------
def _spent_pairs(stem: str) -> dict[str, dict]:
    #: Named directly rather than resolved through a freezer, because the V2R2
    #: adapter overrides the V2R1 freezer's module state process-wide and a test
    #: that went through it would silently read a different study's universe.
    receipts = sorted(glob.glob(str(NS / "receipts" / f"{stem}--*.json")))
    if not receipts:
        return {}
    body = json.loads(Path(receipts[-1]).read_text(encoding="utf-8"))
    return {row["lineage_id"]: row for row in body.get("pairs", ())}


def _units(row: dict):
    before = json.loads((ROOT / row["before"]["canonical_path"]).read_text(encoding="utf-8"))
    after = json.loads((ROOT / row["after"]["canonical_path"]).read_text(encoding="utf-8"))
    before_units, before_shape = engine.snapshots(before)
    after_units, after_shape = engine.snapshots(after)
    return (
        before_units,
        after_units,
        (before, before_shape),
        (after, after_shape),
        after["source_id"],
    )


def _score_spent(row: dict):
    before_units, after_units, (before, before_shape), (after, after_shape), source = _units(row)
    surface = eff.build_effective_surface(before_units, after_units, source)
    diff = diff_documents(
        before_sha256=before["source_digest"],
        after_sha256=after["source_digest"],
        level=DiffLevel.GRAPH,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=source,
    )
    return surface, diff


V2R1_SHAPES = (
    "ecfr:40:273:273.3",
    "git:qdrant/landing_page:qdrant-landing/content/documentation/capacity-planning.md",
    "ecfr:47:54:54.101",
)
V2R2_SHAPES = ("ecfr:47:20:20.19", "ecfr:7:3560:3560.105", "ecfr:7:3560:3560.102")


@pytest.mark.parametrize("lineage_id", V2R1_SHAPES)
def test_v2r1_spent_shapes_are_clean(lineage_id: str) -> None:
    """DEVELOPMENT ONLY. Renamed MATCHED correspondences must be accounted
    through the resolver mapping, not raw-id intersection."""
    rows = _spent_pairs("identity-change-migration-closure-v2r1-universe")
    if lineage_id not in rows:
        pytest.skip("the spent V2R1 universe is not present in this checkout")
    surface, diff = _score_spent(rows[lineage_id])
    violations, observations = inv6.check_effective_accounting(diff, surface)
    assert observations > 0 and violations == []


def test_v2r1_shapes_still_carry_the_renamed_correspondences() -> None:
    """A regression over material that no longer exhibits the defect is hollow."""
    rows = _spent_pairs("identity-change-migration-closure-v2r1-universe")
    if not all(s in rows for s in V2R1_SHAPES):
        pytest.skip("the spent V2R1 universe is not present in this checkout")
    differing = 0
    for lineage_id in V2R1_SHAPES:
        surface, _ = _score_spent(rows[lineage_id])
        differing += sum(1 for b, a in surface.matched_pairs if b != a)
    assert differing == 17


@pytest.mark.parametrize("lineage_id", V2R2_SHAPES)
def test_v2r2_spent_shapes_are_clean(lineage_id: str) -> None:
    """DEVELOPMENT ONLY. The 13 disposition-B units must classify as
    resolver-local NEW plus quarantine override -> EFFECTIVE_UNRESOLVED, and
    production's explicit `identity_unresolved` records must discharge that
    obligation. They do NOT become positive confirmatory evidence."""
    rows = _spent_pairs("identity-change-migration-closure-v2r2-universe")
    if lineage_id not in rows:
        pytest.skip("the spent V2R2 universe is not present in this checkout")
    surface, diff = _score_spent(rows[lineage_id])

    violations, observations = inv6.check_effective_accounting(diff, surface)
    assert observations > 0 and violations == []
    e_violations, _ = inv6.check_quarantine_channel(diff, surface, declared_record=DECLARED)
    assert e_violations == []
    c_violations, _ = inv6.check_unresolved_not_reproduced(
        surface, {b for b, _ in surface.matched_pairs}
    )
    assert c_violations == []


def test_the_13_v2r2_units_are_new_overridden_to_unresolved() -> None:
    """The specific reclassification the founder ruling requires, by count."""
    rows = _spent_pairs("identity-change-migration-closure-v2r2-universe")
    if not all(s in rows for s in V2R2_SHAPES):
        pytest.skip("the spent V2R2 universe is not present in this checkout")
    overridden = 0
    for lineage_id in V2R2_SHAPES:
        surface, _ = _score_spent(rows[lineage_id])
        overridden += sum(
            1
            for u in surface.units
            if u.rule == "B"
            and u.resolver_state == "NEW"
            and u.effective is eff.Effective.UNRESOLVED
        )
    assert overridden == 13
