# W6 — final state

`W6_V8 = CLOSED`. `OUTCOME = CONFIRMATORY_PRE_ARM_GATE_FAILURE_ENDPOINT_NOT_RUN`.

No arm was run. No V9 will be built. No exploratory arm will be run on this
holdout. **These 6,237-candidate titles are development data from this point
forward.**

---

## 1. What this result is, and what it is not

The confirmatory benchmark failed its pre-arm retrieval-validity criterion, so
**no representation-comparison endpoint was run**.

Equivalently: *W6 v8 did not produce confirmatory comparative effectiveness
evidence, because the frozen pre-arm baseline-validity gate refused the untouched
holdout.*

**The following are false and are not to appear anywhere in the paper, the
patent, the audit set or any status document.** None of them describes something
that was measured, because no arm ran and no answer was ever generated:

- TAVONEL lost
- TAVONEL tied
- BASIC RAG beat TAVONEL
- no advantage was found
- Qwen showed no benefit
- the comparative endpoint failed

The comparative endpoint did not fail. It was **not measured**.

---

## 2. Evidence hierarchy

| stage | state |
|---|---|
| v1 / v2 question sets | superseded / development |
| v7 | development, protocol-conflict run; arms `NOT_RUN` |
| v8 development | harness and calibration only — **not** a confirmatory result |
| v8 holdout acquisition | **SUCCESS** — 391 eligible / 359 excluded / 750 consumed / 0 unaccounted; corpus root frozen; development-title overlap **0** |
| v8 question set | 2,548 total — 185 revision-sensitive primary, 2,363 controls |
| structural taint gate | **PASS** |
| residual leakage gate | **PASS** |
| baseline validity gate | **FAIL** — exact ties **19/166 = 11.45%**, ceiling **10%** |
| arms | **NOT_RUN** |
| comparative endpoint | **NOT_MEASURED** |
| final disposition | `CONFIRMATORY_PRE_ARM_GATE_FAILURE_ENDPOINT_NOT_RUN` |

Corpus root:
`sha256:13bfe8600855a9d7eedf9ec32c337581eaed0edb6dbf1fcd60dde7e5191f73cd`

Model that was qualified but never asked a benchmark question:
`Qwen/Qwen3.6-27B @ 6a9e13bd6fc8f0983b9b99948120bc37f49c13e9`, vLLM 0.27.1,
262,144-token window, `temperature 0 / max_tokens 256 / enable_thinking false /
tools off`. **Inference cost of this endpoint: $0.00.**

---

## 3. The 10% tie ceiling — provenance, closed

This is the sharpest reviewer attack surface and it is answered from receipts, not
from reconstruction.

### 3.1 Four statements that are false

- ~~v7 passed the 10% ceiling~~ — **v7 measured 10.38%, which is above 10%.**
- ~~the ceiling was set to the v7 value~~ — 10.38% was the *context*; 10% is a
  different, rounder number, and a stricter one.
- ~~10% was empirically validated by v7~~ — v7 would have failed it.
- ~~v7 showed the threshold was satisfied~~ — v7 showed the opposite.

### 3.2 The chronology that is true

1. **v7 historical reference: 0.1038 = 10.38%, above 10%.** Recorded in the
   gate's own rationale as the observation that motivated having a tie criterion
   at all.
2. **10% was adopted as a round operational-quality ceiling** — deliberately
   below the v7 observation, not equal to it, and not a claim that v7 passed.
3. **v8 development question set: 0.0734 = 7.34% — PASS** (177 evaluated,
   `v8-entity-conditioned-gate-on-v8-questions-dev-2026-08-19.json`). An earlier
   development run over the v7 question set measured 0.0906 = 9.06%; the tie
   criterion passed there too, and that run failed on a different criterion.
4. **The ceiling was frozen before the holdout existed.** `v8-config-freeze.json`
   pins `exact_tie_rate.ceiling = 0.1` at **02:50:43Z**. The holdout title
   manifest was not created until **03:18:39Z**, 28 minutes later, and the
   holdout question set not until **08:51:48Z**. The gate source
   `entity_conditioned_gate_v8.py` is pinned in that freeze at
   `sha256:250bb19e…` and its bytes on disk are still identical.
5. **Untouched holdout: 19/166 = 11.45% — FAIL.**

### 3.3 Epistemic status, stated plainly

The protocol document contains no deeper derivation of exactly 0.10, and this
write-up does not invent one:

