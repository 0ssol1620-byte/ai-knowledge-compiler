# ARENA_CONTRACT — frozen interfaces for campaign TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1

Source of truth for *what to build*: `D:\TAVONEL_PUBLIC_DOC_PARSING_MODEL_ARENA_EXECUTION_MASTERPLAN_2026-09-03.md`
(referenced below as "MP §n"). This file freezes the interfaces between lanes so
they can be built in parallel. If a lane needs to change an interface, it writes
the proposed change into its report and does NOT edit another lane's files.

Repository rules that bind here (from `CLAUDE.md`): no silent fallback; fail
closed on integrity violations; never invent data to satisfy a schema; every
document is hostile data; never route on a scalar blind quality score; separate
operational failure from semantic failure; never infer capability from a model
name; secrets never enter files, receipts, logs or prompts.

## 0. Scope of this namespace

- Root: `research/model_arena_20260903/` (MP §2.5 independent namespace).
- Python package: `arena` (import as `from arena.x import y`). Tests import it
  via `conftest.py`. Run tests with
  `.venv/Scripts/python.exe -m pytest research/model_arena_20260903/tests -q`.
- Lint/type: `.venv/Scripts/python.exe -m ruff check research/model_arena_20260903`
  and `.venv/Scripts/python.exe -m mypy research/model_arena_20260903/arena`
  (repo `pyproject.toml` config: strict mypy, ruff E/F/I/UP/B/ASYNC/S/SIM/RUF,
  line length 100, target py312).
- Python 3.13 venv at `.venv/`. Available deps include pydantic 2, jsonschema,
  pillow, httpx, fastapi, uvicorn, boto3, pyyaml, orjson, tenacity, structlog.
  Do not add new third-party dependencies to the repo `pyproject.toml`; the
  on-pod worker must run with only the standard library + `pillow` + whatever
  the model runtime image already ships (see §6).
- **Never touch**: `research/tavonel_eval_v2/**` (active SFIR frozen state, has
  uncommitted files), `docs/evidence/**`, `docs/ip/**`, `benchmark/**` (read
  only), `infra/**` (read only), `workers/**` (read only), `.claude/**`.
- **No git commands** of any kind from a lane (no add/commit/stash/checkout/
  branch). The orchestrator commits.
- **No paid or external side effects** from a lane unless its lane brief says
  so explicitly. Reading the RunPod API (list/catalog/billing) is allowed for
  the lanes that name it. Creating pods, endpoints, volumes, templates or
  buckets is NOT allowed in this build phase.

## 1. Directory layout and lane ownership

Each lane writes ONLY inside its owned paths. Shared read of everything.

```
research/model_arena_20260903/
├─ ARENA_CONTRACT.md                (orchestrator)   this file
├─ README.md                        (orchestrator)
├─ conftest.py, .gitignore          (orchestrator)
├─ arena/__init__.py, constants.py  (orchestrator)   frozen constants
├─ arena/worker/adapter_api.py      (orchestrator)   frozen adapter interface
│
├─ arena/core/                      (lane A1)  ids, receipts, events, errors, states, schemas/*.json
├─ arena/manifest/                  (lane A2)  source manifest, canary selection, preflight, GT isolation audit
├─ arena/registry/                  (lane A3)  model + evaluator registry resolution and validation
├─ prompt_registry/                 (lane A4)  prompts + sha256.json
├─ arena/controller/                (lane B1)  campaign controller, queue, scheduler, watchdogs, cost ledger
├─ arena/provider/                  (lane B1)  runpod_pods.py, r2.py, secrets.py, catalog snapshot
├─ arena/worker/  (except adapter_api.py)  (lane B2)  server.py, persistence, heartbeat, bundle packaging
├─ runtimes/<model_key>/            (lanes C1/C2/C3)  Dockerfile, adapter.py, canonical.py, runtime.json, README.md
├─ arena/opus/                      (lane D)   Opus 5 subscription runner
├─ arena/tavonel/                   (lane E1)  signals, route freeze, replay variants, recovery plan, disagreement
├─ arena/scoring/                   (lane E2)  QA gate, evaluator adapters, score provenance
├─ arena/reports/                   (lane E3)  §29 report + evidence manifest generators
├─ build/                           (lane F)   image build plan, builder-pod script, .dockerignore, receipts schema
├─ tests/<lane_dir>/                (each lane) tests live in tests/core, tests/manifest, tests/registry,
│                                              tests/controller, tests/provider, tests/worker, tests/runtimes,
│                                              tests/opus, tests/tavonel, tests/scoring, tests/reports, tests/build
│
│  Generated during the campaign (gitignored unless small):
├─ campaign_manifest.json           (A2 writes; B1 reads)
├─ source_manifest.jsonl            (A2)
├─ canary_selection.json            (A2)
├─ model_registry.json              (A3)
├─ evaluator_registry.json          (A3)
├─ queue/  runs/  frozen_outputs/  tavonel/  scores/  failures/  receipts/  cost/  reports/  evidence/
```

Lane-to-model mapping for runtimes:

- C1: `paddleocr_vl_1_6`, `hpd_parsing`, `mineru_pipeline`, `mineru_vlm`
- C2: `deepseek_ocr2`, `ovisocr2`, `unlimited_ocr`
- C3: `infinity_parser2_pro`, `monkeyocrv2_b`, `olmocr2`, `glm_ocr`
- D:  `opus5_subscription` (not a GPU runtime; lives in `arena/opus/`)

## 2. Identifiers (MP §9)

- `campaign_id` = `arena.constants.CAMPAIGN_ID`.
- `benchmark` ∈ `("parsebench", "omnidoc", "olmocr")`; staged ids map via
  `arena.constants.STAGED_BENCHMARK_ID`.
- `sample_id` = `<benchmark>:<official-id>` where official-id is the staged
  manifest's `source_relative_path` with its extension removed, plus
  `#p<page_index>` when `media_type == "pdf"`. Examples:
  `omnidoc:images/PPT_1001115_eng_page_003`,
  `parsebench:docs/chart/(Web_version)_E-Government_Survey_2024_1392024_p101#p0`,
  `olmocr:bench_data/pdfs/arxiv_math/2502.15977_pg21#p0`.
- `case_key` = the staged `case_id` (e.g. `omnidocbench-58851882e7b39101a6f5756c`).
  Filesystem-safe; used for every on-disk file name. `sample_id` is used in
  records and reports. Both appear in every record.
- `inference_job_id` = lowercase hex sha256 of the canonical JSON
  (`sort_keys=True, separators=(",", ":"), ensure_ascii=True`) of exactly:
  `{campaign_id, benchmark_revision, sample_id, source_sha256, model_repo,
  model_revision, runtime_image_digest, prompt_sha256, inference_config_sha256}`.
  `runtime_image_digest` is the string `"bootstrap:<runtime_bundle_sha256>"`
  when a canary runs in bootstrap mode (§6.4). Same id + existing
  `SUCCESS` receipt with matching `raw_output_sha256` ⇒ never re-run.
- `recovery_job_id` = sha256 of `{campaign_id, inference_job_id_of_base,
  recovery_type, recovery_config_sha256, round}` (MP §24).
- `shard_id` = `<model_key>-<benchmark>-<zero-padded index>`.
- `worker_id` = `<model_key>-w<index>-<pod_id>`.
- All sha256 values that identify files are written as `"sha256:<hex>"`;
  identifiers derived from canonical JSON (job ids) are bare hex.

## 3. Records (all JSON, UTF-8, sorted keys, one schema id each)

Schemas live in `arena/core/schemas/*.json` (JSON Schema draft 2020-12) and are
validated with `jsonschema` by `arena.core.receipts.validate(record)`.
Every record has `"schema": "tavonel.arena.<name>.v1"`.

### 3.1 page-receipt (MP §11) — `runs/<model_key>/receipts/<case_key>.json`

Fields exactly as MP §11 plus: `case_key`, `prompt_id`, `prompt_sha256`,
`inference_config_sha256`, `runtime_mode` (`baked|bootstrap|subscription`),
`image_width`, `image_height`, `worker_id`, `shard_id`, `job_kind`
(`inference|canary|recovery`), `canonical_output_path`, `error_message`
(secret-free, ≤ 2,000 chars), `wasted_gpu_seconds`.
`status` ∈ `SUCCESS|FAILED|QUARANTINED|PAUSED`. `error_class` ∈
`arena.constants.ERROR_CLASSES` or null.

### 3.2 event (MP §33) — `receipts/events.jsonl`, append-only

`{schema, campaign_id, ts, entity_kind: campaign|model|shard|worker|job,
entity_id, from_state, to_state, reason, detail(secret-free)}`.

### 3.3 pod cost ledger (MP §42) — `cost/pod_ledger.jsonl`

Exactly MP §42 fields plus `model_key`, `campaign_id`, `data_center_id`,
`price_snapshot_sha256` (hash of the `provider_receipts/catalog-<ts>.json`
row used), `runtime_mode`.

### 3.4 error record (MP §16) — `failures/errors.jsonl`

Exactly MP §16 fields.

### 3.5 route decision (MP §23.2) — `tavonel/route_decisions/<variant>/<case_key>.json`

Exactly MP §23.2 fields plus `variant`, `campaign_id`, `case_key`,
`signals_sha256`, `policy_id`, `policy_sha256`. `decided_before_gt` must be
`true`; the freeze file `tavonel/route_decisions/<variant>/FROZEN.json`
carries `{frozen_at, decision_manifest_sha256, count, policy_sha256}` and is
written before any evaluator runs.

### 3.6 recovery job (MP §24) — `tavonel/recovery_jobs/plan.jsonl`

`{schema, recovery_job_id, base_inference_job_id, case_key, sample_id,
model_key, recovery_type (overlap_tiling|crop|region_extract|higher_dpi|
alternative_prompt|safer_config|partial_page), recovery_config,
recovery_config_sha256, round, trigger_signals, planned_before_gt: true}`.

### 3.7 model registry record (MP §10) — `model_registry.json`

Exactly MP §10 fields plus: `official_source_urls[]`, `resolved_at`,
`resolution_method`, `license_evidence_url`, `license_notes` (FTO caveats:
OSS licence ≠ patent FTO; no LICENSE ⇒ not reusable), `weights_strategy`
(`baked|volume_cache|boot_download`), `runtime_mode_allowed`
(`["baked"]` or `["baked","bootstrap"]`), `official_prompt_id`,
`official_inference_config` (object) and `official_inference_config_sha256`,
`gpu_pool_priority[]` (RunPod `gpuTypeId` strings), `concurrency_policy`
(for `mineru_vlm`: `{"per_worker": 1, "scale": "replicas_only"}` — MP §14),
`shard_size_hint`, `canary_status` (`PENDING|PASS|FAIL`),
`full_run_eligible` (false until canary PASS + baked image or waiver).

### 3.8 evaluator registry record — `evaluator_registry.json`

Per benchmark: `{repository, historical_pin, upstream_head_at_start,
main_pin, main_pin_rationale, historical_lane_required (bool), entrypoint,
dataset_repository, dataset_revision, dataset_manifest_sha256 (from
benchmark/benchmark-registry.lock.yaml), gt_paths[] (evaluator plane only),
license}`. Once `frozen: true`, no field changes.

### 3.9 prompt registry — `prompt_registry/`

`opus5_transcription_v1.txt` (MP §21.5 verbatim), `model_specific_prompts.json`
(`{prompt_id: {model_key, text, source_url, source_revision, notes}}`),
`sha256.json` (`{prompt_id: "sha256:<hex>"}`), `README.md`.

### 3.10 frozen outputs (MP §7, §Phase 4)

```
runs/<model_key>/raw/<case_key>.raw.txt            raw_text verbatim (bytes exactly as returned)
runs/<model_key>/raw/<case_key>.native.json        native_json when present
runs/<model_key>/raw/<case_key>.claude.json        Opus lane only: full `claude -p --output-format json` payload
runs/<model_key>/canonical/<case_key>.md           canonical markdown
runs/<model_key>/canonical/<case_key>.elements.json  optional
runs/<model_key>/receipts/<case_key>.json          page receipt (§3.1)
runs/<model_key>/run-summary.json
frozen_outputs/<model_key>/manifest.jsonl          {case_key, sample_id, benchmark, status, raw_sha256, canonical_sha256, receipt_sha256, raw_path, canonical_path}
frozen_outputs/<model_key>/FROZEN.json             {frozen_at, manifest_sha256, sample_count, success_count, failed_count, model_revision, runtime_image_digest}
```

Atomic write everywhere: write `<name>.tmp` → fsync → hash → rename (MP §15.8).

### 3.11 scores — `scores/<model_key>/<benchmark>/{evaluator_input/, evaluator_raw/, summary.json}` and `scores/<model_key>/scores.json`

`summary.json` carries the official metrics for that evaluator exactly as
named by the evaluator, plus `provenance` = `{evaluator_repository,
evaluator_revision, evaluator_lane (main|historical), frozen_manifest_sha256,
normalization_revision, campaign_id, model_key, model_revision,
runtime_image_digest, scored_at}` (MP §45). Evaluator failure is recorded as
`{"status": "EVALUATOR_BLOCKED"}` — never as a zero score.

## 4. Worker HTTP API (B2 implements the server, B1 the client)

Listens on `arena.constants.WORKER_PORT` (8000), reached through the RunPod
HTTP proxy `https://<pod_id>-8000.proxy.runpod.net`. Every request carries
`Authorization: Bearer <ARENA_WORKER_TOKEN>` (per-campaign random token passed
to the pod as env `ARENA_WORKER_TOKEN`). Unauthorized ⇒ 401. All bodies JSON.

| Method | Path | Body → Response |
|---|---|---|
| GET | `/v1/ready` | → `ReadyResponse {stage: WORKER_STATES value, worker_id, model_key, model_revision, runtime_mode, runtime_image_digest, load_receipt \| null, warmup_receipt \| null, started_at, ready_at \| null, last_error \| null}` |
| GET | `/v1/heartbeat` | → MP §15.4 object + `stage`, `jobs_done`, `jobs_failed`, `pid` |
| GET | `/v1/provenance` | → MP §38 object (versions, cuda, torch, transformers, vllm, pip_freeze_sha256, pip_freeze_text, apt_snapshot_sha256, os, python, driver) |
| POST | `/v1/run` | `RunRequest` → `RunResponse` (synchronous, exactly one page) |
| GET | `/v1/result/{inference_job_id}` | → persisted `RunResponse` or 404 |
| POST | `/v1/drain` | → `{stage: "DRAINING"}`; no new `/v1/run` accepted (409) |

`RunRequest`:
```json
{"campaign_id": "...", "inference_job_id": "<hex>", "sample_id": "...", "case_key": "...",
 "benchmark": "omnidoc", "source_sha256": "sha256:...", "image_b64": "<PNG base64>",
 "width": 1654, "height": 2339, "prompt_id": "...", "prompt_sha256": "sha256:...",
 "inference_config_sha256": "sha256:...", "job_kind": "inference|canary|recovery",
 "metadata": {"page_index": 0, "media_type": "pdf"}}
```
`RunResponse`:
```json
{"inference_job_id": "...", "status": "SUCCESS|FAILED", "error_class": null, "error_message": null,
 "worker_id": "...", "model_key": "...", "model_revision": "...", "runtime_mode": "baked|bootstrap",
 "runtime_image_digest": "...", "gpu_type": "...", "pod_id": "...",
 "started_at": "...", "first_token_at": null, "finished_at": "...",
 "timings_ms": {"load_ms": 0, "preprocess_ms": 0, "inference_ms": 0, "postprocess_ms": 0, "total_ms": 0},
 "peak_vram_mb": 0, "input_bytes": 0, "output_bytes": 0, "output_chars": 0,
 "input_tokens": null, "output_tokens": null,
 "raw_output": {"raw_text": "...", "output_format": "markdown", "native_json": null, "usage": {}, "warnings": []},
 "canonical": {"markdown": "...", "elements": null, "lossy": false, "conversion_notes": []},
 "raw_output_sha256": "sha256:...", "canonical_output_sha256": "sha256:..."}
```
The worker verifies `sha256(image bytes) == source_sha256` (else `CHECKSUM`),
persists `/workspace/arena/results/<inference_job_id>.json` atomically BEFORE
responding, and returns the persisted result for a repeated job id without
re-running inference. Worker-side per-page timeout comes from the request
(`"timeout_seconds"`, default from runtime.json); on expiry the adapter call is
abandoned in a subprocess or thread the server can kill, and the response is
`FAILED/INFERENCE_TIMEOUT`.

Readiness is two-stage (MP §15.3): `IMAGE_READY` → `MODEL_LOADING` →
`WARMING` (one inference on a bundled synthetic PNG, schema check) → `READY`.
The controller sends `/v1/run` only after `READY`.

## 5. Controller (B1) — behaviours by masterplan section

CLI: `python -m arena.controller <command> [--execute]`. Without `--execute`
every command is a dry run that prints the exact provider requests it would
make and writes a dry-run receipt; nothing paid happens. Commands:
`preflight`, `plan`, `canary --model <key>`, `run --model <key>`, `status`,
`pause`, `resume`, `drain`, `freeze --model <key>`, `cleanup-verify`, `cost`.

- Queue: sqlite `queue/campaign.sqlite` (WAL), tables `jobs`, `shards`,
  `workers`, `pods`, `heartbeats`; idempotent on `inference_job_id` (§2).
- Shards (MP §15.6) sized from `model_registry.json.shard_size_hint`; scheduler
  (MP §35) starts the slowest model's shards first, assigns to the healthy
  worker with the earliest predicted finish; straggler diagnosis (MP §36),
  hedging default off.
- Per-worker concurrency from `model_registry.json.concurrency_policy`;
  `mineru_vlm` is hard-coded to 1 and scaling is replicas only (MP §14).
- Heartbeat monitor (MP §15.4), dynamic stall threshold from canary p95
  (MP §15.5), retry table (MP §15.9) as data in `arena/controller/retry_policy.py`,
  circuit breaker (MP §15.10), idle killer (MP §15.11), max pod lifetime
  (MP §15.12, default 6h), budget watchdog with soft/hard caps from
  `arena.constants` (MP §15.13: soft ⇒ no new replicas; hard ⇒ pause queue and
  drain, never kill mid-page), cleanup verification by re-reading the provider
  until zero pods (MP §15.14).
- Canary (MP §17–18): runs `canary_selection.json` pages, writes
  `runs/<model_key>/canary/` and `receipts/canary-<model_key>.json` with p50/p90/
  p95, VRAM, projected GPU-hours/cost/wall-time using the catalog price
  snapshot; PASS/FAIL on runtime correctness only.
- Provider: `arena/provider/runpod_pods.py` against REST v2
  (`https://api.runpod.io/v2`, OpenAPI saved at the orchestrator scratchpad
  `runpod_openapi_v2.json`; pods `POST /v2/pods`, `GET/PATCH/DELETE /v2/pods/{id}`,
  `POST /v2/pods/{id}/action`, `GET /v2/pods/{id}/logs`, `GET /v2/catalog/gpus`,
  `GET /v2/billing/pods`). Bearer key from `arena/provider/secrets.py`, which
  reads label `Runpod_B` (fallback env `RUNPOD_API_KEY`) from
  `D:\Github_API.txt` and never returns it into any serializable structure.
  Price snapshot saved to `receipts/provider_receipts/catalog-<ts>.json` before
  each provisioning decision (MP §13.2).
- Transport: `arena/provider/r2.py` (boto3 S3 client against Cloudflare R2,
  credentials from labels `Access Key ID` / `Secret Access Key` under the
  `Cloudflare R2` block of the same file, account endpoint from the file's
  jurisdiction line). Bucket name `tavonel-arena-20260903`. Objects: the worker
  bundle, runtime bundles, optional shard input tarballs. Workers receive
  time-limited presigned GET URLs (never account credentials). `preflight`
  only checks bucket access in this phase; bucket creation waits for the
  orchestrator's go.
