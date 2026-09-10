# Mixed-source Router holdout pre-registration

Status: **SELECTION PROTOCOL FROZEN; CORPUS UNACQUIRED; HOLDOUT UNOPENED**

The SEC target-cell development run established a useful Ovis component but
did not establish Router superiority. This package defines the next admissible
test before a source corpus, annotation or prediction is opened. It spans the
source classes that can make a Router economically useful: native structured
sources, born-digital PDF tables, scans, layout-heavy pages, Korean DOCX/PPTX/
XLSX, and target-alignment failures.

`MIXED_SOURCE_HOLDOUT_PROTOCOL.json` fixes source ordering, class bounds,
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
