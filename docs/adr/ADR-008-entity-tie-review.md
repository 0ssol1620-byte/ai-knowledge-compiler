# ADR-008: A Context-Overlap Tie Goes to Review, Not to an Arbitrary Merge

- Status: Accepted as a fail-closed tightening; evidence status `IMPLEMENTED_NOT_PROVEN`
- Date: 2026-10-16
- Owners: Platform
- Introduced by: `5f0bca3` (PR #91, "Integrate reviewed parser and entity admission contracts")
- Pending: same-condition no-regression benchmark (Protected Core ladder)

## Context

`akc_cir.entity.resolve_mention` is tested entity logic and therefore Protected
Core. Its tier 4 resolves a mention by context overlap among same-type
candidates. Before `5f0bca3` the candidates were sorted by
`(overlap, entity_id)` descending and the first one won. When two or more
distinct entities shared the highest overlap, the tie was broken by the
lexically greatest `entity_id` and returned `AUTO_MERGE` for an ordinary type.
The merge target was an artifact of identifier spelling, not of evidence.

## Decision

1. **A tie at the highest context overlap is `REVIEW`.** When more than one
   distinct entity holds the top tier-4 score, `resolve_mention` returns
   `MergeVerdict.REVIEW`, `entity_id=None`, tier `CONTEXT_OVERLAP`, the shared
   score, and every tied candidate (sorted, deduplicated) in `candidates`. Lower
   scoring candidates are excluded.
2. **Nothing else in the resolution order moves.** A unique top score keeps
   its previous verdict (`AUTO_MERGE` for an ordinary type, `REVIEW` for a
   high-risk type). Tiers 1-3 (identifier, approved alias, composite key) still
   take precedence over a tier-4 tie. The same entity listed twice is not a tie.
3. **A `REVIEW` decision cannot execute a system merge.** `EntityRegistry.merge`
   already refuses a review decision without a named human reviewer; the tie
   inherits that.

This is a tightening, not a new capability. It follows the constitution's rule
"never auto-resolve an authoritative conflict on insufficient evidence": two
equally supported targets are insufficient evidence for either. The previous
behaviour was not wrong by its own tests; it was unguarded on a case those
tests did not pose.

## Additive Protected Core changes in the same PR

Recorded here so the Protected Core change list for PR #91 is in one place.
None changes existing behaviour for existing data:

- `akc_cir.semantic_diff.ChangeKind.PERMISSION_CHANGED` - additive enum value
  for an ACL-only change; emitted by callers that track source ACLs.
  Covered by `tests/integration/test_core_semantic_incremental_runtime.py::test_acl_only_change_is_recompiled_selectively_and_gates_the_next_ask`.
- `akc_cir.models.CanonicalCell` - optional `raw_text_verbatim`, `value_type`,
  `number_format`, `formula`. Absent keeps the contract-wide whitespace strip,
  so an existing cell's `raw_text` and content hash are unchanged. Covered by
  `tests/unit/test_k13_table_structural_fidelity.py` and
  `tests/unit/test_nonpdf_structured_parsers.py`.
- `akc_cir.ontology.OntologyStore.save` - refuses to write a manifest whose
  schema version `load()` would refuse, before touching disk. Covered by
  `tests/unit/test_ontology_additive_migration_boundary.py::test_save_refuses_an_unsupported_schema_with_a_correct_hash_before_writing`.

## Tests

`tests/unit/test_entity.py`:

- `test_k15_context_two_highest_matches_require_review`
- `test_k15_context_three_highest_matches_retain_every_candidate`
- `test_k15_context_tie_is_invariant_to_input_order_and_lexical_ids`
- `test_k15_context_tie_excludes_lower_scoring_candidates`
- `test_k15_context_unique_highest_preserves_auto_merge`
- `test_k15_context_duplicate_same_entity_is_not_ambiguity`
- `test_k15_context_identifier_match_precedes_context_tie`
- `test_k15_context_approved_alias_precedes_context_tie`
- `test_k15_context_composite_key_precedes_context_tie`
- `test_k15_context_high_risk_tie_retains_candidates_and_unique_top_stays_review`
- `test_k15_context_review_cannot_execute_system_merge`

The pre-existing tier tests in the same file (`test_context_overlap_merges_an_ordinary_type`,
`test_a_customer_does_not_auto_merge_on_context_either`, and the tier-record
tests) pass unchanged.

## Evidence status

`IMPLEMENTED_NOT_PROVEN`. The tests show the code does what this record says.
Nothing yet measures how often a real corpus produces a tier-4 tie, so the
review-queue cost of this change is unknown. The Protected Core ladder requires
a same-condition no-regression benchmark (entity merge precision and review
volume, before and after `5f0bca3`, on the same corpus); it has not been run.
Until it is, this record does not support any public claim about entity
resolution quality.

## Rollback

Revert the 12 added lines in `resolve_mention`. No stored data depends on the
new verdict: a tie that went to review leaves both entities unmerged, which is
the state a revert would start from.
