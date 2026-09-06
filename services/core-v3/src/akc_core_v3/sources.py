"""Turn stored OCR into canonical units, with every source fact accounted for.

This is the half the revision service deliberately does not own. `service.py`
owns the wire; this owns the question "what did the source actually say, and what
did we do with each thing it said".

Three properties are worth stating before the code, because they are the reason
it is shaped this way rather than as a parser.

**Identity comes from structure, not from text and not from the OCR's own ids.**
A re-typeset changes region ids, page positions and pixel boxes, and an amendment
changes words. Neither may break the thread that says "clause 4.1 is still clause
4.1". So a unit's anchor is its clause number as printed, and its path is the
heading it sits under. Those survive both. `regionId` is recorded as provenance
and never used to decide identity -- an OCR run that renumbered its regions would
otherwise orphan every unit in the document.

**A document that cannot ground an answer is refused, not summarised.** OCR
without regions has no page or box, so a claim built from it could be cited but
not shown. That is `UNRESOLVED_SOURCE_FACT`, it is fail-closed, and it is the
whole reason the state machine exists: the alternative is a compile that looks
complete and answers with a citation nobody can open.

**A fact is only ignorable under a policy that existed first.** `IGNORE_POLICIES`
is a fixed registry. An `IGNORED_BY_PREDECLARED_POLICY` naming anything else is
refused, because a policy invented to excuse the fact in front of it is not a
predeclared policy -- it is a silent drop with paperwork.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol

from akc_cir.revision_compile import SourceFact, SourceFactState
from akc_cir.semantic_diff import DocumentShape, UnitSnapshot

from .wire import CompileRefused

__all__ = [
    "IGNORE_POLICIES",
    "CanonicalUnit",
    "ObjectStore",
    "ResolvedSource",
    "SourceDocument",
    "SourceRegion",
    "SourceResolutionRefused",
    "canonicalise_document",
    "document_shape",
    "load_document",
    "resolve_sources",
]


class SourceResolutionRefused(CompileRefused):
    """Resolution stopped, with a code the Product can act on.

    A subclass of `CompileRefused` rather than a sibling, because a service that
    caught one and not the other would turn a named refusal into a dropped
    connection -- which is exactly what it did until a test asked for a world the
    archive had never seen. The default status differs (422: the request was
    understood and the sources do not support it) and nothing else does.
    """

    def __init__(self, code: str, status: int = 422) -> None:
        super().__init__(code, status)


class ObjectStore(Protocol):
    """Read-only access to immutable storage.

    A protocol rather than a client because the Core must be drivable by a test
    that has no bucket, and because a compile service that reaches for network
    credentials of its own is a compile service that can exfiltrate a document.
    The caller supplies something that can read the keys it already authorised.
    """

    def get_json(self, key: str) -> Any: ...


#: Policies under which a source fact may be declined in advance. Fixed here, at
#: import, so that the set cannot grow to fit a document being compiled.
IGNORE_POLICIES: frozenset[str] = frozenset(
    {
        "policy.page-furniture.out-of-scope.v1",
        "policy.decorative-rule.out-of-scope.v1",
    }
)

#: A region whose confidence is below this is not represented as knowledge.
#:
#: This is a **declared refusal floor, not a calibrated threshold.** No corpus
#: has been run to choose it, and it must not be reported as a measured
#: operating point. Its only claim is directional: text the recogniser itself
#: does not stand behind should fail closed rather than become a claim, and a
#: floor of zero would mean no such case exists.
DECLARED_CONFIDENCE_FLOOR = 0.50

#: "4. Payment" -- a numbered heading. The trailing group forbids a full stop so
#: that a numbered *sentence* ("4.1 Payment is due within 30 days.") is not
#: mistaken for the section it belongs to.
_HEADING = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([^.]{1,60})$")

#: "4.1 Payment is due within 30 days of invoice." -- a numbered clause. At least
#: one dot in the number, so a heading can never match this pattern.
_CLAUSE = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(.+)$", re.DOTALL)

#: Running heads, folios and rules. Matched against the whole region text.
_FURNITURE = re.compile(
    r"^(?:page\s+\d+(?:\s*(?:of|/)\s*\d+)?|\d+\s*/\s*\d+|[-_\u2013\u2014\u2022\s]+)$",
    re.IGNORECASE,
)

_AUTHORITIES = frozenset({"unknown", "informal", "official", "contractual"})
_MAX_REGIONS = 50_000


@dataclass(frozen=True, slots=True)
class SourceRegion:
    region_id: str
    page_index0: int
    page_number1: int
    order: int
    block_type: str
    text: str
    bbox1000: tuple[int, int, int, int]
    confidence: float
    authority: str


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """One OCR record, validated and bound to the digest the request declared."""

    document_id: str
    title: str
    version_key: str
    source_immutable_key: str
    ocr_object_key: str
    page_count: int
    text: str
    input_sha256: str
    regions: tuple[SourceRegion, ...]


@dataclass(frozen=True, slots=True)
class CanonicalUnit:
    """A clause, with everything an answer must be able to show."""

    logical_id: str
    document_id: str
    document_title: str
    section: str
    explicit_identifier: str
    text: str
    page_number1: int
    bbox1000: tuple[int, int, int, int]
    evidence_id: str
    region_id: str
    authority: str

    @property
    def document_path(self) -> tuple[str, ...]:
        return (self.document_title, self.section)

    def snapshot(self) -> UnitSnapshot:
        return UnitSnapshot(
            logical_id=self.logical_id,
            text=self.text,
            document_path=self.document_path,
            anchor=self.explicit_identifier,
            explicit_identifier=self.explicit_identifier,
            evidence_id=self.evidence_id,
            page_number1=self.page_number1,
        )

    def provenance(self) -> dict[str, Any]:
        return {
            "evidenceId": self.evidence_id,
            "pageNumber1": self.page_number1,
            "bbox1000": list(self.bbox1000),
            "documentId": self.document_id,
            "regionId": self.region_id,
        }


@dataclass(frozen=True, slots=True)
class ResolvedSource:
    """Every document of a collection, canonicalised, with its fact ledger."""

    documents: tuple[SourceDocument, ...]
    units: tuple[CanonicalUnit, ...]
    facts: tuple[SourceFact, ...]
    source_sha256: str

    @property
    def snapshots(self) -> list[UnitSnapshot]:
        return [unit.snapshot() for unit in self.units]

    def witnesses(self) -> dict[str, dict[str, Any]]:
        """What each unit's answer must be able to point at."""
        return {unit.logical_id: unit.provenance() for unit in self.units}


