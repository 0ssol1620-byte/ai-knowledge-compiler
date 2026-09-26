# DeepSeek-OCR-2 — arena runtime

Text-fidelity challenger (masterplan §3.1). Historical TAVONEL best text edit
distance on the 18-page controlled subset (0.032428) and the slowest of that
cohort at 47.200 s/page (§5.1).

## Official sources, as resolved on 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Model repo | `deepseek-ai/DeepSeek-OCR-2` | `https://huggingface.co/api/models/deepseek-ai/DeepSeek-OCR-2?blobs=true` |
| Model revision | `aaa02f3811945a91062062994c5c4a3f4c0af2b0` | same API response (`sha`), `lastModified` 2026-02-03T00:33:19Z |
| Largest weight file | `model-00001-of-000001.safetensors`, 6,778,573,880 B | same API response (`siblings[].lfs.sha256`) |
| Largest weight sha256 | `d8ff67a424ba6f4dd077885eb9d6a05d2537e76fe5491f0e2a9b712f8c8870fa` | same |
| Code repo | `github.com/deepseek-ai/DeepSeek-OCR-2` @ `2f3699ebbb96fa8af32212e8c170f2cc28730fad` | `https://api.github.com/repos/deepseek-ai/DeepSeek-OCR-2/commits?per_page=1` |
| Licence | Apache-2.0 | HF `cardData.license` + GitHub `license.spdx_id` + `LICENSE.txt` |

The revision matches `benchmark/v6/candidate-registry.yaml` → `deepseek-ocr-2`
(`revision: aaa02f3811945a91062062994c5c4a3f4c0af2b0`), so no re-pin was needed.

**Apache-2.0 is a copyright grant from these contributors. It says nothing about
any third party's patents** (project constitution, FTO rules). Do not read
"approved" in `runtime.json` as freedom to operate.

## The official path, and what this runtime actually runs

The repository ships two entry points:

- `DeepSeek-OCR2-master/DeepSeek-OCR2-hf/run_dpsk_ocr2.py` — Transformers,
  one image, `AutoModel.infer(...)`, `flash_attention_2`, bf16.
- `DeepSeek-OCR2-master/DeepSeek-OCR2-vllm/run_dpsk_ocr2_eval_batch.py` — **the
  OmniDocBench batch script**, vLLM, whose knobs live in `.../vllm/config.py`.

The official *numbers* come from the batch script, so its configuration is
authoritative:

```
PROMPT     = '<image>\n<|grounding|>Convert the document to markdown.'
BASE_SIZE  = 1024
IMAGE_SIZE = 768
CROP_MODE  = True     (MIN_CROPS=2, MAX_CROPS=6 — vLLM preprocessor only)
SamplingParams(temperature=0.0, max_tokens=8192, skip_special_tokens=False)
NoRepeatNGramLogitsProcessor(ngram_size=40, window_size=90,
                             whitelist_token_ids={128821, 128822})
LLM(block_size=256, max_model_len=8192, gpu_memory_utilization=0.7,
    enforce_eager=False, VLLM_USE_V1=0)
```

`adapter.py` takes that **configuration** and runs it through the **Transformers**
entry point, `AutoModel.infer(..., eval_mode=True)`. Two deviations, both
deliberate:

1. **Runtime: Transformers, not vLLM.** The arena worker serves exactly one page
   per `/v1/run` (ARENA_CONTRACT §4); the batch script's only advantage over the
   Transformers path is batching 100 pages into one `llm.generate` call, which
   the worker contract cannot use. Choosing vLLM would also mean vendoring
   `deepseek_ocr2.py`, `deepencoderv2/` and `process/` from the repository into
   the image and pinning an unstated vLLM version — the repo's
   `requirements.txt` does not pin vLLM at all.
2. **`eval_mode=True`, not `save_results=True`.** In
   `modeling_deepseekocr2.py` the `eval_mode` branch *returns the decoded string*
   with the `<｜end▁of▁sentence｜>` stop token removed and no file side effects;
   the `save_results` branch writes `result.mmd` plus cropped images and returns
   nothing useful. `raw_text` must be the verbatim response, so `eval_mode` is
   the only correct choice.

**Consequence of the Transformers path.** The `eval_mode` branch hardcodes its
generation kwargs (`temperature=0.0`, `max_new_tokens=8192`,
`no_repeat_ngram_size=35`, `use_cache=True`) inside the checkpoint's remote code.
The adapter cannot pass them. They are still recorded in
`runtime.json.inference_config` so the `inference_config_sha256` covers what will
actually run. Note `no_repeat_ngram_size` is **35** on this path and **40 with a
90-token window and a `<td>`/`</td>` whitelist** on the vLLM path: the two
official paths differ from each other, and this is recorded, not smoothed over.

### Prompt

Two official spellings exist and they hash differently:

| Source | Prompt | sha256 |
|---|---|---|
| `DeepSeek-OCR2-vllm/config.py` (batch script) | `<image>\n<\|grounding\|>Convert the document to markdown.` | `00a105b332827a249e76115332aef75dfdf7578e026c25fef1a35662a81efa32` |
| HF model card / `run_dpsk_ocr2.py` | same **plus one trailing space** | `a7e799e8c5c81073d707c01e12c7850d693ac14168a878ccfb3b4f70a6a49b58` |

