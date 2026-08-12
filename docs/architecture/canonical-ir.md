# Stable identity

Implements masterplan §9. The constraint it states is not stylistic:

> Temporal + incremental compilation은 Stable ID가 없으면 성립하지 않는다.

Before this, the repository derived none of these ids. `document_version_id` was
threaded through sixty files as an input the caller supplied, and `logical_id`
did not exist. Everything §13–§16 describes — valid time, dependency edges,
impact traversal, selective recompile — needs to answer *is this the same thing
as before*, and none of it can without this layer.

`packages/cir-python/src/akc_cir/identity.py`.

## The three derived ids

Pure functions. Two compiles of the same bytes produce the same id on any
machine, which is what makes a re-upload resolve to the version that already
exists instead of creating a second one.

```
source_id            = f(tenant, connector_type, native_id)
document_version_id  = f(source_id, content_sha256)
evidence_id          = f(document_version_id, page, normalized_bbox, span_hash)
```

Three details that are not obvious and matter:

**Parts are length-delimited before hashing.** Without it, tenant `ab` with
connector `c` collides with tenant `a` and connector `bc`.

**`native_id` is the connector's identifier, never the display filename.**
`warranty.pdf` renamed to `warranty_FINAL.pdf` is the same source. §8.1 forbids
reading `FINAL` in a filename as meaning, and keying identity on the name would
do exactly that.

**Boxes are quantised to two per-mille units.** Re-running the same parser on
the same page can move an edge by a unit; without quantisation that mints a new
evidence id and the evidence appears to have moved.

## Refusals

The masterplan's §8.1 forbids inventing data to fill a schema. These are the
places that rule became executable:

- Evidence needs an anchor — a bbox, a span, or both. A page number alone would
  give every unit on the page one id, and the fix is *not* to invent a box for a
  source that has no coordinates.
- A version id refuses a source id that is not one, and a digest that is not a
  lowercase `sha256:`.
- An inverted or out-of-range box is refused rather than clamped.

## Logical identity is a judgement, and says so

`LogicalIdentityResolver` decides whether a unit in a new version continues one
from the old. It scores four signals — structural path, anchor, content overlap,
neighbouring anchors — and returns one of three outcomes:

```
matched      the score cleared the merge threshold
new          nothing prior came close enough
ambiguous    it is between the two, or two candidates scored alike
```

**Ambiguous is a result, not a failure to produce one.** §9.4 says
`불확실한 경우 자동 merge 금지`, and the reason is asymmetric damage: a wrong
merge silently rewrites the history of a policy clause, and no downstream
temporal query can detect it afterwards. A missed merge shows up as a new
identity, which is visible.

Two candidates within 0.05 of each other are always refused, because picking
either one would attach the new text to an arbitrary history.

Every decision carries its per-signal scores and the sentence explaining it. A
bare "ambiguous" is indistinguishable from a bug.

## Worked example

The case the product exists for — a warranty clause changing from two years to
three:

```
path 1.00 · anchor 1.00 · content 0.83 · neighbours 1.00  → 0.95  matched
```

The clause keeps `ku_warranty` and the change becomes a diff on one identity,
which is what makes a semantic diff and an impact trace possible at all. A
wholesale rewrite under the same heading scores 0.71 and is reported ambiguous
rather than merged.

## Not yet built

This is the floor, not the building. Still absent: `valid_from` / `valid_to`,
`recorded_at`, dependency edges, semantic diff, impact traversal, incremental
recompilation. Those are masterplan PHASE 3–6 and each needs its own slice.

---

# Semantic diff

Implements masterplan §12. `packages/cir-python/src/akc_cir/semantic_diff.py`.

Turns "the bytes are different" into "the warranty clause went from two years to
three". Everything downstream reads its output: dependency traversal (§15) walks
out from the changed units, impact (§16.1) marks artifacts stale from that set,
and selective recompile rebuilds exactly it.

## Five levels, cumulative

```
L0 binary       did the bytes change at all
L1 structural   headings, block counts, table shape, figure refs
L2 evidence     which anchored regions were added, removed, moved
L3 semantic     which knowledge units changed, and how
L4 graph        entities, relationships, authority
```

Asking for L3 runs L0–L3. L0 on two identical digests is one comparison and
returns immediately, which is what makes it cheap enough to run on every ingest.

**A level below L0 never disagrees with it.** Identical bytes cannot produce a
structural or semantic change, whatever the caller passes in.

## The rule this module exists to hold

An identity the resolver could not settle is **never reported as a
modification**, and never as a remove-plus-add either.

- Calling it modified asserts a continuity nobody established.
- Calling it removed-plus-added destroys a history that may be real.

It is reported as `identity_unresolved`, carrying the candidates and the
resolver's reason. Those units do not appear in `changed_logical_ids`, because
marking artifacts stale from an identity nobody settled spreads a guess across
the dependency graph.

A test caught this being violated on the first implementation: the unresolved
path skipped the modification, but the candidates then fell through to the
removal pass and were reported as deleted — the exact spelling the rule forbids.
Candidates named in an unresolved decision are now excluded from removals too.

