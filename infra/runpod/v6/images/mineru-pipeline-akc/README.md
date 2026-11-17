# One page server, three vendor recipes — C0, C3, C1 behind the AKC external-runner protocol

Arena slots C0 (WO-D10-0F), C3 and C1 (WO-D10-0I, decision A0-7). `mineru_akc_server.py` is
the server side of the external-runner protocol the registered runners speak
(`benchmark/runners/base.py::run_external`). It runs the **vendor's own command** for one page,
as a recipe says; no vendor code is in this repository. **Evaluation only.** None of this is the
production endpoint, and the production endpoint is not used for benchmark load.

Nothing here has been built, pushed or run on a pod.

| Slot | Recipe | Vendor command | Weights | Image |
|---|---|---|---|---|
| C0 | `recipes/c0-mineru-pipeline.json` (default) | `mineru -b pipeline -m ocr` against a loopback `mineru-api` | `opendatalab/PDF-Extract-Kit-1.0@ed6b654c`, baked | `Dockerfile --target c0` |
| C0, named deviation | `recipes/c0-mineru-pipeline-lang-ko.json` | the same plus `-l korean` when the payload language is `ko` | as C0 | as C0 |
| C3 | `recipes/c3-mineru-vlm.json` | `mineru -b vlm-engine` against a loopback `mineru-api --enable-vlm-preload true` | `opendatalab/MinerU2.5-Pro-2605-1.2B@bff20d4a`, downloaded at launch | `Dockerfile --target c3` |
| C1 | `recipes/c1-paddleocr-vl.json` | `paddleocr doc_parser --pipeline_version v1.6 …` | `PaddlePaddle/PaddleOCR-VL-1.6@c5630aba`, downloaded at launch; **layout model unpinned** | `../paddleocr-vl-akc/Dockerfile` |

**Rebuilt, not a production digest.** The repository records no image digest for the MinerU or
the PaddleOCR production workers (`infra/runpod/v6/pool-registry.yaml`:
`identity_state: pending_exact_image_digest` for both). Every receipt says "rebuilt".

## Files

| File | What it is |
|---|---|
| `mineru_akc_server.py` | The protocol server (standard library), shared by every recipe; the C1 image copies it at build |
| `mineru_akc_weights.py` | Download a manifest's files at its revision and refuse any size, digest or extra-file difference; also used by the server before it serves |
| `recipes/*.json` | One declarative recipe per slot (below) |
| `recipes/c3-weights-manifest.json`, `recipes/c1-weights-manifest.json` | Every file of the C3 / C1 weights repository at the pin (13 files, 2,328,028,720 B / 20 files, 1,930,462,423 B), from the WO-D10-0A API read |
| `weights-manifest.json` | The 40 files (2,595,586,833 B) of PDF-Extract-Kit-1.0 @ `ed6b654c` that MinerU 3.4.4 loads (C0) |
| `Dockerfile` | Targets `c0` and `c3`. Base by digest, Debian packages by version from a dated snapshot, Python packages by version and sha256 |
| `requirements.in` / `requirements.lock` | C0: top-level pins / the full hashed closure (98 packages) |
| `requirements-c3.lock` | C3 layer: the two packages MinerU's `[vlm]` extra adds (accelerate 1.14.0, psutil 7.2.2), hashed |
| `mineru.json` / `mineru-vlm.json` | MinerU config for C0 / C3: local models only, LLM-aided titles off |
| `test_mineru_akc_server.py` | The real client against the server, in process, for every recipe |
| `../paddleocr-vl-akc/Dockerfile` | C1: the production worker's image stage with this server and the C1 recipe |

## Recipes

A recipe is a JSON object with exactly these keys (`load_recipe` refuses anything else):
`name`, `provider` (the runner key the server answers as), `model` (`repo_id`, full 40-character
`revision`, `dir`, `manifest`: the model it attests), `aux_models` (other models it loads, each
pinned the same way or the server will not start), `packages` (name → pinned version or `null`;
the installed versions go into every receipt, and a pinned one that differs stops the server),
`service` (a long-lived loopback child with its health URL, or `null`), `argv` (the vendor
command; `{source}` and `{out}` are the page file and the output directory), `page_argv`
(appended for a PDF page, `{page}`; `null` = the command reads whole files, so a page index
above 0 is refused), `lang_argv` / `lang_by_language` (appended when the payload language maps),
`env`, `output_glob` (exactly one file must match), `timeout_s`, `options` (what it does, stated).

