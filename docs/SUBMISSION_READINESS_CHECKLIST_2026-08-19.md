# File / submit readiness checklist — 2026-08-19

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Two lists. Everything in **§A** is an internal task and none of it needs a human
outside the project. Everything in **§B** requires a person — a founder
decision, an attorney, an account, a signature or a fee — and **no agent may do
any of it**.

An item is only ticked when the artifact exists and has been verified, not when
it has been planned.

---

## A. Internal — must be complete before either package is handed over

### A1. Evidence integrity

- [x] Every claim binds to a receipt by sha256 — `docs/ip/CLAIM_EVIDENCE_MATRIX.md`
- [x] Matrix generator re-reads every asserted number out of its receipt and
      refuses to emit on disagreement (it caught one on its first run)
- [x] Pinned core modules still hash to what each measurement recorded —
      **undeclared drift 0**; the count of receipts is read from
      `docs/repro/EXPERIMENT_MANIFEST.json`, not written here. Embedded counts in
      this file went stale twice, which is why they were removed.
- [x] Every receipt's self-recorded `receipt_sha256` recomputes —
      `receipts_whose_self_hash_does_not_recompute: 0` in the same manifest
- [x] Superseded and failed results retained, not deleted —
      `docs/evidence/FAILED_AND_SUPERSEDED_LEDGER.md`
- [x] Experiment manifest with commands and environment —
      `docs/repro/EXPERIMENT_MANIFEST.json`
- [x] Consolidated exclusion-rule document — `docs/repro/EXCLUSION_RULES_2026-08-19.md`, pinned by the execution index (X7 closed)
- [ ] Experiment-time environment lock rather than a manifest-time package digest (X5 stays open/mitigated; the digest is **not** a lockfile and is not described as one)
- [x] Execution index separating current reproduction route from historical invocation recovery — `docs/repro/EXECUTION_INDEX_2026-08-19.json` (X8 closed, narrowly: **exactly one** historical invocation is recoverable; the rest are marked NOT_RECOVERABLE_FROM_REPOSITORY, and the denominator is the experiment count in the manifest)
- [x] Drift classified declared-historical vs undeclared — `docs/repro/HISTORICAL_DRIFT_REGISTER.yaml`; manifest fails only on undeclared, currently 0

- [x] **Build status under the project environment** — emitted by
      `tools/repro/run_test_scopes.py` into `docs/repro/TEST_SCOPE_STATUS.json`,
      which records the interpreter and withholds `repository_green` when it is
      not the project one. **Not tickable from a narrower scope**: "697 passed"
      is `tests/unit`, and every figure this programme published before session 9
      was produced by the global interpreter rather than the project venv.
      Current: `unit` 697 passed / 0 failed / 32 skipped; `full` 2,758 passed /
      0 failed / 32 skipped; `repository_green: true`, with four controls passing
      in the same execution.
- [ ] **Convergence** — `docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md` is frozen
      and has been executed **zero** times. Three earlier passes do not count
      under it, and each found new material defects. This box may not be ticked
      until the frozen stop rule is met.

### A2. Patent package

- [x] Claim set drafted and narrowed — `docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md`
- [x] Prior-art and narrowing memo — `docs/ip/PRIOR_ART_AND_NARROWING_MEMO_2026-08-19.md`
- [x] Explicit non-claims enumerated with reasons
- [x] Every claim element mapped to a matrix row, or flagged as
      enablement-only (claim A3)
- [x] Hostile examiner review with open findings and severities
- [x] **Full specification with embodiments** — `docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md`
- [x] Figures: lifecycle, selective-vs-full boundary, identity failure mechanism (Figure 7), identity trade table (Figure 8), evidence map — `docs/paper/FIGURES_2026-08-19.md`, with drawing rules forbidding BLOCKED from being rendered as a success
- [ ] Figures rendered to publication assets (currently specified as mermaid + tables, not exported)
- [ ] Sequence listing of claim dependencies checked for antecedent basis
      (attorney task, but a self-check first would save a round trip)

### A3. Paper package

- [x] Manuscript with methods, results, limitations, threats to validity
- [x] Every number traceable to a receipt
- [x] Permitted/forbidden wording enforced from the matrix
- [x] Negative and invalidated results reported in the body, not buried
- [x] Post-unsealing correction disclosed as such
- [x] Hostile reviewer and reproducibility red-team completed
- [ ] Introduction and related-work sections (deliberately written last)
- [ ] Figures
- [ ] Venue selected, and the manuscript reformatted to its template
- [ ] Anonymisation pass if the venue is double-blind — note that
      `docs/repro/EXPERIMENT_MANIFEST.json` contains absolute Windows paths and
      a git commit hash, and the A9 receipts contain `D:\a9h\...` artifact
      paths. **These must be scrubbed or excluded from any anonymous
      supplementary package.**

