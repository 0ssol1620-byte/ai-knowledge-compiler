# Ledger entry `ABS-B-01` — result block, appended

> **NOT CLEARED FOR EXTERNAL DISCLOSURE.** Gate 6 is BLOCKED: no design-around
> review has been recorded for external language, and the prior-art baseline arm
> was implemented without §15.3 role separation. Internal and exploratory use
> only. See `clean-room-provenance.json` for what must happen before any number
> here appears in a paper, a patent specification's comparative evidence, the
> public Evidence page, or an external presentation.

*Deliverable for the IP track, to be **appended** to §7.2 of
`docs/ip/INVENTION_DISCLOSURE_B.md`. §0.6: appended after results, never
overwritten. Nothing in `ledger-ABS-B-01-opened.md` is edited by this file, and
`why_changed` in particular stands exactly as it was written.*

Every number below is read from `research/experiments/EXP-0101/metrics/` and is
bound by sha256 in `receipts/receipts.json`. None was typed from memory.

## Canonical finding

The rule, in the form adopted as canonical — three questions, kept apart:

> **Alignment asks which elements correspond.**
> **Identity asks whether this is still the same logical thing.**
> **Diff asks what changed about it.**
>
> **Content may be used at the alignment stage for candidate pairing. It must
> not enter the logical identity score.**

As first recorded, and preserved:

> **Content compatibility must not participate in logical identity resolution.**

A logical claim's wording changing is *normal* — it is the ordinary case, which
is why `identity.py:183` excludes content from the identity seed in the first
place. So if content change itself severs identity, the changes that matter most
are exactly the ones pushed below the merge bar, and they land in
`IDENTITY_UNRESOLVED` where `semantic_diff.py:195` correctly excludes them from
`changed_logical_ids`. The abstention is right; its input was wrong. **The
system does not say the wrong thing — it says nothing, about the thing it most
needed to say.** The evidence is critical numeric recall **0/60**.

**Typed element reasoning is retained as a valid challenger capability.** That
half is independent of the identity integration that failed, and it is the
source of every gain measured here.

Machine-readable at `receipts/canonical-finding.json`; successor contract at
`docs/research/ABSORPTION_EXPERIMENT_CONTRACT_A2.md`.

---

## `result_status`

**`worse`** on the primary metric, with a mechanism identified and isolated.

The challenger as specified — five alignment signals into the seven-signal
scorer, 30% share — **regresses critical semantic change recall from 1.0000 to
0.7500** and **misses every injected numeric mutation (recall 0.0000, n = 60)**.
It is not promoted. It is not close to promotable.

## `measured_effect`

`n` = 660 document pairs: 60 seeded documents crossed with all eleven mutation
classes. Every arm is deterministic; no model is called anywhere.

| metric | CURRENT | BASELINE | CHALLENGER | CHALLENGER −content |
|---|---|---|---|---|
| Semantic-change recall | 1.0000 | 1.0000 | **0.6667** | 0.8333 |
| Critical change recall | 1.0000 | 1.0000 | **0.7500** | 1.0000 |
| Critical numeric recall | 1.0000 | 1.0000 | **0.0000** | 1.0000 |
| Layout-only false positive | 0.0708 | 0.1042 | **0.0000** | 0.0292 |
| Layout-only false **invalidation** | 0.7500 | **0.1042** | 0.7292 | 0.6042 |
| Alignment F1 | 0.9759 | **1.0000** | 0.9728 | 0.9735 |
| Identity false merge | 0.0004 | 0.0000 | 0.0000 | 0.0012 |
| Identity false split | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
| Selective/full equivalence | 1.0000 | **0.9470** | 1.0000 | 1.0000 |
| Mean rebuild fraction | 1.0000 | **0.0800** | 1.0000 | 1.0000 |

## `ci_and_denominator`

95% percentile bootstrap, 10,000 resamples, fixed seed, paired at document-pair
level. Denominators: critical recall over 240 high-risk cases; semantic recall
over 360 meaning-changing cases; layout rates over 240 pure-layout cases;
equivalence over all 660.

