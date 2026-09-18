# TAVONEL Arena protocol v1

This namespace validates and compiles evidence that already exists. It does not
call models, rent GPUs, acquire datasets, publish results, or approve claims.
It does not import the stale/dirty `research/model_arena_20260903` scoreboards.

The compiler implements the Arena A–E evidence envelope:

- family-disjoint calibration and Arena corpora with source, license, hash,
  slice, origin, and router split records;
- frozen Track I/N input, Track P prompt, and Track B execution arms;
- complete case × arm × repeat accounting, including errors, timeouts,
  unsupported inputs, invalid output, and truncation;
- success-only quality as a diagnostic and all-page effective quality as the
  headline metric;
- actual cost/page p50/p95, latency p50/p95, and Pareto membership;
- fixed-context downstream raw/native vs single-parser vs TAVONEL arms;
- ontology gold/provenance metrics and a measured 1–5% continuous update;
- preregistration, `results.json`, `results.csv`, and the public-growth contract
  in `manifest.json`.

`schemas/public_manifest.schema.json` is the stable handoff contract for the
public Arena/growth surface. `ELIGIBLE_FOR_FOUNDER_RELEASE_REVIEW` still requires
the founder's release decision; the compiler always emits
`claims_approved: false` because the generating session cannot approve itself.

There is a non-circular external approval path. After export, an independent
reviewer may create a receipt satisfying
`schemas/external_approval_receipt.schema.json`. A public consumer must:

1. require `release_state == ELIGIBLE_FOR_FOUNDER_RELEASE_REVIEW`;
2. recompute every artifact hash and the manifest file hash;
3. recompute `publication_contract.approval_subject_sha256` from the ASCII
   artifact-hash payload described below;
4. require exact subject and manifest hashes in the external receipt;
5. verify the receipt signature against the independently trusted key registry;
6. verify its rights, IP, statistical, and claim review receipt hashes.

The approval subject never serializes result numbers. Its exact ASCII bytes are
`tavonel.arena.approval_subject.v1\n`, followed by one line for every artifact
name in lexical order: `artifact\t<name>\t<sha256:value>\n`. The Python
references are `approval_subject_payload` and `approval_subject_digest`.

The signature input also avoids JSON canonicalization. Validate the external
receipt schema first, then build exact ASCII lines beginning with
`tavonel.arena.approval_signature.v1\n`. Append `field\tvalue\n` for `schema`,
`decision`, `approval_subject_sha256`, `manifest_sha256`, and `approved_at` in
that order. Append `founder_identity_ref_sha256\t<sha256 of its UTF-8 bytes>\n`.
Finally append `review\t<name>\t<sha256:value>\n` in `claim`, `ip`, `rights`,
`statistical` order. Sign those exact bytes. The Python reference is
`approval_signature_payload`.

Only that consumer-side verification authorizes publication. A boolean-like
string, schema-valid-looking digest with no corresponding bytes, eligible
manifest, or `claims_approved: false` alone cannot authorize it.

## Import completed external measurements

`import` is a receipt importer, not a model runner. It never invokes a provider.
`MEASURED_RESEARCH` is the caller's evidence classification, not an execution
attestation. The importer proves that the supplied bytes are complete,
hash-bound, internally consistent, and safe to replay; unsigned local receipts
do not prove who ran the model or whether the reported measurement is truthful.
The CLI summary and every persisted run therefore record
`provenance_assurance: CALLER_SUPPLIED_HASH_BOUND_BYTES` and
`execution_attested: false`.

It accepts a completed `MEASURED_RESEARCH` bundle only after every source,
license, model, prompt, hardware, batch, evaluator, current-price, terminal-run,
and downstream-layer receipt is present below `--artifact-root`, frozen where
applicable, and matches its declared hash and identity. Traversal and symlink
escapes fail closed.

The destination database must already be migrated through the Arena persistence
migration, and each preregistered model must name an existing
`model_registry_id` with the same exact model ID and revision. The importer uses
deterministic campaign, case, and run IDs. Replaying the identical frozen bundle
is idempotent; changing an identity or terminal outcome is rejected by receipt
validation or the append-only repository. Every planned page outcome is stored,
including failures. `TIMEOUT`, `UNSUPPORTED`, and generic `FAILED` outcomes map
to the database's `PROVIDER_ERROR` terminal class while the exact external
status remains in `output_units.external_status`.

The database campaign state `FINALIZED` means that this imported campaign is
complete and immutable. It does not mean externally attested execution,
scientific acceptance, claim approval, or permission to publish. Those decisions
remain downstream review responsibilities, and public release still requires the
independent hash-bound founder approval described above.

```powershell
py -3.13 -m research.model_arena_v1 import `
  --preregistration <completed>/preregistration.json `
  --corpus <completed>/corpus.jsonl `
  --runs <completed>/runs.jsonl `
  --layers <completed>/layers.jsonl `
  --artifact-root <completed> `
  --database-url sqlite+aiosqlite:///work/arena.db `
  --output work/arena-v1-imported-bundle
```

After the transaction commits, the same validated inputs are compiled into the
ordinary release bundle. Import success is therefore independent of public
release: without real rights, reviews, sufficient corpus, and an external
approval receipt, its manifest remains withheld.

## Reproduce the synthetic fixture

The example has three synthetic Arena cases and one calibration case. It is a
schema fixture only, never the promised 1,000-page Arena or 100-page calibration
set.

```powershell
py -3.13 -m research.model_arena_v1.examples.fixture_inputs work/arena-v1-fixture
py -3.13 -m research.model_arena_v1 validate `
  --preregistration work/arena-v1-fixture/preregistration.json `
  --corpus work/arena-v1-fixture/corpus.jsonl `
  --runs work/arena-v1-fixture/runs.jsonl `
  --layers work/arena-v1-fixture/layers.jsonl
py -3.13 -m research.model_arena_v1 export `
  --preregistration work/arena-v1-fixture/preregistration.json `
  --corpus work/arena-v1-fixture/corpus.jsonl `
  --runs work/arena-v1-fixture/runs.jsonl `
  --layers work/arena-v1-fixture/layers.jsonl `
  --output work/arena-v1-fixture-bundle
```

The export command exits `3` for this fixture because public release is
withheld. Its `SYNTHETIC_FIXTURE` evidence class is permanent evidence of its
origin: renaming `study_kind` or `study_id` cannot promote it. A production
preregistration must configure the exact intended Arena
composition (v1: Public 400 + DART/SEC 300 + Failure Zoo 200 + Clean Control
100), a separate 100-case calibration corpus, at least three repeats, current
actual price receipts, publication rights, and IP/statistical/claim review
hashes with local evidence paths. A digest string alone does not prove that a
review, source, license, or price snapshot exists: release evaluation reopens
the bytes and compares their SHA-256. Missing evidence is an error or a named
withholding reason; counts are never padded with invented pages.

## Test

```powershell
py -3.13 -m pytest research/model_arena_v1/tests -q
py -3.13 -m ruff check research/model_arena_v1
py -3.13 -m mypy research/model_arena_v1
```
