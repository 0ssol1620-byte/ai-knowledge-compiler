# Source-bound region inventory — 2026-09-10

## Status

`RESEARCH_IMPLEMENTED`. This is a runtime-visible availability result over the
spent public olmOCR-Bench development source set. It is not an OCR score, a
fresh holdout, a model qualification, a routing superiority result, or a
production promotion.

## Frozen scope

- 1,403 PDF units from campaign
  `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`.
- Source manifest SHA-256:
  `sha256:2ec00f371db5069216362ee946b084ed0d222474162d7eadcbf717f09ae55e7c`.
- Inputs were the source manifest and original public PDFs only. Benchmark
  labels, evaluator outputs and hidden score files were not read.
- The capture writes block IDs, `bbox1000`, witness digests and counts. It does
  not write document text.
- GPU budget and observed GPU cost were both USD 0.

## Result

| Outcome | Units | Share |
|---|---:|---:|
| Exact source regions available | 1,178 | 83.9629% |
| No eligible source text region | 173 | 12.3307% |
| Native runtime dependency unavailable | 49 | 3.4925% |
| Native parser refused malformed/bounded PDF case | 3 | 0.2138% |
| **Total** | **1,403** | **100%** |

The available pages exposed 268,196 exact text regions, an average of 227.67
per available page. 1,066 of the 1,178 available pages (90.4924%) contain at
least one overlapping pair, with 974,609 overlapping pairs in total. This
proves that a whole-page "replace every region" merge is unsafe. A recovery
plan must name a small target set and bind each target to its unchanged block,
source version, representation digest, page and exact bbox.

The three explicit parser refusals were one decompression-limit case and two
PDF image-metadata cases. They remain in the denominator. No failed or missing
page was dropped.

## Determinism

Two independent runs of the final code produced the same 1,403 rows, status
distribution, counts and byte-identical `regions.jsonl`:

- final: `.chatgpt2codex/router-region-inventory-20260910-v3-final`
- reproduction: `.chatgpt2codex/router-region-inventory-20260910-v4-reproduction`
- shared regions SHA-256:
  `sha256:3de6602ad7ee5894c8e26caf43bf398ed9a558a1fdaac734f41244729239c0e7`
- wall time: 184.57 s and 185.10 s

## Implemented contract

`packages/router/src/akc_router/region_recovery.py` now:

1. projects only non-empty CIR text blocks with one exact `SourceRef` and an
   explicit positive-area `bbox1000`;
2. records missing or multi-source geometry as unresolved instead of inventing
   a crop;
3. binds every execution region to source and representation SHA-256, page,
   opaque region ID, block revision and original content hash;
4. creates an immutable replacement candidate only from independently verified
   text-region results;
5. refuses partial, stale, foreign, overlapping or quarantined merge sets; and
6. keeps `production_promotion = false`.

Targeted recovery can select a strict subset of localized regions, so an
unrelated block without geometry does not force a whole document rerun. It may
not silently widen that subset after execution starts.

## Verification

- 84 targeted execution/projection tests passed.
- Ruff passed.
- Strict mypy passed.
- Source projection SHA-256:
  `c7a75a889fb7ef49ba7b645ec14a4bd349bc5b81d1dc5000b981291c8a4e53a4`.
- Freeze SHA-256:
  `97aa7dacbf15c2eac45a578d0a7968240a1228887344c6240bf4e41b8adc3209`.
- Capture code SHA-256:
  `f56f42174054e2be88041d2288df971481fe13630bc2a4a0789df61c970f79f2`.
- Exact implementation head before this report:
  `b14979bcc4fa3bf2d49acc16f615666e47aef3b7`.

## Next bounded experiment

Use runtime-visible Native-versus-primary critical-token disagreement to select
only uniquely localized source blocks. Freeze the target-selection algorithm,
crop renderer, specialist model/runtime, maximum target count, spend ceiling,
timeout and independent verifier before sending any crop to RunPod. Compare
the region candidate with the retained whole-page baseline and keep every
unresolved target in the denominator. If a mismatch cannot be uniquely mapped
to one source region, do not invoke a model for it.
