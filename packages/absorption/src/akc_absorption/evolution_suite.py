"""The Knowledge Evolution Suite — blueprint §9.7, masterplan §8.7.

Eleven controlled mutation classes over a seeded document family, each carrying
the gold labels the metrics need. Contract A calls the 5,132-document corpus
single-version and therefore insufficient for this question, which is the whole
reason this fixture exists: a diff experiment needs *pairs*, and it needs to
know what the second member of each pair was supposed to differ by.

**Shared with Contract D (`EXP-0104`).** FreshnessBench seeds its drafts from
these transitions, so the case ids, the before/after versions and the gold
labels are the interface and are meant to stay stable. Adding a mutation class
is additive; renumbering the existing ones is not.

**What the seed corpus is, exactly.** Deterministically generated
contract-shaped documents, not a subset of the production corpus and not real
filings. Every choice comes from a sha256 over the seed and the position, so
two runs on two machines produce byte-identical fixtures and the reproducibility
gate is checkable. The cost is external validity, and it is a real cost: these
documents have the *shape* of the mutations we care about and none of the mess
of a real scan. The contract's other two dataset arms -- DART/SEC amendment
pairs and Office->PDF export pairs -- are not built here and are not claimed;
`build_suite` is the entry point they would plug into as additional cases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum

from akc_cir.identity import document_version_id, evidence_id, logical_id_seed, source_id
from akc_cir.semantic_diff import DocumentShape, UnitSnapshot

from .element_model import DocumentElement, ElementIndex, ElementType

__all__ = [
    "CRITICAL_MUTATIONS",
    "LAYOUT_ONLY_MUTATIONS",
    "SEMANTIC_MUTATIONS",
    "SUITE_VERSION",
    "DocumentVersion",
    "GoldLabels",
    "MutationCase",
    "MutationClass",
    "build_suite",
    "suite_manifest_sha256",
]

#: Bumped when the generated fixture changes in any way that moves a metric.
#: `EXP-0104` pins this, so a change here invalidates that experiment's receipts
#: as well as this one's.
SUITE_VERSION = "kes-1"

_TENANT = "tenant-evolution-suite"
_CONNECTOR = "fixture"


class MutationClass(StrEnum):
    """§9.7's eleven, verbatim and in the blueprint's order."""

    PURE_LAYOUT_MOVE = "pure_layout_move"
    SECTION_REORDERING = "section_reordering"
    TABLE_ROW_MOVE = "table_row_move"
    TABLE_CELL_NUMERIC_CHANGE = "table_cell_numeric_change"
    TYPO_ONLY = "typo_only"
    DATE_EFFECTIVE_PERIOD = "date_effective_period"
    MAY_TO_MUST = "may_to_must"
    EXCEPTION_ADD_REMOVE = "exception_add_remove"
    CLAUSE_SPLIT_MERGE = "clause_split_merge"
    FIGURE_REPLACEMENT = "figure_replacement"
    OCR_DEGRADATION_ONLY = "ocr_degradation_only"


#: The mutations that change what the document *means*.
SEMANTIC_MUTATIONS = frozenset(
    {
        MutationClass.TABLE_CELL_NUMERIC_CHANGE,
        MutationClass.DATE_EFFECTIVE_PERIOD,
        MutationClass.MAY_TO_MUST,
        MutationClass.EXCEPTION_ADD_REMOVE,
        MutationClass.CLAUSE_SPLIT_MERGE,
        MutationClass.FIGURE_REPLACEMENT,
    }
)

#: §9.8's controlled high-risk set: figures, modal verbs, exception clauses,
#: effective dates. Recall on these is the acceptance criterion, and a miss here
#: is the failure the whole contract is written against.
CRITICAL_MUTATIONS = frozenset(
    {
        MutationClass.TABLE_CELL_NUMERIC_CHANGE,
        MutationClass.DATE_EFFECTIVE_PERIOD,
        MutationClass.MAY_TO_MUST,
        MutationClass.EXCEPTION_ADD_REMOVE,
    }
)

#: Where a reported semantic change is a false positive by construction. Note
#: `TYPO_ONLY` is not here: it is a content edit that does not change meaning,
#: which is a different and harder case than a pure re-render.
LAYOUT_ONLY_MUTATIONS = frozenset(
    {
        MutationClass.PURE_LAYOUT_MOVE,
        MutationClass.SECTION_REORDERING,
        MutationClass.TABLE_ROW_MOVE,
        MutationClass.OCR_DEGRADATION_ONLY,
    }
)

_SUBJECTS = ("warranty", "licence", "indemnity", "delivery", "audit", "renewal")
_PARTIES = ("supplier", "buyer", "licensor", "auditor")
_MODALS = ("may", "shall", "should")
_TOPICS = ("scope", "term", "remedy")
_FIGURE_TOPICS = ("throughput", "coverage", "latency", "retention")


def _pick(options: tuple[str, ...], *parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return options[int.from_bytes(digest[:4], "big") % len(options)]


def _pick_int(low: int, high: int, *parts: str) -> int:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()
    return low + int.from_bytes(digest[4:8], "big") % (high - low + 1)


@dataclass(frozen=True, slots=True)
class _ElementSpec:
    """One element before it is given ids, pages and neighbours."""

    kind: ElementType
    section: str
    anchor: str
    text: str
    style: str
    order: int
    explicit_identifier: str = ""
    table_key: str = ""
    binds_to_anchor: str = ""
    entities: frozenset[str] = frozenset()
    page: int = 0
    bbox: tuple[int, int, int, int] = (100, 60, 900, 180)


@dataclass(frozen=True, slots=True)
class DocumentVersion:
    """One version, described both as `UnitSnapshot`s and as typed elements."""

    version_id: str
    source: str
    content_sha256: str
    units: tuple[UnitSnapshot, ...]
    elements: tuple[DocumentElement, ...]
    shape: DocumentShape

    @property
    def index(self) -> ElementIndex:
        return ElementIndex.of(self.version_id, list(self.elements))


@dataclass(frozen=True, slots=True)
class GoldLabels:
    """What the mutation did, decided by construction rather than by judgement."""

    semantic_change: bool
    critical: bool
    layout_only: bool
    #: before logical id -> after logical id, for every unit that continues.
    aligned_pairs: tuple[tuple[str, str], ...]
    #: before-side ids whose meaning changed. Drives downstream impact recall.
    changed_logical_ids: tuple[str, ...]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    def as_record(self) -> dict[str, object]:
        return {
            "semantic_change": self.semantic_change,
            "critical": self.critical,
            "layout_only": self.layout_only,
            "aligned_pairs": [list(pair) for pair in self.aligned_pairs],
            "changed_logical_ids": list(self.changed_logical_ids),
            "added": list(self.added),
            "removed": list(self.removed),
        }


@dataclass(frozen=True, slots=True)
class MutationCase:
    case_id: str
    document_id: str
    mutation: MutationClass
    before: DocumentVersion
    after: DocumentVersion
    gold: GoldLabels

    def as_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "document_id": self.document_id,
            "mutation": self.mutation.value,
            "before_version_id": self.before.version_id,
            "after_version_id": self.after.version_id,
            "before_sha256": self.before.content_sha256,
            "after_sha256": self.after.content_sha256,
            "gold": self.gold.as_record(),
        }


# ---------------------------------------------------------------------------
# seed corpus
# ---------------------------------------------------------------------------


def _clause_text(document_id: str, section: int, position: int) -> tuple[str, frozenset[str]]:
    key = (document_id, str(section), str(position))
    party = _pick(_PARTIES, "party", *key)
    subject = _pick(_SUBJECTS, "subject", *key)
    modal = _pick(_MODALS, "modal", *key)
    topic = _pick(_TOPICS, "topic", *key)
    days = _pick_int(10, 90, "days", *key)
    year = _pick_int(2024, 2029, "year", *key)
    month = _pick_int(1, 12, "month", *key)
    day = _pick_int(1, 28, "day", *key)
    text = (
        f"The {party} {modal} provide the {subject} {topic} within {days} days "
        f"of the effective date {year}-{month:02d}-{day:02d}."
    )
    return text, frozenset({party, subject})


def _seed_specs(document_id: str) -> list[_ElementSpec]:
    specs: list[_ElementSpec] = []
    order = 0
    for section in (1, 2, 3):
        section_name = f"section_{section}"
        heading = _pick(_SUBJECTS, "heading", document_id, str(section))
        specs.append(
            _ElementSpec(
                kind=ElementType.HEADING,
                section=section_name,
                anchor=f"h-{section}",
                text=f"Article {section}. {heading.title()} provisions",
                style="heading-16pt",
                order=order,
                entities=frozenset({heading}),
            )
        )
        order += 1
        for position in (1, 2):
            text, entities = _clause_text(document_id, section, position)
            specs.append(
                _ElementSpec(
                    kind=ElementType.TEXT,
                    section=section_name,
                    anchor=f"c-{section}-{position}",
                    text=f"Clause {section}.{position}. {text}",
                    style="body-11pt",
                    order=order,
                    explicit_identifier=f"{section}.{position}",
                    entities=entities,
                )
            )
            order += 1

    specs.append(
        _ElementSpec(
            kind=ElementType.TABLE,
            section="section_2",
            anchor="t-1",
            text="Service level | target | penalty",
            style="table-header-10pt",
            order=order,
        )
    )
    order += 1
    for row in (1, 2, 3):
        key = ("row", document_id, str(row))
        metric = _pick(_SUBJECTS, *key)
        target = _pick_int(90, 99, "target", *key)
        penalty = _pick_int(2, 20, "penalty", *key)
        specs.append(
            _ElementSpec(
                kind=ElementType.TABLE_ROW,
                section="section_2",
                anchor=f"t-1-r{row}",
                text=f"{metric} | {target} percent | {penalty} percent credit",
                style="table-body-10pt",
                order=order,
                table_key=metric,
            )
        )
        order += 1

    specs.append(
        _ElementSpec(
            kind=ElementType.FORMULA,
            section="section_3",
            anchor="f-1",
            text="credit = penalty * (target - achieved) / 100",
            style="formula-11pt",
            order=order,
        )
    )
    order += 1
    figure_topic = _pick(_FIGURE_TOPICS, "figure", document_id)
    specs.append(
        _ElementSpec(
            kind=ElementType.FIGURE,
            section="section_3",
            anchor="fig-1",
            text=f"Figure 1: monthly {figure_topic}",
            style="figure",
            order=order,
            entities=frozenset({figure_topic}),
        )
    )
    order += 1
    specs.append(
        _ElementSpec(
            kind=ElementType.CAPTION,
            section="section_3",
            anchor="cap-1",
            text=f"Figure 1 shows monthly {figure_topic} against the agreed target.",
            style="caption-9pt",
            order=order,
            binds_to_anchor="fig-1",
            entities=frozenset({figure_topic}),
        )
    )
    order += 1
    specs.append(
        _ElementSpec(
            kind=ElementType.FOOTNOTE,
            section="section_3",
            anchor="fn-1",
            text="Percentages are measured over a calendar month.",
            style="footnote-8pt",
            order=order,
        )
    )
    return specs


def _paginate(specs: list[_ElementSpec]) -> list[_ElementSpec]:
    """Lay elements out down pages of six, in reading order.

    Position is derived from order rather than stored independently, so a
    mutation that reorders the document produces the page and box changes a
    re-render would produce, instead of a reordering with stale coordinates.
    """
    laid: list[_ElementSpec] = []
    for position, spec in enumerate(sorted(specs, key=lambda item: item.order)):
        slot = position % 6
        top = 60 + slot * 150
        laid.append(
            replace(spec, order=position, page=position // 6, bbox=(100, top, 900, top + 120))
        )
    return laid


def _materialize(specs: list[_ElementSpec], *, source: str, tag: str) -> DocumentVersion:
    ordered = sorted(specs, key=lambda item: item.order)
    payload = json.dumps(
        [
            [
                spec.kind.value,
                spec.section,
                spec.anchor,
                spec.text,
                spec.style,
                spec.order,
                spec.page,
                list(spec.bbox),
            ]
            for spec in ordered
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    content_sha256 = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    version = document_version_id(source=source, content_sha256=content_sha256)

    logical_ids = {
        spec.anchor: logical_id_seed(
            source=source, document_path=(spec.section,), anchor=spec.anchor
        )
        for spec in ordered
    }

    units: list[UnitSnapshot] = []
    elements: list[DocumentElement] = []
    for position, spec in enumerate(ordered):
        previous_anchor = ordered[position - 1].anchor if position > 0 else ""
        next_anchor = ordered[position + 1].anchor if position + 1 < len(ordered) else ""
        anchored_evidence = evidence_id(
            document_version=version,
            page_number1=spec.page + 1,
            bbox1000=spec.bbox,
            span_text=spec.text,
        )
        logical = logical_ids[spec.anchor]
        units.append(
            UnitSnapshot(
                logical_id=logical,
                text=spec.text,
                document_path=(spec.section,),
                anchor=spec.anchor,
                neighbour_anchors=(previous_anchor, next_anchor),
                evidence_id=anchored_evidence,
                page_number1=spec.page + 1,
                entities=spec.entities,
                explicit_identifier=spec.explicit_identifier,
                geometry_style=spec.style,
            )
        )
        elements.append(
            DocumentElement(
                element_id=f"el_{tag}_{spec.anchor}",
                version_id=version,
                element_type=spec.kind,
                logical_id=logical,
                text=spec.text,
                structural_path=(spec.section,),
                page_index=spec.page,
                bbox1000=spec.bbox,
                order_index=spec.order,
                table_key=spec.table_key,
                binds_to=logical_ids.get(spec.binds_to_anchor, ""),
                evidence_id=anchored_evidence,
            )
        )

    rows = sum(1 for spec in ordered if spec.kind is ElementType.TABLE_ROW)
    shape = DocumentShape(
        heading_path_set=frozenset(
            (spec.section, spec.anchor) for spec in ordered if spec.kind is ElementType.HEADING
        ),
        block_count=len(ordered),
        table_shapes=((rows, 3),),
        figure_refs=frozenset(
            spec.text.split(":")[0] for spec in ordered if spec.kind is ElementType.FIGURE
        ),
    )
    return DocumentVersion(
        version_id=version,
        source=source,
        content_sha256=content_sha256,
        units=tuple(units),
        elements=tuple(elements),
        shape=shape,
    )


# ---------------------------------------------------------------------------
# mutations
# ---------------------------------------------------------------------------


def _find(specs: list[_ElementSpec], anchor: str) -> int:
    for position, spec in enumerate(specs):
        if spec.anchor == anchor:
            return position
    raise KeyError(f"no element anchored at {anchor}")


def _text_anchors(specs: list[_ElementSpec]) -> list[str]:
    return [spec.anchor for spec in specs if spec.kind is ElementType.TEXT]


_TYPO_SAFE = ("provide", "within", "effective", "days")

#: Optical confusions the challenger's fold table knows how to invert.
_OCR_SWAPS_COVERED = (("m", "rn"), ("w", "vv"), ("d", "cl"))

#: One it does not. Half the documents get this as well, on purpose: a fixture
#: that only ever injects corruptions the challenger can undo measures the
#: fixture, not the challenger. With this in, the OCR class splits into a half
#: the type reasoning can demote and a half it cannot, and the reported rate is
#: fold-table coverage rather than a claim about scans in general.
_OCR_SWAPS_UNCOVERED = (("e", "c"),)


def _apply(
    mutation: MutationClass, specs: list[_ElementSpec], document_id: str
) -> tuple[list[_ElementSpec], list[str], list[str], list[str]]:
    """Return the mutated specs plus (changed anchors, added, removed).

    Changed anchors are the ones whose *meaning* moved, which is not the same
    as the ones whose bytes moved: a re-paginated clause has new coordinates
    and the same meaning, and the gold labels have to say so or the layout-only
    false-positive rate would be measuring nothing.
    """
    working = list(specs)
    target = _pick(tuple(_text_anchors(working)), "target", mutation.value, document_id)

    if mutation is MutationClass.PURE_LAYOUT_MOVE:
        # A re-render that pushes everything from the second page onward down
        # by one slot. Reading order is untouched; every box and page below the
        # break changes.
        moved = [
            replace(spec, page=spec.page + 1 if spec.order >= 6 else spec.page)
            for spec in working
        ]
        return moved, [], [], []

    if mutation is MutationClass.SECTION_REORDERING:
        first = [spec for spec in working if spec.section == "section_1"]
        third = [spec for spec in working if spec.section == "section_3"]
        rest = [spec for spec in working if spec.section not in {"section_1", "section_3"}]
        reordered = third + rest + first
        return (
            _paginate([replace(spec, order=position) for position, spec in enumerate(reordered)]),
            [],
            [],
            [],
        )

    if mutation is MutationClass.TABLE_ROW_MOVE:
        first_row = _find(working, "t-1-r1")
        last_row = _find(working, "t-1-r3")
        swapped = list(working)
        swapped[first_row], swapped[last_row] = (
            replace(swapped[last_row], order=working[first_row].order),
            replace(swapped[first_row], order=working[last_row].order),
        )
        return _paginate(swapped), [], [], []

    if mutation is MutationClass.TABLE_CELL_NUMERIC_CHANGE:
        row_anchor = _pick(("t-1-r1", "t-1-r2", "t-1-r3"), "row", mutation.value, document_id)
        position = _find(working, row_anchor)
        spec = working[position]
        metric, target_cell, penalty_cell = (part.strip() for part in spec.text.split("|"))
        old_target = int(target_cell.split()[0])
        new_target = old_target - 1 if old_target > 90 else old_target + 1
        working[position] = replace(
            spec, text=f"{metric} | {new_target} percent | {penalty_cell}"
        )
        return working, [row_anchor], [], []

    if mutation is MutationClass.TYPO_ONLY:
        position = _find(working, target)
        spec = working[position]
        word = next((item for item in _TYPO_SAFE if item in spec.text), "within")
        typo = word[:-2] + word[-1] + word[-2] if len(word) > 3 else word
        working[position] = replace(spec, text=spec.text.replace(word, typo, 1))
        return working, [], [], []

    if mutation is MutationClass.DATE_EFFECTIVE_PERIOD:
        position = _find(working, target)
        spec = working[position]
        head, _, tail = spec.text.partition("effective date ")
        year = int(tail[:4])
        working[position] = replace(
            spec, text=f"{head}effective date {year + 1}{tail[4:]}"
        )
        return working, [target], [], []

    if mutation is MutationClass.MAY_TO_MUST:
        candidates = [
            spec.anchor
            for spec in working
            if spec.kind is ElementType.TEXT and " may " in spec.text
        ]
        if not candidates:
            # Not every seeded document draws a `may`. Promote a `should`
            # instead rather than skipping the class for that document, which
            # would leave the class with an uneven denominator.
            candidates = [
                spec.anchor
                for spec in working
                if spec.kind is ElementType.TEXT and " should " in spec.text
            ]
        if not candidates:
            candidates = [target]
        anchor = _pick(tuple(candidates), "modal", mutation.value, document_id)
        position = _find(working, anchor)
        spec = working[position]
        text = spec.text.replace(" may ", " must ", 1).replace(" should ", " must ", 1)
        if text == spec.text:
            text = spec.text.replace(" shall ", " must ", 1)
        if text == spec.text:
            # The gold label is about to say this clause changed. If nothing
            # was replaced it did not, and a silently unchanged case would put
            # a permanent miss in the critical-recall denominator.
            raise ValueError(f"{anchor} carries no modal verb to promote")
        working[position] = replace(spec, text=text)
        return working, [anchor], [], []

    if mutation is MutationClass.EXCEPTION_ADD_REMOVE:
        position = _find(working, target)
        spec = working[position]
        head, _, body = spec.text.partition(". ")
        working[position] = replace(
            spec, text=f"{head}. Except where Article 2 applies, {body[0].lower()}{body[1:]}"
        )
        return working, [target], [], []

    if mutation is MutationClass.CLAUSE_SPLIT_MERGE:
        position = _find(working, target)
        spec = working[position]
        head, _, tail = spec.text.partition(" within ")
        working[position] = replace(spec, text=f"{head}.")
        working.insert(
            position + 1,
            replace(
                spec,
                anchor=f"{spec.anchor}-b",
                text=f"The obligation applies within {tail}",
                explicit_identifier="",
                order=spec.order,
            ),
        )
        return (
            _paginate([replace(item, order=index) for index, item in enumerate(working)]),
            [target],
            [f"{spec.anchor}-b"],
            [],
        )

    if mutation is MutationClass.FIGURE_REPLACEMENT:
        replacement = _pick(_FIGURE_TOPICS, "replacement", mutation.value, document_id)
        figure_position = _find(working, "fig-1")
        caption_position = _find(working, "cap-1")
        old_topic = working[figure_position].text.split("monthly ")[-1]
        if replacement == old_topic:
            replacement = _FIGURE_TOPICS[
                (_FIGURE_TOPICS.index(old_topic) + 1) % len(_FIGURE_TOPICS)
            ]
        working[figure_position] = replace(
            working[figure_position],
            text=f"Figure 2: monthly {replacement}",
            entities=frozenset({replacement}),
        )
        working[caption_position] = replace(
            working[caption_position],
            text=f"Figure 2 shows monthly {replacement} against the agreed target.",
            entities=frozenset({replacement}),
        )
        return working, ["fig-1", "cap-1"], [], []

    # OCR_DEGRADATION_ONLY. Applied to letters only, and with every digit left
    # alone, so the class means what its name says: the scan got worse and the
    # document did not change.
    position = _find(working, target)
    spec = working[position]
    swaps = list(_OCR_SWAPS_COVERED)
    if _pick(("covered", "mixed"), "ocr-mode", document_id) == "mixed":
        swaps.extend(_OCR_SWAPS_UNCOVERED)
    degraded = spec.text
    for source_char, target_chars in swaps:
        degraded = degraded.replace(source_char, target_chars)
    working[position] = replace(spec, text=degraded)
    return working, [], [], []


def _build_case(
    document_id: str, mutation: MutationClass, specs: list[_ElementSpec]
) -> MutationCase:
    source = source_id(tenant_id=_TENANT, connector_type=_CONNECTOR, native_id=document_id)
    before = _materialize(list(specs), source=source, tag="before")
    mutated, changed_anchors, added_anchors, removed_anchors = _apply(
        mutation, list(specs), document_id
    )
    after = _materialize(mutated, source=source, tag="after")

    def logical_of(version: DocumentVersion, anchor: str) -> str:
        for unit in version.units:
            if unit.anchor == anchor:
                return unit.logical_id
        raise KeyError(f"{anchor} is not in {version.version_id}")

    before_anchors = {unit.anchor for unit in before.units}
    after_anchors = {unit.anchor for unit in after.units}
    aligned = tuple(
        (logical_of(before, anchor), logical_of(after, anchor))
        for anchor in sorted(before_anchors & after_anchors)
    )
    return MutationCase(
        case_id=f"{document_id}::{mutation.value}",
        document_id=document_id,
        mutation=mutation,
        before=before,
        after=after,
        gold=GoldLabels(
            semantic_change=mutation in SEMANTIC_MUTATIONS,
            critical=mutation in CRITICAL_MUTATIONS,
            layout_only=mutation in LAYOUT_ONLY_MUTATIONS,
            aligned_pairs=aligned,
            changed_logical_ids=tuple(
                logical_of(before, anchor) for anchor in sorted(changed_anchors)
            ),
            added=tuple(logical_of(after, anchor) for anchor in sorted(added_anchors)),
            removed=tuple(logical_of(before, anchor) for anchor in sorted(removed_anchors)),
        ),
    )


def build_suite(*, documents: int = 60) -> tuple[MutationCase, ...]:
    """Every document crossed with every mutation class, in a fixed order.

    Crossed rather than sampled: a per-class denominator that varies between
    runs makes two runs' rates incomparable, and the contract asks for every
    metric to carry its denominator.
    """
    if documents < 1:
        raise ValueError("the suite needs at least one seed document")
    cases: list[MutationCase] = []
    for index in range(documents):
        document_id = f"kes-doc-{index:03d}"
        specs = _paginate(_seed_specs(document_id))
        for mutation in MutationClass:
            cases.append(_build_case(document_id, mutation, list(specs)))
    return tuple(cases)


def suite_manifest_sha256(cases: tuple[MutationCase, ...]) -> str:
    """The corpus manifest digest every receipt in the experiment binds to."""
    payload = json.dumps(
        {
            "suite_version": SUITE_VERSION,
            "cases": [case.as_record() for case in cases],
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
