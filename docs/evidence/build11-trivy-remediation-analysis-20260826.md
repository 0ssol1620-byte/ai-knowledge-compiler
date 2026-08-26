# Build #11 Trivy Remediation Analysis

> **Status:** Remediation staged on the isolated `agent/tavonel-ovis-release-evidence-v1` branch. It is **not** a release approval, does not authorize endpoint creation, and must pass a new immutable-image build, SBOM, strict Trivy scan, and integrity-receipt workflow before any further release-gate consideration.

## Evidence scope

This record analyzes the raw diagnostic artifact preserved by the failed `Baked model image` Build #11 workflow. The source run is `32957066565`, job `98140979430`, at commit `d9ff3b5e9ef01f8e7460177ac31b716028648a48`. The downloaded report is retained outside the repository at `/home/ubuntu/tavonel-evidence/build11-trivy/ovisocr2-m1.trivy.json`; its SHA-256 is `de4ffc5a83d716cd72cab7f4a33986d53a86f791ae81f6c5ea21703ba8a7f5f2`.

The report was produced at `2026-08-26T10:39:47.159191962Z` by Trivy `0.70.0` for the immutable image `ghcr.io/0ssol1620-byte/ai-knowledge-compiler/ovisocr2-m1@sha256:4021bece6c9ed19c7bf4057f2b1114437228d2464945d1dd2adf06f3b9c1d938`, whose detected operating system is Ubuntu `22.04`. The workflow keeps `severity: CRITICAL`, `ignore-unfixed: true`, `exit-code: "1"`, and a 20-minute timeout unchanged.[1]

## Exact strict-scan finding set

The scan contains **18 CRITICAL vulnerabilities**, all in the same installed OS package: `linux-libc-dev` version `5.15.0-181.191`. There are no CRITICAL Python or Rust binary findings in the report. The effective remediation floor is `5.15.0-187.197`, the highest fixed version required by any finding.

| CVE | Package | Installed version | Fixed version |
|---|---|---:|---:|
| CVE-2025-68263 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-23216 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-31402 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-31637 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43011 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43037 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43038 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43185 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43304 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-43501 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-45988 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-46043 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-46135 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-185.195` |
| CVE-2026-52955 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-186.196` |
| CVE-2026-52989 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-187.197` |
| CVE-2026-52993 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-186.196` |
| CVE-2026-53002 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-186.196` |
| CVE-2026-53215 | `linux-libc-dev` | `5.15.0-181.191` | `5.15.0-187.197` |

The report has three `Class: secret` target records for `/etc/ssh/ssh_host_ecdsa_key`, `/etc/ssh/ssh_host_ed25519_key`, and `/etc/ssh/ssh_host_rsa_key`, but each record contains only `Class` and `Target` fields. It contains **no secret finding object, rule identifier, line range, or raw match value**. Therefore, this artifact establishes no confirmed plaintext-secret exposure; it must not be described as a scanner false positive or as a confirmed leak. Raw secret values were intentionally neither emitted nor copied during this analysis.

## Implemented remediation

The affected Dockerfile now requests `linux-libc-dev` explicitly during `apt-get install` and verifies at build time that the installed package version is at least `5.15.0-187.197`. This both pulls a current repository candidate and makes an insufficient package version fail the image build. The strict scanner configuration was not weakened, no CVE was ignored, and no package was removed from the scanner scope.

| File | Change | Security effect |
|---|---|---|
| `infra/runpod/v6/images/ovisocr2-m1/Dockerfile` | Adds explicit installation of `linux-libc-dev` and a `dpkg --compare-versions` lower-bound assertion. | Prevents a build from succeeding with the vulnerable `5.15.0-181.191` package or any version below `5.15.0-187.197`. |
| `.github/workflows/baked-model-image.yml` | No change. | Retains immutable build/push, SBOM, CRITICAL-only Trivy gate, report artifact upload, and integrity receipt sequence. |

Static verification completed with `git diff --check` and boundary checks confirming that `5.15.0-187.197` and newer satisfy the assertion while `5.15.0-186.196` does not. A local container build was not performed because no Docker runtime is available in this execution environment. Accordingly, only the next GitHub Actions run can validate the final image package state and strict scan result.

## Required next evidence

The remediation is incomplete until a new immutable-image workflow runs from this isolated branch. That run must produce an image digest, SBOM, raw Trivy JSON, and build integrity receipt. The raw JSON must show zero CRITICAL findings and the workflow must complete successfully without changing scanner severity, `ignore-unfixed`, `exit-code`, or timeout. The resulting evidence still does not satisfy the separate model-license, benchmark, internal-validation, human-approval, fallback-recipe, RunPod qualification, or customer-data release gates.

No RunPod endpoint or pod was created; no customer bytes were dispatched; R2 customer intake remains disabled; and active-world promotion remains prohibited.

## References

[1]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/actions/runs/32957066565 "GitHub Actions — Baked model image #11"

## Remediation validation update — workflow run `32963410180`

The isolated-branch remediation was built and validated by a new `Baked model image` workflow run at commit `7161d3c05f2b8ee4725beb463cbaac85d976ac02`. The immutable image build, SBOM generation, **strict Trivy scan**, and diagnostic-report upload all completed successfully. The resulting image digest was `sha256:f1edcb0fd5ff8ac13d999e789cc7f725841074671bc3bafb4b0134864784090f`. Because the scan step retained the unchanged CRITICAL gate and completed successfully, this is evidence that the 18 previously reported CRITICAL findings are absent from that newly built image.[2]

The workflow still concluded failed because `Create build-only integrity receipt` invoked `python -m infra.runpod.v6.image_build_receipt`, which first imported `infra.runpod.v6.__init__`. That package initializer eagerly imported the HTTP client and required `httpx`, even though receipt generation has no HTTP, credential, or RunPod operation. This is an evidence-pipeline dependency-boundary failure, not a scanner failure. The branch now replaces eager convenience re-exports in both `infra.runpod.v6` and `benchmark.v6` with lazy exports. The receipt module's `--help` path and lightweight `build_receipt` import now execute without HTTP or YAML packages.

A final isolated-branch workflow rerun is required to produce the build integrity receipt and artifact. Until that successful run exists, the image remains **not release-approved** and all pre-existing RunPod, R2, and active-world promotion boundaries remain in force.

[2]: https://github.com/0ssol1620-byte/ai-knowledge-compiler/actions/runs/32963410180 "GitHub Actions — Baked model image remediation validation"
