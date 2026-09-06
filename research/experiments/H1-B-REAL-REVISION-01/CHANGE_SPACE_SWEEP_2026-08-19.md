# Sweeping the change space, and the gate defect it found

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Receipt: `receipts/change-space-sweep-2026-08-19.json`
(seed `20260819`, 400 cases × 5 change classes × 2 arms = 4,000 runs).
External GPU cost: **$0.00**.

---

## 1. Why a sweep, when three real corpora already agreed

Because they agreed for a reason that turned out not to be about the mechanism.

The untouched extension holdout — frozen before acquisition, never scored, and
therefore the strongest anti-post-hoc-fitting evidence available — passed with
every arm identical: 5 pairs, 140 artifacts, 9 rebuilt, 0 stale. That is a real
result and it stands. But *identical arms* means the defect never fired there.
**A corpus that cannot trigger a defect cannot confirm its fix.** Reporting it
as confirmation would have been the more comfortable reading and the wrong one.

The corpora answer "does this work on documents we have". They cannot answer
"does this work on changes we have not seen", which is what a post-hoc-fitting
objection actually asks. So this sweeps the change space instead of the corpus.
Each generated pair's change class is known *by construction*, and ground truth
is a full rebuild computed independently of the plan, so both error directions
are visible: a missed rebuild is a stale artifact escaping, an extra rebuild is
wasted work that an equivalence check alone cannot see.

## 2. Result

Default arm (`structural_channel=False`, the shipped default):

| class | cases | equivalent | stale escaped | rebuilt | needed | false invalidations | gate blocked |
|---|---|---|---|---|---|---|---|
| unchanged | 400 | 400 | 0 | 0 | 0 | 0 | 0 |
| semantic_only | 400 | 400 | 0 | 798 | 399 | 399 | 0 |
| **structural_only** | 400 | **0** | **400** | 0 | 400 | 0 | **400** |
| mixed | 400 | 395 | 5 | 790 | 795 | 0 | 5 |
| ambiguous | 400 | 397 | 3 | 2073 | 1600 | 476 | 3 |
| | | | **408 escaped** | | | | **0 permitted** |

With `structural_channel=True`: structural_only 400/400 equivalent, mixed
400/400, total stale escaped 3, gate permitted 0.

## 2a. Two claims, and only one of them is closed

The default arm's numbers prove a safety property and **do not** prove an
equivalence property. Reading the table as "selective recompilation equals a
full rebuild across the change space" inverts what it says: in the default path
the planner broke equivalence on **400 of 400** structural-only changes. What
held is that none of them reached an ACTIVE world state.

| claim | question | verdict |
|---|---|---|
| **B-SAFETY** | when equivalence breaks, does a fail-closed gate stop the stale CURRENT artifact from being promoted? | **strongly supported**, change-space validated: 408 escapes, 408 blocked, 0 permitted |
| **B-EQUIV** | is selective recompilation itself artifact-for-artifact equivalent to a full rebuild? | **partial / adapter-conditional**. Holds for unchanged, semantic-only and mixed; the structural class is **unresolved in the default path** |

"Family B closed" is therefore accurate only as **Family B safety boundary
closed**. The equivalence claim is not closed and is not written as if it were.

## 3. What this overturns

**The real-corpus finding was corpus-specific, not a property of the mechanism.**
`SELECTIVE_RECOMPILATION_EQUIVALENCE_2026-08-19.md` recorded that the structural
channel bought no measured correctness at an 80.5% false-invalidation cost, and
kept it default-off on that basis. That measurement is not withdrawn — it is
still what those corpora show. What is withdrawn is any reading of it as
"structural propagation is unnecessary". With the channel off, **every single
structural-only change left a stale artifact.**

The two are consistent, and the reconciliation is the finding: the v3 adapter
has no artifact whose bytes depend on document shape. There was nothing for a
structural change to invalidate, so the channel had nothing to buy. The sweep
includes a reading-order artifact — deliberately, and declared before running —
which is what makes the class testable at all.

**So the default-off decision is conditional on the adapter, not on the
mechanism, and must be re-derived for any adapter that adds a shape-dependent
artifact.** Stated that way it is a fact about a corpus. Stated the other way it
would have been a false claim about a system.

