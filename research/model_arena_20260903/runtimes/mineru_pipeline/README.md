# mineru_pipeline — MinerU 3.4.x pipeline backend (PP-OCRv6)

Fast, stable structural baseline (masterplan §3.1, §4). MinerU 3.4's changelog
claims the pipeline OCR stage moved to PP-OCRv6, ~11% better OmniDocBench OCR
accuracy and ~100% faster OCR than 3.3. **Those are the vendor's claims**, quoted
here for context; this campaign measures its own numbers.

Historical FOLYNTA measurement on the 18-page controlled subset (§5.1): 6.959
s/page, text edit 0.036507, structure TEDS 0.946825.

## Official sources, as resolved on 2026-09-03

| what | value | how it was resolved |
|---|---|---|
| code repo | `opendatalab/MinerU` | official repository |
| **code revision** | `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` | tag `mineru-3.4.5-released` → the release page's commit link, cross-checked against `commits/mineru-3.4.5-released.atom` |
| weights repo | `opendatalab/PDF-Extract-Kit-1.0` | `mineru/utils/enum_class.py::ModelPath.pipeline_root_hf` |
| **weights revision** | `ed6b654c018d742e65a17671e379c5e6ecc87ec9` | `GET https://huggingface.co/api/models/opendatalab/PDF-Extract-Kit-1.0` → `sha` |
| largest used file | `models/MFR/unimernet_hf_small_2503/model.safetensors`, 810,036,696 B | `?blobs=true`, restricted to the sub-trees the pipeline downloads |
| largest file sha256 | `9244e2565585c0f89bc3a6eeeea080ef3c588375fc0d536074fe88e80b917cda` | LFS `sha256` |
| base image | `vllm/vllm-openai:v0.21.0` @ `sha256:a230095847e93bd4df9888b33dab956fa9504537b828a23657d2b26fed57b5c9` | Docker Hub registry manifest, anonymous token |
| licence | `LicenseRef-MinerU-Open-Source-License` | `pyproject.toml` at the pinned revision |

### Upstream tagged 3.4.5 without bumping its version string

At `fbb1257a`, `mineru/version.py` still reads `__version__ = "3.4.4"` — the same
value as at the 2026-08 pin `79d6d8d7`. The 3.4.5 release notes contain two
fixes (DOCX table cells with special characters, PDF surrogate-pair restoration),
neither of which touches PNG page parsing. This is recorded, not corrected: the
provenance receipt must carry the **git sha**, and any report that quotes
`mineru.__version__` will read 3.4.4. Do not "fix" that by editing a number.

### The v6 registry pin is a different thing

`benchmark/v6/candidate-registry.yaml` pins `79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7`
as the MinerU **code** revision. `runtime.json.model_revision` here is the
**weights repository** revision, so `provenance.json`'s
`model_revision_cross_check.agrees` is null — there is nothing to compare. The
code pin lives in `provenance.json.runtime_source_revision` and is a later 3.4.x
tag of the same repository.

## Where the provenance lives

`arena/core/schemas/runtime.schema.json` is closed
(`additionalProperties: false`), so `runtime.json` carries only the contract
fields. Everything else — how each revision was resolved, the cross-checks, the
dependency pins, the historical numbers, the vendor claims and every open
question — is in **`provenance.json`** beside it. Nothing was dropped to make the
schema pass.

## Why this inference path

`backend=pipeline`, `method=ocr`, invoked through `mineru.cli.common.do_parse` —
the function the `mineru` CLI itself calls — **in the worker process**. The 2026-08
campaign spawned the CLI once per page, which reloads every pipeline model on
every page; `do_parse` reuses MinerU's `ModelSingleton`, so the models load once
in `load()` and stay warm. Same code path, same parameters, one load.

MinerU consumes PDF bytes; `mineru.cli.common.read_fn` is the documented
image → single-page-PDF converter and is used unmodified.

`method=ocr` (not `auto`) because every arena input is a rendered PNG: `auto`
would branch on text-layer detection that a raster page cannot have. `lang=ch`
is MinerU's own default and is applied identically to all three benchmarks —
per-benchmark language tuning would break the fair-comparison contract (§6.1).

There is no prompt. `load()` refuses a non-empty `prompt_text`.

## Weights strategy: `baked`

`hf download --revision <sha> --include <seven sub-trees>` — only what
`download_pipeline_models()` fetches, not the whole 187-file repository. The
largest of those is checked by sha256; `load()` re-reads the revision stamp and
re-hashes it. `MINERU_MODEL_SOURCE=local` and a baked `mineru.json` point MinerU
at the tree, which also stops the huggingface.co probe MinerU makes at import
time when the source is unset.

## What the canary must confirm

1. **PP-OCRv6 is what actually ran.** `models/OCR/paddleocr_torch/` ships v4, v5
   and v6 files side by side (`ch_PP-OCRv6_small_det_infer.safetensors`,
   `ch_PP-OCRv6_medium_rec_infer.safetensors`,
   `ch_PP-OCRv6_small_rec_infer.safetensors`). Record which files the run loaded.
   Do not take "3.4 uses PP-OCRv6" on faith — that is exactly the kind of
   name-based capability inference the constitution forbids.
