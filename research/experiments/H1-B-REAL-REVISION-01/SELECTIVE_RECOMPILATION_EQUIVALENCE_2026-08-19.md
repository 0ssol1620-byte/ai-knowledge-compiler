# Selective recompilation equals full rebuild — two fail-open defects, found and closed

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

The claim this program exists to test is the one incremental recompilation lives
or dies on: **the artifacts a selective rebuild produces are the artifacts a full
rebuild would have produced.** If that fails, the corpus looks compiled and is
quietly wrong, and nothing downstream can tell.

It was failing.

---

## 1. Where it stood

| corpus | pairs | result |
|---|---|---|
| holdout v2 | 12 | all equivalent, 0 stale, 17 of 503 rebuilt |
| **confirmatory v1** | 11 | **not equivalent — 2 artifacts carried over stale** |

The confirmatory run failed its own pre-registered success gate
(`confirmatory_zero_stale_left_behind: false`). A prior session diagnosed a root
cause and stopped there, correctly, because `akc_cir.semantic_diff` and
`akc_cir.recompilation` are Protected Core and a change goes through
`compatibility contract → shadow → benchmark → canary → rollout`.

That diagnosis was **wrong about which defect fired**, and the way it was wrong
is the more useful result.

## 2. Two defects, one symptom

**D2 — a structural change cannot seed a traversal.** `_structural_changes`
builds every `STRUCTURE_CHANGED` without a `logical_id`, correctly, because a
block count is not a property of any one unit. But `changed_logical_ids` keeps
only changes carrying one, so the structural channel contributes nothing to the
seed set and an artifact aggregated over document position is carried over.

**D1 — an unsettled identity names only one side.** When the resolver returns
`AMBIGUOUS`, the diff records `logical_id=None` with the *prior* candidates and
returns — so the **incoming** unit appears in no change at all, not even as
`UNIT_ADDED`. `plan_recompilation` seeds from the candidates alone, so anything
derived from the incoming unit is reached by nothing and is labelled `CURRENT`.

Both are real. Both fail open. The prior diagnosis attributed the confirmatory
failure to D2. Opening the failing pair shows otherwise:

| `Self-driving car`, revisions 1359295324 → 1359295913 | |
|---|---|
| block count | **69 → 69, unchanged** |
| structural change present | heading tree only |
| shared units whose text changed | **0** |
| units only in before / only in after | 1 / 1 |
| artifacts whose bytes genuinely differ | 5 of 75 |

No artifact in that graph depends on heading structure. The carried-over
artifacts belong to `wiki-unit:5a8b71…` — **a unit that exists only in the after
revision**. That is D1, not D2.

## 3. Why the wrong fix passed every acceptance criterion

D2's fix was written first and it *did* make the corpus pass: all pairs
equivalent, stale count zero, no regression on the holdout. Every criterion
green.

It passed by rebuilding enough to cover the artifact D1 had missed.

| arm, confirmatory-v1 (11 pairs, 334 artifacts) | equivalent | stale | rebuilt |
|---|---|---|---|
| legacy | **False** | **2** | 18 |
| D1 only — seed the incoming unit | True | 0 | **20** |
| D2 only — structural channel | True | 0 | 87 |
| both | True | 0 | 87 |

D1 buys full correctness for **two** additional artifact rebuilds. D2 buys the
same correctness for **sixty-nine**, and buys nothing D1 has not already bought.

Holdout v2 is unmoved by either arm — all four are identical at 17 of 503.

### Both error directions, measured

Equivalence only constrains one of the two ways a dirty set can be wrong. An
artifact rebuilt unnecessarily is invisible to it, because rebuilding produces
the same bytes either way. Counting an artifact as *genuinely changed* when its
full-rebuild bytes differ from its previous bytes gives both directions:

| corpus / arm | rebuilt | genuinely changed | falsely invalidated | FI rate | stale escapes |
|---|---|---|---|---|---|
| holdout-v2, every arm | 17 | 17 | **0** | **0.000** | 0 |
| confirmatory, legacy | 18 | 17 | 3 | 0.167 | **2** |
| confirmatory, **D1** | 20 | 17 | 3 | **0.150** | **0** |
| confirmatory, structural | 87 | 17 | **70** | **0.805** | 0 |

