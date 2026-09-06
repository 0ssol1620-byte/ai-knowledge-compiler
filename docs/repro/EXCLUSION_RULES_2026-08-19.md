# TAVONEL program-wide evidence exclusion rules — 2026-08-19

These rules govern what may **not** be counted as support when synchronizing TAVONEL patent claims, paper results, figures, readiness gates, or executive summaries. They consolidate restrictions already present in experiment protocols, receipts, the claim–evidence matrix, failed/superseded ledgers, and hostile reviews. They do not retroactively upgrade any result.

## 1. Global scientific exclusions

1. **Live evidence beats narrative status.** A handoff, status note, manuscript sentence, or planning document is not evidence when it conflicts with the live repository, frozen protocol, code pin, source hash, or receipt.
2. **Failed, invalid, withdrawn, superseded, null, and negative results are never deleted to improve the story.** They remain provenance and may constrain later wording.
3. **No post-outcome endpoint repair is confirmatory.** Any threshold, inclusion rule, corpus membership, baseline, metric, statistical rule, or decision criterion changed after outcome inspection must be recorded as an amendment/exploratory follow-on and cannot inherit the old confirmatory label.
4. **A spent one-shot holdout cannot be reused for tuning.** Regression on it may detect implementation drift only; it cannot become a second independent endpoint.
5. **Controlled/generated, retrospective real-corpus, fresh holdout, exploratory, and confirmatory evidence are different classes.** No class may be silently promoted to another.
6. **Completion is not accuracy.** Parser output/completion/recovery rates cannot be reported as semantic correctness unless a correctness evaluator measured it.
7. **Measured is not extrapolated.** Artifact-count savings, planned rebuild fraction, or asymptotic intuition are not measured latency, memory, I/O, cost, or end-to-end speed.
8. **Stage-local speed is not pipeline speed.** A downstream selective-recompilation ratio or isolated identity-matcher microbenchmark cannot be presented as an end-to-end TAVONEL speedup.
9. **Passing repetitions are not independent observations.** Repeated deterministic cases within one constructed mechanism cell do not multiply the number of independent scenarios.
10. **Research readiness is not production clearance.** Licence approval, a successful research experiment, or a ready runtime does not override `promotion_eligible`, customer-traffic, legal, security, or product gates.
11. **Receipt integrity is not arbitrary input-consumption completeness.** A sealed receipt proves only the captured claims about declared/observed inputs and outputs. It does not prove that an unconstrained builder recorded every filesystem, global, network, dict/list, or other read.
12. **Untracked output is not high-integrity output.** A permissive/untracked build path may be degraded or refused, but cannot be counted as independently verified HIGH_INTEGRITY evidence.

## 2. A9 selective-acceptance exclusions

- The historical wall-clock-dependent evaluator result is retained but excluded from the authoritative confirmatory endpoint. The deterministic correction is authoritative.
- The corrected frozen holdout is 800 pages; it may not be re-tuned after unsealing.
- The observed 6.02 percentage-point risk difference is **not** proof of a causal 6.02-point reduction: its corrected bootstrap interval includes zero. Fisher exact `p=.032` supports an association on the frozen holdout, not a certain effect magnitude.
- Output-only validation cannot support claims that subtle number/sign/date/entity/row swaps were source-groundedly detected when the evaluator had no source-grounded signal for those errors.
- Completion/recovery percentages from the 5,132-document parser benchmark are excluded from semantic-accuracy claims.

## 3. Family B selective recompilation / promotion exclusions

- The final fresh-seed nine-cell holdout is spent. It may not be used for endpoint tuning or described as newly independent after any implementation change.
- Equivalence observed on measured topologies/corpora cannot be generalized to arbitrary dependency declarations, arbitrary builder reads, arbitrary domains, or all future graphs.
- Declaration-integrity falsification and independent verification must remain separate: a verifier derived from the same corrupted declaration is excluded as proof of fail-closed independence.
- Build-receipt seals do not establish consumption completeness for unconstrained builders.
- Planner-level stale classification and publish/controller-level refusal are distinct; neither may be substituted for the other.

## 4. H1-D governance / temporal / lineage exclusions

- The evidence unit is **22 constructed mechanism cells**. Each was repeated 500 deterministic times; `11,000` is an execution count, not 11,000 independent natural observations.
- Correct resolver behavior given valid-time/authority inputs is excluded from claims that TAVONEL automatically extracted those inputs from arbitrary documents.
- Controlled conflict, permission, replay, and lineage mechanisms are excluded from external-frequency or real-world-generalization claims.

