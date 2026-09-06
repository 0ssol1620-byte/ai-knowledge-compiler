# Unlimited-OCR — arena runtime

Long-horizon specialist (masterplan §3.1): *"primary page benchmark + 별도
long-horizon sidecar 가능"*. This directory is the **page** lane. The sidecar is
specified at the bottom and deliberately not wired up.

No TAVONEL measurement of this model exists. Every operational number in
`runtime.json` is a conservative starting point that the canary replaces.

## Official sources, as resolved on 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Model repo | `baidu/Unlimited-OCR` | `https://huggingface.co/api/models/baidu/Unlimited-OCR?blobs=true` |
| Model revision | `07dea832e22aefee32ad281d4b80551282e1c168` | same API response (`sha`), `lastModified` 2026-07-29T04:34:16Z |
| Largest weight file | `model-00001-of-000001.safetensors`, 6,672,547,120 B | same API response (`siblings[].lfs.sha256`) |
| Largest weight sha256 | `2bc48a7a110061ea58fff65d3169367eebe3aee371ca6968dc2219c1b2855fc6` | same |
| Architecture | `UnlimitedOCRForCausalLM`, `model_type: unlimited-ocr`, `trust_remote_code` | HF `config.json` |
| Code repo | `github.com/baidu/Unlimited-OCR` @ `d49ff64afffc1f47ab563dc1c589bc2f78808fa4` | `https://api.github.com/repos/baidu/Unlimited-OCR/commits?per_page=1` |
| Licence | MIT | HF `cardData.license` + GitHub `license.spdx_id` |

Not in `benchmark/v6/candidate-registry.yaml` — this is a new candidate for this
campaign, so there is nothing to cross-check the revision against.

**MIT is a copyright grant from these contributors. It says nothing about any
third party's patents.** The repository also vendors an SGLang wheel
(`wheel/sglang-0.0.0.dev11416+g92e8bb79e-py3-none-any.whl`) whose own licence is
separate from this repo's MIT; this runtime does not install it.

## Three official runtimes, and which one this lane uses

| Runtime | What the card gives | Used here |
|---|---|---|
| **Transformers** | a fully version-pinned dependency list and a single-image example | **yes** |
| vLLM (2026-06-28) | two official images, `vllm/vllm-openai:unlimited-ocr` (CUDA 13.0) and `:unlimited-ocr-cu129`, plus the recipe URL `recipes.vllm.ai/baidu/Unlimited-OCR` — **no configuration in the card itself** | no |
| SGLang | the repo's `infer.py`: `--attention-backend fa3`, `--page-size 1`, `--mem-fraction-static 0.8`, `--context-length 32768`, `DeepseekOCRNoRepeatNGramLogitProcessor(ngram_size=35, window_size=128)`, temperature 0 | no |

Transformers wins because it is the only path whose versions the card states.
The vLLM tags were resolved to digests anyway so the alternative is pinned if it
is ever taken:

```
vllm/vllm-openai:unlimited-ocr        sha256:542961a42d9183813819a23ef3a8b50bfb4f5ef7b0fb4f8e4f56edd8445efb18
vllm/vllm-openai:unlimited-ocr-cu129  sha256:e45cf562cbc885af2531f576e79377069e0a6f0af42cdad7658b8494185a1143
```

Taking the vLLM path would mean reading configuration out of a URL that is not
under version control, which is not a pin.

## The page configuration

The card gives two single-image modes:

```
gundam: base_size=1024, image_size=640,  crop_mode=True
base:   base_size=1024, image_size=1024, crop_mode=False
```

`gundam` is the card's own default (`infer.py --image_mode` defaults to
`gundam`, and the card's single-image example uses it), so it is the page lane.
Full call, as `adapter.py` makes it:

```python
model.infer(tokenizer,
            prompt='<image>document parsing.',
            image_file=<page png>, output_path=<scratch>,
            base_size=1024, image_size=640, crop_mode=True,
            max_length=32768,
            no_repeat_ngram_size=35, ngram_window=128,
            temperature=0.0,
            save_results=False, eval_mode=True)
```

Two deviations from the card's literal snippet, both deliberate:

1. **`eval_mode=True`, not `save_results=True`.** In `modeling_unlimitedocr.py`
   the `eval_mode` branch *returns the decoded string* with the
   `<｜end▁of▁sentence｜>` stop token removed and writes nothing; `save_results`
   writes `result.mmd` plus crops and returns nothing useful. `raw_text` must be
   the verbatim response.
2. **`temperature=0.0` stated explicitly.** It is the signature default, and at
   `0.0` the model's own code sets `do_sample=False`, so this is greedy decoding
   and not a change — it is written down so the `inference_config` hash covers it.

`no_repeat_ngram_size=35` with `ngram_window=128` selects the model's
`SlidingWindowNoRepeatNgramProcessor` rather than HuggingFace's plain
`no_repeat_ngram_size`. That is the card's configuration and it matters: without
the window, generation-loop suppression behaves differently.

### Prompt

| Use | Prompt | sha256 |
|---|---|---|
| **page lane (this runtime)** | `<image>document parsing.` | `a210f5b991d35d2a9a7d6c6160f54165c0ae96e02fbfdd1bc38400232021c303` |
| long-horizon sidecar | `<image>Multi page parsing.` | `649200b6dc0b513d1435fec851cfeaa863e524f7bf99443067ae42091a3bcdfb` |

