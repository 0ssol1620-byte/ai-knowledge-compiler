from pathlib import Path
import json, re
from datetime import datetime, timezone, timedelta
REPORT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905")
kst = timezone(timedelta(hours=9))
now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
launch = json.loads((REPORT / "priority_opus_glm_launch.json").read_text(encoding="utf-8-sig"))
prio_pid = launch.get("priority_omnidoc_pid")
qa_pid = (REPORT / "qa_prepare_opus_glm.pid").read_text(encoding="utf-8-sig").strip() if (REPORT / "qa_prepare_opus_glm.pid").exists() else "28372"
block = f"""## PRIORITY: Opus + GLM OmniDoc STARTED ({now})
**Founder ask:** pull `opus5_subscription` + `glm_ocr` into full-page OmniDoc compare NOW (were only queued behind pool).

### How launched
- Driver: `_priority_omnidoc_opus_glm.py` (imports `_parallel_omnidoc.score_one`)
- Unique prefixes: `md_opus5_subscription`, `md_glm_ocr` (junctions; no shared `markdown_` clobber)
- Workers: **2** each (pool uses 3; CPU was 100% — added alongside, did **not** kill in-flight)
- Log: `priority_opus_glm_omnidoc.log` / `.err.log`
- Launch receipt: `priority_opus_glm_launch.json`

### PIDs / paths
- Supervisor PID: **{prio_pid}**
- `pdf_validation` opus -> `omnidoc_raw/opus5_subscription/` (live ~253MB RSS)
- `pdf_validation` glm -> `omnidoc_raw/glm_ocr/` (live ~253MB RSS)
- Preds: Opus OmniDoc md **1630** nonempty; GLM **1599** nonempty + **47** empty (deferred)
- Opus content-filter FAILED pages naturally excluded (no pred)
- `infinity_parser2_pro` remains FOUNDER_EXCLUDED from main board

### ETA
- Saturated 12-thread CPU + lower workers -> **~90-150 min** wall each; both parallel -> **~2-3 h**
- `comparison_omnidoc_full.md/json` refreshes via `_build_comparison.py` when each finishes

### Full-corpus (olmOCR + ParseBench)
- QA+prepare runner PID: **{qa_pid}** (`_qa_prepare_opus_glm_corpus.py`) — earlier prepare refused missing QA reports; now QA then prepare
- After prepare green: enqueue `_parallel_olmocr.py opus5_subscription glm_ocr` (+ ParseBench when driver ready)
- GLM empties/deferred noted in NOTES

### Still LIVE (untouched)
- orphan `deepseek_ocr2` + pool `hpd_parsing` / `mineru_pipeline` / `mineru_vlm` / `monkeyocrv2_b` / `ovisocr2`
- original pool still queues `olmocr2`, `unlimited_ocr` (opus/glm SKIP if priority finishes first)

"""
status = REPORT / "STATUS.md"
text = status.read_text(encoding="utf-8-sig")
marker = "## PRIORITY: Opus + GLM OmniDoc STARTED"
if marker in text:
    start = text.find(marker)
    nxt = text.find("\n## ", start + 1)
    text = text[:start] + block.strip() + "\n\n" + (text[nxt+1:] if nxt != -1 else "")
else:
    insert_at = text.find("## Corrected scope")
    text = (text[:insert_at] + block.strip() + "\n\n" + text[insert_at:]) if insert_at != -1 else text + "\n" + block
text = text.replace(
    "- queued in same pool after slots free: `olmocr2`, `unlimited_ocr`, `opus5_subscription`, `glm_ocr`",
    "- queued in same pool after slots free: `olmocr2`, `unlimited_ocr` (opus+glm **PRIORITY-STARTED** separately)",
)
text = text.replace(
    "- Queued behind pool: `olmocr2`, `unlimited_ocr`, `opus5_subscription`, `glm_ocr`",
    "- Queued behind pool: `olmocr2`, `unlimited_ocr` — **opus5_subscription + glm_ocr PRIORITY STARTED**",
)
text = re.sub(r"Updated: \*\*[^*]+\*\*", f"Updated: **{now}**", text, count=1)
status.write_text(text, encoding="utf-8")
print("STATUS_OK", now, "prio", prio_pid, "qa", qa_pid)
