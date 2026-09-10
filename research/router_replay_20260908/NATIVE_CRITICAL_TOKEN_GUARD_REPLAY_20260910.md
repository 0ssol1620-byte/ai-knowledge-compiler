# Native critical-token guard replay — 2026-09-10

Status: spent-development diagnostic only. This is not a fresh holdout,
production promotion, or public performance claim.

## Frozen hypothesis

The previous three-model peer election did not improve information retention
and cost about 10.7 times the best fixed arm. `NATIVE_CRITICAL_TOKEN_GUARD_V1`
therefore uses a source-derived verifier instead of another model vote.

The policy was committed and pushed as `068157c` before hidden scoring. It runs
the Native text projection and fixed MinerU VLM primary first. Native is
eligible only with at least 100 characters, at least 0.99 locator coverage,
invalid-Unicode ratio at most 0.005, replacement ratio at most 0.001, and no
image-only source. The verifier compares exact number, sign, unit, date and
currency multiplicities. This is order-independent and does not claim reading
order, table structure or semantic completeness.

olmOCR2 runs only after MinerU has at least one critical-token mismatch. It can
replace MinerU only if it has zero mismatches against the same Native reference.
The two predeclared dispositions were:

- baseline-retaining: keep MinerU with a review reason when neither output
  passes;
- strict: return unresolved when neither output passes.

The source policy freeze is
`NATIVE_CRITICAL_TOKEN_GUARD_FREEZE_20260910.json`. It fixes a GPU budget of
USD 0 and keeps the fresh holdout closed.

## Same-denominator result

All 1,403 spent olmOCR-Bench pages and 8,413 scored rules were retained.
Missing outputs remain failures. Hidden truth was not visible to routing.

| Metric | Best fixed MinerU | Baseline-retaining guard | Strict guard |
| --- | ---: | ---: | ---: |
| Information retention rate | 0.861938 | 0.861993 | 0.146643 |
| Mean loss | 0.138062 | 0.138007 | 0.853357 |
| Hard-fail pages | 550 | 549 | 1,287 |
| SCLR / unit | 0.101212 | 0.101212 | 0.036351 |
| SCLR / opportunity | 0.083027 | 0.083027 | 0.021299 |
| Unresolved fraction | 0 | 0 | 0.794013 |
| Escalation fraction | 0 | 0.803279 | 0.803279 |
| Historical raw provider USD / 1k pages | 0.997408 | 7.137450 | 7.137450 |
| Historical ledger seconds / page | 5.000000 | 15.519965 | 15.519965 |
| Route regret | 0.076608 | 0.076554 | 0.791904 |
| Measured model p95 | unknown | unknown | unknown |

The baseline-retaining point estimate improved mean loss by only 0.000054 and
one hard-fail page. SCLR did not improve. Its Oracle-capture bootstrap point was
-0.016541 with a 95% interval of about [-0.104, 0.019], so the run does not
establish positive capture. Historical provider cost increased about 7.2 times.

The route-visible accounting explains the cost:

- 265 pages had no eligible Native critical-token reference;
- 11 pages had a MinerU output that exactly preserved the reference tokens;
- 1,127 pages invoked olmOCR2 after a MinerU mismatch;
- only 13 of those pages accepted olmOCR2;
- 1,114 pages had no zero-mismatch candidate. The baseline-retaining arm kept
  MinerU with review required; the strict arm returned unresolved.

Exact-match token multiplicity is useful as a narrow fail-closed check, but the
full-page challenger invocation is not selective enough. The strict disposition
does reduce silent critical loss, but a 79.4% unresolved rate is not a usable
whole-page policy.

## Exact receipts

Primary replay:

- preregistered code/policy commit: `068157c`
- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-native-token-guard-20260910-v1`
- SCLR freeze: `sha256:9db34935cbf54f88a4691f5ae5baf299c5aaca8f9b395e4d9a179496c3724f7b`
- policy freeze: `sha256:e86fae6dae7e61037e4e7a8998ff2523adfd84beab4a576d6273150a4eaa90a6`
- results: `sha256:786827fde8f8f5235598316c23c4e63e73e5666ac9ee928de98d93b93112375f`
- tables: `sha256:3a6c265674b14277d4fdbd336447349835690dc3da7a9ded7b068f743065518d`
- manifest: `sha256:5e4f47d25f868f63cc0ac6fe3a8619ffa7c6f9dd8a5d64ab3b54f11e9fed464d`
- runtime: 50.1 seconds

Warm reproduction:

- evidence: `D:\trouter-int-0910\.chatgpt2codex\router-native-token-guard-20260910-v2-reproduction`
- SCLR, policy and table hashes are identical;
- results are identical after removing `runtime_seconds` (50.1 versus 50.5);
- new model calls: 0; new GPU/provider spend: USD 0.

Validation:

- 290 Router package, unit and replay tests passed;
- 61 replay tests passed before scoring;
- Ruff passed for all changed modules;
- strict mypy passed for five replay modules;
- the attempted wider public Native test is excluded from this exact receipt
  because this isolated worktree intentionally lacks the `akc_security`
  package. The earlier public-corpus receipt remains historical evidence, not a
  substitute for this head.

## Decision

Neither disposition is promoted. Fresh holdout, production authority, public
claims and new RunPod inference remain closed.

The next bounded experiment must use source-bound regions: locate the exact
critical-token or table region, run a specialist only on that crop, verify that
region independently, and merge or refuse without replacing the rest of a good
page. This changes the cost and evidence structure. Another whole-page vote or
threshold retune over these same outputs has no decision value.
