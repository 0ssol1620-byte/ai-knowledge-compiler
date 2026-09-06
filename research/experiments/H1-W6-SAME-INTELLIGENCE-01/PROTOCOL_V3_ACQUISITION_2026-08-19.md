# W6 v3 public-corpus acquisition protocol — frozen before acquisition

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

This protocol exists because W6 v2 was not an experiment failure: its existing
Family-B corpus contained consecutive revisions and yielded **zero** changed
infobox attributes. The v2 receipt and NOT-RUN result remain immutable. v3 does
not lower a sample minimum, pad with synthetic changes, or select pages because
we already know their facts changed. It changes only the data-acquisition frame,
before any v3 revision content is inspected.

---

## 1. Public source and outcome-independent candidate universe

Source: **English Wikipedia via the public MediaWiki API**.

Candidate universe is read from the main-namespace members of the current
`Category:Featured articles`. The category is chosen before acquisition because
it is a broad, externally curated article set with enough pages to support a
large deterministic sample. Membership itself is frozen into a title manifest
before any historical revision content is requested.

If the API returns fewer than 1,500 main-namespace members, and only then, the
ordered preregistered fallback is `Category:Good articles`. The first source
with at least 1,500 main-namespace members is used. No other category may be
substituted in this run.

Every title is Unicode-NFC normalised and internal whitespace is collapsed. Its
fixed ordering key is:

    sha256("tavonel-w6-v3-candidate-order-2026-08-19|" + normalized_title)

The candidate manifest is sorted by that key. No semantic, revision, infobox,
change-frequency, popularity, or downstream-performance information enters the
order.

## 2. Historical snapshots

For each title, acquire the latest revision at or before each fixed cutoff:

- **before:** `2023-06-30T23:59:59Z`
- **after:**  `2026-06-30T23:59:59Z`

Both revisions must exist, be main-slot wikitext, and be separated by at least
**1,095 days**. A page failing those mechanical requirements is retained in the
acquisition receipt with an exclusion reason; it is not silently replaced by a
hand-picked page.

Raw wikitext, revision id, timestamp, MediaWiki sha1 when available, local
sha256, title and snapshot cutoff are persisted. Raw bytes are never modified
after their sha256 is recorded.

## 3. Cohorts and the only expansion rule

The hash-sorted title manifest is consumed in contiguous cohorts of **750
candidate titles**, at most **6 cohorts** (maximum 4,500 candidates).

After a *whole* cohort has been acquired, the same conservative infobox parser
used by W6 v2 may count structured `(subject, attribute)` facts present in both
snapshots. Acquisition stops at the first completed cohort for which all of the
following availability conditions hold:

1. at least **60 revision-sensitive structured facts** (value differs),
2. those facts come from at least **20 distinct articles**, and
3. at least **40 unchanged structured facts** exist for the simple-retrieval
   control.

This is a preregistered **data-availability** stopping rule, not a model-result
stopping rule. No RAW/RAG/TAVONEL arm is executed, inspected, or even prepared
between cohorts. If 6 cohorts still cannot satisfy the conditions, the primary
W6 endpoint is `NOT RUN — insufficient real cases`; no seventh cohort or custom
title list is allowed in this protocol.

## 4. Fact extraction and question generation

The v2 principle is preserved: question intent comes from a structured field,
not from answer-bearing prose. Infobox values containing unresolved template
markup, references, file/image links, or values outside the conservative length
bounds are dropped rather than cleaned into uncertain gold.

An attribute present in both frozen snapshots is:

- `revision_sensitive` iff its conservative canonical value differs;
- `simple_retrieval` iff its value is identical.

Questions use only subject/title + attribute (and the fixed before cutoff for an
as-of question). The answer value and answer-bearing prose do not enter the
query. Templates remain those frozen in v2.

To prevent one volatile article from dominating the paired analysis, at most
**3 revision-sensitive attributes per article** enter the primary set. If an
article has more, attributes are ordered by
`sha256("w6-v3-primary-attribute|" + title + "|" + attribute)` and the first
three are retained. This cap and ordering are frozen before acquisition.
All retained primary questions are used; there is no model-outcome subsampling.

## 5. Leakage and baseline validity

No model arm runs until the question set passes the leakage controls already
frozen in W6 v2:

- median query↔oracle content-token overlap <= 0.50,
- p90 overlap <= 0.75,
- zero verbatim query containment,
- zero revision-id/date-only revision leakage.

The Basic-RAG validity gate is also run **before any model arm is scored**. The
v2 thresholds remain binding for this v3 acquisition run; no threshold is
changed after seeing a retrieval result. If the baseline is invalid, this corpus
is sealed as a baseline-invalid development result and no 3-arm performance
claim is made from it.

## 6. Three arms, endpoints and statistics

Only after §§1–5 are frozen and passed:

- `RAW`: frozen document material, no retrieval;
- `BASIC RAG`: BM25 top-k over both frozen revisions;
- `TAVONEL`: the compiled world with stable identity, temporal state and
  provenance.

The **same frozen language model**, system prompt, decoding parameters, answer
budget and questions are used in all arms. Only the world representation and
context assembly differ.

Primary endpoint remains binary answer correctness on revision-sensitive
questions; primary comparison TAVONEL vs BASIC RAG, paired by question, using
McNemar (exact when required). RAW is a floor. The seven v2 secondary endpoints
remain Holm-corrected. Effect sizes and confidence intervals are reported even
when the primary test rejects the null. Abstaining on an answerable question is
wrong; appropriate abstention on genuinely indeterminate evidence is correct.

No aggregate across semantically different question classes is a headline
claim.

## 7. Freeze and provenance requirements

Before the first historical revision request, persist:

1. this protocol sha256,
2. acquisition-script sha256,
3. the category title-manifest sha256 as soon as category membership is fetched,
   *before* any historical revision content is fetched,
4. every raw revision sha256 and metadata,
5. a canonical acquisition-receipt sha256.

Superseded W6 v1/v2 artifacts are retained and hash-pinned; never edited or
deleted. `external_gpu_cost_usd` is zero for acquisition/question construction.
GPU/model cost is recorded separately only if the three-arm inference run
becomes eligible.

## 8. Prohibited shortcuts

- no synthetic revisions for the primary result;
- no search for known historical fact changes and then adding those pages;
- no title/category replacement after observing change yield;
- no lowering 60/20/40 availability requirements;
- no changing overlap/BM25 thresholds after a retrieval result;
- no model-prompt or top-k tuning after arm outputs are visible;
- no excluding questions because an arm answered them incorrectly;
- no GPU/model run before the baseline gate passes.
