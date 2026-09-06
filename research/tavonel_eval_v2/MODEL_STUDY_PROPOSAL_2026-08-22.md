# First model study — design submitted for approval

**Status: AWAITING APPROVAL. No GPU has run. No paid inference has run.
Cumulative spend remains $0.**

Submitted under the founder ruling of 2026-08-22: P4e-Core passing every gate
makes a model study *eligible to be proposed*, and the proposal is approved
before any GPU starts. This document is the proposal. Nothing in it has been
executed.

---

## 0. The recommendation, first

**This design should not be run as written, and the reason is in section 6.**

Every retrieval gate passed. The blocker is source-coverage eligibility.

Measured once on the frozen P4e cohort by the sealed `SOURCE_LOCALITY_V2`
instrument: **77 of 720 questions are `QUESTION_LOCAL_COVERAGE_COMPLETE`, and
only 5 of those are Q1** — the question type this study's endpoint is defined
on. All 5 come from one family. Exact power at n = 5 is **0.0**.

Unlike the earlier provisional figure, this one is **not** an artefact of the
instrument. Locality v2 locates every parser event in the cohort
(`LOCATION_UNVERIFIABLE = 0`) and passes all eight development controls in both
directions. 586 of the refusals are genuine unmodeled source facts inside the
question's dependency closure.

Section 6 gives the per-family structure, which is the part that decides what to
do next: markdown already yields 0.83, the three markup families yield exactly
zero, and **expanding the cohort in the present mix multiplies a zero**. Section
9 gives the sequence.

The design below is complete and ready, so that the decision is about timing and
not about waiting for a plan.

---

## 1. Question

Does compiled current-state restriction change what a model answers, holding the
model, the decoding and the retrieval-context budget fixed?

Every earlier protocol measured retrieval. **No model has been executed in this
programme.** This would be the first.

## 2. Arms — four, one variable

Identical model, identical decoding, identical retrieval-context budget. The
arms differ only in *which revisions of the retrieved evidence reach the
context*.

| arm | context contains |
|---|---|
| **TAVONEL compiled-current** | only atoms the compiled state marks current |
| **same-source full/current oracle** | the current revision, assembled directly from source without the compiler — the ceiling |
| **append-only stale-capable** | both revisions, ordered by score, no currency restriction — the realistic baseline |
| **superseded-control** | only the superseded revision — the floor, and the arm that proves the endpoint can move |

The superseded-control is not decoration. If it does not score materially worse
than the compiled-current arm, the endpoint is insensitive to currency and the
study answers nothing regardless of the other three.

## 3. Model and decoding

| parameter | value |
|---|---|
| model | one open-weight instruct model, exact revision pinned by digest in the receipt |
| precision | as published for that revision; no quantisation |
| decoding | greedy, `temperature = 0`, `top_p = 1.0` |
| max new tokens | 256 |
| seed | fixed and recorded; greedy decoding makes it a formality, and it is recorded anyway |
| prompt | one frozen template, identical across arms, carrying no arm label |

The exact model is left unnamed here on purpose: it is a parameter of the
approval, not a decision to be smuggled in through a design document. Whatever
is chosen is pinned by digest, and the same digest serves all four arms — an
arm comparison across two model revisions measures the revisions.

## 4. Retrieval-context budget

Identical across arms: top-10 envelopes by the frozen P4e index, fine atoms
recovered from them, truncated to **4,096 tokens** of evidence measured by the
model's own tokeniser. When truncation binds, atoms are dropped from the lowest
ranked upward, and the count dropped is recorded per question per arm.

The stale-capable arm sees both revisions inside the same budget, which is the
honest form of the comparison: currency restriction buys context space, and
pretending otherwise would flatter it.

## 5. Primary endpoint and statistical test

**Primary endpoint:** on Q1 questions — those whose target atom moved
semantically between revisions — the share of answers whose extracted value
matches the **current** revision's value and not the superseded one, judged by
exact match against the pre-extracted oracle value for both revisions.

Answers matching neither are `NO_MATCH` and count against every arm equally.
A question whose two revision values are not distinguishable by exact match is
excluded at cohort-freeze time, before any model runs.

**Test:** McNemar's exact test on the paired binary outcome, compiled-current
against append-only stale-capable, the two arms the product claim is about.
Paired because every question is asked of every arm. Significance at
`alpha = 0.05`, two-sided. The other two arms are reported as ceiling and floor
and are **not** subjected to additional tests — a family of tests chosen after
seeing which one moved is not a test.

**Pre-registered power parameters**, declared as protocol values rather than
chosen to produce a convenient answer:

| parameter | value |
|---|---|
| alpha | 0.05, two-sided |
| effect | 0.15, as a difference in marginal proportions |
| assumed discordant-pair rate | 0.30 |
| target power | ≥ 0.95 |
| **hard minimum eligible Q1** | **190** |

Computed by `tools/mcnemar_power.py` — **exact**, summing over the binomial
distribution of the discordant count, not a normal approximation. The
approximation is optimistic at exactly the sample sizes under argument, and
McNemar conditions on a discordant count that is itself random.

| n | 50 | 100 | 150 | **190** | 200 | 250 | 300 |
|---|---|---|---|---|---|---|---|
| power | 0.407 | 0.747 | 0.916 | **0.967** | 0.974 | 0.993 | 0.998 |

Target power is first reached at **n = 173**. The floor of 190 is therefore a
**conservative preregistered floor**, and it is not lowered after seeing any
eligibility count. Below it the study is underpowered and its null is
uninformative.

## 6. Source-coverage eligibility — the binding constraint

