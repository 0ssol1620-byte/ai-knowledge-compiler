# V4 Licence and Supply-Chain Inventory

*Masterplan v4.0 PHASE 0 deliverable. Written 2026-08-10 against
`5999baf8175288f34fb476b4e0b880037239c60c`.*

PHASE 0's exit gate is one sentence: **no production-blocked licence component
silently active.** This file answers it with the registry and pin data, not with
an assurance.

Verdict: **gate passes.** Every model in the registry sits at
`traffic_percent: 0` with an `*_unverified` internal-validation status, so no
licence-unresolved weight can reach a request. Two recording gaps and one stale
document are named below; neither puts an unlicensed component in a production
path.

---

## 1. Model, weight and dataset licences

Registry: `infra/model-registry/models.yaml` (`registry_version: 1.0.0`).
Validator: `infra/model-registry/validate_registry.py`.

Declared policy: `floating_revisions_forbidden`,
`rollout_requires_internal_benchmark`, `external_processing_default: false`,
production statuses `champion | canary | fallback`.

| Provider key | Weight licence | Dataset licence | Traffic % | Internal status |
|---|---|---|---:|---|
| `local_mock_parser` | not_applicable | not_applicable | 0 | local_test |
| `paddleocr_vl_1_6` | review_required | review_required | 0 | candidate_unverified |
| `hpd_parsing_1b` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `unlimited_ocr` | review_required | review_required | 0 | candidate_unverified |
| `infinity_parser2_flash` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `infinity_parser2_pro` | Apache-2.0 | review_required | 0 | offline_teacher_unverified |
| `deepseek_ocr_2` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `olmocr_2` | snapshot_required | review_required | 0 | candidate_unverified |
| `mineru` | review_required | review_required | 0 | optional_provider_unverified |
| `qwen3_5_4b` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `qwen3_5_9b` | Apache-2.0 | review_required | 0 | candidate_unverified |
| `qwen3_6_precision` | Apache-2.0 | review_required | 0 | precision_shadow_unverified |
| `gemma4_12b_challenger` | Apache-2.0 | not_disclosed_review_required | 0 | public_checkpoint_discovered_internal_attestation_required |
| `qwen3_embedding_0_6b` | snapshot_required | review_required | 0 | candidate_unverified |
| `qwen3_reranker_0_6b` | snapshot_required | review_required | 0 | candidate_unverified |
| `mistral_ocr_4` | provider_terms | provider_terms | 0 | external_opt_in_unverified |

**Production-active with unresolved licence: none.** 16/16 at zero traffic.

### Why 14 of 16 have `upstream_revision: null` and that is not a policy breach

`floating_revisions_forbidden: true` reads at a glance like every row needs a
pin. The validator requires an exact 40–64 hex revision only when
`traffic > 0` or the status is `champion | canary | fallback | shadow`
(`validate_registry.py:69-83`), and separately rejects any literal floating tag
(`latest`, `main`). A candidate that has never been routed has no revision
because **nothing has been downloaded or attested yet** — `gemma4_12b_challenger`
carries `checkpoint_downloaded: false` explicitly and the validator fails if that
flips without review.

This is fail-closed: a null revision cannot be promoted, because promotion needs
the pin the promotion check demands. Recorded here so a future reader does not
"fix" the nulls by pinning revisions nobody verified.

### What the campaign actually ran

`docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md` measures **MinerU 3.4.4** plus the
recovery runtime. `mineru` is `review_required / review_required` in the
registry. The benchmark evidence is a *research* result on public corpora, not a
statement that MinerU is cleared for customer production. Nothing in the repo
routes to it. Clearing it is Phase 3 work (capability + licence receipt), and no
public claim depends on the clearance.

---

## 2. Container images

Every tracked Dockerfile is digest-pinned. Verified against
`infra/supply-chain/verified-pins.json` (`verified_at: 2026-07-30`):

