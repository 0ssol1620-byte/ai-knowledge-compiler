# TAVONEL W6 / v8 CONFIRMATORY RUN — NEW SESSION MASTER HANDOFF

Date: 2026-08-20 (KST)

Repository: `D:\CodexProjects\ai-knowledge-compiler`

Branch at handoff creation: `agent/folynta-trust-integration-v1`

Status labels at handoff creation:

- `PATENT_FILING = NOT FILED`
- `PAPER_SUBMISSION = NOT SUBMITTED`
- `V8_HOLDOUT = UNOPENED`
- `ROOT_GOAL = NOT COMPLETE`

This file is a worker handoff, not an authority above the live repository. At session start, reconcile every material statement below against the current repo, receipts, test status, runtime state, and model registries. If live evidence conflicts with this file, preserve the discrepancy and use live evidence as authoritative.

---

## 0. ROOT GOAL

Finish TAVONEL's evidence package to a defensible patent-filing + paper-submission state.

The immediate scientific bottleneck is W6 v8: a fresh, untouched confirmatory holdout comparing the same frozen model across:

1. `RAW`
2. `BASIC_RAG`
3. `BASIC_RAG_PLUS`
4. `TAVONEL`

The primary comparison is **TAVONEL vs BASIC RAG**. RAW is a floor, not the primary comparator. BASIC RAG+ is a stronger deterministic non-temporal retrieval baseline.

Do not stop after intermediate findings. A finding is an input to the next step, not a turn boundary.

Only stop for one of these:

1. `ROOT_GOAL_COMPLETE`
2. a genuine `HARD_ALL_PATH_BLOCKER` where all meaningful runnable work is blocked
3. physical/session termination, in which case leave an exact handoff and do not call the programme complete

`PARTIAL`, `PACKAGE GREEN`, `A6.5 CLOSED`, `HOLDOUT GATE READY`, `FINDING RECORDED`, and `NOT GOAL COMPLETE` are **not** stop conditions.

---

## 1. NON-NEGOTIABLE EVIDENCE RULES

### 1.1 Never repair evidence by editing history

- Never hand-edit raw receipts to make an experiment pass.
- Preserve failed, void, invalidated and superseded artifacts.
- Do not overwrite historical evidence silently.
- If code changes make an old receipt non-regenerable, record that fact rather than regenerating it as though nothing changed.

### 1.2 No post-hoc cohort tuning

- No outcome-based title/question selection.
- No threshold changes after seeing holdout results.
- No changing the benchmark because TAVONEL loses.
- No immediate V9 reflex if v8 fails.

### 1.3 Freeze before endpoint

Protocol, exclusions, model identity, decoding, retrieval settings, scoring, statistics, holdout selection and stop rules must be frozen before the untouched holdout is opened.

### 1.4 Distinguish evidence classes

Keep separate:

- measured empirical evidence
- controlled/generated evidence
- retrospective natural-corpus evidence
- static-code / contract audit
- derived result
- inference
- expected value
- external blocker
- not measured / not run

Do not promote `INFERRED` or `EXPECTED` to `MEASURED` without a new measurement.

### 1.5 Negative results are valid

If TAVONEL does not win, report it. If a gate fails, report the gate failure. Do not redesign the confirmatory benchmark after seeing the result.

---

## 2. OPERATIONAL RULE — BARRIER != TURN BOUNDARY

This programme previously lost time because workers treated temporary barriers as reasons to end the turn.

Examples:

- test suite running, writes forbidden -> continue read-only work; when suite ends, immediately resume writes
- network acquisition running -> continue other patent/paper/science work
- GPU runtime not yet ready -> complete all zero-cost preparation that does not depend on GPU
- fresh session needed for holdout provenance -> finish everything up to that boundary before switching sessions

Do not write a long checkpoint and stop merely because one background job is running.

---

## 3. REPO / RUNTIME STARTUP CHECK

At the start of the new worker session:

1. Select `D:\CodexProjects\ai-knowledge-compiler`.
2. Read `AGENTS.md` and `CLAUDE.md`.
3. Read this handoff.
4. Read the W6 v8 files listed in §16 below.
5. Reconcile git/repo status.
6. Reconcile current test receipt rather than repeating an old number from this handoff.
7. Reconcile runtime generation / canonical goal state if goal tooling is available.
8. Confirm the v8 holdout is still unopened before any holdout action.

