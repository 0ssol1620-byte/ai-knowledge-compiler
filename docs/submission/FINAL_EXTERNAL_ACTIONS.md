# Final external actions

**Ten items. Every one of them requires a person, a licence, an account or a
legal judgement.** Nothing on this list is agent work that was left undone.

The list is short on purpose. A long list of "external actions" is usually a way
of handing someone else the work, and the previous version of this file was
drifting that way: rendering the figures, building the PDFs, assembling the
package, validating the hash manifest, generic typesetting and building a review
copy were all things an agent could do, and they have been done. They are not
here.

What is here is the residue: judgements about scope and disclosure, a search that
needs an engagement, a determination with validity consequences, and the two
buttons that actually submit something.

---

## 1. Pass A — the human read

**Who:** anyone in the programme who did not write the documents.
**Input:** `human-review/HUMAN_PASS_A_PACKET.md` (repository:
`docs/submission/HUMAN_PASS_A_PACKET.md`).
**Time:** 60–90 minutes.

**Why an agent cannot do it:** the pass asks whether a document's supporting text
asserts more than its receipt does, and its declared blindness is "anything the
reader does not think to check". An agent performing it would be the same context
that wrote the text — the one reader guaranteed to think of exactly the things
already instrumented. §5 of the packet asks for blind category judgements, and
knowing the intended answer destroys them.

**Consequence of skipping it:** `clean_round` stays false, no round counts toward
the two-consecutive-clean stop rule, and `convergence_declared` stays false. The
agent-side figure `agent_convergence_complete` is recorded separately and **is
not convergence**.

---

## 2. Patent counsel review, including jurisdiction formatting

**Who:** registered patent counsel in the filing jurisdiction.
**Input:** `patent/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` — title, abstracts,
specification, claim set and drawing sheets in one file — with the registers
beside it in `patent/`.

Four things counsel owns and this package deliberately does not decide:

1. **The eight counsel-flagged amendments** (listed in the Pass A packet §6).
   Each is a prosecution-strategy question — restore a limitation, prosecute the
   broader claim, or sequence claims differently — recorded with the technical
   facts and without a recommendation.
2. **Claim numbering, antecedent basis, dependency form, and jurisdiction
   formatting**, including drawing-sheet size, margins, header blocks and numeral
   conventions. The draft fixes *scope*, not form. The drawing sheets are
   monochrome line art with three-digit reference numerals and are supplied as
   vector SVG, per-sheet PDF and a combined print-ready PDF; adapting them to a
   jurisdiction's formalities is draftsmanship, not redrawing.
3. **Whether the RESERVED group is filed with the application, held for a
   continuation, or dropped.** A3, A4, A5, B7 and B9 are in that group, each with
   its evidence class stated.
4. **The §103 reserves.** Two are held for B1 and recorded with their boundaries;
   A1's reserve is currently **unavailable**, and counsel should know that before
   a rejection rather than after.

---

## 3. Professional prior-art search

**Who:** a professional searcher, commissioned by counsel.

**No search has been performed.** Every §102 and §103 disposition in
`red-team/EXAMINER_RED_TEAM_STATUTORY.md` is a drafting position taken over the
art we happen to know. It is on this list because it needs an engagement and a
budget, not because it is optional — an unsearched application is a filing made
without knowing what it is being filed against.

---

## 4. Freedom to operate

**Who:** counsel, as a separate engagement from patentability.

`patent/TECHNOLOGY_INTAKE_REGISTER.yaml` holds the binding intake position. Its
three rules are easy to get backwards and are repeated here because this is the
document someone reads in a hurry:

- an OSS licence is copyright permission from one contributor, and settles
  nothing about a third party's patents;
- a public repository with no LICENSE grants no commercial reuse right — its
  paper may be read, its code may not be ported;
- code, model weights, dataset and hosted-API terms are four separate licences,
  and clearing one clears none of the others.

