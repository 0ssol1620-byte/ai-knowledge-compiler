# GLM-OCR — arena runtime

The compact challenger (masterplan §3.1): "0.9B class, MIT". Fast, permissively
licensed, and the only candidate in C3 whose official path is **two models**.

## Official sources, resolved 2026-09-03

| What | Value | Where it came from |
|---|---|---|
| Checkpoint | `zai-org/GLM-OCR` | HF model card |
| Revision | `ca5d8b3e287e52589e37c28385d9655ee4372f9d` | HF API — matches `benchmark/v6/candidate-registry.yaml` |
| Architecture | `GlmOcrForConditionalGeneration` (CogViT encoder + connector + GLM-0.5B decoder) | HF `config` + card |
| Weights | `model.safetensors` **2,650,579,464 B (2.65 GB)** | HF blob listing |
| Largest file | `model.safetensors`, `sha256:a16eb0de98d199293371c560f95f83130d2a2c9612449df16839f08ff9498815` | HF blob listing |
| SDK | `github.com/zai-org/GLM-OCR` **v0.1.5** = `98ef9846c7045774ff5391a50139e5cbe2850b54` | GitHub releases |
| Layout model | `PaddlePaddle/PP-DocLayoutV3_safetensors` @ `97d101e6db2642e162a1d05392d1b0231c91033e`, `model.safetensors` 133,270,468 B, `sha256:5ea422c6cc5fe759a47e1357c35639b58173508e025a3131cbe4b6ac59e2b85e` | `glmocr/config.yaml` default + HF API |
| Base image | `vllm/vllm-openai:v0.19.0-ubuntu2404@sha256:69234fc31ff1d5e1687b2f06bba39e0f8c58dd4755f0508dbe0595cd3692b851` | the SDK README's own `docker pull`, digest from Docker Hub |

## Three licences, not one

| Surface | Licence | Evidence |
|---|---|---|
| GLM-OCR weights | **MIT** | model card, `license:mit` tag |
| `glmocr` SDK code | **Apache-2.0** | `LICENSE` in the repo, `pyproject.toml` |
| PP-DocLayoutV3 layout model | **Apache-2.0** | its own HF card |

`runtime.json.license.id` names the *model*. The other two are pinned in
`inference_config` and listed in `official_source_urls` so nothing is cleared by
accident — code, weights, dataset and hosted-API terms are four separate licences and
clearing one clears none of the others. The model card says this itself: "Users
should comply with both licenses." None of it settles patent freedom to operate.

## Why the SDK, and not a bare prompt

The card is explicit: *"For document parsing tasks, we strongly recommend using our
official SDK … the SDK integrates PP-DocLayoutV3 and provides a complete pipeline
for document parsing, including layout analysis and structured output generation."*
Running the raw checkpoint with a single `Text Recognition:` prompt would be a
materially weaker configuration than the one the vendor benchmarks, and §6.2 lets
each model use its official recommended path. So this runtime drives
`glmocr==0.1.5` in self-hosted mode against a local vLLM server.

**Prompts.** `glmocr/config.yaml`'s `page_loader.task_prompt_mapping` is
`{text: "Text Recognition:", table: "Table Recognition:", formula: "Formula
Recognition:"}`, and the card's "Prompt Limited" section says those are the only
document-parsing prompts the model supports. `prompt_id:
glm_ocr_official_sdk_task_prompts_v1` registers that mapping plus the SDK revision,
not one string. The information-extraction JSON-schema prompts are out of scope.

**Sampling** is the SDK's own default block, unchanged: `max_tokens 8192`,
`temperature 0.0`, `top_p 1e-05`, `top_k 1`, `repetition_penalty 1.1`, `min_pixels
12544`, `max_pixels 71372800`, `image_expect_length 6144`, `image_format JPEG`.

**Three deliberate deviations, all recorded:**

| SDK default | Here | Why |
|---|---|---|
| `maas.enabled: true` | **false**, and `load()` raises if it is true | MaaS mode forwards every page to Zhipu's hosted API. This campaign measures the open model, and sending the founder's corpus to a third party is not an adapter's decision. |
| `retry_max_attempts: 2` | **0** | Retry policy belongs to the controller (§15.9). |
| `max_workers: 32` | **8** | The arena serves one page per adapter call; 32 region workers against a single-page request just adds contention. |

