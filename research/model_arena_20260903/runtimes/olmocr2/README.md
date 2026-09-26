# olmOCR-2-7B-1025-FP8 — arena runtime

The benchmark-family reference baseline (masterplan §3.1). One of the three scored
corpora is olmOCR-Bench, and this is that family's own model — a conflict of
interest that stays visible in the report rather than being netted out.

## Official sources, resolved 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Checkpoint | `allenai/olmOCR-2-7B-1025-FP8` | HF model card |
| Revision | `40bd7202494b8264ee17ada08b401b5aab7a9ce1` | HF API — matches `benchmark/v6/candidate-registry.yaml` |
| Base model | `Qwen/Qwen2.5-VL-7B-Instruct`, FP8 via llmcompressor | HF card + `config.quantization_config` |
| Weights | 3 shards, **10,061,929,760 bytes (10.06 GB)** | HF blob listing |
| Largest file | `model-00001-of-00003.safetensors`, 4,940,102,568 B, `sha256:5d5550dbb21e309786fde9a151442181562cf9dc23141116a4e46e3e815b0d02` | HF blob listing |
| Toolkit | `github.com/allenai/olmocr` **v0.4.27** = `1e139a5ea61f1668164e6b63357d7284a8391615`, released 2026-03-12 | GitHub releases + commits feed |
| Toolkit pins | `transformers==4.57.3`, `vllm==0.11.2` | `pyproject.toml` `[gpu]` extra at that tag |
| Base image | `vllm/vllm-openai:v0.11.2@sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331` | the toolkit's own `Dockerfile` at that tag, digest from Docker Hub |
| Licence | Apache-2.0 (model and toolkit), plus Ai2's Responsible Use Guidelines | model card, `LICENSE` present in the repo |

## The three things the toolkit decides, and this runtime obeys

**Prompt.** `olmocr.prompts.build_no_anchoring_v4_yaml_prompt()` at v0.4.27. The
adapter never carries a copy: lane A4 registers the text as
`olmocr2_no_anchoring_v4_yaml_v1`, and `load()` compares the registered text with
what the *installed* toolkit builds. Any drift is a `MODEL_LOAD` failure. The
Dockerfile makes the same check at build time.

**Sampling.** `olmocr/pipeline.py::build_page_query` sets `max_tokens = 8000` and
`temperature = 0.0` on the first attempt. The toolkit's retry ladder
(`TEMPERATURE_BY_ATTEMPT = [0.1, 0.1, 0.2, 0.3, 0.5, 0.8, 0.9, 1.0]`) is **not**
implemented here: the adapter API forbids retries inside the adapter, retry policy
belongs to the controller (§15.9). This is a deliberate, recorded difference from
the vendor's published pipeline score — the card's 82.4 ± 1.1 was measured *with*
that retry-and-rotate ladder, so it is quoted, never treated as reproduced.

**Image handling — the one real deviation.** The toolkit renders a PDF page with
`pdftoppm` at `target_longest_image_dim * 72 / longest_media_box_dim` DPI, default
**1288 px on the longest side**. The arena stages one common PNG render for every
model (§6.3), so the adapter *resamples* that PNG to 1288 px with Lanczos and
**never upscales** a smaller page. Resampling a raster is not the same operation as
re-rendering a vector page. Every receipt records `resize_policy`, the source
dimensions, the served dimensions and whether a resize happened.

## FP8: which pools actually qualify

`config.quantization_config` is compressed-tensors `float-quantized`, 8-bit weights
(the vision tower's first blocks are in the `ignore` list). Native FP8 tensor-core
execution needs **compute capability ≥ 8.9**:

| Pool | Arch | sm | Native FP8 |
|---|---|---|---|
| RTX 4090 | Ada | 8.9 | yes |
| L40S / L4 / RTX 6000 Ada | Ada | 8.9 | yes |
| H100 / H200 | Hopper | 9.0 | yes |
| **A40** | Ampere | 8.6 | **no** |
| A100 | Ampere | 8.0 | **no** |

Masterplan §13.3 lists this lane as "4090/A40". **A40 is left out of
`gpu_pool_priority` on purpose.** On Ampere, vLLM does not run these kernels
natively and may select a dequantising path; that is a *different condition*, not a
slower one, and mixing it into a same-condition comparison would break the fair
comparison contract (§6.1). `entrypoint.sh` prints each device's real compute
capability and whether native FP8 applies before vLLM starts, so the canary receipt
carries the answer instead of an assumption about a GPU's name.

## What the canary must confirm

1. vLLM 0.11.2 loads the FP8 checkpoint on the chosen pool and the log names an FP8
   kernel, not a fallback.
2. The device capability line printed by `entrypoint.sh` says `native_fp8=True`.
3. The prompt check passed (it is a hard failure, so a running worker already proves
   this — the canary just has to see the receipt).
4. `max_tokens 8000` covers the densest canary page; truncation shows up as
   `arena.semantic_error_class=OUTPUT_TRUNCATED`.
5. The front matter block parses on every canary page. `canonical.py` lifts it into
   `elements`; a page with no front matter is flagged, not silently accepted.
6. p50/p90/p95, peak VRAM, projected GPU-hours and cost for 5,132 pages.

## Files

| File | Role |
|---|---|
| `runtime.json` | frozen identity, pins, pools, official inference config |
| `adapter.py` | `ArenaModelAdapter`; stdlib at import time, PIL/olmocr injected at load |
| `canonical.py` | YAML front matter → `elements`, markdown body verbatim |
| `fetch_weights.py` | pinned download + revision/sha256 verification + sidecar |
| `Dockerfile` | baked image and weights; build-time prompt and version assertions |
| `entrypoint.sh` | weights → capability print → `vllm serve` → worker server |
| `bootstrap.sh` | canary-only path from the bare base image |

## Semantic failures travel in `warnings`

Same convention as every C3 runtime: the bytes are always returned verbatim (§7) and
the classification rides in `RawOutput.warnings` behind
`arena.semantic_error_class=` (`OUTPUT_EMPTY`, `OUTPUT_TRUNCATED`,
`OUTPUT_REPETITION`). A dedicated field is proposed in the lane report. The adapter
does not decide whether an empty response means a blank source page — masterplan §41
puts that call on the source-preflight side.

## `prompt_kind: toolkit` (D34) and what lane R must write

The registry file holds exactly what
`olmocr.prompts.build_no_anchoring_v4_yaml_prompt()` returns at toolkit revision
`1e139a5ea61f1668164e6b63357d7284a8391615` (v0.4.27). `adapter.load` hashes the built
text and fails closed on drift, and the text that goes on the wire is the built one,
never the registry copy.

**Caution for lane R:** A4's `olmocr2_official_v1` entry records
`build_finetuning_prompt` -- the *anchored* v1 prompt with a `{base_text}`
placeholder. That is not this runtime's prompt. `olmocr2_no_anchoring_v4_yaml_v1` must
resolve to the no-anchoring v4 YAML builder named in
`inference_config.toolkit_prompt_builder`.

## Boot sequence (D19)

`entrypoint.sh` starts the model server in the background, polls
`http://127.0.0.1:<port>/v1/models` until it answers (default deadline above the
20-minute contract floor; `ARENA_MODEL_SERVER_READY_TIMEOUT_S` overrides it and a
value under 1200 s is refused), then runs `python3 -m arena.worker.server` **as a
child**, `wait`s on it and exits with its status. It does not `exec` the worker:
`exec` would discard the `trap` and orphan the server. A readiness timeout or a
server that dies during load exits non-zero and the trap stops the server.
