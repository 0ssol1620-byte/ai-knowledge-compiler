# Category Leadership gap matrix — 2026-09-05

Read-only research. No code changed to produce this document.

Campaign `TAVONEL-CATEGORY-LEADERSHIP-20260905-V1`, lane `gap-matrix`. It grades
the roadmap items of the category-leadership blueprint §55–§56, the §61
"업계 최정상급" criteria that sit behind them, and the §69 acceptance gate,
against what the two repositories actually contain.

## 0. What was read, and at which commit

| Repository | Ref read | Commit |
|---|---|---|
| `ai-knowledge-compiler` (core) | `research/source-faithful-kc-v1` | `26bb892` |
| `tavonel-saas-foundation` (site) | `origin/main` | `9a7a93d` |

Production `tavonel.com` serves `9a7a93d`. Every site pointer below was read with
`git show origin/main:<path>`; every core pointer was read in a worktree at
`26bb892`. Where a document and the code disagree, this file follows the code.

Two things read outside those refs, and marked as such wherever they are used:

- `research/model_arena_20260903/` — present only in the core repo's **working
  tree**, git-untracked. It is evidence about a campaign, not a commit.
- `feature/revision-compile-v1` in the site repo — a **local-only** branch
  (no `origin/` counterpart). Its revision route is absent from `origin/main`.

## 1. Status vocabulary

The lane contract fixes four words plus an absence. They are narrower than they
sound, and the narrowness is the point.

| Status | Means, exactly |
|---|---|
| `ABSENT` | No implementation at the refs above. Not "planned" — not there. |
| `IMPLEMENTED` | Code exists. No test named here exercises the behaviour the row claims. |
| `TESTED` | Code exists **and** a test at a named path exercises the row's behaviour. |
| `PROVEN` | A receipt or benchmark measures it on a corpus, bound by sha256. |
| `BLOCKED` | A named dependency or a founder decision stops it, and the block is written down. |

`TESTED` here asserts that the test **exists at the named path** and asserts the
named behaviour. **This lane did not execute the suites** — it is read-only
research, and a test run is a separate act from reading one. The most recent
committed run of the repository's own instrument is
`docs/repro/TEST_SCOPE_STATUS.json` at `26bb892`: full scope, 3,199 collected,
3,131 passed, 68 skipped, exit 0, `repository_green: true`, receipt
`sha256:8b9825d4b673dfe6fbfe98065c33605fe1a9bdfae41eb6a75a8728d50ede2ccd`,
`generated_at` `2026-09-03T07:25:53Z`. That timestamp is **earlier than commit
`cfe46b8`**, which added `tests/integration/test_full_compile_chain_e2e.py`, so
the twelve tests in that file are *not* inside the 3,199. No number in this
document should be read as covering them.

`PROVEN` is deliberately almost empty. `CLAUDE.md` states the rule this matrix
obeys: tests show the code does what its author intended, and nothing here shows
a threshold is right. `CalibrationTable.calibrated` is `False`.

Mapping to the older vocabulary in `docs/audit/V4_MIGRATION_MATRIX.md`: that
file's `IMPLEMENTED_NOT_PROVEN` splits here into `IMPLEMENTED` and `TESTED`;
its `PROVEN` and this file's `PROVEN` mean the same thing; its `MISSING` is
`ABSENT`; its `BLOCKED_LICENSE` is one reason among several for `BLOCKED`.

---

## 2. The matrix

Priorities are the blueprint §56 matrix, verbatim.

| # | Item | P | Status | Where it lives |
|---|---|---|---|---|
| 1 | Explore redesign | P0 | `IMPLEMENTED` | site `nextjs/app/explore/page.tsx`, `components/explore-compiled-world.tsx` |
| 2 | Change / Impact UI | P0 | `ABSENT` (public) · `TESTED` (workspace lens) | site `components/world-version-diff.tsx` |
| 3 | Selective recompile production path | P0 | `TESTED` (core) · `BLOCKED` (product) | core `akc_cir/recompilation.py`, `services/core-v3/` |
| 4 | Equivalence proof | P0 | `TESTED` | core `akc_cir/recompilation.py:649` |
| 5 | Benchmark route | P0 | `ABSENT` | site `nextjs/app/benchmarks/page.tsx` |
| 6 | World History | P0 | `TESTED` | site `lib/world-read-model.ts:118`, `components/world-version-diff.tsx` |
| 7 | Compiler Contract page | P0 | `ABSENT` | site `nextjs/app/product/continuous-knowledge/page.tsx` |
| 8 | GitHub trust surface | P0 | `ABSENT` (site) · `IMPLEMENTED` (core) | site repo root; core repo root |
| 9 | Ontology Studio | P1 | `TESTED` (viewer) · `ABSENT` (studio) | site `components/world-ontology-viewer.tsx` |
| 10 | Conflict / authority resolution | P1 | `TESTED` (library) · `ABSENT` (wired) | core `akc_cir/authority.py:263` |
| 11 | Permission lineage | P1 | `ABSENT` | — |
| 12 | Point-in-time Ask | P1 | `TESTED` (library) · `ABSENT` (wired) | core `akc_cir/temporal.py:279` |
| 13 | Connector deltas | P1 | `IMPLEMENTED` (pull) · `ABSENT` (push) | site `lib/developer-contracts.ts:53` |
| 14 | OWL / SHACL / PROV-O adapters | P1 | `IMPLEMENTED` (JSON-LD + SHACL shape) · `ABSENT` (OWL 2, PROV-O, OpenLineage) | core `akc_exporters/jsonld.py` |
| 15 | SSO / SCIM | P2 | `IMPLEMENTED` (control plane) · `BLOCKED` (provider) | site `lib/enterprise-contracts.ts:11` |
| 16 | BYOK / VPC | P2 | `ABSENT` | — |
| 17 | Enterprise compliance | P2 | `ABSENT` (certification) · `TESTED` (the guard against claiming it) | site `e2e/ultimate-blueprint.spec.ts:62` |
| 18 | Domain packs | P3 | `TESTED` (library) · `ABSENT` (surface) | core `packages/domain-packs/` |
| 19 | Partner ecosystem | P3 | `ABSENT` | — |

The rows follow. Lane contract §5 requires four elements per row — file pointers
as `path:line`, the test or receipt that backs the status, the nearest ADR or
contract, and the smallest next step — and every one of the nineteen carries all
four. Two of them are sometimes null, and a null is written out with its reason
rather than omitted, because an omitted element and an empty one are different
claims. **Backed by** reads "nothing tests this" on the four rows where nothing
does — 7, 8, 11 and 19 — and each of those names what *is* tested nearby, so an
untested capability is not confused with an untested neighbourhood; row 17 is the
mixed case, where the guard against the claim is tested and the posture behind it
does not exist. **Smallest next step** is empty on three rows and
for three different reasons: row 15 waits on a founder decision (§5), row 16 is a
deliberate refusal to build ahead of demand, and row 19 is blocked by the
ordering in blueprint §55 rather than by cost.

---

### 1 · Explore redesign — P0 — `IMPLEMENTED`

