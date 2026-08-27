"""Development fixtures for Source Coverage Locality v2.

The founder's anti-fitting rule: the instrument is finished against **these**,
not against the P4e cohort's eligibility count. Nothing in this file is drawn
from the cohort, and no fixture was written or edited after a cohort number was
seen — the instrument is completed here, frozen, sealed, and then applied to the
cohort exactly once.

Eight controls, each naming what it would catch if the instrument were wrong:

``direct_span_positive``
    the only fixture expected to be COMPLETE. If it is not, the instrument
    cannot grant completeness at all and every later zero is meaningless.

``out_of_range_link_definition``
    the adversarial case v1 admitted it could miss. The atom depends on a
    reference definition at the foot of the file, and that definition carries an
    unmodeled construct. An interval rule scoped to the atom never looks there.

``include_directive_dependency``
    the atom invokes a directive whose argument is unmodeled.

``unrelated_unmodeled_outside_witness``
    an unmodeled fact the atom does **not** depend on. This one must stay
    COMPLETE: a witness that fails here is not localising, it is just reporting
    the document-level rule under a new name.

``html_attribute``
    an unmodeled attribute inside the atom's own markup, with a real position.

``nested_markup``
    deep nesting, to check that intervals still close in reading order.

``malformed_markup``
    unclosed tags. The parser's reported position is least trustworthy here.

``ambiguous_location``
    markup whose events cannot all be placed. Must refuse, never guess.
"""

from __future__ import annotations

from typing import Any

COMPLETE = "QUESTION_LOCAL_COVERAGE_COMPLETE"
INCOMPLETE = "QUESTION_LOCAL_COVERAGE_INCOMPLETE"


#: Every fixture: raw source, the atom under test, its envelope members, the
#: expected verdict, and what a wrong verdict would mean.
FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "name": "direct_span_positive",
        "suffix": ".md",
        "expect": COMPLETE,
        "guards": "the instrument can grant completeness at all",
        "raw": (
            "# Retention policy\n"
            "\n"
            "Records are retained for seven years from the close of the period.\n"
        ),
        "atom": "Records are retained for seven years from the close of the period.",
        "members": [],
    },
    {
        "name": "out_of_range_link_definition",
        "suffix": ".md",
        "expect": INCOMPLETE,
        "guards": (
            "the adversarial case locality v1 admitted it could miss: a "
            "dependency outside the atom's interval"
        ),
        "raw": (
            "# Retention policy\n"
            "\n"
            "Records are retained as set out in [the schedule][sched].\n"
            "\n"
            "# An unrelated section\n"
            "\n"
            "Nothing here concerns retention at all.\n"
            "\n"
            '[sched]: <policyref binding="true" targetref="reg/2026/117">\n'
        ),
        "atom": "Records are retained as set out in [the schedule][sched].",
        "members": [],
    },
    {
        "name": "include_directive_dependency",
        "suffix": ".md",
        "expect": INCOMPLETE,
        "guards": "a directive argument the atom depends on is not examined",
        "raw": (
            "# Retention policy\n"
            "\n"
            'Records are retained. {{< include "shared/retention-note.md" >}}\n'
        ),
        "atom": 'Records are retained. {{< include "shared/retention-note.md" >}}',
        "members": [],
    },
    {
        "name": "unrelated_unmodeled_outside_witness",
        "suffix": ".md",
        "expect": COMPLETE,
        "guards": (
            "the witness actually localises. Failing here would mean it is the "
            "document-level rule wearing a new name"
        ),
        "raw": (
            "# Retention policy\n"
            "\n"
            "Records are retained for seven years from the close of the period.\n"
            "\n"
            "# Something else entirely\n"
            "\n"
            '<policyref binding="true" targetref="reg/2026/999"></policyref>\n'
        ),
        "atom": "Records are retained for seven years from the close of the period.",
        "members": [],
    },
    {
        "name": "html_attribute",
        "suffix": ".html",
        "expect": INCOMPLETE,
        "guards": "an unmodeled attribute inside the atom's own markup is seen",
        "raw": (
            "<html><body>\n"
            "<h2>Retention policy</h2>\n"
            '<p binding="true">Records are retained for seven years.</p>\n'
            "</body></html>\n"
        ),
        "atom": "Records are retained for seven years.",
        "members": [],
    },
    {
        "name": "nested_markup",
        "suffix": ".xml",
        "expect": INCOMPLETE,
        "guards": "intervals still close in reading order through deep nesting",
        "raw": (
            "<?xml version='1.0' encoding='UTF-8'?>\n"
            "<DIV8><HEAD>Retention</HEAD>\n"
            "  <SECT><SUB><P force='yes'>Records are retained for seven years.</P></SUB></SECT>\n"
            "</DIV8>\n"
        ),
        "atom": "Records are retained for seven years.",
        "members": [],
    },
    {
        "name": "malformed_markup",
        "suffix": ".html",
        "expect": INCOMPLETE,
        "guards": (
            "a parser's reported position is least trustworthy on broken markup, "
            "which is where a fabricated interval would do the most damage"
        ),
        "raw": (
            "<html><body>\n"
            "<p>Records are retained for seven years.\n"
            "<div><span>unclosed everywhere\n"
        ),
        "atom": "Records are retained for seven years.",
        "members": [],
    },
    {
        "name": "ambiguous_location",
        "suffix": ".html",
        "expect": INCOMPLETE,
        "guards": "an unplaceable event is refused rather than given a guessed position",
        "raw": "<p>Records are retained.</p><!-- \x00 --><p attr",
        "atom": "Records are retained.",
        "members": [],
    },
)


def by_name(name: str) -> dict[str, Any]:
    return next(fixture for fixture in FIXTURES if fixture["name"] == name)


#: The two directional controls, named so the protocol can gate them by role
#: rather than by position in the list.
OVER_GRANT_CONTROL = "out_of_range_link_definition"
UNDER_GRANT_CONTROL = "unrelated_unmodeled_outside_witness"
POSITIVE_CONTROL = "direct_span_positive"
