# ADR-001: Canonical Intermediate Representation

- Status: Accepted
- Date: 2026-07-29
- Owners: Architecture, Data Platform, Product Trust
- Contract version: CIR 1.0

## Context

All parsers, quality engines, editors, and exporters need one lossless contract.
Earlier examples used short origin labels and two normalized coordinate systems.
They also allowed a generated figure description to exist without source
evidence. Those differences would make database rows, TypeScript types, and
export packages disagree.

## Decision

### Canonical origin enum

The following values are the only values allowed on the wire and at rest:

```text
native_extracted
ocr_extracted
rule_reconstructed
ai_reconstructed
ai_summarized
ai_inferred
user_edited
```

`structured`, `knowledge`, `source`, and `index` are content layers, not
origins. A provider adapter MAY accept legacy aliases at its boundary, but MUST
normalize them before producing CIR:

| Legacy/provider value | Canonical value |
|---|---|
| `native` | `native_extracted` |
| `ocr` | `ocr_extracted` |
| `layout_reconstructed` with deterministic rules | `rule_reconstructed` |
| `layout_reconstructed` with model generation | `ai_reconstructed` |

Unknown values fail contract validation. They are not silently mapped.

### Canonical coordinates

`bbox1000` is the canonical normalized rectangle:

```text
[x1, y1, x2, y2]
```

- Values are integers in the inclusive range 0–1000.
- The origin is the top-left of the post-rotation page.
- `x1 < x2` and `y1 < y2` are required for an area-bearing block.
- Page indexes are zero-based inside CIR.
- Polygon coordinates use the same 0–1000 integer space.
- PDF points, pixels, DPI, source dimensions, pre/post-rotation matrices, and
  crop transforms remain in `source_geometry.raw`.
- `bbox_norm` in a provider response is accepted only by the provider adapter,
  converted deterministically, and never persisted as authoritative data.
- `source-map.json` is authoritative; Markdown comments are hints.

Rounding is `round-half-away-from-zero`, then clamped to 0–1000. Conversion
tests MUST enforce a maximum one-unit round-trip error.

### Evidence and figures

Every source-derived block MUST contain at least one source reference. A figure
record MUST link its asset to the page rectangle from which it was cropped. A
caption MUST reference its own block or rectangle. An AI description MUST:

- use `origin=ai_summarized` or `origin=ai_inferred`;
- include the figure asset reference and one or more supporting source blocks;
- be labeled as generated in UI and export metadata;
- be omitted or marked `evidence_incomplete` if evidence is unavailable.

Empty `source_refs` is invalid for figures, captions, formulas, tables, and
generated claims.

### Identity and revision

- IDs are stable, opaque UUID/ULID-based URNs.
- `content_hash` is computed from canonical UTF-8 content and semantic fields.
- Every edit increments `revision`.
- Model reruns do not overwrite a user-locked revision.
- All provider results include model run IDs and exact model revisions.

## Consequences

- Database, JSON Schema, Pydantic, TypeScript, and UI badges share one enum.
- Exporters can regenerate all profiles from the same CIR.
- Provider adapters carry conversion complexity, keeping the core model
  agnostic.
- Existing 0–1 coordinate examples require migration/adaptation before use.

## Verification

- Contract tests reject noncanonical origins and floating `bbox1000` values.
- Property tests cover coordinate transforms and inverse transforms.
- Golden tests verify figure/caption/description evidence.
- Source-map coverage is a hard release gate.
