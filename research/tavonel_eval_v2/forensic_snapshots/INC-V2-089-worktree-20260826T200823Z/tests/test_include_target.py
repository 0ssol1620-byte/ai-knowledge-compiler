"""The frozen INCLUDE_TARGET taxonomy (`source_fact_ir.include_target`) and its
wiring into the Jinja/Liquid include extractor in `source_fact_ir.reference`.

SOURCE_FACT_IR_HELDOUT_V2's E2 endpoint failed on 14 facts — 7 distinct
`{% include ... %}` expressions, every one an unquoted bareword (a plain
variable-or-filename token, alone or followed by `key=value` decorators).
These tests exist to pin the taxonomy that decides such a case, prove the
three classes are exhaustive and mutually exclusive, and prove the 7 observed
expressions land where the taxonomy's own decision rule puts them — not where
a resolver tuned to those 7 shapes would have put them.
"""

from __future__ import annotations

import sys
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))

from source_fact_ir import ir  # noqa: E402
from source_fact_ir.include_target import (  # noqa: E402
    IncludeTargetClass,
    IncludeTargetVerdict,
    classify_include_expression,
    embedded_template_marker,
)
from source_fact_ir.reference import reference_extractor  # noqa: E402

ALL_CLASSES = frozenset(IncludeTargetClass)


# ---------------------------------------------------------------------------
# 1. exhaustive and mutually exclusive: every input lands in exactly one class


def test_classification_is_total_and_single_valued():
    """A battery spanning every shape this module names, plus a few it does
    not specifically discuss. Each must resolve to exactly one recognised
    class — `classify_include_expression` cannot return `None`, cannot raise,
    and the class it returns is always a single member of the enum, which
    *is* mutual exclusivity: a dataclass field holds one value, never a set."""
    samples = [
        '"partials/schedule-v1.md"',
        "'chapters/one.md'",
        '"file.md" region="us" flag=true',
        "JB/setup",
        "region",
        "plans-blockquote.html",
        'plans-blockquote.html feature="AI customization"',
        'plans-blockquote.html feature="Customizable fonts" is_plural=true',
        '"a" ~ region ~ "b"',
        '"partials/schedule-" ~ region ~ ".md"',
        "",
        "   ",
        '"unterminated',
        "'unterminated",
        "~",
        "#bad-token!",
        '"a" + "b"',
        '"a" | upper',
        "foo(bar)",
        '"literal" extra garbage here',
    ]
    for sample in samples:
        verdict = classify_include_expression(sample)
        assert isinstance(verdict, IncludeTargetVerdict), sample
        assert verdict.cls in ALL_CLASSES, sample
        # single-valued: re-classifying the same input is deterministic
        assert classify_include_expression(sample) == verdict, sample


def test_classes_are_pairwise_disjoint_by_construction():
    """The three classes are members of one enum, so nothing can be tagged as
    more than one — this is the structural half of "no input lands in two".
    The behavioural half (no input is refused a class) is
    `test_classification_is_total_and_single_valued` above."""
    assert len(ALL_CLASSES) == 3
    assert IncludeTargetClass.STATIC_RESOLVABLE != IncludeTargetClass.DYNAMIC_COMPUTED
    assert IncludeTargetClass.STATIC_RESOLVABLE != IncludeTargetClass.MALFORMED_AMBIGUOUS
    assert IncludeTargetClass.DYNAMIC_COMPUTED != IncludeTargetClass.MALFORMED_AMBIGUOUS


# ---------------------------------------------------------------------------
# 2. static resolvable target


def test_bare_quoted_literal_is_static_resolvable():
    verdict = classify_include_expression('"partials/schedule-v1.md"')
    assert verdict.cls is IncludeTargetClass.STATIC_RESOLVABLE
    assert verdict.target == "partials/schedule-v1.md"
    assert verdict.reason


