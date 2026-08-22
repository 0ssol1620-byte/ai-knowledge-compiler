# V4 Migration Matrix

*Masterplan v4.0 PHASE 0 deliverable. Written 2026-08-10 against
`5999baf8175288f34fb476b4e0b880037239c60c`.*

Source of truth: `docs/north-star/TAVONEL_MASTERPLAN_v4.0.md`
(sha256 `c996c372ca4702af1f11a67da61fee90c54c332b9238a89f0e1df7942d1b5e5a`),
PART 20 for the categories and PART 31 for the classification vocabulary.

Current-state baseline is `docs/architecture/v31-phase-gap-matrix.md`. That file
records what exists; this one records what happens to it. Where the two disagree
about existence, the gap matrix is re-verified against the tree, not overruled.

---

## Vocabulary

**Action** (PART 20.1) — KEEP · ADAPT · REPLACE · BUILD · DEPRECATE · DEFER.

**Status** (PART 31 step 5) — one of:

| Status | Means |
|---|---|
| `PROVEN` | Code exists **and** a benchmark/evidence receipt measures it |
| `IMPLEMENTED_NOT_PROVEN` | Code and tests exist; nothing measures it on a corpus |
| `PARTIAL` | Some of the requirement exists; named parts do not |
| `MISSING` | No implementation |
| `CONFLICTING` | Two implementations or two specs disagree; needs an ADR |
| `BLOCKED_LICENSE` | Cannot ship on current licence terms |
| `DEFERRED` | Deliberately not built; gated on demand or governance |

The distinction that matters is `PROVEN` vs `IMPLEMENTED_NOT_PROVEN`. Almost
everything this repository calls "Built" is the second one. Tests prove the code
does what its author intended. They do not prove the threshold is right. **No
threshold in this codebase is calibrated** — `CalibrationTable.calibrated` is
`False` and refuses to be set true without naming a corpus.

---

## Protected Core (PART 31)

Not replaceable without a same-condition no-regression benchmark. Verified
present in the tree at this commit:

| Module | Path | Status |
|---|---|---|
| `akc_cir.inspection` | `packages/cir-python/src/akc_cir/inspection.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.recovery_policy` | `packages/cir-python/src/akc_cir/recovery_policy.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.reconciler` | `packages/cir-python/src/akc_cir/reconciler.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.identity` | `packages/cir-python/src/akc_cir/identity.py` | IMPLEMENTED_NOT_PROVEN |
| entity / authority / temporal | `entity.py`, `authority.py`, `temporal.py` | PARTIAL — review queue absent |
| `akc_cir.semantic_diff` | `packages/cir-python/src/akc_cir/semantic_diff.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.dependency` | `packages/cir-python/src/akc_cir/dependency.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.recompilation` | `packages/cir-python/src/akc_cir/recompilation.py` | IMPLEMENTED_NOT_PROVEN |
| `akc_cir.world_state` | `packages/cir-python/src/akc_cir/world_state.py` | IMPLEMENTED_NOT_PROVEN |
| evidence artifacts + claim receipts | `docs/evidence/**` | **PROVEN** — 14/14 hashes verify |

The evidence artifacts are the only row that reads `PROVEN`, and they are proven
as *artifacts*, not as product behaviour: the campaign measured MinerU 3.4.4 plus
the recovery runtime, not the compiler core listed above it.

---

## Module matrix

PART 20.2's rows, resolved to paths and given a status.

| # | Module | Path | Action | Status | Note |
|---|---|---|---|---|---|
| 1 | `akc_cir.inspection` | `packages/cir-python/src/akc_cir/inspection.py` | KEEP/ADAPT | IMPLEMENTED_NOT_PROVEN | v4 finding schema + event wiring in Phase 1/6 |
| 2 | `akc_cir.recovery_policy` | `.../recovery_policy.py` | KEEP/ADAPT | IMPLEMENTED_NOT_PROVEN | must split operational vs semantic actions (PART 8.6) |
| 3 | `akc_cir.reconciler` | `.../reconciler.py` | KEEP/ADAPT | IMPLEMENTED_NOT_PROVEN | needs cross-page benchmark + provenance receipt |
| 4 | `akc_cir.identity` | `.../identity.py` | KEEP | IMPLEMENTED_NOT_PROVEN | **threshold change requires corpus calibration first** |
| 5 | entity / authority / temporal | `entity.py` `authority.py` `temporal.py` `trust.py` | ADAPT | PARTIAL | review queue, API and world-state integration absent |
| 6 | semantic_diff / dependency | `semantic_diff.py` `dependency.py` | KEEP/ADAPT | IMPLEMENTED_NOT_PROVEN | typed event + impact reason path to add |
| 7 | recompilation / world_state | `recompilation.py` `world_state.py` | KEEP/ADAPT | IMPLEMENTED_NOT_PROVEN | atomic publish + rollback gates to add |
| 8 | legacy routing | `packages/parallel-runtime/.../routing.py`, `packages/router/` | KEEP LEGACY → REPLACE | PARTIAL | v4 shadow router, 0→5→25→50→100 rollout |
| 9 | campaign parser harness | `benchmark/runners/`, `benchmark/runpod_eval/` | ADAPT | PARTIAL | to production adapter + registry contract |
| 10 | evidence page | `apps/web/src/data/claims/`, `apps/web/src/lib/claims.ts` | KEEP DATA / REPLACE UX | PROVEN (data) / PARTIAL (UX) | claims-pack renderer |
| 11 | landing | `apps/web/src/app/(marketing)/` | REPLACE | PARTIAL | cinematic narrative, PART 15 |
| 12 | upload | `services/api/`, `apps/web` upload path | ADAPT/REPLACE | PARTIAL | R2 multipart + progressive, PART 4 |
| 13 | retrieval / API / MCP | `packages/retrieval/` (partial), no MCP | BUILD | PARTIAL / MISSING | permission-first; MCP read-only is MISSING |
| 14 | Health Scan / billing | — | BUILD | MISSING | payment *plumbing* exists (`AKC_PAYMENT_*`, migration 0009); the metered ledger does not |
| 15 | connectors | — | BUILD | MISSING | Drive first, then storage |
| 16 | decision replay / write MCP | — | DEFER | DEFERRED | gated on paid demand + governance |

