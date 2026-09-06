# Attacking PRECISE's assumption: what if the declaration is wrong?

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

Receipt: `receipts/declaration-mutation-2026-08-19.json`
(seed `20260820`, 200 cases × 5 change classes × 6 mutations × 2 fingerprint
sources = 12,000 runs). External GPU cost: **$0.00**.

---

## 1. The assumption worth attacking

`StructuralPolicy.PRECISE` buys its precision from the channel declarations, so
its correctness now rests on them being honest. Declarations are written by
adapter authors, drift as artifacts change, and until now nothing checked them.

The design question underneath is where the promotion gate gets its evidence. If
the gate asks the *declaration* whether an artifact depends on shape, then a
single under-declaration silences the traversal **and** the check that was
supposed to catch the traversal. That is not defence in depth; it is one defence
counted twice.

So the fingerprint is built from **what the builder recorded consuming**, not
from what the graph declares. The reading-order builder read the block count
because it read it, and records that regardless of what any edge claims:

| layer | source | if wrong |
|---|---|---|
| planner precision | channel declarations | over- or under-invalidation |
| promotion safety | recorded build inputs | *independent* — unaffected |

## 1a. Two corrections applied before these numbers

**Units were being mixed.** The first version of this table put artifact counts
and case counts side by side, so "1595 stale, 797 blocked" read as a 50% block
rate when the two count different things. Artifact-level and case-level metrics
are now reported separately and the safety endpoint is stated at the artifact
level, where it belongs: *does a stale artifact reach ACTIVE?*

**The generator could collide.** It could draw, for a newly created unit, text
byte-identical to an existing one -- at which point the resolver settles it as a
continuation, correctly, and the generator's label of "new" becomes unrecoverable
from the data. That produced 1 unexplained escape in the `honest` arm (seed
20260820, ambiguous #56) and 3 in the change-space sweep. Traced to root cause,
not assumed: `ku_incoming` produced no change record of any kind because its text
equalled prior `ku_1`'s. The generator was corrected to draw without replacement;
the cases were **not** removed and the seed was **not** changed.
`receipts/generator-collision-correction-2026-08-19.json` records the withdrawal.
After it, `honest` escapes are 0 and the sweep's `precise` arm is 0/4,000.

## 2. Result

Ground truth — each artifact's real hash function — is held fixed under every
mutation. Only the declaration moves.

**Fingerprint from the build record.** `esc.art` counts artifacts; every other
column counts cases except the endpoint, which counts artifacts.

| mutation | esc.art | esc.case | blocked esc.case | **stale promoted** | false refusal | promo. coverage |
|---|---|---|---|---|---|---|
| honest | 0 | 0 | 0 | **0** | 0.000 | 1.000 |
| structural declared as semantic | 200 | 200 | 200 | **0** | 0.000 | 0.800 |
| semantic declared as structural | 200 | 200 | 200 | **0** | 0.250 | 0.600 |
| channel omitted entirely | 1600 | 800 | 800 | **0** | 0.000 | 0.200 |
| over-declared as ALL *(today's default)* | 0 | 0 | 0 | **0** | 0.400 | 0.600 |
| edge missing | 600 | 600 | 600 | **0** | 0.500 | 0.200 |

Gate sensitivity to escape is **1.000 in every row** — blocked escape cases equal
escape cases throughout.

**And it is not achieving that by refusing everything.** Under `honest` the false
refusal rate is 0.000 and promotion coverage is 1.000: every clean case promotes.
The refusal rates in the broken-declaration rows are the cost of a broken graph,
and they are reported rather than netted out.

Planner staleness under under-declaration is **expected** and is not a defect
being excused: a planner told the wrong thing traverses the wrong way. What must
not happen is that stale artifact reaching an ACTIVE world state, and across all
6,000 runs it never does.

## 3. The falsification — the independence is what causes the zero

A result of "0 fail-open" is worth nothing unless something makes it non-zero.
So the same sweep runs a second arm where the fingerprint's structural payload
is supplied **only when the declaration claims a structural dependency**:

| mutation | esc.case | blocked esc.case | **stale artifacts promoted** |
|---|---|---|---|
| honest | 0 | 0 | 0 |
| **structural declared as semantic** | 200 | 0 | **200** |
| semantic declared as structural | 200 | 200 | 0 |
| **channel omitted entirely** | 800 | 600 | **200** |
| over-declared as ALL | 0 | 0 | 0 |
| **edge missing** | 600 | 400 | **200** |

Three mutations go fail-open, on exactly the cases where the declaration is the
thing that is wrong. The gate does not become *slightly* worse; on
under-declaration it drops from blocking 200 of 200 escape cases to blocking
**none of them**.

**So the zero in §2 is caused by the independence, not by the gate being
generally robust.** A version of this system that derives fingerprint coverage
from the dependency declaration has a fail-open path, and the difference is one
design decision.

## 4. What this supports as a claim

Not "typed dependency graphs enable selective rebuild" — that is old art. The
combination is:

> Typed dependency channels are used to **minimise** selective invalidation,
> while an **independent** verification of each carried-forward artifact against
> its recorded input and structure fingerprint blocks stale carry-over caused by
> a wrong dependency declaration or a missed traversal — before promotion, and
> without a full rebuild to compare against.

The two halves fail differently on purpose. The first is an optimisation and may
be wrong; the second is a safety property and does not depend on the first being
right. §3 is the evidence that they are actually independent rather than
nominally so.

## 5. What this does not show

- **Generated cases.** Real declaration errors may cluster differently. This
  says the mechanism holds across the mutation classes, not how often adapter
  authors make each mistake.
- **Six mutation classes, not all of them.** Stale declarations that were once
  right, partial edge sets and cross-artifact dependencies are not covered here.
- **Nothing about cost.** `over_declared_all` rebuilds 4,436 against a need of
  1,595 and is perfectly safe. Safety and cost are separate axes and the safe
  arm is the expensive one.
- **B-EQUIV is not closed by this.** This is a B-SAFETY result under adversarial
  declarations. Equivalence in the default planner path is still open.
- **A new trust assumption was created, not eliminated.** Safety now rests on the
  build record being a complete and accurate account of what the builder
  consumed. Nothing here tests a *corrupted or incomplete build record*, and
  until that is attacked, "independent of the declaration" is the correct claim
  and "independent of everything" is not. That is the next mutation sweep.
