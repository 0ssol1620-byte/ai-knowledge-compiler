# Compatibility contract — identity uncertainty quarantine (INC-V2-047)

Rung 1 of the Protected Core ladder for the INC-V2-047 repair. Written before
the ladder's later rungs run, because the point of a contract is to say what
"not worse" will mean before anyone knows which answer is convenient. INC-V2-042
records what this programme costs when that order is reversed.

**Status: the production default is OFF.** `semantic_diff
.QUARANTINE_UNSETTLED_IDENTITY_DEFAULT` is `False`. Flipping it is rung 5 and a
separate, receipted act.

---

## The defect

`diff_documents` withheld from definite classification exactly the units an
AMBIGUOUS resolver decision *named*:

    unsettled.update(decision.candidates)

That is not the set such a decision makes unsafe. `logical_id` is a pure
function of source id and explicit path, so a restructured section carries the
**same logical id on both sides** with different text. The resolver scores the
incoming unit against a *different* before-side unit, lands in the review band,
and returns AMBIGUOUS naming that other unit. The before-side unit sharing the
incoming's own id is implicated by the identical unsettled question, is named by
nobody, and fell through to the removal loop as `UNIT_REMOVED` — a definite
deletion asserted about a unit whose identity the resolver had explicitly
declined to settle.

`IDENTITY_CHANGE_MIGRATION_CLOSURE_V1` found nine such cases across eight
lineages. They occur identically under the legacy and the migrated change
predicate, so **this is not a migration regression**; it is an older fail-closed
defect that a sufficiently rigorous prospective closure surfaced. V1's FAIL is
permanent and is never repaired, rescored, or reused as a positive denominator.

---

## What the repair must do

Stated as obligations, so a later reading cannot soften them into preferences.

1. **Quarantine the whole neighbourhood, not the named part of it.** For each
   AMBIGUOUS/UNRESOLVED decision: every declared candidate; the selected
   candidate if any; the exact logical-id counterpart when a before-side unit
   carries that id; and transitively any before-side unit a *definite* decision
   matched to an already-quarantined member.

2. **No quarantined member receives a concrete identity-sensitive outcome.**
   Not `UNIT_ADDED`, not `UNIT_REMOVED`, not `MODIFIED_CLAIM`. The guard is
   asked before every one of those exits, not before some of them.

3. **Withholding is not enough — the uncertainty must be STATED.** A unit that
   vanishes from the diff has had a false statement replaced by no statement,
   and a fail-closed endpoint cannot score an absence. Every otherwise-invisible
   quarantined member gets an explicit `IDENTITY_UNRESOLVED` record reachable
   through `SemanticDiff.unresolved`, and therefore observable by SFI3's E7.

4. **State only what is otherwise invisible.** A declared candidate is already
   named inside the incoming unit's unresolved record; giving it a second record
   of its own adds nothing and breaks the property that one unsettled decision
   produces one unresolved record.

5. **An unsettled identity is still not a modification.** These records stay on
   the `UNRESOLVED` channel and never enter `changed_logical_ids`.

## What the repair must not disturb

- genuine removals, genuine additions, and clear one-to-one matches;
- identity normalisation semantics — `normalize_text_for_identity` is not
  touched and must not become content-sensitive;
- the facet-based change predicate from INC-V2-037;
- `legacy_identity_change_predicate=True` as the pinned reference path;
- unrelated units: over-quarantine is its own defect, converting real changes
  into unresolved and destroying the diff's usefulness.

## Not-worse, defined before measuring

No threshold. No number in this repository is calibrated, and a rate bar
invented here would present an uncalibrated number as a measured one. The
comparison is by property:

| property | required |
|---|---|
| units gaining a *definite* outcome they lacked before | **zero** — the repair only ever withholds |
| units vanishing from the diff entirely under the pin | **zero** — that is silent disappearance |
| Protected Core consumer suite (`tests/unit`) | no regression, pin ON vs OFF |
| pin OFF | reproduces V1's finding exactly: 9 cases, 8 lineages |
| the nine V1 cases, pin ON | all close — as **development** regressions only |

The nine V1 cases may be used during development. They may **not** certify the
repair prospectively; that is what `IDENTITY_CHANGE_MIGRATION_CLOSURE_V2` is
for, on a universe disjoint from V1's.

---

## The ladder

    1. compatibility contract        this document
    2. shadow / differential         pin OFF vs pin ON over the cached corpus
    3. adversarial / property        ten controls, each proven able to go red
    4. canary                        properties, not thresholds
    5. production switch             flip the default — separate and receipted

## Reference path

`quarantine_unsettled_identity=False` (and the module default while it is
`False`) restores the pre-repair behaviour exactly, by building an **empty**
quarantine rather than by keeping a second code path that could drift from the
one it stands in for. Verified in both directions: OFF reproduces V1's 18
rows / 9 cases / 8 lineages; ON yields zero INVARIANT_6 violations with all
eight invariants MET.

## Known limits

- The transitive clause (4) is applied to fixpoint although one pass suffices
  for today's resolver, where a definite match names exactly one counterpart. A
  guard whose correctness rested on that unstated property would be the shape of
  defect this file exists to close.
- The 514-pair development corpus is spent as prospective closure evidence and
  is development/forensic material only after this repair.
- Nothing here has been independently re-run by another context.
