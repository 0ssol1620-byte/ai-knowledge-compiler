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
