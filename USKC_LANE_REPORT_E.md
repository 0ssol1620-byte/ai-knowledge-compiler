# USKC P0 — Lane E report (EvidenceLocator v2)

Campaign `TAVONEL-USKC-P0-20260906-V1`. Contract: `D:\CodexProjects\uskc-lanes\USKC_LANE_CONTRACT_2026-09-06.md` §5 "E" / §4.5.
Worktree: `D:\CodexProjects\uskc-lanes\core-e-evidence-locator`. Base: core `research/source-faithful-kc-v1` = `d9db24c`.

## 1. Branch and pushed SHA

- Branch: `agent/uskc-e-evidence-locator`
- Pushed SHA: reported in the structured lane result; `git rev-parse origin/agent/uskc-e-evidence-locator` is authoritative (a commit cannot contain its own SHA). The three code/doc commits under it are `9055734`, `609de9c`, `409979d`.
- No PR, no merge, no deploy, no migration. Core repo — no Vercel preview is involved.

## 2. Files created / modified

Created:

| Path | What |
|---|---|
| `packages/contracts/schemas/evidence-locator.v2.schema.json` | Verbatim copy, sha256 `13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6` (matches `contract/SHA256SUMS`). |
| `packages/contracts/schemas/uskc-enums.v1.json` | Verbatim copy, sha256 `3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1` (matches `contract/SHA256SUMS`). |
| `packages/cir-python/src/akc_cir/evidence_locator.py` | 13-variant pydantic discriminated union, `LocatorKind`, `from_legacy`/`to_legacy`, `locator_anchor_id`, `parse_locator`, `EvidenceLocatorUnion`. |
| `packages/cir-python/src/akc_cir/evidence_locator_resolvers.py` | `FailureClass`, `Resolved`/`Unresolved`, `LocatorResolver` protocol, `PdfLocatorResolver`, `JsonLocatorResolver`, `XlsxLocatorResolver`, `resolve_locator`. |
| `tests/unit/test_evidence_locator.py` | 36 tests. |
| `tests/unit/test_evidence_locator_resolvers.py` | 37 tests. |
| `tests/fixtures/evidence_locator/{build_fixtures.py,sample.json,sample.xlsx,sample.pdf,corrupt.bin}` | Synthetic fixtures + reproducible builder (pinned zip mtimes, LF). |
| `docs/architecture/evidence-locator-v2.md` | Design, what the resolvers prove, what is deferred. |
| `USKC_LANE_REPORT_E.md` | This file. |

Row-only edits (exactly as the ownership row allows):

| Path | Edit |
|---|---|
| `packages/cir-python/src/akc_cir/schema.py` | Two lines: `from .evidence_locator import EvidenceLocatorUnion` and the `"evidence-locator": EvidenceLocatorUnion,` row in `SCHEMA_MODELS`. Nothing else. |
| `packages/contracts/src/generated-contracts.ts` | **Regenerated**, never hand-edited, by `scripts/generate_contract_types.py`. The generator itself was **not** edited — its `anyOf`/`oneOf` → TS union handling worked on a real discriminated union first time. The diff is additive only (+19 lines, one new namespace); every existing `SourceRef` shape in the file is byte-identical before and after (verified by diffing the file with the new namespace filtered out — no other line moved). |

Nothing outside the ownership row was committed. `docs/repro/TEST_SCOPE_SELF_TEST.json` is rewritten as a side effect of running `tests/unit` (see §7 F-4); it was reverted with `git checkout --` and is not in any commit. No Protected Core module was touched: `identity.py`, `semantic_diff.py`, `models.py` (`SourceRef`), `inspection.py`, `recovery_policy.py`, `reconciler.py`, `dependency.py`, `recompilation.py`, `world_state.py` are unchanged. `research/model_arena_20260903/**` was never read, imported, written or run.

## 3. Gates

Interpreter: `D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe` (the project interpreter, as §2 requires).

