# Compatibility contract — structural-channel seeding in selective recompilation

Rung 1 of the Protected Core replacement ladder
(`compatibility contract → shadow → benchmark → canary → rollout`).
`akc_cir.semantic_diff` and `akc_cir.recompilation` are Protected Core, so the
legacy path stays authoritative until a benchmark says the new one is not worse.

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

---

## 1. The defect this exists to close

A structure-only change leaves a stale artifact behind and the run reports
success. Reproduced without a network call in
`scripts/reproduce_structure_only_stale.py`, and observed on the real corpus in
`receipts/wikipedia-real-revision-confirmatory-v1.json`: one pair non-equivalent,
`stale_left_behind = 2`, `all_confirmatory_pairs_equivalent = False`.

The mechanism, exactly:

1. `_structural_changes` builds every `STRUCTURE_CHANGED` **without** a
   `logical_id` — correctly, because a block-count or heading-tree change is not
   a property of any one unit.
2. `SemanticDiff.changed_logical_ids` keeps only changes that carry a
   `logical_id`, so the structural channel contributes nothing.
3. `plan_recompilation` seeds `graph.impact_of` with that empty set and
   traverses `DependencyChannel.SEMANTIC` only.
4. An artifact aggregated over document position — a table of contents, a
   reading-order projection, a topic bucket — is reached by nothing, is
   classified `CURRENT`, and is carried over while a full rebuild would have
   produced different bytes.

**This fails open.** The repository rule is fail closed on integrity violations,
and `recompilation.py`'s own docstring says an `UNRESOLVED` artifact must not
silently become `CURRENT`. A structurally stale artifact silently becomes
`CURRENT` today.

## 1a. The hypothesis in section 1 was wrong, and measurement is what caught it

**Kept above as written, because the correction is the point.** Section 1 says
the structural channel is what left the two artifacts stale on the confirmatory
corpus. It is not. Checking the failing pair instead of trusting the account:

| observation | value |
|---|---|
| `Self-driving car`, block count | **69 → 69, unchanged** |
| structural change actually present | heading tree only |
| shared units whose text changed | **0** |
| units present only before / only after | 1 / 1 |
| artifacts whose bytes genuinely differ | 5 of 75 |

No artifact in this adapter's graph depends on heading structure, so the
structural channel cannot be what made those artifacts diverge.

**The real defect is in the unsettled-identity path.** When the resolver returns
`AMBIGUOUS`, `diff_documents` records `logical_id=None` with the *prior*
candidates and returns — so the **incoming** unit appears in no change at all,
neither there nor as `UNIT_ADDED`. `plan_recompilation` seeds its unresolved
traversal from the candidates alone, so anything derived from the incoming unit
is reached by nothing, is labelled `CURRENT`, and is carried over stale. On this
pair that is `artifact:section:wiki-unit:5a8b71…` — a unit that exists only in
the *after* revision — and the topic bucket containing it.

That is the same class of failure as section 1 described, in a different
mechanism, and the difference matters: the structural channel *appeared* to fix
it only because seeding every unit rebuilds enough to cover it. A fix that works
by rebuilding more is a mask, and it would have been published as a fix if the
failing pair had not been opened.

Both defects are real. Only one of them is the one that fired.

## 2. Why the obvious fixes are wrong

- **Give structural changes a `logical_id`.** There isn't one. Attaching an
  arbitrary unit's id would assert that the block count is a property of that
  unit, which is false, and would make the traversal start from the wrong place.
- **Mark everything stale whenever the structural channel fires.** Correct but
  it discards the entire benefit: on this corpus most changed pairs carry a
  structural change, so selective recompilation would collapse toward full
  rebuild. Correctness bought by giving up the claim is not a fix.
- **Declare a document node and require structural edges to it.** Sound in
  principle, but every existing graph would have to be re-authored, and until it
  was, the fix would appear applied while the defect stayed live. A fix whose
  failure mode is silence is the same class of error as the defect.

## 3. The change

The channel vocabulary already carries the answer. `DependencyEdge.channels`
defaults to **all** channels, so an artifact's existing `DEPENDS_ON` edges
already declare sensitivity to structural change — nothing was ever seeding a
structural traversal.

1. `SemanticDiff` gains `structural_scope`: the logical ids in scope when the
   structural channel fired, empty otherwise. A structural change is a property
   of the document, so its scope is the document's units.
