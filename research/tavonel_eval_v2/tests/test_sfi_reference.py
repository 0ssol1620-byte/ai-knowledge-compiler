"""Tests for the lane-2 reference/locator facet extractor.

No network, no on-disk fixtures — every source document is an inline byte
string built in this file, and `document` dicts come from the real
canonicalizer (`canonical_document`) so the round-trip test exercises the
actual pipeline shape rather than a hand-rolled stand-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))

from canonicalization.canonical_document import canonical_document  # noqa: E402
from source_fact_ir import ir  # noqa: E402
from source_fact_ir.reference import reference_extractor  # noqa: E402

PADDING = (
    "This paragraph exists only to push the section body past the "
    "canonicalizer's minimum-text-length threshold so the heading actually "
    "produces a unit in the compiled document. It carries no test signal "
    "of its own beyond its length."
)


def _doc(payload: bytes, source_family: str = "wiki") -> dict:
    return canonical_document(
        source_family=source_family,
        source_id="test-source",
        version_id="v1",
        payload=payload,
        source_digest="sha256:0" * 8,
        known_at=None,
        valid_from=None,
        licence="cc0",
    )


def _only(facts, **predicates):
    matches = [
        f for f in facts
        if all(
            (getattr(f, key) if key != "construct" else f.witness.construct) == value
            for key, value in predicates.items()
        )
    ]
    message = f"expected exactly one match for {predicates}, got {len(matches)}: {matches}"
    assert len(matches) == 1, message
    return matches[0]


# ---------------------------------------------------------------------------
# 1. visible text unchanged, href changed -> same fact_id, different representation


def test_href_change_with_unchanged_text_same_identity_different_representation():
    raw_a = (
        b"# Heading\n\n"
        + PADDING.encode() + b"\n\n"
        + b"See [docs](https://example.com/a) for details.\n"
    )
    raw_b = raw_a.replace(b"/a)", b"/b)")
    assert len(raw_a) == len(raw_b)

    facts_a = reference_extractor.extract(raw=raw_a, document={})
    facts_b = reference_extractor.extract(raw=raw_b, document={})

    link_a = _only(facts_a, kind=ir.REFERENCE_TARGET, construct="md-inline-link")
    link_b = _only(facts_b, kind=ir.REFERENCE_TARGET, construct="md-inline-link")

    # Identity is witness-derived (kind + construct + unit_path + byte_start).
    # The text before the link is untouched and the replacement is the same
    # byte length, so byte_start does not shift and the identity holds.
    assert link_a.fact_id == link_b.fact_id
    assert link_a.representation != link_b.representation
    assert link_a.representation["normalized"].endswith("/a")
    assert link_b.representation["normalized"].endswith("/b")


# ---------------------------------------------------------------------------
# 2. a reference definition changed outside the referencing unit's span is
# still extracted, and the use resolves to it regardless of distance


def test_reference_definition_outside_referencing_unit_still_extracted():
    raw = (
        b"# Section One\n\n"
        + PADDING.encode() + b"\n\n"
        + b"See [ref link][mylabel] in this section.\n\n"
        + b"# Section Two\n\n"
        + PADDING.encode() + b"\n\n"
        + b'[mylabel]: https://example.com/target "Title"\n'
    )
    facts = reference_extractor.extract(raw=raw, document={})

    definition = _only(facts, kind=ir.REFERENCE_DEFINITION)
    use = _only(facts, kind=ir.REFERENCE_TARGET, construct="md-ref-use-full")

    assert definition.state == ir.REPRESENTED
    assert use.state == ir.REPRESENTED
    assert use.representation["target"]["normalized"] == definition.representation["normalized"]
    # The definition lives well after the use, in a different section.
    assert definition.witness.byte_start > use.witness.byte_end


# ---------------------------------------------------------------------------
# 3. an include/shortcode target change is extracted as INCLUDE_TARGET


def test_include_shortcode_target_change_extracted():
    raw_a = b'{{< include "chapters/one.md" >}}\n'
    raw_b = raw_a.replace(b"one.md", b"two.md")
    assert len(raw_a) == len(raw_b)

    fact_a = _only(
        reference_extractor.extract(raw=raw_a, document={}),
        kind=ir.INCLUDE_TARGET, construct="hugo-shortcode-include",
    )
    fact_b = _only(
        reference_extractor.extract(raw=raw_b, document={}),
        kind=ir.INCLUDE_TARGET, construct="hugo-shortcode-include",
    )

    assert fact_a.fact_id == fact_b.fact_id
    assert fact_a.representation["normalized"] != fact_b.representation["normalized"]
    assert fact_a.representation["normalized"].endswith("one.md")
    assert fact_b.representation["normalized"].endswith("two.md")


# ---------------------------------------------------------------------------
# 4. entity-encoded and percent-encoded targets that are genuinely equivalent
# normalise together


def test_entity_and_percent_encoding_normalize_together():
    raw = b"[a](foo&amp;bar.md) [b](foo&bar.md) [c](foo%2Dbar.md) [d](foo-bar.md)\n"
    facts = reference_extractor.extract(raw=raw, document={})
    represented = [f for f in facts if f.kind == ir.REFERENCE_TARGET and f.state == ir.REPRESENTED]
    assert len(represented) == 4

    normalized = [f.representation["normalized"] for f in represented]
    # a and b both decode the entity to a literal `&`
    assert normalized[0] == normalized[1] == "foo&bar.md"
    # c decodes %2D (unreserved) to `-`, matching d's literal hyphen
    assert normalized[2] == normalized[3] == "foo-bar.md"


# ---------------------------------------------------------------------------
# 5. an ambiguous/malformed target fails closed as UNRESOLVED, never dropped


def test_malformed_target_fails_closed_as_unresolved():
    raw = b"before [bad link](tar get.md) after\n"
    facts = reference_extractor.extract(raw=raw, document={})

    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="md-inline-link")
    assert fact.state == ir.UNRESOLVED
    assert fact.reason
    assert fact.representation is None


def test_unresolvable_reference_use_fails_closed_as_unresolved():
    raw = b"[Missing][nope] and no definition anywhere.\n"
    facts = reference_extractor.extract(raw=raw, document={})

    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="md-ref-use-full")
    assert fact.state == ir.UNRESOLVED
    assert "nope" in fact.reason
    assert fact.representation is None


# ---------------------------------------------------------------------------
# 6. every fact's witness verifies against the raw bytes


def test_every_witness_verifies_against_raw():
    raw = (
        b"# Heading\n\n"
        + PADDING.encode() + b"\n\n"
        + b'[Example](https://example.com/page) and '
        + b'![Alt text](images/pic.png) and '
        + b'[Docs][ref1] and [Missing][nope] and '
        + b'<https://example.org/auto> and '
        + b'<a href="mailto:x@example.com">Email</a> and '
        + b'<img src="pic2.png"> and '
        + b'{{< include "chapters/one.md" >}} and '
        + b'{{% include %}} and '
        + b'{{Template:Foo}} and '
        + b'[bad](tar get.md)\n\n'
        + b'[ref1]: /internal/path "Title"\n'
    )
    document = _doc(raw)
    facts = reference_extractor.extract(raw=raw, document=document)
    assert facts, "fixture produced no facts at all"
    for fact in facts:
        assert fact.witness.verify(raw), f"witness failed to verify for {fact.witness}"


# ---------------------------------------------------------------------------
# 7. an HTML <a href> whose anchor text is unchanged produces a moved
# representation


def test_html_anchor_href_change_with_unchanged_text():
    raw_a = b'<p>See <a href="https://example.com/x">this page</a> for more.</p>\n'
    raw_b = raw_a.replace(b'/x"', b'/y"')
    assert len(raw_a) == len(raw_b)

    fact_a = _only(
        reference_extractor.extract(raw=raw_a, document={}),
        kind=ir.REFERENCE_TARGET, construct="html-a-href",
    )
    fact_b = _only(
        reference_extractor.extract(raw=raw_b, document={}),
        kind=ir.REFERENCE_TARGET, construct="html-a-href",
    )

    assert fact_a.fact_id == fact_b.fact_id
    assert fact_a.representation != fact_b.representation
    assert fact_a.representation["normalized"].endswith("/x")
    assert fact_b.representation["normalized"].endswith("/y")


# ---------------------------------------------------------------------------
# 8. round-trip: ir.tally() over a fixture matches the states expected, and
# no fact is lost between input constructs and output facts


def test_tally_round_trip_matches_expected_states():
    raw = (
        b"# Heading\n\n"
        + PADDING.encode() + b"\n\n"
        # 1: REPRESENTED external link
        + b'[Example](https://example.com/page) '
        # 2: REPRESENTED relative image
        + b'![Alt text](images/pic.png) '
        # 3: REPRESENTED reference-style use, resolved by def below
        + b'[Docs][ref1] '
        # 4 (def, counted separately below): REPRESENTED reference definition
        # 5: UNRESOLVED — no matching definition
        + b'[Missing][nope] '
        # 6: REPRESENTED autolink
        + b'<https://example.org/auto> '
        # 7: IGNORED — mailto: is POLICY-REF-001
        + b'<a href="mailto:x@example.com">Email</a> '
        # 8: REPRESENTED html img src
        + b'<img src="pic2.png"> '
        # 9: REPRESENTED hugo include shortcode
        + b'{{< include "chapters/one.md" >}} '
        # 10: UNRESOLVED — include shortcode with no quoted argument
        + b'{{% include %}} '
        # 11: REPRESENTED mediawiki template
        + b'{{Template:Foo}} '
        # 12: UNRESOLVED — malformed target (unescaped space)
        + b'[bad](tar get.md)\n\n'
        + b'[ref1]: /internal/path "Title"\n'
    )
    document = _doc(raw)
    facts = reference_extractor.extract(raw=raw, document=document)
    counts = ir.tally(facts)

    # 8 REPRESENTED constructs above + 1 REPRESENTED locator for the one
    # heading unit the fixture produces.
    assert counts[ir.REPRESENTED] == 9
    assert counts[ir.UNRESOLVED] == 3
    assert counts[ir.IGNORED] == 1
    assert counts[ir.UNREPRESENTED] == 0
    assert sum(counts.values()) == len(facts)

    # Nothing from the twelve embedded constructs is missing: every one
    # produced exactly the fact kind it was supposed to.
    reference_targets = [f for f in facts if f.kind == ir.REFERENCE_TARGET]
    definitions = [f for f in facts if f.kind == ir.REFERENCE_DEFINITION]
    includes = [f for f in facts if f.kind == ir.INCLUDE_TARGET]
    locators = [f for f in facts if f.kind == ir.LOCATOR]

    # example, image, ref-use, missing, autolink, mailto, img, malformed
    assert len(reference_targets) == 8
    assert len(definitions) == 1
    assert len(includes) == 3  # hugo include, hugo unresolved, mediawiki
    assert len(locators) == 1


# ---------------------------------------------------------------------------
# malformed reference definition also fails closed (not part of the numbered
# list above, but the same rule the ruling states for definitions too)


def test_malformed_reference_definition_fails_closed():
    raw = b"[label]: tar get.md\n"
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.REFERENCE_DEFINITION)
    assert fact.state == ir.UNRESOLVED
    assert fact.reason
    assert fact.representation is None


# ---------------------------------------------------------------------------
# collapsed reference use `[text][]` resolves against the label == text


def test_collapsed_reference_use_resolves():
    raw = b"[MyLabel][] and\n\n[mylabel]: /somewhere\n"
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="md-ref-use-collapsed")
    assert fact.state == ir.REPRESENTED
    assert fact.representation["label"] == "MyLabel"
    assert fact.representation["target"]["normalized"] == "/somewhere"


# ---------------------------------------------------------------------------
# locator: declared pandoc-style {#id} fragment vs derived slug fragment


def test_locator_declared_and_derived_fragment():
    raw = (
        b"# Custom Heading {#my-custom-id}\n\n"
        + PADDING.encode() + b"\n\n"
        + b"# Plain Heading\n\n"
        + PADDING.encode() + b"\n"
    )
    document = _doc(raw)
    facts = reference_extractor.extract(raw=raw, document=document)
    locators = [f for f in facts if f.kind == ir.LOCATOR]
    assert len(locators) == 2

    declared = next(f for f in locators if f.representation["fragment_source"] == "declared")
    derived = next(f for f in locators if f.representation["fragment_source"] == "derived")

    assert declared.representation["fragment"] == "my-custom-id"
    assert derived.representation["fragment"] == "plain-heading"

    for fact in locators:
        assert fact.witness.verify(raw)


# ---------------------------------------------------------------------------
# every fact must leave this extractor anchored: witness.unit_path is never
# None, and is always document-qualified (source_id first)


def test_every_fact_has_a_document_qualified_unit_path():
    raw = (
        b"# Heading\n\n"
        + PADDING.encode() + b"\n\n"
        + b'[Example](https://example.com/page) '
        + b'<a href="#schedule">the schedule</a> '
        + b'<h1 id="schedule">Retention</h1> '
        + b'{{< include "chapters/one.md" >}} '
        + b'[bad](tar get.md)\n\n'
    )
    document = _doc(raw)
    facts = reference_extractor.extract(raw=raw, document=document)
    assert facts
    for fact in facts:
        assert fact.witness.unit_path is not None, fact
        assert fact.witness.unit_path[0] == document["source_id"]

    # A document handed with no "units" at all (the shape the adversarial
    # harness uses) must still anchor every fact -- to document scope, never
    # to nothing.
    bare_document = {"source_id": "bare-doc"}
    bare_facts = reference_extractor.extract(raw=raw, document=bare_document)
    assert bare_facts
    for fact in bare_facts:
        assert fact.witness.unit_path == ("bare-doc",)


# ---------------------------------------------------------------------------
# adv-010: a #fragment target is only decidable through a unique declared id


def test_fragment_target_with_duplicate_id_is_unresolved():
    raw = (
        b'<h1 id="schedule">Retention</h1>'
        b'<p id="schedule">See <a href="#schedule">the schedule</a>.</p>\n'
    )
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="html-a-href")
    assert fact.state == ir.UNRESOLVED
    assert "ambiguous" in fact.reason
    assert fact.representation is None


def test_fragment_target_with_undeclared_id_is_unresolved():
    raw = b'<a href="#missing">See it</a>\n'
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="html-a-href")
    assert fact.state == ir.UNRESOLVED
    assert "not declared" in fact.reason


def test_fragment_target_with_unique_id_is_represented():
    raw = b'<h1 id="schedule">Retention</h1><a href="#schedule">the schedule</a>\n'
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.REFERENCE_TARGET, construct="html-a-href")
    assert fact.state == ir.REPRESENTED
    assert fact.representation["fragment"] == "schedule"


# ---------------------------------------------------------------------------
# adv-003 / adv-016: Jinja/Liquid-style single-brace include


def test_jinja_include_literal_target_changed():
    raw_a = b'{% include "partials/schedule-v1.md" %}\n'
    raw_b = raw_a.replace(b"v1.md", b"v2.md")
    fact_a = _only(
        reference_extractor.extract(raw=raw_a, document={}),
        kind=ir.INCLUDE_TARGET, construct="jinja-include",
    )
    fact_b = _only(
        reference_extractor.extract(raw=raw_b, document={}),
        kind=ir.INCLUDE_TARGET, construct="jinja-include",
    )
    assert fact_a.state == ir.REPRESENTED
    assert fact_a.fact_id == fact_b.fact_id
    assert fact_a.representation["normalized"] != fact_b.representation["normalized"]


def test_jinja_include_computed_target_is_unrepresented_not_silent():
    raw = b'{% include "partials/schedule-" ~ region ~ ".md" %}\n'
    facts = reference_extractor.extract(raw=raw, document={})
    fact = _only(facts, kind=ir.INCLUDE_TARGET, construct="jinja-include")
    assert fact.state == ir.UNREPRESENTED
    assert fact.reason
    assert fact.representation is None


def test_jinja_include_does_not_double_count_a_hugo_percent_shortcode():
    # `{{% include "x" %}}` and the Jinja tag `{% include "x" %}` overlap
    # syntactically (the Hugo form's inner span reads as a valid Jinja tag).
    # This must be seen once, by the Hugo path, not twice.
    raw = b'{{% include "chapters/one.md" %}}\n'
    facts = reference_extractor.extract(raw=raw, document={})
    include_facts = [f for f in facts if f.kind == ir.INCLUDE_TARGET]
    assert len(include_facts) == 1
    assert include_facts[0].witness.construct == "hugo-shortcode-include"
