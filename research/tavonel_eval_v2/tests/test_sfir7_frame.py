"""Red controls for SFIR7's externally-defined frame rule.

Every test here is written against a mutation that would make it fail. The
mutation table is in the lane report; the short version is that none of these
assertions is satisfiable by an empty implementation. A guard whose failure is
impossible is not a guard, and this programme has paid for that defect class six
times (the INC-V2-036 family).

Interpreter of record: D:\\CodexProjects\\ai-knowledge-compiler\\.venv\\Scripts\\python.exe
"""

from __future__ import annotations

import random
import sys
from dataclasses import replace
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_frame as frame  # noqa: E402

CATALOG = "EXTERNAL_CATALOG_UNDER_TEST"
DIGEST = "sha256:" + "a" * 64
SNAPSHOT_DATE = "2026-08-27"


def _record(index: int, **overrides) -> frame.FrameCatalogRecord:
    base = {
        "record_id": f"cat-{index:05d}",
        "host": "github",
        "namespace": f"org{index}",
        "name": f"repo{index}",
        "primary_language": "Python",
        "spdx_license_id": "Apache-2.0",
        "created_utc": "2015-01-01",
        "last_activity_utc": "2026-06-01",
        "catalog_rank_value": 10_000 - index,
    }
    base.update(overrides)
    return frame.FrameCatalogRecord(**base)


def _snapshot(records) -> frame.CatalogSnapshot:
    return frame.CatalogSnapshot(
        catalog_id=CATALOG,
        snapshot_uri="file://catalogue-snapshot-under-test",
        snapshot_sha256=DIGEST,
        snapshot_date_utc=SNAPSHOT_DATE,
        records=tuple(records),
    )


def _rule() -> frame.FrameRule:
    return frame.declared_rule(
        catalog_id=CATALOG, snapshot_sha256=DIGEST, snapshot_date_utc=SNAPSHOT_DATE
    )


# --------------------------------------------------------------------------
# 1. A rule tuned to a target count is refused
# --------------------------------------------------------------------------


def test_a_hand_set_n_is_refused():
    """The forbidden act, stated as code: N moved to whatever clears the bar."""
    tuned = replace(_rule(), n=_rule().n + 1)
    with pytest.raises(frame.SFIR7Refused, match="hand-set N"):
        frame.refuse_count_tuned_rule(tuned)


def test_the_declared_n_is_exactly_the_derivation_over_live_modules():
    rule = _rule()
    assert rule.n == frame.derive_n(
        wall_clock_hours=frame.inherited_wall_clock_hours(),
        published_rate_limit_per_hour=frame.PUBLISHED_GITHUB_AUTHENTICATED_RATE_LIMIT_PER_HOUR,
        per_root_request_bound=frame.inherited_per_root_request_bound(),
        inherited_total_request_cap=frame.inherited_total_request_cap(),
    )
    assert frame.refuse_count_tuned_rule(rule) == rule.n


def test_n_takes_the_stronger_of_the_two_operational_bounds():
    """The founder ruling, as arithmetic rather than as prose.

    The wall clock alone allows 6 x 5000 = 30,000 requests; the inherited cap
    allows 12,000. The cap is the binding constraint, so N is 12,000 / 240 = 50
    and not 125. The direction matters as much as the number: resolving the
    conflict by TIGHTENING cannot be suspected of having been chosen to reach a
    capacity figure, whereas raising the cap to 30,000 after a shortfall could
    only ever have been.
    """
    common = {
        "published_rate_limit_per_hour": 5000,
        "per_root_request_bound": 240,
    }
    assert frame.derive_n(wall_clock_hours=6, inherited_total_request_cap=12_000, **common) == 50
    # the cap binds, so more wall clock buys nothing
    assert frame.derive_n(wall_clock_hours=99, inherited_total_request_cap=12_000, **common) == 50
    # and when the wall clock is the tighter one, it binds instead
    assert frame.derive_n(wall_clock_hours=1, inherited_total_request_cap=12_000, **common) == 20


