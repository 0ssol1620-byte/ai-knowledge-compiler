# NOTES — Model Complementarity Matrix

## Scope
- Built from existing OmniDocBench-style **per-page edit distances** under `omnidoc_raw/`.
- **No re-inference.** Sequential scoring chain left untouched.
- Models: paddleocr_vl_1_6, infinity_parser2_flash, deepseek_ocr2, glm_ocr, opus5_subscription.
- Elements: text_block → text, display_formula → formula, table, reading_order.
- **ALL / overall** surface: **text_block is primary** (most pages). Separate matrices per element; there is no synthetic average-of-elements ALL matrix — use the `text` section as the overall complementarity surface.

## Continuous oracle (primary for router ceiling)
- Clip each page edit to [0,1].
- `alone_mean_edit = mean(edit)` on shared pages of the pair (or all-model intersection for alone tables).
- `alone_score = 1 - alone_mean_edit`.
- `oracle_edit = mean(min(edit_A, edit_B))` — perfect page-wise router picking the better model.
- `oracle_score = 1 - oracle_edit`.
- `oracle_gain_A = oracle_score - alone_score_A` (gain when A is baseline).
- No hard threshold; uses continuous edits.

## Discrete rescue / overlap (tau=0.05)
- Wrong if `edit > 0.05`.
- Rescue rate: `P(B correct | A wrong)`.
- Overlap: `P(B wrong | A wrong)`, `P(both wrong)`.
- Disagreement: `(A wrong) != (B wrong)` OR `|edit_A - edit_B| > 1e-9`.
- Report `P(A wrong | disagreement)` on those pages.
- **tau=0.0 sensitivity:** any nonzero edit = wrong is extremely strict and noisy for near-zero floating edits; we keep tau=0.05 for discrete tables and rely on continuous oracle for ceiling. Primary tables use tau=0.05.

## Pairwise page intersection
- Every pair metric uses **intersection of pages present in both models' per-page JSON** for that element.
- Alone score tables labeled all-intersect use intersection of **all five** models for that element.
- Page-count mismatches across models are expected if some pages failed scoring for one model; see page_counts in JSON.

## File prefixes
- paddle / deepseek: `markdown_quick_match_*_per_page_edit.json`
- flash / glm / opus: `md_<model>_quick_match_*_per_page_edit.json`

## Outputs
- `complementarity_oracle_matrix.md` / `.json`
- `complementarity_rescue_matrix.md` / `.json`
- `complementarity_leaderboard.md`
- `NOTES.md` (this file)