**Where.** `nextjs/app/explore/page.tsx:31` renders `ExploreCompiledWorld` with
one compiled world. `nextjs/components/explore-compiled-world.tsx` is 91 lines;
`:46` carries the single `INTERACTIVE SAMPLE` badge. The world is compiled at
build time by `nextjs/lib/explore-sample.ts:81` (`compileCollectionCandidate`
over three committed PDFs) and refuses to load if the result stops matching the
frozen digest at `:34`, checked at `:90`
(`sha256:929153d4d0ad1dd6e7a52e3aebdab45747c9792b64869dbb636c969ab1c79abc`).

**Backed by.** `nextjs/lib/explore-sample.test.ts`, plus explore assertions in
`nextjs/e2e/ultimate-blueprint.spec.ts`, `e2e/ultimate-mobile-a11y.spec.ts`,
`e2e/ux-polish.spec.ts`. The digest guard is the strongest thing here: it makes
the page fail the build rather than render a world nobody compiled.

**Why not `TESTED` for the row as written.** The row is "Explore redesign" —
blueprint §15–§29's three-act interactive film. What exists is the *predecessor*:
object → evidence → source page, no World act with curated focus, no Change act,
no technical drawer. `EXPLORE_SAMPLE_QUESTIONS` at `:122` includes "Which
revision superseded the 1,500 hour interval?", but the answer is grounded in a
change-notice document, **not** in a diff between two compiled worlds. There is
one world in this page and no second revision to compare it to.

**Nearest contract.** Lane contract §4.1 (`VisualWorldModel`), §4.2 (stage state
machine and `data-visual-*` attributes), §4.3 (`ExploreChangeStory`).

**Smallest next step.** The `explore` lane's Stage A: add
`fp-200-maintenance-manual-revB.pdf` to `scripts/build-explore-sample.mjs`,
compile both worlds at build time, freeze both digests. Everything in Act 3
depends on the second world existing; nothing else does.

---

### 2 · Change / Impact UI — P0 — `ABSENT` on the public site, `TESTED` in the workspace

**Where.** The diff engine is `nextjs/lib/world-version-diff.ts:124`
(`diffWorldVersions`) and `:182` (`countChanges`). It is rendered by
`nextjs/components/world-version-diff.tsx`, reached only through the World
Studio "Versions" lens — `nextjs/components/world-studio-ultimate.tsx:30`
declares the lens, `:137` mounts the panel. The panel reads `model.history`
(`:48`), fetches the other manifest through
`/api/v1/world/${id}?manifest=` (`:69`), and says
"No persisted World history is available" when there is none (`:107`).

**Not present.** `WorkspaceSurface` at
`nextjs/components/workspace-ultimate-shell.tsx:12` is
`"home" | "sources" | "runs" | "review" | "world" | "ask" | "connections" |
"developer" | "activity" | "settings"`. There is no `"changes"` surface and no
Change Inbox. On the public site there is no change/impact surface at all.

**Backed by.** `nextjs/lib/world-version-diff.test.ts`;
`nextjs/e2e/world-lifecycle.spec.ts`.

**Nearest contract.** Lane contract §4.5 (workspace `changes` surface);
blueprint §30–§33.

**Smallest next step.** Promote the Versions lens to its own surface with the
nav row of §4.5 — the diff and the counts already exist and are derived, so the
work is placement and empty-state honesty, not new computation.

---

### 3 · Selective recompile production path — P0 — `TESTED` in core, `BLOCKED` in the product

**Where, core.** The path is complete and runs end to end over loopback sockets:

- `services/core-v3/src/akc_core_v3/sources.py:541` `resolve_sources` — stored
  OCR to canonical units, identity from the printed clause number and the heading
  above it.
- `services/core-v3/src/akc_core_v3/projections.py:221` `plan_artifacts` — the
  collection ontology, directory plan and retrieval index enter the dependency
  graph as ordinary artifacts under reserved ids.
- `services/core-v3/src/akc_core_v3/initial.py:119` `compile_initial`, `:168`
  `InitialCompileService` — `initial_compile` on its own route.
- `services/core-v3/src/akc_core_v3/resolver.py:75` `ProductionSourceResolver` —
  resolves the whole collection at the version being compiled, changed and
  unchanged together.
- `services/core-v3/src/akc_core_v3/service.py:102` `RevisionService`.
- `packages/cir-python/src/akc_cir/semantic_diff.py:610` `diff_documents`,
  `packages/cir-python/src/akc_cir/dependency.py:190` `DependencyGraph`,
  `packages/cir-python/src/akc_cir/recompilation.py:337` `plan_recompilation`.

**Backed by.** `tests/integration/test_full_compile_chain_e2e.py` — twelve tests,
including `:460` `test_world_v1_is_compiled_from_stored_ocr`, `:511`
`test_the_collection_projections_are_artifacts_of_the_world`, `:563`
`test_the_whole_chain`, `:890` `test_the_same_sources_compile_to_the_same_world`.
Also `tests/integration/test_revision_compile_e2e.py` (14 tests) and
`tests/unit/test_revision_compile.py` (25).

**What changed since the closure.** `docs/audit/TAVONEL_RESEARCH_PRODUCT_CLOSURE_FINAL_2026-09-03.md`
records claim 1 ("v1 compile") as PARTIAL and a production `SourceResolver` as
BLOCKED. Commit `cfe46b8` closed both — the resolver exists and the chain begins
with a compile. **That closure document is stale on those two rows** and correct
on everything else. This matrix supersedes it there and nowhere else.

**Why the product half is `BLOCKED`.** The site's revision route
(`nextjs/app/api/collections/[id]/revise/route.ts`) is **not on `origin/main`**;
it exists only on the local-only branch `feature/revision-compile-v1`
(`92843b0`), which is 13 commits ahead of and 87 behind `origin/main`, and has no
`origin/` counterpart. Nothing in production compiles a revision. The reason the
closure gave for blocking activation — the Core not returning collection
projections — is now answerable in the core (see `projections.py` above), but
nothing has re-derived the product route against it.

**Nearest contract.** `docs/adr/ADR-001-canonical-intermediate-representation.md`;
`CLAUDE.md` Protected Core.

**Smallest next step.** Rebase `feature/revision-compile-v1` onto `origin/main`
and re-run its own tests against the projections the Core now returns — before
that, the question "is activation still blocked?" cannot be answered by a test.
This is a founder decision on branch strategy, not an agent's call (see §5).

---

### 4 · Equivalence proof — P0 — `TESTED`

**Where.** `packages/cir-python/src/akc_cir/recompilation.py:628`
`EquivalenceReport`, `:649` `verify_equivalence`. The union of the selective
rebuild and what it carried over must equal the full rebuild, artifact for
artifact and hash for hash. `stale_left_behind` is the failure the function was
written to catch: an artifact the plan called current whose content a full
rebuild would have changed.

**Backed by.** `tests/unit/test_recompilation.py:233`
`test_a_correct_selective_run_equals_a_full_rebuild`, `:290`
`test_equivalence_over_a_whole_worked_change`;
`tests/unit/test_knowledge_cicd_pipeline.py:169`
`test_the_selective_rebuild_equals_a_full_rebuild` and `:200`
`test_a_missing_edge_makes_the_equivalence_check_fail_rather_than_pass_quietly`;
`tests/unit/test_revision_compile.py:328`
`test_the_selective_state_equals_the_independent_full_rebuild`.