def test_removing_the_cap_from_the_derivation_would_raise_n_and_is_refused():
    """The mutation this control exists for: drop the `min` and N returns to 125.

    Stated as a test rather than a comment, because the whole argument for N=50
    is that the second bound is applied. A successor that quietly derives from
    the wall clock alone gets a roster 2.5x larger and a transport that cannot
    finish it.
    """
    without_cap = (6 * 5000) // 240
    with_cap = frame.derive_n(
        wall_clock_hours=6,
        published_rate_limit_per_hour=5000,
        per_root_request_bound=240,
        inherited_total_request_cap=12_000,
    )
    assert without_cap == 125
    assert with_cap == 50
    assert with_cap < without_cap, "the resolution must lower N, never raise it"

    from dataclasses import replace as _replace

    inflated = _replace(_rule(), n=without_cap)
    with pytest.raises(frame.SFIR7Refused, match="hand-set N"):
        frame.refuse_count_tuned_rule(inflated)


def test_an_input_that_drifted_from_the_inherited_bound_is_refused():
    """Leaving N's formula alone and moving its inputs is the same act, slower."""
    rule = _rule()
    drifted = replace(rule, n_inputs={**dict(rule.n_inputs), "wall_clock_hours": 48})
    with pytest.raises(frame.SFIR7Refused, match="not the inherited bounds"):
        frame.refuse_count_tuned_rule(drifted)


def test_a_justification_naming_a_capacity_term_is_refused():
    rule = replace(_rule(), n_justification="N is set so the frame reaches the required capacity")
    with pytest.raises(frame.SFIR7Refused, match="capacity term"):
        frame.refuse_count_tuned_rule(rule)


@pytest.mark.parametrize("numeral", frame.FORBIDDEN_NUMERALS)
def test_a_justification_citing_the_criterion_numbers_is_refused(numeral):
    rule = replace(_rule(), n_justification=f"chosen so the count comfortably exceeds {numeral}")
    with pytest.raises(frame.SFIR7Refused, match="a figure from the capacity"):
        frame.refuse_count_tuned_rule(rule)


def test_a_numeral_that_merely_contains_a_forbidden_one_is_not_refused():
    """The guard must catch 750 and not 7500. A guard that fires on everything
    teaches the study to stop reading it."""
    rule = replace(
        _rule(),
        n_justification="the vendor's published limit is 7500 requests per operational hour",
    )
    assert frame.refuse_count_tuned_rule(rule) == rule.n


def test_chosen_is_not_a_derivation():
    rule = replace(_rule(), n_derivation="chosen_by_the_implementer")
    with pytest.raises(frame.SFIR7Refused, match="not in the closed set"):
        frame.refuse_count_tuned_rule(rule)


def test_select_top_n_runs_the_tuning_gate_rather_than_trusting_the_rule():
    """The gate has to sit on the path that actually produces a frame. A checker
    nobody calls is INC-V2-104's defect, and it is cheap to reintroduce."""
    tuned = replace(_rule(), n=999)
    with pytest.raises(frame.SFIR7Refused, match="hand-set N"):
        frame.select_top_n(_snapshot([_record(i) for i in range(5)]), tuned)


# --------------------------------------------------------------------------
# 2. Selection is deterministic given a snapshot
# --------------------------------------------------------------------------


def test_selection_is_identical_under_a_shuffled_input_order():
    records = [_record(i) for i in range(400)]
    rule = _rule()
    straight = frame.select_top_n(_snapshot(records), rule)
    for seed in (1, 2, 3, 17, 99):
        shuffled = list(records)
        random.Random(seed).shuffle(shuffled)  # noqa: S311 -- a fixture shuffle, not a cryptographic use
        other = frame.select_top_n(_snapshot(shuffled), rule)
        assert frame.frame_fingerprint(other) == frame.frame_fingerprint(straight)
        assert [r.record_id for r in other.selected] == [r.record_id for r in straight.selected]


def test_selection_is_identical_on_repeat():
    records = [_record(i) for i in range(200)]
    rule = _rule()
    first = frame.select_top_n(_snapshot(records), rule)
    second = frame.select_top_n(_snapshot(records), rule)
    assert frame.frame_fingerprint(first) == frame.frame_fingerprint(second)


def test_the_fingerprint_actually_depends_on_what_was_selected():
    """A digest over a constant would satisfy the two tests above and prove
    nothing. This one moves one record's rank and requires the digest to move."""
    records = [_record(i) for i in range(200)]
    rule = _rule()
    before = frame.frame_fingerprint(frame.select_top_n(_snapshot(records), rule))
    records[199] = replace(records[199], catalog_rank_value=99_999)
    after = frame.frame_fingerprint(frame.select_top_n(_snapshot(records), rule))
    assert before != after


