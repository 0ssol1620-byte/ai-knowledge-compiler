# paddleocr_vl_1_6 — PaddleOCR-VL 1.6 arena runtime

Fast high-quality document VLM, 0.9B (masterplan §3.1, §4). Historical TAVONEL
fast lane: 3.525 s/page on the 18-page controlled subset, best formula edit
distance of the five 2026-08 candidates (§5.1).

## Official sources, as resolved on 2026-09-03

| what | value | how it was resolved |
|---|---|---|
| weights repo | `PaddlePaddle/PaddleOCR-VL-1.6` | HF model card |
| **model revision** | `c5630abae1d940eafe0697512a0325494b02ab42` | `GET https://huggingface.co/api/models/PaddlePaddle/PaddleOCR-VL-1.6` → `sha`; repo `lastModified` 2026-08-08 |
| largest weight file | `model.safetensors`, 1,917,255,968 B | same call with `?blobs=true` |
| largest file sha256 | `85a479d506a11e724e7285d395c551be69f41dbc16b6342d3cacfb189aed71db` | LFS `sha256` from the blobs listing |
| runtime source | `PaddlePaddle/PaddleOCR` @ `0006f7874c334ce9c0f497d8b6cce9cdc0b7363d` (release `v3.6.0`, the release that shipped PaddleOCR-VL-1.6) | GitHub `git/ref/tags/v3.6.0`; the image's own `org.opencontainers.image.revision=0006f78` label confirms it was built from this commit |
| **base image** | `paddleocr-vl:paddleocr3.6-nvidia-gpu` @ `sha256:ad0b1f056a76967f9191cd06398e8babb21b49a4673a28c3de5fd31f481884db` | Baidu CCR/Harbor: 401 → Bearer realm `https://ccr-auth.bj.baidubce.com/service/token` → anonymous pull token → 200 with `Docker-Content-Digest` |
| base image contents | paddleocr 3.6.0, paddlex 3.6.1, paddlepaddle-gpu 3.2.1, Python 3.10.16; label `0006f78-ppocr3.6-pdx3.6`; built 2026-05-28 | image config blob and its build history |
| licence | Apache-2.0 | HF model card tag `license:apache-2.0` |

Docs read for this runtime:

- <https://github.com/PaddlePaddle/PaddleOCR/blob/v3.6.0/docs/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL-1.6.en.md>
- <https://github.com/PaddlePaddle/PaddleOCR/blob/v3.6.0/docs/version3.x/pipeline_usage/PaddleOCR-VL.en.md>

Pinned to the `v3.6.0` tag, not `main`: `main` moves, and v3.6.0 is the release
this runtime runs.

### Revision cross-check disagrees with the v6 registry, on purpose

`benchmark/v6/candidate-registry.yaml` pins `66317acc4c9fc17bd154591ce650735cd2855f3e`,
resolved 2026-08-01. The repository moved on 2026-08-08. This campaign pins what
was resolved today and records the older pin in
`provenance.json.model_revision_cross_check` with `agrees: false`. Neither number
is edited into the other.

## Where the provenance lives

`arena/core/schemas/runtime.schema.json` is closed
(`additionalProperties: false`), so `runtime.json` carries only the contract
fields. Everything else — how each revision was resolved, the cross-check, the
dependency pins, the historical numbers, the vendor claims and every open
question — is in **`provenance.json`** beside it. Nothing was dropped to make the
schema pass.

`base_image` must match `name@sha256:<hex>`, and it does: the digest resolves
anonymously through the registry's Bearer realm (401 → token → 200 with
`Docker-Content-Digest`). The earlier note that it could not be resolved without
a pull no longer holds.

## Why this inference path

The official pipeline tutorial opens with a warning worth quoting in full in
spirit: running the 0.9B VLM on its own through Transformers, vLLM, SGLang or
FastDeploy **is not** the PaddleOCR-VL pipeline, and doing so is the first thing
to check when the published numbers cannot be reproduced or the model
hallucinates text. So the arena uses the documented split (tutorial §3.1 + §3.2,
the "PaddlePaddle + vLLM" row of the support matrix):

```
arena worker  ->  paddleocr.PaddleOCRVL(pipeline_version="v1.6", device="gpu:0",
                      vl_rec_backend="vllm-server",
                      vl_rec_server_url="http://127.0.0.1:8118/v1",
                      vl_rec_max_concurrency=8)
                        |
                        v
              `paddleocr genai_server --backend vllm` on loopback :8118
```

The client keeps layout analysis and the rest of the workflow on the GPU; only
the VLM stage is delegated. `adapter.py` owns the server subprocess so that
two-stage readiness (contract §4) actually covers engine boot and `close()`
reaps it.

`prompt_id` is `paddleocr_vl_1_6_pipeline_internal`: this model takes **no user
prompt**. Its prompt is fixed inside the official pipeline. `load()` refuses a
non-empty `prompt_text` rather than quietly ignoring it.

### Concurrency

