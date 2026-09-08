"""Apple SEC filings -> validated regions -> canonical units, nothing invented.

This is a **research adapter**. It sits outside Protected Core and imports it;
nothing here modifies ``akc_cir`` or ``akc_core_v3``.

It exists because the Core's stock canonicaliser
(``akc_core_v3.sources.canonicalise_document``) recognises exactly one unit
shape -- a numbered contract clause, ``4.1 Payment is due`` -- and an SEC filing
has none. Running the five Apple filings through the stock path is still done,
and its result is reported rather than hidden: it is the honest answer to "what
does the Python Core do with a 10-K today".

Three rules this module keeps.

**Page and box come from the parser or the region is refused.** Every evidence
locator below is a ``bbox1000`` that ``akc_native_parsers.pdf_parser`` computed
from the PDF's own text-object matrices. A block whose box is degenerate is
recorded as a fail-closed source fact, never squared off to satisfy a schema.

**Confidence is declared, not measured.** The OCR record shape the Core reads
requires a per-region ``confidence``. Nothing recognised anything here: the
bytes are the PDF's own text layer. ``NATIVE_TEXT_LAYER_CONFIDENCE`` is a
declared constant meaning "no recogniser was involved", it is recorded in the
manifest as such, and it is not a model score.

**Every region leaves this module in exactly one state.** Region counts,
represented counts and unresolved counts add up, which is the only thing that
makes the coverage number mean anything.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from akc_cir.identity import document_version_id, evidence_id, logical_id_seed, source_id
from akc_cir.models import CanonicalDocument
from akc_cir.revision_compile import SourceFact, SourceFactState
from akc_core_v3.sources import (  # type: ignore[import-untyped]
    CanonicalUnit,
    ResolvedSource,
    SourceDocument,
    load_document,
)
from akc_native_parsers.models import ParseContext
from akc_native_parsers.pdf_parser import parse_pdf_to_cir

__all__ = [
    "ANCHOR_MAX_CHARS",
    "DECORATIVE_GRAPHIC_POLICY",
    "NATIVE_TEXT_LAYER_CONFIDENCE",
    "Filing",
    "ParsedFiling",
    "ocr_record",
    "parse_filing",
    "resolve_filing",
    "sec_canonicalise",
]

#: The value written into every region's ``confidence`` field.
#:
#: **Declared, not measured.** A native PDF text layer is the bytes the filer
#: wrote; no recogniser produced a score, so there is no score to report. 1.0
#: records "no recognition step stood between the source and this text". It is
#: not a model confidence and must never be read as one. The consequence is that
#: ``DECLARED_CONFIDENCE_FLOOR`` in the Core never fires on this corpus, which is
#: correct: the floor exists to refuse text a recogniser did not stand behind.
NATIVE_TEXT_LAYER_CONFIDENCE = 1.0

#: Predeclared, and declared here before any filing was looked at. Vector paths
#: with no text and no image asset are the rules, boxes and underlines a
#: HTML-to-PDF render draws. The Core's own registry already names this policy.
DECORATIVE_GRAPHIC_POLICY = "policy.decorative-rule.out-of-scope.v1"

#: An anchor is a heading, so it is short. Longer text that merely begins with
#: "Note 10," is a cross-reference inside a paragraph, and reading it as a
#: section start would move a whole section's evidence to the wrong page.
ANCHOR_MAX_CHARS = 140
_PART_MAX_CHARS = 80

#: The three dash characters SEC filings actually print between a note number
#: and its title: hyphen-minus, U+2013 and U+2014. The two wide ones are what
#: the filings use; a pattern with only the ASCII hyphen matches no note at all.
_DASH = r"[-–—]"  # noqa: RUF001 - the wide dashes are the source's own bytes
_PART = re.compile(rf"^PART\s+([IVXLC]+)(?:\s*{_DASH}\s*(.+))?$", re.IGNORECASE)
_ITEM = re.compile(r"^Item\s+(\d{1,2}[A-Z]?)\.\s+(\S.*)$", re.IGNORECASE)
_NOTE = re.compile(rf"^Note\s+(\d{{1,2}})\s*{_DASH}\s*(.*)$", re.IGNORECASE)
_PROPOSAL = re.compile(
    rf"^Proposal\s+No\.?\s*(\d{{1,2}})\s*{_DASH}?\s*(.*)$", re.IGNORECASE
)


@dataclass(frozen=True, slots=True)
class Filing:
    """One SEC filing, exactly as the committed public manifest declares it."""

    filing_id: str
    form: str
    filing_date: str
    report_date: str
    accession: str
    cik: str
    authority: str
    pdf_filename: str
    pdf_sha256: str
    representation_kind: str
    original_sha256: str | None
    render_profile: str | None
    source_url: str
    title: str
    #: Set only where the committed PDF carries an empty-user-password
    #: encryption dictionary. See ``parse_filing``.
    empty_user_password: bool = False


@dataclass(frozen=True, slots=True)
class ParsedFiling:
    """A filing after the native path, before any canonicalisation."""

    filing: Filing
    document: CanonicalDocument
    source: str
    document_version: str
    page_count: int
    record: Mapping[str, Any]
    parse_facts: tuple[SourceFact, ...]


class _MemoryStore:
    """The read-only object store the Core's loader expects."""

    def __init__(self, objects: Mapping[str, Any]) -> None:
        self._objects = dict(objects)

    def get_json(self, key: str) -> Any:
        return self._objects[key]


