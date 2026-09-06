"""Lane 5 — the adversarial corpus, and the checker that runs it.

The suite is in two halves and the split is the point.

**Half one runs now, unconditionally.** It exercises the fixture data and the
``check`` logic against hand-built ``ir.SourceFact`` lists. No extractor is
involved, so nothing here can be skipped by an absent lane. It includes the
gate-power tests: for every expectation type, a fact list that violates it and
an assertion that ``check`` returns FAIL. A checker nobody has watched fail is
not a checker, it is a decoration.

**Half two runs the corpus through whatever extractors are actually registered.**
At the time of writing that is very likely none, and the correct result is
NOT_EXERCISED with a reason naming the unclaimed kinds — never a pass. There is
a test asserting exactly that: an unexercised fixture must not report as passing.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
#: Package-qualified, as test_sfi_metadata.py does. Importing ``ir`` under a
#: second name would give this suite a second registry and a second SourceFact
#: class, and every registry assertion below would then be about a registry no
#: extractor ever wrote to.
sys.path.insert(0, str(NS))

from source_fact_ir import adversarial_fixtures as af  # noqa: E402
from source_fact_ir import ir  # noqa: E402

# ---------------------------------------------------------------------------
# helpers: hand-built facts, so the checker can be judged without an extractor


def witness(construct: str, start: int = 0, end: int = 10, unit: str = "u1") -> ir.Witness:
    return ir.Witness(construct=construct, byte_start=start, byte_end=end, unit_path=(unit,))


def represented(kind: str, value: object, construct: str = "a", start: int = 0) -> ir.SourceFact:
    return ir.SourceFact(
        kind=kind,
        witness=witness(construct, start, start + 10),
        state=ir.REPRESENTED,
        representation=value,
    )


def unresolved(
    kind: str, reason: str, construct: str = "a", span: tuple[int, int] = (0, 10)
) -> ir.SourceFact:
    return ir.SourceFact(
        kind=kind, witness=witness(construct, *span), state=ir.UNRESOLVED, reason=reason
    )


def unrepresented(
    kind: str, reason: str, construct: str = "a", span: tuple[int, int] = (0, 10)
) -> ir.SourceFact:
    return ir.SourceFact(
        kind=kind, witness=witness(construct, *span), state=ir.UNREPRESENTED, reason=reason
    )


def span(fixture_id: str, snippet: bytes, side: str) -> tuple[int, int]:
    """Byte span of a snippet in one revision of a fixture.

    NoSilentAbsence is anchored to source bytes rather than to construct labels,
    so a hand-built fact has to point at the right bytes to satisfy it. The span
    differs between revisions whenever the edit is upstream of the snippet, which
    is why the side is a parameter and not an assumption.
    """
    raw = getattr(af.BY_ID[fixture_id], side)
    start = raw.find(snippet)
    assert start >= 0, f"{snippet!r} is not in the {side} revision of {fixture_id}"
    return start, start + len(snippet)


ALL_KINDS = ir.KINDS

ANCHOR = b'<a href="#schedule">'
MATH = b"<math>"


def run(fixture_id: str, before: list, after: list, kinds=ALL_KINDS) -> af.Outcome:
    return af.check(af.BY_ID[fixture_id], before, after, available_kinds=kinds)


# ===========================================================================
# half one, part A — the fixture data itself


def test_every_mandated_class_has_a_fixture():
    """The founder named ten classes. Coverage is asserted, not asserted-in-prose."""
    covered = {f.fixture_class for f in af.FIXTURES}
    missing = sorted(set(af.MANDATED_CLASSES) - covered)
    assert not missing, f"mandated fixture classes with no fixture: {missing}"


def test_fixture_ids_are_unique_and_stable_shape():
    ids = [f.fixture_id for f in af.FIXTURES]
    assert len(ids) == len(set(ids)), "duplicate fixture id"
    assert all(i.startswith("adv-") for i in ids)
    assert len(af.BY_ID) == len(af.FIXTURES)


def test_every_fixture_is_raw_bytes_and_actually_differs_or_deliberately_does_not():
    """before/after must be bytes, and must not be accidentally identical.

    An identical pair is the one fixture shape that cannot fail: ChangedIn is
    unsatisfiable and Unchanged is trivially satisfied.
    """
    for f in af.FIXTURES:
        assert isinstance(f.before, bytes), f.fixture_id
        assert isinstance(f.after, bytes), f.fixture_id
        assert f.before != f.after, f"{f.fixture_id} has an identical pair; it cannot test anything"


def test_every_fixture_states_its_requirement_and_the_naive_failure():
    for f in af.FIXTURES:
        assert len(f.requirement) > 20, f.fixture_id
        assert len(f.naive_failure) > 20, f.fixture_id


def test_expectations_name_only_kinds_the_ir_declares():
    for f in af.FIXTURES:
        assert f.expectation.relevant_kinds() <= set(ir.KIND_CHANNEL), f.fixture_id


def test_an_expectation_naming_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown fact kind"):
        af.ChangedIn(("NOT_A_KIND",))


def test_fixture_declaring_an_unknown_class_is_refused():
    with pytest.raises(ValueError, match="unknown class"):
        af.Fixture(
            fixture_id="x",
            fixture_class="INVENTED",
            before=b"a",
            after=b"b",
            requirement="something long enough to pass the check",
            expectation=af.ChangedIn((ir.CONTENT_TEXT,)),
            naive_failure="something long enough to pass the check",
        )


def test_inventory_is_serializable_and_hashes_the_bytes():
    rows = af.inventory()
    assert len(rows) == len(af.FIXTURES)
    for row in rows:
        assert row["before_sha256"].startswith("sha256:")
        assert row["before_sha256"] != row["after_sha256"]


def test_ambiguous_and_decidable_dates_are_a_matched_pair():
    """The contrast is the fixture. Without it, "declare every date ambiguous" passes."""
    ambiguous = af.BY_ID["adv-014-ambiguous-date"]
    decidable = af.BY_ID["adv-015-decidable-date-contrast"]
    assert b"03/04/2026" in ambiguous.before
    assert b"2026-04-03" in decidable.before
    assert isinstance(ambiguous.expectation, af.MustBeInState)
    assert isinstance(decidable.expectation, af.ChangedIn)


def test_percent_encoding_pair_pulls_in_opposite_directions():
    """%7E->~ must produce no delta; %2F->/ must produce one.

    Fixing either one naively breaks the other, which is why they are a pair.
    """
    same = af.BY_ID["adv-012-percent-encoding-equivalent"]
    diff = af.BY_ID["adv-013-percent-encoding-not-equivalent"]
    assert isinstance(same.expectation, af.Unchanged)
    assert isinstance(diff.expectation, af.ChangedIn)


def test_markup_only_fixture_moves_byte_offsets():
    """If the two revisions were the same length the fixture would not exercise the risk."""
    f = af.BY_ID["adv-008-markup-only-equivalence"]
    assert len(f.before) != len(f.after)


# ===========================================================================
# half one, part B — the checker passes when it should


def test_changed_in_passes_when_the_named_kind_moves():
    out = run(
        "adv-001-href-changed-text-unchanged",
        [represented(ir.REFERENCE_TARGET, "https://example.com/policy/v1")],
        [represented(ir.REFERENCE_TARGET, "https://example.com/policy/v2")],
    )
    assert out.status == af.PASS, out.reason
    assert out.passed


def test_unchanged_passes_when_only_provenance_moves():
    """A byte offset moving is not a fact changing; the excluded kind must be excluded."""
    before = [
        represented(ir.CONTENT_TEXT, "Samples are kept for 30 days."),
        represented(ir.PROVENANCE_SPAN, {"start": 40, "end": 70}, construct="p"),
    ]
    after = [
        represented(ir.CONTENT_TEXT, "Samples are kept for 30 days."),
        represented(ir.PROVENANCE_SPAN, {"start": 44, "end": 78}, construct="p"),
    ]
    out = run("adv-008-markup-only-equivalence", before, after)
    assert out.status == af.PASS, out.reason


def test_unchanged_ignores_byte_offsets_in_the_comparison_key():
    """The same fact seen at a different offset is the same fact. fact_id would disagree."""
    before = [represented(ir.CONTENT_TEXT, "text", start=0)]
    after = [represented(ir.CONTENT_TEXT, "text", start=900)]
    assert before[0].fact_id != after[0].fact_id
    assert af.fact_value(before[0]) == af.fact_value(after[0])
    assert run("adv-009-entity-normalization", before, after).status == af.PASS


def test_must_be_in_state_passes_with_a_reason_on_both_sides():
    facts = [unresolved(ir.EFFECTIVE_TIME, "03/04/2026 has two readings and no locale is declared")]
    out = run("adv-014-ambiguous-date", facts, list(facts))
    assert out.status == af.PASS, out.reason


def test_must_fail_closed_accepts_either_fail_closed_state():
    """UNRESOLVED and RECOGNIZED_BUT_UNREPRESENTED are both honest refusals here."""
    fid = "adv-011-unsupported-construct-mathml"
    for maker in (unresolved, unrepresented):
        out = run(
            fid,
            [maker(ir.STRUCTURE, "no representation for an expression tree",
                   construct="math", span=span(fid, MATH, "before"))],
            [maker(ir.STRUCTURE, "no representation for an expression tree",
                   construct="math", span=span(fid, MATH, "after"))],
        )
        assert out.status == af.PASS, out.reason


def test_no_silent_absence_passes_when_the_named_region_is_witnessed():
    """One UNRESOLVED fact pointing at the anchor satisfies both parts of adv-010."""
    fid = "adv-010-malformed-ambiguous-location"
    out = run(
        fid,
        [unresolved(ir.LOCATOR, "two elements claim id=schedule",
                    span=span(fid, ANCHOR, "before"))],
        [unresolved(ir.LOCATOR, "two elements claim id=schedule",
                    span=span(fid, ANCHOR, "after"))],
    )
    assert out.status == af.PASS, out.reason


def test_no_silent_absence_uses_bytes_not_construct_labels():
    """The construct label is lane-owned vocabulary; the byte span is not.

    The same fact carrying a label no fixture author would have guessed still
    satisfies the expectation, because the expectation is about the source.
    """
    fid = "adv-010-malformed-ambiguous-location"
    out = run(
        fid,
        [unresolved(ir.LOCATOR, "ambiguous id", construct="html-a-href",
                    span=span(fid, ANCHOR, "before"))],
        [unresolved(ir.LOCATOR, "ambiguous id", construct="html-a-href",
                    span=span(fid, ANCHOR, "after"))],
    )
    assert out.status == af.PASS, out.reason


# ===========================================================================
# half one, part C — GATE POWER. Every expectation type must be shown to fail.
#
# A safety endpoint that has never been exercised has not been met, it has been
# skipped. Each test below constructs output that violates the property and
# asserts check() catches it.


def test_gate_power_changed_in_fails_when_nothing_changes():
    """The INC-V2-006 shape: visible text identical, and the extractor emits an identical fact."""
    facts = [represented(ir.REFERENCE_TARGET, "https://example.com/policy/v1")]
    out = run("adv-001-href-changed-text-unchanged", facts, list(facts))
    assert out.status == af.FAIL
    assert "invisible to the compiled state" in out.reason
    assert not out.passed


def test_gate_power_changed_in_fails_and_says_so_when_the_kind_produced_nothing():
    """A claimed kind that emits nothing is a silent drop, not a skip.

    The distinction matters to whoever reads the failure: zero facts points at
    an extractor that never ran or never looked, while facts-but-identical points
    at one that looked and represented the change away. Both are FAIL; only one
    of them is fixed by wiring.
    """
    out = run(
        "adv-004-language-metadata-changed",
        [represented(ir.CONTENT_TEXT, "Retention", construct="h1")],
        [represented(ir.CONTENT_TEXT, "Retention", construct="h1")],
    )
    assert out.status == af.FAIL
    assert "silently absent" in out.reason
    assert "was produced for either revision" in out.reason


def test_gate_power_changed_in_fails_when_a_different_kind_changes():
    """A text delta is not a reference delta. Watching the wrong channel must not satisfy it."""
    before = [
        represented(ir.REFERENCE_TARGET, "https://example.com/policy/v1"),
        represented(ir.CONTENT_TEXT, "the retention schedule", construct="p"),
    ]
    after = [
        represented(ir.REFERENCE_TARGET, "https://example.com/policy/v1"),
        represented(ir.CONTENT_TEXT, "the retention timetable", construct="p"),
    ]
    out = run("adv-001-href-changed-text-unchanged", before, after)
    assert out.status == af.FAIL, out.reason


def test_gate_power_unchanged_fails_on_a_false_delta():
    """<b> becoming <strong> must not move a fact. Here it does, and the gate must say so."""
    before = [represented(ir.CONTENT_TEXT, "Samples are kept for **30 days**.")]
    after = [represented(ir.CONTENT_TEXT, "Samples are kept for __30 days__.")]
    out = run("adv-008-markup-only-equivalence", before, after)
    assert out.status == af.FAIL
    assert "false delta" in out.reason


def test_gate_power_unchanged_fails_when_a_fact_appears_from_nowhere():
    before = [represented(ir.CONTENT_TEXT, "Retention & disposal")]
    after = [
        represented(ir.CONTENT_TEXT, "Retention & disposal"),
        represented(ir.STRUCTURE, {"tag": "span"}, construct="span"),
    ]
    out = run("adv-009-entity-normalization", before, after)
    assert out.status == af.FAIL, out.reason


def test_gate_power_must_be_in_state_fails_when_the_ambiguity_is_guessed():
    """dateutil answers confidently. A confident answer to an undecidable question is the bug."""
    facts = [represented(ir.EFFECTIVE_TIME, "2026-04-03")]
    out = run("adv-014-ambiguous-date", facts, list(facts))
    assert out.status == af.FAIL
    assert "resolved when it is not decidable" in out.reason


def test_gate_power_must_be_in_state_fails_when_only_one_side_is_unresolved():
    """Resolving the ambiguity on whichever revision came second is still a guess."""
    before = [unresolved(ir.EFFECTIVE_TIME, "two readings, no locale declared")]
    after = [represented(ir.EFFECTIVE_TIME, "2026-06-05")]
    out = run("adv-014-ambiguous-date", before, after)
    assert out.status == af.FAIL
    assert "after" in out.reason


def test_gate_power_must_be_in_state_fails_when_the_reason_is_missing():
    """ir refuses a reasonless UNRESOLVED outright — the checker must not need to be lenient."""
    with pytest.raises(ValueError, match="with no reason"):
        ir.SourceFact(kind=ir.EFFECTIVE_TIME, witness=witness("meta"), state=ir.UNRESOLVED)


def test_gate_power_must_be_in_state_fails_on_the_wrong_state():
    """UNREPRESENTED is honest but it is not the answer adv-014 demands: the date IS recognised."""
    facts = [unrepresented(ir.EFFECTIVE_TIME, "no representation for dates")]
    out = run("adv-014-ambiguous-date", facts, list(facts))
    assert out.status == af.FAIL, out.reason


def test_gate_power_must_fail_closed_fails_when_the_construct_is_declared_represented():
    """The SFH1 failure verbatim: the grammar recognised it, so the table said MODELED."""
    facts = [represented(ir.STRUCTURE, {"tag": "math", "carried": False}, construct="math")]
    out = run("adv-011-unsupported-construct-mathml", facts, list(facts))
    assert out.status == af.FAIL
    assert "REPRESENTED or silently dropped" in out.reason


def test_gate_power_must_fail_closed_fails_when_ignored_by_policy_is_claimed():
    """IGNORED is the only fail-open state. Reaching for it here launders a loss as a decision."""
    facts = [
        ir.SourceFact(
            kind=ir.STRUCTURE,
            witness=witness("math"),
            state=ir.IGNORED,
            policy_ref="POLICY-MATH-OUT-OF-SCOPE",
        )
    ]
    out = run("adv-011-unsupported-construct-mathml", facts, list(facts))
    assert out.status == af.FAIL, out.reason


def test_gate_power_no_silent_absence_fails_when_a_construct_produces_nothing():
    """The whole ruling in one assertion: silence is not a state.

    adv-011 is used rather than adv-010 because its other AllOf part is satisfied
    here, so the failure that surfaces is unambiguously this one: the extractor
    refused something honestly, but emitted nothing at all for <math>.
    """
    facts = [unresolved(ir.STRUCTURE, "unbalanced markup in the body", construct="p")]
    out = run("adv-011-unsupported-construct-mathml", facts, list(facts))
    assert out.status == af.FAIL
    assert "produced no fact at all" in out.reason


def test_gate_power_all_of_fails_on_its_second_part_and_names_it():
    """A combinator that reports only the first part hides the other half of the contract."""
    facts = [unresolved(ir.LOCATOR, "two elements claim id=schedule", construct="a")]
    out = run("adv-010-malformed-ambiguous-location", facts, list(facts))
    assert out.status == af.FAIL
    assert "part 1" in out.reason and "NoSilentAbsence" in out.reason


def test_gate_power_every_expectation_type_in_the_corpus_has_been_shown_to_fail():
    """Meta-gate: no expectation type may enter the corpus without a failing witness above.

    Each entry is a (fixture_id, before, after) that must FAIL. If a new
    expectation type is added to FIXTURES and no failing case is registered
    here, this test goes red — which is the only mechanism that keeps the gate
    power honest as the corpus grows.
    """
    witnesses = {
        "ChangedIn": (
            "adv-001-href-changed-text-unchanged",
            [represented(ir.REFERENCE_TARGET, "same")],
            [represented(ir.REFERENCE_TARGET, "same")],
        ),
        "Unchanged": (
            "adv-008-markup-only-equivalence",
            [represented(ir.CONTENT_TEXT, "a")],
            [represented(ir.CONTENT_TEXT, "b")],
        ),
        "MustBeInState": (
            "adv-014-ambiguous-date",
            [represented(ir.EFFECTIVE_TIME, "2026-04-03")],
            [represented(ir.EFFECTIVE_TIME, "2026-06-05")],
        ),
        "MustFailClosed": (
            "adv-011-unsupported-construct-mathml",
            [represented(ir.STRUCTURE, {"tag": "math"}, construct="math")],
            [represented(ir.STRUCTURE, {"tag": "math"}, construct="math")],
        ),
        "NoSilentAbsence": (
            "adv-010-malformed-ambiguous-location",
            [unresolved(ir.LOCATOR, "ambiguous", construct="a")],
            [unresolved(ir.LOCATOR, "ambiguous", construct="a")],
        ),
        "AllOf": (
            "adv-010-malformed-ambiguous-location",
            [represented(ir.CONTENT_TEXT, "Retention", construct="h1")],
            [represented(ir.CONTENT_TEXT, "Retention", construct="h1")],
        ),
    }
    used = {type(f.expectation).__name__ for f in af.FIXTURES}
    # AllOf's parts count too: a part type used only inside a combinator still needs a witness.
    for fixture in af.FIXTURES:
        if isinstance(fixture.expectation, af.AllOf):
            used |= {type(p).__name__ for p in fixture.expectation.parts}
    missing = sorted(used - set(witnesses))
    assert not missing, f"expectation type(s) with no proof they can fail: {missing}"

    for name, (fixture_id, before, after) in witnesses.items():
        out = run(fixture_id, before, after)
        assert out.status == af.FAIL, f"{name} did not fail on its violating case: {out.reason}"


# ===========================================================================
# half one, part D — NOT_EXERCISED can never be a pass


def test_unexercised_fixture_never_reports_as_passing():
    """The single most important assertion in this file.

    A corpus that counts unexercised fixtures as green reports coverage it does
    not have. That is how 63,196 constructs were recorded as MODELED.
    """
    out = run("adv-001-href-changed-text-unchanged", [], [], kinds=())
    assert out.status == af.NOT_EXERCISED
    assert out.passed is False
    assert ir.REFERENCE_TARGET in out.reason


def test_empty_facts_do_not_satisfy_an_unchanged_expectation():
    """Unchanged names no kinds, so the kind gate cannot catch it. The empty gate must."""
    out = run("adv-008-markup-only-equivalence", [], [], kinds=ALL_KINDS)
    assert out.status == af.NOT_EXERCISED
    assert not out.passed


def test_empty_facts_do_not_satisfy_no_silent_absence():
    out = run("adv-010-malformed-ambiguous-location", [], [], kinds=ALL_KINDS)
    assert out.status == af.NOT_EXERCISED, out.reason


def test_not_exercised_reason_names_the_missing_kinds():
    out = run(
        "adv-016-recognized-but-unrepresentable-include",
        [represented(ir.CONTENT_TEXT, "x")],
        [represented(ir.CONTENT_TEXT, "y")],
        kinds=(ir.CONTENT_TEXT,),
    )
    assert out.status == af.NOT_EXERCISED
    assert ir.INCLUDE_TARGET in out.reason


def test_outcome_refuses_to_exist_without_a_reason():
    with pytest.raises(ValueError, match="no reason"):
        af.Outcome("adv-001-href-changed-text-unchanged", af.PASS, "")


def test_check_all_reports_not_exercised_separately_from_passed():
    """A summary that folds skips into passes is the report shape under indictment."""
    summary = af.check_all(lambda raw: [], available_kinds=())
    assert summary["passed"] == 0
    assert summary["not_exercised"] == len(af.FIXTURES)
    assert summary["all_exercised_and_passed"] is False


def test_check_all_treats_an_extractor_crash_as_failure_not_as_a_skip():
    def explode(raw: bytes):
        raise RuntimeError("scanner died on the malformed anchor")

    summary = af.check_all(explode, available_kinds=ALL_KINDS)
    assert summary["failed"] == len(af.FIXTURES)
    assert summary["not_exercised"] == 0


# ===========================================================================
# half two — the real extractors, if any lane has registered one yet
#
# Extractors register themselves on import. Their module names are owned by
# other lanes and are not guessed here: every sibling module in source_fact_ir/
# is imported defensively, and whatever registers, registers.


def _load_sibling_extractors() -> tuple[list[str], list[str]]:
    """Import every sibling module so registration happens. Returns (loaded, failed).

    Modules are imported package-qualified. Importing them bare would create a
    second module object for a lane that already registered under the qualified
    name, and ``ir.register`` would then refuse the duplicate — a collision this
    suite would have manufactured itself.

    A module that will not import is recorded, not raised. It is a missing lane,
    and a missing lane is reported through the skip reason of the fixtures it
    would have defended; crashing here would replace that specific report with a
    single unrelated error.
    """
    loaded: list[str] = []
    failed: list[str] = []
    for path in sorted((NS / "source_fact_ir").glob("*.py")):
        name = path.stem
        if name in {"ir", "adversarial_fixtures", "__init__"}:
            continue
        try:
            importlib.import_module(f"source_fact_ir.{name}")
        except Exception as error:
            failed.append(f"source_fact_ir.{name}: {type(error).__name__}: {error}")
        else:
            loaded.append(name)
    return loaded, failed


def test_registry_state_is_reported_not_assumed():
    """Whatever is registered, the suite states it. Zero is a legitimate answer.

    This asserts the *shape* of the report, never a particular registry
    population: another lane landing an extractor must not turn this file red,
    and another lane being absent must not turn it green by silence. What the
    registry actually holds is reported through the skip reasons below.
    """
    loaded, failed = _load_sibling_extractors()
    assert isinstance(ir.registered_kinds(), tuple)
    assert isinstance(ir.unclaimed_kinds(), tuple)
    assert set(ir.registered_kinds()).isdisjoint(ir.unclaimed_kinds())
    assert isinstance(loaded, list)
    assert isinstance(failed, list)


@pytest.mark.parametrize("fixture", af.FIXTURES, ids=lambda f: f.fixture_id)
def test_fixture_against_registered_extractors(fixture: af.Fixture):
    """Run one fixture through the real registry, or skip WITH A REASON naming what is absent.

    The skip is not a courtesy. It is the honest report that this fixture's
    class is not yet defended, and it names both the kinds nobody produces and
    any sibling module that would not import, so the orchestrator can see which
    lane is missing.
    """
    _loaded, failed = _load_sibling_extractors()
    claimed = ir.registered_kinds()
    unimported = f"; modules that would not import: {failed}" if failed else ""
    if not claimed:
        pytest.skip(
            "no extractor is registered in source_fact_ir/ (ir._REGISTRY is empty); "
            f"unclaimed kinds: {', '.join(ir.unclaimed_kinds())}{unimported}"
        )

    def extract(raw: bytes):
        return ir.extract_all(raw=raw, document={"source_id": fixture.fixture_id})

    outcome = af.check(
        fixture,
        extract(fixture.before),
        extract(fixture.after),
        available_kinds=claimed,
    )
    if outcome.status == af.NOT_EXERCISED:
        pytest.skip(
            f"{fixture.fixture_id} not exercised: {outcome.reason} "
            f"(registered kinds: {', '.join(claimed)}){unimported}"
        )
    assert outcome.status == af.PASS, f"{fixture.requirement} -- {outcome.reason}"
