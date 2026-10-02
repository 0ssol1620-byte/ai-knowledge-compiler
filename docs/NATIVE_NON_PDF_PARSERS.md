# Structured Non-PDF Native Parsers

The `akc_native_parsers` package converts validated DOCX, PPTX, XLSX, HTML,
SRT, WebVTT, and CSV bytes directly into canonical CIR. These seven non-PDF
formats are deliberately separate from the PDF parser; the CPU document worker
integrates them through an explicit sandbox manifest adapter.

HWP and HWPX are not supported. They are not in the extension allowlist, and a
Compound File Binary container submitted under an OOXML extension (the wrapper
used by password-protected OOXML, legacy binary Office files, and HWP) is
rejected as `OFFICE_CFB_CONTAINER_UNSUPPORTED` without being opened.

## Public boundary

```python
from datetime import UTC, datetime

from akc_native_parsers import ParseContext, parse_non_pdf_to_cir

cir = parse_non_pdf_to_cir(
    filename="evidence.docx",
    declared_mime=("application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    data=payload,
    context=ParseContext(
        tenant_id="tenant_123",
        document_id="document_123",
        document_version_id="version_123",
        created_at=datetime.now(UTC),
    ),
)
```

The call is synchronous and side-effect free. It does not access the network,
spawn subprocesses, extract an archive to disk, execute macros, activate
embedded objects, calculate spreadsheet formulas, or fetch HTML assets.
`StructuredParseError.code` is the stable job-boundary failure value; exception
messages never include source bytes.

## Structure and provenance

| Format  | CIR structure                                                                                                                                            | Native source location                                         |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| DOCX    | title, headings with parents, paragraphs, lists, quotes, merged tables, distinct headers and footers                                                     | `docx/body/...` and `docx/section/...`                         |
| PPTX    | one title/heading parent per slide, positioned text/list blocks, merged tables, figures/charts as inert references, speaker notes                        | `pptx/slide/{index}/shape/{z-path}/...`; normalized `bbox1000` |
| XLSX    | one heading parent and one sparse canonical used-range table per sheet, merged spans, hidden state, formulas plus cached values, explicit table metadata | `xlsx/sheet/{index}/cell/{A1}` and `/range/{A1:B2}`            |
| HTML    | DOM-order title/headings/paragraphs/lists/quotes/code/tables/figures/captions; `main` or a single `article` receives priority                            | `html/{DOM-path}` including stable `text()[n]` nodes           |
| SRT/VTT | transcript title plus time-ranged cue blocks, speaker labels, adjacent repeated-cue merge                                                                | `{srt,vtt}/cue/{source-index}` and millisecond ranges          |
| CSV     | one sparse canonical table; every non-empty field is a string cell with verbatim raw text; no header row is declared or inferred                      | `csv/row/{record:06d}/cell/{A1}` and `csv/table/range/{A1:B2}` |

Every block and table cell has a `SourceRef`. Block, table, and cell IDs are a
SHA-256 derivation of the source digest and stable native location. Parsers walk
native order and apply explicit deterministic tie breakers; CIR block order is
globally unique and contiguous. Warnings and quality flags are de-duplicated
and sorted before serialization.

## Fail-closed validation

Validation occurs before a format library receives the bytes:

1. Allowlisted extension and exact MIME aliases must agree.
2. Office files must have ZIP magic, the matching OOXML root, and
   `[Content_Types].xml`. A Compound File Binary header is rejected as
   `OFFICE_CFB_CONTAINER_UNSUPPORTED`; nothing is decrypted.
3. ZIP paths must be relative and unique. Encrypted entries, symlinks,
   excessive entry/member/expanded sizes, and excessive compression ratios are
   rejected.
4. DTD/entity declarations, macro-enabled content types, VBA/executable parts,
   ActiveX, OLE/embedded objects, custom UI, external-link parts, and external
   OOXML relationships are rejected.
5. Text formats (HTML, SRT, WebVTT, CSV) must be strict UTF-8 without NUL
   bytes; a UTF-8 BOM is accepted. HTML must have an HTML signature and WebVTT
   must have a `WEBVTT` signature.
6. Unexpected library or malformed-package exceptions are converted to a
   format-specific `*_PARSE_FAILED` code.

