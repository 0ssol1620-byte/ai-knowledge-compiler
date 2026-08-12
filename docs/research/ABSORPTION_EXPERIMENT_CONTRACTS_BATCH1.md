# Absorption Experiment Contracts — Batch 1

*Written 2026-08-11 against `c8de965`. Four contracts, `EXP-0101`–`EXP-0104`.*

**This is a contract, not code and not a performance claim.** No number below is
a measurement. Where a target appears it is a gate to be met, never a result.

Gate: `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml`. Design detail:
`docs/north-star/TAVONEL_FTO_ABSORPTION_BLUEPRINT_v1.0.md` §6, §8, §9, §13,
§15, §16, §17. Evaluation protocol: masterplan PART 8, 9, 31.

---

## 0. Common terms

### 0.1 The path every absorption takes

```
DISCOVER → LEGAL/LICENCE → BASELINE → CHALLENGER → SHADOW → ARENA → CANARY → PROMOTE
```

No challenger touches a production write path. Experiment output goes only under
`research/experiments/EXP-01xx/`. Challenger execution sits behind an `ABSORB_*`
flag, default false, shadow-only.

### 0.2 Three arms, one condition

```
CURRENT                     what the repository does today
PRIOR-ART BASELINE          the paper's method, clean-room reproduced
TAVONEL HYBRID CHALLENGER   what we build after absorbing it
```

Same corpus manifest sha256, same split, frozen prompt/schema/settings, same
downstream configuration. **A CURRENT drawn thinner than it is turns the whole
experiment into a straw man**, so every CURRENT statement below carries a
`file:line` citation and was checked against HEAD.

### 0.3 Out of scope — do not add

Cryptographic provenance ledger productionization · RepoDoc-style full impact
replacement · Cedar/OpenFGA/OPA · generic ontology replacement · retrieval stack
rewrite · Stable Semantic Identity core replacement. **Protected Core is
unchanged**; challengers supply candidate evidence to it, never replace it.

### 0.4 Two binding disciplines

**FTO language.** No file in this repository states that anything "reads onto
claim N" of any patent. FTO sections cite a register ID and the review step
owed, nothing more. Claim-level analysis happens outside the repository under
counsel privilege. A pushed sentence survives its own revert.

**Clean room.** No source snippet from a YELLOW project enters this document, a
requirements summary, or an implementation. §15.3 separates the summariser from
the implementer and requires a provenance record of what each read. Contamination
cannot be undone — a person who has seen the code can no longer be the
independent-implementation witness for it.

### 0.5 Promotion gates — all six, per contract

1. **quality non-regression** — primary metric no worse than CURRENT, margin fixed in advance
2. **catastrophic failure non-regression** — zero catastrophic violations on the critical holdout; CURRENT's fail-closed paths (`UNRESOLVED` / `QUARANTINE` / abstain) preserved
3. **latency/cost budget** — PART 31 stage gates and stop rules; a per-unit cost ceiling
4. **reproducibility** — re-running the frozen manifest reproduces the metrics; deterministic components bit-exact, model calls pinned by receipt
5. **permission/security invariants** — zero unauthorized or cross-tenant candidates; permission filters ahead of similarity
6. **license/FTO gate** — every component APPROVED in the register; YELLOW carries clean-room evidence; RED-adjacent language has passed design-around review

### 0.6 IP linkage — one registry, one source of truth

**Canonical target: the Technology Absorption Ledger,** §7 of
`docs/ip/INVENTION_DISCLOSURE_A.md` and `_B.md`. Not
`V4_DISCLOSURE_REGISTRY.yaml`.

The ledger is purpose-built for this — it already carries `gate_status`, the
`why_written_before_result` honesty flag, the RED gate order, and the four
entries this batch feeds (`ABS-A-01`, `ABS-B-01/02/03`). The registry is
governance: IP items, publication freeze, founder decisions. **Do not operate a
duplicate.** The registry references the ledger; it does not mirror it.

**The entry opens when the experiment is designed, not when it wins.** That is
the correction that makes the rest work: `why_changed` must exist before any
result, so there has to be somewhere to put it before there is a result. The
ledger opens the entry at design time; this contract does not define a second
place.

**Frozen before the experiment starts** — five fields, written when nothing is
known about the outcome:

