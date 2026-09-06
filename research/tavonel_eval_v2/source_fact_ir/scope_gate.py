"""An executable gate over what enters the declared supported/scored SFI3
path for `INCLUDE_TARGET` facts.

Why this module exists (founder ruling, 2026-08-23): the lane that built
`include_target.py`'s taxonomy wired it into `_extract_jinja_includes` only,
because the 14 observed E2 defects were all `jinja-include` facts, and
judged `_extract_html_includes`, `_extract_hugo_shortcodes` and
`_extract_mediawiki_templates` out of scope on the argument that no computed
or ambiguous target can arise in their grammars. **"A lane considered it out
of scope" is not evidence.** A prose scope claim with no executable check
behind it is exactly the INC-V2-034 defect, which sat unresolved for weeks
because prose cannot refuse a bad input — only code that runs against one
can.

This module is that code. For every construct `source_fact_ir.reference`
extracts into an `INCLUDE_TARGET` fact, it states and *proves*:

1. the construct is in the declared supported/scored path — not by
   restating a claim, but by driving `reference_extractor.extract` (the
   actual registered entry point `source_fact_ir.ir.extract_all` calls) with
   a minimal fixture and confirming a fact bearing that construct name comes
   back;
2. the construct's grammar cannot silently turn a computed or ambiguous
   target into a `REPRESENTED` fact — either because the taxonomy is wired
   into it (jinja, hugo, html) and a battery of known-computed/malformed
   fixtures is asserted to never come back `REPRESENTED`, or, for
   `mediawiki-template`, because the construct's own matching regex
   structurally cannot capture a computed name in the first place (proven
   below, not assumed).

What this module tests is the outcome, not the mechanism a given extractor
happens to use to reach it — `include_target.classify_include_expression`
for jinja/hugo, `include_target.embedded_template_marker` for html,
`_MEDIAWIKI_RE`'s character class for mediawiki. A future extractor change
that broke any of those routes without breaking this gate's assertions would
not be a false pass: the gate only cares whether a computed/ambiguous input
can still reach `REPRESENTED`.

`tests/test_scope_gate.py` is what actually runs these checks as pytest
tests; the functions here are importable so nothing about the proof lives
only inside a test collector.
"""

from __future__ import annotations

from dataclasses import dataclass

from source_fact_ir import ir
from source_fact_ir.reference import reference_extractor

# ---------------------------------------------------------------------------
# 1. the declared cohort
#
# One row per construct this module makes a scope claim about. `fixture`
# is the smallest raw input that makes `reference_extractor.extract` emit a
# fact of that construct at all — used to prove membership in the scored
# path (property 1 above), not to exercise the taxonomy itself.

INCLUDE_TARGET_CONSTRUCTS: tuple[str, ...] = (
    "jinja-include",
    "hugo-shortcode-include",
    "html-include-src",
    "mediawiki-template",
)


@dataclass(frozen=True)
class ConstructScope:
    construct: str
    directive: str
    fixture: bytes
    taxonomy_route: str


CONSTRUCT_SCOPES: dict[str, ConstructScope] = {
    scope.construct: scope
    for scope in (
        ConstructScope(
            construct="jinja-include",
            directive="jinja-include",
            fixture=b'{% include "a.md" %}\n',
            taxonomy_route=(
                "include_target.classify_include_expression on the text after "
                "the directive name"
            ),
        ),
        ConstructScope(
            construct="hugo-shortcode-include",
            directive="hugo-shortcode",
            fixture=b'{{< include "a.md" >}}\n',
            taxonomy_route=(
                "include_target.classify_include_expression on the text after "
                "the directive name, same call as jinja-include"
            ),
        ),
        ConstructScope(
            construct="html-include-src",
            directive="html-include",
            fixture=b'<include src="a.html">\n',
            taxonomy_route=(
                "include_target.embedded_template_marker on the resolved "
                "attribute value"
            ),
        ),
        ConstructScope(
            construct="mediawiki-template",
            directive="mediawiki-template",
            fixture=b"{{Foo}}\n",
            taxonomy_route=(
                "no taxonomy call: _MEDIAWIKI_RE's character class structurally "
                "excludes '{'/'}' from the captured name, so no computed "
                "expression can be captured as a name in the first place — "
                "see prove_mediawiki_name_cannot_carry_a_computed_expression"
            ),
        ),
    )
}


