"""Native provenance: the span is right, or there is no span.

SFI1 did not fail because its search was too weak. It failed because a search
that succeeds on canonical text is answering a question about the raw bytes it
was never asked, and 1,284 units came back with a confident wrong answer. These
tests are therefore not about coverage percentages. They are about whether a
reported span, sliced out of the payload, actually contains what it claims — and
about whether the module can still be tempted to look for one.

The shape tests matter for the same reason. A canonicaliser that segments
differently is a different study; comparing its provenance to SFI1's would
compare two things that were never the same measurement. So every fixture's
units are checked against `canonical_document` character for character, and a
difference is only tolerated when it is named in `OBSERVABLE_DIVERGENCES`.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for _sub in ("source_fact_ir", "canonicalization"):
    sys.path.insert(0, str(NS / _sub))

import canonical_document as legacy  # noqa: E402
import provenance_document as native  # noqa: E402
import spanmap  # noqa: E402
from canonical_document import canonical_document  # noqa: E402
from provenance_document import provenance_document  # noqa: E402

PAD = (
    "This sentence exists only to push the block past the canonicaliser's one "
    "hundred and twenty character minimum so that it becomes a unit instead of "
    "being folded away before anything can be measured about it."
)


def build(payload: bytes, family: str = "wikipedia") -> dict[str, object]:
    return provenance_document(
        source_family=family,
        source_id="src",
        version_id="ver",
        payload=payload,
        source_digest="sha256:" + "0" * 64,
        known_at="2026-08-23T00:00:00Z",
        valid_from="2026-08-23T00:00:00Z",
        licence="CC-BY-SA-4.0",
    )


def build_legacy(payload: bytes, family: str = "wikipedia") -> dict[str, object]:
    return canonical_document(
        source_family=family,
        source_id="src",
        version_id="ver",
        payload=payload,
        source_digest="sha256:" + "0" * 64,
        known_at="2026-08-23T00:00:00Z",
        valid_from="2026-08-23T00:00:00Z",
        licence="CC-BY-SA-4.0",
    )


def rebuild(unit: dict[str, object]) -> spanmap.SpanMap:
    """Reconstruct a unit's SpanMap from the serialised form the document ships.

    Deliberately going through `as_list` rather than the in-memory object: what
    a consumer receives is the serialisation, so that is what has to verify.
    """
    segments = []
    for entry in unit["span_map"]:  # type: ignore[index]
        start = entry["source_start"]
        end = entry["source_end"]
        segments.append(
            spanmap.Segment(
                out_start=entry["out_start"],
                out_end=entry["out_end"],
                source_start=-1 if start is None else start,
                source_end=-1 if end is None else end,
                kind=entry["kind"],
            )
        )
    return spanmap.SpanMap(segments)


def source_of(unit: dict[str, object], out_start: int, out_end: int) -> tuple[int, int] | None:
    return rebuild(unit).to_source(out_start, out_end)


MARKDOWN = (
    "---\n"
    "title: front matter that must not become text\n"
    "---\n"
    "\n"
    "# Alpha\n"
    "\n"
    f"{PAD}\n"
    "\n"
    "## Beta\n"
    "\n"
    f"Some **bold** words and a [labelled link](https://example.invalid/x). {PAD}\n"
).encode()

ENTITIES = (
    "# Entities\n"
    "\n"
    f"A caf&eacute; sign, an &amp; ampersand and a &#38; numeric one. {PAD}\n"
).encode()

WRAPPED = ("# Wrapped\n\nfirst\nsecond " + PAD + "\n").encode("utf-8")

CJK = (
    "# 漢字の見出し\n\n" + "これは日本語の段落です。絵文字も入ります。\U0001f600 " * 6 + "\n"
).encode("utf-8")

SEC_HTML = (
    b"<html><head><title>ignored</title></head><body>\n"
    b"<p>Item 1. Business</p>\n"
    b"<p>" + PAD.encode("utf-8") + b"</p>\n"
    b"<p>A caf&eacute; and an &amp; sign. " + PAD.encode("utf-8") + b"</p>\n"
    b"</body></html>\n"
)

SEC_HTML_SINGLE = (
    b"<html><body><h1>Item 2. Risk Factors</h1>\n"
    b"<p>" + PAD.encode("utf-8") + b"</p></body></html>"
)

FIXTURES: dict[str, tuple[bytes, str]] = {
    "markdown": (MARKDOWN, "wikipedia"),
    "entities": (ENTITIES, "wikipedia"),
    "wrapped": (WRAPPED, "wikipedia"),
    "cjk": (CJK, "wikipedia"),
    "sec_html": (SEC_HTML, "sec_edgar"),
    "sec_html_single": (SEC_HTML_SINGLE, "sec_edgar"),
}


@pytest.fixture(params=sorted(FIXTURES))
def fixture_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


# --------------------------------------------------------------------------- #
# 1. A reported span, sliced out of the payload, contains the text it claims.
# --------------------------------------------------------------------------- #


def test_source_span_slices_back_to_the_unit_text(fixture_name: str) -> None:
    payload, family = FIXTURES[fixture_name]
    document = build(payload, family)
    assert document["units"], f"{fixture_name} produced no units"
    for unit in document["units"]:
        span = unit["source_span"]
        assert span is not None, f"{fixture_name} unit {unit['ordinal']} has no span"
        start, end = span
        window = payload[start:end].decode("utf-8", "replace")
        leading = unit["text"].split(" ")[0]
        assert leading in window
        #: the span must bracket the unit, not merely touch it
        trailing = unit["text"].split(" ")[-1]
        assert trailing in window


# --------------------------------------------------------------------------- #
# 2. Every COPY segment verifies against the payload.
# --------------------------------------------------------------------------- #


def test_every_unit_verifies(fixture_name: str) -> None:
    payload, family = FIXTURES[fixture_name]
    document = build(payload, family)
    for unit in document["units"]:
        report = spanmap.verify(rebuild(unit), payload, unit["text"])
        assert report["ok"], report["problems"]
    assert document["provenance"]["units_failed_verification"] == 0
    assert document["provenance"]["parser_position_anomalies"] == 0


def test_a_corrupted_span_is_caught_by_verify() -> None:
    """The checker must be able to refuse. A test suite that never sees it say
    no has not established that it would."""
    payload, family = FIXTURES["markdown"]
    unit = build(payload, family)["units"][0]
    segments = list(rebuild(unit).segments)
    first = segments[0]
    segments[0] = spanmap.Segment(
        out_start=first.out_start,
        out_end=first.out_end,
        source_start=first.source_start + 3,
        source_end=first.source_end + 3,
        kind=first.kind,
    )
    report = spanmap.verify(spanmap.SpanMap(segments), payload, unit["text"])
    assert not report["ok"]


# --------------------------------------------------------------------------- #
# 3. Entity decoding.
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("family", ["wikipedia", "sec_edgar"])
def test_entity_span_covers_the_entity(family: str) -> None:
    if family == "sec_edgar":
        payload = (
            b"<html><body><h1>Item 1. Business</h1><p>A caf&eacute; sign. "
            + PAD.encode("utf-8")
            + b"</p></body></html>"
        )
    else:
        payload = ENTITIES
    unit = build(payload, family)["units"][0]
    text = unit["text"]
    assert "café" in text
    at = text.index("café") + 3
    span = source_of(unit, at, at + 1)
    assert span is not None
    start, end = span
    assert payload[start:end] == b"&eacute;", payload[start:end]


def test_ampersand_entities_decode_to_their_own_bytes() -> None:
    unit = build(ENTITIES)["units"][0]
    text = unit["text"]
    named = text.index("& ampersand")
    numeric = text.index("& numeric")
    assert source_of(unit, named, named + 1) is not None
    assert unit["text"][named] == "&"
    start, end = source_of(unit, named, named + 1)
    assert ENTITIES[start:end] == b"&amp;"
    start, end = source_of(unit, numeric, numeric + 1)
    assert ENTITIES[start:end] == b"&#38;"


# --------------------------------------------------------------------------- #
# 4. Whitespace normalisation across a line break.
# --------------------------------------------------------------------------- #


def test_collapsed_newline_maps_back_to_the_original_run() -> None:
    unit = build(WRAPPED)["units"][0]
    text = unit["text"]
    assert text.startswith("first second")
    at = text.index("first") + len("first")
    assert text[at] == " "
    span = source_of(unit, at, at + 1)
    assert span is not None
    start, end = span
    #: the single canonical space is sourced to the whole run it replaced,
    #: which in the payload is a newline rather than a space
    assert WRAPPED[start:end] == b"\n"


# --------------------------------------------------------------------------- #
# 5. Markup stripping.
# --------------------------------------------------------------------------- #


def test_bold_span_covers_the_word_not_the_asterisks() -> None:
    unit = next(u for u in build(MARKDOWN)["units"] if "bold" in u["text"])
    at = unit["text"].index("bold")
    span = source_of(unit, at, at + 4)
    assert span is not None
    start, end = span
    assert MARKDOWN[start:end] == b"bold"


def test_link_label_span_covers_the_label_not_the_url() -> None:
    unit = next(u for u in build(MARKDOWN)["units"] if "labelled link" in u["text"])
    at = unit["text"].index("labelled link")
    span = source_of(unit, at, at + len("labelled link"))
    assert span is not None
    start, end = span
    assert MARKDOWN[start:end] == b"labelled link"
    assert b"example.invalid" not in MARKDOWN[start:end]


# --------------------------------------------------------------------------- #
# 6. Block composition — and the one place `insert` is allowed.
# --------------------------------------------------------------------------- #


def test_multi_block_unit_spans_both_blocks_and_says_it_is_not_fully_sourced() -> None:
    document = build(SEC_HTML, "sec_edgar")
    unit = document["units"][0]
    inserted = [s for s in unit["span_map"] if s["kind"] == "insert"]
    #: two <p> blocks fold under one heading, so exactly one separator is added
    assert len(inserted) == 1
    assert unit["fully_sourced"] is False
    start, end = unit["source_span"]
    window = SEC_HTML[start:end].decode("utf-8", "replace")
    assert window.startswith("This sentence")  # the first block
    assert "caf&eacute;" in window  # the second block, still undecoded on disk


def test_single_block_unit_is_fully_sourced_with_no_insert() -> None:
    document = build(SEC_HTML_SINGLE, "sec_edgar")
    unit = document["units"][0]
    assert [s for s in unit["span_map"] if s["kind"] == "insert"] == []
    assert unit["fully_sourced"] is True
    assert document["provenance"]["inserted_runs"] == 0


def test_insert_is_the_only_unsourced_kind_anywhere() -> None:
    for name, (payload, family) in FIXTURES.items():
        for unit in build(payload, family)["units"]:
            for segment in unit["span_map"]:
                if segment["kind"] == "insert":
                    assert segment["source_start"] is None, name
                else:
                    assert segment["source_start"] is not None, name


# --------------------------------------------------------------------------- #
# 7. Multi-byte characters — where a char/byte confusion shows.
# --------------------------------------------------------------------------- #


def test_multibyte_document_maps_to_byte_offsets_not_char_offsets() -> None:
    """Every COPY run's byte width must equal its text's UTF-8 width.

    `SpanMap.to_source` answers at segment granularity, so a per-character query
    inside one long COPY run returns that whole run — correctly, and uselessly
    for this question. The sharp check is arithmetic: if any offset were in
    character space, some run's byte width would be short by exactly the number
    of multi-byte characters in it.
    """
    document = build(CJK)
    unit = document["units"][0]
    assert spanmap.verify(rebuild(unit), CJK, unit["text"])["ok"]
    wide = 0
    for segment in unit["span_map"]:
        if segment["kind"] != "copy":
            continue
        chunk = unit["text"][segment["out_start"] : segment["out_end"]]
        width = segment["source_end"] - segment["source_start"]
        assert width == len(chunk.encode("utf-8"))
        assert CJK[segment["source_start"] : segment["source_end"]].decode("utf-8") == chunk
        if width > len(chunk):
            wide += 1
    assert wide, "the fixture was supposed to contain multi-byte characters"


def test_isolated_multibyte_character_gets_its_own_exact_span() -> None:
    """Markup stripping cuts the run, so the emoji becomes its own segment.

    This is the case where an off-by-one in coordinate space is not merely
    detectable but visible: four bytes, one character.
    """
    body = "これは **\U0001f600** と **日本語** です。"
    payload = ("# 見出し\n\n" + body + PAD + "\n").encode("utf-8")
    unit = build(payload)["units"][0]
    at = unit["text"].index("\U0001f600")
    start, end = source_of(unit, at, at + 1)
    assert payload[start:end] == "\U0001f600".encode()
    assert end - start == 4, "an emoji is four bytes; a char offset would say one"

    at = unit["text"].index("日本語")
    start, end = source_of(unit, at, at + 3)
    assert payload[start:end] == "日本語".encode()
    assert end - start == 9
    assert spanmap.verify(rebuild(unit), payload, unit["text"])["ok"]


def test_multibyte_heading_offsets_are_bytes() -> None:
    document = build(CJK)
    assert document["units"][0]["heading"] == "漢字の見出し"
    start, _ = document["units"][0]["source_span"]
    #: '# 漢字の見出し\n\n' is 2 + 18 + 2 = 22 bytes; a char-space answer would be 12
    assert start == 22


# --------------------------------------------------------------------------- #
# 8. No searching. Enforced over the module's own source.
# --------------------------------------------------------------------------- #

FORBIDDEN_METHODS = frozenset({"find", "rfind", "index", "rindex", "search"})
MODULE_SOURCE = Path(native.__file__).read_text(encoding="utf-8")


def test_module_never_searches_for_text() -> None:
    tree = ast.parse(MODULE_SOURCE)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in FORBIDDEN_METHODS:
            offenders.append(f"line {node.lineno}: .{func.attr}(")
        if isinstance(func, ast.Name) and func.id in FORBIDDEN_METHODS:
            offenders.append(f"line {node.lineno}: {func.id}(")
    assert offenders == [], (
        "provenance must be propagated, not recovered by search: " + "; ".join(offenders)
    )


def test_module_source_has_no_search_idioms_in_text_either() -> None:
    #: belt and braces: the AST check would miss a search hidden behind getattr
    #: or eval, and a plain scan would miss an aliased method. Both run.
    for idiom in (".find(", ".index(", ".rfind(", ".rindex(", "re.search", ".search("):
        assert idiom not in MODULE_SOURCE, idiom
    for idiom in ("getattr(", "eval(", "exec("):
        assert idiom not in MODULE_SOURCE, idiom


def test_the_search_check_would_actually_fail() -> None:
    """A guard nobody has watched fail is a guard nobody has tested."""
    tree = ast.parse("raw.find(text)")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in FORBIDDEN_METHODS
    ]
    assert calls


# --------------------------------------------------------------------------- #
# 9. Shape compatibility with the legacy canonicaliser.
# --------------------------------------------------------------------------- #


def test_shape_matches_canonical_document(fixture_name: str) -> None:
    payload, family = FIXTURES[fixture_name]
    mine = build(payload, family)
    theirs = build_legacy(payload, family)

    if fixture_name in native.OBSERVABLE_DIVERGENCES:
        pytest.skip(f"{fixture_name} is a declared observable divergence")

    assert mine["schema"] == theirs["schema"]
    assert mine["structure"] == theirs["structure"]
    assert len(mine["units"]) == len(theirs["units"])
    for ours, legacy_unit in zip(mine["units"], theirs["units"], strict=True):
        for key in ("explicit_path", "heading", "ordinal", "text", "text_sha256"):
            assert ours[key] == legacy_unit[key], (fixture_name, key)
    for key in ("source_family", "source_id", "version_id", "version_time",
                "source_digest", "license"):
        assert mine[key] == theirs[key]


def test_no_undeclared_divergence_is_tolerated() -> None:
    """The declared-divergence list is not decoration.

    If a fixture's canonical text ever stops matching the legacy module, the
    only acceptable outcome is that the fixture is named in
    OBSERVABLE_DIVERGENCES. Anything else is a silent change to what the study
    measures.
    """
    for name, (payload, family) in FIXTURES.items():
        mine = build(payload, family)
        theirs = build_legacy(payload, family)
        same = [u["text"] for u in mine["units"]] == [u["text"] for u in theirs["units"]]
        assert same or name in native.OBSERVABLE_DIVERGENCES, name
    assert frozenset() == native.OBSERVABLE_DIVERGENCES
    assert len(native.DIVERGENCES) == 3


def test_segmentation_constants_are_the_legacy_ones() -> None:
    assert native.MIN_TEXT_CHARS == legacy.MIN_TEXT_CHARS
    assert native.EXCLUDED_HEADINGS == legacy.EXCLUDED_HEADINGS
    for name in ("SPACE", "ATX", "FENCE", "FRONT_MATTER", "MD_LINK", "MD_EMPH",
                 "SHORTCODE", "HTML_TAG", "SEC_ITEM", "SEC_PART"):
        assert getattr(native, name).pattern == getattr(legacy, name).pattern, name
    assert set(legacy.SecHtmlReader.SKIP) == native.ProvenanceHtmlReader.SKIP
    assert set(legacy.SecHtmlReader.BLOCK) == native.ProvenanceHtmlReader.BLOCK


def test_excluded_headings_and_minimum_length_still_drop_units() -> None:
    payload = (
        "# References\n\n" + PAD + "\n\n# Kept\n\n" + PAD + "\n\n# Short\n\ntiny.\n"
    ).encode("utf-8")
    mine = build(payload)
    assert [u["heading"] for u in mine["units"]] == ["Kept"]
    assert mine["structure"] == build_legacy(payload)["structure"]


# --------------------------------------------------------------------------- #
# 10. Document-level provenance is reported, not flattered.
# --------------------------------------------------------------------------- #


def test_provenance_block_totals_are_consistent(fixture_name: str) -> None:
    payload, family = FIXTURES[fixture_name]
    document = build(payload, family)
    block = document["provenance"]
    units = document["units"]
    assert block["units"] == len(units)
    assert block["payload_bytes"] == len(payload)
    assert block["units_fully_sourced"] == sum(1 for u in units if u["fully_sourced"])
    assert block["units_with_source_span"] == sum(1 for u in units if u["source_span"])
    assert block["segments"] == sum(len(u["span_map"]) for u in units)
    assert block["inserted_runs"] == sum(
        1 for u in units for s in u["span_map"] if s["kind"] == "insert"
    )
    assert block["units_fully_sourced"] <= block["units_with_source_span"]
    assert block["divergences"] == list(native.DIVERGENCES)


def test_malformed_utf8_is_decoded_like_the_legacy_reader_and_counted() -> None:
    payload = ("# Broken\n\n" + PAD).encode("utf-8") + b"\xff\xfe " + PAD.encode("utf-8")
    mine = build(payload)
    theirs = build_legacy(payload)
    assert [u["text"] for u in mine["units"]] == [u["text"] for u in theirs["units"]]
    assert mine["provenance"]["decode_replacements"] >= 2
    for unit in mine["units"]:
        assert spanmap.verify(rebuild(unit), payload, unit["text"])["ok"]


def test_html_script_and_style_never_reach_the_canonical_text() -> None:
    payload = (
        b"<html><head><style>p{color:red}</style></head><body>"
        b"<script>var secret = 1;</script>"
        b"<h1>Item 3. Legal Proceedings</h1><p>" + PAD.encode("utf-8") + b"</p>"
        b"</body></html>"
    )
    mine = build(payload, "sec_edgar")
    assert mine["units"], "the filing produced no units"
    for unit in mine["units"]:
        assert "secret" not in unit["text"]
        assert "color:red" not in unit["text"]
        assert spanmap.verify(rebuild(unit), payload, unit["text"])["ok"]
    assert [u["text"] for u in mine["units"]] == [
        u["text"] for u in build_legacy(payload, "sec_edgar")["units"]
    ]
