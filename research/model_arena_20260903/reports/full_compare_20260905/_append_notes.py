from pathlib import Path
p = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905\NOTES.md")
t = p.read_text(encoding="utf-8")
add = """
## Opus+GLM priority (2026-09-05 ~14:41 KST)
- OmniDoc scoring STARTED via `_priority_omnidoc_opus_glm.py` (workers=2) alongside pool; prefixes `md_opus5_subscription` / `md_glm_ocr`.
- GLM OmniDoc: 47 empty md files included as-is (deferred marking on board).
- Corpus: Opus olmOCR prepared (1377); GLM ParseBench prepared. GLM olmOCR RED (1401/1403). Opus ParseBench RED (465/2078) — incomplete SUCCESS set; QA gate blocks prepare.
"""
if "OmniDoc scoring STARTED via `_priority_omnidoc_opus_glm.py`" not in t:
    p.write_text(t.rstrip() + "\n" + add, encoding="utf-8")
    print("NOTES updated")
else:
    print("NOTES already had note")
