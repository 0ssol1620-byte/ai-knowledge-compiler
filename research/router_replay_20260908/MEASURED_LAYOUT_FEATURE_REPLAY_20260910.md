# Measured layout feature replay — 2026-09-10

Status: spent-development diagnostic only. This is not a public benchmark,
production qualification, or evidence of superiority.

## Question and frozen baseline

PR #63's `SOURCE_LAYOUT_AUTHORITY_VERIFIER_V1` result remains unchanged. Its
1,403/1,403 `layout:unknown_conservative` decisions were caused by the feature
contract, not by the page contents: the frozen source manifest supplied raster
edge density, intensity, near-white ratio, entropy and blankness, while V1
required estimated columns, table/formula density, chart probability, image
coverage and native reading-order quality. Those required fields were marked
unknown on every unit. The manifest also supplied no authority metadata.

The V2 candidate was frozen separately. It measures only features available at
route time from the already staged input PNG, binds each observation to both the
input PNG and original-source SHA-256, and never opens scorer, rules, ground
truth or holdout data. The deterministic Pillow probe estimates column count,
long-line density and ink coverage. The separately sealed Native observation
contributes text validity and block locator coverage. It does not claim to
measure semantic reading order.

## Feature coverage and runtime

| Feature | Coverage | Result |
| --- | ---: | --- |
| Raster layout probe | 1,403 / 1,403 | 0 failed |
| Native locator coverage | 1,178 / 1,403 | all measured rows at least 0.99 |
| Native rows without a block denominator | 225 / 1,403 | retained as unknown |
| Authority metadata | 0 / 1,403 | retained as unmeasured |

Observed column-count distribution was 883 one-column, 221 two-column, 291
three-column and 8 four-column pages. The long-line density heuristic is only a
route-time visual proxy; it is not a table-semantics label.

The CPU probe processed every page in 42.876 seconds: p50 14.230 ms, p95
150.581 ms and p99 337.829 ms per page. It made zero model calls and incurred
USD 0 in GPU/provider charges. Local CPU infrastructure cost was not metered
and therefore remains unmeasured. The historical model ledger has no per-page
receipt for MinerU VLM or olmOCR2, so end-to-end model p95 remains unknown; the
available 10.768 seconds per unit is an aggregate ledger estimate, not p95.

## Same-denominator result

All 1,403 pages and 8,413 scored rules were retained. Missing outputs remain
failures. The evaluation uses the same frozen SCLR opportunities, scorer,
model-output matrix, historical cost ledger and document-family bootstrap as
PR #63.

| Arm | Mean loss | IRR | SCLR/unit | SCLR/opportunity | Unresolved | Historical USD/1k | Model p95 | Regret |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Best fixed: MinerU VLM | 0.138062 | 0.861938 | 0.101212 | 0.083027 | 0 | 0.997408 | unknown | 0.076608 |
| Frozen V1 | 0.359793 | 0.640207 | 0.044191 | 0.016964 | 0.295795 | 10.678065 | unknown | 0.298340 |
| Measured V2 | 0.513257 | 0.486743 | 0.039202 | 0.017152 | 0.395581 | 6.437894 | unknown | 0.451804 |

V2's mean-loss 95% document-family bootstrap interval is [0.489463,
0.538244]. Its Oracle headroom capture point is -4.997907 with a 95% interval
of [-5.647281, -4.466528]. It therefore does not beat the best fixed arm and
does not justify a fresh holdout.

V2 route accounting:

- 1,138 pages selected `source:native_qualified`, 254 selected
  `layout:observed`, and 11 selected `layout:observed_low`.
- 263 pages finished after primary-peer agreement; 1,140 invoked the third
  verifier.
- 172 pages accepted Native, 663 MinerU VLM, 13 olmOCR2, and 555 remained
  unresolved.
- Every page explicitly recorded `authority:unmeasured`.

The result separates observability from qualification. A high Native block
locator ratio proves that extracted blocks have source locators; it does not
prove correct reading order, table semantics, formula preservation or
authority. Treating it as a sufficient Native-first gate caused a worse result.
The raster probe eliminated the all-unknown layout branch but its structural
proxy did not create positive routing value under the frozen verifier.

## Exact bindings and reproduction

Layout capture:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\layout-visible-capture-20260910-v1`
- probe: `TAVONEL-LAYOUT-PREFLIGHT-2026-09-10-V1`
- runtime: Python 3.12.13, Pillow 12.3.0, Windows 10, no model/container
- source manifest: `sha256:2ec00f371db5069216362ee946b084ed0d222474162d7eadcbf717f09ae55e7c`
- selected rows: `sha256:7e3654431935a1b2584c4a0fcd960546e380794605a22c630b58a23cbb2b9907`
- records: `sha256:e501d07108f9fdbe062088272811c967d572ed5e33bd5d4cff46c1b2d255ae41`
- probe code: `sha256:101fb9206f177491e21cd2f5870791d593129909d73511c9ce48c0653c39b926`

Primary replay:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-measured-layout-20260910-v2`
- SCLR freeze: `sha256:9db34935cbf54f88a4691f5ae5baf299c5aaca8f9b395e4d9a179496c3724f7b`
- policy freeze: `sha256:a8b4d4c5f5242855fec1f8d286a8b3ae65728bb5eff6d5a9e4be33474f96ca93`
- results: `sha256:ba31c1fa307251454e59edc024bb6e58426af7dbd7cd77c89652f731142eea1f`
- tables: `sha256:9d90f413bc9a5e946cca1a3ddb9d8268f4e8e63746f301f603e057322231e38e`
- manifest: `sha256:672a10b2243e517d3d1fe211440a6ce4e478595fca558e4370406569199235a8`
- runtime: 129.4 seconds, including cold V3 feature-cache construction

Warm reproduction:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-measured-layout-20260910-v3-reproduction`
- policy, SCLR and tables hashes are identical.
- parsed results are identical after removing `runtime_seconds` (129.4 versus
  44.7 seconds); manifests are identical after also removing the derived result
  hash.
- new GPU/provider spend: USD 0.

Validation:

- 234 Router package, unit, and existing Apple 290-page public-corpus tests
  passed with the complete editable `PYTHONPATH` and an isolated receipt path
  (`.chatgpt2codex/router-measured-layout-broad-with-public.log`).
- 65 replay and Oracle math tests passed
  (`.chatgpt2codex/router-measured-layout-focused.log`).
- Ruff passed for all changed runtime, replay and test modules
  (`.chatgpt2codex/router-measured-layout-ruff.log`).
- strict mypy passed for five replay modules
  (`.chatgpt2codex/router-measured-layout-mypy.log`).

Reproduction command:

```text
.venv/Scripts/python.exe research/router_replay_20260908/replay.py --out <new-output-dir> --surfaces olmocr --replicates 2000 --native-capture <sealed-native-capture> --native-score <sealed-native-score> --layout-capture <sealed-layout-capture> --replay-cache <V3-visible-cache>
```

## Decision

Fresh holdout, production promotion and public performance claims remain
closed. A RunPod inference run is not justified by this result. The missing
authority signal must come from the source/connector contract, not a vision
model, and another model call cannot turn locator coverage into reading-order
proof. The next admissible candidate needs a pre-registered independent
reading-order/structure verifier and real authority metadata before hidden
scores are opened. Its exact runtime, page IDs, missing rows, cost and latency
must be sealed with the feature outputs.
