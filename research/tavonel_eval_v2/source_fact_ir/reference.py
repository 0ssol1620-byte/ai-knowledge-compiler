"""Lane 2 — the reference/locator facet extractor.

Owns four kinds from ``source_fact_ir.ir``: ``REFERENCE_TARGET``,
``REFERENCE_DEFINITION``, ``INCLUDE_TARGET`` and ``CANONICAL_SOURCE_LOCATOR``.

Why this file exists (INC-V2-006): ``canonical_document.py`` deliberately
resolves markdown links down to their anchor text and strips HTML tags
entirely — that is correct for a readable body, but it means the compiled
state as it stood before this lane carried *no* representation of a link's
*destination* at all. A link whose href moved while its visible text stayed
put produced zero textual difference, so nothing invalidated and nothing
recompiled. The fix is not to put the target back into unit text (that just
relocates the same blindness) — it is to give the destination its own typed,
JSON-serializable representation in the IR, with its own witness and its own
identity, independent of the text around it.

Consequence for how this module is built: **every extractor here scans
``raw`` directly**, with byte-pattern regexes, rather than working from
``document["units"][...]["text"]``. Unit text has already had the constructs
this lane cares about resolved away by the canonicalizer; it is the wrong
input for this job. Scanning bytes directly also sidesteps a str/bytes offset
mismatch that a decode-then-search approach would have to solve separately:
matching on ``bytes`` patterns against ``raw`` yields byte offsets for free.

``unit_path`` on the witness. Every fact this module emits leaves it with a
document-qualified ``unit_path`` (``ir.unit_path_for(source_id, explicit_path)``)
— never ``None``. ``fingerprint.UnanchoredFact`` refuses a fact with none: an
unanchored fact has no artifact key, so a change to it invalidates nothing,
which is the INC-V2-006 failure by a different route. CANONICAL_SOURCE_LOCATOR
facts know their unit directly (they are emitted one-per-unit from
``document["units"]``) and set it at construction. Every other fact's
``unit_path`` is resolved after extraction, in one pass (``_anchor_facts``),
from its witness byte offset against unit spans built by tolerantly locating
each unit's text in ``raw`` — the same three-tier strategy
``core_extractor._locate`` uses for PROVENANCE_SPAN, independently
reimplemented here (not imported: the two lanes are siblings, and this only
needs a *start* offset per unit, not core's full span semantics). A construct
outside every unit's span — including a document handed with no ``"units"``
at all — is attributed to document scope, ``(source_id,)``: never left
unanchored.

Normalisation decisions for a reference target (documented here because
normalising too aggressively hides the exact class of bug this lane exists to
catch — the inverse mistake of INC-V2-006):

* HTML entities are decoded (``&amp;`` -> ``&``) via ``html.unescape``.
* Percent-encoding is decoded *only* for RFC 3986 "unreserved" characters
  (``ALPHA DIGIT - . _ ~``). ``%2D`` and ``-`` are the same byte and safe to
  fold together; ``%2F`` and ``/`` are not — decoding a reserved-character
  escape can change what the target means (path segment boundaries, query
  delimiters), so those are left encoded.
* Scheme and host are lower-cased (case-insensitive by the URI spec); path
  and query are left exactly as written, because path case sensitivity is a
  server/filesystem property this lane cannot know.
* A default port for the scheme (``:80`` on ``http``, ``:443`` on ``https``,
  ``:21`` on ``ftp``) is stripped, since it is not part of the resource's
  identity.
* Trailing slashes, query parameter order and percent-encoding of *reserved*
  characters are left untouched.

Both the raw and the normalised form are kept on every fact that carries a
target — but not both in `representation`. `fingerprint.py` fingerprints a
fact as a pure function of `(kind, representation)`, so anything placed in
`representation` participates in change detection. The literal raw string
therefore lives on `SourceFact.extra["raw_target"]` (informational, not
compared), while `representation["normalized"]` is what fingerprints and
what a caller compares. Putting the raw string inside `representation` too
would make two re-encodings of the same resource (`%7E` vs `~`) fingerprint
as different facts — a false delta on a meaningless byte difference, which
is the mirror image of the invisibility bug (INC-V2-006) this lane exists
to fix, and exactly what the adversarial corpus's percent-encoding-
equivalence fixture (adv-012) checks for.
"""

from __future__ import annotations

import dataclasses
import html
import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from canonicalization.canonical_document import clean_markdown

from source_fact_ir import ir
from source_fact_ir.include_target import (
    IncludeTargetClass,
    classify_include_expression,
    embedded_template_marker,
)
from source_fact_ir.ir import (
    IGNORED,
    INCLUDE_TARGET,
    LOCATOR,
    REFERENCE_DEFINITION,
    REFERENCE_TARGET,
    REPRESENTED,
    UNREPRESENTED,
    UNRESOLVED,
    SourceFact,
    Witness,
)

