import sqlite3, json
from pathlib import Path
root = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
# freeze markers / manifests
for pat in ("**/FROZEN*", "**/frozen*", "**/*freeze*", "**/manifest*.json", "**/models/*/state*"):
    hits = list(root.glob(pat))[:40]
    if hits:
        print("PAT", pat)
        for h in hits[:40]:
            print(" ", h, h.stat().st_size if h.is_file() else "dir")

# campaign_state + models table
db = root / "queue" / "campaign.sqlite"
conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
cur = conn.cursor()
print("MODELS_TABLE")
for r in cur.execute("SELECT * FROM models"):
    print(r)
print("CAMPAIGN_STATE")
for r in cur.execute("SELECT * FROM campaign_state"):
    print(r)

# look for freeze dirs under runs or reports
for d in [root/"runs", root/"reports", root/"manifests", root/"freeze", root/"frozen"]:
    if d.exists():
        print("DIR", d)
        for c in sorted(d.iterdir())[:50]:
            print(" ", c.name)
