# Handoff execution ledger, Core — 2026-10-02

Private companion to Foundation `docs/audit/HANDOFF_EXECUTION_2026-10-02.md` (Foundation `lane/DOC`). The requirement list and the frozen 2026-09-30 classification are Foundation's `MASTERPLAN_IMPLEMENTATION_2026-09-30.md` and `CUMULATIVE_ACCEPTANCE_2026-09-30.md`; neither is edited. This file holds the Core detail the public ledger must not carry, including security-fix specifics.

Pins: base `cbfd19dc208fdc7d7c336ef4a182dc6c03f0f963` → PR #91 head `4c234df4c8a9c815158449ae32f0a09711ae7209` (remote branch `codex/masterplan-checkpoint-2026-09-30`, private, draft, unmerged). No merge, deployment, production store, credential, customer document or paid call was used. Classification proposals below need founder confirmation.

## Core CI status

At the base `cbfd19dc` Core CI allocated no runner (run 36740959690: every job 0 steps). Since `4b3cadac` (runs 37011796206/…309/…229) runners are allocated and jobs execute, including on the head `4c234df`.

| Workflow on `4c234df` | Run | Result |
|---|---|---|
| CI | 37013961712 | failure. `python-core (3.13)`: **1 failed, 3,440 passed, 2 skipped, 2 xfailed**. `python-core (3.12)`: same 1 failure and same 3,440 passed, then `INTERNALERROR coverage.exceptions.DataError: Can't combine statement coverage data with branch data` (exit 3). The one failure is `benchmark/runpod_eval/test_evaluate_omnidoc_repeats.py::test_page_count_includes_pages_beyond_the_windows_max_path_limit` (`OSError: [Errno 36] File name too long` on Linux). `postgres-rls-and-role-boundaries`: privilege receipt drift (expected `0037_gpu_post_claim_authorization`, actual `0041_source_cursor_acl`; `identity_ledger`, `source_cursors` absent from expected receipt). `contracts`: `verified container pin is unused: gcr.io/distroless/nodejs24-debian13:nonroot@sha256:af85d1…`. `visual-and-browser-matrix`: missing Linux baselines and two screenshot diffs. `web-and-contracts`, `lighthouse`, `worker-syntax`, `infrastructure`, `live-browser-e2e` success |
| Security | 37013962093 | failure. Image scans report urllib3 CVE-2026-97689 (lock pins urllib3 2.7.0) in api, scheduler and cpu-document images, and `next` 16.3.3 GHSA-vcvr-r3jv-pc5j (CRITICAL, RCE in `next/og` ImageResponse, fixed 16.3.6) in the web image; `dependency-audit` and `filesystem-and-iac` fail. `IP privilege guard`, `registry` success |
| Model CI | 37013961703 | failure. Four local GPU images fail the same urllib3 scan |

None of these failing gates is in this handoff's diff (no migration, lockfile, Dockerfile, workflow or visual baseline changed in `cbfd19dc..4c234df`). They were invisible while runners were not allocated. Every test file this handoff added or changed **passed** in both python-core jobs: `test_core_semantic_incremental_runtime.py` (`...xx.......`, the two strict xfails), `test_core_semantic_incremental_fixtures.py`, `test_nonpdf_structured_parsers.py`, `test_ontology_additive_migration_boundary.py`, `test_pdf_native_fidelity.py`, `services/api/tests/test_ask_api.py`, `services/api/tests/test_native_nonpdf_worker_e2e.py`.

The Next.js critical advisory and the urllib3 CVE are security findings on the Core images; they belong to the stop-the-line review, not to a feature lane.

### Next.js GHSA-vcvr-r3jv-pc5j on PR #91

- The PR #91 branch pins `apps/web` `next` 16.3.3, inside the advisory range (>=16.2.0 <16.3.6; critical, RCE in `next/og` `ImageResponse`). `apps/web` uses `next/og` in `icon.tsx`, `apple-icon.tsx` and `opengraph-image.tsx`, so the vulnerable path is reachable in that build.
- `origin/main` already carries 16.3.6 (commit `9fd84e2`). The exposure is specific to the PR branch.
- PR #91 is 31 commits behind main with about 30 conflicting files, including `compiler-runtime` `extraction.py` and `pipeline.py` (both changed by this handoff), migration 0038 and `pnpm-lock.yaml`.
- PR #91's Vercel preview reports "Deployment was blocked", so there is no evidence the vulnerable build is served. This was not verified against the Vercel project's deployment list.
- Foundation uses `next` ^15.5.9, outside the advisory range.
- Blocker: absorb main into PR #91 before any merge. Owner: Core integration. The conflicts touch this handoff's ACL and extraction changes and need careful resolution plus a re-run of the M2 failure-path tests.

## Local re-run by the ledger author

