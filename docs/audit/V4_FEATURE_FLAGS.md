# V4 / V5 Feature Flag Registry

*Masterplan v4.0 PHASE 0 deliverable ("feature flag framework"), extended
2026-08-11 with v5.0 PART 22's keys.*

## The framework already exists

`services/api/src/akc_api/feature_flags.py` with the `FeatureFlag` table. It
gives PART 20.4 everything it asks for, and PHASE 0 adds no code:

| PART 20.4 requirement | Where it is satisfied |
|---|---|
| tenant / workspace scope | `FeatureFlag.tenant_id`, nullable for a global default; a tenant row outranks the global row |
| cohort rollout | `cohort_enabled()` — SHA-256 of `tenant:subject:key`, bucketed 0–99, so a subject's bucket is stable across deploys and independent per flag |
| kill switch | `enabled = False` short-circuits before any percentage arithmetic |
| audit | rows are ordinary DB rows under the existing audit path |
| fail closed | no row → `False`; an unknown key in `conditions` → `False` |

The condition vocabulary is bounded to `tenant_ids`, `user_ids`,
`document_types`. Anything else fails the flag closed rather than being ignored —
which is the behaviour that matters when a typo would otherwise silently enable
a surface for everyone.

Three keys already exist for shipped features and are not touched here:
`ontology_export`, `existing_vault_merge`, `chart_description`.

## The thirteen surviving v4 keys

Registered as documentation now; rows are created by the phase that needs them,
defaulting to absent (= off). Phases are **v5's** numbering
(`docs/audit/V5_MIGRATION_MATRIX.md`), which is what governs now.

| Key | Owning phase | Gates | Off means |
|---|---|---|---|
| `V4_CONTRACTS` | 1 | v4/v5 canonical DTO/event serialisation | current CIR contracts unchanged |
| `V4_INGEST` | 2 | R2 multipart upload session path | existing upload path stays live |
| `V4_PREFLIGHT` | 2 | per-format preflight + quarantine | no preflight; current admission |
| `V4_PROFILER` | 3 | page/document profiler | profiler runs shadow-only or not at all |
| `V4_MODEL_REGISTRY` | 3 | registry-gated adapter selection | current provider selection |
| `V4_BENCHMARK_OS` | 17 | full 5,132 + DART/SEC research campaign | Arena and campaign harness only |
| `V4_RETRIEVAL` | 12 | permission-first retrieval | existing hybrid retrieval |
| `V4_ASK` | 12 | grounded answer surface | absent |
| `V4_HEALTH_SCAN` | 13 | Knowledge Health Scan | absent |
| `V4_CINEMATIC_LANDING` | 14 | cinematic landing narrative | current landing |
| `V4_CONNECTOR_DRIVE` | 15 | Google Drive connector | absent |
| `V4_PUBLIC_API` | 15 | public REST surface | internal API only |
| `V4_MCP_READ` | 16 | read-only MCP server | absent |

**`V4_SHADOW_ROUTER` and `V4_ROUTE_EXECUTION` are withdrawn.** v5 replaces them
with `V5_ROUTER_SHADOW` / `V5_ROUTER_CANARY` and moves the router from Phase 4 to
Phase 6, behind the Arena. Neither v4 key ever had a row, so nothing is stranded
and no deprecation path is owed.

## The eleven v5 keys

| Key | Owning phase | Gates | Off means |
|---|---|---|---|
| `V5_ARENA` | 4 | Arena harness — case selection, run execution, scoring | no Arena runs |
| `V5_ARENA_BATCH` | 4 | batch/bulk execution lane (Track B) | interactive only |
| `V5_DPM` | 5 | Document Performance Map construction | no map |
| `V5_ORACLE_DATASET` | 5 | Router Oracle Dataset emission | no oracle rows |
| `V5_ROUTER_SHADOW` | 6 | router computes a decision **nothing acts on** | legacy routing only |
| `V5_ROUTER_CANARY` | 6+ | the v5 decision actually executes, by cohort | shadow decisions recorded, not obeyed |
| `V5_API_PROVIDER_OPENAI` | 4 | OpenAI candidates in the Arena | family excluded |
| `V5_API_PROVIDER_ANTHROPIC` | 4 | Anthropic candidates | family excluded |
| `V5_API_PROVIDER_GEMINI` | 4 | Gemini candidates | family excluded |
| `V5_LOCAL_PADDLE` | 4 | PaddleOCR-VL-1.6 candidate | candidate excluded |
| `V5_LOCAL_DEEPSEEK_OCR2` | 4 | DeepSeek-OCR-2 candidate | candidate excluded |

