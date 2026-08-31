# H3-B-REGULATORY-ECFR-01 — Family B robustness on US federal regulation

**Date:** 2026-08-31 KST
**Experiment:** `research/experiments/H3-B-REGULATORY-ECFR-01/`
**Seal:** `sha256:b42db9920c251a3b39a51a5964665f9e70ebd1027022f679b770c6297a3d2b3f`
**Corpus family:** eCFR Title 21 (Food and Drugs), 11 parts
**External GPU cost:** $0.00
**Audit reference:** `TAVONEL_RESEARCH_MASTER_HANDOFF_2026-08-31.md` §28-C
(Family B robustness: "at least one non-Wikipedia production-shaped revision
source")

## Verdict

**PARTIAL — safety PASS, evidence-adequacy FAIL against its own preregistered
gate.**

The runner exits 1. That is the honest outcome and the gate is not being
revised after seeing the result (protocol `forbidden`
`tuning_any_threshold_on_this_corpus_then_calling_it_confirmatory`).

## Preregistered gates

| Gate | Required | Measured | Result |
|---|---|---|---|
| all evaluated pairs equivalent | true | true (11/11) | **PASS** |
| stale left behind total | 0 | 0 | **PASS** |
| minimum changed pair count | 6 | 5 | **FAIL** |

The adequacy gate exists to stop a corpus of near-identical revisions from
producing a flattering work-avoided number. It fired exactly as designed: 6
of the 11 selected pairs contained no semantic change at all, so this cohort
carries less change evidence than the protocol demanded.

## Measurements (not pass gates)

| Metric | Value |
|---|---|
| pairs evaluated | 11 |
| mean rebuild fraction | 0.0388 |
| mean work avoided | **96.12%** |
| unresolved identity | 0 |

Change channels across all pairs:

```
locator      484     evidence_moved      484
metadata     484     metadata_changed    484
semantic       9     modified_claim        9
unchanged      6     content_unchanged     6
```

968 locator/metadata changes were correctly excluded from semantic traversal;
only 9 semantic changes drove recompilation. This is the same typed-channel
behaviour V03 measured on Wikipedia, now observed on a regulatory corpus.

**The 96.12% work-avoided figure must not be quoted as a headline.** It is
higher than V03's 85.32% largely because 6 pairs had zero semantic change and
therefore avoided ~100% by definition — which is precisely the condition the
failed adequacy gate flags. A mean over a cohort that thin is not a
generalisable rate.

## Independent external label — the reason eCFR was chosen

Unlike Wikipedia, every eCFR `content_versions` record carries a
government-assigned `substantive` boolean: did this amendment change
regulatory substance, or was the section merely reissued. That is an external
ground truth for "did the meaning change" that TAVONEL did not produce.

Agreement between the eCFR label and TAVONEL's semantic-channel detection:

| | eCFR substantive=true | eCFR substantive=false |
|---|---:|---:|
| TAVONEL semantic > 0 | **5** | 0 |
| TAVONEL semantic = 0 | 0 | **6** |

**11 / 11 agreement, 0 disagreement.** Every part the publisher marked as
substantively amended produced at least one semantic change; every part marked
non-substantive produced none, only locator and metadata changes.

Per-part detail:

| Part | eCFR substantive | TAVONEL semantic | rebuild fraction |
|---|---|---:|---:|
| 1 | true | 4 | 0.0275 |
| 11 | false | 0 | 0.0 |
| 101 | true | 2 | 0.0727 |
| 117 | false | 0 | 0.0 |
| 120 | false | 0 | 0.0 |
| 130 | true | 1 | 0.1875 |
| 131 | true | 1 | 0.1200 |
| 133 | false | 0 | 0.0 |
| 136 | false | 0 | 0.0 |
| 172 | true | 1 | 0.0190 |
| 179 | false | 0 | 0.0 |

This label was **never used to select pairs and is not a pass gate**
(protocol `forbidden`). Selection took the two most recent distinct issue
dates per part, computed before any content was fetched.

### Why this result is weaker than it looks

11/11 with zero disagreement is a small sample, and the false cases are easy:
a non-substantive reissue of 21 CFR §1.71 returns **byte-identical XML**
(`sha256:68b9aadf6dace6af…`, 3338 bytes at both 2022-11-17 and 2023-03-30 —
measured before the freeze and recorded in the protocol). Detecting "no
semantic change" when the bytes are identical is not a demanding test.

The informative half is the 5 substantive parts, where the document did change
and TAVONEL had to separate 484 locator/metadata movements from 9 real
semantic changes without over- or under-firing. That it agreed with the
publisher on all 5 is real but thin evidence.

## What this establishes

- Typed change-channel separation and selective recompilation hold on a
  second, non-Wikipedia, production-shaped revision family, under the
  **byte-identical sealed V01 evaluator** — only transport and the section
  projection are new.
- Full-rebuild equivalence: 11/11. Stale artifacts: 0. Unresolved identity: 0.
- On this cohort, TAVONEL's semantic/non-semantic decision matched an
  independent government label 11/11.

## What this does NOT establish

- It does not widen the V03 claim boundary; V03 remains the evidence for its
  own declared English-Wikipedia projection and was re-verified unchanged
  (its sealed core hashes are checked by this runner before any network call).
- It does not establish a general work-avoided rate. 96.12% is this cohort's
  number and is inflated by 6 no-change pairs.
- It does not clear §28-C. The adequacy gate failed; §28-C needs a rerun on a
  cohort selected to contain more substantive amendments, or additional
  revision families.
- Nothing here speaks to OCR, ontology, or customer-data performance.

## Next step for §28-C

Re-select within eCFR for parts with **more frequent substantive amendment
activity** (the versions endpoint exposes amendment dates before any content
fetch, so this stays selection-before-observation), targeting ≥8 changed pairs
rather than the 5 obtained here. That is a new experiment id with its own
seal, not an edit to this one — this result and its FAIL stay on the record.
