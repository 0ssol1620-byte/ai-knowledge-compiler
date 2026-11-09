# ADR-007: Bound contradiction candidates by group, not by pair

- Status: **Proposed** (design only; no code in this change)
- Date: 2026-11-05
- Scope: `akc_product_core.semantics.compile_semantics` (contradiction grouping),
  `akc_product_core.compiler` (VALIDATION_RECORD objects, review reasons, package files),
  Foundation `core-runtime-v2.ts` contradiction projection
- Changes digests: **yes** — `artifactHashes`, `manifestDigest`, `worldStateId`, candidate key

## Context

`compile_semantics` groups claims by `(topic_key, temporal_refs)` and compares **every pair**
inside a group (`semantics.py`, the `for left … for right in group[left_index + 1 :]` loop).
A pair whose numeric values differ, or whose polarity differs, becomes one
`ContradictionCandidate`. Nothing bounds the number of pairs and nothing summarises a group.

Each pair is then written several times into the package: a VALIDATION_RECORD object in
`canonical/model.json`, its JSON-LD node, `graph/nodes.csv` and `relationships.csv` rows, two
TTL link lines, a `semantics/contradictions.jsonl` row, a `CONTRADICTION_CANDIDATE:<id>`
review reason, and a `contradicts` edge on the Foundation side. Measured on the deployed
compiler with synthetic input (not a production job): about **5.6 KB per pair** in the
Foundation candidate.

`topic_key` keeps the first 12 tokens after removing dates and numbers, so rows that differ
only by a number ("○○ 금액은 N원이다") all fall into one group. Measured on synthetic input:

| claims in one group | pairs | candidate |
|---|---|---|
| 30 (unit-test fixture `_fragmented_document`) | 435 | 2.7 MB package for 32 regions |
| 206 | 21,114 | 127 MB |
| 512 | 130,816 | 695 MB, 91 s Core CPU |

A 12-page scan that failed with `JSON_TOO_LARGE` (134.6 MB candidate) fits this shape, but
**which amplifier fired on that job was not observed**; the refusal log of F0 is what will
tell. F0 (`CORE_OUTPUT_TOO_LARGE`) now refuses such an output by name; this ADR is about not
producing it.

## Decision (proposed)

Represent contradictions **per group, by value class**, and derive pairs instead of storing them.

For each `(topic_key, temporal_refs)` group with at least one disagreeing pair:

1. Partition the group's claims into **value classes** keyed by
   `(numeric_values, polarity)`. Claims in one class are mutually consistent under the current
   rule.
2. Emit one `ContradictionGroup` record:
   `{groupId, topicKey, temporalRefs, classes: [{classKey, claimIds[], representativeClaimId}],
   rule: "numeric_or_polarity.v1"}`.
3. The pair set is **derivable**: for every two classes, apply today's rule to their keys
   (both numeric and different → `numeric_disagreement`; else polarity different →
   `polarity_disagreement`; else none). Every claim in class A pairs with every claim in class
   B under that verdict. This reproduces today's pair set exactly; it is an encoding change,
   not a semantic change.
4. **Stored cost is O(claims) per group, and only because nothing pair-shaped is stored.**
   Classes are *not* reliably few: the motivating shape, a repeated row with a different
   number each time, is one class per claim (the unit-test fixture: 30 claims, 30 classes).
   So classes² is the pair count again, and it is paid only at read time.

   **Compatibility contract: pairs are never expanded into stored rows.** Not in the package
   (no per-pair VALIDATION_RECORD, JSON-LD node, CSV row, TTL link or JSONL row), not in
   review reasons, and not on the Foundation side: Foundation `contradicts` edges are derived
   **per class** (one edge from the group to each class representative), never per pair. A
   reader that needs a pair (a review drill-down, an export) derives it on request from the
   group record and the rule in step 3, and does not persist it. Breaking this moves the
   quadratic cost from Core to Foundation instead of removing it.
5. One review reason per group, `CONTRADICTION_GROUP:<groupId>`, instead of one per pair. The
   reviewer adjudicates a group (pick the authoritative class), not N² pairs.

Rejected: **a per-group pair cap with `CONTRADICTION_GROUP_TRUNCATED`**. It is not silent, but
it drops pairs, so recall falls and the benchmark must then argue quality instead of proving
equivalence. Kept only as a fallback if class counts turn out to be unbounded on real corpora.

Out of scope, and deliberately separate: whether `topic_key` (12 tokens) and the CJK
predicate rule (`…다` line ending) are the right claim/grouping rules. Those are precision
questions that need a gold set; mixing them into this change would make the benchmark a
quality comparison instead of an equivalence check.

