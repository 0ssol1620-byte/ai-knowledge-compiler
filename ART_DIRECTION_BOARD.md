# Structara v4 art direction board

## Decision state

This board is the implementation brief for the six v4 signature scenes. It is
not screenshot evidence and it does not award a QA score. The current worktree
remains blocked until each selected composition is captured in its actual route
at 1920, 1440, 1280, 1024, 768, 390, and 360 pixels, including reduced motion, and passes the
machine-readable gates in `VISUAL_QUALITY_GATES.yml`.

The governing idea is **Editorial Intelligence with product truth**. Warm paper
and ink carry the composition. Brand blue marks a real transformation; evidence
cyan marks a real provenance link. Product and public proof are dominant. 3D,
glyphs, grids, and texture support the explanation but never impersonate proof.

## Three required static compositions

Every P0 signature scene must be resolved in all three compositions before its
provisional direction becomes an approved direction.

### A — Editorial Source

One actual or clearly labeled deterministic source page occupies the dominant
plane. A strong editorial statement and generous negative space frame the
source. Structure and knowledge appear as restrained annotations rather than a
dashboard wall.

- Best for category comprehension and source continuity.
- The source identity, fixture label, and evidence boundary remain visible.
- Mobile uses a source-first vertical poster, not a crop of the desktop scene.

### B — Proof-First Product

The actual product state is dominant. A selected result and its exact source
target are visible together; the connecting line avoids text and preserves a
text equivalent. Controls are real, or visibly unavailable when no connected
workspace exists.

- Best for product truth, proof links, and autonomous state.
- No generated screenshot, fabricated progress, or confidence-only result.
- Mobile becomes source/result tabs with a persistent evidence summary.

### C — Knowledge Architecture

A deterministic directory, MOC, note, relation, and package hierarchy becomes
the dominant visual. The graph remains secondary until a selected relation can
show adjacent evidence.

- Best for architecture and deployable-output comprehension.
- Trees and relationships have ordered list/table equivalents.
- Mobile is list-first and reveals only a local graph neighborhood.

## Provisional composition decision matrix

These are implementation targets, not approvals. A direction can change after
current-route evidence exposes a truth, crop, accessibility, or performance
failure.

| Asset | Message | A | B | C | Provisional direction |
| --- | --- | ---: | ---: | ---: | --- |
| A01 Drop Everything | A collection arrives with structure, classification, and dedupe intact | required | required | required | B — manifest-led product state |
| A02 Source to Structure | One source section becomes typed blocks | required | required | required | A — same-source transformation |
| A03 Proof Link | A result returns to the exact source target and authority | required | required | required | B — selected result beside proof |
| A04 Knowledge Architecture | Directory, MOC, notes, entities, and relations form | required | required | required | C — architecture before graph |
| A05 Graph with Evidence | A typed relation keeps its adjacent proof | required | required | required | B — graph selection plus proof |
| A06 Deployable Package | Obsidian, ontology, Neo4j, RAG, provenance, and validation ship together | required | required | required | C — inspectable package tree |

## Signature scene contracts

### A01 — Drop Everything

- Actual DOM: homepage `[data-signature-asset="A01"]`; operational context
  `/intake`.
- Required semantics: folder and file arrival, safe relative paths,
  classification, dedupe counts, and signed-preflight availability.
- Truth boundary: the first-party hero model is T2 illustration. It may support
  the scene, but it is never evidence that bytes uploaded or a job completed.
- Static state: the manifest remains comprehensible without WebGL or motion.
- Mobile: summary first, grouped files, accessible pause/resume/reselect; never a
  5,000-row wall.

### A02 — Source to Structure

- Actual DOM: homepage `[data-signature-asset="A02"]`; processing context
  `/workspace`.
- Required semantics: one stable source identity, original page region, typed
  blocks, excluded repeated header, reconstructed table, joined split paragraph,
  and source references.
- Truth boundary: before and after may not use unrelated fragments.
- Static state: transformation order has a selectable text equivalent.
- Mobile: Source and Result are separate tabs with the same persistent evidence
  identity.

