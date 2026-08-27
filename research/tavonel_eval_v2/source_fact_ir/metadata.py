"""LANGUAGE, ACCESSIBILITY, APPLICABILITY, EFFECTIVE_TIME, AUTHORITY.

Lane 3's five kinds, per the ownership table in `ir.KIND_OWNER`. All five are
descriptive/temporal facets: today the compiled state carries unit text,
headings, paths and order and nothing else, so a document whose language
attribute changes, whose image alt text changes, whose applicability note
changes or whose effective date changes produces no delta at all while the
body prose is untouched. Those facts are made first-class typed facts here.

Where this extractor reads from matters. `canonicalization/canonical_document.py`
strips every HTML tag (`HTML_TAG.sub`), every markdown link/emphasis marker
and the whole YAML front-matter block *before* a unit's text is stored — see
`clean_markdown` and `sections_from_markdown`/`SecHtmlReader`. None of the
constructs this lane owns survive into `document["units"]`. So extraction
here works against `raw` (the undecoded source bytes), not against the
canonicalized document; `document` is read for `source_id` (every witness is
document-qualified, see below) and is otherwise unused today -- the same
regex vocabulary covers both the markdown+front-matter grammar and the
constrained HTML/XML subset, so no branch on `source_family` is needed yet.

Witness byte offsets are computed by decoding `raw` once (utf-8, matching the
canonicalizer's own decode step) and re-encoding the prefix up to each match:
`len(text[:start].encode("utf-8"))`. That is exact for well-formed UTF-8
source, which is what this corpus is.

Every witness this lane produces is anchored with `ir.unit_path_for(source_id,
...)`, never a bare tuple. A bare, unqualified path still looks like a path,
still hashes, still compares -- and anchors the fact to the wrong artifact, or
to none, silently. This lane cannot recover which canonical *unit* a raw
match fell inside (canonicalization discards byte offsets once it strips tags
and front matter -- see the module note above), so every witness here is
anchored at the *document* level: `ir.unit_path_for(source_id, ())`. That is
honest about what this extractor actually knows: which document, not which
unit. Claiming a specific unit without a real mapping to one would be worse
than an admittedly document-level anchor -- it would look precise and be wrong.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

# Two-step import so this module resolves identically whether it is loaded as
# a package member (`from source_fact_ir import metadata`) or flat, with
# `source_fact_ir/` itself on `sys.path` (`import metadata`, the convention the
# sibling-extractor loader in tests/test_sfi_adversarial.py and
# source_fact_ir/core_extractor.py both use). Only the package-relative form
# resolves under the first caller; only the bare form resolves under the
# second. Falling back silently on ImportError, rather than picking one and
# letting the other caller's import fail, is exactly what keeps a broken
# import from manufacturing a false "no extractor produces LANGUAGE" pass.
try:  # loaded as a package member
    from . import ir
    from .ir import SourceFact, Witness
except ImportError:  # loaded flat, with source_fact_ir/ on sys.path
    import ir
    from ir import SourceFact, Witness

# ---------------------------------------------------------------------------
# predeclared policy table
#
# Every IGNORED fact this extractor can emit cites one of these. Keeping the
# whole table here (rather than a string inlined at each call site) is the
# point: a reader who wants to see everything this lane declines in advance
# reads this dict once instead of hunting the code for `state=ir.IGNORED`.

POLICY: dict[str, str] = {
    "POLICY-META-001": (
        "a `title` attribute on an element other than <a>/<abbr> is presentational "
        "in this grammar -- it duplicates visible text far more often than it adds "
        "an accessible name that is not otherwise available -- and is declined "
        "rather than represented."
    ),
    "POLICY-META-002": (
        "an attribute or element this extractor recognises whose value is the "
        "empty string carries no fact (the canonical case is alt=\"\" on a "
        "deliberately decorative image); declined rather than represented as an "
        "empty string or treated as ambiguous."
    ),
}

MONTHS: dict[str, int] = {
    name: index
    for index, name in enumerate(
        (
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        ),
        start=1,
    )
}

# ---------------------------------------------------------------------------
# grammar

# Both quote styles are valid HTML/XML and the grammar this lane serves does
# not pick one -- adv-008 in the adversarial corpus is exactly this: a
# quote-style-only edit (`lang="en"` -> `lang='en'`) that must produce zero
# delta. Matching only double quotes would make the LANGUAGE/ACCESSIBILITY
# fact vanish on a semantically identical revision, which is a false delta.
ATTR_RE = re.compile(r'''([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)')''')
TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^>]*)>", re.DOTALL)
ID_ELEMENT_RE = re.compile(
    r"""<([a-zA-Z][a-zA-Z0-9]*)\b[^>]*\bid=(?:"([^"]+)"|'([^']+)')[^>]*>(.*?)</\1>""",
    re.DOTALL,
)
FRONT_MATTER_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n", re.DOTALL)
FM_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.+?)\s*$", re.MULTILINE)
FIGCAPTION_RE = re.compile(r"<figcaption[^>]*>(.*?)</figcaption>", re.DOTALL | re.IGNORECASE)
CAPTION_RE = re.compile(r"<caption[^>]*>(.*?)</caption>", re.DOTALL | re.IGNORECASE)
APPLICABILITY_LABEL_RE = re.compile(r"Applicability\.\s+([^\n]+)")
EXCEPT_RE = re.compile(r"(Except as provided in[^\n.]+\.)")
AUTHORITY_CITE_RE = re.compile(r"(?:^|\n)Authority:\s*([^\n]+)")
AGENCY_RE = re.compile(r"(?:^|\n)Agency:\s*([^\n]+)")
EFFECTIVE_LABEL_RE = re.compile(r"(?:^|\n)Effective [Dd]ate:\s*([^\n]+)")
PERIOD_OF_REPORT_RE = re.compile(r"(?:^|\n)Period of Report:\s*([^\n]+)")

