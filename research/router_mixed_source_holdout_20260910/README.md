# Mixed-source Router holdout pre-registration

Status: **SOURCE MANIFEST FROZEN; RUNTIME AND PREDICTIONS PENDING; HOLDOUT UNOPENED**

The SEC target-cell development run established a useful Ovis component but
did not establish Router superiority. This package defines the next admissible
test before a source corpus, annotation or prediction is opened. It spans the
source classes that can make a Router economically useful: native structured
sources, born-digital PDF tables, scans, layout-heavy pages, Korean DOCX/PPTX/
XLSX, and target-alignment failures.

`MIXED_SOURCE_HOLDOUT_PROTOCOL.json` fixes source ordering, exactly 12 units
per class and 96 total units,
missing-output handling, arms, metrics, statistics, cost ceiling and teardown.
Its current SHA-256 is recorded in `PREOPEN_STATE.json`. Source URLs and bytes
are intentionally absent at this boundary. Adding convenient documents after
seeing model behavior would invalidate the experiment.

`preflight_mixed_holdout.py` refuses to open the run unless all of these are
true:

- every required class meets the fixed denominator;
- every input has an exact canonical HTTPS official-source record, a qualified
  research-use rights state and evidence URL, a host in the frozen allowlist,
  unique source/hash/family identities, byte size, media type, language,
  publisher and a truth-free source-native or bbox1000 target locator;
- rows follow the pre-registered class and URL-hash order, and no exact source
  hash or source family overlaps the immutable development inventory;
- the selection protocol, candidate inventory, source manifest, development
  inventory, preflight code and route prediction manifest match their frozen
  digests;
- Native/source-contract/router/evaluator/statistics and all three model
  runtimes, bundles and inference configurations are exact;
- every selected unit has exactly one source-bound route prediction, and both
  the input and prediction schemas reject truth, labels, expected answers and
  evaluator outputs;
- the truth directory is absent or empty.

For structurally valid inputs, the script emits a machine-readable result and
exits with code 2 on any blocker. Invalid JSON or unreadable inputs fail before
the gate can pass. It downloads nothing, launches no model, and reports
`holdout_opened=false`, `model_calls=0` at this stage.

The protocol authorizes at most USD 20, 600 model-unit calls and three parallel
pods after the pre-open gate passes. RunPod authorization does not override
the truth, identity, rights, denominator or cleanup gates. All pods must be
deleted and a separate zero-live-pod inventory receipt must be retained.

This package supports no public performance claim and no production promotion.

## Candidate acquisition boundary

`CANDIDATE_SEED_SCHEMA.json` and `prepare_candidate_inventory.py` define the
only admissible path from curated official metadata to the frozen candidate
inventory. The script reads no source content. It rejects unknown fields,
duplicate source/family identities, unqualified rights and incomplete classes,
requires an exact item title, filename and item-page rights marker, then selects
exactly 12 rows per class by the frozen URL-hash order. The inventory binds both
the seed manifest and selector bytes.

`OFFICIAL_SOURCE_ACQUISITION_STATE.json` records the frozen candidate boundary
and two official rights-policy anchors. A government host alone is not a rights
receipt: each Korean item needs its own KOGL Type 1 or equivalent record, and
each U.S. federal item needs item- or agency-specific government-work evidence.

`OFFICIAL_SOURCE_CANDIDATE_SEEDS.jsonl` contains 128 rights-qualified metadata
rows from independent source packages. Its SHA-256 is
`sha256:e0d96eeb2f31acf3abedb57ce94f1d79a124294d2110fa6b6edb87022d31586d`.
`FROZEN_CANDIDATE_INVENTORY.json` applies the preregistered URL-hash order and
selects exactly 12 units in each of the eight classes, 96 total, with 32 unused
standby candidates. Its SHA-256 is
`sha256:f7da723da18e35300dff774d50c03917eb9a13b7c68e3a5fc537698a5b88a8c0`.
The exact 96 selected source byte streams are privately persisted and bound by
`SELECTED_SOURCE_MANIFEST.jsonl` (`sha256:5001577b021a9f93869017e32a613e161ddc6edde95c75fd724f3faf29b1a451`).
The committed manifest contains metadata and digests only; 600,229,016 original
bytes remain in the ignored evidence directory. The development inventory binds
10,203 hashes and 3,848 source families from the exact spent Arena and SEC
source manifests; source-hash overlap and family overlap are both zero. Runtime
bindings and truth-free route predictions remain absent, so the pre-open gate
is closed and no model or GPU execution is authorized.

`acquire_selected_sources.py` is the bounded no-replacement acquisition path.
It accepts only HTTP 200 without redirects, caps each source at 300 MiB, writes
through a temporary file, validates PDF, OOXML and native structure, and emits
a manifest only when all 96 selected units succeed. A partial run keeps a named
failure receipt and emits no manifest. Original bytes remain under the ignored
private evidence directory and are never committed.

For `born_digital_pdf_table`, the candidate locator rule
`first_table_or_numeric_dense_page_full_bbox1000_v1` is resolved only after the
URL-hash selection is frozen. It scans pages in source order using the native
text layer, selects the first page with a line beginning `Table ` followed by
an ASCII letter or digit, and otherwise selects the first page containing at
least two lines with at least three numeric tokens each. The target is that
page's complete bbox1000 rectangle. It reads no annotation, model output or
evaluation result; failure to resolve the rule leaves the selected unit
unresolved rather than permitting a replacement.