def _refuse(condition: object, code: str, status: int = 422) -> None:
    if not condition:
        raise SourceResolutionRefused(code, status)


def _text(region: Mapping[str, Any], key: str, code: str) -> str:
    value = region.get(key)
    if not isinstance(value, str) or not value:
        raise SourceResolutionRefused(code)
    return value


def _whole(region: Mapping[str, Any], key: str, code: str) -> int:
    """An integer field, with `bool` excluded because `True == 1` in Python.

    These extractors exist so the checks and the narrowing are the same act. The
    earlier version validated with a helper that returned `None`, which left
    every field typed as `Any | None` afterwards -- so the type checker could not
    tell a validated page index from an unvalidated one, and neither could a
    reader.
    """
    value = region.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SourceResolutionRefused(code)
    return value


def _region(
    raw: Any, *, page_count: int, seen_ids: set[str], seen_orders: set[int]
) -> SourceRegion:
    if not isinstance(raw, dict):
        raise SourceResolutionRefused("CORE_V3_OCR_REGION_INVALID")
    region: Mapping[str, Any] = raw

    region_id = _text(region, "regionId", "CORE_V3_OCR_REGION_INVALID")
    _refuse(region_id not in seen_ids, "CORE_V3_OCR_REGION_DUPLICATE")

    page_index0 = _whole(region, "pageIndex0", "CORE_V3_OCR_REGION_PAGE_INVALID")
    _refuse(0 <= page_index0 < page_count, "CORE_V3_OCR_REGION_PAGE_INVALID")
    _refuse(region.get("pageNumber1") == page_index0 + 1, "CORE_V3_OCR_REGION_PAGE_INVALID")

    order = _whole(region, "order", "CORE_V3_OCR_REGION_ORDER_INVALID")
    _refuse(order >= 0, "CORE_V3_OCR_REGION_ORDER_INVALID")
    _refuse(order not in seen_orders, "CORE_V3_OCR_REGION_ORDER_DUPLICATE")

    text = _text(region, "text", "CORE_V3_OCR_REGION_TEXT_EMPTY")
    _refuse(text.strip(), "CORE_V3_OCR_REGION_TEXT_EMPTY")

    box = region.get("bbox1000")
    _refuse(
        isinstance(box, (list, tuple))
        and len(box) == 4
        and all(isinstance(v, int) and not isinstance(v, bool) for v in box),
        "CORE_V3_OCR_REGION_BBOX_INVALID",
    )
    corners = tuple(int(value) for value in box)  # type: ignore[union-attr]
    _refuse(
        all(0 <= value <= 1000 for value in corners)
        and corners[0] < corners[2]
        and corners[1] < corners[3],
        "CORE_V3_OCR_REGION_BBOX_INVALID",
    )

    raw_confidence = region.get("confidence")
    _refuse(
        isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool),
        "CORE_V3_OCR_REGION_CONFIDENCE_INVALID",
    )
    confidence = float(raw_confidence)  # type: ignore[arg-type]
    _refuse(0.0 <= confidence <= 1.0, "CORE_V3_OCR_REGION_CONFIDENCE_INVALID")

    authority = region.get("authority")
    _refuse(authority in _AUTHORITIES, "CORE_V3_OCR_REGION_AUTHORITY_INVALID")

    seen_ids.add(region_id)
    seen_orders.add(order)
    return SourceRegion(
        region_id=region_id,
        page_index0=page_index0,
        page_number1=page_index0 + 1,
        order=order,
        block_type=str(region.get("blockType", "paragraph")),
        text=text,
        bbox1000=(corners[0], corners[1], corners[2], corners[3]),
        confidence=confidence,
        authority=str(authority),
    )