def test_single_quoted_literal_with_decorators_is_static_resolvable():
    """A quoted literal followed only by `key=value` decorator arguments is
    still statically named — the decorators do not participate in naming the
    target, so they cannot make it undecidable."""
    verdict = classify_include_expression(
        '"partials/notice.html" feature="Custom fonts" is_plural=true'
    )
    assert verdict.cls is IncludeTargetClass.STATIC_RESOLVABLE
    assert verdict.target == "partials/notice.html"


def test_single_quoted_target_arg_value_with_spaces_does_not_split_tokenization():
    verdict = classify_include_expression('"x.html" feature="value with spaces" flag=true')
    assert verdict.cls is IncludeTargetClass.STATIC_RESOLVABLE
    assert verdict.target == "x.html"


# ---------------------------------------------------------------------------
# 3. dynamic / computed target


def test_bareword_alone_is_dynamic_not_static():
    """An unquoted bareword filename token. The 7 observed cases include this
    exact shape (`JB/setup`) four times. It is DYNAMIC_COMPUTED, not because
    it looks "computed" in the concatenation sense, but because whether it
    names a literal path or a variable is a dialect fact this extractor is
    never told — deciding it would mean assuming a dialect."""
    verdict = classify_include_expression("JB/setup")
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
    assert verdict.target is None
    assert "JB/setup" in verdict.reason
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value in verdict.reason


def test_bareword_with_decorators_is_dynamic_not_static():
    """The other observed shape: an unquoted bareword first token followed by
    `key=value` decorators. Unlike the quoted-literal case, decorators after
    a bareword do not rescue it — the bareword rule applies regardless of
    what follows, because the ambiguity is in the first token itself."""
    verdict = classify_include_expression(
        'plans-blockquote.html feature="Customizable fonts" is_plural=true'
    )
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
    assert verdict.target is None


def test_plain_variable_name_is_dynamic():
    verdict = classify_include_expression("region")
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED


def test_literal_concatenated_with_a_variable_is_dynamic():
    verdict = classify_include_expression('"partials/schedule-" ~ region ~ ".md"')
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
    assert verdict.target is None


def test_literal_followed_by_non_decorator_content_is_dynamic():
    verdict = classify_include_expression('"a" + "b"')
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
    verdict = classify_include_expression('"a" | upper')
    assert verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED


# ---------------------------------------------------------------------------
# 4. malformed / ambiguous expression


def test_empty_expression_is_malformed():
    verdict = classify_include_expression("")
    assert verdict.cls is IncludeTargetClass.MALFORMED_AMBIGUOUS
    assert verdict.target is None
    verdict = classify_include_expression("   ")
    assert verdict.cls is IncludeTargetClass.MALFORMED_AMBIGUOUS


def test_unterminated_quote_is_malformed():
    verdict = classify_include_expression('"partials/schedule-v1.md')
    assert verdict.cls is IncludeTargetClass.MALFORMED_AMBIGUOUS
    assert verdict.target is None


def test_unparseable_token_is_malformed():
    verdict = classify_include_expression("~")
    assert verdict.cls is IncludeTargetClass.MALFORMED_AMBIGUOUS
    verdict = classify_include_expression("foo(bar)")
    assert verdict.cls is IncludeTargetClass.MALFORMED_AMBIGUOUS


# ---------------------------------------------------------------------------
# 5. every reason names its class and what could not be resolved


def test_fail_closed_reasons_name_their_class():
    dynamic = classify_include_expression("JB/setup")
    malformed = classify_include_expression("")
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value in dynamic.reason
    assert IncludeTargetClass.MALFORMED_AMBIGUOUS.value in malformed.reason
    # a reader must be able to tell the two apart from the reason text alone
    assert dynamic.reason != malformed.reason
    assert IncludeTargetClass.MALFORMED_AMBIGUOUS.value not in dynamic.reason
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value not in malformed.reason


# ---------------------------------------------------------------------------
# 6. wired into the extractor: the observed 7 expressions, verbatim


def _jinja_include_fact(raw: bytes):
    facts = [
        f for f in reference_extractor.extract(raw=raw, document={})
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "jinja-include"
    ]
    assert len(facts) == 1, facts
    return facts[0]


