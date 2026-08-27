"""Tests for the native-provenance adversarial corpus and its checker.

Two halves, matching ``test_sfi_adversarial.py``'s own split and for the same
reason.

**Half one runs now, unconditionally.** Every fixture's ``reference_document``
is built by hand with ``spanmap.TrackedText`` — the frozen provenance spine —
and ``check`` must PASS every one of them. Alongside that, for every
expectation TYPE this corpus uses, a document that VIOLATES it is hand-built
and ``check`` must FAIL it: an expectation nobody has seen fail is not an
expectation.

**Half two** asserts what happens when the real canonicaliser is exercised.
``canonicalization/provenance_document.py`` is owned by a separate,
concurrent workstream. A prior session found its actual entrypoint,
``provenance_document()``, is keyword-only and needs a full document-assembly
context (source_family, source_id, version_id, source_digest, known_at,
valid_from, licence) — not the single raw-bytes argument this corpus
originally assumed — and correctly declined to fabricate a PROVENANCE answer
to force a call through. That left every fixture reporting NOT_EXERCISED,
which has no gate power at all.

The reconciliation (founder ruling, 2026-08-23, quoted in full in
``provenance_fixtures.py``): those seven non-payload parameters are calling
context, not a provenance claim, so supplying them is not the fabrication
that was rightly refused. Each fixture is now wrapped in a real Markdown (or,
for the one fixture that needs it, HTML) heading and padded past
``MIN_TEXT_CHARS`` so ``provenance_document`` actually emits a unit for it,
and every fixture below runs for real. Nine PASS. Three — prov-005, prov-009,
prov-011 — FAIL, and each failure is a genuine finding about the real
canonicaliser, not a fixture defect:

  * **prov-005 (multibyte)**: ``SpanMap.to_source`` answers only at the
    granularity ``to_tracked_text`` actually recorded. Plain, byte-contiguous
    COPY text with no kind change anywhere near the CJK run — no tag, no
    entity, no stripped delimiter — merges into ONE segment spanning the
    whole sentence, so a query for just the CJK sub-range returns that
    whole segment's source bytes, including the neighbouring word
    "Warranty" the fixture asserts must be absent. The map is not
    misattributing; it simply cannot answer narrower than the run it built.
  * **prov-009 (malformed tag)**: neither the Markdown reader's ``HTML_TAG``
    regex nor the ``sec_edgar`` reader's ``HTMLParser`` treats
    ``<b class="term"30 days</a>`` as recoverable content behind a decidable
    boundary. Both silently absorb "30 days" as bogus tag/attribute soup —
    it never reaches canonical text at all, and the unit that remains
    reports ``fully_sourced: True``. That is a third outcome, neither the
    naive wrong-span failure this fixture documents nor the honest
    SpanAbsent+NotFullySourced it hopes for.
  * **prov-011 (derived value)**: ``provenance_document`` has no
    interpolation/substitution mechanism at all — its only unsourced-insert
    path is the single block-join space in ``assemble()``. A literal
    ``{{computed}}`` placeholder is never replaced by anything; it stays
    literal, COPY-sourced text, so "DERIVED-VALUE" never appears in
    canonical output for the real system to make a claim about.

If a later change to either module makes one of these three start passing,
that is real news and this test should be updated to say so — not have it
happen silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))

from source_fact_ir import provenance_fixtures as pf  # noqa: E402
from source_fact_ir.spanmap import TrackedText  # noqa: E402

# ===========================================================================
# half one, part A — the fixture data itself


def test_every_mandated_class_has_a_fixture():
    covered = {f.fixture_class for f in pf.FIXTURES}
    missing = sorted(set(pf.MANDATED_CLASSES) - covered)
    assert not missing, f"mandated fixture classes with no fixture: {missing}"


def test_at_least_twelve_fixtures():
    assert len(pf.FIXTURES) >= 12


def test_fixture_ids_are_unique_and_stable_shape():
    ids = [f.fixture_id for f in pf.FIXTURES]
    assert len(ids) == len(set(ids)), "duplicate fixture id"
    assert all(i.startswith("prov-") for i in ids)
    assert len(pf.BY_ID) == len(pf.FIXTURES)


def test_every_fixture_source_is_raw_bytes():
    for fixture in pf.FIXTURES:
        assert isinstance(fixture.raw, bytes), fixture.fixture_id


def test_every_fixture_names_its_requirement_and_naive_failure():
    for fixture in pf.FIXTURES:
        assert fixture.requirement, fixture.fixture_id
        assert fixture.naive_failure, fixture.fixture_id


def test_every_fixture_class_is_declared():
    unknown = [f.fixture_id for f in pf.FIXTURES if f.fixture_class not in pf.CLASSES]
    assert not unknown, f"fixtures with an undeclared class: {unknown}"


def test_inventory_is_serialisable_and_one_row_per_fixture():
    rows = pf.inventory()
    assert len(rows) == len(pf.FIXTURES)
    for row in rows:
        assert row["raw_sha256"].startswith("sha256:")
        assert row["expectation"]["describes"]


# ===========================================================================
# half one, part B — every reference document satisfies its own fixture
#
# This is the corpus proving the ruling is satisfiable at all: each document
# below is built by construction with TrackedText, the same discipline a real
# canonicaliser must follow, and `check` must agree it is correct.


@pytest.mark.parametrize("fixture", pf.FIXTURES, ids=lambda f: f.fixture_id)
def test_reference_document_passes_its_own_fixture(fixture: pf.Fixture):
    document = fixture.reference_document()
    outcome = pf.check(fixture, document)
    assert outcome.status == pf.PASS, (
        f"{fixture.fixture_id}: reference document (built by construction) does not satisfy "
        f"its own fixture — {outcome.reason}"
    )
    assert outcome.passed


def test_reference_documents_are_rebuilt_fresh_each_call():
    """`reference_document` is a callable, not a shared mutable value.

    A SpanMap is frozen and TrackedText is single-use, so this mostly guards
    against a fixture accidentally memoising a document across calls in a way
    that would let one test's mutation leak into another's.
    """
    for fixture in pf.FIXTURES:
        first = fixture.reference_document()
        second = fixture.reference_document()
        assert first is not second, fixture.fixture_id
        assert first == second or first["units"][0]["text"] == second["units"][0]["text"]


# ===========================================================================
# half one, part C — gate power: every expectation type has a failure witness
#
# A checker nobody has watched fail is a decoration. For each expectation type
# used by this corpus, build a document that violates it and assert `check`
# returns FAIL with a reason naming the violation.


def _one_unit_doc(explicit_path, text, tracked: TrackedText) -> dict:
    span_map = tracked.map
    return {
        "units": [
            {
                "explicit_path": list(explicit_path),
                "text": text,
                "source_span": span_map.to_source(0, len(text)),
                "fully_sourced": span_map.is_fully_sourced(0, len(text)),
                "span_map": span_map,
            }
        ]
    }


def test_gate_span_covers_bytes_must_contain_can_fail():
    """A span that misses the required bytes entirely — the plain miss case."""
    fixture = pf.BY_ID["prov-001-entity-decoding"]
    tracked = TrackedText()
    #: the entity's own span, correctly emitted this time as the WRONG bytes:
    #: pretend the whole unit came from "Meeting at caf" only, so the "é"
    #: character has no entity behind it at all.
    tracked.copy("Meeting at café today.", 0, len(b"Meeting at caf"))
    bad = _one_unit_doc(("meeting",), tracked.text, tracked)
    outcome = pf.check(fixture, bad)
    assert outcome.status == pf.FAIL
    assert "does not contain" in outcome.reason


def test_gate_span_covers_bytes_must_not_contain_can_fail():
    """A span that satisfies must_contain but ALSO contains the forbidden bytes.

    Isolated from any one fixture on purpose: must_contain and must_not_contain
    are independent checks, and a witness for must_not_contain has to show it
    catching a violation even when must_contain alone would have passed —
    otherwise it is impossible to tell which of the two checks actually fired.
    """
    raw = b"keep this region but also avoid this word"
    tracked = TrackedText()
    tracked.copy("irrelevant unit text", 0, len(raw))
    doc = _one_unit_doc(("x",), tracked.text, tracked)
    expectation = pf.SpanCoversBytes(("x",), must_contain=b"keep", must_not_contain=b"avoid")
    held, reason, _ = expectation.evaluate(doc, raw=raw)
    assert held is False
    assert "must not" in reason


def test_gate_span_covers_bytes_wrong_occurrence_is_caught():
    """The duplicate-content shape itself: text and byte range from two occurrences."""
    fixture = pf.BY_ID["prov-010-duplicate-content-second-occurrence"]
    #: unit "second"'s text is correct ("Policy B") but its span points at unit
    #: "first"'s bytes (which spell "Policy A") instead of its own — the exact
    #: raw.find(text) bug this fixture exists to catch.
    tracked = TrackedText()
    tracked.copy(pf._DUP_SHARED + pf._DUP2_TAIL, pf._DUP_OFF[1], pf._DUP_OFF[2])
    bad = _one_unit_doc(("duplicate", "second"), tracked.text, tracked)
    outcome = pf.check(fixture, bad)
    assert outcome.status == pf.FAIL


def test_gate_span_covers_bytes_missing_unit_can_fail():
    fixture = pf.BY_ID["prov-007-link-text-vs-target"]
    outcome = pf.check(fixture, {"units": []})
    assert outcome.status == pf.FAIL
    assert "no unit matching hint" in outcome.reason


def test_gate_span_covers_bytes_no_source_can_fail():
    fixture = pf.BY_ID["prov-003-markup-stripping"]
    tracked = TrackedText()
    tracked.insert("This is bold text.")  # every byte inserted: no source anywhere
    bad = _one_unit_doc(("markup",), tracked.text, tracked)
    outcome = pf.check(fixture, bad)
    assert outcome.status == pf.FAIL
    assert "no source span" in outcome.reason


def test_gate_fully_sourced_can_fail():
    """`FullySourced` is used inside a real fixture only via its negation in
    this corpus, so it is exercised directly here against a partially-sourced
    unit — the property must be able to say no."""
    tracked = TrackedText()
    tracked.copy("known ", 0, 6)
    tracked.insert("unknown")
    doc = _one_unit_doc(("mixed",), tracked.text, tracked)
    expectation = pf.FullySourced(("mixed",))
    held, reason, _ = expectation.evaluate(doc, raw=b"known ")
    assert held is False
    assert "not fully sourced" in reason


def test_gate_not_fully_sourced_can_fail():
    fixture = pf.BY_ID["prov-004-block-composition-join"]
    #: build a document where nothing is inserted, so the unit IS fully
    #: sourced — violating the fixture's expectation that a separator exists.
    tracked = TrackedText()
    tracked.copy("First block text here. Second block text here.", 0, len(pf._BLOCK_JOIN_RAW))
    bad = _one_unit_doc(("joined",), tracked.text, tracked)
    outcome = pf.check(fixture, bad)
    assert outcome.status == pf.FAIL
    #: AllOf fails on its first failing part; with nothing inserted, the
    #: separator range DOES have a source, so SpanAbsent (part 0) fails first.
    assert "part 0" in outcome.reason


def test_gate_span_absent_can_fail():
    fixture = pf.BY_ID["prov-009-malformed-tag-fails-closed"]
    #: a forgiving parser that DOES claim a source for "30 days" behind the
    #: broken tag — the exact naive failure this fixture documents.
    tracked = TrackedText()
    tracked.copy("Retention period ", len(b"<p>"), len(b"<p>Retention period "))
    guessed_start = len(pf._MAL_BEFORE) + len(pf._MAL_BROKEN)
    tracked.copy("30 days", guessed_start, guessed_start + len("30 days"))
    bad = _one_unit_doc(("malformed",), tracked.text, tracked)
    outcome = pf.check(fixture, bad)
    assert outcome.status == pf.FAIL
    assert "part 0" in outcome.reason


def test_gate_all_of_reports_the_failing_part_index():
    good = pf.SpanAbsent(("x",), within=(0, 1))
    bad = pf.SpanAbsent(("x",), within=(0, 1))
    combo = pf.AllOf((good, bad))
    tracked = TrackedText()
    tracked.copy("a", 0, 1)
    doc = _one_unit_doc(("x",), "a", tracked)
    # both parts here actually check the same thing (source present, so
    # SpanAbsent fails on part 0 already)
    held, reason, detail = combo.evaluate(doc, raw=b"a")
    assert held is False
    assert "part 0" in reason
    assert detail["part_0"]["held"] is False


#: Every expectation type this file has demonstrated `check` can actually FAIL
#: on, in the tests above. Register a type here only next to the test that
#: witnesses its failure.
_WITNESSED_EXPECTATION_TYPES: frozenset[type] = frozenset(
    {pf.SpanCoversBytes, pf.FullySourced, pf.NotFullySourced, pf.SpanAbsent, pf.AllOf}
)


def _expectation_types_in_use() -> set[type]:
    """Every expectation type FIXTURES actually exercises, AllOf unwrapped."""
    found: set[type] = set()

    def walk(expectation: pf.Expectation) -> None:
        found.add(type(expectation))
        if isinstance(expectation, pf.AllOf):
            for part in expectation.parts:
                walk(part)

    for fixture in pf.FIXTURES:
        walk(fixture.expectation)
    return found


def test_every_expectation_type_in_use_has_a_failure_witness():
    """An expectation nobody has seen fail is not an expectation.

    If a new expectation type is added to FIXTURES without a gate-power test
    proving `check` can FAIL on it, this fails and names the type — the same
    guard `test_sfi_adversarial.py` does not have but should, and this corpus
    was asked for explicitly.
    """
    used = _expectation_types_in_use()
    missing = used - _WITNESSED_EXPECTATION_TYPES
    assert not missing, (
        f"expectation type(s) {sorted(t.__name__ for t in missing)} appear in FIXTURES but have "
        "no gate-power test demonstrating check() can FAIL on them; add one and register the "
        "type in _WITNESSED_EXPECTATION_TYPES"
    )


# ===========================================================================
# half one, part D — expectation construction refuses nonsense inputs


def test_span_covers_bytes_requires_at_least_one_check():
    with pytest.raises(ValueError):
        pf.SpanCoversBytes(("x",))


def test_span_covers_bytes_rejects_backwards_range():
    with pytest.raises(ValueError):
        pf.SpanCoversBytes(("x",), must_contain=b"a", within=(5, 1))


def test_span_absent_rejects_backwards_range():
    with pytest.raises(ValueError):
        pf.SpanAbsent(("x",), within=(5, 1))


def test_not_fully_sourced_requires_a_reason():
    with pytest.raises(ValueError):
        pf.NotFullySourced(("x",), why="")


def test_all_of_requires_at_least_two_parts():
    with pytest.raises(ValueError):
        pf.AllOf((pf.FullySourced(("x",)),))


def test_fixture_rejects_unknown_class():
    with pytest.raises(ValueError):
        pf.Fixture(
            fixture_id="bad",
            fixture_class="NOT_A_REAL_CLASS",
            raw=b"x",
            requirement="r",
            expectation=pf.FullySourced(("x",)),
            naive_failure="n",
            reference_document=lambda: {"units": []},
        )


def test_fixture_rejects_str_source():
    with pytest.raises(ValueError):
        pf.Fixture(
            fixture_id="bad",
            fixture_class=pf.ENTITY_DECODING,
            raw="not bytes",  # type: ignore[arg-type]
            requirement="r",
            expectation=pf.FullySourced(("x",)),
            naive_failure="n",
            reference_document=lambda: {"units": []},
        )


# ===========================================================================
# half one, part E — outcome hygiene


def test_outcome_requires_a_reason():
    with pytest.raises(ValueError):
        pf.Outcome("id", pf.PASS, "")


def test_outcome_rejects_unknown_status():
    with pytest.raises(ValueError):
        pf.Outcome("id", "MAYBE", "because")


def test_not_exercised_is_never_a_pass():
    outcome = pf.Outcome("id", pf.NOT_EXERCISED, "nothing ran")
    assert outcome.passed is False


# ===========================================================================
# half two — running the corpus through the real canonicaliser
#
# canonicalization.provenance_document now exists, and _load_canonicaliser's
# metadata-kwargs contract now matches it — this section documents the real,
# current, exercised result: nine PASS, three genuine FAIL. See the module
# docstring above for why each of the three fails and why that is real news
# about the canonicaliser, not a fixture defect.


def test_canonicaliser_entrypoint_now_matches_this_corpus_contract():
    """The metadata-kwargs reconciliation actually closes the integration gap.

    If this starts failing, the entrypoint contract has drifted again —
    that is real news, and the right response is to look at what
    ``provenance_document`` requires now and update
    ``CANONICALISER_METADATA_KEYS``/``_fixture_metadata_kwargs`` to match,
    not to quietly delete this assertion.
    """
    entrypoint, reason = pf._load_canonicaliser()
    assert entrypoint is not None, reason
    assert reason is None


#: The three fixtures that FAIL against the real canonicaliser today, and why
#: — named here once so the per-fixture test below and ``check_all`` both
#: read from the same honest ledger. Every entry is a genuine finding about
#: ``canonicalization.provenance_document``, established by running the real
#: entrypoint, not a fixture that was loosened to match it. See the module
#: docstring for the full explanation of each.
EXPECTED_REAL_FAILURES: dict[str, str] = {
    "prov-005-utf8-multibyte": (
        "SpanMap.to_source answers at run granularity: the CJK run is byte-contiguous "
        "COPY text with no neighbouring kind-change, so it merges with the surrounding "
        "sentence into one segment and a narrow query returns the whole segment, "
        "including the forbidden neighbouring word"
    ),
    "prov-009-malformed-tag-fails-closed": (
        "neither reader treats the unterminated tag as recoverable content behind a "
        "decidable boundary; '30 days' is absorbed as bogus tag/attribute soup and never "
        "reaches canonical text, so the SpanAbsent locator cannot even find the region"
    ),
    "prov-011-text-not-in-source": (
        "provenance_document has no interpolation/substitution mechanism — its only "
        "unsourced-insert path is the single block-join space — so a literal "
        "'{{computed}}' placeholder is never replaced and 'DERIVED-VALUE' never appears "
        "in canonical text for the SpanAbsent locator to find"
    ),
}


def test_every_fixture_is_exercised_through_the_real_canonicaliser():
    """not_exercised == 0: the entrypoint mismatch that used to block every fixture is closed."""
    for fixture in pf.FIXTURES:
        outcome = pf.check_through_canonicaliser(fixture)
        assert outcome.status != pf.NOT_EXERCISED, (
            f"{fixture.fixture_id} reported NOT_EXERCISED: {outcome.reason}"
        )


def test_real_canonicaliser_results_match_the_honest_ledger():
    """Nine fixtures PASS for real; the three that FAIL do so for the documented reason.

    This is intentionally not a blanket 'all green' assertion. A fixture
    moving off this list without the module docstring being updated to
    explain why is exactly the silent-pass-by-accident this corpus exists to
    prevent.
    """
    for fixture in pf.FIXTURES:
        outcome = pf.check_through_canonicaliser(fixture)
        if fixture.fixture_id in EXPECTED_REAL_FAILURES:
            assert outcome.status == pf.FAIL, (
                f"{fixture.fixture_id}: expected a documented FAIL, got {outcome.status} — "
                f"{outcome.reason}"
            )
        else:
            assert outcome.status == pf.PASS, (
                f"{fixture.fixture_id}: expected PASS, got {outcome.status} — {outcome.reason}"
            )


def test_check_all_reports_the_real_mixed_result_honestly():
    summary = pf.check_all()
    assert summary["total"] == len(pf.FIXTURES)
    assert summary["not_exercised"] == 0
    assert summary["failed"] == len(EXPECTED_REAL_FAILURES)
    assert set(summary["failing"]) == set(EXPECTED_REAL_FAILURES)
    assert summary["passed"] == len(pf.FIXTURES) - len(EXPECTED_REAL_FAILURES)
    assert summary["all_exercised_and_passed"] is False


def test_no_fixtures_padding_leaks_a_must_not_contain_byte_string():
    """Padding is filler, not part of the check. It must never be why a fixture passes or fails.

    Walks every expectation (AllOf unwrapped) collecting each
    ``must_not_contain`` byte string, and asserts none of a fixture's own
    declared padding segments contain it.
    """

    def _must_not_contains(expectation: pf.Expectation) -> list[bytes]:
        if isinstance(expectation, pf.AllOf):
            found: list[bytes] = []
            for part in expectation.parts:
                found.extend(_must_not_contains(part))
            return found
        value = getattr(expectation, "must_not_contain", None)
        return [value] if value is not None else []

    checked_any = False
    for fixture in pf.FIXTURES:
        for forbidden in _must_not_contains(fixture.expectation):
            checked_any = True
            for segment in fixture.padding:
                assert forbidden not in segment, (
                    f"{fixture.fixture_id}: padding segment {segment!r} contains the forbidden "
                    f"byte string {forbidden!r} — padding must never be able to satisfy or "
                    "violate a fixture's own check"
                )
    assert checked_any, "no must_not_contain values were found to check — the test is a no-op"


def test_a_crashing_canonicaliser_is_a_failure_not_a_skip(monkeypatch):
    """If the real module raises, that must FAIL, not skip."""

    def _boom(**_kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(pf, "_load_canonicaliser", lambda: (_boom, None))
    fixture = pf.FIXTURES[0]
    outcome = pf.check_through_canonicaliser(fixture)
    assert outcome.status == pf.FAIL
    assert "boom" in outcome.reason


def test_a_wired_up_canonicaliser_can_actually_pass(monkeypatch):
    """Proves NOT_EXERCISED is a real absence, not a hardcoded ceiling.

    Swap in the fixture's own reference builder as if it were the real
    canonicaliser; `check_through_canonicaliser` must then report PASS.
    """
    fixture = pf.BY_ID["prov-001-entity-decoding"]

    def _stub(**_kwargs: object) -> dict:
        return fixture.reference_document()

    monkeypatch.setattr(pf, "_load_canonicaliser", lambda: (_stub, None))
    outcome = pf.check_through_canonicaliser(fixture)
    assert outcome.status == pf.PASS
    assert outcome.passed is True