## Version floors, and what "pinned" means here

The official docs give floors, not pins: the model card says `pip install -U vllm
--extra-index-url https://wheels.vllm.ai/nightly`, and the SDK README says
`pip install -U "vllm>=0.17.0"` **or** `docker pull vllm/vllm-openai:v0.19.0-ubuntu2404`.
A nightly wheel cannot be pinned and `pip install -U` is forbidden (§15.1). So:

- the **base image digest is the pin** for vLLM, torch and torchvision;
- the build *asserts* `torch >= 2.10.0` and `vllm >= 0.17.0` and fails if the image
  does not satisfy the SDK's floors — it never upgrades them underneath vLLM;
- **transformers is the exception, and it is installed, not asserted** — see the
  next section;
- `glmocr` is installed `--no-deps` at `==0.1.5` and the packages its
  `[selfhosted]` extra needs that the image lacks are installed with `==` at the
  latest version satisfying the SDK's floors on 2026-09-03 (resolved from the PyPI
  JSON API): `pymupdf==1.28.2`, `portalocker==4.3.0`, `python-dotenv==1.2.3`,
  `pypdfium2==5.13.0`, `opencv-python-headless==5.0.0.93`, `sentencepiece==0.2.2`,
  `accelerate==1.14.0`.

## The transformers pin, and the claim it replaces

This section used to say the build asserts `transformers >= 5.3.0`. It did not.
`bootstrap.sh` only recorded versions; nothing asserted anything. On 2026-09-03 the
bootstrap completed on pod `92miysvw0wk4wq` (RTX 4090) — bundle sha verified,
`glmocr==0.1.5` installed, both checkpoints verified — and `vllm serve` then died in
ten seconds:

    pydantic ValidationError for ModelConfig: the checkpoint you are trying to load
    has model type `glm_ocr` but Transformers does not recognize this architecture

RunPod restarts a start command that exits, so the pod billed a GPU in a crash loop
that neither `/v1/ready` nor the v1 pod record showed.

vLLM 0.19.0 is not the problem. Its registry maps
`GlmOcrForConditionalGeneration → ("glm_ocr", …)` and `GlmOcrMTPModel →
("glm_ocr_mtp", …)` for the MTP head, and its own `glm_ocr.py` imports
`transformers.models.glm_ocr.configuration_glm_ocr` — so the `transformers >= 4.56.0,
< 5` in its `requirements/common.txt` is stale against its own code. The SDK README's
"Using vLLM" section resolves it on this exact image tag with
`pip install "transformers>=5.3.0"`.

A floor is not a pin, so:

| Pin | Why |
|---|---|
| `transformers==5.4.0` | **not** the `5.3.0` the SDK names — see below; knows `model_type: glm_ocr` (`CONFIG_MAPPING_NAMES`, and `models/glm_ocr/` is still present at 5.4.0); released 2026-03-27 |
| `tokenizers==0.22.2` | `0.22.0` caps `huggingface_hub < 1.0` and cannot coexist with transformers 5.x; `0.22.2` lifts the cap, stays inside transformers' `<= 0.23.0` and vLLM's `>= 0.21.1` |
| `huggingface_hub==1.5.0` | the pod had `0.36.2`; transformers 5.4.0 needs `>= 1.5.0`. This is the one upgrade the fix forces |
| `hf-xet==1.3.2` | `huggingface_hub 1.5.0` raises the floor from `1.1.3` to `1.2.0`, and this lane has no evidence of the image's version |
| `wordfreq==3.1.1` | an **undeclared** dependency of the SDK — see below. The one pin installed *with* deps |

The four framework pins go in `--no-deps` so pip cannot resolve torch or vLLM again.
**Not the newest transformers on purpose:** `5.16.1` needs `tokenizers >= 0.23.1` and
`safetensors >= 0.8.0`, and the pod carries `safetensors 0.7.0` — three upgrades
underneath vLLM instead of one. Full evidence, with URLs and the PyPI `requires_dist`
readings, is in `source-resolution-receipt.json` under `dependency_resolution`.

**No vendor receipt attests any vLLM 0.19.0 + transformers 5.x pair.** That is what
the preflights below are for.

### Why 5.4.0 and not the 5.3.0 the vendor documents