`max_concurrency_per_worker` is **1** — one page per `/v1/run`. Parallelism
inside a page comes from `vl_rec_max_concurrency: 8`, which is what the 2026-08
FastDeploy `c8` cohort ran (`benchmark/runpod_eval/paddle-fastdeploy-backend.yaml`).
Throughput scales with replicas.

## Weights strategy: `baked`

`hf download --revision <sha>` into `/opt/arena/weights/paddleocr_vl_1_6`,
followed by a `sha256sum -c` of `model.safetensors` against the digest in
`runtime.json`. The build writes `arena-weights-revision.txt`; `load()` re-reads
that stamp **and** re-hashes the largest file, so a checkpoint swap fails closed
at model load rather than showing up as a quality regression. Chosen over
`volume_cache` because §15.1 wants an immutable image for the Full Run and the
checkpoint is under 2 GB.

`bootstrap.sh` is the canary-only alternative: it caches weights under
`/workspace/arena/weights/` and records every installed version into
`/opt/arena/bootstrap-receipt.txt`.

## What the canary must confirm

1. `base_image_digest` — the digest actually pulled, against the one pinned in
   `runtime.json`. The 401 is the unauthenticated first hop, not a refusal: the
   registry issues an anonymous pull token and the digest is resolved. The
   Dockerfile still carries it as a build ARG so a mismatch fails closed.
2. The **resolved layout model** name, directory and per-file sha256. The
   pipeline downloads its own default and the docs name no revision, so
   `runtime.json.inference_config` keeps those fields `null` rather than guessing.
3. The **pip set** that `paddleocr install_genai_server_deps vllm` resolved:
   vLLM, transformers, torch, flash-attn — and whether it moved `paddlex` or
   `paddleocr` off the 3.6.1 / 3.6.0 the image ships. `pip freeze` is captured
   into the image at build time (§38); the canary records its sha256.
   The assertion in the build runs *before* this step, so only the canary can
   prove the post-install set.
4. That the running service reports the model name `PaddleOCR-VL-1.6-0.9B` and
   that `/v1/models` is reachable only on loopback.
5. p50/p90/p95 seconds per page and peak VRAM on the first pool GPU, against the
   3.525 s/page historical figure — a large deviation means the pipeline is not
   the one that produced it.
6. That `runtime.json.model_revision` equals the revision the image baked.

## Known incidents and risks

- **VLM-only invocation is the classic failure.** If ParseBench/OmniDocBench
  scores come in far below the published 96.33 on OmniDocBench v1.6, check that
  the client pipeline — not a bare vLLM call — produced the output.
- **The image is not a version behind the model, and the 3.7.0 overlay this
  runtime used to carry was a mistake.** PaddleOCR **v3.6.0 is the release that
  shipped PaddleOCR-VL-1.6** (release notes, 2026-05-28); v3.7.0 released
  PP-OCRv6, a separate non-VL OCR family, and touches nothing here. At tag
  v3.6.0 the pipeline doc already gives `pipeline_version` the values
  `v1`/`v1.5`/`v1.6` with **`v1.6` as the default**, already documents
  `paddleocr genai_server --model_name PaddleOCR-VL-1.6-0.9B --backend vllm`,
  `paddleocr install_genai_server_deps vllm` and the prebuilt FlashAttention
  wheel note for this image; and the image's own build history downloads
  `PaddleOCR-VL-1.6_infer.tar`. The sibling `paddleocr-genai-vllm-server`
  image at the same label defaults its CMD to `--model_name
  PaddleOCR-VL-1.6-0.9B`. So the official image is used **unmodified**: the
  `paddleocr[doc-parser]==3.7.0` install is gone from both the Dockerfile and
  `bootstrap.sh`, replaced by a fail-closed assertion that the digest really
  carries paddleocr 3.6.0 / paddlex 3.6.1. Evidence in `provenance.json` →
  `paddleocr_version_finding`.
- **There is no newer official image to move to.** Anonymous tag listings on
  2026-09-03 (`paddleocr-vl` 198 tags, `paddleocr-genai-vllm-server` 97,
  `paddleocr-genai-fastdeploy-server` 71) stop at the `ppocr3.6-pdx3.6` family;
  `paddlex/paddlex` stops at `paddlex3.3.11`; `paddlepaddle/paddlex` and
  `paddlepaddle/paddleocr` do not exist on that registry; Docker Hub's
  `paddlepaddle/paddle` carries the framework only. `paddleocr3.7-nvidia-gpu`
  still 404s. See `provenance.json` → `registry_tag_enumeration`.
- **The base image is pinned by the documented version tag, not `latest`.**
  `paddleocr3.6-nvidia-gpu`, `latest-nvidia-gpu` and
  `0006f78-ppocr3.6-pdx3.6-nvidia-gpu` all resolve to the same digest today; the
  version tag is used because `latest-*` moves by design. The digest is what
  binds either way.
- **`paddleocr install_genai_server_deps vllm` is still an unpinned vendor
  resolve.** It publishes no `==` versions and may move `paddlex` or
  `transformers` inside the image. The version assertion runs before it; the
  resolved set is captured in the image pip freeze and the bootstrap receipt,
  and the canary records it.