def test_the_top_n_is_the_highest_ranked_and_the_cut_is_at_n():
    rule = _rule()
    records = [_record(i) for i in range(rule.n + 50)]
    selection = frame.select_top_n(_snapshot(records), rule)
    assert len(selection.selected) == rule.n
    ranks = [r.catalog_rank_value for r in selection.selected]
    assert ranks == sorted(ranks, reverse=True)
    chosen = {s.record_id for s in selection.selected}
    assert min(ranks) > max(
        r.catalog_rank_value for r in records if r.record_id not in chosen
    )


def test_a_short_pool_is_reported_and_not_repaired():
    rule = _rule()
    selection = frame.select_top_n(_snapshot([_record(i) for i in range(9)]), rule)
    assert frame.selection_is_short(selection) is True
    assert selection.eligible_count == 9
    assert len(selection.selected) == 9
    assert selection.n == rule.n


# --------------------------------------------------------------------------
# 3. The snapshot digest is bound
# --------------------------------------------------------------------------


def test_a_flipped_byte_is_refused():
    payload = b"catalogue,record\n1,alpha\n"
    declared = frame.digest_bytes(payload)
    assert frame.bind_snapshot_bytes(payload, declared) == declared
    with pytest.raises(frame.SFIR7Refused, match="digest does not match"):
        frame.bind_snapshot_bytes(payload + b" ", declared)


def test_a_bare_hex_declaration_is_accepted_and_still_compared():
    payload = b"catalogue,record\n1,alpha\n"
    bare = frame.digest_bytes(payload).removeprefix("sha256:")
    assert frame.bind_snapshot_bytes(payload, bare) == frame.digest_bytes(payload)
    with pytest.raises(frame.SFIR7Refused):
        frame.bind_snapshot_bytes(b"different", bare)


def test_a_rule_bound_to_another_snapshot_cannot_select():
    other = replace(_rule(), snapshot_sha256="sha256:" + "b" * 64)
    with pytest.raises(frame.SFIR7Refused, match="bound by digest"):
        frame.select_top_n(_snapshot([_record(0)]), other)


def test_a_rule_written_for_another_catalogue_cannot_select():
    other = replace(_rule(), catalog_id="SOME_OTHER_CATALOG")
    with pytest.raises(frame.SFIR7Refused, match="written for catalogue"):
        frame.select_top_n(_snapshot([_record(0)]), other)


def test_eol_is_counted_from_bytes_not_guessed():
    """INC-V2-105: a shell grep has already given a wrong answer here."""
    assert frame.snapshot_eol(b"a\nb\n") == "LF"
    assert frame.snapshot_eol(b"a\r\nb\r\n") == "CRLF"
    assert frame.snapshot_eol(b"a\r\nb\n") == "MIXED"


# --------------------------------------------------------------------------
# 4. Eligibility is decided without any capacity quantity
# --------------------------------------------------------------------------


def test_a_predicate_on_a_field_the_catalogue_does_not_carry_is_refused():
    rule = _rule()
    smuggled = replace(
        rule,
        predicates=(
            *rule.predicates,
            frame.EligibilityPredicate(
                field="expected_candidates", op="gte", value=40, why="pool size"
            ),
        ),
    )
    with pytest.raises(frame.SFIR7Refused, match="does not carry"):
        frame.assert_capacity_blind(smuggled)


def test_a_predicate_whose_reason_names_a_capacity_term_is_refused():
    """The field can be innocent while the intent is not. The stated reason is
    part of the rule and is checked like any other part of it."""
    rule = _rule()
    smuggled = replace(
        rule,
        predicates=(
            *rule.predicates,
            frame.EligibilityPredicate(
                field="catalog_rank_value",
                op="gte",
                value=500,
                why="raises the qualifying pair yield per root",
            ),
        ),
    )
    with pytest.raises(frame.SFIR7Refused, match="capacity term"):
        frame.assert_capacity_blind(smuggled)


def test_a_ranking_key_outside_the_catalogue_record_is_refused():
    rule = replace(_rule(), ranking=(frame.RankKey(field="candidate_count", descending=True),))
    with pytest.raises(frame.SFIR7Refused, match="not a catalogue field"):
        frame.assert_capacity_blind(rule)


def test_a_tie_breaker_outside_the_catalogue_record_is_refused():
    rule = replace(_rule(), tie_breaker="measured_yield")
    with pytest.raises(frame.SFIR7Refused, match="not a catalogue field"):
        frame.assert_capacity_blind(rule)


