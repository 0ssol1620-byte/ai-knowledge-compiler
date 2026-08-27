# Compatibility contract: identity/change separation (INC-V2-037)

Status: **development shadow, rung 3 of 8**. Nothing in `packages/cir-python/src/akc_cir/`
is touched by this contract or by anything it authorizes. This document and the shadow it
describes are the only things this lane is licensed to produce.

## The established root cause

`akc_cir.identity.normalize_text_for_identity` is documented, in its own docstring, as a
**lossy** fold built for exactly one job: deciding whether a unit in a new revision is the
same logical thing as a unit in an old one ("This is deliberately lossy and is only ever used
for identity, never for content" — `identity.py:87-97`).

`akc_cir.semantic_diff.diff_documents` nonetheless uses that fold's output as the *entire*
gate for reporting a matched unit as changed:

```python
if counterpart.identity_text != incoming.identity_text:
    changes.append(SemanticChange(kind=ChangeKind.MODIFIED_CLAIM, ...))
```

(`semantic_diff.py:594-604`). `_nonsemantic_dimension_changes` (`semantic_diff.py:434-470`)
separately tracks `visual_fingerprint` / `temporal_fingerprint` / `metadata_fingerprint`, but
nothing else in `diff_documents` ever looks at the unit's raw text again. A pair whose
`identity_text` values fold equal is therefore *silently* reported unchanged, with no other
gate that could catch it.

All 14 of the SFI2 confirmed selective stale escapes
(`receipts/sfi2-native-provenance--20260823T085006Z-e53cc8aaeb7d.json`,
`rebuild.E5_confirmed_selective_stale_escape.confirmed`) are this one root cause: `Apache` →
`Apache®`, `Github` → `GitHub`, a spacing/punctuation edit, a hyphen replaced by an em dash.
Replaying all 14 through `tools/forensic_sfi2_execution.py` (read-only, real production
modules, cache-only, confirmed 2026-08-23 in this checkout) shows the same shape every time:
`identity_text_equal=True`, `raw_text_differs=True`, `modified_claim_emitted=False`,
`first_divergence_stage=typed_delta` — 14/14, no exceptions. See "Differential results" below
for the per-case table.

Every one of the 14 is correctly the *same unit* under identity continuity — the resolver
must keep matching them across revisions, and this contract does not propose changing that.
Every one of them is also a real, compiled-relevant change that must not vanish from change
detection. Both things are true at once because they are answers to two different questions:

    Identity equivalence is not change equivalence.

## What is forbidden, and stays forbidden

- **`normalize_text_for_identity` is not made more sensitive.** Its insensitivity is required
  for identity continuity; sharpening it to catch these 14 cases would break unit matching
  across revisions for every case it currently gets right, in exchange for fixing 14 it
  currently gets wrong.
- **No `if old.text != new.text:` patch.** Raw-text equality over-fires on every
  formatting-only change (a re-wrap, an encoder swapping precomposed and decomposed Unicode
  for the same character) and gives no facet-level account of *what* changed — a caller who
  gets `changed` cannot tell a wording edit from a citation renumbering from a stray
  whitespace normalization.
- **The 14 SFI2 cases are development fixtures only.** They are replayed as often as this
  lane needs for diagnosis. They are never added to a certification corpus and never used to
  re-score SFI2 — SFI2 is spent, and its cohort does not widen retroactively.

## The separation

    IDENTITY : "is this the same unit?"      -> akc_cir.identity (unchanged, untouched)
    CHANGE   : "has this same unit's compiled-relevant state moved?"
               -> source_fact_ir/change_facets.py, decomposed into 9 declared facets

Matched-unit change comparison runs over the declared facet partition, each of which
resolves independently to exactly one of four verdicts:

| Facet                            | Data source in `UnitSnapshot` today                | Verdicts actually reachable |
|-----------------------------------|-----------------------------------------------------|------------------------------|
| `CONTENT`                         | `text`, NFC-normalized only                          | changed, unchanged |
| `STRUCTURAL`                      | `document_path[1:]`, `anchor`, `explicit_identifier` | changed, unchanged |
| `REFERENCE_LOCATOR`               | `evidence_id`, `page_number1`                        | changed, unchanged, unresolved |
| `TEMPORAL`                        | `temporal_fingerprint`                               | changed, unchanged, unresolved |
| `AUTHORITY_APPLICABILITY`         | `authority`                                          | changed, unchanged, unresolved, ignored_by_predeclared_policy |
| `METADATA`                        | `metadata_fingerprint`                               | changed, unchanged, unresolved |
| `VISUAL`                          | `visual_fingerprint`                                 | changed, unchanged, unresolved |
| `ACCESSIBILITY`                   | none                                                  | unresolved (always) |
| `EXTERNAL_DEPENDENCY_EXECUTION`   | none                                                  | unresolved (always) |

The four verdicts:

- **`changed`** / **`unchanged`** — both sides carried real data for this facet, and the
  facet's own projection agreed or did not.
- **`unresolved`** — no data was available to compare (a field was never populated on one or
  both sides). **Never mapped to `unchanged`.** That mapping is the exact defect class
  INC-V2-037 belongs to, one layer up: an absence read as agreement.
- **`ignored_by_predeclared_policy`** — the caller declared, in advance and by name (the
  `ignored_facets` parameter), that this facet does not apply to this comparison. The only
  case this contract currently names: `AUTHORITY_APPLICABILITY` for a source family that
  carries no jurisdiction concept at all (e.g. software documentation, as opposed to a
  regulation). This is deliberately *not* inferred from the data — an inferred "ignore" is
  indistinguishable from a bug that happens to produce two matching empty values, which is
  exactly what `unresolved` exists to catch instead.

`ACCESSIBILITY` and `EXTERNAL_DEPENDENCY_EXECUTION` are declared facets with **no data
source anywhere in `UnitSnapshot` today**. They always resolve `unresolved`. This is named
here as a real, permanent limitation of the current unit representation — not a policy
decision, so it is never reported as `ignored_by_predeclared_policy` — and it is the honest
alternative to silently dropping them from the partition, which would hide that
compiled-relevant state exists that nothing in this shadow can see.

## The risk a more sensitive predicate creates, and how the decomposition bounds it

Replacing an under-sensitive gate with an over-sensitive one is the standard way this kind of
repair goes wrong: catch the 14 missed escapes, and also start reporting every whitespace
normalization, every re-wrap, every Unicode-encoder round-trip as a change — which inflates
the selective rebuild set on every ingest, not just the 14 cases that motivated the fix.

The facet decomposition bounds this by construction, not by tuning a threshold:

- `CONTENT`'s projection is NFC normalization only — it undoes an encoder's choice between a
  precomposed codepoint and a base character plus a combining mark for the *same* visible
  text, and nothing else. It does not fold case, does not fold punctuation, does not collapse
  whitespace. A genuinely formatting-only difference (two spellings of one accented letter)
  resolves `CONTENT unchanged`; a genuinely different sequence of codepoints — `Apache` vs
  `Apache®`, hyphen vs em dash — resolves `CONTENT changed`. `tests/test_change_facets.py::
  test_pure_unicode_encoding_difference_is_not_reported_as_a_content_change` is the control
  for the first half of that claim.
- A change that moves a unit's position (`STRUCTURAL`) does not, by itself, make `CONTENT`
  fire, and vice versa — the two are independent facets, so a caller downstream can act on
  "this moved but did not reword" differently from "this reworded but did not move." All 14
  SFI2 cases are pure text edits: `STRUCTURAL unchanged` on every one (see differential
  results), which is the expected shape of a decomposition that does not conflate the two,
  not an accident of this particular cohort.
- `document_path`'s shared source-id prefix is excluded from `STRUCTURAL`'s projection by
  construction — a caller passing a different source-id string for the same document family
  would otherwise make every comparison spuriously structural.
- `neighbour_anchors` (an identity-*resolution* signal, not a property this unit owns) is
  excluded from `STRUCTURAL` for the same reason: folding a neighbouring unit's edit into
  this unit's own verdict would make "did this unit move" depend on an unrelated unit.

None of this claims the bound is *proven* against every possible corpus — see "What this
shadow does not establish" below.

## What this shadow does and does not establish

**Establishes**, with evidence pointers:

- The 14 SFI2 confirmed cases, replayed independently (not through `semantic_diff`'s own
  decision), all resolve `CONTENT=changed` under this facet decomposition.
  (`tests/test_change_facets.py::test_differential_all_fourteen_confirmed_cases_are_caught_by_content_facet`,
  passed 2026-08-23, 14/14.)
- The facet partition is closed and total: every call returns exactly the nine declared keys,
  never an undeclared key, never a missing one.
  (`test_every_call_returns_exactly_the_declared_facet_keys`, `test_change_facets` module
  `assert set(verdicts) == set(FACETS)` on every call.)
- Every declared facet is reachable — none is dead (frozen to one value regardless of input)
  except the two with no data source, which are *declared* to be permanently `unresolved`
  and tested as such.
  (`test_every_declared_facet_is_reached_by_this_suite` and the per-facet reachability tests.)
- A synthetic, hand-built identity-regression control: units with identical text still match
  (`test_identical_text_is_unchanged_the_same_unit_still_matches`), and a pure Unicode
  round-trip encoding difference (no information changed) does not fire `CONTENT`
  (`test_pure_unicode_encoding_difference_is_not_reported_as_a_content_change`).

**Does not establish:**

- **A real identity-regression corpus.** The control above is one hand-built pair, not a
  measured false-positive rate over real revision history. This lane was not able to
  construct a corpus of genuinely-same-unit pairs at scale from real data without pulling in
  net-new acquisition, which is out of scope here. Stated plainly rather than implied: **the
  over-fire risk is bounded by construction (see above), not measured on a corpus.**
- **Adversarial controls.** Named as the next rung on the ladder below; not attempted in this
  lane.
- **Any claim about what production should do with a `CONTENT changed` verdict.** This module
  is a diagnostic projection. It is not wired into `semantic_diff.diff_documents`,
  `recompilation.plan_recompilation`, or `compiler/selective_build.py`, and nothing here
  proposes that wiring. That is a later rung, gated on the differential and benchmark rungs
  below actually running.
- **Completeness of the facet set itself.** The candidate list this contract works from
  (`CONTENT`, `STRUCTURAL`, `REFERENCE_LOCATOR`, `TEMPORAL`, `AUTHORITY_APPLICABILITY`,
  `METADATA`, `ACCESSIBILITY`, `VISUAL`, `EXTERNAL_DEPENDENCY_EXECUTION`) was handed to this
  lane, not derived from a survey of every compiled-relevant dimension a unit can carry. A
  facet nobody thought of is a facet this module cannot report on, and there is no coverage
  instrument here (compare `facets/facet_coverage.py`'s `UNCLASSIFIED` mechanism in the
  separate P0b/P0c lane) that would catch that gap. Extending this module with such an
  instrument is out of scope for this rung.

## Differential results (2026-08-23, this checkout, no network)

All 14 E5-confirmed cases, replayed through `tools/forensic_sfi2_execution.py`'s real
production pipeline (for the old predicate) and independently through
`source_fact_ir/change_facets.py` (for the new one), via
`tests/test_change_facets.py::test_differential_all_fourteen_confirmed_cases_are_caught_by_content_facet`:

| lineage_id | old `identity_text_equal` | old `modified_claim_emitted` | new `CONTENT` | new `STRUCTURAL` |
|---|---|---|---|---|
| git:apache/druid:docs/api-reference/data-management-api.md | True | False | changed | unchanged |
| git:apache/druid:docs/data-management/schema-changes.md | True | False | changed | unchanged |
| git:apache/druid:docs/data-management/manual-compaction.md | True | False | changed | unchanged |
| git:apache/druid:docs/design/indexing-service.md | True | False | changed | unchanged |
| git:apache/dolphinscheduler:docs/docs/en/contribute/join/become-a-committer.md | True | False | changed | unchanged |
| ecfr:40:761:761.180 | True | False | changed | unchanged |
| git:apache/druid:docs/design/metadata-storage.md | True | False | changed | unchanged |
| git:apache/druid:docs/api-reference/legacy-metadata-api.md | True | False | changed | unchanged |
| git:apache/druid:docs/api-reference/supervisor-api.md | True | False | changed | unchanged |
| git:microsoft/playwright:docs/src/api/class-playwrightassertions.md | True | False | changed | unchanged |
| git:apache/druid:docs/design/deep-storage.md | True | False | changed | unchanged |
| ecfr:38:4:4.117 | True | False | changed | unchanged |
| ecfr:40:761:761.123 | True | False | changed | unchanged |
| ecfr:40:262:262.1 | True | False | changed | unchanged |

14/14: old predicate agreed (folded identity-equal, no `MODIFIED_CLAIM`); new `CONTENT`
facet, computed without ever reading `semantic_diff`'s answer, disagrees correctly on all 14.
0/14 show a `STRUCTURAL` change — consistent with all 14 being pure text edits, and with the
decomposition not conflating a content edit with a structural move.

## Migration ladder

1. **Compatibility contract** — this document. Done.
2. **Development shadow implementation** — `source_fact_ir/change_facets.py`. Done. Imports
   nothing from `akc_cir.semantic_diff`; does not call `diff_documents`; does not read
   `identity_text`.
3. **Old/new differential** — done, this rung, against the 14 confirmed SFI2 cases (table
   above). Real production payloads, cache-only, no network.
4. **Identity-regression benchmark** — **not done**. Requires a real corpus of genuinely-same
   -unit pairs at scale, not the single hand-built control this rung produced. Blocking rung
   for anything past here.
5. **SFI2 14 cases as development fixtures** — in effect since rung 3; reiterated as a
   standing constraint, not a one-time step: never enters a certification corpus, never
   re-scores SFI2.
6. **Adversarial controls** — **not attempted**.
7. **Canary** — not reached.
8. **Production switch** — not reached. `packages/cir-python/src/akc_cir/semantic_diff.py`
   is not modified by this contract or by anything currently authorized under it. Wiring this
   module's verdicts into `diff_documents` (or into `recompilation`/`selective_build`)
   requires rungs 4, 6 and 7 first, per the project constitution's replacement ladder
   (`compatibility contract → shadow → benchmark → canary → rollout → deprecate` — this
   contract adds the differential and adversarial-control rungs inside "benchmark" rather
   than skipping to it).

## Verify

```bash
python -m pytest tests/test_change_facets.py -q
python -m ruff check source_fact_ir/change_facets.py tests/test_change_facets.py
```

Both run clean in this checkout as of 2026-08-23 (20 passed; ruff `All checks passed!`).