## Distinctions the levels are there to preserve

| situation | reported as | not |
|---|---|---|
| clause reworded, same meaning slot | `modified_claim` on one logical id | remove + add |
| clause moved to another page | `evidence_moved` | `modified_claim` |
| whitespace and casing differ | nothing | `modified_claim` |
| same shape, different words | L3 only | `structure_changed` |
| two candidates score alike | `identity_unresolved` | either of them |

## Reproducibility

`change_id` is a digest over the ordered change records. Two runs over the same
pair of versions produce the same id, because an impact analysis that cannot be
re-derived cannot be audited.

## Not yet built

The diff produces a change set. Nothing yet consumes it: dependency edges,
impact traversal and selective recompile are masterplan PHASE 4–5 and do not
exist.

---

# Dependency graph and impact (§15, §16.1)

`packages/cir-python/src/akc_cir/dependency.py`.

**Edge direction is declared, not inferred.** An edge is written the way the
sentence reads — `A DEPENDS_ON B` — but impact does not travel the way the arrow
points. A chunk that depends on a clause goes stale when the clause changes, so
staleness runs backwards along `DEPENDS_ON` and forwards along `CONSUMED_BY`.
Each type states its own direction, because getting it backwards produces a
blast radius that is confidently wrong.

```
DERIVED_FROM · DEPENDS_ON            upstream    (target changes → source stale)
SUPPORTS · CONSUMED_BY · EXPORTS_TO
INVALIDATES                          downstream  (source changes → target stale)
REFERENCES · SUPERSEDES              inert       (never propagates)
```

`REFERENCES` is inert on purpose: a document mentioning another does not become
wrong when the other changes, and treating a mention as a dependence makes every
blast radius the size of the corpus. `SUPERSEDES` records history.

**Every affected node carries the path that reached it.** Marking an artifact
stale is a bill for compute and a claim that someone's answer was wrong, so the
report shows `clause 4.2 [DEPENDS_ON] → chunk 88 [CONSUMED_BY] → workflow 3`
rather than a number. Breadth-first, so the recorded path is the shortest one.

Cycles terminate and are reported — a graph with a dependence loop cannot be
recompiled in any order, and that is worth surfacing rather than hanging on.
Edges carry `valid_from` / `valid_to`, so an edge retired last month does not
propagate staleness in a query about today.

# Incremental recompilation (§16)

`packages/cir-python/src/akc_cir/recompilation.py`.

Three states, and the middle one carries the weight:

```
STALE       a change reached it
UNRESOLVED  a change may have reached it, but identity was not settled
CURRENT     nothing reached it
```

**UNRESOLVED never silently becomes CURRENT.** The diff declined to settle an
identity; skipping the artifact would turn that honest refusal into a claim that
it is still valid. Unresolved artifacts are rebuilt — they may not need it, and
rebuilding one costs compute, but not rebuilding one that did need it ships a
stale answer. The asymmetry decides.

`verify_equivalence` is §44 PHASE 5's exit criterion made executable: the union
of what a selective run rebuilt and what it carried over must equal a full
rebuild, artifact for artifact and hash for hash. The failure it exists to catch
is the quiet one — an artifact the plan called current whose content a full
rebuild would have changed. That is a corpus that looks compiled and is wrong,
and nothing downstream sees it. A test drops one edge from the graph and asserts
the check fails rather than passing.

# Temporal model (§13)

`packages/cir-python/src/akc_cir/temporal.py`.

Two clocks, because two questions that look identical are not:

```
what was the policy on 3 January?              valid time
what did the AI believe it was on 3 January?   system time
```

A policy backdated to January but recorded in March is correct under the first
and absent under the second. An agent that answered in February was not wrong —
it answered from what was recorded then. Collapsing the axes makes a stale answer
indistinguishable from a dishonest one.

**§8.1 governs what may be stored.** A fact whose validity the document never
stated carries `temporal_source=UNKNOWN`, and an as-of query will not silently
treat unknown as always-true. `TemporalPolicy` makes the caller choose, and the
answer records which policy produced it and which facts it affected — the same
shape as the claims pack's rule that every rate carries its denominator.

`contradictions()` implements §17.1's temporal-contradiction category: two facts
for one logical id whose validity windows overlap and whose values differ. Two
*undated* facts are missing dates, not a contradiction, and a retracted fact does
not contradict its replacement.

`replay_context` is §19's input reconstruction, pinning both axes to one moment.
§19 is explicit that this reconstructs the input context and never claims to
reconstruct a model's reasoning.

# The four composed

`tests/unit/test_knowledge_cicd_pipeline.py` asserts the seams, not just the
layers. A worked change — warranty two years to three:

```
identity     one clause id, stable across both versions
diff         one modified_claim, no remove-plus-add
impact       2 rag chunks, 1 export, 1 agent workflow
plan         rebuild 4 of 6, 33% of the work avoided
equivalence  selective result == full rebuild, nothing stale left behind
temporal     Feb reads "two years", Jun reads "three years", no contradiction
```

Dropping one edge from the graph makes the equivalence check fail, which is the
test that the check is doing anything.
