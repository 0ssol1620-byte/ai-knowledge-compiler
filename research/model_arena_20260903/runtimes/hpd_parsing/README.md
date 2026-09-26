# hpd_parsing — HPD-Parsing arena runtime

Throughput specialist (masterplan §3.1, §4). Hierarchical parallel decoding plus
Progressive Multi-Token Prediction; the official claim is a peak of 4,752
tokens/s on public benchmarks, 1.62× the fastest existing document parser and
3.06× its own autoregressive baseline. **That number is quoted, not reproduced** —
this campaign measures seconds per page under its own conditions.

## Official sources, as resolved on 2026-09-03

| what | value | how it was resolved |
|---|---|---|
| weights repo | `PaddlePaddle/HPD-Parsing` | official tutorial `hf download PaddlePaddle/HPD-Parsing` |
| **model revision** | `91de80054c23ab4238e3d7073fa2b83c2a7e301e` | `GET https://huggingface.co/api/models/PaddlePaddle/HPD-Parsing` → `sha`; `lastModified` 2026-07-22 |
| largest weight file | `model.safetensors`, 2,143,907,448 B | same call with `?blobs=true` |
| largest file sha256 | `f82b9c83ca8a85931b51b717143c24858281aa8cd1f016dd5a7a1ec5d40a7d91` | LFS `sha256` |
| P-MTP checkpoint | `P-MTP/model.safetensors`, 644,361,256 B, sha256 `a84e697098ce5242a5a10cb95ae05a8cc579134ae01d615ed7bd64f97cddec3a` | same |
| engine | `vllm 0.17.1+hpdparsing` | tutorial §1.2 prebuilt wheel filename |
| licence | Apache-2.0 | HF model card tag `license:apache-2.0` |

Doc read for this runtime:
<https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/pipeline_usage/HPD-Parsing.en.md>

There is **no prior pin** for HPD-Parsing in `benchmark/v6/candidate-registry.yaml`,
so `provenance.json`'s `model_revision_cross_check` is null rather than fabricated.

## Where the provenance lives

`arena/core/schemas/runtime.schema.json` is closed
(`additionalProperties: false`), so `runtime.json` carries only the contract
fields. Everything else — how each revision was resolved, the wheel pin, the
verified-hardware list, the vendor claims and every open question — is in
**`provenance.json`** beside it. Nothing was dropped to make the schema pass.

One thing genuinely does not fit the schema: `base_image` must match
`name@sha256:<hex>`, and the digest for this image cannot be resolved without a
pull. See "What the canary must confirm" below, and the lane report's
`INTERFACE_CHANGES_PROPOSED`.

## Why this inference path

The engine is a *fork* of vLLM 0.17.1 that adds dynamic request forking (what
makes hierarchical parallel decoding possible) and medusa-style P-MTP
speculative decoding. Masterplan §15.1 names exactly this case as the one that
must use the official Docker image. So:

- **base image**: `hpd-parsing-vllm:latest-nvidia-gpu-offline`, pinned to
  `sha256:1493923dd6b7e368c56b5497f2c82ade2599be9c69aa7498a71417b5c6d9948a` — the
  offline variant, so no model download happens at pod boot. The digest came
  from the registry's anonymous Harbor token flow (401 → Bearer realm
  `https://ccr-auth.bj.baidubce.com/service/token` → pull token → 200 with
  `Docker-Content-Digest`) and matches what lane F recorded in
  `build/build_plan.json`. The image config carries CUDA 12.8.1,
  `MAX_PATCHES_WITH_RESIZE=true`, `HPD_OFFLINE=true` and its own
  `ENTRYPOINT ["/bin/bash", "/home/hpd/entrypoint.sh"]`;
- **server**: `vllm serve` with the documented flags, on loopback `:8118`;
- **client**: the documented OpenAI-compatible `POST /v1/chat/completions`,
  spoken with the standard library rather than the `openai` package. The HTTP
  contract is what the docs specify; the client library is not.

Every server flag in `runtime.json.inference_config.server` is copied from the
tutorial, including `MAX_PATCHES_WITH_RESIZE=true` (documented as *must be set*),
`--attention-backend FLASHINFER`, `--enable-chunked-prefill`,
`--enable-prefix-caching` and `num_speculative_tokens: 6`.

