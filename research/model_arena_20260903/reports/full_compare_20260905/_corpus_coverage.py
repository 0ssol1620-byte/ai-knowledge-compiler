"""Corpus-wide non-judge coverage stats across ~5132 pages."""
from __future__ import annotations
import json, sqlite3, sys
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
sys.path.insert(0, str(ROOT))
REPORT = ROOT / "reports" / "full_compare_20260905"
REPORT.mkdir(parents=True, exist_ok=True)
KST = timezone(timedelta(hours=9))
EXCLUDE_MAIN = {"infinity_parser2_pro"}

from arena.scoring.paths import ScoringPaths
from arena.scoring.outputs import load_model_output_set
from arena.scoring.evaluators import _read_canonical

db = ROOT / "queue" / "campaign.sqlite"
con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
cm = json.loads((ROOT / "campaign_manifest.json").read_text(encoding="utf-8"))
rows = con.execute(
    "SELECT model_key, benchmark, state, COUNT(*) FROM jobs GROUP BY model_key, benchmark, state"
).fetchall()
by = defaultdict(lambda: defaultdict(Counter))
totals = defaultdict(Counter)
for mk, bench, st, c in rows:
    by[mk][bench][st] += c
    totals[mk][st] += c

def output_stats(model: str) -> dict:
    try:
        oset = load_model_output_set(ScoringPaths.default(), model)
    except Exception as exc:
        return {"error": str(exc)}
    by_bench = defaultdict(lambda: {"n": 0, "empty": 0, "nonempty": 0, "chars": [], "bytes": [], "failed_adapter": 0})
    for row in oset.rows:
        b = getattr(row, "benchmark", None) or "unknown"
        slot = by_bench[b]
        slot["n"] += 1
        try:
            text = _read_canonical(row) or ""
        except Exception:
            text = ""
        nbytes = len(text.encode("utf-8", errors="replace"))
        nchars = len(text)
        slot["chars"].append(nchars)
        slot["bytes"].append(nbytes)
        if not text.strip():
            slot["empty"] += 1
        else:
            slot["nonempty"] += 1
        err = getattr(row, "error_class", None)
        if err in {"OUTPUT_EMPTY","OUTPUT_TRUNCATED","OUTPUT_MALFORMED","OUTPUT_REPETITION","POSTPROCESS","INPUT_DECODE","PREPROCESS"}:
            slot["failed_adapter"] += 1
    out = {}
    for b, slot in by_bench.items():
        chars = sorted(slot["chars"])
        def pct(p):
            if not chars: return None
            i = min(len(chars)-1, max(0, int(round((p/100)*(len(chars)-1)))))
            return chars[i]
        out[b] = {
            "n": slot["n"], "empty": slot["empty"], "nonempty": slot["nonempty"],
            "empty_rate": (slot["empty"] / slot["n"]) if slot["n"] else None,
            "chars_p50": pct(50), "chars_p90": pct(90), "chars_p99": pct(99),
            "chars_mean": (sum(chars)/len(chars)) if chars else None,
            "bytes_sum": sum(slot["bytes"]), "failed_adapter": slot["failed_adapter"],
        }
    return out

models = sorted(by.keys())
# also check frozen for flash not in jobs
fo = ROOT / "frozen_outputs"
for d in fo.iterdir() if fo.exists() else []:
    if d.is_dir() and d.name not in models and not d.name.startswith("glm_ocr._"):
        models.append(d.name)
models = sorted(set(models))
print("models", models)

ref_model = "paddleocr_vl_1_6" if "paddleocr_vl_1_6" in by else models[0]
planned_by_bench = {b: sum(by[ref_model][b].values()) for b in by.get(ref_model, {})}
report = {
    "generated_at_kst": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
    "cloud_cost_usd": 0,
    "exclude_from_main_board": sorted(EXCLUDE_MAIN),
    "campaign_manifest": cm,
    "planned_pages_by_benchmark_ref": {"ref_model": ref_model, "by_benchmark": planned_by_bench, "total": sum(planned_by_bench.values())},
    "job_states_by_model_benchmark": {mk: {b: dict(ctr) for b, ctr in benches.items()} for mk, benches in by.items()},
    "job_states_by_model": {mk: dict(ctr) for mk, ctr in totals.items()},
    "output_stats": {},
    "coverage_summary": [],
    "flash_models": [m for m in models if "flash" in m.lower()],
}
for mk in models:
    print("stats", mk, flush=True)
    ostats = output_stats(mk)
    report["output_stats"][mk] = ostats
    js = totals.get(mk, Counter())
    success = js.get("SUCCESS", 0)
    total = sum(js.values())
    unsettled = sum(v for k,v in js.items() if k not in ("SUCCESS","FAILED","QUARANTINED","SKIPPED","CANCELLED"))
    report["coverage_summary"].append({
        "model": mk,
        "main_board": mk not in EXCLUDE_MAIN,
        "jobs_total": total,
        "SUCCESS": success,
        "FAILED": js.get("FAILED", 0),
        "QUARANTINED": js.get("QUARANTINED", 0),
        "PENDING": js.get("PENDING", 0),
        "RUNNING": js.get("RUNNING", 0),
        "unsettled_like": unsettled,
        "success_rate": (success/total) if total else None,
        "by_benchmark_jobs": {b: dict(ctr) for b,ctr in by.get(mk, {}).items()},
        "by_benchmark_outputs": ostats,
    })

out_json = REPORT / "corpus_coverage_5132.json"
out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
lines = [
    f"# Corpus coverage (~5132) — {report['generated_at_kst']}", "",
    f"Ref planned total ({ref_model}): **{report['planned_pages_by_benchmark_ref']['total']}** "
    + ", ".join(f"{k}={v}" for k,v in planned_by_bench.items()),
    "", "Infinity Pro excluded from main board (FOUNDER_EXCLUDED).", "",
    "| Model | main | jobs | SUCCESS | FAILED | Q | PENDING | empty_omni | empty_olmocr | empty_pb | success% |",
    "|---|:---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]
for row in report["coverage_summary"]:
    os_ = row.get("by_benchmark_outputs") or {}
    def emp(b):
        s = os_.get(b) if isinstance(os_, dict) else None
        if not isinstance(s, dict): return "—"
        if "error" in s: return "err"
        return f"{s.get('empty',0)}/{s.get('n',0)}"
    sr = f"{row['success_rate']:.3f}" if row.get("success_rate") is not None else "—"
    lines.append(
        f"| `{row['model']}` | {'Y' if row['main_board'] else 'N'} | {row['jobs_total']} | {row['SUCCESS']} | {row['FAILED']} | {row['QUARANTINED']} | {row['PENDING']} | {emp('omnidoc')} | {emp('olmocr')} | {emp('parsebench')} | {sr} |"
    )
(REPORT / "corpus_coverage_5132.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
print("wrote", out_json)
