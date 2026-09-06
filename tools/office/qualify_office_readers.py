"""Qualify the native Office readers against the committed corpus (lane C-3).

For each format the tool runs the provider over
``tests/fixtures/office_corpus/<format>``, derives the observed value of every
capability row in ``expected.json`` **from the provider's own output**, and
writes ``docs/evidence/receipts/office_reader_qualification_<format>_<date>.json``.

Two things about this measurement are worth stating plainly, because they decide
what the receipt can honestly say.

*The subject is the provider surface, not the parser.* A qualification receipt
backs a `ReaderCapability` tier, and a caller of the reader plane sees exactly
one thing: the `ExtractedUnit` stream, each unit carrying text, an
EvidenceLocator v2 anchor, an optional bbox, table id and formula. A fact the
wrapped parser knows but never puts into a unit — a merged span, a hidden sheet,
a comment's author, a deleted phrase — is *not recoverable by a caller*, so the
row that asks for it fails. Those rows are marked ``unobservable`` with the
reason, and they are the lane's C-4 list.

*The status rule is the contract's, not a judgement.* Founder ruling G-6
(contract §4) requires six kinds of evidence in a family's own receipt before
it may say ``VERIFIED_NATIVE``: structural preservation, source locator
correctness, the website full sequence, malformed-input behaviour, measured
performance, and deterministic output. This tool measures the first two and
cites committed tests for the fourth and sixth; the website sequence and the
performance figures are lane C-5 and are recorded as ``ABSENT``. So every
receipt this tool writes is ``BEST_EFFORT`` by construction, and the manifest
is never edited to move that line.

Determinism: the only clock is ``--generated-at``, which defaults to the date in
the receipt filename. Everything else is a function of the committed bytes.
``runtime`` is the exception and is excluded from the drift test: it pins the
interpreter and library versions that ran the qualification, and a different
patch release legitimately changes it.

Run: ``python tools/office/qualify_office_readers.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
for _relative in (
    "packages/cir-python/src",
    "packages/security/src",
    "packages/native-parsers/src",
    "packages/readers/src",
):
    _source_root = str(REPO_ROOT / _relative)
    if _source_root not in sys.path:
        sys.path.insert(0, _source_root)

from akc_readers import (  # noqa: E402 - the path bootstrap above must run first
    CapabilityStatus,
    NativeDocxV1,
    NativePptxV1,
    NativeXlsxV1,
    ReaderInput,
)
from akc_readers.models import ExtractedUnit  # noqa: E402
from akc_readers.office import (  # noqa: E402
    DOCX_MIME,
    PPTX_MIME,
    XLSX_MIME,
    _NativeOfficeV1,
)

RECEIPT_SCHEMA = "tavonel.office_reader_qualification.v1"
RECEIPT_DATE = "2026-09-06"
CORPUS_ROOT = REPO_ROOT / "tests" / "fixtures" / "office_corpus"
EXPECTED_PATH = CORPUS_ROOT / "expected.json"
RECEIPT_DIR = REPO_ROOT / "docs" / "evidence" / "receipts"

PROVIDERS: dict[str, tuple[type[_NativeOfficeV1], str]] = {
    "xlsx": (NativeXlsxV1, XLSX_MIME),
    "docx": (NativeDocxV1, DOCX_MIME),
    "pptx": (NativePptxV1, PPTX_MIME),
}


# --------------------------------------------------------------------------
# observers: expected fact -> what the provider's units actually show
# --------------------------------------------------------------------------

Units = Sequence[ExtractedUnit]
Observer = Callable[[Units], Any]

#: CIR gives table cells their own id prefix, which is the one stable way to
#: tell a cell unit from the table block unit that precedes it.
_CELL_PREFIX = "cell_"


def _anchored(units: Units, field: str) -> list[tuple[dict[str, Any], ExtractedUnit]]:
    return [(unit.locator, unit) for unit in units if unit.locator and field in unit.locator]


def _xlsx_key(locator: dict[str, Any], field: str) -> str:
    return f"{locator['sheet']}!{locator[field]}"


def _xlsx_sheet_names(units: Units) -> list[str]:
    names: list[str] = []
    for unit in units:
        if unit.locator is None:
            continue
        sheet = unit.locator.get("sheet")
        if isinstance(sheet, str) and sheet not in names:
            names.append(sheet)
    return names


def _xlsx_cell_values(units: Units) -> dict[str, str]:
    return {_xlsx_key(locator, "cell"): unit.text for locator, unit in _anchored(units, "cell")}


def _xlsx_formula_text(units: Units) -> dict[str, str]:
    return {
        _xlsx_key(locator, "cell"): unit.formula
        for locator, unit in _anchored(units, "cell")
        if unit.formula is not None
    }


def _xlsx_table_range(units: Units) -> dict[str, str]:
    return {locator["sheet"]: locator["range"] for locator, _ in _anchored(units, "range")}


def _xlsx_chart_title(units: Units) -> dict[str, str]:
    return {
        locator["sheet"]: unit.text.split("\n")[0]
        for locator, unit in _anchored(units, "chartId")
    }


def _xlsx_chart_series_names(units: Units) -> dict[str, list[str]]:
    return {
        locator["sheet"]: [line.split(": ", 1)[0] for line in unit.text.split("\n")[1:]]
        for locator, unit in _anchored(units, "chartId")
    }


def _docx_paragraphs(units: Units, prefix: str) -> list[tuple[str, ExtractedUnit]]:
    return [
        (locator["paragraphId"], unit)
        for locator, unit in _anchored(units, "paragraphId")
        if str(locator["paragraphId"]).startswith(prefix)
    ]


def _docx_body_paragraphs(units: Units) -> list[str]:
    return [unit.text for _, unit in _docx_paragraphs(units, "docx/body/p/")]


def _docx_headers_footers(units: Units) -> dict[str, str]:
    return {
        paragraph_id: unit.text for paragraph_id, unit in _docx_paragraphs(units, "docx/section/")
    }


def _docx_table_cells(units: Units) -> dict[str, dict[str, str]]:
    order: list[str] = []
    cells: dict[str, dict[str, str]] = {}
    for locator, unit in _anchored(units, "cellId"):
        if not unit.unit_id.startswith(_CELL_PREFIX):
            continue
        table_id = str(locator["tableId"])
        if table_id not in order:
            order.append(table_id)
        cells.setdefault(str(order.index(table_id)), {})[str(locator["cellId"])] = unit.text
    return cells


def _docx_comment_text(units: Units) -> dict[str, str]:
    return {str(locator["commentId"]): unit.text for locator, unit in _anchored(units, "commentId")}


def _docx_footnotes(units: Units) -> dict[str, str]:
    return {
        str(locator["footnoteId"]): unit.text for locator, unit in _anchored(units, "footnoteId")
    }


def _docx_equation_formula(units: Units) -> bool:
    return any(unit.formula is not None for unit in units)


def _pptx_slide(locator: dict[str, Any]) -> str:
    return str(locator["slideNumber1"])


def _pptx_slide_units(units: Units) -> dict[str, list[str]]:
    slides: dict[str, list[str]] = {}
    for locator, unit in _anchored(units, "slideNumber1"):
        if unit.unit_id.startswith(_CELL_PREFIX):
            continue
        slides.setdefault(_pptx_slide(locator), []).append(unit.text)
    return slides


def _pptx_shape_reading_order(units: Units) -> dict[str, list[str]]:
    slides: dict[str, list[str]] = {}
    for locator, _ in _anchored(units, "shapeId"):
        shapes = slides.setdefault(_pptx_slide(locator), [])
        shape_id = str(locator["shapeId"])
        if shape_id not in shapes:
            shapes.append(shape_id)
    return slides


def _pptx_table_cells(units: Units) -> dict[str, list[str]]:
    tables: dict[str, list[str]] = {}
    for locator, unit in _anchored(units, "shapeId"):
        if not unit.unit_id.startswith(_CELL_PREFIX):
            continue
        key = f"{_pptx_slide(locator)}/{locator['shapeId']}"
        tables.setdefault(key, []).append(unit.text)
    return tables


def _unobservable(units: Units) -> None:
    """No field of the unit stream witnesses this fact. Never a guess."""
    return None


#: Why a capability has no observer. These are the C-4 items: closing one means
#: giving `ExtractedUnit` a field that carries the evidence (and, for a named
#: range, giving the parser something to carry).
UNOBSERVABLE: dict[str, str] = {
    "xlsx_merged_ranges": (
        "ExtractedUnit carries no rowSpan/columnSpan; CanonicalCell has them, the reader "
        "surface does not. The covered cells are absent from the unit stream, which is a "
        "consequence of a merge, not evidence of its extent."
    ),
    "xlsx_named_ranges": (
        "the xlsx parser records no defined names at all, so no unit and no metadata "
        "carries one; EvidenceLocator v2 has a namedRange anchor with nothing to fill it."
    ),
    "xlsx_hidden_sheets": (
        "sheet visibility lives in the parser's metadata['sheets'][*]['state'] and in the "
        "cell quality flags; NativeExtraction carries neither."
    ),
    "docx_merged_cell_spans": (
        "same as xlsx_merged_ranges: the span is computed by the parser and dropped at the "
        "reader surface."
    ),
    "docx_comment_author": (
        "the parser keeps the author as a quality flag on the comment block "
        "(comment_author_preserved) rather than as text; ExtractedUnit has no attribution "
        "field, so the author cannot reach a caller."
    ),
    "docx_tracked_changes": (
        "insertions are folded into the visible paragraph text and deletions are kept only "
        "in metadata['docx']['trackedChanges']; neither is a unit, so the change list and "
        "the deleted text are unreachable."
    ),
    "docx_endnotes": (
        "the docx parser reads word/footnotes.xml and never word/endnotes.xml, so an "
        "endnote body is not a block at all; and EvidenceLocator v2's docx variant has "
        "paragraphId / tableId+cellId / commentId / footnoteId and no endnote anchor, so "
        "even an extracted endnote would have nothing to be addressed by. Closing this row "
        "needs the parser and an enums v2 locator field, in that order."
    ),
    "docx_equation_formula": (
        "the docx parser flattens OMML to its run text and never sets formula_latex, so the "
        "equation's structure (the superscript) is lost even though its characters survive."
    ),
    "pptx_speaker_notes": (
        "the notes block's native id is pptx/slide/NNNN/notes and EvidenceLocator v2's pptx "
        "variant has no notes field. The note's text lives in "
        "ppt/notesSlides/notesSlideN.xml, not in the slide part a slideNumber1 anchor names, "
        "so the unit carries locator=None. Its text is still emitted; what a caller cannot "
        "get is an address for it."
    ),
    "pptx_merged_cell_spans": (
        "same as xlsx_merged_ranges, and the pptx variant additionally has no cell anchor at "
        "all: a cell is addressed no finer than its shape."
    ),
}

OBSERVERS: dict[str, Observer] = {
    "xlsx_sheet_names": _xlsx_sheet_names,
    "xlsx_cell_values": _xlsx_cell_values,
    "xlsx_formula_text": _xlsx_formula_text,
    "xlsx_table_range": _xlsx_table_range,
    "xlsx_chart_title": _xlsx_chart_title,
    "xlsx_chart_series_names": _xlsx_chart_series_names,
    "docx_body_paragraphs": _docx_body_paragraphs,
    "docx_equation_text": _docx_body_paragraphs,
    "docx_headers_footers": _docx_headers_footers,
    "docx_table_cells": _docx_table_cells,
    "docx_comment_text": _docx_comment_text,
    "docx_footnotes": _docx_footnotes,
    "pptx_slide_units": _pptx_slide_units,
    "pptx_shape_reading_order": _pptx_shape_reading_order,
    "pptx_table_cells": _pptx_table_cells,
    **{name: _unobservable for name in UNOBSERVABLE},
}


# --------------------------------------------------------------------------
# the six-item evidence block (contract §4, founder ruling G-6)
# --------------------------------------------------------------------------

#: Promotion to `VERIFIED_NATIVE` needs all six of these in the family's own
#: receipt. This tool measures two of them and cites committed tests for two
#: more; `website` (upload -> CDR -> native read -> compile -> evidence UI on a
#: Preview) and `performance` (p50/p95 per file-size class) are lane C-5 work
#: and no artifact here measures them. They are `ABSENT`, never "not
#: applicable", so the receipt states the gap rather than hiding it.
EVIDENCE_ITEMS: tuple[str, ...] = (
    "structural",
    "locator",
    "website",
    "malformed",
    "performance",
    "deterministic",
)

#: Capabilities whose observed value is *selected by an EvidenceLocator v2
#: anchor* — the sheet/cell, paragraphId, tableId+cellId, commentId,
#: footnoteId, slideNumber1 or shapeId a unit carries. A failing row here is
#: counted against the `locator` item. That is deliberately the conservative
#: reading: this receipt cannot separate a wrong anchor from correct addressing
#: of content the reader got wrong, so it never records the more flattering of
#: the two. `docx_equation_formula` is excluded because it reads a unit field,
#: not an anchor, and the unobservable rows are excluded because they select
#: nothing at all.
LOCATOR_KEYED: frozenset[str] = frozenset(
    {
        "xlsx_sheet_names",
        "xlsx_cell_values",
        "xlsx_formula_text",
        "xlsx_table_range",
        "xlsx_chart_title",
        "xlsx_chart_series_names",
        "docx_body_paragraphs",
        "docx_equation_text",
        "docx_headers_footers",
        "docx_table_cells",
        "docx_comment_text",
        "docx_footnotes",
        "pptx_slide_units",
        "pptx_shape_reading_order",
        "pptx_table_cells",
    }
)

#: The committed tests that measure an evidence item this tool does not run
#: itself. `_cited_tests` checks each one is really in the tree; a citation that
#: has been renamed or deleted demotes its item to `ABSENT` rather than leaving
#: a `PASS` standing on a test that no longer exists.
_READER_TESTS = "tests/unit/test_office_readers.py"
_CORPUS_TESTS = "tests/unit/test_office_qualification.py"

EVIDENCE_CITATIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "malformed": tuple(
        (_READER_TESTS, name)
        for name in (
            "test_an_undecompressable_package_member_is_a_receipt_not_an_exception",
            "test_a_malformed_main_part_is_refused_not_partially_extracted",
            "test_a_zip_bomb_office_package_is_refused_not_partially_extracted",
            "test_an_external_relationship_is_refused_not_partially_extracted",
            "test_macro_enabled_bytes_are_refused_not_partially_extracted",
            "test_a_password_protected_office_container_is_locked_not_corrupt",
        )
    ),
    "deterministic": (
        (_CORPUS_TESTS, "test_the_corpus_rebuilds_to_the_committed_bytes"),
        (_CORPUS_TESTS, "test_the_committed_receipt_matches_a_fresh_run"),
        (_READER_TESTS, "test_probe_samples_are_byte_deterministic"),
    ),
}

EVIDENCE_NOTES: dict[str, str] = {
    "structural": (
        "measured here: every expected-manifest row for this family, from the provider's "
        "own ExtractedUnit stream over the committed corpus."
    ),
    "locator": (
        "measured here: the rows whose observed value is selected by an EvidenceLocator v2 "
        "anchor. A row whose value differs is counted as a miss, because this receipt "
        "cannot tell a wrong anchor from a right anchor over wrong content."
    ),
    "website": (
        "ABSENT: the full upload -> CDR -> native read -> compile -> evidence UI sequence on "
        "a Preview deployment is lane C-5. Nothing in this repository measures it, and no "
        "test here is a substitute for it."
    ),
    "malformed": (
        "not measured by this tool; the committed tests named in evidenceCitations are, and "
        "they run in the CI unit scope. They cover an undecompressable package member, a "
        "malformed main part, a zip bomb, an external relationship, macro-enabled bytes and "
        "a password-protected container, each asserted through ReaderRegistry.read()."
    ),
    "performance": (
        "ABSENT: no p50/p95 per file-size class has been measured for these readers. A "
        "timing taken on this machine would not be a receipt."
    ),
    "deterministic": (
        "not measured by this tool; the committed tests named in evidenceCitations are. They "
        "rebuild the corpus to the committed bytes and re-run this qualifier against the "
        "committed receipt."
    ),
}


def _cited_tests(item: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """The citations for one evidence item, or an empty list if any is gone."""
    citations = EVIDENCE_CITATIONS.get(item, ())
    if not citations:
        return []
    found: list[str] = []
    for relative, test_name in citations:
        path = repo_root / relative
        if not path.is_file() or f"def {test_name}(" not in path.read_text(encoding="utf-8"):
            return []
        found.append(f"{relative}::{test_name}")
    return found


def _evidence(rows: Sequence[dict[str, Any]], repo_root: Path = REPO_ROOT) -> dict[str, str]:
    """The six-item block. `ABSENT` is a value, not a missing key."""
    locator_rows = [row for row in rows if row["capability"] in LOCATOR_KEYED]
    evidence = {
        "structural": "PASS" if all(row["pass"] for row in rows) else "FAIL",
        "locator": "PASS" if all(row["pass"] for row in locator_rows) else "FAIL",
        "website": "ABSENT",
        "malformed": "PASS" if _cited_tests("malformed", repo_root) else "ABSENT",
        "performance": "ABSENT",
        "deterministic": "PASS" if _cited_tests("deterministic", repo_root) else "ABSENT",
    }
    return {item: evidence[item] for item in EVIDENCE_ITEMS}


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------


def _read_units(provider: _NativeOfficeV1, mime: str, path: Path, relative: str) -> Units:
    data = path.read_bytes()
    source = ReaderInput(
        # The qualification identity is the corpus path, so a receipt row names
        # the file it measured and two runs bind to the same ids.
        source_version_id=f"corpus-{relative.replace('/', '-').replace('.', '-')}",
        tenant_id="office-qualification",
        representation_id="original",
        filename=path.name,
        declared_mime=mime,
        content_sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        data=data,
    )
    return provider.extract_native(source).units


def _corpus_digest(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return "sha256:" + digest.hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_receipt(
    source_format: str,
    *,
    generated_at: str = RECEIPT_DATE,
    corpus_root: Path = CORPUS_ROOT,
    expected_path: Path = EXPECTED_PATH,
) -> dict[str, Any]:
    """Run one provider over its corpus and return the receipt body."""
    provider_type, mime = PROVIDERS[source_format]
    provider = provider_type()
    manifest = json.loads(expected_path.read_text(encoding="utf-8"))
    entries = [entry for entry in manifest["files"] if entry["format"] == source_format]

    rows: list[dict[str, Any]] = []
    for entry in entries:
        path = corpus_root / entry["path"]
        recorded = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded != entry["sha256"]:
            raise SystemExit(
                f"{entry['path']} digests {recorded}, not the manifest's {entry['sha256']}; "
                "rebuild the corpus rather than qualifying against bytes the manifest "
                "does not describe"
            )
        units = _read_units(provider, mime, path, entry["path"])
        for row in entry["rows"]:
            capability = row["capability"]
            observer = OBSERVERS.get(capability)
            if observer is None:
                raise SystemExit(f"expected.json names an unknown capability {capability!r}")
            observed = observer(units)
            result: dict[str, Any] = {
                "file": entry["path"],
                "capability": capability,
                "expected": row["expected"],
                "observed": observed,
                "pass": observed == row["expected"],
            }
            if capability in UNOBSERVABLE:
                result["unobservable"] = UNOBSERVABLE[capability]
            rows.append(result)

    passed = sum(1 for row in rows if row["pass"])
    failed = [row for row in rows if not row["pass"]]
    evidence = _evidence(rows)
    status = (
        CapabilityStatus.VERIFIED_NATIVE
        if not failed and all(value == "PASS" for value in evidence.values())
        else CapabilityStatus.BEST_EFFORT
    )
    return {
        "schemaVersion": RECEIPT_SCHEMA,
        "format": source_format,
        "providerId": provider.provider_id,
        "revision": provider.revision,
        "generatedAt": generated_at,
        "corpus": {
            "root": f"tests/fixtures/office_corpus/{source_format}",
            "fileCount": len(entries),
            "sha256": _corpus_digest([corpus_root / entry["path"] for entry in entries]),
        },
        "expectedManifest": {
            "path": "tests/fixtures/office_corpus/expected.json",
            "sha256": _file_digest(expected_path),
        },
        "runtime": {
            "digest": provider.runtime_digest,
            "python": ".".join(str(part) for part in sys.version_info[:3]),
        },
        "rows": rows,
        "totals": {"rows": len(rows), "passed": passed, "failed": len(failed)},
        "failedCapabilities": sorted({str(row["capability"]) for row in failed}),
        "evidence": evidence,
        "evidenceNotes": EVIDENCE_NOTES,
        "evidenceCitations": {
            item: _cited_tests(item) for item in EVIDENCE_ITEMS if _cited_tests(item)
        },
        "status": status.value,
        "statusRule": (
            "VERIFIED_NATIVE requires all six evidence items PASS in this receipt "
            "(lane contract §4, founder ruling G-6); C-3 supplies at most four, so "
            "this tool never mints one. Every expected row must also pass, and a failing "
            "row is listed verbatim as a known limitation. A receipt claiming "
            "VERIFIED_NATIVE with any ABSENT item is a P0 false success."
        ),
    }


def receipt_path(source_format: str, generated_at: str = RECEIPT_DATE) -> Path:
    return RECEIPT_DIR / f"office_reader_qualification_{source_format}_{generated_at}.json"


def serialise(receipt: dict[str, Any]) -> str:
    return json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--generated-at",
        default=RECEIPT_DATE,
        help="the date recorded in the receipt and in its filename (no wall clock is read)",
    )
    parser.add_argument("--format", choices=sorted(PROVIDERS), action="append")
    arguments = parser.parse_args(argv)

    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    for source_format in arguments.format or sorted(PROVIDERS):
        receipt = build_receipt(source_format, generated_at=arguments.generated_at)
        path = receipt_path(source_format, arguments.generated_at)
        path.write_text(serialise(receipt), encoding="utf-8", newline="\n")
        totals = receipt["totals"]
        print(
            f"{source_format}: {totals['passed']}/{totals['rows']} rows pass -> "
            f"{receipt['status']}  ({path.relative_to(REPO_ROOT).as_posix()})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