| Image | Pin record | Used by |
|---|---|---|
| `node:24.18.0-bookworm-slim` | OK | `apps/web/Dockerfile` |
| `gcr.io/distroless/nodejs24-debian13:nonroot` | OK | `apps/web/Dockerfile` runtime |
| `python:3.13-slim-bookworm` | OK | api, scheduler, url-fetcher, cpu-document |
| `python:3.12-slim-bookworm` | OK | gpu-hpd, gpu-knowledge, gpu-parser, gpu-unlimited (local stage) |
| `nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04` | OK | all four GPU workers (production stage) |
| `vllm/vllm-openai` | **UNRECORDED** | `infra/runpod/v6/images/ovisocr2-m1/Dockerfile` |

**S-1 — `vllm/vllm-openai` is digest-pinned in the Dockerfile
(`sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05`) but
absent from `verified-pins.json`.** The digest is immutable, so this is not a
mutable-tag exposure; it is an unverified pin — nobody hashed the registry
manifest bytes and recorded the check the README describes. It also carries an
Apache-2.0 upstream whose bundled CUDA/NVIDIA components have their own terms.
**Owed before any RunPod v6 image is promoted, not before Phase 1.**

`grafana/k6:0.57.0` and `pgvector/pgvector:pg17` are pinned but not referenced by
a tracked Dockerfile — they are CI/compose-side and harmless as surplus records.

### Toolchain version skew worth knowing

| Surface | Version | Note |
|---|---|---|
| CI Python matrix | 3.12, 3.13 | `.github/workflows/ci.yml` |
| Local `.venv` | 3.13.0 | this baseline was measured on 3.13 |
| Service images | 3.13 | api / scheduler / url-fetcher / cpu-document |
| GPU worker local stage | 3.12 | intentional — CUDA wheel availability |
| CI Node | 22 | `.github/workflows/ci.yml` |
| Local Node | 22.14.0 | matches CI |
| `apps/web` image | Node 24.18.0 | **image is a major ahead of CI** |
| Vercel project | `nodeVersion: 24.x` | matches the image, not CI |

**S-2 — the web runtime is built and deployed on Node 24 while CI tests it on
Node 22.** Not a licence issue and not new in v4, but it means the tested
runtime is not the shipped runtime. Cheap to resolve (align CI to 24); recorded
rather than fixed here because PHASE 0 does no feature or config change.

Nine open Dependabot branches propose CUDA 13.3.1, Python 3.14 and Node 26 base
images. None is merged. Each is a supply-chain change that must repeat the
manifest verification in `infra/supply-chain/README.md`, not a version bump.

---

## 3. GitHub Actions

All action references are 40-hex SHA-pinned with a version comment.

| Action | Status |
|---|---|
| `actions/checkout@v4.4.0` | OK |
| `actions/setup-python@v5.6.0` | OK |
| `actions/setup-node@v4.4.0` | OK |
| `actions/upload-artifact@v4.6.2` | OK |
| `actions/dependency-review-action@v4.9.0` | OK |
| `anchore/sbom-action@v0.17.9` | OK |
| `aquasecurity/trivy-action@v0.36.0` | OK |
| `easimon/maximize-build-space@v10` | OK |
| `hashicorp/setup-terraform@v3.1.2` | OK |
| `github/codeql-action/{init,analyze,upload-sarif}@v3.37.3` | **key mismatch, SHA correct** |

**S-3 — the pin record keys `github/codeql-action@v3.37.3`; the workflows use the
three sub-action paths.** The SHA in the workflows
(`4187e74d05793876e9989daffde9c3e66b4acd07`) is byte-identical to the recorded
one, so nothing unverified runs. It is a record-precision defect: an automated
coverage check keyed on exact strings reports three unrecorded actions. Fix when
`verified-pins.json` is next revised.

---

## 4. Python and JavaScript dependencies

- Root and GPU runtimes carry separate `uv.lock` files. CI runs
  `uv sync --locked` then `uv pip check`. A pinned `uv==0.12.0` is the only
  pre-lock install permitted.
- `pnpm-lock.yaml` is committed; CI installs `--frozen-lockfile` and warns loudly
  if the lockfile is absent.
- `pnpm@11.9.0` is declared in `packageManager` and resolved through corepack.