The prompt is fixed by the model: `document parsing with fork.` `load()` refuses
any other prompt text rather than quietly substituting.

### Output is not Markdown

HPD-Parsing emits a flat block stream:

```
<BLOCK>title [12,30,900,80]<CHILD>Annual Report<BLOCK>image [10,90,900,400]
```

`canonical.py` uses the block regex published in the tutorial, verbatim. Blocks
without `<CHILD>` (images, charts) contribute no Markdown because they carry no
text — they still appear in `elements` with `content: null`. Only
`doc_title`/`title` → `#` and `paragraph_title`/`sub_title` → `##` become
headings; that map is fixed and nothing else is promoted.

### Concurrency

`max_concurrency_per_worker: 8` is a **starting point**, not a measurement. The
docs say the throughput advantage only appears with concurrent requests and show
a 16-thread client pool, but publish no per-GPU number. The canary sets the real
value, and it must be lowered on any `TENSOR_SHAPE` or `OUTPUT_TRUNCATED`
cluster — see the MinerU VLM incident in `../mineru_vlm/README.md` for why that
rule exists.

## Weights strategy: `baked`

The offline image already contains weights, but the image tag names no model
revision — so the Dockerfile re-materialises the pinned revision with
`hf download --revision` into a directory the adapter owns, then checks the
sha256 of both `model.safetensors` and `P-MTP/model.safetensors` and asserts
both `config.json` files exist (the tutorial requires the layout to stay
intact). `load()` re-reads the revision stamp and re-hashes the main checkpoint.

## What the canary must confirm

1. `base_image_digest` — the digest actually pulled. The registry
   `ccr-2vdh3abv-pub.cnc.bj.baidubce.com` refused anonymous manifest reads (401)
   on 2026-09-03; the Dockerfile takes the digest as a required build ARG.
2. Whether the offline image's own baked weights are the pinned revision. If
   they are, the extra download can be dropped; if not, this build is already
   correct and the discrepancy is the finding.
3. The GPU and driver satisfy CUDA ≥ 12.8 and FLASHINFER is actually selected —
   not silently swapped for another attention backend.
4. Real per-page latency and tokens/s at concurrency 1, 4 and 8, and peak VRAM
   at 80 GB class. `gpu_memory_utilization: 0.9` with `max_model_len: 16384`.
5. That `<BLOCK>` markers appear in the output at all — the adapter raises no
   error for their absence but records `no_block_markers`, and a canary full of
   that warning means the prompt or the served model is wrong.
6. `finish_reason == "length"` rate at `max_tokens: 8000`. A high rate means
   pages are being truncated, which is a quality finding, not a runtime one.

## Known incidents and risks

- **Verified hardware is a short list**: H100, H800, H20, A100, A800, A30, L20,
  RTX Pro 6000. `gpu_pool_priority` holds only 80 GB-class entries from that
  list. Do not substitute a GPU the vendor has not verified.
- **`latest-*` tags move.** The offline image is ~24.5 GB and the online one
  ~20.2 GB; both are published only under moving tags, which is why a digest is
  mandatory here.
- **The customized wheel is `cp38-abi3`** and targets `manylinux_2_31_x86_64`.
  It is not a stock vLLM and must never be replaced by one.
- **Licence ≠ freedom to operate.** Apache-2.0 covers the weights repository.
  The customized vLLM wheel and the container image are separate artifacts under
  their own terms, and none of them settles third-party patents.

## How the pod starts (ARENA_CONTRACT §11.3)

Both modes converge on one script.

| mode | who starts what |
|---|---|
| baked | image `ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]` |
| bootstrap | B2 start command extracts and verifies the bundle into `/opt/arena`, symlinks `/opt/arena/runtime` → `/opt/arena/runtimes/hpd_parsing`, exports `PYTHONPATH=/opt/arena` and `ARENA_RUNTIME_DIR=/opt/arena/runtime`, then execs `bootstrap.sh`, which installs the pinned versions, fetches the pinned weights, writes `/opt/arena/bootstrap-receipt.txt` and `/opt/arena/bootstrap-pip-freeze.txt`, and execs the same `entrypoint.sh` |

