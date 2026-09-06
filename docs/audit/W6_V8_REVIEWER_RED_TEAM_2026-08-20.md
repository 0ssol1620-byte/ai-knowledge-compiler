# W6 v8 — reviewer red team

Ten questions a hostile reviewer asks first about a benchmark that stopped before
its arms. Each answer is from receipts and pinned source, not reconstruction.

Disposition under review: `CONFIRMATORY_PRE_ARM_GATE_FAILURE_ENDPOINT_NOT_RUN`.

---

## 1. Why was the 10% tie ceiling chosen?

**A. Provenance.** `exact_tie_rate.ceiling = 0.1` is pinned in
`v8-config-freeze.json` under `baseline_validity_gate.bounds`, frozen at
**2026-08-20T02:50:43.840186Z**. The gate that reads it,
`entity_conditioned_gate_v8.py`, is pinned in the same freeze at
`sha256:250bb19e0aa3ecfe2d71b48e373df2c4e9a7fe245914cbb5ca95c750c5f76d2e`; the
bytes on disk today are identical.

**B. Empirical context.** The gate's own rationale records the v7 measurement:
`"v7 measured 0.1038; a tie is resolved by index order, so ties are ranking that
did not happen. One-sided: fewer ties is never a defect."` The v8 development
question set then measured **7.34%** (177 evaluated,
`v8-entity-conditioned-gate-on-v8-questions-dev-2026-08-19.json`).

**C. Epistemic status.** The protocol contains no derivation of exactly 0.10 and
we do not invent one:

> **10% was a predeclared operational validity threshold, not a theoretically
> derived universal constant.**

What is defensible is the direction (one-sided — fewer ties is never a defect),
the timing (fixed in a hashed freeze before any holdout title existed), and the
discipline (not relaxed after measurement).

**D. Confirmatory discipline.** The holdout measured **19/166 = 11.45%**. The
threshold was not relaxed, and the arms did not run.

---

## 2. Was it frozen before the holdout?

Yes, and the interval is 28 minutes, not a claim of intent:

| artifact | timestamp (UTC) |
|---|---|
| `v8-config-freeze.json` — ceiling pinned | **02:50:43.840186Z** |
| `holdout-manifest-v8.json` — holdout titles first selected | 03:18:39.870628Z |
| transport seal | 03:19:19.787878Z |
| acquisition receipt | 08:19:19.531207Z |
| `question-set-v8-holdout.json` | 08:51:48.355184Z |
| baseline gate run | 08:52:51.080879Z |

The ceiling predates the existence of the holdout title list, the corpus and the
question set. `freeze_config_v8.py` re-run reports **16 sources, drift 0, FREEZE
INTACT**.

---

## 3. Did v8 development actually pass it?

Yes. `v8-entity-conditioned-gate-on-v8-questions-dev-2026-08-19.json`:
`exact_tie_rate = 0.0734`, 177 questions evaluated, criterion `passes: true`,
overall gate `PASS`.

An earlier development run over the *v7* question set
(`v8-entity-conditioned-gate-dev-2026-08-19.json`) measured `0.0906`, also below
the ceiling; that run's overall state was `FAIL` on a different criterion. Both
are reported; neither is 0.1038.

---

## 4. Why does v7's 10.38% not invalidate the threshold choice?

Because the ceiling was set **stricter than** the observation, not equal to it.
Four statements are false and appear nowhere in our documents:

- ~~v7 passed the 10% ceiling~~ — 10.38% > 10%.
- ~~the ceiling was set to the v7 value~~ — it was set below it.
- ~~10% was empirically validated by v7~~ — v7 would have failed it.
- ~~v7 showed the threshold satisfied~~ — v7 showed the opposite.

A threshold fitted *to* a prior observation would be the objectionable move. This
one was fixed at a rounder, stricter value than the observation that motivated
it, and the machinery that had to clear it did so at 7.34% before the holdout was
opened.

---

## 5. Why were the arms not run after only a 1.45-percentage-point excess?

Because the criterion is not a percentage comparison; it is a comparison over
counts, and the excess is three questions.

| ties | rate | verdict |
|---|---|---|
| 16 | 9.64% | largest admissible count |
| 17 | 10.24% | FAIL |
| 18 | 10.84% | FAIL |
| **19** | **11.45%** | **observed — FAIL** |

With n = 166 there is no tie count between 9.64% and 10.24%; the ceiling
discretises to "at most 16 ties". The holdout returned 19. **19 > 16.**

The deeper answer is that the stop rule was predeclared. A gate that is honoured
only when the excess feels large is not a gate — it is a preference expressed
after the fact. Running the arms "because it is close" would mean the threshold
never constrained anything.