The batch-script spelling is used. `adapter.load()` **fails closed** if the prompt
handed to it by the prompt registry does not hash to `00a105b3…`. The previous
TAVONEL run (`benchmark/runpod_eval/deepseek_ocr2_stage2.py`) used the
trailing-space variant; that is a difference in the campaign record, not a
correction applied silently.

Proposed prompt-registry id: `deepseek_ocr2_grounding_markdown_v1` (lane A4 owns
`prompt_registry/`; this runtime only pins the hash).

## Canonicalization

`canonical.py` transcribes the batch script's post-processing exactly, including
two behaviours that look like bugs and are kept because changing them would
change what the official evaluator is fed:

- `clean_formula` strips `\quad (...)` from inside `\[ … \]` display formulas.
  That deletes equation tags the model emitted → `lossy=True` with a note.
- The `\n\n\n\n → \n\n` collapsing runs *inside* the loop over grounding matches,
  so a page with **no** `<|ref|>…<|det|>` markers is never collapsed.

Grounding markers are removed from the markdown (official behaviour) but their
category and raw `det` payload are re-presented in `CanonicalOutput.elements`;
`lossy=True` records that their position in the markdown is gone. The HF
`save_results` branch additionally rewrites `\coloneqq`/`\eqqcolon` and converts
image refs to `![](images/N.jpg)`; the batch script does not, so neither does
this runtime.

## Empty and truncated output

- **Empty**: the adapter returns the empty response with a
  `OUTPUT_EMPTY: …` warning rather than raising. Masterplan §41 is explicit that
  a valid blank source page and a failed extraction are different things, and the
  adapter has no way to tell them apart. The QA gate (§44) decides.
- **Truncated**: the Transformers path does not expose a finish reason, so
  truncation is **unknown** at this layer, not `false`. `finish_reason` is `None`
  in `BackendResult` and no truncation warning is emitted. The vLLM path would
  expose it; that is a cost of deviation 1 above and is listed as such.

## Dependency pins

| Package | Version | Pinned by |
|---|---|---|
| torch | 2.6.0 (+cu118) | model card, supplied by the base image, asserted at build |
| transformers | 4.46.3 | model card + `requirements.txt` |
| tokenizers | 0.20.3 | model card + `requirements.txt` |
| flash-attn | 2.7.3 | model card (`--no-build-isolation`) |
| einops | 0.8.1 | **arena-chosen** — upstream lists it unpinned |
| addict | 2.4.0 | **arena-chosen** — upstream lists it unpinned |
| easydict | 1.13 | **arena-chosen** — upstream lists it unpinned |
| Pillow | 11.1.0 | **arena-chosen** — upstream lists it unpinned |
| numpy | 1.26.4 | **arena-chosen** — upstream lists it unpinned |
| packaging / ninja | 24.2 / 1.11.1.3 | **arena-chosen** — flash-attn build tooling |
| huggingface_hub | 1.17.0 | download stage only; cannot coexist with transformers 4.46.3 |

The arena-chosen rows are a lane decision made on 2026-09-03, not an upstream
statement. Lane F's build is what confirms they resolve; a mismatch fails the
build rather than degrading quietly (`pip install` has no `-U` anywhere).

The model card was tested on Python 3.12.9 + CUDA 11.8. The pinned base image
`pytorch/pytorch:2.6.0-cuda11.8-cudnn9-devel` ships **Python 3.11**. That is a
recorded deviation; the canary must confirm it.

## What the canary must confirm

1. `flash_attention_2` actually loads on the chosen GPU (A40 first, then RTX
   4090 — masterplan §13.3) and the build's compiled `flash-attn==2.7.3` matches
   the driver.
2. `AutoModel.infer(..., eval_mode=True)` returns a `str` and the weights receipt
   verifies (revision + full manifest) at load.
3. p50/p90/p95 seconds per page against the historical 47.200 s/page, which is
   what `per_page_timeout_seconds: 900` and `shard_size_hint: 25` were set from.
4. Whether `max_concurrency_per_worker` can go above 1. It is 1 until the canary
   says otherwise; scaling is replicas only until then.
5. Peak VRAM under `crop_mode=True` with up to 6 × 768 crops plus the 1024 base
   view, against `gpu_min_vram_gb: 24`.

## Known incidents

- The previous TAVONEL run used the trailing-space prompt variant (above).
- `benchmark/reports/DEEPSEEK_OCR_2_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md`
  is the 18-page × 3 measurement this runtime is being re-pinned against. It ran
  each case in a killable child process because of a per-case hang risk at
  900 s; the arena worker gets the same protection from the server-side per-page
  timeout in ARENA_CONTRACT §4, not from the adapter (the adapter never retries).

## Files

- `runtime.json` — frozen configuration, validated by
  `arena/core/schemas/runtime.schema.json` (lane A1).
- `adapter.py` — `ArenaModelAdapter`; also the build-time
  `--write-weights-receipt` helper, so the receipt the adapter verifies is
  written by the code that verifies it.
- `canonical.py` — official post-processing, transcribed.
- `Dockerfile` — two stages (weights download, runtime). Build context is the
  namespace root.
- `bootstrap.sh` — canary-only. Never used for a Full Run (§15.1).
