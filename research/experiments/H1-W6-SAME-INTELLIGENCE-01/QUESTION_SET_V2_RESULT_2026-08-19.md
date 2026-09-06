# W6 v2 question set — primary endpoint NOT RUN, insufficient real cases

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Protocol: `PROTOCOL_V2_2026-08-19.md`, frozen before the set was built.
Receipt: `receipts/question-set-v2-2026-08-19.json`. No LLM. GPU cost $0.00.

---

## 1. What was built and what came out

Questions are rendered from the article title and an infobox attribute name
only — the value and the sentence carrying it never enter the query. That is the
fix for v1, where queries were built from the target passage's own remaining
sentences and the median query↔oracle token overlap was 1.0.

| class | required | produced |
|---|---|---|
| simple retrieval (control) | 40 | **73** |
| **revision-sensitive (primary endpoint)** | **60** | **0** |
| conflicting evidence | 30 | 0 |
| multi-document | 30 | 0 |
| provenance-sensitive | 40 | 0 (blocked by the above) |

9 of 23 documents have parsable infoboxes. Across every one of them, **not a
single infobox attribute changed between the before and after revisions.**

## 2. Why, and why it is not fixable by parsing harder

The Family B corpora were acquired as **consecutive revision pairs** — edits
minutes to hours apart, selected to exercise incremental recompilation, where a
small diff is the point. Structured facts almost never move in that window.
Prose moves: W5 found 11 units whose text changed across the same 23 pairs. But
11 is far below the 60 the protocol fixed, and using prose changes would
reintroduce the v1 failure unless the intent still comes from a structured
source — which, for prose, it does not.

Loosening the infobox parser would not help. The attributes are unchanged in the
source; there is no stricter or looser reading of "identical" that produces a
revision-sensitive question.

## 3. Verdict, by the rule frozen beforehand

Protocol §1: *"A class that cannot reach its minimum from real data is reported
as NOT RUN — insufficient real cases, never padded and never simulated."*

**Primary endpoint: NOT RUN.** The three arms are not executed. No comparison of
RAW / BASIC RAG / TAVONEL exists, and none is claimed.

The alternatives were considered rather than skipped:

- **Lower the minimum to 11.** Rejected — that is changing a threshold after
  seeing the count, the exact move these protocols exist to prevent.
- **Generate revision-sensitive questions from prose diffs.** Rejected — the
  intent would come from the changed sentence, reproducing v1's leakage.
- **Synthesise revision pairs.** Rejected — a manufactured revision proves the
  system handles manufactured revisions.

## 4. What this actually establishes

**The frozen corpora cannot support W6's headline experiment.** That is a real
and reportable finding about the evidence base, not a failure of the design: a
corpus built to exercise *small* diffs is by construction the wrong corpus for
questions about *large* factual change over time.

What W6 needs is a corpus of revision pairs separated by **months to years**, on
documents whose structured facts demonstrably move — pre-registered, acquired
once, and frozen before any question is scored. That acquisition is a
public-data operation requiring no approval from anyone, and it is the next step;
it is named here rather than performed silently mid-analysis, because acquiring
data after seeing which data would have helped is exactly the pattern that
invalidates a holdout.

The 73 simple-retrieval questions are retained as the control set. They remain
non-discriminating by design and are not evidence for or against any arm.

## 5. Status carried forward

- W6 primary endpoint: **NOT RUN — insufficient real cases**
- W6 control class: built, 73 questions, valid as a control only
- v1 question set: **INVALID / SUPERSEDED**, retained in provenance
- No arm has been run; no TAVONEL advantage is claimed at any point in W6
