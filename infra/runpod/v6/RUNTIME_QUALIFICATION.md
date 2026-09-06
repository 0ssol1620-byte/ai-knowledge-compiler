# Runtime image qualification

## Build integrity is not runtime qualification

`.github/workflows/baked-model-image.yml` can build and publish the frozen
OvisOCR2 M1 image to GHCR on its scoped integration-branch push or a manual
dispatch, without creating GPU capacity. It emits a
`folynta.baked-image-build-integrity.v1` receipt binding the source tree,
Dockerfile, immutable image digest, model revision and artifact manifest,
SBOM, and vulnerability scan. The receipt requires zero critical
vulnerabilities and always records both:

- `runtime_qualification_required: true`; and
- `paid_capacity_ready: false`.

`infra.runpod.v6.image_build_receipt.BakedImageBuildReceipt` rejects any
build-only receipt that attempts to waive the GPU smoke or authorize paid
capacity. The workflow does not call the RunPod API. Its output is only the
prerequisite for the runtime qualification below.

A paid benchmark pod may use `qualification_state: READY` only when its spec
contains a complete `baked_runtime_qualification` object and
`baked_runtime_receipt_sha256` equals the canonical SHA-256 of that object.

The qualification is produced after the immutable image has been built and
pushed. It must bind:

- release commit and source-tree SHA-256;
- Dockerfile SHA-256 and immutable registry image digest;
- exact GPU and CUDA version;
- framework and model revision;
- downloaded model artifact SHA-256;
- baked runtime-file, SBOM, and vulnerability-scan SHA-256 values;
- zero critical vulnerabilities;
- frozen smoke input, prediction, and expected-output SHA-256 values; and
- passed identity, artifact, and smoke gates.

Required object shape:

```json
{
  "schema": "folynta.baked-runtime-qualification.v1",
  "generated_at": "2026-08-03T12:00:00Z",
  "source_commit": "40-lowercase-hex",
  "source_tree_sha256": "sha256:...",
  "dockerfile_sha256": "sha256:...",
  "image_digest": "registry/repository@sha256:...",
  "gpu_type": "NVIDIA A40",
  "cuda_version": "12.9",
  "framework_version": "vllm-0.22.1",
  "model_revision": "immutable-model-revision",
  "model_artifact_sha256": "sha256:...",
  "baked_runtime_file_sha256": "sha256:...",
  "sbom_sha256": "sha256:...",
  "vulnerability_scan_sha256": "sha256:...",
  "critical_vulnerability_count": 0,
  "smoke_input_sha256": "sha256:...",
  "smoke_prediction_sha256": "sha256:...",
  "smoke_expected_sha256": "sha256:...",
  "identity_verified": true,
  "model_artifact_verified": true,
  "smoke_passed": true,
  "passed": true
}
```

The smoke prediction must exactly match the frozen expected hash. Unknown or
missing fields, a hash-only claim, a different image/GPU/CUDA identity, any
critical vulnerability, or any failed gate keeps the pod spec non-runnable.

The current Ovis specs correctly remain `BUILD_REQUIRED`: their `image_name`
still identifies the upstream base image rather than a published, qualified
FOLYNTA baked image.

## Fail-closed build → qualification → READY sequence

There are three distinct capacities and they are intentionally not
interchangeable:

1. **Image builder** — `.github/workflows/build-ovis-runtime.yml` or the bounded
   `RunPodBuilderClient` may construct and publish an immutable GHCR image. A
   builder receipt is never runtime qualification and can never authorize
   benchmark inference.
2. **Qualification-only GPU** — `RunPodQualificationClient` may boot that exact
   immutable digest under an `AuthorizedSpendBudget`. Its contract explicitly
   sets `public_benchmark_inference_allowed: false`; only identity, artifact,
   CUDA/framework and deterministic frozen-smoke evidence belong here.
   The measured result is persisted as
   `folynta.runtime-verification-evidence.v1` and is combined with the immutable
   image-build receipt by `build_runtime_qualification`; the final qualification
   is therefore derived from both build-time and GPU-time evidence rather than
   assembled manually.
3. **Normal benchmark capacity** — only a passed
   `folynta.baked-runtime-qualification.v1` receipt may be bound to a
   `BUILD_REQUIRED` Pod spec. The binding is performed offline by
   `promote_build_required_spec` / `promote-runtime`, which rechecks image,
   GPU and CUDA identity and refuses manual READY overrides.

Example offline promotion after qualification has passed:

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6 `
  --receipt-out 'D:\evidence\runtime-promotion.json' `
  promote-runtime `
  --spec 'infra\runpod\v6\specs\folynta-ovis-m1-vllm-0.22.1-cu129-a40.json' `
  --qualification 'D:\evidence\runtime-qualification.json' `
  --ready-spec-out 'D:\evidence\folynta-ovis-m1-a40.READY.json'
```

`promote-runtime` is deliberately offline-only and rejects `--execute`. The
READY spec is written with exclusive-create semantics and contains the exact
qualification object plus its canonical receipt SHA-256. The separate promotion
receipt is secret-free. A failed smoke, GPU/CUDA mismatch, pre-existing READY
state, or pre-populated qualification material fails closed.

First build the qualification receipt from the immutable build evidence and the
qualification-only GPU evidence:

```powershell
.\.venv\Scripts\python.exe -m infra.runpod.v6.runtime_qualification `
  --build-receipt 'D:\evidence\baked-image-build.json' `
  --runtime-evidence 'D:\evidence\runtime-verification.json' `
  --output 'D:\evidence\runtime-qualification.json'
```

The producer requires the runtime image digest, model revision and model artifact
hash to match the build receipt exactly. Failed identity/artifact/smoke gates or
a prediction/expected smoke-hash disagreement are rejected. The output path is
exclusive-create so a later attempt cannot silently overwrite the evidence used
to promote a runtime.

### GitHub hosted-runner disk boundary observed on 2026-08-15

The two most recent immutable-image attempts established opposite sides of the
disk constraint rather than a model/runtime failure:

- Actions run `30860545607` exposed only about 32 GiB at `/var/lib/docker` and
  stopped at the then-55-GiB Docker-space preflight before a model image build;
- Actions run `31284919996` enlarged the Docker allocation but preserved only
  8 GiB for the runner root. GitHub's own worker then terminated with
  `No space left on device` while flushing its `_diag` log during checkout.

The local workflow now preserves 16 GiB root, 1 GiB temporary reserve and 1 GiB
swap, and requires both at least 10 GiB free root and 40 GiB free Docker storage
before starting a long build. These values are safety floors, not measured final
image-size claims. A remote run is still required to establish the actual build
peak and produce the immutable digest.
