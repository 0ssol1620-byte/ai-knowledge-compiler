# Pass A — the human read

**This is the only thing in the package an agent cannot do.** Pass A of the
convergence protocol asks whether a document's supporting *text* asserts more
than its receipt does. Every other pass is a detector looking for a form of
defect someone already thought of. Pass A is the reader noticing something
nobody instrumented.

It is deliberately short. The automated passes narrow the manual surface; they do
not replace it, and a packet long enough to skim is a packet that gets skimmed.

**Time this honestly at 60–90 minutes.** If you have 15, do §1 and §5 and record
the result as partial rather than as a pass.

**What to open.** Everything below cites the repository source, because that is
what the audits read. If you are reading from the hand-over package instead, the
four documents this pass actually needs are built and in it:

| what | in the package | in the repository |
|---|---|---|
| the paper, as built, figures in place | `paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` | `docs/paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` |
| the patent, whole, in one file | `patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` | `docs/ip/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` |
| the two independent claims | `patent/CLAIM_SET.md` §2 (A1), §3 (B1) | `docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md` |
| the drawing sheets | `patent/drawings/TAVONEL_PATENT_DRAWINGS.pdf`, sheets `figures/patent/SHEET01`–`SHEET06` | `docs/ip/drawings/` |
| the paper figures | `figures/paper/FIG01`–`FIG08` (SVG, PDF, 300 dpi PNG) | `docs/paper/figures/` |

The PDFs are generic builds: A4, single column, no venue template, and the patent
copy is a review copy rather than a filing. Neither adds or removes a word.

---

## 0. How to record the result

Tick one box at the end and hand the file back. Do not annotate a PASS with
reservations — a reservation is a FAIL with a note, and recording it as a pass is
the exact failure mode this pass exists to catch.

**A FAIL is not a setback.** It means the package is not handed to counsel or a
venue until the named item is fixed and Pass A is re-run. The convergence stop
rule already requires two consecutive clean rounds, so one FAIL costs a round,
not a programme.

---

## 1. The two independent claims — read the recital against the evidence line

Source: `docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md`, §2 (A1) and §3 (B1) — or
Part III of `patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf`, which is the same
text.

For each numbered element, ask one question: **does the evidence named beside it
observe that limitation, or something adjacent to it?**

The six A1 elements and nine B1 elements were amended on 2026-08-20 specifically
to close that gap, so the interesting reads are:

- **A1 element 1** now says *page-level* attribution. The receipt records
  `image_path` and `document_id` per row. Is "page-level source evidence
  attribution" a fair description of that, or is it still one step grander?
- **A1 element 3** now says *per-page critical-token correspondence*. The receipt
  records `cross_parser_mismatches` against a frozen operating point of 21. Same
  question.
- **A1 element 5** says the gate applies both signals *jointly*. The receipt
  records 5 severe errors caught by agreement alone, 5 by stability alone, 38 by
  neither. Does "jointly" overstate that?
- **B1 element 1** now recites only identifier persistence. Does the claim read as
  ordinary record linkage without the evidence-region binding that was removed?
  (Counsel flagged this; your read is the other half of it.)
- **B1 element 7** recites predicates *invariant to evaluation order*. H1-I
  measured order-invariance and explicitly did **not** measure independence. Does
  any sentence near this element imply independence?
- **B1 element 9** recites a *single state-transition event*. Does anything in
  the surrounding text drift toward crash safety or distributed atomicity?

## 2. The abstract and the conclusion

Source: `docs/paper/MANUSCRIPT_v1_2026-08-19.md` §Abstract and §7, or the same
sections of `paper/TAVONEL_MANUSCRIPT_GENERIC.pdf`.

These are the two passages a reader remembers, and both are prose with few
numbers, which is exactly what the numeric-binding detector cannot check.

Read for one thing: **a sentence that would still sound true if every negative
result were removed.** The programme's negatives are the structure-only defect,
the identity path-dependence veto, the sparse-acceleration slowdown, the
governance-filter redundancy, and the unmeasured comparative endpoint. If the
abstract reads well without them, it is overstating.

## 3. The primary figures and tables

- **Figure 6** especially — rendered at `figures/paper/FIG06.svg` (and in place
  in the built PDF); specified in `docs/paper/FIGURES_2026-08-19.md`. It is the
  package's own limitations section in one image, and it gained two boxes on
  2026-08-20: a contract-audit class and an amber "implementation only —
  reserved, not filed" class. Are the boxes in the right places?
