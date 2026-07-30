# AKMP 1.0 Specification

AI Knowledge Markdown Profile (AKMP) is the deterministic export contract for
AI Knowledge Compiler. The normative keywords MUST, MUST NOT, SHOULD, SHOULD
NOT, and MAY are interpreted as requirements.

## Package requirements

The package root MUST contain `manifest.json`. Paths MUST be UTF-8, relative,
slash-separated, normalized, and free of `..`, drive prefixes, control
characters, or ambiguous Unicode normalization. Exporters MUST reject path
collisions after NFC normalization and case folding.

```text
manifest.json
documents/          Portable structured Markdown
knowledge/          evidence-backed notes and MOCs
assets/             figures, tables, and page previews
source-map/         authoritative block-to-source mappings
quality/            policy, findings, and metric records
rag/                RAG JSONL; a derived index layer
linked-data/        pinned context and JSON-LD graph
```

An Obsidian profile MAY add `00-Home`, taxonomy folders, Wikilinks, aliases,
tags, and flat properties. A Portable profile MUST remain CommonMark-readable.

## Manifest

`manifest.json` MUST contain:

- `akmp_version`, `cir_version`, `package_id`, and `profile`;
- creation time and deterministic-build epoch;
- source document IDs and SHA-256 hashes;
- route, quality, prompt, schema, and exporter versions;
- every model run's provider, upstream ID, exact revision, runtime image digest,
  and quantization;
- an ordered file inventory with media type, byte length, and SHA-256;
- external-processing disclosures;
- retention/deletion metadata that is safe to export;
- quality summary and unresolved warnings.

The manifest MUST NOT contain presigned URLs, credentials, internal bucket
names, user email addresses, or provider tokens.

## Markdown

- Encoding is UTF-8 without BOM; line endings are LF.
- ATX headings are used and one H1 is recommended per document.
- Links and attachments use safe relative paths.
- Images have useful alt text.
- Fenced code blocks include a language when known.
- Raw HTML is prohibited except the documented sanitized complex-table subset.
- AI summary/inference is separated from extracted content and labeled in
  frontmatter or an explicit generated-content section.
- Source-map sidecars, not hidden comments, are authoritative provenance.

Suggested frontmatter:

```yaml
---
akmp_version: "1.0"
id: "urn:akmp:doc:01J..."
title: "Document title"
content_layer: "structured"
review_status: "auto_with_warnings"
language: "ko"
source_sha256: "sha256:..."
source_document_id: "urn:akmp:source:..."
model_policy: "parse_balanced_v1"
provenance_file: "../source-map/document-id.json"
quality_file: "../quality/document-id.json"
---
```

Nested provenance and quality objects belong in sidecars, not YAML properties.

## Source map

Each entry MUST include block ID, output path/range, canonical origin, revision,
content hash, and at least one source reference. `bbox1000` follows ADR-001.
Markdown offsets are UTF-8 byte offsets or line/column pairs as declared by the
source-map schema; an exporter MUST NOT mix conventions.

Generated statements MUST list supporting block IDs. If support is missing,
the package fails knowledge export or emits an explicitly incomplete draft only
when the user has chosen a review-only export.

## RAG JSONL

Each line is independently valid JSON and includes:

- stable chunk/document/version IDs;
- title, heading path, content, content type, language, and token count;
- `content_layer` and canonical `origin` as separate fields;
- ordered source references using `bbox1000`;
- quality and warnings;
- previous/next chunk IDs;
- SHA-256 content hash.

Default chunk targets are 500–900 tokens, up to 1,200 for long coherent
sections, with 8–12% overlap. Tables are not split mid-row, figure-caption pairs
remain together, and short sections may inherit parent context.

## JSON-LD and SHACL

The exporter copies the pinned `context-v1.jsonld` into the package. Validation
MUST NOT retrieve remote contexts. Every note uses the base
`akmp:KnowledgeNote` type and a separate `akmp:noteType` specialization.
`knowledge-note.shacl.ttl` is the normative minimum shape.

## Deterministic archive

- File order is lexical by normalized path, with the manifest last after hashes
  are finalized.
- ZIP timestamps use the declared build epoch.
- File mode is fixed to 0644 and directory mode to 0755.
- No host path, username, locale, or wall-clock metadata is included.
- Rebuilding the same package inputs and versions MUST produce the same bytes.

## Validation order

1. Path and archive safety.
2. Manifest and profile JSON Schema.
3. File inventory hashes.
4. Markdown/link rules.
5. Source-map coverage and geometry.
6. RAG JSONL schema and adjacency.
7. JSON-LD expansion against the local context and SHACL.
8. Unsupported-claim and quality gates.

Any failure is reported with a stable machine-readable code and JSON pointer.
