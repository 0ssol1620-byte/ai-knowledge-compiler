# Native provenance: replacing search with construction

**INTERNAL DRAFT — NOT FOR RELEASE.** IP gate CLOSED. No arXiv, no public
repository, no dataset, no demo. Every numbered claim below is bound to a row
of `paper/CLAIM_MATRIX.yaml` and through it to a sealed receipt.

**Every positive provenance claim in this section is PROVISIONAL until the
fresh held-out study (`SOURCE_FACT_IR_HELDOUT_V2`, successor to
`SOURCE_FACT_IR_HELDOUT_V1`) returns a verdict.** No sentence below asserts
that the mechanism it describes has been shown to work on held-out data. What
is asserted is narrower and already true today: what the mechanism is, why it
replaces the thing that failed, and what a PASS or a FAIL on the fresh study
would each mean. §4 is where the verdict goes, and it is written so a FAIL
requires no rewriting above it.

## 1. Why searching was a category error, not a tuning problem

`SOURCE_FACT_IR_HELDOUT_V1` FAILED on one ground above the others: 1,284
`RECOGNIZED_BUT_UNREPRESENTED` facts, every one a `PROVENANCE_SPAN`, every one
carrying the same declared reason — *the unit's text could not be located in
the raw source*. The instinct that reason invites is to try harder: a fourth
location strategy, a fuzzier match, a larger search window. That instinct is
wrong, and it is wrong for a structural reason rather than a performance one.

The canonicaliser strips markup, collapses whitespace runs to single spaces,
decodes HTML entities and joins adjacent blocks with a separator the source
never contained. By the time a unit's canonical text exists, it is generally
not a substring of anything in the raw payload — not because the search is
weak, but because the bytes that would make it a substring were deliberately
discarded on the way to producing it. Searching harder against that text does
not find more correct spans. It finds more *confident* spans, some of which
are wrong, and a provenance span that is wrong is worse than one that is
absent: the absent one is visible as a gap, and the wrong one looks like
evidence.

This is why the fix is not a better `_locate`. Widening the location
strategies on the corpus that produced the 1,284 would be fitting an
instrument to its own result — the same discipline this programme applied
everywhere else (§8.4.2 of the internal draft makes the same refusal for the
same reason) — and it would still be searching. The category error is
attempting to recover, after the fact, information that the transformation
already had and did not keep.

## 2. The span-map, built by construction

The repair keeps the information instead of discarding it. `source_fact_ir/spanmap.py`
gives the canonicaliser a ledger — `TrackedText` — that it writes into at the
moment it still knows which source bytes it is reading. Every character
emitted into canonical text is recorded as one of three things:

- **`copy`** — emitted verbatim from an exact source byte range.
- **`replace`** — emitted *instead of* a source byte range (entity decoding,
  whitespace collapsing, typographic folding). The output text differs from
  the input bytes; the byte range behind it is exact anyway, which is what
  makes normalisation survivable without becoming untraceable.
- **`insert`** — emitted from nothing. See §3.

The result, `SpanMap`, answers one question in log time: given a range of
canonical output, what raw source byte range produced it? It never answers
that question by re-reading the canonical text and going looking for a match.
The answer was recorded when the text was written, not reconstructed
afterward. `SpanMap.to_source` is honest about the one case where the
question has no answer: a region backed entirely by `insert` segments returns
`None` rather than the span of a neighbouring segment. A neighbour's span is
close by construction and wrong by fact, and this design refuses to return it.

`SpanMap.compose` extends the same discipline through a multi-stage pipeline.
When canonicalisation runs raw bytes through more than one transformation, each
stage's map is chained through the one before it, so a final canonical offset
still resolves all the way back to raw source bytes — never to an
intermediate stage's offsets, which would be a span into text that does not
exist in the artifact anyone can check against.

## 3. `insert` is the only unsourced path, and that is deliberate