```yaml
prior_art_used:          [register id + version]
what_changed:
why_changed:                      # technical reason
expected_technical_effect:        # what we predict, before measuring
design_rationale:                 # why this design and not the alternatives
```

Plus the bookkeeping the gate needs: `classification` (BLUE…RED),
`gate_status`, `claim_elements_touched` — a record that cannot name the element
it supports cannot be filed against one — and `sources_read`, the provenance
trail the intake register's binding rules require.

**Appended after results. Never overwritten:**

```yaml
measured_effect:
ci_and_denominator:
result_status:                    # improved | no effect | worse | inconclusive
promotion_decision:
patent_relevance:
receipt_binding:
  experiment_receipt_ref:
  git_commit_sha:
  model_registry_ids:             # + revisions
  config_sha256: []
  corpus_manifest_sha256:
```

| Moment | What happens |
|---|---|
| Before the experiment starts | Entry opened; the five fields frozen. |
| Experiment runs | Receipt fields bound. |
| Result arrives | Result block appended — **improvement, null result or regression alike**. |

**Failed, void and no-improvement results are never deleted.** A ledger holding
only successes is one an examiner is right to distrust, and "no effect" answers a
question the next experiment would otherwise re-ask.

**`why_changed` is immutable once the experiment is designed.** It is written
before any result exists, and `why_written_before_result` records that. If the
result later demands a different explanation, **append an amendment — never
overwrite.** The original and the amendment both stand, with their dates.

The reason is the whole point of the clause: the contemporaneous sentence is
evidence, and the same sentence written after seeing the result is argument an
examiner discounts as hindsight reconstruction. An overwrite destroys exactly the
property that makes the record worth keeping.

**A failed experiment is kept, not deleted.** Its receipt and its ledger entry
stay. "No effect" is a research result, and a record that only contains successes
is a record an examiner is right to distrust.

**Filing and publication timing is the founder's alone.** These records are
defensive facts, not filing decisions.

### 0.7 RED ordering — binding, in two stages

Any technology touching a RED family clears **both** gates, in order:

| Gate | What | Required before |
|---|---|---|
| **`FTO-1A`** | Internal claim chart + design-around review (§15.4 steps 1–5) | **Contract B challenger code is written** |
| **`FTO-1B`** | External patent counsel review (§15.4 step 6) | Commercial activation · patent-sensitive public disclosure · any filing decision |

`FTO-1A` is internal work and gates engineering. `FTO-1B` is counsel and gates
commerce and disclosure. **They are not the same gate and do not block the same
things** — treating them as one either stalls the experiment waiting for counsel,
or ships a challenger with no design-around on record.

An implementation that ran before `FTO-1A` is not absorbed. It is exposure.

The Arena's research posture covers **baseline arms**, not a shipped challenger.

### 0.8 Execution order — approved

```
EXP-0101  →  EXP-0103  →  EXP-0104 (deterministic arm)  →  EXP-0102
```

0101 is local-only and bears directly on Stable Identity and Semantic Diff. 0103
validates adaptive-k and granularity while preserving the existing hybrid and
permission-first retrieval. 0104's deterministic arm starts without an API
credential. 0102 comes last because it needs Arena data, API credentials, **and**
`FTO-1A`.

Every challenger is a shadow-only adapter behind an `ABSORB_*` flag. **None
replaces a production core path.**

### 0.9 Holdout hygiene

`ROUTER_HOLDOUT` and every experiment holdout is access-controlled and access is
receipted. Editing a policy or threshold after seeing holdout labels requires a
new policy version **and a new holdout** (§8.4). A burned holdout does not come
back.

### 0.10 Reproducibility package

`research/experiments/EXP-01xx/` = `manifest.json` (corpus_manifest_sha256, git
commit, model registry IDs + revisions, prompt receipt sha256s, config sha256,
seeds, split definition) · `raw/` · `normalized/` (§9.5 conversions only — no
semantic content added) · `metrics/` · `receipts/` · `tables/` · `figures/` ·
`scripts/`.

**A number not bound to a receipt does not exist.**

---

## Contract A — `EXP-0101` · Alignment-First Heterogeneous Diff

*Blueprint §9, experiment D1.*

**Question.** Does putting element alignment ahead of diffing reduce false
semantic invalidation from pure layout change, while holding or improving recall
on critical semantic change (figures, modal verbs, exception clauses)?

