# Source/layout/authority-aware selector replay — 2026-09-10

Status: **exploratory spent development evidence**. This is not a fresh
holdout, public benchmark, qualified portfolio, production promotion, or
evidence of general superiority.

Follow-up: `MEASURED_LAYOUT_FEATURE_REPLAY_20260910.md` preserves this V1
result unchanged and evaluates a separately frozen V2 with a route-time raster
probe. V2 removes the all-unknown layout branch but remains negative.

## Frozen candidate

`SOURCE_LAYOUT_AUTHORITY_VERIFIER_V1` was specified without opening evaluator
labels and recorded in the policy freeze before hidden scores loaded.

1. An authority-bound source is `UNRESOLVED` because the replay has no scored
   authority arm. Authority absence is never read as permission to use a
   parser result as authority.
2. Native can lead only when source fidelity, reading order and all relevant
   layout fields are measured and pass the existing production preflight
   limits: at least 100 characters, invalid Unicode at most 0.005 and
   replacement characters at most 0.001.
3. Unknown layout risk selects the layout specialist. Unknown is not low.
4. The selected primary and text/layout peer run first. Agreement at the
   already-frozen 0.80 threshold accepts the selected primary.
5. Disagreement invokes PaddleOCR-VL 1.6 as a third, independent provider. It
   may corroborate and retain the primary or overturn it in favour of the
   peer. No corroboration is `UNRESOLVED`.

The unit-feature cache is now bound to `FEATURE_BUILDER_ID`. A cache created by
an older feature contract cannot be silently reused. The V2 feature contract
also declares `native_reading_order_score` unknown on this corpus instead of
letting a caller infer a measurement from its absence.

## Same-denominator result

The replay retains the same 1,403 olmOCR pages, 8,413 rules, 13 model arms,
missing-as-failure rule, source manifest and Native capture/score bindings as
the PR #63 baseline.

| Arm | loss | IRR | SCLR/unit | SCLR/opportunity | unresolved | USD/1k | p95 | regret |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| Best fixed: MinerU VLM | 0.138062 | 0.861938 | 0.101212 | 0.083027 | 0 | 0.997408 | unknown | 0.076608 |
| Source/layout/authority verifier V1 | 0.359793 | 0.640207 | 0.044191 | 0.016964 | 0.295795 | 10.678065 | unknown | 0.298340 |
| Router v2 page visual | 0.146817 | 0.853183 | 0.086957 | 0.037603 | 0 | 5.698133 | 9,359 ms | 0.085364 |
| Router v2 Native first | 0.642807 | 0.357193 | 0.199572 | 0.137310 | 0.006415 | 0.792334 | 3,302 ms | 0.581353 |
| Always all, frozen reconciler | 0.207743 | 0.792257 | 0.073414 | 0.069551 | 0 | unknown | unknown | 0.146290 |

The new verifier lowers silent critical loss but does not produce positive
router value. It leaves 415 pages unresolved, raises mean loss to 0.359793 and
costs $10.678065 per 1,000 pages on the historical raw provider ledger. Its
Oracle capture point is -2.956154 with a 95% document-family bootstrap interval
of [-3.387414, -2.579901]. Its mean-loss interval is [0.334887, 0.385092].

Runtime-visible route accounting:

- 822 pages reached primary-peer agreement after two routes.
- 581 pages invoked the third verifier.
- 920 pages accepted MinerU VLM, 68 accepted olmOCR2 and 415 were unresolved.
- All 1,403 pages followed `layout:unknown_conservative`; this corpus contains
  no authority-domain field and no measured table/formula/chart layout fields.

That last point limits what this experiment establishes. The source and
authority branches are unit-tested, but this corpus does not empirically test
them. Per-page p95 is also unknown because MinerU VLM and olmOCR2 have no
per-page inference receipts in the retained ledger. The available aggregate
ledger estimate is 19.65645 seconds per page for invoked routes; it is not a
measured p95.

## Reproducibility

Primary run:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-source-layout-authority-20260910-v1`
- SCLR freeze: `sha256:9db34935cbf54f88a4691f5ae5baf299c5aaca8f9b395e4d9a179496c3724f7b`
- policy freeze: `sha256:3aab6ff23cbad5478ed056eda3bd5f6635ec7914b8435abcab61332e7b26efc2`
- results: `sha256:81e19d9a5d42edafa10e7344809a45a9fdac03b447351f228c85c73bf4733d14`
- tables: `sha256:f56095f8265966631607f2c6501e46f863233f76a9482170475913ad3b8d7e4b`
- manifest: `sha256:7fd7cd73f9cacfae96e1e4b83c4c4dd7d65c6f75cf9663d7b077232d170166f0`
- cold V2 feature-cache runtime: 130.1 seconds
- new GPU/provider spend: USD 0

Reproduction:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-source-layout-authority-20260910-v2-reproduction`
- policy, SCLR and table hashes are identical.
- parsed results are identical after removing `runtime_seconds` (130.1 versus
  23.3 seconds); manifests are identical after also removing the derived
  result hash.

Validation:

- 228 Router unit/research integration tests passed
  (`.chatgpt2codex/router-source-layout-broad.log`).
- 53 replay and Router package tests passed
  (`.chatgpt2codex/router-source-layout-focused.log`).
- Ruff passed (`.chatgpt2codex/router-source-layout-ruff.log`).
- strict mypy passed for two package and four research modules
  (`.chatgpt2codex/router-source-layout-mypy.log`).

## Decision

Fresh holdout, production authority and public performance claims remain
closed. No additional threshold sweep is admissible on this spent corpus.
RunPod is not justified by this result: the limiting evidence is selector and
authority/layout observability, not a missing copy of an existing model
output. A future paid run needs a pre-registered source-diverse corpus with
measured layout/authority features, exact runtime bindings and a frozen
acceptance rule before the first inference starts.