On holdout v2 the dirty set is **exactly** the changed set — no misses and no
waste. On the confirmatory corpus the D1 fix reaches zero escapes at three
unnecessary rebuilds.

The structural channel's **80.5% false-invalidation rate** is the quantitative
form of "it was masking": four rebuilds in five were work that produced
identical bytes.

**The single-arm acceptance suite was green and wrong.** A fix that works by
widening the dirty set is indistinguishable from a real fix if the only question
asked is whether the failure went away. That is why the benchmark is four-armed
and why the two seeding paths are pinned by separate tests, each against a case
only it can solve.

## 4. What shipped, and what did not

| fix | default | reasoning |
|---|---|---|
| `seed_unresolved_incoming` | **on** | strict correctness fix; +2 rebuilds of 334 on real data; not worse on either corpus |
| `structural_channel` | **off** | the defect is real but shown only synthetically; on every real pair measured it buys no correctness and rebuilds ~4× as much |

Turning the structural channel on by default would mean paying a measured cost
for an unmeasured benefit. It stays available, documented, and off.

**One existing test changed.** `test_an_unsettled_identity_is_not_a_remove_plus_add_either`
asserted `logical_id is None` — an assertion that encoded the defect rather than
the invariant. The invariant it protects, that an unsettled identity is never
spelled as remove-plus-add, is now asserted explicitly.

**Compatibility note:** recording the incoming id changes `change_id` for any
diff containing an unsettled identity. Diffs without one are unaffected.

## 5. What the claim may now say

**Supported:** on 23 public revision pairs across two independently frozen
corpora, selective recompilation produced artifacts identical to a full rebuild,
with **zero stale artifacts carried over**, rebuilding 37 of 837 artifacts of
which 34 had genuinely changed — a false-invalidation rate of **8.1%** and a
stale-escape rate of **0/34**.

**Not supported, and not to be implied:**

- *Any percentage as a general rebuild-reduction figure.* 4.4% here is a
  property of these documents, this adapter's artifact graph and this change
  distribution. Wikipedia edits are small; a corpus of large structural
  revisions would look nothing like it.
- *Compute or latency reduction.* Artifact count is not compute. Nothing here
  measured either, and the receipt records `external_gpu_cost_usd: 0.0` because
  no rebuild was actually executed — hashes were compared.
- *Production behaviour.* This is an offline adapter over frozen text, not the
  persistence, world-state and publish path.
- *Domain performance.* Wikipedia is revision data, not evidence about legal or
  regulatory documents.

## 6. What is still missing, stated plainly

1. **The false-invalidation rate now exists but is small-sample.** 3 of 37, on
   two corpora, one adapter. It is a measurement, not a calibrated property.
2. **Stale-escape rate has a denominator of 34 changed artifacts across 23
   pairs.** Zero out of 34 is consistent with a real rate of several percent;
   the binomial upper bound alone is around 10%.
3. **D2 has no natural corpus.** It needs artifacts that genuinely aggregate
   over document position; this adapter has none, which is exactly why D2 never
   fired.
4. **Compute and latency remain unmeasured**, and the reduction claim cannot be
   made in those terms until they are.

## 7. Ladder position

Rungs 1–3 are complete: compatibility contract, shadow implementation behind
flags, benchmark on two frozen corpora. **Canary and rollout are not taken
here** — changing production recompilation defaults is a founder decision, and
what this program delivers is the evidence that decision needs.

---

## Correction, same day — the default-off conclusion was over-generalised

Added after `CHANGE_SPACE_SWEEP_2026-08-19.md`, which contradicts one reading of
this document and must be recorded here rather than only there.

Everything measured above stands: on these corpora the structural channel bought
no correctness and cost 80.5% false invalidation, and default-off is the right
setting **for this adapter**. What does not stand is the inference that
structural propagation is unnecessary in general. A sweep across the change
space found that with the channel off, **400 of 400 structural-only changes left
a stale artifact**.

Both are true because the v3 adapter has no artifact whose bytes depend on
document shape — so there was nothing for a structural change to invalidate.
That is a fact about a corpus, not about the mechanism, and the default must be
re-derived for any adapter that adds a shape-dependent artifact.

The sweep also found that the promotion gate itself passed every one of those
400 escapes: its fingerprint covered unit content, which is the one thing a
structural change does not touch. That defect is fixed and pinned by regression
tests; see the sweep document, §4.
