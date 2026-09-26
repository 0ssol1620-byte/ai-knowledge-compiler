import sqlite3
from pathlib import Path
root = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
db = root/"queue"/"campaign.sqlite"
con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
print("PODS by state:")
for r in con.execute("SELECT state, COUNT(*), ROUND(SUM(listed_rate_usd_per_hour),4), SUM(gpu_count) FROM pods GROUP BY state"):
    print(r)
open_rows = list(con.execute("SELECT pod_id, model_key, listed_rate_usd_per_hour, gpu_count, provisioned_at, state FROM pods WHERE terminated_at IS NULL"))
print("OPEN_PODS", len(open_rows))
held = 0.0
for r in open_rows:
    rate = float(r[2] or 0)
    held += rate
    print(f"  {r[0][:16]} model={r[1]} rate={rate}/h state={r[4]}")
print(f"open_rate_sum_usd_per_h={held:.4f}")
row = con.execute("SELECT SUM(state='SUCCESS'), SUM(state='PENDING'), SUM(state='RUNNING'), SUM(state='ASSIGNED'), SUM(state='PAUSED'), COUNT(*) FROM jobs WHERE model_key='infinity_parser2_flash'").fetchone()
print(f"infinity S={row[0]} P={row[1]} R={row[2]} A={row[3]} PAU={row[4]} T={row[5]} pct={100*row[0]/row[5]:.1f}")
print("last_success", con.execute("SELECT finished_at FROM jobs WHERE model_key='infinity_parser2_flash' AND state='SUCCESS' AND finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1").fetchone())
# unsettled non-flash
print("unset_nonzero:")
for r in con.execute("SELECT model_key, SUM(state IN ('PENDING','ASSIGNED','RUNNING','PAUSED')) u FROM jobs GROUP BY model_key HAVING u>0"):
    print(r)
con.close()
# opus marker + any local status json
opus_frozen = root/"frozen_outputs"/"opus5_subscription"/"FROZEN.json"
print("opus_frozen_exists", opus_frozen.exists())
# look for opus progress under runs without deep rglob
opus_run = root/"runs"/"opus5_subscription"
if opus_run.exists():
    for p in sorted(opus_run.iterdir())[:30]:
        print("opus_run", p.name, "dir" if p.is_dir() else p.stat().st_size)