HTML is parsed locally. Active elements and event attributes are removed;
URL-bearing attributes are stripped before extraction and no resource is
fetched. The removal count and `html_external_references_not_fetched` warning
are retained in CIR metadata.

XLSX is opened once with formulas and once in `data_only` mode, always with
`keep_links=False`. Formulas are preserved as source text and are never
evaluated. A cached value is used as normalized text only when it already
exists in the workbook; otherwise the cell receives
`formula_cached_value_missing`.

CSV uses one fixed RFC 4180 dialect: comma delimiter, `"` quote character,
doubled quotes as the escape, strict quoting. The dialect is never sniffed: a
semicolon- or tab-delimited file is still split on commas only, so its
structure is not recovered. An unterminated or misplaced quote fails the whole
document as `CSV_MALFORMED`. CSV must be UTF-8; the legacy text path's encoding
fallbacks do not apply. Each cell keeps the field exactly as the reader produced it in
`rawText` (surrounding whitespace, embedded CRLF, Unicode composition); only
`normalizedText` is normalized. Fields that begin with `=`, `+`, `-`, or `@`
remain text: they are never evaluated, the cell's `formula` stays absent,
`valueType` stays `string`, and the cell is flagged
`spreadsheet_formula_prefix_preserved_as_text` with a document warning
`csv_formula_prefixed_text_not_executed`. Escaping such text is an export
concern, not a CIR change. The first record is not promoted to a header:
`headerRowCount` is `0` and the table carries `csv_header_not_declared`.
Records of differing width are kept as-is and flagged `csv_ragged_records`.

## Default hard limits

These are parser safety ceilings, not customer plan quotas. Callers can replace
them with stricter positive values through `ParserLimits`.

| Limit                                      |                         Default | Failure                                          |
| ------------------------------------------ | ------------------------------: | ------------------------------------------------ |
| Input bytes                                |                          50 MiB | `FILE_TOO_LARGE`                                 |
| ZIP entries                                |                           2,000 | `ARCHIVE_ENTRY_LIMIT`                            |
| Expanded ZIP bytes                         |                         250 MiB | `ARCHIVE_SIZE_LIMIT`                             |
| One ZIP member                             |                          64 MiB | `ARCHIVE_MEMBER_LIMIT`                           |
| Compression ratio                          |                           100:1 | `ARCHIVE_RATIO_LIMIT`                            |
| CIR blocks / extracted characters          |             50,000 / 10,000,000 | `BLOCK_LIMIT` / `EXTRACTED_TEXT_LIMIT`           |
| Table rows / columns / occupied grid cells |       100,000 / 1,024 / 500,000 | `TABLE_*_LIMIT`                                  |
| Slides / shapes per slide                  |                   2,000 / 5,000 | `SLIDE_LIMIT` / `SLIDE_SHAPE_LIMIT`              |
| Sheets / rows / columns / cells per sheet  | 512 / 100,000 / 1,024 / 500,000 | `SHEET_*_LIMIT`                                  |
| HTML nodes / depth                         |                   150,000 / 256 | `HTML_NODE_LIMIT` / `HTML_DEPTH_LIMIT`           |
| Subtitle cues / characters per cue         |                100,000 / 20,000 | `SUBTITLE_CUE_LIMIT` / `SUBTITLE_CUE_TEXT_LIMIT` |
| CSV records / fields per record            |                 100,000 / 1,024 | `CSV_ROW_LIMIT` / `CSV_COLUMN_LIMIT`             |
| CSV parsed fields / characters per field   |               500,000 / 131,072 | `CSV_CELL_LIMIT` / `CSV_FIELD_LIMIT`             |

Table area and merged-span occupancy are bounded before grid allocation.
Worksheet XML is preflighted with `defusedxml` before `openpyxl` materializes a
workbook; cumulative merged ranges count against the per-sheet cell ceiling.
The four CSV ceilings are preflighted on a scan of the fixed strict dialect
before `csv.reader` materializes any record, so a source is refused at the
first ceiling it crosses in reading order; syntax errors are still reported by
the strict reader as `CSV_MALFORMED`.

## Deliberate fidelity boundaries

