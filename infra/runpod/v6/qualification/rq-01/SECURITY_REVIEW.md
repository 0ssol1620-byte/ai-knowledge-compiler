# RQ-01 — Security / Secret Review (D8)

Scope: every file newly created in this round (D1-D7) under runtime
qualification for `paddleocr-vl-1.6-fastdeploy-c8` and `mineru-3.4.4-vlm-c1`.
Read-only review — no D1-D7 file was modified to produce this report.

## Files reviewed

Enumerated programmatically (the same enumeration `test_runtime_qualification_secrets.py`
performs via `Path.rglob`), 24 files total (this list also picked up
`KNOWN_ISSUES.md`, added to `rq-01/` by a parallel agent while this review was
in progress — the `rglob`-based discovery caught it automatically without
needing to hardcode its name, and it was reviewed like every other file
below):

- `infra/runpod/v6/qualification/rq-01/fixtures/generate_fixture.py`
- `infra/runpod/v6/qualification/rq-01/fixtures/manifest.json`
- `infra/runpod/v6/qualification/rq-01/fixtures/rq-01-smoke-001.png`
- `infra/runpod/v6/qualification/rq-01/lineage.json`
- `infra/runpod/v6/qualification/rq-01/README.md`
- `infra/runpod/v6/qualification/rq-01/KNOWN_ISSUES.md`
- `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/backend-config.yaml`
- `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/Dockerfile`
- `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/start-ssh.sh`
- `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/verify-runtime.sh`
- `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/Dockerfile`
- `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/README.md`
- `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/start-ssh.sh`
- `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/verify-runtime.sh`
- `.github/workflows/baked-confirmatory-images.yml`
- `infra/runpod/v6/runtime_smoke_baseline.py`
- `infra/runpod/v6/build_runtime_qualification.py`
- `benchmark/tests/v6/test_confirmatory_image_workflow.py`
- `benchmark/tests/v6/test_confirmatory_pod_controller.py`
- `benchmark/tests/v6/test_confirmatory_runtime_images.py`
- `benchmark/tests/v6/test_frozen_science_boundary.py`
- `benchmark/tests/v6/test_runtime_qualification_builder.py`
- `benchmark/tests/v6/test_runtime_qualification_fixture.py`
- `benchmark/tests/v6/test_runtime_qualification_lineage.py`

(`rq-01-smoke-001.png` is binary and was scanned as raw bytes, not text —
see Check 6.)

## Secret-shaped pattern used for this review

Reproduced from `research/tavonel_recovery_eval_v1/runpod_qualification.py:225-229`
(`_redacted_json`), read in place, not modified:

```python
def _redacted_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    if re.search(r"(?i)(bearer\s+|runpod_b|api[_-]?key|authorization)", raw):
        raise QualificationRefused("secret-like material would enter a local receipt")
    return raw
```

The exact regex checked against every file above:
`r"(?i)(bearer\s+|runpod_b|api[_-]?key|authorization)"`.

Separately, every file was scanned for 40+ character contiguous hex strings,
and every hit was cross-checked against the known, already-documented hash
list for this round (weights/source revisions in `lineage.json`, artifact and
runner-pin `sha256` values in the Dockerfiles/`lineage.json`, and the public
pinned-action commit SHAs in the workflow file).

## Summary table

| File / area | What was checked | Result |
|---|---|---|
| `research/tavonel_recovery_eval_v1/runpod_qualification.py:211-229` (read-only, not modified) | Confirmed exact `_redacted_json` regex before using it as the audit pattern | PASS |
| All 23 text files listed above (excludes the binary PNG) | Grepped for `(?i)(bearer\s+\|runpod_b\|api[_-]?key\|authorization)` | FLAG (see below) — resolved as false positive, not a leak |
| All 23 text files listed above | Grepped for 40+ char hex strings; every hit cross-checked against documented hashes | PASS — every hit is a documented sha256/git-revision/pinned-action-SHA, or a synthetic test `dataset_revision` fixture value |
| `infra/runpod/v6/qualification/rq-01/KNOWN_ISSUES.md` | Secret pattern + 40+ char hex scan | PASS — zero matches of either kind |
| `.github/workflows/baked-confirmatory-images.yml` | `secrets.*` usage — only `secrets.GITHUB_TOKEN`? | PASS |
| `.github/workflows/baked-confirmatory-images.yml` | Secret ever echoed to logs? | PASS |
| `.github/workflows/baked-confirmatory-images.yml` | `persist-credentials: false` on checkout? | PASS (line 38, already present) |
| `infra/runpod/v6/runtime_smoke_baseline.py` | `os.environ`, `getenv`, `httpx`, `requests`, `RunPodPodClient`, `PodCreateSpec(` | PASS — zero matches |
| `infra/runpod/v6/build_runtime_qualification.py` | same markers | PASS — zero matches |
| All 23 text files | Hardcoded env-specific credential-file paths (`D:\Github_API.txt`, `Runpod_B`, `CREDENTIAL_FILE`, etc.) | PASS — zero matches |
| `infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/Dockerfile` | ARG/ENV values are model revisions/hashes/paths only, no credential | PASS |
| `infra/runpod/v6/images/mineru-3.4.4-vlm-c1/Dockerfile` | same | PASS |
| `infra/runpod/v6/qualification/rq-01/fixtures/generate_fixture.py` + both Dockerfiles' `COPY` of the fixture | Fixture PNG is only ever copied as a file / read as bytes — never executed or interpreted as code | PASS |

