# USKC P0 — Lane C report: ReaderProvider SDK + registry (`akc_readers`)

Campaign `TAVONEL-USKC-P0-20260906-V1`. Contract `USKC_LANE_CONTRACT_2026-09-06.md` §4.4, §5 C, §7 R-3.
Worktree `D:\CodexProjects\uskc-lanes\core-c-reader-sdk`, base core `d9db24c`.

## 1. Branch and pushed SHA

- Branch: `agent/uskc-c-reader-sdk`
- SDK + doc commit: `d6a7203`
- Report commit / branch tip pushed: `5dd15a6` (`5dd15a6cf86ea61bf74ed980b97bf26b45faf910`)
- No PR, no merge, no deploy, no migration. Core repo — no Vercel preview applies.

## 2. Files created / modified

Created (all inside the lane's exclusive ownership row):

| Path | What |
|---|---|
| `packages/readers/src/akc_readers/__init__.py` | package exports |
| `packages/readers/src/akc_readers/enums.py` | frozen vocabulary + `FailureCode` ↔ `FailureClass` mapping data |
| `packages/readers/src/akc_readers/models.py` | `ReaderInput`, `SourceInspection`, `ReaderCapability`, `ExtractedUnit`, `NativeExtraction`, `ReaderHealth`, `ReaderRun`, `ReaderRegistryEntry`, `ReaderResolution` |
| `packages/readers/src/akc_readers/inspector.py` | blueprint §8.1 inspector wrapping `validate_source()` |
| `packages/readers/src/akc_readers/registry.py` | `ReaderProvider` / `VisualReaderProvider` protocols, `ReaderRegistry`, breaker, receipts, locator validation |
| `packages/readers/src/akc_readers/providers.py` | `PlainTextV1`, `LegacyPdfV1` |
| `packages/readers/src/akc_readers/py.typed` | typed marker |
| `packages/readers/src/akc_readers/contract/enums.v1.json` | **verbatim** copy, sha256 `3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1` |
| `packages/readers/src/akc_readers/contract/evidence-locator.v2.schema.json` | **verbatim** copy, sha256 `13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6` |
| `packages/readers/tests/test_frozen_contract.py` | artifact hashes + enum transliteration + mapping-gap tests |
| `packages/readers/tests/test_reader_plane.py` | inspector, resolution, providers, receipts, failure paths |
| `docs/architecture/reader-provider-plane.md` | the lane doc |
| `USKC_LANE_REPORT_C.md` | this file |

Row-only edits (exactly the two the contract allows, both in root `pyproject.toml`):

- `[tool.hatch.build.targets.wheel] packages` — one row `"packages/readers/src/akc_readers",`
- `[tool.pytest.ini_options] pythonpath` — one row `"packages/readers/src",`

Nothing else in the repository is modified. `akc_native_parsers/security.py`,
`parser.py`, `pdf_parser.py`, `akc_router/providers.py`, `akc_cir/**`,
`packages/contracts/**`, `research/**`, `docs/evidence/**` are untouched.
`[tool.coverage.run] source` was **not** extended — the contract allows two rows
only, and `akc_readers` is deliberately outside the seven-package 80% gate, so
this lane cannot move that number in either direction.

## 3. Gates

Interpreter for every command: `D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe`
(referred to below as `PY`), run from the worktree root.

Import resolution verified before trusting any run: under pytest,
`akc_cir.__file__` is
`D:\CodexProjects\uskc-lanes\core-c-reader-sdk\packages\cir-python\src\akc_cir\__init__.py`
— the worktree, via `pythonpath` in `pyproject.toml`. No `PYTHONPATH` override
was needed. (A bare `PY -c "import akc_cir"` outside pytest resolves to the main
checkout's editable install; that is expected and only pytest runs matter.)

### Gate 1 — `PY -m pytest packages/readers/tests -q -p no:randomly`

exit **0**

```
................................                                         [100%]
32 passed in 15.76s
```

### Gate 2a — `PY -m ruff check packages/readers`

exit **0**

```
All checks passed!
```

Also run over the whole CI package scope, `PY -m ruff check packages` — exit **0**,
`All checks passed!`. And with `--extend-select RUF100` to prove no dead `noqa`
directive was left behind — exit **0**.

### Gate 2b — `PY -m mypy packages/readers`

exit **0**

```
Success: no issues found in 6 source files
```

### Gate 3 — `PY -m pytest tests/unit -q -p no:randomly`

exit **1** — **7 pre-existing failures, none in this lane's scope.**

```
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[stale-attribution-correction-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[question-set-v1-invalidation-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v6-acquisition-failure-diagnosis-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-acquisition-failure-2026-08-20.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-post-open-instrumentation.json]
FAILED tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate
FAILED tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data
7 failed, 1005 passed, 74 skipped in 325.96s (0:05:25)
```

Verbatim head of the first failure, reported and **not fixed** per contract §2:

```
E       AssertionError: stale-attribution-correction-2026-08-19.json retracts a version of structure-only-stale-diagnosis-2026-08-18.json that is not the one on disk.
E           declared: sha256:ba444ddb6b2e479da706a3e723e11b21bb2c17c10e4f79fe2e4e104c58fc8ee7
E           actual:   sha256:522d8a5cac38161634d098ed9e8dc86b7c54704157949be52f8b8ed291f2e056
E         The retraction no longer applies to these bytes, so the retracted claim is live again.
```

None of these tests import `akc_readers`, and no file they read is touched by
this branch (`git status` shows three paths, all listed in §2). **They are
nonetheless a `CLAUDE.md` "stop the line" class — evidence hash mismatch — and
the founder should see them:** five retraction receipts point at digests that no
longer match the bytes on disk, which by that test's own words means the
retracted claim is live again. Not this lane's to fix.

### Gate 3b — `PY -m mypy packages services` (the CI mypy scope)

exit **1** — **2 pre-existing errors, neither in this lane's files.**

```
packages\absorption\src\akc_absorption\synthetic_corruption.py:36: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
services\api\src\akc_api\collection_retrieval_api.py:413: error: Invalid index type "tuple[UUID | None, int | None]" for "dict[tuple[UUID, int], DocumentVersion]"; expected type "tuple[UUID, int]"  [index]
Found 2 errors in 2 files (checked 269 source files)
```

### Gate 4 — `git status` / push

`git status --short` before commit showed exactly `M pyproject.toml`,
`?? docs/architecture/reader-provider-plane.md`, `?? packages/readers/`.

**One side effect worth naming:** running `pytest tests/unit` rewrites
`docs/repro/TEST_SCOPE_SELF_TEST.json` — a test in that scope regenerates it.
That file is outside this lane's ownership row, so the change was reverted with
`git checkout --` and is **not** in either commit. In a worktree it regenerates
with `"project_venv_present": false` and `"is_project_interpreter": false`,
because the worktree has no `.venv` of its own even though the run used the
project interpreter. That is a worktree artefact of the self-test's detection,
not a real interpreter regression — but any lane that commits this file from a
worktree would publish a false negative about the interpreter guard.

`git push -u origin agent/uskc-c-reader-sdk` — exit **0**:
`* [new branch]      agent/uskc-c-reader-sdk -> agent/uskc-c-reader-sdk`.
Production deploy 안 함. Core repo이므로 Preview deployment도 생성되지 않음.

### Gates not run, with the reason

- `uv run --locked --extra dev pytest --cov --cov-fail-under=80` (seam map's full
  coverage gate) — **skipped**. `akc_readers` is not in `[tool.coverage.run]
  source` and the contract permits only two `pyproject.toml` rows, so this lane
  cannot change that number; running the full-tree coverage suite would only
  re-measure the pre-existing failures above. Gate 3 is the contract's core-lane
  scope and it was run.
- `tools/repro/run_test_scopes.py --scopes full` — **skipped**. It is the seam
  map's gate list, not the contract's (§2 "Gates — core lanes"), and the `full`
  scope runs the whole repository including paths this lane is forbidden to
  touch while the Model Arena chain is live.
- Playwright / `pnpm` gates — not applicable; this is a core lane.

## 4. What the blueprint asked that I did NOT do, and why

1. **§14.2 scanned-PDF / OCR reader, §9 `render()` and `extract_visual()`.**
   Not built. `VisualReaderProvider` exists as the frozen shape of §9's optional
   half with no implementation. P0-C is the SDK; adding an OCR provider means a
   GPU runtime, an image digest and a §27 qualification suite, none of which
   exist in this campaign. `legacy_pdf_v1` is the native path only, and the doc
   says so rather than implying scanned PDFs are covered.
2. **§13 reconciliation / loss detection.** Needs two representations to
   disagree; there is one.
3. **§14.4–14.x readers for DOCX/XLSX/PPTX/HWPX/images/email/code/CAD/media.**
   Not built. The inspector *identifies* those packages; no provider claims them,
   so they resolve `UNSUPPORTED` — fail closed, not a silent pass-through.
4. **§22 measured registry fields** (`p50/p95LatencyMs`, `costPerUnit`,
   `memoryRequirement`, `strengths`, `weaknesses`, `evaluatorReceipts`). Left
   `None`/empty and `status: candidate`. There is no measurement, and the Model
   Arena directory is off-limits this campaign. `ReaderRegistryEntry` refuses to
   be `qualified` without at least one evaluator receipt (tested). The doc lists
   exactly what each field must be filled from when the Arena is wired.
5. **§44 `$/source`, `$/page`, `$/accepted knowledge unit`.** Not computable:
   `gpu_seconds` and `provider_cost_usd` are `null` because no GPU ran and no
   price snapshot exists. Nothing in this package publishes a cost number.
6. **§27 qualification suite.** Not run. Consequently **no reader here is
   `VERIFIED_NATIVE` or `VERIFIED_HYBRID`** — `ReaderCapability` refuses to
   construct a VERIFIED tier without a receipt digest (tested).
7. **`schema.py` registration and `generated-contracts.ts`.** Not touched — one
   regeneration in P0, and it is lane E's (seam map X-7, contract §4.5).
8. **Retry policy.** `retries` is in the receipt and is always 0; the registry
   does not retry. Recovery is `akc_cir.recovery_policy`'s job (Protected Core,
   read-only here).

## 5. Conflicts with other lanes or with the contract — proposals, not edits

1. **`akc_readers` imports `akc_cir.inspection.FailureCode`.** The seam map's
   backward-compat obligation #1 says the registry "must not import from
   `akc_cir` Protected Core at all", while contract §4.4 says the mapping table
   "starts from `akc_cir.inspection.FailureCode` F0–F48". I followed the
   contract (§7: the contract is the decision). It is a **read-only import of an
   enum**; nothing in Protected Core is called, subclassed or modified, and
   §48 P0-C's "reader replaceable without compiler-core change" still holds — a
   new reader changes no core file. Transliterating the F-codes instead would let
   the two lists drift silently, which is worse. *Proposal: keep the import;
   record it in ADR-007 as the one permitted core dependency of the reader plane.*
2. **`ProviderRegistry` is not subclassed** (contract §4.4 asked for a reason if
   not): its resolution API is `parser_for(provider_id, route)` — resolution by
   name, which this lane's own acceptance test forbids from existing; it keys on
   `Route`, a GPU-tier concept; and its protocol is `async`. `ProviderUnavailableError`
   **is** imported and raised through, so isolation semantics are shared. Full
   reasoning in the doc.
3. **`ReaderCapability` is the fourth capability shape in the tree** (seam map
   C-9). It declares itself the source for *source-format* capability; the other
   three are untouched and nothing derives them yet. *Proposal: merging them is
   P4 (seam map O-3), and `RecipeProfile` is where a GPU reader's registry entry
   should be derived from.*
4. **Lane D consumes `qualification_status` from `ReaderCapability`.** Contract
   §7 R-4 already says D derives manifest v1 from the live site pipeline, not
   from this registry, so there is no coupling to resolve in P0. When D is
   regenerated from registry receipts, `CapabilityStatus` is byte-identical on
   both sides (both transliterate `contract/enums.v1.json`; both carry a test).
5. **Lane E owns the Python `EvidenceLocator` model.** This lane emits locators
   as dicts validated against its own verbatim copy of the schema and imports
   nothing from E, so the two branches do not collide. At integration the two
   verbatim schema copies are byte-identical and one can be dropped.
6. **No new third-party dependency.** Everything used is already in the root
   `pyproject.toml`: `jsonschema`, `pydantic`, `pypdf`, plus stdlib
   (`zipfile`, `concurrent.futures`, `fnmatch`, `hashlib`, `importlib.resources`).

## 6. Open questions for the founder

1. **`LocatorKind` has no plain-text variant.** `plain_text_v1` therefore emits
   **no** evidence locator — every existing variant needs an anchor a `.txt` has
   not got (a page, a commit sha, a JSON pointer), and inventing one is
   forbidden. *Proposed for enums v2:* a `text` variant keyed on
   `{byteRange | lineRange}` plus optional `encoding`. Until then, TXT/Markdown
   knowledge is not citable to an exact source location. This is a product
   decision, not an agent's.
2. **`PROBEABLE_FEATURES` is 4 of 14.** A reader that genuinely produces
   `comments`, `track_changes`, `chart_data`, `geometry`, `assembly`, `acl`,
   `thread`, `timestamp`, `ast` or `dependency_graph` cannot register today,
   because the registry has no way to witness those claims. Fail-closed by
   design; the upgrade is one `ExtractedUnit` field per feature, added when a
   reader that produces it arrives. Confirm that fail-closed is the wanted
   behaviour rather than "declare and trust".
3. **`ENCRYPTED_SOURCE` has no `FailureCode`.** Should F-codes gain an
   encryption code (so recovery policy can act on it), or does §45 stay the only
   vocabulary that expresses it?
4. **§27 qualification.** No `VERIFIED_*` tier can exist anywhere in the product
   until a qualification receipt is produced and committed. Who runs that suite,
   against which corpus, and where do the receipts live?
5. **Timeout kill.** A timed-out reader thread runs to completion (Python cannot
   kill a thread). Accept the leaked CPU second, or move reader execution into
   the existing `-I` subprocess sandbox now?
6. **Coverage.** Should `akc_readers` join the seven packages under the 80% merge
   gate? It would need a third `pyproject.toml` row, which this lane's contract
   does not permit.

## 7. Contradictions found, with path:line

1. **Seam map C-8 / contract §4.4 line 320 are incomplete.**
   `USKC_LANE_CONTRACT_2026-09-06.md:320` and `P0_SEAM_MAP_2026-09-06.md:229,501`
   both say the frozen classes with no `FailureCode` counterpart are
   `SOURCE_DELETED` and `PRESERVATION_FAILED`. **`ENCRYPTED_SOURCE` has none
   either** — `F28_SECURITY_BLOCKED`
   (`packages/cir-python/src/akc_cir/inspection.py:110`) is a security block, not
   a password. Recorded in `akc_readers.enums.FAILURE_CLASSES_WITHOUT_FAILURE_CODE`
   and pinned by `test_failure_mapping_names_its_gaps_in_both_directions`.
2. **The reverse gap is far larger than the seam map states.**
   `P0_SEAM_MAP_2026-09-06.md:501` lists nine F-codes with no §45 class
   (F2/F7/F9/F10/F21/F23/F26/F27/F29). Under an unambiguous-only mapping the real
   figure is **29 of 49** — the whole F29–F44/F48 block plus F15, F16, F18, F20.
   Computed, not asserted, in `FAILURE_CODES_WITHOUT_FAILURE_CLASS`.
3. **Contract §4.4 line ~317 maps `F3→PARSER_TIMEOUT`.** The code is
   `F3_QUEUE_TIMEOUT` (`akc_cir/inspection.py:83`) — a *queue* timeout, not a
   parser timeout. The mapping is kept (it is the only timeout class in §45), but
   it is a rename, not an equivalence, and the doc says so.
4. **Blueprint §9 names the inspect return type `ReaderInspection`
   (`…BLUEPRINT_2026-09-06.md:646`) while §8.2 defines `SourceInspection`
   (line ~616).** One type, two names. Implemented as `SourceInspection`, per the
   contract's frozen §4.4 signature.
5. **Blueprint §10's manifest example uses locator kinds that are not in the
   frozen list** — `"evidenceLocatorKinds": ["xlsx_cell", "xlsx_range",
   "xlsx_chart"]` (`…BLUEPRINT_2026-09-06.md:699`) versus `LocatorKind`'s single
   `"xlsx"` in `contract/enums.v1.json`. Sub-kinds live inside the `xlsx` variant
   (`cell` / `range` / `chartId`), not in the kind enum. **This affects lane D**,
   whose manifest field is that list.
6. **Seam map Lane C "Creates"/"Modifies" is superseded** by contract §7 R-3:
   the SDK is `packages/readers` (`akc_readers`), not a module inside
   `akc_native_parsers`, and `security.py` is not edited. Followed the contract.
   Its `validate_source()` is wrapped: its `StructuredParseError` codes become
   `SourceInspection.review_reasons`, exactly as R-3 specifies.
7. **`validate_source()` covers seven extensions, not the eleven MIME types the
   site accepts** (`packages/native-parsers/src/akc_native_parsers/security.py:24-25`:
   `.docx .pptx .xlsx .html .htm .srt .vtt`). PDF has no `validate_source()` path
   at all — `parse_pdf_to_cir` does its own checks inline
   (`pdf_parser.py:354-379`). The inspector therefore runs its own §8.1 chain for
   PDF and text and only defers to `validate_source()` for those seven. Worth
   knowing for lane D's honesty about where each format's gate actually is.
