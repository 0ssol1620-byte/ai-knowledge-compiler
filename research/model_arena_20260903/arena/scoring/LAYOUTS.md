# Evaluator input layouts — campaign `TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1`

`python -m arena.scoring prepare` turns one model's frozen canonical markdown
into the exact directory shape each official evaluator expects. This file
records where each shape came from, so a reader can check it against the
evaluator's own source rather than trusting this lane.

Every layout below was derived from two places and from nothing else:

- the previous FOLYNTA campaign's scripts —
  `benchmark/runpod_eval/public_core_merge.py`,
  `evaluate_parsebench_official.py`, `evaluate_omnidoc_repeats.py`,
  `evaluate_olmocr_official.py`
- the pinned evaluator sources under `benchmark/cache/{parsebench,omnidoc,olmocr}`

`LAYOUT_REVISION` in `arena/scoring/evaluators.py` is bumped whenever anything
on this page changes, and it is recorded in every `summary.json`.

---

## Common rules

- Input root: `scores/<key>/<benchmark>/evaluator_input/`, where `<key>` is a
  model key or a TAVONEL variant directory name.
- Only pages whose frozen row is `SUCCESS`, not `unresolved`, and whose
  canonical file is on disk are written. Everything skipped is listed with its
  reason in `evaluator_input/_prepare-receipt.json`.
- File names come from the **source** path in `source_manifest.jsonl`
  (`original_source_relative_path`), never from the `case_key`. Evaluators
  match predictions to ground truth by the dataset's own names.
- Canonical markdown is written **verbatim**. No evaluator-specific rewriting
  is applied. The 2026-08 lane applied a MinerU-specific HTML repair
  (`normalize_parsebench_markdown`, tagged
  `parsebench-mineru2605pro-compatible-v1`); applying one model's repair to
  twelve candidates would not be a fair comparison (masterplan §6.1), so this
  campaign does not. That is a deliberate difference from the historical run
  and it is why a historical-lane number here is not byte-identical to the
  2026-08 number even at the same evaluator pin.
- **Windows long paths.** ParseBench ships source names up to 199 characters
  and OmniDocBench ships CJK names. Every write goes through
  `arena.scoring.jsonio.io_path`, which uses the `\\?\` extended-length form,
  because `Path.is_file()` on an over-length path returns `False` instead of
  raising and would silently undercount. The evaluators themselves are third
  party: running them on Windows over these trees is an open risk, and the
  intended host is the CPU evaluation plane (masterplan §40).

---

## ParseBench

**Layout**

```
evaluator_input/<category>/<source stem>.result.json
```

- `<category>` is `Path(original_source_relative_path).parent.name` — one of
  `chart`, `layout`, `table`, `text` in the staged tree (568 / 500 / 503 / 507
  pages).
- `test_id` inside the file is `<category>/<stem>`, which is exactly what
  `test_cases/loader.py` builds (`test_id = f"{group_name}/{file_path.stem}"`
  with `group_name = file_path.parent.name`).
- `evaluation/runner.py` finds predictions with
  `output_dir.rglob("*.result.json")` and filters them by the parent directory
  name, mapping the two text groups onto one directory:
  `_INFERENCE_DIR = {"text_content": "text", "text_formatting": "text"}`.
  So the `text` directory is scored twice, by different rules.

**Document shape** — `parsebench_result_document()`, following
`public_core_merge.build_parsebench_result`:

- `request.example_id`, `request.source_file_path`, `request.product_type`
- `output.task_type` = `parse`, with `pages[0].markdown` and `markdown`
- for `category == "layout"`: `product_type` is `layout_detection` and
  `output.predictions` is a list of `{bbox, score, label, page, content}`

**What is deliberately empty.** `output.predictions` is populated only from an
adapter-emitted `runs/<model>/canonical/<case_key>.elements.json`. When a
runtime emits no element list, the predictions array is empty and the case is
counted in the prepare receipt's notes. The 2026-08 lane could fill it because
it had MinerU's native block JSON with bboxes; twelve heterogeneous runtimes
do not share one. Emitting a placeholder box would be a fabricated
measurement, which `CLAUDE.md` forbids outright.

**Run command** (one process per group, `cwd` = the pinned checkout):

```
uv run parse-bench evaluation run \
  --output_dir=<evaluator_input> --test_cases_dir=<gt docs dir> \
  --product_type=<parse|layout_detection> --group=<group> \
  --report_dir=<evaluator_raw>/<group> \
  --export_csv=True --export_rule_csv=False --export_markdown=True \
  --export_html=True --verbose=False --force=True --multi_task=True \
  --max_workers=8 --enable_teds=True --skip_rules=False \
  --ontology=canonical --verified_only=False
