"""The frozen taxonomy for INCLUDE_TARGET classification.

SOURCE_FACT_IR_HELDOUT_V2's E2 endpoint failed on 14 facts, every one an
``INCLUDE_TARGET`` fact in state ``RECOGNIZED_BUT_UNREPRESENTED``, and every one
for the same underlying reason: the text following an ``include`` directive's
name is not always a single string literal. Sometimes it names a variable,
sometimes it concatenates pieces together, sometimes it is simply broken. None
of those are the same defect V1's 1,284-fact ``PROVENANCE_SPAN`` failure was —
that one was a representation the compiled state never built at all. This one
is a target that, per the founder's ruling, **does not exist until evaluation**:

    Do not infer a single target from an expression that does not statically
    name one.

This module is the taxonomy that ruling implies, made explicit and frozen
before any fresh corpus is scored against it, so a scoring run cannot quietly
redraw the lines to make a bad number look better. It classifies one include
target *expression* — the text between the directive's name and its closing
delimiter — into exactly one of three classes.

Decision rule (the one paragraph a reviewer could disagree with)
------------------------------------------------------------------

**An include target expression is STATIC_RESOLVABLE only when its first token
is a complete quoted string literal and everything after that literal is
either nothing or a sequence of `key=value` decorator arguments; any unquoted
bareword in the target position is DYNAMIC_COMPUTED regardless of what
follows it, because whether a bareword names a literal path or a variable to
be resolved at render time is a fact about the host template dialect, not
about the bytes in front of the parser, and deciding it would mean assuming a
dialect this extractor was never told; anything left over — an empty
expression, an unterminated quote, or a first token that is neither a clean
quoted literal nor a plain path/identifier bareword — is
MALFORMED_AMBIGUOUS, because no expression could be parsed out of it at all.**

That rule is deliberately narrower than "does it look like a filename". A
bareword filename (``JB/setup``) and a bareword variable name (``region``)
are the same shape in this grammar — nothing about the bytes distinguishes an
include tag's own dialect from another's — so both fall on the DYNAMIC side
of the line, not because either one is *actually* computed, but because this
extractor cannot tell which one it is without evaluating (or assuming) more
than the source gives it. Only a quoted literal is unconditionally a string
regardless of dialect.

Where the 14 observed cases land
---------------------------------

All 14 are ``jinja-include`` facts (``source_fact_ir.reference``'s Jinja/Liquid
single-brace extractor) and reduce to 7 distinct expressions:

* ``JB/setup`` (x4) — an unquoted bareword. DYNAMIC_COMPUTED: it is exactly
  the ambiguous-dialect bareword case above, not a "computed expression" in
  the sense of concatenation or a function call, but still not decidable
  without assuming a dialect.
* ``plans-blockquote.html feature="…" is_plural=true`` (x2) and
  ``plans-blockquote.html feature="…"`` (x1) — an unquoted bareword first
  token followed by `key=value` decorators. Also DYNAMIC_COMPUTED, and for
  the same reason: the bareword rule does not carve out an exception for a
  bareword that happens to look like a filename. None of the 14 land in
  MALFORMED_AMBIGUOUS or STATIC_RESOLVABLE — they are honestly one class, not
  three artificially split ones.

A quoted-literal case such as ``"partials/schedule-v1.md"`` (present
elsewhere in this corpus, not among the 14) is STATIC_RESOLVABLE, and a
concatenation such as ``"partials/schedule-" ~ region ~ ".md"`` is
DYNAMIC_COMPUTED for the more familiar reason: it is a literal fragment glued
to a variable at render time, and no single static string is what the source
says the target is.

What fraction of include expressions this generalises to
-----------------------------------------------------------

No corpus-wide estimate exists here — this taxonomy has not been scored
against SOURCE_FACT_IR_HELDOUT_V2 or any other corpus yet, only checked
against the 14 observed cases and the fixtures already in this test suite.
Structurally, though, any include directive whose home dialect allows an
unquoted target (Jekyll/Liquid's bare filename convention, or a Jinja
variable reference — the same syntax, two dialects, no way to tell them
apart from bytes alone) will always land DYNAMIC_COMPUTED under this rule,
and any dialect that requires quoting its literal targets (this corpus's
observed ``"partials/…"`` style) will land STATIC_RESOLVABLE whenever the
author actually quoted it. The undecidable fraction is therefore a property
of how disciplined the corpus's authors were about quoting, not of this
taxonomy — and nothing here calibrates that number.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "IncludeTargetClass",
    "IncludeTargetVerdict",
    "classify_include_expression",
    "embedded_template_marker",
]


class IncludeTargetClass(StrEnum):
    """The three classes. Exhaustive and mutually exclusive by construction:
    `classify_include_expression` is a total function that returns exactly
    one of these for any string, never zero and never more than one."""

    #: A represented typed dependency: the bytes alone name one target.
    STATIC_RESOLVABLE = "STATIC_RESOLVABLE_TARGET"
    #: A target that does not exist until evaluation — a variable reference,
    #: a bareword whose meaning depends on an unstated dialect, or a
    #: literal glued to something else at render time.
    DYNAMIC_COMPUTED = "DYNAMIC_COMPUTED_TARGET"
    #: Not a parseable expression at all: empty, unterminated, or a first
    #: token that is neither a clean literal nor a plain bareword.
    MALFORMED_AMBIGUOUS = "MALFORMED_AMBIGUOUS_EXPRESSION"


@dataclass(frozen=True)
class IncludeTargetVerdict:
    """The classification of one include target expression.

    `target` carries the resolved literal string and is set only for
    `STATIC_RESOLVABLE`; the other two classes never carry one, matching
    `ir.SourceFact`'s own rule that only a REPRESENTED fact may have a
    representation. `reason` is always set — for `STATIC_RESOLVABLE` it
    explains the resolution (informational only, not required by the IR); for
    the two fail-closed classes it names the class and says what could not be
    resolved, so a reader can tell a computed target from a malformed one
    without re-parsing the source.
    """

    cls: IncludeTargetClass
    target: str | None
    reason: str


# ---------------------------------------------------------------------------
# grammar
#
# A plain path/identifier bareword: filename-safe characters only, no
# operator, quote, or brace punctuation. This is what makes a bareword
# "ambiguous" rather than "malformed" — it is a well-formed token, just one
# whose meaning (literal path vs. variable name) depends on a dialect this
# extractor is never told.
_BAREWORD_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]*$")

# A `key=value` decorator argument, the shape Jekyll/Hugo-style include tags
# use to pass parameters alongside a literal target. `value` may be a quoted
# string or a bare token; either way it is not part of the target.
_DECORATOR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s\"']+)$")


def _tokenize(text: str) -> list[str] | None:
    """Split on whitespace, treating a quoted run as part of its token.

    Returns `None` for an unterminated quote — the one case that must be
    told apart from "no tokens" (empty) and "tokens that don't parse"
    (malformed bareword), because it is a different fact about the source: a
    quote was opened and never closed.
    """
    tokens: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i].isspace():
            i += 1
            continue
        start = i
        while i < n and not text[i].isspace():
            if text[i] in "\"'":
                quote = text[i]
                end = text.find(quote, i + 1)
                if end == -1:
                    return None
                i = end + 1
            else:
                i += 1
        tokens.append(text[start:i])
    return tokens


def _unquote(token: str) -> str | None:
    """The literal value of `token` if it is exactly one quoted string,
    else `None`. Deliberately strict: a token like `"a"b` (content after the
    closing quote) is not a clean literal and must not be treated as one."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    return None