2. `plan_recompilation` gains `structural_channel: bool = False`. When enabled
   and the diff carries a structural change, it runs a second traversal over
   `structural_scope` on `DependencyChannel.STRUCTURAL` and merges the result,
   with its own reason string so the plan says *why*.

An edge that genuinely does not care about structure — a pure text extract —
narrows its `channels` and stays `CURRENT`. Precision is bought back by
declaration rather than assumed by default.

## 3a. The second change, which is the one that mattered

`SemanticChange` for `IDENTITY_UNRESOLVED` now names **both sides**:
`candidates` are the prior units, `logical_id` is the incoming unit whose
identity was not settled. `plan_recompilation` seeds its unresolved traversal
from both, behind `seed_unresolved_incoming` (default **on**).

The channel stays `UNRESOLVED`, so this does not enter `changed_logical_ids`:
an unsettled identity is still not a modification. No `UNIT_ADDED` or
`UNIT_REMOVED` is emitted, so it is still not a remove-plus-add.

**One existing test had to change**, and it is worth naming rather than
absorbing: `test_an_unsettled_identity_is_not_a_remove_plus_add_either` asserted
`logical_id is None`. That assertion encoded the defect rather than the
invariant. The invariant it exists to protect — no remove-plus-add spelling — is
now asserted explicitly instead of implied.

**Compatibility note.** Recording the incoming id changes `as_record()` for
unresolved changes, and therefore `change_id` for any diff containing one. That
is a visible, intended consequence: a stored change id from before this fix will
not match a recomputed one for such a diff. Diffs with no unsettled identity are
unaffected.

## 4. What must not change

| invariant | why |
|---|---|
| default `structural_channel=False` | the legacy path stays authoritative until benchmarked |
| locator-only movement never makes a semantic artifact stale | §N15 — this is a different channel and the existing separation is load-bearing |
| `UNRESOLVED` never becomes `CURRENT` | the module's own stated rule |
| unchanged content still yields all-`CURRENT` | L0 short-circuit must keep dominating |
| `changed_logical_ids` keeps its current meaning | callers depend on it being *semantic* changes |
| two runs over the same pair produce the same plan | impact analysis that is not reproducible cannot be audited |
| no metric, threshold or identity rule moves | this is a traversal seeding fix, nothing else |

## 5. Acceptance, measured not asserted

| # | criterion |
|---|---|
| C1 | the isolated reproduction leaves **0** stale artifacts with the channel on, and still reproduces the defect with it off |
| C2 | on the confirmatory corpus, `stale_left_behind` goes to **0** and every changed pair is equivalent |
| C3 | the v2 holdout, which already passed, **still** passes — no regression |
| C4 | rebuild fraction is reported before and after; an increase is the honest price and is published, not hidden |
| C5 | every existing Protected Core test passes unchanged |
| C6 | plans are byte-identical across repeated runs |

C4 is the one to watch. This fix necessarily rebuilds more, and a version of
this work that reported only C1–C3 would be advertising the correctness and
concealing the cost.

### Measured — `receipts/recompilation-fix-benchmark-2026-08-19.json`

Four arms over the same frozen revisions, so each fix is attributable rather
than bundled.

**confirmatory-v1 — 11 pairs, 334 artifacts**

| arm | all equivalent | stale left behind | rebuilt |
|---|---|---|---|
| legacy | **False** | **2** | 18 |
| unresolved-incoming only | True | 0 | **20** |
| structural only | True | 0 | 87 |
| both | True | 0 | 87 |

**holdout-v2 — 12 pairs, 503 artifacts:** every arm identical — all equivalent,
0 stale, 17 rebuilt. Neither fix regresses the corpus that already passed.

The identity fix buys full correctness for **two additional artifact rebuilds**.
The structural channel buys the same correctness for **sixty-nine**, and buys
nothing the identity fix has not already bought. That is the evidence that it
was masking.

### The resulting defaults

| fix | default | why |
|---|---|---|
| `seed_unresolved_incoming` | **on** | strict correctness fix; +2 rebuilds of 334 on real data; benchmarked not worse on both corpora |
| `structural_channel` | **off** | the defect is real but demonstrated only synthetically; on every real pair measured it buys no correctness and rebuilds ~4x as much |

Leaving the structural channel on by default would have meant paying a
measured cost for an unmeasured benefit.

## 6. Rollout position

This contract covers rungs 1–3. **Canary and rollout are not taken here**:
enabling `structural_channel` by default changes production recompilation
behaviour, which is a founder decision under the same rule that keeps the legacy
path authoritative. What this program delivers is the evidence that decision
needs.
