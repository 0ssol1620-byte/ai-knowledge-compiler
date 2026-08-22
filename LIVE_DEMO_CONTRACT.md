# Structara Landing Live Demo Contract

Authority: design masterplan section 7 and research blueprint sections 11–20.

## Purpose

The landing demo proves the entire product sentence in one bounded, inspectable
experience. It uses a frozen, rights-cleared fixture and never calls a mutable
production service. The live product routes remain available for real jobs.

## State machine

`idle -> collect -> structure -> verify -> knowledge -> package -> complete`

- The default autoplay loop is 12 seconds and advances through all five named
  customer phases: Collect, Structure, Verify, Knowledge, Package.
- A user selection pauses autoplay and becomes authoritative until Resume is
  chosen.
- Replay returns to Collect without reloading the page.
- Reduced motion renders Complete immediately and preserves every control.
- Background tabs and offscreen demos pause. They resume without skipping an
  explicitly selected phase.

## Frozen fixture

- Dataset: registered OpenDART public filing fixture.
- Receipt: `20260730000413`.
- Selected fact: Revenue, 2026 Q1, JPY 4,902,490,901.
- Truth boundary: native XBRL-tagged source; no parser-quality claim.
- Source, Markdown, knowledge, graph, and proof states use the same stable IDs.

## Phase contract

### Collect

Show the collection manifest, folder preservation, file count, policy boundary,
classification readiness, and provisional duplicate state.

### Structure

Show the same source page split into typed blocks. Repeated headers and ignored
regions must be visible as exclusions rather than silently disappearing.

### Verify

Show candidate route, numeric hard gate, exact source cell or bbox, authority
identifier, validation level, and First Verified decision. A failed candidate
remains visible as a failure.

### Knowledge

Show notes, entities, typed relations, evidence references, and conflicts. No
relation may appear without a source reference or an explicit unresolved state.

### Package

Show portable Markdown, Obsidian, RAG JSONL, JSON-LD/RDF, hashes, and package
manifest. Export availability is derived from verified inputs only.

## Interaction contract

- Tabs or segmented controls expose every phase and use arrow-key navigation.
- Play/Pause, Replay, and Open exact source are real controls.
- Selecting the revenue fact highlights the result and exact source cell in the
  same viewport.
- A text status announces phase changes at a throttled rate.
- Keyboard focus is never moved automatically.
- Visual state uses label, icon, and color; color alone is insufficient.

## Public evidence rules

- A benchmark number may appear only when the canonical public snapshot status
  is `available` and contains an evidence bundle digest.
- Diagnostic, smoke, synthetic, and official provider claims are visually and
  semantically distinct.
- Missing metrics render `Not measured` with the missing evidence requirement.
- Cost includes provider class, observed runtime, and pricing observation date.
- Exactly-three repeat results use distribution or range, not a single value.

## Accessibility

- Semantic tablist, tab, and tabpanel relationships are mandatory.
- The animated region has a visible pause control and does not start with audio.
- `prefers-reduced-motion` disables phase interpolation and video autoplay.
- Every visualization has a DOM table or ordered-list equivalent.
- Minimum target is WCAG 2.2 AA at 200% zoom and 390 CSS pixels.

## Performance

- First render is static DOM/CSS; enhancement is idle and offscreen-aware.
- Hero media budget: poster <= 180 KB, initial JS <= 170 KB route-specific,
  video lazy-loaded below the first proof interaction.
- The 12-second loop must not cause layout shift.
- Video has WebM and MP4 where available, poster, width/height, preload metadata,
  and no audio track unless a transcript and user-initiated audio are provided.

## Analytics

Allowed events: `demo_phase_viewed`, `demo_paused`, `demo_resumed`,
`demo_replayed`, `demo_fact_selected`, `demo_source_opened`, and
`demo_primary_cta_clicked`. Payloads contain fixture and phase IDs, never source
document content.

## Acceptance

- Five phases and three proof surfaces are visible and operable at 1440 and 390.
- Reduced motion shows a coherent final state.
- Source selection is exact and hash-bound.
- Browser console has no error or warning attributable to the demo.
- Component, accessibility, browser, and visual tests pass.
