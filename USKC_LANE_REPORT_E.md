# USKC P0 — Lane E report (EvidenceLocator v2)

Campaign `TAVONEL-USKC-P0-20260906-V1`. Contract: `D:\CodexProjects\uskc-lanes\USKC_LANE_CONTRACT_2026-09-06.md` §5 "E" / §4.5.
Worktree: `D:\CodexProjects\uskc-lanes\core-e-evidence-locator`. Base: core `research/source-faithful-kc-v1` = `d9db24c`.

## 1. Branch and pushed SHA

- Branch: `agent/uskc-e-evidence-locator`
- Pushed SHA: reported in the structured lane result; `git rev-parse origin/agent/uskc-e-evidence-locator` is authoritative (a commit cannot contain its own SHA). **Corrected in repair round 2:** this line said "the three code/doc commits under it are `9055734`, `609de9c`, `409979d`", which was already stale when it was pushed — the first repair pass added `4d389b3` and `768060b`. `git log --oneline d9db24c..HEAD` is the authoritative list; repair round 2 adds `db1bf88`, `83d1c26`, `50ab5f4` and the commit carrying this correction.
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
| `packages/contracts/src/generated-contracts.ts` | **Regenerated**, never hand-edited, by `scripts/generate_contract_types.py`. The generator itself was **not** edited — its `anyOf`/`oneOf` → TS union handling worked on a real discriminated union first time. The diff is additive only (**21 lines added, 0 removed** — `git diff d9db24c..HEAD --numstat`; the first pass said "+19" and was wrong), one new namespace; every existing `SourceRef` shape in the file is byte-identical before and after (verified by diffing the file with the new namespace filtered out — no other line moved). |

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

**STRUCK in repair round 2 — the diagnosis was wrong and the escalation is withdrawn.** The first pass called this an evidence-hash mismatch on the base branch and escalated it under `CLAUDE.md` "Stop the line". Contract §8.1 ("Withdrawn stop-the-line") closes it: the failures are a CRLF-vs-LF working-tree artifact plus git-ignored corpus files absent from a fresh worktree, and the same tests pass on the main checkout at the same commit (orchestrator: 1017 passed, 1 env-dependent tooling failure). **No evidence was overwritten and nothing here is stop-the-line.** The remedy, if any, belongs to the integrator: an `eol=lf` attribute for the receipt paths, and only if the committed blobs are LF and a fresh worktree then hashes identically. See §11.1.

6. `tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate` — `AssertionError: expected at least one element-level binding on file / assert {}`. Working data that is not tracked and so does not exist in a fresh worktree.

7. `tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data` — `FileNotFoundError: …\research\experiments\H1-W6-SAME-INTELLIGENCE-01\corpus-v7\00253-9c6001a8c477\before.wikitext`. Confirmed: `corpus-v7` exists only in the main checkout as untracked working data, so no git worktree can have it. Worktree-provisioning artifact.

8. `tests/unit/test_run_test_scopes_receipt_safety.py::test_self_test_does_not_touch_the_canonical_receipt` — `UnicodeDecodeError: 'cp949' codec can't decode byte 0x80 in position 126` inside `tools/repro/run_test_scopes.py:131` (`text = proc.stdout + proc.stderr`, where `proc.stdout` is then `None`). Order/environment dependent: it **passed** in the first full run of this session and fails in later ones, and `python tools/repro/run_test_scopes.py --self-test` standalone exits 0 three times out of three. A cp949 console-decode fragility in the tool, not a product defect and not caused by this lane.

Coverage: ~~this lane adds ~330 statements to `akc_cir` and 73 tests that exercise both modules including every failure branch; the CI `fail_under = 80` gate is over the whole coverage source list and was not run separately (no `--cov` gate is named in §2)~~. **Corrected twice.** §2 gate 3 does name `fail_under = 80` over `akc_cir`, and "every failure branch" was not true. Measured in repair round 2: 443 statements, 94 branches, **98 tests, 100% statement and branch coverage, no missing lines** (§11.3 gate 4).

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
5. ~~**The base branch has a live evidence-hash mismatch** (gate 3 failures 1–5). CLAUDE.md classes that as stop-the-line. Who owns fixing `research/experiments/H1-B-REAL-REVISION-01/receipts/`?~~ **Withdrawn in repair round 2.** Contract §8.1 answers it: a CRLF-vs-LF worktree artifact, not an evidence mismatch, and not a founder question. Nothing to escalate.

