# FOLYNTA recovery benchmark implementation evidence — 2026-08-03

## Executive status

| Area | Status | Evidence boundary |
| --- | --- | --- |
| Adaptive repeat policy | PASS | Implemented and unit/integration tested locally |
| Failure detection evaluation | PASS | Exact type, localization, minimum scope, recovery decision, escalation, omission, and false-recovery gates |
| Official evaluator adapters | PASS | OmniDoc 5, ParseBench 26/169,011 assertions, olmOCR 6/7,019 assertions; unknown types fail closed |
| Independent recovery routing | PASS | Scheduler tests prove failed-family exclusion and alternate worker/family routing |
| Selective replay | PASS | Scheduler tests prove only impacted lineage descendants are replayed |
| Public-core acquisition | PASS | All locked Git LFS objects for OmniDocBench, ParseBench, and olmOCR-Bench are materialized |
| Public-core source inventory | PASS | 5,132 official source cases are revision/hash bound with evaluator-only index access |
| Public-core inference staging | PASS | All 5,132 cases rendered to 144-DPI PNG and independently re-hashed; 5,368,250,915 bytes |
| Stratified repeat audits | PASS | 128 inputs per suite, 384 total, full-manifest bound and independently re-hashed |
| Synthetic 18-fault campaign | PASS | Exact masterplan taxonomy contract; not model accuracy or public benchmark evidence |
| Full public model inference | NOT EXECUTED | No qualified endpoint or pod, no approved cost ceiling, and all required candidates remain promotion-ineligible |
| Production promotion | REJECT | Fail-closed preflight remains correct |

The code and frozen public inputs are ready for a real campaign. No public-core accuracy uplift is claimed because model inference has not run.

## Implemented adaptive repetition

Every candidate receives:

1. one full public-core run; and
2. three deterministic stratified audits.

The policy expands to exactly three full runs only for finalists or when prediction-hash drift, score drift, or runtime failure occurs. A stable non-finalist stops after the first full run. All observations must share candidate, benchmark, and environment identity and must use unique run IDs.

Failed attempts are retained but do not count toward the required successful
runs. More than three successful runs per scope, non-finite scores, mismatched
item sets, and full-run drift all fail closed. Three stable full reruns may clear
an initial stratified-audit drift signal; unstable full reruns cannot pass.

This answers the repetition question directly: three full runs are not spent on every stable candidate, but three small audits are always retained to detect nondeterminism before promotion.

The frozen audit contains 128 inputs from each suite. OmniDoc covers 118
non-answer source/language/layout/special-issue-presence strata, ParseBench four
source-category strata, and olmOCR seven source-category strata. For a stable
candidate the plan performs 6,284 page inferences instead of 15,396 for blind
three-full execution, saving 9,112 page inferences (59.1842%). The four model
runners now default to one full run; audit indexes 1-3 and expansion full
indexes 2-3 are enforced by the CLI contract.

## Failure detector gate

The detector receipt records and gates all of the following independently:

- failure-code precision, recall, and F1;
- exact failure-type accuracy;
- exact localization and minimum-scope accuracy;
- recovery/no-recovery decision accuracy;
- escalation decision accuracy;
- silent omission rate; and
- false recovery rate.

The gate is fail-closed. Any extra or missing failure type, wrong location, overly broad scope, wrong recovery decision, wrong escalation decision, silent omission, or recovery of a non-recoverable item rejects the receipt.

Official evaluator adapters connect real future model failures to this
taxonomy without exposing expected content to inference. The frozen adapter
inventory covers OmniDoc's four configured metrics plus missing-page handling,
all 26 ParseBench rule types across 169,011 assertions, and all six olmOCR
test types across 7,019 assertions. A new or renamed official type rejects the
campaign instead of being guessed. This adapter coverage is not itself a claim
that a model has been run or that real detector precision is 1.0.

The deterministic injector covers the complete registered taxonomy:

