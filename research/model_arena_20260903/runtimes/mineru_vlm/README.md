# mineru_vlm — MinerU2.5-Pro-2605-1.2B via the MinerU vlm-engine

Complex table / layout specialist (masterplan §3.1, §4). On the 18-page
controlled subset (§5.1) this runtime held the best table TEDS (0.959696), the
best structure TEDS (0.984524) and the best reading order (0.076693) — at
34.708 s/page, roughly ten times the PaddleOCR-VL lane. It is also the pipeline
that produced the 5,132-page campaign's 99.98% **completion** (not accuracy).

## Read this before changing anything: masterplan §14

> MinerU VLM worker concurrency = 3 → 48 of 54 pages failed with tensor-shape
> errors, and the pages that succeeded changed between repeats, so no accuracy
> metric could be computed.

The standing rule:

```
concurrency per worker = 1
throughput scaling     = horizontal replicas

  8 workers × concurrency 1        ✅
  1 worker  × concurrency 8        ❌ forbidden
```

`adapter.py` raises `AdapterError("MODEL_LOAD", ...)` when
`cfg.max_concurrency != 1`. It **refuses** rather than clamping, because a
caller who asked for more has a wrong plan and silently correcting it hides the
wrong plan. `runtime.json.inference_config.concurrency_policy` carries
`{per_worker: 1, scale: "replicas_only"}` for the controller (contract §3.7, §5),
and `provenance.json.known_incidents` carries the diagnostic it came from.

## Official sources, as resolved on 2026-09-03

| what | value | how it was resolved |
|---|---|---|
| code repo | `opendatalab/MinerU` | official repository |
| **code revision** | `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` | tag `mineru-3.4.5-released` → release page commit link |
| weights repo | `opendatalab/MinerU2.5-Pro-2605-1.2B` | `mineru/utils/enum_class.py::ModelPath.vlm_root_hf` |
| **weights revision** | `bff20d4ae2bf202df9f45284b4d43681555a97ed` | `GET https://huggingface.co/api/models/opendatalab/MinerU2.5-Pro-2605-1.2B` → `sha`; `lastModified` 2026-06-16 |
| largest weight file | `model.safetensors`, 2,312,126,640 B | `?blobs=true` |
| largest file sha256 | `abf8681ca63b8dec7b67de257af47b821f179442f72998d0696ae2ed9232a5f0` | LFS `sha256` |
| base image | `vllm/vllm-openai:v0.21.0` @ `sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9` | Docker Hub registry manifest, anonymous token |
| licence | `LicenseRef-MinerU-Open-Source-License` | `pyproject.toml` at the pinned revision |

**The weights revision cross-checks cleanly.** `infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh`
pinned `bff20d4ae2bf202df9f45284b4d43681555a97ed` in 2026-08 and the repository
has not moved since 2026-06-16, so today's HEAD is byte-identical. That is the
only one of this lane's four models whose pin agrees with the prior campaign.

Upstream tagged `mineru-3.4.5-released` without bumping `mineru/version.py`,
which still reads `3.4.4` at that commit. Record the git sha, not the version
string. See `../mineru_pipeline/README.md` for the full note.

## Where the provenance lives

`arena/core/schemas/runtime.schema.json` is closed
(`additionalProperties: false`), so `runtime.json` carries only the contract
fields. Everything else — how each revision was resolved, the cross-check, the
dependency pins, the two 2026-08 incidents and every open question — is in
**`provenance.json`** beside it. Nothing was dropped to make the schema pass.

## Why this inference path

`backend=vlm-engine`, `batch_size=1`, through `mineru.cli.common.do_parse` —
the function the `mineru` CLI itself calls — in the worker process, so MinerU's
`ModelSingleton` keeps the 1.2B checkpoint warm across pages instead of
reloading it per page.

### The engine resolution is checked, not accepted

`vlm-engine` is a *public* backend name. MinerU turns it into a concrete engine
at call time with `get_vlm_engine(inference_engine="auto")`, which picks
`vllm-engine` when vLLM is importable and `transformers` otherwise. The base
image **does** ship vLLM, so "auto" is not a safe way to get a known runtime.

`adapter.py` therefore reads the resolved engine and fails closed with
`MODEL_LOAD` unless it equals `inference_config.expected_vlm_engine`
(`transformers` — the engine behind the 2026-08 c1 evidence). Accepting whatever
happens to be installed would change what is being measured while the label
stayed the same, which is the exact silent-fallback failure the constitution
bans. If the canary shows `vllm-engine` being selected, that is a **finding**
and a founder decision: pin transformers, or re-baseline on vLLM and say so.

There is no prompt. `load()` refuses a non-empty `prompt_text`.

## Weights strategy: `baked`

`hf download --revision <sha>` into `/opt/arena/weights/mineru_vlm`, then a
`sha256sum -c` of `model.safetensors` against `runtime.json`. `load()` re-reads
the revision stamp and re-hashes the checkpoint, so a swapped checkpoint fails
at model load rather than showing up as a quality regression.
`MINERU_MODEL_SOURCE=local` plus a baked `mineru.json` also stops the
huggingface.co probe MinerU makes at import time when the source is unset.

## What the canary must confirm

1. **Which engine `vlm-engine` resolved to** — the single most important line in
   the receipt. It must be `transformers`.
