# V5 Migration Matrix

*Masterplan v5.0 PHASE 0 deliverable ("v4/v5 migration matrix"). Written
2026-08-11 against `9b5edd9`.*

Source of truth: `docs/north-star/TAVONEL_MASTERPLAN_v5.0.md`
(sha256 `35e6bcec1ed5bab30b86478d8d44e20e66d71adb1bcf9f921804cf99f06b19b7`),
PART 22 for the matrix and PART 34 for the operating rules.

This file records **what v5 changes**. `docs/audit/V4_MIGRATION_MATRIX.md`
remains valid for everything v5 does not contradict — v5 supersedes v4 only on
phase order, router, model evaluation and benchmark. The module actions, the
status vocabulary and the C-1…C-5 conflict register there still stand.

---

## What actually changed

### 1. A new core system: the Model Arena

v4 designed the Adaptive Economic Router. v5 says the router has nothing to
route on until same-condition evidence exists, and makes producing that evidence
a first-class system.

```text
Representative Documents → Same-condition Model Arena
  → Model × Slice × Quality × Cost × Latency × Failure × Reproducibility
  → Document Performance Map → Router Oracle Dataset
  → Shadow Router → Canary → Champion/Challenger
```

| Module | v4 | v5 | Status |
|---|---|---|---|
| Model Arena / Evaluation OS | not a named system | **BUILD BEFORE ACTIVE ROUTER** | MISSING |
| Document Performance Map | Phase 7 artifact | promoted to core moat | MISSING |
| Router Oracle Dataset | Phase 7 artifact | promoted to core moat | MISSING |

### 2. Phase order

The renumbering is not cosmetic. The router moved *behind* the evidence that
justifies it.

| v4 | v5 | Change |
|---|---|---|
| 0 Baseline | 0 Baseline | same |
| 1 Contracts | 1 Contracts **+ Arena schemas** | **scope grew** |
| 2 Ingestion | 2 Ingestion | same |
| 3 Renderer/Profiler/Registry | 3 Renderer/Profiler/Registry | same |
| **4 Shadow Router** | **4 Arena Harness + Prompt Calibration** | **replaced** |
| 5 Parser/Scheduler/RunPod | **5 Arena v1 — 1,000 pages** | **replaced** |
| — | **6 Execution Planner + Shadow Router** | router moved from 4 → 6 |
| — | 7 Scheduler / RunPod / **Batch lanes** | batch/bulk is new |
| 6 Inspector/Recovery | 8 Recovery/Review | +2 |
| 7 Benchmark OS | **17** Full 5,132 + DART/SEC campaign | moved far later |
| 8–18 | 9–20 | shifted |

Two things follow. **Phase 1's scope grew** — Arena schemas are now part of the
contract lock, so a Phase 1 plan written against v4 is incomplete. And
**Benchmark OS moved from Phase 7 to Phase 17**, because the Arena now does at
Phase 4–5 what v4 expected the Benchmark OS to do later.

### 3. Evaluation fairness becomes normative

v5 PART 9 splits evaluation into four tracks that must not be mixed:

| Track | What it holds constant |
|---|---|
| **I** — Standardized page-image | every model gets the same rendered image |
| **N** — Native provider best-practice | each provider gets its own preferred input (native PDF etc.) |
| **P** — Provider-optimized prompt | prompts tuned per provider, frozen before the run |
| **B** — Batch/bulk economics | batch pricing and behaviour, tested for equivalence first |

Track I and Track N answer different questions and a single number across both
is not a result. Batch and interactive may not be treated as one execution path
until equivalence is measured.

### 4. Stage-gated spend

v5 PART 31 replaces "run the corpus" with "what uncertainty does the next $100
buy?":

```text
Stage 0   50 pages × candidates      capability + cost smoke
Stage 1   200 pages × all candidates screening, drop dominated models
Stage 2   1,000-page Arena           Pareto survivors + controls + TAVONEL adaptive
Stage 3   5,132 full public          2–4 survivor paths only
Stage 4   DART/SEC expansion         slices with real enterprise value
```

Full-run approval only after the screening report. Detail and the current
blockers are in `docs/audit/V5_COST_BUDGET.md`.

---

## Corpus (PART 8.2) — what exists here today

Arena v1 is exactly 1,000 pages unless a receipt documents a revision.