- Pod env passed at creation: `ARENA_WORKER_TOKEN`, `ARENA_MODEL_KEY`,
  `ARENA_MODEL_REVISION`, `ARENA_RUNTIME_MODE`, `ARENA_IMAGE_DIGEST`,
  `ARENA_BUNDLE_URL` (presigned, bootstrap mode only), `ARENA_CAMPAIGN_ID`.
  Never `HF_TOKEN` unless a model repo is gated (none of the 11 are expected
  to be) — pod env is readable through the provider API.

## 6. Runtimes (C1/C2/C3)

Per `runtimes/<model_key>/`:

- `runtime.json` — validated by `arena/core/schemas/runtime.schema.json`
  (A1 writes the schema from this list): `model_key, display_name, model_repo,
  model_revision (exact commit sha, resolved from the official HF/GitHub API and
  cross-checked with benchmark/v6/candidate-registry.yaml where present),
  official_runtime (vllm|transformers|paddle|mineru_cli|custom), runtime_version,
  base_image (name@sha256 digest), gpu_min_vram_gb, gpu_pool_priority[],
  max_concurrency_per_worker, shard_size_hint, per_page_timeout_seconds,
  prompt_id, inference_config (object), weights_strategy, runtime_mode_allowed,
  official_source_urls[], license {id, url, status}, notes`.
- `adapter.py` — implements `arena.worker.adapter_api.ArenaModelAdapter` using
  the model's OFFICIAL inference path (MP §6.2: official prompt, resolution,
  max tokens, batch size, runtime). Heavy imports happen inside `load()`, never
  at module import, so tests can import the module on a CPU box.
- `canonical.py` — `canonicalize(raw) -> CanonicalOutput`; deterministic; never
  adds content; flags `lossy=True` when something could not be represented.
- `Dockerfile` — build context is the namespace root
  (`research/model_arena_20260903/`), so `COPY arena/ /opt/arena/arena/` and
  `COPY runtimes/<model_key>/ /opt/arena/runtime/`. Pin everything: base image
  by digest, pip packages by `==`, model weights by revision with a sha256 check
  of the largest weight file. Entry point runs `python -m arena.worker.server`.
  No `pip install -U` anywhere. Weights either baked (`hf download --revision`)
  or fetched at boot from `/workspace` cache with a revision check — state
  which in `runtime.json.weights_strategy`.
- `bootstrap.sh` — OPTIONAL: canary-only path that starts from the official base
  image, downloads the worker bundle from `$ARENA_BUNDLE_URL`, pins the same
  pip versions and pulls weights into `/workspace/arena/weights/<model_key>`.
  Every version installed is recorded into `/opt/arena/bootstrap-receipt.txt`.
- `README.md` — official sources with revisions, what the canary must confirm,
  known incidents (e.g. MinerU VLM tensor-shape failures at concurrency > 1,
  OvisOCR2 historical discrepancy — MP §4).
- `tests/runtimes/test_<model_key>.py` — adapter unit tests with a fake
  backend (no GPU, no network), canonicalization fixtures (at least: heading,
  table, formula, empty output, truncated output), `runtime.json` schema check.

## 7. Opus lane (D) — `arena/opus/`

- Runner CLI `python -m arena.opus <preflight|canary|run|status|resume>`.
- One fresh `claude -p` process per page (MP §21.6). Base command from MP §21.4,
  re-verified against `claude --help` on the installed Claude Code 2.1.252:
  `--model opus --output-format json --no-session-persistence --tools Read
  --allowedTools Read --permission-mode dontAsk --effort high
  --disable-slash-commands`. `--bare` is forbidden (MP §21.3).