# ---------------------------------------------------------------------------
# 2. property 1 — membership in the declared supported/scored path
#
# "Supported/scored" is not a label anything in this codebase sets — it is a
# fact about wiring: `source_fact_ir.ir.extract_all` calls every extractor in
# `ir._REGISTRY`, `reference_extractor` is registered there for
# `INCLUDE_TARGET` (source_fact_ir/reference.py, bottom of file), and every
# fact it emits enters `E1`-`E4`/`E7` scoring. There is no separate opt-out:
# an extractor either produces facts through that one call, or it produces
# nothing and does not exist for scoring purposes. So membership is proven
# behaviourally — feed the fixture in through the *actual* registered entry
# point, not the private `_extract_*` function directly, and confirm a fact
# bearing the construct's name comes back with the registered kind.


def is_in_scored_path(construct: str) -> bool:
    """`True` iff `construct` actually reaches an `INCLUDE_TARGET` fact
    through `reference_extractor.extract` — the entry point
    `source_fact_ir.ir.extract_all` (and therefore every SFI3 scoring run)
    actually calls.
    """
    if ir.INCLUDE_TARGET not in ir.registered_kinds():
        return False
    scope = CONSTRUCT_SCOPES[construct]
    facts = reference_extractor.extract(raw=scope.fixture, document={})
    return any(
        f.kind == ir.INCLUDE_TARGET and f.witness.construct == construct
        for f in facts
    )


# ---------------------------------------------------------------------------
# 3. property 2 — a computed/ambiguous input can never reach REPRESENTED
#
# Curated per-construct batteries of raw source bytes that name a computed
# or malformed target in that construct's own grammar. Every one of these is
# a real, previously-reachable defect this module's tests pin: before the
# fixes accompanying this gate, `html-include-src` and `hugo-shortcode-include`
# both turned a subset of these into a silently wrong `REPRESENTED` fact.

_COMPUTED_OR_MALFORMED_FIXTURES: dict[str, tuple[bytes, ...]] = {
    "jinja-include": (
        b"{% include JB/setup %}\n",  # bareword, one of the 14 observed cases
        b'{% include "partials/schedule-" ~ region ~ ".md" %}\n',  # concatenation
        b"{% include %}\n",  # empty
        b'{% include "unterminated %}\n',  # unterminated quote
    ),
    "hugo-shortcode-include": (
        b"{{< include .Region >}}\n",  # bareword variable reference
        b'{{< include (printf "%s.html" .Param) >}}\n',  # computed via function call
        b'{{< include (print "a" .Region "b.html") >}}\n',  # ditto
        b'{{< include "a" "b.html" >}}\n',  # two positional args, ambiguous which is the target
        b"{{% include %}}\n",  # empty
    ),
    "html-include-src": (
        b'<include src="{{ region }}.html">\n',  # Liquid/Jekyll interpolation, spaced
        b'<include src="{{region}}.html">\n',  # same, unspaced — the silent-REPRESENTED case
        b'<include src="pre-{{ region }}.html">\n',  # interpolation glued to a literal prefix
        b"<include src=pre-{{region}}.html>\n",  # unquoted attribute value
        b"<include src=\"{{% if x %}}a{{% else %}}b{{% endif %}}.html\">\n",  # logic tag
        b'<include src="<% region %>.html">\n',  # ERB delimiter
    ),
}


def represented_facts_for_construct(
    raw: bytes, construct: str
) -> list[ir.SourceFact]:
    return [
        f
        for f in reference_extractor.extract(raw=raw, document={})
        if f.kind == ir.INCLUDE_TARGET
        and f.witness.construct == construct
        and f.state == ir.REPRESENTED
    ]


def assert_never_represents_a_computed_or_malformed_target(construct: str) -> None:
    """Raise `AssertionError` if any fixture in
    `_COMPUTED_OR_MALFORMED_FIXTURES[construct]` produces a `REPRESENTED`
    `INCLUDE_TARGET` fact for `construct`. A `REPRESENTED` fact from one of
    these inputs would mean a target that does not statically exist was
    inferred anyway — the exact failure lane D's frozen taxonomy exists to
    refuse.
    """
    fixtures = _COMPUTED_OR_MALFORMED_FIXTURES.get(construct)
    if not fixtures:
        raise ValueError(f"no fixture battery registered for construct {construct!r}")
    for raw in fixtures:
        represented = represented_facts_for_construct(raw, construct)
        if represented:
            raise AssertionError(
                f"{construct} represented a computed/malformed target as static "
                f"for input {raw!r}: {[f.representation for f in represented]!r}"
            )


