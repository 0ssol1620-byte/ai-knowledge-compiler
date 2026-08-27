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


def _record(index: int, **overrides) -> frame.CatalogRecord:
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
    return frame.CatalogRecord(**base)


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
    )
    assert frame.refuse_count_tuned_rule(rule) == rule.n


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
    """If CatalogRecord ever grows a measured quantity, this is where it shows."""
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


def test_the_charter_has_not_been_frozen_and_names_what_blocks_it():
    """SFIR7 is design-only until a founder rules on the catalogue and its terms.
    If this goes green-by-deletion, something froze a frame with no universe."""
    state = CHARTER["design_freeze_state"]
    assert state["frozen"] is False
    assert state["catalogue_identity_decided"] is False
    assert state["catalogue_licence_cleared"] is False
    assert state["snapshot_digest_pinned"] is False
    assert len(state["blocking_freeze"]) >= 2
    assert CHARTER["root_selection_rule"]["universe"]["catalog_id"] == "PENDING_FOUNDER_DECISION"


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


def test_the_budget_conflict_is_registered_with_the_live_numbers_and_still_blocks():
    """Prose in a charter is not a mechanism; this reads the constants.

    N=125 roots at 240 requests each implies 30,000 requests against an
    inherited cap of 12,000. The conflict is real, it blocks the freeze, and the
    two honest resolutions are both frame decisions that must be taken before a
    count exists. If someone quietly raises either constant, the recorded
    arithmetic stops matching the modules and this goes red.
    """
    import sfir5_transport as t5
    import sfir6_transport as t6
    from acquisition import sources_sfir4 as sources

    charter = CHARTER
    conflict = charter["inherited_transport_budget_conflict"]

    assert conflict["state"] == "OPEN_AND_BLOCKING"
    assert conflict["inherited_cap"] == t5.MAX_TOTAL_REQUESTS
    assert conflict["per_root_request_bound"] == sources.MAX_GIT_API_REQUESTS_PER_ROOT
    assert conflict["n_roots"] * conflict["per_root_request_bound"] == (
        conflict["implied_worst_case_requests"]
    )
    assert conflict["implied_worst_case_requests"] > conflict["inherited_cap"], (
        "the conflict was recorded as open but the numbers no longer conflict"
    )
    # the wall clock the N derivation reads, pinned here too
    assert t6.MAX_TOTAL_WALL_CLOCK_SECONDS == 21600

    assert any(
        "transport request budget" in str(item)
        for item in charter["design_freeze_state"]["blocking_freeze"]
    )
    assert charter["design_freeze_state"]["frozen"] is False
