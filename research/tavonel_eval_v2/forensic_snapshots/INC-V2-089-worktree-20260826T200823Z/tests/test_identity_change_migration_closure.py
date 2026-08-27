"""Every check in the migration closure, proven able to come back RED.

This study's most-repeated defect -- roughly ten instances now, from the import
system through the facet table to the two freeze conditions of INC-V2-044 -- is
a check that reports a clean result because it is watching nothing. INC-V2-036
is the guard whose failure was structurally impossible; INC-V2-044 is the guard
whose success was. Both reported a fixed answer and neither was a measurement.

So every test below injects a violation and asserts the closure notices. A test
that only asserts the closure passes on good input would be the same defect in
test form: it would go green on a closure that had stopped looking.

Nothing here reads a held-out lineage, writes a receipt, or touches
`akc_cir`'s production modules. The two immutable ladder receipts are not opened.
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler", "source_fact_ir"):
    sys.path.insert(0, str(NS / _sub))
sys.path.insert(0, str(NS))
ROOT = NS.parents[1]
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

import change_facets as facets  # noqa: E402
import expected_change_status as oracle  # noqa: E402
import freeze_migration_closure as freezer  # noqa: E402
import identity_change_migration_closure as closure  # noqa: E402
from akc_cir.identity import normalize_text_for_identity  # noqa: E402
from akc_cir.semantic_diff import (  # noqa: E402
    ChangeKind,
    SemanticChange,
    SemanticDiff,
    diff_documents,
)

PROTOCOL = NS / "protocols" / "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1.yaml"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def protocol() -> dict[str, Any]:
    return freezer.load_protocol(PROTOCOL)


def tables() -> tuple[
    dict[str, bool], dict[str, str | None], dict[str, str | None], dict[str, str]
]:
    declared = protocol()["facet_channels"]
    return (
        {facet: bool(declared[facet]["has_production_channel"]) for facet in facets.FACETS},
        {facet: declared[facet]["production_record"] for facet in facets.FACETS},
        {facet: declared[facet]["unresolved_production_record"] for facet in facets.FACETS},
        {facet: declared[facet]["scope"] for facet in facets.FACETS},
    )


@pytest.fixture()
def scratch(request: pytest.FixtureRequest) -> Path:
    """A throwaway directory INSIDE the repository.

    `tmp_path` lands on another drive here, and `common.rel` -- which every
    receipt path goes through -- is repository-relative by design and raises on
    a path outside it. Writing the fixture modules under the repo keeps the test
    exercising the real code path rather than a loosened one.
    """
    import shutil

    target = NS / "artifacts" / "development" / "_scratch_migration_closure" / request.node.name
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    return target


def document(
    source_id: str = "fixture",
    digest: str = "sha256:aaa",
    units: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A canonical document in the shape `selective_build.snapshots` reads."""
    return {
        "source_id": source_id,
        "source_digest": digest,
        "units": units
        or [
            {
                "heading": "Records",
                "explicit_path": ["Chapter", "Records"],
                "text": "The permit holder shall retain records for three years.",
            },
            {
                "heading": "Scope",
                "explicit_path": ["Chapter", "Scope"],
                "text": "This section applies to every licensed facility.",
            },
        ],
    }