`TrackedText` has no `write(text)` method that omits a source. Emitting text
without one requires calling `insert` by name, and the name says what is
happening: this text came from nothing in the source. The only legitimate use
is a separator introduced when two blocks are joined — a newline or a space
the canonicaliser adds between them, which the source genuinely never
contained at that position.

This is a narrow door on purpose. A canonicaliser that could silently emit
unsourced text through the same call it uses for everything else would
reintroduce exactly the failure this module exists to prevent: text with no
way to say where it came from, indistinguishable at the API level from text
that does. Naming the unsourced path, and only the unsourced path, `insert`
means every other call site in a canonicaliser is asserting — by which method
it called — that what it emitted has a source. `verify()` checks the
assertion holds: every `copy` segment's claimed bytes must actually decode to
the text it claims, every segment's source range must fall inside the payload,
and every character of output must be covered by some segment. A gap that
nothing accounts for is a bug in the canonicaliser, not a limitation of the
map, and `verify()` reports it as one.

## 4. What the fresh held-out study must show

A span-map that exists and passes `verify()` on fixtures is a claim about the
mechanism, not about what it does on real, held-out documents at scale. The
mechanism is judged the same way the design it replaces was judged: by a
protocol frozen before its cohort exists, scored once, and reported however it
comes out.

For a PASS to mean what it should mean, at minimum:

- the count of `PROVENANCE_SPAN` facts failing for the SFH1 reason — *unit
  text could not be located in the raw source* — must be structurally
  impossible to reach, because no fact in this design is ever attributed by
  search in the first place. A fact can still be `RECOGNIZED_BUT_UNREPRESENTED`
  for a different, honestly-stated reason (an `insert`-only region, for
  instance); it cannot be so for *this* one.
- the two endpoints SFH1 reported `SKIPPED — never exercised` — selective
  path versus clean-rebuild equivalence, and confirmed stale-escape detection
  — must actually be exercised, not merely re-declared. They require rebuilding
  artifacts from raw payloads, which the span-map-backed witness makes
  checkable in a way the retrospective one did not: a witness derived by
  construction can be compared against a fresh clean rebuild's own
  construction, where a witness derived by search could only be compared
  against itself.
- the four forensically confirmed selective stale escapes, replayed through
  span-map-backed witnesses on fresh acquisition rather than the fixtures used
  to design the repair, must continue to have their stale artifact named by
  the typed delta's invalidation set. A repair that only works on the cases
  used to build it has not been shown to generalise past them.

None of the three bullets above is a result. They are the shape a PASS would
have to have, stated before the cohort that would produce one exists.

## 5. What a FAIL would mean

A FAIL is not a return to SFH1's finding. SFH1's failure was that the
*instrument* could not distinguish a fact the compiled state carried from one
the grammar merely recognised — the four-state vocabulary exists to close
exactly that gap, and closing it is a property of `source_fact_ir/ir.py`, not
of the span-map. A FAIL on the fresh study, if it comes, would mean the
span-map's *construction-time* attribution — the mechanism this section
describes — does not eliminate the retrospective-search failure mode at the
scale and diversity of a fresh cohort: perhaps a canonicalisation stage the
fixtures did not exercise still discards source bytes before `TrackedText`
sees them, or `compose` misattributes across a pipeline stage the fixtures did
not chain. Either would be a finding about where construction-time tracking
currently falls short of covering the canonicaliser, published in the same
house style as every other negative result in this programme — not repaired,
re-scored or re-run on the corpus that exposed it, and not treated as smaller
than it is because the surrounding mechanism is otherwise sound.

A FAIL also would not authorise widening what counts as `REPRESENTED`, adding
a fourth location strategy back in to close the gap, or narrowing the fresh
cohort to exclude whatever caused it. Any of those would be the same fitting
this programme has refused at every other turn, done to a different number.

## Proposed claim rows

The rows below are proposed for `paper/CLAIM_MATRIX.yaml`, ids `C-24` onward,
continuing from `C-23`. They are not applied here — `CLAIM_MATRIX.yaml` is
owned by the orchestrator's integration pass. Every row uses
`status: NOT_YET_ESTABLISHED` and `receipt: PENDING`, the pairing
`tools/build_claim_matrix.py` requires for anything unproven, because nothing
in this section has yet been measured against held-out data.