The repository is intentionally dirty with a large body of active programme work. Do not normalize or delete unrelated changes.

---

## 4. IMPORTANT PROGRAMME FINDINGS THAT DEFINE THE CURRENT CLAIM BOUNDARY

### 4.1 Natural selective recompilation evidence — H1-F

`H1-F-REAL-CORPUS-EQUIV-01`

- 28 natural English Wikipedia revision pairs
- 28/28 selective vs full rebuild equivalent under the measured endpoint
- stale total = 0
- changed pairs = 11
- mean rebuild fraction ~= 7.94%

Boundary:

- retrospective
- one natural source family
- not broad arbitrary-document external validation

### 4.2 Identity scalability — H1-E

Historical performance evidence showed a sparse/blocking candidate could be much faster than the dense LEGACY path, including a large speedup at 1,000 units.

But correctness promotion was vetoed by later experiments.

### 4.3 Path-dependent semantic divergence — H1-E2

`H1-E2-TIE-PATH-DEPENDENCE-01`

- current divergences = 8
- future-revision divergences = 8
- all 8 residual differences propagate into future lineage semantics
- disposition: promotion veto for the approximate/blocking path

Mechanism:

global one-to-one contention can make a row lose a candidate and fall through to `NEW`; decomposition can let it acquire the candidate and become `AMBIGUOUS`; that changes candidate attribution, rebuild seeds and future lineage.

Forbidden overclaim:

- do not describe the residual as a harmless permutation
- do not describe candidate attribution as diagnostic-only

### 4.4 Candidate attribution is semantic — H1-K

The downstream chain was traced:

`decision.candidates`
-> semantic unresolved changes
-> recompilation seeds
-> promotion/accounting seeds
-> serialized semantic record

Dynamic probes showed that changing candidate attribution changes impacted artifacts. Therefore exact matcher endpoints must preserve candidate attribution and related runner-up semantics, not just winner/logical-id.

### 4.5 Certified sparse matcher — H1-L / P2-13

The certified exact strategy preserved the expanded semantic contract in tested corpora/topologies, including H1-E topology replays, but was roughly **2-3x slower** than the LEGACY reference path.

Interpretation:

- exactness succeeded under the tested contract
- acceleration objective failed
- do not claim exact sparse acceleration is mathematically impossible
- safe wording: under the tested certification strategy, preserving global assignment, candidate attribution and runner-up semantics removed the expected sparsity advantage

### 4.6 Promotion audit — H1-G

Controlled contract audit covered publish refusal / success / rollback behaviours and related provenance checks.

Boundary:

- contract audit, not proof of distributed atomicity
- no crash/network/multi-node consensus guarantee
- wording was narrowed from broad `atomic` language to single state-transition event / no partially activated state under the tested contract

### 4.7 Gate ordering — H1-I

Measured 24 permutations of four checks over six constructed states, 144 evaluations, 0 verdict divergences; positive order-dependent control separated.

Safe claim:

> a sequence/conjunction of candidate-state predicates whose acceptance result is invariant to evaluation order

Forbidden:

- mutually independent checks
- prescribed order matters to the observed verdict

### 4.8 Governance ablation — H1-J

Some filters are essential, some are load-bearing but masked by redundancy, and some ranking elements are not independently measurable with the current instrument.

Specificity was withdrawn as an independent ranking signal because it is definitionally tied to scope size in the current implementation.

### 4.9 A12 cause-conditioned recovery

Source/license work and same-family recipe work were substantially prepared, but runtime immutability / image identity remained externally blocked in prior state. Do not spend GPU on A12 merely because W6 uses GPU; these are separate gates.

### 4.10 Receipt overwrite incident

An earlier A12 runtime-readiness receipt was accidentally overwritten during tooling changes and could not be restored byte-identically from git because the directory was untracked. The incident is deliberately retained in the failed/superseded/incident record.

Do not erase or soften it.

---

## 5. W6 HISTORY — WHY v8 EXISTS