### A03 — Proof Link

- Actual DOM: homepage `[data-signature-assets~="A03"]` and
  `[data-signature-asset="A03"]`; full public proof at `/demo/dart`.
- Required semantics: selected value, source cell or normalized `bbox1000`,
  authority, verification status, receipt, taxonomy, source line, and archive
  hash.
- Truth boundary: the registered OpenDART fixture is product/public proof, not
  labeled benchmark ground truth and not a quality score.
- Static state: the selected source target and evidence receipt remain visible.
- Mobile: no connector crossing text; stack result, source target, and receipt.

### A04 — Knowledge Architecture

- Actual DOM: homepage `[data-signature-asset="A04"]`; inspectable context
  `/knowledge-bases`.
- Required semantics: directory tree, MOC, notes, entities, relations, and the
  document-to-note source link.
- Truth boundary: a generic node motif does not satisfy this asset.
- Static state: the hierarchy is complete as DOM before progressive graph
  enhancement.
- Mobile: tree/list first with collapsible groups and readable long Korean and
  English labels.

### A05 — Graph with Evidence

- Actual DOM: homepage `[data-signature-assets~="A05"]`; relation context
  `/knowledge-bases`.
- Required semantics: typed nodes and edges, selected relation, adjacent proof,
  authority state, and accessible relation table.
- Truth boundary: every visible edge resolves to source evidence; orphan or
  decorative graph edges are prohibited.
- Static state: relation table and proof panel carry the complete meaning.
- Mobile: local neighborhood only; the relation list is the primary view.

### A06 — Deployable Package

- Actual DOM: homepage `[data-signature-asset="A06"]`; package context
  `/app/projects/project_research/exports`.
- Required semantics: `source/`, `canonical/`, `obsidian/`, `ontology/`,
  `graph/`, `rag/`, `provenance/`, and `validation/`, plus checksums, signature
  state, and round-trip result.
- Truth boundary: ready, signed, downloadable, and import-validated are data
  states, never decorative labels. Missing evidence renders as unavailable.
- Static state: a readable package tree and validation summary are complete
  without motion.
- Mobile: ordered package roots first; details disclose on demand.

## Responsive, accessibility, and motion direction

- Capture all selected scenes at exact widths 1920, 1440, 1280, 1024, 768,
  390, and 360. The 390 and 360 layouts are independently composed and are not
  desktop crops.
- At 200% zoom, no key evidence, source identity, status, or primary action is
  clipped or obscured.
- All core flows are keyboard operable; upload has a non-drag path; focus is
  visible; status never depends on color alone.
- Evidence connectors have ordered text equivalents. Graphs have tables; source
  boxes have textual source references.
- Product motion is event-driven only: file arrived, block detected, numeric
  verified, note created, folder created, package ready.
- Reduced motion and Save-Data preserve identical information in the complete
  static composition. No infinite float, glow pulse, fake loading, or typing of
  already-complete output.

## Performance and provenance direction

- Hero LCP is HTML text and a responsive poster. WebGL and GLB are lazy,
  offscreen-paused, and optional; context loss falls back to the poster with no
  layout shift.
- T0 captures must come from real code with deterministic fixtures, frozen time,
  stable IDs, and explicit Sample or Public demo labels.
- T0 evidence, benchmarks, customers, logos, certifications, and security claims
  may never be generated.
- First-party code, SVG, and 3D use the repository provenance records. Public or
  external material requires source, creator, license, commercial and
  modification rights, hash, allowed use, and review evidence before intake.
- Lab performance is labeled as lab evidence. Field Core Web Vitals require a
  canonical deployment and real traffic.

## Approval boundary

The board is complete as a direction contract. Production art approval is not.
No A01–A06 score is recorded until current actual-page captures, accessibility,
performance, provenance, and finding counts have been inspected. Previous
screenshots and visual regression baselines are useful history but cannot close
the v4 gate.
