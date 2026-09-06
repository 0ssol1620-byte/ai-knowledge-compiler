# Infinity-Parser2-Pro — arena runtime

Precision flagship of the open lane (masterplan §3.1). This runtime exists to test
**§47 H4**: whether the vendor's published ParseBench 74.3 / olmOCR-Bench 87.6
reproduce on the campaign's pinned evaluators. Those numbers are *quoted from the
model card*, never claimed as reproduced.

## Official sources, resolved 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Checkpoint | `infly/Infinity-Parser2-Pro` | HF model card |
| Revision | `b27d470100514329fc6439aada8f16ccea5f9e2a` | `GET /api/models/infly/Infinity-Parser2-Pro?blobs=true` — matches `benchmark/v6/candidate-registry.yaml` |
| Architecture | `Qwen3_5MoeForConditionalGeneration` | HF `config` |
| Weights | 15 safetensors shards, **70,214,492,328 bytes (70.21 GB)** | HF blob listing |
| Largest file | `model-00006-of-00015.safetensors`, 32,423,724,072 B, `sha256:84eee8d855324eab6838e8aefbc4c42aa67c29d9de24813712f5dc4ff6cd2b81` | HF blob listing |
| Serving stack | `vllm==0.17.1` | model card, "Pre-requisites" |
| Base image | `vllm/vllm-openai:v0.17.1@sha256:0dc46f74eb0e630675d83101dc66c6441c4475cceedcf9235ee42b87c3affd23` | Docker Hub manifest, resolved by digest |
| Model licence | Apache-2.0 | model card + `license:apache-2.0` tag |
| Runtime repo | `github.com/infly-ai/INF-MLLM` @ `cb7534339205968cc059121da94922b11c003b2a` | GitHub commits feed |

Prompt: the doc2json prompt printed on the model card is registered by lane A4 as
`infinity_parser2_pro_doc2json_v1`. This runtime never carries its own copy of the
prompt text; it receives it through `AdapterConfig.prompt_text` and its sha256
lands in every receipt.

Sampling, all from the card verbatim: `max_tokens 32768`, `temperature 0.0`,
`top_p 1.0`, `min_pixels 2048`, `max_pixels 16777216`,
`chat_template_kwargs {"enable_thinking": false}`.

Serve flags, all from the card verbatim: `--trust-remote-code --reasoning-parser
qwen3 --tensor-parallel-size 2 --gpu-memory-utilization 0.85 --max-model-len 65536
--mm-encoder-tp-mode data --mm-processor-cache-type shm --enable-prefix-caching`.

## Licence: `blocked`, and why that is not about the weights

`runtime.json.license.status` is `blocked`. The **checkpoint** is Apache-2.0 and
that is not in doubt. The **official runtime wrapper**, `infly-ai/INF-MLLM`, ships
**no LICENSE file** — not at the repository root and not under `Infinity-Parser2/`
(checked 2026-09-03 through the GitHub contents API; the repo's `license` field is
`null`). Under the FTO blueprint's rules that is decisive:

- *Readable is not reusable.* A public repository with no LICENSE grants no
  commercial reuse right. Its paper may be read; its code may not be copied,
  translated, ported or vendored.
- *Code, weights, dataset and hosted-API terms are four separate licences.*
  Clearing the weights clears nothing about the wrapper.
- *An OSS licence is not patent freedom to operate*, in either direction.

**The design-around:** this runtime installs no `infinity_parser2` package and
vendors no INF-MLLM code. It runs the `vllm serve` command the *model card itself*
prints and posts to the OpenAI-compatible endpoint with the *model card's own*
prompt and sampling values. Everything used is on the Apache-2.0 model card.
Whether `blocked` clears is a founder decision, not an agent's.

## VRAM: where 160 GB comes from

Measured, not assumed. The HF blob listing at the pinned revision sums to
**70.21 GB** of safetensors, with two 32.42 GB MoE expert shards. At bf16 the
weights alone leave under 10 GB on an 80 GB device — not a working KV cache at the
card's `--max-model-len 65536`. That is why the card prints
`--tensor-parallel-size 2`.

`runtime.json.gpu_min_vram_gb: 160` is therefore **aggregate across two 80 GB
devices**, not per-device. Masterplan §13.3 puts this lane on A100 80 / H100 and
marks the canary **mandatory** — the canary, not this file, decides whether TP=2 is
required or a single 80 GB device with a reduced `max_model_len` suffices, and it
is the only thing allowed to move `full_run_eligible` to true.

## Weights strategy: `baked`, and `runtime_mode_allowed: ["baked"]` (D36)