- Environment passed to the child: a scrubbed copy — remove `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN`, every `CLAUDE_CODE_*` and `CLAUDECODE` variable (the
  runner is launched from inside a Claude Code session during qualification, and
  the nesting guard must not change the child's behaviour); keep `PATH`, `HOME`,
  `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`, `SystemRoot`.
- Prompt = `prompt_registry/opus5_transcription_v1.txt` + one line naming the
  absolute PNG path. Prompt sha256 in every receipt.
- Receipt (MP §22): the full JSON payload saved verbatim to
  `runs/opus5_subscription/raw/<case_key>.claude.json`; page receipt per §3.1
  with `runtime_mode: "subscription"`, `actual_marginal_api_cost: "N/A"`,
  `subscription_included_usage: true`, `api_equivalent_list_price_usd` computed
  from `usage` and the list price recorded in `arena/opus/price_snapshot.json`
  (source URL + captured_at). Never `$0/page`.
- Image handling caveat recorded in every receipt (MP §21.10): original
  dimensions, bytes, sha256, and `surface: "claude-code-read-tool"`.
- Limits (MP §21.8): detect `SUBSCRIPTION_LIMIT | RATE_LIMIT |
  TEMPORARY_CAPACITY` from `is_error`, exit code, stderr and result text;
  on detection: pause the queue, checkpoint `runs/opus5_subscription/checkpoint.json`,
  record the reset time if the message carries one, and exit 75. No fallback,
  no model downgrade, no API auto-switch. If the reported model in the JSON
  payload is not an Opus 5 model id, the page is `FAILED/UNKNOWN` with
  `error_message: "unexpected model"` and the runner stops.
- Worker ramp (MP §21.7): 2 → 50-page canary → 4 → 6, configurable, never more.
- Qualification in this phase: the lane MAY run up to 3 real pages from
  `canary_selection.json` to prove the command works (this consumes the
  founder's subscription allowance, which the masterplan authorizes for the
  canary). Record the outcome; do not run more.

## 8. TAVONEL replay (E1), scoring (E2), reports (E3)

- E1 reads ONLY `frozen_outputs/`, `runs/*/raw`, `runs/*/canonical`,
  `runs/*/receipts`, `source_manifest.jsonl` and the page PNGs. Signals (MP §26,
  §12.2) are computed per `(model_key, case_key)` into
  `tavonel/signals/<model_key>/<case_key>.json`. Variants A–E (MP §25) are
  policies in `arena/tavonel/policies.py`; each policy is pure and versioned
  (`policy_id`, `policy_sha256`). Replay writes route decisions (§3.5), a
  composite output manifest per variant
  (`tavonel/adaptive_replay/<variant>/manifest.jsonl` pointing at the chosen
  frozen output per case), the recovery plan (§3.6) for cases that need new
  inference, counterfactual cost (MP §23.1) and the disagreement matrix
  (MP §27) at `tavonel/disagreement/pairs.jsonl`. Oracle outputs carry
  `ORACLE_POST_HOC_NOT_DEPLOYABLE` in every file name and record.
  Thresholds are parameters with `calibrated: false`; nothing here reads
  `research/tavonel_eval_v2` or `research/tavonel_recovery_eval_v1` state.
- E2: `python -m arena.scoring qa --model <key>` (MP §44 gate, must be green
  before evaluators run), `python -m arena.scoring score --model <key>
  --benchmark <b> --lane main|historical`. Evaluators run from the pinned
  clones under `benchmark/cache/` (checkout the pinned revision into a
  campaign-owned worktree copy under `scores/_evaluators/<benchmark>/<rev>/`,
  never mutate `benchmark/cache`). Evaluator input adapters convert canonical
  markdown into each evaluator's expected layout; the previous campaign's
  `benchmark/runpod_eval/evaluate_*_official.py` and `public_core_merge.py`
  show the layouts. GT paths come from `evaluator_registry.json.gt_paths` and
  are touched only by this lane.
- E3: generators for every file in MP §29 under `reports/` and `evidence/`,
  fed only from `scores/`, `runs/*/receipts`, `cost/`, `failures/`,
  `tavonel/`, `model_registry.json`, `evaluator_registry.json`. Tables keep
  benchmarks separate (MP §28); Pareto frontier over `$/1,000 pages` and
  `GPU seconds/page`. `executive_summary_ko.md` is a template whose `[RESULT]`
  slots are filled only from data and left as `[RESULT]` when absent.
  `FINAL_EVIDENCE_MANIFEST.json` lists every artifact with sha256.

## 9. Engineering rules for every lane

- Typed Python (`from __future__ import annotations`, no `Any` leaks in public
  signatures where avoidable), `ruff` and `mypy --strict` clean for the
  namespace, tests for the failure path as well as the happy path.
- Secrets: read only through `arena/provider/secrets.py`; never logged,
  never serialized, never placed in a URL, never in a test fixture. Receipts
  are validated by a `secret-free` check (reject strings that look like
  `rpa_`, `hf_`, `sk-`, `ghp_`, `AKIA`, long base64 tokens).
- Network: only lanes A3, A4, D, F and B1's `preflight` may read the network
  (public model cards, GitHub, HF API, RunPod read endpoints, R2 bucket
  access check). No lane downloads model weights in this phase.
- Every CLI defaults to dry run; `--execute` is the only way to spend.
- Windows host: use `pathlib`, `encoding="utf-8"` everywhere, `os.replace`
  for atomic renames, and long-path-safe file names (case_key only).
- Do not invent data: a missing metric is `null` with a reason, never 0.

## 10. Lane report format

The final message of every lane is machine-consumed. First line:
`상태: <NOT_STARTED|PARTIAL|IMPLEMENTED|TESTED|PROVEN|BLOCKED>` then sections
`FILES` (paths written), `TESTS` (exact commands run and their pass/fail
counts), `INTERFACE_CHANGES_PROPOSED` (or `none`), `OPEN_QUESTIONS`,
`EVIDENCE` (receipts produced, if any). `TESTED` requires the test command
output in this session; `PROVEN` requires evidence beyond tests.

---

## 11. Integration pass — 2026-09-03 (binding addendum after lane delivery)

All 14 lanes delivered. This section records the cross-lane decisions of the
integration pass. Where it conflicts with §0–§10, this section wins. Path
ownership from §1 still holds: a fix lane edits only its own paths.

### 11.1 Decisions

- **D1 ParseBench evaluator pin.** Main lane `main_pin` =
  `45298128406f5bcc3942ccf97c618af15289770c` (upstream head on 2026-09-03).
  Historical lane keeps `1d460294b3b9c57fb3fa944dc17a9c044c24d1e5`. OmniDocBench
  `193627ae…` and olmOCR-bench `cfa88c1e…` unchanged. `frozen` flips to `true`
  in the Phase 0 freeze step, not in this pass.
- **D2 Bootstrap-mode entrypoint (verified).** RunPod REST v2 `CreatePodRequest`
  has only `args` ("arguments passed to the container entrypoint"); it cannot
  override an image ENTRYPOINT, so bootstrap on `vllm/vllm-openai` and similar
  images is impossible through v2. RunPod REST **v1** (`https://rest.runpod.io/v1`,
  deprecated but live — verified 2026-09-03 with the campaign key:
  `GET /v1/pods` → 200, 5 pods, records carry `dockerEntrypoint` and
  `dockerStartCmd`) accepts `dockerEntrypoint: string[]` and
  `dockerStartCmd: string[]` on `PodCreateInput`. Therefore:
  - bootstrap-mode pods are created through REST v1 with
    `dockerEntrypoint: ["/bin/bash", "-lc"]` and `dockerStartCmd: ["<script>"]`
    where `<script>` is `arena.worker.bundle.render_bootstrap(model_key)`
    (B2 owns the template; B1 calls it verbatim);
  - baked-mode pods keep REST v2 (the image ENTRYPOINT is the arena worker);
  - the pod ledger records `provider_api_version` (`"v1"|"v2"`) and the
    redacted create payload;
  - v1 needs the same bearer; both APIs may be used for read/stop/delete.
    Cloudflare in front of v2 returns 403 error 1010 to the Python `urllib`
    default User-Agent — every client sets an explicit `User-Agent`.
- **D3 Semantic error class propagation.** `RawOutput` (adapter_api.py) now has
  `semantic_error_class: str | None = None` (values `OUTPUT_EMPTY`,
  `OUTPUT_TRUNCATED`, `OUTPUT_REPETITION`, `OUTPUT_MALFORMED`). The worker
  server fills response field `semantic_error_class` (nullable, new in
  `worker-run-response.schema.json`) from that field, else from a warning with
  the exact prefix `arena.semantic_error_class=` (C3 convention), else `null`.
  The controller copies it into the page receipt. Page receipts gain
  `semantic_error_class` (nullable enum) and `recovery_job_id` (nullable
  string). `status` stays `SUCCESS` when a raw output exists (MP §41: an empty
  output is SUCCESS + `OUTPUT_EMPTY`).
- **D4 Extension-open records.** `page-receipt`, `heartbeat`,
  `model-registry-record`, `evaluator-registry-record` set
  `additionalProperties: true`. Required core keys stay required; no consumer
  may require a non-core key. Heartbeat gains optional `ts` (ISO-8601 UTC) and
  `gpu_metrics_unavailable_reason` (nullable string); `gpu_util` and
  `vram_used` become nullable; `state` enum = `WORKER_STATES` from
  `arena.constants`.
- **D5 runtime.json.** Adds `gpu_count_min` (integer ≥ 1, default 1;
  `infinity_parser2_pro` = 2). `notes` is a string or an array of strings.
  `license.status` enum is the union actually used by A3 and C1–C3 (read the
  files; at least `verified`, `unverified`, `review_required`, `blocked`,
  `none_found`, `not_reusable`). `base_image` MUST be digest-pinned
  (`…@sha256:<64 hex>`; a `name:tag@sha256:…` form is allowed).
  `paddleocr_vl_1_6` must repoint to a tag that exists on the Baidu registry
  and pin its digest (resolve with `build/registry_check.py`, which already
  handles the Harbor token flow); `hpd_parsing` pins
  `sha256:1493923dd6b7e368c56…` (full digest in `build/build_plan.json`).
  `model-registry-record` allows `repo`, `runtime_version`, `gpu_min_vram_gb`
  to be `null`, adds `runtime_type` values `paddle`, `pipeline`, `mineru_cli`,
  `custom`, and `gpu_count_min`.
- **D6 Authorization receipts replace the build-phase refusal.** Money-spending
  commands check `receipts/authorizations/*.json` (schema
  `arena/core/schemas/authorization-receipt.schema.json`, A1):

      {"schema": "arena/authorization-receipt/v1", "campaign_id": "...",
       "phase": "phase1_canary" | "phase2_full_run" | "phase3_opus_full_run" | "builder_pod",
       "authorized_by": "founder" | "orchestrator-on-founder-instruction",
       "authorized_at": "<ISO-8601 UTC>", "expires_at": "<ISO-8601 UTC>" | null,
       "max_usd": <number>, "model_keys": "*" | ["<model_key>", ...],
       "statement": "<free text quoting the instruction>"}

  `canary --execute <model>` requires an unexpired `phase1_canary` receipt
  covering the model whose `max_usd` ≥ the projected canary cost of that model
  (price snapshot × estimated pod hours incl. bootstrap); `run --execute`
  requires `phase2_full_run` **and** (baked image or a waiver under
  `receipts/waivers/`); the Opus full run requires `phase3_opus_full_run`.
  Missing/expired/insufficient receipt → `EXIT_BLOCKED` (3) with the reason.
  The receipt file path and sha256 are recorded in the pod ledger and the
  canary receipt.
- **D7 License gate.** A model whose registry `license.status` is `blocked`
  (Infinity-Parser2-Pro) is refused by `--execute` unless
  `receipts/waivers/license-<model_key>.json` exists (founder decision).
- **D8 Hash convention (byte-exact).** `raw_output_sha256 =
  sha256(raw_text.encode("utf-8"))`, `canonical_output_sha256 =
  sha256(markdown.encode("utf-8"))`; the frozen files contain exactly those
  bytes (UTF-8, no BOM, no added newline). E1/E2 hash file bytes and compare.
- **D9 GPU pool validation.** Every name in `gpu_pool_priority` is validated
  against the provider catalog snapshot at preflight and plan time; an unknown
  name fails preflight for that model with the closest catalog names listed.
- **D10 Pod lifetime.** Canary pods: max 2 h. Full-run pods: 6 h (§15.11).
- **D11 Budget accounting.** `spent_usd` = campaign-tagged pods from the ledger
  and provider listing; preflight additionally prints account-wide spend for
  the last 24 h from the billing endpoint as an information line (not a gate).
- **D12 Images and weights.** Baked images stay private GHCR packages. F
  documents the storage/bandwidth implication of 11 images (private GHCR
  quota vs paid vs public) and the alternative of weights on a RunPod network
  volume. No Dockerfile changes in this pass; founder decides.
- **D13 Stall threshold.** Per model, stall threshold ≥ that runtime's
  `per_page_timeout_seconds`; a worker past it is STALLED and terminated.

### 11.2 Fix-lane paths (this pass)

| lane | writes only | must not touch |
|---|---|---|
| A1 | `arena/core/**`, `tests/core/**` | any other lane's tests |
| B1 | `arena/controller/**`, `arena/provider/**`, `tests/controller/**`, `tests/provider/**` | `arena/worker/**` |
| B2 | `arena/worker/**` except `adapter_api.py`, `tests/worker/**` | `arena/controller/**` |
| C1 | `runtimes/{paddleocr_vl_1_6,hpd_parsing,mineru_pipeline,mineru_vlm}/**`, `tests/runtimes/<those>/**` | other runtimes |
| C2 | `runtimes/{deepseek_ocr2,ovisocr2,unlimited_ocr}/**`, their tests | other runtimes |
| C3 | `runtimes/{infinity_parser2_pro,monkeyocrv2_b,olmocr2,glm_ocr}/**`, their tests | other runtimes |
| F  | `build/**`, `tests/build/**` | runtimes |

Every fix lane: no git commands, no `--execute`, no paid side effect, secrets
only through `arena/provider/secrets.py`, and run its own tests plus
`ruff check` on its paths before reporting.

### 11.3 Bootstrap-mode filesystem and hand-off (extends D2; binding for B1, B2, C1–C3)

Today B2's bundle template expects to run *from inside* the extracted bundle
and delegates to `runtimes/<key>/bootstrap.sh`, while the C-lane scripts
re-download the bundle themselves and `exec /opt/arena/runtime/entrypoint.sh`.
That is two competing conventions. The single convention from now on:

1. **Start command** (B1 renders from
   `arena.worker.bundle.render_start_cmd(model_key, bundle_sha256)`; B2 owns
   the text). It runs under `dockerEntrypoint: ["/bin/bash", "-lc"]` and does
   exactly: `set -euo pipefail; mkdir -p /opt/arena; curl -fsSL --retry 5
   --max-time 900 "$ARENA_BUNDLE_URL" -o /tmp/arena-bundle.tar.gz; echo
   "<bundle_sha256>  /tmp/arena-bundle.tar.gz" | sha256sum -c -; tar -xzf
   /tmp/arena-bundle.tar.gz -C /opt/arena; exec bash /opt/arena/bootstrap.sh`.
   The bundle sha256 is pinned into the command, so a tampered or wrong bundle
   never starts. `ARENA_BUNDLE_URL` (presigned GET, at least 2 h validity) and
   the other `ARENA_*` variables come from the pod env (B1 `PodSpec.env()`).
2. **Bundle root `/opt/arena`** holds `bootstrap.sh` (B2 template, rendered
   per model), `bundle-manifest.json`, the `arena/` package (constants, core,
   worker) and `runtimes/<model_key>/` (adapter.py, canonical.py,
   runtime.json, bootstrap.sh, entrypoint.sh, fetch_weights.py, and whatever
   else that runtime directory contains). Nothing else from the repo.
3. **B2 template** verifies the manifest, creates the symlink
   `/opt/arena/runtime -> /opt/arena/runtimes/<model_key>` (so runtime scripts
   use the same `/opt/arena/runtime/...` paths in baked and bootstrap mode),
   exports `PYTHONPATH=/opt/arena` and `ARENA_RUNTIME_DIR=/opt/arena/runtime`,
   then `exec bash /opt/arena/runtime/bootstrap.sh` when that file exists;
   otherwise it writes `/opt/arena/bootstrap-receipt.txt` and `exec`s the
   worker server.
4. **Runtime `bootstrap.sh`** (C lanes) never downloads the bundle and never
   requires `ARENA_BUNDLE_URL`. It installs exactly the pinned versions the
   Dockerfile installs, fetches the pinned weights (revision + sha256 check,
   public repos, no token), writes `/opt/arena/bootstrap-receipt.txt`
   (campaign, model_key, base image, versions, `pip freeze` sha256) and
   `/opt/arena/bootstrap-pip-freeze.txt`, then
   `exec /opt/arena/runtime/entrypoint.sh`.
5. **Runtime `entrypoint.sh`** starts the model server if the runtime needs
   one (vLLM etc.), waits until it answers, then
   `exec python3 -m arena.worker.server` (or the image's interpreter). The
   worker server locates `adapter.py`, `canonical.py` and `runtime.json`
   through `ARENA_RUNTIME_DIR` (default `/opt/arena/runtime`); B2 makes that
   the only lookup rule.
6. **Baked images** copy `runtimes/<model_key>/` to `/opt/arena/runtime/` and
   the `arena/` package to `/opt/arena/arena/`, set
   `ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]`, and are created through
   REST v2 with no `args`.

### 11.4 Shared module for authorization receipts

`arena/core/authorizations.py` (written by the orchestrator; A1 tests it,
B1 calls it) exposes:

    class AuthorizationError(ValueError)
    @dataclass(frozen=True) class AuthorizationReceipt:
        path: Path; sha256: str; campaign_id: str; phase: str; authorized_by: str
        authorized_at: datetime; expires_at: datetime | None; max_usd: float
        model_keys: tuple[str, ...] | None   # None means "*"
        statement: str
        def covers(self, *, phase: str, model_key: str | None, now: datetime) -> bool
        def to_record(self) -> dict[str, Any]
    def parse_authorization(path: Path, *, campaign_id: str) -> AuthorizationReceipt
    def load_authorizations(directory: Path, *, campaign_id: str) -> tuple[AuthorizationReceipt, ...]
        # every *.json in the directory must validate; any invalid file raises (fail closed)
    def select_authorization(receipts, *, phase, model_key, now, required_usd) -> AuthorizationReceipt | None
        # unexpired, covers phase+model, max_usd >= required_usd; largest max_usd wins

Schema: `arena/core/schemas/authorization-receipt.schema.json`
(`schema` const `tavonel.arena.authorization-receipt.v1`). Receipts live under
`receipts/authorizations/`.

### 11.5 Second integration pass — 2026-09-03 (after the adversarial review; binding)

Two read-only critics reviewed the namespace after the first pass and both
returned NO-GO for Phase 1. The decisive finding: **`canary --execute`
provisions a pod and returns; nothing dispatches pages, evaluates, receipts,
or terminates the pod.** The decisions below close that and the seams around
it. Where they conflict with §2–§11.4, this section wins.

- **D14 Source manifest field names (A2 owns; B1 reads).** The manifest keeps
  A2's names. The controller maps them, in one place, with no aliases:
  `source_sha256` (job-id input) := `input_png_sha256` — the bytes the model
  sees; `benchmark_revision` := `dataset_revision`; `image_path` :=
  `input_relative_path`. `original_source_sha256` is provenance only and never
  enters the job id. B1's reader fails closed if any of the three is missing.
- **D15 Digest and prompt sources for a canary.** A bootstrap pod's
  `runtime_image_digest` is `bootstrap:<bundle sha256>` (from
  `arena.core.ids.bootstrap_image_digest`), derived from the bundle receipt
  (D21), never from the registry, never the base image. The registry's
  `container_digest` stays `null` with its reason until images are baked, and
  the registry reader must not require it for a bootstrap canary. The base
  image goes into `image_name` and into the receipt as `base_image` only.
- **D16 Revision ownership.** `runtimes/<key>/runtime.json` owns
  `model_repo`, `model_revision`, the runtime repository/revision and
  `prompt_id`. `model_registry.json` is a derived copy: the registry
  resolver regenerates those fields from runtime.json, and preflight fails
  when they disagree for any model. The two disagreements found
  (`monkeyocrv2_b` revision, `mineru_pipeline` repo) are resolved by copying
  runtime.json's values, unless the runtime lane finds runtime.json wrong.
  `infinity_parser2_pro` licence status in the registry becomes `blocked`
  (runtime.json is right; the founder has not cleared it).
- **D17 Prompt registry is keyed by the runtime.json `prompt_id`.** For every
  model, `prompt_registry/<prompt_id>.txt` must exist with the exact text the
  adapter sends (or, when the official toolkit builds the prompt at run time,
  the text that builder produces for this revision), and
  `prompt_registry/sha256.json` maps `prompt_id` → sha256. A4's
  `<model_key>_official_v1` entries are renamed or re-pointed so each
  runtime.json `prompt_id` resolves. The registry copies `prompt_sha256` per
  model from that file. The bundle carries `prompt_registry/` and every baked
  Dockerfile copies it to `/opt/arena/prompt_registry/`. The worker resolves
  `ARENA_PROMPT_FILE` (default `/opt/arena/prompt_registry/<prompt_id>.txt`
  from runtime.json), fails closed when it is missing, and refuses a run whose
  request `prompt_sha256` differs from the file's hash. Adapters that build
  the prompt through the official toolkit compare the built text's sha256
  with `AdapterConfig.prompt_sha256` and fail closed on mismatch; adapters that
  take the prompt as text use `AdapterConfig.prompt_text` and refuse an empty
  one.
- **D18 Start command and template are self-sufficient.** Some official base
  images (nvidia/cuda for `unlimited_ocr`) ship neither `curl` nor `python3`.
  The start command probes `curl` (falls back to `wget`, and as a last resort
  `apt-get install -y curl ca-certificates` when `apt-get` exists); the B2
  template resolves `python3`, then `python`, and otherwise installs
  `python3` the same way, recording what it installed in the bootstrap
  receipt. The pinned sha256 check stays before extraction.
- **D19 Model-server readiness and process ownership.** A runtime
  `entrypoint.sh` that starts a model server (vLLM, paddlex, …) polls its
  health endpoint until it answers, with a deadline no shorter than the
  model's load time (≥ 20 min for the 7B-class models) and a hard failure on
  timeout; it then starts the worker as a child, `wait`s on it, and a trap
  stops the server on any exit. It does not `exec` the worker (that
  discards the trap and orphans the server). This amends 11.3(5). The worker's
  own warm-up gets a bounded retry on connection refused.
- **D20 Canary driver and termination (B1).** `canary --execute` runs the
  whole Phase 1 for one model, in one process: bundle receipt check →
  authorization gate → provision (v1) → poll readiness (bootstrap deadline
  45 min, later configurable) → dispatch the selected pages one at a time with
  the runtime's per-page timeout → page receipts → `evaluate_canary` →
  schema-valid `receipts/canary-<model>.json` and
  `receipts/registry-updates/<model>.json` → drain → **stop and delete the pod
  in a `finally` block**, then re-list through v1 and v2 until the pod is gone.
  A lifetime watchdog thread stops and deletes the pod at 2 h regardless. A
  driver crash still returns the pod (the `finally`). The worker exits by
  itself when `ARENA_MAX_POD_AGE_HOURS` elapses (B2). `cleanup-verify
  --execute` lists through v1 and v2, matches on campaign env **or** the
  `arena-…-20260903v1` name prefix, deletes every match, and counts an EXITED
  pod as not cleaned up until it is gone from both listings.
- **D21 Bundle command (B1).** `python -m arena.controller bundle --model <k>
  [--execute]` builds and verifies the bundle, uploads it to
  `bundles/<campaign>/<model_key>/arena-bundle.tar.gz`, HEADs the object and
  compares its sha256 checksum (or re-downloads and hashes when the
  checksum header is absent) with the built file, refuses on mismatch, and
  writes `receipts/bundles/<model_key>.json` (schema
  `tavonel.arena.bundle-publish.v1`: bundle sha256, size, file count,
  manifest sha256, r2 key, uploaded_at). `canary` reads the sha256 from that
  receipt; `--bundle-sha256` on argv is accepted only when it equals the
  receipt. Bundle URLs in receipts are reduced to `bucket/key`.
- **D22 Cumulative budget.** `authorize()` sums the ceilings of every earlier
  provisioning line in `cost/pod_provisioning.jsonl` plus actuals in the pod
  ledger and refuses when that sum plus this action's `required_usd` crosses
  `BUDGET_SOFT_CAP_USD`; nothing crosses `BUDGET_HARD_CAP_USD`. The driver
  timer runs `BudgetWatchdog`.
- **D23 Price snapshot freshness.** Under `--execute` the catalog is refreshed
  (live, receipted) before pricing; a snapshot older than 6 h is refused for
  pricing in a dry run and the age is recorded in the gate receipt.
- **D24 Provider hygiene.** `volume_gb` and a non-default container disk are
  priced into `required_usd`. A pod record without `env` is a protocol error,
  and campaign matching also accepts the name prefix. An ambiguous create
  (5xx, timeout) re-lists by name and campaign before propagating; a
  provisional ledger line naming the pod is written before the POST.
- **D25 Runtime mode and capability checks.** The computed runtime mode must
  be in `runtime_mode_allowed`, naming the file that forbids it. `validate_pool`
  rejects a pool whose catalog `memory_gb × gpu_count_min < gpu_min_vram_gb`.
  A compute-capability floor is deferred: it needs a sourced table, not a
  name heuristic; the canary receipt keeps the device's reported capability.
- **D26 Canary receipt conformance.** `write_canary_receipt` validates against
  `canary-receipt.schema.json` through `arena.core.receipts.validate` before
  writing and records the authorization receipt path + sha256 and the pod
  ledger reference. B1 completes the fields; A1 changes the schema only where
  a field is genuinely missing from the contract.
- **D27 Opus lane.** `runtime_image_digest` grammar gains
  `subscription:<label>` (`[A-Za-z0-9._-]+`), used by the Opus lane as
  `subscription:claude-code-<cli version>-<model id>`. The Opus lane derives
  every id through `arena.core.ids` (shard width 4) and deletes its private
  implementation. A fallback page selection is refused once
  `canary_selection.json` exists; the Opus canary is re-run over the frozen
  `opus_canary` block (50 pages) with fresh receipts.
- **D28 Pod ledger.** On stop/delete the driver writes the §3.3 record to
  `cost/pod_ledger.jsonl` from the queue's pod row plus provider values
  (start/stop times, billed seconds, price snapshot sha256, runtime mode,
  wasted GPU seconds); `cost` reads it. `cost/pod_provisioning.jsonl` stays as
  the create-time record.
- **D29 Shell.** `dockerEntrypoint` is `["/bin/bash", "-c"]` (no login shell;
  nothing needs profile sourcing and it can reset the image PATH). Amends
  11.3(1) and D2.
- **D30 Test hygiene.** Shell-syntax tests resolve bash by absolute path
  (`shutil.which` plus the Git-for-Windows location) and `xfail` rather than
  skip when no usable bash exists.
- **D31 Evaluator provenance.** The olmOCR-bench evaluator repository recorded
  as `jina-ai/olmocr-bench` must be traced: the registry lane verifies what
  the local clone's remote and the masterplan name, records a resolution
  receipt, and repoints to `allenai/olmocr` (the `olmocr/bench` tree) if that
  is the upstream, keeping the historical pin only if it exists there.
- **D32 Authorization receipt validity.** `covers()` also requires
  `authorized_at <= now`. The stale `"schema": "arena/authorization-receipt/v1"`
  string in D6 is superseded by §11.4's `tavonel.arena.authorization-receipt.v1`.
- **D33 Runtime lane details.** `glm_ocr/bootstrap.sh` gains the
  `ARENA_MODEL_REVISION` guard the others have. Every entrypoint's readiness
  poll and process ownership follow D19. Dockerfiles `COPY prompt_registry/
  /opt/arena/prompt_registry/` (D17).

Fix-lane paths for this pass are those of §11.2 plus: **R** (registries) owns
`arena/registry/**`, `model_registry.json`, `evaluator_registry.json`,
`prompt_registry/**`, `tests/registry/**`, `tests/prompt_registry/**`
(A3 + A4 merged); **D** owns `arena/opus/**`, `tests/opus/**`,
`runs/opus5_subscription/**`, `receipts/opus-*.json`. A2 is unchanged.
- **D34 Prompt kinds.** `runtime.json` gains `prompt_kind`: `text` (the
  adapter sends `AdapterConfig.prompt_text`, which must be non-empty and
  equal the registry file), `toolkit` (the official toolkit builds the prompt
  at run time; the adapter hashes the built text and fails closed when it
  differs from `AdapterConfig.prompt_sha256`), or `none` (a pipeline with no
  prompt; the registry file is empty and its sha256 is the hash of the empty
  string). The worker enforces the rule for the declared kind.

### 11.6 Third pass — 2026-09-03 20:15 KST (after the second pass landed partially)

Lanes B2, A1, R, D, C1, C2 delivered the second pass; B1, C3 and F were cut
off by a session limit and run now. Decisions raised by the delivered lanes:

- **D35 sha256 spelling.** Bundle receipts store `bundle_sha256` as bare
  64-hex (what the on-pod `sha256sum -c` line needs). Callers of
  `arena.core.ids.bootstrap_image_digest` prepend `sha256:`; `render_start_cmd`
  accepts either. Receipts may carry either spelling where the schema says so;
  nothing compares the two spellings as strings without normalising.
- **D36 Infinity-Parser2-Pro.** `runtime_mode_allowed` is `["baked"]` and
  `weights_strategy` is `baked` (the candidate note is right: a 70 GB boot
  download inside a canary pod is the stall risk §15.1 exists to prevent).
  Its canary waits for the baked image and the licence decision.
- **D37 Canary receipt for the subscription lane.** `gpu_type` and `pod_id`
  are nullable when `runtime_mode == "subscription"` and required otherwise
  (cross-field rule, like page receipts). `criteria` is the list of masterplan
  §17 criteria as named objects; the schema enumerates the criterion ids and
  requires all of them, not a bare `minItems`. The Opus lane then re-emits its
  50-page canary receipt in the shared schema from the per-page receipts (no
  new inference).
- **D38 Page receipt image dimensions.** `image_width`/`image_height` may be
  null only when `status != SUCCESS` and the image could not be read; a
  SUCCESS receipt still requires them.
- **D39 Opus full-run page source.** `run` for the Opus lane reads its pages
  from `source_manifest.jsonl` (all 5,132), not from the canary selection;
  wired when Phase 3 is authorized, not now.
- **D40 Opus canary retry.** The one INFRA_CAPACITY page is not retried in the
  canary; the receipt with `attempt: 1` stays as the record of the capacity
  event. Retries with incremented `attempt` belong to the Full Run retry table.
- **§3.9 superseded.** The prompt registry holds one `<prompt_id>.txt` per
  runtime.json `prompt_id` (plus `opus5_transcription_v1.txt`), `sha256.json`
  keyed by those ids with no null values, `model_specific_prompts.json` with
  `prompt_kind` and source, and a README mapping retired ids. For a toolkit
  runtime with a per-region prompt mapping (glm_ocr, monkeyocrv2_b) the file
  holds the §2 canonical JSON of the vendor mapping, and the D34 check is
  "the installed toolkit's mapping canonicalises to this sha256".
- **mineru_vlm** runs MinerU's default in-process engine (`transformers`),
  not a vLLM server; C1's reading stands and D19's exec path applies.
- **`AdapterConfig.prompt_sha256`** now exists (orchestrator edit,
  2026-09-03): the worker fills it; toolkit adapters compare against it.

### 11.7 Founder decisions of 2026-09-03 (final execution prompt; binding)

The founder's final execution prompt settled four questions that earlier
sections left open or decided the other way. Where they conflict with §11.5
or §11.6, this section wins.

- **D41 Infinity-Parser2-Pro is allowed (supersedes D16's `blocked` and
  D36's baked-only).** The official model card licenses the checkpoint
  Apache-2.0; `runtimes/infinity_parser2_pro/runtime.json` now carries
  `license.status = "verified"` with the HF revision, the hashed licence text
  and its URL, receipted at
  `receipts/registry-updates/license-infinity_parser2_pro.json`. Baked-only
  was an operational choice, not a licence fact: `runtime_mode_allowed` is
  `["baked", "bootstrap"]` and `weights_strategy` is `volume_cache`. A
  bootstrap canary passes `--volume-gb` so the weights are fetched once onto a
  network volume that the full run reuses. The model is not excluded from any
  benchmark on licence grounds; a low score is a result, not an exclusion.
- **D42 MinerU licence is recorded as what it is.** `mineru_pipeline` and
  `mineru_vlm` carry `license.name = "MinerU Open Source License"`,
  `spdx_base = "Apache-2.0"`, `additional_terms = true`, `status =
  "verified"`, the licence text hash at the pinned runtime revision and the
  attribution/commercial notes. Benchmark execution is allowed; the extra
  terms live in metadata and in the report's licence table, nowhere else.
  The registry vocabulary gains `verified`; `LicenseRef` gains the optional
  `name`, `spdx_base`, `additional_terms`, `text_sha256`, `source_url`,
  `notes` fields (all nullable; `runtime.schema.json` amended accordingly).
- **D43 PaddleOCR-VL 1.6 runs the official image without an overlay.** The
  premise behind the 3.6-image-plus-3.7-pip path was wrong: PaddleOCR
  v3.6.0 is the release that shipped PaddleOCR-VL-1.6 (release notes headline;
  `PaddleOCR-VL.en.md` at tag v3.6.0 defaults `pipeline_version` to v1.6);
  v3.7.0 is the PP-OCRv6 release. The runtime pins
  `paddlepaddle/paddleocr-vl:paddleocr3.6-nvidia-gpu@sha256:ad0b1f05…84db`
  (the same digest `latest-nvidia-gpu` resolved to on 2026-09-03), asserts
  the image carries paddleocr 3.6.0 / paddlex 3.6.1 and fails closed
  otherwise, and installs nothing but the documented genai-server extras.
  `runtime_revision` is the v3.6.0 commit. No 3.7-compatible VL image exists
  on the vendor registries (tag enumerations in `provenance.json`).
- **D44 Opus lane proves subscription auth.** The Opus preflight runs
  `claude auth status` in the scrubbed child environment and records only
  `logged_in`, `auth_method` and `api_provider` (never a token or key). It
  fails closed unless the method is `claude.ai` and the provider is
  `firstParty`. `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` stay forbidden
  in the parent shell and are scrubbed from the child. There is no Opus →
  Sonnet and no Opus → API fallback; a quota stop is exit 75 with a
  checkpoint and a later resume.
- **D45 Status vocabulary for reports.** Progress is reported only as
  `DESIGNED`, `UNIT_TESTED`, `PROVIDER_LIVE_READ`, `DRY_RUN_VALIDATED`,
  `RUNPOD_E2E_SMOKE`, `CANARY_EXECUTED`, `FULL_RUN_EXECUTED`,
  `OUTPUT_FROZEN`, `SCORED`, `REPORTED`, `CLEANED_UP`. `RUNPOD_E2E_SMOKE`
  requires the real pod id and name, GPU type, hourly price snapshot, model
  revision, runtime image digest, real bundle sha, model-ready timestamp,
  per-page runtime, raw and canonical output hashes, provider receipts,
  billed or estimated cost, the delete receipt and a post-delete inventory of
  zero arena pods. `CANARY_EXECUTED` and `FULL_RUN_EXECUTED` require real GPU
  inference. Nothing is called tested without it.
- **D46 Readiness wait reads container logs and fails fast (after pod
  92miysvw0wk4wq).** During the bootstrap wait the driver tails the pod's
  container log about every two minutes (v2 `GET /pods/{id}/logs`, bounded,
  secret-scrubbed per line) and fails readiness at once on `[arena] FATAL`,
  `[arena] model server exited`, `[arena] model server did not answer`, a
  server `Traceback`, or a second `start container for` line (RunPod restarts
  an exited start command, so a crashed model server otherwise becomes an
  invisible crash loop billed until the deadline). A pod that the provider
  no longer returns (404 twice in a row) fails as "pod gone" instead of
  polling the proxy to the deadline. Readiness progress is printed as it
  happens (state changes and a five-minute heartbeat with the last `[arena]`
  milestone). Provider `get_pod` receipts during the wait are thinned to the
  first read, every status change and every tenth unchanged read; the kept
  and suppressed counts are recorded in the driver receipt's
  `readiness.provider_reads`. The v1 pod record does not expose
  `gpu_count`/`gpu_type_id` for a running pod (all 20 reads of a running
  bootstrap pod showed 0/None), so no "never scheduled" heuristic exists.
- **D47 Runtimes fail before the server, and stay failed.** Every
  `bootstrap.sh` runs an architecture preflight after its installs and before
  any model server starts: the pinned framework versions are asserted and the
  framework must recognise the checkpoint's `model_type`/architecture
  (Transformers config mapping or `AutoConfig` on the weights directory,
  vLLM's model registry when vLLM serves, the toolkit's own resolver
  otherwise); it prints `[arena] architecture preflight PASS …` or exits 64
  with the reason, and the bootstrap receipt records it. Where the pinned
  base image ships a framework older than the model's documented floor and
  the vendor's own documented path installs a newer one, the runtime pins
  that version exactly (`pkg==X.Y.Z`, newest release inside both bounds, from
  PyPI metadata) in both `bootstrap.sh` and the Dockerfile; never `-U`, never
  a floating spec. When a model server exits or never answers within its
  D19 deadline, `entrypoint.sh` writes `/opt/arena/FATAL` (reason plus the
  last 200 server-log lines), prints `[arena] FATAL <reason>` and sleeps
  forever instead of exiting, so the failure is visible to D46 and the pod
  cannot restart-loop. Any runtime change re-publishes that model's bundle
  (`bundle --model <key> --execute`) before its next canary; a dry-run
  `bundle` overwrites the receipt with a dry-run record and the canary then
  refuses, by design.
- **D48 Host CUDA floor and pool walk (after pod 3xag0y00rgoj4n).** Every
  runtime that rents a GPU declares `min_cuda_version` in `runtime.json`,
  read from the pinned base image's own OCI config (`CUDA_VERSION`,
  `NVIDIA_REQUIRE_CUDA`) or its documented install index, never from the
  image name; the evidence sits in `provenance.json` (`cuda_floor`) or, for
  glm_ocr, in the runtime notes. The provision gate refuses a GPU runtime
  without the floor and names the file. The create payload sends
  `allowedCudaVersions` (REST v1 enum 11.8 … 13.0; v2 `gpu.allowedCudaVersions`
  for baked pods) as every listed version at or above the floor, so a host on
  an older driver is never selected (the 4090 host RunPod gave us ran 12.8
  under a cu129 image and GeForce refuses forward compatibility, CUDA error
  804). With the filter in place the driver walks `gpu_pool_priority` one GPU
  type per create request, receipting each refusal, and the provisioning line
  and ledger name the GPU that was actually created and the host's reported
  `cudaVersion`. D24's ambiguous-create rule is unchanged. The registry does
  not copy `min_cuda_version`: the controller reads it from runtime.json.
- **D49 Log reads are bounded and per source.** `get_logs` returns what it has
  when `max_lines` is reached, when no event arrives for `quiet_seconds`
  (2 s), when `total_seconds` (10 s) elapse, or when the stream ends; a read
  timeout after at least one line is not an error; zero lines on timeout is.
  The v2 endpoint returns the `container` and `system` sources as separate
  blocks, so the driver reads them separately (`source=` parameter), scans
  the container block for milestones, `[arena] FATAL` and tracebacks, the
  system block for `start container for` restarts, and merges by `ts` only
  for the receipt tail. A failed fetch is reported as "log fetch failed: …"
  in the heartbeat, distinct from "no milestone yet".
- **D50 The worker's crash reason is evidence (after pod jdwdnvg8a2rzx6).**
  The driver keeps the last parsed `/v1/ready` body and writes it, secret-
  scrubbed, as `readiness.last_ready_response` in the driver receipt; the
  worker prints `[arena] worker CRASHED: <reason>` on every transition into
  CRASHED so the container log carries it too. Diagnostic log reads request
  400 container lines and the quiet rule cannot end a read before the
  requested tail has arrived (`stopped_because` says why a read stopped).
  The ledger, canary receipt and budget watchdog name the GPU that was
  actually created, priced from that GPU's own snapshot row.
- **D51 GLM-OCR runs the SDK the way the SDK is built.** `GlmOcr` takes
  `config_path`, not a config dict, and silently drops unknown keyword
  arguments — the earlier `config=` call left the vendor default
  `pipeline.maas.enabled: true` in force, which would have sent pages to the
  vendor's hosted API. The adapter now writes its own config file, loads it
  through `config_path`, and fails closed unless the resolved config shows
  `maas.enabled = false`, the local vLLM host/port, `retry_max_attempts = 0`
  and the verified local weight and layout directories (`ARENA_WEIGHTS_DIR`,
  `ARENA_LAYOUT_DIR`, exported by the entrypoint). The worker starts with
  `HF_HUB_OFFLINE=1` / `TRANSFORMERS_OFFLINE=1`. Bootstrap pins
  `transformers==5.4.0` (the first release exporting
  `PPDocLayoutV3ImageProcessor`, which the SDK imports at module level) and
  `wordfreq==3.1.1` (imported unguarded by the SDK's result formatter and
  not declared in its pyproject), and runs an import preflight over every
  module the adapter imports before the architecture preflight.
- **D52 First real end-to-end run, and what "empty output" means.** On
  2026-09-03 20:08–20:16Z pod `trzep8nu19x000` (RTX 4090, SECURE, $0.74/h,
  host filtered to CUDA ≥ 12.9) ran GLM-OCR at revision `ca5d8b3e…` under
  bundle `786f3ebd…` and returned 15 of 15 canary pages with page receipts,
  raw and canonical outputs and hashes; billed 458 s (299 s load, 127 s
  useful inference); stop and delete answered; v1 and v2 listings clear. The
  proof package is `evidence/canary-proof-glm_ocr.json`. That is the
  campaign's `RUNPOD_E2E_SMOKE`. The canary verdict on that run was FAIL on
  two criteria that were measurement and policy gaps, not runtime faults:
  `peak_vram_mb` was null because a server-backed runtime's memory is not
  visible from the worker process (fixed: the worker samples whole-GPU
  memory through `nvidia-smi` around every page and records the source), and
  one page of fifteen returned zero characters. That page
  (omnidocbench-c27af7…, a textbook page of cartoon figures with the name
  labels redacted) contains no legible text, so an empty result is a
  defensible answer, and the criterion was in any case blind: nothing ever
  set `blank_source`. `output_non_empty_on_non_blank` now uses a pixel-based
  blank detector (dark fraction < 0.2 % = blank), passes when at least 90 %
  of non-blank SUCCESS pages have output, and lists every empty non-blank
  page in the canary receipt for the recovery lane. The canary is a runtime
  qualification; page quality is scored later, against ground truth, never
  here.
- **D53 Opus full run selects from `source_manifest.jsonl`, not the canary
  block; auth failure is not a page failure.** Two defects found on the
  first real `python -m arena.opus run --execute` attempt
  (2026-09-04T05:46 local), both fixed:

  1. `cmd_run` was selecting pages the same way `canary` does
     (`select_canary_pages`, the frozen 50-page `opus_canary` block). A full
     run must cover the whole campaign benchmark. `arena/opus/selection.py`
     now has `select_source_manifest_pages(limit)`, which reads the
     namespace-root `source_manifest.jsonl` (5,132 rows: parsebench 2078,
     omnidoc 1651, olmocr 1403) in file order, resolves every row's
     `case_key` against the staged manifest for its benchmark (through
     `load_staged_index`, cached per benchmark rather than re-read per row),
     and fails closed -- the same discipline the frozen canary block gets --
     when a `case_key` is missing from the staged index or its
     `input_png_sha256` disagrees with what the staged manifest derives.
     `cmd_run` uses it by default (all 5,132 pages); `--case-key` still
     overrides and `--limit` still trims. `canary` is unchanged and still
     uses `select_canary_pages`. `runs/opus5_subscription/checkpoint.json`
     is shared by `canary`, `run` and `resume` (one file, one path,
     unmoved); `RunnerConfig` now carries `selection_source` /
     `selection_detail` so both `run-summary.json` and `checkpoint.json`
     record which selection produced a run and the manifest's sha256 (in
     `selection_detail`). The **canary's own stop/checkpoint history is
     superseded, for scoring purposes, by the cumulative shared-schema
     receipt** `receipts/canary-opus5_subscription.json` (built by
     `_emit_shared_canary_receipt` / `python -m arena.opus canary-receipt`
     from every page receipt under `canary/receipts/`, not by the
     per-invocation `canary/run-summary.json` or the checkpoint) -- that
     receipt, not the checkpoint, is the source of truth for what the
     canary has produced.

  2. When the child `claude -p` cannot authenticate, its JSON payload (see
     `runs/opus5_subscription/raw/olmocr-bench-83a5e23571dfcfe2482ddf35.claude.json`)
     carries `is_error: true`, `terminal_reason: "api_error"`,
     `result: "Failed to authenticate: OAuth session expired and could not
     be refreshed"`, `modelUsage: {}`, and names no model. The runner was
     scoring this as `FAILED/UNKNOWN` ("unexpected model: the payload names
     no model...") -- an infrastructure/auth condition mislabelled as a page
     failure, burning pages until it stopped. `arena/opus/limits.py` adds an
     `AUTH_EXPIRED` detection class (mirroring the existing
     `SUBSCRIPTION_LIMIT` / `RATE_LIMIT` / `TEMPORARY_CAPACITY` handling),
     matched case-insensitively on `authentication_failed`, "Failed to
     authenticate", "OAuth session expired", "not logged in", "Invalid
     authentication", `oauth_org_not_allowed` in the payload's `result` /
     error-ish fields, in stderr, or in raw stdout -- and runs inside
     `classify()`, which `run_page` already calls before the "unexpected
     model" check, so an auth-failure payload naming no model never reaches
     that check. On detection: no page receipt is written (the case_key
     stays in `pending_case_keys`, not `failed_case_keys`, for a later
     `resume`), the queue pauses, the checkpoint records
     `stop_reason: "limit:AUTH_EXPIRED"` with the fixed
     `AUTH_EXPIRED_RESET_HINT` ("re-authenticate with `claude login`
     (subscription OAuth), then `python -m arena.opus resume --execute`"),
     and the process exits 75 (`LIMIT_EXIT_CODE`). No fallback of any kind
     (no API key, no other model) -- the standing founder rule is unchanged.

  The 2026-09-04T05:46 attempt itself produced three receipts, moved to
  `runs/opus5_subscription/superseded-auth-expired-20260904T054627/receipts/`:
  all `status: "FAILED"`, `error_class: "UNKNOWN"`,
  `error_message: "unexpected model: the payload names no model, so the run
  cannot be attributed to Opus 5"`, `input_tokens`/`output_tokens: 0`,
  `api_equivalent_list_price_usd: 0.0` -- the pre-fix runner's "unexpected
  model" path scoring what was, underneath, three OAuth-authentication
  failures with zero tokens and zero cost, not three real pages. The
  checkpoint from that attempt (moved alongside, `job_kind: "inference"`,
  `stop_reason: "unexpected_model"`, `counts: {done: 0, failed: 3,
  pending: 47}`) confirms it selected the 50-page canary block, not the
  campaign -- `3 + 47 = 50`. That attempt is **superseded and must not be
  scored** (see the `WHY.md` beside the moved files). A real full run
  happens only after the founder re-authenticates (`claude login`), under
  `select_source_manifest_pages`, with `AUTH_EXPIRED` now pausing cleanly
  instead of burning pages.
- **D54 A non-root base-image USER cannot write `/opt/arena`; ARENA_ROOT is
  chosen at pod-start time and threaded through, and a failed
  `runtimes/<model>/bootstrap.sh` is now a sticky FATAL, not a restart loop.**
  Two independent, real-canary defects in the bootstrap-mode start command,
  both in `arena/worker/bundle.py`.

  1. **Non-root USER, hard-coded `mkdir -p /opt/arena`.** Two live canaries
     today, pod `jglzhcxtrph372` (hpd_parsing) and pod `cpl10cxsby0wum`
     (paddleocr_vl_1_6), each restarted repeatedly printing `mkdir: cannot
     create directory '/opt/arena': Permission denied` twice per start
     (`receipts/canary-driver-hpd_parsing.json` /
     `receipts/canary-driver-paddleocr_vl_1_6.json`,
     `readiness.container_log_tail`). Reading each image's own OCI config
     anonymously (`build/image_config_inspect.py`'s manifest+blob fetch,
     reused directly rather than re-derived) confirms why: both official
     base images declare a non-root `USER` with no write access to `/opt`.
     `hpd-parsing-vllm:latest-nvidia-gpu-offline@sha256:1493923d…`
     (`ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/hpd-parsing-vllm`)
     declares `User: "hpd"`, `WorkingDir: "/home/hpd"`, `Env: HOME=/home/hpd`
     and a `PATH` that starts with `/home/hpd/venv/bin` (its own venv, owned
     by `hpd`, ahead of everything else). `paddleocr-vl:paddleocr3.6-nvidia-gpu
     @sha256:ad0b1f05…`
     (`ccr-2vdh3abv-pub.cnc.bj.baidubce.com/paddlepaddle/paddleocr-vl`)
     declares `User: "paddleocr"`, `WorkingDir: "/home/paddleocr"`,
     `Env: HOME=/home/paddleocr`, and a plain system `PATH`
     (`/usr/local/bin:/usr/local/sbin:...`, no venv). `START_CMD_TEMPLATE`
     now probes `/opt/arena`, then `${HOME}/arena`, then `/tmp/arena`
     (`mkdir -p` + `-w`, in that order — a normal root image still gets
     `/opt/arena`, unchanged), exports the winner as `ARENA_ROOT`, and prints
     one `[arena] ARENA_ROOT=<path>` line so the driver log shows which root
     was used. No writable candidate is a fail-closed stop: it writes a
     best-effort marker to `/tmp/arena-bootstrap-fatal` and `sleep infinity`
     (D47's sticky-failure shape, since there is no `ARENA_ROOT` yet for the
     usual `$ARENA_ROOT/FATAL` location at that point) rather than `exit`,
     which RunPod would just restart. `BOOTSTRAP_TEMPLATE` reads `ARENA_ROOT`
     from the environment (`export ARENA_ROOT="${ARENA_ROOT:-$BUNDLE_ROOT}"`,
     falling back to the directory it actually lives in when invoked without
     that export — a baked image's own `ENTRYPOINT`) and derives the receipt
     path and the installed-packages marker from it instead of the
     `/opt/arena` literal. `runtimes/hpd_parsing/bootstrap.sh` and
     `runtimes/paddleocr_vl_1_6/bootstrap.sh` read `ARENA_ROOT` the same way
     (`"${ARENA_ROOT:-/opt/arena}"`, so a baked image is unaffected), and
     their weights/results directories (previously a hard-coded
     `/workspace/arena/...`, which a non-root image may not own either) now
     probe `/workspace/arena/weights/<model>` for `mkdir`+writability first
     and fall back under `ARENA_ROOT` — `ARENA_WEIGHTS_DIR` still overrides
     either default, matching the convention `runtimes/glm_ocr/bootstrap.sh`
     and `runtimes/olmocr2/bootstrap.sh` already use. Both bootstrap scripts
     also now export `ARENA_FATAL_FILE`/`ARENA_MODEL_SERVER_LOG` derived from
     `ARENA_ROOT` at hand-off, so `entrypoint.sh`'s own `/opt/arena/FATAL` /
     `/opt/arena/model-server.log` defaults track wherever `ARENA_ROOT`
     actually landed. Each `pip install` in the two runtime bootstraps now
     goes through a `pip_install()` helper that retries with `--user` on
     failure, but only when Python is not already running inside a venv (pip
     refuses `--user` inside one) — a no-op for hpd_parsing (its image ships
     the venv above, already writable by `hpd`), a real fallback for
     paddleocr_vl_1_6 (no venv on `PATH`, so a system-site-packages install
     can need it). `paddleocr install_genai_server_deps vllm` is its own CLI,
     not a raw `pip install`, so it is **not** wrapped by `pip_install()` —
     a non-writable system site there is a documented, unverified residual
     risk, not something this pass could close without a real non-root pod
     run (which this lane is not authorized to launch).
  2. **A failed `runtimes/<model>/bootstrap.sh` used to `exec`, so RunPod
     restarted the whole install on every failure.** Real evidence: pod
     `59kv17utzyhs9h` (mineru_pipeline) and pod `lr7qqjnnsgvriz`
     (mineru_vlm) each restarted 7 times, re-running `apt-get update` and a
     failing `pip install mineru @ git+…` because `git` was absent, every
     single time, because the old `exec bash "$RUNTIME_BOOTSTRAP"` replaced
     the process — a non-zero exit killed the container outright and RunPod
     restarted the start command from scratch. `BOOTSTRAP_TEMPLATE`'s
     delegation step now runs the runtime bootstrap under `set +e`, captures
     its exit status, and on non-zero writes a sticky FATAL file (format
     matching D47's: `model_key=`, `reason=bootstrap.sh exited <code>`,
     `at=`, at `${ARENA_FATAL_FILE:-$ARENA_ROOT/FATAL}`) with the
     `[arena] FATAL` prefix `arena.controller.run.FATAL_LOG_SIGNATURES`
     matches on, then `sleep infinity` — one condemnation instead of a
     restart loop. A successful run is unaffected: the runtime bootstrap
     still ends by `exec`ing `entrypoint.sh`, which replaces this waiting
     `bash "$RUNTIME_BOOTSTRAP"` child and blocks for the pod's lifetime same
     as before. Every FATAL path D47 already wired into each runtime's own
     `entrypoint.sh` (`fatal_and_hold`, etc.) is untouched — this is a second,
     independent mechanism around the install step, not a replacement.

  Both changes are confined to `arena/worker/bundle.py`,
  `runtimes/hpd_parsing/bootstrap.sh` and
  `runtimes/paddleocr_vl_1_6/bootstrap.sh`; bundle hashing semantics and every
  other runtime's bootstrap are untouched. `tests/worker/test_bootstrap_handoff.py`
  freezes the exact new `START_CMD_TEMPLATE`/`BOOTSTRAP_TEMPLATE` text (same
  discipline as the pre-D54 version), and `tests/runtimes/test_hpd_parsing.py`
  / `tests/runtimes/test_paddleocr_vl_1_6.py` check the two runtime bootstraps
  directly. Not verified by this pass: an actual non-root pod run exercising
  the fallback branches end-to-end (no pod may be created from this lane) —
  the evidence here is the OCI config reads, `bash -n` parses of every
  rendered template, and the frozen-text tests, not a live RunPod canary.
- **D55 Infinity-Parser2-Pro's tokenizer needs a real transformers v5, not
  just a vLLM that resolves the architecture (after pod gx5b5cakrhp359).**
  The 2026-09-03 architecture preflight (D47) checked only that vLLM's own
  bundled `Qwen3_5MoeConfig`/`Qwen3_5MoeTextConfig`
  (`vllm/transformers_utils/configs/qwen3_5_moe.py`) could resolve the
  checkpoint's architecture, and concluded no transformers pin was needed
  because that bundled shim does not depend on transformers knowing the
  model at all. That conclusion was correct for the architecture and wrong
  for the tokenizer: real canary pod `gx5b5cakrhp359` (2 x H100 80GB,
  2026-09-04, receipt
  `receipts/canary-driver-infinity_parser2_pro.json`) resolved the
  architecture as `Qwen3_5MoeForConditionalGeneration` and then died with
  `ValueError: Tokenizer class TokenizersBackend does not exist or is not
  currently imported` (raised from
  `transformers/models/auto/tokenization_auto.py` via
  `vllm/tokenizers/hf.py`). Tokenizer loading always goes through the
  image's real transformers -- the bundled vLLM config shim never touches
  it -- and the checkpoint's `tokenizer_config.json` (fetched read-only from
  revision `b27d4701…` on huggingface.co) declares
  `"tokenizer_class": "TokenizersBackend"`, a class that exists only in
  transformers' v5.x line
  (`src/transformers/tokenization_utils_tokenizers.py`); the pinned
  `vllm==0.17.1` image bounds transformers to `>= 4.56.0, < 5`
  (`requirements/common.txt`), so it never had that class regardless of
  which 4.x release was actually installed. The same pod also confirmed a
  second defect: `bootstrap.sh` resolved the 70.21 GB checkpoint into
  `/workspace`, but never exported `ARENA_WEIGHTS_DIR`, so `entrypoint.sh`'s
  default fell back to `/opt` and resolved the same checkpoint a second
  time -- two ~1.5-2 minute downloads of the same weights on a $6.98/h pod.

  Fix, both landed in `runtimes/infinity_parser2_pro/`: `runtime.json` and
  the `Dockerfile`'s `FROM` are bumped to
  `vllm/vllm-openai:v0.19.0-ubuntu2404@sha256:69234fc3…` -- the exact digest
  `runtimes/glm_ocr` already proved live on RunPod (D51) -- with the same
  four `--no-deps` pins glm_ocr uses on top of it:
  `transformers==5.4.0`, `tokenizers==0.22.2`, `huggingface_hub==1.5.0`,
  `hf-xet==1.3.2`, installed in both `bootstrap.sh` and the `Dockerfile`.
  Verified by fetching the actual source: transformers v5.3.0 (the
  checkpoint's own declared `transformers_version`) already maps
  `model_type` `qwen3_5_moe`/`qwen3_5_moe_text` in `CONFIG_MAPPING_NAMES` /
  `TOKENIZER_MAPPING_NAMES` to `Qwen3_5Tokenizer`, and
  `transformers.tokenization_utils_tokenizers.TokenizersBackend` is
  importable; both facts hold unchanged at the pinned v5.4.0. vLLM v0.19.0
  still registers `Qwen3_5MoeForConditionalGeneration`
  (`model_executor/models/registry.py`) and still ships
  `vllm/transformers_utils/configs/qwen3_5_moe.py` with
  `Qwen3_5MoeConfig`/`Qwen3_5MoeTextConfig` (`model_type
  "qwen3_5_moe_text"` unchanged), so the D47 preflight's vLLM-side checks
  stay valid and were kept verbatim; a transformers-side check
  (`CONFIG_MAPPING_NAMES` membership plus `TokenizersBackend`
  importability) was added ahead of them. `bootstrap.sh`'s preflight now
  runs *before* the 70.21 GB weight download -- fetching only
  `config.json` and `tokenizer_config.json` via `hf_hub_download`, a few KB
  -- instead of after, so a framework that cannot serve this checkpoint
  fails in seconds rather than after minutes of paid two-GPU download; and
  `bootstrap.sh` now exports `ARENA_WEIGHTS_DIR` so `entrypoint.sh` reuses
  the directory bootstrap already resolved instead of re-downloading.
  `inference_config` and its `inference_config_sha256` are unchanged (this
  fix is base-image and framework only); `min_cuda_version` stays `12.9`
  (the new image reports the same `CUDA_VERSION=12.9.1` the old one did).
  `provenance.json`'s `framework_floor_audit` keeps the 2026-09-03
  conclusion under a `superseded` key rather than deleting it, so the wrong
  call and the evidence that overturned it both stay on the record.
  `tests/runtimes -q` (849 passed) and `tests/core -q` (452 passed) both
  green after the change; no `.py` file was touched, so `ruff`/`mypy` have
  nothing new to check.
- **D56 flash-attn is a pinned wheel, never built on the pod.** The
  2026-09-03 RunPod canary (pod `d8s9nypr5wrcz9`, RTX 4090, receipt
  `receipts/canary-driver-deepseek_ocr2.json`) failed `bootstrap.sh`'s
  `pip install --no-cache-dir --no-build-isolation flash-attn==2.7.3` line
  during metadata generation with
  `FileNotFoundError: [Errno 2] No such file or directory: 'git'`; even with
  git present that line compiles flash-attn from source on the pod
  (`MAX_JOBS=4`), tens of minutes of paid GPU time per canary and per Full
  Run pod. A prebuilt wheel matching this image's exact stack exists on the
  official flash-attention v2.7.3 release
  (https://github.com/Dao-AILab/flash-attention/releases/tag/v2.7.3, asset
  list confirmed via `https://api.github.com/repos/Dao-AILab/flash-attention/releases/tags/v2.7.3`):
  `flash_attn-2.7.3+cu11torch2.6cxx11abiFALSE-cp311-cp311-linux_x86_64.whl`
  (193,188,239 bytes, sha256
  `727fad58861999fcf23b400b9ae47ad8cb5ee9b0a88550b1d4ae0b629212c646`, HTTP
  HEAD confirmed 302 to a signed `release-assets.githubusercontent.com` URL,
  downloaded once and hashed locally). The wheel's tag matches the base
  image on every axis that matters: cu11 (base image is CUDA 11.8),
  torch2.6 (pinned torch is 2.6.0), cp311 (base image ships Python 3.11),
  and `cxx11abiFALSE` -- the pip `cu118` build of torch 2.6.0
  (`linux_x86_64`, manylinux2014-tagged per
  `download.pytorch.org/whl/cu118`) predates PyTorch's
  manylinux_2_28/new-ABI switch, which lands in torch 2.7+, so
  `torch._C._GLIBCXX_USE_CXX11_ABI` is `False` on this base image and the
  `FALSE`-tagged wheel is the correct match; no ABI mismatch was found so
  the base image did not need to change. `bootstrap.sh` now downloads that
  exact wheel by URL, verifies its sha256 with `sha256sum --check --strict`
  before installing, and fails closed (`echo "[arena] FATAL ..."` + `exit
  64`, the same D47 mechanism the architecture preflight uses) on a
  mismatch, then `pip install`s the verified wheel file directly instead of
  building from source; the downloaded wheel is deleted after install. No
  other bootstrap.sh step needs git or a compiler: every other `pip
  install` in the script pulls a prebuilt wheel. The baked-image
  `Dockerfile` still builds flash-attn from source at image-build time (not
  per rented pod), which is a one-time cost rather than a per-canary/per-run
  one and is out of scope for this fix; its `RUN pip install --no-cache-dir
  --no-build-isolation flash-attn==2.7.3` line is unchanged, with a comment
  added pointing at this decision. `runtime.json`'s `base_image` and
  `min_cuda_version` are unchanged since the base image did not change.
- **D58 monkeyocrv2_b's server dies on its own documented legacy install
  because of an upstream tuple-length bug in `parsing/serve.py`, not a bad
  image pin; the image stays and the vendor's own comparison is widened by
  one line.** The 2026-09-03 RunPod canary (pod `sdxexiyyx33a2p`, RTX 4090,
  receipt `receipts/canary-driver-monkeyocrv2_b.json`) passed the
  architecture preflight (`model_type=monkeyocrv2`,
  `MonkeyOCRv2ForCausalLM` `registered_by=modeling.modeling_monkeyocrv2_vllm_011`,
  `transformers=4.57.1`, `vllm=0.11.2`, image
  `vllm/vllm-openai:v0.11.2@sha256:2c908d5a84ed251b6a17d179f42d06df1aff353007779ac5eecd8a0ea3fe9331`)
  and then the vendor's own server printed `Unsupported vLLM version: (0,
  11, 2). MonkeyOCRv2 requires vLLM >= 0.25 for DFlash acceleration or
  ==0.11 for legacy support.` and exited after 10s. Read at the pinned
  runtime revision `d46699fb6a4c71d61588e4a71fce03bff4f1ba33`
  (`https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/parsing/serve.py`,
  lines 18-35):

  ```python
  def vllm_version_tuple() -> tuple[int, ...]:
      try:
          raw_version = version("vllm")
      except PackageNotFoundError as exc:
          raise SystemExit("vLLM is not installed in the current Python environment.") from exc
      numbers = re.match(r"^(\d+(?:\.\d+)*)", raw_version)
      if not numbers:
          raise SystemExit(f"Unable to determine the installed vLLM version: {raw_version}")
      return tuple(int(part) for part in numbers.group(1).split("."))


  installed = vllm_version_tuple()
  if installed == (0, 11):
      from modeling import modeling_monkeyocrv2_vllm_011  # noqa: F401
  elif installed >= (0, 25):
      from modeling import modeling_monkeyocrv2_vllm  # noqa: F401
  else:
      raise SystemExit(f"Unsupported vLLM version: {installed}. MonkeyOCRv2 requires vLLM >= 0.25 for DFlash acceleration or ==0.11 for legacy support.")
  ```

  `vllm_version_tuple()` parses `importlib.metadata.version("vllm")` into a
  full `(major, minor, patch)` tuple -- for the installed `0.11.2` that is
  `(0, 11, 2)` -- and the legacy branch compares it with `==` against the
  literal 2-tuple `(0, 11)`. A 3-tuple is never `==` a 2-tuple in Python
  regardless of its values, so this branch is unreachable for *any* released
  vLLM patch version; only a bare `"0.11"` (no patch component, which no
  PyPI release reports) would satisfy it. The vendor's own README at the
  same revision
  (`https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/README.md`,
  "Document Parsing" quick start) says: "If your system does not support
  CUDA 12.9, you can instead install vLLM 0.11.2 (without DFlash support)"
  and gives `uv pip install vllm==0.11.2 --torch-backend=auto` as the
  install command -- i.e. the exact version this runtime already pins is
  the version upstream's own documentation says to run through this exact
  broken check. `parsing/requirements.txt` at the same revision pins only
  `gradio==5.30.0` and `pypdfium2==5.10.1`; it does not pin vllm at all, so
  it gives no separate signal.

  This is upstream broken at this exact revision, not a pin mismatch: no
  choice of `vllm/vllm-openai` image tag or digest changes the outcome,
  because every real vLLM release reports a 3-part version and the check as
  written accepts none of them. Per this task's option (b) evaluation: the
  vendor's newer path (`vllm >= 0.25.1` for DFlash) is out of scope by
  runtime.json's own `notes` (DFlash is deliberately off -- different
  checkpoint, different serving stack, different benchmark condition) and
  was not revisited here. The smallest correct change is a one-line,
  minimally-scoped patch to the vendor's own comparison, applied to the
  vendor's cloned copy of `parsing/serve.py` after checkout and before
  `serve.py` runs, in both places the repo is cloned:
  `runtimes/monkeyocrv2_b/bootstrap.sh` (canary path, clones at pod start)
  and `runtimes/monkeyocrv2_b/Dockerfile` (baked path, clones at image
  build; `entrypoint.sh` invokes `serve.py` at container start in both
  paths, so both clones need it):

  ```
  sed -i \
      's/^if installed == (0, 11):$/if installed[:2] == (0, 11):  # ARENA D58 patch: .../' \
      <cloned-repo>/parsing/serve.py
  ```

  followed by a `grep -q` assertion that the substitution landed, so a
  future upstream rewrite of that line fails the bootstrap/build loudly
  instead of silently no-opping the patch. This changes only the equality
  check from a literal 2-tuple to a major.minor slice (`installed[:2]`),
  which is what the vendor's own error message already says it wants
  ("...or ==0.11 for legacy support") -- it does not disable, loosen past
  major.minor, or bypass the check: vLLM 0.10.x, 0.12.x, etc. are still
  refused, and DFlash's `elif installed >= (0, 25):` branch and the
  separate `--draft-model` guard at line 158
  (`if installed_version < (0, 12) and args.draft_model:`) are untouched
  and were confirmed (by tuple comparison semantics) to already work
  correctly for 3-part versions. `runtime.json`'s `base_image`,
  `min_cuda_version` (`12.9`, shared with `olmocr2` per
  `tests/runtimes/test_cuda_floor.py::test_the_two_runtimes_that_share_an_image_share_a_floor`)
  and every other pin are unchanged, because the image was never the
  problem. The D47 architecture-preflight FATAL/fail-closed contract in
  `bootstrap.sh` is unchanged and untouched by this patch -- it runs before
  `serve.py` and independently imports
  `modeling.modeling_monkeyocrv2_vllm_011` and checks
  `ModelRegistry.get_supported_archs()` itself, which is exactly why it
  already passed on the failing canary while `serve.py`'s own check failed
  afterward.

  Sources read for this decision:
  `https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/parsing/serve.py`,
  `https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/parsing/modeling/modeling_monkeyocrv2_vllm_011.py`
  (no version check; confirms the DFlash branch's module is the only other
  consumer of `vllm_version_tuple`-shaped logic),
  `https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/parsing/requirements.txt`,
  `https://raw.githubusercontent.com/Yuliang-Liu/MonkeyOCRv2/d46699fb6a4c71d61588e4a71fce03bff4f1ba33/README.md`.
  Not verified: the patch was read-reviewed and syntax-checked
  (`ast.parse`) against a locally fetched copy of `parsing/serve.py` at the
  pinned revision; it was not exercised against a real vLLM process on a
  rented GPU, since this task's instructions forbid creating pods or
  running `arena.controller canary|run|bundle --execute`. The next canary
  attempt against `monkeyocrv2_b` is the first place this patch runs for
  real and is the open item this decision leaves behind.
- **D57 The pod ledger prices per GPU, not per pod, and `cost` labels
  in-flight pods instead of hiding them (defect: pod `gx5b5cakrhp359`).**
  `infinity_parser2_pro` pod `gx5b5cakrhp359` was provisioned with 2 x
  NVIDIA H100 80GB HBM3; the driver's own cost ceiling printed it correctly
  (`2 x NVIDIA H100 80GB HBM3 on SECURE at $3.49/h for 2h + disk = $14.04`)
  but the pod ledger row carried only `listed_rate_usd_per_hour: 3.49` (the
  per-GPU snapshot rate) with no GPU count, and `cost.py` priced
  `billed_seconds/3600 * rate` -- one GPU's worth, $0.445 for 459 billed
  seconds, when two were rented (~$0.89). `PodRecord`, `PodLedgerRow` and
  `PodLedgerEntry` now all carry `gpu_count` (positive int, default 1);
  `arena/controller/queue.py`'s `pods` table gains a `gpu_count INTEGER NOT
  NULL DEFAULT 1` column via `_add_missing_columns`, so a campaign database
  opened before this revision is migrated in place rather than losing the
  column resume already relies on for D2/D6. `listed_rate_usd_per_hour`
  keeps meaning the per-GPU rate (said explicitly in
  `pod-ledger.schema.json` now); `cost.build_ledger_row` multiplies
  `estimated_provider_cost_usd` and `useful_cost_usd` by `gpu_count`.
  `arena/controller/driver.py`'s canary path sets `gpu_count` from
  `runtime.gpu_count_min` at provisioning (`_record_pod`) and carries the
  same pod's `gpu_count` through `_mark_ready` and `_write_ledger`'s settled
  row rather than letting either upsert silently reset it to the dataclass
  default; `arena/controller/cli.py`'s full-run provisioning path sets it
  from `PodSpec.gpu_count`, the same field D50's pool-walk rebinding already
  keeps intact. `pod-ledger.schema.json` adds `gpu_count` as an optional
  (not required) integer property, so an existing `cost/pod_ledger.jsonl`
  row written before this decision still validates read back; the one wrong
  historical row for `gx5b5cakrhp359` is not rewritten in place -- the
  ledger is evidence -- and the correction is recorded separately at
  `receipts/incidents/ledger-gpu-count-correction.json`.

  Separately: `python -m arena.controller cost` reporting "21 pod(s) ...
  billed 11.34 GPU-h (idle 10.82)" against `cost/pod_ledger.jsonl`'s 16 rows
  summing to 2.59 billed hours was not lost or duplicated evidence. `_cost`
  recomputes a fresh `PodLedgerRow` for every row in the queue database's
  `pods` table, not just the ones already settled into
  `cost/pod_ledger.jsonl`; `build_ledger_row` measures a pod with no
  `terminated_at` as billed "to now", by design (masterplan section 42),
  because that pod is still actually running. With canary drivers running
  concurrently while this decision was made, several queue rows were
  legitimately still open, and each `cost` invocation's "now" pushed their
  billed seconds higher -- a live number, not a corrupt one, sitting next to
  the closed rows in the append-only ledger file, which by construction only
  gains a line when a pod is torn down. No rows are dropped or excluded:
  `cost_module.summarize` now adds an explicit note whenever any input row
  has no `terminated_at`, naming how many pods are still billing, their
  live GPU-hours measured to now, and separately how many pods are settled
  and their GPU-hours -- the same split `cost/pod_ledger.jsonl` already
  carries as fact. The campaign total is unchanged and still counts every
  pod; the note only makes the open/closed split legible instead of leaving
  the reader to reconcile two different-shaped numbers unaided.
- **D59 mineru_pipeline's weights never landed because `hf download`'s
  `--include` flag only keeps the last pattern, and mineru_vlm's
  `expected_vlm_engine` was pinned to the wrong engine for its own base
  image (after pods `jtaueklmmsieo4` and `plz5obsz7ega3a`).**

  (A) `mineru_pipeline`'s real canary (pod `jtaueklmmsieo4`, 3 container
  restarts, receipt `receipts/canary-driver-mineru_pipeline.json`) restarted
  and, in the same second as its pip "Requirement already satisfied" lines,
  jumped straight to `sha256sum: WARNING: 1 listed file could not be read`
  with no `hf download` output at all -- the restart took the cache-hit
  branch because `arena-weights-revision.txt` already existed, written by
  the *first* attempt before its checksum ran. huggingface_hub 0.35.3's CLI
  (`src/huggingface_hub/commands/download.py`, fetched read-only) declares
  `download_parser.add_argument("--include", nargs="*", type=str, ...)` --
  `nargs="*"`, not `action="append"` -- so `bootstrap.sh`'s seven repeated
  `--include PATTERN` flags did not accumulate: each flag replaced the
  previous value, and only the last one,
  `models/TabCls/paddle_table_cls/PP-LCNet_x1_0_table_cls.onnx`, survived.
  `hf download` therefore fetched that one file, returned exit 0 (a
  genuinely successful download of what it was actually told to fetch), and
  never touched `models/MFR/unimernet_hf_small_2503/model.safetensors` --
  confirmed present at the pinned revision via
  `https://huggingface.co/api/models/opendatalab/PDF-Extract-Kit-1.0/tree/ed6b654c018d742e65a17671e379c5e6ecc87ec9/models/MFR/unimernet_hf_small_2503`
  (size 810036696, `lfs.sha256`
  `9244e2565585c0f89bc3a6eeeea080ef3c588375fc0d536074fe88e80b917cda`, matching
  `ARENA_WEIGHTS_LARGEST_SHA256` exactly). Fix, in
  `runtimes/mineru_pipeline/bootstrap.sh`: the CLI call is replaced with
  `huggingface_hub.snapshot_download(repo_id=..., revision=..., local_dir=...,
  allow_patterns=[...])`, which takes all seven patterns as one Python list
  instead of seven overwriting CLI flags; on failure or an empty fetch it
  prints `[arena] FATAL weights: <reason>` to stderr and exits 64, the same
  fail-closed convention the architecture preflight already uses; on
  success it records the number of files fetched and the largest file's
  path/size to the bootstrap receipt (`weights_fetch_summary=`). The
  `sha256sum -c` check now also fails closed explicitly
  (`[arena] FATAL weights: checksum verification failed ...` + exit 64
  instead of relying only on `set -e`), and -- the actual ordering bug --
  `arena-weights-revision.txt` is now written *after* that checksum passes,
  never before, so a restart after a failed or partial fetch retries the
  download instead of silently taking the cache-hit branch. The same
  marker-after-checksum reordering is applied to
  `runtimes/mineru_vlm/bootstrap.sh` even though its plain `hf download`
  (no `--include`, so the `nargs="*"` defect never applied) fetched the
  right file on the real canary.

  (B) `mineru_vlm`'s real canary (pod `plz5obsz7ega3a`, A40) downloaded and
  checksummed its weights correctly, then MinerU logged `Using vllm-engine
  as the inference engine for VLM` and the bootstrap's own architecture
  preflight raised `[arena] FATAL architecture preflight: MinerU's
  vlm-engine resolved to 'vllm-engine', but runtime.json's
  inference_config.expected_vlm_engine is 'transformers'` -- the preflight
  did exactly its job. The adapter (`runtimes/mineru_vlm/adapter.py:221`)
  and the bootstrap preflight both call
  `get_vlm_engine(inference_engine="auto", is_async=False)`; MinerU never
  receives an explicit backend override, so the auto-detected engine is
  what actually runs. `mineru/utils/engine_utils.py` at the pinned
  revision `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` (fetched read-only,
  `raw.githubusercontent.com/opendatalab/MinerU/fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883/mineru/utils/engine_utils.py`)
  shows `_select_linux_engine` tries `import vllm` first and returns
  `'vllm'` (formatted `'vllm-engine'` by `_format_engine_name`) whenever
  that import succeeds, falling back to `lmdeploy` then `transformers`
  only if it does not; this runtime's base image is
  `vllm/vllm-openai:v0.21.0`, which ships vLLM, so the import always
  succeeds and the auto-detected engine on this image is always
  `vllm-engine`, never `transformers`. This is not a MinerU defect: MinerU's
  own `docker/global/Dockerfile`
  (`raw.githubusercontent.com/opendatalab/MinerU/fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883/docker/global/Dockerfile`)
  itself `FROM vllm/vllm-openai:v0.21.0` -- the identical base image this
  arena runtime uses -- so auto-detecting `vllm-engine` on this image is the
  path MinerU's own official image is built to take, not an accident of our
  pin. Corroborating evidence already inside this repository:
  `model_registry.json`'s `official_inference_config` for `mineru_vlm`
  (resolved from the model card, unrelated to this bug) already names
  `"backend": "vllm-engine"`. `inference_config.expected_vlm_engine` was
  simply pinned to the wrong value for this image.

  Fix, keeping the adapter's auto-detection design (an explicit backend
  override was not added; the failure mode this preflight exists to catch
  -- a toolkit resolving to a different engine than the image was built for
  -- stays caught, it just now checks against the correct expectation):
  `runtimes/mineru_vlm/runtime.json`'s `inference_config.expected_vlm_engine`
  is now `"vllm-engine"` (was `"transformers"`), `official_runtime` is now
  `"vllm"` (was `"transformers"`, and the schema's enum has no
  `"vllm-engine"` value), `display_name` and `runtime_version` are updated
  to match, and `inference_config_sha256` in `model_registry.json` is
  recomputed via the same `arena.worker.util.config_sha256` function
  `arena/registry/runtimes.py` calls
  (`sha256:3d1b1a011b48d91652de6e009bd341f7fa2398818546c4cc04cac2aaabdb42bb`,
  was `sha256:3cfd60a2af048732ecce2214f21f925661414d66ba59f0a71fd8c0662f312170`)
  -- confirmed against `tests/controller/test_preflight_sections.py`'s own
  `config_sha256(runtime["inference_config"])` comparison, which stayed
  green. `runtimes/mineru_vlm/bootstrap.sh`'s preflight `EXPECTED_ENGINE`
  constant is updated the same way, with the comment explaining why
  `vllm-engine` is what this image will always resolve to. The bootstrap's
  "starts no model server" claim still holds with `vllm-engine`:
  `mineru/backend/vlm/vlm_analyze.py`'s `ModelSingleton.get_model` holds
  the vLLM engine as an in-process `vllm.LLM` object keyed by
  `(backend, model_path, server_url)`, not an HTTP server process -- that is
  the separate `"http-client"` backend -- so `entrypoint.sh` keeps `exec`
  per D19 and `ARENA_CONTRACT` 11.6 is unaffected.
  `tests/runtimes/test_mineru_vlm.py::test_runtime_json_pins_the_expected_vlm_engine`
  and `::test_the_preflight_names_this_checkpoints_architecture_mineru_vlm`
  encoded the old (wrong) pin and are updated to the corrected one, with a
  comment naming the real canary that caught it.
  `tests/runtimes/test_c1_integration_contract.py::test_bootstrap_pins_weights_by_revision_and_sha256_without_a_token`
  is loosened to accept either the CLI `--revision` flag or
  `snapshot_download`'s `revision=os.environ[...]` keyword, since
  `mineru_pipeline` now uses the latter. `tests/runtimes -q` (855 passed),
  `tests/core -q` (452 passed), `tests/registry -q` (167 passed) and
  `tests/controller -q` (321 passed) all green after both fixes; `ruff
  check` and `mypy` clean on the two test files touched; `bash -n` clean on
  both bootstraps, and both embedded Python heredocs compile.

  (C) Follow-up, same decision (2026-09-04): both weights and engine fixes
  above worked -- the relaunched canaries got past download, checksum and
  (for `mineru_vlm`) the vllm-engine preflight -- then both crashed in
  warm-up with the identical `AdapterError: UNKNOWN: Exception: Unknown file
  suffix: .png` (`mineru_pipeline` pod `eymd8t51r6597g`, receipt
  `receipts/canary-driver-mineru_pipeline.json`; `mineru_vlm` pod
  `d4qo3kl49kai6v`, receipt `receipts/canary-driver-mineru_vlm.json`). Both
  adapters call `self._read_fn(image_path, image_path.suffix.lower())` before
  calling `do_parse`. `mineru/cli/common.py` at the pinned revision
  `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` (fetched read-only,
  `raw.githubusercontent.com/opendatalab/MinerU/fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883/mineru/cli/common.py`)
  declares `pdf_suffixes = ["pdf"]`, `image_suffixes = ["png", "jpeg", "jp2",
  "webp", "gif", "bmp", "jpg", "tiff"]` and `office_suffixes` -- every entry a
  bare token, never dotted -- and `read_fn(path, file_suffix)` raises exactly
  `Exception(f"Unknown file suffix: {file_suffix}")` when `file_suffix` is in
  none of those lists. `Path.suffix` returns `".png"` (with the dot), which
  matches none of them, reproducing the canary's error precisely.
  `mineru/cli/client.py`'s own callers (`raw.githubusercontent.com/opendatalab/MinerU/fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883/mineru/cli/client.py`)
  and `mineru/utils/guess_suffix_or_lang.py`'s
  `guess_suffix_by_path`/`guess_suffix_by_bytes` (same revision, same host)
  confirm this is not an edge case: MinerU's own suffix resolution (Magika
  content sniffing, `_guess_ooxml_suffix_by_*`, the PDF-signature check) never
  produces a leading dot anywhere in the codebase.

  Fix, identical in both `runtimes/mineru_pipeline/adapter.py` and
  `runtimes/mineru_vlm/adapter.py` (the two adapters carry independent copies
  of this call by design -- ARENA_CONTRACT's own note at the top of
  `tests/runtimes/conftest.py` says each `runtimes/<model_key>/` must stay
  self-contained): a new module-level `_mineru_file_suffix(path: Path) ->
  str` returns `path.suffix.lower().lstrip(".")`, and both backends'
  `parse()` methods call `self._read_fn(image_path,
  _mineru_file_suffix(image_path))` instead of passing `image_path.suffix.lower()`
  straight through. `warmup()` needed no separate fix: it calls
  `self.infer(page)`, the same `infer` → `backend.parse` path `parse()`
  pages already used, so the one fix covers both. `inference_config` and
  `inference_config_sha256` are unchanged in both runtimes -- this is an
  adapter-code fix only, nothing in `runtime.json`'s pinned identity moved.

  New unit tests in both `tests/runtimes/test_mineru_pipeline.py` and
  `tests/runtimes/test_mineru_vlm.py`: `test_mineru_file_suffix_strips_the_dot_path_suffix_keeps`
  checks the pure helper directly, and
  `test_official_backend_passes_dotless_suffix_to_read_fn` constructs the
  real `_OfficialMineruBackend`/`_OfficialMineruVlmBackend` (not the
  `FakeBackend` fixture the rest of each suite uses, which bypasses this code
  path entirely), calls its real `.parse()` against the suite's existing real
  PNG fixture (`png`, a genuine 2x2 PNG with the right magic bytes), and
  substitutes fake `read_fn`/`do_parse` functions in place of `mineru.cli.common`'s
  (no GPU, no mineru import needed) -- the fake `read_fn` reproduces MinerU's
  own `Unknown file suffix` failure mode for any suffix outside MinerU's
  real allow-list, so the test fails loudly if the fix regresses. Both new
  tests assert the suffix `read_fn` actually receives is `"png"`, not
  `".png"`.

  `tests/runtimes -q` (859 passed, up from 855 -- 4 new tests), `tests/core
  -q` (452 passed) both green after the fix; `ruff check` and `mypy` clean
  on both `adapter.py` files and both test files touched (checked
  separately per-runtime, since `runtimes/mineru_pipeline/adapter.py` and
  `runtimes/mineru_vlm/adapter.py` collide as the same mypy module name
  `adapter` when checked together); `bash -n` clean on both bootstraps
  (unchanged this pass).

- **D60 an ambiguous 5xx on `POST /pods` is re-listed by name twice, ten
  seconds apart, and then the pool walk continues to the next entry instead
  of ending (after `hpd_parsing`'s two HTTP 500 refusals on 2026-09-03).**

  `hpd_parsing`'s canary was refused twice at provisioning with HTTP 500 on
  its first pool entry (an H100 PCIe that the RunPod capacity view showed
  as out of stock at the time; `receipts/canary-driver-hpd_parsing.json`)
  and never reached the A100 entries behind it. D24 ended the walk on any
  5xx after one re-list by name, so that a create that had actually
  succeeded server-side could never be rented twice. The instinct was right
  and the price was wrong: an out-of-stock 5xx is far more common than a
  create that succeeds and then answers 500, and ending the walk on it
  costs a whole launch and a human relaunch. `arena/provider/runpod_v1.py`
  now, on any error that `_is_request_rejected` does not class as a 4xx
  refusal: re-lists by name; waits `AMBIGUOUS_CREATE_RECHECK_SECONDS`
  (10 s -- injectable through `ambiguous_recheck_sleep`, so the tests do
  not sleep); re-lists once more; adopts the pod if either listing shows it
  (receipt summary `adopted_after: "ambiguous create, second re-list"`);
  and otherwise records the attempt with `ambiguous: true` and
  `re_listed_by_name: 2` and moves to the next `gpu_type_ids` entry.
  Rejections (4xx) are unchanged, and so is the D24 promise -- no ambiguous
  create rents a second pod -- it is now checked twice before the walk moves
  on. Tests `test_an_ambiguous_create_walks_on_after_two_re_lists` and
  `test_a_pod_that_appears_on_the_second_re_list_is_adopted_not_duplicated`
  in `tests/provider/test_runpod_v1.py`; `tests/provider -q` 162 passed;
  `ruff check` clean on both files and `mypy` clean on the client.

- **D61 paddleocr_vl_1_6's architecture preflight asked vLLM's registry a
  question PaddleX answers only at server start, and killed a healthy pod
  (pod `rcre8rpux1oohv`, 2026-09-04).**

  The real canary downloaded and checksummed the PaddleOCR-VL-1.6 weights
  (`model.safetensors: OK`) and then died on the bootstrap's own D43-era
  check: `[arena] FATAL architecture preflight: the genai_server's vLLM
  0.10.2 does not register ['PaddleOCRVLForConditionalGeneration']`
  (`receipts/canary-driver-paddleocr_vl_1_6.json`, container log tail).
  The check was written on the assumption in its own comment -- that the
  vLLM which `paddleocr install_genai_server_deps vllm` installs is recent
  enough to carry the architecture built in, as upstream vllm v0.17.1's
  registry does. It is not, by the vendor's own choice: that installer runs
  `paddlex --install genai-vllm-server` (PaddleOCR v3.6.0 `_cli.py`), whose
  extra pins `vllm == 0.10.2` (PaddleX v3.6.1 `setup.py`), and PaddleX
  declares `min_vllm_version: 0.11.1` for PaddleOCR-VL-1.6-0.9B in
  `paddlex/inference/genai/models/__init__.py` -- below that it ships the
  model out-of-tree and registers it itself through a `vllm.general_plugins`
  entry point (`register_paddlex_genai_models =
  paddlex.inference.genai.backends.vllm:register_models`), which vLLM runs
  when the server process starts. So the genai server would have come up;
  the preflight asked a cold `ModelRegistry.get_supported_archs()` and
  refused the pod for an answer the server never sees. Fix, in
  `runtimes/paddleocr_vl_1_6/bootstrap.sh`: when the architecture is missing
  from the cold registry, the preflight imports and runs that same
  `register_models()` hook, re-reads the registry, and fails only if the
  architecture is still unknown (or the hook itself raises); the receipt
  line now carries `arch_registration=` naming which of the two answered.
  Nothing about what is measured changes: the served vLLM is still the one
  the vendor installs. The preflight stays -- GLM-OCR's restart loop (the
  reason it exists) was a real Transformers mismatch, and this check still
  catches that class; it just no longer refuses the vendor's own
  configuration. `bash -n` clean; bundle republished
  (sha256 `fdfaa255f9289e6a52aa38c54bdcde6c4b7d89cd9b866c9ea19a8d3788029f43`,
  `receipts/bundles/paddleocr_vl_1_6.json`) and the canary relaunched.

- **D62 the canary driver now keeps the container log from *after* the
  pages ran, not only from readiness (after mineru_vlm's pod
  `r0yal3hocpipsm` returned 15 SUCCESS pages with nothing in them,
  2026-09-04).**

  mineru_vlm's real canary came up cleanly on an A40 (MODEL_LOADING ->
  WARMING -> READY in 7.6 min), ran all 15 pages at 0.63 s each, and every
  page came back `status=SUCCESS`, `output_bytes=0`,
  `semantic_error_class=OUTPUT_EMPTY`: MinerU's own `middle_json` has
  `para_blocks: []` for every page and `model_json` is `[[]]` -- the VLM's
  layout step returned no blocks, and the worker, which only sees MinerU's
  files, had no error to report. The section 17 floor did its job
  (`output_non_empty_on_nonblank` 0.0% < 90%, verdict FAIL,
  `receipts/canary-mineru_vlm.json`), but the *why* was gone: the driver's
  only container log is the readiness tail, which ends where the worker came
  up, and the pod was deleted seconds after the last page. Input images were
  the same 1224x1584 pages olmocr2 answered on; MinerU 3.4.5's default VLM
  checkpoint is exactly the pinned `opendatalab/MinerU2.5-Pro-2605-1.2B`
  (`mineru/utils/enum_class.py`), its `vllm` extra accepts the image's vLLM
  0.21.0 (`>=0.10.1.1,<0.22.0`), and its own Dockerfile builds on that same
  `vllm/vllm-openai:v0.21.0` image with `transformers==4.57.3` -- so the
  stack is the vendor's, and reasoning alone cannot say why it printed
  nothing. `arena/controller/driver.py` therefore adds step 8 to the canary
  driver: after the worker is drained and before the pod is terminated, it
  reads the container log once more (`_postrun_diagnostics`, same
  `_read_log_tail`, same 400-line container tail, same per-line secret
  scrub) and writes it to the driver receipt as `postrun.container_log_tail`
  with `captured_at`, a note, and the read receipts; a failed read is
  recorded as `log read failed: ...` and noted, never as an empty tail. Two
  tests in `tests/controller/test_canary_driver.py`
  (`test_a_pass_keeps_what_the_runtime_printed_while_serving_pages`,
  `test_the_post_run_log_goes_through_the_same_secret_guard`);
  `tests/controller -q` 323 passed; `ruff` and `mypy` clean. The mineru_vlm
  canary is relaunched on the same bundle so the next receipt carries
  MinerU's page-time output; the root cause gets its own decision when that
  evidence exists.