def test_observed_case_jb_setup_is_recognized_but_unrepresented():
    fact = _jinja_include_fact(b"{% include JB/setup %}\n")
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert fact.reason
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value in fact.reason


def test_observed_case_bareword_with_decorators_is_recognized_but_unrepresented():
    raw = b'{% include plans-blockquote.html feature="AI customization" %}\n'
    fact = _jinja_include_fact(raw)
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value in fact.reason


def test_observed_case_bareword_with_two_decorators_is_recognized_but_unrepresented():
    raw = (
        b'{% include plans-blockquote.html feature="Customizable fonts" '
        b"is_plural=true%}\n"
    )
    fact = _jinja_include_fact(raw)
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None


def test_quoted_literal_target_is_represented_through_the_extractor():
    """The taxonomy does not turn every include into a fail-closed fact — a
    disciplined, quoted target still resolves, exactly as before."""
    fact = _jinja_include_fact(b'{% include "partials/schedule-v1.md" %}\n')
    assert fact.state == ir.REPRESENTED
    assert fact.representation["normalized"].endswith("schedule-v1.md")


def test_concatenated_target_is_recognized_but_unrepresented_through_the_extractor():
    raw = b'{% include "partials/schedule-" ~ region ~ ".md" %}\n'
    fact = _jinja_include_fact(raw)
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert fact.reason


def test_empty_include_tag_is_unresolved_not_unrepresented_through_the_extractor():
    """An empty target position is not "computed" — nothing was parsed at
    all. The taxonomy routes it to MALFORMED_AMBIGUOUS, which the extractor
    maps to UNRESOLVED_SOURCE_FACT, distinct from the DYNAMIC_COMPUTED cases
    above which map to RECOGNIZED_BUT_UNREPRESENTED."""
    fact = _jinja_include_fact(b"{% include %}\n")
    assert fact.state == ir.UNRESOLVED
    assert fact.representation is None
    assert fact.reason


# ---------------------------------------------------------------------------
# 7. `embedded_template_marker` — the taxonomy's second route to
# DYNAMIC_COMPUTED, for a grammar (an already-resolved attribute value) that
# has no bareword-vs-literal tokenization question of its own


def test_embedded_template_marker_finds_liquid_jinja_django_delimiters():
    assert embedded_template_marker("{{ region }}.html") == "{{"
    assert embedded_template_marker("{{region}}.html") == "{{"
    assert embedded_template_marker("pre-{{region}}.html") == "{{"
    assert embedded_template_marker("{% if x %}a{% endif %}.html") == "{%"
    assert embedded_template_marker("{# comment #}.html") == "{#"


def test_embedded_template_marker_finds_erb_delimiter():
    assert embedded_template_marker("<%= region %>.html") == "<%"


def test_embedded_template_marker_is_none_for_a_plain_literal():
    assert embedded_template_marker("partials/schedule-v1.md") is None
    assert embedded_template_marker("") is None


# ---------------------------------------------------------------------------
# 8. wired into `_extract_html_includes`
#
# The previous lane argued no computed expression can arise in an HTML
# attribute value. It can: a template engine's own delimiters can be
# embedded inside an otherwise-plausible-looking `src` string (Jekyll/
# Liquid/Django `{{ }}` interpolation is the common real-world shape). Before
# the fix these tests pin, `<include src="{{region}}.html">` (no whitespace,
# so the pre-existing "unescaped whitespace" UNRESOLVED path never caught it
# either) came back REPRESENTED with the literal template markup asserted as
# the target.


def _html_include_fact(raw: bytes):
    facts = [
        f for f in reference_extractor.extract(raw=raw, document={})
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "html-include-src"
    ]
    assert len(facts) == 1, facts
    return facts[0]


def test_html_include_plain_literal_is_still_represented():
    fact = _html_include_fact(b'<include src="partials/one.html">\n')
    assert fact.state == ir.REPRESENTED
    assert fact.representation["normalized"].endswith("partials/one.html")