```

Groups and product types, exactly as the 2026-08 lane ran them:
`chart/parse`, `layout/layout_detection`, `table/parse`,
`text_content/parse`, `text_formatting/parse`.

**Result file** per group: `<report_dir>/_evaluation_report.json`, carrying
`total_examples`, `successful`, `failed`, `aggregate_metrics` and
`per_example_results[]` with `metrics[].metric_name` / `.value` and
`metrics[].metadata.rule_results[].passed`.

**Environment**: `uv sync --extra runners` (README "Quick Start"). The
optional `--extra fast` only swaps in a numba TEDS kernel and does not change
scores.

---

## OmniDocBench

**Layout**

```
evaluator_input/markdown/<source stem>.md
```

Flat, one file per page, named after the ground-truth image
(`images/PPT_1001115_eng_page_003.png` → `PPT_1001115_eng_page_003.md`). The
2026-08 lane used `markdown-repeat-1/<stem>.md`; the only difference is the
directory name.

The directory name matters beyond cosmetics: OmniDocBench writes its results
as `result/<prediction dir name>_quick_match_*`, so the name is fixed at
`markdown` and every parser path derives from that constant.

Two pages that map to the same stem are a hard error — silently overwriting
one prediction with another would score the wrong page.

**Config** — written to `evaluator_raw/omnidoc-config.yaml`, field for field as
`evaluate_omnidoc_repeats.render_config` produced it: `text_block`,
`display_formula`, `table` (TEDS + Edit_dist), `reading_order`,
`match_method: quick_match`, `quick_match_truncated_timeout_sec: 60`,
`match_timeout_sec: 90`, `timeout_fallback_max_chunk_span: 10`,
`timeout_fallback_order_penalty: 0.10`. CDM is not requested: the portable
evaluator lane has no validated rendering toolchain, and that exclusion is
recorded rather than hidden.

**Run command** (`cwd` = the pinned checkout):

```
python pdf_validation.py --config <evaluator_raw>/omnidoc-config.yaml
```

**Result files**, copied out of `<checkout>/result/` into
`evaluator_raw/end2end/`:

- `markdown_quick_match_metric_result.json` — the official metrics
- `markdown_quick_match_text_block_per_page_edit.json`
- `markdown_quick_match_display_formula_per_page_edit.json`
- `markdown_quick_match_table_per_page_edit.json`
- `markdown_quick_match_reading_order_per_page_edit.json`
- `markdown_quick_match_table_per_table_TEDS.json` — keyed
  `<page file name>_[<table index>]`

**Environment**: conda env on Python 3.10 (`requires-python >=3.10,<3.12`),
then `pip install -e .`; the project pins every dependency with `==`.

---

## olmOCR-Bench

**Layout**

```
evaluator_input/pdfs/<...>.pdf                                  linked from GT
evaluator_input/<rule file>.jsonl                               copied from GT
evaluator_input/<candidate>/<path under bench_data/pdfs>/<stem>_pg<page>_repeat1.md
```

`benchmark.py` matches candidate files with
`^{re.escape(md_base)}_pg\d+_repeat\d+\.md$` against the path **relative to
the candidate folder**, where `md_base` is the PDF's path relative to `pdfs/`
without its extension. So `bench_data/pdfs/arxiv_math/2502.15977_pg21.pdf`
becomes `<candidate>/arxiv_math/2502.15977_pg21_pg1_repeat1.md`. The page
number is one-based; the staged manifest's `page_index` is zero-based, so the
name uses `page_index + 1`. Every olmOCR-bench source is a single-page PDF, so
in practice this is always `_pg1_`.

**Why the bench root is rebuilt.** `benchmark.py` reads the PDFs, the rule
`.jsonl` files and the candidate directories from **one** directory. The
ground-truth tree under `benchmark/datasets/acquired/public-core` is read
only, so `stage_olmocr_bench_root()` populates the campaign-owned input root
instead: PDFs by hard link where the filesystem allows it and by copy where it
does not, rule files by copy. Nothing is written under `benchmark/`.

**Run command** (`cwd` = the pinned checkout):

```
python arena/scoring/drivers/olmocr_driver.py \
  --evaluator-dir <checkout> --bench-dir <evaluator_input> \
  --candidate <key> --out <evaluator_raw>/benchmark/official-result.json
```

The driver calls the checkout's own `evaluate_candidate` — the official
scoring function, unmodified — and serialises what it returns. `benchmark.py`
prints its scores to stdout and keeps the per-test outcomes in memory only;
masterplan §12.1 asks for individual test pass/fail, so the driver exists to
capture them. The aggregation is the evaluator's: the overall score is the
mean of the per-`jsonl` pass rates, not the flat pass rate over all tests.

**Environment**: `pip install -r requirements.txt`, then
`python -m playwright install chromium` for the math rendering tests.

---

## Evaluator checkouts

```
scores/_evaluators/<benchmark>/<revision>/
```

Made with, in this order:

```
git clone --no-checkout <clone source> scores/_evaluators/<benchmark>/<rev>
git -C scores/_evaluators/<benchmark>/<rev> checkout <rev>
```

The clone source is the local mirror under `benchmark/cache/<dir>` when the
requested revision is the FOLYNTA historical pin (the mirror is at exactly
that revision), and the upstream URL otherwise. `benchmark/cache` is a clone
source and is never checked out, patched or written to.

`--dry-run` prints these commands, the setup commands and every evaluator
command without running any of them.