- **D63 the Opus lane can be stopped by an operator and restarted with a
  different worker count without paying twice (2026-09-04, ramp 2 -> 4).**

  The plan ramps the subscription lane 2 -> 4 -> 6 workers once it is
  stable, and after 25 minutes at 2 workers (~5.8 pages/min, 141 receipts,
  no limit hit) it was. But the runner only ever stopped itself: a limit,
  AUTH_EXPIRED (D53) or an unexpected model wrote a checkpoint and exited
  75; nothing let an operator ask it to stop, and a killed process wrote no
  checkpoint, so `resume` had nothing and `run` would have started the
  5,132 pages from the top. Two changes. (A) `arena/opus/runner.py`: a file
  named `STOP` under the run root is checked before every dispatch; when it
  appears the pool starts nothing new, every page already running finishes
  and writes its receipt, the rest are checkpointed with
  `stop_reason: "operator_stop"` exactly as a limit would, and the file is
  removed once acknowledged so the resume does not stop on the same request.
  (B) `arena/opus/cli.py`: `run` drops any page whose receipt already exists
  under the receipt directory and says how many it dropped in the selection
  detail; with nothing left it exits 0 without running. A receipt is written
  once, atomically, after the page finished in either status, so its
  presence is the fact that the page ran (a page that failed is not retried
  by `run` either -- that is the recovery lane's job, section 24). The ramp
  itself used (B): the 2-worker process (pid 22876, old code) was killed at
  06:54 KST with 157 receipts on disk, and `run --workers 4` restarted at
  06:54:52 KST skipping those; the two pages in flight at the kill were
  re-run. Tests: `test_an_operator_stop_file_checkpoints_the_rest_and_is_consumed`
  (`tests/opus/test_runner.py`), `test_run_skips_pages_that_already_have_a_receipt`
  and `test_run_with_everything_receipted_runs_nothing`
  (`tests/opus/test_cli_run_selection.py`); `tests/opus -q` 145 passed;
  `ruff` and `mypy` clean on both files.

- **D65 the pod-side code must run on Python 3.10, and `arena/core` is not
  on the pod (paddleocr_vl_1_6, pod `kfvy42gzo6ikt3`, 2026-09-04).**

  With D61 in place the PaddleOCR-VL canary got all the way up -- weights
  checksummed, architecture preflight PASS through PaddleX's own hook, genai
  server answering `/v1/models` 200 -- and then the worker died on its first
  line: `from datetime import UTC` -> `ImportError: cannot import name 'UTC'`.
  The official image runs Python 3.10.16 (`provenance.json`
  `image_python_version`); `datetime.UTC` and `enum.StrEnum` are 3.11. The
  floor test from the deepseek incident (`tests/worker/test_pod_python_floor.py`)
  parses every shipped file at `feature_version=(3, 10)`, which catches
  *syntax* the floor lacks and nothing else; this was a *name* the floor
  lacks. Two fixes and one correction. (A) `arena/worker/compat.py` is the
  one place the older spellings live (`UTC = timezone.utc`, a `StrEnum`
  backport under `sys.version_info < (3, 11)`); `arena/worker/server.py`,
  `arena/worker/util.py` and the runtime scripts that stamp timestamps
  (`runtimes/*/fetch_weights.py`, `runtimes/glm_ocr/fetch_layout_model.py`)
  import from it. (B) The floor test gains a static scan of every shipped
  file for names newer than the floor (`datetime.UTC`, `enum.StrEnum`,
  `typing.Self`, `tomllib`, `asyncio.timeout`, `contextlib.chdir`,
  `itertools.batched`, ...), alias-aware (`import datetime as dt; dt.UTC`),
  with the compat module exempt and a self-check that the scan catches
  exactly the paddle line. (C) The correction: the first draft put the compat
  module under `arena/core`, and `test_worker_server_imports_in_a_stdlib_only_interpreter`
  refused it -- `arena/worker/bundle.py` ships `arena/__init__.py`,
  `arena/constants.py`, `arena/worker` and `prompt_registry`, deliberately
  *not* `arena/core` (the worker must not depend on it). The floor test now
  derives its file list from `ARENA_BUNDLED_FILES`/`ARENA_BUNDLED_DIRS`
  instead of a hand-written one, so it can no longer disagree with the
  bundle about what is on the pod, and `arena/core` keeps its 3.11
  spellings (it runs on the campaign venv only). Every bundle was
  republished on the fixed worker (`receipts/bundles/*.json`, 2026-09-04
  07:07 KST); `tests/worker` + `tests/core` 826 passed, `tests/runtimes` 859
  passed; `ruff` and `mypy` clean on `arena/worker` and `arena/core`.

- **D66 the pod start command fetches the bundle with Python when the image
  has neither curl nor wget, before it would need apt-get (hpd_parsing,
  pods `lht6n046kt7pio` and `lxuzn8dlhf9a5t`, 2026-09-04).**

  hpd_parsing's official image finally pulled (35 minutes of
  `b816f1490294 Retrying` on the first H100 host; 30 seconds on the second,
  which had it cached) and the container then restarted every 16 s:
  `[arena] no curl and no wget; installing curl` -> `E: List directory
  /var/lib/apt/lists/partial is missing. - Acquire (13: Permission denied)`
  -> `curl: command not found` (`receipts/canary-driver-hpd_parsing.json`,
  container lines). D18's fetch chain was curl, wget, then apt-get; the image
  runs as `USER hpd` (D54), so the apt-get route can never succeed there, and
  a non-root image with no curl was not a case D18 had met. Python is the one
  fetcher every arena image has -- the start command probes for it moments
  later to run the worker -- so `arena/worker/bundle.py` now tries `python3`,
  then `python`, between wget and apt-get, and fetches with
  `urllib.request.urlretrieve`. The sha256 gate is unchanged and still sits
  between the fetch and the extraction. The driver's restart-loop signature
  condemned the second pod in 0.5 min, which is the D47/D54 machinery doing
  what it is for; the first pod's 29 minutes were the image pull, not the
  loop. Test `test_start_cmd_fetches_with_python_before_it_would_need_apt_get`
  plus the updated rendered-command fixture in
  `tests/worker/test_bootstrap_handoff.py`; `tests/worker` 375 passed; `ruff`
  and `mypy` clean. No bundle is affected (the start command is rendered by
  the driver at pod creation); hpd_parsing relaunched.

