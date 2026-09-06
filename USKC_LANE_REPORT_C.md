# USKC P0 — Lane C report: ReaderProvider SDK + registry (`akc_readers`)

Campaign `TAVONEL-USKC-P0-20260906-V1`. Contract `USKC_LANE_CONTRACT_2026-09-06.md` §4.4, §5 C, §7 R-3.
Worktree `D:\CodexProjects\uskc-lanes\core-c-reader-sdk`, base core `d9db24c`.

## 1. Branch and pushed SHA

- Branch: `agent/uskc-c-reader-sdk`
- SDK + doc commit: `d6a7203`
- Report commit: `5dd15a6` (`5dd15a6cf86ea61bf74ed980b97bf26b45faf910`), SHA note `11c5a94`
- **Repair-pass commit: `f82fd57` (`f82fd57b1afdfd66094be9d7f4ceaed8d4278375`)** —
  see the Repair section at the end of this file. The commit that records that
  line was `63d9245e187ade32c4fb1da910bb171d49a9715c`.
- **Repair round 2 (2026-09-06): `88878dd`** (the four code findings + 13 failure-path
  tests) and the doc/report commit that follows it, which is the branch tip. See
  "Repair round 2" at the end of this file.
- No PR, no merge, no deploy, no migration. Core repo — no Vercel preview applies.

## 2. Files created / modified

Created — all inside the lane's exclusive ownership row **except the last row**:
`USKC_LANE_REPORT_C.md` is a repo-root file that contract §3's lane C row does
not cover. It is written and committed at the orchestrator's explicit
instruction; no other lane writes that path.

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

exit **1** — **7 failures, none in this lane's scope, none of them pre-existing
on `main`.** ("Pre-existing" was true only relative to this lane's own first pass
in the same worktree; all seven are artifacts of running the CI scope *inside a
worktree* — see the struck escalation below.)

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
this branch (`git status` shows three paths, all listed in §2).