## 7. Contradictions found (blueprint / contract / seam map vs. disk)

- **F-1 — `packages/cir-python/src/akc_cir/semantic_preservation.py` does not exist.** Contract §5 "E" names it in the reading list ("read only — its invariant list is what a locator must be able to answer"). On `research/source-faithful-kc-v1` it is absent; contract §0.2 itself says it lives on `agent/tavonel-vkc-research`, which no lane may touch. The seam map's Lane E risk list already said this (`P0_SEAM_MAP_2026-09-06.md:375`). The contract's §5 reading list was not updated to match its own §0.
- **F-2 — Seam-map Lane E "Exposes" block is not what the frozen schema says.** `P0_SEAM_MAP_2026-09-06.md:330-351` proposes `@dataclass(frozen=True) BaseEvidenceLocator` with `content_digest`, `source_ref_to_pdf_locator()`, `pdf_locator_to_source_ref()` and `resolve_locator(loc) -> ResolvedAnchor` returning `(evidence_id, page_number1, anchor)`. The contract §4.5 (which wins) specifies pydantic camelCase models, `from_legacy`/`to_legacy`, and `resolve_locator` returning `Resolved | Unresolved`. Implemented per the contract; recording the divergence as §7 requires.
- **F-3 — Seam-map C-5 confirmed on disk.** "No code anywhere resolves a locator against stored bytes" was true: `grep` finds only structural validation (`page_index0 + 1 == page_number1` in `models.py:83`, bbox ordering in `models.py:20`). §20 invariant #1 was unimplemented, not untested. This lane implements it for three kinds on synthetic fixtures — which is a prototype, not a proof, and the doc says so.
- **F-4 — Running `tests/unit` mutates a tracked file.** `docs/repro/TEST_SCOPE_SELF_TEST.json` is rewritten by the suite. In a git worktree it additionally records `"is_project_interpreter": false, "project_interpreter": null, "project_venv_present": false` because the guard resolves `.venv` relative to the repo root and a worktree has no `.venv` — even when the run *is* using the project interpreter (`running_interpreter` shows it). Any lane that runs gate 3 in a worktree and commits carelessly will commit a false "wrong interpreter" record. I reverted it. The guard's venv probe should follow `sys.executable`, not the repo root.
- **F-5 — `packages/contracts/src/index.ts` hand-writes `SourceRef`, `CanonicalDocument` etc. in parallel with the generated file.** Contract §5 E asked whether `generated-contracts.ts` is generated or hand-written; the answer is *both files exist*: `generated-contracts.ts` is generated and re-exported by `index.ts`, which then hand-writes a second, differently-shaped set of the same concepts (`SourceRef` is hand-written there, not generated). The hand-written `SourceRef` is unchanged by this lane. Two sources of truth for one wire type is a latent drift hazard; not this lane's to fix.
- **F-6 — The frozen schema has no `additionalProperties: false`,** so a payload with an unknown field validates against it while the pydantic model rejects it. Tested and documented. If the contract intends the schema to be the strict boundary, it needs that keyword; proposing, not editing.

## 8. Definition-of-done self-check

**This paragraph was false as first written and is corrected here, not only in the appendix.** It claimed "73 tests; every `Unresolved` branch … are all covered". At the time it was written the suite was 85 tests and four `Unresolved`-producing branches had no test at all. Repair round 2 closed them; the claim is now measured rather than asserted.

Code exists · tests and **failure paths** pass — **98 tests**, and **100% statement and branch coverage** over `akc_cir.evidence_locator` and `akc_cir.evidence_locator_resolvers` (gate 4 in §11.3, `--cov-report=term-missing` with no missing lines), so every `Unresolved` branch, the corrupt/encrypted/missing/mismatched cases and the "wrong variant handed to a resolver" case are covered, and the claim can be re-measured in one command · ruff and mypy clean · TS regenerated and type-checks · doc written and names what is missing · nothing enabled, nothing deployed, no Protected Core touched, no dependency added. Coverage is not proof: it says every branch ran once on committed synthetic fixtures, not that the thresholds or the fixtures are right. **This session does not approve its own result** — independent review is the orchestrator's step.

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

---

## 11. Repair round 2 (2026-09-06, after `REPAIR2_FINDINGS_2026-09-06.json`)