def _text_of(block: Any) -> str:
    return (block.normalized_text or block.raw_text or "").strip()


def parse_filing(
    filing: Filing, data: bytes, *, tenant_id: str, created_at: datetime
) -> ParsedFiling:
    """Native PDF -> CIR -> a validated OCR-v2 record, with a fact per region.

    ``empty_user_password`` is not a workaround. ``parse_pdf_to_cir`` refuses an
    encrypted PDF outright unless the caller supplies a password, and Apple's
    own 2025 Form 10-K PDF carries an encryption dictionary with an empty user
    password. A caller with no password fails closed on the anchor document of
    this corpus; that refusal is recorded in the run manifest rather than being
    made invisible by always passing ``b""``.
    """
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    if digest != f"sha256:{filing.pdf_sha256}":
        raise ValueError(
            f"{filing.filing_id}: committed bytes hash to {digest}, "
            f"the manifest declares sha256:{filing.pdf_sha256}"
        )
    source = source_id(
        tenant_id=tenant_id, connector_type="sec-edgar", native_id=filing.accession
    )
    version = document_version_id(source=source, content_sha256=digest)
    document = parse_pdf_to_cir(
        filename=filing.pdf_filename,
        declared_mime="application/pdf",
        data=data,
        context=ParseContext(
            tenant_id=tenant_id,
            document_id=filing.filing_id,
            document_version_id=version,
            created_at=created_at,
            source_url=filing.source_url,
        ),
        password=b"" if filing.empty_user_password else None,
    )
    record, facts, pages = ocr_record(document, filing=filing, digest=digest)
    return ParsedFiling(
        filing=filing,
        document=document,
        source=source,
        document_version=version,
        page_count=pages,
        record=record,
        parse_facts=facts,
    )


def ocr_record(
    document: CanonicalDocument, *, filing: Filing, digest: str
) -> tuple[dict[str, Any], tuple[SourceFact, ...], int]:
    """Every CIR block becomes a region or a source fact. Never neither."""
    regions: list[dict[str, Any]] = []
    facts: list[SourceFact] = []
    pages = max(
        (ref.page_number1 for block in document.blocks for ref in block.source_refs),
        default=0,
    )
    for block in document.blocks:
        base = f"sf-{filing.filing_id}-{block.id}"
        ref = block.source_refs[0]
        text = _text_of(block)
        box = ref.bbox1000
        if not text:
            decorative = block.table is None and ref.image_asset_id is None
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind=f"BLOCK_{block.type.value.upper()}_NO_TEXT",
                    state=(
                        SourceFactState.IGNORED
                        if decorative
                        else SourceFactState.UNREPRESENTED
                    ),
                    policy_id=DECORATIVE_GRAPHIC_POLICY if decorative else "",
                    reason=(
                        ""
                        if decorative
                        else "the block carries an asset this adapter does not represent"
                    ),
                )
            )
            continue
        if box is None:
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="TEXT_WITHOUT_GEOMETRY",
                    state=SourceFactState.UNRESOLVED,
                    reason=(
                        "the parser produced no bbox for this text, so a claim built "
                        "from it could be cited and not shown"
                    ),
                )
            )
            continue
        x0, y0, x1, y1 = box.as_tuple()
        if not (x0 < x1 and y0 < y1):
            # `BBox1000` already refuses a zero-area box, so reaching this means
            # the contract changed. Recorded rather than assumed impossible.
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="DEGENERATE_GEOMETRY",
                    state=SourceFactState.UNRESOLVED,
                    reason=(
                        f"bbox1000 {(x0, y0, x1, y1)} has no area; squaring it off "
                        "would invent a region the source does not have"
                    ),
                )
            )
            continue
        regions.append(
            {
                "regionId": block.id,
                "pageIndex0": ref.page_index0,
                "pageNumber1": ref.page_number1,
                "order": len(regions),
                "blockType": block.type.value,
                "text": text,
                "bbox1000": [x0, y0, x1, y1],
                "confidence": NATIVE_TEXT_LAYER_CONFIDENCE,
                "authority": filing.authority,
            }
        )
    record = {
        "schemaVersion": "tavonel.ocr.v2",
        "inputSha256": digest,
        "sourceImmutableKey": f"sec/{filing.accession}/{filing.pdf_filename}",
        "versionKey": filing.accession,
        "pageCount": pages,
        "text": "\n".join(region["text"] for region in regions),
        "regions": regions,
    }
    return record, tuple(facts), pages


