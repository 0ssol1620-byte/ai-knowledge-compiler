from pathlib import Path
import re
err = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905\omnidoc_raw\paddleocr_vl_1_6\stderr.log").read_text(encoding="utf-8", errors="replace")
# broader page name patterns from logs: after ] space then name:
names = re.findall(r"\] ([^:\s]+\.(?:png|jpg|jpeg))", err)
print("name_mentions", len(names), "unique", len(set(names)))
print("sample", list(sorted(set(names)))[:8])
print("slow", err.count("match-stage-slow"))
print("formula", err.count("formula-match-candidate"))
print("text-fallback", err.count("text-fallback"))
print("lines", err.count("\n"))
print("last", err.strip().splitlines()[-1][:120])
# Check if matching phase done - look for metric stage keywords
for kw in ["TEDS", "metric", "Aggregat", "Saving", "finished", "end2end", "reading_order", "table_"]:
    if kw.lower() in err.lower():
        print("has", kw)
