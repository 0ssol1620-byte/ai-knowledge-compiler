# Contributing

AI Knowledge Compiler treats contracts, evidence, and tenant isolation as
product behavior. Changes must preserve those properties even when they appear
to make a parser, model adapter, or user interface simpler.

## Development workflow

1. Create or update an ADR for a contract-level decision.
2. Change the canonical JSON Schema before generated or hand-maintained client
   types.
3. Add regression tests at the narrowest useful layer.
4. Run `scripts/check.ps1`.
5. Record benchmark evidence for any routing, quality, prompt, or model change.

## Non-negotiable invariants

- Every business query and object key is tenant scoped.
- AI-derived factual content requires valid source block evidence.
- L1/L2 extracted content is not overwritten by L3 knowledge output.
- External model transfer is opt-in and impossible in Private mode.
- Credit entries are append-only, idempotent, and transactionally settled.
- Identical CIR snapshot, exporter version, and options produce identical
  archives.
- Document content, complete signed URLs, credentials, emails, and source
  filenames do not enter operational logs.
- Model, prompt, router, schema, runtime image, and source revisions are
  recorded for reproducibility.

## Pull request evidence

Include:

- requirements or ADR affected;
- tests added and commands run;
- schema/API compatibility impact;
- tenant/security review;
- quality and cost impact for model-path changes;
- rollback procedure.

Do not commit credentials, customer files, licensed private benchmark data, or
live provider responses containing source content.