# ---------------------------------------------------------------------------
# predeclared policy table
#
# IGNORED is fail-open and exists only for a loss declined in advance. One
# policy today: contact-channel targets (mailto:, tel:) name a person, not a
# document — there is nothing for a dependency/invalidation edge to point at.

POLICY_REF_001 = "POLICY-REF-001"

POLICY_TABLE: dict[str, str] = {
    POLICY_REF_001: (
        "mailto: and tel: targets are out of scope: they name a contact "
        "channel rather than a document, so no compiled artifact should carry "
        "an invalidation edge to an email address or phone number."
    ),
}

_IGNORED_SCHEMES = frozenset({"mailto", "tel"})
_DEFAULT_PORTS = {"http": "80", "https": "443", "ftp": "21"}


# ---------------------------------------------------------------------------
# construct patterns — all bytes patterns, matched directly against `raw`

_INLINE_RE = re.compile(rb"(!?)\[([^\]]*)\]\(([^)]*)\)")
_DEF_LINE_RE = re.compile(rb"^[ \t]{0,3}\[([^\]]+)\]:[ \t]*(.*)$", re.MULTILINE)
_REF_USE_FULL_RE = re.compile(rb"(?<!!)\[([^\]]+)\]\[([^\]]*)\]")
_REF_USE_SHORTCUT_RE = re.compile(rb"(?<!!)\[([^\]\[]+)\](?!\s*[\(\[])")
_AUTOLINK_RE = re.compile(rb"<([a-zA-Z][a-zA-Z0-9+.\-]*:[^\s<>]+)>")
_HTML_TAG_RE = re.compile(rb"<(a|img|link|script|iframe|area)\b([^>]*)>", re.IGNORECASE)
_HTML_INCLUDE_RE = re.compile(rb"<include\b([^>]*)/?>", re.IGNORECASE)
_ATTR_RE = re.compile(rb"""\b(href|src)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.IGNORECASE)
_SHORTCODE_RE = re.compile(rb"\{\{[<%](.*?)[>%]\}\}", re.DOTALL)
_MEDIAWIKI_RE = re.compile(rb"\{\{(?![<%])((?:[^{}])+?)\}\}", re.DOTALL)
# Jinja/Liquid-style single-brace tag: `{% include "x" %}`. The lookaround
# pair excludes the case where this is really the inside of a Hugo
# `{{%...%}}` double-brace tag (`_SHORTCODE_RE`'s construct) — without it,
# `{{% include %}}` would match twice, once per regex, and double-count.
_JINJA_TAG_RE = re.compile(rb"(?<!\{)\{%(.*?)%\}(?!\})", re.DOTALL)
_FENCE_LINE_RE = re.compile(rb"^\s*(```|~~~)")
_ATX_LINE_RE = re.compile(rb"^(#{1,6})[ \t]+(.*?)[ \t]*#*[ \t]*$")
# Any element's `id="..."` — generic, not tied to headings, because
# fragment-target decidability (adv-010) depends on the whole document's id
# namespace, not on which elements this lane treats as locator-bearing.
_ID_ATTR_RE = re.compile(rb"""\bid\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)

_HTML_ATTR_BY_TAG = {
    b"a": b"href",
    b"area": b"href",
    b"link": b"href",
    b"img": b"src",
    b"script": b"src",
    b"iframe": b"src",
}

# `(target, title)` inner-content grammar shared by inline links/images and
# reference definitions: an optional `<...>`-wrapped target or a bare
# whitespace-free token, then an optional `"title"`. Anything else — a
# literal unescaped space in a bare target, unbalanced quoting, trailing
# garbage — fails this match, which is exactly the malformed/ambiguous case
# that must come back UNRESOLVED rather than silently not matching at all.
_INNER_RE = re.compile(r'^\s*(?:<([^<>]*)>|([^\s"]*))(?:\s+"([^"]*)")?\s*$')

_PANDOC_ID_RE = re.compile(r"\{#([-\w]+)\}\s*$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9\s-]")
_SLUG_SPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# small shared helpers


def _percent_decode_unreserved(value: str) -> str:
    unreserved = frozenset(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~"
    )

    def repl(match: re.Match[str]) -> str:
        ch = chr(int(match.group(0)[1:], 16))
        return ch if ch in unreserved else match.group(0)

    return re.sub(r"%[0-9A-Fa-f]{2}", repl, value)


def _normalize_target(raw_target: str) -> dict[str, Any]:
    decoded = html.unescape(raw_target)
    decoded = _percent_decode_unreserved(decoded)
    parsed = urlsplit(decoded)
    fragment = parsed.fragment or None
    if parsed.scheme:
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        default_port = _DEFAULT_PORTS.get(scheme)
        if default_port is not None and netloc.endswith(f":{default_port}"):
            netloc = netloc[: -(len(default_port) + 1)]
        kind = "external"
        normalized = urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    elif decoded.startswith("#"):
        scheme = None
        kind = "fragment"
        normalized = decoded
    elif decoded.startswith("/"):
        scheme = None
        kind = "internal"
        normalized = decoded
    else:
        scheme = None
        kind = "relative"
        normalized = decoded
    return {
        "normalized": normalized,
        "scheme": scheme,
        "kind": kind,
        "fragment": fragment,
    }


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = _SLUG_STRIP_RE.sub("", text)
    text = _SLUG_SPACE_RE.sub("-", text)
    return text


