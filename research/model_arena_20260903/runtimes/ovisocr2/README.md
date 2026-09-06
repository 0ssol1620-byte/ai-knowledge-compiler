# OvisOCR2 — arena runtime

Compact 0.8B end-to-end page parser; the "official runtime으로 반드시 재검증"
candidate (masterplan §3.1) and the subject of **hypothesis H3**: *does re-running
OvisOCR2 on the official runtime close the previous TAVONEL discrepancy?*

Everything in this directory is written so that H3 has a clean answer. Where the
2026-08 TAVONEL run differed from the official model card, the difference is
listed below with an explicit keep-or-drop decision. No difference in inference
semantics is kept.

## Official sources, as resolved on 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Model repo | `ATH-MaaS/OvisOCR2` | `https://huggingface.co/api/models/ATH-MaaS/OvisOCR2?blobs=true` |
| Model revision | `1fc9221b7823a371d6e97f92d527cc847e24e107` | same API response (`sha`), `lastModified` 2026-08-28T08:46:00Z |
| Largest weight file | `model.safetensors`, 1,706,030,496 B | same API response (`siblings[].lfs.sha256`) |
| Largest weight sha256 | `9270560288656ece5cb3a6989001afcf5af8d223bceed4a423c33a008861d009` | same |
| Base model | `Qwen/Qwen3.5-0.8B`, `model_type: qwen3_5` | HF `cardData` + `config.json` |
| Official runtime | `vllm==0.22.1` | model card "Inference" section |
| Licence | Apache-2.0 | HF `cardData.license` + repo `LICENSE` |

**Revision moved, weights did not.** `benchmark/v6/candidate-registry.yaml` pins
`65c619d374b55d4152e85150fc1b003700bc1f0c` from the 2026-08 campaign. The current
revision is `1fc9221b…`, but `model.safetensors` still hashes to
`9270560288…` — the identical value asserted in
`infra/runpod/v6/images/ovisocr2-m1/Dockerfile`. The checkpoint is byte-identical;
only repository metadata moved. **This means H3 cannot be explained away as "a
different checkpoint".**

**Apache-2.0 is a copyright grant from these contributors. It says nothing about
any third party's patents.**

## What the previous TAVONEL run actually measured

`benchmark/reports/OVISOCR2_0_9B_VLLM_CU129_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md`,
18 OmniDocBench demo pages × 3 repeats:

- text edit distance 0.097963 — roughly 3× worse than every other candidate in
  the same 18-page cohort (masterplan §5.1: PaddleOCR-VL 0.038209, MinerU
  pipeline 0.036507, MinerU VLM 0.034258, DeepSeek-OCR-2 0.032428)
- **overall and CDM were unavailable and were correctly not reported as zero.**
  So the published 96.58 OmniDocBench v1.6 overall was never contradicted by a
  TAVONEL overall; the anomaly in the record is the text edit distance.
- prompt sha256 `c0fb65bf41705f32189c0e2407d824db52a68a365024239b2029a7a283f64567`

That prompt hash is the first thing this runtime fixes.

## Deviation ledger — 2026-08 run vs the official model card

| # | Model card | 2026-08 `benchmark/runpod_eval/ovisocr2_stage2.py` | Decision |
|---|---|---|---|
| 1 | Prompt begins with a newline (`'\nExtract all readable…'`) | no leading newline | **dropped** — card restored |
| 2 | `…standard Markdown.` **space** `Preserve the original text…` | newline instead of the space | **dropped** — card restored |
| 3 | `strip()` → `filter_imgtags` → `_clean_truncated_repeats` | `_clean_truncated_repeats` → filter → `strip()` | **dropped** — card order restored |
| 4 | filter predicate `block.strip().startswith('<img src="images/bbox_')` | full-match regex `^\s*<img …/>\s*$` | **dropped** — card predicate restored |
| 5 | no `.strip()` after the `"\n\n".join` | extra `.strip()` after the join | **dropped** |
| 6 | `LLM(...)` without `trust_remote_code` | `trust_remote_code=True` | **dropped** — canary must confirm the checkpoint loads without it |
| 7 | not mentioned | `VLLM_WORKER_MULTIPROC_METHOD=spawn` | **kept** — operational, cannot change what the model emits; reported in runtime provenance and set in the Dockerfile so it is visible |
| 8 | not mentioned | venv `bin` prepended to `PATH` for FlashInfer's JIT `ninja` | **dropped** — the arena image has one system Python, no venv |
| 9 | `parse()` batches the whole image list into one `generate` | batches of 2 | **neither** — the arena worker serves one page per `/v1/run` (ARENA_CONTRACT §4), so the batch is always 1. Recorded as a forced deviation from both. |
| 10 | `gpu_memory_utilization=0.8`, `gdn_prefill_backend="triton"`, `tensor_parallel_size=1` | same | kept |
| 11 | `SamplingParams(max_tokens=16384, temperature=0.0)` | same | kept |
| 12 | `min_pixels=448*448`, `max_pixels=2880*2880` | same | kept |
| 13 | `apply_chat_template(tokenize=False, add_generation_prompt=True, enable_thinking=False)` | same | kept |