Python 3.12.6 (`task-3\core-work\.venv`), PYTHONPATH = worktree `packages/*/src`, `services/api/src`, `workers/cpu-document/src`, on `4c234df` (core-DOC worktree), the seven changed test files: **161 passed, 2 xfailed, 2 failed**. Both failures are in `test_native_nonpdf_worker_e2e.py` (task reaches `dead_letter` / `PARSER_RESULT_INVALID`). Root cause is the environment, not the head: the worker spawns its sandbox child as `sys.executable -I -m akc_worker_document.sandbox_runner` with a sanitized environment (no PYTHONPATH), so the child imports the venv's editable installs from `task-3\core-work`, whose `akc_native_parsers` has no `csv_parser.py`. The same tests pass on the hosted runner (above). This venv cannot qualify the sandbox e2e for any worktree other than `core-work`; no package was installed to work around it.

## Changes by lane

| Lane | Requirement (masterplan row) | Commits | What changed | Independent review | Tests (env, counts) | Evidence class |
|---|---|---|---|---|---|---|
| F | K11, K12, K13, K22 (K27 scope statement) | `b00cabb`, `114ccf3`, merge `4b3cada` | CSV raw field text kept beside normalized text; row/column/cell/field limits enforced before `csv.reader`; malformed CSV dead-letters as non-retryable `CSV_MALFORMED`, no partial result; XLSX keeps sheet order, merged/sparse cells, types, formula + cached value, number format, array formula text, marks data-table formula unavailable; Python/JSON Schema/TS parity. `raw_text_verbatim` made an explicit producer opt-in so OCR cells keep the contract-wide strip and their content hashes. **HWP/HWPX unsupported; CSV strict UTF-8, fixed comma dialect** (`docs/NATIVE_NON_PDF_PARSERS.md`) | Patch reviewed before integration (sha256 `065d2fe7…1f1c246`); separate reviewer agent: `b00cabb` CHANGES REQUIRED (`CanonicalCell` strip regression on OCR cells) → `114ccf3` APPROVE | Lane: CPython 3.12.6, 66 then 68 native-format tests, 416 then 450 adjacent, ruff, strict mypy (8 sources), `generate_contract_types --check`. Hosted CI 37013961712: all changed files passed | unit/mock + synthetic local runtime (real `AnalysisWorker` + sandbox child over local ASGI/SQLite) |
| M | K06, K09, K18 (lane tag K25) | `b497421`, `d50e7d9`, `1911721`, merge `ff5c792` | Semantic incremental equivalence fixtures (test-only builder; not production behaviour); `OntologyStore.save()` refuses an unsupported schema before touching disk; `/v1/ask` world store partitioned by tenant (below); runtime test drives the production `Pipeline` over real files and compares an incremental recompile with a forced full compile (identical claims, evidence, manifest hash) and a from-scratch compile (identical except logical ids of the edited document) | Separate reviewer agent: `b497421` APPROVE (integrates reviewed lane commit `2980e72` byte-for-byte); `d50e7d9` APPROVE; `1911721` APPROVE, reviewer flagged the ACL pinning test, which M2 flipped | Hosted CI: all pass; runtime file shows 2 strict xfails. Local: included in 161 passed / 2 xfailed | unit/mock (`/v1/ask` via in-process ASGI) + synthetic local runtime (Pipeline over a 9-file demo corpus) |
| M2 | K09, K21, K03 (ACL-only change) (lane tag K15/K25) | `9b4a835`, `223bc95`, `9bc0c06`, merge `4c234df` | Source front-matter `required_permission` carried into compiled rows; asks gated on the asker's permissions; ACL-only edit emits `PERMISSION_CHANGED` (additive member in protected-core `akc_cir.semantic_diff`; no existing behaviour changed) and recompiles selectively; unreadable ACL shapes fail closed (below) | Separate reviewer agent: `9b4a835` CHANGES REQUIRED (BOM / CR-only / YAML-syntax / camelCase bypasses) → `223bc95` CHANGES REQUIRED (NEL/LS/PS breaks, nonstandard opener) → `9bc0c06` APPROVE. Reviewer `acl_probe.py`: 0 leaks; `acl_probe2.py`: only the two documented-limit cases remain public | Hosted CI: all pass. Commit trail: 34 unmappable shapes + 9 further failure paths fail closed | unit/mock + synthetic local runtime (production `Pipeline` over real files) |

## Security fixes (private detail)

**Tenant partition of `/v1/ask` (`d50e7d9`).** `_resolve_world` globbed every snapshot in one shared `world_store_dir` with no tenant input, so with a mounted multi-tenant store tenant A could be answered from tenant B's ACTIVE world. Exposure is conditional: the deployed base leaves the store unset, so no live exposure is claimed. Fix: resolver takes the principal's `tenant_id` (never the body) and reads only `<store>/<tenant uuid>/*.json`; snapshot schema v2 carries a required `tenant_id` verified on read; a missing or foreign binding poisons the lookup (no fallback to a sibling); root-level JSON refuses every lookup; a tenant with no partition reads as empty, so a foreign world id returns "not found" (no existence oracle). Not fixed: no in-repo writer of the v2 snapshot format exists (Pipeline store → `/v1/ask` wiring missing), and workspace entitlement inside a tenant is unchecked (`workspace_id` is descriptive only).