| metric | CURRENT | CHALLENGER | CHALLENGER −content |
|---|---|---|---|
| Critical change recall | [1.0000, 1.0000] | [0.6958, 0.8042] | [1.0000, 1.0000] |
| Semantic-change recall | [1.0000, 1.0000] | [0.6167, 0.7139] | [0.7944, 0.8722] |
| Layout-only false invalidation | [0.6958, 0.8042] | [0.6708, 0.7833] | [0.5417, 0.6667] |
| Selective/full equivalence | [1.0000, 1.0000] | [1.0000, 1.0000] | [1.0000, 1.0000] |

Exact two-sided McNemar against CURRENT, Holm-Bonferroni across every arm × slice:

| comparison | arm better | CURRENT better | p (Holm) |
|---|---|---|---|
| `challenger::critical_detection` | 0 | 60 | 2.602e-17 |
| `challenger::semantic_judgement` | 17 | 120 | 4.494e-19 |
| `challenger::layout_false_positive` | 17 | 0 | 1.678e-04 |
| `challenger::layout_false_invalidation` | 5 | 0 | **4.375e-01** |
| `challenger_no_content::critical_detection` | 0 | 0 | 1.000 |
| `challenger_no_content::semantic_judgement` | 16 | 66 | 2.702e-07 |
| `challenger_no_content::layout_false_invalidation` | 35 | 0 | **7.567e-10** |
| `challenger_no_type_reasoning::layout_false_invalidation` | 0 | 0 | 1.000 |
| `baseline::layout_false_invalidation` | 155 | 0 | **8.758e-46** |
| `baseline::semantic_judgement` | 17 | 25 | 1.000 |

## What the numbers mean, including the parts that flatter nobody

**1. The predicted failure mode happened, and it is worse than predicted.**
`expected_technical_effect` named the risk: a content-derived signal inside an
identity score can push a real content edit below the 0.92 bar. It does, on
every numeric mutation. A single changed cell drops a pair from 0.9412 to
0.9006, and the resolver correctly abstains at 0.9006. The change is not lost —
`critical_change_surfaced_rate` is 1.0000, because the mutated unit is named in
the abstention's candidate list — but it is **not reported as a change**, and
anything reading `changed_logical_ids` never sees it.

Removing that one signal restores critical recall to 1.0000 with the rest of the
layer intact. The regression is `align_content` and nothing else.

**This is a finding about design, not about tuning.** `identity.py:183` says
content is deliberately excluded from the identity seed *"so that a clause keeps
its identity when its wording changes -- which is the entire point."* Contract A
says to feed §9.3's signals in as additional signals, and §9.3's signal list
includes Content. Following both produces a scorer that is less stable across
content change than the one it extends. **Content compatibility is a diff
signal. It must not be an identity signal.** A revised Contract A should feed
type, spatial, structural and context into identity and route content
compatibility to the type-specific reasoning stage, where it already works.

**1b. The other half of the challenger delivers a capability CURRENT does not
have at all.** `critical_change_labelled_rate` is **0.0000 for CURRENT** and
1.0000 for the `−content` variant, over 240 high-risk cases. CURRENT can say a
claim was modified; it cannot say the modification was a modal verb, an
exception clause, an effective date or a figure, because
`semantic_diff.py:422` has one label for all of them. Type-specific reasoning
supplies that and it is independent of the identity integration that failed. It
is the part of Contract A worth keeping.

**2. The layout-only gain does not survive the metric that decides cost.** The
false-positive rate falls from 0.0708 to 0.0000 and that is significant
(Holm p = 1.678e-04). But a false positive and an abstention both end in a
rebuild, and on the combined false-invalidation rate the challenger scores
0.7292 against CURRENT's 0.7500 — **5 discordant cases in its favour, 0 against,
Holm-adjusted p = 0.4375. Not significant.** **The challenger converts false
positives into abstentions.** It does not learn that a moved element did not
change; it becomes less sure that it is the same element.

The same test says where the real gain is. `−content` scores 0.6042 on 35
discordant cases in its favour and 0 against, Holm p = 7.567e-10, and the
`−type-reasoning` ablation scores exactly CURRENT's 0.7500 with **zero**
discordant cases. So the entire layout gain comes from the type-specific
reasoning, and `align_content` was cancelling most of it: on the
optical-degradation class alone, `−content` false-invalidation is **0.4167
against CURRENT's 1.0000**, while the full challenger manages only 0.9167.