The second of those is the one that makes the row worth trusting: a passing
equivalence check on a graph with a missing edge would be the exact silent
failure the mechanism exists to prevent, and there is a test that it fails.

**Why not `PROVEN`.** Every one of those runs is over a fixture graph authored in
the test file. No receipt binds an equivalence result to a corpus by sha256. The
`change-receipt` lane of this campaign is producing exactly that artifact under
`research/explore_change_receipt_20260905/`; until it lands, this row is
`TESTED` and the public surface must not show a PASS badge.

**Nearest contract.** Lane contract §4.3 — `equivalence` is `{state: "not_yet"}`
unless a real core receipt is wired.

**Smallest next step.** Land the `change-receipt` lane's receipt, then cite it by
sha256 from the Change Act. Not before.

---

### 5 · Benchmark route — P0 — `ABSENT`

**Where.** `nextjs/app/benchmarks/page.tsx` is six lines and calls `notFound()`
at `:5`, commented "Intentionally unavailable. Kept only as a stable 404 for
retired inbound URLs." `/benchmarks` does not appear in
`nextjs/app/sitemap.ts:10`.

**What exists instead.** `nextjs/app/research/page.tsx:61` publishes the
"Reproduce before comparing" rule; `/reproducibility` and `/evidence` exist.
There is no benchmark registry, no receipt validator, no metric taxonomy.

**Backed by.** The absence is asserted, not merely observed:
`nextjs/e2e/ultimate-mobile-a11y.spec.ts:35` requires `/benchmarks` to answer
404, and `nextjs/lib/public-copy-purge.test.ts:66` carries the route as a
`noindex` exemption. The route is a deliberate, tested 404 — activating it will
break a test, which is the correct way for a stub to behave.

**Nearest contract.** Lane contract §4.4 — `BenchmarkReceipt`,
`validateBenchmarkReceipt()`, `qualifiedBenchmarkRecords()`; blueprint §37–§39.

**Smallest next step.** Implement §4.4's validator with its four rejection tests
(missing hash, missing denominator, quoted-as-reproduced, unknown family) and
publish the protocol page with an empty record set. The page is content, not a
table, until a record validates — see §3 of this document for why no record can
validate today.

---

### 6 · World History — P0 — `TESTED`

**Where.** `nextjs/lib/world-read-model.ts:118` `WorldHistoryEntry` —
`version`, `manifestDigest`, `status` (`active | candidate | superseded`),
`activatedAt: ReadValue<string>`, `activationCount: ReadValue<number>`.
`:179` carries `history` on `WorldReadModel`. Rendered at
`nextjs/components/world-version-diff.tsx:127`, which prints
`entry.activatedAt.value` when the state is `read` and the literal string
`"not activated"` otherwise. The `ReadValue` wrapper is what keeps this row
honest: a version with no activation timestamp says so instead of showing a
plausible date.

**Backed by.** `nextjs/lib/world-read-model.test.ts`;
`nextjs/lib/world-version-diff.test.ts`; `nextjs/e2e/world-lifecycle.spec.ts`.
Server-side lifecycle: `supabase/migrations/0007_foundation_world_lifecycle.sql`
and `supabase/tests/foundation_world_lifecycle.sql` (pgTAP — **requires a live
Postgres and was not executed here or in the 2026-09-03 closure**).

**Nearest contract.** Lane contract §4.5.

**Smallest next step.** Surface it outside the Versions lens; the data contract
needs nothing.

---

### 7 · Compiler Contract page — P0 — `ABSENT`

**Where.** `nextjs/app/product/continuous-knowledge/page.tsx` is six lines and
calls `notFound()` at `:5`. It is already listed in
`nextjs/lib/brand-copy.test.ts:59` `COPY_SURFACES`, so copy rules will bind it
the moment it has copy — and it is **not** in `nextjs/app/sitemap.ts:10`.

**The vocabulary it must use already exists.** `nextjs/lib/capabilities.ts:76–77`
marks "Knowledge architecture" and "Selective recompilation" as `Direction`, the
second reading "Demonstrated above on fixture data. Not offered as a shipped
capability in this deployment." `nextjs/lib/claim-state.ts` defines
`QUALIFIED / DEMONSTRATED / RESEARCH FRONTIER / HUMAN GATE / BLOCKED /
STATUS UNKNOWN` with `AFFIRMATIVE_CLAIM_STATES = ["qualified"]`.

**Export reality, for the §8 interoperability list.** What actually leaves the
product today is Markdown, JSON, JSON-LD, Turtle, CSV and JSON Lines, in an
Ed25519-signed ZIP — `nextjs/README.md` line 9, `nextjs/lib/export-signing.ts:15`
(`algorithm: "Ed25519"`), `:73` `createExportSigner`, delivered by
`nextjs/app/api/collections/[id]/download/route.ts`. OWL 2, PROV-O and
OpenLineage are **not** exported (row 14). A page that lists all nine as
capabilities would be an overclaim.

**Backed by.** Nothing tests the page's content, because it has none. What is
tested is that the stub stays out of the public surface while it is a stub:
`nextjs/lib/production-hardening.test.ts:103` asserts the route is absent from
`llms.txt`, and `nextjs/app/robots.ts:5` disallows it. The `COPY_SURFACES` entry
at `nextjs/lib/brand-copy.test.ts:59` passes over a six-line file, so it is a
guard that will bind later, not evidence now — the distinction matters, because
a vacuous pass reads identically to a real one in a test report.

**Nearest contract.** Blueprint §7, §8, §45–§46, §63.

**Smallest next step.** Write the eight clauses with a state label per clause
taken from `capabilities.ts` / `claim-state.ts` vocabulary, and split the §8 list
into "exported today" (six formats, verifiable) and "direction" (three).

---

### 8 · GitHub trust surface — P0 — `ABSENT` on the site, `IMPLEMENTED` in the core

**Site repo at `9a7a93d`.** Root contains no `README.md`, no `LICENSE`, no
`RELEASE_POLICY.md`. `.github/` has `CODEOWNERS`, `dependabot.yml`, and the
workflows `ci.yml`, `codeql.yml`, `foundation-ocr-image.yml`, `launch-qa.yml`,
`operations-smoke.yml`. There is **no** `PULL_REQUEST_TEMPLATE.md`. `SECURITY.md`
exists. Two tags exist and both are operational safety points
(`safety/pre-integration-20260831-221008`, `safety/pre-rebase2-221712`) — there
is no version tag and no release. `.github/workflows/ci.yml:21–23` runs
`pnpm check`, `pnpm test`, `pnpm build`, and `:36–38` repeats the same three in a
second job.

**Core repo at `26bb892`.** Root has `README.md`, `LICENSE`, `SECURITY.md`,
`CONTRIBUTING.md`; `.github/` has `pull_request_template.md`, issue templates,
and seven workflows including `release-gates.yml` and `security.yml`. The
`LICENSE:3` reads "All rights reserved." — proprietary, no grant.

