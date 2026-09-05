from pathlib import Path
import json, re
from datetime import datetime, timezone, timedelta
REPORT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905")
kst = timezone(timedelta(hours=9))
now = datetime.now(kst).strftime("%Y-%m-%d %H:%M KST")
launch = json.loads((REPORT / "priority_opus_glm_launch.json").read_text(encoding="utf-8-sig"))
prio = launch.get("priority_omnidoc_pid")
status = REPORT / "STATUS.md"
text = status.read_text(encoding="utf-8-sig")
# Update supervisor PID line and add fix note under How launched
text = re.sub(r"- Supervisor PID: \*\*[0-9]+\*\*", f"- Supervisor PID: **{prio}** (relaunched {now} after prefix fix)", text, count=1)
fix_note = f"""
### Prefix fix ({now})
- Bug: `_parallel_omnidoc.yaml_path` used `Path.resolve()` which followed `md_<model>` junctions → basename collapsed to `markdown` → all scorers wrote `markdown_quick_match_*` (clobber risk vs orphan deepseek).
- Fix: `yaml_path` now uses `Path.absolute()` (keeps `md_<model>` basename). OmniDoc `save_name` = `md_<model>_quick_match`.
- Priority opus/glm **killed and relaunched** with fixed configs (prediction paths now end in `md_opus5_subscription` / `md_glm_ocr`).
- Existing pool (hpd/mineru/monkey/ovis) + deepseek **left running** (founder: do not kill). They still have the pre-fix resolve() configs — **known clobber risk on `markdown_`**; recommend restart of pool after deepseek harvest, or accept deferred harvest via shared prefix.
"""
if "### Prefix fix" in text:
    start = text.find("### Prefix fix")
    end = text.find("\n### ", start + 1)
    if end == -1:
        end = text.find("\n## ", start + 1)
    text = text[:start] + fix_note.strip() + "\n\n" + (text[end+1:] if end != -1 else "")
else:
    anchor = "### ETA"
    if anchor in text:
        text = text.replace(anchor, fix_note.strip() + "\n\n" + anchor, 1)
    else:
        text += "\n" + fix_note
text = re.sub(r"Updated: \*\*[^*]+\*\*", f"Updated: **{now}**", text, count=1)
status.write_text(text, encoding="utf-8")
print("STATUS updated", now, "prio", prio)
# NOTES
notes = REPORT / "NOTES.md"
nt = notes.read_text(encoding="utf-8")
add = """
## OmniDoc prefix fix (2026-09-05)
`_parallel_omnidoc.yaml_path`: `resolve()` → `absolute()` so `md_<model>` junctions keep unique OmniDoc result prefixes. Priority opus/glm relaunched; original pool still on old configs (shared `markdown_` risk with deepseek).
"""
if "yaml_path`: `resolve()` → `absolute()`" not in nt and "yaml_path: resolve() -> absolute()" not in nt:
    notes.write_text(nt.rstrip() + "\n" + add, encoding="utf-8")
    print("NOTES updated")