- **FlashAttention must be the prebuilt 2.8.2 wheel** inside the `paddleocr-vl`
  image; that image has no `nvcc` and a source build will fail. The exact wheel
  URL is the one the official docs publish.
- **Licence ≠ freedom to operate.** Apache-2.0 covers the contributors'
  copyright. It settles nothing about third-party patents, and the container
  base image, the weights and any hosted API each carry their own terms.

## How the pod starts (ARENA_CONTRACT §11.3)

Both modes converge on one script.

| mode | who starts what |
|---|---|
| baked | image `ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]` |
| bootstrap | B2 start command extracts and verifies the bundle into `/opt/arena`, symlinks `/opt/arena/runtime` → `/opt/arena/runtimes/paddleocr_vl_1_6`, exports `PYTHONPATH=/opt/arena` and `ARENA_RUNTIME_DIR=/opt/arena/runtime`, then execs `bootstrap.sh`, which installs the pinned versions, fetches the pinned weights, writes `/opt/arena/bootstrap-receipt.txt` and `/opt/arena/bootstrap-pip-freeze.txt`, and execs the same `entrypoint.sh` |

`bootstrap.sh` never downloads the bundle and needs no bundle URL: by the time
it runs the bundle is already on disk. `entrypoint.sh` checks that
`runtime.json`, `adapter.py` and `canonical.py` are present under
`$ARENA_RUNTIME_DIR` and refuses to start if they are not. **Superseded by D19 in the second integration pass below**: `entrypoint.sh` now starts the `paddleocr genai_server` service itself, polls it, runs the worker as a child and stops the server from a trap. It no longer `exec`s the worker.

## Semantic error class (ARENA_CONTRACT D3)

`adapter.infer()` fills `RawOutput.semantic_error_class` from what it can actually see: an empty page → `OUTPUT_EMPTY`. The pipeline returns whole pages rather than a token stream, so truncation is not observable and the field stays `null` instead of being guessed.
An empty output is still `SUCCESS` (masterplan §41); the class is the verdict, not the status.

## Second integration pass, 2026-09-03 (ARENA_CONTRACT section 11.5)

### Prompt (D34) - `prompt_kind: none`

`prompt_id` is `paddleocr_vl_1_6_pipeline_internal` and it is **unchanged**.
The PaddleOCR-VL pipeline builds its own per-block prompt inside `paddleocr`;
nothing in `adapter.py` sends one. The adapter states this as the module-level
constant `OFFICIAL_PROMPT = ""` with `PROMPT_KIND = "none"`, and `load()`
refuses a non-empty `AdapterConfig.prompt_text` rather than quietly leaving the
official path. `prompt_registry/paddleocr_vl_1_6_pipeline_internal.txt` is
therefore the **empty file** and its sha256 is the hash of the empty string.

### Model server ownership (D19) - this runtime has one

`paddleocr genai_server --backend vllm` on loopback is a model server, so
`entrypoint.sh` owns it, not the adapter:

1. it renders the argv, env and readiness probe from
   `python adapter.py --print-server-plan` (one builder, `build_server_plan`,
   so the entrypoint and the adapter can never launch different services on the
   same port);
2. it polls `genai_server.ready_probe` until it answers, with a hard deadline -
   `ready_timeout_seconds` was raised from 900 s to **1200 s**, the D19 floor -
   and it fails the container on timeout or on the server dying early;
3. it runs `python -m arena.worker.server` as a **child** and `wait`s on it; it
   never `exec`s, which would discard the trap and orphan the server;
4. a `trap ... EXIT INT TERM` stops the server on any exit, and the worker's
   exit code becomes the container's exit code.

The adapter attaches to that service when
`ARENA_MODEL_SERVER_MANAGED_BY=entrypoint` and re-probes it once, so a server
that died between the entrypoint's poll and `load()` is a `MODEL_LOAD` failure
rather than a per-page one.

### Revisions re-verified (D16)

`model_repo` / `model_revision` (`PaddlePaddle/PaddleOCR-VL-1.6` @ `c5630aba...`)
and `runtime_repository` / `runtime_revision` (`PaddlePaddle/PaddleOCR` @
`0006f787...`, tag v3.6.0) were both re-checked read-only on 2026-09-03 against
the Hugging Face revision API and the GitHub tag API; both exist upstream. The
runtime revision moved from v3.7.0 to v3.6.0 in the same pass that removed the
3.7.0 pip overlay: v3.6.0 is the release this pipeline actually runs.

### Prompt registry in the image (D17)

The Dockerfile now carries

    COPY prompt_registry/ /opt/arena/prompt_registry/

so the worker can resolve `ARENA_PROMPT_FILE`
(default `/opt/arena/prompt_registry/<prompt_id>.txt`) in a baked image and fail
closed when it is missing. Bootstrap mode gets the same directory from the
bundle. `.dockerignore` does not exclude it, and a test asserts that.
