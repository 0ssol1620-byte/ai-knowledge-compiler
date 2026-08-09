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
