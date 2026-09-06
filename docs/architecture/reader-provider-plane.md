# Reader provider plane (`akc_readers`)

**Status:** `IMPLEMENTED_NOT_PROVEN`. Code exists, tests including failure paths
pass, no threshold here is calibrated and no reader is qualified.
**Campaign:** TAVONEL-USKC-P0-20260906-V1, lane C.
**Blueprint sections:** §5, §8, §9, §14.1–14.2, §22, §27, §29, §44, §45, §48 P0-C, §62 step 3.
**Frozen contract:** `USKC_LANE_CONTRACT_2026-09-06.md` §4.4 and §4.6.

## What this package is

A plug-in layer *above* the native parsers and *above* the router. It answers
one question — "which reader may read this source version, and what did that run
actually cost and produce?" — and it answers it from capability evidence, never
from a provider or model name.

    ReaderInput (bytes + sourceVersion identity)
      → inspect_source()          §8.1 detection order → SourceInspection §8.2
      → ReaderRegistry.resolve()  capability match      → ReaderResolution
      → ReaderRegistry.read()     timeout + breaker     → NativeExtraction + ReaderRun §44
      → provider.emit_evidence_locators()               → EvidenceLocator v2 dicts

`akc_readers` does not import any Protected Core module except
`akc_cir.base` (the shared `ContractModel`/digest primitives) and
`akc_cir.inspection.FailureCode`, which it **reads** to build the failure-class
mapping table. It modifies nothing in `akc_cir` and nothing in
`akc_native_parsers`.

## What is wrapped, and what is not fixed

`legacy_pdf_v1` wraps `akc_native_parsers.parse_pdf_to_cir` at its existing
signature. The four pinned parser tests
(`tests/unit/test_native_parser_fidelity.py`, `test_nonpdf_structured_parsers.py`,
`test_pdf_native_fidelity.py`, `test_parser_verification.py`) are untouched: if a
wrapper needed one of them edited it would not be a wrapper.

Honest description of `legacy_pdf_v1`:

| Claim | Reality |
|---|---|
| Tier | `BEST_EFFORT`. No §27 qualification receipt exists, so no reader in this package is `VERIFIED_NATIVE` or `VERIFIED_HYBRID`. A VERIFIED tier must carry a receipt **path, sha256 and date** (`ReaderCapability` refuses less), and `register()` must find that file in this repository and re-digest it — a sha256-shaped string alone is refused. |
| Features | `native_text`, `layout` only. It does not reconstruct tables, formulas, comments or tracked changes, so it declares none of them. `ReaderRegistry.register()` refuses a provider that declares `tables` here — that refusal is a test. |
| Scanned PDFs | Not handled. This is the *native* path (blueprint §14.1). §14.2's page-image → OCR → specialist chain is not in this package and no OCR provider is registered. The registry has no visual reader; `VisualReaderProvider` exists as the frozen shape of §9's optional half and has no implementation. |
| Evidence | `pdf` locators, and only for blocks that carry a real `bbox1000`. A block without a rectangle yields **no** locator rather than a guessed one. |
| Reconciliation | Not implemented. §13's native/visual loss detection needs a second representation to disagree with. |

`plain_text_v1` is new, deterministic and stdlib-only: TXT/Markdown split on
blank lines into units carrying real byte ranges.

## Capability, and why this is a fourth capability shape

Three capability shapes already exist in the tree, none matching §9.1's feature
vocabulary:

| Existing shape | Path | What it is |
|---|---|---|
| `ParserCapabilities` | `akc_router/providers.py` | route/language/table-boolean shape, keyed to `Route` |
| `ParserCapability` | `akc_cir/parser_verification.py` | GPU-second and cost shape |
| `RecipeProfile` | `akc_parallel_runtime/routing.py` | `model_revision` + `runtime_image_digest` + opaque `capabilities: frozenset[str]` |

`ReaderCapability` is the fourth. It declares itself the **source** for
source-format capability: the §9.1 feature vocabulary is frozen in
`contract/enums.v1.json` and the site's Capability Manifest (lane D) consumes
`qualification_status` from it. The other three stay as they are; nothing in this
campaign derives them from `ReaderCapability`, and merging them is a P4 decision
(seam map O-3). `RecipeProfile` is the natural place a *GPU* reader's registry
entry would be derived from when one exists.

### Reuse of `akc_router.providers`

