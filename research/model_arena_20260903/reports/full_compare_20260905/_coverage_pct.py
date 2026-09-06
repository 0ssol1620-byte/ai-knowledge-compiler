import sqlite3, json
from pathlib import Path
from collections import defaultdict, Counter
c=sqlite3.connect(r"file:D:/CodexProjects/ai-knowledge-compiler/research/model_arena_20260903/queue/campaign.sqlite?mode=ro",uri=True)
rows=c.execute("SELECT model_key,benchmark,state,COUNT(*) FROM jobs GROUP BY 1,2,3").fetchall()
by=defaultdict(lambda: defaultdict(Counter))
for mk,b,st,n in rows:
    by[mk][b][st]+=n
# planned from paddle
plan={b:sum(by['paddleocr_vl_1_6'][b].values()) for b in by['paddleocr_vl_1_6']}
total=sum(plan.values())
print(f"PLANNED total={total} {plan}")
EXCLUDE={'infinity_parser2_pro'}
print("\nCOVERAGE % of planned pages by SUCCESS outputs (jobs SUCCESS / planned_bench)")
header=["model","omnidoc%","olmocr%","parsebench%","all%","SUCCESS","PENDING","main"]
print("|".join(header))
summary=[]
for mk in sorted(by):
    succ=0; pend=0; tot=0
    parts={}
    for b,planned in plan.items():
        s=by[mk][b].get('SUCCESS',0)
        parts[b]=100.0*s/planned if planned else None
        succ += by[mk][b].get('SUCCESS',0)
        pend += by[mk][b].get('PENDING',0)+by[mk][b].get('RUNNING',0)
        tot += sum(by[mk][b].values())
    allpct=100.0*succ/total if total else 0
    main = 'N' if mk in EXCLUDE else 'Y'
    line=f"{mk}|{parts.get('omnidoc',0):.1f}|{parts.get('olmocr',0):.1f}|{parts.get('parsebench',0):.1f}|{allpct:.1f}|{succ}|{pend}|{main}"
    print(line)
    summary.append({"model":mk,"omnidoc_pct":parts.get('omnidoc'),"olmocr_pct":parts.get('olmocr'),"parsebench_pct":parts.get('parsebench'),"all_pct":allpct,"SUCCESS":succ,"PENDING_or_RUNNING":pend,"main_board":mk not in EXCLUDE,"by_benchmark_success":{b:by[mk][b].get('SUCCESS',0) for b in plan},"planned":plan})
out=Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905\coverage_pct_5132.json")
out.write_text(json.dumps({"planned_total":total,"planned_by_benchmark":plan,"models":summary},indent=2)+"\n",encoding="utf-8")
print("wrote",out)