The three `V5_API_PROVIDER_*` keys have no credential behind them today
(`docs/audit/V5_COST_BUDGET.md` C-7). Leaving them off is correct until a key
exists — but note that an Arena run with all three off is a **local-only**
comparison, which cannot answer the question the Arena exists to answer. The flag
makes the exclusion visible; it does not make it valid.

`V5_ROUTER_SHADOW` and `V5_ROUTER_CANARY` stay two flags for the reason the v4
pair did: shadow and execution must not share a switch.

## F-1 — `rollout_percent = 0` meant *everyone* — **FIXED 2026-08-10**

`cohort_enabled()` short-circuited on `percent in {0, 100}` and returned `True`.
On an `enabled = True` row, zero percent therefore enabled the flag for the whole
tenant. Reproduced at the `v3.1-baseline` tag:

```text
enabled=True, rollout_percent=  0 -> True     <-- expected False
enabled=True, rollout_percent=  1 -> False
enabled=True, rollout_percent=  5 -> False
enabled=True, rollout_percent= 25 -> False
enabled=True, rollout_percent= 50 -> False
enabled=True, rollout_percent=100 -> True
enabled=False, rollout_percent=100 -> False
```

The author's intent was readable — treat `percent` as a restriction that only
applies strictly between the endpoints. The existing test
(`test_feature_flags.py`) paired a global `enabled=True, percent=0` row with a
tenant `enabled=False` row and asserted `False`, which proves the tenant row wins
and never exercised `percent=0` alone.

It mattered for v4 specifically. **PART 31 makes `0` the first rung of the router
rollout: `0→5→25→50→100`.** A `V4_SHADOW_ROUTER` row created at 0 to mean
"recorded for nobody yet" would have routed everybody. The one rung the ladder
exists to make safe was the one that was inverted. `FeatureFlag.rollout_percent`
defaults to `0`, so every freshly created enabled row was affected.

### Fix

`percent <= 0 → False`, `percent >= 100 → True`, bucket comparison in between.
The endpoints no longer share a branch, and out-of-range values resolve by the
same rule instead of falling through to the bucket arithmetic.

Three tests were added: zero reaches nobody across 200 tenants; the ladder is
monotonic over a 400-subject sample at every rung, empty at 0 and complete at
100; out-of-range percentages do not widen a cohort.

**One caller depended on the old behaviour.**
`services/api/tests/test_api_integration.py` enabled `ontology_export` and
`existing_vault_merge` with `rollout_percent=0` in order to turn them *on* for
its vertical slice — correct only while 0 and 100 shared a branch. The fixture
now says `100`, which is what it was always asking for.
`product_analytics.py` was already writing `100 if enabled else 0`, so the fix
makes that path mean what it reads as.

Verified: `test_feature_flags.py` 17 passed; `test_api_integration.py`,
`test_analysis_isolation.py` and `tests/unit/test_page_attempt_runtime.py`
53 passed.

## Two rules that are easy to get wrong

**`V4_SHADOW_ROUTER` and `V4_ROUTE_EXECUTION` are two flags on purpose.** Shadow
mode means the v4 router computes and records a decision that nothing acts on.
Collapsing them into one flag makes "start shadow" and "start executing"
the same switch, which is the failure PART 8.10 and the rollout ladder exist to
prevent.

**Percentages roll out; they do not roll back on their own.** A flag at 25% that
starts failing can be withdrawn either way now — `enabled = False` is the kill
switch, and `rollout_percent = 0` empties the cohort. Prefer the kill switch: it
survives a later percentage edit by someone who has not read this file.