def test_the_capacity_record_field_set_is_closed():
    """If FrameCatalogRecord ever grows a measured quantity, this is where it shows."""
    assert {
        "record_id",
        "host",
        "namespace",
        "name",
        "primary_language",
        "spdx_license_id",
        "created_utc",
        "last_activity_utc",
        "catalog_rank_value",
    } == frame.CATALOG_FIELDS
    for field_name in frame.CATALOG_FIELDS:
        assert not any(term in field_name for term in frame.CAPACITY_TERMS)


def test_apply_eligibility_runs_the_blindness_gate():
    rule = _rule()
    smuggled = replace(
        rule,
        predicates=(
            frame.EligibilityPredicate(field="not_a_field", op="eq", value=1, why="x"),
        ),
    )
    with pytest.raises(frame.SFIR7Refused):
        frame.apply_eligibility(_snapshot([_record(0)]), smuggled)


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"host": "gitlab"}, "REJECTED_host_eq"),
        ({"spdx_license_id": ""}, "REJECTED_spdx_license_id_in"),
        ({"spdx_license_id": "SSPL-1.0"}, "REJECTED_spdx_license_id_in"),
        ({"created_utc": "2026-01-01"}, "REJECTED_created_utc_on_or_before"),
        ({"last_activity_utc": "2019-01-01"}, "REJECTED_last_activity_utc_on_or_after"),
    ],
)
def test_each_declared_predicate_actually_rejects_something(override, expected):
    """A predicate that nothing can fail is decoration. Each one is shown biting."""
    record = _record(0, **override)
    eligible, dispositions = frame.apply_eligibility(_snapshot([record]), _rule())
    assert eligible == ()
    assert dispositions[record.record_id] == expected


def test_a_record_that_passes_everything_is_eligible():
    record = _record(0)
    eligible, dispositions = frame.apply_eligibility(_snapshot([record]), _rule())
    assert eligible == (record,)
    assert dispositions[record.record_id] == "ELIGIBLE"


def test_documentation_eligibility_is_a_path_property_read_from_the_frozen_frame():
    assert frame.DOC_EXTENSIONS == (".md", ".mdx", ".rst")
    assert frame.is_documentation_path("docs/GUIDE.MD") is True
    assert frame.is_documentation_path("docs/index.rst") is True
    assert frame.is_documentation_path("src/main.py") is False
    for predicate in _rule().predicates:
        assert predicate.field != "documentation_files"


def test_the_rule_does_not_exclude_the_prior_programmes_roots():
    """Excluding them would be TAVONEL curating the external universe again.
    Whether the external rule reselects any of them is a diagnostic, not an input."""
    for predicate in _rule().predicates:
        assert predicate.op not in {"not_in"} or predicate.field != "record_id"


# --------------------------------------------------------------------------
# 5. Ranking has no tie resolved by anything non-deterministic
# --------------------------------------------------------------------------


def test_two_records_sharing_a_full_ranking_key_are_refused():
    twin_a = _record(1, record_id="same-id", catalog_rank_value=500)
    twin_b = _record(2, record_id="same-id", catalog_rank_value=500)
    with pytest.raises(frame.SFIR7Refused, match="tie the declared tie-breaker cannot settle"):
        frame.select_top_n(_snapshot([twin_a, twin_b]), _rule())


def test_a_rank_tie_broken_by_the_declared_key_is_allowed_and_ordered():
    a = _record(1, record_id="cat-00002", catalog_rank_value=500)
    b = _record(2, record_id="cat-00001", catalog_rank_value=500)
    selection = frame.select_top_n(_snapshot([a, b]), _rule())
    assert [r.record_id for r in selection.selected] == ["cat-00001", "cat-00002"]


def test_a_descending_rank_over_a_non_integer_field_is_refused():
    """Descending order over a string has no definition here, and silently
    reversing a lexicographic sort is exactly the kind of implementation detail
    that makes a 'deterministic' rule depend on the library."""
    rule = replace(_rule(), ranking=(frame.RankKey(field="name", descending=True),))
    with pytest.raises(frame.SFIR7Refused, match="has no total-order definition"):
        frame.select_top_n(_snapshot([_record(0)]), rule)


def test_the_tie_breaker_is_appended_even_when_it_is_not_declared_in_ranking():
    rule = _rule()
    key = frame._ranking_key(_record(3), rule)
    assert key[-1] == "cat-00003"


# --------------------------------------------------------------------------
# 6. No network, and the check reads the file rather than a comment
# --------------------------------------------------------------------------


def test_this_module_cannot_reach_a_network():
    assert frame.declares_no_network() is True