- **D67 the worker's state directory follows the writable arena root, not
  `/workspace/arena` unconditionally (paddleocr_vl_1_6 pod `zvfrug8rrsdsya`,
  hpd_parsing pod `3lzp9czvko2ao3`, 2026-09-04).**

  Both pods got further than any before them: paddle's genai server answered
  `/v1/models` 200 on the vendor's vLLM 0.10.2 (D61 confirmed), the D65
  worker imported on Python 3.10, hpd's vLLM API server came up on an H100
  PCIe after the D66 python fetch -- and then `WorkerCore.__init__` died on
  `mkdir /workspace/arena/inputs` -> `PermissionError: [Errno 13]
  /workspace`. `arena/worker/config.py` defaults `ARENA_STATE_DIR` to
  `/workspace/arena` (the RunPod volume, root-owned), and D54 moved only
  `ARENA_ROOT` for non-root images. The bootstrap template in
  `arena/worker/bundle.py` now probes `/workspace/arena` right after
  `ARENA_ROOT` is settled; when it cannot be created or is not writable it
  exports `ARENA_STATE_DIR=$ARENA_ROOT/state` and says so on stdout. The
  worker itself is unchanged and still strict (no silent fallback inside it:
  the choice is made once, in the shell, and printed). Test
  `test_bootstrap_routes_the_worker_state_dir_through_a_writable_root`;
  `tests/worker` 376 passed. Every bundle republished (the template is in
  all of them); paddle and hpd relaunched.

