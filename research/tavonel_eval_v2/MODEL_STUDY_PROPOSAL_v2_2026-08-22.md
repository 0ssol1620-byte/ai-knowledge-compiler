# First model study — v2, resubmitted with real numbers

**Status: AWAITING FOUNDER APPROVAL. No GPU has run. No paid inference has run.
Cumulative spend remains $0.**

Resubmitted under the standing ruling: when `admitted >= 400`,
`eligible Q1 >= 190`, `eligible families >= 2` and every integrity gate passes,
the proposal is updated with the real figures and approval is requested. All
four conditions are now met. **Approval of the study is a separate decision from
meeting the gates, and nothing here has been executed.**

`MODEL_STUDY_PROPOSAL_2026-08-22.md` (v1) is preserved unmodified. Its
recommendation was *do not run*, on eligible Q1 = 5, and that recommendation was
correct when it was written. This document does not amend it; it supersedes it
with a different cohort.

---

## 0. What changed, and what did not

| | v1 | v2 |
|---|---|---|
| cohort | P4e, 57 documents | **P4i, 511 documents, 4 families** |
| scored questions | 720 | **5,686** |
| Q1 | 175 | **1,564** |
| **eligible Q1** | **5** | **296** |
| eligible families | 1 | **3** |
| exact power | **0.0** | **0.9977** |
| recommendation | do not run | **ready to run, on approval** |

**The instrument did not change.** The composite identity at P4i scoring time is
byte-identical to the one that produced eligible Q1 = 174 on P4g:
`sha256:0ed844f6eb83e8b342f6790a772099c8ebec4c80c525cdf721b59a54df10fe2a`.
`G_P4I_INSTRUMENT_UNCHANGED` gates it with no escape clause.

**The floor did not move.** 190 stands, and specifically was not lowered to 174
when P4g came in one gate short of it.

**The markup policy did not move.** `attr:class` and `attr:style` remain
`UNRESOLVED_SOURCE_FACT` and still block completeness. Either one reclassified to
`IGNORED` would have cleared the floor on P4g in a single line. Neither moved.
The route from 174 to 296 was 190 more documents, not a looser rule.

## 1. Question

Does compiled current-state restriction change what a model answers, holding the
model, the decoding and the retrieval-context budget fixed?

**No model has been executed in this programme.** This would be the first.

## 2. Arms — four, one variable

Identical model, identical decoding, identical retrieval-context budget. The
arms differ only in *which revisions of the retrieved evidence reach the
context*.

| arm | context contains |
|---|---|
| **TAVONEL compiled-current** | only atoms the compiled state marks current |
| **same-source full/current oracle** | the current revision assembled directly from source, without the compiler — the ceiling |
| **append-only stale-capable** | both revisions, ordered by score, no currency restriction — the realistic baseline |
| **superseded-control** | only the superseded revision — the floor, and the arm that proves the endpoint can move |

Sections 3, 4 and 5 of v1 are carried forward unchanged: model and decoding,
retrieval-context budget, primary endpoint and statistical test. Only the cohort
and the sizing below are new.

## 3. Primary endpoint and test

Endpoint: exact-match agreement with the current-revision value on Q1
(`Q1_REVISED_VALUE`) questions.

Test: **exact McNemar**, conditioning on the discordant count, comparing
compiled-current against append-only stale-capable. Preregistered parameters,
fixed before any result and unchanged since:

| parameter | value |
|---|---|
| alpha | 0.05, two-sided |
| effect | 0.15 difference in marginal proportions |
| assumed discordant-pair rate | 0.30 |
| target power | 0.95 |
| **hard minimum eligible Q1** | **190** |

| n | exact power |
|---|---|
| 173 | 0.9500 — first n reaching target |
| **190** | **0.9670** — the preregistered floor |
| 250 | 0.9925 |
| **296** | **0.9977** — this cohort |

The cohort exceeds the floor by 1.56×. That headroom was not purchased by
re-weighting toward the families that score well — see section 5.

## 4. The cohort

| | |
|---|---|
| protocol | `P4i_cohort_expansion`, frozen `sha256:b7aa130c…` |
| manifest | `p4i-cohort-manifest--20260822T140001Z-d7ae58b41561.json` |
| admitted documents | **511** across **4** families |
| acquisition target | 550 — attempted for headroom, non-gating |
| breadth gate | **≥ 400 admitted across ≥ 4 families** — PASS |
| candidates selected | 768 |
| scored questions | 5,686 |
| Q1 | 1,564 |
| **eligible Q1** | **296**, in **3** families |
| result receipt | `p4i--20260822T142215Z-d7c7ff4a8c3b.json`, verdict **PASS**, 10 of 10 gates |

Admitted mix and eligibility:

| family | admitted | Q1 | eligible Q1 | eligible per Q1 |
|---|---|---|---|---|
| `git_docs` | 165 | 274 | **202** | 0.74 |
| `regulation_ecfr` | 165 | 467 | **87** | 0.19 |
| `encyclopedia_wikipedia` | 165 | 767 | **7** | 0.01 |
| `sec_edgar` | 16 | 56 | 0 | 0.00 |

Rejections, every one reason-coded:

| code | count |
|---|---|
| `SOURCE_EXHAUSTION` | 4,490 |
| `PARSE_FLOOR` | 122 |
| `SPACING_NOT_MET` | 60 |
| `PAYLOAD_UNAVAILABLE` | 6 |
| `NO_SOURCE_CHANGE` | 4 |
| `LISTING_FAILED` | 3 |
| `RELATION_FAILURE` | 3 |
| `OTHER` (beyond family quota) | 125 |