def classify_include_expression(expr: str) -> IncludeTargetVerdict:
    """Classify one include target expression per the frozen taxonomy.

    `expr` is the text between the directive's name (e.g. ``include``) and
    its closing delimiter — never the whole directive, and never re-derived
    from anything but the source bytes.
    """
    text = expr.strip()
    if not text:
        return IncludeTargetVerdict(
            IncludeTargetClass.MALFORMED_AMBIGUOUS,
            None,
            "MALFORMED_AMBIGUOUS_EXPRESSION: include directive has no target "
            "expression at all",
        )

    tokens = _tokenize(text)
    if tokens is None:
        return IncludeTargetVerdict(
            IncludeTargetClass.MALFORMED_AMBIGUOUS,
            None,
            "MALFORMED_AMBIGUOUS_EXPRESSION: unterminated quote in include "
            f"target expression {text!r}",
        )

    first, rest = tokens[0], tokens[1:]
    literal = _unquote(first)

    if literal is not None:
        if not rest:
            return IncludeTargetVerdict(
                IncludeTargetClass.STATIC_RESOLVABLE,
                literal,
                "STATIC_RESOLVABLE_TARGET: a single quoted string literal "
                "names the target",
            )
        if all(_DECORATOR_RE.match(tok) for tok in rest):
            return IncludeTargetVerdict(
                IncludeTargetClass.STATIC_RESOLVABLE,
                literal,
                "STATIC_RESOLVABLE_TARGET: a quoted string literal names the "
                f"target; the trailing key=value argument(s) {' '.join(rest)!r} "
                "are decorators, not part of the target",
            )
        return IncludeTargetVerdict(
            IncludeTargetClass.DYNAMIC_COMPUTED,
            None,
            "DYNAMIC_COMPUTED_TARGET: the expression begins with a string "
            f"literal but continues with {' '.join(rest)!r}, which is not a "
            "key=value decorator; no single static target can be named "
            "without evaluating the rest of the expression",
        )

    if _BAREWORD_RE.match(first):
        return IncludeTargetVerdict(
            IncludeTargetClass.DYNAMIC_COMPUTED,
            None,
            f"DYNAMIC_COMPUTED_TARGET: {first!r} is an unquoted bareword; "
            "whether it names a literal path or a variable to resolve at "
            "render time depends on a template dialect this extractor is "
            "never told, so no single target can be named without assuming one",
        )

    return IncludeTargetVerdict(
        IncludeTargetClass.MALFORMED_AMBIGUOUS,
        None,
        f"MALFORMED_AMBIGUOUS_EXPRESSION: target token {first!r} is neither "
        "a complete quoted string literal nor a plain path/identifier "
        "bareword",
    )