def _declared_id_counts(raw: bytes) -> Counter[str]:
    """How many times each `id="..."` value is declared anywhere in `raw`.

    Used only to judge whether a `#fragment` target is decidable. Zero
    declarations means the fragment names nothing recognisable; more than
    one means the source itself does not decide which element it means —
    picking one anyway would assert a fact the source does not determine
    (adv-010). Duplicate ids are not decidable by document order: order is
    not a predeclared policy, and treating it as a tie-break would need one.
    """
    counts: Counter[str] = Counter()
    for match in _ID_ATTR_RE.finditer(raw):
        value = match.group(1) if match.group(1) is not None else match.group(2)
        counts[value.decode("utf-8", "replace")] += 1
    return counts


def _parse_inner(inner: bytes) -> tuple[str | None, str | None, bool]:
    """Parse the `target [ "title" ]` grammar shared by links and defs.

    Returns `(target, title, malformed)`. `target` may legitimately be the
    empty string (an explicit empty target); `malformed` is True when the
    inner content does not fit the grammar at all (e.g. an unwrapped literal
    space in the target) — the caller must turn that into UNRESOLVED, never
    a silent non-match.
    """
    text = inner.decode("utf-8", "replace")
    match = _INNER_RE.match(text)
    if not match:
        return None, None, True
    target = match.group(1) if match.group(1) is not None else match.group(2)
    title = match.group(3)
    return target, title, False


def _witness(
    construct: str, start: int, end: int, raw: bytes, unit_path: tuple[str, ...] | None
) -> Witness:
    excerpt = raw[start:end].decode("utf-8", "replace")
    return Witness(
        construct=construct, byte_start=start, byte_end=end, excerpt=excerpt, unit_path=unit_path
    )


def _fact(
    kind: str,
    construct: str,
    start: int,
    end: int,
    raw: bytes,
    *,
    state: str,
    representation: dict[str, Any] | None = None,
    policy_ref: str | None = None,
    reason: str | None = None,
    unit_path: tuple[str, ...] | None = None,
    extra: dict[str, Any] | None = None,
) -> SourceFact:
    return SourceFact(
        kind=kind,
        witness=_witness(construct, start, end, raw, unit_path),
        state=state,
        representation=representation,
        policy_ref=policy_ref,
        reason=reason,
        extra=extra or {},
    )


def _target_fact(
    kind: str,
    construct: str,
    start: int,
    end: int,
    raw: bytes,
    raw_target: str | None,
    *,
    malformed: bool = False,
    title: str | None = None,
    extra: dict[str, Any] | None = None,
) -> SourceFact:
    """Build one fact from a raw target string, deciding REPRESENTED / IGNORED
    / UNRESOLVED. Shared by every construct whose payload is "a target".

    The literal `raw_target` string is carried on `extra`, never inside
    `representation` — `fingerprint.py` fingerprints a fact as a pure function
    of `(kind, representation)`, so anything in `representation` participates
    in change detection. Two re-encodings of the same resource (`%7E` vs `~`)
    must fingerprint identically; putting the raw string in `representation`
    would make every meaningless re-encoding look like a changed fact, which
    is the mirror-image of the bug this lane exists to fix.
    """
    if malformed:
        return _fact(
            kind, construct, start, end, raw,
            state=UNRESOLVED, reason="malformed target/title syntax", extra=extra,
        )
    if not raw_target:
        return _fact(
            kind, construct, start, end, raw,
            state=UNRESOLVED, reason="empty target", extra=extra,
        )
    if any(ch.isspace() for ch in raw_target):
        return _fact(
            kind, construct, start, end, raw,
            state=UNRESOLVED,
            reason=f"target contains unescaped whitespace: {raw_target!r}",
            extra={**(extra or {}), "raw_target": raw_target},
        )
    representation = _normalize_target(raw_target)
    if title:
        representation["title"] = title
    merged_extra = {**(extra or {}), "raw_target": raw_target}
    if representation["kind"] == "fragment":
        # A `#fragment` target only resolves through the document's id
        # namespace. Zero declarations or more than one are both cases the
        # source itself does not decide — REPRESENTED would assert a fact
        # the source does not determine (adv-010's naive failure).
        fragment_name = representation["fragment"] or ""
        count = _declared_id_counts(raw).get(fragment_name, 0) if fragment_name else 0
        if count == 0:
            return _fact(
                kind, construct, start, end, raw,
                state=UNRESOLVED,
                reason=f"fragment target #{fragment_name} is not declared by any id in the source",
                extra=merged_extra,
            )
        if count > 1:
            return _fact(
                kind, construct, start, end, raw,
                state=UNRESOLVED,
                reason=(
                    f"fragment target #{fragment_name} is ambiguous: {count} elements "
                    "declare that id"
                ),
                extra=merged_extra,
            )
    if representation["scheme"] in _IGNORED_SCHEMES:
        return _fact(
            kind, construct, start, end, raw,
            state=IGNORED, policy_ref=POLICY_REF_001, extra=merged_extra,
        )
    return _fact(
        kind, construct, start, end, raw,
        state=REPRESENTED, representation=representation, extra=merged_extra,
    )


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(s < end and start < e for s, e in spans)


