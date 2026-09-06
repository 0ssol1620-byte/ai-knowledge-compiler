# Failed, invalidated and superseded results — retained ledger

**Nothing in this file is deleted, edited or softened.** A superseded receipt is
pinned by hash from the receipt that supersedes it. A failed result keeps its
original wording. This file exists because a research record that contains only
successes is not a research record.

Every row states what was claimed, what actually happened, what it cost, and
what changed as a result.

---

## 1. Family B — structure-only change left a stale artifact CURRENT

| | |
|---|---|
| receipts | `H1-B-REAL-REVISION-01/receipts/structure-only-stale-diagnosis-2026-08-18.json`, `.../stale-attribution-correction-2026-08-19.json` |
| outcome | `all_equivalent = False`, `stale_left_behind = 2` |
| status | **FAILED**, superseded by the corrected implementation |

A change that altered only the order of units produced no changed logical
identifiers. The impact traversal therefore started from an empty seed, and a
position-aggregated artifact that was genuinely stale was carried forward as
CURRENT. The promotion gate blocked the run.

**Two things not to conclude from this.** The gate holding is not a pass:
equivalence had already been violated by the time it fired, and scoring the run
as a success because the safety net worked scores the wrong thing. And the
system did not publish a wrong world state — the planner produced a
false-negative CURRENT classification, and the first version of the promotion
gate had a fingerprint blind spot.

**What changed:** the structural dependency channel, `StructuralPolicy`,
`DocumentShape.unit_order`, unresolved-incoming seeding, and a fingerprint that
covers structural facts as well as declared inputs.

## 2. Family B — an early adversarial topology extension was invalidated

| | |
|---|---|
| receipts | `.../adversarial-topology-extension-attempt1-invalidation-2026-08-19.json`, superseded by `.../adversarial-topology-extension-v2-2026-08-19.json` |
| status | **SUPERSEDED** |

Retained because the invalidation is itself the evidence that the sweep was
checked rather than accepted.

## 3. Family B — generator collision

| | |
|---|---|
| receipt | `.../generator-collision-correction-2026-08-19.json` |
| status | **SUPERSEDED** |

A harness defect, traced rather than dismissed as a generator artifact. Recorded
because two harness bugs and one real Protected Core gap were separated only by
dumping the actual diff, and that method is the transferable part.

## 4. A9 — the first confirmatory evaluator was non-deterministic

| | |
|---|---|
| receipts | `H1-A9-01/receipts/evaluator-determinism-2026-08-18.json`, `.../evaluator-correction-comparison-2026-08-18.json` |
| superseded by | `.../confirmatory-result-deterministic-2026-08-18.json` |
| status | **SUPERSEDED** |

The endpoint had already been unsealed when the defect was found. This is a
**post-unsealing correction** and is disclosed as one in the manuscript rather
than presented as the original result. The corrected numbers are the ones that
may be cited.

## 5. A9 — the magnitude claim was withdrawn

| | |
|---|---|
| status | **WITHDRAWN** |

An earlier framing reported a 6.02 pp reduction in severe-error rate. The
corrected risk-difference bootstrap interval is [−0.21 pp, +12.79 pp] and
contains zero. The association survives (Fisher exact p = .032); **the magnitude
does not** and is withdrawn. The pre-registered test being significant and an
effect size being established are different claims.

## 6. A9 — no source-grounded arm was possible

| | |
|---|---|
| status | **NOT RUN**, cohort limitation |

The frozen cohort is scan-image centred and carries no compatible native text
layer, so there was nothing to ground against. This is a property of the cohort,
not a design decision, and it must not be repaired by redefining the frozen
cohort. A source-grounded arm needs a new protocol and a new cohort.

## 7. W6 v1 — invalidated by leakage

| | |
|---|---|
| receipt | `H1-W6-SAME-INTELLIGENCE-01/receipts/question-set-v1-invalidation-2026-08-19.json` |
| status | **SUPERSEDED / INVALID** |

Recall@1 ≈ 0.9969 with a same-document share of 1.0. The baseline was not a
baseline; the questions could be answered from the retrieved passage because the
questions were built from it. The binding upper-bound gate is what caught it,
which is the argument for making ceilings binding rather than advisory.

## 8. W6 v2 — primary endpoint NOT RUN, honestly