Patentability and freedom to operate answer different questions. Clearing item 3
does not touch this one.

---

## 5. Inventorship and applicant entity

**Who:** the founder, with counsel.

Inventorship is a legal determination with consequences for validity, and it is
**not derivable from commit authorship**. The package names no inventors.
Applicant entity, assignment, and any employment-agreement obligations are the
same kind of question and are decided at the same time.

---

## 6. The filing decision, and filing

**Who:** the founder decides; counsel executes.

`PATENT_FILING = NOT FILED`. Filing timing, jurisdiction, whether to file at all,
and whether any element should be held as a trade secret instead are founder
decisions recorded in `patent/DISCLOSURE_REGISTRY.yaml`.

**This item gates item 10.** Submitting the paper is a public disclosure, so the
paper cannot be scheduled before this is settled.

---

## 7. Paper venue selection

**Who:** the founder.

The manuscript, references, figures, tables, reviewer prebuttal and
reproducibility statement are complete and internally consistent. What is missing
is a venue — and with it the answer to whether the W6 boundary, the negative
results and the twenty limitations are presented as they stand or reframed for a
particular audience. That is an editorial judgement about where the work belongs,
not a formatting step.

---

## 8. Venue-specific formatting

**Who:** whoever prepares the camera copy, once item 7 is answered.

`paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` is a **generic** build: A4, single column,
no template. `paper/submission-source/` carries the manuscript split at its own
headings — body, references, appendices, tables, figures, reproducibility — so
that an ACM, IEEE or NeurIPS template can be filled without re-deriving the
structure. The rendered figures in `figures/paper/` are SVG vector masters with
PDF copies and 300 dpi PNG previews, which is every form a venue asks for.

What remains is genuinely venue-specific: the template itself, the page limit and
what is cut to meet it, anonymisation if the venue is double-blind, and the
venue's own figure and reference styles.

---

## 9. Authors, author order, acknowledgements and funding

**Who:** the founder, confirmed before submission.

The manuscript states that these are deliberately absent. Author order and
acknowledgement are social and contractual facts about who did what, and funding
disclosure is a statement with consequences if it is wrong. None of the three is
derivable from the repository.

---

## 10. The submission itself

**Who:** the founder.

Creating the account, uploading the files, agreeing to the venue's terms, and
pressing submit. Nothing in this package has been uploaded anywhere.

---

## Recorded separately: an environment blocker, not a submission action

Claim **A3**'s empirical arm (`H1-A12`) needs a container registry that can
produce a real image digest. No container runtime exists on this host, and an
image digest is the hash of pushed content — it cannot be authored by hand. A3 is
in the RESERVED group and is not in the filing core, so this blocks no item
above. It is written here so that it is not rediscovered as a surprise.

Customer-data consent, pilot contracts and pricing are founder decisions in the
same category, and are not part of this submission.

---

## What is **not** on this list, and why

| not here | because |
|---|---|
| render the figures, build the PDFs, assemble the package, validate the manifest, generic typesetting, build the review copy | agent work, and it is done — `figures/`, the three built PDFs, and a manifest that verifies |
| "fix the remaining Pass K findings" | the four remaining are RESERVED claims held out of the filing core by a recorded decision, printed in every round and never counted as fixed |
| "close the three UNDETERMINED amendment histories" | a declared standing bound — the claim set is deliberately untracked and the hash chain reaches nothing before it was pinned. Unrepairable, not unfinished |
| "identify the three unreproducible test failures" | their identities were never captured and are unrecoverable. The reporting invocation now carries `-rf` so a recurrence names itself; that is the whole available action and it was taken |
| "run the W6 comparative endpoint" | the cohort is spent and is development data. A comparative result needs a fresh untouched cohort, which is a new experiment and not a completion of this one |
| "produce evidence for A4, A5, B7, B9" | each would require either a measurement campaign or building a mechanism so that a claim could be tested. The second was refused on principle; the first is a scoping decision, not a gap |