Every result's receipt carries the recipe name, its sha256 (canonical JSON) and options, the
installed package versions, the weights repository, revision and manifest sha256, the Python
version, input and source digests, page index, language value, latency and the markdown sha256.

## Launch on a pod (the A0 shape: download at the revision, checksum to the log, serve)

The image's `CMD` is the launch; nothing has to be passed. Port 8080, `POST /parse`, health
`GET /health` (provider, revision, recipe name, receipt sha256, `busy`, `ready`). Set
`AKC_BENCHMARK_PROVIDER_TOKEN` from a RunPod secret before any real page (§5G A0-4); the vendor
command never sees it.

- **C0**: `python /opt/akc/mineru_akc_server.py --recipe /opt/akc/recipes/c0-mineru-pipeline.json`.
  The weights are baked; the server checks them against `weights-manifest.json` again and logs
  `weights model opendatalab/PDF-Extract-Kit-1.0@ed6b654c… manifest <sha256> 40 files verified`,
  starts `mineru-api`, waits for its `/health`, then serves. The named Korean variant: the same
  with `--recipe /opt/akc/recipes/c0-mineru-pipeline-lang-ko.json`.
- **C3**: `sh -c 'HF_HUB_OFFLINE=0 python /opt/akc/mineru_akc_weights.py /opt/akc/recipes/c3-weights-manifest.json /opt/akc/models/MinerU2.5-Pro-2605-1.2B && exec python /opt/akc/mineru_akc_server.py --recipe /opt/akc/recipes/c3-mineru-vlm.json'`.
  The download is the only step with network; it prints `13 files, 2328028720 bytes, verified`;
  the server then logs the manifest sha256 (`43f70d9f…`) and serves with every hub offline.
- **C1**: the same shape with `recipes/c1-weights-manifest.json`, `/opt/akc/models/PaddleOCR-VL-1.6`
  and `recipes/c1-paddleocr-vl.json`. **It stops at start today** with
  `layout_detection: not pinned in the recipe; refusing to serve` (below).

## What a failure looks like in the log

| Kind | Log | Answer |
|---|---|---|
| Operational, at start | `recipe refused: …`, `<pkg> … installed, the recipe pins …`, `<role>: weights differ from the manifest`, `<role>: not pinned in the recipe`, `the recipe's service did not become healthy` | the process exits; the pod is not serving |
| Operational, serving | `service did not come back; answering 503`; the vendor service's own crash output | `503 pipeline_unavailable`, nothing recorded for the page |
| Recovery | after a timed-out page or a non-zero exit of a recipe with a service, the service is killed and restarted | `503 pipeline_unavailable` until it is healthy again, so no abandoned work runs into the next page |
| Model / page | the vendor command's own stdout and stderr; for `pipeline_error` the Python trace | `200` with a failure row: `pipeline_exit_nonzero`, `pipeline_timeout`, `pipeline_output_missing`, `empty_output`, `output_too_large`, `page_content_type_unsupported`, `pipeline_error`; never a trace in the body |
| Request | — | `400/401/404/409/411/413/429` with `{"error": "<fixed code>"}` |

A timed-out or out-of-memory run is recorded as a page failure; the vendor's stderr in the log is
what tells an operational cause from a model one.

## Protocol (the mirror of `base.external_exchange`)

`POST /parse` with the provider payload as JSON. Headers: `X-AKC-Benchmark-Provider` = the
recipe's provider, `X-AKC-Model-Revision` = the recipe's revision, `X-AKC-Input-SHA256` = sha256
of the body, `Authorization: Bearer <token>` when `AKC_BENCHMARK_PROVIDER_TOKEN` is set on the pod.

- **Before any of the body is read:** wrong route **404**; no or malformed `Content-Length`
  (anything but 1–12 ASCII digits, or `Transfer-Encoding`) **411**; over 96 MiB **413** — the
  connection is closed after the answer.
- **Headers only, body discarded unstored:** token configured and missing or wrong **401**;
  another provider, or a revision other than the recipe's **409** (never echoed).
- **After the body is in:** a page already running **429** (the slot is taken only now, so a slow
  upload holds nothing); body digest not 64 lowercase hex or not matching, JSON, payload shape,
  source digest, page index, non-string language **400**; pipeline recovering or down **503**.
- Every read and write on the socket times out after 30 s; a stalled client is dropped.
- **200** only for a page the command ran: the output (`benchmark/schemas/parser-output.schema.json`)
  or a failure row. The 8 MiB bound applies to the serialized response, not the text.
