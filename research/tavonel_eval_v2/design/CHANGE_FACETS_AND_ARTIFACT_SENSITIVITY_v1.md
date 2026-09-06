# Change facets and artifact sensitivity — design v1

Written in response to `INC-V2-002`. This document specifies a mechanism; it
does not modify P0 v1, whose protocol and implementation stay frozen with their
failure intact. The mechanism is validated in P0b and nowhere earlier.

---

## 1. What went wrong, stated as a mechanism rather than a bug

A selective compiler decides what to rebuild by comparing two revisions. The
comparison runs at some resolution. Every derived artifact reads its inputs at
some resolution. When an artifact reads at a finer resolution than the
comparison runs at, the gap between the two is a window in which a real change
exists, the comparison cannot see it, and the artifact is carried forward while
a full rebuild would produce different bytes.

In P0 v1 the comparison ran at `normalize_text_for_identity` resolution, which
casefolds. The `section:` artifact stored raw text. A real `w` → `W` edit landed
in the gap.

Two obvious repairs were both rejected by the founder, and both deserve to be:

- **Normalise every artifact payload.** Closes the window by destroying
  information. Case and punctuation stop existing in any derived artifact, which
  is unacceptable for a quotation, an obligation, an identifier or a citation.
- **Invalidate on any raw-byte difference.** Closes the window by discarding the
  selectivity that is the point of the system. A whitespace reflow would rebuild
  a document's every summary.

Both treat resolution as a single global setting. It is not one setting. It is
two, and they belong to different things.

---

## 2. The separation

**Identity normalisation** answers *is this the same unit as before*. It should
be coarse. Case, whitespace and punctuation drift do not make a paragraph a
different paragraph, and a resolver that thinks they do splits histories.

**Invalidation fidelity** answers *is what this artifact read still the same*.
It cannot be one setting at all, because different artifacts read different
things. An artifact that stores a verbatim quotation is sensitive to case. An
artifact that stores a topic label is not. Forcing both to one fidelity is what
produced the false choice above.

So: keep identity coarse, and make invalidation **per-artifact**, decided by
what the artifact actually read.

---

## 3. Change facets

A source change is decomposed into facets. A facet is a deterministic
projection from a unit to a comparable value; two revisions differ *in a facet*
when that facet's projections differ.

| facet | projection | example difference |
|---|---|---|
| `SEMANTIC` | identity-normalised text | a sentence is rewritten |
| `LEXICAL` | raw text, Unicode-normalised to NFC and nothing else | `w` → `W`; a comma added |
| `STRUCTURAL` | explicit path, heading tree, reading order | two sections swap places |
| `LOCATOR` | page, region, span anchor | the same text moves to another page |
| `TEMPORAL` | validity and knowledge times | an effective date is corrected |
| `METADATA` | document metadata fingerprint | a title is corrected |
| `AUTHORITY` | issuing authority, applicability scope | a policy is reissued by another body |
| `VISUAL` | rendering fingerprint | a table is restyled |

`LEXICAL` is the facet P0 v1 had no name for. It is deliberately not called
"raw" or "byte": it is a projection like any other, and the point is that it
sits *beside* `SEMANTIC` rather than replacing it.

The facet set is open. An implementation that adds one adds a projection and a
column; it does not change the traversal.

### Facet ordering is a lattice, not a scale

`SEMANTIC` difference implies `LEXICAL` difference; the converse does not hold.
That containment is worth stating because it is the only reason a
`SEMANTIC`-sensitive artifact can safely ignore a `LEXICAL`-only change: if the
meaning had changed, the semantic facet would have said so.

---

## 4. Artifact sensitivity is observed, not declared

The obvious design has each artifact declare the facets it depends on. That
design fails the same way P0 v1 failed, one level up: a hand-written
declaration can be wrong, and a wrong declaration is silent.

So the builder does not declare. It is **watched**.

A unit is handed to a builder wrapped in a recording view. Every accessor on
that view is bound to a facet, and reading it records the facet:

| accessor | records |
|---|---|
| `.text` | `LEXICAL` |
| `.semantic_text` | `SEMANTIC` |
| `.explicit_path`, `.ordinal`, `.heading` | `STRUCTURAL` |
| `.page`, `.region` | `LOCATOR` |
| `.valid_from`, `.known_at` | `TEMPORAL` |
| `.authority`, `.applicability` | `AUTHORITY` |