**CURRENT.** `diff_documents()` runs cumulative levels L0 binary → L1 structural
→ L2 evidence → L3 semantic → L4 graph, deterministic, `change_id` a sha256
digest (`semantic_diff.py:218`). Identity is a seven-signal weighted sum —
`source_continuity` .25, `structural_path` .20, `explicit_identifier` .15,
`semantic` .15, `previous_neighbor` .10, `next_neighbor` .10, `geometry_style`
.05 (`identity.py:231`) — abstaining when a critical signal is absent
(`identity.py:245`). Bands: merge ≥ 0.92, new < 0.75, tie band 0.05
(`identity.py:249`), **all uncalibrated**. `IDENTITY_UNRESOLVED` is not a change
and is excluded from `changed_logical_ids` (`semantic_diff.py:195`) — guesses do
not enter dependency propagation.

**What CURRENT lacks.** No typed element model (`UnitSnapshot` has no
TEXT/TABLE/FORMULA/FIGURE, `semantic_diff.py:100`). No bbox or spatial signal.
No type-specific difference reasoning — a normalised-text mismatch *is* a
`MODIFIED_CLAIM` (`semantic_diff.py:422`). L1 compares tables by `(rows, cols)`
shape alone (`semantic_diff.py:151`).

**Baseline.** `tech_xversion_diff` — **YELLOW, CLEAN_ROOM_ONLY.**
Requirement-level reproduction: typed elements, spatial/structural/content
compatibility, 1:1 assignment, per-type reasoning. No code copied, translated or
ported.

**Challenger.** An alignment layer feeds §9.2's typed element model and §9.3's
signals into the existing seven-signal system **as additional signals**,
inheriting availability-aware renormalisation and critical-signal abstention.
Final stable-ID assignment stays with `akc_cir.identity` (§9.6) — Protected Core
untouched. Type-specific reasoning splits `MODIFIED_CLAIM` into row-move vs
value-change, may→must, formula-tree vs rendering-only.

*Why.* CURRENT has no signal that separates a move from a meaning change, and
that misjudgement propagates into dependency and recompilation.

**Dataset.** The 5,132-document corpus is single-version and **insufficient**.
New fixture — Knowledge Evolution Suite (masterplan §8.7 = blueprint §9.7): 11
controlled mutation classes seeded from a corpus subset, DART/SEC amendment
pairs, Office→PDF export pairs. **Shared with Contract D.**

**Metrics** (denominator in parentheses). Alignment P/R/F1 (gold aligned pairs) ·
semantic-change P/R (injected mutations) · layout-only false-positive rate
(pure-layout mutation set) · critical numeric change recall (injected numeric
mutations) · identity false merge / false split (gold identity pairs) ·
downstream impact recall · selective-vs-full rebuild equivalence.

**Ablations.** −spatial signals · −type-specific reasoning · identity without
alignment · per-mutation-class breakdown.

**Statistics.** Paired at document-pair level. McNemar for binary judgements,
10k bootstrap CI for rates, Holm–Bonferroni across slices, fixed seeds.

**Gates.** The six, plus: critical semantic mutation recall ≥ CURRENT on the
controlled high-risk set (target 100%, §9.8) · zero critical false merges ·
ambiguous cases stay reviewable rather than silently merged.

**Resources.** Local CPU. An embedding provider for the semantic signal, pinned
in the registry. No API credential otherwise.

**FTO.** The narrative *diff → dependency → impact → rebuild* approaches the
generic expression of `tech_palantir_propagated_deletion` and
`tech_palantir_universal_data_pipeline` (RED). This experiment changes neither
module, but its documentation and any external language pass design-around
review. `tech_xversion_diff` clean-room evidence required.

---

## Contract B — `EXP-0102` · Marginal-Gain / Outcome-Aware Routing

*Blueprint §6, experiment R1.*

**Question.** Does selecting on marginal gain conditioned on attempt history
lower `$ / Trusted Page` against the current deterministic ladder and absolute
expected-cost selection, without increasing catastrophic trust violations?

**CURRENT — and this is the one most likely to be drawn as a straw man.** Three
layers already exist:

- Deterministic ladder: `select_first_route()` → NATIVE → HPD_FAST (speed mode,
  en/zh, difficulty < 65, handwriting < 0.2, `engine.py:114`) → PADDLE_FAST →
  PADDLE_VL. `decide_escalation()` fails closed to `UNRESOLVED` on quarantine,
  gates quality at 0.82 with warning and 0.90 (`engine.py:302`), bounds retries.
