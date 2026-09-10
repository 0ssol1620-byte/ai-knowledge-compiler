# Selective peer-override verifier replay — 2026-09-10

Status: spent-development diagnostic only. This is not a fresh holdout,
production promotion, or public performance claim.

## Frozen hypothesis

The measured layout V2 showed that route-visible feature coverage alone did not
qualify Native: locator coverage did not establish reading order or semantic
preservation. The next bounded candidate therefore changes election rather than
retuning a layout threshold.

`SELECTIVE_PEER_OVERRIDE_VERIFIER_V1` freezes MinerU VLM as the layout primary,
olmOCR2 as challenger and PaddleOCR-VL 1.6 as independent verifier. It accepts
the primary on direct primary/challenger agreement. On disagreement it accepts
the challenger only when Paddle corroborates the challenger and not the
primary. Otherwise it retains the present primary with an explicit reason that
states whether corroboration was absent. A missing primary is never silently
replaced without independent corroboration.

The policy consumes only model availability and token-set similarity already
visible at route time. It does not consult evaluator truth, per-model loss,
Oracle choice, ground-truth rules or holdout data. Its models, 0.80 agreement
threshold, override rule and fallback rule were written into the policy freeze
before the new arm's hidden scores were evaluated.

## Same-denominator result

All 1,403 spent-development pages and 8,413 scored rules were retained. Missing
outputs remain failures. The scorer, SCLR opportunity freeze, model-output
matrix, historical cost ledger and 2,000-replicate document-family bootstrap are
the same as the earlier PR #63 runs.

| Metric | Best fixed: MinerU VLM | Selective override | Change |
| --- | ---: | ---: | ---: |
| Information retention rate | 0.861938 | 0.860369 | -0.001570 |
| Mean loss | 0.138062 | 0.139631 | +0.001570 |
| SCLR / unit | 0.101212 | 0.099073 | -0.002138 |
| SCLR / opportunity | 0.083027 | 0.080954 | -0.002073 |
| Unresolved fraction | 0 | 0 | 0 |
| Historical raw provider USD / 1k pages | 0.997408 | 10.678065 | +9.680656 |
| Historical ledger seconds / page | 5.000000 | 19.656450 | +14.656450 |
| Measured model p95 | unknown | unknown | unknown |
| Route regret | 0.076608 | 0.078178 | +0.001570 |
| Oracle headroom capture | 0.000000 | -0.037980 | -0.037980 |

The candidate's mean-loss 95% interval is [0.128393, 0.151953]. Its Oracle
capture 95% interval is [-0.132918, 0.000552]. The interval touching zero does
not establish positive value, while the point estimate, mean loss, regret,
historical cost and ledger time are all worse than the best fixed arm.

Runtime-visible route accounting:

- 822 pages retained MinerU after direct primary/challenger agreement.
- 581 pages invoked the third-provider verifier.
- 68 pages accepted the exclusively corroborated olmOCR2 challenger.
- 98 pages retained a Paddle-corroborated MinerU primary.
- 415 pages retained MinerU while explicitly recording that neither candidate
  was independently corroborated.
- Final accepted outputs: MinerU 1,335, olmOCR2 68, unresolved 0.

The small SCLR reduction does not compensate for the higher loss, regret and
roughly 10.7-fold historical provider cost. This election therefore remains a
negative research result.

## Exact receipts

Primary replay:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-selective-override-20260910-v1`
- SCLR freeze: `sha256:9db34935cbf54f88a4691f5ae5baf299c5aaca8f9b395e4d9a179496c3724f7b`
- policy freeze: `sha256:3448b3dd0250873f80dce7e5355b4abee3d6bf34812666709bc2e5cda96196bc`
- results: `sha256:3823585f50bd37a1935848206128a071b5a673d758eaae1b2faf7ded929eaccd`
- tables: `sha256:1bf309a77757f0a7b22bc0b1874217f0650fb61a4c943708ba8326b60266eb3d`
- manifest: `sha256:c1651568601f2ab085081e278ae1cf19c936955e17b990eaebb78b582fcd54a5`
- runtime: 23.6 seconds

Warm reproduction:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-selective-override-20260910-v2-reproduction`
- policy, SCLR and tables hashes are identical.
- parsed results are identical after removing `runtime_seconds` (23.6 versus
  23.8 seconds); manifests are identical after also removing the derived result
  hash.
- new model calls: 0; new GPU/provider spend: USD 0.

Validation:

- 234 Router package, unit and Apple 290-page public-corpus tests passed
  (`.chatgpt2codex/router-selective-override-broad.log`).
- 69 replay and Oracle math tests passed
  (`.chatgpt2codex/router-selective-override-focused.log`).
- Ruff passed for all changed runtime, replay and test modules
  (`.chatgpt2codex/router-selective-override-ruff.log`).
- strict mypy passed for five replay modules
  (`.chatgpt2codex/router-selective-override-mypy.log`).

Reproduction command:

```text
.venv/Scripts/python.exe research/router_replay_20260908/replay.py --out <new-output-dir> --surfaces olmocr --replicates 2000 --native-capture <sealed-native-capture> --native-score <sealed-native-score> --layout-capture <sealed-layout-capture> --replay-cache <V3-visible-cache>
```

## Decision

Fresh holdout, production promotion, public claims and RunPod use remain
closed. The existing outputs were sufficient to reject this hypothesis, so new
inference has no decision value for it. A further candidate must add a genuinely
independent reading-order or semantic-structure verification signal with its
policy frozen before evaluation; another agreement permutation over the same
three outputs would be post-result tuning.