| | |
|---|---|
| receipt | `.../question-set-v2-2026-08-19.json` |
| status | **NOT RUN** |

Structured questions were generated from infobox attribute names after the
protocol was frozen. The 56-pair corpus consisted of *consecutive* revisions, in
which zero infobox facts moved. Two escapes were available and both were
declined: lowering the threshold, and manufacturing questions from prose diffs.
The endpoint was declared not run.

**This is the correct outcome and is recorded as a success of process**, not as
a gap to be closed by weaker evidence.

## 9. W6 v3 / v4 — transport failures, not scientific failures

| | |
|---|---|
| receipts | `.../title-manifest-v3-2026-08-19.json`, `.../transport-freeze-v4-2026-08-19.json` |
| status | **FAILED (infrastructure)**, retryable |

v3 and v4 failed on the MediaWiki API — transient error envelopes, and an
`invalidparammix` from combining multiple titles with `rvstart`. No scientific
criterion was involved. v5 changes the transport to one title per request and
changes nothing else; the freeze receipt records `scientific_rules_changed:
false` and pins the v3 protocol and script hashes.

The 6,987-title candidate manifest was frozen **before** any revision outcome
was inspected, so no selection leakage exists to inherit.

## 10. Family B performance — first attempt incomplete

| | |
|---|---|
| receipt | `.../measured-performance-attempt1-incomplete-2026-08-19.json` |
| superseded by | `.../measured-performance-v2-2026-08-19.json` |
| status | **SUPERSEDED** |

## 11. Identity at 10,000 units — `MemoryError`

| | |
|---|---|
| receipt | `.../measured-performance-v2-2026-08-19.json`, field `attempt1_10k_identity_limit` |
| status | **FAILED**, retained as a current limitation |

Deliberately kept as a headline limitation rather than omitted. It is the reason
the selective-recompilation speedup must always be reported as a downstream
figure. Root cause and the shadow remedy are in `H1-E-IDENTITY-SCALABILITY-01`.

## 12. H1-E — the first falsification arm could not separate

| | |
|---|---|
| receipt | `H1-E-IDENTITY-SCALABILITY-01/receipts/shadow-equivalence-2026-08-19.json`, arm `identifier_and_anchor_union_removed` |
| status | **FAILED (arm design)**, retained as a recorded null |

The protocol's original falsification arm returned zero divergences. Traced
rather than accepted: the weakening could not change any answer *by
construction*, because the correct candidate also shared the path root. A
weakening that cannot change the answer tests nothing, and a zero from it is not
evidence of safety.

Corrected in Amendment 1 with a second arm that empties the candidate set
entirely and does produce divergence. **The null arm is retained in the receipt
with `separates: false`** so that the record shows what was tried, not only what
worked.

## 13. A12 — blocked, and the previously recorded reason was wrong

| | |
|---|---|
| stale document | `H1-A12-01/A12_BLOCKER_SCOPING_2026-08-18.md` |
| status | **BLOCKED_INTERNAL**, reclassified twice |

The blocker was recorded as awaiting a founder licence decision. Checked against
live repository truth (`benchmark/v6/candidate-registry.yaml`), that is **no
longer accurate**: `paddleocr-vl-1.6` and `deepseek-ocr-2` are both
`license.id: Apache-2.0`, `status: approved`, `commercial_use: allowed`.

The actual blocker is runtime: both are `execution_state:
measured_partial_runtime_image_pending` with no qualified runtime image READY,
so no GPU arm can execute. Research measurement is blocked by infrastructure,
not by law.

**This reclassification does not touch production.** `promotion_eligible: false`
still governs customer traffic for both candidates, and nothing here is a
production clearance.

## 14. A12 readiness receipt overwritten by my own tooling change

| | |
|---|---|
| path | `H1-A12-01/receipts/runtime-readiness-audit-2026-08-19.json` |
| lost original sha256 | `sha256:825fd68dd2b704c6cc5cdc22eae74b36506801192a58d864477e579ff9b8d078` |
| regenerated sha256 now on that path | `sha256:56ff7b44ec86946bd30e961376ceba8a3c3403e2c900884b1915b04b26a2e8f9` |
| full record | `research/experiments/H1-A12-01/INCIDENT_RECEIPT_OVERWRITE_2026-08-19.md` |
| status | **DESTROYED — regenerated, not restored** |

