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
| C1 | `recipes/c1-paddleocr-vl.json` | PaddleOCR's documented `PaddleOCRVL(...)` object, pipeline v1.6, kept loaded by a loopback service (`../paddleocr-vl-akc/paddleocr_vl_service.py`); one client call per page | `PaddlePaddle/PaddleOCR-VL-1.6@c5630aba` and the layout model `PaddlePaddle/PP-DocLayoutV3@241f8bdf`, both downloaded at launch | `../paddleocr-vl-akc/Dockerfile` |

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
| `recipes/c1-layout-weights-manifest.json` | Every file of `PaddlePaddle/PP-DocLayoutV3` at `241f8bdf` (5 files, 132,018,611 B), from the Hub API read at that revision (snapshot sha256 `6f73f857…`) |
| `weights-manifest.json` | The 40 files (2,595,586,833 B) of PDF-Extract-Kit-1.0 @ `ed6b654c` that MinerU 3.4.4 loads (C0) |
| `Dockerfile` | Targets `c0` and `c3`. Base by digest, Debian packages by version from a dated snapshot, Python packages by version and sha256 |
| `requirements.in` / `requirements.lock` | C0: top-level pins / the full hashed closure (98 packages) |
| `requirements-c3.lock` | C3 layer: the two packages MinerU's `[vlm]` extra adds (accelerate 1.14.0, psutil 7.2.2), hashed |
| `mineru.json` / `mineru-vlm.json` | MinerU config for C0 / C3: local models only, LLM-aided titles off |
| `test_mineru_akc_server.py` | The real client against the server, in process, for every recipe |
| `../paddleocr-vl-akc/Dockerfile` | C1: the production worker's image stage with this server, the C1 service and the C1 recipe |
| `../paddleocr-vl-akc/paddleocr_vl_service.py` | C1's service (`serve`: the `PaddleOCRVL` object built once with the production adapter's arguments, `127.0.0.1` only) and its one-page client (`page`); standard library, no subprocess |
| `../paddleocr-vl-akc/test_paddleocr_vl_service.py` | The service with a fake `PaddleOCRVL` (no paddle, no GPU), through this server's own command pipeline |

## Recipes

A recipe is a JSON object with exactly these keys (`load_recipe` refuses anything else):
`name`, `provider` (the runner key the server answers as), `model` (`repo_id`, full 40-character
`revision`, `dir`, `manifest`: the model it attests), `aux_models` (other models it loads, each
pinned the same way or the server will not start), `packages` (name → pinned version or `null`;
the installed versions go into every receipt, and a pinned one that differs stops the server),
`service` (a long-lived loopback child: `argv`, `health_url` on `127.0.0.1` with a port, a finite
`startup_timeout_s` below 3600, and optionally `page_failure_exits`, the command's exit codes 2-99
that mean "the service answered that this page failed and is idle", each with a fixed reason;
or `null`), `argv` (the vendor
command; `{source}` and `{out}` are the page file and the output directory), `page_argv`
(appended for a PDF page, `{page}`; `null` = the command reads whole files, so a page index
above 0 is refused), `lang_argv` / `lang_by_language` (appended when the payload language maps),
`absent_packages` (packages that must not be installed, for example another inference engine;
one that is stops the server), `env`, `output_glob` (exactly one file must match), `timeout_s`
(the page limit: 90 in every recipe, refused at 100 or more, below), `options` (what it does,
stated).