ARENA_CONTRACT D36 (2026-09-03) reversed this lane's earlier `volume_cache` choice
and closed bootstrap mode for this model. The reason is the stall risk, not tidiness:
at **70.21 GB** every non-baked path pays the fetch where it hurts most — bootstrap
downloads the checkpoint inside a metered canary pod, and `volume_cache` pays the
same wait once into a network volume the canary still has to sit through. Masterplan
§15.1 exists to keep that download out of a paid pod.

So `Dockerfile` runs `fetch_weights.py --manifest` at **build** time into
`/opt/arena/weights/infinity_parser2_pro`, and the pod boots against a local
directory. The cost moved; it did not vanish — the image is roughly 78 GB and the
build lane must size it as baked, not as a bare vLLM base. `bootstrap.sh` is kept
(deleting it would leave nothing to refuse with) and now reads
`runtime.json.runtime_mode_allowed` and exits 64 rather than starting that download.

This runtime's canary therefore waits for two things: that image, and the founder's
licence decision (`license.status: blocked`).

## What the canary must confirm

1. vLLM 0.17.1 loads a Qwen3.5-MoE checkpoint with `--reasoning-parser qwen3` and
   `--trust-remote-code` on the chosen pool without a `MODEL_LOAD` or `CUDA_OOM`.
2. TP=2 actually works on the RunPod pod shape offered (two visible devices, NVLink
   or PCIe), and what it costs in GPU-seconds/page versus a single-device run at a
   lower `max_model_len`.
3. The doc2json prompt returns a **parseable JSON object** and not prose. The
   adapter reports `output_format: "markdown"` plus an explicit warning when it does
   not; that is a canary FAIL, not something to normalise away.
4. `max_tokens 32768` is enough for the densest canary page. Truncation surfaces as
   `arena.semantic_error_class=OUTPUT_TRUNCATED` in `RawOutput.warnings`.
5. p50/p90/p95 per page, peak VRAM, and the projected GPU-hours for 5,132 pages.
   This is the most expensive candidate in the portfolio; if the projection breaks
   the §19 budget the founder decides before a Full Run, not the lane.

## Known limitations, from the card

English and Chinese only, degraded on other languages; weaker on complex charts and
on tables rotated at odd angles; no fine-grained text formatting (bold, italic,
strikethrough); weak multi-step visual instruction following. These are published
weaknesses and they stay in the report — they are not averaged away.

## Files

| File | Role |
|---|---|
| `runtime.json` | frozen identity, pins, pools, official inference config |
| `adapter.py` | `ArenaModelAdapter`; stdlib only, importable without torch/vllm |
| `canonical.py` | doc2json elements → canonical markdown, no content added |
| `fetch_weights.py` | pinned download + revision/sha256 verification + sidecar |
| `Dockerfile` | baked image on the official vLLM base by digest, weights fetched at build time (D36) |
| `entrypoint.sh` | weights → `vllm serve` → `python -m arena.worker.server` |
| `bootstrap.sh` | closed by D36; refuses because `runtime_mode_allowed` is `["baked"]` |

## Semantic failures travel in `warnings`

Masterplan §7 says no native output is ever discarded, and §16 still demands that a
truncated or degenerate page be classified. The adapter API has no field for both
at once, so the adapter returns the bytes verbatim and prefixes the classification
with `arena.semantic_error_class=` inside `RawOutput.warnings`
(`OUTPUT_EMPTY`, `OUTPUT_TRUNCATED`, `OUTPUT_REPETITION`). The worker is expected to
map that prefix onto the receipt's `error_class`. A proper field is raised in the
lane report under `INTERFACE_CHANGES_PROPOSED`.

Blank-page handling stays where masterplan §41 puts it: the adapter reports an empty
model response, it does **not** decide whether the source page was blank. That
distinction is drawn from the source preflight signals, on the evaluator side.

## `prompt_kind: text` (D34) and what lane R must write

`adapter.py` sends `AdapterConfig.prompt_text` verbatim as the text part of the chat
message (`_build_payload`) and refuses an empty one. It carries **no copy** of the
prompt, so `prompt_registry/infinity_parser2_pro_doc2json_v1.txt` is the only place
the doc2json prompt bytes live and its sha256 is what the receipts record.

## Boot sequence (D19)

`entrypoint.sh` starts the model server in the background, polls
`http://127.0.0.1:<port>/v1/models` until it answers (default deadline above the
20-minute contract floor; `ARENA_MODEL_SERVER_READY_TIMEOUT_S` overrides it and a
value under 1200 s is refused), then runs `python3 -m arena.worker.server` **as a
child**, `wait`s on it and exits with its status. It does not `exec` the worker:
`exec` would discard the `trap` and orphan the server. A readiness timeout or a
server that dies during load exits non-zero and the trap stops the server.