FRONT_MATTER_LANGUAGE_KEYS = frozenset({"lang", "language"})
FRONT_MATTER_APPLICABILITY_KEYS = frozenset(
    {"applies_to", "scope", "audience", "platform", "version", "deprecated"}
)
FRONT_MATTER_TIME_KEYS = frozenset({"date", "updated", "effective"})
FRONT_MATTER_AUTHORITY_KEYS = frozenset({"author", "owner", "maintainer", "filer"})

TITLE_HOST_TAGS = frozenset({"a", "abbr"})
CELL_TAGS = frozenset({"td", "th"})

# a fact kind for each front-matter key group, so an empty-valued front-matter
# line can still be reported UNRESOLVED against the right kind.
_FRONT_MATTER_KIND: dict[str, str] = {}
for _key in FRONT_MATTER_LANGUAGE_KEYS:
    _FRONT_MATTER_KIND[_key] = ir.LANGUAGE
for _key in FRONT_MATTER_APPLICABILITY_KEYS:
    _FRONT_MATTER_KIND[_key] = ir.APPLICABILITY
for _key in FRONT_MATTER_TIME_KEYS:
    _FRONT_MATTER_KIND[_key] = ir.EFFECTIVE_TIME
for _key in FRONT_MATTER_AUTHORITY_KEYS:
    _FRONT_MATTER_KIND[_key] = ir.AUTHORITY


# ---------------------------------------------------------------------------
# small shared helpers


