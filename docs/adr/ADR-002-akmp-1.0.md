# ADR-002: AKMP 1.0

- Status: Accepted
- Date: 2026-07-29
- Owners: Knowledge Platform, Export, Product Trust
- Contract version: AKMP 1.0

## Context

Portable Markdown, Obsidian, RAG JSONL, and JSON-LD must be deterministic views
of a canonical package. Earlier examples used `akmp:ConceptNote` while the
SHACL shape targeted `akmp:KnowledgeNote`, and used `structured` as a RAG
origin. Both would break validation and provenance reporting.

## Decision

### Canonical package

An AKMP package contains:

```text
manifest.json
documents/
knowledge/
assets/
source-map/
quality/
rag/
linked-data/
```

`manifest.json` records the package/schema versions, source hashes, exact model
and prompt revisions, route policy, deterministic file inventory, and SHA-256
for every file. ZIP entry order, timestamps, permissions, path separators, and
compression settings are fixed by the exporter profile.

### Content layer and origin are independent

The content layer enum is:

```text
source | extracted | structured | knowledge | index
```

The origin enum is the CIR enum in ADR-001. Each RAG chunk MUST carry both:

```json
{
  "content_layer": "structured",
  "origin": "rule_reconstructed"
}
```

`origin: "structured"` is invalid. A chunk can contain multiple source
origins; in that case `origin` is the dominant canonical origin and
`source_origins` contains the unique ordered set.

### KnowledgeNote JSON-LD

Every note is emitted as:

```json
{
  "@id": "urn:akmp:note:...",
  "@type": "akmp:KnowledgeNote",
  "akmp:noteType": "concept",
  "dcterms:title": "...",
  "dcterms:source": { "@id": "urn:akmp:doc:..." },
  "akmp:supportedBy": [{ "@id": "urn:akmp:block:..." }]
}
```

`noteType` MAY be `concept`, `document`, `person`, `organization`, `project`,
`glossary`, `moc`, or a versioned domain-pack value. The pinned local context
defines all terms. Export validation MUST NOT dereference a remote JSON-LD
context.

SHACL targets `akmp:KnowledgeNote` and requires title, source, and at least one
supporting block. `ai_inferred` notes also require a confidence value and an
explicit inference marker.

### Markdown profiles

Portable Markdown uses UTF-8/LF, ATX headings, one recommended H1, relative
CommonMark links, fenced-code languages, image alt text, YAML frontmatter, and
no raw HTML except a sanitizer-compatible complex-table subset.

The Obsidian profile may add aliases, tags, flat properties, Wikilinks, MOCs,
and relative attachments. Obsidian syntax is never authoritative provenance.

RAG JSONL uses adaptive semantic chunks, preserves table rows and
figure-caption pairs, includes adjacent chunk IDs, content hash, language,
token count, source references, content layer, and canonical origin.

## Consequences

- JSON-LD and SHACL agree on the base note class.
- Retrieval filters can distinguish what a block represents from how it was
  produced.
- Exporters remain deterministic and profile-specific without forking source
  truth.

## Verification

- Every package passes JSON Schema, SHACL, source-map, link, and hash checks.
- RAG contract tests reject layer values in `origin`.
- Golden ZIPs are byte reproducible.
- Unsupported generated claims block export.