## Consequences

- Memory, alongside this ADR: the Core idempotency cache (`api.py`) is capped at 8 entries /
  256 MiB of **serialised** bytes. The resident pydantic objects measured 1.75× serialised
  (18.4 MB → 32.1 MB, tracemalloc), so the cap is about 450 MB resident. The cap stays; fewer
  stored contradiction rows shrink each entry and so raise the effective entry count.
- `semantics/contradictions.jsonl` rows, VALIDATION_RECORD objects and their JSON-LD / CSV /
  TTL projections change shape → `artifactHashes`, `manifestDigest`, `worldStateId` change for
  every World that has a contradiction. Its next compile is a rebuild, not a carry-over.
- Foundation's projection rejects a contradiction whose links are not exactly two
  (`core-runtime-v2.ts:536-557`); it must accept the group shape. Its per-contradiction
  `reviewReasons.includes(...)` (O(C²), `:548`) becomes a Set lookup in the same change,
  and its `contradicts` edges become one per class, per the step-4 contract.
- Review UI and `/api/v1/reviews` label a group, not a pair.
- Response schema: the candidate gains a new record kind → bump the semantics record version
  (`numeric_or_polarity.v1` above) and keep the reader dual-shape until legacy Worlds are gone.

## Ladder (the change does not ship without each step)

1. **Compatibility contract.** A pure function `expand(groups) -> pairs`. Property test: for
   any claim set, `expand(group_encode(claims)) == legacy_pairs(claims)` (ids, reasons,
   temporal refs). Foundation reader accepts both shapes. No output change yet.
2. **Shadow.** Core computes both encodings, ships the legacy one, and records in the receipt
   (internal only): `groups`, `classes`, `legacyPairs`, `expandedPairsEqual`, and the byte
   size each encoding would add. Digests unchanged in this step.
3. **Benchmark (same condition).** Corpus: the GDP sample used for the density figures plus the
   12-page scan document named in the internal receipt, rebuilt from its OCR output. Pass
   criteria, all required:
   `expandedPairsEqual` on 100 % of documents; candidate bytes and Core wall time not worse on
   any document; review items per document reported (expected to fall); stored rows per
   group linear in claims (the step-4 contract). An internal benchmark receipt binds each
   number to its artifact hash.
4. **Canary.** Flag on one internal workspace. Watch: compile success, `CORE_OUTPUT_TOO_LARGE`
   rate, review completion, Foundation projection errors.
5. **Rollout**, then **deprecate** the legacy pair encoding once no active World carries it.

F0 stays as the backstop throughout: whatever this ADR does, a package over budget is refused
by name, never truncated.

## Addendum 2026-11-09: the fallback is taken, as an interim bound

The condition this ADR kept the rejected cap for has been observed. The D0 production proof
(a 12-page scan, `CORE_OUTPUT_TOO_LARGE`) is the motivating shape exactly: 216 claims in one
group, **216 value classes**, 23,220 pairs, 168.8 MB of Core response on the current compiler.
Class encoding would store O(claims) but every reader that expands it pays the 23,220 pairs
again, and Foundation needs a new contradiction shape before it can read one. So the cap ships
first, as a fail-closed bound, and the group encoding above stays the proposed target.

What shipped (`semantics.py`, IMPLEMENTED_NOT_PROVEN, uncalibrated):

- `MAX_CONTRADICTION_PAIRS_PER_GROUP = 496` (C(32, 2)). The largest group any existing fixture
  forms is 30 claims / 435 pairs, so every existing output is byte-identical.
- `MAX_CONTRADICTION_PAIRS_PER_COMPILE = 1,024`, groups admitted smallest first. Measured at
  the bound: 1,020 pairs = 8.8 MB of response, about a quarter of the 32 MiB budget.
- A group past either bound emits **no** pair and is named in review:
  `CONTRADICTION_GROUP_TOO_LARGE:<groupId>:claims=<n>:pairs=<m>` or
  `CONTRADICTION_PAIR_BUDGET_EXCEEDED:<groupId>:claims=<n>:pairs=<m>`. The pair count is the
  exact count the pairwise rule would have produced, computed in O(n).
- `corpus_reduce` recomputes both reasons over the union, like the candidates.

The cost is the one this ADR named: recall falls for a group past the bound. On the D0 input
those pairs were false positives (line, page and range numbers are identifiers, not
measurements), but recall on real corpora is unmeasured; there is no gold set. Excluding
enumerator-like numbers is a separate precision rule and is not in this change: it would move
existing golden outputs (the `_fragmented_document` fixture is that shape), so it needs its own
benchmark.