def load(parsed: ParsedFiling, *, document_id: str | None = None) -> SourceDocument:
    """Run the record through the Core's own loader, not a private copy."""
    key = f"ocr/{parsed.filing.filing_id}.json"
    return load_document(
        _MemoryStore({key: dict(parsed.record)}),
        document_id=document_id or parsed.filing.filing_id,
        title=parsed.filing.title,
        ocr_object_key=key,
        immutable_object_key=str(parsed.record["sourceImmutableKey"]),
        content_sha256=str(parsed.record["inputSha256"]),
        page_count=parsed.page_count,
    )


@dataclass(frozen=True, slots=True)
class _Anchor:
    identifier: str
    heading: str
    region_index: int


def _anchor_of(text: str) -> _Anchor | None:
    if len(text) > ANCHOR_MAX_CHARS:
        return None
    item = _ITEM.match(text)
    if item:
        return _Anchor(f"Item {item.group(1)}", item.group(2).strip(), -1)
    note = _NOTE.match(text)
    if note:
        return _Anchor(f"Note {note.group(1)}", note.group(2).strip(), -1)
    proposal = _PROPOSAL.match(text)
    if proposal:
        return _Anchor(
            f"Proposal No. {proposal.group(1)}", proposal.group(2).strip(), -1
        )
    return None