### Corrections to PART 20.2 found while resolving paths

- **Row 13 is not uniformly BUILD.** `packages/retrieval/` exists and migration
  `0024_production_hybrid_retrieval` is applied, so hybrid retrieval is PARTIAL,
  not absent. What is missing is the *permission-first* filter order of PART 13.3.
  Treating it as greenfield would discard applied schema.
- **Row 14 is not uniformly MISSING.** Migration `0009_payment_credit_purchase`
  and the `AKC_PAYMENT_*` variable family exist, and the provider is abstract
  rather than Stripe-specific. PART 18.7 names a Stripe adapter; the repo has a
  provider-agnostic seam. This is a **CONFLICTING** row pending an ADR — see below.

---

## Conflicts requiring an ADR before the phase that touches them

| ID | Conflict | Phase | Resolution owed |
|---|---|---|---|
| C-1 | PART 18.7 says "Stripe adapter"; repo has provider-agnostic `AKC_PAYMENT_PROVIDER` with a Toss-shaped webhook contract (migration 0009) | 16 | ADR: keep the abstraction and name Stripe one implementation, or collapse to Stripe |
| C-2 | PART 2/APPENDIX B assume Cloudflare Queues bindings; repo runs a PostgreSQL outbox/dispatch scheduler (`services/scheduler`, migrations 0002/0008) | 1, 5 | ADR: the at-least-once contract is satisfied by the existing outbox. Adding Queues needs a measured bottleneck (PART 31 forbids new infra without one) |
| C-3 | APPENDIX B names `R2_*`; repo uses S3-compatible `AKC_S3_*` against `AKC_S3_ENDPOINT_URL` | 0, 2 | Naming only — R2 *is* the S3 endpoint. Recorded so no one "adds R2 support" that already exists |
| C-4 | v4 PART 15 reinstates a cinematic hero; `DEPENDENCY_LICENSES.md` still records the W0 removal of `three`/R3F as current | 13 | `CLAUDE.md` already reverses this (2026-08-09). The licence register is stale and is corrected in `V4_LICENSE_AND_SUPPLY_CHAIN.md` |
| C-5 | Two `0023_*` migration files exist (`0023_trial_ingest`, `0023_v4_collections`) | 1 | Not a conflict in fact — the chain verifies single-head over 33 revisions. Recorded because the duplicated *prefix* invites one |

---

## X1–X16 closure placement

PART 1.9 maps v3.1's closure sections onto v4 modules. All sixteen remain
`MISSING` at this commit; the gap matrix already says so. The v4 change is
*where* they land, not whether they exist:

| v3.1 gap | v4 module | Phase | Status |
|---|---|---|---|
| X1 Semantic Model Gateway | Model Registry + Task Gateway | 3 | MISSING |
| X2 Embedding / reranking | Retrieval Contract | 11 | MISSING |
| X3 Structure-aware chunking | Knowledge Packaging Compiler | 8 | MISSING |
| X4 Office dual path | Secure Preflight + Reconciler | 2, 3 | MISSING |
| X5 Dedup / revision graph | Source Identity / Revision Graph | 2 | PARTIAL (0016/0017 exist) |
| X6 Connector change / ACL | Connector Control Plane | 14 | MISSING |
| X7 Multi-tenant GPU scheduler | Execution Scheduler / FinOps | 5 | PARTIAL |
| X8 E2E answer / citation eval | Benchmark OS | 7 | MISSING |
| X9 Blueprint compiler / exports | Deterministic Target Compiler | 8 | PARTIAL (`packages/exporters`) |
| X10 API / stream / webhooks / SDK | Public Platform Surface | 14 | MISSING |
| X11 Credits / billing | Usage Ledger + Billing Adapter | 16 | PARTIAL — see C-1 |
| X12 Human review / active learning | Review Queue + Outcome Feedback | 6, 9 | MISSING |
| X13 Zero-downtime release | Compatibility / Canary / Pointer Swap | 1 | PARTIAL |
| X14 Competitive checklist | Same-condition Comparator Harness | 7 | MISSING |
| X15 GTM | Evidence Funnel + Health Scan | 12, 16 | PARTIAL (claims pack exists) |
| X16 Solo-founder path | AI-Native Software Factory | 0 | PARTIAL (`.claude/`, `.agents/` exist) |

---

## Feature flags

PART 20.4 names fifteen flags. The repository already has a tenant-scoped,
cohort-hashed, fail-closed flag resolver at
`services/api/src/akc_api/feature_flags.py` with a `FeatureFlag` table. It
resolves global rows first and lets a tenant row win, returns `False` when no
row exists, and rejects unknown condition keys.

**No new framework is needed.** The v4 flags are rows, and are registered in
`docs/audit/V4_FEATURE_FLAGS.md` with their owning phase. Three flag keys already
exist for other features (`ontology_export`, `existing_vault_merge`,
`chart_description`) and are untouched.

---

## The rule that governs every REPLACE row

PART 20.3, quoted because it is the one that gets skipped under time pressure:

```text
compatibility contract → shadow → benchmark → canary → rollout → deprecate
```

No row above may go straight to rollout. The legacy router in particular stays
live and authoritative until the v4 router has run in shadow against it and a
benchmark says it is not worse.