# ---------------------------------------------------------------------------
# markdown inline link / image — `[text](target "title")`, `![alt](target)`


def _extract_inline(raw: bytes) -> tuple[list[SourceFact], list[tuple[int, int]]]:
    facts: list[SourceFact] = []
    spans: list[tuple[int, int]] = []
    for match in _INLINE_RE.finditer(raw):
        start, end = match.start(), match.end()
        spans.append((start, end))
        construct = "md-image" if match.group(1) == b"!" else "md-inline-link"
        target, title, malformed = _parse_inner(match.group(3))
        facts.append(_target_fact(REFERENCE_TARGET, construct, start, end, raw, target,
                                   malformed=malformed, title=title))
    return facts, spans


# ---------------------------------------------------------------------------
# markdown link reference definitions — `[label]: target "title"`


def _definitions_index(raw: bytes) -> dict[str, tuple[str, str | None]]:
    index: dict[str, tuple[str, str | None]] = {}
    for match in _DEF_LINE_RE.finditer(raw):
        label = match.group(1).decode("utf-8", "replace")
        target, title, malformed = _parse_inner(match.group(2))
        if not malformed and target:
            index.setdefault(label.casefold(), (target, title))
    return index


def _definition_spans(raw: bytes) -> list[tuple[int, int]]:
    # The `[label]` inside `[label]: target` is definition syntax, not a
    # shortcut reference use — its span must be excluded from shortcut
    # scanning or the label bracket gets double-counted as its own use.
    return [(match.start(), match.end()) for match in _DEF_LINE_RE.finditer(raw)]


def _extract_reference_definitions(raw: bytes) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for match in _DEF_LINE_RE.finditer(raw):
        label = match.group(1).decode("utf-8", "replace")
        start, end = match.start(), match.end()
        target, title, malformed = _parse_inner(match.group(2))
        if malformed:
            facts.append(_fact(REFERENCE_DEFINITION, "md-ref-definition", start, end, raw,
                                state=UNRESOLVED,
                                reason=f"malformed reference definition for label {label!r}"))
            continue
        if not target:
            facts.append(_fact(REFERENCE_DEFINITION, "md-ref-definition", start, end, raw,
                                state=UNRESOLVED,
                                reason=f"empty target in reference definition for label {label!r}"))
            continue
        representation = _normalize_target(target)
        representation["label"] = label
        if title:
            representation["title"] = title
        extra = {"raw_target": target}
        if representation["scheme"] in _IGNORED_SCHEMES:
            facts.append(_fact(REFERENCE_DEFINITION, "md-ref-definition", start, end, raw,
                                state=IGNORED, policy_ref=POLICY_REF_001, extra=extra))
            continue
        facts.append(_fact(REFERENCE_DEFINITION, "md-ref-definition", start, end, raw,
                            state=REPRESENTED, representation=representation, extra=extra))
    return facts


# ---------------------------------------------------------------------------
# markdown reference-style use — `[text][label]`, `[text][]`, and shortcut `[label]`


def _reference_use_fact(construct: str, start: int, end: int, raw: bytes, label: str,
                         defs: dict[str, tuple[str, str | None]]) -> SourceFact:
    entry = defs.get(label.casefold())
    if entry is None:
        return _fact(REFERENCE_TARGET, construct, start, end, raw,
                      state=UNRESOLVED,
                      reason=f"reference label {label!r} has no matching definition")
    target, title = entry
    representation = _normalize_target(target)
    if title:
        representation["title"] = title
    extra = {"raw_target": target}
    if representation["scheme"] in _IGNORED_SCHEMES:
        return _fact(REFERENCE_TARGET, construct, start, end, raw,
                      state=IGNORED, policy_ref=POLICY_REF_001, extra=extra)
    return _fact(REFERENCE_TARGET, construct, start, end, raw,
                 state=REPRESENTED, representation={"label": label, "target": representation},
                 extra=extra)


def _extract_reference_uses_full(
    raw: bytes, defs: dict[str, tuple[str, str | None]]
) -> tuple[list[SourceFact], list[tuple[int, int]]]:
    facts: list[SourceFact] = []
    spans: list[tuple[int, int]] = []
    for match in _REF_USE_FULL_RE.finditer(raw):
        start, end = match.start(), match.end()
        spans.append((start, end))
        text = match.group(1).decode("utf-8", "replace")
        label_raw = match.group(2).decode("utf-8", "replace")
        construct = "md-ref-use-collapsed" if label_raw == "" else "md-ref-use-full"
        label = text if label_raw == "" else label_raw
        facts.append(_reference_use_fact(construct, start, end, raw, label, defs))
    return facts, spans


