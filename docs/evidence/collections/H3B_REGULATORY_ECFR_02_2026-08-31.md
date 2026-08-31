# H3-B-REGULATORY-ECFR-02 — Family B robustness across seven US regulators

**Date:** 2026-08-31 KST
**Experiment:** `research/experiments/H3-B-REGULATORY-ECFR-02/`
**Seal:** `sha256:32fb7403b5e36bd579bc122638d35b887552beafd29494f1723ccad523e645c8`
**Corpus family:** eCFR, 11 parts across 7 regulators / 6 CFR titles
**External GPU cost:** $0.00
**Audit reference:** `TAVONEL_RESEARCH_MASTER_HANDOFF_2026-08-31.md` §28-C
**Predecessor:** `H3-B-REGULATORY-ECFR-01` (safety PASS, adequacy FAIL, result
untouched)

## Verdict

**PASS against every preregistered gate.**

The runner exits 0. ECFR-01's FAIL is left on the record; this experiment
does not edit that result or lower its gate.

## Preregistered gates

| Gate | Required | Measured | Result |
|---|---|---|---|
| all evaluated pairs equivalent | true | true (11/11) | **PASS** |
| stale left behind total | 0 | 0 | **PASS** |
| minimum changed pair count | 8 | **11** | **PASS** |

The adequacy threshold was *raised* from ECFR-01's 6 to 8, not lowered, so
this is not a post-hoc weakening of a failed gate. Selection used only
amendment metadata (the eCFR versions endpoint) before any section XML was
fetched; that screening is recorded in the protocol as
`candidate_screening_measured_before_freeze`.

## Measurements (not pass gates)

| Metric | Value |
|---|---|
| pairs evaluated | 11 |
| changed pairs | 11 |
| mean rebuild fraction | 0.1134 |
| median rebuild fraction | 0.0275 |
| max rebuild fraction | 0.5000 (40 CFR 80) |
| mean work avoided | **88.66%** |
| unresolved identity | 6 (abstained, not force-matched) |

Change channels across all pairs:

```
locator      5613     evidence_moved      5613
metadata     5613     metadata_changed    5613
semantic       94     modified_claim        87
structural      7     structure_changed      7
unresolved      6     identity_unresolved    6
                      unit_added             3
                      unit_removed           4
```

11,226 locator/metadata changes were excluded from semantic traversal; 94
semantic changes plus 7 structural changes drove recompilation. Unresolved
identities remained explicit abstentions.

Unlike ECFR-01's 96.12% — which was inflated by 6 no-change pairs and which
the failed adequacy gate correctly refused to promote — this 88.66% is
computed over a cohort in which **every pair actually changed**. It is
therefore the honest work-avoided figure for this family. It is still this
cohort's number, not a general rate (protocol `forbidden`).

## Independent external label

Every pair in this cohort was screened to contain at least one
government-assigned `substantive=true` record in its most recent window. The
label was **not used as a pass gate**.

| | eCFR substantive=true | eCFR substantive=false |
|---|---:|---:|
| TAVONEL semantic > 0 | **11** | 0 |
| TAVONEL semantic = 0 | 0 | 0 |

**11 / 11 agreement, 0 disagreement.** There are no easy cases in this
cohort: unlike ECFR-01, no pair is a byte-identical reissue. Every pair
changed in substance according to the publisher, and TAVONEL detected
semantic change in every one, without over-firing on the locator/metadata
mass (5,613 + 5,613).

Per-part detail:

| Part | Regulator | semantic | rebuild fraction |
|---|---|---:|---:|
| 21 CFR 1 | FDA | 4 | 0.0275 |
| 21 CFR 101 | FDA | 2 | 0.0727 |
| 21 CFR 172 | FDA | 1 | 0.0190 |
| 40 CFR 60 | EPA | 9 | 0.0078 |
| 40 CFR 63 | EPA | 15 | 0.0096 |
| 40 CFR 80 | EPA | 35 | 0.5000 |
| 29 CFR 1910 | OSHA | 1 | 0.0166 |
| 45 CFR 164 | HHS/OCR | 5 | 0.1957 |
| 17 CFR 240 | SEC | 1 | 0.0054 |
| 12 CFR 1026 | CFPB | 5 | 0.1429 |
| 49 CFR 571 | NHTSA | 16 | 0.2500 |

The 0.5 rebuild fraction on 40 CFR 80 is the cohort's most aggressive
recompilation. Equivalence still held and nothing was left stale.

## What this establishes

- Typed change-channel separation and selective recompilation hold on a
  second, non-Wikipedia, production-shaped revision family, across **seven
  US federal regulators**, under the **byte-identical sealed V01 evaluator**.
- Full-rebuild equivalence: 11/11. Stale artifacts: 0.
- On a cohort selected (from metadata only) to contain substantive
  amendments, TAVONEL's semantic/non-semantic decision matched an
  independent government label 11/11, with no easy identical-byte cases.
- Mean work avoided on this changed-only cohort: 88.66%.
- Combined with V03 (Wikipedia, 12/12, 85.32%) this is the two-family
  robustness evidence §28-C asked for.

## What this does NOT establish

- It does not widen the V03 claim boundary. V03 remains the evidence for
  its own declared English-Wikipedia projection; its sealed core hashes
  were re-verified by this runner before any network call.
- It does not establish a general work-avoided rate. 88.66% is this
  cohort's number.
- It does not establish OCR, ontology, or customer-data performance.
- Unresolved identity (6) is reported, not hidden; those cases abstained
  rather than force-matching.

## Integrity

- ECFR-01 result was not modified.
- V03 seal was re-verified before fetch.
- Protocol frozen (`sha256:32fb7403…`) before any content fetch for this
  experiment.
- External GPU: $0.00.