W6 asks whether the Living Knowledge / compiled temporal representation provides measurable benefit under the **same model intelligence** compared with non-temporal baselines.

### 5.1 v1 question set

Invalid/superseded because the question construction leaked target passage wording. Retained for provenance only.

### 5.2 v2 question set

Intent was moved to structured infobox attributes, but the then-available corpora used consecutive revisions. Structured facts rarely changed, producing zero revision-sensitive primary questions against the frozen minimum.

Endpoint remained NOT RUN.

### 5.3 corpus-v7 acquisition

Longer-separated snapshots solved the corpus-sufficiency problem.

Measured acquisition/integrity state from the completed v7 work:

- 391 eligible pages
- 293 revision-sensitive attributes across 151 articles
- 2,522 unchanged controls
- 11/11 corpus integrity gates passed
- 0 incomplete directories

### 5.4 v7 frozen-protocol development failure

The v7 question set reached the primary sample requirement, but pre-arm gates failed.

Measured development diagnosis:

- query/oracle overlap was dominated by subject/title terms
- BM25 frequently found the correct subject/document family but the wrong unit/revision
- the original benchmark confounded entity localization with temporal-unit discrimination

The v7 run is development evidence. It is sealed and must not be converted into confirmatory evidence by tuning and rerunning the same questions.

### 5.5 v8 design response

v8 separates deterministic Stage-0 subject/entity routing from the temporal evidence-selection problem, adds structural taint protection, residual-overlap calibration, a stronger BASIC RAG+ baseline, explicit temporal scoring, and a fail-closed untouched-holdout boundary.

---

## 6. v8 DEVELOPMENT STATE — BUILT, DO NOT REDO

The following development machinery has been built and tested. Reconcile live files, but do not rebuild from scratch merely because this is a new session.

### 6.1 Structural taint gate

Question builder may use structured intent fields, but not answer value or oracle passage text. Mutation/falsification controls exist and separate.

### 6.2 Residual overlap calibration

Structured-intent vocabulary is separated from residual passage-derived overlap. Development ceilings were calibrated/frozen before the untouched holdout.

### 6.3 Stage-0 entity routing

Deterministic subject -> document namespace routing, identical across arms.

### 6.4 v8 question generator

Development result after correcting the value-change eligibility representation:

- v7-style revision-sensitive candidates: 293
- v8 primary revision-sensitive: **194**
- markup-only cases excluded from primary eligibility: **96**
- markup-only outside primary path: 20
- degenerate value: 3

Exact wording boundary:

> 96 cases fail the frozen v8 value-change eligibility representation and independently match the development markup-only diagnostic.

Do **not** write `96 proven non-semantic`.

The 4-reject / 3-admit control is detector liveness, not classification accuracy.

### 6.5 Holdout overlap guard defect — fixed before holdout opening

An earlier guard read the wrong key from the v7 development seal, so the development-title set became empty and the guard would have passed a contaminated holdout.

That was a serious fail-open defect.

Current implementation is expected to:

- read the correct sealed title list
- fail closed if the seal records no development titles
- reject title overlap
- exercise the refusal path in tests

Re-verify; do not assume.

### 6.6 Four arms

Built:

- `RAW`
- `BASIC_RAG`
- `BASIC_RAG_PLUS`
- `TAVONEL`

`BASIC_RAG_PLUS` uses deterministic BM25 + RM3 pseudo-relevance feedback. It adds retrieval strength, not extra model intelligence, and does not receive temporal metadata that BASIC RAG lacks.

### 6.7 Shared fairness contract

The same model intelligence / decoding contract applies across arms. Controls reject decoding drift, temporal-metadata leakage and extra intelligence.

### 6.8 Answer normalization and scoring

Built:

- normalization
- answer correctness
- evidence correctness
- provenance localization
- temporal correctness
- stale answer / stale evidence distinctions
- unsupported assertion
- abstention appropriateness

A development control caught a real numeric-normalization bug (`1,450` vs `1450`), which was repaired.

### 6.9 Statistics

Built without SciPy dependency:

- exact binomial McNemar on discordant pairs
- paired difference
- Newcombe paired interval
- discordant and concordant counts
- Holm correction across seven secondary endpoints

Report effect sizes / intervals, not a naked p-value.