The SDK's stated floor is not enough for the SDK's own code.
`glmocr/layout/layout_detector.py` imports, at module level:

    from transformers import (
        PPDocLayoutV3ForObjectDetection,
        PPDocLayoutV3ImageProcessor,
    )

At transformers `v5.3.0` that second name does not exist. The module ships
`image_processing_pp_doclayout_v3_fast.py`, whose `__all__` is
`["PPDocLayoutV3ImageProcessorFast"]`, and `image_processing_auto.py` maps
`("pp_doclayout_v3", (None, "PPDocLayoutV3ImageProcessorFast"))` — a null slow slot,
so there is no alias to fall back on. `v5.4.0` is the first release where the file is
`image_processing_pp_doclayout_v3.py` and `__all__` carries the un-suffixed name.

`glmocr/layout/__init__.py` **catches** that `ImportError`, sets
`PPDocLayoutDetector = None` and re-raises only when `Pipeline()` is built — inside
the worker, on a billed GPU. Which is why the architecture preflight could not see it.

### wordfreq: a dependency the SDK does not declare

`glmocr/postprocess/result_formatter.py` imports `from wordfreq import
zipf_frequency` at module level; `glmocr/postprocess/__init__.py` imports
`ResultFormatter` with no `try`/`except`; `glmocr/pipeline/pipeline.py` imports that.
The string `wordfreq` appears **nowhere** in `glmocr 0.1.5`'s `pyproject.toml` — not
in the base dependencies, not in the `selfhosted` extra. So
`pip install "glmocr[selfhosted]"` produces a package whose self-hosted pipeline
cannot be constructed. It is pinned here explicitly, with its dependencies, because
`msgpack`, `langcodes`, `ftfy` and `locate` are not in the vLLM image.

## Fail closed before the GPU bills

Two preflights, in this order.

**Import preflight** — `bootstrap.sh`, immediately after the installs and *before*
2.8 GB of weights are pulled, imports every module the adapter will import: the
twenty `glmocr` modules on the self-hosted path, `glmocr.GlmOcr` through the
package's lazy `__getattr__`, and `adapter.py` under the module name
`arena.worker.loader` gives it. Leaf modules, not packages — `glmocr.layout` would
swallow the very error this is looking for. It instantiates nothing: no `GlmOcr`, no
detector, no CUDA context. On failure it prints
`[arena] FATAL import preflight: <module>: <error>` and exits 64; on success:

    [arena] import preflight PASS 22 modules

**Architecture preflight** — after the weight fetches and before `entrypoint.sh`
starts anything, four checks, exit 64 with the reason otherwise: transformers imports
and its version equals the pin; `glm_ocr` is in
`transformers.models.auto.configuration_auto.CONFIG_MAPPING_NAMES`; the weights dir's
`config.json` declares `model_type: glm_ocr`; and every architecture it declares is in
`vllm.model_executor.models.registry.ModelRegistry.get_supported_archs()`. On success:

    [arena] architecture preflight PASS transformers=… vllm=… arch=…

Both lines go into `/opt/arena/bootstrap-receipt.txt`, and the `Dockerfile` runs both
at build time, where they fail a build instead of a pod.

## The 2026-09-03 18:34–18:39Z pod, and three defects on the load path

Pod `jdwdnvg8a2rzx6` (RTX 4090, CUDA 12.9 host): bundle verified, `glmocr==0.1.5`
installed, `architecture preflight PASS transformers=5.3.0 vllm=0.19.0
arch=GlmOcrForConditionalGeneration`, both checkpoints verified, vLLM 0.19.0 engine
initialising at 18:38:24Z — and the driver refused at 18:39:15Z with
`observed_stages: ["CRASHED"]`. **No reason text was captured**: the kept log tail
ends at 18:38:24Z, and the first readiness poll that reached the worker already
returned `HTTP 200 stage=CRASHED`, so not even the stage it died in is known. What
follows is what reading `glmocr 0.1.5` against this adapter found — three defects,
all in the worker's `_prepare`, after vLLM is up. **Which one fired first is not
established.**

