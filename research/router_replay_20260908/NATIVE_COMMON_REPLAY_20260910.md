# Native-inclusive common-denominator replay — 2026-09-10

Status: **spent development evidence, diagnostic only**. This is not a fresh
holdout, public benchmark, champion qualification, production promotion, or a
claim that one system is universally better.

## Question and frozen denominator

The run asks whether a runtime-visible router can improve on the best fixed
stored arm after the separately sealed Native capture is joined to the same
olmOCR source and rule identities as the retained Arena arms.

- 1,403 source pages and 8,413 rules are retained.
- Missing and failed outputs remain failures.
- The runtime-visible half cannot open evaluator labels or benchmark truth.
- The Native capture and hidden score must both be supplied and their freeze
  hashes must match.
- The policy and SCLR opportunity denominator are written before scores load.
- No new model inference, network request, GPU use, or paid action occurred.

The final policy freeze includes the post-negative-result conservative
verifier candidate. It runs Native, PaddleOCR-VL 1.6 and OvisOCR2, accepts only
a candidate corroborated by another route at the previously frozen Jaccard
threshold of 0.80, and otherwise returns `UNRESOLVED`. A missing route remains
an observed failure; two surviving routes may still establish agreement.

## Common results

`loss` is the frozen evaluator loss and `IRR` is its `1 - loss` proxy. `SCLR`
is silent critical loss, not general accuracy. Latency sums stored per-page
inference receipts and excludes queue, load, preprocessing and postprocessing.

| Arm | loss | IRR | SCLR/unit | SCLR/opportunity | unresolved | USD/1k | p95 ms | regret |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Best fixed: MinerU VLM | 0.138062 | 0.861938 | 0.101212 | 0.083027 | 0 | 0.997408 | unknown | 0.076608 |
| Native | 0.742883 | 0.257117 | 0.164647 | 0.117048 | 0.160371 | 0 raw GPU/API | 284.01 | 0.681430 |
| Current Core, optimistic Native | 0.622963 | 0.377037 | 0.193870 | 0.133635 | 0 | 0.929065 | 3,317.00 | 0.561510 |
| Current Core, visual assumption | 0.146817 | 0.853183 | 0.086957 | 0.037603 | 0 | 4.918784 | 5,003.00 | 0.085364 |
| Router v2 page visual | 0.146817 | 0.853183 | 0.086957 | 0.037603 | 0 | 5.698133 | 9,359.00 | 0.085364 |
| Router v2 Native first | 0.642807 | 0.357193 | 0.199572 | 0.137310 | 0.006415 | 0.792334 | 3,302.05 | 0.581353 |
| Peer-agreement verifier v2 | 0.394950 | 0.605050 | 0.049180 | 0.017529 | 0.260870 | 9.756956 | 13,419.67 | 0.333497 |
| Always all, frozen reconciler | 0.207743 | 0.792257 | 0.073414 | 0.069551 | 0 | unknown | unknown | 0.146290 |

The page-visual Router v2 candidate has the same loss as the Paddle fixed arm
while adding peer spend and latency. The Native-first variants are materially
worse on this text-projection surface. The verifier lowers SCLR, but it pays
for three routes, leaves 366 of 1,403 pages unresolved, and raises mean loss to
0.394950. Its Oracle capture point is -3.423985 with a 95% cluster-bootstrap
interval of [-3.919902, -2.987866]. It is a useful fail-closed trust-mode
experiment, not a default router candidate.

No runtime-visible candidate beats the best fixed arm on mean loss. The fresh
holdout remains closed. More threshold tuning on this spent corpus is also
closed; it would convert development evidence into leakage.

## Reproducibility receipts

Final run:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-native-common-replay-20260910-v9-final`
- SCLR freeze: `sha256:9db34935cbf54f88a4691f5ae5baf299c5aaca8f9b395e4d9a179496c3724f7b`
- policy freeze: `sha256:68ff630bc4003165440095c193546506dd035f227ee43ff54d666ee5baf51357`
- results: `sha256:b1718e33342b2ca607da3b36265610a97f6fd6cea60433191e22c0ecca699686`
- tables: `sha256:440a852a6211b3dfa2fc76e6eb0699d816b9f228a3d252a74994aaa4c2cd4b3b`
- manifest: `sha256:8808cfdab791f78e0248a9d0d8cf572b1caff20261f0455c7704783e18577f6b`
- runtime: 23.2 seconds with a warm runtime-visible cache
- new GPU spend: USD 0

Independent reproduction:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-native-common-replay-20260910-v10-reproduction`
- policy, SCLR and table hashes are identical.
- parsed results are byte-for-byte equivalent after removing the measured
  `runtime_seconds` field (23.2 versus 23.4 seconds).
- manifest content is equivalent after removing runtime and its derived result
  hash.

Validation on the integrated Native execution plus replay branch:

- 228 Router unit/research integration tests passed, including the five-file,
  290-page public Native source fixture
  (`.chatgpt2codex/router-broad-final.log`).
- 48 replay and Router package tests passed
  (`.chatgpt2codex/router-replay-package-final3.log`).
- Ruff passed on all changed Python files
  (`.chatgpt2codex/router-ruff-final3.log`).
- strict mypy passed on the two changed package modules and four research
  modules (`.chatgpt2codex/router-mypy-final3.log`).

The repository-wide unit suite is not claimed green. This stacked candidate
does not contain several unrelated packages and service/script modules that
the full checkout's unit collection imports. Exact-SHA hosted CI is also
blocked before job execution by the repository account payment/spending
limit, so the local receipts do not substitute for hosted CI.

## Next admissible experiment

The next policy must be designed and frozen before another score read. It
should use source type, Native coverage/qualification state, layout risk,
authority availability, and independent verification to decide among a
qualified portfolio. A RunPod run is justified only after that policy and its
missing exact-runtime evidence are frozen. The required receipt must bind the
image digest, model artifact, source manifest, output denominator, cost,
latency and failures. Until then, spending GPU budget would repeat inference
without resolving the selector and verifier defect found here.