- **An outcome-aware objective already exists** —
  `inference + verification + p_recover·recovery_cost + p_crit·penalty`
  minimised subject to `p_crit ≤ bound` (`expected_verified_cost.py:19`).
  It is **absolute, not marginal**, and **not learned**.
- Correlation exclusion already exists — `independent_family` required, with
  `excluded_independent_families` (`parallel-runtime/routing.py:51`).
  `LearnedRouterShadowRecord` exists with zero authority (`estimation.py`).

**So the challenger's novelty is exactly two things: marginal rather than
absolute, and learned rather than fixed.** Nothing else.

`CalibrationTable.calibrated` is `False`. No threshold here may be presented as
a measured result.

**Baseline.** RouteLLM MF/BERT and AdaParse-style predicted parser quality —
**not in the register.** §15.1 intake record is a precondition; until then they
are Arena-baseline-only and may not become dependencies. RouteLMT insight is
paper-only, treated YELLOW. The ten baselines of §6.4 apply.

**Challenger.** Layers 0–1 (admission, deterministic safety) keep the current
rules. Layer 2 predicts `P(trusted | page, attempt_history, m)`, IncrementalGain,
ExpectedCost and a CorrelationPenalty over `independent_family`. Layer 3
minimises expected loss subject to a trust floor and budget (§6.2–6.3).

*Why.* The campaign published blind quality scoring as **not supported**, so
route signals must be learned from outcome lineage; and the increment over the
previous attempt — not an absolute probability — is what matches incremental
recovery yield in the Failure Zoo.

**Dataset.** Model Arena v1, 1,000 pages (§8.2: 400 public GT + 300 DART/SEC +
200 Failure Zoo + 100 clean control), split 60/20/20 by document family (§8.4).
Oracle labels need a full candidate-model matrix — **blocked on API
credentials.** Available before credentials: local-model replay and deterministic
policy simulation.

**Metrics.** Oracle regret · `$ / Trusted Page` (pages judged trusted) ·
catastrophic trust violations (critical holdout, target 0) · severe regression
rate · hard-slice incremental recovery (that Failure Zoo slice) · unnecessary
frontier escalation rate (all escalations) · calibration ECE.

**Ablations.** −CorrelationPenalty · marginal → absolute · −deterministic guard
(safety ablation, expected to degrade) · guard-only · per-slice.

**Statistics.** Paired per-page on one holdout. Pages correlate within a family,
so **family-cluster bootstrap**. McNemar for catastrophic events. The holdout is
spent once.

**Gates.** The six, plus §6.6 entire: zero catastrophic on the critical holdout ·
required-trust coverage not below the static safety baseline · `$/TP` improved ·
route receipts reproducible from frozen inputs, policy and model snapshot.

**Resources.** **API credentials required — BLOCKED.** GPU for local candidates.
PART 31 stage gates (50 → 200 → 1,000) and §31.3 stop rules are built into the
contract.

**FTO.** `tech_ibm_sequential_inference` (RED) is directly adjacent. The register
warns that **claim 1 recites latency/precision/recall rather than confidence, and
the conditional is claim 4 — claim 1 is broader than the blueprint's summary.**

Gate order per §0.7: **`FTO-1A` (internal claim chart + design-around review)
must complete before challenger code is written.** That is engineering's gate and
it does not wait on counsel. **`FTO-1B` (external counsel) gates commercial
activation, patent-sensitive disclosure and any filing** — not this experiment.
The baseline arms carry the Arena's research posture; a shipped challenger does
not.

The ledger entry for this contract is `ABS-A-01`, currently
`gate_status: CLAIM_CHART_DONE`. `DESIGN_AROUND_REVIEWED` is unsatisfied, so
implementation is not permitted yet.

Language discipline: the system is never defined or described as *"first result
below a QoS threshold → run a second model."* The centre of the description is
failure-cause classification driving materially different recovery (§6.5).

---

## Contract C — `EXP-0103` · Adaptive Multi-Granular Retrieval

*Blueprint §8, experiment Q1.*

**Question.** Does intent-driven granularity plus score-distribution adaptive-k
raise critical evidence recall at equal context budget, while lowering context
tokens, against fixed k?