1. **The layout model was looked for in the wrong place.**
   `inference_config.layout_model_dir` pins the *baked* path
   `/opt/arena/weights/pp_doclayoutv3_safetensors`, and it is frozen and hashed, so
   it cannot hold two. `bootstrap.sh` fetches to `/workspace/...` and exports
   `ARENA_LAYOUT_DIR` — which nothing read: not this adapter, and not
   `arena/worker/config.py`, which reads `ARENA_WEIGHTS_DIR` only. `adapter.load`
   hashes the 2.65 GB checkpoint and then fails in `verify_layout_model`, which is
   the observed timing. This one is corroborated rather than inferred: the pod log
   at 18:37:37Z reads `[arena] verifying PP-DocLayoutV3 layout model in
   /workspace/arena/weights/pp_doclayoutv3_safetensors`, so the file was under
   `/workspace` while the frozen config named `/opt`. `resolve_layout_model_dir` now
   reads the override, and `entrypoint.sh` exports the directory it just verified.

2. **The SDK was not actually being configured.** The adapter called
   `GlmOcr(config=<dict>, layout_device=…)`, but `config` is not a parameter of
   `glmocr.api.GlmOcr.__init__` at v0.1.5. The signature is
   `(config_path=None, *, api_key, api_url, model, mode, timeout, log_level,
   env_file, ocr_api_host, ocr_api_port, cuda_visible_devices, layout_device,
   **kwargs)`, and every keyword is forwarded into `load_config`, which drops names
   it does not know. The whole dict — MaaS off, `ocr_api` host/port,
   `retry_max_attempts: 0`, `task_prompt_mapping`, layout `model_dir` — was
   discarded without a word, leaving the shipped `config.yaml` in force, whose
   `pipeline.maas.enabled` is **true**. No `TypeError` is raised on that path, so the
   adapter's `TypeError` guard could never fire. The adapter now renders
   `sdk_config()` to a YAML file and passes `config_path=` — the mechanism the SDK
   README's self-hosted section names — and then reads `maas.enabled`,
   `ocr_api.api_host`/`api_port`/`retry_max_attempts`, `layout.model_dir` and
   `page_loader.task_prompt_mapping` back off `GlmOcr.config_model`, failing closed
   on any disagreement. `layout_device` stays a constructor keyword: it is real.

3. **A missing layout directory is a download, not an error.** `glmocr` passes
   `layout.model_dir` straight to `PPDocLayoutV3ImageProcessor.from_pretrained`,
   and its shipped default for that key is the repo id
   `PaddlePaddle/PP-DocLayoutV3_safetensors`. A path that does not exist is read as a
   repo id and fetched unpinned — a hashed Apache-2.0 checkpoint silently replaced by
   whatever `main` holds. The adapter refuses to build the pipeline when the resolved
   directory does not exist, and `entrypoint.sh` exports `HF_HUB_OFFLINE=1` and
   `TRANSFORMERS_OFFLINE=1` after both fetch steps and before the worker starts —
   there rather than in the image, because those two fetches are the only things
   allowed to download.

A fourth, in the dependency set rather than the load path, is `wordfreq` above.

## A discrepancy recorded, not resolved

The card and masterplan §3.1/§4 both call GLM-OCR **0.9B**. The single
`model.safetensors` at the pinned revision is **2,650,579,464 bytes**, roughly 1.3B
parameters at bf16. The likely explanation is that "0.9B" counts the GLM-0.5B
decoder plus connector and excludes the CogViT encoder — but this lane did not
verify that and does not assert it. The measured file size is what goes in the
report; the parameter count is the vendor's claim.

## What the canary must confirm

1. vLLM 0.19.0 serves `GlmOcrForConditionalGeneration` with
   `--speculative-config '{"method":"mtp","num_speculative_tokens":3}'`. MTP is the
   vendor's own default (the model is trained with a Multi-Token Prediction head),
   unlike MonkeyOCRv2's DFlash, which is a separate checkpoint.
2. The SDK constructor accepts the arena's config shape. `OfficialSdkPipeline`
   raises `DEPENDENCY` rather than falling back if `glmocr 0.1.5` disagrees.
3. Both models loaded and both hashes matched. `load()` verifies the layout model
   too — an unpinned layout model would make the pipeline unreproducible while
   looking perfectly healthy.
4. Layout model and vLLM sharing `cuda:0` do not contend. If they do, the SDK's
   documented lever is `layout_device: cpu`; that is a config change with a receipt,
   not a code change.