Two correctness findings (one blocker, one major) and one honesty finding, plus
five report-claim contradictions. **All were confirmed on disk; none is
disputed.** Every fix follows the ruling in contract §8.1 ("E resolvers"), and
each comes with the failure-path test that would have caught it. Scope was not
widened: the same two modules, their two test files, the lane doc and this
report.

### 11.1 The stop-the-line escalation is struck

Contract §8.1 "Withdrawn stop-the-line" is binding and this lane obeys it. The
first pass reported the five `test_superseded_receipt_contract` failures as an
evidence-hash mismatch on the base branch and escalated it to the founder under
`CLAUDE.md` "Stop the line". That diagnosis was wrong. The failures are a
CRLF-vs-LF working-tree artifact plus git-ignored corpus files that no fresh
worktree can have; the same tests pass on the main checkout at the same commit
(orchestrator: 1017 passed, 1 env-dependent tooling failure). **No evidence was
overwritten. Nothing here is stop-the-line, and there is no founder question.**
The escalation is struck at both places it appeared — §3 (the gate-3 narrative)
and §6 question 5 — not softened and not left standing with a footnote. Any
remedy is the integrator's `eol=lf` attribute for the receipt paths, and only if
the committed blobs are LF and a fresh worktree then hashes identically.

I should have checked the main checkout before publishing an alarm. That is the
lesson, and it is recorded rather than explained away.

### 11.2 The findings

**R2-E-1 (blocker) — `evidence_locator_resolvers.py:376`: the xlsx resolver was
the one door that accepted a package every other door refuses.**
Reproduced exactly as reported. Taking the committed `sample.xlsx`, appending a
second `xl/workbook.xml` (declaring a sheet `Payroll`), a second
`xl/_rels/workbook.xml.rels` and an `xl/worksheets/shadow.xml` whose A1 is the
inline string `ATTACKER SUPPLIED`:

```
resolve_locator(xlsx sheet='Payroll' cell='A1', tampered)
  -> Resolved(excerpt='ATTACKER SUPPLIED', digest='sha256:c3d2bf43…')
resolve_locator(xlsx sheet='Revenue' cell='A1', tampered)   # the real sheet
  -> Unresolved(EVIDENCE_BROKEN, "workbook has no sheet named 'Revenue'")
validate_source(tampered)  -> StructuredParseError ARCHIVE_DUPLICATE_ENTRY
```

`zipfile` resolves a duplicate name to whichever entry the central directory
lists last, so the attacker's shadow workbook decided which sheets existed and
where they lived, and the resolver handed back a `Resolved` excerpt and digest
for content that is in no sheet a viewer or the product's own parser would ever
open.

Fixed per §8.1: `XlsxLocatorResolver.resolve` now calls the repo's existing
`akc_native_parsers.security.validate_source` before a single part is read —
duplicate part names, path traversal, encrypted and symlink members, entry
count, uncompressed size, compression ratio, active content, external
relationships and the OOXML package shape. `StructuredParseError.code` is a
stable, body-free vocabulary, so it maps to a `FailureClass`
(`ARCHIVE_ENCRYPTED_ENTRY` → `ENCRYPTED_SOURCE`; active content or an
embedded/external object → `MALWARE_QUARANTINED`; everything else →
`CORRUPT_SOURCE`) with the code carried in the detail. The call sits inside the
existing `try`, so the broad handler still covers the
`NotImplementedError`/`RuntimeError` family `zipfile` raises *before*
`validate_source` can classify it (the R-E-1 case from the first repair pass
still passes).

*Root-cause placement:* one guard at the archive open, not one per part read.
`_read_part`, `_parse_part`, `_sheet_part`, `_shared_strings` and `_sheet_cells`
all sit inside that `with`, so they all inherit it.

Tests: `test_a_shadow_workbook_part_cannot_supply_evidence` (both the attacker's
sheet *and* the genuine one are refused, with `ARCHIVE_DUPLICATE_ENTRY` named in
the detail) and
`test_an_encrypted_package_member_is_encrypted_source_not_corruption`. The two
package-shape tests that previously built a bare zip now build a package the
guards accept, because what they test is the resolver's behaviour on a
well-formed package — the helper `_ooxml_package` says so in its docstring.