The contract asked whether `ProviderRegistry` could be imported or subclassed.
`ProviderUnavailableError` **is** imported and raised through, so an unavailable
reader carries the same `autonomous_isolation_required` semantics the router
already gives an unavailable parser. `ProviderRegistry` itself is **not**
subclassed, for three reasons, each structural:

1. Its resolution API is `parser_for(provider_id, route)` — resolution **by
   name**. This lane's contract forbids that API existing at all, and a subclass
   inherits it. `test_the_registry_offers_no_way_to_resolve_by_provider_name`
   asserts no public `ReaderRegistry` method accepts a name-shaped parameter.
2. It resolves on `Route`, a router concept about GPU execution tiers, not on
   MIME/source family/feature.
3. Its provider protocol is `async`; readers here are synchronous CPU work run
   under a thread timeout.

It is also load-bearing for the live `Route`/`RouteDecision` engine (seam map
X-6), so P0 leaves it read-only.

## Registration is a probe, not a declaration

`ReaderRegistry.register(provider)` accepts a provider only after witnessing what
it claims:

1. duplicate `provider_id` → refused;
2. any declared feature outside `PROBEABLE_FEATURES` → refused, because the
   registry cannot witness it (fail closed);
3. every `provider.probe_samples()` entry is inspected, `can_read` must return
   true, `extract_native` must succeed;
4. **per MIME pattern and per source family** — not per capability, and not
   across their union (contract §8.1): *every* pattern a capability declares must
   be matched by at least one probe sample, *every* source family it declares
   must be the inspected family of at least one sample, and every feature *that
   capability* declares must appear in the `NativeExtraction.observed_features()`
   of the samples that matched it — derived from concrete output fields (text,
   `bbox1000`, `table_id`, `formula`), never from the declaration. Folding
   `text/plain` and `application/pdf` into one capability therefore no longer
   lets the `.txt` probe qualify the PDF half, and that is why `plain_text_v1`
   ships a `.md` probe beside its `.txt` one;
5. every emitted locator must validate against the bundled verbatim copy of
   `evidence-locator.v2.schema.json` **and address the probe sample it came
   from** — same ids, a kind that can address that MIME, a page inside it;
6. a `VERIFIED_NATIVE` / `VERIFIED_HYBRID` capability must name a §27
   qualification receipt that exists in this repository. The model requires all
   three of path, sha256 and date; `register()` then opens the file and compares
   the digest. A sha256-shaped string is not a receipt — without this check a
   provider self-declaring `VERIFIED_NATIVE` with `sha256:000…0` registers and
   outranks every honest `BEST_EFFORT` reader in `_STATUS_RANK`;
7. `health_check()` must be healthy.

**Ceiling on globs, recorded not hidden:** a glob pattern (`*`, `image/*`) is
witnessed by whatever sample matches it, so one sample of a family admits the
whole family's MIME types — the declared *families* are what get checked one by
one. Listing concrete patterns is what makes a registration mean something, and
both shipped providers declare concrete patterns only.

**Known ceiling:** `PROBEABLE_FEATURES` is four of the fourteen frozen
`ReaderFeature` values. A provider that genuinely produces `comments`,
`track_changes`, `chart_data`, `geometry`, `assembly`, `acl`, `thread`,
`timestamp`, `ast` or `dependency_graph` cannot register today. That is the
fail-closed direction — the alternative is accepting a claim nothing checks — and
the upgrade path is one field on `ExtractedUnit` per feature, added when a reader
that produces it arrives.

## Run receipts (§44)

Every call to `ReaderRegistry.read()` returns a `ReaderRun`, including every
refusal. Fields that were measured are measured; fields that were not are `None`:

| §44 field | `ReaderRun` | Populated today |
|---|---|---|
| source version | `source_version_id`, `representation_id` | yes |
| reader/model revision | `reader_revision` | yes |
| runtime digest | `runtime_digest` | yes — see below |
| input/output digest | `input_digest`, `output_digest` | yes — both **recomputed**, never accepted from the provider's assertion (`output_digest` null on failure) |
| start/end | `started_at`, `ended_at` | yes |
| queue/wait | `queue_wait_ms` | caller-supplied; 0 in-process |
| retries | `retries` | 0 — the registry does not retry in P0 |
| failure class | `failure_class` | yes, from the frozen `FailureClass` list |
| CPU seconds | `cpu_seconds` | yes, `time.thread_time()` around the call |
| GPU seconds | `gpu_seconds` | **null** — no GPU runs here |
| provider cost | `provider_cost_usd` | **null** — no price snapshot exists |
| accepted/rejected | `accepted` | yes |
| escalation reason | `escalation_reason` | yes |