def _extract_reference_uses_shortcut(
    raw: bytes, defs: dict[str, tuple[str, str | None]], consumed: list[tuple[int, int]]
) -> list[SourceFact]:
    # Scoped deliberately: a bare `[label]` is everywhere in ordinary prose
    # ("see [1]", "[TODO]"). Treating every such bracket as reference syntax
    # would manufacture UNRESOLVED noise out of plain text. The shortcut
    # reference form is only meaningful in a document that actually uses
    # reference-style definitions, so scanning for it is gated on at least
    # one definition existing — a documented scope limit, not an oversight.
    if not defs:
        return []
    facts: list[SourceFact] = []
    for match in _REF_USE_SHORTCUT_RE.finditer(raw):
        start, end = match.start(), match.end()
        if _overlaps(consumed, start, end):
            continue
        label = match.group(1).decode("utf-8", "replace")
        facts.append(_reference_use_fact("md-ref-use-shortcut", start, end, raw, label, defs))
    return facts


# ---------------------------------------------------------------------------
# autolink — `<https://example.com>`


def _extract_autolinks(raw: bytes) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for match in _AUTOLINK_RE.finditer(raw):
        target = match.group(1).decode("utf-8", "replace")
        facts.append(
            _target_fact(REFERENCE_TARGET, "autolink", match.start(), match.end(), raw, target)
        )
    return facts


# ---------------------------------------------------------------------------
# HTML `<a href>`, `<img src>`, `<link href>`, `<script src>`, `<iframe src>`,
# `<area href>`


def _find_attr(attrs: bytes, name: bytes) -> bytes | None:
    for match in _ATTR_RE.finditer(attrs):
        if match.group(1).lower() != name:
            continue
        for group in (match.group(2), match.group(3), match.group(4)):
            if group is not None:
                return group
    return None


def _extract_html_targets(raw: bytes) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for match in _HTML_TAG_RE.finditer(raw):
        tag = match.group(1).lower()
        attr_name = _HTML_ATTR_BY_TAG[tag]
        value = _find_attr(match.group(2), attr_name)
        if value is None:
            continue  # e.g. a bare `<a name="x">` — not a reference construct
        construct = f"html-{tag.decode()}-{attr_name.decode()}"
        target = value.decode("utf-8", "replace")
        facts.append(
            _target_fact(REFERENCE_TARGET, construct, match.start(), match.end(), raw, target)
        )
    return facts


# ---------------------------------------------------------------------------
# include / transclusion directives


def _extract_html_includes(raw: bytes) -> list[SourceFact]:
    """`<include src="...">`.

    The `src` attribute's own grammar (`_ATTR_RE`/`_find_attr`) has already
    resolved *what the attribute's text is* by the time it reaches here —
    quoted or bare, that text is the whole of the attribute per HTML's own
    rules, so there is no bareword-vs-literal tokenization question the way
    there is for a Jinja/Hugo directive's argument list. What can still make
    that text a target that does not exist until evaluation is a *different*
    template engine's delimiters embedded inside it (Jekyll/Liquid/Django
    `{{ }}`/`{% %}`, a Jinja/Django comment `{# #}`, ERB `<% %>`) — those
    bytes are markup to be evaluated, not a path, even when what is left
    after stripping them would decode to a plausible-looking relative path.
    `include_target.embedded_template_marker` is the taxonomy's route to
    DYNAMIC_COMPUTED for this grammar; see `scope_gate.py` for the proof this
    extractor cannot silently represent a marked-up value as static.
    """
    facts: list[SourceFact] = []
    for match in _HTML_INCLUDE_RE.finditer(raw):
        value = _find_attr(match.group(1), b"src")
        target = None if value is None else value.decode("utf-8", "replace")
        extra = {"directive": "html-include"}
        start, end = match.start(), match.end()
        if value is None:
            facts.append(_fact(
                INCLUDE_TARGET, "html-include-src", start, end, raw,
                state=UNRESOLVED, reason="include tag has no src attribute", extra=extra,
            ))
            continue
        marker = embedded_template_marker(target)
        if marker is not None:
            facts.append(_fact(
                INCLUDE_TARGET, "html-include-src", start, end, raw,
                state=UNREPRESENTED,
                reason=(
                    f"{IncludeTargetClass.DYNAMIC_COMPUTED.value}: src attribute "
                    f"value {target!r} contains the template-engine delimiter "
                    f"{marker!r}; the literal bytes are markup to be evaluated, "
                    "not a path"
                ),
                extra={**extra, "raw_target": target},
            ))
            continue
        facts.append(_target_fact(
            INCLUDE_TARGET, "html-include-src", start, end, raw, target,
            extra=extra,
        ))
    return facts