The artifact's sensitivity is the set of facets its builder actually touched
while producing the payload. A builder that reads `.text` is `LEXICAL`-sensitive
whether or not anyone remembered to say so, and a builder that reads only
`.semantic_text` is not — also whether or not anyone remembered.

This is the difference between a declaration and a measurement. It is the same
discipline this programme applies to its own claims.

### Input fingerprint

For artifact `A` with observed sensitivity `F(A)` over input units `U(A)`:

    fingerprint(A) = sha256( canonical([
        {"unit": u, "facet": f, "value": project(f, u)}
        for u in sorted(U(A)) for f in sorted(F(A))
    ]) )

It is stored with the artifact. The carry-forward rule becomes one line:

> An artifact may be carried forward exactly when its input fingerprint is
> unchanged.

This is stronger than a traversal, because it does not depend on the traversal
being right. The traversal decides what to *look at*; the fingerprint decides
what may be *kept*. Where they disagree, the fingerprint wins and the
disagreement is recorded — a traversal that would have carried an artifact whose
fingerprint moved is a traversal defect, and it is now visible instead of silent.

---

## 5. Typed invalidation over facets

A dependency edge carries the facets it transmits. An edge is traversed when the
change facts on its source share at least one facet with the edge:

    traverse(edge) iff facets(change on edge.target) ∩ edge.facets ≠ ∅

The worked case from `INC-V2-002`, with the case-only edit:

    unit u changed: {LEXICAL}          (SEMANTIC projection unchanged)

    section:u          edge facets {LEXICAL, SEMANTIC}  → traversed → REBUILT
    semantic-summary:u edge facets {SEMANTIC}           → not traversed → CARRIED
    document-index:doc edge facets {STRUCTURAL}         → not traversed → CARRIED
    structure-map:doc  edge facets {STRUCTURAL}         → not traversed → CARRIED

One artifact rebuilds. Under global normalisation none would have, and the
escape would recur. Under global raw-byte invalidation all four would, and the
selectivity would be gone.

Edge facets are not hand-written either: they are the observed sensitivity of
the edge's source artifact, so §4 and §5 cannot drift apart.

---

## 6. Fail-closed, where it belongs

Three states, and only the first permits carrying forward:

| state | meaning |
|---|---|
| `CURRENT` | the input fingerprint recomputed and is unchanged |
| `STALE` | the fingerprint changed, or the traversal reached the artifact |
| `UNVERIFIABLE` | the artifact has no recorded sensitivity, or a facet projection could not be computed |

`UNVERIFIABLE` is not `CURRENT` and is not `STALE`. It is a refusal: the system
cannot say whether the artifact is current, so it may not be published as
current. An artifact built before sensitivity recording existed is
`UNVERIFIABLE` on its first pass and becomes verifiable once rebuilt — a
migration cost paid once, visibly, rather than a silent assumption that legacy
artifacts are fine.

---

## 7. What this costs

- **A wider fingerprint.** One digest per artifact over `|U(A)| × |F(A)|`
  projections. Linear in what the artifact already reads.
- **Projection cost.** Each facet must be computed for each changed unit. The
  cheap facets dominate; `SEMANTIC` was already being computed.
- **More rebuilds than a semantic-only differ.** A `LEXICAL`-sensitive artifact
  now rebuilds on edits that carry no meaning. That is the correct answer for an
  artifact that stores raw text, and it is confined to those artifacts rather
  than applied to all of them.
- **A recording view on the builder input.** The intrusive part. A builder that
  bypasses the view — reading the underlying dict directly — records nothing and
  its artifact is `UNVERIFIABLE`, which is the right failure but only if the
  bypass is detectable. P0b detects it by asserting a non-empty sensitivity set
  for every artifact it builds.

---

## 8. What is not claimed

No performance, precision or correctness result is asserted here. Nothing in
this document has been measured. It is a design, and the only evidence that will
exist for it is whatever P0b produces after its protocol is frozen.

In particular it is **not** claimed that this eliminates the class of failure
`INC-V2-002` belongs to. It closes the gap between comparison resolution and
payload resolution for facets that have a projection. A change that no facet
projects remains invisible, and the honest statement of the residual risk is:
the facet set is a declaration about what kinds of difference matter, and that
declaration can still be incomplete. What changes is that incompleteness is now
a property of a short, reviewable list rather than an emergent property of an
accidental mismatch between two functions written years apart.