**Backed by.** Nothing tests governance posture; this row is file presence, and
most of its pointers are therefore paths without line numbers — a file that does
not exist has no line to cite. The three pointers above that *do* carry lines
(`ci.yml:21–23`, `:36–38`, core `LICENSE:3`) are the row's only content claims;
everything else is an existence claim, checked with `git ls-tree -r --name-only`
rather than by opening a file (see §6 for why that distinction matters here).

**Nearest contract.** Blueprint §43, §55, §64.

**Smallest next step.** The `github-trust` lane's three files. Branch protection
and the first tag are **founder actions** and must not be executed by an agent
(§5 below).

---

### 9 · Ontology Studio — P1 — `TESTED` as a viewer, `ABSENT` as a studio

**Where.** `nextjs/lib/world-read-model.ts:110` `WorldOntology` carries
`classes`, `properties`, `hierarchy: ReadValue<never>` and `exports` (path,
mediaType, sha256). Rendered by
`nextjs/components/world-ontology-viewer.tsx` (132 lines), mounted at
`nextjs/components/world-studio-ultimate.tsx:135`.

**Backed by.** `nextjs/lib/world-directory-and-ontology.test.ts` — `:99` counts
instances and evidence coverage per class, `:107` reports the domain and range
each property was actually used between, and `:116` *"refuses to invent a class
hierarchy the artifact does not contain"*. `hierarchy` being typed
`ReadValue<never>` is that refusal expressed in the type system.

**What is missing for "Studio".** No editing, no class/property authoring, no
validation run, no round-trip back into a compile. It is a lens over what a
compile produced.

**Nearest contract.** Blueprint §35; `docs/adr/ADR-002-akmp-1.0.md`.

**Smallest next step.** Decide whether "Studio" means authoring or validation —
they are different products. Validation is the cheaper one and has an existing
artifact to validate against (row 14).

---

### 10 · Conflict / authority resolution — P1 — `TESTED` as a library, `ABSENT` as a wired path

**Where.** `packages/cir-python/src/akc_cir/authority.py:48` `AuthorityClass`,
`:65` `SourceStatus`, `:161` `ResolutionRule`, `:229` `rank_claims`, `:263`
`resolve_authority`, `:329` `_explain`.

**Backed by.** `tests/unit/test_authority.py` (21 tests);
`tests/integration/test_governed_revision_consumption.py:40`
`test_governed_revision_marks_only_exact_prior_consumption_at_risk`, which
composes authority with `consumption_lineage` and `world_state`.

**Not wired.** `resolve_authority` has **no caller under `services/`** and none
in the site. The product's nearest behaviour is optimistic-concurrency conflict
detection in the review route — `nextjs/app/api/v1/reviews/route.ts:107`, "A
mismatch is a conflict, not a malformed request" — which is a stale-read guard,
not authority resolution or abstention.

**Nearest contract.** `CLAUDE.md`: "Never auto-resolve an authoritative conflict
on insufficient evidence."

**Smallest next step.** Call `resolve_authority` from the compile chain and
record its `Resolution` in the world manifest, so the world states which claim
won and why. Until a world carries that field, no surface can show it.

---

### 11 · Permission lineage — P1 — `ABSENT`

**What the words could be confused with, and are not.** Three neighbouring
things exist and none of them is permission lineage:

- **Tenant isolation** — Postgres RLS
  (`supabase/migrations/0001_tavonel_tenant_foundation.sql`,
  `0003_harden_rls_function_exposure.sql`,
  `0043_foundation_security_hardening.sql`) with `supabase/tests/tenant_rls.sql`
  and `tenant_rls_matrix.sql` (pgTAP, not executed here). RLS answers "may this
  tenant read this row".
- **Enterprise RBAC** — `nextjs/lib/enterprise-contracts.ts:7`
  `EnterprisePermission` and `nextjs/lib/enterprise-auth.ts`, which authorize
  calls to the enterprise control plane.
- **Credential revocation** — API keys and connections can be revoked
  (`nextjs/app/api/developer/keys/[id]/route.ts`,
  `nextjs/app/api/v1/connections/[id]/route.ts`).

**What is absent.** Nothing carries a source document's access control forward
into the claims compiled from it, so nothing can answer "which compiled claims
must stop being answerable because a source ACL changed". A world does not record
who may read each object, and no revoke path touches a compiled world.