### 6.10 Deterministic development E2E

Development harness ran 177 questions x 4 arms with a non-inferring development model. Those numbers are **harness checks, not scientific results**.

Do not cite development-model arm outcomes as W6 endpoint evidence.

### 6.11 Fail-closed pre-holdout gate

Built and mutation/break controlled. It must refuse holdout opening unless all required development, freeze, runtime and repository conditions are satisfied.

### 6.12 Freeze builder

Built to require explicit decisions and refuse to overwrite an existing freeze. It must pin model/runtime identity, decoding, retrieval, scoring, statistics, exclusions, holdout selection and stop rules.

---

## 7. FOUNDER DECISIONS — FINAL, DO NOT ASK AGAIN

These have been decided.

### 7.1 Model

Use:

`Qwen/Qwen3.6-27B`

No automatic fallback to Qwen3.5, Gemma, provider API models, Codex, Claude, or any other model.

Decoding decision:

- temperature = 0.0
- max_tokens = 256
- tools = off
- one shared model contract for all four arms

### 7.2 RAW context policy

Use **whole-document RAW**, not the shared 3,000-token truncation budget.

Development measurement motivating the decision:

Shared 3,000-token policy:

- truncation rate ~= 0.8701
- oracle lost by truncation ~= 0.5763
- evidence correctness ~= 0.1299
- answer correctness ~= 0.8305

Whole-document policy after implementation:

- truncation = 0.0 in the measured development run
- oracle loss = 0.0
- evidence correctness ~= 0.2260
- answer correctness ~= 0.9209

Safe interpretation:

> Removing the shared truncation budget eliminated measured oracle loss and materially changed RAW outcomes; the prior RAW result was materially budget-confounded.

Do not overclaim that the remaining RAW number is a universal representation floor.

If the real model cannot fit both documents:

- never silently truncate
- record `RAW_CONTEXT_OVERFLOW`
- report RAW overflow separately
- the primary TAVONEL vs BASIC RAG paired comparison remains governed by the frozen primary rules because RAW is not the primary comparator

Report per-arm context tokens/utilization, latency and inference cost.

### 7.3 `before_after_separable_share`

Disposition:

`GENERATOR_INTEGRITY_CHECK_ONLY`

It is excluded from independent difficulty evidence because the generator and the metric use the same value-token distinction. Do not invent a replacement metric now.

---

## 8. CRITICAL MODEL-IDENTITY RECONCILIATION — FIRST MATERIAL TASK IN NEW SESSION

There is an important registry inconsistency that must be resolved **before the v8 holdout is opened**.

### 8.1 Candidate evidence registry

`benchmark/v6/candidate-registry.yaml`

For `qwen3.6-27b`, the repository records:

- upstream repository: `Qwen/Qwen3.6-27B`
- an existing exact `identity.revision` value
- execution state indicating artifact manifest/runtime work is still pending

Treat this existing candidate-registry revision as the **EXPECTED_MODEL_REVISION** unless live repository evidence establishes a formally superseding decision.

### 8.2 Runtime model registry

`infra/model-registry/models.yaml`

For `qwen3_6_precision`, the observed state was:

- upstream id = `Qwen/Qwen3.6-27B`
- `upstream_revision: null`
- vLLM runtime version null
- runtime image digest null

Therefore the correct statement is **not** `there is no pinned revision`.

The correct state is:

> the candidate evidence registry carries an expected pinned revision, while the runtime model registry has not yet been qualified against it.

### 8.3 Required equality chain

Before config freeze / holdout opening:

`candidate registry EXPECTED revision`

must equal

`live runtime ATTESTED revision`

must equal

`config-freeze model revision`

If they differ:

`MODEL_IDENTITY_MISMATCH`

Fail closed. Do not silently update the candidate revision after seeing the runtime.

### 8.4 Required runtime attestation fields

The live runtime qualification must capture at least:

- exact checkpoint/upstream revision
- model-file manifest SHA256
- tokenizer identity
- tokenizer hash
- serving runtime
- serving runtime version
- immutable runtime image digest
- model attestation

If the expected Qwen revision cannot be qualified exactly:

`MODEL_RUNTIME_NOT_READY`