> **Struck in repair round 2 (contract §8.1, "Withdrawn stop-the-line").** This
> paragraph originally escalated the seven failures to the founder as a
> `CLAUDE.md` "source or evidence hash mismatch" stop-the-line, on the strength
> of the test's own wording that "the retracted claim is live again". That
> diagnosis was wrong and I did not check the baseline before publishing it. The
> same tests pass in the **main checkout at the same commit** (the orchestrator
> measured 1,017 passed, 1 environment-dependent tooling failure). Five of the
> seven are a CRLF-vs-LF working-tree artifact — the receipt's declared digest
> `ba444ddb…` is the CRLF rendering of the bytes that a fresh worktree checks out
> as LF (`522d8a5c…`, the git blob's own sha256) — and the other two fail because
> `.gitignore:157` excludes `research/experiments/H1-W6-SAME-INTELLIGENCE-01/corpus-v7/`,
> which exists only in the main checkout. **No evidence was overwritten and no
> retracted claim is live.** The integrator adds an `eol=lf` attribute for the
> receipt paths only if the committed blobs are LF and a fresh worktree then
> hashes identically (§8.1). Nothing here is the founder's to act on.

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
4. **§27 qualification.** No `VERIFIED_*` tier can exist **in this registry**
   until a qualification receipt is produced and committed: since repair round 2
   the tier requires a receipt path, a sha256 and a date, and `register()` opens
   that file in this repository and re-digests it. (As first written this item
   said "anywhere in the product", which was a claim about code that did not
   exist: the registry then accepted any 64-hex string and `resolve()` published
   `VERIFIED_NATIVE` on it. It does not any more, and the scope of the sentence
   is this package — no other package is bound by it.) Who runs that suite,
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

---

# Repair pass (2026-09-06, after adversarial review)

Two reviewers returned `GO_WITH_CONDITIONS` with seven confirmed `major`
findings (five on fail-closed correctness, two on contract/honesty conformance)
and a list of contradicted report/doc statements. Every confirmed finding is
fixed below, each with the failure-path test that would have caught it. No
finding was rejected: I reproduced all seven. Scope was not widened beyond the
findings and the doc/report statements the reviewers contradicted.

## R1 — Source-side failure charged to the provider's circuit breaker

*(both lenses, `registry.py:392`; violated CLAUDE.md "separate operational
failure from semantic failure")*

`read()` incremented `entry.breaker.failures` for **every** non-accepted run, so
three whitespace-only `.txt` uploads opened the circuit and the next healthy
source was refused `PROVIDER_UNAVAILABLE` naming a reader that never failed.

Fix: `OPERATIONAL_FAILURE_CLASSES = {PARSER_TIMEOUT, PARSER_OOM,
PROVIDER_UNAVAILABLE}` (`registry.py`), and only a failure in that set charges
the breaker. `EMPTY_OUTPUT`, `CORRUPT_SOURCE`, `MALWARE_QUARANTINED`,
`RECEIPT_MISMATCH`, `EVIDENCE_BROKEN` and the feature-failure classes are the
*source's* failure and leave a working reader online.

The second half of the finding — a file whose ASCII head passes the 8 KB text
sniff but whose CP949 tail does not decode — was landing in the catch-all
`except Exception` and being published as `PROVIDER_UNAVAILABLE` with
`escalation_reason="UnicodeDecodeError"`. `read()` now catches
`UnicodeDecodeError` explicitly and classifies it `CORRUPT_SOURCE`: the bytes
are not what they were detected as, which is not the reader's fault. The 8 KB
sniff itself stays (a sniff that decodes whole files is not a sniff); the
mis-detection now fails closed with the honest class instead of blaming the
reader.

Tests: `test_blank_sources_never_take_a_healthy_reader_offline`,
`test_a_source_that_is_not_utf8_is_the_sources_failure_not_the_readers`
(both assert `circuit_open is False` after three consecutive failures, and the
first asserts the next good source is still accepted).

## R2 — Evidence locators were validated only at registration

*(lens 1, `registry.py:185`)*

`validate_evidence_locator` had exactly two callers: `register()` and the tests.
A production `read()` validated nothing, so an accepted extraction could carry a
locator the frozen `evidence-locator.v2.schema.json` rejects — reachable because
the locator's `sourceVersionId`/`representationId` come from the **caller's**
ids, which registration never sees, and the frozen `$defs/Identifier` pattern
`^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$` forbids the slashes and spaces an object
key carries.

Fix: `_verify_output()` validates every locator an accepted run carries — the
ones `emit_evidence_locators()` returns *and* the ones attached to
`ExtractedUnit.locator` — and refuses with `EVIDENCE_BROKEN`. The validator is
now built once (`jsonschema.validators.validator_for(...)`, `@cache`) instead of
recompiled per call, so validating per unit is not a per-run cost regression.

Test: `test_an_invalid_evidence_locator_is_refused_at_read_time_not_only_at_registration`
(the reviewer's exact ids, `tenant/9f21 doc#3` / `rep 1/2`).

## R3 — The registration probe checked the union of capabilities

*(lens 1, `registry.py:178`)*

`declared` was a set comprehension over **every** capability, compared against
one probe sample, so a provider could declare `tables` on a PDF capability on
the strength of a `.txt` probe and then be resolved for a PDF.

Fix: `probe_sample() -> ReaderInput` becomes `probe_samples() -> tuple[ReaderInput, ...]`
on the `ReaderProvider` protocol, and `register()` checks **per capability**: a
capability must be exercised by at least one sample whose inspected MIME and
source family it matches (`_capability_matches`, now shared with
`_best_capability`), and only the features observed on *those* samples count
toward it. A capability no sample exercises is refused.

Tests: `test_a_capability_no_probe_sample_exercises_is_refused` (the reviewer's
two-faced provider, txt + pdf) and `test_a_capability_with_its_own_probe_sample_registers`
(the fix refuses over-claiming, not multi-capability providers as such).

> **Superseded in repair round 2.** "A capability no sample exercises is refused"
> was true only when the over-claim was *split across* capabilities. Folded into
> one capability's `mime_patterns` / `source_families` it was neither refused nor
> witnessed. Witnessing is now per MIME pattern and per source family — see
> R2-1 below.

## R4 — `read()` never verified the extraction against the source

*(lens 1, `registry.py:381`)*

The §44 receipt copied the provider's self-asserted `output_digest`, and an
extraction bound to a different `sourceVersionId`/`representationId` was
accepted as this source's output.

Fix: `digest_units()` moves into `models.py` as the single definition; providers
compute it and `_verify_output()` **recomputes** it, refusing `RECEIPT_MISMATCH`
on a mismatch. The same check rejects an output whose `sourceVersionId`,
`representationId` or `providerId` is not the one asked for. The input-digest
check that already existed is unchanged.

Tests: `test_an_extraction_bound_to_another_source_is_refused`,
`test_a_self_asserted_output_digest_is_recomputed_not_believed`.

## R5 — `required_features` was satisfied from the declaration

*(lens 1, `registry.py:345`)*

`required_features` reached `resolve()` only, which filters *capabilities*.
An accepted run could answer a layout request with zero layout evidence.

Fix: `_verify_output()` compares `required` against
`NativeExtraction.observed_features()` and refuses with the class the missing
feature names — `FEATURE_TO_FAILURE_CLASS` in `enums.py`
(`native_text→TEXT_OMISSION`, `layout→LAYOUT_FAILURE`, `tables→TABLE_FAILURE`,
`formula→FORMULA_FAILURE`), falling back to `PRESERVATION_FAILED`. `read()` also
now materialises `required_features` once, so a generator argument is no longer
consumed by `resolve()` before the check.

Test: `test_a_required_feature_absent_from_the_output_is_refused`.

## R6 — A malware refusal was published as `CORRUPT_SOURCE`

*(lens 2, `docs/architecture/reader-provider-plane.md:211`)*

The doc claimed `validate_source()` codes become "(via `PARSE_ERROR_TO_CLASS`) a
frozen failure class"; `inspector.py` never referenced that table, so
`OFFICE_ACTIVE_CONTENT`, `OOXML_UNSAFE_XML` and the archive-bomb limits surfaced
as `CORRUPT_SOURCE` in the class lane F consumes as audit vocabulary.

Fix: `resolve()` derives the corrupted-source class from the review reasons
(`_corruption_class`): any reason `PARSE_ERROR_TO_CLASS` maps to
`MALWARE_QUARANTINED` wins, everything else stays `CORRUPT_SOURCE`. The
inspector still sets only the two facts it can stand behind; the doc now says
where the translation happens.

Test: `test_active_content_is_published_as_malware_not_as_ordinary_corruption`
(an `.xlsx` package carrying `xl/vbaProject.bin`).

## R7 — The encrypted-Office failure path was not the product's

*(reviewer contradiction, not a numbered finding)*

The committed test patched the ZIP general-purpose encryption bit. A real
ECMA-376 password-protected `.docx` is **not a ZIP**: it is an OLE/CFB container,
so it came back `encrypted=False, corrupted=True, MAGIC_MISMATCH` — refused, but
mislabelled.

Fix: the inspector sniffs the CFB magic (`D0 CF 11 E0 A1 B1 1A E1`) and the
UTF-16LE `EncryptedPackage` directory name (MS-OFFCRYPTO) and reports
`encrypted` with `OOXML_ENCRYPTED_PACKAGE`; `validate_source()`'s
`MAGIC_MISMATCH` no longer also marks such a file corrupt. The source family
stays `unknown` — `.doc`, `.xls` and `.msg` are CFB as well and guessing which
would be an invention.

**Stated plainly:** the new test is a *signature* test built from those two byte
sequences, not a real password-protected Office file — no such file exists in
this repository and none is claimed. The ZIP-bit test stays as what it is: the
ZIP-level encrypted-entry path.

Test: `test_a_cfb_office_container_holding_an_encrypted_package_is_locked_not_corrupt`.

## R8 — `runtime_digest` did not pin the code `legacy_pdf_v1` runs

*(reviewer contradiction on the doc's "a real pin of the real runtime")*

It pinned `python` + `pypdf` + two literals, while the reader's behaviour comes
from `akc_native_parsers`, which ships no version metadata in this monorepo. A
§22 pin that does not move when the wrapped code moves would misattribute a later
Arena receipt.

Fix: `_wrapped_parser_digest()` — sha256 over every `.py` source of the wrapped
package, in path order, cached — is one of `legacy_pdf_v1`'s runtime pins. The
doc now states exactly what it covers and what it does not (non-Python assets;
pypdf beyond its version string).

Test: `test_the_legacy_pdf_runtime_digest_pins_the_wrapped_parser_source`.

## Verifying the tests bind to the repair

The new tests were run with each guard disabled at runtime (project interpreter,
`PYTHONPATH` set to this worktree's `packages/*/src`), and the old defect
reappears in every case:

```
breaker guard off -> circuit_open: True
breaker guard off -> good read class: PROVIDER_UNAVAILABLE
verify OFF -> accepted True   digest sha256:02644cb9784c0…
             locator INVALID under frozen schema:
             'tenant/9f21 doc#3' does not match '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
verify ON  -> accepted False  class EVIDENCE_BROKEN
derivation off -> CORRUPT_SOURCE      derivation on -> MALWARE_QUARANTINED
```

## Contradicted statements, corrected

Every reviewer contradiction is accepted; each is now true or retracted:

1. *"this lane emits locators as dicts validated against its own verbatim copy"*
   — was true only at registration. Now true at both ends (R2); the doc says so.
2. *"a provider declaring tables it cannot produce → registration refused"* —
   held only for the single-capability shape. Now per capability (R3).
3. *"Encrypted OOXML (ZIP bit patched) → ARCHIVE_ENCRYPTED_ENTRY"* — that is the
   ZIP-level path, not what Office produces. The CFB path now exists and is
   labelled honestly as a signature test (R7).
4. *§44 receipt table "input/output digest … yes"* — `output_digest` was copied
   from the provider. Now recomputed (R4); the table says "recomputed".
5. *`runtime_digest` "a real pin of the real runtime"* — now pins the wrapped
   parser's sources too (R8).
6. *"Created (all inside the lane's exclusive ownership row)"* — **accurate
   finding, not fixed by code.** `USKC_LANE_REPORT_C.md` is a repo-root file that
   contract §3's lane C row (`packages/readers/**`, root `pyproject.toml`,
   `docs/architecture/reader-provider-plane.md`) does not cover. The orchestrator
   instructed both lanes' reports to be written to that exact path and committed
   on the branch, so the file stays; the §2 sentence is corrected to say it is
   written on the orchestrator's instruction and is outside the ownership row.
   No other lane writes it, so it cannot conflict.
7. *Breaker described purely as a provider-fault mechanism* — it was not one.
   Now it is (R1), and the doc names the exact class set.

## Files changed in the repair

| Path | Change |
|---|---|
| `packages/readers/src/akc_readers/registry.py` | `OPERATIONAL_FAILURE_CLASSES`; per-capability registration probe; `_capability_matches`; `_corruption_class`; `_verify_output`; cached schema validator; `UnicodeDecodeError` → `CORRUPT_SOURCE`; `required_features` materialised once |
| `packages/readers/src/akc_readers/models.py` | `digest_units()` — the one definition of the output digest |
| `packages/readers/src/akc_readers/enums.py` | `FEATURE_TO_FAILURE_CLASS` |
| `packages/readers/src/akc_readers/inspector.py` | CFB + `EncryptedPackage` detection; a file already known encrypted is not also called corrupt |
| `packages/readers/src/akc_readers/providers.py` | `probe_samples()`; `digest_units` reused; `_wrapped_parser_digest()` in `legacy_pdf_v1`'s runtime pin |
| `packages/readers/src/akc_readers/__init__.py` | exports for the three new public names |
| `packages/readers/tests/test_reader_plane.py` | 11 new failure-path tests (32 → 43) |
| `docs/architecture/reader-provider-plane.md` | registration, run-verification, breaker, inspector, locator and runtime-digest sections corrected |
| `USKC_LANE_REPORT_C.md` | this section |

No new dependency. No file outside the lane's ownership row was touched
(`pyproject.toml` still carries exactly the two allowed rows; `[tool.coverage.run]
source` is still untouched). Protected Core, `research/**`, `docs/evidence/**`
and `akc_native_parsers` remain unmodified — `akc_native_parsers` is now *read*
one level deeper (its source bytes are digested), never written.

## Repair gates

Every gate rerun from the worktree with the project interpreter
(`D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe` = `PY`).

### Repair gate 1 — `PY -m pytest packages/readers/tests -q -p no:randomly`

exit **0**

```
...........................................                              [100%]
43 passed in 6.52s
```

(32 before the repair, 43 after: 11 new failure-path tests.)

### Repair gate 2a — `PY -m ruff check packages/readers` / `packages` / `--extend-select RUF100`

exit **0** for all three.

```
All checks passed!
```

### Repair gate 2b — `PY -m mypy packages/readers`

exit **0**

```
Success: no issues found in 6 source files
```

### Repair gate 3 — `PY -m pytest tests/unit -q -p no:randomly`

exit **1** — the **same 7 pre-existing failures, the same node ids**, unchanged
by this repair. Nothing new failed; 1005 passed (was 1005).

```
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[stale-attribution-correction-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[question-set-v1-invalidation-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v6-acquisition-failure-diagnosis-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-acquisition-failure-2026-08-20.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-post-open-instrumentation.json]
FAILED tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate
FAILED tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data
7 failed, 1005 passed, 74 skipped in 244.48s (0:04:04)
```

The same `docs/repro/TEST_SCOPE_SELF_TEST.json` side effect appeared and was
reverted with `git checkout --` again; it is in neither commit.

### Repair gate 3b — `PY -m mypy packages services`

exit **1** — the same 2 pre-existing errors, neither in this lane's files.

```
packages\absorption\src\akc_absorption\synthetic_corruption.py:36: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
services\api\src\akc_api\collection_retrieval_api.py:413: error: Invalid index type "tuple[UUID | None, int | None]" for "dict[tuple[UUID, int], DocumentVersion]"; expected type "tuple[UUID, int]"  [index]
Found 2 errors in 2 files (checked 269 source files)
```

### Repair gate 4 — `git status` / push

Working tree clean after the repair commit except the intended files; the two
gates the first pass skipped are still skipped for the same reasons (the
coverage gate cannot move because `akc_readers` is deliberately outside
`[tool.coverage.run] source`; `tools/repro/run_test_scopes.py --scopes full`
runs `research/model_arena_20260903` paths this lane must not touch while the
Arena chain is live).

---

# Repair round 2 (2026-09-06, `REPAIR2_FINDINGS_2026-09-06.json` key `C`)

Two `blocker` and two `major` code findings, one `major` doc finding, and a list
of contradicted report claims. **Every one is accepted and fixed; none is
disputed.** I reproduced each before changing anything. Scope was not widened
beyond the findings, the statements the reviewer contradicted, and the two
rulings contract §8.1 addresses to this lane.

The four code fixes landed in **one commit**, not one per finding, because they
overlap inside `registry.py` (the same import block, the same `register()` loop
and the same `_verify_output()` call site); splitting them would have meant
fabricating a history in which each half compiled alone. The commit body names
all four. The doc and report corrections are a second commit.

## R2-1 — Probe witnessing was per capability, not per MIME pattern

*(blocker, `registry.py:225`; ruling §8.1 "C registration and read path")*

`register()` marked a capability `exercised` as soon as **one** probe sample
matched **any** of its patterns. A capability declaring
`("text/plain", "application/pdf")` with a single `probe.txt` therefore
registered, won `resolve()` for a real PDF, and produced an ACCEPTED §44 receipt
whose "native text" was the PDF's raw header bytes. The same hole let a
`mime_patterns=("*",)` capability declaring four source families be fully
qualified by one 18-byte `.txt`, after which `entries()` published all four in
`ReaderRegistryEntry.qualified_source_families` — a §22 field named *qualified*
filled from a declaration.

Fix: witnessing is now **per declared MIME pattern and per declared source
family**. Every pattern must be matched by at least one probe sample, every
family must be the inspected family of at least one sample, and only the samples
that matched a capability contribute features to it. `plain_text_v1` consequently
ships a second probe sample (`probe.md`) — before this, `text/markdown` was in
the shipped registry on the `.txt` sample's back, exactly the shape the finding
describes.

Recorded ceiling (doc, "Ceiling on globs"): a glob is still witnessed by whatever
sample matches it, so `*` plus one family is one sample away from that family's
MIME types. The declared *families* are what get checked one by one. Both shipped
providers declare concrete patterns only.

Tests: `test_a_mime_pattern_no_probe_sample_exercises_is_refused` (the reviewer's
folded two-MIME capability), `test_a_source_family_no_probe_sample_exercises_is_refused`
(the wildcard-over-four-families provider), `test_every_published_qualified_family_was_witnessed_by_a_probe`
and `test_plain_text_probes_every_mime_pattern_it_declares`.

## R2-2 — `_verify_output` never bound a locator to the source

*(blocker, `registry.py:556`; ruling §8.1)*

Locators were only **shape**-validated against the frozen schema. Nothing
compared a locator's `sourceVersionId` / `representationId` with the source being
read, its kind with the source's MIME, or its page with the source's pages — so
an accepted run could carry evidence pointing at another tenant's source version,
or a `pdf` locator with page 999,999 on a `text/plain` file that has no pages.

Fix: `_verify_locator_binding()` runs after schema validation on every locator an
accepted run carries, and at registration on every probe locator:

- ids not this source's → `RECEIPT_MISMATCH`;
- `locatorKind` not admissible for the inspected MIME → `EVIDENCE_BROKEN`. The
  table (`_ADMISSIBLE_LOCATOR_KINDS`) is fail-closed: a MIME absent from it
  admits **no** locator, which is why `plain_text_v1` emits none;
- `page` outside the inspected `page_like_units` → `EVIDENCE_BROKEN`.

Tests: `test_a_locator_naming_another_source_is_refused_and_strikes_semantically`,
`test_a_locator_kind_that_cannot_address_the_source_is_refused`,
`test_a_locator_page_outside_the_source_is_refused`.

Per §8.1, a run that binds to the wrong source is refused **and counted on a
separate semantic strike counter** (`SEMANTIC_FAILURE_CLASSES` →
`ReaderHealth.semantic_strikes`), never on the operational circuit breaker: a
wrong reader is not an unavailable worker, and `PROVIDER_UNAVAILABLE` would
misname the defect. Nothing acts on the counter — de-registration is manual in
P0, and the test asserts `circuit_open is False` after a strike.

## R2-3 — `read()` trusted the caller's inspection and never called `can_read()`

*(major, `registry.py:338`; ruling §8.1)*

The inspection was taken on trust: never re-derived from the bytes, never bound
to the source version, and `can_read()` was used only at registration. A forged
or stale inspection made the registry accept a source the inspector refuses, and
downgraded a security refusal to ordinary corruption — the string lane F consumes
as audit vocabulary (contract §4.6).

Fix: `read()` re-derives the inspection with `inspect_source(source)`. The
`inspection` keyword is now optional and is a **cross-check**: one that disagrees
with the bytes is refused `RECEIPT_MISMATCH` before any reader is called. The
resolved provider's own `can_read(source, inspection)` must then also say yes, or
the run is refused `UNSUPPORTED_FORMAT` — resolution matches a declaration,
`can_read` looks at these bytes, and both must agree.

Tests: `test_a_caller_inspection_that_disagrees_with_the_bytes_is_refused` (the
reviewer's `resume.docx`: honest inspection `corrupt=True`, forged one refused,
no inspection at all → `CORRUPT_SOURCE`), `test_a_provider_that_declines_the_source_at_can_read_is_refused`.

## R2-4 — A VERIFIED tier was accepted on any sha256-shaped string

*(major, `models.py:96`; ruling §8.1)*

`ReaderCapability` checked only that a VERIFIED tier carried *something*
sha256-shaped. Nothing checked the receipt exists, and the model carried no date
although contract §1 requires "a §27 qualification receipt (sha256 of a committed
receipt) **and a date**". A provider self-declaring `VERIFIED_NATIVE` with
`sha256:000…0` registered, and `resolve()` published `VERIFIED_NATIVE`,
outranking every honest `BEST_EFFORT` reader in `_STATUS_RANK`.

Fix: the tier now carries `qualification_receipt` + `qualification_receipt_path`
+ `qualified_at`, all three required for a VERIFIED status and refused for any
other status; `register()` resolves the path under **this repository**, refuses a
path that escapes it or does not exist, and re-digests the bytes. A model cannot
touch a disk, so the existence check is where the provider enters the registry.

This is a deliberate deviation from the §4.4 sketch's two-field
`ReaderCapability`, made because §8.1 requires "path + sha256 + date"; §8.1 is
newer than §4.4 and binding for this round. Nothing in the campaign consumes the
Python `ReaderCapability` shape yet (lane D derives manifest v1 from the live
site pipeline, §7 R-4), so no other lane is affected.

Tests: `test_a_verified_tier_needs_a_receipt_path_and_a_date_not_only_a_digest`,
`test_a_verified_tier_whose_receipt_is_not_committed_is_refused`,
`test_a_verified_tier_whose_receipt_digest_does_not_match_is_refused`, and
`test_a_verified_tier_backed_by_a_committed_file_registers` — the last one proves
the check is not vacuous by pointing at a real committed file
(`contract/enums.v1.json`) with its real digest. That file stands in for a §27
receipt in a test and **no qualification is claimed**; no receipt exists in this
repository and none was created.

## R2-5 — The doc claimed a guarantee the code did not make

*(major, `docs/architecture/reader-provider-plane.md:104`)*

"A capability no sample exercises is refused, so a feature witnessed on a `.txt`
can never qualify a PDF capability" was false for the folded-capability shape.
The registration section now describes per-pattern and per-family witnessing, the
locator binding, the `can_read` step, the qualification-receipt rule and the glob
ceiling. The sentence at :151-155 that gave the run-time check's reason ("locator
ids come from the caller's `sourceVersionId`/`representationId`, which
registration never sees") now sits above the comparison it names, which the
run-time check previously never made.

## Contradicted claims, corrected in place

| Claim | Where | Correction |
|---|---|---|
| stop-the-line escalation of the 7 `tests/unit` failures | §3 Gate 3 | **Struck** per §8.1. CRLF-vs-LF worktree artifact (5) + git-ignored corpus absent from worktrees (2); the same tests pass in the main checkout at the same commit. No evidence was overwritten. |
| "7 **pre-existing** failures" | §3 Gate 3 heading | Qualified: pre-existing only against this lane's own first pass in the same worktree, not against `main`. |
| "A capability no sample exercises is refused" | Repair §R3 | Marked superseded; true per pattern and per family since R2-1. |
| "No `VERIFIED_*` tier can exist anywhere in the product until a qualification receipt is produced and committed" | §6 question 4 | Rewritten: it is now true **of this registry** and enforced (R2-4); as written it described code that did not exist. |
| "this lane emits locators … validated against its own verbatim copy" (§5.5) and the §44 receipt table | §5, doc | Still true, and now stronger: validation is shape **plus** binding at both registration and run time. |

Everything else the reviewer checked and confirmed stands unchanged: both frozen
artifacts are byte-identical to `contract/` and match `SHA256SUMS`; the seven
enums equal the frozen value lists in order; `pyproject.toml` carries exactly the
two allowed rows with `[tool.coverage.run]` untouched; no Protected Core module,
`research/**`, `docs/evidence/**` or `packages/contracts/**` path is in the diff;
no barred phrase, no VERIFIED entry, no activation flag, no hand-typed preserved
list, no roadmap row; every commit carries both required trailers.

## Files changed in repair round 2

| Path | Change |
|---|---|
| `packages/readers/src/akc_readers/registry.py` | per-pattern/per-family witnessing; `_verify_qualification_receipt`; `_verify_locator_binding` (registration + run); `read()` re-derives the inspection and calls `can_read`; `SEMANTIC_FAILURE_CLASSES` and the strike counter |
| `packages/readers/src/akc_readers/models.py` | `ReaderCapability` receipt path + date; `ReaderHealth.semantic_strikes` |
| `packages/readers/src/akc_readers/providers.py` | `plain_text_v1` probes `text/markdown` as well as `text/plain` |
| `packages/readers/src/akc_readers/__init__.py` | exports `SEMANTIC_FAILURE_CLASSES` |
| `packages/readers/tests/test_reader_plane.py` | 13 new failure-path tests (43 → 56) |
| `docs/architecture/reader-provider-plane.md` | registration, run-verification, breaker/strike and tier sections corrected |
| `USKC_LANE_REPORT_C.md` | this section and the in-place corrections above |

No new dependency. No file outside the lane's §3 ownership row (plus this report,
written at the orchestrator's instruction) was touched. Nothing was enabled;
`research/model_arena_20260903/**` was neither read nor run.

## Repair round 2 gates

Every gate from the first report rerun from the worktree with the project
interpreter (`D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe` =
`PY`).

### R2 gate 1 — `PY -m pytest packages/readers/tests -q -p no:randomly`

exit **0**

```
........................................................                 [100%]
56 passed in 2.25s
```

(43 before this round, 56 after: 13 new failure-path tests.)

### R2 gate 2a — `PY -m ruff check packages/readers`, `packages`, and `--extend-select RUF100`

exit **0** for all three.

```
All checks passed!
```

### R2 gate 2b — `PY -m mypy packages/readers`

exit **0**

```
Success: no issues found in 6 source files
```

### R2 gate 3 — `PY -m pytest tests/unit -q -p no:randomly`

exit **1** — the **same 7 failures, the same node ids**, unchanged by this round;
1,005 passed (was 1,005), nothing new failed. They are the worktree artifacts
§8.1 withdrew as a stop-the-line, not a defect of this branch.

```
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[stale-attribution-correction-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[question-set-v1-invalidation-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v6-acquisition-failure-diagnosis-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-acquisition-failure-2026-08-20.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-post-open-instrumentation.json]
FAILED tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate
FAILED tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data
7 failed, 1005 passed, 74 skipped in 164.12s (0:02:44)
```

The `docs/repro/TEST_SCOPE_SELF_TEST.json` side effect appeared again and was
reverted with `git checkout --`; it is in no commit.

### R2 gate 3b — `PY -m mypy packages services` (the CI mypy scope)

exit **1** — the same 2 pre-existing errors, neither in this lane's files.

```
packages\absorption\src\akc_absorption\synthetic_corruption.py:36: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
services\api\src\akc_api\collection_retrieval_api.py:413: error: Invalid index type "tuple[UUID | None, int | None]" for "dict[tuple[UUID, int], DocumentVersion]"; expected type "tuple[UUID, int]"  [index]
Found 2 errors in 2 files (checked 269 source files)
```

### R2 gate 4 — `git status` / push

Working tree clean except the intended files. The two gates the earlier passes
skipped are skipped again for the same reasons (`akc_readers` is deliberately
outside `[tool.coverage.run] source` and this lane may not add a third
`pyproject.toml` row; `tools/repro/run_test_scopes.py --scopes full` runs
`research/model_arena_20260903` paths this lane must not touch while the Arena
chain is live).

Repair round 2 commits: `88878dd` (the four code findings + 13 tests) and the
doc/report commit that follows it, which is the branch tip and the pushed SHA
recorded at the top of this file. Production deploy 안 함. Core repo이므로
Preview deployment도 생성되지 않음.
