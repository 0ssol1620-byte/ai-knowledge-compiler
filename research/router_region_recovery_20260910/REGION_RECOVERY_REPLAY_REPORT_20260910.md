# Source-bound region recovery replay — 2026-09-10

Status: spent-development diagnostic only. This is not a fresh holdout,
production promotion, or public performance claim.

## Frozen candidate

`SOURCE_BOUND_REGION_RECOVERY_ROUTER_V1` was frozen and pushed at `f2b8f27`
before hidden olmOCR evaluation opened. It keeps MinerU VLM as the page
representation, invokes PaddleOCR-VL 1.6 only for the 31 previously frozen
source-bound targets, attaches a Paddle block only after exact source
critical-token verification, and marks only the selected region unresolved
when verification fails.

The runtime-visible Paddle reuse pass was deterministic across two executions:

- 31 targets;
- 20 verified critical regions;
- 5 unresolved because no unique containing Paddle block existed;
- 6 unresolved because critical-token multiplicity still disagreed;
- records SHA-256
  `sha256:d7e4b7737510128409461026ec5e2a84ec390a583b87f0cc1b219df2ba411a91`;
- new GPU cost: USD 0.

## Same-denominator hidden result

All 1,403 olmOCR pages and 10,611 frozen critical-token opportunities were
retained. The 31 source-derived target tokens did not overlap any deletion in
olmOCR's partial asserted-span ground truth. Consequently, the candidate
changed neither SCLR nor the unchanged main representation score.

| Metric | Fixed MinerU | Region candidate |
| --- | ---: | ---: |
| Main-representation IRR | 0.861938 | 0.861938 |
| Main-representation mean loss | 0.138062 | 0.138062 |
| Hard-fail pages on main representation | 550 | 550 |
| SCLR / unit | 0.101212 | 0.101212 |
| SCLR / opportunity | 0.083027 | 0.083027 |
| Silent critical events | 881 | 881 |
| Verified source regions | — | 20 / 31 |
| Localized unresolved page fraction | — | 0.007840 |
| Historical raw provider USD / 1k pages | 0.997408 | 1.106091 |
| Region runtime p95 | — | unmeasured |

The paired 5,000-replicate bootstrap SCLR delta is exactly 0 with interval
`[0, 0]`. This is a measurement-coverage failure for the candidate, not evidence
that the source tokens are unimportant: olmOCR publishes only selected
assertions rather than full page truth.

## Exact receipts

- policy freeze:
  `sha256:058a1de028bc4f84039f82445a05a518fd8f5784e47e1456547a292439632522`
- primary result:
  `D:\trouter-int-0910\.chatgpt2codex\router-region-recovery-replay-20260910-v1`
- reproduced result:
  `D:\trouter-int-0910\.chatgpt2codex\router-region-recovery-replay-20260910-v2-reproduction`
- identical result SHA-256:
  `sha256:baff89fb2a5d7137a04d1c0b4c3737ed3284d9704ab76a1de51786eea2c20c39`
- output disclosed no source, model, ground-truth, or literal token text.

## Decision

Do not promote this candidate and do not spend GPU on its 11 unresolved regions.
Even a successful crop would have no measurable endpoint on this frozen
olmOCR surface. The next experiment must keep the source-bound contract but use
a surface with complete relevant truth, starting with ParseBench tables. Freeze
the selector and disposition before opening its table ground truth; use stored
Paddle and MinerU outputs first, and provision RunPod only when a crop execution
can change a predeclared measurable endpoint.
