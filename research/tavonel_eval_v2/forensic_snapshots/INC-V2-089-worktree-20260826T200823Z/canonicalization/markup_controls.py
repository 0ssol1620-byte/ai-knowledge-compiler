"""Adversarial controls for MARKUP_SEMANTICS_V1.

Each control is a **pair of sources** that differ in exactly one construct, plus
the facet and state the difference must produce. Pairs rather than single
documents, because the claim under test is not "this attribute is classified
somehow" but "a change to this attribute changes the compiled interpretation" —
and only a pair can show that.

The eighth control is the one that keeps the policy honest in the other
direction: a genuinely decorative attribute must remain ignorable. Without it a
policy that classified everything as meaningful would pass all seven others
while being useless.

Nothing here is drawn from the P4e cohort. The corpus was surveyed to learn
which constructs *exist* — 65,485 `class`, 58,014 `href`, 15,415 `&#160;`,
1,198 `colspan`, 194 XBRL `contextref` — which is permitted development
evidence. What each construct *means* is decided by the semantic-effect rule,
never by how much eligibility a classification would buy.
"""

from __future__ import annotations

from typing import Any

from markup_policy import (
    ACCESSIBILITY,
    CONTENT_LEXICAL,
    EXTERNAL_DEPENDENCY,
    IGNORED,
    METADATA,
    MODELED,
    REFERENCE_LOCATOR,
    STRUCTURAL,
    UNRESOLVED,
)

CONTROLS: tuple[dict[str, Any], ...] = (
    {
        "name": "rowspan_changes_table_association",
        "construct": "colspan",
        "kind": "attribute",
        "expect_state": MODELED,
        "expect_facet": STRUCTURAL,
        "guards": "a span change moves which header a cell answers to",
        "before": '<table><tr><th>Year</th><th>Amount</th></tr>'
                  '<tr><td colspan="1">2025</td><td>100</td></tr></table>',
        "after": '<table><tr><th>Year</th><th>Amount</th></tr>'
                 '<tr><td colspan="2">2025</td><td>100</td></tr></table>',
        "differs_in": "colspan 1 → 2",
        "same_visible_tokens": True,
    },
    {
        "name": "alt_changes_accessible_content",
        "construct": "alt",
        "kind": "attribute",
        "expect_state": MODELED,
        "expect_facet": ACCESSIBILITY,
        "guards": "for a non-visual consumer the alternative text IS the content",
        "before": '<img src="/chart.png" alt="Revenue rose in 2025">',
        "after": '<img src="/chart.png" alt="Revenue fell in 2025">',
        "differs_in": "the entire accessible content, with no visible text at all",
        "same_visible_tokens": True,
    },
    {
        "name": "lang_changes_interpretation",
        "construct": "lang",
        "kind": "attribute",
        "expect_state": MODELED,
        "expect_facet": METADATA,
        "guards": "the same characters mean different things in different languages",
        "before": '<p lang="en">chat</p>',
        "after": '<p lang="fr">chat</p>',
        "differs_in": "the declared language; the text is byte-identical",
        "same_visible_tokens": True,
    },
    {
        "name": "rel_changes_relationship",
        "construct": "rel",
        "kind": "attribute",
        "expect_state": MODELED,
        "expect_facet": REFERENCE_LOCATOR,
        "guards": "canonical, nofollow and license assert different things about the same URL",
        "before": '<link rel="canonical" href="https://example.invalid/a">',
        "after": '<link rel="nofollow" href="https://example.invalid/a">',
        "differs_in": "the asserted relationship, with the destination unchanged",
        "same_visible_tokens": True,
    },
    {
        "name": "charref_changes_canonical_text",
        "construct": "&#160;",
        "kind": "character_reference",
        "expect_state": MODELED,
        "expect_facet": CONTENT_LEXICAL,
        "guards": "a reference produces a real character in the canonical text",
        "before": "<p>10&#160;000</p>",
        "after": "<p>10&#8212;000</p>",
        "differs_in": "a non-breaking space becomes an em dash — ten thousand becomes a range",
        "same_visible_tokens": False,
    },
    {
        "name": "nesting_changes_structure_same_tokens",
        "construct": "li",
        "kind": "tag",
        "expect_state": MODELED,
        "expect_facet": STRUCTURAL,
        "guards": (
            "the visible token sequence is identical and the structure is not. "
            "A policy that ignored tags would call these two documents the same"
        ),
        "before": "<ul><li>alpha<ul><li>beta</li></ul></li></ul>",
        "after": "<ul><li>alpha</li><li>beta</li></ul>",
        "differs_in": "beta is a child of alpha, or a sibling of it",
        "same_visible_tokens": True,
    },
    {
        "name": "class_external_dependency_unresolved",
        "construct": "class",
        "kind": "attribute",
        "expect_state": UNRESOLVED,
        "expect_facet": EXTERNAL_DEPENDENCY,
        "guards": (
            "an external rule may hide or reorder this. Neither MODELED nor "
            "IGNORED is honest, which is why the third state exists"
        ),
        "before": '<p class="note">Records are retained for seven years.</p>',
        "after": '<p class="sr-only">Records are retained for seven years.</p>',
        "differs_in": "a class that may or may not hide the paragraph, decided elsewhere",
        "same_visible_tokens": True,
    },
    {
        "name": "decorative_attribute_stays_ignorable",
        "construct": "cellpadding",
        "kind": "attribute",
        "expect_state": IGNORED,
        "expect_facet": None,
        "guards": (
            "the other direction. A policy that called everything meaningful "
            "would pass the seven controls above and be useless"
        ),
        "before": '<table cellpadding="2"><tr><td>x</td></tr></table>',
        "after": '<table cellpadding="8"><tr><td>x</td></tr></table>',
        "differs_in": "spacing only; no text, structure, reference or accessible name moves",
        "same_visible_tokens": True,
    },
)

#: The control that keeps the policy from collapsing into "everything matters".
NEGATIVE_DIRECTION_CONTROL = "decorative_attribute_stays_ignorable"

#: The control that keeps it from collapsing into "nothing matters".
POSITIVE_DIRECTION_CONTROLS = tuple(
    control["name"] for control in CONTROLS if control["expect_state"] == MODELED
)

#: The control for the third state, which neither direction covers.
THIRD_STATE_CONTROL = "class_external_dependency_unresolved"


def by_name(name: str) -> dict[str, Any]:
    return next(control for control in CONTROLS if control["name"] == name)