`adapter.load()` **fails closed** on any prompt that does not hash to
`a210f5b9…`, and names the sidecar prompt specifically if it sees it, so the two
lanes cannot be crossed by a registry mistake.

Proposed prompt-registry id: `unlimited_ocr_document_parsing_v1` (lane A4 owns
`prompt_registry/`).

## Canonicalization

`canonical.py` is the card's `remove_det`, transcribed. Two quirks of that
function are kept because changing them would change what the official evaluator
is fed:

- A `<|det|>image …<|/det|>` line is skipped **without flushing the block being
  built**, so the lines after an image marker join the *previous* block.
- Blank lines are dropped before block assembly, so paragraph breaks inside a
  block are lost and blocks are re-joined with `\n\n`.

Both set `lossy=True` with a named note. The `det` categories and bboxes the
markdown loses are re-presented in `CanonicalOutput.elements` — including the
image markers, flagged `dropped_from_markdown: true`.

## Empty and truncated output

- **Empty**: returned with an `OUTPUT_EMPTY: …` warning, not raised. Masterplan
  §41 — a valid blank source page and a failed extraction are different things
  and the adapter cannot tell them apart.
- **Truncated**: the Transformers path exposes no finish reason, so truncation is
  **unknown** here, not `false`. This matters more for this model than for the
  others: `max_length=32768` is a long ceiling and a long-horizon model is
  exactly the kind that reaches it. A page whose output is near the cap should be
  treated as suspect by the QA gate (§44), which can see `output_tokens` from the
  receipt, not by this adapter guessing.

## Dependency pins

Every row is stated by the model card. **No version in this table is a lane
choice** — the only runtime in lane C2 where that is true.

| Package | Version |
|---|---|
| torch | 2.10.0 (cu129 index) |
| torchvision | 0.25.0 |
| transformers | 4.57.1 |
| Pillow | 12.1.1 |
| matplotlib | 3.10.8 |
| einops | 0.8.2 |
| addict | 2.4.0 |
| easydict | 1.13 |
| pymupdf | 1.27.2.2 |
| psutil | 7.2.2 |
| huggingface_hub | 1.17.0 — download stage only; cannot coexist with transformers 4.57.1 |

Card test environment: Python 3.12.3 + CUDA 12.9. The base image
`nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04` ships Python 3.12 on Ubuntu 24.04,
which matches. Ubuntu 24.04 marks the system interpreter externally managed, so
the runtime lives in `/opt/arena/venv` rather than being forced in with
`--break-system-packages`.

`matplotlib` and `pymupdf` are unused by this lane (the model's remote code
imports matplotlib lazily for geometry output; pymupdf is for the card's PDF
helper). They are installed anyway because dropping a pinned dependency the card
states would be a deviation, and a missing lazy import fails at inference time,
not at load.

## What the canary must confirm

1. `torch==2.10.0` resolves on the cu129 index and reports CUDA 12.9. The
   Dockerfile asserts both; if the wheel tag differs, the build fails rather than
   installing something else.
2. The checkpoint loads with `trust_remote_code=True` (required — the
   architecture is not in transformers) and `torch_dtype=torch.bfloat16`.
3. p50/p90/p95 seconds per page. **There is no prior measurement**, so
   `shard_size_hint: 25` and `per_page_timeout_seconds: 900` are guesses shaped
   by `max_length=32768`; the canary replaces them.
4. Whether `max_concurrency_per_worker` can go above 1.
5. Peak VRAM in gundam mode against `gpu_min_vram_gb: 24` (A40 first, then RTX
   4090 — masterplan §13.3). The checkpoint is 6.7 GB in bf16 and gundam adds a
   crop grid on top of the 1024 base view.
6. How often output lands near the 32,768-token ceiling, since truncation cannot
   be detected directly on this path.

## Long-horizon sidecar — specified, not wired

The model's headline claim is one-shot long-horizon parsing across a whole
document, which `infer_multi` does:

```python
model.infer_multi(tokenizer,
                  prompt='<image>Multi page parsing.',
                  image_files=[...],          # base mode only
                  image_size=1024,
                  max_length=32768,
                  no_repeat_ngram_size=35, ngram_window=1024,
                  save_results=True)
```

It is not part of this lane because the arena worker serves exactly one page per
`/v1/run` (ARENA_CONTRACT §4) and `sample_id` is page-scoped (§2). Running it
would need a document-scoped job shape, a different prompt id, its own
`inference_config` hash and its own canonicalization, and its results would not
be comparable page-for-page with the other eleven candidates. If the sidecar is
run, it must be a separate `model_key`, not a variant of this one — otherwise the
Model × Benchmark table (§28.1) silently mixes two contracts.

## Files

- `runtime.json` — frozen configuration, validated by
  `arena/core/schemas/runtime.schema.json` (lane A1).
- `adapter.py` — `ArenaModelAdapter`; also the build-time
  `--write-weights-receipt` helper, so the receipt the adapter verifies is
  written by the code that verifies it.
- `canonical.py` — the card's `remove_det`, transcribed.
- `Dockerfile` — two stages (weights download, runtime). Build context is the
  namespace root.
- `bootstrap.sh` — canary-only. Never used for a Full Run (§15.1).
