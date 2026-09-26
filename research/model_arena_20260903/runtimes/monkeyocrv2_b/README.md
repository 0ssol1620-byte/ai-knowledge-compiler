# MonkeyOCRv2-B-Parsing — arena runtime

The compact multilingual / photographed-document challenger (masterplan §3.1). It
exists to test **§47 H5**: whether MonkeyOCRv2 is genuinely strong on photographed
and multilingual-like difficulty. The vendor's MDPBench 83.3 and "17 languages" are
quoted from the card, never claimed as reproduced.

## Official sources, resolved 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Checkpoint | `zenosai/MonkeyOCRv2-B-Parsing` | HF model card |
| Revision (pinned) | `de7a993bd0f39a97b122dac767e82ae04935bce4` (2026-07-28) | `benchmark/v6/candidate-registry.yaml`, re-resolved through the HF API at that revision |
| Revision (HF head) | `2419139b7bcd3fda2689b2a83167172afba91c8b` (2026-08-12) | `GET /api/models/.../refs` |
| Architecture | `MonkeyOCRv2ForCausalLM`, `trust_remote_code` | HF `config.auto_map` |
| Weights | `model.safetensors` 1,755,925,032 B + `preprocessor2.pth` 288,533,650 B + `preprocessor1.pth` 4,823,415 B = **2.05 GB** | HF blob listing |
| Largest file | `model.safetensors`, `sha256:0267fdc991c9be02cf1b60405f77fe0629d084970ad9d6d08163feda3d470284` | HF blob listing |
| Runtime repo | `github.com/Yuliang-Liu/MonkeyOCRv2` @ `d46699fb6a4c71d61588e4a71fce03bff4f1ba33` | GitHub commits feed |
| Serving stack | `vllm==0.11.2` (non-DFlash path) + `pypdfium2==5.10.1` | v2 README + `parsing/requirements.txt` |
| Base image | `vllm/vllm-openai:v0.11.2@sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331` | Docker Hub manifest |
| Licence | Apache-2.0, code **and** all MonkeyOCRv2 weights | `LICENSE` in the v2 repo, first line |

**Dataset caveat, kept separate from the code licence:** the repo's LICENSE line
also says the MonkeyDoc v2 *annotations* are CC BY 4.0 with image-source terms on
the dataset card. That is a fourth licence surface and it is untouched here — this
campaign uses the model, not the training data.

## Two corrections to what the repo already recorded

**1. The runtime repository moved.** `candidate-registry.yaml` names
`Yuliang-Liu/MonkeyOCR` as `runtime_source_repository`. That is the **v1**
repository; its README now redirects to `Yuliang-Liu/MonkeyOCRv2`, and only the v2
tree ships `parsing/modeling/modeling_monkeyocrv2_vllm_011.py`, which is what
registers `MonkeyOCRv2ForCausalLM` with vLLM 0.11. Using v1 would not serve this
checkpoint at all. Lane A3 should carry the correction into `model_registry.json`.

**2. The HF head moved, the weights did not.** `main` is now `2419139b`, but
`model.safetensors` has the same sha256 at both revisions, so the newer commit is
documentation only. The registry revision `de7a993b` is pinned to keep the two
documents consistent at no cost in weights. Both were checked through the HF API.

## DFlash is off, on purpose

The card and the v2 README advertise `MonkeyOCRv2-B-Parsing-DFlash` for "up to ~2×
faster inference", and `parsing/serve.py` turns it on with `--draft-model`. This
runtime does **not** use it, and `adapter.load` raises `MODEL_LOAD` if
`dflash_enabled` is ever set true:

- it is a **different checkpoint** (a speculative draft model), not a flag;
- it needs **vLLM ≥ 0.25.1 and CUDA ≥ 12.9**, a different serving stack from the
  0.11.2 path the README gives for everything else;
- speculative decoding is a different condition, so a DFlash throughput number and a
  baseline quality number cannot sit in the same row (§6.1).

It stays a documented follow-up. Speeding a candidate up by swapping its checkpoint
mid-campaign is exactly the silent substitution the contract forbids.

## Prompts: the pipeline is the prompt