| Code | Failure | Recovery preprocessing |
| --- | --- | --- |
| P01 | page omission | page re-render plus alternate parser |
| B01 | block omission | region crop |
| T01 | bottom row omission | overlapping tiles |
| T02 | middle row omission | adaptive row-band tiles |
| T03 | extra rows | candidate reject |
| T04 | wrong table | target selection |
| T05 | column shift | cell geometry specialist |
| N01 | digit mutation | native/authority reconstruction |
| N02 | sign or scale error | canonical numeric recovery |
| R01 | reading order | layout specialist |
| C01 | cross-page split | page-pair stitch |
| F01 | formula corruption | formula specialist |
| G01 | grounding mismatch | source remap |
| H01 | hallucination | candidate reject |
| H02 | repetition | candidate reject |
| K01 | note split error | recompile affected note |
| K02 | wrong entity merge | split entity |
| K03 | unsupported relation | remove relation |

## Runtime recovery behavior

For a semantic failure, the scheduler rejects the failed candidate, excludes its worker and independent model family, chooses a recovery-stage route from another family, applies the failure-specific preprocessing variant at the smallest source-localized scope, and validates the replacement. If validation still fails and the bounded attempt budget remains, the scope expands by one level. Recovery acceptance itself also binds the base and repair family identities and rejects same-family evidence, even if the caller bypasses scheduler routing. A verified replacement triggers replay only for lineage descendants of the repaired object.

For an infrastructure failure, the scheduler retries the same work on a different worker/model family. Semantic recovery and infrastructure retry remain distinct attempt kinds in the receipt.

The current scheduler tests specifically prove MinerU-to-Paddle semantic recovery, a second independent DeepSeek recovery route, exact one-level region-to-page scope escalation, cross-worker/family infrastructure retry, and selective replay of impacted descendants without replaying unrelated objects. The checkpoint retains the complete localized scope ladder across retries and rejects a scope ID if its evidence is redefined.

## Paid runtime qualification boundary

`READY` can no longer be asserted with an arbitrary SHA-shaped string. A paid
pod spec must embed a content-bound qualification that matches the exact image
digest, GPU, and allowed CUDA version and binds release source, Dockerfile,
model artifact, baked runtime file, SBOM, vulnerability scan, and frozen smoke
input/prediction/expected hashes. Identity, artifact, and smoke gates must all
pass, the smoke hashes must match, and the critical-vulnerability count must be
zero. Direct client construction is rechecked immediately before the provider
write, so bypassing JSON parsing cannot evade the gate.

The repository now also separates the preceding image-build gate from GPU
qualification. The scoped `.github/workflows/baked-model-image.yml` workflow
can build and push only the frozen OvisOCR2 M1 image, create an SPDX SBOM, scan
the immutable digest for critical vulnerabilities, and emit a content-bound
`folynta.baked-image-build-integrity.v1` receipt. That receipt is structurally
required to say `runtime_qualification_required: true` and
`paid_capacity_ready: false`; it therefore cannot make a pod spec `READY`.
The workflow contains no provider-capacity operation. It runs only on the
integration branch when its four image-build paths change, or by manual
dispatch. It was published in commits `c2cd649`, `7997c82`, `f70efee`, and
`f6275f9`. Three live workflow configurations were exercised. The first
proved the default Docker driver could not emit attestations; the next two
used a container Buildx driver, explicit hosted-tool cleanup, and finally
removed duplicate inline attestations while retaining the independent SBOM and
scan. Both container-driver builds exhausted the standard GitHub runner disk
during the vLLM image build. No complete GHCR package or receipt was emitted.
The attempt evidence is frozen in
`benchmark/reports/generated/folynta-ovis-ghcr-build-attempts-2026-08-03.json`.

The source evidence is insufficient to create equivalent images for the
other current recipes without fabricating missing facts: DeepSeek has an exact
33-file/6.79 GB model artifact manifest but no frozen runtime-image contract;
Paddle has exact package versions and a compatibility-patch receipt but the
78-file model artifact manifest itself is not stored in the repository; and
the two MinerU paths retain source revisions and aggregate manifest hashes but
not their content-bound manifests or baked runtime definitions. Those three
paths remain fail-closed.

## Public-core acquisition evidence

