import sqlite3, json
from pathlib import Path
c=sqlite3.connect(r"file:D:/CodexProjects/ai-knowledge-compiler/research/model_arena_20260903/queue/campaign.sqlite?mode=ro",uri=True)
print("flash jobs", c.execute("SELECT model_key,state,COUNT(*) FROM jobs WHERE model_key LIKE '%flash%' GROUP BY model_key,state").fetchall())
print("all models", c.execute("SELECT model_key, COUNT(*) FROM jobs GROUP BY model_key").fetchall())
# benches for paddle
print("paddle benches", c.execute("SELECT benchmark,state,COUNT(*) FROM jobs WHERE model_key='paddleocr_vl_1_6' GROUP BY benchmark,state").fetchall())
# registry flash
reg=json.loads(Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\model_registry.json").read_text(encoding="utf-8"))
def walk(o,path=""):
    if isinstance(o,dict):
        for k,v in o.items():
            if "flash" in str(k).lower() or (isinstance(v,str) and "flash" in v.lower() and len(v)<80):
                print("reg hit", path, k, v if not isinstance(v,dict) else list(v.keys())[:5])
            walk(v, path+"/"+str(k))
    elif isinstance(o,list):
        for i,v in enumerate(o[:50]):
            walk(v, path+f"[{i}]")
walk(reg)