def test_the_no_network_check_would_notice_an_import(monkeypatch):
    """The mutation, performed. `declares_no_network` reads bytes from
    `module_source_bytes`, so injecting a source with an import must turn it red."""
    poisoned = frame.module_source_bytes().replace(
        b"import hashlib", b"import hashlib\nimport requests", 1
    )
    monkeypatch.setattr(frame, "module_source_bytes", lambda: poisoned)
    assert frame.declares_no_network() is False


def test_the_module_source_is_read_as_bytes_and_is_lf():
    payload = frame.module_source_bytes()
    assert frame.snapshot_eol(payload) == "LF"


# --------------------------------------------------------------------------
# 7. The charter is checked against the live module, not against itself
# --------------------------------------------------------------------------
# SFIR5's batching gate passed by proving the charter matched its predecessor,
# and the predecessor had never worked (INC-V2-106). A document that certifies
# itself certifies nothing, so these read the YAML and compare it to the code
# that will actually run.

import yaml  # noqa: E402

CHARTER = yaml.safe_load(
    (NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7_DESIGN_CHARTER.yaml").read_text(
        encoding="utf-8"
    )
)


def test_the_charter_declares_the_n_the_module_derives():
    declared = CHARTER["root_selection_rule"]["n"]["value_under_the_currently_inherited_bounds"]
    assert declared == _rule().n


def test_the_charter_declares_the_derivation_the_module_accepts():
    assert CHARTER["root_selection_rule"]["n"]["derivation"] in frame.N_DERIVATIONS


def test_the_charter_predicate_list_is_the_module_predicate_list():
    """Fields and operators, in declared order. A charter predicate the code does
    not apply, or a code predicate the charter does not disclose, is the defect."""
    charter_pairs = [
        (item["field"], item["op"])
        for item in CHARTER["root_selection_rule"]["eligibility"]["predicates"]
    ]
    module_pairs = [(p.field, p.op) for p in _rule().predicates]
    assert charter_pairs == module_pairs


def test_the_charter_licence_allowlist_is_the_module_allowlist():
    charter_licences = next(
        item["value"]
        for item in CHARTER["root_selection_rule"]["eligibility"]["predicates"]
        if item["field"] == "spdx_license_id"
    )
    assert tuple(charter_licences) == frame.SPDX_ALLOWLIST


def test_the_freeze_state_is_coherent_with_the_artifacts_on_disk():
    """Two assertions this has already outlived: that the catalogue was undecided,
    and that the snapshot was unacquired. Both were true when written and both
    became the wrong thing to check as the study progressed. What is durable is
    the implication rather than any particular stage of it.

    A frozen charter must have a roster whose fingerprint is the one the freeze
    receipt sealed; an unfrozen charter must say what blocks it. Both halves bite:
    declaring `frozen: true` without a roster goes red, and so does a fingerprint
    that has drifted from the receipt.
    """
    state = CHARTER["design_freeze_state"]
    assert state["snapshot_acquired"] is (NS / "receipts/sfir7-catalog-snapshot.json").exists()
    assert state["snapshot_digest_pinned"] is state["snapshot_acquired"]
    freeze_receipt = NS / "receipts/sfir7-roster-freeze.json"
    assert state["roster_frozen"] is freeze_receipt.exists()
    if state["frozen"]:
        import json

        assert state["roster_frozen"] is True
        sealed = json.loads(freeze_receipt.read_text(encoding="utf-8"))
        assert state["roster_fingerprint"] == sealed["roster_fingerprint"]
        assert sealed["state"] == "ROSTER_FROZEN"
        assert state["blocking_freeze"] == []
    else:
        assert state["blocking_freeze"], "a charter that is not frozen must say what blocks it"
    assert CHARTER["root_selection_rule"]["universe"]["catalog_id"] != "PENDING_FOUNDER_DECISION"


def test_the_catalogue_is_pinned_to_an_immutable_third_party_deposit():
    """The universe is someone else's, dated, and addressable by DOI."""
    universe = CHARTER["root_selection_rule"]["universe"]
    catalogue = universe["catalogue"]
    assert universe["externally_defined"] is True
    assert universe["curated_by_tavonel"] is False
    assert catalogue["doi"] == "10.5281/zenodo.3626071"
    assert catalogue["version"] == "1.6.0"
    assert str(catalogue["publication_date"]) == "2020-01-12"
    assert catalogue["publisher_digest"].startswith("md5:")
    assert catalogue["locally_computed_sha256_is_required_in_addition"] is True
    # the deposit predates every SFIR study in this programme
    assert str(catalogue["publication_date"]) < "2026"