**CURRENT — also richer than assumed.** `candidate_k` 30–100 default 50,
`top_k` 5–15 default 10 (`models.py:138`) — **fixed**. But pgvector cosine
(`<=>`) plus SQL BM25 with normalised fusion is **already hybrid**
(`postgres.py:120`), tenant/project filters already run **ahead of** candidate
generation (`engine.py:90`), and the reranker already enforces pinned model
id/revision attestation (`engine.py:143`).

**So the challenger's novelty is adaptive-k and granularity. It is not hybrid
retrieval, and not permission-first.**

**What CURRENT lacks.** No adaptive k. No per-intent granularity — a single unit
size. No visual page lane. No version-graph lane.

**Baseline.** Adaptive-k upstream (BSD-3-Clause candidate, §1.1C) — **not in the
register**; intake record, exact commit pin and SBOM entry precede any
dependency, and until then it is reproduced behind an independent wrapper.
`tech_smartchunk` — **YELLOW, CLEAN_ROOM_ONLY** if its multi-granular policy is
referenced. **Visual lane (ColPali/ColQwen) is excluded from this batch** — §8.3
constraints and checkpoint licensing make it a separate experiment.

**Challenger.** `retrieval_intent` (§8.5) selects preferred unit granularity
(TABLE_CELL / CLAIM / …), existing fusion is retained, then an adaptive cutoff
`clamp(above_threshold, K_MIN, K_MAX)` (§8.4) produces an adaptive context
package. Permission, temporal and authority filters stay ahead of similarity —
invariant.

*Why.* A fixed top-k over- or under-fills context depending on the query, and a
single granularity misaligns the evidence unit for numeric and tabular questions.

**Dataset.** Documents can come from the existing corpus, but **there are no
query or gold-evidence labels — a new fixture is required**: automatic truth from
SEC XBRL and OpenDART structured facts (§31.4), controlled synthetic queries, and
a **cross-tenant unauthorized probe set**.

**Metrics.** recall@budget (gold evidence per query) · critical evidence recall ·
version-correct recall where a version fixture exists · **unauthorized candidate
rate = 0** (probe set) · context tokens · latency p50/p95 · downstream
QA/citation accuracy under one frozen LLM and configuration.

**Ablations.** §16.5 stage-gated pairwise: fixed-k vs adaptive-k · flat vs
structure-aware units · fusion composition · reranker on/off. **No full
factorial.**

**Statistics.** Paired per query, Wilcoxon signed-rank with bootstrap CI.
Unauthorized rate is not a statistic — it is a hard gate.

**Gates.** The six, plus: unauthorized rate zero, absolutely · critical evidence
recall not degraded even where adaptive-k reduced k · frozen downstream
configuration evidenced.

**Resources.** Local Postgres/pgvector, registry-pinned embedding and rerank
providers, one fixed LLM for downstream QA — small API spend. **Startable
independently of the Arena credential gate**; only downstream QA needs a
credential.

**FTO.** No RED contact. SmartChunk clean-room evidence if referenced;
adaptive-k licence pin is the gate.

---

## Contract D — `EXP-0104` · State-to-Draft Freshness Auditor

*Blueprint §13, experiment F1.*

**Question.** Does an auditor combining deterministic verification with
world-state supersession transitions catch drafts that retrieved current state
and still **used a superseded premise implicitly** — while controlling false
repairs?

**CURRENT is absence.** There is no draft auditor; a repository-wide search finds
none. **The comparison arm is "retrieval-grounded answer, no audit."** Adjacent
assets exist and must not be mistaken for one: `temporal.py` (bitemporal —
`valid_from`/`valid_to` for reality, `recorded_at`/`superseded_at` for record,
as-of resolution), `world_state.py` (atomic pointer-swap publish, `dirty_set`),
`dependency.py` (`impact_of`), `authority.py` (SUPERSEDED), `inspection.py`
(`F26_STALE_WORLD_STATE`).

**Baseline.** `tech_memlineage` (MemLineage / StateAuditor) — **YELLOW,
CLEAN_ROOM_ONLY.** Reproduce at requirement level the distinction between
provenance/chronology verification and semantic supersession.

**Challenger.** §13.2 pipeline with §13.3 transition objects. Three TAVONEL
changes: (1) "the old one is superseded" is asserted **only when the
authority/applicability engine has a RESOLVED status** (§13.3); (2) citations and
evidence IDs are verified deterministically and invalid proposed transitions are
discarded (§13.5); (3) three states — PASS / REPAIR_REQUIRED / **ABSTAIN** —
with repeated failure going to abstain and review.