def load_document(
    store: ObjectStore,
    *,
    document_id: str,
    title: str,
    ocr_object_key: str,
    immutable_object_key: str,
    content_sha256: str,
    page_count: int,
) -> SourceDocument:
    """Read one OCR record and bind it to what the request said it was.

    The digest check is the point. A request names a document version by
    `contentSha256`; if the object behind the key hashes to something else, the
    compile would be of a different document than the one whose lineage the
    receipt claims. That is refused here rather than discovered later by whoever
    tries to reconcile a world against its sources.
    """
    try:
        record = store.get_json(ocr_object_key)
    except SourceResolutionRefused:
        raise
    except Exception as error:  # any store failure is one outcome to the caller
        raise SourceResolutionRefused("CORE_V3_SOURCE_UNREADABLE", 503) from error
    _refuse(isinstance(record, dict), "CORE_V3_OCR_RECORD_INVALID")
    _refuse(
        record.get("inputSha256") == content_sha256,
        "CORE_V3_SOURCE_DIGEST_MISMATCH",
    )
    _refuse(
        record.get("sourceImmutableKey") == immutable_object_key,
        "CORE_V3_SOURCE_KEY_MISMATCH",
    )
    stored_pages = record.get("pageCount")
    _refuse(stored_pages == page_count, "CORE_V3_SOURCE_PAGE_COUNT_MISMATCH")
    _refuse(
        isinstance(page_count, int) and not isinstance(page_count, bool) and page_count > 0,
        "CORE_V3_SOURCE_PAGE_COUNT_MISMATCH",
    )
    text = record.get("text")
    _refuse(isinstance(text, str), "CORE_V3_OCR_RECORD_INVALID")
    raw_regions = record.get("regions")
    if raw_regions is None:
        # No regions means no page and no box. A claim built from this could be
        # cited and not shown, so the document resolves to nothing and its
        # unrepresented content is recorded as a fail-closed fact by the caller.
        regions: tuple[SourceRegion, ...] = ()
    else:
        _refuse(
            isinstance(raw_regions, list) and 1 <= len(raw_regions) <= _MAX_REGIONS,
            "CORE_V3_OCR_REGIONS_INVALID",
        )
        seen_ids: set[str] = set()
        seen_orders: set[int] = set()
        regions = tuple(
            sorted(
                (
                    _region(raw, page_count=page_count, seen_ids=seen_ids, seen_orders=seen_orders)
                    for raw in raw_regions
                ),
                key=lambda item: item.order,
            )
        )
        _refuse(
            text.strip() == "\n".join(item.text for item in regions).strip(),
            "CORE_V3_OCR_TEXT_REGION_DISAGREEMENT",
        )
    return SourceDocument(
        document_id=document_id,
        title=title,
        version_key=str(record.get("versionKey", "")),
        source_immutable_key=immutable_object_key,
        ocr_object_key=ocr_object_key,
        page_count=page_count,
        text=text,
        input_sha256=content_sha256,
        regions=regions,
    )