def run_pair(before: dict[str, Any], after: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    channels, records, unresolved_records, scopes = tables()
    return closure.measure_pair(
        before,
        after,
        channels=channels,
        records=records,
        unresolved_records=unresolved_records,
        scopes=scopes,
        ignored=frozenset(),
        **kwargs,
    )


def doctoring_diff(transform: Any) -> Any:
    """Wrap `diff_documents` so a test can edit the change set it returns."""

    def _diff(**kwargs: Any) -> SemanticDiff:
        real = diff_documents(**kwargs)
        return replace(real, changes=tuple(transform(real, kwargs)))

    return _diff


def flat(violations: dict[str, list[Any]]) -> list[Any]:
    return [row for rows in violations.values() for row in rows]


# --------------------------------------------------------------------------
# the fixture battery holds, and is wired to the frozen declaration
# --------------------------------------------------------------------------


def test_fixture_battery_holds_and_does_not_drift() -> None:
    report = closure.run_fixture_battery(protocol()["fixture_battery"]["classes"])
    assert report["drift"] == {
        "declared_without_a_builder": [],
        "built_without_a_declaration": [],
    }
    assert report["failed"] == []
    assert report["held"] is True


def test_fixture_battery_goes_red_when_a_declared_fixture_has_no_builder() -> None:
    declared = dict(protocol()["fixture_battery"]["classes"])
    declared["a_fixture_nobody_wrote"] = {"invariant": "INVARIANT_4"}
    report = closure.run_fixture_battery(declared)
    assert report["drift"]["declared_without_a_builder"] == ["a_fixture_nobody_wrote"]
    assert report["held"] is False


# --------------------------------------------------------------------------
# INVARIANT_2 -- the identity fold must stay identity-only
# --------------------------------------------------------------------------


PRODUCTION_FOLD_CASES = [
    ("Apache", "Apache®"),
    ("Github", "GitHub"),
    ("( e.g.", "(e.g."),
    ("a-b", "a—b"),
    ("§§ 262.14,", "§ 262.14,"),
]


@pytest.mark.parametrize(("before", "after"), PRODUCTION_FOLD_CASES)
def test_the_fold_still_folds_the_inc_v2_037_shapes(before: str, after: str) -> None:
    """The repair explicitly ruled out is making this fold content-sensitive."""
    assert before != after
    assert normalize_text_for_identity(before) == normalize_text_for_identity(after)


def test_fold_check_is_green_on_real_shaped_text() -> None:
    report = closure.measure_identity_fold(
        [case[0] for case in PRODUCTION_FOLD_CASES],
        classes=tuple(closure.FOLD_CLASSES),
    )
    assert report["violations"] == []
    assert report["lossiness_witnesses"] > 0


def test_fold_check_goes_red_when_the_fold_becomes_content_sensitive() -> None:
    """The one repair the ruling forbids: comparing raw text for identity."""
    report = closure.measure_identity_fold(
        ["Apache Druid ingestion spec"],
        classes=tuple(closure.FOLD_CLASSES),
        fold=lambda text: text,
    )
    assert report["violations"], "a raw-text fold must break every declared class"
    assert {row["class"] for row in report["violations"]} == set(closure.FOLD_CLASSES)


def test_fold_check_goes_red_when_only_the_punctuation_stage_is_dropped() -> None:
    report = closure.measure_identity_fold(
        ["Apache Druid ingestion spec"],
        classes=("punctuation_to_space",),
        fold=lambda text: text.casefold(),
    )
    assert [row["class"] for row in report["violations"]] == ["punctuation_to_space"]


def test_fold_invariant_is_unproven_without_a_lossiness_witness() -> None:
    """A fold that is never shown to be lossy has not been shown to be a fold."""
    graded = closure.grade(
        pairs=[_synthetic_pair_result()],
        fold={"observations": 4, "lossiness_witnesses": 0, "per_class": {}, "violations": []},
        independence={
            "modules_inspected": ["x"],
            "signature": "()",
            "observations": 1,
            "violations": [],
        },
        mapping={"combinations_evaluated": 72, "observations": 74, "violations": []},
        fixtures={
            "declared": [],
            "drift": {
                "declared_without_a_builder": [],
                "built_without_a_declaration": [],
            },
            "results": {},
            "failed": [],
            "held": True,
        },
        disjointness={"violations": []},
    )
    assert (
        graded["invariants"]["INVARIANT_2_identity_fold_remains_identity_only"]["verdict"]
        == closure.VIOLATED
    )


# --------------------------------------------------------------------------
# INVARIANT_3 -- the expectation oracle is independent
# --------------------------------------------------------------------------


FORBIDDEN_IMPORTS = ("akc_cir.semantic_diff", "akc_cir.identity", "akc_cir")
FORBIDDEN_ATTRS = ("identity_text", "normalize_text_for_identity", "MODIFIED_CLAIM")


def test_oracle_is_independent_today() -> None:
    report = closure.audit_oracle_independence(
        forbidden_imports=FORBIDDEN_IMPORTS, forbidden_attributes=FORBIDDEN_ATTRS
    )
    assert report["violations"] == []
    assert any("expected_change_status.py" in name for name in report["modules_inspected"])
    assert any("change_facets.py" in name for name in report["modules_inspected"])


def test_oracle_audit_goes_red_on_an_aliased_forbidden_import(scratch: Path) -> None:
    """A grep would pass on this. The AST walk resolves the alias."""
    variant = scratch / "leaky_oracle.py"
    variant.write_text(
        "from akc_cir import semantic_diff as sd\n"
        "\n"
        "def facet_obligations(before, after, *, channels, ignored):\n"
        "    return sd\n",
        encoding="utf-8",
    )
    report = closure.audit_oracle_independence(
        entry=variant,
        forbidden_imports=FORBIDDEN_IMPORTS,
        forbidden_attributes=FORBIDDEN_ATTRS,
    )
    assert any(row["kind"] == "import_from" for row in report["violations"])


def test_oracle_audit_goes_red_on_a_forbidden_attribute_read(scratch: Path) -> None:
    variant = scratch / "peeking_oracle.py"
    variant.write_text(
        "def facet_obligations(before, after, *, channels, ignored):\n"
        "    return before.identity_text == after.identity_text\n",
        encoding="utf-8",
    )
    report = closure.audit_oracle_independence(
        entry=variant,
        forbidden_imports=FORBIDDEN_IMPORTS,
        forbidden_attributes=FORBIDDEN_ATTRS,
    )
    assert any(row["kind"] == "attribute" for row in report["violations"])


def test_oracle_audit_goes_red_on_a_signature_leak(scratch: Path) -> None:
    """A parameter through which production's answer could enter."""
    variant = scratch / "leaky_signature.py"
    variant.write_text(
        "def facet_obligations(before, after, *, channels, ignored, production_diff=None):\n"
        "    return {}\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(scratch))
    try:
        import leaky_signature  # type: ignore[import-not-found]

        report = closure.audit_oracle_independence(
            entry=variant,
            forbidden_imports=FORBIDDEN_IMPORTS,
            forbidden_attributes=FORBIDDEN_ATTRS,
            module=leaky_signature,
        )
    finally:
        sys.path.remove(str(scratch))
        sys.modules.pop("leaky_signature", None)
    assert any(row["kind"] == "signature" for row in report["violations"])


# --------------------------------------------------------------------------
# INVARIANT_5 (a)-(c) -- the oracle's mapping over its whole input domain
# --------------------------------------------------------------------------


def test_obligation_mapping_is_total_and_never_lenient() -> None:
    report = closure.audit_obligation_mapping()
    assert report["combinations_evaluated"] == len(facets.FACETS) * len(facets.VERDICTS) * 2
    assert report["violations"] == []


def test_mapping_goes_red_when_unresolved_becomes_no_obligation() -> None:
    """The hard rule: `unresolved` may never become `unchanged`."""

    def lenient(facet: str, verdict: str, *, has_production_channel: bool) -> str:
        if verdict == facets.UNRESOLVED:
            return oracle.NO_OBLIGATION
        return oracle.obligation_for(
            facet, verdict, has_production_channel=has_production_channel
        )

    report = closure.audit_obligation_mapping(obligation_for=lenient)
    assert report["violations"]
    assert all(
        row.get("verdict") == facets.UNRESOLVED
        for row in report["violations"]
        if "verdict" in row
    )


def test_mapping_goes_red_when_an_unknown_verdict_is_defaulted() -> None:
    def defaulting(facet: str, verdict: str, *, has_production_channel: bool) -> str:
        if verdict not in facets.VERDICTS or facet not in facets.FACETS:
            return oracle.NO_OBLIGATION
        return oracle.obligation_for(
            facet, verdict, has_production_channel=has_production_channel
        )

    report = closure.audit_obligation_mapping(obligation_for=defaulting)
    assert any("instead of raising" in row["why"] for row in report["violations"])


def test_mapping_goes_red_when_the_permissive_set_is_widened() -> None:
    report = closure.audit_obligation_mapping(
        permissive=oracle.OBLIGATIONS_SATISFIED_BY_SILENCE | {oracle.REQUIRE_FAIL_CLOSED}
    )
    assert any("dischargeable by silence" in row["why"] for row in report["violations"])


def test_oracle_refuses_an_unknown_facet_and_an_unknown_verdict() -> None:
    with pytest.raises(oracle.ContractBroken):
        oracle.obligation_for("NOT_A_FACET", facets.CHANGED, has_production_channel=True)
    with pytest.raises(oracle.ContractBroken):
        oracle.obligation_for(facets.CONTENT, "not_a_verdict", has_production_channel=True)


def test_oracle_refuses_an_incomplete_channel_declaration() -> None:
    before, after = _units_for("alpha", "beta")
    with pytest.raises(oracle.ContractBroken):
        oracle.facet_obligations(before, after, channels={facets.CONTENT: True})


# --------------------------------------------------------------------------
# INVARIANT_1, 4, 5(d), 6, 7 -- over a real pair, with injected violations
# --------------------------------------------------------------------------


def _units_for(before_text: str, after_text: str) -> tuple[Any, Any]:
    import selective_build as engine

    before, _ = engine.snapshots(
        document(units=[{"heading": "H", "explicit_path": ["H"], "text": before_text}])
    )
    after, _ = engine.snapshots(
        document(units=[{"heading": "H", "explicit_path": ["H"], "text": after_text}])
    )
    return before[0], after[0]


def _synthetic_pair_result() -> dict[str, Any]:
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    after["units"][0]["text"] = "The permit holder shall retain records for four years."
    return run_pair(before, after)


def test_a_clean_pair_reports_no_violations() -> None:
    result = _synthetic_pair_result()
    assert flat(result["violations"]) == []
    assert result["matched_pair_count"] == 2
    assert result["changed_facet_observations"] > 0
    assert result["unresolved_facet_observations"] > 0


def test_goes_red_when_a_modified_claim_is_removed() -> None:
    """INVARIANT_4 and INVARIANT_5(d): a CONTENT change that produced nothing."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    after["units"][0]["text"] = "The permit holder shall retain records for four years."
    result = run_pair(
        before,
        after,
        diff_fn=doctoring_diff(
            lambda diff, _kw: [
                change for change in diff.changes if change.kind is not ChangeKind.MODIFIED_CLAIM
            ]
        ),
    )
    assert result["violations"]["INVARIANT_4"], "a changed CONTENT facet produced no record"
    assert result["violations"]["INVARIANT_5"], "CONTENT did not fail closed"


def test_goes_red_when_the_locator_record_is_removed() -> None:
    """INVARIANT_4 on a channel other than CONTENT."""
    text = "The permit holder shall retain records for three years."
    before = document(
        units=[{"heading": "H", "explicit_path": ["H"], "text": text, "evidence_id": "e:1"}]
    )
    after = document(
        digest="sha256:bbb",
        units=[{"heading": "H", "explicit_path": ["H"], "text": text, "evidence_id": "e:2"}],
    )
    clean = run_pair(before, after)
    # Asserted so the red case below cannot pass vacuously: a pair the resolver
    # did not match produces no facet observations at all, and an empty
    # violation list would then mean "nothing was looked at" rather than "nothing
    # was wrong". That is the defect this whole battery exists to prevent.
    assert clean["matched_pair_count"] == 1
    assert clean["changed_facet_observations"] >= 1
    assert clean["violations"]["INVARIANT_4"] == []

    result = run_pair(
        before,
        after,
        diff_fn=doctoring_diff(
            lambda diff, _kw: [
                change for change in diff.changes if change.kind is not ChangeKind.EVIDENCE_MOVED
            ]
        ),
    )
    assert [row["facet"] for row in result["violations"]["INVARIANT_4"]] == [
        facets.REFERENCE_LOCATOR
    ]


def test_goes_red_when_an_unsettled_identity_also_asserts_continuity() -> None:
    """INVARIANT_6(a). Ambiguity must not be forced into continuity."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"

    def forced(diff: SemanticDiff, kwargs: dict[str, Any]) -> list[SemanticChange]:
        victim = kwargs["after_units"][0].logical_id
        return [
            SemanticChange(
                kind=ChangeKind.IDENTITY_UNRESOLVED,
                logical_id=victim,
                detail="two candidates scored alike",
                candidates=(victim,),
            ),
            SemanticChange(kind=ChangeKind.MODIFIED_CLAIM, logical_id=victim, after="x"),
        ]

    result = run_pair(before, after, diff_fn=doctoring_diff(forced))
    assert any(
        "continuity assertion" in row["why"] for row in result["violations"]["INVARIANT_6"]
    )


def test_goes_red_when_a_candidate_of_an_unsettled_identity_is_reported_removed() -> None:
    """INVARIANT_6(b). A deletion the resolver explicitly declined to make."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"

    def forced(diff: SemanticDiff, kwargs: dict[str, Any]) -> list[SemanticChange]:
        incoming = kwargs["after_units"][0].logical_id
        candidate = kwargs["before_units"][1].logical_id
        return [
            SemanticChange(
                kind=ChangeKind.IDENTITY_UNRESOLVED,
                logical_id=incoming,
                detail="review band",
                candidates=(candidate,),
            ),
            SemanticChange(kind=ChangeKind.UNIT_REMOVED, logical_id=candidate),
        ]

    result = run_pair(before, after, diff_fn=doctoring_diff(forced))
    assert any(
        "reported removed" in row["why"] for row in result["violations"]["INVARIANT_6"]
    )


def test_goes_red_when_identity_records_move_with_the_predicate() -> None:
    """INVARIANT_1(a). The regression the whole ladder exists for."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    after["units"][0]["text"] = "The permit holder shall retain records for four years."

    def predicate_sensitive(diff: SemanticDiff, kwargs: dict[str, Any]) -> list[SemanticChange]:
        changes = list(diff.changes)
        if kwargs["legacy_identity_change_predicate"]:
            changes.append(
                SemanticChange(kind=ChangeKind.UNIT_REMOVED, logical_id="u:ghost")
            )
        return changes

    result = run_pair(before, after, diff_fn=doctoring_diff(predicate_sensitive))
    assert any(
        "moved with the predicate" in row["why"] for row in result["violations"]["INVARIANT_1"]
    )


def test_goes_red_when_a_predicate_names_a_claim_the_resolver_did_not_match() -> None:
    """INVARIANT_1(c). Neither predicate may create a match."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    result = run_pair(
        before,
        after,
        diff_fn=doctoring_diff(
            lambda diff, _kw: [
                *diff.changes,
                SemanticChange(kind=ChangeKind.MODIFIED_CLAIM, logical_id="u:never-matched"),
            ]
        ),
    )
    assert any(
        "did not match" in row["why"] for row in result["violations"]["INVARIANT_1"]
    )


def test_goes_red_on_an_ignore_the_frozen_declaration_does_not_name() -> None:
    """INVARIANT_7. An ignore is a declaration, never an inference."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    channels, records, unresolved_records, scopes = tables()

    def sneaky(
        before_unit: Any,
        after_unit: Any,
        *,
        channels: dict[str, bool],
        ignored: frozenset[str],
    ) -> dict[str, dict[str, str]]:
        resolved = oracle.facet_obligations(
            before_unit, after_unit, channels=channels, ignored=ignored
        )
        resolved[facets.TEMPORAL] = {
            "verdict": facets.IGNORED_BY_PREDECLARED_POLICY,
            "obligation": oracle.IGNORED_BY_PREDECLARED_POLICY,
        }
        return resolved

    result = closure.measure_pair(
        before,
        after,
        channels=channels,
        records=records,
        unresolved_records=unresolved_records,
        scopes=scopes,
        ignored=frozenset(),
        obligations=sneaky,
    )
    assert any(
        row["facet"] == facets.TEMPORAL for row in result["violations"]["INVARIANT_7"]
    )


def test_goes_red_when_a_changed_facet_is_treated_as_change_equivalent() -> None:
    """INVARIANT_7. With an empty declaration, nothing may be change-equivalent."""
    before = document()
    after = copy.deepcopy(before)
    after["source_digest"] = "sha256:bbb"
    after["units"][0]["text"] = "The permit holder shall retain records for four years."
    channels, records, unresolved_records, scopes = tables()

    def waving_through(
        before_unit: Any,
        after_unit: Any,
        *,
        channels: dict[str, bool],
        ignored: frozenset[str],
    ) -> dict[str, dict[str, str]]:
        resolved = oracle.facet_obligations(
            before_unit, after_unit, channels=channels, ignored=ignored
        )
        for row in resolved.values():
            if row["verdict"] == facets.CHANGED:
                row["obligation"] = oracle.NO_OBLIGATION
        return resolved

    result = closure.measure_pair(
        before,
        after,
        channels=channels,
        records=records,
        unresolved_records=unresolved_records,
        scopes=scopes,
        ignored=frozenset(),
        obligations=waving_through,
    )
    assert result["change_equivalent_observations"] > 0
    assert result["violations"]["INVARIANT_7"]


# --------------------------------------------------------------------------
# grading -- vacuity, UNPROVEN, and disjointness
# --------------------------------------------------------------------------


def _clean_grade_inputs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pairs": pairs,
        "fold": {
            "observations": 12,
            "lossiness_witnesses": 12,
            "per_class": {},
            "violations": [],
        },
        "independence": {
            "modules_inspected": ["x"],
            "signature": "()",
            "observations": 1,
            "violations": [],
        },
        "mapping": {"combinations_evaluated": 72, "observations": 74, "violations": []},
        "fixtures": {
            "declared": [],
            "drift": {"declared_without_a_builder": [], "built_without_a_declaration": []},
            "results": {
                "ambiguous_identity_stays_unresolved": {
                    "identity_unresolved_records": 1
                }
            },
            "failed": [],
            "held": True,
        },
        "disjointness": {"violations": []},
    }


def test_a_closure_over_zero_pairs_fails_as_vacuous() -> None:
    """The purest form of a check that is watching nothing."""
    graded = closure.grade(**_clean_grade_inputs([]))
    assert graded["overall"] == "VACUOUS_FAIL"
    assert graded["pairs_resolved"] == 0


def test_a_clean_grade_passes_so_the_vacuity_test_means_something() -> None:
    graded = closure.grade(**_clean_grade_inputs([_synthetic_pair_result()]))
    assert graded["overall"] == "PASS"


def test_an_unproven_invariant_can_never_contribute_to_a_pass() -> None:
    inputs = _clean_grade_inputs([_synthetic_pair_result()])
    inputs["fixtures"]["results"] = {}
    for pair in inputs["pairs"]:
        pair["ambiguity_observations"] = 0
    graded = closure.grade(**inputs)
    invariant = graded["invariants"]["INVARIANT_6_ambiguous_identity_stays_unresolved"]
    assert invariant["verdict"] == closure.UNPROVEN
    assert invariant["cohort_gate_power"] == "none"
    assert graded["overall"] == "UNPROVEN"


def test_grade_goes_red_when_disjointness_does_not_hold() -> None:
    """INVARIANT_8. The 14 forensic cases cannot certify their own repair."""
    inputs = _clean_grade_inputs([_synthetic_pair_result()])
    inputs["disjointness"] = {
        "violations": [
            {"why": "from_the_14_sfi2_forensic_cases does not hold", "overlap": ["x"]}
        ]
    }
    graded = closure.grade(**inputs)
    assert (
        graded["invariants"]["INVARIANT_8_sfi2_cases_cannot_certify"]["verdict"]
        == closure.VIOLATED
    )
    assert graded["overall"] == "FAIL"


# --------------------------------------------------------------------------
# INVARIANT_8 at the source: the universe builder excludes the spent cohort
# --------------------------------------------------------------------------


def _one_real_row() -> dict[str, Any]:
    body = json.loads(
        (NS / "artifacts" / "development" / "p4i_cohort.json").read_text(encoding="utf-8")
    )
    return body["documents"][0]


def test_universe_builder_drops_a_confirmed_defect_lineage(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    confirmed, _ = freezer.confirmed_defect_lineages()
    keeper = _one_real_row()
    planted = copy.deepcopy(keeper)
    planted["document_id"] = sorted(confirmed)[0]
    planted["document_slug"] = keeper["document_slug"] + "-planted"

    manifest = scratch / "manifest.json"
    manifest.write_text(
        json.dumps({"documents": [keeper, planted]}), encoding="utf-8"
    )
    monkeypatch.setattr(freezer, "candidate_manifests", lambda _p: [manifest])

    universe = freezer.build_universe(freezer.load_protocol(PROTOCOL))
    assert universe["pair_count"] == 1
    assert universe["disjointness"]["lineages_removed_by_disjointness"] == [
        sorted(confirmed)[0]
    ]
    assert universe["disjointness"]["from_the_14_sfi2_forensic_cases"]["overlap"] == []


def test_universe_builder_refuses_an_empty_universe(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A closure needs pairs. An empty universe is refused, never frozen."""
    confirmed, _ = freezer.confirmed_defect_lineages()
    planted = copy.deepcopy(_one_real_row())
    planted["document_id"] = sorted(confirmed)[0]
    manifest = scratch / "manifest.json"
    manifest.write_text(json.dumps({"documents": [planted]}), encoding="utf-8")
    monkeypatch.setattr(freezer, "candidate_manifests", lambda _p: [manifest])

    with pytest.raises(freezer.FreezeRefused, match="empty"):
        freezer.build_universe(freezer.load_protocol(PROTOCOL))


def test_universe_builder_excludes_a_payload_that_changed_since_acquisition(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pair whose cached bytes no longer match its manifest is not measurable."""
    keeper = _one_real_row()
    tampered = copy.deepcopy(_one_real_row())
    tampered["document_id"] = keeper["document_id"] + "#tampered"
    tampered["document_slug"] = keeper["document_slug"] + "-tampered"
    tampered["before"] = dict(tampered["before"], raw_sha256="sha256:" + "0" * 64)
    manifest = scratch / "manifest.json"
    manifest.write_text(json.dumps({"documents": [keeper, tampered]}), encoding="utf-8")
    monkeypatch.setattr(freezer, "candidate_manifests", lambda _p: [manifest])

    universe = freezer.build_universe(freezer.load_protocol(PROTOCOL))
    assert universe["pair_count"] == 1
    excluded = universe["excluded_as_unverifiable"]
    assert excluded["count"] == 1
    assert excluded["rows"][0]["lineage_id"] == tampered["document_id"]
    assert "changed since acquisition" in excluded["rows"][0]["reason"]


def test_universe_builder_excludes_both_sides_of_a_slug_collision(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One overwrote the other's payload and nothing says which is which."""
    first = _one_real_row()
    second = copy.deepcopy(first)
    second["document_id"] = first["document_id"] + "#collides"
    manifest = scratch / "manifest.json"
    manifest.write_text(json.dumps({"documents": [first, second]}), encoding="utf-8")
    monkeypatch.setattr(freezer, "candidate_manifests", lambda _p: [manifest])

    with pytest.raises(freezer.FreezeRefused, match="empty"):
        freezer.build_universe(freezer.load_protocol(PROTOCOL))


# --------------------------------------------------------------------------
# ordering -- the INC-V2-042 rule, as a refusal
# --------------------------------------------------------------------------


def test_the_closure_refuses_an_unfrozen_protocol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freezer, "protocol_freeze_receipt", lambda stem=None: None)
    with pytest.raises(freezer.FreezeRefused, match="has not been frozen"):
        freezer.require_frozen_protocol(PROTOCOL)


def test_the_closure_refuses_a_protocol_edited_after_its_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        freezer,
        "protocol_freeze_receipt",
        lambda stem=None: {"protocol_sha256": "sha256:" + "0" * 64, "_receipt_path": "x"},
    )
    with pytest.raises(freezer.FreezeRefused, match="changed since it was frozen"):
        freezer.require_frozen_protocol(PROTOCOL)


def test_the_closure_refuses_without_a_frozen_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(closure, "runs_of", lambda stem: [])
    with pytest.raises(closure.ClosureRefused, match="has not been frozen"):
        closure.universe_receipt()


# --------------------------------------------------------------------------
# the reference path stays reachable
# --------------------------------------------------------------------------


def test_the_legacy_predicate_is_preserved() -> None:
    """The founder's ruling: keep the pinned pre-INC-V2-037 reference path."""
    import inspect as _inspect

    parameters = _inspect.signature(diff_documents).parameters
    assert "legacy_identity_change_predicate" in parameters
    assert parameters["legacy_identity_change_predicate"].default is False


def test_the_two_ladder_receipts_are_present_and_unedited() -> None:
    """Reclassified by a new artifact, never by editing these."""
    for name in (
        "identity-change-benchmark--20260824T092056Z-eb6269afcbd0.json",
        "identity-change-canary--20260824T092141Z-36fa48664af6.json",
    ):
        path = NS / "receipts" / name
        assert path.is_file(), f"an immutable ladder receipt is missing: {name}"
        body = json.loads(path.read_text(encoding="utf-8"))
        assert body["provenance"]["immutable"] is True