2. No outbound network during inference (`MINERU_MODEL_SOURCE=local`).
3. `importlib.metadata.version("mineru")` and the git sha in
   `/opt/arena/receipts/mineru-git-revision.txt` — expect 3.4.4 and `fbb1257a`.
4. p50/p90/p95 s/page against the 6.959 s/page historical figure, and peak VRAM.
5. That every page produced `<stem>.md`, `<stem>_middle.json`,
   `<stem>_model.json` and `<stem>_content_list.json`. A missing markdown file
   is a `POSTPROCESS` failure, not an empty page.
6. `lang=ch` on a Latin-script canary page: confirm it is not a quality
   regression before the full run.

## Known incidents and risks

- **Empty output is not a blank page** (masterplan §41). The adapter returns an
  empty `raw_text` with an `empty_output` warning and never invents content; the
  blank-vs-failed distinction is made downstream from source preflight signals.
- **The v0.21.0 base ships its own transformers.** This image pins
  `transformers==4.57.3` on top, which is what MinerU's `vlm` extra requires and
  what the FOLYNTA bootstrap recorded. vLLM is present in the base but unused by
  the pipeline backend; if a dependency conflict surfaces at canary time, the
  fix is a different base image, not an unpinned upgrade.
- **Licence is unresolved for commercial use.** `LicenseRef-MinerU-Open-Source-License`
  is not a standard SPDX identifier and the v6 registry recorded
  `commercial_use: unknown`. Whether that is acceptable is a founder decision.
  The weights repository carries separate terms again.

## How the pod starts (ARENA_CONTRACT §11.3)

Both modes converge on one script.

| mode | who starts what |
|---|---|
| baked | image `ENTRYPOINT ["/opt/arena/runtime/entrypoint.sh"]` |
| bootstrap | B2 start command extracts and verifies the bundle into `/opt/arena`, symlinks `/opt/arena/runtime` → `/opt/arena/runtimes/mineru_pipeline`, exports `PYTHONPATH=/opt/arena` and `ARENA_RUNTIME_DIR=/opt/arena/runtime`, then execs `bootstrap.sh`, which installs the pinned versions, fetches the pinned weights, writes `/opt/arena/bootstrap-receipt.txt` and `/opt/arena/bootstrap-pip-freeze.txt`, and execs the same `entrypoint.sh` |

`bootstrap.sh` never downloads the bundle and needs no bundle URL: by the time
it runs the bundle is already on disk. `entrypoint.sh` checks that
`runtime.json`, `adapter.py` and `canonical.py` are present under
`$ARENA_RUNTIME_DIR` and refuses to start if they are not. There is no model server to start: MinerU runs in-process, then
execs `python3 -m arena.worker.server`.

## Semantic error class (ARENA_CONTRACT D3)

`adapter.infer()` fills `RawOutput.semantic_error_class` from what it can actually see: an empty markdown body → `OUTPUT_EMPTY`. A missing side-car dump stays a warning: the markdown is still what the model produced.
An empty output is still `SUCCESS` (masterplan §41); the class is the verdict, not the status.

## Second integration pass, 2026-09-03 (ARENA_CONTRACT section 11.5)

### Prompt (D34) - `prompt_kind: none`

`prompt_id` is `mineru_pipeline_no_prompt` and it is **unchanged**. The pipeline
backend takes no prompt: the adapter declares `OFFICIAL_PROMPT = ""` and
`PROMPT_KIND = "none"`, and `load()` refuses a non-empty
`AdapterConfig.prompt_text`. `prompt_registry/mineru_pipeline_no_prompt.txt` is
the **empty file** and its sha256 is the hash of the empty string.

### Which repository is which (D16)

The registry and this file disagreed, and both were naming something real:

| runtime.json field | value | what it is |
|---|---|---|
| `model_repo` / `model_revision` | `opendatalab/PDF-Extract-Kit-1.0` @ `ed6b654c018d742e65a17671e379c5e6ecc87ec9` | **model weights** (Hugging Face); the seven sub-trees the pipeline backend downloads |
| `runtime_repository` / `runtime_revision` | `opendatalab/MinerU` @ `fbb1257a555a3fde78ae5aaaa931e3b3f8fb2883` | **runtime code** (GitHub), tag `mineru-3.4.5-released` |

runtime.json now carries both, so the registry copies each into the field it
belongs in instead of choosing one. Both were re-verified read-only on
2026-09-03 (Hugging Face revision API; GitHub commits API) and both exist.

### Model server ownership (D19) - this runtime has none

MinerU runs **in-process** through `mineru.cli.common.do_parse` inside the
adapter. There is no vLLM or paddlex service and no loopback port, so D19 keeps
`exec "${PYTHON_BIN}" -m arena.worker.server`: there is no server process to
poll, to trap or to orphan, and the worker's exit code is the container's by
construction.

### Prompt registry in the image (D17)

The Dockerfile now carries

    COPY prompt_registry/ /opt/arena/prompt_registry/

so the worker can resolve `ARENA_PROMPT_FILE`
(default `/opt/arena/prompt_registry/<prompt_id>.txt`) in a baked image and fail
closed when it is missing. Bootstrap mode gets the same directory from the
bundle. `.dockerignore` does not exclude it, and a test asserts that.