def canonicalise_document(
    document: SourceDocument,
) -> tuple[tuple[CanonicalUnit, ...], tuple[SourceFact, ...]]:
    """Walk the regions in reading order and account for every one of them.

    Every region leaves this function in exactly one of the four states. That
    total is what makes coverage meaningful: a region that simply fell out of a
    loop would lower nothing and be visible nowhere.
    """
    units: list[CanonicalUnit] = []
    facts: list[SourceFact] = []
    section = ""

    if not document.regions:
        facts.append(
            SourceFact(
                fact_id=f"sf-doc-{document.document_id}",
                kind="DOCUMENT_TEXT",
                state=SourceFactState.UNRESOLVED,
                reason=(
                    "OCR carries no regions, so no page or box exists for any claim this "
                    "document would support; a citation could be printed but not opened"
                ),
            )
        )
        return (), tuple(facts)

    for region in document.regions:
        base = f"sf-{document.document_id}-{region.region_id}"
        stripped = region.text.strip()

        # The order of these branches is the classification, and it is fixed so
        # that no region can match two of them. A block we cannot shape comes
        # first, then text we do not trust, then text we trust and decline, then
        # the two things that become knowledge. `_CLAUSE` is tried before
        # `_HEADING` because a numbered heading has no dot in its number and a
        # clause always does -- checking the other way round would classify a
        # short clause with no full stop ("4.1 Payment is due") as the section it
        # belongs to.
        if region.block_type != "paragraph":
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind=f"BLOCK_{region.block_type.upper()}",
                    state=SourceFactState.UNREPRESENTED,
                    reason=(
                        f"no canonical unit shape for block type {region.block_type!r}; "
                        "representing it as a paragraph would assert a structure the "
                        "source does not have"
                    ),
                )
            )
            continue

        if region.confidence < DECLARED_CONFIDENCE_FLOOR:
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="LOW_CONFIDENCE_TEXT",
                    state=SourceFactState.UNRESOLVED,
                    reason=(
                        f"recogniser confidence {region.confidence:.2f} is below the declared "
                        f"floor {DECLARED_CONFIDENCE_FLOOR:.2f}; the text is not trusted enough "
                        "to become a claim and is not discarded silently"
                    ),
                )
            )
            continue

        if _FURNITURE.match(stripped):
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="PAGE_FURNITURE",
                    state=SourceFactState.IGNORED,
                    policy_id="policy.page-furniture.out-of-scope.v1",
                )
            )
            continue

        clause = _CLAUSE.match(stripped)
        if not clause:
            if _HEADING.match(stripped):
                section = stripped
                facts.append(
                    SourceFact(
                        fact_id=base,
                        kind="SECTION_HEADING",
                        state=SourceFactState.REPRESENTED,
                    )
                )
                continue
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="UNNUMBERED_PARAGRAPH",
                    state=SourceFactState.UNRESOLVED,
                    reason=(
                        "paragraph carries no clause number, so it has no anchor that would "
                        "survive a re-typeset; giving it a positional identity would break "
                        "the moment the document is reflowed"
                    ),
                )
            )
            continue

        if not section:
            facts.append(
                SourceFact(
                    fact_id=base,
                    kind="ORPHAN_CLAUSE",
                    state=SourceFactState.UNRESOLVED,
                    reason=(
                        "clause appears before any section heading, so its document path "
                        "cannot be established"
                    ),
                )
            )
            continue

        identifier, body = clause.group(1), clause.group(2).strip()
        logical_id = f"ku_{document.document_id}_{identifier.replace('.', '_')}"
        unit = CanonicalUnit(
            logical_id=logical_id,
            document_id=document.document_id,
            document_title=document.title,
            section=section,
            explicit_identifier=identifier,
            text=body,
            page_number1=region.page_number1,
            bbox1000=region.bbox1000,
            evidence_id=f"ev_{document.document_id}_{region.region_id}",
            region_id=region.region_id,
            authority=region.authority,
        )
        units.append(unit)
        facts.append(
            SourceFact(
                fact_id=f"{base}-content",
                kind="CONTENT_TEXT",
                state=SourceFactState.REPRESENTED,
                logical_id=logical_id,
            )
        )
        facts.append(
            SourceFact(
                fact_id=f"{base}-span",
                kind="PROVENANCE_SPAN",
                state=SourceFactState.REPRESENTED,
                logical_id=logical_id,
            )
        )

    return tuple(units), tuple(facts)