**Import resolution check.** `python -c "import akc_cir; print(akc_cir.__file__)"` from the worktree prints the **main checkout** path — the venv carries an editable install pointing at `D:\CodexProjects\ai-knowledge-compiler`. Under `pytest` run from the worktree, `pythonpath` in `pyproject.toml` wins and it prints
`D:\CodexProjects\uskc-lanes\core-e-evidence-locator\packages\cir-python\src\akc_cir\__init__.py` — verified with a throwaway test before trusting any run. For the two non-pytest commands (`scripts/generate_contract_types.py`) `PYTHONPATH` was set explicitly to the worktree's `packages/cir-python/src` and the worktree root; that is stated in the command below.

| # | Command (cwd = worktree) | Exit | Output tail |
|---|---|---|---|
| 1 | `python -m pytest tests/unit/test_evidence_locator.py tests/unit/test_evidence_locator_resolvers.py -q -p no:randomly` | **0** | `73 passed in 1.19s` |
| 2a | `python -m ruff check packages/cir-python/src/akc_cir/evidence_locator.py packages/cir-python/src/akc_cir/evidence_locator_resolvers.py packages/cir-python/src/akc_cir/schema.py tests/unit/test_evidence_locator.py tests/unit/test_evidence_locator_resolvers.py tests/fixtures/evidence_locator/build_fixtures.py` | **0** | `All checks passed!` |
| 2b | `python -m mypy packages/cir-python/src/akc_cir/` | **0** | `Success: no issues found in 43 source files` |
| 3 | `python -m pytest tests/unit -q -p no:randomly` | **1** | `8 failed, 1077 passed, 74 skipped in 163.23s (0:02:43)` — all 8 pre-existing, see below |
| 4 | `PYTHONPATH=<worktree>/packages/cir-python/src;<worktree> python scripts/generate_contract_types.py --check` | **0** | `generated contracts are current: packages\contracts\src\generated-contracts.ts, packages\contracts\schemas\collection-event.schema.json` |
| 5 | `packages/contracts $ tsc -p tsconfig.json --noEmit` | **0** | (no output) — run with the **main checkout's** `packages/contracts/node_modules/.bin/tsc` 5.9.3, because core worktrees have no `node_modules` (§2 installs them only for site lanes). `strict` + `exactOptionalPropertyTypes` + `noUncheckedIndexedAccess` all on. |
| 6 | `git status --porcelain` | **0** | clean except the intended commits |

Gates **not** run, with reasons:

- `pnpm lint` / `pnpm typecheck` / `pnpm --filter @akc/contracts build` (seam map's Lane E list): **skipped** — no `node_modules` in this worktree and installing them is a dependency action outside the lane. Gate 5 above covers the same compiler on the same tsconfig with the same TypeScript version.
- `npx vitest run lib/retrieval-units.test.ts` (seam map): **skipped** — that file is in the *site* repo and contract §7 R-5 makes Lane E core-only.
- `python -m uv run --locked --extra dev mypy packages services` (seam map): **skipped** in favour of the contract's §2 gate (`mypy <your package paths>`); `mypy` was run over the whole `akc_cir` package, which is the package this lane changes.

### The 8 failures in gate 3 — all pre-existing, none fixed (per §2 gate 3)

None of these import, or are imported by, anything this lane touched.

1–5. `tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes` × 5 (`stale-attribution-correction-2026-08-19.json`, `question-set-v1-invalidation-2026-08-19.json`, `v6-acquisition-failure-diagnosis-2026-08-19.json`, `v8-acquisition-failure-2026-08-20.json`, `v8-post-open-instrumentation.json`). Verbatim:

```
AssertionError: stale-attribution-correction-2026-08-19.json retracts a version of
structure-only-stale-diagnosis-2026-08-18.json that is not the one on disk.
    declared: sha256:ba444ddb6b2e479da706a3e723e11b21bb2c17c10e4f79fe2e4e104c58fc8ee7
    actual:   sha256:522d8a5cac38161634d098ed9e8dc86b7c54704157949be52f8b8ed291f2e056
  The retraction no longer applies to these bytes, so the retracted claim is live again.
```

These are **tracked** files (`git ls-files research/experiments/H1-B-REAL-REVISION-01/receipts/` lists them) at base commit `d9db24c`, the worktree is clean, and the mismatch is not a line-ending artifact (`.gitattributes` is `* text=auto eol=lf`; the file on disk is LF and hashes to `522d8a5…` either way). **This is an evidence-hash mismatch on the base branch, which `CLAUDE.md` lists under "Stop the line".** `research/experiments/**` is explicitly outside every lane's reach, so it is reported, not touched. Flagged for the orchestrator and the founder.

6. `tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate` — `AssertionError: expected at least one element-level binding on file / assert {}`. Working data that is not tracked and so does not exist in a fresh worktree.

7. `tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data` — `FileNotFoundError: …\research\experiments\H1-W6-SAME-INTELLIGENCE-01\corpus-v7\00253-9c6001a8c477\before.wikitext`. Confirmed: `corpus-v7` exists only in the main checkout as untracked working data, so no git worktree can have it. Worktree-provisioning artifact.

8. `tests/unit/test_run_test_scopes_receipt_safety.py::test_self_test_does_not_touch_the_canonical_receipt` — `UnicodeDecodeError: 'cp949' codec can't decode byte 0x80 in position 126` inside `tools/repro/run_test_scopes.py:131` (`text = proc.stdout + proc.stderr`, where `proc.stdout` is then `None`). Order/environment dependent: it **passed** in the first full run of this session and fails in later ones, and `python tools/repro/run_test_scopes.py --self-test` standalone exits 0 three times out of three. A cp949 console-decode fragility in the tool, not a product defect and not caused by this lane.

Coverage: this lane adds ~330 statements to `akc_cir` and 73 tests that exercise both modules including every failure branch; the CI `fail_under = 80` gate is over the whole coverage source list and was not run separately (no `--cov` gate is named in §2).

## 4. What the blueprint asked that I did NOT do, and why

- **§48 P0-E "UI serializer".** Not done. Contract §7 R-5 defers it: the seam map assigned `nextjs/lib/retrieval-units.ts`, which hashes the whole unit into `contentDigest`, so adding a field re-hashes every stored retrieval unit. Lane E is core-only. This is the one unmet P0-E checklist item and the doc says so.
- **Region-level PDF resolution.** The `pdf` resolver is page-bound, as contract §4.5 specifies ("structural + page-bound check"). Nothing in this tree extracts text for an arbitrary bbox, and producing one would be a fabricated excerpt. The doc states that `contentDigest` on a `pdf` locator therefore means "digest of the resolved page text".
- **Ten variants have no resolver** (`image`, `docx`, `pptx`, `email`, `xml`, `code`, `cad`, `media`, `database`, `api`). They are typed, schema-validated and round-trippable; `resolve_locator` returns `Unresolved(UNSUPPORTED_FORMAT)` naming the kind. Contract §5 E explicitly allows this and requires the doc to say it — it does.
- **`namedRange` / `tableId` / `chartId` xlsx anchors** resolve to `UNSUPPORTED_FORMAT` rather than to an adjacent cell.
- **No proposed diff against `semantic_preservation.py`.** Contract §5 E says to read it and, if the union would need a change there, to write the proposed diff in the doc instead of editing. **The file does not exist on this branch** (see §7 F-1), so no diff could be written honestly. `source_grounded_acceptance.py` — the nearest analogue that does exist, keyed on an opaque `source_region_ref: str` — is left untouched; rewiring it is §20 work.
- **No `evidence_locators` field added to any CIR model.** §12 lists `CanonicalSource.evidence_locators[]`, but adding it to `CanonicalKnowledgeObject`/`CanonicalDocument` would change hash preimages that `tests/unit/test_canonical_knowledge_model_v4.py` pins. Sibling type only, per §7 R-5 / seam-map O-2.

## 5. Conflicts with other lanes or with the contract (proposals, not edits)

- **`FailureClass` is now defined twice in the core.** Contract §4.4 gives it to Lane C (`akc_readers/enums.py`); contract §4.5 requires Lane E's `Unresolved.reason` to be a `FailureClass`. Lane C's package does not exist on this branch and Lane E must not depend on it, so I transliterated the frozen list into `akc_cir.evidence_locator_resolvers.FailureClass` with a test that it equals `packages/contracts/schemas/uskc-enums.v1.json`. **Proposal for integration:** keep both (each with the frozen-list test), or move the single definition into `akc_cir` and have `akc_readers` re-export it — `akc_readers` already sits above `akc_cir`, so that direction is safe; the reverse is not. Orchestrator's call, not mine.
- **`PdfLocator.to_legacy()` cannot have the signature §4.5 writes.** `SourceRef` requires `document_id`; the frozen locator schema has no field for it. Implemented as `to_legacy(*, document_id: str)`. **Proposed contract amendment:** change §4.5's signature line to `PdfLocator.to_legacy(*, document_id)` and record that the document→source alias lives on `Source`, not on the anchor.
- **§4.5 says the xlsx resolver is `zipfile` + `xml.etree`, "stdlib only".** I used `zipfile` + **`defusedxml`**. Reason: `ruff` selects `S`, and `xml.etree.ElementTree` parsing trips `S314`; more importantly a representation is hostile data and `akc_native_parsers.{security,xlsx_parser,docx_parser}` all already use `defusedxml`. **No dependency was added** — `defusedxml>=0.7,<1` and `pypdf>=6.15,<7` (used by the pdf resolver) are existing root dependencies of this repo, both already imported by `akc_native_parsers`/`akc_api`.
- **`akc_cir/__init__.py` is not in the ownership row, so the new names are not re-exported from the package root.** Consumers import `from akc_cir.evidence_locator import …`. If the orchestrator wants them at `akc_cir.*` like every other contract, that is a one-block edit to `__init__.py` at integration.
- **X-7 respected:** this lane is the only one that regenerated `generated-contracts.ts`. Lane C must not register schema models until this lands.

## 6. Open questions for the founder

1. **Two anchor-id algorithms now exist** — `identity.evidence_id()` (page-based, Protected Core) and `locator_anchor_id()` (path-based, new). A source that has both a page-like unit and a native object id needs one canonical convention *before* anything indexes on either, or identity collisions become a real bug class. Which is authoritative, and when?
2. **Is `sourceVersionId == document_version_id` permanent or interim?** This lane implements it as the interim identity alias (contract §7 R-8). Reversing it later is a data migration.
3. **Does an evidence excerpt get stored at all?** `Resolved.excerpt` is capped at the schema's 2,000 characters while `Resolved.digest` covers the whole resolved unit. If excerpts are ever persisted or shown, whether a 2,000-character slice of customer content may be stored is a privacy decision, not an engineering one.
4. **The `pdf` locator resolves to a page, not to a box.** The site currently says "Exact bbox" / "evidence back to the page" (`home-page-client.tsx`, pinned by `brand-copy.test.ts`). Blueprint §30.2 wants "exact source location" generalised per source. Nothing in this lane changes copy, but the copy and the capability should be reconciled before either is published as a claim.
5. **The base branch has a live evidence-hash mismatch** (gate 3 failures 1–5). CLAUDE.md classes that as stop-the-line. Who owns fixing `research/experiments/H1-B-REAL-REVISION-01/receipts/`?

## 7. Contradictions found (blueprint / contract / seam map vs. disk)

- **F-1 — `packages/cir-python/src/akc_cir/semantic_preservation.py` does not exist.** Contract §5 "E" names it in the reading list ("read only — its invariant list is what a locator must be able to answer"). On `research/source-faithful-kc-v1` it is absent; contract §0.2 itself says it lives on `agent/tavonel-vkc-research`, which no lane may touch. The seam map's Lane E risk list already said this (`P0_SEAM_MAP_2026-09-06.md:375`). The contract's §5 reading list was not updated to match its own §0.
- **F-2 — Seam-map Lane E "Exposes" block is not what the frozen schema says.** `P0_SEAM_MAP_2026-09-06.md:330-351` proposes `@dataclass(frozen=True) BaseEvidenceLocator` with `content_digest`, `source_ref_to_pdf_locator()`, `pdf_locator_to_source_ref()` and `resolve_locator(loc) -> ResolvedAnchor` returning `(evidence_id, page_number1, anchor)`. The contract §4.5 (which wins) specifies pydantic camelCase models, `from_legacy`/`to_legacy`, and `resolve_locator` returning `Resolved | Unresolved`. Implemented per the contract; recording the divergence as §7 requires.
- **F-3 — Seam-map C-5 confirmed on disk.** "No code anywhere resolves a locator against stored bytes" was true: `grep` finds only structural validation (`page_index0 + 1 == page_number1` in `models.py:83`, bbox ordering in `models.py:20`). §20 invariant #1 was unimplemented, not untested. This lane implements it for three kinds on synthetic fixtures — which is a prototype, not a proof, and the doc says so.
- **F-4 — Running `tests/unit` mutates a tracked file.** `docs/repro/TEST_SCOPE_SELF_TEST.json` is rewritten by the suite. In a git worktree it additionally records `"is_project_interpreter": false, "project_interpreter": null, "project_venv_present": false` because the guard resolves `.venv` relative to the repo root and a worktree has no `.venv` — even when the run *is* using the project interpreter (`running_interpreter` shows it). Any lane that runs gate 3 in a worktree and commits carelessly will commit a false "wrong interpreter" record. I reverted it. The guard's venv probe should follow `sys.executable`, not the repo root.
- **F-5 — `packages/contracts/src/index.ts` hand-writes `SourceRef`, `CanonicalDocument` etc. in parallel with the generated file.** Contract §5 E asked whether `generated-contracts.ts` is generated or hand-written; the answer is *both files exist*: `generated-contracts.ts` is generated and re-exported by `index.ts`, which then hand-writes a second, differently-shaped set of the same concepts (`SourceRef` is hand-written there, not generated). The hand-written `SourceRef` is unchanged by this lane. Two sources of truth for one wire type is a latent drift hazard; not this lane's to fix.
- **F-6 — The frozen schema has no `additionalProperties: false`,** so a payload with an unknown field validates against it while the pydantic model rejects it. Tested and documented. If the contract intends the schema to be the strict boundary, it needs that keyword; proposing, not editing.

## 8. Definition-of-done self-check

Code exists · tests and **failure paths** pass (73 tests; every `Unresolved` branch, the corrupt/encrypted/missing/mismatched cases, and the "wrong variant handed to a resolver" case are all covered) · ruff and mypy clean · TS regenerated and type-checks · doc written and names what is missing · nothing enabled, nothing deployed, no Protected Core touched, no dependency added. **This session does not approve its own result** — independent review is the orchestrator's step.

## 9. Push

`git push -u origin agent/uskc-e-evidence-locator` — pushed.
Production deploy 안 함. Git push로 Preview deployment는 자동 생성됨 — 단, 이 레인은 core repo라 Preview 대상이 아님.

---

## 10. Repair pass (2026-09-06, after adversarial review)

Two reviewers returned four confirmed correctness findings and two confirmed
honesty findings. All six are fixed, each with the failure-path test that would
have caught it. No finding was disputed. Scope was not widened: the same two
modules, their two test files and the lane doc.

### R-E-1 (blocker) — hostile xlsx bytes escaped as `NotImplementedError`

`evidence_locator_resolvers.py:367` guarded the `zipfile.ZipFile` open with
`except zipfile.BadZipFile` only. CPython's `zipfile` raises
`NotImplementedError` from `_RealGetContents` when a central-directory entry's
"version needed to extract" exceeds 63 — a **two-byte** edit of an otherwise
well-formed archive — and `RuntimeError` for an encrypted member. Neither is
`BadZipFile`, so both crashed out of `resolve_locator` instead of returning
`Unresolved`. That breaks contract section 1 "fail closed ... never a crash" and
CLAUDE.md "every document is hostile data".

Fix: the `except _XlsxError` handler now comes first, followed by a broad
`except Exception` mapping the whole family to
`Unresolved(CORRUPT_SOURCE, "xlsx is not a readable package: <ExceptionType>")`.
Root-cause placement: one guard around the archive open covers every part read
inside the `with`, rather than one guard per call site.

Test: `test_xlsx_with_an_unsupported_zip_version_is_refused_not_a_crash` takes
the committed `sample.xlsx`, sets `blob[rindex(b"PK\x01\x02") + 6] = 99`, and
asserts `CORRUPT_SOURCE` with `NotImplementedError` named in the detail. It
fails against the old code with a traceback, which is the point.

### R-E-2 (major) — an empty anchor resolved to the digest of the empty string

`_resolved()` digested whatever it was handed, so a blank PDF page or an empty
cell returned `Resolved(excerpt="", digest=sha256(""))`. That digest is
identical for every empty page of every document, so a `contentDigest` receipt
taken from one blank page **verified** against another — evidence that proves
nothing, in exactly the case that dominates the product's own corpus
(image-only scans, where `extract_text()` is `""` for every page). The frozen
`FailureClass.EMPTY_OUTPUT` existed and was never used.

Fix: `_resolved(text, anchor)` returns `Unresolved(EMPTY_OUTPUT, ...)` when the
resolved text is empty. One change, all four call sites (pdf page, json
pointer, xlsx cell, xlsx range); each passes the anchor description so the
detail names what was empty. An **absent** cell stays `EVIDENCE_BROKEN` —
absent and empty are different facts.

Tests: `test_a_page_with_no_extractable_text_is_empty_output_not_a_digest_of_nothing`
(two blank pages, plus the borrowed-receipt case: page 2 carrying page 1's
`sha256("")` digest is refused, where before it resolved) and
`test_a_cell_that_holds_an_empty_string_is_empty_output` (parametrized over
`cell` and a 1x1 `range`, asserting the same workbook still resolves a
populated cell).

### R-E-3 (major) — `from_legacy` silently dropped three `SourceRef` fields

`image_asset_id`, `time_start_ms` and `time_end_ms` were dropped, so
`to_legacy()` did **not** return the input for figure or media evidence, and
two `SourceRef`s differing only in those fields collapsed to one
`locator_anchor_id`. The `pdf` variant has nowhere to keep them, so a lossless
mapping is impossible — but silently losing evidence is not the fail-closed
reading of that. This is live shape, not synthetic: `pdf_parser.py:327-335`
emits `bbox1000` and `image_asset_id` together on every FIGURE block, and
`docx_parser.py` / `pptx_parser.py` / `xlsx_parser.py` do the same.

Fix: `from_legacy` refuses such a `SourceRef` with a `ValueError` naming the
exact fields, matching the existing box-less refusal. **The honest consequence,
now stated in the doc and in the acceptance table: figure and media evidence
has no v2 locator today.** Giving it one means dispatching to the `image` /
`media` variants (which do carry `imageId` / `startMs` / `endMs`), listed under
"What is deferred".

Test: `test_a_source_ref_the_pdf_variant_cannot_carry_is_refused_not_silently_dropped`,
parametrized over `image_asset_id` and the time pair (`SourceRef` itself
requires the pair, so it is set as a pair).

### R-E-4 (major) — a caller-supplied `locator_id` bypassed validation

`from_legacy` wrote the caller's id through `model_copy(update=...)`, which is
documented pydantic behaviour to skip validation. `"  ../../etc/passwd  "`,
`"<script>"` and `"x" * 400` were all stored verbatim on a "validated" frozen
contract object that the frozen schema then rejects and `parse_locator` cannot
re-parse.

Fix: the locator is **rebuilt** through `PdfLocator(**fields)` with the final
id, so `LocatorIdentifier` and `str_strip_whitespace` apply. `locator_id=None`
still means "derive the anchor id"; `locator_id=""` is now rejected rather than
silently replaced.

Test: `test_a_caller_supplied_locator_id_is_validated_not_written_through`,
parametrized over the reviewer's three values plus `""` and `"loc bad"`.

### R-E-5 (major) — the default serialization failed the frozen schema

`ContractModel`'s `ConfigDict` has no `exclude_none`; it lives only inside
`canonical_json`. So `locator.model_dump_json()` emitted
`"contentDigest": null` and failed the frozen schema's `oneOf` **entirely**.
Both of the lane's existing dump assertions passed `exclude_none=True`
explicitly, so the green suite never touched the path a consumer would take.
This is a cross-lane hazard: contract section 4.4 has lane C validate locator
dicts against this same file with `jsonschema`.

Fix: `BaseEvidenceLocator` overrides `model_dump` / `model_dump_json` to
default `exclude_none=True`; `EvidenceLocatorUnion` delegates to its root.
Deliberately **not** a `model_serializer(mode="wrap")`: probed, and a wrap
serializer collapses `model_json_schema(mode="serialization")` to
`{"type": "object", "additionalProperties": true}` — and that schema is what
generates the TypeScript union, so it would have silently destroyed
`generated-contracts.ts`. `base.py` is outside the ownership row and was not
touched.

Test: `test_the_default_serialization_validates_against_the_frozen_schema`
validates all 13 variants through `model_dump_json()`,
`model_dump(mode="json")` and the union wrapper, and asserts that an explicit
`exclude_none=False` still produces the payload the schema refuses (the default
is a default, not a lock).

### R-E-6 (major, honesty) — three doc over-claims corrected

`docs/architecture/evidence-locator-v2.md` now says:

- "The adapter round-trips losslessly **or refuses**; it never round-trips
  lossily" — replacing "The adapter is a pure round-trip", with the
  figure/media consequence spelled out and added to the deferred list and the
  P0-E acceptance table.
- The `null` asymmetry is **two** asymmetries, and the Python side is named:
  input accepts an explicit `null` the schema rejects, and the wire is
  null-free only because of the `model_dump` override, not because
  `ContractModel` sets `exclude_none`.
- The xlsx guard paragraph names the `NotImplementedError` / `RuntimeError`
  family, not just `BadZipFile`.

### Reviewer statements I accept but did not change code for

- **Gate 3 count.** My first report recorded `8 failed, 1077 passed`; one
  reviewer's rerun produced `7 failed, 1078 passed`. This repair pass's rerun
  produced `8 failed, 1089 passed, 74 skipped` — the same eight, including the
  cp949 `test_run_test_scopes_receipt_safety`, which my report already flagged
  as order-dependent. The set is stable; that one member is not. Nothing here
  is fixable in this lane, and gate 3 instructs me not to fix pre-existing
  failures. (Pass count rose 1077 -> 1089 because this pass adds 12 tests.)
- **Coverage.** My `not_done` said "no `--cov` gate is named in contract
  section 2". That was wrong: gate 3 names `fail_under = 80` over `akc_cir` and
  calls Lane E out by name. Measured and now reported as gate 4 below: **94%**
  over the two new modules. The requirement is met; the report line was not.

### Gates rerun (all of them, this pass)

| # | Command | Exit | Tail |
|---|---|---|---|
| 1 | `PY -m pytest tests/unit/test_evidence_locator.py tests/unit/test_evidence_locator_resolvers.py -q -p no:randomly` | 0 | `85 passed in 1.29s` (was 73) |
| 2a | `PY -m ruff check <lane files>` | 0 | `All checks passed!` |
| 2b | `PY -m mypy packages/cir-python/src/akc_cir/` | 0 | `Success: no issues found in 43 source files` |
| 3 | `PY -m pytest tests/unit -q -p no:randomly` | 1 | `8 failed, 1089 passed, 74 skipped in 130.73s` — the same pre-existing eight documented in section 4; none imports or is imported by anything this lane touches |
| 4 | `PY -m pytest <lane tests> --cov=akc_cir.evidence_locator --cov=akc_cir.evidence_locator_resolvers` | 0 | `Required test coverage of 80.0% reached. Total coverage: 93.96%` (locator 98%, resolvers 92%) |
| 5 | `PYTHONPATH=<worktree src>;<worktree> PY scripts/generate_contract_types.py --check` | 0 | `generated contracts are current` — the `model_dump` override does not move the generated TS, which was the whole reason for choosing it over a serializer |
| 6 | `tsc -p packages/contracts/tsconfig.json --noEmit` (main checkout's pinned typescript 5.9.3 on this worktree's tsconfig; core worktrees have no `node_modules`) | 0 | (no output) |
| 7 | `git status --porcelain` | 0 | only the five intended files; `docs/repro/TEST_SCOPE_SELF_TEST.json` was not mutated on this run |

Interpreter note, unchanged from the first pass: a bare
`python -c "import akc_cir"` resolves to the **main checkout**, but `pytest`
uses the worktree because `pyproject.toml:111` sets `pythonpath`. The generator
is the one command that needs `PYTHONPATH` set explicitly, and gate 5 above
sets it.

Nothing enabled, nothing deployed, no PR, no merge, no migration, no dependency
added, no Protected Core module touched, `research/model_arena_20260903`
untouched. This session still does not approve its own result.
