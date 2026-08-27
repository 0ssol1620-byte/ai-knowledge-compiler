"""The markup classification policy. Data, sealed by its own content hash.

Founder ruling, 2026-08-22. This file is **policy, not code**. Its digest is
computed over the declared mapping itself — not over the file bytes and not over
the code that reads it — so reformatting or re-commenting cannot move it while
reclassifying a single attribute always does. Sealing only a tool digest would
leave a loophole in which the semantics change and the seal does not notice.

The test for modelling is no longer "is it user-visible prose". It is:

    can a change to this source construct change the compiled interpretation
    or a downstream artifact?

If yes, it is a canonical source fact with a facet. Not every canonical source
fact is a retrieval knowledge unit; several are **control facts** that exist so
correctness can be checked.

``IGNORED_BY_DECLARED_POLICY`` is now narrow. An entry may be ignored only with
(1) a statement of what the construct means, (2) an argument that it changes
none of the nine facets under the declared consumer semantics, and (3) that
argument recorded before the measurement it affects. "It is a presentation
attribute" is not an argument; it is a category name.

INC-V2-010 recorded that the previous policy failed all three tests for
``colspan``, ``rowspan``, ``role``, ``aria-*``, ``alt``, ``title``, ``lang``,
``dir``, ``scope``, ``rel``, ``media``, ``target``, ``content`` and
``http-equiv``. Those are reclassified here, forward only. P0d and Locality v2
keep their results under the grammar they declared.
"""

from __future__ import annotations

# --- facets ------------------------------------------------------------------

CONTENT_LEXICAL = "CONTENT_LEXICAL"
STRUCTURAL = "STRUCTURAL"
REFERENCE_LOCATOR = "REFERENCE_LOCATOR"
TEMPORAL = "TEMPORAL"
AUTHORITY_APPLICABILITY = "AUTHORITY_APPLICABILITY"
METADATA = "METADATA"
ACCESSIBILITY = "ACCESSIBILITY"
VISUAL = "VISUAL"
EXTERNAL_DEPENDENCY = "EXTERNAL_DEPENDENCY_EXECUTION"

FACETS = (
    CONTENT_LEXICAL,
    STRUCTURAL,
    REFERENCE_LOCATOR,
    TEMPORAL,
    AUTHORITY_APPLICABILITY,
    METADATA,
    ACCESSIBILITY,
    VISUAL,
    EXTERNAL_DEPENDENCY,
)

# --- states ------------------------------------------------------------------

MODELED = "MODELED"
IGNORED = "IGNORED_BY_DECLARED_POLICY"
UNRESOLVED = "UNRESOLVED_SOURCE_FACT"
UNMODELED = "UNMODELED_SOURCE_FACT"

#: The third state exists so nothing has to be forced into the first two. A
#: construct that may carry meaning but cannot be interpreted from the local
#: source alone is UNRESOLVED. It is **not** IGNORED and it never permits local
#: coverage completeness.
STATES = (MODELED, IGNORED, UNRESOLVED, UNMODELED)


def _fact(facet: str, why: str, *, control_only: bool = False) -> dict[str, object]:
    return {"state": MODELED, "facet": facet, "why": why, "control_fact": control_only}


def _ignore(what: str, why: str) -> dict[str, object]:
    return {"state": IGNORED, "facet": None, "means": what, "why": why}


def _unresolved(facet: str, why: str) -> dict[str, object]:
    return {"state": UNRESOLVED, "facet": facet, "why": why}


# --- attributes --------------------------------------------------------------