def test_the_rank_is_the_catalogues_own_and_tavonel_may_not_recompute_it():
    """The independence of the frame rests on the ordinal being someone else's."""
    policy = CHARTER["root_selection_rule"]["universe"]["rank_field_policy"]
    assert policy["use_the_catalogues_published_rank_verbatim"] is True
    assert policy["tavonel_may_not_recompute_popularity_or_yield"] is True
    # asserted over the rule the code will actually apply, not over the prose
    ranking = _rule().ranking
    assert [key.field for key in ranking] == ["catalog_rank_value"]
    assert ranking[0].descending is True
    assert CHARTER["root_selection_rule"]["ranking"]["computed_by_tavonel"] is False


def test_the_licence_posture_is_the_stricter_reading_and_is_scoped_to_the_data():
    """A compliance posture, recorded with the discrepancy it steps around."""
    licence = CHARTER["root_selection_rule"]["universe"]["licence"]
    assert licence["treat_derived_artifacts_as"] == "CC-BY-SA-4.0"
    assert licence["attribution_required"] == "Libraries.io"
    assert licence["this_is_a_compliance_posture_not_a_legal_determination"] is True
    # the discrepancy is recorded rather than resolved: Zenodo's record metadata
    # says CC BY 4.0 while Libraries.io states share-alike. Operating under the
    # stricter reading satisfies either, and which governs is not an agent's call.
    assert licence["discrepancy_recorded"]["zenodo_record_metadata_says"] == "cc-by-4.0"
    # and the share-alike scope is isolated to the data, not spread over the repo
    for excluded in ("TAVONEL source code", "patent material", "manuscript source"):
        assert excluded in licence["scope_explicitly_excludes"]
    assert licence["external_publication"]["permitted_only_after"] == "KOREAN_PRIORITY_FILING"


def test_the_budget_conflict_was_resolved_by_tightening_not_by_raising():
    """Recorded while SFIR6 was blind, resolved afterwards in the pre-declared
    conservative direction. The record of both is what makes the second sound."""
    conflict = CHARTER["inherited_transport_budget_conflict"]
    assert conflict["state"] == "RESOLVED_BY_TIGHTENING_NOT_BY_RAISING"
    assert conflict["registered_before_the_predecessor_result_existed"] is True
    assert conflict["what_the_conflict_was"]["inherited_cap"] == 12_000
    assert conflict["what_the_conflict_was"]["n_roots_under_the_first_draft"] == 125
    n_now = CHARTER["root_selection_rule"]["n"]["value_under_the_currently_inherited_bounds"]
    assert n_now < conflict["what_the_conflict_was"]["n_roots_under_the_first_draft"]


def test_the_charter_says_sfir7_is_a_new_frame_question_and_not_a_repair():
    block = CHARTER["what_sfir7_is_not"]
    assert block["it_is_not_an_instrument_repair"] is True
    assert block["it_does_not_rescore_any_predecessor"] is True
    assert block["a_pass_here_does_not_convert_a_predecessor_failure_into_a_pass"] is True
    preserved = CHARTER["predecessor_results_preserved"]
    assert preserved["sfir6"]["this_charter_was_designed_without_reading_it"] is True
    for predecessor in ("sfir5", "sfir6"):
        assert preserved[predecessor]["is_not_rescored"] is True
        assert preserved[predecessor]["numbers_are_not_copied_into_sfir7"] is True


def test_the_charter_does_not_quote_a_predecessor_capacity_number_as_a_target():
    """The two figures may appear in `purpose`, where they state the question.
    They may not appear anywhere in the selection rule."""
    rule_text = yaml.safe_dump(CHARTER["root_selection_rule"])
    for numeral in frame.FORBIDDEN_NUMERALS:
        assert numeral not in rule_text


# ---------------------------------------------------------------------------
# The inherited transport budget conflict, registered while SFIR6 was blind.
# ---------------------------------------------------------------------------