No fallback model.

---

## 9. TEST / LINT STATE AT HANDOFF BOUNDARY

Do not blindly reuse this number. Reconcile the current machine receipt after entering the new session.

Last canonical machine-emitted repository-green state observed before the final model/RAW decision edits:

- collected = 2,955
- passed = 2,909
- failed = 0
- skipped = 46
- `repository_green = true`

After the founder-decision implementation, the prior worker initiated another full-suite run. Its final canonical result was not part of the handoff evidence available when this master file was written.

Therefore:

1. inspect current `docs/repro/TEST_SCOPE_STATUS.json`
2. compare its generation/write time to the latest A6.5 code edits
3. if stale, run the project-venv full suite cleanly with no concurrent receipt writes
4. if a failure occurs, capture failing test identity + traceback; do not run with `--tb=no` if diagnosing a new failure

There was one earlier one-off full-suite failure whose identity was not captured. Safe wording remains:

> likely concurrent receipt-write race

It is not established or proven.

### Lint boundary

An unrelated/untracked `tests/unit/test_parser_verification.py` produced ruff findings when the worker widened lint scope. The worker correctly did **not** call it pre-existing because git history could not date it.

Do not modify unrelated files simply to make an A6.5-owned lint scope green. But clearly distinguish:

- A6.5-owned files lint status
- relevant W6 experiment-tree lint status
- wider repository lint status

---

## 10. HOLDOUT PURITY — ABSOLUTE RULES

At this handoff boundary the v8 untouched holdout must still be:

`UNOPENED`

Before config freeze + preflight all-pass, do not:

- create the holdout manifest from untouched titles
- inspect untouched title content
- preview holdout questions
- dry-run the holdout generator
- dry-run holdout leakage/baseline gates
- fetch a sample from the untouched cohort “just to check”
- use holdout information for tuning

The 6,237 untouched-title source pool mentioned by the development freeze is a selection source, not permission to inspect it.

The holdout is opened once.

---

## 11. NEW SESSION EXECUTION ORDER — DO THIS, DO NOT RE-PLAN FROM SCRATCH

### Phase 1 — reconcile and qualify model identity

1. Reconcile live repo and rules.
2. Read this file and current v8 handoff/dev findings.
3. Verify holdout status is still unopened.
4. Verify the v7 development seal and all expected development hashes.
5. Reconcile current test/lint status.
6. Reconcile candidate-registry Qwen expected revision vs runtime-model-registry null fields.
7. If canonical goal tooling is available, update/reconcile the canonical goal state from the fresh runtime session.
8. Build/qualify the actual Qwen3.6-27B runtime against the existing expected revision.
9. Capture all required attestation fields.
10. Fail closed on revision mismatch or missing immutable runtime identity.

### Phase 2 — config freeze

Once runtime attestation is valid:

1. write the v8 config-freeze receipt using the already-decided founder choices
2. pin the exact Qwen identity and runtime attestation
3. pin decoding = temperature 0.0, max_tokens 256, tools off
4. pin RAW whole-document policy
5. pin separability = generator integrity only
6. pin BM25 / RM3 / top-k / entity routing
7. pin scoring/statistics/exclusion rules
8. pin holdout selection and stop rules
9. re-run freeze verification and confirm it does not overwrite

### Phase 3 — pre-holdout verification

1. run focused v8 tests
2. run relevant lint
3. run full repository suite under project venv, with no concurrent writes
4. verify `repository_green = true`
5. run the fail-closed pre-holdout gate
6. require **all** current conditions to pass
7. confirm holdout status remains unopened

If any condition fails, fix the actual condition without touching the holdout.

### Phase 4 — open untouched v8 holdout once

Only after preflight all-pass:

1. deterministically build the holdout manifest from the untouched source pool under the frozen selection rule
2. acquire the holdout
3. freeze acquisition integrity/hashes
4. build the holdout question set under the frozen generator
5. run structural taint / residual leakage gates
6. run baseline validity gates

If a pre-arm gate fails:

- do not run the four arms if protocol forbids it
- report the confirmatory gate failure as measured
- do not tune and immediately create V9

If all pre-arm gates pass:

1. run RAW
2. run BASIC RAG
3. run BASIC RAG+
4. run TAVONEL
5. score all endpoints
6. compute paired statistics
7. create the W6 endpoint receipts

### Phase 5 — W6 scientific interpretation

Primary:

- revision-sensitive answer correctness
- primary comparison = TAVONEL vs BASIC RAG

Also report:

- stale-answer rate
- temporal correctness
- evidence correctness
- provenance localization
- unsupported assertion rate
- appropriate abstention
- paired effect size
- confidence interval
- discordant counts

Do not report only significance.

Valid outcomes include:

- TAVONEL clearly better
- similar answer correctness but lower stale/provenance errors
- no measurable advantage
- TAVONEL worse
- pre-arm confirmatory gate failure

All are legitimate results.

---

## 12. AFTER W6 — PATENT + PAPER MUST BE UPDATED IN THE SAME PASS

W6 completion is not the end of the programme.

Immediately synchronize:

### Patent

- `docs/ip/PATENT_CLAIMS_v1_2026-08-19.md`
- `docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md`
- claim-evidence matrix / element support
- figures
- prior-art memo
- counsel flags

### Paper

- manuscript
- abstract
- methods
- results
- failure analysis
- limitations / threats to validity
- tables
- figures
- reproducibility statement
- conclusion

### Audit / status

- hostile review
- reviewer red-team
- convergence protocol/rounds
- failed/superseded ledger
- incident log
- experiment manifest
- execution index
- submission readiness checklist
- programme status

Standing rule learned from P14/P19/P22:

> a scientific narrowing is not finished until claims, specification, manuscript, tables and figures all reflect the same boundary.

---

## 13. CONVERGENCE / PATENT SUPPORT WORK AFTER W6

The convergence framework was expanded because prior “clean” sweeps missed proposition-level and element-level defects.

Important historical classes:

- withdrawn assertion propagation
- inferred-vs-measured wording
- numerical receipt binding
- claim amendment direction
- element-level claim support
- figures/captions outrunning claims
- test-scope reporting

The live repository now contains `docs/audit/STANDING_BOUNDS.yaml`; reconcile the current standing-bound policy rather than relying on an old handoff count.

Historically, some amendment history is unrecoverable because older claim sets were not retained in git. That limitation should remain visible rather than being fabricated away.

After W6, run the current convergence machinery prospectively and close all **actionable** material findings. Do not redefine the stop rule after seeing a round merely to make it clean.

If current Pass-K-like element-level support findings remain, bind each independent-claim element to:

- exact claim language
- specification paragraph
- implementation location
- evidence receipt
- evidence class
- limitation / unsupported breadth
- counsel flag where needed

Do not call claim-level evidence element-level evidence unless it actually supports that element.

---

## 14. CLAIM / PAPER WORDING BOUNDARIES TO PRESERVE

### Identity

Do not say:

- candidate attribution is diagnostic only
- BLOCKED is semantically equivalent
- residual divergences are harmless permutations
- exact sparse acceleration is impossible

### Promotion

Do not imply distributed/crash atomicity.

### Gate ordering

Use order-invariant conjunctive acceptance wording, not “mutually independent ordered checks.”

### Governance

Do not present unmeasured ranking elements as independently validated.

### Natural evidence

Do not call one-family retrospective Wikipedia evidence broad cross-source real-world validation.

### v8 generator

Do not call the 96 excluded cases proven non-semantic.

### Separability

Do not cite `before_after_separable_share = 1.0` as independent difficulty evidence.

### One-off suite failure

Do not call the receipt-write race established; safe phrase is “likely concurrent receipt-write race.”

### RAW

Do not present the old 3,000-token RAW result as a representation floor; it was materially budget-confounded.

---

## 15. COST / GPU DISCIPLINE

W6 now requires a real Qwen3.6-27B runtime, so GPU spend is expected.

Rules:

- spend only after model identity/runtime qualification requirements are clear
- record runtime image/model/tokenizer identity before confirmatory execution
- record cost per arm / total cost where measurable
- do not burn GPU on A12 or unrelated experiments merely because a W6 pod exists
- no repeated holdout reruns for tuning

The W6 confirmatory run should be treated as a one-shot evidence event after development configuration is frozen.