- **D68 mineru_vlm runs the vendor's own resolution of `mineru[core]` --
  the arena's re-pins are removed -- and the bootstrap self-test uses the
  CLI's real backend name (pod `8sb0n4zqo8tapn`, 2026-09-04).**

  The D64 diagnostics answered two questions. The pip-freeze diff of the
  arena pins against what `mineru[core]` resolves on the
  `vllm/vllm-openai:v0.21.0` image: `transformers 4.57.6 -> 4.57.3`,
  `mineru_vl_utils 1.2.1 -> 1.0.5`, `huggingface_hub 0.36.2 -> 0.35.3`,
  `accelerate 1.13.0 -> 1.14.0` (plus the `[cli]` extra's InquirerPy). And,
  on that pinned stack, the layout step again answered every page with
  `]]<|><|><|><|>` (loguru DEBUG `Layout raw output` + `Layout output does
  not match expected format`, warm-up included). `mineru-vl-utils` 1.0.5 vs
  1.2.1 was ruled out by reading both tags (identical client and vLLM-engine
  code; 1.1/1.2 add llama-cpp only), which leaves the transformers 4.57.3 vs
  4.57.6 processor code path and the hub downgrade as the only departures
  from the vendor stack. The vendor Dockerfile for this MinerU tag is
  `FROM vllm/vllm-openai:v0.21.0` + `pip install -U 'mineru[core]>=3.4.0'`
  and nothing else, so `runtimes/mineru_vlm/bootstrap.sh` now installs
  exactly that (the pinned MinerU git revision, no re-pins) and records the
  resolved versions by name (`vendor_resolution=` in the receipt, `[arena]
  vendor resolution:` in the log). The self-test's `-b vlm-vllm-engine`
  was a name from an older CLI; 3.4.5 accepts `vlm-engine` (usage error,
  exit 2, on pod `8sb0n4zqo8tapn`), and it is corrected so the next pod
  gives the CLI-vs-adapter answer. If the vendor stack still answers
  garbage, the fault is the image + weights + GPU combination itself and the
  model is reported as such, with the receipt; it is not excluded.

- **D69 the Opus lane knows the 5-hour session-limit text, and the lane is
  driven across windows by a loop that waits for the reset (2026-09-04).**

  At 07:17:59 KST, 213 pages into the 4-worker run, `claude -p` answered
  two pages with `is_error: true` and the text "You've hit your session
  limit · resets 7:50am (Asia/Seoul)". `arena/opus/limits.py` knew "usage
  limit", "limit reached", "weekly limit" and the rest of the documented
  wording family, but not "session limit"; the payload named no model, so
  the attribution check filed both pages as FAILED/UNKNOWN "unexpected
  model", stopped the pool with `stop_reason: unexpected_model` and no reset
  hint, and the lane sat idle for 75 minutes. Two page receipts that were
  never page results are moved to
  `runs/opus5_subscription/superseded-session-limit-20260904T071759/` (with
  a WHY.md) so `run` re-runs them (D63). The classifier gains "session limit"
  and "hit your ... limit" as SUBSCRIPTION_LIMIT and a reset pattern for a
  bare clock time with am/pm and a zone; test
  `test_the_session_limit_text_of_2026_09_04_is_a_subscription_limit_with_its_reset`.
  Measured window: 157 pages at 2 workers (06:25-06:54) + 213 at 4 workers
  (06:54-07:18) = 370 pages before the limit, with this orchestration
  session sharing the same account. The lane is now started by
  `opus_loop.ps1`: `run --workers 4 --execute`; exit 75 -> parse the
  checkpoint's reset hint, wait until then + 3 min, run again; exit 0 ->
  done; any other exit -> stop for a human. It never changes the model and
  never touches an API key. 4,753 pages remain; at ~370 pages per window
  that is ~13 windows, so the founder should expect the lane to take days
  and to compete with interactive use of the same subscription.

- **D70 the pod's `ARENA_PROMPT_FILE` is re-rooted to the bundled registry
  when the controller's `/opt/arena` path does not exist on the image
  (2026-09-04).**

  The controller pins every pod's prompt file at
  `/opt/arena/prompt_registry/<prompt_id>.txt` (`POD_PROMPT_DIR` in
  `arena/controller/prompts.py`) and the worker prefers `ARENA_PROMPT_FILE`
  over the registry directory (D17). That is right on every root image and
  wrong on an image whose bundle D54 relocated: hpd_parsing pod
  `prjumbgggb0e33` (H100, 2026-09-03T23:41Z) got past D66 and D67, warmed up
  under `/home/hpd/arena`, and the worker refused to start with
  `WorkerConfigError: prompt file not found ... (resolved from
  ARENA_PROMPT_FILE)` after ~7 min ($0.41). paddleocr_vl_1_6 pod
  `m67wcj2zkw5vw0` was launched before that cause had been read and ends the
  same way. The bootstrap template in `arena/worker/bundle.py` now, right
  after it exports `ARENA_PROMPT_REGISTRY_DIR`, checks whether
  `ARENA_PROMPT_FILE` is set and absent and whether the same basename exists
  in the registry that travelled with the bundle; if so it re-exports the
  bundled path and logs `[arena] ARENA_PROMPT_FILE ... absent; using bundled
  ...`. A prompt that exists nowhere still fails closed in the worker (D17).
  The controller's path and the job id's prompt binding (prompt_id + sha,
  section 2) are unchanged; only where the same bytes are read from moves.
  Test `test_bootstrap_re_roots_a_relocated_prompt_file_to_the_bundled_registry`
  (tests/worker 377 passed); all 11 bundles republished (hpd_parsing
  `bf449b59...`, paddleocr_vl_1_6 `06849dac...`, mineru_vlm `68c0be8b...`).
  Incident receipts: `receipts/incidents/hpd_parsing-prjumbgggb0e33-*.json`.

  D68 follow-up, same day: mineru_vlm pod `zzxxxq8mnyy659` (A40,
  2026-09-03T23:41Z) installed the vendor stack as D68 intended and was then
  refused by the bootstrap's own preflight, which still asserted the exact
  pins D68 had removed (`FATAL architecture preflight: transformers is
  4.57.6, this runtime pins 4.57.3`, 7.1 min, $0.06). The preflight now
  checks MinerU's own ranges for the pinned revision (transformers
  [4.57.3, 5.0.0), mineru-vl-utils [1.0.5, 2.0.0)) and records the exact
  versions it found instead of asserting them. Incident receipt:
  `receipts/incidents/mineru_vlm-zzxxxq8mnyy659-*.json`. Both models are
  relaunched on the new bundles (hpd_parsing pod `f15sgcc1cvuqrv`, mineru_vlm
  pod `t0e8yz3oobso7i`).

