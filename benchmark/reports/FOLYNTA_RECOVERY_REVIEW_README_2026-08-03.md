# FOLYNTA recovery benchmark review bundle

## What is proven

- The masterplan's 18 failure codes are detected and routed through exact
  minimum-scope recovery strategies in the frozen contract campaign.
- Recovery requires an independently identified model family and expands only
  one scope level after a failed verified attempt.
- Only the repaired object's lineage descendants are replayed.
- Adaptive repetition uses one full run plus three stratified audits, expanding
  to three successful full runs only for finalists, drift, or runtime failure.
- The frozen audits contain 128 inputs per suite. Stable candidates perform
  6,284 page inferences instead of 15,396, a 59.1842% reduction.
- Official evaluator adapters cover OmniDoc 5 types, all 26 ParseBench types
  over 169,011 assertions, and all six olmOCR types over 7,019 assertions;
  unknown future types fail closed.
- OmniDocBench 1,651, ParseBench 2,078, and olmOCR-Bench 1,403 official source
  cases were all staged and independently re-hashed: 5,132/5,132 inputs and
  5,368,250,915 bytes.
- Ground truth and benchmark rules remain evaluator-only.
- The final repository test run passed 1,664 tests.
- A scoped GHCR workflow now builds only the frozen Ovis image and emits a
  source/image/SBOM/scan-bound build receipt that is forbidden from marking
  paid capacity ready.

## What is not yet proven

No real public-model accuracy or recovery uplift is claimed. There is no
qualified immutable GPU image, Docker is unavailable on the local host, live
RunPod refreshes report zero endpoints and zero pods, no provider cost ceiling
has been approved, and every required registry candidate remains
promotion-ineligible. The other three current recipes lack complete stored
image-build inputs. Three live Ovis GHCR workflow attempts failed closed: the
final two exhausted standard GitHub runner storage during the vLLM image build
despite exact tool-cache cleanup and duplicate-attestation removal. A
post-attempt package inventory found zero matching complete Ovis packages. The
locally stored RunPod credential was used only for
read-only inventory and billing refreshes; it was not copied into this bundle.
The 18/19 synthetic uplift validates the recovery contract only.

## Primary evidence

- `benchmark/reports/FOLYNTA_RECOVERY_BENCHMARK_IMPLEMENTATION_2026-08-03.md`
- `benchmark/reports/generated/folynta-public-core-source-manifest-verification-2026-08-03.json`
- `benchmark/reports/generated/folynta-public-core-staged-input-verification-2026-08-03.json`
- `benchmark/reports/generated/folynta-recovery-fault-injection-golden-2026-08-03.json`
- `benchmark/v6/cohorts/recovery-fault-injection-golden.json`
- `.github/workflows/baked-model-image.yml`
- `infra/runpod/v6/image_build_receipt.py`
- `benchmark/reports/generated/folynta-ovis-ghcr-build-attempts-2026-08-03.json`

The ZIP includes all source and inference-input manifests but intentionally
excludes the 5.37 GB rendered PNG payload and the 2.43 GB acquired public
datasets. Those remain under ignored local dataset directories and contain no
credentials.

## Local verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q packages/parallel-runtime/tests services/scheduler/tests benchmark/tests/v6 benchmark/runpod_eval tools/release/test_run_folynta_recovery_campaign.py
.\.venv\Scripts\python.exe benchmark/runpod_eval/verify_public_core_source_manifests.py --acquisition-receipt benchmark/reports/generated/folynta-public-core-acquisition-live-2026-08-03.json --manifest-dir benchmark/reports/generated/public-core-manifests --output benchmark/reports/generated/folynta-public-core-source-manifest-verification-2026-08-03.json
.\.venv\Scripts\python.exe benchmark/runpod_eval/verify_staged_public_core_inputs.py --stage-root benchmark/datasets/staged-public-core --source-manifest-dir benchmark/reports/generated/public-core-manifests --output benchmark/reports/generated/folynta-public-core-staged-input-verification-2026-08-03.json
```