## 5. H1-E / H1-E2 identity-scaling exclusions

- `MatchingPolicy.BLOCKED` remains a performance shadow; LEGACY is the correctness/default policy.
- The H1-E generated topologies are controlled mechanism evidence, not a real-corpus identity arm.
- The eight residual tied split assignments may **not** be waived because their outcome multiset matches. H1-E2 found all 8/8 source-row differences changed the next-revision decision under valid controls.
- The current BLOCKED implementation is therefore `PROMOTION_VETO_PATH_DEPENDENT`; its speed/memory measurements remain reportable only within their isolated benchmark scope.
- BLOCKED microbenchmark timing is excluded from end-to-end identity-plus-change-detection or whole-pipeline speed claims.
- A later LEGACY-exact sparse matcher would require a new frozen protocol; H1-E2 cannot be reinterpreted post hoc as its validation.

## 6. H1-F natural-revision regression exclusions

- H1-F includes all 28 previously stored English-Wikipedia revision pairs / 56 sealed files. It is **retrospective real-corpus regression**, not a fresh holdout and not confirmatory.
- Only 11/28 pairs contain semantic changed logical IDs under the evaluation adapter. The other 17 no-semantic-change pairs are excluded from counts of positive semantic-change events.
- The 28/28 selective/full match with stale 0 is excluded from claims of general equivalence, cross-source external validity, arbitrary production-graph correctness, or 28 independent domains.
- English Wikipedia is one source family. SEC/DART/contracts/scans/language/layout generalization remains open unless measured under a separate frozen protocol.

## 7. W6 same-intelligence evaluation exclusions

- W6 v1 remains INVALID/SUPERSEDED because query construction leaked target passage wording and made the retrieval baseline degenerate. Its high retrieval score is excluded from model/world-quality comparisons.
- W6 v2 remains protocol-valid NOT RUN because the frozen corpus supplied zero revision-sensitive structured facts. Thresholds/corpus requirements may not be lowered after seeing that result and still be called the same confirmatory endpoint.
- The 6,987 Featured Article title manifest was frozen before historical outcomes. Titles may not be reselected after acquisition based on whether they produce convenient revisions/questions.
- Transport fixes may add checkpointing/resume/backoff but may not change candidate membership, historical cutoffs, or inclusion based on outcomes.
- A final question set cannot use target-passage near-copies; conflict and multi-document categories count only when genuinely present.
- Raw vs Basic RAG vs TAVONEL may run only after question sufficiency and baseline validity pass under frozen rules, with primary endpoint/statistical rules frozen before outcome inspection.

## 8. A12 cause-conditioned recovery exclusions

- The 48 frozen source-only cases are fixed. GPU inputs may not contain or mount ground truth/evaluator labels.
- A research GPU run is excluded unless an immutable qualified runtime, exact same-family ablation recipe, independent local evaluator/scoring contract, and budget/preflight gates are satisfied before spend.
- GPU outputs must be hash-frozen before local scoring.
- Current state is `BLOCKED_RUNTIME_AND_RECIPE`: licence and source-only integrity pass, immutable runtime and exact same-family recipe do not. Provider provisioning is therefore excluded by the preregistered stop-before-spend rule.
- Candidate licence approval is excluded from any claim of production promotion; `promotion_eligible: false` remains separately binding.

## 9. Prior-art / patent-language exclusions

- Generic RAG, dependency graphs, lineage, provenance, incremental build, versioned state, or confidence routing alone are excluded as novelty arguments for TAVONEL.
- Patent language may rely only on the narrower technical combinations actually implemented/enabled and supported at the evidence class stated in `docs/ip/claim-evidence-matrix.yaml`.
- A technical mechanism may be described as an embodiment when implemented without empirical support, but its performance/correctness benefit cannot be upgraded beyond the matrix status.

## 10. Reproducibility exclusions

- A reconstructed *current reproduction command* is not evidence of the exact historical invocation unless the invocation is preserved in a receipt, log, protocol, shell record, or other repository artifact.
- Missing historical invocations are reported as `NOT_RECOVERABLE_FROM_REPOSITORY`; they are never invented from argparse/help text.
- A current dirty worktree/environment snapshot is not retroactively asserted as the historical environment of an older result.
- A receipt whose self-hash fails, whose source/code pin has drifted, or whose required frozen source bytes no longer match is excluded from a current pinned claim until the discrepancy is resolved by provenance-preserving rerun/amendment rather than receipt editing.