| Block | Pages | Repository status |
|---|---:|---|
| A. Public Ground Truth | 400 | **Partial** — the 5,132-doc campaign used olmOCR-bench / OmniDocBench / ParseBench; stratified 400-page extraction not done |
| B. Real Corporate (DART 150 + SEC 150) | 300 | **Missing** — `benchmark/acquire_dart.py` exists and a DART key is available; SEC acquisition absent |
| C. TAVONEL Failure Zoo | 200 | **Partial** — the campaign's 1,797 recovery-required documents are the raw material; not classified into the nine failure slices |
| D. Clean Control | 100 | **Missing** |
| Prompt calibration set (separate) | 100 | **Missing** — must not overlap Arena document families |

Full corpus plan in `docs/audit/V5_ARENA_CORPUS.md`.

---

## Feature flags

v5 PART 22 adds eleven keys to v4's fifteen. Same resolver
(`services/api/src/akc_api/feature_flags.py`), same fail-closed semantics; the
`rollout_percent = 0` inversion that would have broken the ladder was fixed at
`9b5edd9`. Registered in `docs/audit/V4_FEATURE_FLAGS.md`.

```text
V5_ARENA               V5_ROUTER_SHADOW          V5_API_PROVIDER_OPENAI
V5_ARENA_BATCH         V5_ROUTER_CANARY          V5_API_PROVIDER_ANTHROPIC
V5_DPM                                           V5_API_PROVIDER_GEMINI
V5_ORACLE_DATASET                                V5_LOCAL_PADDLE
                                                 V5_LOCAL_DEEPSEEK_OCR2
```

`V5_ROUTER_SHADOW` and `V5_ROUTER_CANARY` supersede v4's `V4_SHADOW_ROUTER` /
`V4_ROUTE_EXECUTION`. Neither v4 key has a row yet, so nothing is stranded — the
v4 pair is withdrawn from the registry rather than deprecated.

---

## New database surface (PART 3.4)

Four tables, none of which exist:

| Table | Holds |
|---|---|
| `arena_campaigns` | corpus manifest sha256, protocol version, status |
| `arena_cases` | family, split (CALIBRATION/EVAL/ROUTER_TRAIN/ROUTER_HOLDOUT), slice labels, truth ref |
| `arena_runs` | exact model revision, input track, prompt track, settings hash, raw + normalized artifacts, actual cost |
| `arena_scores` | evaluator id + revision, metric, value, receipt ref |

**PART 3.5 is the row that must not be lost:** production route outcomes live in
a *separate namespace* from the Arena, and customer data is never automatically
folded into the benchmark corpus.

---

## Conflicts v5 introduces or resolves

| ID | Conflict | Resolution owed |
|---|---|---|
| **C-6** | v5 PART 7.2 pins a 2026-08-11 model catalogue (`gpt-5.6-*`, Claude Sonnet/Opus 5 + Haiku 4.5, Gemini Batch at 50%). The repo's `infra/model-registry/models.yaml` has none of the API families — 16 local entries only | Phase 3 extends the registry with the `license_state`/`lifecycle`/`batch_supported`/`native_pdf_supported` fields of PART 7.3. **v5's own rule: re-query prices at run time; the document's numbers are not production price truth** |
| **C-7** | v5 requires OpenAI / Anthropic / Gemini API access for the General Multimodal families. The available credential set has no key for any of them | **Founder decision + missing secret.** Blocks Phase 4–5 for API families; local families are unblocked. See `V5_COST_BUDGET.md` |
| **C-8** | v4's `V4_SHADOW_ROUTER` / `V4_ROUTE_EXECUTION` vs v5's `V5_ROUTER_SHADOW` / `V5_ROUTER_CANARY` | Withdraw the v4 pair — no rows exist |
| C-2 (carried) | Cloudflare Queues vs the existing PostgreSQL outbox | Unchanged by v5; PART 34 still says at-least-once + idempotent consumers without naming a transport. ADR-007 draft stands |
| C-1, C-5 (carried) | payment provider vocabulary; migration numbering | Unchanged by v5 |

---

## What did **not** change

Worth stating, because a new North Star invites over-reading:

- The protected core list is identical.
- Every absolute preservation rule is identical — FOLYNTA artifact names and
  hashes, 99.98% is completion not accuracy, 99.94% carries its 1,797
  denominator, the 36.9% low-quality row stays, blind quality detection stays
  published as *not supported*.
- `Minimum Cost to Trusted Output` is still the objective function.
- The runtime invariants (R2 immutable truth, at-least-once, hostile documents,
  no scalar blind quality score, public DTOs never expose router internals) are
  restated, not revised.
- The website narrative and the evidence rules carry over.