An incomplete patch meant to add an `--output` argument left the write calls
pointing at the hardcoded path, so a re-run overwrote the earlier readiness
receipt while reporting that it had written elsewhere. The directory is
untracked, so git could not restore it.

The path now holds a **deterministic regeneration** whose gate state matches the
original field for field; its `generated_at` and `receipt_sha256` do not and
cannot match. That mismatch is deliberate and is the fingerprint of the
incident.

Recorded here because a rule against destroying evidence is worth nothing if a
violation of it can be tidied away. No result moved: `gpu_spend_authorized` was
false before and after, no arm ran, and `incremental_gpu_spend_usd` is 0.0.

## 15. H1-I — the ordering harness was voided by its own fidelity gate

| | |
|---|---|
| receipt | `H1-I-GATE-ORDERING-01/receipts/gate-ordering-attempt1-void-2026-08-19.json` |
| status | **VOID (fidelity gate)**, retained unedited |

The permutation harness reimplemented `_declares_structural` against the wrong
channel API and therefore **admitted S5**, a state the real gate refuses. The
protocol's fidelity gate — canonical order must reproduce the real gate's verdict
*and* its first failing step — caught it and refused to report any ordering
result.

The protocol was not amended to fit. The harness was corrected to *import* the
system helper instead of paraphrasing it, on the principle that every internal
the harness borrows is one fewer place it can diverge from what it is measuring.

## 16. H1-I — the permutation arm could not separate by construction

| | |
|---|---|
| receipt | `.../gate-ordering-attempt2-nonseparating-2026-08-19.json` |
| status | **NULL, uncitable as run**, retained |

Attempt 2 passed fidelity and returned 0 verdict divergences over 144
evaluations. Read naively that is "ordering does not matter". It was not
evidence for that: the four checks are pure functions of the candidate state, so
**no permutation could have produced a divergence whatever the truth was**.

This is the identical defect already recorded at entry 12 for the H1-E
falsification arm, found the second time by applying the rule written the first
time. Amendment 1 added a positive control — a deliberately order-dependent gate
— which diverged on 12 of 24 orders. Only then did the null become citable, and
only for the narrow proposition that the acceptance conjunction is invariant to
evaluation order. Amendment 2 later had to narrow even that: the first wording
said the checks were "mutually independent", which the permutation study could
not have shown, and a static audit found the coupling that refutes it.

**Consequence: claim B1 element 7 was narrowed**, per a rule frozen before the
experiment ran.

## 17. H1-L — the exactness harness was VOID twice before it could anything

| | |
|---|---|
| receipt | `H1-L-CERTIFIED-SPARSE-MATCHER-01/receipts/exactness-attempt1-void-mutant-2026-08-19.json` |
| status | **VOID (mutant did not separate)**, retained |

The runner-up mutant separated on zero cases. Correcting the mutant did not help.
The real cause was the frozen corpus: it omitted `source_lineage`, so every pair
abstained on a missing critical signal and **no row ever reached MATCHED, the
review band, or the tie guard**. Two of three facets were unfalsifiable by
construction.

Recorded as a **protocol deviation**: the corpus was repaired and two
band-covering cases added after results were seen, which the protocol's stop rule
forbids. Divergences were 0 before and after the repair. Disclosed in
`AMENDMENT_1_2026-08-19.md` rather than absorbed.

## 18. H1-L — exact sparse acceleration failed on speed, and that is the result

| | |
|---|---|
| receipt | `.../exactness-2026-08-19.json` |
| status | **FAILED (objective)**, matcher itself exact |

`CERTIFIED_SPARSE` preserves the full LEGACY contract with 0 divergences over 50
comparisons and three separating mutants. It runs at **0.35–0.48x** the dense
baseline and performs *more* scoring work, not less.

Structural, not an optimisation defect: preserving the runner-up requires
retaining `min(M, N+1)` candidates per row, and `N+1 > M` for square windows.

**Not proposed for promotion.** Exact sparse acceleration remains unresolved, and
the binding facet is now identified.

## 19. W6 — a safe resume cannot be built without breaking the freeze

| | |
|---|---|
| receipt | `H1-W6-SAME-INTELLIGENCE-01/receipts/acquisition-resume-audit-2026-08-19.json` |
| status | **RESUME_UNSAFE_AS_IMPLEMENTED** |

