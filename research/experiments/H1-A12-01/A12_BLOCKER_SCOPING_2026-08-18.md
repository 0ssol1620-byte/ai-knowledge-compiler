# A12 — what is actually blocked, and what is not

A12 has been carried as "blocked behind the 4-way licence clearance for
`deepseek_ocr_2` / `paddleocr_vl_1_6`". This is a re-examination of that
dependency, prompted by the rule that a blocker should be declared only after
resolution paths have actually been tried.

**Conclusion: the blocker is real and correctly placed, but it is not a licence
question in the shape it was being carried.** The first version of this document
argued that MinerU could substitute for the blocked models and that A12 could
run immediately; §3 records why that is wrong, because the frozen cohort was
*selected against those two specific models*. What survives is a sharper
statement of what is blocked and a genuine, cheaper alternative that does not
depend on a full licence review. Nothing here is a licence decision — those
remain the founder's.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

---

## 1. The dependency as it was carried

`preregistration-v2.json` lists, among the cohort selection constraints:

> at least two candidate model families are available

and A12 #6 was opened to qualify `deepseek-ocr-2` and `paddleocr-vl-1.6` as
runtimes to supply that second family. #6 needs licence clearance across four
separate instruments — code, model weights, training dataset and hosted-API
terms — which per `CLAUDE.md` clear independently and none of which is settled
by any of the others. That clearance is a founder decision, so A12 stopped.

## 2. What the registry actually says

From `docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md`:

| model | code | weights | traffic | status |
|---|---|---|---|---|
| `deepseek_ocr_2` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `paddleocr_vl_1_6` | review_required | review_required | 0 | candidate_unverified |
| `mineru` | review_required | review_required | 0 | optional_provider_unverified |

The load-bearing observation is the third row. **MinerU carries the same
unresolved licence status as the two models A12 is waiting on** — and MinerU has
already been run, at length, on public benchmark corpora. The frozen campaign
`folynta-mineru344-quality-candidate-merged-2026-08-09` is the second-parser arm
of A9, and it is what the cross-parser agreement signal is measured against.

The repository is explicit that this is coherent rather than an oversight:

> The benchmark evidence is a *research* result on public corpora, not a
> statement that MinerU is cleared for customer production. Nothing in the repo
> routes to it.

So the distinction the repository already draws is **research measurement on
public corpora** versus **production routing of customer data**. All three models
sit on the same side of it. Production traffic is 0 for all sixteen registry
entries, and the validator is fail-closed: a candidate with a null upstream
revision cannot be promoted, because promotion requires a pin that nobody has
attested.

## 3. Why substituting MinerU does not rescue A12 as preregistered

The obvious move from §2 is: A12 needs *two independent families*, OvisOCR2 and
MinerU are two independent families already run on public corpora, so run it.
**That does not work, and the reason is in the frozen cohort.**

`cohorts/semantic-divergence-pilot-v1.json` records, per case:

    "candidate_models": ["deepseek-ocr-2", "paddleocr-vl-1.6"]

on **all 48 cases, with no variation**, and its selection block records
`requires_at_least_two_candidate_models: true`. The cases were not merely
*compatible* with those two models — they were **selected because those two
models were available recovery candidates for them**. The constraint is an
eligibility filter that has already been applied, not a runtime parameter still
open for binding.

Swapping in a different second family therefore does not satisfy the frozen
cohort; it invalidates the selection that produced it. Doing so would require
re-deriving eligibility against the new family, re-selecting 48 cases across the
six strata, and issuing a new preregistration. That is a different experiment
with a different cohort, not A12 executed as written.

Two further corrections to the assumption, recorded because they were wrong in
the first draft of this document:

- **A12's cohort is not an OmniDocBench cohort.** It spans three benchmarks —
  21 `olmocr-bench`, 19 `parsebench`, 8 `omnidocbench`. The claim that MinerU
  already holds frozen predictions for "the pages A12 is drawn from" conflated
  A9's corpus with A12's.
- The precedent in §2 is real and still holds. It simply does not reach this
  cohort, because what blocks the cohort is its own selection criterion rather
  than a licence.

## 4. What remains genuinely blocked, stated precisely

A12 as preregistered is blocked on A12 #6, and §3 is why: the cohort binds those
two models. Three further things do **not** follow from §2, and none of them is
an agent's call:

1. **Production clearance for any of the three models.** Unchanged, unaffected,
   and required before a single byte of customer data is routed. "Unlicensed
   component in production" is a stop-the-line condition.
2. **Any public claim derived from an A12 result.** Whether evidence supports a
   claim, and whether a claim is made, is the founder's decision regardless of
   how clean the measurement is.
3. **Whether the research-on-public-corpora precedent extends to A12.** This is
   the actual open question, and it is a *scoping* question rather than a
   four-instrument licence review. It is much smaller than A12 #6 as written.

## 5. The question the founder is being asked

The four-instrument clearance in A12 #6 is one path and stays as carried. §2
opens a second, cheaper one, and the choice between them is the decision:

> A9 already runs MinerU 3.4.4 on public benchmark pages as a research
> measurement, under the registry's `review_required / review_required` status
> and with zero production traffic — the same status class as
> `deepseek-ocr-2` and `paddleocr-vl-1.6`.
>
> **Does that precedent cover downloading and running `deepseek-ocr-2`
> (code Apache-2.0, weights `review_required`) on public benchmark corpora for
> A12's research measurement, ahead of the full four-instrument clearance?**
>
> - If **yes** — A12 #6 shrinks from a four-instrument licence review to a
>   runtime qualification, the frozen cohort stays valid because
>   `deepseek-ocr-2` is one of the two models it was selected against, and A12
>   runs at its preregistered $3 nominal cap. Production clearance remains
>   entirely untouched and still required before any customer data moves.
> - If **no** — A12 stays blocked exactly as carried, and the four-instrument
>   clearance is the path. Nothing is lost by having asked.
>
> This is *not* a request to clear either model for production, and not a
> request to route anything. It asks only whether the existing
> research-on-public-corpora precedent extends one model further.

**What must not be done instead:** substituting an already-run family to dodge
the question. §3 shows that silently re-binding the second family would void the
cohort's selection while leaving the preregistration's text unchanged — the
result would look like A12 and would not be A12.

## 6. What was done rather than assumed

The prior status asserted a blocker. This checked it: the registry rows were
read, the precedent was located in the repository's own audit document, and the
residual founder decision was reduced to a single yes/no with both branches
costed. No licence was interpreted, and no model was downloaded.

The check also falsified this document's own first conclusion. The MinerU
substitution looked sound from the preregistration's prose and collapsed on
contact with the frozen cohort manifest, which names the two models on every one
of its 48 cases. That correction is kept in §3 rather than edited away, because
the failure mode it demonstrates — reading a constraint as an open parameter
when selection has already consumed it — is the one most likely to recur.

A12 remains `PREREGISTERED_PROTOCOL_NOT_RUN` until the question in §5 is
answered.
