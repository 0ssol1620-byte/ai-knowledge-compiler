# W6 baseline validation — retriever valid, question set invalid

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Protocol: `BASELINE_ACCEPTANCE_2026-08-19.md`, frozen before this ran.
Receipt: `receipts/baseline-validation-2026-08-19.json`. No LLM. GPU cost $0.00.

---

## 1. Measured

BM25 over 692 units from the before-revisions of 23 documents; 655 queries.

| metric | value | criterion | |
|---|---|---|---|
| candidate pool | 692 | ≥ 100 | PASS |
| exact-tie rate | 0.000 | ≤ 0.05 | PASS |
| distinct top-1 documents | 21 | ≥ 20 | PASS |
| Recall@1 | **0.9969** | ≥ 0.30 | PASS |
| Recall@5 | 1.000 | ≥ 0.60 | PASS |
| miss rate @10 | 0.000 | ≤ 0.40 | PASS |
| verbatim leaked queries | 0 | = 0 | PASS |
| median score gap | 37.51 | > 0 | PASS |
| same-document top-1 share | **1.000** | reported | — |
| median query↔oracle token overlap | **1.000** | *not in the frozen set* | — |

**All eight frozen criteria pass. The question set is nonetheless invalid, and
the three arms are not run on it.**

## 2. The opposite failure from W5, and it is still a failure

W5's baseline was degenerate because it could not discriminate. This one is
degenerate because it cannot fail: Recall@1 sits at the ceiling, every top-1 hit
is in the oracle's own document, and the median query token overlap with its
oracle is **1.0** — every query word appears in the passage it is meant to find.

The frozen protocol anticipated the shape of this and said what it means:
*"C4/C5 are floors, not targets… one at ceiling would mean the questions are
trivial. Either way the finding is about the question set, not about TAVONEL."*
That sentence is doing its job now rather than being reinterpreted.

Two causes, both real:

1. **Query construction leaks lexically.** Dropping the answer-bearing first
   sentence and building the query from the remaining ones avoids *verbatim*
   copying while leaving a near-copy in bag-of-words terms. C7 tested substring
   containment, which this passes trivially.
2. **The corpus makes document-level retrieval trivial.** 23 unrelated Wikipedia
   articles: any topical query identifies its document uniquely. No retriever
   has to be good.

## 3. C7 was too weak, and that is recorded rather than quietly widened

A leakage criterion that only catches verbatim substrings is not a leakage
criterion. The token-overlap statistic is added as a **measurement**, not
retrofitted into the frozen acceptance set — changing a threshold after seeing a
result is the thing these protocols exist to prevent. Any future protocol
freezes lexical overlap as a criterion from the start.

## 4. What follows, and what does not

**Does not follow:** that basic RAG is strong, or that TAVONEL cannot beat it.
Nothing has been compared. A trivial question set produces a ceiling for every
arm and separates none of them.

**Does follow:** simple-retrieval questions cannot serve as the primary endpoint
on this corpus — which is what the frozen design already says, since the primary
endpoint is **revision-sensitive** questions. Those do not depend on retrieval
difficulty: both revisions are equally findable, and the question is which one an
arm returns and whether it can say *when*. That is the discrimination this corpus
can genuinely support.

**Required before the arms run:** a question set whose queries do not derive
their wording from the passage they target, and whose classes are separable —
revision-sensitive, conflicting-evidence, multi-document, provenance-sensitive.
Simple-retrieval stays in the design as a **control** that all arms are expected
to pass, not as evidence of anything.