# ---------------------------------------------------------------------------
# 4. mediawiki — a structural proof instead of a fixture battery
#
# `_extract_mediawiki_templates` calls no taxonomy function at all. That is
# not an oversight to fix here; it is provable that none is needed, because
# `source_fact_ir.reference._MEDIAWIKI_RE`'s captured group is
# `(?:[^{}])+?` — a character class that excludes `{` and `}` from the match
# by construction. A nested transclusion such as `{{ {{PAGENAME}} }}` (the
# one shape that would make a mediawiki template *name* itself computed)
# therefore can never appear inside the text this extractor reads as a name:
# the regex instead matches the inner `{{PAGENAME}}` as its own separate,
# unrelated construct, never as part of an outer one. This function checks
# the *consequence* of that structural fact directly against whatever
# `reference_extractor.extract` actually returns, for whatever `raw` the
# caller supplies — it is not limited to a fixed sample list, so a change to
# `_MEDIAWIKI_RE` that broke the exclusion would be caught here without this
# module needing to enumerate the new shape in advance.


def prove_mediawiki_name_cannot_carry_a_computed_expression(raw: bytes) -> None:
    """Raise `AssertionError` if any `mediawiki-template` fact `extract`
    produces for `raw` carries a name (`extra["raw_target"]`, or
    `representation["normalized"]` when `REPRESENTED`) containing a brace
    character — the one byte class that could signal a nested, computed
    transclusion leaking through as if it were a literal name.
    """
    for fact in reference_extractor.extract(raw=raw, document={}):
        if fact.kind != ir.INCLUDE_TARGET or fact.witness.construct != "mediawiki-template":
            continue
        name = fact.extra.get("raw_target")
        if name is None and fact.representation is not None:
            name = fact.representation.get("normalized")
        name = name or ""
        if "{" in name or "}" in name:
            raise AssertionError(
                f"mediawiki-template captured a braced (computed) name from "
                f"{raw!r}: {name!r}"
            )


# A battery of inputs that *try* to make a computed/nested name reach the
# extractor — attempts at the exact scenario the structural proof above
# rules out. Kept here (not only in the test file) so the attempted-attack
# shapes are visible as part of the scope claim itself, not buried in a test.
MEDIAWIKI_NESTED_TRANSCLUSION_ATTEMPTS: tuple[bytes, ...] = (
    b"{{ {{PAGENAME}} }}\n",
    b"{{ {{ns:Template}}:{{PAGENAME}} }}\n",
    b"{{Template:{{PAGENAME}}}}\n",
    b"{{ {{#invoke:Module|func}} }}\n",
)


# ---------------------------------------------------------------------------
# 5. the whole cohort, driven together
#
# One call proving every claim this module makes, for a caller that wants
# the summary rather than to drive each property itself (used by
# tests/test_scope_gate.py's parametrised cases and available for a report).


def prove_scope() -> dict[str, dict[str, object]]:
    """Run every proof for every declared construct and return a results
    table. Raises the first `AssertionError`/`ValueError` encountered — this
    is a gate, not a reporter that swallows failures into a summary row.
    """
    results: dict[str, dict[str, object]] = {}
    for construct in INCLUDE_TARGET_CONSTRUCTS:
        in_scope = is_in_scored_path(construct)
        if not in_scope:
            raise AssertionError(
                f"{construct} is declared part of the INCLUDE_TARGET cohort "
                "but reference_extractor.extract never produced a fact for "
                "it — the scope claim and the wiring disagree"
            )
        if construct == "mediawiki-template":
            for raw in MEDIAWIKI_NESTED_TRANSCLUSION_ATTEMPTS:
                prove_mediawiki_name_cannot_carry_a_computed_expression(raw)
            never_represents = True
        else:
            assert_never_represents_a_computed_or_malformed_target(construct)
            never_represents = True
        results[construct] = {
            "in_scored_path": in_scope,
            "never_represents_computed_or_malformed": never_represents,
            "taxonomy_route": CONSTRUCT_SCOPES[construct].taxonomy_route,
        }
    return results


if __name__ == "__main__":
    import json

    print(json.dumps(prove_scope(), indent=2))