**Source ACL into compiled rows (`9b4a835`).** Front matter was stripped before extraction and `_row_from_draft` hard-set `required_permission=None`, so a claim from a restricted source answered CURRENT to an asker with no permission.

**Front-matter bypass vectors closed (`223bc95`, `9bc0c06`).** The first parser matched a key-name denylist; these reached the restricted claim through the real Pipeline: UTF-8 BOM, CR-only line endings, quoted keys, flow mappings, anchors with `<<` merges, `?` complex keys, camelCase `requiredPermission`; then YAML 1.1 NEL/LS/PS line breaks hiding an escaped key on one scanner line, and openers such as `--- # fm` or `--- !meta` falling into the no-front-matter branch. The scanner now allows exactly one shape (`required_permission: <token>` inside a standard `---` block, one matched quote pair); BOM dropped, CRLF/CR/NEL/LS/PS normalised; Unicode format characters removed before NFKC casefold; any key-position syntax, `<<`, repeat, comment, tag, escape, unquoted null/bool/number, ACL-ish token in a nonstandard block, or a declaration outside the mapped line → `UNMAPPED_ACL`, which is stripped from asker permissions and therefore never grantable. **Known limit, pinned by test:** vocabulary outside the token list (for example `permitted_users`, `audience`) is not recognised and stays public; `required_permission` is the only ACL contract.

## Proposed classification for the Core-touched items (founder confirmation required)

| ID | Frozen | Proposed | Justification and what is missing |
|---|---|---|---|
| K06 | Partial | Partial | Oracle equality on one edit over 9 files; recompile re-parses all 9 and resolves 10 vs 9 for a full compile — **no saving**, strict xfails, no corpus |
| K09 | Partial | Partial | Tenant partition and fail-closed source ACL (unit + synthetic runtime); cache/export/historical-snapshot leak audit, workspace entitlement and derived-document permission inheritance missing |
| K11 | Partial | Partial | Raw/normalized cell contract and opt-in parity; universal anchor contract not complete |
| K12 | Partial | Partial | No per-format golden corpus; HWP/HWPX unsupported |
| **K13** | Unassessed | **Partial** | First assessment: cell, type, merged/sparse, formula + cached value, number format preserved (unit + in-process worker e2e, passing on hosted runner). Header/unit semantics and golden corpus missing |
| K18 | Unassessed | Unassessed | One refusal guard is not a breaking-change rebuild/rollback test |
| K21 | Partial | Partial | Source-side and asker-side revoke apply on the next ask in the runtime; vectors/summaries/cache/backup/restore not covered |
| K22 | Partial | Partial | Bounded CSV preflight against delimiter amplification; full parser/archive/injection audit missing |
| K25 | Unassessed | Unassessed | Lane tag only; tenant partition is K09 work, not 10,000-document scale |
| K27 | Unassessed | Unassessed | Unsupported is declared, not evaluated for safety/accuracy/licence |
| K15 | Partial | Partial | Lane tag only; no locked-holdout resolver evidence |

Core's narrower lane count (0/18/9/4 in `CORE_CUMULATIVE_READINESS_2026-09-30.md`) is not replaced here. Global proposal (Foundation ledger): 2 / 38 / 9 / 6.

## Open blockers and the exact owner

| Blocker | Owner |
|---|---|
| Core CI red: privilege receipt 0037 vs 0041 drift, unused container pin, coverage combine error, Linux path-length test, missing Linux visual baselines | Core lane (receipt regeneration is an evidence artifact update; founder approves overwriting a receipt) |
| PR #91 pins `next` 16.3.3 (GHSA-vcvr-r3jv-pc5j, critical); main already has 16.3.6 (`9fd84e2`); PR is 31 commits behind with ~30 conflicting files | Core integration: absorb main into PR #91 before any merge; founder schedules as stop-the-line |
| urllib3 CVE-2026-97689 in Core images | Core lane to bump (check whether main already fixes it during the absorb) |
| Joined upload → Core compile → consumer proof (Core cannot run in Foundation public CI) | Founder: read-only Core deploy key for Foundation CI, or a Core-side joined workflow |
| Pipeline store → `/v1/ask` v2 snapshot writer | Core engineering |
| Workspace entitlement inside a tenant | Core engineering + founder on the entitlement model |
| Derived-document permission inheritance; ACL vocabulary beyond `required_permission` | Core engineering |
| Incremental recompile saves no work | Core engineering |
| Sandbox e2e cannot be qualified locally outside `core-work` | Core lane (a worktree-bound venv), no install into the shared venv |
| Classification change, main merge, deployment | Founder |

## Rollback

All Core changes are on the unmerged PR #91 branch. No Alembic migration was added in this range; the `CanonicalCell.raw_text_verbatim` field is optional and dropped from canonical JSON when absent, so existing content hashes are unchanged. Snapshot schema v1 files fail closed under the new resolver; reverting `d50e7d9` restores the unpartitioned (unsafe) layout and should not be done without a replacement.