def test_the_budget_conflict_record_still_matches_the_live_constants():
    """Superseded form of an earlier control.

    It used to assert the conflict was OPEN_AND_BLOCKING, which was correct while
    SFIR6 was still running and is now stale: the founder resolved it by tightening
    N rather than raising the cap. What must still hold is that the numbers the
    charter recorded are the numbers the modules carry, so the account of the
    conflict cannot drift out from under the resolution.
    """
    import sfir5_transport as t5
    import sfir6_transport as t6
    from acquisition import sources_sfir4 as sources

    conflict = CHARTER["inherited_transport_budget_conflict"]["what_the_conflict_was"]
    assert conflict["inherited_cap"] == t5.MAX_TOTAL_REQUESTS
    assert conflict["per_root_request_bound"] == sources.MAX_GIT_API_REQUESTS_PER_ROOT
    assert conflict["n_roots_under_the_first_draft"] * conflict["per_root_request_bound"] == (
        conflict["implied_worst_case_requests"]
    )
    assert conflict["implied_worst_case_requests"] > conflict["inherited_cap"], (
        "the conflict as recorded must still be a conflict, or the record is fiction"
    )
    assert t6.MAX_TOTAL_WALL_CLOCK_SECONDS == 21600

    n_now = CHARTER["root_selection_rule"]["n"]["value_under_the_currently_inherited_bounds"]
    assert n_now * conflict["per_root_request_bound"] <= conflict["inherited_cap"], (
        "the resolved N must fit inside the cap that caused the conflict"
    )




# ---------------------------------------------------------------------------
# Vocabulary reconciliation: the predicates were written blind, the catalogue
# writes its own spellings, and a predicate that matches nothing is invisible.
# ---------------------------------------------------------------------------


def _catalog_vocabulary() -> dict:
    import json

    path = NS / "receipts" / "sfir7-catalog-vocabulary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_declared_licence_matches_at_least_one_row_in_the_catalogue():
    """The control that would have caught the original fault.

    All four declared copyleft spellings matched ZERO rows: the charter says
    `GPL-2.0-only`, this 2020 deposit predates the SPDX 3.0 split and writes
    `GPL-2.0`. Left alone, the rule would have removed every copyleft repository
    from the universe and produced a roster of permissive licences -- smaller,
    entirely real, and wrong in a way nothing downstream could see.
    """
    tally = _catalog_vocabulary()["license_tally"]
    # summed, not overwritten: MIT and mit both fold to `mit`, and a dict
    # comprehension keyed on casefold() keeps only the last one. That bug
    # shipped a wrong count in the projection-audit receipt.
    folded: dict[str, int] = {}
    for name, count in tally.items():
        folded[name.casefold()] = folded.get(name.casefold(), 0) + count
    declared = next(p.value for p in _rule().predicates if p.field == "spdx_license_id")
    unmatched = []
    for value in declared:
        spellings = frame.catalog_spellings(value)
        if not any(folded.get(s.casefold(), 0) > 0 for s in spellings):
            unmatched.append((value, spellings))
    assert not unmatched, (
        f"declared licence values that match nothing in the catalogue: {unmatched}. "
        "A predicate that is false for every row silently narrows the universe."
    )


def test_the_declared_host_matches_the_catalogues_own_spelling():
    """The charter says `github`; the catalogue writes `GitHub`."""
    hosts = _catalog_vocabulary()["enumerated"]["Host Type"]
    folded = {name.casefold() for name in hosts}
    declared = next(p.value for p in _rule().predicates if p.field == "host")
    assert declared.casefold() in folded, (
        f"declared host {declared!r} is not in the catalogue's vocabulary {sorted(hosts)}"
    )


def test_the_or_later_spellings_are_excluded_and_named_as_excluded():
    """`GPL-3.0+` means or-later and is a different licence choice from `-only`.

    Excluding it is correct; excluding it by accident would not be. It is named
    in the module so the exclusion is a declared act rather than an omission.
    """
    mapped = {
        spelling
        for spellings in frame.LICENSE_SPELLINGS_IN_THIS_CATALOG.values()
        for spelling in spellings
    }
    for excluded in frame.OR_LATER_SPELLINGS_DELIBERATELY_EXCLUDED:
        assert excluded not in mapped
        # and it really is a value the catalogue uses, or the exclusion is theatre
        assert excluded in _catalog_vocabulary()["license_tally"]


def test_the_mapping_changes_spelling_only_and_never_adds_a_licence_family():
    """What is eligible must not have moved. Ten families in, ten families out."""
    declared = next(p.value for p in _rule().predicates if p.field == "spdx_license_id")
    assert len(declared) == 10
    for value in declared:
        spellings = frame.catalog_spellings(value)
        # each declared value maps to spellings of ITSELF, never to another licence
        stem = value.replace("-only", "")
        assert all(s in (stem, value) for s in spellings), (value, spellings)