*Consequence recorded, not hidden:* the resolver now refuses any workbook the
product's own upload path would refuse. That is the intent, but it does mean a
package that a spreadsheet application would open and this validator would not
now resolves to `Unresolved(CORRUPT_SOURCE)` rather than to evidence. Failing
closed is the contract; if a real corpus later shows honest workbooks being
refused, that is a `validate_source` calibration question, not a reason to put
the bare `zipfile` back.

**R2-E-2 (major) — `evidence_locator_resolvers.py:111`: whitespace resolved.**
Reproduced. Two structurally different single-page PDFs whose only content
stream is `BT /F1 12 Tf 10 100 Td ( ) Tj ET` and
`BT /F1 24 Tf 50 50 Td ( ) Tj ET` both extract to `' '` and both resolved to
`sha256(' ')` = `36a9e7f1…`, so a `contentDigest` taken from one verified
against the other. `if not text` was the wrong emptiness test.

Fixed per §8.1 ("`EMPTY_OUTPUT` covers whitespace-only content"):
`_resolved` now tests `text.strip()`. One change in the one shared helper, so
all four call sites (pdf page, json pointer, xlsx cell, xlsx range) move
together. The digest still covers the text as read — stripping decides
emptiness, it does not normalise the evidence.

Tests: `test_a_page_whose_only_text_is_whitespace_is_empty_output` (the two
PDFs above, plus the borrowed `sha256(" ")` receipt refused against the second)
and `test_a_cell_that_holds_only_whitespace_is_empty_output`, parametrized over
`cell` and a 1×1 `range`, with the same workbook still resolving a populated
numeric cell and an inline-string cell.

**R2-E-3 (major, honesty) — `USKC_LANE_REPORT_E.md:121`: the coverage claim.**
Confirmed false on both halves. §8 said "73 tests; every `Unresolved` branch …
are all covered"; the suite was 85 tests, and four branches that return
`Unresolved` had no test —
`evidence_locator_resolvers.py:150-151` and `:161-162` (`CORRUPT_SOURCE` when
`pypdf` fails after the reader opens), `:249` (the 8 MiB part-size cap) and
`:283` (a sheet the workbook relationships do not name). §10 had corrected the
test count and left the coverage claim standing, which is the worse half of the
error.

Fixed in two places. The claim itself: §8 now carries the retraction inline and
states a **measured** number — 98 tests, 100% statement and branch coverage over
both modules — instead of an asserted one. And the branches: all four now have a
test, along with the `_range_references` A1 guard (unreachable through
`resolve_locator` because `A1Range` pins the same pattern, so it is tested where
it lives and its docstring says why it stays), every shape `_cell_text` gives up
on, the boolean cell that does resolve and had no test at all, the pptx anchor
refusal, the media span that ends before it starts (which the frozen schema
cannot express — only the model refuses it, which is §7 F-6 in miniature) and
the union wrapper's `model_dump`.

Two of the new tests inject a fault rather than fabricate a fixture: a fake
`PdfReader` that constructs and then raises (pypdf fails lazily, and the branch
under test is our mapping of that failure), and `monkeypatch` on the part-size
cap rather than an 8 MiB workbook in git. Both exercise the real branch, and
each docstring says which knob was turned and why. Neither invents data.

### 11.3 Report claims the reviewer contradicted — every one accepted

| Claim as published | Verdict | Where it is corrected |
|---|---|---|
| §8: "73 tests; every `Unresolved` branch … all covered" | **False**, both halves | §8 rewritten with a measured figure; §11.2 R2-E-3 |
| §2: "The diff is additive only (+19 lines…)" | Number **wrong** — `git diff d9db24c..HEAD --numstat` says 21 added, 0 removed. The additive-only and `SourceRef`-byte-identical halves are correct | §2 row corrected in place |
| §1: "The three code/doc commits … `9055734`, `609de9c`, `409979d`" | **Incomplete** — six commits on the branch at that point; `4d389b3` and `768060b` were missing | §1 corrected; `git log --oneline d9db24c..HEAD` named as authoritative |
| Structured gate 9 tail: "the six intended files are committed" | **Wrong count** — `git diff d9db24c..HEAD --name-status` is 13 added, 2 modified. The §2 file table itself was accurate | Corrected here and in this pass's structured result |
| Structured gate 4: "8 failed, 1089 passed" vs the reviewer's 7 | **Not a contradiction of substance**, and the reviewer says so. This pass reproduces the reviewer's number exactly: 7 failed, 1103 passed, 74 skipped. The differing member is `test_run_test_scopes_receipt_safety`, which the first report already flagged as order-dependent; it did not recur here | §11.4 gate 3 |

