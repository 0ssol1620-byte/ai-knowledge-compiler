"""Watchdog: wait for orphaned pdf_validation, harvest artifacts, resume full scorer."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
EVAL_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc")
REPORT = ROOT / "reports" / "full_compare_20260905"
RAW = REPORT / "omnidoc_raw"
DRIVER = REPORT / "_win_omnidoc_score_full.py"
PY = Path(r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe")
OMNI_PY = EVAL_DIR / ".venv" / "Scripts" / "python.exe"
LOG = REPORT / "watchdog.log"

def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")

def pid_alive(pid: int) -> bool:
    # Windows: tasklist
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in (r.stdout or "")

def harvest(model: str, started: float, returncode: int | None = None) -> dict:
    out_dir = RAW / model
    out_dir.mkdir(parents=True, exist_ok=True)
    result_dir = EVAL_DIR / "result"
    prefix = "markdown_quick_match"
    metric = result_dir / f"{prefix}_metric_result.json"
    copied = {}
    if result_dir.is_dir():
        for src in sorted(result_dir.glob(f"{prefix}_*")):
            if src.is_file():
                dst = out_dir / src.name
                shutil.copy2(src, dst)
                copied[src.name] = dst.stat().st_size
    summary = {
        "model": model,
        "tag": "settled_full_1651",
        "gt": str(Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json")),
        "returncode": 0 if metric.is_file() else (returncode if returncode is not None else 1),
        "elapsed_seconds": time.time() - started,
        "metric_result_exists": metric.is_file(),
        "copied_artifacts": copied,
        "harvested_by": "watchdog",
    }
    if metric.is_file():
        data = json.loads(metric.read_text(encoding="utf-8"))
        (out_dir / "metric_result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        md = data.get("match_debug")
        if isinstance(md, dict):
            summary["page_count"] = md.get("page_count")
        for k in ("text_block", "display_formula", "table", "reading_order", "score", "metrics", "average", "summary"):
            if k in data:
                summary[k] = data[k]
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return summary

def find_validation_pids():
    r = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/FORMAT:LIST"], capture_output=True, text=True, errors="replace")
    text = r.stdout or ""
    blocks = text.split("\n\n")
    pids = []
    for b in blocks:
        if "pdf_validation.py" in b and "omnidoc-full-config" in b:
            pid = None
            for line in b.splitlines():
                if line.startswith("ProcessId="):
                    pid = int(line.split("=",1)[1].strip())
            if pid:
                pids.append(pid)
    return pids

def main() -> int:
    # Known orphan from earlier start
    watch = [23824, 42000]
    started_approx = time.time() - 180  # rough
    # Prefer detecting live validation pids
    live = find_validation_pids()
    log(f"live validation pids: {live}")
    targets = live or [p for p in watch if pid_alive(p)]
    if targets:
        log(f"waiting for pids {targets}")
        while any(pid_alive(p) for p in targets):
            time.sleep(30)
            still = [p for p in targets if pid_alive(p)]
            err = RAW / "paddleocr_vl_1_6" / "stderr.log"
            sz = err.stat().st_size if err.exists() else 0
            log(f"still running {still}; stderr_bytes={sz}")
        log("validation exited; harvesting paddleocr_vl_1_6")
        summary = harvest("paddleocr_vl_1_6", started_approx)
        log(f"harvest: metric={summary.get('metric_result_exists')} pages={summary.get('page_count')} rc={summary.get('returncode')}")
        # update progress
        prog = REPORT / "scoring_progress.json"
        arr = []
        if prog.exists():
            try:
                arr = json.loads(prog.read_text(encoding="utf-8"))
            except Exception:
                arr = []
        arr = [x for x in arr if x.get("model") != "paddleocr_vl_1_6"]
        arr.append(summary)
        prog.write_text(json.dumps(arr, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    else:
        log("no live validation; checking if paddleocr already harvested")
        rs = RAW / "paddleocr_vl_1_6" / "run_summary.json"
        if rs.exists():
            log("paddleocr run_summary exists")
        else:
            # try harvest anyway if metric exists
            metric = EVAL_DIR / "result" / "markdown_quick_match_metric_result.json"
            if metric.exists():
                summary = harvest("paddleocr_vl_1_6", started_approx)
                log(f"late harvest ok metric={summary.get('metric_result_exists')}")

    log("starting resumable driver")
    # Run driver in-process wait (this watchdog IS the long-lived parent)
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1"})
    with (REPORT / "score_runner2.log").open("a", encoding="utf-8") as out, (REPORT / "score_runner2.err.log").open("a", encoding="utf-8") as err:
        proc = subprocess.run([str(PY), str(DRIVER)], cwd=str(REPORT), stdout=out, stderr=err, env=env)
    log(f"driver finished rc={proc.returncode}")
    # build comparison
    subprocess.run([str(PY), str(REPORT / "_build_comparison.py")], cwd=str(REPORT), check=False)
    return proc.returncode

if __name__ == "__main__":
    raise SystemExit(main())
