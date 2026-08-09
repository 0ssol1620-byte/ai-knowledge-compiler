# Architecture Decision Records

These records are normative for AI Knowledge Compiler 1.0. When prose, an
example payload, a database definition, or an older implementation disagrees
with an accepted ADR, the ADR wins. Contract changes require a new ADR and a
schema version bump; accepted ADRs are not edited to hide a superseded
decision.

| Conflict                                                                       | Canonical resolution                                                                                                        | Record                                                      |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------- |
| C-01 origin names differ between CIR examples, UI, and PostgreSQL              | The database `block_origin` values are the only wire/storage enum. Legacy labels are input aliases only.                    | [ADR-001](ADR-001-canonical-intermediate-representation.md) |
| C-02 examples alternate between `bbox_norm` (0–1) and `bbox1000`               | `bbox1000` integer coordinates in the inclusive 0–1000 range are canonical. Raw coordinates and transforms remain metadata. | [ADR-001](ADR-001-canonical-intermediate-representation.md) |
| C-03 quality score ranges overlap at 0.90 and do not state precedence          | Ranges are half-open and critical findings take precedence. Exact 0.90 is `PASS`; exact 0.82 is `PASS_WITH_WARNINGS`.       | [ADR-005](ADR-005-quality-gate-boundaries.md)               |
| C-04 URL ingestion is described but is not a safe MVP default                  | URL ingestion is disabled by the independent `url_ingest_enabled=false` feature flag.                                       | [ADR-004](ADR-004-multi-tenant-security-retention.md)       |
| C-05 an example enables external fallback by default                           | Every external-processing flag defaults to `false`; private mode enforces false regardless of tenant flags.                 | [ADR-003](ADR-003-provider-abstraction-model-policy.md)     |
| C-06 a figure example has an AI description but empty evidence                 | Every source-derived figure and every generated description MUST carry non-empty source evidence.                           | [ADR-001](ADR-001-canonical-intermediate-representation.md) |
| C-07 JSON-LD emits `ConceptNote` while SHACL targets `KnowledgeNote`           | Every note has `@type: akmp:KnowledgeNote`; specialization uses `akmp:noteType`.                                            | [ADR-002](ADR-002-akmp-1.0.md)                              |
| C-08 a RAG example puts `structured` in the origin field                       | `content_layer` and `origin` are separate fields. `structured` is a layer, never an origin.                                 | [ADR-002](ADR-002-akmp-1.0.md)                              |
| C-09 the UI shows security scanning but the state machine skips it             | `SECURITY_SCANNING` and `SECURITY_VERIFIED` are mandatory before preflight.                                                 | [ADR-004](ADR-004-multi-tenant-security-retention.md)       |
| C-10 `parse_fast_v1` is a product profile but missing from the initial recipes | `parse_fast_v1` is registered as a disabled-by-default HPD shadow recipe with a balanced fallback.                          | [ADR-003](ADR-003-provider-abstraction-model-policy.md)     |

## Proposed records

Not yet accepted. They do not bind until they are.

| Record | Decides |
| --- | --- |
| [ADR-006](ADR-006-anonymous-trial-ingest.md) | Whether the marketing hero may accept a document from an anonymous visitor, and under what caps. Preserves tenant scoping through a system trial tenant; does not shorten the ADR-004 quarantine path; stops at `PREFLIGHTED` so GPU spend stays closed; off by default. |

## Decision order

1. Security and tenant isolation constraints.
2. CIR, event, provider, and AKMP contracts.
3. Versioned route and quality policies.
4. Provider-specific manifests and implementation details.
5. Non-normative examples.

## Required review

Every change to an accepted contract must include:

- a compatibility impact statement;
- updated JSON Schema and generated types;
- migration or adapter behavior for persisted data;
- golden benchmark and snapshot impact;
- rollback behavior;
- security, privacy, and license review where applicable.