Nothing in the findings list was disputed. Every reviewer statement I checked
held.

### 11.4 Gates rerun — all of them, this pass

Interpreter `PY` = `D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe`, cwd = worktree.

| # | Command | Exit | Output tail |
|---|---|---|---|
| 1 | `PY -m pytest tests/unit/test_evidence_locator.py tests/unit/test_evidence_locator_resolvers.py -q -p no:randomly` | **0** | `98 passed in 3.24s` |
| 2a | `PY -m ruff check packages/cir-python/src/akc_cir/evidence_locator.py packages/cir-python/src/akc_cir/evidence_locator_resolvers.py packages/cir-python/src/akc_cir/schema.py tests/unit/test_evidence_locator.py tests/unit/test_evidence_locator_resolvers.py tests/fixtures/evidence_locator/build_fixtures.py` | **0** | `All checks passed!` |
| 2b | `PY -m mypy packages/cir-python/src/akc_cir/` | **0** | `Success: no issues found in 43 source files` |
| 3 | `PY -m pytest tests/unit -q -p no:randomly` | **1** | `7 failed, 1103 passed, 74 skipped in 199.11s (0:03:19)` — the five `test_superseded_receipt_contract` CRLF/LF artifacts, `test_verification_tooling_controls::test_the_shipped_bindings_all_validate` and `test_w6_v8_confirmatory::test_the_dry_run_…`, all withdrawn by §8.1 as worktree artifacts. None imports or is imported by anything this lane touches. Per §2 gate 3 they are not fixed here. |
| 4 | `PY -m pytest <lane tests> -q -p no:randomly --cov=akc_cir.evidence_locator --cov=akc_cir.evidence_locator_resolvers --cov-report=term-missing` | **0** | `TOTAL 443 0 94 0 100%` · `2 files skipped due to complete coverage` · `Required test coverage of 80.0% reached. Total coverage: 100.00%` |
| 5 | `PYTHONPATH=<worktree>/packages/cir-python/src;<worktree> PY scripts/generate_contract_types.py --check` | **0** | `generated contracts are current: packages\contracts\src\generated-contracts.ts, packages\contracts\schemas\collection-event.schema.json` — no TS moved; the resolver change is behavioural only |
| 6 | `tsc -p packages/contracts/tsconfig.json --noEmit` (main checkout's pinned typescript 5.9.3; core worktrees have no `node_modules`) | **0** | (no output) |
| 7 | `git status --porcelain` | **0** | clean after `git checkout -- docs/repro/TEST_SCOPE_SELF_TEST.json`, which gate 3 rewrites as a side effect (§7 F-4) and which is in no commit |

### 11.5 New conflict for the integrator (proposal, not an edit)

`akc_native_parsers` imports `akc_cir`, so `akc_cir.evidence_locator_resolvers`
importing `akc_native_parsers.security` runs **against the package layering**.
It is safe as shipped — `akc_cir/__init__` does not import this module, so no
import cycle exists, and every package here ships in the one
`ai-knowledge-compiler` distribution — and §8.1 rules that these guards are what
the resolver must use. But the honest reading is that the guard belongs *below*
both packages. **Proposal:** at integration, move
`_validate_office_archive` (or a thin public wrapper over it) into
`akc_security`, which both packages already depend on, and have
`akc_native_parsers.security` and this resolver call it there. I did not do it:
`packages/security/**` and `packages/native-parsers/**` are outside this lane's
§3 ownership row, and §1 says to report the conflict rather than edit.

### 11.6 Files touched in repair round 2

`packages/cir-python/src/akc_cir/evidence_locator_resolvers.py` ·
`tests/unit/test_evidence_locator_resolvers.py` ·
`tests/unit/test_evidence_locator.py` ·
`docs/architecture/evidence-locator-v2.md` · `USKC_LANE_REPORT_E.md`. All five
are in the §3 ownership row. No new dependency, nothing enabled, no PR, no
merge, no migration, no deploy, no Protected Core module touched,
`research/model_arena_20260903/**` never read, imported, written or run.
Production deploy 안 함. Git push로 Preview deployment는 자동 생성됨 — 단, 이
레인은 core repo라 Preview 대상이 아님.

**This session still does not approve its own result.**