Receipt: `benchmark/reports/generated/folynta-public-core-acquisition-live-2026-08-03.json`

- OmniDocBench revision `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`: 1,658 LFS files, 1,550,593,007 bytes, zero missing/pointer files.
- ParseBench revision `2805a1d940f95a203e0ae4b88be9934f7765b3fc`: 1,194 LFS files, 526,208,240 bytes, zero missing/pointer files.
- olmOCR-Bench revision `54a96a6fb6a2bd3b297e59869491db4d3625b711`: 1,403 LFS files, 354,384,964 bytes, zero missing/pointer files.
- Receipt gate: `PASS`.
- Receipt SHA-256: `sha256:3d942bacdaafb46056730b28b94feb6c3d62086d408131af35034cea2c764217`.
- Ground truth is evaluator-only and forbidden to inference workers.

## Public-core source and inference-input evidence

Source verification receipt:
`benchmark/reports/generated/folynta-public-core-source-manifest-verification-2026-08-03.json`

Staged-input verification receipt:
`benchmark/reports/generated/folynta-public-core-staged-input-verification-2026-08-03.json`

The evaluator reads each official index only to discover the source path and
page. It emits no expected text, rule, label, layout detection, or other
ground-truth field to inference. Each source is bound to its original SHA-256,
stable case ID, and page index. PDFs are rendered at 144 DPI to PNG; native
images are decoded and normalized to PNG. A second process then re-reads and
re-hashes every staged file using the same fail-closed contract required by all
four model runners.

| Benchmark | Official sources | Staged inputs | Input bytes | Source manifest SHA-256 | Input manifest SHA-256 |
| --- | ---: | ---: | ---: | --- | --- |
| OmniDocBench | 1,651 | 1,651 | 2,998,122,547 | `sha256:8e1b87abbc520b9852676c0e578ff469bd0a8be6e5713368de313f0967a603a6` | `sha256:4035179aa51eede8f36ec35e6050f8a72d76c0b8cc06b3fa81edd4b44666e149` |
| ParseBench | 2,078 | 2,078 | 991,778,130 | `sha256:71591d45993ae45c0b839186095278d349c3dd45bd9b7e6939d7557fd3664495` | `sha256:03c7577426128ef0b6271f313723e53bb4b1c2deaeb43f77c48ea13b90f75a03` |
| olmOCR-Bench | 1,403 | 1,403 | 1,378,350,238 | `sha256:ff58e4e1dc6cf38f51674b0d014215e713b798c81b37ce046ad31fe27a0e5fb9` | `sha256:456014a9afceb20514342e0b19d0423ce75f8ac3a70e5a79f9c4414c3e849704` |

- Total official/staged inputs: 5,132 / 5,132.
- Total staged bytes: 5,368,250,915.
- Source-manifest verification gate: `PASS`; receipt SHA-256: `sha256:32041903b1266797b8305743fff4416626a5c185c16b4ca687ef656f56eb9475`.
- Staged-input verification gate: `PASS`; receipt SHA-256: `sha256:add3b350693a52a364ea9dad2bb4dfe1322091e1acfa63c5a497f97b37049c56`.
- Runtime public-core mode requires `--limit 0`, the exact frozen count, and a content-hash-valid input manifest. Missing, extra, moved, or mutated files fail before model loading.

## Adaptive audit and official evaluator adapter evidence

Audit receipt:
`benchmark/reports/generated/folynta-public-core-stratified-audit-verification-2026-08-03.json`

Official evaluator adapter receipt:
`benchmark/reports/generated/folynta-public-failure-adapter-verification-2026-08-03.json`

- Audit inputs: 128 per suite, 384 total; all hashes re-read from the staged 5,132-input inventory.
- Stable adaptive work: 6,284 page inferences versus 15,396 for blind three-full execution.
- Stable-candidate page-inference saving: 9,112 (59.1842%).
- Audit selection is identical across its three repeat indexes and is bound to each full input manifest.
- Adapter inventory gate: `PASS`; receipt SHA-256: `sha256:453574f861ccd0befa181a779ecb14b8884a25251c4cd2284ec4b575c57d6605`.
- Audit gate: `PASS`; receipt SHA-256: `sha256:e839fed26f3778d74d3694b9d904e4fe25584bc12cfefd0752e658404ac5d125`.