def sec_canonicalise(
    parsed: ParsedFiling,
    document: SourceDocument,
    *,
    lineage_source: str,
    lineage_title: str,
    lineage_document_id: str,
) -> tuple[tuple[CanonicalUnit, ...], tuple[SourceFact, ...]]:
    """An SEC disclosure section is the unit; its printed number is the anchor.

    ``Item 1A``, ``Note 3``, ``Proposal No. 5``. The identifier is what the
    filing prints, so it survives a re-typeset and a re-render -- which is the
    whole reason identity is not derived from text or from position.

    ``lineage_*`` decide what the unit belongs to. Passing the filing's own id
    makes each filing an independent source; passing a form-family id makes the
    quarterly filings versions of one disclosure lineage. The caller declares
    which it means; this function never guesses.

    ponytail: the duplicate rule is a heuristic with a stated ceiling. A filing
    prints its section number in the table of contents, in a summary table and
    as a running header on every page of the section, so an identifier occurs
    many times. Consecutive occurrences merge (a running header does not start a
    new section) and, among what is left, the occurrence with the most body text
    wins. Every rejected occurrence is recorded as a fail-closed fact, not
    dropped. Upgrade path if this proves too blunt: use the render's outline /
    the filing's own XBRL section tags instead of text matching.
    """
    regions = document.regions
    part = ""
    spans: list[tuple[_Anchor, str, list[int]]] = []
    preamble: list[int] = []
    facts: list[SourceFact] = []

    for index, region in enumerate(regions):
        text = region.text.strip()
        part_match = _PART.match(text) if len(text) <= _PART_MAX_CHARS else None
        if part_match:
            part = f"PART {part_match.group(1).upper()}"
            # Represented as the section path of every unit below it, exactly as
            # the Core's own canonicaliser represents a section heading: seen,
            # used, and not itself a unit.
            facts.append(
                SourceFact(
                    fact_id=f"sf-{document.document_id}-{region.region_id}",
                    kind="PART_HEADING",
                    state=SourceFactState.REPRESENTED,
                )
            )
            continue
        anchor = _anchor_of(text)
        if anchor is not None:
            anchor = _Anchor(anchor.identifier, anchor.heading, index)
            if spans and spans[-1][0].identifier == anchor.identifier:
                # A running header repeating the section it sits inside.
                continue
            spans.append((anchor, part, []))
            continue
        if spans:
            spans[-1][2].append(index)
        else:
            preamble.append(index)

    for index in preamble:
        facts.append(
            SourceFact(
                fact_id=f"sf-{document.document_id}-{regions[index].region_id}",
                kind="OUTSIDE_ANCHORED_SECTION",
                state=SourceFactState.UNRESOLVED,
                reason=(
                    "the region sits before the first numbered disclosure section, so "
                    "it has no anchor that would survive a re-typeset"
                ),
            )
        )

    best: dict[str, int] = {}
    for position, (anchor, _part, body) in enumerate(spans):
        size = sum(len(regions[i].text) for i in body)
        current = best.get(anchor.identifier)
        if current is None or size > sum(
            len(regions[i].text) for i in spans[current][2]
        ):
            best[anchor.identifier] = position

    units: list[CanonicalUnit] = []
    for position, (anchor, span_part, body) in enumerate(spans):
        chosen = best.get(anchor.identifier) == position
        member_regions = [regions[anchor.region_index], *(regions[i] for i in body)]
        if not chosen or not body:
            for region in member_regions:
                facts.append(
                    SourceFact(
                        fact_id=f"sf-{document.document_id}-{region.region_id}",
                        kind=(
                            "ANCHOR_WITHOUT_BODY"
                            if not body
                            else "DUPLICATE_ANCHOR_OCCURRENCE"
                        ),
                        state=SourceFactState.UNRESOLVED,
                        reason=(
                            f"{anchor.identifier} occurs here with "
                            f"{sum(len(regions[i].text) for i in body)} body characters; "
                            "a longer occurrence of the same identifier was taken as the "
                            "section and this one is neither represented nor discarded"
                        ),
                    )
                )
            continue
        section = span_part or parsed.filing.form
        head = regions[anchor.region_index]
        logical = logical_id_seed(
            source=lineage_source,
            document_path=(lineage_title, section),
            anchor=anchor.identifier,
        )
        unit = CanonicalUnit(
            logical_id=logical,
            document_id=lineage_document_id,
            document_title=lineage_title,
            section=section,
            explicit_identifier=anchor.identifier,
            text="\n".join(regions[i].text for i in body),
            page_number1=head.page_number1,
            bbox1000=head.bbox1000,
            evidence_id=evidence_id(
                document_version=parsed.document_version,
                page_number1=head.page_number1,
                bbox1000=head.bbox1000,
                span_text=head.text,
            ),
            region_id=head.region_id,
            authority=head.authority,
        )
        units.append(unit)
        facts.append(
            SourceFact(
                fact_id=f"sf-{document.document_id}-{head.region_id}-anchor",
                kind="SECTION_ANCHOR",
                state=SourceFactState.REPRESENTED,
                logical_id=logical,
            )
        )
        for region in member_regions[1:]:
            facts.append(
                SourceFact(
                    fact_id=f"sf-{document.document_id}-{region.region_id}",
                    kind="SECTION_BODY_TEXT",
                    state=SourceFactState.REPRESENTED,
                    logical_id=logical,
                )
            )
    return tuple(units), tuple(facts)


def resolve_filing(
    parsed: Sequence[ParsedFiling],
    documents: Sequence[SourceDocument],
    units: Sequence[CanonicalUnit],
    facts: Sequence[SourceFact],
) -> ResolvedSource:
    """Assemble the Core's own ``ResolvedSource`` from adapter output."""
    joined = "\n".join(f"{d.document_id}:{d.input_sha256}" for d in documents)
    _ = parsed
    return ResolvedSource(
        documents=tuple(documents),
        units=tuple(units),
        facts=tuple(facts),
        source_sha256="sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest(),
    )
