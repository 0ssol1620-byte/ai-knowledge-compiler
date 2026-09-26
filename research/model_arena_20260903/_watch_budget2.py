import json, sqlite3
from pathlib import Path
root = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
db = root/"queue"/"campaign.sqlite"
con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
print("all tables", [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")])
for t in [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
    n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})")]
    print(f"  {t}: {n} cols={cols}")
con.close()
# opus checkpoint under runs
opus = root/"runs"/"opus5_subscription"
hits = []
if opus.exists():
    for p in opus.rglob("*"):
        if p.is_file() and any(k in p.name.lower() for k in ("status","checkpoint","progress","summary","state")):
            hits.append(p)
print("OPUS_HITS", len(hits))
for p in hits[:30]:
    print(p, p.stat().st_size)
# look for separate opus sqlite
for p in root.rglob("*opus*.sqlite*"):
    if "site-packages" in str(p) or ".venv" in str(p):
        continue
    print("OPUSDB", p, p.stat().st_size)