def _extract_hugo_shortcodes(raw: bytes) -> list[SourceFact]:
    """`{{< include ... >}}` / `{{% include ... %}}`.

    The argument list after the shortcode's own name is the same shape of
    problem as a Jinja `{% include ... %}` tag's argument text — a single
    quoted literal (optionally followed by `key=value` decorators) is
    statically named; an unquoted bareword (a positional Hugo variable
    reference such as `.Param`, or a bareword filename) is ambiguous between
    a literal and a variable for the same reason a Jinja bareword is; and a
    Go template function call such as `(printf "%s.html" .Param)` computes
    its result at render time, so no quoted substring inside it can be taken
    as the target no matter where in the argument list it appears. A prior
    version of this extractor found the first quoted string *anywhere* in
    the shortcode body — including one buried inside such a function call —
    and represented it as the target; that is exactly the class of bug this
    taxonomy exists to close, so this now reuses the same
    `classify_include_expression` the Jinja extractor uses on the same
    "text after the directive name" slice, rather than restating a
    second, laxer decision rule for a grammar that is not actually
    different in the way that matters.
    """
    facts: list[SourceFact] = []
    extra = {"directive": "hugo-shortcode"}
    for match in _SHORTCODE_RE.finditer(raw):
        inner = match.group(1).decode("utf-8", "replace")
        name_match = re.match(r"\s*(\w[\w-]*)", inner)
        if not name_match or name_match.group(1).lower() != "include":
            continue  # a recognised-but-unowned shortcode kind, not ours
        start, end = match.start(), match.end()
        rest = inner[name_match.end():]
        verdict = classify_include_expression(rest)
        if verdict.cls is IncludeTargetClass.STATIC_RESOLVABLE:
            facts.append(_target_fact(
                INCLUDE_TARGET, "hugo-shortcode-include", start, end, raw,
                verdict.target, extra=extra,
            ))
            continue
        state = (
            UNREPRESENTED
            if verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
            else UNRESOLVED
        )
        facts.append(_fact(
            INCLUDE_TARGET, "hugo-shortcode-include", start, end, raw,
            state=state, reason=verdict.reason, extra=extra,
        ))
    return facts


def _extract_jinja_includes(raw: bytes) -> list[SourceFact]:
    """Jinja/Liquid-style single-brace tag: `{% include ... %}`.

    A recognised `include` tag never comes back silent. Its target expression
    is classified by the frozen taxonomy in `source_fact_ir.include_target`:
    a static resolvable target (a single string literal, optionally followed
    by `key=value` decorator arguments) is REPRESENTED through the same
    target grammar as everything else; a dynamic/computed target (an
    unquoted bareword such as a Jinja variable, or a literal glued to
    something else, e.g. `"a" ~ region ~ "b"`) or a malformed/ambiguous
    expression (empty, unterminated quote, an unparseable token) comes back
    fail-closed with a reason naming which — never resolved to a guess and
    never dropped.
    """
    facts: list[SourceFact] = []
    extra = {"directive": "jinja-include"}
    for match in _JINJA_TAG_RE.finditer(raw):
        inner = match.group(1).decode("utf-8", "replace")
        name_match = re.match(r"\s*(\w[\w-]*)", inner)
        if not name_match or name_match.group(1).lower() != "include":
            continue  # a recognised-but-unowned tag kind, not ours
        start, end = match.start(), match.end()
        rest = inner[name_match.end():]
        verdict = classify_include_expression(rest)
        if verdict.cls is IncludeTargetClass.STATIC_RESOLVABLE:
            facts.append(_target_fact(
                INCLUDE_TARGET, "jinja-include", start, end, raw, verdict.target, extra=extra,
            ))
            continue
        state = (
            UNREPRESENTED
            if verdict.cls is IncludeTargetClass.DYNAMIC_COMPUTED
            else UNRESOLVED
        )
        facts.append(_fact(
            INCLUDE_TARGET, "jinja-include", start, end, raw,
            state=state, reason=verdict.reason, extra=extra,
        ))
    return facts