### A run is a probe too

`read()` verifies the extraction before it becomes an accepted receipt, for the
same reason registration probes a declaration:

- the **inspection is re-derived from the bytes** inside `read()`. A caller may
  pass one, but it is a cross-check, never the decision: an inspection that
  disagrees with the bytes is `RECEIPT_MISMATCH`. A stale or forged inspection
  used to make the registry accept a source the inspector refuses, and to
  publish a security refusal as ordinary corruption in the class lane F consumes;
- the resolved provider's own `can_read(source, inspection)` must also say yes →
  otherwise `UNSUPPORTED_FORMAT`. Resolution matches a *declaration*; `can_read`
  is the provider looking at these bytes, and both must agree;
- `sourceVersionId`, `representationId` and `providerId` on the output must equal
  the ones asked for → otherwise `RECEIPT_MISMATCH`;
- `outputDigest` is recomputed with `digest_units()` — the one definition
  providers also call → otherwise `RECEIPT_MISMATCH`;
- every `required_features` entry must be in the output's **observed** features →
  otherwise the matching class (`LAYOUT_FAILURE`, `TABLE_FAILURE`,
  `FORMULA_FAILURE`, `TEXT_OMISSION`, else `PRESERVATION_FAILED`). A declaration
  never satisfies a requirement;
- every locator the output carries (emitted or attached to a unit) must validate
  against the frozen schema **and be bound to the source actually read**:
  - its `sourceVersionId` / `representationId` must be this source's →
    otherwise `RECEIPT_MISMATCH`. The schema only says a locator is well
    *formed*; it cannot say whose source it names, so a locator citing
    `SRC-OTHER-TENANT-9999` used to ride out on an accepted run;
  - its `locatorKind` must be one the inspected MIME can carry
    (`_ADMISSIBLE_LOCATOR_KINDS`; a MIME absent from that table admits none, which
    is why plain text carries no locator) → otherwise `EVIDENCE_BROKEN`;
  - its `page`, when it has one, must lie inside the source's inspected
    `page_like_units` → otherwise `EVIDENCE_BROKEN`. A `pdf` locator with page
    999,999 on a `.txt` was accepted before this.

  Registration-time validation alone was not enough: locator ids come from the
  *caller's* `sourceVersionId`/`representationId`, which registration never sees.

`$/source`, `$/page` and `$/accepted knowledge unit` are therefore **not
computable** from these receipts yet: the cost half is null on purpose rather
than estimated. Nothing in this package publishes a cost number.

`runtime_digest` for an in-process reader is a sha256 over the canonical JSON of
`{python: <version>, reader, revision, <library pins>}`. There is no container
behind a stdlib/pypdf reader; this is a real pin of the real runtime, not a
stand-in for an image digest. A containerised reader supplies its image digest
instead.

For `legacy_pdf_v1` the library pins are the `pypdf` version **and a sha256 over
every `.py` source of the wrapped `akc_native_parsers` package** — that package
ships no version metadata in this monorepo, and a pin that did not move when the
wrapped code moved would misattribute a later Arena receipt to the wrong code.
What it does *not* cover: non-Python assets, and pypdf beyond its version string.

## Timeout and circuit breaker

`extract_native` runs in a one-worker `ThreadPoolExecutor` with
`future.result(timeout=…)`. Exceeding it produces a `PARSER_TIMEOUT` receipt and
counts a breaker failure; `failure_threshold` consecutive failures open the
circuit for `cooldown_seconds`, during which `resolve()` returns
`REVIEW_REQUIRED` + `PROVIDER_UNAVAILABLE` rather than a silent fallback to
another reader.

**Only an operational fault charges the breaker.** `OPERATIONAL_FAILURE_CLASSES`
is exactly `{PARSER_TIMEOUT, PARSER_OOM, PROVIDER_UNAVAILABLE}`. A source that is
empty, corrupt, encrypted, hostile, mis-digested or missing a required feature is
the *source's* failure and leaves the breaker untouched — otherwise three blank
uploads would report a working stdlib reader as unavailable, which is exactly the
constitution's "separate operational failure from semantic failure" violation.
A source whose bytes do not decode as the text they were detected as (a CP949
tail past the 8 KB sniff window, say) is `CORRUPT_SOURCE`, not
`PROVIDER_UNAVAILABLE`.