Every result's receipt carries the recipe name, its sha256 (canonical JSON) and options, the
installed package versions and the packages ruled out, the weights repository, revision and
manifest sha256 of the model and of every aux model, `includes_model_load` (true when the recipe
has no long-lived service, so the command loads every model for each page), the Python version,
input and source digests, page index, language value, latency and the markdown sha256.

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
- **C1**: the same shape, twice: `recipes/c1-weights-manifest.json` into
  `/opt/akc/models/PaddleOCR-VL-1.6`, then `recipes/c1-layout-weights-manifest.json` into
  `/opt/akc/models/PP-DocLayoutV3` (`5 files, 132018611 bytes, verified`); the server logs a
  `weights` line for each (`model` and `layout_detection`), starts the recipe's service
  (`paddleocr_vl_service.py serve`), which builds `PaddleOCRVL(...)` once and prints
  `PaddleOCRVL loaded; serving on 127.0.0.1`, waits for its `GET http://127.0.0.1:8081/health`
  (200 only once the object is loaded; up to 600 s), then serves. Each page runs the client
  (`paddleocr_vl_service.py page --url http://127.0.0.1:8081/page --source <page file>`).
  The image's `CMD` does exactly this.

## What a failure looks like in the log

| Kind | Log | Answer |
|---|---|---|
| Operational, at start | `recipe refused: …`, `<pkg> … installed, the recipe pins …`, `<role>: weights differ from the manifest`, `<role>: not pinned in the recipe`, `the recipe's service did not become healthy` (for C1 preceded by `AKC_SERVICE_LOAD_FAILED <exception type>` and its trace when `PaddleOCRVL(...)` cannot be built) | the process exits; the pod is not serving |
| Operational, serving | the vendor service's own crash output | `503 pipeline_unavailable`, nothing recorded for the page |
| Recovery | after a timed-out page or a non-zero exit of a recipe with a service, the service is killed and restarted | `503 pipeline_unavailable` until it is healthy again, so no abandoned work runs into the next page |
| Service died between pages | `service exited on its own (<code>); restarting`: the next page starts **one** restart | that page and every page until the new child is healthy: `503 pipeline_unavailable` |
| Restart failed | `service did not come back; answering 503`; no further restart | `503` for every page and `/health` `ready: false` for good. **A launcher treats this as a dead pod** (operational): it tears the pod down and records it, it does not retry pages into it |
| Model / page | the vendor command's own stdout and stderr; for `pipeline_error` the Python trace; for C1 the service's trace of the object's exception and `page failure: '<reason>'` | `200` with a failure row: `pipeline_exit_nonzero`, `page_timeout`, `pipeline_output_missing`, `empty_output`, `output_too_large`, `page_content_type_unsupported`, `pipeline_error`, and for C1 `pipeline_raised` (the object raised on the page) and `page_count_unsupported` (the object read the source as more than one page). The two C1 reasons come from the recipe's `page_failure_exits`: the service is idle and stays loaded, so there is no restart; any other non-zero exit of C1's client (service unreachable, refused, not loaded) restarts the service like C0's; never a trace in the body |
| Request | — | `400/401/404/409/411/413/429` with `{"error": "<fixed code>"}`; never a page failure, never a restart |
| Server bug | `refused to send <n> bytes` or the trace | `500 response_too_large` / `500 internal_error` |

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
  Every request field the server echoes or passes on is bounded: `benchmark_case_id` 1–256
  printable ASCII (`case_id_invalid`), `page_index` an integer 0–9999 (`page_index_invalid`),
  `source.content_type` 1–128 printable ASCII (`content_type_invalid`). Two `Content-Length`
  headers are **411**.
- **What reaches the vendor command.** Its argv is the recipe's own items (`vendor_argv`); a
  request decides only the page number (bounded above) and, through the recipe's own mapping,
  a language value. A test drives 454 generated payloads through the server to show it.
- **Page limit 90 s.** The pod's HTTP proxy cuts a request at 100 s (§5G). Each recipe's
  `timeout_s` is 90, so a slow page is killed with its process group and answered with the
  failure row `page_timeout` before the proxy cuts the connection: a recorded failure, not a
  transport error. The value is configurable per recipe; a recipe at 100 s or more is refused
  at start. The launcher (WO-D10-0G) reads it from the recipe or the registry row
  (`page_timeout_s`).