# ---------------------------------------------------------------------------
# embedded template markup — a second, narrower route to DYNAMIC_COMPUTED
#
# `classify_include_expression` tokenizes a directive's own argument grammar
# (Jinja/Liquid `{% include ... %}`, and — via the same call — a Hugo
# shortcode's `{{< include ... >}}` argument list). An HTML `<include src=...>`
# tag's target is not tokenized the same way: the attribute-value grammar has
# already resolved *what the attribute's text is* (quoted or bare) by the time
# it reaches this module, so there is no further bareword-vs-literal question
# to ask of it. What can still make that text a target that "does not exist
# until evaluation" is a *different* template engine's own delimiters embedded
# inside it — Jekyll/Liquid/Django `{{ ... }}` variable interpolation or
# `{% ... %}` logic, a Jinja/Django comment `{# ... #}`, or ERB `<% ... %>` —
# because those bytes are markup a template engine evaluates before any path
# exists, not a path themselves, regardless of whether they happen to look
# like a well-formed relative filename once decoded.

_EMBEDDED_TEMPLATE_MARKERS: tuple[str, ...] = ("{{", "}}", "{%", "%}", "{#", "#}", "<%", "%>")


def embedded_template_marker(value: str) -> str | None:
    """The first template-engine delimiter found in `value`, or `None`.

    Order of `_EMBEDDED_TEMPLATE_MARKERS` decides which marker is reported
    when more than one is present; the reported marker is informational
    (it names *why* the target is DYNAMIC_COMPUTED), not a ranking of which
    template dialect is "the" one in play.
    """
    for marker in _EMBEDDED_TEMPLATE_MARKERS:
        if marker in value:
            return marker
    return None
