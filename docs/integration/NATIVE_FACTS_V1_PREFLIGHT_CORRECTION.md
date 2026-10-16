# Native facts v1 preflight correction — offline DRAFT

Apply this separate follow-on after the immutable `native-facts-v1-DRAFT.patch`
(SHA256 `15a8b02bfa116e3296d10147a1c530443437b8eafff27d7db4d03b1a696763c1`)
and its frozen corrected native-CIR prerequisite at PR91 base
`f62a1b4a4bfea1ac555a7ac8f43b6bfb8de648c2`.

`NativeFactsDraft` formerly constructed unrestricted `CanonicalDocument`
instances before its after-validator reconstructed the bounded native request.
The normal four-cell fixture with `MAX_NATIVE_CELLS=1` was rejected only after
8 occupied-grid range calls. The new `canonical_documents` before-validator
requires the same 1–16 document envelope and invokes the existing native CIR
`_preflight` for every document before Pydantic constructs any table grid.
Existing model instances are converted to canonical wire dictionaries first.
The complete original digest/identity/projection after-validation remains.

The request/response schema, valid serialized output, projection ordering,
formula treatment, empty header bindings and all original CIR are unchanged.
No HTTP, compiler, parser, journal, provider or live routing code changes.
Native processing remains closed and this remains an offline unbound DRAFT.

Thirteen new regressions exercise lowered cell/grid, block and CIR-byte budgets
through JSON, Python dictionary and existing-model inputs; malformed dimensions,
depth, document count and an out-of-budget later document. They require zero
occupied-grid work before rejection. The original red regression recorded
exactly 8 calls. Focused suite, lint, typing and exact applied source hash
verification are recorded in the separate correction review bundle.

BEA acceptance is independently blocked before consumer-local hash verification:
both authorized supported Library attempts failed when the current helper tried
to use extended attributes unavailable in Windows Python. No readable workbook
was installed and no alternate download bypass occurred. BEA parse/projection,
13,006-cell comparisons, actual output size and package determinism remain
UNRUN; see the separately saved BEA acceptance evidence. This correction does
not claim to close that unrelated materialization blocker.