`DEPENDENCY_LICENSES.md` (reviewed 2026-08-07) lists MIT / Apache-2.0 / SIL OFL
1.1 across the bundled set. One entry, the local "UI UX Pro Max" skill, is marked
*License metadata inconsistent* and scoped **internal research only, not
bundled** — correct handling, and it must stay unbundled.

**S-4 — `DEPENDENCY_LICENSES.md` is stale on 3D.** It states that `three`,
`@react-three/fiber`, `@react-three/drei` were removed and "the hero now ships
the poster image alone." `CLAUDE.md` reversed that on 2026-08-09 and v4 PART 15
requires the cinematic hero. The register describes a decision that no longer
holds. The dependencies are genuinely absent from the tree today, so the register
is accurate about *now* and wrong about *intent*. It must be updated in the same
change that reintroduces R3F (Phase 13), together with the §22 script-budget
re-derivation `CLAUDE.md` already requires.

---

## 5. Secrets and environment

`.env.example` declares **305 names, values absent** — the APPENDIX B principle
holds. Mapping APPENDIX B to what exists:

| APPENDIX B name | Repository reality |
|---|---|
| `DATABASE_URL` | `AKC_DATABASE_URL` ✓ |
| `R2_ACCOUNT_ID`, `R2_BUCKET_*`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | `AKC_S3_*` against `AKC_S3_ENDPOINT_URL`, with **separate credentials per bucket** (source/derived/working/audit) — a stronger split than APPENDIX B asks for. R2 is the S3 endpoint; this is naming, not a gap |
| `CLOUDFLARE_QUEUE_*` | **absent** — queueing is a PostgreSQL outbox (`services/scheduler`, migrations 0002/0008). See conflict C-2 in the migration matrix |
| `RUNPOD_API_KEY` | `AKC_RUNPOD_API_KEY` ✓ |
| `RUNPOD_ENDPOINT_*` | registry-side, `infra/runpod/` ✓ |
| `OIDC_*` | 13 `AKC_*OIDC*` names ✓ (migration 0019) |
| `GOOGLE_DRIVE_OAUTH_*`, `GCS_SERVICE_ACCOUNT_REF`, `MICROSOFT_GRAPH_OAUTH_*` | **absent** — Phase 14 |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | **absent by design** — `AKC_PAYMENT_PROVIDER` + `AKC_PAYMENT_WEBHOOK_SECRET` are provider-agnostic. See conflict C-1 |
| `OTEL_EXPORTER_*` | `AKC_OTEL_EXPORTER_OTLP_ENDPOINT` ✓ |
| `SIGNING_KEY_REF` / COSIGN policy | **absent** — no signing key or cosign policy in the tree |

**S-5 — no image signing exists.** `security.yml` runs SBOM (`anchore/sbom-action`)
and scanning (`trivy`, `codeql`) but nothing signs or verifies a signature.
PART 17.12 and PART 24.13 require it. Due at Phase 17, needed earlier if an image
is promoted to a customer-facing deployment.

**S-6 — a real secrets file is present in the working tree.** `.env` (2,932
bytes) sits at the repository root. It is git-ignored and not tracked
(`git ls-files` does not list it), so nothing has leaked through version control.
Recorded because PHASE 0 is where the secret inventory is supposed to be honest:
rotation and a managed store are still owed (PART 17.6), and local `.env` files
are the usual way that debt turns into an incident.

---

## Findings summary

| ID | Finding | Severity | Due |
|---|---|---|---|
| S-1 | `vllm/vllm-openai` digest not in `verified-pins.json` | Medium | before any RunPod v6 image promotion |
| S-2 | Web ships Node 24, CI tests Node 22 | Medium | Phase 1 CI revision |
| S-3 | codeql pin recorded under a key the workflows do not use | Low | next `verified-pins.json` revision |
| S-4 | `DEPENDENCY_LICENSES.md` stale on the 3D reversal | Low | Phase 13, with the R3F reintroduction |
| S-5 | No image signing / cosign policy | Medium | Phase 17, earlier if promoted |
| S-6 | Untracked `.env` present locally; no managed secret store | Medium | Phase 17 |

None of these blocks PHASE 0's exit gate, which asks only whether a
production-blocked licence component is silently active. None is.