The baseline beats every arm here — 0.1042, 155 discordant in its favour and 0
against, Holm p = 8.758e-46 — and finding 3 is the price it pays for that.

**3. The prior-art baseline wins on alignment and loses on trust, exactly as
`why_changed` predicted.** It is the only arm with perfect alignment F1
(1.0000), it rebuilds 8% of artifacts where every other arm rebuilds 100%, and
it is **the only arm that leaves a stale artifact behind**: selective/full
equivalence 0.9470, CI [0.9288, 0.9636], concentrated in the optical-degradation
class where its demotion says "nothing changed" about a unit whose bytes did.
Forced assignment plus confident demotion is cheaper and occasionally wrong in
the direction the repository refuses to be wrong in. That is the contemporaneous
prediction in `why_changed`, measured.

**4. Two of the challenger's passing gates are passing for a reason that is not
the challenger.** Selective/full equivalence 1.0000 and rebuild fraction 1.0000
are the same fact: an evidence id is derived from the document version
(`identity.py:177`), so every matched unit reports `EVIDENCE_MOVED` on every
version pair and lands in `changed_logical_ids` (`semantic_diff.py:432`).
Selective recompilation currently degenerates to a full rebuild for every arm
that goes through `akc_cir.semantic_diff`. Equivalence holds because nothing is
ever carried over. **If that were fixed, the challenger would inherit the
baseline's staleness**, because `plan_recompilation` reads the core diff and
never sees the type-specific refinement at all — the refinement changes what is
reported and not what is rebuilt.

**5. Figure replacement is the same disease under a different name.** Both
challenger arms score 0.0000 while CURRENT scores 1.0000, and Contract A did not
predict it. Investigated after the fact, it is not a second mechanism:
`align_structural` resolves a caption's figure binding and then compares **the
bound element's content hash**. It is named structural and behaves as content.

Measured over 20 seeded figure-replacement cases: all signals **0/20**; minus
`align_content` alone **0/20**; minus `align_structural` alone **0/20**; minus
**both, 20/20**. Removing either one alone recovers nothing, which is what rules
out two independent faults.

**Corollary, adopted as canonical:** a signal named `structural` or `context` is
treated as content-derived — and therefore banned from the identity stage — **if
its value is produced by reading text, a content hash, a token set, an embedding,
or any content-derived digest. The name does not matter; what it reads does.**

`align_structural` is the canonical example: reading the bound figure's content
hash produced 0/20 figure-replacement recall, and removing either signal alone
recovered nothing. Keeping "structural compatibility" in the identity stage is
therefore only safe once it is redefined to compare bindings rather than the
content of what is bound, and **the content-derivation test is applied per
signal as part of Contract A v2's definition of done.**

## `promotion_decision`

**DENIED.** Two of the nine gates fail and one is blocked.

| gate | verdict |
|---|---|
| 1 quality non-regression | **FAIL** — 0.6667 vs 1.0000 |
| 2 catastrophic failure non-regression | PASS, but see finding 4 |
| 3 latency/cost budget | PASS as a tie at 1.0000, see finding 4 |
| 4 reproducibility | **PASS** — `receipts/reproducibility.json`, every arm recomputed identically |
| 5 permission/security invariants | **N/A** — no tenant data, no connection, no permission path |
| 6 license/FTO | **BLOCKED** — clean-room evidence recorded; design-around review for external language not done |
| A-i critical semantic recall ≥ CURRENT | **FAIL** — 0.7500 vs 1.0000 |
| A-ii zero critical false merges | **PASS** — 0.0000 |
| A-iii ambiguous stays reviewable | **PASS** — false split 0.0000, every abstention carries candidates |

The `−content` variant meets A-i and A-ii, is the only challenger arm with a
significant gain on the cost metric (Holm p = 7.567e-10), and **still fails gate
1** — semantic-change recall 0.8333, because figure replacement goes to 0.0000.
It is the shape a revised Contract A should specify. It is not a promotable arm
today, and calling it one because it is the best of the challengers would be
grading on a curve.

## Note appended to this entry — `DIAG-B-01`, and what may be written about it