def test_case_folding_is_applied_to_licences_and_hosts_but_not_to_everything():
    """SPDX matches case-insensitively and this catalogue is inconsistent about
    it -- `MIT` and `mit` are both present. INC-V2-109 is the opposite case:
    MediaWiki titles ARE case-sensitive and folding them merged two pages. The
    domain decides, not convenience."""
    assert {"spdx_license_id", "host"} == frame.CASE_INSENSITIVE_FIELDS
    tally = _catalog_vocabulary()["license_tally"]
    assert "MIT" in tally, "the inconsistency this exists for is gone"
    assert "mit" in tally, "the inconsistency this exists for is gone"


def test_a_lowercase_licence_row_is_eligible_under_the_reconciled_rule():
    from dataclasses import replace as _replace

    rule = _rule()
    record = _record(1, spdx_license_id="mit", host="GitHub")
    predicate = next(p for p in rule.predicates if p.field == "spdx_license_id")
    assert frame._evaluate(predicate, record) is True
    host_predicate = next(p for p in rule.predicates if p.field == "host")
    assert frame._evaluate(host_predicate, record) is True
    # and a licence outside the ten families is still refused
    assert frame._evaluate(predicate, _replace(record, spdx_license_id="Other")) is False


def test_a_copyleft_row_in_the_catalogues_spelling_is_eligible():
    """The rows the original spelling would have dropped: 1,076,735 of them."""
    predicate = next(p for p in _rule().predicates if p.field == "spdx_license_id")
    for spelling in ("GPL-2.0", "GPL-3.0", "LGPL-2.1", "LGPL-3.0"):
        assert frame._evaluate(predicate, _record(1, spdx_license_id=spelling)) is True
    # or-later is a different choice and stays out
    for spelling in ("GPL-3.0+", "LGPL-2.1+", "LGPL-3.0+"):
        assert frame._evaluate(predicate, _record(1, spdx_license_id=spelling)) is False


# --- the scope of N's derivation (INC-V2-115) --------------------------------


def _charter() -> dict:
    import yaml

    path = NS / "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7_DESIGN_CHARTER.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _inherited_request_caps() -> dict[str, int]:
    """Every inherited constant that can stop the census by counting requests."""
    import sfir5_transport as t5
    from acquisition import sources_sfir4 as sources

    return {
        "sfir5_transport.MAX_TOTAL_REQUESTS": t5.MAX_TOTAL_REQUESTS,
        "sources_sfir4.MAX_GIT_API_REQUESTS_GLOBAL": sources.MAX_GIT_API_REQUESTS_GLOBAL,
    }


def test_every_cap_tighter_than_the_one_n_uses_is_registered_in_the_charter():
    """`refuse_count_tuned_rule` is blind outside the inputs the derivation names.

    It checks that N's four declared inputs equal the live inherited bounds, so a
    bound the derivation never names cannot fail it. `MAX_GIT_API_REQUESTS_GLOBAL`
    is 4,800, is enforced on the only family SFIR7 traverses, and is 2.5x tighter
    than the 12,000 N was derived from -- and no control saw it (INC-V2-115).

    This is that control. It does not change N, which is a founder ruling. It
    requires that any cap capable of binding the census before N's own term does
    is written down where a reader of the charter will find it.
    """
    used = frame.inherited_total_request_cap()
    tighter = {
        name: value for name, value in _inherited_request_caps().items() if value < used
    }
    registered = _charter().get("second_inherited_request_cap") or {}
    for name, value in tighter.items():
        assert registered.get("constant", "").endswith(name.split(".")[-1]), name
        assert registered["value"] == value
        assert registered["state"] == "REGISTERED_NOT_ACTED_ON"


def test_the_registration_control_has_something_to_find():
    """A control over an empty set proves nothing. There is a tighter cap today."""
    used = frame.inherited_total_request_cap()
    assert any(value < used for value in _inherited_request_caps().values())


def test_the_registered_cap_is_the_one_the_transport_actually_enforces():
    """Registered against the live constant, not against a number retyped here."""
    from acquisition import sources_sfir4 as sources

    registered = _charter()["second_inherited_request_cap"]
    assert registered["value"] == sources.MAX_GIT_API_REQUESTS_GLOBAL
    assert registered["n_as_frozen"] == frame.declared_rule(
        catalog_id="LIBRARIES_IO_OPEN_DATA_1_6_0",
        snapshot_sha256="sha256:" + "0" * 64,
        snapshot_date_utc="2020-01-12",
    ).n
    assert registered["action_taken"] == "none"