`SOURCE_EXHAUSTION` is overwhelmingly CFR sections carrying a single dated
version — a property of the source, not of the fetcher, which is exactly what
reason codes exist to distinguish.

## 5. Two things this cohort is not

**It is not a re-weighted cohort.** Family quotas are `165 / 165 / 165 / 55`,
the declared scale-up of P4g's predeclared nominal balance rule.
`git_docs` yields 0.74 eligible per Q1 and Wikipedia 0.01; shifting the quota
toward `git_docs` would have reached 296 with far fewer documents. It was not
done, and `G_P4I_MIX_NOT_REWEIGHTED` gates it. The cost of refusing is that 165
Wikipedia documents contributed 7 eligible questions.

**It is not P4g's realized mix.** P4g admitted `98 / 93 / 114 / 16`. The quotas
are a plan scaled, not an outcome copied — the conflation is recorded in
`INC-V2-016` and corrected here.

`sec_edgar` reached 16 of a 55 quota. Amendment pairs whose primary document
yields three canonical units are scarce, and the family is reported at what it
reached rather than padded by relaxing the parse floor or dropped for
contributing nothing. **A family that yields zero is evidence about the family.**

## 6. Source-coverage eligibility

A question is a confirmatory candidate only when every relevant source fact in
its target and evidence scope is `MODELED` or `IGNORED_BY_DECLARED_POLICY` with
no relevant `UNMODELED_SOURCE_FACT` and no `UNRESOLVED_SOURCE_FACT`.

| refusal | count |
|---|---|
| `UNMODELED_SOURCE_FACT_IN_CLOSURE` | 3,704 |
| `UNRESOLVED_SOURCE_FACT_IN_CLOSURE` | 2,716 |
| `NO_DIRECT_SPAN_FOR_TARGET_ATOM` | 554 |
| `ATOM_SOURCE_REGION_NOT_LOCALISABLE` | 279 |
| `LOCATION_UNVERIFIABLE` | **0** |

`attr:class` accounts for **2,629** of the 2,716 unresolved refusals and is why
Wikipedia yields 7 from 767. Under a fail-closed reading, an element carrying a
class cannot be shown to be unaffected by an external rule. That constraint is
intact in this cohort; the study is powered *despite* it, not by relaxing it.

**P0d's standing result is unchanged and not worked around: 26 of 26 document
revisions are `SOURCE_COVERAGE_INCOMPLETE`.** No revision is called globally
CURRENT. The two endpoints stay separate:

- **controlled currency** — what this study would measure, on locally
  coverage-complete targets;
- **source-faithful end-to-end** — `NOT_ESTABLISHED`, and not implied by any
  controlled-currency figure.

Retrieval measures on this cohort, reported and not gated: envelope
retrievable@10 = **0.9863**, atom recoverable from envelope = **1.0**.

## 7. Frozen cohort for the run

Frozen before any model runs, with the freeze receipt written before the first
GPU second:

- source: the P4i cohort, `p4i-cohort-manifest--20260822T140001Z-d7ae58b41561.json`
- filter: `QUESTION_LOCAL_COVERAGE_COMPLETE` and `Q1_REVISED_VALUE` and both
  revision values distinguishable by exact match
- split: **confirmatory, opened once.** Development results do not transfer, and
  the untouched confirmatory split is not reused for a second question
- no question is added, dropped or re-labelled after the first model call

## 8. GPU hours, cost ceiling and stop rules

Sized for the actual 296, not for the 190 floor.

| item | estimate |
|---|---|
| questions × arms | 296 × 4 = **1,184 generations** |
| tokens per generation | ~4,400 in, ≤256 out |
| single GPU, one model load | ~2.4 hours including load and warm-up |
| repeat for determinism check | ×2 |
| **total GPU hours** | **≤ 6** |
| **cost ceiling** | **$40**, hard |

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
5. eligible Q1 count at freeze is below 190 — do not start.

Rule 5 no longer binds: 296.

## 9. Confirmatory hardening already in place

The query builder for any confirmatory run executes in a separate interpreter
under `python -I -S`, receiving only a serialised `IntentView` on stdin.
Verified: the child imports no repository module, `site` is not loaded, and both
parent and child refuse a forbidden field independently. This does not revise
P4e, whose in-process result stands.

## 10. What this proposal does not ask for

- It does not start GPU work. **GPU runs only after founder approval of this
  document**, under any outcome.
- It does not ask to relax the source-coverage eligibility rule, and did not
  need to.
- It does not ask to reclassify `attr:class`, `attr:style` or any other
  construct.
- It does not combine the controlled-currency and source-faithful endpoints, or
  the semantic and citation figures.
- It does not treat P4i's development results as confirmatory.
- It does not claim that 296 eligible questions make any document revision
  source-faithful end-to-end. That endpoint remains unestablished.

## 11. Decision requested

Approve, decline, or amend the design below the line:

1. **model choice** — a parameter of the approval, not decided here;
2. **GPU hours ≤ 6 and a hard $40 ceiling**;
3. **opening the confirmatory split once**, on the frozen 296-question cohort.

**IP gate remains CLOSED. `docs/ip/` is untouched. Spend to date: $0. GPU
seconds to date: 0.**