Finding 4 opened a registered engineering gap:
`docs/research/DIAGNOSTIC_CONTRACT_DIAG_B_01.md`. It produces an explanation,
not a fix, and it authorises no change to Protected Core. It must attribute the
full-rebuild behaviour among four candidate causes — evidence identity design ·
version-scoped evidence id · conflation of semantic identity with evidence
identity · dependency invalidation rule — before any fix is decided.

**This gates Family B §5, and the IP track is holding for it.** Three permitted
claim states, and no others:

| state | asserts | current |
|---|---|---|
| `IMPLEMENTED` | the mechanism exists in code | **yes** |
| `DEMONSTRATED` | a narrow recompilation benefit is proven | no |
| `NOT YET DEMONSTRATED` | neither shown end to end | **this is the state** |

`plan_recompilation`, `impact_of`, `verify_equivalence` and the dirty-set
machinery are `IMPLEMENTED`. Nothing measured shows they reduce work in the
assembled pipeline, and `EXP-0101` measured that on this fixture they did not —
mean rebuild fraction **1.0000** for every arm routed through
`akc_cir.semantic_diff`, against **0.0800** for the prior-art baseline.

Note the opposite error too: the finding is **not** "selective recompilation does
not work". It is "it has not been shown to work end to end, and one synthetic
measurement says it did not." Over- and under-claiming are both wrong.

**The cause is not settled and must not be written down as settled** until
`DIAG-B-01` decomposes C1–C4 by read-only counterfactual. The Family B §5
consistency pass happens after that.

## `patent_relevance`

`claim_elements_touched` **B1, B2, B3/B4** stands, and the measurement lands on
B3/B4 — the abstention chain — rather than on B1/B2.

Three contemporaneous facts, recorded without any assertion about what they read
onto, which is `docs/ip/` and counsel's question and not this file's:

1. The strongest arm on alignment accuracy (baseline, F1 1.0000) is the only one
   that produced a stale artifact (equivalence 0.9470). Alignment quality and
   trustworthy invalidation are measurably not the same axis.
2. Abstention carried information that no other outcome carried: on the
   challenger's failed critical cases, detection was 0.0000 while
   *surfacing* — the unit appearing in an abstention's candidate list — was
   1.0000. The unresolved outcome was the only thing standing between a wrong
   answer and a silent one.
3. A design that improves alignment can degrade identity stability, because the
   evidence that two elements differ is not evidence that they are different
   elements. That distinction is the substance of the abstention chain and it is
   now measured rather than argued.

**No claim-reading assertion is made here, and none should be added.** Filing
and publication timing is the founder's alone.

## `receipt_binding`

| field | value |
|---|---|
| `experiment_receipt_ref` | `research/experiments/EXP-0101/receipts/receipts.json` |
| `git_commit_sha` | in `research/experiments/EXP-0101/manifest.json` |
| `model_registry_ids` | **none** — no model is called anywhere in this experiment |
| `config_sha256` | in `manifest.json`, over weights, thresholds, shares, seeds and arms |
| `corpus_manifest_sha256` | in `manifest.json`, over the 660 generated case records |

## Limits a reader must carry with these numbers

- **The seed corpus is generated, not real.** No DART/SEC amendment pair and no
  Office→PDF export pair was used; Contract A names both and neither is built.
  External validity is correspondingly limited.
- **No embedding provider was used.** Contract A's Resources line allows one for
  the semantic signal. All content comparison here is lexical, numeric and
  structural, so the semantic ceiling is lexical and an embedding arm is
  unmeasured. Determinism was bought with that.
- **The optical-degradation class is half inside and half outside the fold
  table.** Half the documents are corrupted only in ways the type reasoning
  knows how to invert. The reported demotion rate is fold-table coverage on a
  constructed corruption, not a claim about scans.
- **`TYPO_ONLY` is a class every arm fails**, by construction: nothing here can
  distinguish a typo correction from a wording change without a lexicon, and
  none of the arms is given one.
- **The alignment share of 0.30 is uncalibrated** and was not swept. Nothing in
  this experiment calibrates the 0.92 / 0.75 bands either, so **RQ-B5 remains
  open** — though finding 1 tells it something useful: at 0.92, a single numeric
  edit inside a table row is enough to cross the bar when content is in the
  score.
- **Clean-room role separation was not achieved.** Summariser and implementer
  were one agent. `receipts/clean-room-provenance.json` records it and carries
  the founder question.