2. That the loaded client reports `batch_size == 1`.
3. **No tensor-shape failures at concurrency 1** across the 15 canary pages, and
   byte-identical output on a repeat of the same page. Any `TENSOR_SHAPE` at
   concurrency 1 is a stop-the-line finding, not a retry.
4. Per-page latency against the 34.708 s/page historical figure. `shard_size_hint`
   is 100 and the scheduler starts this model's shards first (§35) because it is
   the slowest lane.
5. `importlib.metadata.version("mineru")` and the git sha — expect 3.4.4 and
   `fbb1257a`.
6. Peak VRAM on A40 and on 4090, since the pool order prefers A40.

## Known incidents and risks

- **The concurrency incident above.** It is the campaign's most important past
  failure and the reason this runtime has a hard guard.
- **`accelerate` version sensitivity.** The 2026-08 diagnostic recorded that the
  local VLM engine only passed its smoke test once the declared optional
  dependency `accelerate>=1.5.1` was supplied as the pinned **1.14.0**. That pin
  is carried forward here rather than left as a range.
- **Empty output is not a blank page** (§41). Empty artefacts were recorded as
  failures in 2026-08, never as successful blank pages; the adapter returns an
  `empty_output` warning and lets the downstream preflight signals decide.
- **Licence unresolved for commercial use.** `LicenseRef-MinerU-Open-Source-License`
  is not a standard SPDX identifier; the v6 registry recorded
  `commercial_use: unknown`. The weights repository carries separate terms.
  That call belongs to the founder.

## How the pod starts (ARENA_CONTRACT §11.3)

Both modes converge on one script.

| mode | who starts what |
|---|---|
| baked | image `ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]` |
| bootstrap | B2 start command extracts and verifies the bundle into `/opt/arena`, symlinks `/opt/arena/runtime` → `/opt/arena/runtimes/mineru_vlm`, exports `PYTHONPATH=/opt/arena` and `ARENA_RUNTIME_DIR=/opt/arena/runtime`, then execs `bootstrap.sh`, which installs the pinned versions, fetches the pinned weights, writes `/opt/arena/bootstrap-receipt.txt` and `/opt/arena/bootstrap-pip-freeze.txt`, and execs the same `entrypoint.sh` |

`bootstrap.sh` never downloads the bundle and needs no bundle URL: by the time
it runs the bundle is already on disk. `entrypoint.sh` checks that
`runtime.json`, `adapter.py` and `canonical.py` are present under
`$ARENA_RUNTIME_DIR` and refuses to start if they are not. There is no model server to start: MinerU runs in-process, and `MINERU_API_MAX_CONCURRENT_REQUESTS=1` is re-asserted here so the §14 rule survives a bootstrap pod that inherited nothing, then
execs `python3 -m arena.worker.server`.

## Semantic error class (ARENA_CONTRACT D3)

`adapter.infer()` fills `RawOutput.semantic_error_class` from what it can actually see: an empty markdown body → `OUTPUT_EMPTY`. A missing side-car dump stays a warning: the markdown is still what the model produced.
An empty output is still `SUCCESS` (masterplan §41); the class is the verdict, not the status.

## Second integration pass, 2026-09-03 (ARENA_CONTRACT section 11.5)

### Prompt (D34) - `prompt_kind: none`

`prompt_id` is `mineru_vlm_no_prompt` and it is **unchanged**. The `vlm-engine`
backend takes no prompt: the adapter declares `OFFICIAL_PROMPT = ""` and
`PROMPT_KIND = "none"`, and `load()` refuses a non-empty
`AdapterConfig.prompt_text`. `prompt_registry/mineru_vlm_no_prompt.txt` is the
**empty file** and its sha256 is the hash of the empty string.

### Model server ownership (D19) - this runtime has none

Worth stating plainly, because the base image is `vllm/vllm-openai` and that
misleads: **no vLLM server is started here.** `runtime.json` pins
`expected_vlm_engine: "transformers"` and the adapter fails closed unless
MinerU's `get_vlm_engine(inference_engine="auto")` resolves to exactly that, so
inference is in-process through `do_parse`. With no server process to poll, to
trap or to orphan, D19 keeps `exec "${PYTHON_BIN}" -m arena.worker.server`.

Masterplan section 14 is unchanged by this pass: concurrency stays 1 per worker
and throughput scales by replicas only.

### Revisions re-verified (D16)

| runtime.json field | value | what it is |
|---|---|---|
| `model_repo` / `model_revision` | `opendatalab/MinerU2.5-Pro-2605-1.2B` @ `bff20d4ae2bf202df9f45284b4d43681555a97ed` | **model weights** (Hugging Face) |
| `runtime_repository` / `runtime_revision` | `opendatalab/MinerU` @ `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` | **runtime code** (GitHub) |

Both were re-checked read-only on 2026-09-03 and both exist upstream.

### Prompt registry in the image (D17)

The Dockerfile now carries

    COPY prompt_registry/ /opt/arena/prompt_registry/

so the worker can resolve `ARENA_PROMPT_FILE`
(default `/opt/arena/prompt_registry/<prompt_id>.txt`) in a baked image and fail
closed when it is missing. Bootstrap mode gets the same directory from the
bundle. `.dockerignore` does not exclude it, and a test asserts that.