ATTRIBUTES: dict[str, dict[str, object]] = {
    # structure — a change here moves which cell belongs to which header
    "colspan": _fact(STRUCTURAL, "changes which columns a cell spans, so it changes cell-to-header association", control_only=True),
    "rowspan": _fact(STRUCTURAL, "changes which rows a cell spans", control_only=True),
    "headers": _fact(STRUCTURAL, "names the header cells a data cell belongs to, explicitly"),
    "scope": _fact(STRUCTURAL, "declares whether a header governs its row or its column"),
    "start": _fact(STRUCTURAL, "sets a list's first ordinal, changing every item's number"),
    "value": _fact(STRUCTURAL, "sets a list item's ordinal"),
    "reversed": _fact(STRUCTURAL, "reverses list numbering"),

    # reference and locator
    "href": _fact(REFERENCE_LOCATOR, "the destination of a link"),
    "src": _fact(REFERENCE_LOCATOR, "the source of an embedded resource"),
    "srcset": _fact(REFERENCE_LOCATOR, "candidate sources for an embedded resource"),
    "cite": _fact(REFERENCE_LOCATOR, "the source a quotation or edit is attributed to"),
    "rel": _fact(REFERENCE_LOCATOR, "the relationship a link asserts — canonical, nofollow and license all mean different things"),
    "id": _fact(REFERENCE_LOCATOR, "an anchor other constructs may address"),
    "name": _fact(REFERENCE_LOCATOR, "a legacy anchor or form field identifier"),
    "for": _fact(REFERENCE_LOCATOR, "binds a label to the control it names"),
    "usemap": _fact(REFERENCE_LOCATOR, "binds an image to a client-side map"),
    "target": _fact(REFERENCE_LOCATOR, "the browsing context a link opens in, which is behaviour and not decoration"),
    "data": _fact(REFERENCE_LOCATOR, "the resource an object element embeds"),
    "action": _fact(REFERENCE_LOCATOR, "where a form submits"),
    "formaction": _fact(REFERENCE_LOCATOR, "where a control submits, overriding the form"),
    "poster": _fact(REFERENCE_LOCATOR, "the still shown for a video"),
    "longdesc": _fact(REFERENCE_LOCATOR, "a long description's location"),

    # interpretation metadata
    "lang": _fact(METADATA, "declares the natural language, which changes tokenisation, collation and meaning"),
    "xml:lang": _fact(METADATA, "as lang, in the XML namespace"),
    "dir": _fact(METADATA, "declares base text direction, which changes reading order"),
    "charset": _fact(METADATA, "declares an encoding, which changes what characters the bytes are"),
    "encoding": _fact(METADATA, "declares an encoding"),
    "content": _fact(METADATA, "the value a meta element asserts — the whole payload of the element"),
    "http-equiv": _fact(METADATA, "declares a pragma directive, including refresh and content policy"),
    "property": _fact(METADATA, "the predicate in an RDFa assertion"),
    "typeof": _fact(METADATA, "the type in an RDFa assertion"),
    "itemprop": _fact(METADATA, "the predicate in a microdata assertion"),
    "itemtype": _fact(METADATA, "the type in a microdata assertion"),
    "media": _fact(METADATA, "the conditions under which a resource applies, which is applicability and not styling"),

    # temporal and authority
    "datetime": _fact(TEMPORAL, "the machine-readable time a time element denotes"),
    "contextref": _fact(TEMPORAL, "XBRL: binds a fact to its reporting period and entity — both temporal and authority"),
    "unitref": _fact(AUTHORITY_APPLICABILITY, "XBRL: the unit a numeric fact is denominated in"),
    "decimals": _fact(AUTHORITY_APPLICABILITY, "XBRL: the precision a reported figure claims"),
    "scale": _fact(AUTHORITY_APPLICABILITY, "XBRL: the power of ten a reported figure is scaled by"),
    "sign": _fact(AUTHORITY_APPLICABILITY, "XBRL: the sign of a reported figure"),
    "datatype": _fact(AUTHORITY_APPLICABILITY, "declares how a value is to be read"),

    # accessibility — accessible content is content
    "alt": _fact(ACCESSIBILITY, "the text alternative, which IS the content for a non-visual consumer"),
    "role": _fact(ACCESSIBILITY, "overrides an element's semantics for assistive technology"),
    "aria-label": _fact(ACCESSIBILITY, "supplies an accessible name"),
    "aria-labelledby": _fact(ACCESSIBILITY, "names the elements supplying an accessible name"),
    "aria-describedby": _fact(ACCESSIBILITY, "names the elements supplying a description"),
    "aria-hidden": _fact(ACCESSIBILITY, "removes an element from the accessibility tree entirely"),
    "title": _fact(ACCESSIBILITY, "advisory text exposed as a tooltip and as an accessible name of last resort"),
    "abbr": _fact(ACCESSIBILITY, "an abbreviated header label for a table cell"),
    "summary": _fact(ACCESSIBILITY, "a table's structural description"),

    # external dependency — visibility and ordering can be decided elsewhere
    "class": _unresolved(EXTERNAL_DEPENDENCY, "an external stylesheet or script may make this hide, reorder or transform the element. Not ignorable unless the absence of such a rule is proven"),
    "style": _unresolved(EXTERNAL_DEPENDENCY, "inline declarations can set display:none, order or content. Not ignorable unless proven inert"),
    "hidden": _fact(VISUAL, "removes the element from rendering, which changes what a reader sees"),
    "onclick": _unresolved(EXTERNAL_DEPENDENCY, "script may replace or insert content"),
    "onload": _unresolved(EXTERNAL_DEPENDENCY, "script may replace or insert content"),
    "srcdoc": _unresolved(EXTERNAL_DEPENDENCY, "an inline document whose coverage is not established here"),

    # genuinely ignorable — each states its meaning and why no facet moves
    "width": _ignore("a rendering hint for intrinsic size", "changes pixels only; no text, structure, reference, time, authority, metadata or accessible name depends on it under the declared consumer semantics"),
    "height": _ignore("a rendering hint for intrinsic size", "as width"),
    "cellpadding": _ignore("space inside table cells", "affects spacing only; cell-to-header association is carried by colspan, rowspan, scope and headers"),
    "cellspacing": _ignore("space between table cells", "as cellpadding"),
    "border": _ignore("a table border width hint", "affects rendering only"),
    "align": _ignore("horizontal alignment hint", "affects placement only; reading order is carried by document order and dir"),
    "valign": _ignore("vertical alignment hint", "affects placement only"),
    "bgcolor": _ignore("a background colour hint", "affects colour only; no declared consumer reads meaning from it"),
    "decoding": _ignore("a hint for how an image is decoded", "a performance hint with no effect on content or reference"),
    "loading": _ignore("a hint for when an image is fetched", "a performance hint; the reference itself is carried by src"),
    "data-file-width": _ignore("the intrinsic width of the referenced file", "a rendering hint duplicating information about the referenced resource"),
    "data-file-height": _ignore("the intrinsic height of the referenced file", "as data-file-width"),
}

