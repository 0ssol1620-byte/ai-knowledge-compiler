# USKC P0 — Core integration report

Campaign `TAVONEL-USKC-P0-20260906-V1`. Contract `USKC_LANE_CONTRACT_2026-09-06.md` §1, §2, §3, §7, §8.
Repository `ai-knowledge-compiler`, branch `agent/uskc-integration`, base `d9db24c`
(`research/source-faithful-kc-v1`). Worktree `D:\CodexProjects\uskc-lanes\core-integration`.

Core lanes only. Site lanes AB, D and F are a different repository and are not in this branch.

No PR. No merge to `main`. No production deploy. No Supabase migration applied. No activation flag moved.
No new third-party dependency. **Production deploy 안 함.** (Core repo — no Vercel project, so no Preview
deployment is created either.)

---

## 1. What was merged

| Merge commit | Brings in | Lane tip |
|---|---|---|
| `f6dfe92` | `packages/readers` (`akc_readers`) — `ReaderProvider` protocol, `ReaderRegistry`, inspector, `plain_text_v1`, `legacy_pdf_v1`, the reader-plane doc, and the two allowed `pyproject.toml` rows | `origin/agent/uskc-c-reader-sdk` = `3ff358bbad9d954e17368d122556c5aa85c55d04` |
| `4ed01e8` | `akc_cir.evidence_locator` + resolvers, the frozen schema copies, the regenerated `generated-contracts.ts`, the locator doc and 129 tests | `origin/agent/uskc-e-evidence-locator` = `cf56340e97cf11185440f0bc1109d0b7977083eb` |

Both merged with `--no-ff`, each as its own merge commit, C first.

### Conflicts

**None.** The expected `pyproject.toml` conflict did not occur: lane E never edited that file (its row-only
edits were `packages/cir-python/src/akc_cir/schema.py` and the regenerated
`packages/contracts/src/generated-contracts.ts`). Only lane C added the two rows, so both lanes' rows are
present because only one lane wrote any:

```
+  "packages/readers/src/akc_readers",     [tool.hatch.build.targets.wheel] packages
+  "packages/readers/src",                 [tool.pytest.ini_options] pythonpath
```

`[tool.coverage.run] source` is untouched, as lane C's contract row required.

### The frozen contract artifacts, bundled twice

Both lanes bundled the frozen JSON. All four copies are byte-identical to
`D:\CodexProjects\uskc-lanes\contract\SHA256SUMS`, so **both copies are kept** and neither was fixed:

| File | sha256 | Matches SHA256SUMS |
|---|---|---|
| `packages/readers/src/akc_readers/contract/enums.v1.json` | `3c668dc9…f11d1` | yes |
| `packages/contracts/schemas/uskc-enums.v1.json` | `3c668dc9…f11d1` | yes |
| `packages/readers/src/akc_readers/contract/evidence-locator.v2.schema.json` | `13608314…4f8ff9c6` | yes |
| `packages/contracts/schemas/evidence-locator.v2.schema.json` | `13608314…4f8ff9c6` | yes |

Proof (`sha256sum` on the merged tree):

```
3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1 *packages/readers/src/akc_readers/contract/enums.v1.json
13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6 *packages/readers/src/akc_readers/contract/evidence-locator.v2.schema.json
3c668dc9c22289b27a7d0dd8b072cf23fa0511fd8fe888875770171e664f11d1 *packages/contracts/schemas/uskc-enums.v1.json
13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6 *packages/contracts/schemas/evidence-locator.v2.schema.json
```

`capability-manifest.v1.schema.json` belongs to lane D and lives in the site repository; nothing here
consumes it.

### Reports moved

`USKC_LANE_REPORT_C.md` and `USKC_LANE_REPORT_E.md` moved from the repository root into `docs/uskc/`
with `git mv`, so the rename is recorded rather than a delete-plus-add.

---

## 2. Records placed