```yaml
claims:
  - id: C-24
    wording: >-
      Native span-map propagation attributes every emitted canonical
      character to either a source byte range or an explicit unsourced
      (`insert`) marker at the moment the canonicaliser writes it, so no
      character of canonical text is ever attributed to a source byte range
      by post-hoc text search.
    protocol: SOURCE_FACT_IR_HELDOUT_V2
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed:
      - the span-map's construction-time recording eliminates retrospective
        text-location as the attribution mechanism for facts it covers
      - an unsourced output region reports None rather than a neighbour's span
    forbidden:
      - source-faithful end-to-end
      - no source fact is lost
      - the compiler is correct
    limitations:
      - a claim about the mechanism as designed and fixture-tested, not about
        its behaviour on a fresh held-out corpus at scale
      - PROVISIONAL until SOURCE_FACT_IR_HELDOUT_V2 returns a verdict

  - id: C-25
    wording: >-
      On the fresh SOURCE_FACT_IR_HELDOUT_V2 cohort, the count of
      PROVENANCE_SPAN facts recognized but unrepresented for
      SOURCE_FACT_IR_HELDOUT_V1's stated reason — unit text could not be
      located in the raw source — is zero, because no fact in the span-map
      design is ever attributed by search.
    protocol: SOURCE_FACT_IR_HELDOUT_V2
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed:
      - a fact may still be RECOGNIZED_BUT_UNREPRESENTED for an insert-only
        region or another honestly stated reason
      - this row is specifically about the SFH1 failure mode, not about the
        RECOGNIZED_BUT_UNREPRESENTED state in general
    forbidden:
      - source-faithful end-to-end
      - no source fact is lost
      - SFH1 was repeated and passed
    limitations:
      - a structural prediction from the mechanism's design, not a measured
        count. The measured count is what SOURCE_FACT_IR_HELDOUT_V2 produces.
      - PROVISIONAL until SOURCE_FACT_IR_HELDOUT_V2 returns a verdict

  - id: C-26
    wording: >-
      E5 and E6 — selective-versus-clean-rebuild equivalence and confirmed
      stale-escape detection, both reported SKIPPED_NEVER_EXERCISED by
      SOURCE_FACT_IR_HELDOUT_V1 — are exercised, not merely re-declared, under
      SOURCE_FACT_IR_HELDOUT_V2, because a span-map-backed witness can be
      compared against a fresh clean rebuild's own construction rather than
      only against itself.
    protocol: SOURCE_FACT_IR_HELDOUT_V2
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed:
      - being exercised is a precondition for E5/E6 to MET or FAIL; it is not
        itself a MET verdict
    forbidden:
      - the repair passed
      - source-faithful end-to-end
    limitations:
      - exercised does not mean passed. This row asserts only that the
        endpoints stop being SKIPPED, not what verdict they reach.
      - PROVISIONAL until SOURCE_FACT_IR_HELDOUT_V2 returns a verdict

  - id: C-27
    wording: >-
      Replayed through span-map-derived witnesses built on fresh acquisition
      rather than the fixtures used to design the repair, the four
      forensically confirmed selective stale escapes continue to have their
      stale artifact named by the typed delta's invalidation set.
    protocol: SOURCE_FACT_IR_HELDOUT_V2
    receipt: PENDING
    split: held_out
    status: NOT_YET_ESTABLISHED
    allowed:
      - a favourable replay on fresh acquisition is stronger evidence than a
        replay on the fixtures the repair was designed against, and is still
        four named cases, not a denominator
    forbidden:
      - the repair works
      - stale escapes are eliminated
      - a rate, a percentage or a denominator of any kind
    limitations:
      - four named cases are not a denominator, on fresh acquisition or not
      - PROVISIONAL until SOURCE_FACT_IR_HELDOUT_V2 returns a verdict
```