def document_shape(units: Sequence[CanonicalUnit]) -> DocumentShape:
    return DocumentShape(
        heading_path_set=frozenset(unit.document_path for unit in units),
        block_count=len(units),
        unit_order=tuple(unit.logical_id for unit in units),
    )


def resolve_sources(
    store: ObjectStore,
    documents: Sequence[Mapping[str, Any]],
) -> ResolvedSource:
    """Resolve every document a request names, in a stable order.

    Sorted by document id rather than by request order: the units, the shape and
    the collection digest all depend on this sequence, and two requests naming
    the same documents in different orders must compile to the same world.
    """
    ordered = sorted(documents, key=lambda item: str(item.get("nativeId", "")))
    loaded: list[SourceDocument] = []
    units: list[CanonicalUnit] = []
    facts: list[SourceFact] = []
    for entry in ordered:
        native_id = _text(entry, "nativeId", "CORE_V3_DOCUMENT_ID_INVALID")
        document = load_document(
            store,
            document_id=native_id,
            title=str(entry.get("title") or native_id),
            ocr_object_key=str(entry.get("ocrObjectKey", "")),
            immutable_object_key=str(entry.get("immutableObjectKey", "")),
            content_sha256=str(entry.get("contentSha256", "")),
            page_count=_whole(entry, "pageCount", "CORE_V3_SOURCE_PAGE_COUNT_MISMATCH"),
        )
        loaded.append(document)
        document_units, document_facts = canonicalise_document(document)
        units.extend(document_units)
        facts.extend(document_facts)

    for fact in facts:
        if fact.state is SourceFactState.IGNORED and fact.policy_id not in IGNORE_POLICIES:
            # A policy named after the fact is not a predeclared policy.
            raise SourceResolutionRefused("CORE_V3_IGNORE_POLICY_UNDECLARED", 500)

    _refuse(units, "CORE_V3_NO_RESOLVABLE_UNIT")
    joined = "\n".join(f"{d.document_id}:{d.input_sha256}" for d in loaded)
    return ResolvedSource(
        documents=tuple(loaded),
        units=tuple(units),
        facts=tuple(facts),
        source_sha256="sha256:" + sha256(joined.encode("utf-8")).hexdigest(),
    )