**A wrong reader is not an unavailable one.** `SEMANTIC_FAILURE_CLASSES`
(`RECEIPT_MISMATCH`, `EVIDENCE_BROKEN`) charges a *separate* counter,
`ReaderHealth.semantic_strikes`, and never the breaker: a provider that binds its
output or its evidence to the wrong source is defective, and hiding it behind
`PROVIDER_UNAVAILABLE` would misname the defect. Nothing acts on the counter
automatically — de-registration is a manual act in P0 (contract §8.1), and the
threshold that would make it automatic is a decision, not a default.

**Ceiling, recorded not hidden:** Python cannot kill a worker thread, so a
timed-out reader runs to completion in the background. That leaks a CPU second,
not a result — the receipt is `PARSER_TIMEOUT` and the output is discarded. The
upgrade path is the repository's existing `-I` subprocess parser sandbox, which
is what a reader that can hang unboundedly needs.

## Failure-class mapping (§45 ↔ `FailureCode` F0–F48)

Shipped as **data** (`akc_readers.enums.FAILURE_CODE_TO_CLASS`), not as a claim
of equivalence. The mapping is lossy in both directions and the module names both
gaps as tuples that a test keeps accurate.

| `FailureCode` | frozen `FailureClass` |
|---|---|
| F0_SOURCE_CORRUPT | CORRUPT_SOURCE |
| F1_SOURCE_UNSUPPORTED | UNSUPPORTED_FORMAT |
| F3_QUEUE_TIMEOUT | PARSER_TIMEOUT |
| F4_WORKER_LOST, F5_MODEL_INIT | PROVIDER_UNAVAILABLE |
| F6_MODEL_OOM | PARSER_OOM |
| F8_EMPTY_OUTPUT | EMPTY_OUTPUT |
| F11_GARBLED_TEXT | TEXT_OMISSION |
| F12_READING_ORDER | LAYOUT_FAILURE |
| F13_TABLE_STRUCTURE | TABLE_FAILURE |
| F14_FORMULA | FORMULA_FAILURE |
| F17_NATIVE_RENDER_DISAGREEMENT | NATIVE_VISUAL_DISAGREEMENT |
| F19_ENTITY_AMBIGUITY | IDENTITY_UNRESOLVED |
| F22_LINEAGE_BROKEN | EVIDENCE_BROKEN |
| F24_RECOMPILE_DIVERGENCE | EQUIVALENCE_FAILED |
| F25_PERMISSION_VIOLATION | ACL_UNRESOLVED |
| F28_SECURITY_BLOCKED, F45_ACTIVE_CONTENT_OR_MALWARE | MALWARE_QUARANTINED |
| F46_ARTIFACT_CHECKSUM_MISMATCH, F47_PROVENANCE_SIGNATURE_INVALID | RECEIPT_MISMATCH |

**Frozen classes with no F-code:** `ENCRYPTED_SOURCE`, `SOURCE_DELETED`,
`PRESERVATION_FAILED`. The seam map named only the last two;
`ENCRYPTED_SOURCE` has none either (F28 is a *security block*, not a password),
so the reader plane raises it from the inspector's own `encrypted` fact instead
of translating an F-code.

**F-codes with no §45 class:** every code not in the table above — 29 of the 49,
including F2, F7, F9, F10, F15, F16, F18, F20, F21, F23, F26, F27 and F29–F44,
F48. They are recorded in `FAILURE_CODES_WITHOUT_FAILURE_CLASS`; a run carrying
one keeps the F-code in `escalation_reason` and leaves `failure_class` unset
rather than forcing a near-miss.

Only unambiguous mappings are made. `F16_CROSS_PAGE → LAYOUT_FAILURE` and
`F20_AUTHORITY_CONFLICT → IDENTITY_UNRESOLVED` are plausible and deliberately
*not* asserted.

## The inspector (§8.1)

Order: extension → declared MIME → magic bytes → container signature → ZIP
package structure → encryption → truncation → text/native-structure presence →
page count → bomb ratio. It never trusts the extension, never extracts an archive
member, and never raises for hostile input: an unknown binary comes back as
`application/octet-stream` with `UNRECOGNIZED_BINARY` in `review_reasons`.