- **D71 the driver keeps the container log at READY too, so the bootstrap's
  own record survives a pod that comes up and answers garbage (2026-09-04).**

  hpd_parsing passed 15/15 on pod `f15sgcc1cvuqrv` (H100, first pod after
  D70) and has its proof and forecast row. mineru_vlm pod `t0e8yz3oobso7i`
  (A40, bundle `68c0be8b...`, the vendor's own stack: mineru 3.4.4 at the
  3.4.5 tag, mineru-vl-utils 1.2.1, vllm 0.21.0, transformers 4.57.6, torch
  2.11.0+cu130) came up in 8 min, served all 15 pages in ~0.6 s each, and
  the D62 post-run tail shows MinerU's layout stage getting the string
  `]]<|><|><|><|>` from the VLM on every page -- the same answer the
  re-pinned stack gave on pods `r0yal3hocpipsm` and `733khrz3mcscrw`. The
  re-pins were therefore never the cause. The lines that would separate
  weights/tokenizer/prompt-format from the arena adapter -- the D64 CLI
  self-test verdict (`[arena] selftest: ...`), the vendor resolution line and
  vLLM's weight-loading warnings -- were printed before READY, and no
  receipt kept them: the readiness tail exists only when readiness fails,
  the post-run tail is 400 page-time lines, and the provider `get_logs`
  receipts hold request metadata, not lines. Incident receipt
  `receipts/incidents/mineru_vlm-t0e8yz3oobso7i-*.json`; the driver receipt
  of that attempt is preserved under `receipts/incidents/raw/`.

  The driver now reads the container log once more, right after
  `_mark_ready` and before the first page, through the same helper, scrub
  and per-line withholding as D62, and writes it to the driver receipt as
  `bootstrap_log` (`captured_at`, `container_log_tail`, `container_log_note`,
  `container_log_reads`). A read failure is a note (`ready-time container
  log not captured: ...`) and never stops the canary. Tests
  `test_a_pass_keeps_what_the_runtime_printed_while_coming_up` and
  `test_the_ready_time_log_read_failure_is_recorded_not_fatal`
  (tests/controller 325 passed). The driver is controller-side, so this
  changes no bundle; a mineru_vlm re-run still needs a bundle change of its
  own (section 9.3), and the one that pays for a pod is the self-test
  printing the CLI's raw layout answer so the receipt says whether the
  vendor path fails the same way without the arena adapter in the loop.