---

## 16. FILES TO READ FIRST

Minimum first-read set:

1. `research/TAVONEL_W6_V8_NEW_SESSION_MASTER_HANDOFF_2026-08-20.md` — this file
2. `research/experiments/H1-W6-SAME-INTELLIGENCE-01/V8_FRESH_SESSION_HANDOFF_2026-08-19.md`
3. `research/experiments/H1-W6-SAME-INTELLIGENCE-01/V8_DEVELOPMENT_FINDINGS_2026-08-19.md`
4. current v8 protocol file in `research/experiments/H1-W6-SAME-INTELLIGENCE-01/`
5. `research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/freeze_config_v8.py`
6. `research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/preflight_holdout_v8.py`
7. v8 arms / scoring / stats modules in the same experiment
8. `tests/unit/test_w6_v8_arms.py`
9. `tests/unit/test_w6_v8_freeze.py`
10. `tests/unit/test_w6_v8_gates.py`
11. `tests/unit/test_w6_v8_model_identity.py`
12. `tests/unit/test_w6_v8_preflight.py`
13. `benchmark/v6/candidate-registry.yaml`
14. `infra/model-registry/models.yaml`
15. `docs/repro/TEST_SCOPE_STATUS.json`
16. `research/PROGRAM_STATUS_2026-08-19.md`
17. `docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md`
18. `docs/audit/STANDING_BOUNDS.yaml`

Then read current patent/paper package before W6 result synchronization.

---

## 17. ROOT-GOAL COMPLETION BAR

Do not declare `ROOT_GOAL_COMPLETE` merely because W6 ran.

Required final state:

### Science

- W6 v8 confirmatory outcome executed under untouched/frozen protocol, or honestly stopped at a frozen confirmatory gate
- all currently runnable load-bearing experiments executed or defensibly blocked/not-run
- negative/null evidence preserved
- evidence classes explicit

### Patent

- claim/evidence matrix synchronized
- independent/dependent claim scope defensible
- element-level support mapped
- specification supports current claim language
- no stale stronger wording in figures/tables/manuscript
- no unresolved critical hostile patent finding

### Paper

- complete manuscript structure
- all headline numbers receipt-backed
- W6 result integrated honestly
- failure analysis and limitations complete
- figures/tables publication-ready
- reviewer red-team material fixable issues closed

### Reproducibility

- receipts self-hash valid
- undeclared drift = 0
- historical drift classified
- failed/superseded ledger complete
- current experiment invocations/environment/model identity captured

### Engineering

- relevant tests green
- full repository scope reported honestly
- required generators/audits green

### Status

- only genuinely external/non-runnable blockers remain
- programme status and submission checklist reflect the same final DAG

---

## 18. WORKER BEHAVIOUR FOR THIS NEW SESSION

Use the live repo as source of truth.

Do not ask the founder again about the three v8 decisions; they are final in §7.

Do not reopen design questions already frozen unless a hard contradiction makes the frozen protocol impossible to execute.

Do not stop after reporting a finding.

Preferred loop:

```text
while ROOT_GOAL not complete:
    reconcile live evidence
    choose highest-value runnable gap
    inspect implementation/evidence
    freeze protocol/config if required
    execute
    falsify / run controls
    retain failed/null evidence
    update claim implications
    update patent/paper/figures when evidence changes
    run integrity/tests at the proper batch boundary
    immediately continue to next runnable gap
```

When a background suite runs and writes are prohibited, continue read-only work. When it finishes, resume writes immediately.

---

## 19. IMMEDIATE NEXT ACTION

The next worker should **not** start by acquiring the holdout.

Start with the Qwen3.6-27B identity chain:

1. read expected exact revision from `benchmark/v6/candidate-registry.yaml`
2. inspect `infra/model-registry/models.yaml`
3. qualify a real Qwen3.6-27B runtime
4. prove expected revision == attested revision
5. capture model-file/tokenizer/runtime/image attestations
6. generate immutable v8 config freeze with founder decisions already fixed
7. run full suite + preflight all-pass
8. confirm holdout remains unopened
9. only then open the untouched v8 holdout

Then drive W6 through endpoint and continue directly into patent/paper synchronization and final convergence.