The claim this licenses is bounded: **structural propagation is necessary for
shape-dependent artifacts.** It does **not** license "production workloads
commonly require it" or "enabling it is globally cost-effective" -- the first
needs a real distribution and the second is contradicted by the 80.5% false
invalidation the corpora measured. The right target is not a global default but
**precise structural invalidation**: propagate on the structural channel exactly
when the graph contains a shape-dependent artifact and the diff carries a
structural change.

## 4. The gate defect

Worse, and found only here: **the promotion gate passed 400 of 400 structural
escapes.** Its fingerprint covered each artifact's declared inputs and their
content hashes — and a structural-only change is precisely the change that
leaves every unit's content byte-identical. The check matched every time, on the
one thing that had not moved. An integrity check blind to an entire change class
is not a conservative check; it is a check that reports success.

Two changes close it:

1. `artifact_input_fingerprint` takes a `structural` payload — block count,
   reading order, whatever shape facts the artifact consumed — hashed separately
   from unit content.
2. The gate **refuses** any CURRENT artifact that declares a `STRUCTURAL`
   dependency edge and is not named in `structural_coverage`. A caller who
   forgets is failed closed, not believed. Inferring coverage from a fingerprint
   would be impossible: it looks the same either way.

After both, the default arm blocks all 408 escapes and permits **zero**, and the
structural arm permits zero. Fail-closed holds across all 4,000 runs.

The migration cost is real and is not hidden: `DependencyEdge.channels` defaults
to every channel, so most existing artifacts now require an explicit structural
declaration before the gate will trust their fingerprint. That is strictness the
defect earned.

## 5. The 3 residual escapes are a generator artifact, not a defect

In 3 of 400 `ambiguous` cases the generator drew a sentence for the incoming
unit byte-identical to an existing one, so the resolver correctly settled the
incoming unit onto that prior — making the sweep's separately-keyed artifact for
it a phantom that never should have existed. The system behaved correctly; the
model of it did not. The gate blocked all 3 anyway.

This is recorded rather than removed. Regenerating until the number is zero is
choosing the data to suit the answer.

## 6. What this is not

Generated documents. This says nothing about real change distributions — the
corpora do that, and their limitations are recorded in their own result
document. It says the mechanism is correct across change classes the corpora
happen not to contain, which is exactly what a corpus cannot say. Neither result
substitutes for the other, and a claim resting on only one of them is weaker
than it looks.

No compute or latency figure appears here. Artifact counts are not compute, and
no rebuild was executed.

---

## 7. Precise structural invalidation — the blunt choice was a false one

Receipt: `receipts/precise-structural-2026-08-19.json`.

The choice looked like: leave structural propagation off and accept staleness,
or turn it on and pay 80.5% false invalidation. Both are unacceptable and the
dilemma was an artifact of how the graph was declared.

`DependencyEdge.channels` defaults to `ALL_DEPENDENCY_CHANNELS`. The v3 adapter
declares nothing, so **every artifact asserts that it depends on document
shape** — and none of them do. Each v3 artifact hashes `sorted(logical_ids)`
plus normalised unit text; neither reordering nor a block-count change can reach
its bytes. The traversal was already channel-filtered. The cost was the
declaration, not the propagation.

`StructuralPolicy.PRECISE` activates structural propagation exactly when the
graph declares a shape-dependent artifact **and** the diff carries a structural
change. Measured on the same frozen pairs, with channels declared honestly:

| confirmatory-v1 (11 pairs, 334 artifacts) | equivalent | stale | rebuilt | needed | false invalidation |
|---|---|---|---|---|---|
| legacy (off) | True | 0 | 20 | 17 | 0.150 |
| always (on, undeclared channels) | True | 0 | 87 | 17 | **0.805** |
| **precise (declared channels)** | True | **0** | **20** | 17 | **0.150** |

holdout-v2 is identical across all three arms (17 rebuilt, 0 stale, 0.0 false
invalidation), and on the change-space sweep `precise` matches `always` exactly
— 400/400 structural-only equivalent — because there the graph really does
contain a shape-dependent artifact.

So precise invalidation gets the safety of `always` at the cost of `legacy`.

**What this does not show.** That production graphs are mostly semantic. This
adapter's artifacts genuinely are, which is why declaring them honestly costs
nothing here; a graph with real shape-dependent artifacts will pay for them, and
should. `PRECISE` is only as precise as the declarations — against an adapter
that declares nothing it degenerates to `always`, which is a property of the
adapter, not a fault in the policy. The default remains `LEGACY` so no existing
caller changes behaviour; promotion follows the ladder.