#: Attribute prefixes resolved by rule rather than by name.
ATTRIBUTE_PREFIXES: tuple[tuple[str, dict[str, object]], ...] = (
    ("aria-", _fact(ACCESSIBILITY, "an ARIA property, which changes what an assistive consumer is told")),
    ("data-", _unresolved(EXTERNAL_DEPENDENCY, "a custom attribute whose consumer is script this source does not contain")),
    ("on", _unresolved(EXTERNAL_DEPENDENCY, "an inline event handler; script may alter content")),
    ("xmlns", _fact(METADATA, "declares the namespace a vocabulary is read in")),
)

# --- tags --------------------------------------------------------------------

TAGS: dict[str, dict[str, object]] = {
    "table": _fact(STRUCTURAL, "opens a tabular relation"),
    "thead": _fact(STRUCTURAL, "declares the header section of a table"),
    "tbody": _fact(STRUCTURAL, "declares the body section of a table"),
    "tfoot": _fact(STRUCTURAL, "declares the footer section of a table"),
    "tr": _fact(STRUCTURAL, "opens a row, which is a grouping of cells"),
    "td": _fact(STRUCTURAL, "a data cell whose position carries its association"),
    "th": _fact(STRUCTURAL, "a header cell that governs other cells"),
    "caption": _fact(STRUCTURAL, "names the table as a whole"),
    "ul": _fact(STRUCTURAL, "opens an unordered list"),
    "ol": _fact(STRUCTURAL, "opens an ordered list, where position is meaning"),
    "li": _fact(STRUCTURAL, "an item whose membership and order are structure"),
    "dl": _fact(STRUCTURAL, "opens a definition list"),
    "dt": _fact(STRUCTURAL, "a defined term"),
    "dd": _fact(STRUCTURAL, "a definition bound to the preceding term"),
    "h1": _fact(STRUCTURAL, "a heading, which opens a section and sets depth"),
    "h2": _fact(STRUCTURAL, "as h1"),
    "h3": _fact(STRUCTURAL, "as h1"),
    "h4": _fact(STRUCTURAL, "as h1"),
    "h5": _fact(STRUCTURAL, "as h1"),
    "h6": _fact(STRUCTURAL, "as h1"),
    "blockquote": _fact(STRUCTURAL, "marks quoted material, changing who is asserting it"),
    "q": _fact(STRUCTURAL, "marks an inline quotation"),
    "section": _fact(STRUCTURAL, "opens a section"),
    "article": _fact(STRUCTURAL, "opens a self-contained composition"),
    "aside": _fact(STRUCTURAL, "marks tangential content"),
    "nav": _fact(STRUCTURAL, "marks navigational content"),
    "p": _fact(STRUCTURAL, "opens a paragraph, a unit boundary"),
    "pre": _fact(STRUCTURAL, "preserves whitespace, so whitespace becomes content"),
    "code": _fact(STRUCTURAL, "marks material to be read literally"),
    "a": _fact(REFERENCE_LOCATOR, "an anchor, whose destination is a reference"),
    "link": _fact(REFERENCE_LOCATOR, "a document-level relationship"),
    "img": _fact(REFERENCE_LOCATOR, "an embedded resource with an accessible alternative"),
    "cite": _fact(REFERENCE_LOCATOR, "names the source of a work"),
    "time": _fact(TEMPORAL, "carries a machine-readable time"),
    "meta": _fact(METADATA, "asserts a document-level property"),
    "del": _fact(TEMPORAL, "marks removed content, which is a change assertion"),
    "ins": _fact(TEMPORAL, "marks inserted content"),
    "script": _unresolved(EXTERNAL_DEPENDENCY, "may insert, remove or rewrite content; its effect is not decidable from this source"),
    "style": _unresolved(EXTERNAL_DEPENDENCY, "may hide or reorder content"),
    "iframe": _unresolved(EXTERNAL_DEPENDENCY, "embeds a document not present here"),
    "object": _unresolved(EXTERNAL_DEPENDENCY, "embeds a resource not present here"),
    "embed": _unresolved(EXTERNAL_DEPENDENCY, "embeds a resource not present here"),
    "template": _unresolved(EXTERNAL_DEPENDENCY, "inert content instantiated by script"),
    "slot": _unresolved(EXTERNAL_DEPENDENCY, "a placeholder filled from elsewhere"),
    "b": _ignore("bold rendering with no defined semantics", "the HTML specification defines b as stylistically offset with no added importance; strong carries the meaning"),
    "i": _ignore("italic rendering with no defined semantics", "as b; em carries the meaning"),
    "span": _ignore("a generic inline container", "carries no meaning of its own — but its attributes are classified separately and class/style remain UNRESOLVED"),
    "div": _ignore("a generic block container", "as span"),
    "br": _ignore("a line break", "changes line layout; paragraph and list structure is carried by block elements"),
    "wbr": _ignore("a line break opportunity", "a hyphenation hint"),
}