5. p50/p90/p95, peak VRAM (both models), projected GPU-hours and cost for 5,132
   pages. The card's 1.86 pages/s PDF and 0.67 images/s are the vendor's numbers on
   the vendor's hardware and are quoted, not reproduced.

## Files

| File | Role |
|---|---|
| `runtime.json` | frozen identity, both model pins, pools, official inference config |
| `adapter.py` | `ArenaModelAdapter`; imports `glmocr` only inside `load()`; refuses MaaS |
| `canonical.py` | markdown pass-through, `json_result` regions → `elements` |
| `fetch_weights.py` | pinned GLM-OCR download + verification + sidecar |
| `fetch_layout_model.py` | pinned PP-DocLayoutV3 download + verification + sidecar |
| `Dockerfile` | baked image and both models; the transformers pin and the same architecture preflight at build time |
| `entrypoint.sh` | both models verified → `vllm serve` (MTP) → worker server; sticky `/opt/arena/FATAL` instead of a restart loop |
| `bootstrap.sh` | canary-only path from the bare base image; installs the pins and runs the architecture preflight |
| `source-resolution-receipt.json` | what the official APIs returned, plus the `dependency_resolution` evidence behind the transformers pin |

## Semantic failures travel in `warnings`

Same convention as every C3 runtime: bytes returned verbatim (§7), classification in
`RawOutput.warnings` behind `arena.semantic_error_class=`. Note that GLM-OCR's
markdown has already been reflowed by the SDK's post-processing switches
(`merge_formula_numbers`, `merge_text_blocks`, `format_bullet_points`, all on by
default). That is the official path and it stays — but `canonical.py` records it, so
nobody later mistakes this markdown for a raw model transcript.

## `prompt_kind: toolkit` (D34) and what lane R must write

GLM-OCR is prompted with a per-region task prefix, not one instruction, so the
registry file holds a canonical rendering of the SDK's `task_prompt_mapping` —
the ARENA_CONTRACT §2 canonical JSON of the mapping — `sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=True`, no trailing
newline, the format lane R already wrote — produced by
`adapter.build_official_prompt_text`. At SDK revision
`98ef9846c7045774ff5391a50139e5cbe2850b54` that is 90 bytes:

```
{"formula":"Formula Recognition:","table":"Table Recognition:","text":"Text Recognition:"}
```

`sha256:3d62ac2e6e72a4064fdbbc5d8b045111133f663fb774e9eb0483933f36cf5e67`, which is
the value already in `prompt_registry/sha256.json`.
`adapter.load` hashes the mapping it hands the SDK and fails closed on a mismatch.

## Boot sequence (D19)

`entrypoint.sh` starts the model server in the background, polls
`http://127.0.0.1:<port>/v1/models` until it answers (default deadline above the
20-minute contract floor; `ARENA_MODEL_SERVER_READY_TIMEOUT_S` overrides it and a
value under 1200 s is refused), then runs `python3 -m arena.worker.server` **as a
child**, `wait`s on it and exits with its status. It does not `exec` the worker:
`exec` would discard the `trap` and orphan the server.

A readiness timeout, or a server that dies during load, **no longer exits 70**. That
is what produced the invisible crash loop: RunPod starts the container again and the
next attempt fails identically, on a billed GPU. Instead the script writes
`/opt/arena/FATAL` with the reason and the last 200 lines of the server log, prints
`[arena] FATAL <reason>`, and sleeps. `[arena] FATAL` is already a `MODEL_LOAD`
signature in `arena.controller.run.FATAL_LOG_SIGNATURES` — retried zero times — so the
driver condemns the pod at its next log read (about two minutes) and deletes it in the
D20 `finally` block. The server's output is `tee`d to `/opt/arena/model-server.log`
and to the pod log, so the driver's readiness poll still sees it.

Two consequences worth knowing:

- the pod is ended by the **driver**, not by the worker's `ARENA_MAX_POD_AGE_HOURS`
  fuse — the worker never starts on this path, so that fuse never arms;
- the worker is not started in a failed mode either. `arena/worker/server.py` reaches
  `CRASHED` only through its own readiness path and exposes no environment knob for
  "start pre-failed", so there is no supported way for `entrypoint.sh` to make
  `/v1/ready` report the failure. Teaching the worker to read `/opt/arena/FATAL` and
  answer `CRASHED` is a follow-up for the worker lane, not a change this runtime may
  make.
