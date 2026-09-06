# W6 baseline acceptance criteria — frozen before any retrieval was run

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Written before `validate_baseline.py` was executed. Nothing below is chosen with
knowledge of a result.

---

## 1. Why this document exists

W5's arm B collapsed: all 11 comparisons were exact lexical ties, so its scores
were the tie-break and nothing else. Its numbers happened to favour TAVONEL,
which is precisely why they could not be reported as a win.

W6 is likely to be the paper's headline experiment. A degenerate baseline there
would be worse than no experiment, so the baseline must prove it discriminates
**before** any arm is scored, against thresholds fixed now.

## 2. The baseline being validated

Basic RAG, honestly built: BM25 over **every knowledge unit in every document of
every corpus**, not over the two revisions of one section. A retrieval problem
needs a real candidate pool, and W5's did not have one.

## 3. Acceptance criteria — all must hold

| # | criterion | threshold |
|---|---|---|
| C1 | candidate pool per query | **≥ 100 units** |
| C2 | exact-tie rate at rank 1 | **≤ 5%** |
| C3 | ranking varies across queries — distinct top-1 documents | **≥ 20 distinct** |
| C4 | oracle evidence Recall@1 | **≥ 0.30** |
| C5 | oracle evidence Recall@5 | **≥ 0.60** |
| C6 | retrieval miss rate (oracle absent from top-10) | **≤ 0.40** |
| C7 | query leakage: queries that are a verbatim substring of their oracle | **= 0** |
| C8 | score separation between rank 1 and rank 2, median | **> 0** |

C4/C5 are floors, not targets: a baseline far *below* them is not a baseline,
and one at ceiling would mean the questions are trivial. Either way the finding
is about the question set, not about TAVONEL.

## 4. Leakage controls, fixed now

- **Query construction never copies the oracle verbatim.** A query is built from
  the oracle's content words with the answer-bearing sentence removed, and C7
  enforces it mechanically rather than by inspection.
- **Same-document bias is reported, not prevented.** The share of top-1 hits
  landing in the oracle's own document is measured and published. Excluding
  same-document candidates would make the task artificial; hiding the share
  would make the number unreadable.
- **Revision leakage is prevented.** Only the *before* revision of each document
  enters the index. Indexing both revisions would let a retriever find the
  answer in a revision the temporal arms are supposed to distinguish.

## 5. What happens if the baseline fails

The result is recorded as **BASELINE INVALID**. The comparison is not run, no
TAVONEL win is claimed, and the failure is published with the criterion that
failed. Substituting a different baseline *after* seeing that this one lost is
forbidden; substituting one after seeing it is **degenerate** is required, and
the two are distinguished by C1–C8 being fixed here, before any run.

## 6. Statistical design, frozen now

- **Primary endpoint:** answer correctness on revision-sensitive questions.
- **Primary comparison:** TAVONEL compiled world vs basic RAG. Raw-document is a
  floor condition, not the comparator.
- **Paired design.** Every question goes to all three arms with the same frozen
  LLM, so pairing is by question; McNemar for binary outcomes.
- **Multiple comparisons:** five secondary endpoints (evidence correctness,
  temporal correctness, stale-answer rate, unsupported-claim rate, abstention),
  Holm-corrected. The primary endpoint is not corrected and is not selected
  after the fact.
- **Question classes reported separately:** simple retrieval · revision-sensitive
  · conflicting evidence · multi-document · provenance-sensitive. An aggregate
  mean across classes would hide the only interesting result — *which class of
  problem a compiled world actually helps with* — and "TAVONEL beats RAG
  everywhere" is not a claim this design is built to make.
- **Temporal conditions separated:** oracle temporal metadata vs extracted
  temporal metadata, so a resolver failure is never confused with an extraction
  failure. W5 established that distinction matters.