`bootstrap.sh` never downloads the bundle and needs no bundle URL: by the time
it runs the bundle is already on disk. `entrypoint.sh` checks that
`runtime.json`, `adapter.py` and `canonical.py` are present under
`$ARENA_RUNTIME_DIR` and refuses to start if they are not. The official image declares its own `ENTRYPOINT ["/bin/bash", "/home/hpd/entrypoint.sh"]`, which the baked build replaces and bootstrap mode overrides through the RunPod REST v1 `dockerEntrypoint` route of ARENA_CONTRACT D2. **Superseded by D19 in the second integration pass below**: `entrypoint.sh` now starts the same `vllm serve` engine itself, polls it, runs the worker as a child and stops the server from a trap. It no longer `exec`s the worker.

## Semantic error class (ARENA_CONTRACT D3)

`adapter.infer()` fills `RawOutput.semantic_error_class` from what it can actually see: an empty body → `OUTPUT_EMPTY`; `finish_reason == "length"` → `OUTPUT_TRUNCATED`; a non-empty body with no `<BLOCK>` marker → `OUTPUT_MALFORMED`. Emptiness wins over truncation because it is the more specific fact.
An empty output is still `SUCCESS` (masterplan §41); the class is the verdict, not the status.

## Second integration pass, 2026-09-03 (ARENA_CONTRACT section 11.5)

### Prompt (D34) - `prompt_kind: text`

`prompt_id` is `hpd_parsing_document_parsing_with_fork_v1` and it is
**unchanged**. The text the adapter sends is the module-level constant

    OFFICIAL_PROMPT = "document parsing with fork."

`prompt_registry/hpd_parsing_document_parsing_with_fork_v1.txt` must hold
exactly that string. `load()` refuses any other `AdapterConfig.prompt_text`
(an empty one included), and `build_request_body` sends `cfg.prompt_text`
rather than reaching for the constant behind the config's back.

### Model server ownership (D19) - the official image's server, started the same way

The official image's own `ENTRYPOINT` is `/bin/bash /home/hpd/entrypoint.sh`,
which starts the customized vLLM `0.17.1+hpdparsing` server. The arena replaces
that entrypoint, so `entrypoint.sh` here starts the same server the same way:

1. it renders the `vllm serve` argv (including `--speculative-config` pointing
   at `<weights>/P-MTP`), the `MAX_PATCHES_WITH_RESIZE=true` env and the
   readiness probe from `python adapter.py --print-server-plan` - one builder,
   `build_server_plan`, shared with the adapter;
2. it polls `http://127.0.0.1:8118/v1/models` until it answers, deadline
   `server.ready_timeout_seconds` = 1800 s (above the D19 20-minute floor), and
   fails the container on timeout or if the server exits first;
3. it runs `python -m arena.worker.server` as a **child** and `wait`s on it -
   never `exec`, which would discard the trap and orphan an 80 GB-VRAM engine;
4. a `trap ... EXIT INT TERM` stops the server on any exit and the worker's exit
   code becomes the container's exit code.

The adapter attaches when `ARENA_MODEL_SERVER_MANAGED_BY=entrypoint`.

### Revisions re-verified (D16)

`PaddlePaddle/HPD-Parsing` @ `91de8005...` was re-checked read-only against the
Hugging Face revision API on 2026-09-03 and exists upstream. There is
deliberately **no** `runtime_repository` / `runtime_revision`: upstream
publishes the customized vLLM fork only as the Docker image, the digest-pinned
`base_image` is the runtime pin, and inventing a source repository would be
fabricated data.

### Prompt registry in the image (D17)

The Dockerfile now carries

    COPY prompt_registry/ /opt/arena/prompt_registry/

so the worker can resolve `ARENA_PROMPT_FILE`
(default `/opt/arena/prompt_registry/<prompt_id>.txt`) in a baked image and fail
closed when it is missing. Bootstrap mode gets the same directory from the
bundle. `.dockerignore` does not exclude it, and a test asserts that.