def _extract_mediawiki_templates(raw: bytes) -> list[SourceFact]:
    """`{{Name|args}}`. No taxonomy call here, and that omission is proven,
    not assumed: `_MEDIAWIKI_RE`'s captured group is `(?:[^{}])+?` — its
    character class structurally excludes `{` and `}` from ever appearing in
    `inner`, so a nested transclusion such as `{{ {{PAGENAME}} }}` (a
    genuinely computed template name) can never be captured as part of this
    construct's own name; the regex instead matches the inner `{{PAGENAME}}`
    as its own separate, unrelated construct. The name this function reads —
    `inner.split("|", 1)[0]` — is therefore always literal source bytes with
    no MediaWiki transclusion syntax embedded in it, for every input this
    regex matches at all. `scope_gate.py` drives an executable test of that
    claim (attempted nested-transclusion inputs, asserted to never produce a
    fact whose name contains a brace character) rather than leaving it as
    prose. What that structural exclusion does *not* address — a bare magic
    word like `{{PAGENAME}}` being represented as if it named a literal
    template page, when it is in fact a render-time substitution — is a
    different defect class (dialect/magic-word recognition, not a computed
    *expression* in the `|`-delimited name grammar) and is out of this
    module's scope as owned here.
    """
    facts: list[SourceFact] = []
    extra = {"directive": "mediawiki-template"}
    for match in _MEDIAWIKI_RE.finditer(raw):
        start, end = match.start(), match.end()
        inner = match.group(1).decode("utf-8", "replace")
        if not inner.strip():
            facts.append(_fact(
                INCLUDE_TARGET, "mediawiki-template", start, end, raw,
                state=UNRESOLVED, reason="empty mediawiki template reference", extra=extra,
            ))
            continue
        name = inner.split("|", 1)[0].strip()
        name_clean = re.sub(r"(?i)^template:", "", name).strip()
        if not name_clean:
            facts.append(_fact(
                INCLUDE_TARGET, "mediawiki-template", start, end, raw,
                state=UNRESOLVED, reason="mediawiki template has no name", extra=extra,
            ))
            continue
        representation = {
            "normalized": name_clean,
            "scheme": None,
            "kind": "internal",
            "fragment": None,
        }
        facts.append(_fact(INCLUDE_TARGET, "mediawiki-template", start, end, raw,
                            state=REPRESENTED, representation=representation,
                            extra={**extra, "raw_target": inner}))
    return facts


# ---------------------------------------------------------------------------
# CANONICAL_SOURCE_LOCATOR — one per unit
#
# The witness for a locator is real: it is the byte span of the ATX heading
# line that produced the unit (found by re-scanning `raw` for headings and
# matching by cleaned text, in document order, against `document["units"]`).
# Where a unit's heading cannot be found verbatim in `raw` — the only case
# expected today is a source dialect this lane does not scan headings for —
# the fact comes back UNRESOLVED rather than guessing a witness that isn't
# real. `<a name=...>`/`<h2 id=...>` anchor detection for HTML-headed
# documents is not implemented here; only a markdown ATX heading's own
# `{#slug}` attribute (declared) or its derived GitHub-style slug (derived)
# are supported as the fragment.


def _heading_occurrences(raw: bytes) -> list[tuple[int, int, str]]:
    occurrences: list[tuple[int, int, str]] = []
    in_fence = False
    offset = 0
    for line in raw.split(b"\n"):
        line_start = offset
        offset += len(line) + 1
        if _FENCE_LINE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _ATX_LINE_RE.match(line)
        if not match:
            continue
        text = clean_markdown(match.group(2).decode("utf-8", "replace"))
        occurrences.append((line_start, line_start + len(line), text))
    return occurrences


def _heading_fragment(cleaned_heading: str) -> tuple[str | None, str]:
    match = _PANDOC_ID_RE.search(cleaned_heading)
    if match:
        return match.group(1), "declared"
    slug = _slugify(cleaned_heading)
    return (slug or None), ("derived" if slug else "none")