*Why.* The auditor LLM is not a truth oracle, and never auto-resolving an
authoritative conflict on insufficient evidence is a repository invariant. An
LLM-only auditor breaks it.

**Dataset.** **FreshnessBench is entirely new**: seeded from Contract A's
Knowledge Evolution Suite transitions, drafts generated by a frozen model, with a
stale-premise arm, a no-change control and a false-invalidation control (§13.6).

**Metrics.** Implicit stale-dependency recall (injected drafts) · false repair
rate (no-change control) · final answer accuracy · abstention rate · repair
success (REPAIR_REQUIRED cases) · per-audit cost and latency.

**Ablations.** −deterministic pinning (LLM-only, safety ablation) · −RESOLVED
requirement · single pass vs re-audit after repair.

**Statistics.** Paired per draft. McNemar for recall, bootstrap CI for rates.
Auditor model ID, revision and prompt receipt frozen.

**Gates.** The six, plus: false repair rate below a ceiling fixed in advance
against the control · ABSTAIN preserved, no forced verdict · zero cases where a
supersession without RESOLVED status was used as staleness grounds.

**Resources.** Auditor LLM API — credential-gated. **The deterministic-only arm
runs without credentials.**

**FTO.** Avoid claiming generic provenance plus temporal lineage as an
independent invention (`tech_oracle_dynamic_lineage`, RED). This is a matter of
**assertion and language, not of implementation** — disclosure and any external
wording pass design-around review. `tech_memlineage` clean-room evidence
required.

---

## Acceptance — how this file is graded

1. File exists at this path; zero code, migration or schema change.
2. Exactly four contracts, `EXP-0101`–`EXP-0104`; the out-of-scope list is in §0.
3. **Every CURRENT claim carries a `file:line` citation matching HEAD** — the
   identity weights and bands, `engine.py`'s 0.82/0.90 gates, `models.py:138`
   fixed k, the `expected_verified_cost` formula, and D's absence.
4. Every prior-art item names its register grade by ID; unregistered items
   (RouteLLM, AdaParse, adaptive-k upstream) are marked intake-required and
   blocked from dependency use.
5. Contract B carries the RED ordering as a binding clause and the prohibition on
   *"first result below QoS → second model"* phrasing.
6. Zero sentences in this repository admitting infringement.
7. All six promotion gates instantiated in all four contracts.
8. Every metric has a denominator.
9. Statistics state the paired design, the significance test, multiple-comparison
   handling, and family clustering for B.
10. Reproducibility package structure and mandatory manifest fields in all four.
11. IP linkage schema present; filing timing stated as the founder's alone.
12. Credential-dependent items marked blocked (B entirely, C downstream QA, D
    auditor arm).
13. Holdout hygiene and PART 31 stage gates built into B.
14. Zero YELLOW code snippets, zero performance claims, zero uncalibrated
    thresholds presented as measurements.

## Irreversible points

**Clean-room contamination** cannot be rolled back — only the contaminated role
can be replaced. **A pushed legal phrase** stays in history after revert. **A
burned holdout** requires a fresh extraction. **Executed API spend** is not
refundable. These four are governed by gates in advance, not by rollback; that
is the structure of this plan.

## Founder decisions

| ID | Decision | Blocks |
|---|---|---|
| `FTO-1A` | **Who performs and signs the internal design-around review** for the RED families | Contract B challenger code — and nothing else |
| `FTO-1B` | External patent counsel engagement and timing | Commercial activation · patent-sensitive disclosure · filing. **Not this batch.** |
| — | API credential gate release and PART 31 stage 0/1 budget | B entirely, C downstream QA, D auditor arm |
| `FTO-3` | Owner for the new intake records (RouteLLM, AdaParse, adaptive-k) | Their use as dependencies |

**Settled, no longer a founder question:** the IP linkage target. §0.6 names the
Technology Absorption Ledger as canonical and `V4_DISCLOSURE_REGISTRY.yaml` as
governance-only. There is one registry.

**`FTO-1A` is the only gate this batch actually waits on**, and only for
`EXP-0102` — which the approved order puts last for exactly that reason.
`EXP-0101`, `EXP-0103` and `EXP-0104`'s deterministic arm are unblocked today.