Per the founder ruling, a question is a confirmatory candidate only when every
relevant source fact in its target and evidence scope is `MODELED` or
`IGNORED_BY_DECLARED_POLICY` with no relevant `UNMODELED_SOURCE_FACT`.

| | count |
|---|---|
| P4e scored questions | 720 |
| Q1 questions | 175 |
| `QUESTION_LOCAL_COVERAGE_COMPLETE` (locality v2) | **77** |
| **eligible and Q1** | **5** |
| eligible Q1 by family | `git_docs: 5`, everything else **0** |
| required for the powered endpoint | **190** |
| exact power at 5 | **0.0** |

The shortfall is **thirty-eightfold**, and its cause is identified rather than
assumed. These are locality v2 numbers, measured once on the frozen cohort by a
sealed instrument with all eight development controls passing and
`LOCATION_UNVERIFIABLE = 0`. Position is no longer a limitation:

| family | Q1 | eligible Q1 | rate |
|---|---|---|---|
| git_docs | 6 | 5 | **0.83** |
| encyclopedia_wikipedia | 93 | 0 | 0 |
| regulation_ecfr | 59 | 0 | 0 |
| sec_edgar | 17 | 0 | 0 |

Witness failures: **586** `UNMODELED_SOURCE_FACT_IN_CLOSURE`, 98
`NO_DIRECT_SPAN_FOR_TARGET_ATOM`, **0** `LOCATION_UNVERIFIABLE`.

The binding constraint is now **front-end source coverage on HTML and XML**, not
cohort size and no longer position. Within markdown, eligibility is already 0.83;
across the three markup families it is exactly zero, so **expanding the cohort in
the present mix multiplies a zero**. A four-arm study on 5 single-family
questions would be a demonstration, not a measurement, and this proposal does not
ask for one.

P0d's standing result is unchanged and is not worked around: **26 of 26 document
revisions are `SOURCE_COVERAGE_INCOMPLETE`.** No revision in this cohort is
called globally CURRENT, and no result from this study — if run — could be
called source-faithful end-to-end evidence. The two endpoints stay separate:

- **controlled currency** — what this study measures, on locally
  coverage-complete targets;
- **source-faithful end-to-end** — `NOT_ESTABLISHED`, and not implied by any
  controlled-currency figure.

## 7. Frozen cohort

Frozen before any model runs, and the freeze receipt written before the first
GPU second:

- source: the P4e cohort, `p4e-cohort-manifest--20260822T075642Z-5039a951e220.json`
- filter: `QUESTION_LOCAL_COVERAGE_COMPLETE` and `Q1_REVISED_VALUE` and both
  revision values distinguishable by exact match
- split: **confirmatory, opened once.** Development results do not transfer, and
  the untouched confirmatory split is not reused for a second question
- no question is added, dropped or re-labelled after the first model call

## 8. GPU hours, cost ceiling and stop rule

Sized for the powered cohort of ~190 Q1 questions, not for the 20 available now.

| item | estimate |
|---|---|
| questions × arms | 190 × 4 = 760 generations |
| tokens per generation | ~4,400 in, ≤256 out |
| single GPU, one model load | ~1.5 hours including load and warm-up |
| repeat for determinism check | ×2 |
| **total GPU hours** | **≤ 4** |
| **cost ceiling** | **$25**, hard |

**Stop rules, any one of which halts the run:**

1. spend reaches the ceiling — stop, report what completed, claim nothing from a
   partial arm;
2. the two determinism repeats disagree on any answer — stop; greedy decoding
   that is not reproducible invalidates the comparison;
3. the superseded-control arm does not score materially below compiled-current —
   stop and report the endpoint as insensitive, because the remaining
   comparisons cannot then mean what they appear to;
4. any arm's truncation rate exceeds 0.25 — stop; the budget is binding harder
   than the variable under test;
5. eligible Q1 count at freeze is below 190 — **do not start.**

Rule 5 is the one that binds today.

## 9. Recommended sequence

1. ~~Extend positional locality to HTML and XML.~~ **Done** — `SOURCE_LOCALITY_V2`,
   sealed, 8/8 controls, `LOCATION_UNVERIFIABLE = 0`.
2. ~~Re-derive eligibility on the frozen P4e cohort.~~ **Done, once** — eligible
   Q1 = 5. The instrument was not adjusted after that number was seen.
3. Execute `P4f_cohort_expansion` (frozen, `sha256:117e5586…`): a 400-document
   expansion across all four families **paired with** a declared markup coverage
   workstream, because expansion alone multiplies a zero. Markdown-only
   narrowing is not adopted. CPU-only, $0.
4. Re-derive eligibility once on the expanded cohort with the sealed instrument.
5. If eligible Q1 clears 190 and appears in more than one family, submit this
   proposal again with the real numbers, for approval.
6. If it does not, report that. Do not request GPU, do not re-fit the
   instrument, do not narrow, do not lower the floor.

## 10. What this proposal does not ask for

- It does not ask to start GPU work now.
- It does not ask to relax the source-coverage eligibility rule.
- It does not ask to combine the controlled-currency and source-faithful
  endpoints, or the semantic and citation figures.
- It does not treat P4e's development results as confirmatory.
- It does not propose reclassifying HTML constructs as non-semantic in order to
  raise eligibility. Each such change must be justified on what the construct
  means and declared before the measurement it affects.

**Confirmatory hardening already in place:** the query builder for any
confirmatory run executes in a separate interpreter under `python -I -S`,
receiving only a serialised `IntentView` on stdin. Verified — the child imports
no repository module, `site` is not loaded, and both parent and child refuse a
forbidden field independently. This does not revise P4e, whose in-process result
stands.

**IP gate remains CLOSED. `docs/ip/` is untouched. Spend $0.**