## Synthetic contract evidence

Input: `benchmark/v6/cohorts/recovery-fault-injection-golden.json`

Generated receipt: `benchmark/reports/generated/folynta-recovery-fault-injection-golden-2026-08-03.json`

- 18 masterplan-taxonomy faulty cases plus one healthy control.
- Detector precision/recall/F1 and all exact-decision metrics: 1.0.
- Silent omission and false recovery: 0.
- Synthetic initial accuracy: 1/19.
- Synthetic selective final accuracy: 19/19.
- Synthetic absolute uplift: 18/19 (0.9473684).
- Synthetic accepted precision and verified coverage: 1.0; unresolved rate: 0.0.
- Selective result equals full replay in this frozen contract.
- Synthetic cost and latency saved ratio: about 0.9053.
- Adaptive repeat decision: one full run plus three completed stratified audits; no extra full runs.
- Receipt gate: `PASS`.
- Receipt SHA-256: `sha256:2265937cfa8e3ff7696134ba65c88ee301dd9956d6f16e414d5a53e118743c04`.

These numbers validate metric wiring and fail-closed contracts only. They must not be reported as model, public-core, private-holdout, or production accuracy.

## Verification executed

- Entire Python repository after final implementation: `1664 passed in 486.03s` using `.venv` Python 3.13.
- Final focused backend integration suite: `358 passed in 87.71s`.
- Final recovery/public-input integration suite: `451 passed in 90.07s`.
- Adaptive/evaluator/recovery integration suite after follow-up audit: `510 passed in 86.72s`.
- Source/input contract unit suite: `17 passed`; staged/source receipt verifier suite: `4 passed`.
- Benchmark v6 suite before the full run: `80 passed`.
- Strict detector/receipt follow-up: `20 passed`.
- Ruff on changed recovery and detector sources: pass.
- Mypy on changed core source modules: pass.
- Mypy on 12 recovery/public-input core modules and two RunPod qualification modules: pass.
- `git diff --check`: pass.
- Offline v6 preflight: local contract `pass`, production gate `reject`, paid endpoints created `0`.
- Baked-image build receipt/workflow/Ovis fail-closed contract suite: `11 passed`.
- Live GHCR workflow attempts: three fail-closed failures; zero matching complete Ovis GHCR packages after the attempts.

## External execution blockers

The refreshed live provider receipts show zero endpoints, zero pods, and USD 0 provider spend. Every Ovis M1 pod spec is intentionally `BUILD_REQUIRED` and has no baked-runtime qualification receipt. Docker is not installed on this host, and the standard GitHub runner exhausted its disk in two successive container-driver image builds even after exact tool-cache cleanup and removal of duplicate inline attestations. A read-only package inventory found zero matching Ovis GHCR packages. Completing the image now requires an approved larger GitHub runner or another approved image builder. The candidate registry reports 0 required candidates as promotion-eligible and only four parser candidates currently have runtime recipes; three of those four still lack sufficient stored content-bound runtime material for a reproducible image. The locally stored RunPod credential was used only for read-only refreshes; no capacity was created.

Consequently, creating paid capacity or claiming a full-model public benchmark result would be unsafe and misleading. The remaining authorized sequence is:

1. push and run the scoped Ovis GHCR build workflow, preserve its build-integrity receipt, and reconstruct the missing runtime/artifact contracts for the other three recipes;
2. perform GPU identity/artifact/smoke qualification for each immutable image;
3. bind each required candidate's artifact, license, and runtime receipt;
4. approve a hard provider cost ceiling;
5. upload the verified 5,132 full inputs plus the 384-input audit selection and run one full pass plus three audits with ground truth isolated from inference;
6. run paired baseline/selective-recovery/full-replay evaluation;
7. expand finalists or unstable candidates to three full runs;
8. sign evidence, clean up temporary capacity, and only then resolve the champion matrix.