---

## 6. Did the authors inspect outcomes before refusing?

No, and this is checkable rather than asserted:

- `v8-endpoint-seal.json` records `arms_ran: false`; `v8-pre-arm-gate-verdict.json`
  records `arms_run: false`.
- Measured **inference cost $0.00**. The model was never sent a benchmark
  question — the only generation it ever performed was the content-free
  attestation proof (`"Reply with exactly one word: attested."`).
- GPU utilization on the attested pod was **0%** throughout the gate runs, and
  the pod was deleted immediately afterwards.
- The gates are deterministic and model-free: they compute BM25 retrieval
  statistics over the corpus. No arm output exists anywhere to have been
  inspected.

There is no artifact containing an arm result, because none was ever produced.

---

## 7. Was any threshold changed after the holdout?

No. `freeze_config_v8.py` re-run after the gate: **16 sources checked, drift 0,
FREEZE INTACT**. The baseline gate's pinned digest matches its bytes on disk. The
freeze refuses to overwrite; the endpoint seal likewise refuses (re-invoking it
with a different outcome class returns `SEAL INTACT`).

The forbidden actions are enumerated in `v8-pre-arm-gate-verdict.json`: raising or
removing the ceiling, regenerating the question set with different admission or
tie-breaking, deleting questions, changing the retriever/top-k/BM25/RM3, running
the arms anyway, or building an immediate replacement benchmark. None was taken.

---

## 8. Were the 19 ties deterministic index-order ties?

Yes, and the mechanism is one line of pinned source:

```python
order = sorted(range(len(pool)), key=lambda i: (-scores[i], i))
...
"tied_at_top": len(order) > 1 and scores[order[0]] == scores[order[1]],
```

A tie is exact float equality between the rank-1 and rank-2 BM25 scores, and the
sort key breaks it by the candidate's index in the pool. So a tied question is
resolved by list position — the retriever expressed no preference. That is why
the criterion is one-sided: a tie is a ranking that did not happen, and fewer of
them is never a defect.

---

## 9. Does the 64.46% wrong-revision dominance imply difficulty rather than invalidity?

They are different claims and we report both without merging them.

*Difficulty.* Under the frozen baseline retrieval representation, the strongest
superseded-revision unit outscored the oracle current-revision unit for **64.46%**
of evaluated primary questions (median gap **-0.0537**, p10 **-1.041**). We label
this a **baseline retrieval difficulty observation**. It is not evidence for our
system; no arm ran, so nothing here compares representations.

*Validity.* The gate's `stale_revision_retrieval_rate` (0.488) passed its
two-sided bounds [0.02, 0.90] — the cohort is hard, and being hard is not why the
gate refused. The gate refused on tie rate: a distinct property, about how often
the retriever declined to rank at all.

So the honest reading is *both*: this cohort is genuinely difficult for the
baseline, **and** it independently failed a predeclared validity criterion. The
difficulty does not excuse the tie rate, and the tie rate does not explain away
the difficulty. Neither supports a conclusion about our system.

---

## 10. What exactly remains supported after W6 is NOT_RUN?

**Every patent claim, unchanged — because none of them ever depended on W6.**

A mechanical scan of all 23 files under `docs/ip/` finds 71 mentions of W6, and
**all of them are inside the claim-evidence matrix's own W6 entry** (its evidence
paths and limitations). `PATENT_CLAIM_SET_v1`, `PATENT_SPECIFICATION_v1`,
`ELEMENT_SUPPORT_BINDINGS.yaml`, `ASSERTION_REGISTRY.yaml` and
`CLAIM_AMENDMENTS.yaml` contain **zero** W6 references. The matrix has recorded
`patent: none — no claim depends on this endpoint` since before this run.

What W6 was to have supplied, and does not: **same-intelligence comparative
effectiveness**. That is now `NOT_MEASURED`, and no claim, figure, table or
sentence may rest on it.

What remains, factored by its own evidence rather than by W6: the selective and
full equivalence results, the identity semantics and path-dependence findings,
the gate-ordering result, the promotion audit, the governance ablation and the
component exactness evidence. The element support matrix reports **24 elements, 1
unsupported, state FINDINGS** — unchanged by this run, because nothing in it was
bound to W6.

A mechanical sweep of the whole submission surface (926 files) for W6-derived
comparative claims — "beats RAG", "outperforms", "same-intelligence advantage",
"comparative improvement", "validated superiority", "confirmed effectiveness",
"TAVONEL lost", "no advantage was found" — returns **zero substantive hits**. The
only matches are this programme's own prohibition lists and one pre-existing
sentence stating that "TAVONEL beats RAG everywhere" is explicitly *not* a claim
the design is built to make.
