# arena/registry — model and evaluator identity (lane A3)

Resolves the two files every other lane reads before it can do anything:

- `model_registry.json` — one record per `arena.constants.MODEL_KEYS`
  (ARENA_CONTRACT §3.7, masterplan §10).
- `evaluator_registry.json` — one record per `arena.constants.BENCHMARK_KEYS`
  plus the pinned olmOCR toolkit (ARENA_CONTRACT §3.8, masterplan §1.1).

```
python -m arena.registry resolve                       # live, records fixtures
python -m arena.registry resolve --use-recorded        # live, reuses recorded URLs
python -m arena.registry resolve --offline --fixtures tests/registry/fixtures
python -m arena.registry validate [--strict-core]
```

Run from the namespace root, or with
`PYTHONPATH=research/model_arena_20260903`.

## Where the numbers come from

| field | source |
|---|---|
| `revision`, `weights.*` | `GET https://huggingface.co/api/models/<repo>?blobs=true` |
| code repository revisions | `GET https://api.github.com/repos/<repo>` + `/commits/<branch>` or `/tags` |
| `license.id` | `cardData.license` on the model card; `null` when absent |
| `runtime_version`, `official_inference_config`, `container_image` | the official model card / official documentation, quoted |
| `historical_evidence` | masterplan §5.1 and §19 |
| `previous_registry_revision` | `benchmark/v6/candidate-registry.yaml`, recorded 2026-08-01 |
| `recommended_gpu_pool` | masterplan §13.3 |
| `gpu_pool_priority` | §13.3 plus the 2026-09-03 RunPod catalog in `catalog.py` |
| `shard_size_hint` | masterplan §15.6 band chosen from the §19 sec/page row |
| evaluator heads | `git ls-remote <repository> HEAD` |
| dataset revision / manifest hash / entrypoint | `benchmark/benchmark-registry.lock.yaml` |

Nothing else. A value the upstream does not publish is `null` and its reason is
appended to the record's `unresolved` list — never zero, never a guess.

## The two estimates, and why they are marked

`gpu_min_vram_gb` is an estimate for every model. When a candidate carries no
explicit override, `models.estimate_min_vram_gb` applies one published rule:

```
required_gb = (published weight bytes / 1e9) * 1.6 + 4
value       = smallest RunPod catalog VRAM tier >= required_gb
```

and writes the arithmetic into `gpu_min_vram_gb_detail.basis`. Three models
override it with a documented reason (MinerU pipeline loads several sub-models,
Infinity-Parser2-Pro is documented at tensor-parallel-size 2, HPD-Parsing is
architecture-bound rather than capacity-bound). The canary replaces every one of
them with a measurement; the registry never promotes an estimate on its own.

`shard_size_hint` is a planning parameter, not a measurement, and
`shard_size_hint_basis` says which masterplan band it came from and whether a
sec/page row existed.

## Record shape and the arena/core/schemas conflict

`license` and `gpu_min_vram_gb` are emitted with masterplan §10's scalar types so
lane A1's `arena/core/schemas/model-registry-record.schema.json` can read the
same record. The structured evidence the lane brief asks for lives beside them in
`license_detail` and `gpu_min_vram_gb_detail`, and `concurrency_plan` carries
what the two-key `concurrency_policy` cannot.

Four things still conflict with lane A1's schema, and `validate` prints them as
`INTERFACE CONFLICT` rather than hiding them:

1. `additionalProperties: false` rejects `weights`, `code_repositories`,
   `historical_evidence`, `previous_registry_revision`,
   `revision_changed_since_2026_08` and `unresolved` — all named in the lane A3
   brief and all load-bearing evidence.
2. `repo` is a required non-empty string; `opus5_subscription` has no repository.
3. `runtime_version` is a required non-empty string; GLM-OCR's card pins nothing,
   so the honest value is `null` with a reason.
4. `runtime_type` has no `paddle`, which ARENA_CONTRACT §6's `runtime.json` enum
   does have and PaddleOCR-VL 1.6 needs.

`--strict-core` makes those fatal for whoever wants to gate on them.

## Offline reproduction

`tests/registry/fixtures/` holds the verbatim public JSON that was fetched on
2026-09-03. `resolve --offline --fixtures tests/registry/fixtures` rebuilds both
files without touching the network, and the CLI test asserts the result is
byte-for-byte identical across runs.

## Rules this package will not bend

- Only `huggingface.co` and `api.github.com` are reachable; every other host
  raises before a socket opens.
- `HF_TOKEN` is read only after a public request answers 401 or 429, and is never
  logged, echoed or written into a payload.
- A GPU model without a 40-hex revision aborts the whole resolution.
- `canary_status` starts `PENDING` and `full_run_eligible` starts `false` for
  every model; `validate` fails if either has been moved by hand.
- `mineru_vlm` is pinned to `{"per_worker": 1, "scale": "replicas_only"}`
  (masterplan §14) and `validate` fails if that changes.
- `gt_paths` are recorded as paths only, inside
  `benchmark/datasets/acquired/public-core`, and are the evaluator plane's
  business alone.

## Second integration pass — D16 / D17 / D31 (2026-09-03)

`model_registry.json` is no longer the owner of a model's identity. Per
`ARENA_CONTRACT.md` §11.5:

- **D16** — `runtimes/<model_key>/runtime.json` owns `model_repo`,
  `model_revision`, the runtime repository/revision and `prompt_id`; `gpu_count_min`
  comes from it too (D5). `arena/registry/runtimes.py` reads those files and
  `resolve_models` applies them **last**, after the candidate specification and
  after `spec.extra`, so the registry is a faithful derived copy. `resolve_models`
  then re-checks its own output with `overlay_disagreements` and raises rather than
  writing a registry that already disagrees with its owner.
- **D17** — `prompt_sha256` comes from `prompt_registry/sha256.json`, keyed by the
  runtime.json `prompt_id`. A `prompt_id` with no entry, or an entry that is not a
  `sha256:<hex>` string, is a hard failure: the worker resolves the same file at run
  time and fails closed, so an unresolved prompt id would only move the failure onto
  a paid pod.
- **D31** — the olmOCR-bench evaluator repository was traced. The receipt is
  `receipts/registry-updates/evaluator-olmocr-provenance.json`; `OLMOCR_PROVENANCE`
  in `evaluators.py` carries the additive fields it justifies. The repository was
  **not** repointed: the historical pin `cfa88c1e…` exists only in
  `jina-ai/olmocr-bench` (GitHub answers 422 for it in `allenai/olmocr`), so
  repointing would destroy the lane that pin defines.

### For B1's preflight

```python
from arena.registry.runtimes import load_overlays, overlay_disagreements

problems = overlay_disagreements(json.loads(model_registry_path.read_text("utf-8")),
                                 load_overlays())
if problems:
    ...  # fail preflight and print every line; each names model.field, both values
         # and the runtime.json path that owns it
```

Regenerate after any runtime.json or prompt change:

```
.venv/Scripts/python.exe -m arena.registry resolve --offline
```