> **10% was a predeclared operational validity threshold, not a theoretically
> derived universal constant.**

What the protocol *does* support is the direction and the discipline: the
criterion is one-sided because fewer ties is never a defect, the number was fixed
in a hashed freeze before any holdout title existed, and it was not relaxed after
the holdout was measured against it.

### 3.4 The discrete boundary

The rate is a ratio of integers over 166 evaluated questions, so the ceiling has
an exact integer form:

| ties | rate | verdict |
|---|---|---|
| 16 | 9.64% | largest passing count |
| 17 | 10.24% | **FAIL** |
| 18 | 10.84% | FAIL |
| **19** | **11.45%** | **observed — FAIL** |

**The holdout exceeded the largest admissible tie count by three questions.**

The failure is not to be softened as "only 1.45 percentage points". The protocol
is deterministic and the comparison is over counts: **19 > 16 admissible ties.**
A tie is broken by index order, so each tied question is a ranking decision the
retriever did not make.

---

## 4. The one substantive finding that survives

Under the frozen baseline retrieval representation, on 166 evaluated primary
questions:

    oracle - strongest wrong-revision unit
      median         -0.0537
      p10            -1.041
      negative share  64.46%

Stated in the only form the evidence supports:

> In this holdout, the strongest superseded-revision unit outscored the oracle
> current-revision unit for 64.46% of evaluated primary questions under the
> frozen baseline retrieval representation.

**Label: `BASELINE RETRIEVAL DIFFICULTY OBSERVATION`.** It is an observation
about how hard temporal retrieval is on this corpus under this baseline. It is
**not** TAVONEL evidence, and it must never be presented as one — no arm ran, so
nothing here compares representations.

---

## 5. Defects recorded, none repaired in place

| id | classification | disposition |
|---|---|---|
| `W6-V8-GATE-01` | `POST_OUTCOME_METADATA_LABEL_DEFECT` | the gate receipt hard-codes `run_class: DEVELOPMENT_ONLY`; its recorded input digest `sha256:2f20b9a5…` **is** the holdout question set's receipt hash. Corrected semantic run class `HOLDOUT_CONFIRMATORY_PRE_ARM_GATE`. Values not recomputed, thresholds unchanged, script unchanged, verdict unchanged, raw artifact preserved. |
| `W6-V8-SEAL-01` | seal under-binds; nothing it states is false | the sealer's arm-receipt filename map was written before the gates ran; two names were wrong and it omitted them **silently**. The pinned sealer is **not** edited and the endpoint is **not** re-sealed. An append-only supplement digest-binds everything it missed. Any repair is a future-only new version. |
| `W6-V8-TIE-CHRONOLOGY-01` | `REPORTING_ARITHMETIC_CORRECTION` | an interim status statement called v7's 10.38% "development" and "just under" 10%. Both halves wrong. Corrected before reaching any document. |
| instrumentation | `POST_OBSERVATION_PROVENANCE_SCHEMA_REPAIR` | one earlier version preserved, current version preserved, **the intermediate `supersedes.file` state was lost**. "All versions preserved" and "fully write-once from creation" are forbidden phrasings. |
| `W6-V8-ACQ` attempt 1 | `CONFIRMATORY_ACQUISITION_ATTEMPT_INVALID_TRANSPORT_INVOCATION` | 149 MediaWiki 429 retries, then a deterministic `ValueError` at `acquire_w6_v3.py:376` from a repository-relative `--corpus` — the same defect already diagnosed for v6. Partial corpus quarantined unexamined, not reused. |

---

## 6. Joint evidence package

The immutable `v8-endpoint-seal.json` **plus** the append-only
`v8-endpoint-seal-completion-notes.jsonl` together are the evidence package.
Neither alone is complete: the seal bound 3 of 5 arm receipts, and the supplement
digest-binds the structural taint gate, the baseline gate, the question set, the
verdict, both acquisition attempts, the provenance incident and the runtime and
model receipts.

The seal is not overwritten or recomputed. Re-invoking it with a different
outcome class returns `SEAL INTACT` and refuses.

---

## 7. Boundary wording, final

> The sealed confirmatory cohort was accessed by the transport, a question set
> was generated from it, and three pre-arm gates were measured on it. No arm ran,
> no answer was generated, no score exists, and no threshold, cohort, retriever,
> model or decoding parameter was changed as a result of any holdout observation.

Forbidden: "the holdout was not opened", "the holdout was never read".