`akc_native_parsers.security.validate_source()` is wrapped, not forked: for the
seven extensions it covers, its `StructuredParseError` codes become review
reasons on the inspection. The inspector itself sets only the two facts it can
stand behind (`encrypted`, `corrupted`); `resolve()` is where those reasons
become a frozen class, and a code that `PARSE_ERROR_TO_CLASS` maps to
`MALWARE_QUARANTINED` (active content, unsafe XML, archive-bomb limits) is
published as `MALWARE_QUARANTINED`, never as ordinary `CORRUPT_SOURCE` — lane F
reads these strings as its audit vocabulary. `security.py` is not edited —
contract §7 R-3.

**Encrypted Office packages.** A ZIP-level encryption bit is only one of the two
shapes. An ECMA-376 password-protected `.docx`/`.xlsx`/`.pptx` is not a ZIP at
all: it is an OLE/CFB container whose directory names an `EncryptedPackage`
stream (MS-OFFCRYPTO). The inspector sniffs the CFB magic and that UTF-16LE
name and reports `encrypted` with `OOXML_ENCRYPTED_PACKAGE`, so a locked file is
refused as `ENCRYPTED_SOURCE` rather than mislabelled `CORRUPT_SOURCE` through
`validate_source()`'s `MAGIC_MISMATCH`. The source family stays `unknown` — a
`.doc`, an `.xls` and an `.msg` are all CFB too, and guessing which would be an
invention. The committed test is a *signature* test built from those two byte
sequences; no real password-protected Office file is committed or claimed.

`confidence` is a **structural-completeness** score, not a calibrated probability
and not a quality score. It counts which detection steps concluded something.
Nothing routes on it: `resolve()` uses capability plus the `encrypted` and
`corrupted` facts, per the constitution's "never route on a scalar blind quality
score".

## Evidence locators

Locators are emitted as plain dicts and validated with `jsonschema` against the
bundled verbatim copy of `evidence-locator.v2.schema.json` (sha256
`13608314b63dfba8aef94de5cafc47d3712d0ed2a134a7a00e0f7aad4f8ff9c6`, pinned by a
test) at **both** ends: once when a provider registers, and again on every
accepted run, over the emitted locators and the ones attached to units. Lane E
owns the Python pydantic model of the union; this package does not import it.

**Gap:** the frozen `LocatorKind` list has **no plain-text variant**, and every
existing variant needs an anchor a `.txt` has not got (a page, a commit sha, a
JSON pointer). `plain_text_v1.emit_evidence_locators()` therefore returns nothing
rather than inventing an anchor, and the byte ranges stay on the units. A `text`
variant with `{byteRange | lineRange}` is proposed for enums v2 in the lane
report.

## Filling a Reader Registry entry from Model Arena receipts (§22)

`ReaderRegistry.entries()` projects §22 rows today with every measured field
`None` and `status: candidate`. `ReaderRegistryEntry` refuses to be `qualified`
without at least one `evaluator_receipts` digest. What a later wiring must supply,
per §22 and this contract — **not** read from the arena directory, which no lane
in this campaign touches:

| §22 field | Source when the Arena is wired |
|---|---|
| `model_revision` | the pinned exact model ID + revision from the run receipt |
| `runtime_digest` | the runtime image digest recorded in the same receipt |
| `strengths` / `weaknesses` | per-failure-class outcomes, not a prose summary |
| `qualified_source_families` | families the evaluator actually ran, never inferred |
| `qualified_failure_classes` | frozen `FailureClass` values the reader was measured on |
| `p50_latency_ms` / `p95_latency_ms` | measured on that exact revision + runtime digest |
| `cost_per_unit` | with the price snapshot date; raw cost never beside a retail price |
| `memory_requirement` | observed peak, not a configured limit |
| `evaluator_receipts` | sha256 of committed receipts; promotion gate is `ChampionMatrix`'s |
| `status` | `candidate` until receipts exist; `qualified` is a promotion decision |

Rules that carry over unchanged: never infer capability from a model's name;
route on capability and failure class, never on "stronger model"; a comparison is
only same-condition.

## Deliberately not built in P0

- No OCR/visual reader, no rendering, no reconciliation, no loss detection.
- No XLSX/DOCX/PPTX/HWPX reader — the inspector identifies those packages, and
  no provider claims them, so they resolve as `UNSUPPORTED` (fail closed).
- No `schema.py` registration and no `generated-contracts.ts` regeneration —
  that is lane E's single regeneration in P0 (seam map X-7).
- No retry policy; `retries` is present in the receipt and always 0.
- No wiring to the site. The site talks to the core over one HTTPS seam and this
  package is not on it yet.