| Path | What |
|---|---|
| `docs/adr/ADR-007-universal-source-front-end.md` | The orchestrator's draft, in the house format. Status: **Proposed — founder decisions resolved 2026-09-06**. The placement parenthetical is gone (it is placed), and a Compliance sub-table records the four committed artifact copies and their digests, the lane reports, and that everything here is `IMPLEMENTED_NOT_PROVEN`. |
| `docs/adr/README.md` | One row added to the **Capability records** table, listed the way ADR-006 is listed (record link + what it decides + status). |
| `docs/decisions/USKC_FOUNDER_DECISIONS_RESOLVED_2026-09-06.md` | Verbatim, sha256 `a69be36abd578b6434d0375455be9167e5e31407ead0327b5e8ac134165eac61`, byte-identical to `D:\CodexProjects\uskc-lanes\USKC_FOUNDER_DECISIONS_RESOLVED_2026-09-06.md`. |
| `docs/audit/V4_MIGRATION_MATRIX.md` | Two rows added to the **Module matrix**. |

**`docs/decisions/` is new.** The repository has no existing decisions directory under another name —
`docs/adr` holds architecture decision records in a numbered normative format, which a founder product
decision list is not. Rather than paraphrase the resolutions into the ADR, they are copied whole into their
own directory and the ADR cites them.

The migration matrix's rows went into the **Module matrix**, not the Protected Core table above it: neither
module is Protected Core, and adding them there would misstate what "not replaceable without a
same-condition no-regression benchmark" covers.

```
| 17 | `akc_readers` (reader plane) | packages/readers/src/akc_readers/ | BUILD | IMPLEMENTED_NOT_PROVEN |
      ADR-007 §2. Registration and refusal are covered by tests; no §27 qualification suite has been run,
      so every capability is BEST_EFFORT and nothing is VERIFIED_*
| 18 | `akc_cir.evidence_locator` (+ resolvers) | .../evidence_locator.py, .../evidence_locator_resolvers.py
      | BUILD | IMPLEMENTED_NOT_PROVEN | ADR-007 §4. A sibling of SourceRef, not a replacement; 3 of 13
      variants resolve, and only against committed synthetic fixtures — no corpus measures it
```

---

## 3. Founder-resolution conformance — verified on the merged tree

| Ruling | Check | Result |
|---|---|---|
| **B-3** locator is a sibling of `SourceRef`; no Protected Core module changed | `git diff d9db24c..HEAD --name-only \| grep -E 'akc_cir/(inspection\|recovery_policy\|reconciler\|identity\|semantic_diff\|dependency\|recompilation\|world_state)\.py'` | **no match.** The only `akc_cir` files in the diff are the two new modules plus two rows in `schema.py`. `identity.py` is imported and called, never edited. |
| **B-4** `akc_readers` does not subclass the router's `ProviderRegistry`, and resolves by capability | `grep -rn ProviderRegistry packages/readers/src/` | **no match.** The only `akc_router` symbol crossing the seam is `ProviderUnavailableError` (`registry.py:28`), raised through so isolation semantics are shared. `resolve()` ranks entries by qualification tier and capability match; `provider_id` enters only as a final tie-break so a tie is deterministic, never as the criterion. |
| **C-1** the read-only `FailureCode` import is the only import from `akc_cir.inspection` | `grep -rn akc_cir packages/readers/src/` | one import from `akc_cir.inspection` — `from akc_cir.inspection import FailureCode` (`enums.py:17`) — and one from `akc_cir.base` (`models.py:11`), which is not Protected Core. Nothing in Protected Core is called, subclassed or modified. |
| no re-exports added to `akc_cir/__init__.py` | file not in the diff | held. |

No deviation found; nothing was changed for these three.

### Contract §8.1 / §8.2 rulings — verified, not assumed

Lane C:

- **Probe samples classified by the registry's own inspector.** `registry.py:261` — `inspection = inspect_source(sample)`; `provider.inspect(sample)` is consulted only for agreement and a disagreement raises `ReaderRegistrationError`. Present.
- **Glob / wildcard MIME patterns refused at registration.** `_CONCRETE_MIME` (`registry.py:122`) admits no `*`, `?` or `[`; applied at `:232` before anything is probed; `fnmatch` is gone from the module and resolution compares MIME by equality. Present.
- **Hostile-archive scan selected by content-detected signature, not filename extension.** `_CONTENT_SCANNED_MIME` (`inspector.py:109`) replaces the old extension set; the scan is chosen at `:235` from the detected MIME, with an HTML markup sniff so the one scanned text subtype is not extension-driven either. Present.
- **A `VERIFIED_*` receipt must be git-tracked.** `_is_git_tracked()` (`registry.py:680`) runs `git ls-files --error-unmatch` and refuses when git is absent or errors. Present.

Lane E:

- **One boundary guard in `resolve_locator`.** `evidence_locator_resolvers.py:509-515` — `except Exception` at the single dispatch site returns `Unresolved(CORRUPT_SOURCE, "<kind> resolver raised <ExceptionClass>")`. Present.
- **JSON emptiness.** `_json_is_empty()` (`:123`): `None`, `""`, whitespace-only, `{}` and `[]` → `EMPTY_OUTPUT`; numbers and booleans are content. Present.
- **Anchor identity.** `anchor_id()` (`evidence_locator.py:347`) dispatches `PdfLocator` → `identity.evidence_id(document_version, page_number1, bbox1000)` and every other kind → `locator_anchor_id()`. **The pdf variant does not use the new function** — the defect the integration was told to look for is not present, and the equality is pinned by `test_the_pdf_anchor_id_is_the_legacy_evidence_id`. Present, no fix needed.

**No `resolution_fix` was needed for any §8.1 or §8.2 ruling.** The lanes landed all of them in repair rounds 2 and 3.

Recorded contract amendments accepted as-is, per instruction and per the ADR draft: `PdfLocator.to_legacy(*, document_id)` (C-E-1) and lane C's read-only `FailureCode` import.

---

## 4. Integration fixes (`resolution_fixes`)

### 4.1 A content-detected PDF was refused because of its filename — `providers.py`

Carry-over from lane C's final review, fixed here with the failure-path test that catches it.

`LegacyPdfV1.extract_native` handed `parse_pdf_to_cir` the **caller's** `filename` and `declared_mime`.
That parser gates on both before it reads a byte (`pdf_parser.py:354-358`):

```python
if Path(normalized_filename).suffix.casefold() != ".pdf":
    raise StructuredParseError("UNSUPPORTED_PDF_TYPE")
if declared_mime.split(";", 1)[0].strip().casefold() != "application/pdf":
    raise StructuredParseError("MIME_MISMATCH")
```

So a real PDF named `report.bin` and declared `application/octet-stream` — which the inspector detects as
`application/pdf` by content, which `resolve()` therefore routes to `legacy_pdf_v1`, and which `can_read()`
accepts — was refused, and the §44 receipt published `failure_class=CORRUPT_SOURCE`,
`escalation_reason="UNSUPPORTED_PDF_TYPE"`: **an assertion of corruption about a source that is not
corrupt**, and the same "the filename decides" defect §8.2 removed from the inspector, still live one layer
down in the read path.

Reproduced before the fix:

```
E       AssertionError: assert False is True
E        +  where False = ReaderRun(... failure_class=<FailureClass.CORRUPT_SOURCE>,
E                                   escalation_reason='UNSUPPORTED_PDF_TYPE').accepted
```