The acquisition script overwrites unconditionally, writes non-atomically, keeps
no checkpoint and leaves undefined state after an exception. Adding skip-on-exists
would require editing the script whose sha256 the frozen title manifest pins —
and which the script self-checks.

Immutability and recoverability are not free together. Chosen: a fresh
`corpus-v6` under the same frozen manifest, with `corpus-v5`'s single pair
retained as failed-run evidence and **not** copied forward.


---

## 20. W6 — two acquisitions failed, and the recorded cause was wrong both times

| | |
|---|---|
| receipt | `H1-W6-SAME-INTELLIGENCE-01/receipts/v6-acquisition-failure-diagnosis-2026-08-19.json` |
| refines | `.../receipts/acquisition-resume-audit-2026-08-19.json` (not edited) |
| status | **FAILED — cause corrected, defect located in the invocation** |

Both the v5 and v6 acquisitions ended with one pair directory holding
`before.wikitext` and `after.wikitext`, no `metadata.json`, and no completion
sidecar. The first was recorded as a worker that died mid-run. The second
reproduced the signature byte for byte — identical sha256 on both files — and
raised `ValueError` at `acquire_w6_v3.py:376`, computing
`before_path.relative_to(EXP)` where `EXP` is absolute and `--corpus` had been
passed repository-relative. It raises on the first eligible page, after both
files are written and before the metadata.

The cause was therefore a deterministic defect, not an interruption, and it was
at the **call site** rather than in the sealed bytes: a probe using the sealed
module's own `page_dir` and `EXP` shows an absolute `--corpus` succeeds. The
freeze did not have to be broken to recover, and was not.

Retained as evidence, not repaired: `corpus-v5` and `corpus-v6` both stay on
disk, the earlier audit receipt is unedited, and the frozen script keeps its
latent precondition — it requires an absolute `--corpus` and neither resolves nor
validates one. That precondition is now documented rather than silently fixed,
because fixing it would break the manifest's hash pin for a defect that does not
live there.

**What the second failure bought.** About five and a half hours of rate-limited
fetching, and the traceback that the first failure was diagnosed without.

---

## 21. H1-IP-HARDENING-01 — the receipt generator has never run in its current form

| | |
|---|---|
| script | `research/experiments/H1-IP-HARDENING-01/build_receipt.py` |
| receipt | `.../receipts/implementation.json` (2026-08-16), **retained, not regenerated** |
| status | **GENERATOR BROKEN — receipt not regenerable** |

The script carried JSON literals (`true`, `false`) where Python literals belong
and raised `NameError` before writing. The receipt on disk lacks the
`a12_primary_input_discovery` block the script builds, so it was produced by an
earlier version of the generator.

Fixed in two parts: the literals, and a refusal to overwrite an existing receipt
without an explicit `--force`. The second is the durable one — a runnable script
here would have destroyed the artifact, which is precisely entry 14.

**The receipt was not regenerated.** Superseding a measured 2026-08-16 artifact
with output from changed code needs a recorded decision, not a side effect.

---

## 22. W6 — the acquisition that failed three times, and what the third failure was worth

| | |
|---|---|
| receipt | `.../receipts/acquisition-v7-2026-08-19.json` |
| integrity | `.../receipts/v7-corpus-integrity-2026-08-19.json` — **11/11 gates PASS** |
| status | **ACQUISITION COMPLETE. ENDPOINT STILL NOT RUN.** |

Three acquisitions: v5 and v6 both died on the first eligible page at the same
deterministic `relative_to()` defect, and v7 completed — 391 eligible pages, 293
revision-sensitive attributes across 151 articles, 2,522 controls, zero
incomplete directories.

**What made v7 possible was the second failure, not the third attempt.** v5 was
diagnosed without a traceback as a dying worker; v6 reproduced the signature
byte-for-byte and produced one. The repair was a call-site argument, not a code
change, and the sealed script's hash pin never moved.

**Entries 19 and 20 stand.** The corpora from both failures are retained, both
receipts are unedited, and the earlier resume audit is refined by a superseding
receipt rather than corrected in place.

**The endpoint is still NOT RUN, and the distinction matters.** A verified corpus
is a precondition. No question set has been built, no leakage threshold measured,
no arm executed. What changed is that the blocker is now the work rather than
the data.
