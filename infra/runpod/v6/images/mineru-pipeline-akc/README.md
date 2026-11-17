# C0 — MinerU 3.4.4 pipeline behind the AKC external-runner protocol

Arena slot C0 (WO-D10-0F): the incumbent every other candidate is compared with. The
registered runner `mineru` (`benchmark/runners/mineru.py` → `base.run_external`) speaks the
external-runner protocol; this image is the server side of it. **Evaluation only.** It is not
the production endpoint, and the production endpoint is not used for benchmark load.

**Rebuilt, not the production digest.** The repository does not record the image digest the
production MinerU endpoint runs: `infra/runpod/v6/pool-registry.yaml` has
`identity_state: pending_exact_image_digest` for `parser-mineru-3-4-4`, and
`benchmark/v6/candidate-registry.yaml` has `measured_partial_runtime_image_pending` for
`mineru-3.4.4-pipeline`. Per §5A, the 3.4.4 release is rebuilt and every receipt says
"rebuilt".

Nothing here has been built, pushed or run on a pod.

## Files

| File | What it is |
|---|---|
| `Dockerfile` | Base by digest, Debian packages from a dated snapshot, Python packages by version and sha256, weights by revision and per-file digest |
| `requirements.in` / `requirements.lock` | Top-level pins / the full hashed closure (98 packages) |
| `weights-manifest.json` | The 40 files (2,595,586,833 B) of `opendatalab/PDF-Extract-Kit-1.0` @ `ed6b654c` that MinerU 3.4.4 loads |
| `mineru_akc_weights.py` | Build step: download those files, refuse any size, digest or extra-file difference |
| `mineru.json` | MinerU config: local models only, LLM-aided titles off |
| `mineru_akc_server.py` | The protocol server (standard library) |
| `test_mineru_akc_server.py` | The real client against the server, in process |

## Protocol (the mirror of `base.external_exchange`)

`POST /parse` with the provider payload as JSON. Headers: `X-AKC-Benchmark-Provider: mineru`,
`X-AKC-Model-Revision` = the weights revision, `X-AKC-Input-SHA256` = sha256 of the body,
`Authorization: Bearer <token>` when `AKC_BENCHMARK_PROVIDER_TOKEN` is set on the pod.

- **200** only for a page the pipeline ran: the parser output (`benchmark/schemas/parser-output.schema.json`),
  or a failure row (`failure.reason`, `receipt`) when the pipeline failed on the page. The
  receipt carries the recipe and its sha256, the package versions, the weights revision and
  manifest sha256, the input and source digests, page index, `-l` value, latency and the
  markdown sha256.
- **401** token configured and missing or wrong · **411** no `Content-Length` · **413** over
  96 MiB · **409** another provider, or a revision other than the baked one (the server never
  echoes the header) · **429** a page is already running (never queued) · **400** body digest,
  JSON, payload shape, source digest, or page index wrong · **503** the `mineru-api` child is
  gone (operational, nothing recorded). Every error body is `{"error": "<fixed code>"}`; a
  pipeline exception's text and trace go to the pod log only.
- `GET /health` gives provider, revision, receipt sha256 and whether a page is running.

The pod proxy terminates TLS (`https://<podId>-8080.proxy.runpod.net/parse`). Before any real
page (§5G A0-4) the token is set from a RunPod secret.

## Recipe, and where it differs from the recorded one

Recorded recipe in the repository: `benchmark/runpod_eval/mineru_stage2.py` (the candidate
registry's `runtime_recipe` for `mineru-3.4.4-pipeline`), the bootstrap pattern in
`infra/runpod/v6/bootstrap/`, and `benchmark/reports/MINERU_3_4_4_OMNIDOCBENCH_DEMO_EVALUATION_2026-08-01.md`.
`workers/` has no MinerU worker. Differences:

| | Recorded | This image |
|---|---|---|
| MinerU | git checkout `opendatalab/MinerU` @ `79d6d8d7`, `[core]` extra | PyPI `mineru==3.4.4` (wheel sha256 `d4d67853…`), `[pipeline]` extra. Whether `79d6d8d7` is the wheel's commit was not checked (no repository read) |
| Torch | 2.8.0+cu128 from the PyTorch index | 2.8.0 from PyPI with the CUDA 12.8 `nvidia-*` wheels |
| Python | `/usr/bin/python3.11` on an unrecorded pod image | `python:3.11-slim-bookworm@sha256:e8c69d86…` (amd64) |
| Other packages | no pip freeze in the repository | resolved as of 2026-08-01 (the pipeline evaluation's date), hashed |
| pypdfium2 | unrecorded | 4.30.0 (the arena's one renderer, §5F decision 5) |
| Weights | artifact manifest `sha256:fc2064a5…` (contents not in the repository) | the ModelPath subtree at `ed6b654c`, per-file digests |
| Invocation | `mineru --path <dir> --backend pipeline --method ocr`, a batch per call, no `-l` | per page `-s N -e N`, `-l korean` when the payload language is `ko` (otherwise MinerU's default), `-f true -t true` (the documented defaults, stated), against a long-lived loopback `mineru-api` so models stay loaded |
| Concurrency | `MINERU_API_MAX_CONCURRENT_REQUESTS=1` | same, and the server refuses a second page |

The `mineru` command is run in process through its console-script entry point (a click
command) because its arguments carry the page's temporary path, page index and language.

## Open before real pages (not checked here)

- The image is not built: the lock, the Debian snapshot date and the weights download are
  verified only by the build. Python patch version is recorded at build.
- "No outbound request at inference" is configured (`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`,
  `MINERU_MODEL_SOURCE=local`), not proven. MinerU dependencies such as `fast-langdetect` may
  fetch at first use; A0 runs it with egress observed.
- That MinerU 3.4.4 loads nothing outside `weights-manifest.json`: a missing file fails the
  page (failure row), it is not fetched.
- The 100 s proxy limit against a page's latency (§5G A0-4).
