import sqlite3, json
from pathlib import Path
from datetime import datetime, timezone

db = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\queue\campaign.sqlite")
conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
cur = conn.cursor()
print("CAMPAIGN_STATE")
for k,v,u in cur.execute("SELECT key, value, updated_at FROM campaign_state ORDER BY key"):
    print(f"{k}={v} updated={u}")
print("MODELS")
for r in cur.execute("SELECT model_key, state, canary_status, full_run_eligible, updated_at FROM models"):
    print(r)
# infinity recent progress rate
rows = cur.execute("""
SELECT state, COUNT(*), MAX(updated_at), MIN(started_at), MAX(finished_at)
FROM jobs WHERE model_key='infinity_parser2_flash' GROUP BY state
""").fetchall()
print("INFINITY_JOBS")
for r in rows:
    print(r)
# last hour success finishes
recent = cur.execute("""
SELECT COUNT(*) FROM jobs
WHERE model_key='infinity_parser2_flash' AND state='SUCCESS'
AND finished_at >= datetime('now', '-2 hours')
""").fetchall()
print("infinity_success_last_2h", recent)
# try parse finished_at formats
sample = cur.execute("""
SELECT finished_at FROM jobs WHERE model_key='infinity_parser2_flash' AND state='SUCCESS' AND finished_at IS NOT NULL
ORDER BY finished_at DESC LIMIT 5
""").fetchall()
print("recent_finished", sample)