The parsing path is two stages — a `LAYOUT` pass over the whole page, then
per-block recognition where each block gets its own prompt (`Text`, `Title`,
`Formula` → LaTeX, `Table` → OTSL, …). Those strings are data inside
`parsing/core_runner.py::ALL_PROMPT`. This adapter **calls `core_runner.run_pipeline`**
rather than reimplementing the sequence, because reimplementing it would mean
inventing a composition the vendor did not publish.

So `prompt_id: monkeyocrv2_b_official_pipeline_prompts_v1` registers a *pipeline
identity* (repository + revision), not a single prompt string. Lane A4 should record
it that way, and the Dockerfile prints `sorted(ALL_PROMPT)` at build time so the
image provenance carries the prompt set it actually shipped.

Defaults taken verbatim from `parse.py`: `max_pixels 1003520` (the official
preprocessor does any downscaling, so the arena does none), `request_timeout 300`,
`--end2end` off, `--skip-preprocess` off. Changed on purpose: `http_max_retries`
`5 → 0` and `retry_repeat` off, because the adapter contract puts retry policy on
the controller (§15.9).

## What the canary must confirm

1. `serve.py` registers `MonkeyOCRv2ForCausalLM` on vLLM 0.11.2 and the server
   answers — the Dockerfile already asserts the module imports, the canary proves it
   serves.
2. `run_pipeline` on a **single-image directory** really writes
   `<out>/markdowns/<stem>.md` and `<out>/jsons/<stem>.json`. The adapter fails with
   `POSTPROCESS` if it finds zero or more than one artifact rather than guessing.
3. The two-stage pipeline's per-page cost. This model is 0.7B-class but runs *many*
   requests per page (one layout call plus one call per block), so pages/second and
   `max_concurrency_per_worker` cannot be inferred from parameter count.
4. Whether OTSL survives into the markdown. `canonical.py` flags it as lossy and
   refuses to translate it; if it happens on the canary the formatter is
   misconfigured and that is a FAIL, not something to normalise later.
5. p50/p90/p95, peak VRAM, projected GPU-hours and cost for 5,132 pages.

## Files

| File | Role |
|---|---|
| `runtime.json` | frozen identity, pins, pools, official inference config |
| `adapter.py` | `ArenaModelAdapter`; imports `core_runner` only inside `load()` |
| `canonical.py` | markdown pass-through, block list → `elements`, OTSL/image flags |
| `fetch_weights.py` | pinned download + revision/sha256 verification + sidecar |
| `Dockerfile` | baked image and weights; clones the runtime at an exact commit |
| `entrypoint.sh` | weights → `parsing/serve.py` (no `--draft-model`) → worker server |
| `bootstrap.sh` | canary-only path from the bare base image |

## Semantic failures travel in `warnings`

Same convention as every C3 runtime: bytes returned verbatim (§7), classification in
`RawOutput.warnings` behind `arena.semantic_error_class=`. The adapter does not
decide whether an empty response means a blank source page (§41).

## `prompt_kind: toolkit` (D34) and what lane R must write

There is no single prompt string, so the registry file holds a **canonical rendering
of `core_runner.ALL_PROMPT`** — the ARENA_CONTRACT §2 canonical JSON of the mapping — `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`, no trailing
newline. That is the format lane R already wrote.
`adapter.render_prompt_mapping` produces it and `adapter.load` fails closed when the
installed toolkit's mapping does not hash to the registry entry.

At runtime revision `d46699fb6a4c71d61588e4a71fce03bff4f1ba33` the mapping has 11
keys (`Caption`, `END2END`, `Formula`, `LAYOUT`, `List-item`, `Page-footer`,
`Page-header`, `Section-header`, `Table`, `Text`, `Title`) and the rendering is 831
bytes hashing to
`sha256:3384d4732fd91113b9f7989e488dba575f65225d745a30b797364e12df47dca4`, which is
the value already in `prompt_registry/sha256.json`.

## Boot sequence (D19)

`entrypoint.sh` starts the model server in the background, polls
`http://127.0.0.1:<port>/v1/models` until it answers (default deadline above the
20-minute contract floor; `ARENA_MODEL_SERVER_READY_TIMEOUT_S` overrides it and a
value under 1200 s is refused), then runs `python3 -m arena.worker.server` **as a
child**, `wait`s on it and exits with its status. It does not `exec` the worker:
`exec` would discard the `trap` and orphan the server. A readiness timeout or a
server that dies during load exits non-zero and the trap stops the server.
