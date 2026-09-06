# GPU successor readiness — decision-grade assessment

Written for the orchestrator's run/no-run decision. It reads
`protocols/GPU_SUCCESSOR_STUDY_V1.yaml`, `GPU_SUCCESSOR_STUDY_V2.yaml`,
`GPU_SUCCESSOR_MODEL_PIN_V1.yaml`, `GPU_SUCCESSOR_RUNTIME_V1.yaml`,
`GPU_SUCCESSOR_RUNTIME_V2.yaml`, the preflight/execution/launch/freeze tools
under `tools/`, every immutable receipt those tools have ever written, and
`paper/CLAIM_MATRIX.yaml`. Every figure below was read from a file this pass
opened and, where a `receipts/latest/*.json` pointer was involved, verified by
recomputing the pointed-to file's own sha256 and comparing it against the
pointer's `points_to_file_sha256` field — the arithmetic is shown at the point
it is used. Nothing here reports a reading this pass did not perform.

---

## 1. What exists, read directly

**Two generations of protocol, not one.** `GPU_SUCCESSOR_STUDY_V1.yaml`
(authored 2026-08-23) is `status: DRAFT_NOT_FROZEN` and has never left that
state — no `gpu-successor-v2-protocol-freeze`-equivalent receipt exists for
it, and its own gate `G_SUCC_PROTOCOL_FROZEN` (line 84) would refuse it on
that basis alone. `GPU_SUCCESSOR_STUDY_V2.yaml` (authored 2026-08-27, today)
declares `status: FROZEN` in its own text (line 6) with
`freeze_semantics: prospective and result-blind; FROZEN does not imply
execution authority` (line 7) — a self-declared field, not an immutable
freeze receipt. `tools/freeze_gpu_successor_v2_protocols.py` is the only
mechanism that would seal that declaration (schema
`tavonel.v2.gpu_successor_v2.protocol_freeze.v1`, stem
`gpu-successor-v2-protocol-freeze`), and no receipt with that stem exists
anywhere under `research/tavonel_eval_v2/receipts/` (checked by listing every
receipt whose name contains `gpu`). **The V2 protocol's `FROZEN` field is
text, not proof.**

**Hypothesis, arms, endpoints, decision rule (V1).** The study varies
*currency* of served compiled state — `VERIFIED_CURRENT_TYPED` vs
`STALE_APPEND_ONLY` — holding model, decoding, prompt template and question
fixed (`GPU_SUCCESSOR_STUDY_V1.yaml` §3, lines 182–227). Scoring classes are
`ANSWER_MATCHES_CURRENT` / `ANSWER_REFUSED` / `ANSWER_OTHER`, paired into
`NO_DIFFERENCE` / `DIFFERENCE_TOWARD_CURRENT` /
`DIFFERENCE_TOWARD_STALE_OR_WORSE` / `DIFFERENCE_NEITHER_CORRECT` (§7, lines
383–424). The decision rule is a hard preflight gate list, not a threshold on
the outcome: `run()` in `tools/gpu_successor_preflight.py` (lines 815–971)
computes twelve `G_GSP_*` gates and reports `READY_TO_AUTHORIZE` only if every
one passes; `verdict` is otherwise `BLOCKED` (line 944).

**Hypothesis, arms, endpoints, decision rule (V2).** V2 adds a third arm,
`CURRENT_TEXT_ONLY`, and a formal inferential design: exact paired McNemar
test at power 0.90, two-sided alpha 0.05, minimum detectable risk difference
0.10, target lineages 450, one SHA-256-selected question per lineage
(`GPU_SUCCESSOR_STUDY_V2.yaml` `inferential_design:`, lines 590–615). Its
authority section (lines 9–17) requires an explicit, path-and-sha256-bound
`SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4` (SFIR4) acceptance receipt with
`ACCEPTED/PASS`, and forbids `latest_pointer`, `newest_wins`,
`receipt_stem_glob` and `historical_manifest` as discovery mechanisms (line
16). Its four-link gate requires **independent** revalidation against an
"exact immutable V2 universe" manifest with a floor of 450 (lines 32–37).

**Pre-registration status.** V1: draft, never frozen. V2: self-declared
frozen in the file's own text; no freeze receipt exists to seal that
declaration, so by the V1 protocol's own standard for what "frozen" means
(an immutable receipt sealing a digest, `gpu_protocol_freeze.verify_freeze` in
`tools/gpu_successor_preflight.py`), **V2 is not provably frozen either** —
it asserts its own status rather than having it attested externally.

---

## 2. What each stage of tooling actually does, and what it refuses