def _byte_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Char offsets in the decoded text -> byte offsets in `raw`.

    Witnesses point into the raw payload, never into the decoded string, so
    every offset here is produced by re-encoding the prefix rather than
    reused from anywhere the canonicalizer already measured.
    """
    byte_start = len(text[:start].encode("utf-8"))
    byte_end = byte_start + len(text[start:end].encode("utf-8"))
    return byte_start, byte_end


def _witness(
    text: str, start: int, end: int, construct: str, unit_path: tuple[str, ...]
) -> Witness:
    byte_start, byte_end = _byte_span(text, start, end)
    return Witness(
        construct=construct,
        byte_start=byte_start,
        byte_end=byte_end,
        excerpt=text[start:end],
        unit_path=unit_path,
    )


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1].strip()
    return value


def _clean_inner(raw_inner: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", raw_inner)
    return re.sub(r"\s+", " ", stripped).strip()


def _quoted_value(match: re.Match[str], dq_group: int, sq_group: int) -> tuple[str, int, int]:
    """Pick whichever quote-style group actually matched.

    A non-participating alternation group returns None from `.group()`, not
    an empty string, so this is the one place that can tell "double-quoted
    and empty" apart from "the single-quoted branch matched instead" -- an
    ambiguity `.findall()` would silently collapse.
    """
    if match.group(dq_group) is not None:
        return match.group(dq_group), match.start(dq_group), match.end(dq_group)
    return match.group(sq_group), match.start(sq_group), match.end(sq_group)


def _normalise_lang_tag(raw_value: str) -> str | None:
    """BCP-47, case-folded with a canonical hyphen separator.

    Not a full BCP-47 registry validator -- this extractor serves document
    metadata, not language-tag validation -- but it does reject values that
    are not even shaped like a language tag, which is what turns a malformed
    tag into UNRESOLVED instead of a silently accepted guess.
    """
    candidate = raw_value.strip().replace("_", "-")
    if not re.fullmatch(r"[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*", candidate):
        return None
    return candidate.lower()


def _normalise_date(raw_value: str) -> tuple[str | None, str | None]:
    """Return (iso, None) on success or (None, reason) on failure.

    Never guesses: an ambiguous numeric date (MM/DD vs DD/MM) and a datetime
    with a time-of-day but no declared timezone both come back as failures,
    per the hard project rule against inferring dates.
    """
    value = raw_value.strip().rstrip(".,")
    iso_match = re.fullmatch(
        r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?)?",
        value,
    )
    if iso_match:
        year, month, day, hour, _minute, _second, tz = iso_match.groups()
        try:
            date(int(year), int(month), int(day))
        except ValueError:
            return None, f"{value!r} is not a valid calendar date"
        if hour is not None and tz is None:
            return None, f"{value!r} has a time of day with no declared timezone"
        return (f"{year}-{month}-{day}" if hour is None else value), None
    month_first = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", value)
    day_first = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", value)
    named_match = month_first or day_first
    if named_match:
        if month_first:
            month_name, day_str, year_str = named_match.groups()
        else:
            day_str, month_name, year_str = named_match.groups()
        month = MONTHS.get(month_name.lower())
        if month is None:
            return None, f"{value!r} names an unrecognised month"
        try:
            date(int(year_str), month, int(day_str))
        except ValueError:
            return None, f"{value!r} is not a valid calendar date"
        return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}", None
    if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", value):
        return None, (
            f"{value!r} is an ambiguous numeric date (MM/DD vs DD/MM is not "
            "determinable from the source alone)"
        )
    return None, f"{value!r} is not a date format this extractor supports"


def _language_fact(
    text: str,
    start: int,
    end: int,
    raw_value: str,
    *,
    scope: str,
    construct: str,
    unit_path: tuple[str, ...],
    extra: dict[str, Any] | None = None,
) -> SourceFact:
    witness = _witness(text, start, end, construct, unit_path)
    normalised = _normalise_lang_tag(raw_value)
    if normalised is None:
        return SourceFact(
            kind=ir.LANGUAGE,
            witness=witness,
            state=ir.UNRESOLVED,
            reason=f"{raw_value!r} is not shaped like a BCP-47 language tag",
        )
    representation: dict[str, Any] = {"tag": normalised, "raw": raw_value, "scope": scope}
    if extra:
        representation.update(extra)
    return SourceFact(
        kind=ir.LANGUAGE, witness=witness, state=ir.REPRESENTED, representation=representation
    )


def _effective_time_fact(
    text: str,
    start: int,
    end: int,
    raw_value: str,
    *,
    role: str,
    construct: str,
    unit_path: tuple[str, ...],
) -> SourceFact:
    witness = _witness(text, start, end, construct, unit_path)
    iso, reason = _normalise_date(raw_value)
    if iso is None:
        return SourceFact(
            kind=ir.EFFECTIVE_TIME, witness=witness, state=ir.UNRESOLVED, reason=reason
        )
    return SourceFact(
        kind=ir.EFFECTIVE_TIME,
        witness=witness,
        state=ir.REPRESENTED,
        representation={"role": role, "iso": iso, "raw": raw_value},
    )


def _accessibility_value_fact(
    text: str, start: int, end: int, value: str, *, construct: str, unit_path: tuple[str, ...]
) -> SourceFact:
    witness = _witness(text, start, end, construct, unit_path)
    if value == "":
        return SourceFact(
            kind=ir.ACCESSIBILITY, witness=witness, state=ir.IGNORED, policy_ref="POLICY-META-002"
        )
    return SourceFact(
        kind=ir.ACCESSIBILITY,
        witness=witness,
        state=ir.REPRESENTED,
        representation={"construct": construct, "text": value},
    )


# ---------------------------------------------------------------------------
# front matter


def _front_matter(text: str, unit_path: tuple[str, ...]) -> list[SourceFact]:
    facts: list[SourceFact] = []
    block = FRONT_MATTER_RE.match(text)
    if block is None:
        return facts
    body = block.group(1)
    body_offset = block.start(1)
    for line_match in FM_LINE_RE.finditer(body):
        key = line_match.group(1).lower()
        kind = _FRONT_MATTER_KIND.get(key)
        if kind is None:
            continue  # a front-matter key this lane does not own; not ours to speak for
        raw_value = _strip_quotes(line_match.group(2))
        start = body_offset + line_match.start(2)
        end = body_offset + line_match.end(2)
        construct = f"front-matter:{key}"
        if raw_value == "":
            facts.append(
                SourceFact(
                    kind=kind,
                    witness=_witness(text, start, end, construct, unit_path),
                    state=ir.UNRESOLVED,
                    reason=f"front-matter key {key!r} has an empty value",
                )
            )
            continue
        if key in FRONT_MATTER_LANGUAGE_KEYS:
            facts.append(
                _language_fact(
                    text, start, end, raw_value,
                    scope="document", construct=construct, unit_path=unit_path,
                )
            )
        elif key in FRONT_MATTER_APPLICABILITY_KEYS:
            facts.append(
                SourceFact(
                    kind=ir.APPLICABILITY,
                    witness=_witness(text, start, end, construct, unit_path),
                    state=ir.REPRESENTED,
                    representation={"source": "front_matter", "key": key, "value": raw_value},
                )
            )
        elif key in FRONT_MATTER_TIME_KEYS:
            facts.append(
                _effective_time_fact(
                    text, start, end, raw_value, role=key, construct=construct, unit_path=unit_path
                )
            )
        elif key in FRONT_MATTER_AUTHORITY_KEYS:
            facts.append(
                SourceFact(
                    kind=ir.AUTHORITY,
                    witness=_witness(text, start, end, construct, unit_path),
                    state=ir.REPRESENTED,
                    representation={"source": "front_matter", "role": key, "name": raw_value},
                )
            )
    return facts


# ---------------------------------------------------------------------------
# HTML/XML attributes and elements


def _build_id_index(text: str) -> dict[str, str]:
    """id -> cleaned inner text, for resolving `aria-describedby`."""
    index: dict[str, str] = {}
    for match in ID_ELEMENT_RE.finditer(text):
        element_id = match.group(2) if match.group(2) is not None else match.group(3)
        index[element_id] = _clean_inner(match.group(4))
    return index


def _aria_describedby_fact(
    text: str,
    start: int,
    end: int,
    value: str,
    id_index: dict[str, str],
    unit_path: tuple[str, ...],
) -> SourceFact:
    witness = _witness(text, start, end, "aria-describedby", unit_path)
    ids = value.split()
    if not ids:
        return SourceFact(
            kind=ir.ACCESSIBILITY, witness=witness, state=ir.IGNORED, policy_ref="POLICY-META-002"
        )
    missing = [element_id for element_id in ids if element_id not in id_index]
    if missing:
        # The construct itself is fully understood -- it is a well-formed
        # accessibility hook naming id(s) to describe this element -- what is
        # missing is the resolved description *content*, which is what a
        # canonical representation of this fact would actually need to carry.
        # That is a representation gap, not a malformed or ambiguous source,
        # so RECOGNIZED_BUT_UNREPRESENTED rather than UNRESOLVED.
        return SourceFact(
            kind=ir.ACCESSIBILITY,
            witness=witness,
            state=ir.UNREPRESENTED,
            reason=(
                f"aria-describedby references id(s) {missing!r} with no matching element "
                "in this payload; the referenced description text is unavailable to canonicalise"
            ),
        )
    resolved = {element_id: id_index[element_id] for element_id in ids}
    return SourceFact(
        kind=ir.ACCESSIBILITY,
        witness=witness,
        state=ir.REPRESENTED,
        representation={"construct": "aria-describedby", "ids": ids, "text": resolved},
    )


def _meta_fact(
    text: str,
    attrs: dict[str, str],
    attrs_text: str,
    attrs_offset: int,
    unit_path: tuple[str, ...],
) -> list[SourceFact]:
    name = attrs.get("name")
    content = attrs.get("content")
    if name is None or content is None:
        return []
    content_match = re.search(r'''content\s*=\s*(?:"([^"]*)"|'([^']*)')''', attrs_text)
    if content_match is None:
        return []
    _value, value_start, value_end = _quoted_value(content_match, 1, 2)
    start = attrs_offset + value_start
    end = attrs_offset + value_end
    construct = f"<meta name={name}>"
    if name == "author":
        if content == "":
            return [
                SourceFact(
                    kind=ir.AUTHORITY, witness=_witness(text, start, end, construct, unit_path),
                    state=ir.IGNORED, policy_ref="POLICY-META-002",
                )
            ]
        return [
            SourceFact(
                kind=ir.AUTHORITY,
                witness=_witness(text, start, end, construct, unit_path),
                state=ir.REPRESENTED,
                representation={"source": "meta", "role": "author", "name": content},
            )
        ]
    if name in ("date", "effective-date"):
        # `effective-date` is eCFR/SEC/EDGAR head-metadata style; `date` is the
        # generic HTML convention. Both name the same TEMPORAL fact.
        return [
            _effective_time_fact(
                text, start, end, content, role=f"meta-{name}", construct=construct,
                unit_path=unit_path,
            )
        ]
    if name == "applicability":
        if content == "":
            return [
                SourceFact(
                    kind=ir.APPLICABILITY, witness=_witness(text, start, end, construct, unit_path),
                    state=ir.IGNORED, policy_ref="POLICY-META-002",
                )
            ]
        return [
            SourceFact(
                kind=ir.APPLICABILITY,
                witness=_witness(text, start, end, construct, unit_path),
                state=ir.REPRESENTED,
                representation={"source": "meta", "statement": content},
            )
        ]
    return []


def _attribute_facts(text: str, unit_path: tuple[str, ...]) -> list[SourceFact]:
    facts: list[SourceFact] = []
    id_index = _build_id_index(text)
    for tag_match in TAG_RE.finditer(text):
        tag = tag_match.group(1).lower()
        attrs_text = tag_match.group(2)
        attrs_offset = tag_match.start(2)
        attrs: dict[str, str] = {}
        for _m in ATTR_RE.finditer(attrs_text):
            _value, _vs, _ve = _quoted_value(_m, 2, 3)
            attrs[_m.group(1).lower()] = _value
        for attr_match in ATTR_RE.finditer(attrs_text):
            name = attr_match.group(1).lower()
            value, value_start, value_end = _quoted_value(attr_match, 2, 3)
            start = attrs_offset + value_start
            end = attrs_offset + value_end
            construct = f"<{tag} {name}>"
            if name in ("lang", "xml:lang"):
                scope = "document" if tag == "html" else "element"
                extra = None if scope == "document" else {"tag": tag}
                facts.append(
                    _language_fact(
                        text, start, end, value, scope=scope, construct=construct,
                        unit_path=unit_path, extra=extra,
                    )
                )
            elif name == "hreflang" and tag == "a":
                facts.append(
                    _language_fact(
                        text, start, end, value,
                        scope="link", construct=construct, unit_path=unit_path,
                    )
                )
            elif name == "alt" and tag == "img":
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct="img-alt", unit_path=unit_path
                    )
                )
            elif name == "title" and tag in TITLE_HOST_TAGS:
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct=f"{tag}-title", unit_path=unit_path
                    )
                )
            elif name == "title":
                facts.append(
                    SourceFact(
                        kind=ir.ACCESSIBILITY,
                        witness=_witness(text, start, end, construct, unit_path),
                        state=ir.IGNORED,
                        policy_ref="POLICY-META-001",
                    )
                )
            elif name == "aria-label":
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct="aria-label", unit_path=unit_path
                    )
                )
            elif name == "aria-describedby":
                facts.append(
                    _aria_describedby_fact(text, start, end, value, id_index, unit_path)
                )
            elif name == "scope" and tag in CELL_TAGS:
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct="cell-scope", unit_path=unit_path
                    )
                )
            elif name == "headers" and tag in CELL_TAGS:
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct="cell-headers", unit_path=unit_path
                    )
                )
            elif name == "summary" and tag == "table":
                facts.append(
                    _accessibility_value_fact(
                        text, start, end, value, construct="table-summary", unit_path=unit_path
                    )
                )
            elif name == "datetime" and tag == "time":
                facts.append(
                    _effective_time_fact(
                        text, start, end, value, role="time-element", construct=construct,
                        unit_path=unit_path,
                    )
                )
            elif name == "data-applies-to":
                # The HTML-embedded analogue of front-matter `applies_to`: a
                # jurisdiction/scope note carried as a `data-*` attribute
                # rather than prose. Easy to mistake for vendor decoration
                # (that is the whole adversarial point of it) -- dropping it
                # silently would make a document apply somewhere the compiled
                # state has no record of it entering.
                if value == "":
                    facts.append(
                        SourceFact(
                            kind=ir.APPLICABILITY,
                            witness=_witness(text, start, end, construct, unit_path),
                            state=ir.IGNORED,
                            policy_ref="POLICY-META-002",
                        )
                    )
                else:
                    facts.append(
                        SourceFact(
                            kind=ir.APPLICABILITY,
                            witness=_witness(text, start, end, construct, unit_path),
                            state=ir.REPRESENTED,
                            representation={
                                "source": "attribute", "construct": "data-applies-to",
                                "value": value,
                            },
                        )
                    )
        if tag == "meta":
            facts.extend(_meta_fact(text, attrs, attrs_text, attrs_offset, unit_path))
    facts.extend(_element_text_facts(text, FIGCAPTION_RE, "figcaption", unit_path))
    facts.extend(_element_text_facts(text, CAPTION_RE, "table-caption", unit_path))
    return facts


def _element_text_facts(
    text: str, pattern: re.Pattern[str], construct: str, unit_path: tuple[str, ...]
) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for match in pattern.finditer(text):
        inner = _clean_inner(match.group(1))
        facts.append(
            _accessibility_value_fact(
                text, match.start(1), match.end(1), inner, construct=construct, unit_path=unit_path
            )
        )
    return facts


# ---------------------------------------------------------------------------
# plain-text patterns (eCFR / SEC prose, not markup)


def _plain_text_facts(text: str, unit_path: tuple[str, ...]) -> list[SourceFact]:
    facts: list[SourceFact] = []
    for match in APPLICABILITY_LABEL_RE.finditer(text):
        statement = match.group(1).strip()
        facts.append(
            SourceFact(
                kind=ir.APPLICABILITY,
                witness=_witness(
                    text, match.start(1), match.end(1), "applicability-label", unit_path
                ),
                state=ir.REPRESENTED,
                representation={
                    "source": "prose", "label": "Applicability", "statement": statement,
                },
            )
        )
    for match in EXCEPT_RE.finditer(text):
        statement = match.group(1).strip()
        facts.append(
            SourceFact(
                kind=ir.APPLICABILITY,
                witness=_witness(
                    text, match.start(1), match.end(1), "applicability-exception", unit_path
                ),
                state=ir.REPRESENTED,
                representation={"source": "prose", "label": "exception", "statement": statement},
            )
        )
    for match in AUTHORITY_CITE_RE.finditer(text):
        citation = match.group(1).strip()
        facts.append(
            SourceFact(
                kind=ir.AUTHORITY,
                witness=_witness(
                    text, match.start(1), match.end(1), "authority-citation", unit_path
                ),
                state=ir.REPRESENTED,
                representation={"source": "prose", "role": "citation", "name": citation},
            )
        )
    for match in AGENCY_RE.finditer(text):
        agency = match.group(1).strip()
        facts.append(
            SourceFact(
                kind=ir.AUTHORITY,
                witness=_witness(text, match.start(1), match.end(1), "issuing-agency", unit_path),
                state=ir.REPRESENTED,
                representation={"source": "prose", "role": "agency", "name": agency},
            )
        )
    for match in EFFECTIVE_LABEL_RE.finditer(text):
        facts.append(
            _effective_time_fact(
                text, match.start(1), match.end(1), match.group(1).strip(),
                role="effective", construct="effective-date-label", unit_path=unit_path,
            )
        )
    for match in PERIOD_OF_REPORT_RE.finditer(text):
        facts.append(
            _effective_time_fact(
                text, match.start(1), match.end(1), match.group(1).strip(),
                role="period_of_report", construct="period-of-report", unit_path=unit_path,
            )
        )
    return facts


# ---------------------------------------------------------------------------
# the extractor


class MetadataExtractor:
    """The descriptive/temporal facet extractor: lane 3 of SOURCE_FACT_IR_V1.

    Owns exactly `LANGUAGE`, `ACCESSIBILITY`, `APPLICABILITY`, `EFFECTIVE_TIME`
    and `AUTHORITY` (see `ir.KIND_OWNER`). Reads `raw` because none of these
    constructs survive canonicalization into `document["units"]` -- see the
    module docstring.
    """

    kinds: tuple[str, ...] = (
        ir.LANGUAGE, ir.ACCESSIBILITY, ir.APPLICABILITY, ir.EFFECTIVE_TIME, ir.AUTHORITY,
    )

    def extract(self, *, raw: bytes, document: dict[str, Any]) -> list[SourceFact]:
        # document["source_id"] is required, not defaulted: a document this
        # extractor cannot identify is a fact it cannot honestly anchor, and a
        # silent fallback value would manufacture a wrong-looking anchor
        # instead of failing loudly. See module docstring for why every
        # witness here is document-level (`unit_path_for(source_id, ())`)
        # rather than naming a specific unit.
        unit_path = ir.unit_path_for(document["source_id"], ())
        text = raw.decode("utf-8", errors="replace")
        facts: list[SourceFact] = []
        facts.extend(_front_matter(text, unit_path))
        facts.extend(_attribute_facts(text, unit_path))
        facts.extend(_plain_text_facts(text, unit_path))
        return facts


EXTRACTOR = ir.register(MetadataExtractor())