#: Tag syntax that is genuinely residue rather than structure.
SYNTAX_RESIDUE = ("<", ">", "</", "/>")

# --- character data ----------------------------------------------------------

CHARACTER_REFERENCES = {
    "state": MODELED,
    "facet": CONTENT_LEXICAL,
    "why": (
        "a character or entity reference produces an actual character in the "
        "canonical text. &#160; is a non-breaking space and &amp; is an "
        "ampersand; both are content, and 15,415 of the first alone appear in "
        "the development corpus. Ignoring them would make the canonical text "
        "untraceable to its source at exactly the characters most likely to "
        "differ."
    ),
}

TEXT_DATA = {
    "state": MODELED,
    "facet": CONTENT_LEXICAL,
    "why": "character data is the text itself",
}

WHITESPACE_ONLY_DATA = _ignore(
    "inter-element whitespace outside a pre or a preserved context",
    "the canonicaliser normalises runs of whitespace between elements, so a "
    "change in indentation cannot reach any facet. Whitespace inside pre is "
    "content and is NOT covered by this entry.",
)

#: The declared consumer, against which every "changes no facet" argument above
#: is made. Naming it is what makes those arguments falsifiable.
CONSUMER_SEMANTICS = {
    "reader": "a text and structure consumer plus a non-visual assistive consumer",
    "reads": [
        "canonical text, including characters produced by references",
        "block and list and table structure, including cell association",
        "reference destinations and relationships",
        "declared language, direction and encoding",
        "accessible names, descriptions and hidden state",
        "machine-readable times and reporting contexts",
        "document-level assertions",
    ],
    "does_not_read": [
        "pixel geometry, colour, spacing and alignment",
        "fetch and decode performance hints",
    ],
    "cannot_decide_locally": [
        "what an external stylesheet or script does to a class, a style, a data "
        "attribute or an event handler",
    ],
}

POLICY_VERSION = 1
POLICY_ID = "MARKUP_SEMANTICS_V1"

#: Everything the digest is computed over. Code that reads this file is hashed
#: separately; a change to either must be visible on its own.
POLICY = {
    "policy_id": POLICY_ID,
    "version": POLICY_VERSION,
    "facets": list(FACETS),
    "states": list(STATES),
    "attributes": ATTRIBUTES,
    "attribute_prefixes": [list(item) for item in ATTRIBUTE_PREFIXES],
    "tags": TAGS,
    "syntax_residue": list(SYNTAX_RESIDUE),
    "character_references": CHARACTER_REFERENCES,
    "text_data": TEXT_DATA,
    "whitespace_only_data": WHITESPACE_ONLY_DATA,
    "consumer_semantics": CONSUMER_SEMANTICS,
}
