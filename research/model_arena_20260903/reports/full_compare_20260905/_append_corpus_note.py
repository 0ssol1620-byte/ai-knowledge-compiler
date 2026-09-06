from pathlib import Path
from datetime import datetime, timezone, timedelta
REPORT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905")
kst = timezone(timedelta(hours=9))
now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
note = f"""
### Corpus prepare outcome ({now})
| Model | olmOCR QA/prep | ParseBench QA/prep |
|---|---|---|
| opus5_subscription | PASS / wrote 1377 (26 skipped) | **RED** 465/2078 missing_case_keys — prepare refused |
| glm_ocr | **RED** 1401/1403 missing 2 keys — prepare refused | PASS / prepared |

- Opus olmOCR score attempted (`_parallel_olmocr.py opus5_subscription`) — see `olmocr_raw/opus5_subscription/` (rc details in logs)
- GLM olmOCR + Opus ParseBench blocked by section-44 QA gate until missing SUCCESS pages exist (note deferred; do not force)
- GLM ParseBench evaluator_input ready for later score
"""
status = REPORT / "STATUS.md"
text = status.read_text(encoding="utf-8")
marker = "### Corpus prepare outcome"
if marker in text:
    start = text.find(marker)
    # replace until next ### or ## Still LIVE
    end = text.find("\n### Still LIVE", start)
    if end == -1:
        end = text.find("\n## ", start + 1)
    if end != -1:
        text = text[:start] + note.strip() + "\n\n" + text[end+1:]
    else:
        text = text[:start] + note.strip() + "\n"
else:
    anchor = "### Still LIVE (untouched)"
    if anchor in text:
        text = text.replace(anchor, note.strip() + "\n\n" + anchor)
    else:
        text += "\n" + note
status.write_text(text, encoding="utf-8")
print("STATUS corpus note appended")