| Tool | What it does | What it refuses |
|---|---|---|
| `gpu_successor_preflight.py` (1083 lines) | CPU-only, twelve `G_GSP_*` gates over SFI3 held-out acceptance, four-link acceptance, protocol-bundle freeze, model-pin sealing, model pin identity, capability-not-inferred-from-name, tokenizer parity battery availability, runtime image digest form, materializer readiness, context-budget feasibility, cohort feasibility, closed-endpoint exclusion, cost-cap arithmetic. Writes `gpu_seconds: 0` and `estimated_cost_usd: 0.0` unconditionally (`G_GSP_NO_GPU_YET`, always `passed: true`). | Reports `BLOCKED` unless **all twelve** pass; never provisions anything; never reads a live GPU. |
| `gpu_successor_execution.py` (234 lines) | Fail-closed contract: validates a materialized input set's SHA-256 chain before provisioning is ever proposed, and validates a returned terminal worker result's structure after teardown. | Contains no network or credential code by design (module docstring); a pod id, health response or process id is explicitly stated to never count as scientific completion. |
| `launch_gpu_successor.py` (950 lines) | Orchestrates: re-runs the preflight, requires `--execute` to attempt provisioning, writes a receipt for every outcome (`REFUSED`/provisioned/whatever). | `test_no_bypass_flag_or_env_var_exists` (in `tests/test_launch_gpu_successor.py`) asserts the module's own source text contains no `import os`, `os.environ`, `os.getenv` — no environment-variable escape hatch around the gates is structurally possible without failing that test. |
| `launch_gpu_successor_v2.py` (322 lines) | Same orchestration role for the V2 bundle. | Requires the V2 protocol-freeze receipt (which does not exist) before it can proceed past its own precondition checks. |
| `gpu_successor_r2.py` (112 lines) | Content-addressed S3/R2 object transport (`put_if_absent`, key-path sanitisation, SHA-256 verification on upload). | Never discovers or reads credentials itself — accepts an already-configured client only (module docstring). Refuses any object key containing `..` or a leading `/`. |
| `build_gpu_successor_v2_cohort.py` (348 lines) | Builds the V2 cohort manifest from the exact SFIR4-bound universe. | — (not run; no output receipt exists, see §3). |
| `build_gpu_successor_v2_contexts.py` (121 lines) | Materializes per-question context payloads for the three V2 arms. | — (not run). |
| `freeze_gpu_successor_protocols.py` (243 lines) | Seals the V1 study+runtime declaration pair into one immutable bundle-freeze receipt, digest-bound. | Refuses to seal a draft; V1's `status: DRAFT_NOT_FROZEN` means this has never been run to completion for V1 either. |
| `freeze_gpu_successor_v2_protocols.py` (219 lines) | Seals the fourteen-file V2 executable bundle (cohort builder, four-link acceptance, prompt schema, context builder, materializer, scorer, worker, inference, safety, runtime, RunPod backend, launcher, worker-bundle freeze, itself) plus the V2 study+runtime protocol pair, stem `gpu-successor-v2-protocol-freeze`. | `V2FreezeRefused` if any component is missing, unfrozen, or the bundle is incomplete. **No receipt with this stem exists — never successfully run.** |
| `freeze_gpu_successor_v2_worker_bundle.py` (185 lines) | Seals the exact worker code that would run on the pod, content-addressed. | — (not run; no receipt). |
| `runpod_provisioner.py` (in `tools/`) | The only module in this chain that makes a real network call: REST v1 for pod get/delete, GraphQL `podFindAndDeployOnDemand` for creation (chosen specifically because only GraphQL exposes `stopAfter`/`terminateAfter` auto-terminate fields — verified read-only against Runpod's own OpenAPI specs and `runpodctl` source, per the module's own docstring). Every GPU field it fills is read from `GPU_SUCCESSOR_RUNTIME_V1.yaml`, never invented. | Split out of `launch_gpu_successor.py` specifically so the bypass-flag test above can assert `import os` never appears in the orchestrator; credential reading lives only here. |
| `gpu_successor_v2_runpod_backend.py` (236 lines) | V2-specific provisioning backend, bound to `GPU_SUCCESSOR_RUNTIME_V2.yaml`'s tighter operational caps (5.75h/$38 inside the 6h/$40 founder ceiling) and its create-intent / positive-absence-proof deletion lifecycle. | Same structural isolation from the orchestrator's `os`-free contract. |

Nothing in this table is inferred from a filename. Every "what it does" cell
above was read from the file's own docstring or the function whose name is
named; every "what it refuses" cell cites a specific test or a specific
runtime check in the file.

