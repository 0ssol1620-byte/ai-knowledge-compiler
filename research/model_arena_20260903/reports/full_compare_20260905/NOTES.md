# Notes — full_compare_20260905 (corrected scope)

## Scope
Full ~5132 campaign pages across OmniDoc + olmOCR + ParseBench, not OmniDoc-1651-only.
Infinity Pro FOUNDER_EXCLUDED from main board. Flash included at partial SUCCESS coverage (~38%).

## Parallel OmniDoc
- Sequential 9–14h queue stopped; orphan `deepseek_ocr2` kept mid-run.
- `_parallel_omnidoc.py` runs up to 5 models concurrently with unique `md_<model>` prefixes.
- Per-model workers reduced to 3 under parallel load (12 logical CPUs).

## GLM
- INVALIDATED freeze; empties + residual unsettled historically; include with deferred marking.
- Manual OmniDoc prepare: 1646 md / 47 empty.

## Opus
- 1630/1651 OmniDoc prepare; REF under full GT.

## Flash (`infinity_parser2_flash`)
- SUCCESS ~1938 / PENDING+RUNNING ~3194 (~37.8% of 5132).
- ParseBench coverage ~0% so far; olmOCR ~100% of planned olmocr pages.
- Include on board only with explicit partial-coverage caveat; do not wait for full settle.

## ParseBench blocker update
- Prior Levenshtein DLL failure was from wrong interpreter.
- `benchmark/cache/parsebench/.venv` imports Levenshtein successfully.
- File-redirect scoring via that venv / `uv run` in checkout is the path forward.

## olmOCR
- File-redirect via `arena/scoring/drivers/olmocr_driver.py --out ...`
- Prepare batch running for QA-green models.

## Cost
GPU $0. Local CPU only.

## Opus+GLM priority (2026-09-05 ~14:41 KST)
- OmniDoc scoring STARTED via `_priority_omnidoc_opus_glm.py` (workers=2) alongside pool; prefixes `md_opus5_subscription` / `md_glm_ocr`.
- GLM OmniDoc: 47 empty md files included as-is (deferred marking on board).
- Corpus: Opus olmOCR prepared (1377); GLM ParseBench prepared. GLM olmOCR RED (1401/1403). Opus ParseBench RED (465/2078) — incomplete SUCCESS set; QA gate blocks prepare.

## OmniDoc prefix fix (2026-09-05)
`_parallel_omnidoc.yaml_path`: `resolve()` → `absolute()` so `md_<model>` junctions keep unique OmniDoc result prefixes. Priority opus/glm relaunched; original pool still on old configs (shared `markdown_` risk with deepseek).