- **After every command exit** (success, failure, timeout) its process group is killed, so a
  grandchild that outlives the vendor CLI cannot run into the next page. The output file is
  stat'ed before it is read: above the response bound it is `output_too_large`, unread.
- Every read and write on the socket times out after 30 s; a stalled client is dropped.
- **200** only for a page the command ran: the output (`benchmark/schemas/parser-output.schema.json`)
  or a failure row. The 8 MiB bound applies to the serialized response, not the text, and is
  checked where every answer is written.
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
| Invocation | `mineru --path <dir> --backend pipeline --method ocr`, a batch per call | one page per call: `-s N -e N`, `-f true -t true` (the documented defaults, stated), against a long-lived loopback `mineru-api` so models stay loaded; the CLI runs as a child process with a 90 s limit |
| Language | no `-l` | **no `-l`** (same). `-l korean` for `ko` only in the named recipe `c0-mineru-pipeline-lang-ko` |
| Concurrency | `MINERU_API_MAX_CONCURRENT_REQUESTS=1` | same, and the server refuses a second page |

**C3** — recorded: `infra/runpod/v6/bootstrap/mineru-3.4.4-transformers-c1.sh` with
`run-mineru-3.4.4-public-core-worker.sh` (`--backend vlm-engine`), the only MinerU script under
`infra/`; it runs this model at this revision. The attested weights are the ones the tool loads
because `mineru-vlm.json` points `models-dir.vlm` at the verified directory and
`MINERU_MODEL_SOURCE=local`; the card at `bff20d4a` asks for `transformers>=4.56.0` (4.57.3
here) and, for the vLLM engine only, `vllm>=0.10.1`.