---

## 3. Recorded state — has anything actually executed?

**No pod has ever been provisioned. No inference output has ever been
produced or verified.** Every receipt this pass could find and read says so
directly, and the receipts are read as immutable files, not through the
mutable `receipts/latest/*.json` pointers (each pointer's `points_to` was
followed and its `points_to_file_sha256` was verified against the pointed-to
file's actual SHA-256 before that file's content was trusted; all three
checked — preflight, pin, launch — matched).

- **Pin resolution** (`gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json`,
  pointer-verified): `gpu_seconds: 0`, `estimated_cost_usd: 0.0`,
  `cross_check_against_model_endpoint.all_match: true`. Explicitly: "It does
  not attest a live tokenizer load, a live config.json re-hash, or any model
  capability beyond what `capability_evidence.pointer` names."
- **Preflight** (`gpu-successor-preflight--20260823T073737Z-09f98c2086b2.json`,
  pointer-verified, earliest of two preflight receipts): `verdict: BLOCKED`,
  blocking on `G_GSP_COHORT_FEASIBILITY`, `G_GSP_HELD_OUT_PASS_PRESENT`,
  `G_GSP_MODEL_PINNED`.
- **Launch, most recent attempt**
  (`gpu-successor-launch--20260826T005726Z-e6f185ff8b08.json`,
  pointer-verified): `outcome: "REFUSED"`, `provisioning: null`,
  `invocation.execute: false` (this was a dry run — `--execute` was never
  passed), `gpu_seconds: 0`, `estimated_cost_usd: 0.0`. Blocking gates:
  `G_GSP_COST_WITHIN_CAP`, `G_GSP_HELD_OUT_PASS_PRESENT`,
  `G_GSP_MODEL_PINNED`. Reading the gate detail: this invocation was called
  **without a `--model-pin` argument** (the gate's `detail` shows
  `repository: ""`, `revision: ""` — empty strings, not a resolution
  failure) and against the *development* manifest
  `artifacts/development/typed_fact_cohort.json` (20,018 facts), whose cost
  arithmetic is shown in the receipt: `20018 × 2 arms × 2 repeats = 80,072
  calls`, `80,072 × 2,304 tokens/call = 184,485,888 tokens`,
  `184,485,888 / 2000.0 tok/s = 92,242.9 s = 25.62 GPU-hours`,
  `25.62 × $2.5/hr = $64.06` — **more than four times the $40 cap and more
  than four times the 6-hour cap.** Five earlier launch receipts exist
  (2026-08-23 through 2026-08-25), every one also `execute: false` or refused.
  **No launch receipt in this study's entire history shows `execute: true`
  with a non-null `provisioning` block.**
- **V2 chain**: zero receipts exist for `gpu-successor-v2-protocol-freeze`,
  any V2 cohort build, any V2 four-link acceptance, any V2 worker-bundle
  freeze, or any V2 launch, checked by listing every receipt filename
  containing `gpu` and `v2` under `research/tavonel_eval_v2/receipts/`
  (outside the read-only forensic snapshot directory, which is historical
  evidence of a different incident, not a live receipt store).