def _extract_locators(raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
    source_id = str(document.get("source_id", ""))
    occurrences = _heading_occurrences(raw)
    facts: list[SourceFact] = []
    pointer = 0
    for unit in document.get("units", []):
        path = tuple(unit["explicit_path"])
        qualified = ir.unit_path_for(source_id, path)
        heading = unit["heading"]
        if heading == "lead":
            # The implicit section before any heading: its location is the
            # start of the document by definition, not something to search
            # for — a zero-length witness there is accurate, not a guess.
            representation = {"path": list(path), "fragment": None, "fragment_source": "none"}
            facts.append(_fact(LOCATOR, "canonical-locator-lead", 0, 0, raw,
                                state=REPRESENTED, representation=representation,
                                unit_path=qualified))
            continue
        match_index = None
        for idx in range(pointer, len(occurrences)):
            if occurrences[idx][2] == heading:
                match_index = idx
                break
        if match_index is None:
            reason = f"heading text for unit {path!r} not found verbatim in raw source"
            facts.append(_fact(
                LOCATOR, "canonical-locator", 0, 0, raw,
                state=UNRESOLVED, reason=reason, unit_path=qualified,
            ))
            continue
        start, end, cleaned = occurrences[match_index]
        pointer = match_index + 1
        fragment, source = _heading_fragment(cleaned)
        representation = {"path": list(path), "fragment": fragment, "fragment_source": source}
        facts.append(_fact(LOCATOR, "canonical-locator", start, end, raw,
                            state=REPRESENTED, representation=representation,
                            unit_path=qualified))
    return facts


# ---------------------------------------------------------------------------
# unit attribution — link 4's anchor, for every fact this module emits
#
# CANONICAL_SOURCE_LOCATOR sets its own unit_path above (it knows its unit
# directly). Everything else is attributed here, in one place, by mapping the
# fact's witness byte offset to a unit span. Spans are built by tolerantly
# locating each unit's canonical *text* in `raw`, mirroring
# `core_extractor._locate`'s three-tier strategy (exact, an 80-byte prefix,
# then whitespace-insensitive) — reimplemented independently rather than
# imported, since the two lanes are siblings and this only needs a start
# offset per unit, not core's full provenance-span semantics.

_WS_RE = re.compile(rb"\s+")


def _locate_unit_text(raw: bytes, needle: str, start: int) -> tuple[int, int] | None:
    if not needle:
        return None
    encoded = needle.encode("utf-8", "replace")

    exact = raw.find(encoded, start)
    if exact != -1:
        return exact, exact + len(encoded)

    head = encoded[:80]
    if len(head) >= 24:
        found = raw.find(head, start)
        if found != -1:
            return found, found + len(head)

    pattern = rb"\s+".join(re.escape(part) for part in _WS_RE.split(encoded[:80]) if part)
    if pattern:
        match = re.compile(pattern).search(raw, start)
        if match:
            return match.start(), match.end()
    return None


def _unit_spans(raw: bytes, document: dict[str, Any]) -> list[tuple[int, int, tuple[str, ...]]]:
    """One `(start, end, explicit_path)` span per unit, in document order.

    A document handed with no `"units"` at all — the adversarial harness's
    shape — yields no spans, and every fact then falls through to document
    scope in `_resolve_unit_path` below. That is the correct answer for that
    shape, not a bug to work around: there are no units to attribute to.
    """
    units = document.get("units") or []
    starts: list[tuple[int, tuple[str, ...]]] = []
    cursor = 0
    for unit in units:
        path = tuple(unit["explicit_path"])
        located = _locate_unit_text(raw, unit.get("text", ""), cursor)
        unit_start = located[0] if located is not None else cursor
        starts.append((unit_start, path))
        if located is not None:
            cursor = located[1]
    spans: list[tuple[int, int, tuple[str, ...]]] = []
    for index, (unit_start, path) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(raw)
        spans.append((unit_start, max(end, unit_start), path))
    return spans


def _resolve_unit_path(
    spans: list[tuple[int, int, tuple[str, ...]]], source_id: str, offset: int
) -> tuple[str, ...]:
    for start, end, path in spans:
        if start <= offset < end or (start == end and offset == start):
            return ir.unit_path_for(source_id, path)
    # Outside every unit's span, including the common case of no units at
    # all. Document scope, never left unanchored: fingerprint.UnanchoredFact
    # exists precisely to refuse the alternative.
    return ir.unit_path_for(source_id, ())


def _anchor_facts(
    facts: list[SourceFact], raw: bytes, document: dict[str, Any]
) -> list[SourceFact]:
    """Give every fact a document-qualified `witness.unit_path`.

    LOCATOR facts already carry one (set at construction, above) and are
    passed through unchanged. Every other fact is rebuilt — `SourceFact` and
    `Witness` are both frozen dataclasses — with `unit_path` resolved from
    its own byte offset. One pass, one policy, so unit attribution cannot
    drift between kinds.
    """
    source_id = str(document.get("source_id", ""))
    spans = _unit_spans(raw, document)
    anchored: list[SourceFact] = []
    for fact in facts:
        if fact.witness.unit_path is not None:
            anchored.append(fact)
            continue
        unit_path = _resolve_unit_path(spans, source_id, fact.witness.byte_start)
        witness = dataclasses.replace(fact.witness, unit_path=unit_path)
        anchored.append(dataclasses.replace(fact, witness=witness))
    return anchored


# ---------------------------------------------------------------------------
# the extractor


class ReferenceExtractor:
    kinds: tuple[str, ...] = (REFERENCE_TARGET, REFERENCE_DEFINITION, INCLUDE_TARGET, LOCATOR)

    def extract(self, *, raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
        facts: list[SourceFact] = []

        inline_facts, inline_spans = _extract_inline(raw)
        facts.extend(inline_facts)

        defs = _definitions_index(raw)
        facts.extend(_extract_reference_definitions(raw))

        full_facts, full_spans = _extract_reference_uses_full(raw, defs)
        facts.extend(full_facts)
        excluded_spans = inline_spans + full_spans + _definition_spans(raw)
        facts.extend(_extract_reference_uses_shortcut(raw, defs, excluded_spans))

        facts.extend(_extract_autolinks(raw))
        facts.extend(_extract_html_targets(raw))
        facts.extend(_extract_html_includes(raw))
        facts.extend(_extract_hugo_shortcodes(raw))
        facts.extend(_extract_jinja_includes(raw))
        facts.extend(_extract_mediawiki_templates(raw))
        facts.extend(_extract_locators(raw, document))

        return _anchor_facts(facts, raw, document)


reference_extractor = ReferenceExtractor()
ir.register(reference_extractor)