**Backed by.** Nothing, and the shape of that nothing is the finding. Each of
the three neighbours above has its own test — tenant RLS by
`supabase/tests/tenant_rls.sql` and `tenant_rls_matrix.sql` (pgTAP, not executed
here), enterprise RBAC by `nextjs/lib/enterprise-contracts.test.ts:5`
("keeps security and billing duties separate"), credential revocation by
`nextjs/lib/developer-auth.test.ts:125` ("revokes API access when the key
creator leaves the pilot allowlist") — and not one of them asserts anything
about a *compiled claim*. The coverage is real and it stops at the compiler's
door. There is no test to cite because there is no behaviour to test.

**Nearest contract.** `CLAUDE.md`: "Never let an ACL revoke wait for a background
reindex." Blueprint §34.

**Smallest next step.** Write the contract before the code: what is the revoke
SLO, and what does Ask return for a claim whose only evidence is now unreadable —
refuse, or answer without it? That is a product decision, and it decides the
implementation.

---

### 12 · Point-in-time Ask — P1 — `TESTED` as a library, `ABSENT` as a wired path

**Where.** `packages/cir-python/src/akc_cir/temporal.py:62` `TemporalFact`,
`:115` `AsOfAnswer`, `:154` `TemporalTimeline` (bitemporal), `:279`
`replay_context`. `AsOfAnswer` carries `included_unknown` / `excluded_unknown`
so an answer that mixed facts with stated validity and facts without says so —
the same denominator discipline the evidence rules impose on rates.

**Backed by.** `tests/unit/test_temporal.py` (25 tests);
`tests/unit/test_knowledge_cicd_pipeline.py:232`
`test_the_change_carries_a_timeline_that_answers_both_clocks`.

**Not wired.** `replay_context` has no caller under `services/`. The product Ask
path reads the **active world only**: `nextjs/app/api/collections/[id]/ask/route.ts:78`
`getFoundationActiveWorld`, and `:151` refuses when the artifact's
`manifestDigest` does not match the active world's.
`nextjs/app/api/v1/world/[id]/ask/route.ts` re-exports that handler unchanged.
There is no `asOf` parameter anywhere in the request contract.

**Nearest contract.** Blueprint §33.

**Smallest next step.** Add `asOf` to the Ask contract and answer from the
manifest that was active at that moment — the world archive and the history
already exist (row 6); the retrieval index for a superseded world does not, so
the honest first version refuses rather than falling back to the active one.

---

### 13 · Connector deltas — P1 — `IMPLEMENTED` as pull, `ABSENT` as push

**Where.** `nextjs/lib/developer-contracts.ts:53` `ConnectionBatchInput` is a
cursor-chained delta contract: `batchId`, `previousCursorSha256`,
`nextCursorSha256`, `manifestSha256`, `events[]`. Applied by
`nextjs/app/api/v1/connections/[id]/sync/route.ts`, which returns
`CONNECTION_CURSOR_CONFLICT` (409) when the chain does not line up and
`CONNECTION_NOT_SYNCABLE` (423) when the connection is not in a syncable state.
OAuth connectors have their own sync route and a secret vault
(`supabase/migrations/0013_connector_oauth.sql`, `0016_oauth_secret_vault.sql`,
`0018_oauth_callback_state_binding.sql`).

**Not present.** No inbound webhook receiver for any connector — the only
webhook route in the repository is `nextjs/app/api/paddle/webhook/route.ts`.
Deltas are applied when a client pushes a batch; nothing subscribes to a source.

**Backed by.** `nextjs/lib/connector-contract.test.ts` and seven
`connector-oauth*.test.ts` files.

**Nearest contract.** The published OpenAPI document, not an internal type:
`nextjs/app/api/openapi/route.ts:209` declares `/connections/{id}/sync`, `:211`
names the operation `applyConnectionBatch` and `:212` binds it to the
`connections:sync` scope. So the cursor chain is a public commitment — which is
also why the missing half is a *push* problem and not a schema problem.
Blueprint §55 puts "connector delta/webhook" in the 30–90 day band.

**Smallest next step.** A freshness surface that shows, per connection, the
cursor's age — the data is already in the chain, and staleness is currently
invisible.

---

### 14 · OWL / SHACL / PROV-O adapters — P1 — partly `IMPLEMENTED`, mostly `ABSENT`

**What exists.** `packages/exporters/src/akc_exporters/jsonld.py:9`
`AKMP_CONTEXT` — a pinned JSON-LD 1.1 context over `dcterms:` and `schema:`;
`:38` `KNOWLEDGE_NOTE_SHACL` — a SHACL **NodeShape** in Turtle with `minCount`,
`datatype`, `nodeKind` and an `sh:in` enumeration for `akmp:origin`; `:87`
`context_jsonld`, `:100` `knowledge_jsonld`, `:164` `chunks_jsonl`.

**What that is and is not.** The SHACL shape is a *published constraint
document*. Nothing in either repository runs a SHACL engine over an export.
`tests/contract/test_contract_examples.py:48` asserts the shipped
`knowledge-note.shacl.ttl` is byte-identical to the constant — that tests
publication, not validation.

**Absent entirely.** OWL 2 ontology, PROV-O provenance vocabulary, OpenLineage.
`git grep -i` for `prov-o|openlineage|owl 2|owl2` over core `packages/`,
`services/` and `tests/` at `26bb892`, and over site `nextjs/{lib,app,components}`
at `origin/main`, returns nothing in either repository.

**Backed by.** `tests/unit/test_exporters_extended.py:245`;
`tests/contract/test_contract_examples.py:48`.

**Nearest contract.** `docs/adr/ADR-002-akmp-1.0.md`.

**Smallest next step.** Run the shape against the export in CI. A published
constraint nobody checks is a claim, and a validator turning it into a gate is
about a day's work.

---

### 15 · SSO / SCIM — P2 — `IMPLEMENTED` control plane, `BLOCKED` on a provider

**Where.** `nextjs/lib/enterprise-contracts.ts:11`
`IdentityProtocol = "saml" | "scim"`, `:75` rejects anything else, `:123` gates
each on `ENTERPRISE_SAML_PROVIDER_ENABLED` / `ENTERPRISE_SCIM_PROVIDER_ENABLED`.
`nextjs/app/api/enterprise/identity/route.ts:27` answers a successful `PUT` with
`activation: "PROVIDER_VERIFICATION_REQUIRED"` — configured is explicitly not
active. Schema: `supabase/migrations/0014_enterprise_control_plane.sql:11`
(`enterprise_identity_protocol` enum), `:65` `enterprise_identity_configs`,
`:103` `enterprise_audit_events`. Roles at `enterprise-contracts.ts:8–9`;
regions at `:10` (`us | eu | apac`) — a **policy field**, not a deployment.

**Why `BLOCKED` and not `IMPLEMENTED`.** No SAML assertion is ever verified and
no SCIM endpoint is served. The row cannot advance without an identity provider
and a founder decision on which one.

**Backed by.** `nextjs/lib/enterprise-contracts.test.ts:20` ("fails closed when
SAML metadata or its secret reference is missing") and `:26` ("accepts metadata
and an external secret reference without accepting secret fields"). Read them
for what they are: both test the *shape and refusals of a configuration record*.
Neither verifies a SAML assertion, because nothing in the repository does. A
reader who sees "SSO tests pass" and infers working SSO has inverted the result.

**Nearest contract.** `docs/enterprise/EXTERNAL_GATES.md:5` — the "Identity"
section, five named gates ending at `:11` with "Set
`ENTERPRISE_SAML_PROVIDER_ENABLED=true` … only after provider verification is
persisted", which is the same gate `enterprise-contracts.ts:123` reads at
runtime. `docs/enterprise/README.md:18` states the non-claim in the repository's
own words. Blueprint §41.

**Smallest next step.** None available to an agent. See §5.

---

### 16 · BYOK / VPC — P2 — `ABSENT`

No customer-managed key path, no dedicated-deployment path.
`EnterprisePolicyInput` carries `dedicatedDeploymentRequired: boolean`
(`nextjs/lib/enterprise-contracts.ts:109`) and `allowedRegions` — both are
*recorded policy*, with no enforcement plane behind them. Export signing uses one
deployment-level Ed25519 key (`nextjs/lib/export-signing.ts:73`), configured from
environment, never customer-supplied.

**Backed by.** `nextjs/lib/enterprise-contracts.test.ts:33` ("accepts bounded
governance policy and rejects no-region policies") — which tests that the policy
is *recorded and bounded*, and is the whole of the coverage. Nothing tests
enforcement, because there is no enforcement plane to test. The row is `ABSENT`
rather than `IMPLEMENTED` precisely because a validated policy field and a
customer-managed key are different objects.

**Nearest contract.** `docs/enterprise/EXTERNAL_GATES.md:17` ("Provision
physical US/EU/APAC storage and compute paths before offering region selection")
and `:18` ("Provision dedicated network, database, storage, worker and
observability resources before assigning a deployment reference"). The contract
already says the recorded field must not be sold as the capability, which is
what this row is checking. Blueprint §41.

**Smallest next step.** Do not build this before a design partner asks for it in
writing; blueprint §55 puts it in the 3–6 month band and the code agrees. If
anything is done sooner, it is making the two policy fields self-describing in
the console so a recorded preference cannot be read as a provisioned one.

---

### 17 · Enterprise compliance — P2 — `ABSENT`, and the guard against claiming it is `TESTED`

There is no SOC 2, ISO 27001 or HIPAA artifact in either repository, and no
certification is claimed anywhere. Two tests enforce that:
`nextjs/e2e/ultimate-blueprint.spec.ts:62` asserts the rendered body does not
match `/SOC 2 certified|ISO 27001 certified/i`, and
`nextjs/lib/category-guide.test.ts:124` asserts the page does not match
`/trusted by|customers|certified|SOC 2|ISO 27001/i`.

What does exist: `SECURITY.md`, `/security`, `/trust`, `/subprocessors`,
`.github/workflows/codeql.yml`, an audit-event table and an audit export route
(`nextjs/app/api/enterprise/audit/export/route.ts`).

**This row is a strength, recorded as one.** The absence is published rather than
hidden, and it is the absence a test protects.

**Backed by.** The two assertions named above —
`nextjs/e2e/ultimate-blueprint.spec.ts:62` and
`nextjs/lib/category-guide.test.ts:124`. Nothing backs the compliance posture
itself, because there is no posture: no audit, no certificate, no artifact.

**Nearest contract.** `docs/enterprise/EXTERNAL_GATES.md:26` — "Establish
security program ownership, evidence retention and SOC 2/ISO 27001 readiness
assessment" — with `docs/enterprise/README.md:18` naming SOC 2 and ISO 27001
among the things the package explicitly does not claim. Blueprint §40 and §41,
the latter closing with the rule this row is graded against: certification is
never implied before it is obtained.

**Smallest next step.** Make the guard general rather than per-page. Both
assertions are bound to one page each — `/security` and the category guide — so
a new page could claim SOC 2 and trip neither. `nextjs/lib/brand-copy.test.ts:63`
already runs a `BARRED` substring list over all 33 `COPY_SURFACES`, lowercased,
and that list holds six marketing phrases and no certification term. Adding
`"soc 2"` and `"iso 27001"` to it is two lines and passes today: no copy surface
currently contains either string. Do **not** add `"certified"` — it appears twice
in `nextjs/components/opening-film.tsx` (`:73`, `:385`) as fixture text inside a
synthetic document ("Total certified"), and that file is locked by lane contract
§1, so the broader term would fail the build against content nobody may edit.

---

### 18 · Domain packs — P3 — `TESTED` as a library, `ABSENT` as a surface

**Where.** `packages/domain-packs/src/akc_domain_packs/domain-packs.yaml`
declares six packs — `study_pack`, `research_pack`, `work_project_pack`,
`legal_contract_pack`, `technical_support_pack` (`:81`), `archive_book_pack` —
each with `note_types`, `knowledge_profile`, `export_profiles`, `quality_rules`
(`severity`, `autonomous_outcome`, `evaluator`) and `forbidden_claims`.
`registry.py:75` `DomainPack`, `:103` `DomainPackRegistry`, `:134`
`builtin_domain_packs`, `:190` `validate_user_schema` with `:129`
`SchemaPolicyError`. Seven blueprints ship beside them:
`corporate-filings`, `course-materials`, `generic-mixed-corpus`,
`legal-contracts`, `personal-knowledge`, `research-library` and
`technical-documentation`.

**Backed by.** `packages/domain-packs/tests/test_domain_packs.py`,
`test_blueprints.py`.

**Not surfaced.** No reference to any pack in the site repository.

**Nearest contract.** `docs/adr/ADR-005-quality-gate-boundaries.md` — the pack
`quality_rules` speak its vocabulary (`hard_fail`, `review_required`) and inherit
its rule that an override is permitted only through a versioned policy record
carrying corpus version, approval, effective date and rollback target. That
matters here: a domain pack is an override surface, so shipping one without a
policy record would breach the ADR. Blueprint §44 (the wedge) and §55 (6–12
month band).

**Smallest next step.** Bind the pack that already matches the wedge, rather
than building a pack surface. §44 names version-sensitive technical knowledge —
maintenance manuals, SOPs, change notices — and both halves already exist for
it: `technical_support_pack` (`domain-packs.yaml:81`, whose rules are
`command_verbatim` at `hard_fail` and `warning_evidence` at `review_required`)
and the `technical-documentation` blueprint, whose declared validators are
`source_coverage, procedure_order, version_identity, relation_evidence`
(`blueprints/technical-documentation/module.yaml:12`). `version_identity` and
`procedure_order` are the FP-200 revision problem written down as validators.
Run one of them over the `/explore` sample and see whether it holds. That is a
measurement, not a feature, and it is the cheapest thing on this row.

This row is further along than its P3 priority suggests, and the matrix records
that rather than smoothing it to match the plan — the wedge's own pack is
already in the tree, unused.

---

### 19 · Partner ecosystem — P3 — `ABSENT`

**Where.** Nowhere. No partner integration, destination adapter, certification
path or listing exists in either repository. The only occurrence of "partner" in
the site application is an enquiry category — `nextjs/app/api/contact/route.ts:14`,
`partnership: "Partnership"`.

**What a partner would build on, and it already exists.** The distribution
substrate is real: a published OpenAPI 3.1 document
(`nextjs/app/api/openapi/route.ts:30`), a CLI and an MCP server shipped as
static assets (`nextjs/public/developer/tavonel-cli.mjs`,
`nextjs/public/developer/tavonel-mcp.mjs`), and the portable export formats of
row 14. What is absent is a partner *programme* — an adapter contract, a
certification path, a listing — not the interface one would integrate against.
The distinction decides the cost of this row, and it is why `ABSENT` here is
cheaper to close than `ABSENT` on rows 11 or 16.

**Backed by.** Nothing tests a partner surface, because none exists. The
substrate under it is tested: `nextjs/lib/developer-distribution.test.ts:29`
("publishes one version across CLI, MCP, and the update channel") and `:44`
("completes a real MCP initialize and exposes read-only tools only") — note the
second, which fixes the current integration boundary at read-only.

**Nearest contract.** `docs/adr/ADR-002-akmp-1.0.md`, the portable knowledge
format a third party would consume, together with the OpenAPI document above.
Blueprint §55 places "partner ecosystem" in the 6–12 month band, beside "public
ontology/export spec" and "third-party interoperability".

**Smallest next step.** None yet, and the ordering is the reason rather than the
priority. §55 sequences the export spec ahead of the ecosystem, and row 14 shows
that spec is *published but never validated* — nothing in either repository runs
a SHACL engine over an export. A partner integrating against an unchecked spec
inherits every drift in it silently. Close row 14's validator first; that step
is already written there and is worth about a day.

---

## 3. Model Arena receipts mapped onto the §4.4 benchmark receipt

Lane contract §4.4 defines `BenchmarkReceipt` for the site's benchmark registry.
The Model Arena campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1` already emits
most of those fields. This section says which, so the benchmark lane knows what
it would have to invent versus what it could read.

**Three cautions, before the table.**

1. `research/model_arena_20260903/` is **git-untracked working-tree state** in
   the core repository. It is not part of `26bb892`. A receipt cited from an
   untracked path is not a receipt a third party can fetch.
2. The campaign is **incomplete**. `scores/<model>/<benchmark>/` contains
   `evaluator_input/` only; a recursive search under `scores/` finds **zero**
   `summary.json` and **zero** `scores.json`. Per `ARENA_CONTRACT.md:201`,
   `summary.json` is where the official metrics live. **No metric has been
   scored, so there is nothing to publish and no `metrics[]` to fill.**
3. Nothing in this section is a benchmark result, and nothing here may be
   published. Publishing any arena number is a founder decision (§5).

| §4.4 field | Arena source | Present? |
|---|---|---|
| `datasetName` | `campaign_manifest.json` → `benchmarks.<id>.dataset_repository` (`llamaindex/ParseBench`, `opendatalab/OmniDocBench`, `allenai/olmOCR-bench`) | yes |
| `datasetVersion` | `benchmarks.<id>.dataset_revision` (a git sha) | yes |
| `corpusDigest` | `benchmarks.<id>.dataset_manifest_sha256` and `staged_manifest_content_sha256`; campaign-level `source_manifest_sha256` | yes |
| `denominator` | `benchmarks.<id>.sample_count` per benchmark; `total_samples` campaign-wide; QA report `sample_count_exact` check compares observed to the manifest | yes — population **and** count |
| `modelId` | `model_registry.json` → `models.<key>.repo` | yes |
| `modelRevision` | `models.<key>.revision`, echoed in each receipt as `model_revision` | yes |
| `inputMode` | `models.<key>.prompt_kind` plus `official_inference_config` (`base_size`, `crop_mode`, entrypoint) | partial — needs a normalised vocabulary |
| `promptDigest` | `models.<key>.prompt_sha256`, resolved from `prompt_registry/sha256.json` | yes |
| `configDigest` | `models.<key>.inference_config_sha256` and `official_inference_config_sha256`; campaign `constants_sha256` | yes |
| `compilerVersion` | — no field. Arena measures parsers, not the compiler | **absent** |
| `hardware` | canary receipt `gpu_type`, `gpu_total_vram_mb`, `peak_vram_mb`, `replica_count` | yes |
| `gpu` | canary receipt `gpu_type` | yes |
| `runtime` | canary receipt `runtime_image_digest`, `runtime_mode`, `base_image` (image + digest) | yes |
| `priceSnapshot` | canary receipt `price_snapshot_sha256`, `selected_gpu_hourly_rate_usd`; `cost/campaign-cost.json`, `cost/pod_ledger.jsonl` | yes |
| `rawResultDigest` | `frozen_outputs/<model>/` (per `ARENA_CONTRACT.md:185`); one tree carries an `_INVALIDATED_<ts>` sibling | partial — frozen, and one invalidation must be explained |
| `worldDigest` | — arena does not compile a World | **absent** |
| `runReceiptDigest` | `receipts/<kind>-<model>.json`; `receipts/manifest-hash-cache.json`; `authorization_receipt_sha256` per receipt | yes |
| `date` | `started_at` / `finished_at` per receipt; `campaign_manifest.created_at` | yes |
| `metrics[]` | `scores/<model>/<benchmark>/summary.json` | **absent — none exist yet** |
| `comparisonBasis` | `model_registry.json` → `models.<key>.historical_evidence` is explicitly third-party and carries a `scope_warning`; `historical_evaluator_pins` pins the evaluator revision used for those | maps to `"quoted"`, never `"same_condition"` |
| `publishedFailures[]` | `receipts/incidents/`, `receipts/waivers/`, per-receipt `fail_reasons` / `empty_output_pages`, `FOUNDER_EXCLUDE_INFINITY_2026-09-04.md`. `ARENA_CONTRACT.md:139` also declares `failures/errors.jsonl`, and that directory is **empty** | yes, with one contract path unwritten |

**What this shows.** Of the twenty-one fields §4.4 requires: fourteen have a
direct source, one has a source with a gap (`publishedFailures[]`), two are
partial (`inputMode`, `rawResultDigest`), one can only ever be `"quoted"`
(`comparisonBasis`), and three are absent.

The three absent ones are the three that matter most. `compilerVersion` and
`worldDigest` are missing because the arena measures **parsers**, not the
Knowledge Compiler — it never compiles a World, so there is no world digest to
record. `metrics[]` is missing because the campaign has not produced a score. A
§4.4 record built from these receipts today would be a parser benchmark wearing a
compiler benchmark's schema, and §37's whole point is that those are different
things.

**Consequence for the benchmarks lane.** `qualifiedBenchmarkRecords()` returning
empty on this branch is the correct state, not a placeholder. The page publishes
the protocol.

---

## 4. §69 acceptance gate, graded line by line

Blueprint §69 is a sixteen-line checklist. None is checked. Three are close.

| # | §69 line | Grade | Why, in one line |
|---|---|---|---|
| 1 | 30 sec category comprehension | `ABSENT` (unmeasured) | No comprehension test exists; `nextjs/lib/category-guide.test.ts` checks copy discipline, not comprehension. |
| 2 | Landing film explains source→world | `IMPLEMENTED` | The films exist and are locked (`nextjs/app/film-4/page.tsx`, `components/opening-film-4.tsx`); nothing measures that a viewer draws the conclusion. |
| 3 | Explore proves world→source | `TESTED` | `/explore` walks object → evidence → page region over a real compile whose digest is frozen (`lib/explore-sample.ts:34`, `:90`); the e2e specs assert the walk. |
| 4 | Explore proves source change→world change | `ABSENT` | One world, one revision. Row 1 above. |
| 5 | Workspace handles same semantics with real user data | `IMPLEMENTED` | World Studio's seven lenses read a `WorldReadModel` from a real compile; no test drives the workspace over a real tenant's corpus. |
| 6 | selective recompile vs full rebuild equivalence demonstrated | `TESTED` | Row 4. Fixture graphs, no corpus receipt, and nothing on a public surface. |
| 7 | benchmark public | `ABSENT` | `/benchmarks` 404s; zero scored arena metrics. Rows 5 and §3. |
| 8 | exact evidence public | `TESTED` | `/explore` and `/evidence` publish page and bbox from the compile; the digest guard makes a drifted world fail the build. **The strongest line on this list.** |
| 9 | portable signed export public | `IMPLEMENTED` | Ed25519-signed six-format ZIP with an offline verifier (`pnpm verify:export`), but the endpoint is authenticated and pilot-gated, so "public" is not yet true. |
| 10 | model backend swappable | `IMPLEMENTED` | `packages/router/src/akc_router/providers.py:74` `ParserProvider` / `:85` `KnowledgeProvider` protocols and `:105` `ProviderRegistry`, under `docs/adr/ADR-003-provider-abstraction-model-policy.md`; no shadow-to-canary swap has been performed. |
| 11 | identity ambiguity fail-closed | `TESTED` | `akc_cir/identity_quarantine.py:146` `build_quarantine`, `tests/unit/test_identity.py` (47 tests). **Every threshold is uncalibrated** — `CalibrationTable.calibrated` is `False` — so "fail-closed" is a shape, not a measured rate. |
| 12 | stale knowledge cannot be silently promoted | `TESTED` | `akc_cir/promotion_gate.py:182`, `akc_cir/world_state.py:66` `PublishRefused`, `supabase/migrations/0021_retrieval_compile_run_active_world_guard.sql`, and `capabilities.ts:61` keeps promotion closed as an explicit human decision. The pgTAP half was not executed. |
| 13 | permission lineage implemented | `ABSENT` | Row 11. |
| 14 | enterprise auth / audit path | `IMPLEMENTED` | Control plane, RBAC roles, audit table and export route exist; SSO/SCIM need a provider (row 15) and the pgTAP RLS suites were not executed. |
| 15 | GitHub/release posture trustworthy | `ABSENT` | Site repo has no README, no LICENSE, no PR template, no release tag, and branch protection is unverified. Row 8. |
| 16 | no fabricated metric/certification/customer claim | `TESTED` | `nextjs/lib/brand-copy.test.ts` bars the phrases and overclaims; `e2e/ultimate-blueprint.spec.ts:62` and `lib/category-guide.test.ts:124` bar certification and customer claims; `capabilities.ts` is fail-closed by construction. |

**Score: 0 of 16 checked.** Lines 3, 8 and 16 are `TESTED` and would survive
scrutiny today.

The five `ABSENT`s are not the same kind of absent, and the distinction decides
what to do about them. Line 1 is absent only in that **nothing measures it** —
the landing exists and may well achieve 30-second comprehension; no instrument
says. Lines 4, 7, 13 and 15 are absent in that **the thing does not exist**, and
three of those four are P0 rows already assigned to lanes in this campaign.

**On §61's other axes.** *Product*: raw-source-to-knowledge, exact evidence,
temporal knowledge and portable export are `TESTED` or better; ontology is a
viewer; conflict/abstention and permissions are not wired. *Proof*: a public
benchmark, an independent artifact verification and a customer case are all
`ABSENT`; research transparency is the one that holds, and it holds because the
repository publishes its failures (`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md`,
the 36.9 % low-quality-scan row, blind quality detection published as *not
supported*). *UX*: none of the four timing criteria is measured by anything.
*Enterprise*: identity/permission/audit is the control plane of row 15 with no
provider behind it; private deployment, SSO/SCIM and retention are `ABSENT`;
security posture is `SECURITY.md`, CodeQL and the certification guard of row 17.
*Ecosystem*: this axis is stronger than the rest — a versioned `/api/v1` surface,
six export formats signed with Ed25519, an offline verifier CLI
(`nextjs/scripts/verify-signed-export.mjs`, `pnpm verify:export`) and a read-only
stdio MCP server shipped as readable source
(`nextjs/public/developer/tavonel-mcp.mjs`, 400 lines, with
`nextjs/lib/mcp-server.test.ts`) that refuses to start if any tool is not a read.
Partner destinations are `ABSENT`.

---

## 5. Founder decisions this matrix could not make

Each of these blocks a row above, and none is an agent's call under `CLAUDE.md`
or lane contract §7.

1. **Branch strategy for `feature/revision-compile-v1`.** It is local-only, 87
   commits behind `origin/main`, and holds the only product-side revision route.
   Rebase, cherry-pick or abandon — row 3 cannot advance until this is answered.
2. **Whether to publish any Model Arena figure, and when.** The campaign is
   incomplete and untracked; §3 explains what a record would and would not say.
3. **Main-branch protection and the first release tag** on the site repository
   (row 8). The `github-trust` lane writes the `gh api` commands; running them is
   a founder action.
4. **Adding a `LICENSE` to the site repository.** The core repository publishes
   "All rights reserved"; the site publishes nothing. Both are decisions.
5. **The identity provider for SSO/SCIM** (row 15), which decides whether the
   control plane's `PROVIDER_VERIFICATION_REQUIRED` can ever clear.
6. **The revoke SLO and Ask's behaviour on revoked evidence** (row 11) — refuse,
   or answer without the revoked evidence. The contract decides the code.
7. **Calibration corpus for the identity thresholds** (§69 line 11).
   `CalibrationTable.calibrated` refuses to be set true without one being named.
8. **Whether "Ontology Studio" means authoring or validation** (row 9).

---

## 6. How the citations in this file were checked

A gap matrix is worth nothing if its pointers drift, and a `path:line` that does
not resolve is a fabricated citation whether or not anyone meant it. Every
pointer in this document was therefore machine-checked before it was committed:
241 assertions — each `path:line` must exist **and** the line must contain the
text this document says is there, each "exists" claim must resolve, each "absent"
claim must not, and §3's two load-bearing absences (an empty `failures/`, zero
scored `summary.json`) are asserted rather than assumed, so a later campaign run
turns this file red instead of leaving it quietly wrong. Core paths were read
from the worktree at `26bb892`; site paths with `git show origin/main:<path>`;
arena paths from the untracked working tree, which is why they are marked as
such throughout §3.

Four of those assertions are *computed*, not merely looked up, because two rows
make claims that a lookup cannot defend:

- Row 18 enumerates six pack ids and seven blueprint directories. The check
  compares the enumeration against the actual directory listing, so a pack added
  or renamed upstream fails the check instead of quietly making the row
  incomplete — which is the defect this round was fixing.
- Row 17's next step asserts that adding `"soc 2"` and `"iso 27001"` to
  `BARRED` passes today, and that adding `"certified"` does not. The check reads
  all 33 `COPY_SURFACES`, confirms none contains the first two, and confirms the
  third hits exactly one file — `components/opening-film.tsx`, which lane
  contract §1 locks. A recommendation that would break the build is worth
  catching before someone follows it.

The check found four errors on its first run at 185 assertions, and all four are
fixed above: three line numbers had drifted by one or two lines, and one absence
was reported as a presence. The 56 assertions added in the second round — the
per-row elements that completed rows 5, 7, 8, 11, 13 and 15–19 against lane
contract §5 — passed on their first run, which is the expected outcome of writing
the pointer and the check together rather than the pointer first. The error worth
recording is from the first round, because it is a trap for anyone verifying this
file by hand:

> `git show origin/main:nextjs/app/api/collections/[id]/revise/route.ts`
> **exits 0 and prints nothing** when the path does not exist. The bracket is
> read as a pathspec wildcard that matched nothing, so the exit code says
> "success". Existence must be decided from `git ls-tree -r --name-only`, never
> from that exit code.

The checker itself is not committed — this lane owns exactly one file — so the
check is described here rather than shipped. It is a table of
`(repo, path, line, expected substring)` tuples, a list of paths that must
exist, a list that must not, and the four computed assertions above; anyone
re-deriving it should start from the `git ls-tree` rule, because that is the
part that is easy to get wrong and silent when you do. Committing it as a repo
gate is worth doing and needs an ownership grant this lane does not have.

---

## 7. What this document does not say

- It does not say any suite passes **now**. It names test paths and cites the
  committed scope receipt with its timestamp and its known gap (§1).
- It does not grade the pgTAP suites (`supabase/tests/*.sql`). They require a
  live Postgres and were not executed here or in the 2026-09-03 closure.
- It does not grade the site's runtime behaviour. Everything site-side was read
  from `git show origin/main:<path>`; no browser was opened.
- It does not restate any arena metric, cost or vendor score as a result. There
  are no scored metrics to restate (§3).
- It supersedes `docs/audit/TAVONEL_RESEARCH_PRODUCT_CLOSURE_FINAL_2026-09-03.md`
  on exactly two rows — claim 1 "v1 compile" and the production `SourceResolver`,
  both closed by `cfe46b8` — and on nothing else.