- **SFIR4** (the study V2 depends on for its authority chain): three receipts
  exist —`sfir4-core-conformance.json` (`verdict: PASS`, a static-import
  conformance check only), `sfir4-core-revision-comparison.json` (a
  read-only diff report, no verdict field), and
  `sfir4-execution-closure.json`, whose **verdict is `REFUSE`**: "3 of 83
  files in the closure differ from the bytes committed at HEAD, so the
  manifest pins bytes git cannot return." No `SOURCE_FACT_IR_INDEPENDENT_
  REPLICATION_V4` acceptance receipt of any kind exists — searched by name
  pattern (`*acceptance*`) across the receipts directory and found nothing
  for SFIR4. **The exact authority V2's own `authority:` block requires
  (line 15, `source_acceptance_requirement: ACCEPTED/PASS`) does not exist.**

**Conclusion for this section, stated plainly**: a pod has never been
created for this study. Provisioning has never been attempted with
`--execute`. No inference has ever run. No output has ever been scored.
Every dollar and every GPU-second in every receipt this study has ever
written is `0` / `0.0`.

---

## 4. Claims that depend on this experiment (`paper/CLAIM_MATRIX.yaml`)

- **F-02** (forbidden claim, line 24): "model QA improvement across all
  semantic revisions" — why forbidden: "no model was ever run. The model
  experiment is NOT_RUN — PREDEFINED CPU PREFLIGHT INFEASIBLE."
- **C-30** (line 757): `status: NOT_YET_ESTABLISHED`, `receipt: PENDING`,
  `allowed: []`. Wording: "RESERVED. The downstream effect of
  verified-current typed source-fact state versus stale or append-only
  state... under a hard cap of 6 GPU hours and $40." Its own `limitations`
  say: "the slot is reserved, not filled. The study is gated on a held-out
  PASS that does not exist, and no GPU second has been spent."
- **C-15** (line ~347): already-established held-out negative result — three
  preregistered CPU preflights (the closed `MODEL_ENDPOINT_V1` line, distinct
  from this successor) refused to start a GPU experiment, spending 0 GPU
  seconds of an approved $40. This is evidence the *preflight-then-refuse*
  discipline already has a track record, not evidence for the successor
  itself.
- **C-33 / C-34 / C-35** reference the GPU successor only in their
  `forbidden` lists ("SFI3 or the GPU successor passed" must never be
  claimed) — none of them are GPU results.
- **G-02** (paper readiness gap, line 931): "no model was run; SFI3
  exhausted its frozen frame with a family quota shortfall and was not
  scorable, and SFIR1 through SFIR3 each terminated before payload, so no
  successor cohort or GPU authority exists." Consequence: "no claim about
  model behaviour of any kind is available."

No other claim row cites the GPU successor as its evidentiary receipt.

---

## A. Is the GPU experiment scientifically required?

**No.** The paper's stated contribution — stable identity separated from
evidence occurrence, independent typed identity/change decisions, fail-closed
quarantine of unsettled identity, revision-bound SourceFact witness, typed
dependency propagation, selective candidate recompilation, isolated candidate
generation, provenance continuity + quarantine release + from-scratch
equivalence, atomic verified activation — is a claim about **what the
compiler does to its own artifacts**. Every one of those nine links is
established (to whatever degree it is established) by CPU-only, compiler-
internal instruments already in this evidence tree: `akc_cir.identity`,
`akc_cir.semantic_diff`, `akc_cir.dependency`, `akc_cir.recompilation`,
`source_fact_ir/ir.py`, the migration-closure V2R4 chain (C-34, held-out
positive), the forensic four-divergence replay (C-23), and the change-facets
design this document's sibling (`CHANGE_FACETS_AND_ARTIFACT_SENSITIVITY_v1.md`)
specifies. None of those measurements involve a language model, a GPU, or an
inference call of any kind.

The GPU successor study measures a **different, downstream question**: given
the compiler's typed output, does an LLM's *answer to a question* change when
the served context moves from a stale carried-forward artifact to the
verified-current typed one (V1's `arms_axis`, line 185), or additionally
whether typed representation beats a text-only baseline at fixed currency
(V2's `representation_superiority` estimand, line 610). This is a claim about
**model consumption of the compiler's output**, not about the compiler's own
correctness. The claim matrix agrees with this reading explicitly: C-30's own
`limitations` block and G-02 both frame the GPU study as producing "a claim
about model behaviour," and the study protocol itself (`GPU_SUCCESSOR_
STUDY_V1.yaml`, "authorization" §10) lists among what a PASS or FAIL each
authorise: "citing this result as evidence that serving the verified-current
typed state changed model answers relative to a stale carried-forward
artifact" — never "the compiler is correct" or "recompilation is selective."

So: **none of the nine core incremental-recompilation links need a GPU run.**
The GPU study supports a separate, explicitly secondary and currently
`RESERVED`/`NOT_YET_ESTABLISHED` claim (C-30) about whether an LLM downstream
of the compiler answers differently when served current versus stale typed
state. That is a real and legitimate thing to want to know, and the founder
has pre-authorized spend for it — but it is evidence for a downstream-
consumption story, not for the recompilation mechanism the paper's core
contribution is about.

---

## B. Exact preflight gap

| Requirement | State | Citation |
|---|---|---|
| Exact model revision pinned | **PRESENT** (as a file) | `GPU_SUCCESSOR_MODEL_PIN_V1.yaml` §2 (`model.repository`, `model.revision` = `6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`), cross-checked against `MODEL_ENDPOINT_V1.yaml` in `gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json` (`cross_check_against_model_endpoint.all_match: true`). **But**: the most recent real launch attempt was invoked without supplying this pin (`G_GSP_MODEL_PINNED.detail.repository: ""` in the 2026-08-26 launch receipt) — the file exists; the operational habit of actually passing it does not yet have a green run behind it. |
| Tokenizer hash/parity check | **PARTIAL** | Static: `tokenizer_parity_available()` passes (`gpu_successor_preflight.py`, `G_GSP_TOKENIZER_PARITY_BATTERY_AVAILABLE`), the frozen probe battery digest is deterministic. Live: `GPU_SUCCESSOR_MODEL_PIN_V1.yaml` §4 states plainly "no tokenizer is loaded in this pass... recorded as NOT_YET_ATTESTED, never faked as a pass." **ABSENT for the live check.** |
| Inference template fixed | **PRESENT** | V1 cohort manifest carries `prompt_schema_digest`; V2 has a dedicated `gpu_successor_v2_prompt_schema.py` component in the frozen-bundle component list (`freeze_gpu_successor_v2_protocols.py`, `COMPONENTS`). Not yet exercised against real output, but the artifact exists and is digest-bound. |
| Container image digest | **PRESENT** | `runpod/pytorch@sha256:0a360022e8de4375af99430f84e8b38951acc397252163a37ceac7204d01be35`, form-checked by `G_GSP_RUNTIME_IMAGE_PINNABLE` (passed in every preflight receipt read). |
| CUDA/runtime info | **PRESENT, but explicitly `declared_assumption` not `measurement`** | `GPU_SUCCESSOR_RUNTIME_V1.yaml` §3 (`serving_stack.engine: vllm`, `engine_version: 0.27.1`, `dtype: bfloat16`) — every field there is tagged `kind: declared_assumption` and the file's own header says "No GPU second has been spent against this declaration." |
| Input manifest | **PRESENT but disqualified** | The only cohort manifest that reports `feasible: true` is `artifacts/development/typed_fact_cohort.json` (20,018 facts), and its own `source_acquisition_artifact` field names `artifacts/development/sfi2/sfi2_acquisition.json` — the SFI2 corpus. `GPU_SUCCESSOR_STUDY_V1.yaml`'s own `relates_to.SOURCE_FACT_IR_HELDOUT_V1` clause (line ~37) states SFI2's corpus "is development material only. This study's cohort is drawn from a DIFFERENT frame — the fresh held-out run that supersedes it, not from SFI2's spent corpus." **The one manifest that currently passes the feasibility gate is the one the protocol says must not be used.** No qualifying held-out manifest exists. |
| Expected experiment count | **PRESENT** | Worked arithmetic in `GPU_SUCCESSOR_STUDY_V1.yaml` §6 (cohort 120 → 480 calls; boundary at 4,687/4,688) and in every cost-cap gate detail in the receipts read. |
| Estimated upper-bound cost | **PRESENT, and it currently fails** | See §C below — the only real arithmetic on file for a concrete cohort ($64.06 against the dev manifest) exceeds both caps. |
| Teardown path | **PRESENT** | `GPU_SUCCESSOR_RUNTIME_V2.yaml` `resource_lifecycle` block: `platform_terminate_after_seconds: 20700`, `process_watchdog_seconds: 20700`, `deletion.required_on_all_terminal_and_exception_paths: true`, `positive_absence_proof_required: true`. Not yet exercised against a live pod. |
| Failure cleanup | **PRESENT** | Same block; `boundary_rule` requires "three positive read-after-delete absence observations" and a dedicated authoritative usage poll immediately before delete — designed, unexercised. |
| **(added — the gate that actually blocks everything)** Fresh held-out SOURCE_FACT_IR PASS | **ABSENT** | `G_GSP_HELD_OUT_PASS_PRESENT`/`G_GSP_SFI3_ACCEPTANCE_PASS` failed in every preflight and launch receipt read. SFI3 itself is `ESTABLISHED_NEGATIVE` (CLAIM_MATRIX C-33: non-scorable, Wikipedia quota short 25 of 70). SFIR1 through SFIR3 all terminated before payload (C-35). SFIR4's own execution-closure gate reports `verdict: REFUSE` (`sfir4-execution-closure.json`) and no SFIR4 acceptance receipt of any kind exists. |
| **(added)** V2 protocol freeze receipt | **ABSENT** | No `gpu-successor-v2-protocol-freeze` receipt exists; V2's `status: FROZEN` is self-declared text in the protocol file, not a sealed digest. |
| **(added)** INC-V2-089 line-item disposition | **BLOCKING, currently open** | `incident_ledger.md` line 7427: "the frozen instrument drifted, and the verifier could not see it." Disposition (line 7429–7431): "STOP THE LINE; no re-pin; no new freeze; no acquisition; no GPU." `receipts/frozen-instrument-integrity.json` verdict `FAIL`: 526 bindings checked, 59 frozen-drift, 29 files drifted, 20 receipts affected — including the scorer that produced the only PASS this whole research tree currently holds (V2R4, C-34). Explicitly unresolved as of the incident entry's own text: "No SFIR4 freeze was opened, no corpus was acquired, no GPU was provisioned and no paper claim was strengthened while this stands open." |

---

## C. Cost — the arithmetic, shown

Two ceilings exist, both founder-approved and both read from files, not
invented here:

- **V1/founder ceiling**: `6.0` GPU-hours, `$40.00` — `GPU_SUCCESSOR_STUDY_
  V1.yaml` §6 (line 316–317), reused verbatim in `GPU_SUCCESSOR_RUNTIME_
  V1.yaml` and in `gpu_successor_preflight.py` (`CAP_GPU_HOURS`, `CAP_USD`).
- **V2 tighter operational ceiling**: `5.75` GPU-hours, `20,700` GPU-seconds,
  `$38.00` — inside the same founder ceiling — `GPU_SUCCESSOR_RUNTIME_
  V2.yaml` `spend:` block.

The formula (`GPU_SUCCESSOR_STUDY_V1.yaml` §6, `formula:`, and reproduced
identically in `gpu_successor_preflight.estimate_cost`):

```
tokens_per_item      = prompt_tokens (2048) + max_new_tokens (256) = 2304
total_calls           = cohort_size × arms × repeats
total_tokens          = total_calls × tokens_per_item
estimated_gpu_hours   = (total_tokens / throughput_tok_per_s) / 3600
estimated_cost_usd    = estimated_gpu_hours × gpu_hourly_rate_usd
```

with declared assumptions `throughput_tok_per_s = 2000.0` and
`gpu_hourly_rate_usd = 2.5` (both `declared_assumption`, not measured —
`GPU_SUCCESSOR_RUNTIME_V1.yaml` §6).

**Worked examples that exist on file:**

| cohort_size | total_calls | total_tokens | GPU-hours | USD | within cap? |
|---|---|---|---|---|---|
| 120 (floor) | 480 | 1,105,920 | 0.1536 | $0.38 | yes |
| 4,687 (largest still inside hours cap) | 18,748 | 43,195,392 | 5.999 | $15.00 | yes |
| 4,688 (crosses hours cap) | — | — | 6.0006 | $15.00 | **no** |
| 6,000 (over-cap demo) | 24,000 | 55,296,000 | 7.68 | $19.20 | **no** |
| **20,018 (the only real dev-cohort manifest on file)** | **80,072** | **184,485,888** | **25.62** | **$64.06** | **no — actual gate result recorded in `gpu-successor-launch--20260826T005726Z-e6f185ff8b08.json`** |

**Defensible upper bound for a legitimate run**: the founder's own ceiling —
**≤6.0 GPU-hours / ≤$40.00** (V1) or the tighter **≤5.75 GPU-hours / ≤$38.00**
(V2 operational cap) — because `G_GSP_COST_WITHIN_CAP` / the V2 budget
boundary rule refuse anything above it by construction, arithmetically, with
no discretionary override (`GPU_SUCCESSOR_STUDY_V1.yaml`,
`cost_cap.refusal_is_arithmetic_not_judgement`). What the *actual* eligible
held-out cohort size would be, and therefore what the real run would cost
inside that ceiling, is **UNKNOWN** — no qualifying held-out cohort exists
(see §D). The only concrete cohort this study has ever measured cost against
($64.06 for 20,018 facts) is disqualified from being the launch manifest and
exceeds the cap regardless.

---

## D. Is the cohort available and unspent?

**No usable cohort currently exists.** The only manifest on disk that reports
`feasible: true` — `artifacts/development/typed_fact_cohort.json`, checked
directly (`eligible_count: 20018`, `feasible: true`, `floor: 120`) — is built
from `artifacts/development/sfi2/sfi2_acquisition.json`, i.e. the SFI2
corpus. `GPU_SUCCESSOR_STUDY_V1.yaml`'s `relates_to` block states SFI2's
corpus is "development material only" and that the study's cohort "is drawn
from a DIFFERENT frame — the fresh held-out run that supersedes it, not from
SFI2's spent corpus." This manifest therefore both (a) satisfies the numeric
feasibility gate and (b) violates the frame requirement the same protocol
states in the paragraph immediately above the gate — it is available, but it
is not the corpus this study is licensed to run on.

The corpus V2 actually authorizes — "exact V2 universe," schema
`tavonel.v2.gpu_successor_v2.cohort_manifest.v1`, run-id
`SFIR4_GPU_SUCCESSOR_UNIVERSE_V2`, sourced from "SFIR4 accepted acquisition
only" (`GPU_SUCCESSOR_STUDY_V2.yaml`, `authority.exact_v2_universe`, lines
18–24) — **does not exist**: no such manifest file, no SFIR4 acceptance
receipt, and SFIR4's own execution-closure gate is `REFUSE`
(`sfir4-execution-closure.json`).

No spend-overlap check was possible because there is nothing to check
overlap against: the only assembled cohort is explicitly the disqualified
one, and the qualifying one has never been built.

---

## E. Blockers, ranked

1. **INC-V2-089 stop-the-line, currently open — `incident_ledger.md:7427–7431`, `receipts/frozen-instrument-integrity.json` (verdict `FAIL`).**
   The incident's own disposition text is explicit: "no re-pin; no new
   freeze; no acquisition; no GPU" while it stands open. This blocks every
   other line item below by the project's own declared rule, independent of
   whether any other gate would otherwise pass. Twenty frozen receipts and
   twenty-nine files — including the scorer behind the study's only held-out
   PASS (V2R4) — no longer reproduce from the working tree, and the research
   tree (`research/tavonel_eval_v2/`) is confirmed untracked by git
   (`git ls-files` returns 0 paths under it per the incident entry), so there
   is no recovery path; the drifted bytes are gone.

2. **No held-out SOURCE_FACT_IR PASS exists for either study generation —
   `gpu_successor_preflight.py:815–971` (`G_GSP_HELD_OUT_PASS_PRESENT` /
   `G_GSP_SFI3_ACCEPTANCE_PASS`), `sfir4-execution-closure.json` (verdict
   `REFUSE`), `CLAIM_MATRIX.yaml:C-33` (SFI3 `ESTABLISHED_NEGATIVE`,
   non-scorable), `CLAIM_MATRIX.yaml:C-35` (SFIR1–3 all terminated before
   payload).** This is the study's own central, load-bearing gate
   (`GPU_SUCCESSOR_STUDY_V1.yaml:87`, `G_SUCC_HELD_OUT_SOURCE_FACT_IR_PASS`).
   Every preflight and launch receipt this study has ever produced fails it.

3. **V2 has no sealed freeze receipt — `freeze_gpu_successor_v2_protocols.py`
   (never successfully run; stem `gpu-successor-v2-protocol-freeze` absent
   from the receipts directory).** The protocol file's `status: FROZEN`
   (`GPU_SUCCESSOR_STUDY_V2.yaml:6`) is unattested self-declaration.

4. **No qualifying cohort exists — §D above.** The only feasible manifest is
   drawn from a corpus the protocol names as disqualified
   (`GPU_SUCCESSOR_STUDY_V1.yaml`, `relates_to.SOURCE_FACT_IR_HELDOUT_V1`);
   the exact V2 universe the frozen V2 protocol requires
   (`GPU_SUCCESSOR_STUDY_V2.yaml:18–24`) has never been built.

5. **The only concrete cost estimate on file exceeds both caps by roughly
   1.6× on hours and 1.6× on dollars — `gpu-successor-launch--20260826T005726Z-e6f185ff8b08.json`, `G_GSP_COST_WITHIN_CAP` detail** ($64.06 /
   25.62h against $40.00 / 6.0h). This is a direct consequence of blocker 4:
   fix the cohort source and this may resolve itself, but it is currently a
   real, independently-tripping gate.

6. **Model pin was not supplied on the one CLI invocation that got furthest —
   same receipt, `G_GSP_MODEL_PINNED.detail`** (empty repository/revision
   strings). Lower severity than 1–5: the pin file itself
   (`GPU_SUCCESSOR_MODEL_PIN_V1.yaml`) is well-formed and cross-checked
   (`gpu-successor-pin--20260823T082423Z-6902ef5f7efa.json`,
   `all_match: true`); this is an operator/invocation gap, not a missing
   artifact.

7. **Live tokenizer parity is `NOT_YET_ATTESTED` by the pin file's own
   admission — `GPU_SUCCESSOR_MODEL_PIN_V1.yaml` §4.** Lowest severity of
   the group: the static battery digest is deterministic and available; only
   the live load-time check is missing, and it requires either network
   access or a local model copy neither available in this preflight-only
   environment.

---

## Bottom line

The honest reading of everything cited above is that **the GPU experiment
should not run now**, for reasons that have nothing to do with whether it is
a good idea in principle:

- It is not scientifically required for the paper's core recompilation
  contribution (§A) — it would support a separate, already-`RESERVED`,
  explicitly secondary claim about downstream model consumption of the
  compiler's output.
- Its own preconditions are not met, by its own gates, on every receipt this
  study has ever produced (§B, §E.2).
- The one corpus that currently satisfies the feasibility count is the one
  the protocol says must not be used, and the one the protocol does require
  does not exist yet (§D, §E.4).
- The concrete cost estimate this study has actually computed exceeds the
  founder's approved cap by more than half again (§C, §E.5).
- A stop-the-line incident with an explicit "no GPU" clause is open and, by
  its own text, unrecoverable in its current form — no bytes exist to repair
  it with (§E.1).

None of this is manufactured to justify not running; it is what the study's
own instruments, receipts and incident ledger already say. A future run
becomes legitimate only after, in order: INC-V2-089 is resolved or formally
superseded by the founder; a fresh held-out SOURCE_FACT_IR PASS exists,
proven by an explicit acceptance receipt bound by path and SHA-256; the V2
protocol bundle is actually sealed by `freeze_gpu_successor_v2_protocols.py`
producing a receipt; the exact SFIR4-bound V2 universe manifest is built and
independently four-link-revalidated at or above its 450-lineage floor; and
the resulting cost estimate is recomputed and shown to sit inside the
approved cap. None of those five steps has happened yet.

---

## Addendum, 2026-08-27 — two of the blockers above moved while this was being written

This assessment was produced against the repository as it stood earlier on
2026-08-27, and two of its load-bearing citations are now stale. The assessment
body is left exactly as written, because it was true of the state it read; this
addendum states what changed and what did not. Its conclusion — **do not run the
GPU experiment** — is unchanged, and now rests on fewer blockers rather than
more, which is worth saying plainly.

### Stale: `sfir4-execution-closure.json` verdict `REFUSE`

The receipt this document cites at lines 139, 243, 319 and 343 recorded a real
state: three `akc_cir` modules the SFIR4 closure reaches were committed at HEAD
and *diverged* from it, carrying 982 uncommitted lines. The manifest digest is
taken over the working tree, so a fresh clone would have reconstructed a
different instrument.

That work has since landed as its own commit and the gate now reads:

    commit 4823d5d  Protected Core, 20 modules + 20 tests
    commit ad99d18  the rest of the research tree, 1445 files

    closure_files 86 · committed_at_head 86 · uncommitted 0
    byte_identical_to_head 86 · divergent_from_head 0 · unresolved_imports 0
    verdict PASS

The cited receipt is not edited. It is a correct record of a state that existed,
and a later receipt supersedes it.

### Stale: "the research tree was never under version control"

True when written, and it is the root cause INC-V2-089 named. It is no longer
true: 1445 files were committed byte-for-byte in `ad99d18`, verified against
their working-tree bytes before staging, with the tree's own `.gitattributes`
(`* -text -eol`) keeping the committed blob identical to the file the digests
are taken over.

**This recovers nothing.** The 59 drifted bindings across 29 files and 20
receipts belong to the V2R4 and SFIR1–3 chains; those bytes were never committed
and no commit returns them. What changed is prospective only: from `ad99d18`
forward, the failure mode that produced INC-V2-089 cannot recur. The historical
irreproducibility stands as a published limitation and must never be recorded as
repaired.

### Not stale, and still the reason not to run

Blocker (2) is untouched: **no fresh held-out SOURCE_FACT_IR PASS exists.** SFI3
is `ESTABLISHED_NEGATIVE`, SFIR1–3 all terminated before payload, and SFIR4 has
not executed. Blockers (3), (4), (5) and the two minor ones are likewise
unchanged — the V2 freeze remains self-declared without an attestation receipt,
no qualifying cohort exists, and the only cost arithmetic on file
(25.62 GPU-h / $64.06) still exceeds both the 6.0 h / $40 and 5.75 h / $38 caps.

### Chain separation

INC-V2-089's disposition — "STOP THE LINE; no re-pin; no new freeze; no
acquisition; no GPU" — is authored about the chain that failed. On 2026-08-27
the founder ruled that the historical integrity FAIL is preserved as a
limitation of the **historical** chain and is not a global blocker on a **new,
independently reproducible** prospective chain. SFIR4 proceeds under that
ruling, from an isolated checkout at a pinned revision, with source
recoverability, Protected Core conformance and isolated execution all gated
fail-closed before any freeze.

That ruling does not reach this document's conclusion. The GPU experiment stays
unrun because blocker (2) has nothing to do with version control: there is still
no held-out PASS for it to be conditioned on, and manufacturing one is not
available.
