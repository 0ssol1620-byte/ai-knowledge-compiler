# Shared evidence and entity lineage qualification — 2026-09-30

Masterplan v4.0 section 10.5 requires evidence anchors to resolve to existing
artifacts; section 12.8 requires selective/full equivalence. Its source-verifiable
knowledge contract requires provenance to survive semantic projection. Inspection
of native DOCX/XLSX extraction shows native object/cell identities are distinct
from geometry. Core evidence identity hashes source version, page, geometry and
text, deliberately excluding native object ID. Different native anchors can
therefore legitimately share one evidence digest.

The old reducer indexed blocks only by evidence digest, overwrote one citation,
and emitted an evidence object for every unit with that same stable ID. The
canonical model correctly rejected the duplicate IDs. Separately, entities with
mentions in multiple documents exposed only their first claim's citation.

Core now indexes blocks by source version and native anchor, keeps claim-specific
and relation-subject-specific citations, emits one shared evidence object with
the union of its native citations, and retains the full deduplicated supporting
citation set for each entity. Shared evidence remains unresolved if any supporting
unit has unresolved identity. Evidence and native identity formulas, external
contracts and Foundation gates remain unchanged.

## Bounded acceptance

Two synthetic regressions exercise actual candidate compilation and canonical
model validation. Both fail with the original compiler: duplicate-object rejection
for coincident spans, and a missing document citation for a cross-source entity.
With the fix, coincident spans have unique knowledge object IDs, valid graph link
targets, one evidence object carrying both anchors, and distinct correctly cited
claims/relations. A subsequent no-op revision passes full-rebuild equivalence and
reuses all six unit artifacts. The second fixture verifies both supporting source
citations survive entity projection. No thresholds or rejection validators change.

This does not prove native decoder completeness on real Office/PDF corpora,
physical overlap disambiguation, OCR derivation, entity recognition accuracy,
causal relation extraction, or generalization. Relations remain rule-derived
mentions with warning-level verification; no inferred fact is promoted. Existing
native-format fidelity and ontology tests are regression evidence, not benchmark
measurements. Blueprint ontology terms remain configuration-derived and are not
newly asserted as source-derived facts by this change.

Worktree: task-3/core-grounding, branch codex/core-grounding-qualification, based
on 39f4eff2a8cd6e3eba5611f60566b61883688b0e. Integration and previous offline
checkouts remain unchanged. No provider, credentials, storage infrastructure,
publication or deployment was introduced. A changed compiler requires a new
release digest when deployed; old stored receipts are immutable.

Verification: 127 Product Core/native-format/PDF/ontology tests passed; canonical
knowledge model and package tests were also run independently. Product Core Ruff,
formatting, strict compiler mypy and whitespace checks passed. All tests used the
existing isolated Python environment with PYTHONPATH selecting this worktree's
package sources and a workspace-local pytest temporary directory.
