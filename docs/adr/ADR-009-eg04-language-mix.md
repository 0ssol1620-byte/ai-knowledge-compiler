# ADR-009: EG-04 language mix — per-stratum floors replace the Korean >=50% rule

- Status: **Proposed** — the lead adopts or changes the numbers at review. Nothing is enforced until WO-LPC-ADR-IMPL.
- Date: 2026-11-16
- Work order: WO-LPC-ADR (`v34-lanes/workorders/local-public-corpus.md`); decided by Amendment 2 of `v34-lanes/adr/SCOPE-FOUNDER-20261116.md` (customers are global; gold is global-first)
- Scope: the **EG-04 profile only**. The model screen (`profile: screen`, nine strata in `benchmark/screen/strata.yaml`, dev 300 / holdout 100 pages) is unchanged.
- Changes digests of existing compiles: no. Touches no Protected Core module.

## Context

The rule "EG-04 corpus is at least 50% Korean pages" lives in four places:

| Place | Text |
|---|---|
| `benchmark/corpus/CORPUS_POLICY.md`, "Minimum corpus gates" | "Private beta: 1,500 pages, 150 documents, at least 50% Korean, at least ten document classes" |
| `benchmark/screen/manifest.py` (lines ~165, ~209-210) | `korean_pages` count and `ContractError("eg04 needs >=50% Korean pages ...")` |
| `benchmark/screen/strata.yaml` header comment | "Korean strata (language: ko) must be >= 50% of pages" (the screen's own plan happens to satisfy it: 235 of 300 dev pages) |
| core-runtime-arena §7 plan (not in this repository; cited by the work order) | assumes >=50% Korean pages |

It is also pinned by `benchmark/tests/test_screen_manifest.py::test_eg04_profile_accepts_disjoint_and_rejects_overlap_and_low_korean`
(the 40%-Korean fixture) and described in `docs/release/EXTERNAL_GATES.md` (EG-04: >=1,500 pages, >=150 documents).

Amendment 2 made the target customer global and the gold global-first (SEC EDGAR, ESEF, UK iXBRL, NIST OSCAL, US federal data). Korean
sources are kept only for the Korean/HWP stratum. A corpus-wide Korean majority now contradicts the product claim, and one aggregate
share hides the thing EG-04 must show: quality **per document class**.

The only corpus that exists locally is the SEC set (Amendment 3). It is born-digital English financial filings. That fact shapes
what can be promised.

## Options

- **(a) Keep >=50% Korean.** Contradicts the global decision, and forces most of the corpus to be sourced from Korean material that
  Amendment 2 says is not the headline.
- **(b) Per-stratum page floors, plus an English tables stratum.** Each class has its own minimum, so a strong stratum cannot pay for
  a missing one. **Recommended.**
- **(c) Drop any language floor.** An aggregate of 1,500 pages could then be all clean English text and still pass. Rejected.

## Decision (proposed): option (b)

EG-04 keeps its minimums (1,500 pages, 150 documents, at least ten classes) and replaces the aggregate Korean share with the floors
below. The strata are the screen-v1 strata, with `tables` split by language (`ko_tables`, new `en_tables`) and `ko_hwp` added (the
blueprint's V31 Korean/HWP stratum, which the screen does not have).

| Stratum | Lang | Page floor | Min docs | Why this number | Can show | Cannot show |
|---|---|---|---|---|---|---|
| `en_native` | en | 225 (15%) | 20 | Global headline class; same share as the largest Korean stratum so neither language dominates | Text-layer English reading order, headings, lists, footnotes on real filings | Anything about scans, layout stress or non-English |
| `en_tables` (new) | en | 225 (15%) | 20 | Financial statements are the product's money case; 225 pages gives several hundred table grids, enough for a per-table (not per-page) rate | Table grid and span recovery, exact numbers/units/periods, checked against XBRL gold | Merged-cell or rotated tables in scans; tables in other languages |
| `ko_native` | ko | 250 (17%) | 20 | Largest class, because Korean text-layer quality is the cheapest regression to catch | Hangul text-layer fidelity, mixed ko/en lines | Layout stress |
| `ko_scan` | ko | 150 (10%) | 15 | Where the 36.9% weak low-quality-scan row lives; needs enough pages to give an interval, not an anecdote | Recovery cost and failure classes on scanned Korean | Anything in English scans |
| `ko_tables` | ko | 150 (10%) | 15 | Korean statements and forms use different borders and units than SEC tables | Korean table grid and unit handling | Table claims for other languages |
| `ko_hwp` (new) | ko | 75 (5%) | 10 | The blueprint's own HWP stratum; small because HWP is a conversion path, not a model path | HWP/HWPX conversion fidelity | OCR or scan quality |
| `slides` | ko | 100 (7%) | 10 | Slide layout is a distinct failure class (text boxes, no flow) | Region order on non-flow layouts | Dense-text behaviour |
| `formulas` | en | 75 (5%) | 8 | Few documents, but every formula is a binary pass/fail | LaTeX recovery on typeset math | Handwritten math |
| `handwriting` | ko | 75 (5%) | 8 | Hard class with high variance; small floor, reported with its interval | Handwriting transcription | Printed-text quality |
| `distorted` | ko | 100 (7%) | 10 | Skew, blur, curve; shows where the recovery ladder escalates | Degraded-image recovery | Clean-scan quality |
| `adversarial` | en | 75 (5%) | 8 | Hostile-document handling (injection text, malformed files); each page is a pass/fail safety check | Fail-closed behaviour | Typical quality |

Floors sum to 1,500 pages and 151 documents. They are **floors**: a stratum above its floor does not relax another stratum. No
backfilling: a shortfall in one stratum is reported as a shortfall and is not covered by pages from another stratum.

Two guards go with the floors, because floors alone can be gamed by one large document:
- no document supplies more than 10% of its stratum's pages;
- each stratum has at least 5 distinct issuers/publishers (or authors, for handwriting).

Language shares are an **outcome, not a rule**. With these floors Korean pages are 900 of 1,500 (60%) and English 600 (40%). If the
lead moves numbers, nothing requires either share to stay above 50%.

## What the local SEC corpus can and cannot fill

SEC filings are born-digital English HTML/iXBRL, rendered to PDF by the pinned renderer. They can fill:

- `en_native` and `en_tables` — fully, with gold taken from the registrant's XBRL (publisher-authored, per SCOPE Amendment 1).

They cannot fill, and the ADR does not pretend otherwise:

- **Korean strata** (`ko_native`, `ko_tables`, `ko_scan`, `slides`, `distorted`, `handwriting`) — no Korean text exists in the SEC set;
- **scans** — a rendered PDF has a perfect text layer; printing and rescanning would be a synthetic degradation, not a real scan, and
  must be labelled as such if ever used;
- **handwriting** — none exists in the set;
- **slides** — filings are flow documents (investor decks are not in the pinned set);
- **formulas** — financial filings contain almost no typeset math, so `formulas` is not fillable from SEC;
- **adversarial** — real filings are not hostile; adversarial pages must be constructed and labelled as constructed;
- **HWP** — no HWP files exist in the set.

Those strata therefore need another source (DART and other Korean public sources only for these strata, per Amendment 2; own or
constructed documents for `adversarial`). Until they are sourced and rights-cleared, EG-04 is not closable. The corpus freeze must
report each unfilled stratum by name and shortfall, and must not mark EG-04 passed. Screen-v1 is unaffected: SEC still fills `en_native`
there (Amendment 4), and the screen's other eight strata stay as they are.

## Consequences

- Tables are measured separately in English and Korean; a single "tables" number can no longer average them.
- The 1,500-page total can be reached only when every stratum is filled, which is stricter than the old rule for a corpus that is
  mostly English and weaker for one that is mostly Korean.
- Floors are plans, not measurements. No floor is calibrated; they are not evidence of a model's quality on that class.

## Places to change when accepted (WO-LPC-ADR-IMPL)

1. `benchmark/screen/manifest.py`: replace the `korean_pages` check (eg04 only) with a per-stratum floor check; the screen profile is untouched.
2. `benchmark/corpus/CORPUS_POLICY.md`: private-beta bullet.
3. `benchmark/screen/strata.yaml`: header comment only (the screen strata list is unchanged); EG-04 floors live with the profile, not in the screen list.
4. `benchmark/tests/test_screen_manifest.py`: `test_eg04_profile_...` (the 40%-Korean fixture no longer fails on language; a fixture missing the `en_tables` floor fails).
5. core-runtime-arena §7 (outside this repository): the lead updates the plan text.

## Rollback

Restore the `korean_pages * 2 < pages` check, the CORPUS_POLICY bullet and the old fixture. No data or digest depends on this rule.