| | Recorded | `c3-mineru-vlm` |
|---|---|---|
| MinerU | git `79d6d8d7`, `[core]` | PyPI `mineru==3.4.4`, `[pipeline]` + `[vlm]` (the C0 image plus accelerate and psutil); `[core]`'s gradio is not installed |
| Inference engine | transformers (no vLLM installed) | **transformers**, stated in the recipe and fixed: `absent_packages: [vllm, lmdeploy]`, so the server refuses to start if either is installed. MinerU's card recommends vLLM; a vLLM-engine recipe would be a named deviation (not built) |
| Torch / transformers / accelerate / mineru-vl-utils | 2.8.0+cu128 / 4.57.3 / 1.14.0 / 1.0.5 | 2.8.0 PyPI / 4.57.3 / 1.14.0 / 1.0.5 |
| Weights | `snapshot_download` at `bff20d4a`, no file check | the same download plus a per-file manifest check, then again at server start |
| Invocation | batch per call, `--method ocr` (applies to pipeline/hybrid only per the CLI help) | one page per call, `-s N -e N`, no `-m`; `-f true -t true --image-analysis true` (the CLI's documented defaults, stated) |
| Preload | not recorded | `mineru-api --enable-vlm-preload true` |

Same tool as C0: same MinerU version, image and server; only the backend, the weights and
two packages differ.

**Engine.** The 3.4.4 documents read (`docs/en/usage/cli_tools.md`, sha256 `c33cd86d…`;
`quick_start/extension_modules.md`, `061f634c…`; `quick_start/index.md`, `usage/quick_usage.md`)
list the backends `pipeline`, `vlm-engine`, `hybrid-engine`, `vlm-http-client`,
`hybrid-http-client`, and name `vllm` and `lmdeploy` as optional modules that accelerate VLM
inference ("choose one of them to install"). They document no option of `mineru` or
`mineru-api` that selects the engine for `vlm-engine` (`--engine` is documented only for
`mineru-openai-server`). The documented selection is which module is installed, so the recipe
selects transformers by installing neither and the server enforces it at start
(`absent_packages`); the receipt records `options.inference_engine` and `absent_packages`.

**C1** — production: `workers/gpu-parser/paddleocr_adapter.py` in the `production` stage of
`workers/gpu-parser/Dockerfile`.

| | Production | `c1-paddleocr-vl` |
|---|---|---|
| Image | CUDA 12.9.1 cuDNN Ubuntu 24.04 by digest, apt unpinned, gpu-common `uv.lock`, `paddlepaddle-gpu==3.2.1` (cu126 index), `paddleocr[doc-parser]==3.7.0`, transitive packages resolved at build | the same, the same commands (`../paddleocr-vl-akc/Dockerfile`), plus `paddlex==3.7.2` (the release whose v1.6 pipeline config names the pinned layout model; production lets it resolve). **Not hash-locked.** For this evaluation-only image the pin is the built image digest plus the `uv pip freeze` and `pip inspect` output the build prints to its log, which the lead saves as a receipt. **A hash-locked requirements file is required before any production use** and is not part of this work order |
| Entry | the generic runtime handler → `PaddleOcrVlAdapter` (Python API) | the same Python API: `paddleocr_vl_service.py` keeps one `PaddleOCRVL` object and calls `predict(input=<page file>, …)` then `save_to_markdown(save_path=<out>)` on the result (PaddleOCR 3.7.0 `PaddleOCR-VL.en.md`, snapshot sha256 `4d383354…`) |
| Arguments | `PaddleOCRVL(pipeline_version="v1.6", layout_detection_model_dir=<manifest's layout dir>, vl_rec_model_dir=<manifest's VLM dir>, use_layout_detection=True, use_doc_orientation_classify=False, use_doc_unwarping=False, use_queues=True, engine=$PADDLEOCR_ENGINE (default paddle), device=$PADDLEOCR_DEVICE (default gpu:0))`; `predict(input=str(input_path), use_doc_orientation_classify/use_doc_unwarping/use_chart_recognition/use_seal_recognition/use_ocr_for_image_block = the request's option, default False, use_layout_detection=True, format_block_content=True, temperature=0.0, max_new_tokens=the request's max_output_tokens, default 4096)` | **the same keywords and the same values**, with production's defaults where production reads an option: `construct_kwargs` and `PREDICT_KWARGS`. Where each comes from: the two directories are the recipe's verified model directories (`--layout-dir`, `--vl-rec-dir`, checked against the manifests before the service starts); `engine` `paddle` and `device` `gpu:0` are production's defaults, checked against production's sets; the option flags are production's defaults (False); `max_new_tokens` is production's default 4096 (the CLI of round 2 could not pass it). A test reads the adapter as text and fails when the keywords or values drift |
| Output | blocks with bbox and confidences; the adapter **requires** `token_confidences`/`token_scores`/`rec_scores` on every block | the vendor's Markdown (`save_to_markdown`). The documented `parsing_res_list` fields are `block_bbox`, `block_label`, `block_content`, `block_id`, `block_order` — no confidences — so, per the documentation, the production adapter would refuse every page with `paddleocr_token_confidence_required` (not run; recorded for the production lane) |
| Models | `PADDLEOCR_MODEL_MANIFEST` (+ sha256): a layout directory and the VLM directory with file digests; contents not in the repository | **pinned where production is not**: the VLM repository at `c5630aba`, every file; the layout model **`PaddlePaddle/PP-DocLayoutV3` @ `241f8bdfc77a7c7bee915a5057aaee58c235a8d3`**, every file (`recipes/c1-layout-weights-manifest.json`), passed as `layout_detection_model_dir`. Like production, the model *name* is not passed: it is the pipeline config's, `paddlex/configs/pipelines/PaddleOCR-VL-1.6.yaml` at v3.7.0, v3.7.1 and v3.7.2 (byte-identical, sha256 `af89f00e…`) sets `LayoutDetection.model_name: PP-DocLayoutV3`, and the repository's `inference.yml` at the pin says `model_name: PP-DocLayoutV3`. Weights licence: the card's `license: apache-2.0` (no LICENSE file in the repository), its own intake row `model_pp_doclayoutv3` |
| Auxiliary models | orientation and unwarping off (`use_doc_orientation_classify=False`, `use_doc_unwarping=False`) | the same, so neither PP-LCNet_x1_0_doc_ori nor UVDoc (the config's doc-preprocessor models) is loaded: switched off by the documented options `--use_doc_orientation_classify False --use_doc_unwarping False`, not pinned |
| Model load | the Python object stays loaded across pages | **the same**: the service builds the object once when the pod starts (inside the service's 600 s start-up limit, not a page's 90 s), and the receipt says `includes_model_load: false`. A page's time is its request: the client call, `predict` and `save_to_markdown`. C1's latency and cost per page are measured on the same terms as C0's and C3's |
| Pages | one page per request (`paddleocr_single_page_result_required`) | one page per request: the server refuses `page_index` above 0 (400 `page_index_unsupported`, no page range in the object's documented `predict`), and the service reads every result of the object and refuses a source the object reads as more than one page (failure row `page_count_unsupported`, nothing written), production's rule. The server does not count PDF pages itself: the standard library cannot do it reliably (object streams compress the page tree, incremental updates leave superseded page objects), so the count is the vendor parser's own |

## Review notes closed (review of WO-D10-0F, r20)

Each with a test and a mutant (`receipts/WO-D10-0I/mutants.out.txt`): the command's return code
is checked (a non-zero exit is a failure even when it left a file); socket timeout, and the busy
slot taken only after the body is read; non-ASCII digest headers, non-ASCII or non-digit content
length, non-string language → fixed 4xx; the size bound on the serialized response; after a
timeout or a non-zero exit the server answers 503 until the service is fresh and the command is
killed with its process group; PDF `page_index` true, an image with a page index, an unsupported
content type, the refused body read off the socket, `/health`'s revision — each tested.

**Round 2 (review of WO-D10-0I).** Each with a test and a mutant
(`receipts/WO-D10-0I/round2/mutants.out.txt`): every request field the server echoes or passes
on is bounded, and a generated-payload test covers the class, not the probe's one input; the
response bound is enforced where every answer is written; the command's process group is killed
after every exit; the output file is stat'ed before it is read; `main()` gives the vendor command
no bearer token; the real `Service` restarts after `recover`, restarts once after its child died
on its own, and stops trying after a failed restart; the 90 s page limit; C3's engine and C1's
layout model pinned; the two recipe-driven `Popen` calls carry `# noqa: S603` with the reason the
generated-payload test checks.

**Debian packages.** `libgl1=1.6.0-1` and `libglib2.0-0=2.74.6-2+deb12u9` are pinned by version
as well as by the snapshot date: those are the versions the snapshot's indexes carry at
`20261116T000000Z` (bookworm main `Packages.xz` sha256 `9e0b5aab…`, bookworm-updates `87e7e940…`,
bookworm-security `5625320b…`; the security index carries `libglib2.0-0` only at `deb12u2`, lower
than main's). Their dependencies are fixed by the snapshot date alone: a snapshot archive does not
change, so the date fixes every version apt resolves.

**Round 3 (review of WO-D10-0I r2).** Each with a test: C1 keeps its models loaded behind
`paddleocr_vl_service.py` (above), with a fake `PaddleOCRVL` injected in the tests (loaded once
across pages; health 503 before and 200 after the load; a raising page is a failure row and the
next page works; a construction failure is an operational exit the server reports; the
arguments equal the production adapter's, read from its text; the service binds `127.0.0.1`
only and accepts only a page file of the server's own work directory, by a property test over
hostile values). `load_recipe` is checked as a class, not by the probe's inputs: every field of
every shipped recipe replaced by each of 26 hostile values or removed raises only `ValueError`,
and whatever it accepts the server uses without a type error; NaN and infinities are refused
(JSON constants and `1e999` alike), both time limits are finite numbers in range, `aux_models`
is a list of fully pinned models with unique roles other than `model`, argv fields are bare
names, the health URL has a valid loopback port, the output pattern is relative and stays in
the output directory. The registry contract test requires `image_build` to be a file named
`Dockerfile` whose resolved path is inside the repository.

## Open before real pages (not checked here)

- No image is built: the locks, the Debian versions and the weights are verified only by a build
  and a launch. The C1 image's transitive packages are known only from its build log.
- C3's runner key `mineru_vlm` is registered (`benchmark/runners/registry.py`, round 2).
- "No outbound request at inference" is configured (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`,
  `MINERU_MODEL_SOURCE=local`), not proven. PaddleX may check its model hosters at import; A0 runs
  each image with egress observed.
- Whether 90 s is enough per page is measured at A0. C1's models now load once at start, within
  the service's 600 s start-up limit, which A0 also measures.
- The arena manifest addresses pages of whole documents (`doc_id#p`). C1 runs only `page_index`
  0 of a one-page source; a later page is 400 `page_index_unsupported` and a multi-page source
  at page 0 is the failure row `page_count_unsupported`. C1 needs one-page sources from the
  driver, or a page selection the vendor documents, before it can screen multi-page documents.

## How the image is built and where its digest is recorded

This machine has no Docker, so the images are built on GitHub Actions by
`.github/workflows/build-arena-page-servers.yml` (WO-D10-0K), on the precedent of
`build-ovis-runtime.yml`: the same pinned actions, `contents: read` and `packages: write`, the
workflow's own token for GHCR and no other secret. It runs on `workflow_dispatch` and on a push to
`codex/v34-c-arena-build` that touches this directory, `../paddleocr-vl-akc/`, the two
`workers/gpu-common` files the C1 image copies, or the workflow itself.

| Slot | Dockerfile, target | Build context, and why | Tag |
|---|---|---|---|
| C0 | `Dockerfile --target c0` | this directory: every `COPY` names one of its files | `ghcr.io/<owner>/<repo>/arena-mineru-pipeline-akc-c0:<commit>` |
| C3 | `Dockerfile --target c3` | this directory, as C0 | `ghcr.io/<owner>/<repo>/arena-mineru-pipeline-akc-c3:<commit>` |
| C1 | `../paddleocr-vl-akc/Dockerfile` | the repository root: it copies `workers/gpu-common/{pyproject.toml,uv.lock}` and this directory's server, weights checker and C1 recipes | `ghcr.io/<owner>/<repo>/arena-paddleocr-vl-akc:<commit>` |

`<owner>/<repo>` is the repository name in lower case and `<commit>` the commit the run checked
out (the job fails if that is not the workflow's commit). Each job builds `linux/amd64` without
provenance or SBOM attestations, pushes, then reads the manifest digest back from GHCR with
`docker buildx imagetools inspect` and **fails if it cannot read one or if it differs from the
digest the build reported**. The job also fails if the Dockerfile does not name exactly one base
image by digest, or if the package listing is missing, clipped by BuildKit's log limit, came from
a cached step or did not finish.

The package listing is the build log section of the steps that print it: for C0 and C3 the
`pip install --require-hashes` steps (C3 has two), for C1 the step that runs `uv pip freeze` and
`pip inspect`. Each job writes to its job summary the pinned image (`…@sha256:…`), the manifest
digest, the base image, the source commit and the listing's sha256, and uploads the artifact
`arena-page-server-<slot>-<commit>` (30 days) with `build-receipt.json` (the same fields plus
the build log's sha256 and the run id), `build-metadata.json`, the full `build.log` and
`package-listing.log`. The workflow never changes the package's visibility.

The lead pushes the build branch, reads the digests from the run, saves the artifact as a
receipt and records each digest in its row of `infra/model-registry/models.yaml`
(`built: true`, `image: ghcr.io/…@sha256:…`).