- **D72 the Full Run has a driver: `run --execute` provisions, dispatches every
  pending page, returns the pod, and repeats until nothing is left or a stop
  rule fires (2026-09-04).**

  Until now `run --execute` provisioned one pod and returned, and it refused
  every bootstrap model before that at the registry ("missing
  runtime_image_digest"), because `run` loaded the registry without the
  bundle digest `canary` derives from the publish receipt (D15/D21). Ten of
  eleven canaries are PASS on bootstrap pods, so the Full Run path had never
  been exercisable. `arena/controller/full_run.py` (`run_full`) is the canary
  driver's shape over the whole queue: bundle receipt -> eligibility (canary
  PASS and a baked image or a founder waiver, checked in the driver as well as
  the CLI) -> every manifest page planned into the queue (idempotent;
  stale RUNNING/ASSIGNED jobs from a driver that died are returned to PENDING;
  section 9.3 keeps settled jobs settled) -> pods in sequence, each one:
  provision -> readiness -> READY-time log (D71) -> PENDING pages in shard
  dispatch order, one at a time through `run.dispatch_page` -> stop rule ->
  drain -> post-run log (D62) -> stop+delete in a `finally` -> confirm gone
  -> ledger -> run summary -> `freeze_model` when nothing is undecided.
  Stop rules after every page: `runs/<model>/STOP` (consumed, D63's rule),
  `--page-limit` for a rehearsal, the D10 lifetime (6 h) less a 15-minute
  margin so the page in flight and the teardown finish inside it (the next
  pod resumes), the section 15.13 budget caps (hard cap ends the run; soft
  cap allows no new pod), and twenty consecutive failures (a runtime that
  stopped answering is not rented again). `--max-pods` bounds one invocation
  (default 1); each pod after the first goes back through the D6 gate with the
  spend so far counted (`next_pod_allowed`), so one receipt never quietly pays
  for six pods. Status vocabulary: COMPLETE (nothing undecided, frozen),
  PARTIAL (pages remain: max-pods, page-limit, STOP, soft cap), STOPPED (hard
  cap, consecutive failures, authorization refused), ERROR. Receipt
  `receipts/full-run-driver-<model>.json` (`tavonel.arena.full_run_driver.v1`)
  with one record per pod. `run` now resolves the bootstrap digest the way the
  canary does (`_registry_entry_for_run`), so the refusal a bootstrap model
  meets is the real one: "no founder waiver receipt exists at
  `receipts/waivers/<model>-bootstrap-full-run.json`" (section 15.1). Tests:
  `tests/controller/test_full_run_driver.py` (12: every page and freeze;
  second invocation rents nothing; lifetime margin then resume; max-pods;
  refused next-pod authorization; STOP file consumed; page limit; bootstrap
  without waiver rents nothing; waiver permits; consecutive failures stop;
  readiness failure is returned; freeze refusal is a note);
  tests/controller 337 passed. DRY_RUN_VALIDATED against the fakes; not yet
  run against a provider: that needs the founder's `phase2_full_run` receipt
  and, for every bootstrap model, the waiver file above.

- **D73 mineru_vlm: the vendor CLI is correct and the adapter path is not, on
  the same pod; the next pod bisects the call site (2026-09-04).**

  Pod `o6eq3bm2ei7r9c` (A40, bundle `05ff5d58...`) ran with D71 and the
  self-test that keeps the CLI's answer. The receipt's `bootstrap_log` holds
  both halves: `mineru -p warmup.png -o out -b vlm-engine` in its own process
  produced the right markdown for the synthetic page (`exit=0
  markdown_bytes=362`, the page's text and its table), and one minute later
  the arena worker's in-process warm-up of the same file through the adapter
  got `Layout raw output: ]]<|><|><|><|>` and `markdown_chars=0 blocks=0`;
  all 15 benchmark pages then answered the same. vLLM's load lines are clean
  (Qwen2VLForConditionalGeneration, one safetensors shard, no missing or
  unexpected weights, FlashAttention 2, custom logits processor on). That
  clears the image, the weights, the GPU and the vendor stack, and leaves the
  adapter's call or the worker-process context. The sources say what the call
  changes: the adapter's `batch_size=1` reaches `VllmEngineVlmClient` and
  only sets the chunk size (a one-page batch is identical to the CLI's
  `batch_size=0`); `read_fn(path, "png")` is the same conversion the CLI
  makes; the `f_*` dump flags do not touch inference. What is left is the
  worker process itself: the adapter's env (`OMP_NUM_THREADS=1`,
  `MINERU_API_MAX_CONCURRENT_REQUESTS=1`), the non-main HTTP-handler thread,
  and whatever the worker imported first. `runtimes/mineru_vlm/selftest_probe.py`
  runs the adapter's exact `do_parse` call in a fresh process under each
  candidate (`adapter-args`, `adapter-args-env`, `adapter-args-thread`) and the
  CLI defaults through the same in-process path (`cli-args`), each with the
  loguru sink at DEBUG so the layout stage's raw answer is captured, and the
  bootstrap prints one `[arena] probe summary:` line last so the READY-time
  capture keeps it. Bundle `945245c6...`, pod `x5kia8xy68w500`. Incident
  receipt `receipts/incidents/mineru_vlm-o6eq3bm2ei7r9c-*.json`. The model is
  not excluded; if every probe answers correctly and only the worker fails,
  the next step is the worker's own warm-up path, not the vendor's.

- **D74 the Full Run gate reads the canary's registry-update receipt, and
  judges the runtime mode the run will actually use (2026-09-04).**

  Two findings from dry-running `run` for the ten PASS models after D72.
  First, every one was refused with "canary_status is PENDING": `arena.registry
  resolve` writes `canary_status: PENDING` and `validate` insists on it, and
  nothing ever applied the verdict the canary driver writes to
  `receipts/registry-updates/<model>.json` (`tavonel.arena.registry_update.v1`,
  sourced from the canary receipt). `model_registry.json` stays a resolve-time
  artifact; the receipt is the evidence, so `run.entry_with_canary_verdict`
  overlays `canary_status` and `full_run_eligible` from it before
  `eligibility`, naming the receipt in the gate's output ("canary verdict PASS
  from paddleocr_vl_1_6.json (source receipts/canary-paddleocr_vl_1_6.json,
  proposed 2026-09-04T00:17:25Z)"). A malformed receipt is refused, not
  ignored; a receipted FAIL refuses even if the registry said PASS. Second,
  with the verdict applied the gate answered "canary PASS and a baked runtime
  image" for models that have no baked image: `eligibility` judged the most
  permissive mode the runtime *allows* (`["baked", "bootstrap"]`), not the mode
  the run would use, so section 15.1's waiver rule never fired. `eligibility`
  now takes `runtime_mode`; `run_full` passes `"bootstrap"` (it is the bundle
  path by construction, D15/D21), the CLI passes the mode it resolved, and a
  mode the runtime forbids is refused with the D25 reason. The gate now says,
  for all ten: "runtime_mode is bootstrap and no founder waiver receipt exists
  at receipts/waivers/<model>-bootstrap-full-run.json (masterplan section
  15.1)". That receipt (`{"model_key": "<model>", ...}`, founder decision) and
  the `phase2_full_run` authorization receipt (D6) are what the Full Run
  waits on; the code no longer is. Tests: five D74 cases in
  `tests/controller/test_full_run_driver.py` (receipted PASS makes a PENDING
  entry eligible; no receipt refuses; receipted FAIL refuses; malformed
  receipt refuses; a baked-only runtime refuses a bootstrap run);
  tests/controller 342 passed.

- **D75 a pod is counted once: its ceiling until it is billed, its actual after
  (2026-09-04).**

  The D22 cumulative budget added every live provisioning line's `required_usd`
  to every ledger row's `estimated_provider_cost_usd`. Those are the same pods.
  After 46 canary pods the gate read $148 of "cumulative" spend against $10.50
  actually billed, and the first Full Run pod was refused at a soft cap the
  campaign was nowhere near. The ceiling exists because nothing yet says what a
  running pod will cost; the moment its billed row lands, the actual is what it
  cost and the ceiling is a guess about the past. `cumulative_budget` now reads
  the ledger first, collects the pod ids it settled, and skips those pods'
  provisioning lines. The caps are untouched -- soft $300, hard $500 -- and an
  unreturned pod still counts its full ceiling, which is the half of the rule
  that stops eleven pods being rented on one $25 receipt. Corrected reading for
  this campaign: $10.60 billed, no line outstanding. Tests: two in
  `tests/controller/test_bundle_and_gates.py` (a settled pod contributes its
  actual and not its ceiling; an unreturned one still contributes its ceiling).

- **D76 the Full Run runs a model's shards in parallel, one driver per slice
  (2026-09-04).**

  `run_full` rented pods one after another, so `unlimited_ocr`'s 42.6 inference
  hours were 42.6 hours of wall clock. The queue already has the structure that
  fixes it: pages are planned into shards, and two drivers that never touch the
  same shard never dispatch the same page. `--shard-count N --shard-index i`
  gives a driver the slice `position % N == i` of the deterministic dispatch
  order. Three things had to follow the slice, not the model: the stale-job
  requeue at start (a driver that returned another driver's RUNNING job to
  PENDING would hand a page in flight to a second pod), the stop condition (the
  model's PENDING count would keep a finished slice renting pods for pages it
  does not own), and nothing else -- planning and freezing stay whole-model,
  which is why the last slice out is the one that freezes. `queue.py` also
  gained `PRAGMA busy_timeout=30000`: WAL lets many writers share the file,
  but without a busy timeout sqlite3 raises "database is locked" the first time
  two of thirty-one drivers commit in the same instant. Campaign plan: 31
  slices over ten models, longest slice ~5.2 h. Tests: five in
  `tests/controller/test_full_run_driver.py`, over a twenty-page manifest in
  shards of ten because the section 15.6 band puts the smallest legal shard at
  ten pages (a slice runs only its own pages; two slices together run every
  page exactly once and rent two pods; a slice leaves another slice's in-flight
  job alone; an index outside its count and an index without a count are both
  refused). tests/controller 350 passed.

- **D77 what modes a runtime permits is read in the runtime's own file
  (2026-09-04).**

  `hpd_parsing`'s Full Run was refused with "runtime_mode 'bootstrap' is not
  allowed by runtimes/hpd_parsing/runtime.json (['baked']; D25)" -- and
  runtime.json says `["baked", "bootstrap"]`. The list came from
  `model_registry.json`, which `arena.registry resolve` wrote once; hpd's
  runtime.json was corrected afterwards, and its canary then ran, and passed,
  on a bootstrap pod. The message named the right file and quoted the wrong
  one. `_with_runtime_modes` overlays the runtime spec's own list onto the
  registry entry before the gate, printing both when they differ, which fixes
  the refusal without re-resolving the registry mid-campaign and disturbing the
  digests the frozen canaries depend on. Tests: the baked-only refusal now sets
  the mode where the message says it comes from, plus a case that a stale
  registry no longer refuses a run its runtime permits.

- **D78 mineru_vlm: the vendor CLI parses through an API server, and that
  server uses the async engine (2026-09-04).**

  Pod `x5kia8xy68w500` ran the four D73 probes. All four returned the same
  `]]<|><|><|><|>` layout answer -- including `cli-args`, the CLI's own default
  kwargs. That kills the kwargs hypothesis outright: the adapter's `batch_size`,
  its `f_*` flags and its env are not what breaks the parse. Reading MinerU at
  the pinned revision says why the CLI still gets it right: since 3.4.4 the
  `mineru` command does not parse in its own process at all. `run_orchestrated_cli`
  starts a `LocalAPIServer` and posts to it, and the server parses through
  `aio_do_parse` -> `aio_doc_analyze` -> `get_vlm_engine(inference_engine='auto',
  is_async=True)`, while every probe and the adapter go through `do_parse` ->
  `doc_analyze` -> `get_vlm_engine(..., is_async=False)`. The remaining variable
  is the engine, so the next pod asks it directly: `engine-ids` prints what
  'auto' resolves to on each path, and `aio-cli-args` and `aio-adapter-args`
  run the async path in-process. If the async path parses correctly the adapter
  moves to it; if it does not, the adapter attaches to a vendor server the way
  the CLI does. The model is not excluded either way.

- **D79 mineru_vlm: MinerU's two engines do not agree, and only the async one
  parses (2026-09-04).**

  Pod `8uzvgo0oj1vi43` asked the engine directly. `engine-ids` answered
  `sync=vllm-engine async=vllm-async-engine`, and both async probes -- the
  CLI's default kwargs and the adapter's own -- returned 362 bytes of correct
  markdown with the layout answer `<|box_start|>081 057 207 066<|box_end|>`
  and no format warning, in the same process where the sync path returns
  `]]<|><|><|><|>` and an empty body. Four D73 probes had already cleared the
  kwargs, the env and the calling thread; D78 explained why the vendor command
  looked correct all along (it starts a local API server, which is on the
  async path). So the engine was the variable. `adapter.py` now calls
  `aio_do_parse` on an event loop the backend owns on its own thread -- the
  engine binds to the loop it was created on, so a fresh `asyncio.run` per
  page would abandon the cached predictor after the first -- and
  `runtime.json` pins `expected_vlm_engine` to `vllm-async-engine`, with the
  adapter still failing closed on anything else. Nothing about the checkpoint,
  the prompt, the pages or the scoring changed: what the four failed canaries
  measured was a broken parse, not a weaker model. The runtime still starts no
  model server; an `AsyncLLMEngine` is in-process. Incident receipt
  `receipts/incidents/mineru_vlm-8uzvgo0oj1vi43-sync-engine-returns-garbage-async-does-not.json`;
  tests/runtimes 859 passed.

- **D80 planning the same model from several drivers at once (2026-09-04).**

  Eighteen of the thirty-one Full Run slices exited within seconds of the
  first parallel launch. Two causes, both in `enqueue`. It asked "does this id
  exist?" and then inserted, which two drivers planning the same model both
  lose: each reads absent, each inserts, and the second dies on
  `UNIQUE constraint failed: jobs.inference_job_id`. And with the connection
  in autocommit, each of the 5,132 inserts took the write lock on its own, so
  nine drivers spent longer queueing than writing and the ones that could not
  get in inside 30 s died on `database is locked`. The insert is now
  `ON CONFLICT(inference_job_id) DO NOTHING` -- the skip is decided by the
  write itself, and it never overwrites, so section 9.3's settled jobs stay
  settled -- and the batch is one `BEGIN IMMEDIATE` transaction, with the busy
  timeout raised to 300 s so a driver that cannot get the lock waits instead
  of failing the run. Test: `tests/controller/test_queue_and_plan.py` races
  four real subprocesses on one file and asserts that exactly 400 rows land
  and every process exits 0; threads would have shared a connection and proved
  nothing.

- **D81 an operational failure is not the model's answer (2026-09-04).**

  The Full Run driver marked every failed page final. A pod that died
  mid-dispatch left its page FAILED with `INFRA_NETWORK`, and nothing returned
  it to PENDING, so a dead pod's page would have been frozen and scored as
  what the model produced -- against the constitution's own rule that an
  operational failure and a semantic one are different problems. The retry
  table in `arena/controller/retry.py` already said which classes are
  retryable and how long to back off; the driver simply never asked it.
  `_retry_if_operational` now consults `retry.decide` after a failure and
  requeues when the allowance is not spent, so a deterministic failure still
  settles after its retries and is never dispatched forever. Tests: an
  `INFRA_NETWORK` answer on the first dispatch ends with every page SUCCESS,
  none FAILED, and the requeue named in the pod's notes; a worker that always
  answers 500 settles every page FAILED after its allowance, with the dispatch
  count bounded. The drivers already running when this landed still hold the
  old module, so their operational failures need a mop-up requeue before
  freeze.

- **D82 a driver that is killed does not return its pod (2026-09-04).**

  The two fixed-list schedulers were replaced by a supervisor and stopped with
  the harness's TaskStop. That kills the process *tree*, so every Full Run
  driver they had launched died with them, and a driver returns its pod from a
  `finally` block it never reached. Twenty pods stayed up with nobody to stop
  them. `cleanup-verify --execute` found and deleted all twenty and confirmed
  across both provider listings that none remained; the jobs they left RUNNING
  come back to PENDING through the next driver for that slice, which is
  section 9.3's own rule and needed no manual edit. Those pods wrote no ledger
  row, because the drivers that owned them were killed, so the campaign's
  billed total understates them until the provider invoice is reconciled.
  The rule this buys: **a process that owns a rented pod is asked to stop, not
  killed.** `runs/<model>/STOP` is the mechanism the drivers already have --
  each one consumes it after the page in flight, returns its pod and exits --
  and the supervisor is stopped only after the drivers are down. This was an
  orchestrator mistake, not an arena defect; it is recorded because the next
  operator will otherwise make it too. Incident receipt
  `receipts/incidents/orchestrator-20260904T0550Z-taskstop-killed-drivers-and-orphaned-20-pods.json`.

- **D83 a slice provisions its own pod (2026-09-04).**

  RunPod treats a pod name as an identity: create with a name that is already
  up and you are handed the pod that is up. The name carries a replica index,
  and the index defaulted to 0 for everyone, so all nine `unlimited_ocr`
  slices asked for `arena-unlimited-ocr-w0-...` and all nine were given the
  same pod. The parallelism was on paper for about forty minutes. The
  measurements survived it -- masterplan section 14 holds
  `max_concurrency_per_worker` at 1 and the worker enforces it with a bounded
  semaphore, so the pages still ran one at a time inside the adapter and no
  output was interleaved -- but nine drivers were queueing behind one GPU.
  A sliced run now defaults `--replica-index` to its own `--shard-index`, and
  distinct pods `arena-unlimited-ocr-w0` through `-w8` were confirmed against
  both provider listings.

- **D84 reserve what the watchdog will actually allow (2026-09-04).**

  D10 permits a Full Run pod six hours and the budget gate reserved all six.
  Measured across the fifty-nine pods that did real work, the median pod
  lived 0.60 h and the longest 1.76 h, because the driver returns a pod as
  soon as its shard is done. So $174.83 of six-hour ceilings stood against
  the $300 soft cap on behalf of pods whose real bill was a tenth of that,
  and the campaign deadlocked: nineteen slices held the whole budget while
  `paddleocr_vl_1_6` sat at 1.2%, `mineru_pipeline` at 7.5% and
  `hpd_parsing` at 11.6% with no pod available to them.

  No cap moved. `--lifetime-hours` already existed and was already a real
  watchdog -- the pod carries `ARENA_MAX_POD_AGE_HOURS` and deletes itself at
  that age -- but the reservation ignored it and priced six hours for a pod
  the run would kill at three. `effective_pod_lifetime_hours` makes the
  reservation and the watchdog the same number, clamped to the D10 ceiling in
  both directions: asking for eight hours reserves and enforces six, exactly
  as before, and a fraction rounds up so the reservation is never cheaper
  than the life it stands for. The Full Run asks for three, which is above
  every pod yet measured. A pod that does hit three hours is deleted with its
  shard unfinished, and section 9.3 returns its RUNNING pages to PENDING for
  the next pod, so the shortened life costs a bootstrap and never a page.

- **D85 a provision-gate receipt is named after the phase that wrote it
  (2026-09-04).**

  `canary_provision_receipt` returned one path per model and all four call
  sites wrote it, so the Full Run overwrote all eleven canary provision-gate
  receipts and each of the thirty-one slices then overwrote the one before
  it. Atomic writes made the loss clean rather than visible. The contract
  test that asserts the on-disk receipt is a canary's is what caught it; the
  test was right and the code was wrong.

  The path now carries the phase and the slice. What was lost is stated and
  not rebuilt: the licence, CUDA and pool verdicts those canary gates
  recorded are gone. What the Full Run is actually gated on survived, because
  it was never on this path -- `receipts/canary-<model>.json` holds each
  canary's own verdict and page results, `receipts/canary-driver-<model>.json`
  its driver record, and `cost/pod_provisioning.jsonl` every canary pod's
  phase, GPU, price-snapshot digest, ceiling and authorization reference.
  Receipt: `receipts/incidents/provision-gate-receipts-20260904T0940Z-full-run-overwrote-every-canary-gate-receipt.json`.
  The canaries are not re-run to refill the files: a fresh pod on a fresh
  price snapshot would be a new measurement wearing an old date.

- **D86 an operational failure does not get frozen (2026-09-04).**

  Sixty-two pages stood FAILED with class `INFRA_NETWORK` and their retry
  allowance spent, across `unlimited_ocr` (27), `monkeyocrv2_b` (30) and
  `glm_ocr` (5). Every one was dispatched before D81, when the driver marked
  any failure final instead of asking the retry table whether the class was
  operational. The messages name what happened: HTTP 404 from pods that no
  longer existed, most of them the twenty the D82 tree-kill orphaned, and
  HTTP 500 from six `monkeyocrv2_b` pods. Freezing those would have scored
  three models on infrastructure that died, and in most cases on an
  orchestrator mistake, against the constitution's own rule that an
  operational failure and a semantic one are different problems. They went
  back to PENDING with the retry count cleared; a page that genuinely fails
  now spends its D81 retries and settles on its own evidence. Nothing in
  SUCCESS was touched, so section 9.3 was not involved. Receipt:
  `receipts/incidents/requeue-20260904T0950Z-operational-failures.json`.

- **D87 freeze refuses a run that has not finished (2026-09-04).**

  `python -m arena.controller freeze --model glm_ocr` was run without
  `--execute`, on the belief that the controller's "Dry run unless --execute"
  line covered it. It does not, and it should not have been assumed to:
  `--execute` marks what spends money, and freeze spends none. It froze
  glm_ocr at 4,179 of 5,132 pages and said nothing that distinguished that
  from a complete run.

  Two faults. The command that seals evidence was outside every gate, and
  `freeze_model` asked the receipt directory what existed rather than asking
  the queue what should exist. A partial manifest is not detectably partial
  once written: `sample_count` counts receipts, and the scoring lane reads
  the marker as the statement that these outputs are final.

  Freeze now asks the queue and refuses while any job is PENDING, ASSIGNED,
  RUNNING or PAUSED, naming how many. SUCCESS, FAILED and QUARANTINED have
  all reached an answer -- QUARANTINED is one of the queue's own terminal
  states and a job resting in FAILED has spent its D81 retries. A deliberate
  partial freeze takes `--allow-incomplete` and stamps the marker
  `complete: false` with the planned and settled counts, so no reader has to
  infer completeness from a receipt count.

  The premature manifest and marker were moved to
  `receipts/incidents/withdrawn-freeze-glm_ocr-20260904T0947Z/` rather than
  deleted -- what was written stays inspectable, and out of the path the
  scoring lane reads. No scoring, report or ablation had read it, and the
  Full Run driver does not consult `FROZEN.json`, so glm_ocr kept running and
  no page was lost. Receipt:
  `receipts/incidents/freeze-20260904T0947Z-glm_ocr-sealed-at-4179-of-5132.json`.

- **D88 a credential prefix is matched where a credential could start
  (2026-09-04).**

  `assert_secret_free` looked for each prefix with `prefix in text`, so an
  occurrence anywhere counted. Three ordinary words end in the letters that
  make one: di`sk-`, ta`sk-`, ma`sk-`. A container log line carrying
  "no disk-space left on device" therefore read as an OpenAI key, and the
  `ReadinessError` that quotes the container log could not be written to a
  driver receipt. Seventy times across six slices the driver rented a pod,
  waited out the 45-minute readiness deadline, and then died writing the
  receipt that records what happened -- so the slice began again from
  nothing, and glm_ocr sat at 82.2% for over an hour with pods that kept
  being replaced.

  The rule now requires the prefix to start a token: the character before it
  must not be a letter or a digit. `sk-abc` at the start of a value, after a
  space, a quote, an `=`, a `:` or a `(` still matches -- every shape a real
  key appears in -- because a real key never has a letter welded to its
  front. One rule is narrowed and no other is touched: the live-secret
  identity check, the presigned-URL check and the opaque-token shape check
  are unchanged, and a value holding a credential this process actually
  loaded is caught by identity before this rule is reached.

  Drivers already running keep the old module, so a `SecretLeak` in a slice
  log after this landed means a pre-D88 driver is still alive; restarting the
  supervisor is what replaces it.

- **D89 the baked images run as a non-root user (Trivy DS-0002,
  2026-09-24).**

  All 12 `runtimes/*/Dockerfile` ended as root. Each final stage now ends on
  `USER`: uid/gid 10001 `arena` (HOME `/home/arena`, the uid `services/api`
  uses) for ten images, and the vendor's own `hpd` / `paddleocr` for
  hpd_parsing and paddleocr_vl_1_6, whose HOME holds what the vendor image was
  tested with (paddle's `~/.paddlex/official_models`). Every existing build
  step, including the Section 38 receipt steps, runs unchanged and as root
  before the switch, so weights, receipts and code stay root-owned and
  read-only to the runtime; nothing under `/opt/arena` is chowned. Only
  `/var/lib/arena`, `/var/lib/arena/state` and `/workspace/arena` belong to the
  runtime user, and the image points `ARENA_FATAL_FILE` and
  `ARENA_MODEL_SERVER_LOG` into `/var/lib/arena`. glm_ocr's entrypoint
  hard-coded `FATAL_FILE=/opt/arena/FATAL`; it now reads `ARENA_FATAL_FILE`
  like the other seven.

  Two things a root runtime had hidden:

  1. `fetch_weights.py` (glm_ocr, infinity_parser2_flash/pro, monkeyocrv2_b,
     olmocr2) and glm_ocr's `fetch_layout_model.py` rewrote the weights
     sidecar on every boot. As non-root that is a `PermissionError` under
     `set -e`. It was also wrong as root: boot runs without `--manifest`, so
     the rewrite replaced the build-time `files_manifest_sha256` with `null`
     -- the value infinity_parser2_pro's `hash_weights_on_load: false` relies
     on. A cache hit now verifies revision and largest-file hash and leaves the
     sidecar alone. Consequence: the load receipt's `cache_hit` on a baked pod
     is the build-time value (`false`), the same as deepseek_ocr2, ovisocr2
     and unlimited_ocr already report.
  2. D67 kept the worker strict and let the bootstrap shell choose the state
     dir. A baked image has no bootstrap shell, and D67's own evidence is that
     the RunPod volume at `/workspace` is root-owned and masks the image's
     `/workspace/arena`. `arena.worker.config.resolve_state_dir` therefore
     falls back to `ARENA_STATE_FALLBACK_DIR` when `/workspace/arena` cannot
     be written -- only when the image names one (all 12 baked images do;
     bootstrap pods do not, and D67 still sets `ARENA_STATE_DIR` for them).
     An explicit `ARENA_STATE_DIR` is never second-guessed. The choice is
     printed on the pod log and published as `state_dir` in the worker's
  public environment, so it is not silent.

  The controller already supplies `ARENA_MODEL_KEY` to each pod (see the pod
  environment contract above). The 12 Dockerfiles no longer duplicate that
  public model identifier in `ENV`; Trivy classified the word `KEY` as a
  possible secret (DS-0031). A direct image run without the required runtime
  identity now fails closed, except vendor entrypoints that set their fixed
  model identity themselves. This change does not alter model weights or the
  controller's identity check.

  Not yet proven: no image was rebuilt and no pod was started. A rebuild gives
  new image digests, which need new build and canary receipts; the old ones
  are history and are not rewritten. Test
  `tests/runtimes/test_nonroot_runtime.py`.