## Detail: the one pattern hit (resolved, not a leak)

`benchmark/tests/v6/test_confirmatory_pod_controller.py` matches
`api[_-]?key` (case-insensitive) at lines 40, 476, 549, 585, 619, 633, 647.
Every hit is the identifier `FAKE_API_KEY` / the keyword argument `api_key=`
used to construct `RunPodPodClient` in a test, defined at line 40:

```python
FAKE_API_KEY = "fake-test-key-not-a-real-runpod-credential"
```

This is a synthetic placeholder string, not real credential material, and
`httpx.MockTransport` is used for the client's transport — no real network
call is made. Two of the tests in this file
(`test_preflight_receipt_has_no_secret_material`,
`test_execute_success_receipt_has_no_secret_material`) exist specifically to
assert `FAKE_API_KEY` never appears in a serialized receipt. This is a
security-positive test, not a leak, and is not downgraded further in this
report. No fix applied — nothing to fix.

## Detail: 40+ character hex strings

23 distinct strings matched. All resolve to one of:

- Model/source **weights revisions** and **artifact sha256** values recorded
  in `infra/runpod/v6/qualification/rq-01/lineage.json` and repeated
  identically in the two Dockerfiles (e.g. `66317acc4c9fc17bd154591ce650735cd2855f3e`,
  `40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53`,
  `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7`,
  `bff20d4ae2bf202df9f45284b4d43681555a97ed`,
  `1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84`,
  `2661c7c0ef5c613e8f93c6e93b2e052399f0f854`).
- **Runner-pin sha256 values** for the frozen `benchmark/runpod_eval/*.py`
  files, identical in `lineage.json` and the Dockerfiles' inline `check()`
  calls (`414b5b876f71c527e0c2ac3baadde37dca53fb9d49d5eb270501c5ba71c8f120`,
  `497bada5cba15af8d45a9aca243b58445b975fd84f11ac8d9863e897c51ba310`,
  `05559dba43b6c250dcf8f077600f48e72dfd0238af3c137836e32d7667a34372`,
  `e7d84e289d9ea1b123d4451243a185950af3bf236520eb92c54ea2ba80387c77`).
- The **FastDeploy compatibility patch** before/after hashes in the PaddleOCR
  Dockerfile (`b50570cb...`, `3be4e76c...`).
- `candidate_registry_sha256` / `protocol_sha256` in `lineage.json`
  (`4a22d8c5...`, `c8238f96...`), and the fixture manifest's own image
  `sha256` (`d6eb3433...` in `manifest.json`, matching the PNG's real digest).
- The base image digest `263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84`,
  reused verbatim from existing pinned provisioning scripts elsewhere in the
  repo (see the Dockerfile comments citing `tools/release/provision_folynta_*`).
- **Pinned third-party GitHub Action commit SHAs** in the workflow file
  (`actions/checkout@11d5960a...`, `actions/setup-python@a26af69b...`,
  `anchore/sbom-action@df80a981...`, `aquasecurity/trivy-action@ed142fd0...`,
  `actions/upload-artifact@ea165f8d...`) — these are public git commit hashes
  used for supply-chain pinning, not secrets.
- Two **synthetic test fixture `dataset_revision` values**
  (`f5f559bddf50e36f7f9899d842d0006f13ce8afc`,
  `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`) in
  `benchmark/tests/v6/test_confirmatory_pod_controller.py` lines 133/138/394/414 —
  git-revision-shaped placeholder strings for test manifests, not credentials.

No hit is an unaccounted-for, unexplained, or credential-shaped literal.

## Check-by-check verdict (matches the 6 categories in the task)

1. `_redacted_json` regex sweep over all new files — **PASS** (one pattern
   hit, resolved above as a fake-credential test identifier, not a leak).
2. Workflow secret usage — **PASS**. Only `secrets.GITHUB_TOKEN` is
   referenced (`.github/workflows/baked-confirmatory-images.yml:104`); the
   token is piped directly into `docker login --password-stdin` and never
   echoed to a log line; `persist-credentials: false` is present on the
   checkout step (line 38) — this was independently re-verified by reading
   the live file, not taken on the prior implementer's word.
3. D6 modules never touch `os.environ`/`getenv`/`httpx`/`requests`/
   `RunPodPodClient`/`PodCreateSpec(` — **PASS**, independently re-verified
   with `grep` returning zero matches against both files, not merely cited
   from the D6 implementer's own claim (also encoded as an automated test in
   `test_runtime_qualification_secrets.py::test_d6_module_has_no_environment_network_or_client_markers`).
4. No hardcoded environment-specific credential-file path
   (`D:\Github_API.txt`, `Runpod_B`, etc.) in any new file — **PASS**, zero
   matches.
5. No credential embedded as a Dockerfile ARG/ENV in either new image — only
   model revisions, artifact hashes, and filesystem paths — **PASS**.
6. The D2 synthetic smoke fixture is passive image data everywhere it is
   referenced (`COPY` into the image filesystem in both Dockerfiles, raw
   byte hashing in `test_runtime_qualification_fixture.py`) — no new code
   path executes or interprets its content as anything but an image — **PASS**.

## Overall result

**PASS.** No secret or credential leakage found in any new D1-D7 artifact
from this round.