Native text and structure are authoritative. Media binaries are not decoded in
this package. DOCX media/SmartArt/comments/text boxes/tracked changes, PPTX
figures/charts, and XLSX images/charts produce explicit reference-only warnings
or quality flags instead of silently executing or interpreting content.
Rendered-page/OCR fidelity remains the separate PDF/GPU parser path.

Production workers must still apply process-level CPU, memory, wall-clock, and
filesystem isolation around this library. The in-process bounds are defense in
depth, not a replacement for a sandbox.

## Analysis worker integration

For the seven structured non-PDF formats (DOCX, PPTX, XLSX, HTML/HTM, SRT,
WebVTT, CSV), `sandbox_runner` calls `parse_non_pdf_to_cir` after the existing
upload checksum and file validation boundary. PDF is dispatched in the same
sandbox to the separate `parse_pdf_to_cir` parser and also yields CIR. Image,
Markdown, and plain-text sources remain on the legacy `parse_document` path and
produce no CIR. The successful subprocess manifest carries both logical pages
and, for the structured types, the complete `CanonicalDocument`.

Before persistence, the parent worker validates that:

- structured types (`pdf` plus the seven formats above) contain CIR and other
  types do not;
- tenant, document, version, source SHA, and document type match the claimed
  source context;
- every block and table-cell `SourceRef` belongs to that document version;
- logical page numbers are contiguous; and
- recomputed page text exactly matches the CIR blocks assigned to each page.

Persisted blocks use deterministic UUIDv5 database IDs. Parent relationships,
block order/type/origin, text and Markdown, normalized `bbox1000`, content
hashes, quality flags, tables, sanitized HTML, formula content, and every
native/time source reference are stored. The lossless fields live in
`Block.structured_content` under schema `akc-native-block-1.0`; the
persistence-to-CIR export bridge validates and restores that schema. Parser
metadata and the native source-location scheme are retained on the first
logical page.

All `StructuredParseError` values are non-retryable sandbox failures. A code
reaches `AnalysisTask.last_error_code` only if it is named in the worker's
explicit `_SAFE_ERROR_CODES` allowlist; any other code is recorded as
`PARSER_INTERNAL_ERROR`. The CSV codes (`CSV_MALFORMED`, `CSV_EMPTY_DOCUMENT`,
`CSV_ROW_LIMIT`, `CSV_COLUMN_LIMIT`, `CSV_CELL_LIMIT`, `CSV_FIELD_LIMIT`,
`CSV_TEXT_UNAVAILABLE`, `CSV_PARSE_FAILED`) and
`OFFICE_CFB_CONTAINER_UNSUPPORTED` are allowlisted. Persistence is
transactional, so a rejected manifest or parser failure leaves no partial Page
or Block rows.

## Verification

The focused unit module builds real minimal OOXML packages with
`python-docx`, `python-pptx`, and `openpyxl`, reads fixed HTML/SRT/VTT byte
fixtures, and uses synthetic CSV text. It verifies structure, provenance,
merged cells, formula policy, hidden sheets, speaker notes, cue timing/merge
behavior, CSV verbatim raw text and formula-prefix handling, deterministic CIR
round trips, active-content rejection, external-relationship rejection,
malformed-package normalization, and resource ceilings.

The worker end-to-end module uploads each of the seven formats through the API,
runs the analysis worker, and checks persisted Page/Block rows plus the
persistence-to-CIR export bridge. For a synthetic CSV it asserts that the
persisted `Block.structured_content` table and the reconstructed export table
keep each cell's verbatim `rawText`, its `normalizedText`, its
`csv/row/.../cell/...` source anchor, and formula-prefixed fields as
non-evaluated string cells. A malformed CSV is checked to reach `AnalysisTask`
as the non-retryable `CSV_MALFORMED` after a single attempt, with no Page or
Block rows written.

```powershell
.\.venv\Scripts\pytest.exe -q tests/unit/test_nonpdf_structured_parsers.py
.\.venv\Scripts\python.exe -m pytest -q services/api/tests/test_native_nonpdf_worker_e2e.py
.\.venv\Scripts\ruff.exe check packages/native-parsers/src tests/unit/test_nonpdf_structured_parsers.py
$env:MYPYPATH='packages/cir-python/src;packages/security/src;packages/native-parsers/src'
.\.venv\Scripts\mypy.exe --strict packages/native-parsers/src tests/unit/test_nonpdf_structured_parsers.py
```