def test_html_include_embedded_interpolation_without_whitespace_is_unrepresented():
    fact = _html_include_fact(b'<include src="{{region}}.html">\n')
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None
    assert fact.reason
    assert IncludeTargetClass.DYNAMIC_COMPUTED.value in fact.reason


def test_html_include_embedded_interpolation_with_whitespace_is_unrepresented():
    fact = _html_include_fact(b'<include src="{{ region }}.html">\n')
    assert fact.state == ir.UNREPRESENTED
    assert fact.representation is None


def test_html_include_embedded_logic_tag_is_unrepresented():
    fact = _html_include_fact(b'<include src="{% if x %}a{% endif %}.html">\n')
    assert fact.state == ir.UNREPRESENTED


def test_html_include_embedded_erb_delimiter_is_unrepresented():
    fact = _html_include_fact(b'<include src="<% region %>.html">\n')
    assert fact.state == ir.UNREPRESENTED


def test_html_include_unquoted_attribute_with_embedded_markup_is_unrepresented():
    fact = _html_include_fact(b"<include src=pre-{{region}}.html>\n")
    assert fact.state == ir.UNREPRESENTED


# ---------------------------------------------------------------------------
# 9. wired into `_extract_hugo_shortcodes`
#
# The previous lane argued Hugo's "quoted-arg search" cannot produce a
# computed target. It can: `re.search(r'"([^"]*)"', inner)` found the first
# quoted substring *anywhere* in the shortcode body, including one buried
# inside a Go template function call such as `(printf "%s.html" .Param)`,
# and represented it as the target. This extractor now reuses
# `classify_include_expression` on the same "text after the directive name"
# slice the Jinja extractor uses, rather than a second, laxer rule.


def _hugo_include_fact(raw: bytes):
    facts = [
        f for f in reference_extractor.extract(raw=raw, document={})
        if f.kind == ir.INCLUDE_TARGET and f.witness.construct == "hugo-shortcode-include"
    ]
    assert len(facts) == 1, facts
    return facts[0]


def test_hugo_shortcode_plain_literal_is_still_represented():
    fact = _hugo_include_fact(b'{{< include "chapters/one.md" >}}\n')
    assert fact.state == ir.REPRESENTED
    assert fact.representation["normalized"].endswith("chapters/one.md")


def test_hugo_shortcode_literal_with_decorator_is_still_represented():
    fact = _hugo_include_fact(b'{{< include "chapters/one.md" lang="en" >}}\n')
    assert fact.state == ir.REPRESENTED
    assert fact.representation["normalized"].endswith("chapters/one.md")


def test_hugo_shortcode_bareword_variable_is_unresolved_not_represented():
    fact = _hugo_include_fact(b"{{< include .Region >}}\n")
    assert fact.state != ir.REPRESENTED
    assert fact.representation is None


def test_hugo_shortcode_function_call_target_is_not_silently_represented():
    """The exact previously-reachable defect: a `printf` call's format
    string is not the target, but the naive quoted-string search picked it
    anyway."""
    fact = _hugo_include_fact(b'{{< include (printf "%s.html" .Param) >}}\n')
    assert fact.state != ir.REPRESENTED
    assert fact.representation is None


def test_hugo_shortcode_two_positional_args_is_not_silently_represented():
    """Two bare quoted strings in the argument list are ambiguous about
    which one names the target; the naive search silently picked the first.
    """
    fact = _hugo_include_fact(b'{{< include "a" "b.html" >}}\n')
    assert fact.state != ir.REPRESENTED
    assert fact.representation is None


def test_hugo_shortcode_empty_target_is_still_unresolved():
    """Regression pin: `{{% include %}}` (no target at all) must keep the
    same UNRESOLVED_SOURCE_FACT state it had before this extractor was
    rewired onto `classify_include_expression` —
    `tests/test_sfi_reference.py::test_tally_round_trip_matches_expected_states`
    depends on this exact fixture producing UNRESOLVED, not UNREPRESENTED."""
    fact = _hugo_include_fact(b"{{% include %}}\n")
    assert fact.state == ir.UNRESOLVED
    assert fact.representation is None
