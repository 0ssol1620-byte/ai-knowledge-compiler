# ParseBench table source-region replay — 2026-09-10

Status: spent-development diagnostic only. This is not a fresh holdout,
production promotion, or public performance claim.

## Source-region availability

The source-only capture was frozen at `d7e2e8a`. It opened no ParseBench rule,
score, model-output or ground-truth file. Two executions produced the same
`REGIONS.jsonl` SHA-256:
`sha256:8893428d6d26824491027a8a4972cf2fe2fdb2fcd3e1dccc19fec8e1ae1293c4`.

- 503 table PDFs retained;
- 498 pages with source-bound regions;
- 5 pages with no projected source text region;
- 73,764 exact source regions;
- source/model text disclosed: none;
- GPU cost: USD 0.

## Frozen selection and verification

The selector was committed at `262c197` before table truth opened. It accepted
only source-side critical-token omissions that localized to one exact region,
with bounded geometry, at least two source critical-token observations and no
more than 16 mismatches on the page.

Only four pages passed:

- three sign targets and one number target;
- 299 pages refused because the mismatch did not localize to one region;
- 145 pages refused because mismatch count exceeded the bound;
- targets SHA-256:
  `sha256:1c55470e8a21c96e583dc3289a332c18125faf63115d5bec85b96c0e3c14bb79`.

Stored Paddle verification was frozen at `60cfc26` and reproduced byte for
byte. All four targets remained unresolved: one had no unique containing block
and three retained critical-token disagreement. Records SHA-256:
`sha256:19d8dfc4136ceaed3c58f2b51f625473bafe404a505dea9d33ace74a050dce5a`.

## Hidden table result

The localized-refusal policy was frozen at `132aa38` before hidden table truth
opened. All 503 pages and 199,543 critical-token opportunities were retained.
None of the four exact source-token hashes overlapped a missing event in the
ParseBench table ground truth.

| Metric | Fixed MinerU | Localized-refusal candidate |
| --- | ---: | ---: |
| Main-representation IRR | 0.786319 | 0.786319 |
| Main-representation mean loss | 0.213681 | 0.213681 |
| Hard-fail pages | 407 | 407 |
| SCLR / unit | 0.335984 | 0.335984 |
| SCLR / opportunity | 0.062292 | 0.062292 |
| Silent critical events | 12,430 | 12,430 |
| Localized unresolved fraction | — | 0.007952 |
| Historical raw provider USD / 1k pages | 0.997408 | 1.036524 |

The 5,000-replicate paired bootstrap SCLR delta is exactly 0 with interval
`[0, 0]`. Primary and reproduced result SHA-256:
`sha256:17ed17e33d2b1dc6c8b913c88fe45795f37b0cb0c319a18b25ace5cb898ba846`.

## Decision

Do not promote and do not run new GPU crops for these four targets. A crop
cannot improve the frozen measurable endpoint because its target token is
outside that endpoint. Together with the olmOCR result, this shows that the
current public benchmark assertions cannot validate the source-retention
failure class that the Router detects.

The next holdout must define full source-origin critical facts before inference,
bind every fact to an exact source region, retain missing outputs as failures,
and score recovery/refusal against those source facts. Only that benchmark can
decide whether RunPod region inference improves SCLR at acceptable cost and
latency.