### A4. Science still open (does not block handover, does weaken it)

- [ ] W6 primary endpoint — acquisition running; endpoint currently NOT RUN
- [ ] A12 GPU arm — **one** gate left (`formal_immutable_runtime_not_ready`); the exact same-family recipe is now frozen for all 48 cases. Not licence, not data
- [ ] Real-corpus equivalence arm for Family B (examiner finding P4)
- [ ] External generalization: unseen domains, layouts, languages
      (**highest-severity open finding, R5**)
- [x] Ablation coverage audited — `docs/audit/ABLATION_COVERAGE_2026-08-19.md`; most load-bearing mechanisms already carry ablation-shaped evidence
- [ ] Gate-check **ordering** ablation (claim limitation currently rests on reasoning)
- [ ] Per-filter authority/temporal/lineage ablations
- [ ] Ontology / entity resolution on SEC/DART
- [ ] Source-grounded acceptance cohort under a *new* protocol
- [ ] `MatchingPolicy.BLOCKED` promotion — needs a new protocol covering the
      permutation class, independent review, and a canary

---

## B. External — human only. No agent performs any of these.

### B1. Founder decisions

- [ ] Whether to file at all, and **when** — `docs/ip/V4_DISCLOSURE_REGISTRY.yaml`
- [ ] Jurisdictions, and provisional versus direct
- [ ] Whether any element is better held as a trade secret
- [ ] Whether claim A3 is filed on enablement, held for a continuation, or dropped
- [ ] What any public claim says, and whether the evidence supports it
- [ ] Venue and submission timing, relative to the filing date
- [ ] Author list, order, affiliations, funding and conflict disclosures
- [ ] Whether the reproducibility package is released publicly, and under what
      licence

### B2. Attorney work

- [ ] Professional prior-art search — **none has been performed**
- [ ] Freedom-to-operate analysis — **not addressed anywhere in this repository**
- [ ] Formal claim drafting, antecedent basis, jurisdiction formatting
- [ ] Inventorship determination

### B3. Accounts, signatures, fees

- [ ] Patent office account, electronic signature, filing fees
- [ ] Submission portal account, camera-ready agreement, any publication fee
- [ ] Any licence or data-use permission the venue requires for released data

---

## Honest summary

The **evidence layer is submission-grade**: verified end to end, with failures
retained and every number bound to a hash. The **patent package now has claims,
a specification with embodiments, and a narrowing memo**; the manuscript has its
load-bearing half.

Neither package is at "one button away." The remaining internal gaps are
**figures** on both sides and the **introduction / related work** on the paper
side. Both are writing tasks with no external dependency.

The scientific gap that most limits what either package can claim is external
validity: the Living Knowledge results are controlled-corpus results. That is
stated in both artifacts, and it is the honest ceiling on the current claim set.

---

## E. Added 2026-08-19, session 5

- [x] Manuscript introduction and related work written — no longer a placeholder
- [x] Manuscript failure analysis (§5.1) and conclusion (§7) written
- [x] Abstract updated with the exact-matcher negative result and both claim narrowings
- [x] P2-13 answered: semantic contract frozen, exact matcher built, measured slower, registered `FAILED` on the objective
- [x] W6 resume audit — `RESUME_UNSAFE_AS_IMPLEMENTED`, option B (fresh corpus-v6) selected with an explicit contract
- [x] A12 zero-cost unblock audit — `BLOCKED_EXTERNAL_CONFIRMED_AT_ZERO_COST`, no container runtime present
- [x] Claim B4 given an explicit boundary: bounded-score property of an indexing scheme, **not** a correctness-preserving optimisation
- [x] Claim A3 corrected from "two internal gates" to one external gate
- [x] Ablation coverage closed: every remaining mechanism either has ablation-shaped evidence or supports a claim drafted too narrowly for an ablation to test
- [x] Hostile review P9–P11 recorded
- [ ] W6 recovery protocol frozen + tiny kill/restart fixture — **required before any network acquisition**, not yet built
- [ ] H1-E residual 8 cases wired into the H1-L exactness corpus — declared gap, not covered
- [ ] Second source family for external validity — no offline corpus with explicit amendment relationships exists

