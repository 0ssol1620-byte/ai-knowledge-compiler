# mineru-3.4.4-vlm-c1

Baked RunPod image definition for the `mineru-3.4.4-vlm` candidate
(`benchmark/v6/candidate-registry.yaml`), used as the research specialist lane
in `research/experiments/SEM-RISK-CONF-02`. This directory holds only static
build definitions -- no image is built or pushed by this round of work.

## RESEARCH COMPARISON ONLY -- not eligible for promotion

This image exists to produce comparator evidence for `SEM-RISK-CONF-02`. It is
**not** licensed, reviewed, or approved for commercial use, and its results
must not be used to promote MinerU commercially.

- `research/experiments/SEM-RISK-CONF-02/protocol.json` `forbidden` block sets
  `"mineru_commercial_promotion_from_this_experiment": true` -- this
  experiment's results may never be used for that purpose.
- `benchmark/v6/candidate-registry.yaml`'s `mineru-3.4.4-vlm` entry carries
  `license: { id: "AGPL-3.0-or-upstream-current", status: review_required,
  commercial_use: unknown }`. An unreviewed, unresolved license status is not
  a green light -- it is a standing block on commercial use until legal review
  closes it out.
- The Dockerfile in this directory carries the same notice as a `LABEL` on the
  built image (`folynta.research_comparator_only`,
  `folynta.commercial_promotion=forbidden`) so the constraint travels with the
  artifact, not just this document.

Consistent with the North Star's FTO rules: an OSS licence is not patent
freedom to operate, and being able to read this model's weights or source is
not the same as having a commercial right to use them.

## Two identities that must never be conflated

| | repository | revision | used for |
|---|---|---|---|
| Source | `opendatalab/MinerU` | `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7` | `git clone` + `checkout --detach` |
| Weights | `opendatalab/MinerU2.5-Pro-2605-1.2B` | `bff20d4ae2bf202df9f45284b4d43681555a97ed` | `snapshot_download` |

`artifact_sha256: sha256:1611a8892cc0e7e287d31c4a1b5af87652f0f6e4a3f80276b92b4c71f982de84`
corresponds to the **weights** revision, never the source revision. The
Dockerfile uses two separate `ARG`s (`SOURCE_REVISION`, `MODEL_REVISION`) and
never merges or swaps them.

## Base image

`runpod/pytorch@sha256:263d4144a3053f5125b04174e279d73b43768c5b798cd76c4871af7b737f0c84`
-- the same digest already pinned for MinerU provisioning in this repo at
`tools/release/provision_folynta_mineru_recovery_worker.ps1:148`. Torch and
torchvision are reinstalled at their pinned versions during the build, so the
base image's own torch (if any) is not relied upon.

## Pinned versions

Copied verbatim from `infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh`:
`torch==2.8.0`, `torchvision==0.23.0` (from the `cu128` PyTorch wheel index),
`accelerate==1.14.0`, `transformers==4.57.3`, `mineru-vl-utils==1.0.5`,
`MinerU[core]` (installed from the pinned source checkout, not a released
version). `MINERU_API_MAX_CONCURRENT_REQUESTS=1` is baked as an image `ENV`,
matching the same key documented in
`infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:76` (its
`runtime-identity.json` writer) and used consistently across
`tools/release/provision_folynta_mineru_recovery_worker.ps1:164`,
`tools/release/provision_folynta_mineru_retry_expansion.ps1:147`,
`infra/runpod/v6/bootstrap/run-mineru-3.4.4-public-core-worker.sh:22`, and
`research/tavonel_recovery_eval_v1/runpod_qualification.py:375`.

`/root/mineru.json` is written with the same shape (`models-dir`,
`model-source: "local"`, `config_version: "1.3.2"`) as
`infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh:39-45`.

## Known defect this image does not repeat

`benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh` (~lines 37-41) checks
`sha256sum --check` of a file's hash against the env var
`FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256`. That env var's actual meaning, per
`infra/runpod/v6/pod_client.py` (`PodCreateSpec.provider_payload`) and
`infra/runpod/v6/runtime_qualification.py`
(`BakedRuntimeQualification.receipt_sha256 = canonical_sha256(value)`), is the
canonical hash of the **entire qualification-receipt object**, not any one
file's hash. `verify-runtime.sh` in this directory bakes its own file-hash
constant at build time (`/opt/folynta/baked-runtime-receipt.sha256`) and
compares the recomputed file hash against that constant only. It reads
`FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256` (when set) solely to log it.

## Files

- `Dockerfile` -- build definition. Not built in this round.
- `start-ssh.sh` -- mirrors `infra/runpod/v6/images/ovisocr2-m1/start-ssh.sh` byte for byte.
- `verify-runtime.sh` -- install-free runtime verification: source-tree revision, model artifact manifest, package versions, baked-runtime-file hash (against the build-time constant, never `FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256`), and GPU/CUDA identity reporting.