- An unexpected server error is **500** `internal_error` with the trace in the log.

The pod proxy terminates TLS (`https://<podId>-8080.proxy.runpod.net/parse`).

## Differences from the recorded recipes (decision A0-8)

The default of each recipe follows the recipe recorded in the repository; a deviation is a named,
separate recipe or is listed here.

**C0** — recorded: `benchmark/runpod_eval/mineru_stage2.py` (`--backend pipeline --method ocr`),
the candidate registry's `runtime_recipe` for `mineru-3.4.4-pipeline`.

| | Recorded | `c0-mineru-pipeline` |
|---|---|---|
| MinerU | git checkout `opendatalab/MinerU` @ `79d6d8d7`, `[core]` extra | PyPI `mineru==3.4.4` (wheel sha256 `d4d67853…`), `[pipeline]` extra; whether `79d6d8d7` is the wheel's commit was not checked |
| Torch | 2.8.0+cu128 from the PyTorch index | 2.8.0 from PyPI with the CUDA 12.8 `nvidia-*` wheels |
| Python | `/usr/bin/python3.11` on an unrecorded pod image | `python:3.11-slim-bookworm@sha256:e8c69d86…` (amd64) |
| Other packages | no pip freeze in the repository | resolved as of 2026-08-01, hashed |
| pypdfium2 | unrecorded | 4.30.0 (the arena's one renderer, §5F decision 5) |
| Weights | artifact manifest `sha256:fc2064a5…` (contents not in the repository) | the ModelPath subtree at `ed6b654c`, per-file digests |
| Invocation | `mineru --path <dir> --backend pipeline --method ocr`, a batch per call | one page per call: `-s N -e N`, `-f true -t true` (the documented defaults, stated), against a long-lived loopback `mineru-api` so models stay loaded; the CLI runs as a child process with a 175 s limit |
| Language | no `-l` | **no `-l`** (same). `-l korean` for `ko` only in the named recipe `c0-mineru-pipeline-lang-ko` |
| Concurrency | `MINERU_API_MAX_CONCURRENT_REQUESTS=1` | same, and the server refuses a second page |

**C3** — recorded: `infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh` with
`run-mineru-3.4.4-public-core-worker.sh` (`--backend vlm-engine`), the only MinerU script under
`infra/`; it runs this model at this revision. MinerU 3.4.4's own default VLM model is this
repository (`ModelPath.vlm_root_hf` in `mineru/utils/enum_class.py` at `mineru-3.4.4-released`,
snapshot sha256 `f3c6d71d…`), so the pinned tool runs the pinned revision; the card at
`bff20d4a` asks for `transformers>=4.56.0` (4.57.3 here) and, for the vLLM engine only,
`vllm>=0.10.1`.

| | Recorded | `c3-mineru-vlm` |
|---|---|---|
| MinerU | git `79d6d8d7`, `[core]` | PyPI `mineru==3.4.4`, `[pipeline]` + `[vlm]` (the C0 image plus accelerate and psutil); `[core]`'s gradio is not installed |
| Inference engine | transformers (no vLLM installed) | transformers (no vLLM installed) — same. MinerU's card recommends vLLM; a vLLM-engine recipe would be a named deviation (not built) |
| Torch / transformers / accelerate / mineru-vl-utils | 2.8.0+cu128 / 4.57.3 / 1.14.0 / 1.0.5 | 2.8.0 PyPI / 4.57.3 / 1.14.0 / 1.0.5 |
| Weights | `snapshot_download` at `bff20d4a`, no file check | the same download plus a per-file manifest check, then again at server start |
| Invocation | batch per call, `--method ocr` (applies to pipeline/hybrid only per the CLI help) | one page per call, `-s N -e N`, no `-m`; `-f true -t true --image-analysis true` (the CLI's documented defaults, stated) |
| Preload | not recorded | `mineru-api --enable-vlm-preload true` |

Same tool as C0: same MinerU version, image and server; only the backend, the weights and
two packages differ. Which engine `vlm-engine` picks when vLLM is absent is not stated in the
documentation read; the recorded run and the log at A0 show it.

**C1** — production: `workers/gpu-parser/paddleocr_adapter.py` in the `production` stage of
`workers/gpu-parser/Dockerfile`.

| | Production | `c1-paddleocr-vl` |
|---|---|---|
| Image | CUDA 12.9.1 cuDNN Ubuntu 24.04 by digest, apt unpinned, gpu-common `uv.lock`, `paddlepaddle-gpu==3.2.1` (cu126 index), `paddleocr[doc-parser]==3.7.0`, transitive packages resolved at build | the same, the same commands (`../paddleocr-vl-akc/Dockerfile`) — **not hash-locked, as production is not**; the paddle index's hashes are outside what this work order could read |
| Entry | the generic runtime handler → `PaddleOcrVlAdapter` (Python API) | the vendor CLI `paddleocr doc_parser` |
| Arguments | `PaddleOCRVL(pipeline_version="v1.6", use_layout_detection=True, use_doc_orientation_classify=False, use_doc_unwarping=False, use_queues=True, engine=$PADDLEOCR_ENGINE (default paddle), device=$PADDLEOCR_DEVICE (default gpu:0))`; `predict(…, chart/seal/ocr_image_blocks False by default, format_block_content=True, temperature=0.0, max_new_tokens=4096)` | the same values as CLI flags; **`max_new_tokens` has no CLI flag** in the 3.7.0 documentation, so the vendor default applies (value not read) |
| Output | blocks with bbox and confidences; the adapter **requires** `token_confidences`/`token_scores`/`rec_scores` on every block | the vendor's Markdown (`save_to_markdown`). The documented `parsing_res_list` fields are `block_bbox`, `block_label`, `block_content`, `block_id`, `block_order` — no confidences — so, per the documentation, the production adapter would refuse every page with `paddleocr_token_confidence_required` (not run; recorded for the production lane) |
| Models | `PADDLEOCR_MODEL_MANIFEST` (+ sha256): a layout directory and the VLM directory with file digests; contents not in the repository | the VLM repository at `c5630aba`, every file; **the layout model is unpinned**: the v1.6 pipeline's layout model is not named in the documentation read (v1 used PP-DocLayoutV2), so the recipe lists it with `null` repository and revision and the server refuses to start |
| Pages | one page per request | one-page sources only (the CLI has no page range; `page_index` above 0 → 400 `page_index_unsupported`) |

## Review notes closed (review of WO-D10-0F, r20)

Each with a test and a mutant (`receipts/WO-D10-0I/mutants.out.txt`): the command's return code
is checked (a non-zero exit is a failure even when it left a file); socket timeout, and the busy
slot taken only after the body is read; non-ASCII digest headers, non-ASCII or non-digit content
length, non-string language → fixed 4xx; the size bound on the serialized response; after a
timeout or a non-zero exit the server answers 503 until the service is fresh and the command is
killed with its process group; PDF `page_index` true, an image with a page index, an unsupported
content type, the refused body read off the socket, `/health`'s revision — each tested.

**Debian packages.** `libgl1=1.6.0-1` and `libglib2.0-0=2.74.6-2+deb12u9` are pinned by version
as well as by the snapshot date: those are the versions the snapshot's indexes carry at
`20261116T000000Z` (bookworm main `Packages.xz` sha256 `9e0b5aab…`, bookworm-updates `87e7e940…`,
bookworm-security `5625320b…`; the security index carries `libglib2.0-0` only at `deb12u2`, lower
than main's). Their dependencies are fixed by the snapshot date alone: a snapshot archive does not
change, so the date fixes every version apt resolves.

## Open before real pages (not checked here)

- No image is built: the locks, the Debian versions and the weights are verified only by a build
  and a launch.
- **C3's runner key.** `infra/model-registry/models.yaml` names C3 `mineru_vlm`, and
  `benchmark/runners/registry.py` has no external-protocol entry for it. The one-line change for
  the lead to route (with `RunnerConfig, run_external` imported from `.base`):
  `"mineru_vlm": lambda case, *, endpoint, revision, allow_network=False: run_external(RunnerConfig("mineru_vlm", revision, endpoint, allow_network), case),`
  The withdrawn chat runner on `codex/v34-c-arena-serve` registers the same key; only one of the
  two can stay.
- **C1's layout model**: name, repository, revision, licence and a manifest; until then C1 does not
  start. The C1 image's transitive packages are not locked.
- "No outbound request at inference" is configured (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`,
  `MINERU_MODEL_SOURCE=local`), not proven. PaddleX may check its model hosters at import; A0 runs
  each image with egress observed.
- The 100 s proxy limit against a page's latency (§5G A0-4); the server's own limit is 175 s.
