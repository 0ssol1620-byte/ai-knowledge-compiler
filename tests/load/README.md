# Opt-in nonproduction scale tests

Nothing in this directory runs automatically. `profiles.json` is the canonical
v4 readiness catalog and `scale-profile.schema.json` plus
`validate_profiles.py` make the exact dimensions machine-checkable. The
catalog covers:

- 5,000-file collection manifest;
- interrupted 10 GiB collection upload and new-process resume;
- 30,000-page preflight;
- 1,000-page processing UI, 10,000-block workspace, and 5,000-node graph;
- 1,000 SSE clients, 100 uploads, 10,000-page enqueue, mixed-tenant fairness,
  and a 100-export burst.

Validate the declarations without executing a load test:

```powershell
py.exe tests/load/validate_profiles.py
py.exe tests/load/validate_profiles.py --print-command collection_manifest_5000
py.exe tests/load/validate_profiles.py --print-command collection_resume_10gib
```

Every profile requires a dedicated synthetic tenant and:

```text
AKC_LOAD_CONFIRM=NONPRODUCTION_LOAD_ONLY
```

Remote execution also requires HTTPS, `AKC_ALLOW_REMOTE_SYNTHETIC=true`, and
an exact `AKC_ALLOWED_REMOTE_ORIGINS` match. Direct object-storage targets used
by the 10 GiB harness additionally require exact origins in
`AKC_ALLOWED_UPLOAD_ORIGINS`. Wildcards, suffix matches, customer data,
production targets, automatic capacity provisioning, and automatic provider
spend are forbidden.

## Exact v4 profiles

### 5,000-file manifest

The k6 adapter creates one disposable collection and source root, posts exactly
5,000 unique 1 KiB metadata entries, verifies the returned count and upload-only
state, and deletes the collection. It does not transfer file bodies.

```powershell
k6 run tests/load/k6-collection-manifest.js
```

Required fixture variables are listed by:

```powershell
py.exe tests/load/validate_profiles.py --print-command collection_manifest_5000
```

### Interrupted 10 GiB resume

`resume-10gib.mjs` uses ten unique synthetic 1 GiB `.txt` files because the
Team limit is 1 GiB per file. The fixture manifest must be JSON with
`schema_version=1.0.0`, `synthetic=true`, `customer_data=false`,
`total_bytes=10737418240`, and ten entries containing a manifest-relative
`path`, collection `relative_path`, `size_bytes=1073741824`,
`content_type=text/plain`, and the full file SHA-256. The adapter rehashes each
file before transfer.

The first process uploads exactly 5 GiB, pauses the collection, persists only
the opaque browser resume token and non-secret IDs in a mode-0600 state file,
and exits successfully at the expected interruption boundary. A new process
must perform the resume phase:

```powershell
node tests/load/resume-10gib.mjs --phase interrupt
node tests/load/resume-10gib.mjs --phase resume
```

The resume phase requires `AKC_CLEANUP_ON_SUCCESS=true`, verifies token rotation
and exact completed byte/file counts, deletes the disposable collection, emits
a raw observation, and removes the resume-token state file. An object-store
inventory is still required to prove that orphaned multipart uploads are zero;
the harness does not infer that metric.

### 30,000-page preflight

The preflight profile consumes a release-owned fixture attestation rather than
creating a costly corpus. The attestation must bind the collection ID, exactly
30,000 known pages, synthetic/no-customer-data declarations, and SHA-256 values
for both fixture and source manifest.

```powershell
k6 run tests/load/k6-preflight-30000.js
```

The k6 call enforces the 15-minute precise-estimate budget. The required
two-minute fast-estimate metric must come from stage telemetry bound to the
same run; a single request duration cannot substitute for that metric.

### Browser scale interface

The browser adapter is deliberately read-only and fails closed until the real
nonproduction UI exposes `window.__AKC_SCALE_EVIDENCE__` with all of:

```json
{
  "ready": true,
  "profile": "processing_ui_1000_pages",
  "target_revision": "40-character deployment revision",
  "fixture_sha256": "sha256:...",
  "dataset": { "pages": 1000 },
  "virtualization": {}
}
```

The 10,000-block and 5,000-node profiles use the same interface with
`dataset.blocks=10000` or `dataset.graph_nodes=5000`. The adapter requires a
real authenticated Playwright storage state and a fixture attestation bound to
the exact target origin, route, deployment revision, deployment-evidence hash,
and fixture hash. It records readiness time, JS heap, DOM nodes, and long tasks.

```powershell
node tests/load/browser-scale-probe.mjs --profile processing_ui_1000_pages
node tests/load/browser-scale-probe.mjs --profile workspace_10000_blocks
node tests/load/browser-scale-probe.mjs --profile graph_5000_nodes
```

No application route currently gains a release claim merely because this
interface exists. Missing UI evidence, a mismatched count/hash/revision, or an
unsupported target is a hard failure.

## Existing concurrency, fairness, and export profiles

The existing adapters remain versioned in the same catalog:

```powershell
k6 run tests/load/k6-sse.js
k6 run tests/load/k6-journey.js
k6 run tests/load/k6-enqueue.js
k6 run tests/load/k6-fairness.js
k6 run tests/load/k6-export.js
```

For `upload_100`, set the catalog-bound `AKC_VUS=100`,
`AKC_ITERATIONS=100`, and
`AKC_SYNTHETIC_CONFIRM=NONPRODUCTION_SYNTHETIC_ONLY`; smaller journey runs are
diagnostics, not the named profile.

## Fail-closed evidence

`scale-evidence.schema.json` records immutable harness/catalog hashes, verified
deployment revision evidence, the exact-origin allowlist hash/match, synthetic
fixture hashes and dimensions, raw result hashes, required observations,
cleanup receipts, and explicit nonproduction confirmation. Generate an honest
unexecuted template with:

```powershell
py.exe tests/load/validate_profiles.py --emit-not-run graph_5000_nodes artifacts/graph-not-run.json
```

That template is valid as a status record but intentionally fails gate
validation. After an authorized run, validate a completed receipt with:

```powershell
py.exe tests/load/validate_profiles.py --evidence artifacts/scale-evidence.json
```

The command fails unless status is `passed`, every required metric exists and
passes, target revision evidence is independently verified, the fixture binds
the exact catalog dimensions, current catalog/script hashes match, and cleanup
is complete for mutating profiles. Even an admissible receipt remains
nonproduction diagnostic evidence: it cannot assert a production SLO or close
a release gate by itself.