Fix: the parser now receives the inspector's content-detected MIME and a filename whose extension matches
it (the caller's stem is kept, so provenance is not lost). The parser's own `%PDF-` magic check still
refuses bytes that are not a PDF, so nothing is weakened — the filename simply stops being able to decide.

Test: `test_a_content_detected_pdf_reads_the_same_under_any_filename` — the same PDF bytes under
`probe.pdf` / `application/pdf` and under `report.bin` / `application/octet-stream` produce equal unit text,
an equal `output_digest`, the same provider, `accepted is True` and `failure_class is None`.

### 4.2 The two `FailureClass` enums cannot drift — one cross-check test

`FailureClass` is transliterated twice by design: `akc_readers.enums.FailureClass` and
`akc_cir.evidence_locator_resolvers.FailureClass`, because `akc_cir` sits below the reader plane and must
not import from `akc_readers`. Both copies are kept, as instructed. `packages/readers/tests` is the only
scope that may import both, so the single cross-check lives there:
`test_the_two_transliterated_failure_class_enums_cannot_drift` asserts the two value lists are identical
**and** equal to `contract/enums.v1.json`'s `FailureClass` list.

### 4.3 `pytest tests/unit` no longer rewrites a tracked receipt

Every lane in this campaign had to `git checkout -- docs/repro/TEST_SCOPE_SELF_TEST.json` before
committing. Root cause, found by elimination rather than assumed: after a full run the working tree carried
exactly that one modified file, and `tests/unit/test_run_test_scopes_receipt_safety.py` is the **only** test
under `tests/unit` that references `tools/repro/run_test_scopes.py` (`grep -rn run_test_scopes tests/unit/*.py`
returns one line). It is not another test polluting shared state — the test runs the real tool, and the tool
writes its receipt to a fixed tracked path.

In a worktree the receipt it writes is also **false**:

```
-    "is_project_interpreter": true,          +    "is_project_interpreter": false,
-    "project_interpreter": ".../.venv/...",  +    "project_interpreter": null,
-    "project_venv_present": true,            +    "project_venv_present": false,
     "running_interpreter": "D:\\CodexProjects\\ai-knowledge-compiler\\.venv\\Scripts\\python.exe",
```

— the run *is* on the project interpreter, and the receipt says it is not, because
`run_test_scopes.py:50` resolves `PROJECT_PYTHON` relative to the repository root and a git worktree has no
`.venv` of its own. That is lane E's finding F-4, and committed carelessly it publishes a false negative
about the interpreter guard.

Fix: an autouse fixture in that test file snapshots the receipt and restores it. The write is **not**
redirected to `tmp_path` — these tests must observe what the real tool really writes to the real path;
that is the assertion. Verified: `pytest tests/unit/test_run_test_scopes_receipt_safety.py` → 3 passed,
`git status --short` shows only the test file; and the full gate run below leaves `git status --short`
**empty**.

The tool's venv probe following the repository root rather than `sys.executable` is a real defect and is
**not fixed here** — it is `tools/repro/`, outside both lanes, and it is a behaviour change to a repro
guard rather than test isolation. It is recorded for its owner.

---

## 5. The worktree-only failures — measured, and the CRLF diagnosis corrected

Contract §8.1's "Withdrawn stop-the-line" instructed the integrator to add an `eol=lf` attribute for the
receipt paths **only if** the committed blobs are LF and a fresh worktree then hashes identically.

**No `.gitattributes` rule was added, because the repository already has one and it is not the problem.**

```
$ git ls-files --eol research/experiments/H1-B-REAL-REVISION-01/receipts/
i/lf    w/lf    attr/text=auto eol=lf   .../structure-only-stale-diagnosis-2026-08-18.json
```

`.gitattributes:1` is already `* text=auto eol=lf`. The committed blob is LF **and** the working tree is LF
(`w/lf`, not `w/crlf`), so the prescribed remedy is already in force and re-checking-out changes nothing.
The mismatch is one level up — the receipt pins a digest of bytes that this repository can no longer
produce:

```
LF   522d8a5cac38161634d098ed9e8dc86b7c54704157949be52f8b8ed291f2e056   <- committed blob, and the file on disk
CRLF ba444ddb6b2e479da706a3e723e11b21bb2c17c10e4f79fe2e4e104c58fc8ee7   <- the digest the receipt declares
```

The declared digest is **exactly** the sha256 of the CRLF rendering of the committed LF bytes. So the
correction receipt was written on a checkout made under `core.autocrlf=true` *before* `.gitattributes`
landed, and it pins that CRLF rendering. The main checkout still holds those CRLF working files and
therefore still passes; every fresh checkout gets LF and fails. **No evidence was overwritten and no
retracted claim is live** — §8.1's conclusion stands; only its stated mechanism ("the working tree is
CRLF") is wrong for a current worktree.

Fixing it means editing files under `research/experiments/**`, which contract §1 forbids and which is
evidence, not code. **Not done. Recorded for the founder as the owner of that receipt corpus.**

### Git-ignored files, named

| Test | File it needs | Ignored by |
|---|---|---|
| `test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data` | `research/experiments/H1-W6-SAME-INTELLIGENCE-01/corpus-v7/00253-9c6001a8c477/before.wikitext` (the whole `corpus-v7/` tree) | `.gitignore:157` |
| `test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate` | `docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml` | `docs/ip/.gitignore:24` |

Both **fail** rather than skip (the first with `FileNotFoundError`, the second with
`assert accepted, "expected at least one element-level binding on file"` against an empty `{}`). Neither
file was fabricated. Five other tests in `test_verification_tooling_controls.py` *do* skip cleanly on the
same absence (`element support bindings are not present`), which is what this one should arguably do too —
recorded, not changed, because it is outside both lanes.

### Proven pre-existing on the base commit

`git stash` was unavailable, so the base was checked out into its own worktree
(`git worktree add D:/CodexProjects/uskc-lanes/core-base-check d9db24c`), measured, and removed.

```
$ cd core-base-check   # d9db24c, nothing from either lane
$ PY -m pytest tests/unit/test_superseded_receipt_contract.py \
      tests/unit/test_verification_tooling_controls.py \
      tests/unit/test_w6_v8_confirmatory.py -q -p no:randomly
7 failed, 65 passed, 73 skipped in 8.35s
```

The same seven node ids, on the base commit, with no lane code present.

```
$ cd core-base-check
$ PY -m mypy packages services
packages\absorption\src\akc_absorption\synthetic_corruption.py:36: error: ... [no-untyped-def]
services\api\src\akc_api\collection_retrieval_api.py:413: error: Invalid index type ... [index]
Found 2 errors in 2 files (checked 263 source files)
```

The same two mypy errors, on the base commit. Neither file is in this branch's diff.

### `test_run_test_scopes_receipt_safety` — did not reproduce here

The orchestrator's one main-checkout failure (`TypeError: unsupported operand type(s) for +: 'NoneType'
and 'str'` at `tools/repro/run_test_scopes.py:131`) **did not occur in this worktree**, in either full run
(`-p no:randomly`, 1,202 passed) or standalone (3 passed). It is not fixed and not claimed fixed. What the
code shows: the test spawns `run_test_scopes.py --self-test`, whose `self_test()` runs
`run_scope("__negative_control__", ["tests/unit/test_migration_graph.py"])` — a **nested pytest of this
same repository, from inside a pytest run**, inheriting the outer environment — and line 131 is
`text = proc.stdout + proc.stderr` with no guard on either. Lane E saw the same line fail differently
(`UnicodeDecodeError: 'cp949'`). Both are that unguarded line under a nested run. Left alone deliberately:
`(proc.stdout or "")` would convert the crash into a parsed-empty summary and a wrong-looking green
verdict, which is papering over a guard, not fixing it. Recorded for `tools/repro/`'s owner.

---

## 6. Gates

Interpreter for every command: `D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe` (`PY`),
run from `D:\CodexProjects\uskc-lanes\core-integration`.

**Import resolution.** A bare `PY -c "import akc_cir"` prints the **main checkout** path — the venv carries
an editable install pointing there. Under `pytest` the worktree wins, via `pythonpath` in the worktree's own
`pyproject.toml`; verified by collecting `tests/unit/test_evidence_locator.py` (60 tests, which exist only
on this branch). For the one non-pytest Python command (`scripts/generate_contract_types.py`) `PYTHONPATH`
was set explicitly to this worktree's `packages/cir-python/src` and its root; that is shown in the command.
`ruff` and `mypy` take paths, not imports, and were given this worktree's paths.

### Gate 1 — `PY -m pytest tests/unit packages/readers/tests -q -p no:randomly`

exit **1**

```
7 failed, 1202 passed, 74 skipped in 254.93s (0:04:14)
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[stale-attribution-correction-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[question-set-v1-invalidation-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v6-acquisition-failure-diagnosis-2026-08-19.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-acquisition-failure-2026-08-20.json]
FAILED tests/unit/test_superseded_receipt_contract.py::test_a_supersedes_pointer_resolves_and_pins_bytes[v8-post-open-instrumentation.json]
FAILED tests/unit/test_verification_tooling_controls.py::test_the_shipped_bindings_all_validate
FAILED tests/unit/test_w6_v8_confirmatory.py::test_the_dry_run_exercises_the_confirmatory_harness_on_development_data
```

All seven are the §5 pre-existing set, proven on `d9db24c` above. **Nothing else fails.** `git status
--short` immediately after the run is **empty** — the receipt-rewriting side effect every lane reported is
gone (§4.3).

Lane E added no test directory outside `tests/unit`; its two files are `tests/unit/test_evidence_locator.py`
and `tests/unit/test_evidence_locator_resolvers.py`, both inside gate 1's scope. The two lanes' own tests
collect 197 ids (`packages/readers/tests` 68 + the two locator files 129).

### Gate 2 — `PY -m ruff check packages services tests`

exit **0**

```
All checks passed!
```

### Gate 3 — `PY -m mypy packages services`

exit **1** — the two pre-existing errors, both proven on `d9db24c` in §5, neither file in this diff.

```
packages\absorption\src\akc_absorption\synthetic_corruption.py:36: error: Function is missing a type annotation for one or more parameters  [no-untyped-def]
services\api\src\akc_api\collection_retrieval_api.py:413: error: Invalid index type "tuple[UUID | None, int | None]" for "dict[tuple[UUID, int], DocumentVersion]"; expected type "tuple[UUID, int]"  [index]
Found 2 errors in 2 files (checked 271 source files)
```

(271 files here vs 263 on the base — the eight added by the two lanes all check clean.)

### Gate 4 — contracts typecheck, `tsc -p tsconfig.json --noEmit` from `packages/contracts`

exit **0**, no output.

`packages/contracts/package.json` documents `typecheck` / `lint` / `test` as exactly this command. Core
worktrees have no `node_modules` (contract §2 installs them for site lanes only), so it was run with the
main checkout's pinned binary, `packages/contracts/node_modules/.bin/tsc` (typescript 5.9.3), against
**this worktree's** `tsconfig.json` — `strict`, `exactOptionalPropertyTypes` and
`noUncheckedIndexedAccess` all on. No dependency was installed in this worktree.

### Gate 5 — contract drift, `PY scripts/generate_contract_types.py --check`

exit **0**

```
generated contracts are current: packages\contracts\src\generated-contracts.ts, packages\contracts\schemas\collection-event.schema.json
```

Run with `PYTHONPATH` set to this worktree's `packages/cir-python/src` and its root, as lane E documented.
This is the drift check lane E named; there is no separate one.

### Gates not run, with the reason

- **Coverage** (`--cov --cov-fail-under=80`) — **skipped**. `akc_readers` is deliberately outside
  `[tool.coverage.run] source` (lane C's contract row allowed two `pyproject.toml` rows and neither is a
  coverage row), so the number cannot move for it, and lane E measured 100% statement and branch coverage
  over both of its modules in its own gate 4. Re-running the whole-tree coverage suite would only
  re-measure the §5 pre-existing failures.
- **`tools/repro/run_test_scopes.py --scopes full`** — **skipped**. Its `full` scope runs the whole
  repository including `research/model_arena_20260903/**`, where a benchmark chain is live and which
  contract §1 puts off-limits.
- **Site gates** (`pnpm check` / `test` / `build`, Playwright) — **not applicable.** This is the core
  repository; lanes AB, D and F are a different repository and a different integration branch.
- **`supabase db test`** — **not applicable.** This branch contains no migration.

---

## 7. What is not done, and what is not claimed

- **Nothing here is wired into the live compile path.** `akc_readers` is not called by any service, the
  site does not consume the registry, and `parse_pdf_to_cir` is still reached by the legacy entry points as
  well. This is the SDK and the union, additive, beside the existing flow.
- **No `VERIFIED_NATIVE` / `VERIFIED_HYBRID` anywhere.** No §27 qualification suite has been run and no
  qualification receipt exists in this repository. Both shipped providers are `BEST_EFFORT`.
- **No cost, latency or throughput number is published.** `gpu_seconds`, `provider_cost_usd`, `p50/p95`
  are `None` because nothing measured them.
- **Ten of the thirteen locator variants have no resolver** (`image`, `docx`, `pptx`, `email`, `xml`,
  `code`, `cad`, `media`, `database`, `api`); they are typed and round-trippable and resolve
  `Unresolved(UNSUPPORTED_FORMAT)`. Figure and media `SourceRef`s are **refused** by `from_legacy` rather
  than silently truncated, so they have no v2 locator today.
- **`plain_text_v1` emits no evidence locator** — enums v1 has no `text` kind and inventing an anchor is
  forbidden. A `text {byteRange|lineRange}` variant is proposed for enums v2 in lane C's doc; the frozen
  artifact was not edited.
- **The three worktree-only test failures are not fixed** (§5): the receipt digests are evidence under
  `research/experiments/**` and the two corpus files are git-ignored. Named, not fabricated.
- **`tools/repro/run_test_scopes.py`'s two defects are not fixed** — the venv probe resolving `.venv`
  against the repository root, and the unguarded `proc.stdout + proc.stderr` at line 131. Both are outside
  both lanes' ownership and neither is test isolation.
- **This session does not approve its own result.** Integration is not review; the merged branch has had no
  independent adversarial pass.

## 8. For the founder

Only real-world acts. Nothing below was done.

1. **Open and merge the PR for `agent/uskc-integration`** (core). Agents do not open PRs or merge to main.
2. **The superseded-receipt digests under `research/experiments/**/receipts/` pin CRLF renderings.** Every
   fresh checkout of this repository fails five tests that read them, and the main checkout passes only
   because it still holds pre-`.gitattributes` CRLF working files. Re-pinning them means rewriting evidence
   receipts, which no agent does. §5 has the exact bytes and both digests.
3. **`docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml` and `research/experiments/.../corpus-v7/` are git-ignored**, so
   two more tests fail in any fresh checkout or CI runner rather than skipping. Whether they should be
   committed, skipped-on-absence, or left as they are is a decision about what CI is allowed to depend on.
4. **ADR-007 is `Proposed`, not `Accepted`.** Accepting it is the founder's act.
5. **`approved_customer_data` remains off** and nothing in this branch can reach it. Enabling it is
   explicitly outside every agent's authority (RESOLVED B-10).

---

Branch `agent/uskc-integration`. Base `d9db24c`. Merges `f6dfe92` (lane C) and `4ed01e8` (lane E), then
`4eaf869`, `df4fc70`, `f8894c7` and this report's commit. **Production deploy 안 함.**