- `docs/paper/TABLES_2026-08-19.md` — **Table 1** (evidence hierarchy) and
  **Table 5** (blocked and not-run work). Table 5's W6 row is the most-read row
  in the package. Does it read as "not measured", or does it read as "failed"?

## 4. The limitations section

Source: `docs/paper/MANUSCRIPT_v1_2026-08-19.md` §5, limitations 1–20.

You are not checking that they are true. You are checking **whether any of them
is contradicted elsewhere in the same document.** A limitation that says a thing
is unmeasured, sitting three sections away from a sentence that treats it as
measured, is the defect. Limitations 10–20 are the newest and least re-read.

## 5. Blind category judgements — do these without reading the answer first

This section is the one that cannot be delegated, because knowing the intended
answer destroys it. For each, write your judgement **before** looking anything
up, then compare.

| # | judge this | your call |
|---|---|---|
| 1 | Is "the comparative endpoint was NOT_MEASURED" a fair description of a benchmark that acquired a corpus, generated 2,548 questions, ran three gates, and stopped? Or is it a euphemism? | ☐ fair ☐ euphemism |
| 2 | The v8 development set measured a 7.34% tie rate and passed; the untouched holdout measured 19/166 = 11.45% and failed. Does the package's account of *why the arms did not run* read as principle or as rationalisation? | ☐ principle ☐ rationalisation |
| 3 | A1 element 7 was removed rather than made testable by building an admission path. Is that discipline or avoidance? | ☐ discipline ☐ avoidance |
| 4 | Eleven of twenty-four amendments are recorded as broadenings. Does the package treat that as a cost it paid, or does it present it as an improvement? | ☐ cost ☐ improvement |
| 5 | Read the 64.46% wrong-revision observation and its label. Does the label hold, or does the surrounding text let it drift into evidence for the system? | ☐ holds ☐ drifts |

**If any answer lands in the right-hand column, that is a FAIL** and the item
should be named in the box below. The right-hand answers are the ones the whole
package is built to make impossible; finding one is the packet working.

## 6. Counsel flags still open — read these as questions, not as defects

Eight amendments carry a counsel flag. They are prosecution-strategy questions
that an agent is not permitted to decide, and they are listed here so nobody
mistakes them for unfinished work:

| flag | question |
|---|---|
| `B1-E2-RESTRICTED-STRUCK` | restore a different narrowing limitation, or prosecute the broader element? |
| `B1-QUERY-FILTER-TO-B10` | how should B1 be sequenced against B10? |
| `B1-E7-ORDERING-WITHDRAWN` | is order-invariance a sufficient structural limitation? |
| `A3-RESERVED` | evaluate on enablement alone, or hold for a continuation? |
| `B6-DEPENDENCY-TO-B10` | keep B6 depending from B10, or restate the constraint inside B6? |
| `A1-E1-PER-UNIT-REGION-TO-A4` | file A4 with the application, or hold it? |
| `A1-E7-ADMISSION-TO-A5` | prosecute A5 on enablement, or hold for a continuation? |
| `B1-E1-EVIDENCE-REGION-TO-B7` | is B1 element 1 still distinguishable from record linkage? |

Also open, and also not an agent's call: **whether to file at all, when, and in
which jurisdictions** (`docs/ip/V4_DISCLOSURE_REGISTRY.yaml`), and whether any
element should be held as a trade secret instead.

---

## Result

**Read the consequence before ticking.**

- ☐ **PASS** — no supporting text asserts more than its receipt. The package may
  go to counsel and to a venue. The convergence round is re-run with
  `--human-findings 0`, and this becomes the first of the two consecutive clean
  rounds the stop rule requires.

- ☐ **FAIL** — at least one item below. Nothing is handed over. Each item is
  fixed, every dependent surface is re-synced, the automated passes are re-run,
  and Pass A is performed again from the top. The round does not count, and
  `consecutive_clean` returns to zero.

**Items found (one line each — document, location, what it asserts, what the
receipt says):**

1.
2.
3.

**Read by:** ______________________  **Date:** ______________

---

## What this packet deliberately does not include

The full manuscript, the full specification, every dependent claim, and the
twenty-four amendment entries. They are in the package and available, and a Pass
A that requires reading all of them will not be performed — which is worse than a
narrow one that is.

**This is a stated limitation of Pass A itself**, recorded in the convergence
protocol: the pass is blind to *anything the reader does not think to check*, and
narrowing the packet narrows the reader's field of view further. §5 exists to
push against that, by asking for judgements rather than for verification.