Rows 1–2 are the substantive ones. The two prompt strings and their hashes:

```
official  (513 chars) sha256 de9617f877f6110d22adf1a6ba2a96221189dc246fb1fef161e408d37bff5267
2026-08   (512 chars) sha256 c0fb65bf41705f32189c0e2407d824db52a68a365024239b2029a7a283f64567
```

`adapter.load()` **fails closed** on any prompt that does not hash to
`de9617f8…`, and it names the 2026-08 hash specifically when it sees it, so the
old spelling cannot come back silently.

Proposed prompt-registry id: `ovisocr2_page_markdown_v1` (lane A4 owns
`prompt_registry/`; this runtime only pins the hash).

**Row 9 is a real limitation of this campaign, not a fix.** Batch size can change
vLLM scheduling and therefore numerics. If the canary still reproduces a low text
edit distance, batch size 1 is a live remaining explanation and H3 must say so
rather than concluding "the prompt was the cause".

## Canonicalization

`canonical.py` is the card's `parse()` tail, in the card's order. `lossy=True`
with a named note when `filter_imgtags` drops a visual-region block (bbox
coordinates leave the markdown) or when `_clean_truncated_repeats` trims a
repeating tail (which means the page degenerated — the raw file keeps the
untrimmed text). `elements` is `None`: this model emits a single markdown
document with no separable structure to re-present.

## Empty and truncated output

- **Empty**: returned with an `OUTPUT_EMPTY: …` warning, not raised. Masterplan
  §41 — a valid blank source page and a failed extraction are different things
  and the adapter cannot tell them apart. The QA gate (§44) decides.
- **Truncated**: vLLM does expose `finish_reason`, so `finish_reason == "length"`
  at the 16,384-token cap emits an `OUTPUT_TRUNCATED` warning. This is real
  information the Transformers-based runtimes in this campaign do not have.

## Dependency pins

Every version comes from the base image, which is asserted at build:

| Package | Version | Pinned by |
|---|---|---|
| vllm | 0.22.1+cu129 | model card (`pip install "vllm==0.22.1"`); supplied by the base image |
| huggingface-hub | 1.17.0 | base image; used only for `hf download` |
| pillow | 12.2.0 | model card (`pip install … pillow`); supplied by the base image |
| transformers | 5.10.2 | base image (transitive) |

Base image
`docker.io/vllm/vllm-openai@sha256:e1668bce9790a4b86682f8fcc99678153a13e12dc70e05348d8e239ffa474b05`.
That digest was pinned and its four versions asserted during the 2026-08
campaign in `infra/runpod/v6/images/ovisocr2-m1/Dockerfile`; this runtime
re-asserts them rather than trusting the record. **This Dockerfile installs no
Python package at all** — it verifies. Nothing to drift, no `pip install -U`.

## What the canary must confirm

1. The checkpoint loads under vLLM 0.22.1 **without** `trust_remote_code`
   (deviation 6). If it does not, that is a finding, not a reason to add the flag
   back silently — record it and re-run with the flag as a named second variant.
2. `gdn_prefill_backend="triton"` is accepted by vLLM 0.22.1 on the chosen GPU
   (RTX 4090 first, masterplan §13.3).
3. p50/p90/p95 seconds per page against the historical 6.171 s/page, which is
   what `shard_size_hint: 150` and `per_page_timeout_seconds: 300` were set from.
4. Whether `max_concurrency_per_worker` can go above 1.
5. Peak VRAM at `max_pixels = 2880 × 2880` and `gpu_memory_utilization = 0.8`
   against `gpu_min_vram_gb: 24`.
6. **Repeatability.** The 2026-08 run found 16 of 18 pages byte-identical across
   three repeats; two pages differed between the first (JIT-warming) repeat and
   repeats two and three. The two-stage readiness warm-up (ARENA_CONTRACT §4)
   should absorb that, and the canary should show whether it does.

## Known incidents

- The prompt drift above.
- First-repeat JIT warming changed two of 18 pages in 2026-08
  (`OVISOCR2_RUNPOD_STAGE1_DIAGNOSTIC_2026-08-01.md`,
  `OVISOCR2_0_9B_VLLM_CU129_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md`).
- vLLM's default `fork` start method breaks after CUDA initialisation; the
  `spawn` setting (deviation 7) is why.

## Files

- `runtime.json` — frozen configuration, validated by
  `arena/core/schemas/runtime.schema.json` (lane A1).
- `adapter.py` — `ArenaModelAdapter`; also the build-time
  `--write-weights-receipt` helper, so the receipt the adapter verifies is
  written by the code that verifies it.
- `canonical.py` — the model card's post-processing, transcribed in its order.
- `Dockerfile` — single stage; verifies, never installs.
- `bootstrap.sh` — canary-only. Never used for a Full Run (§15.1).
