"""Parallel OmniDoc scoring with unique result prefixes (no shared markdown_ clobber)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
EVAL_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc")
OMNI_PY = EVAL_DIR / ".venv" / "Scripts" / "python.exe"
REPORT = ROOT / "reports" / "full_compare_20260905"
RAW_ROOT = REPORT / "omnidoc_raw"
FULL_GT = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json")
ARENA_PY = Path(r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe")

# Keep deepseek/paddleocr out — deepseek mid-run, paddleocr done
MODELS = [
    "hpd_parsing",
    "mineru_pipeline",
    "mineru_vlm",
    "monkeyocrv2_b",
    "ovisocr2",
    "olmocr2",
    "unlimited_ocr",
    "opus5_subscription",
    "glm_ocr",
]
# Exclude Pro. Flash added if prepared later via argv.

MAX_PARALLEL = 5  # ~12 cores / 2, leave room for orphan deepseek
WORKERS = 3       # match_workers / teds_workers per model when parallel

def yaml_path(path: Path) -> str:
    # Do NOT Path.resolve(): Windows junctions (md_<model> -> markdown) must keep
    # the md_<model> basename so OmniDoc save_name = md_<model>_quick_match (unique).
    # resolve() follows the junction and collapses every model onto markdown_quick_match,
    # clobbering the orphan deepseek run and sibling parallel scorers.
    return path.absolute().as_posix().replace("'", "''")

def ensure_alias_pred(model: str) -> Path:
    """Create junction/symlink markdown_<model> -> markdown for unique result prefix."""
    base = ROOT / "scores" / model / "omnidoc" / "evaluator_input"
    src = base / "markdown"
    alias = base / f"md_{model}"
    if not src.is_dir():
        raise FileNotFoundError(src)
    if alias.exists():
        return alias
    # Windows junction
    subprocess.run(["cmd", "/c", "mklink", "/J", str(alias), str(src)], check=True, capture_output=True)
    return alias

def write_config(model: str, gt: Path, pred: Path, out: Path, workers: int) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    cfg = out / "omnidoc-parallel-config.yaml"
    cfg.write_text(
        f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: {workers}
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{yaml_path(gt)}'
    prediction:
      data_path: '{yaml_path(pred)}'
    match_method: quick_match
    match_workers: {workers}
    deterministic_matching: false
    quick_match_polygon_timeout_sec: 60
    match_timeout_sec: 90
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
""",
        encoding="utf-8",
    )
    return cfg

def extract_into_summary(summary: dict, data: dict) -> None:
    md = data.get("match_debug")
    if isinstance(md, dict):
        summary["page_count"] = md.get("page_count")
    for k in ("text_block", "display_formula", "table", "reading_order", "score"):
        if k in data:
            summary[k] = data[k]

def score_one(model: str, gt: Path, tag: str, workers: int) -> dict:
    out_dir = RAW_ROOT / model
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "run_summary.json"
    if existing.is_file():
        prev = json.loads(existing.read_text(encoding="utf-8"))
        if prev.get("returncode") == 0 and prev.get("metric_result_exists"):
            print(f"SKIP {model}", flush=True)
            return prev
    pred = ensure_alias_pred(model)
    prefix = pred.name  # md_<model>
    cfg = write_config(model, gt, pred, out_dir, workers)
    stdout_path = out_dir / "stdout.log"
    stderr_path = out_dir / "stderr.log"
    result_dir = EVAL_DIR / "result"
    # clear only this model's prefix leftovers
    if result_dir.is_dir():
        for p in result_dir.glob(f"{prefix}_quick_match_*"):
            try: p.unlink()
            except OSError: pass
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TQDM_DISABLE": "1", "PYTHONIOENCODING": "utf-8"})
    started = time.time()
    print(f"==== PARALLEL SCORE {tag} {model} prefix={prefix} workers={workers} ====", flush=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out_h, stderr_path.open("w", encoding="utf-8", errors="replace") as err_h:
        proc = subprocess.run(
            [str(OMNI_PY), "pdf_validation.py", "--config", str(cfg)],
            cwd=str(EVAL_DIR), stdout=out_h, stderr=err_h, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
    elapsed = time.time() - started
    print(f"DONE {model} rc={proc.returncode} elapsed_s={elapsed:.1f}", flush=True)
    metric = result_dir / f"{prefix}_quick_match_metric_result.json"
    copied = {}
    if result_dir.is_dir():
        for src in sorted(result_dir.glob(f"{prefix}_quick_match_*")):
            if src.is_file():
                dst = out_dir / src.name
                shutil.copy2(src, dst)
                copied[src.name] = dst.stat().st_size
    summary = {
        "model": model, "tag": tag, "gt": str(gt), "prefix": prefix,
        "returncode": proc.returncode, "elapsed_seconds": elapsed,
        "metric_result_exists": metric.is_file(), "copied_artifacts": copied,
        "parallel": True, "workers": workers,
    }
    if metric.is_file():
        data = json.loads(metric.read_text(encoding="utf-8"))
        (out_dir / "metric_result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        extract_into_summary(summary, data)
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    # refresh comparison
    subprocess.run([str(ARENA_PY), str(REPORT / "_build_comparison.py")], check=False)
    # append progress
    prog = REPORT / "scoring_progress_parallel.json"
    arr = []
    if prog.exists():
        try: arr = json.loads(prog.read_text(encoding="utf-8"))
        except Exception: arr = []
    arr = [x for x in arr if x.get("model") != model]
    arr.append(summary)
    prog.write_text(json.dumps(arr, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return summary

def harvest_orphan_deepseek() -> None:
    """If deepseek pdf_validation still running, wait; then harvest markdown_quick_match_*."""
    out_dir = RAW_ROOT / "deepseek_ocr2"
    rs = out_dir / "run_summary.json"
    if rs.exists():
        prev = json.loads(rs.read_text(encoding="utf-8"))
        if prev.get("returncode") == 0 and prev.get("metric_result_exists"):
            print("deepseek already harvested", flush=True)
            return
    # poll for process
    print("waiting for orphan deepseek pdf_validation if any", flush=True)
    while True:
        r = subprocess.run(
            ["wmic", "process", "where", "name='python.exe'", "get", "ProcessId,CommandLine", "/FORMAT:LIST"],
            capture_output=True, text=True, errors="replace",
        )
        alive = "deepseek_ocr2" in (r.stdout or "") and "pdf_validation" in (r.stdout or "")
        # also check stderr growth
        err = out_dir / "stderr.log"
        if not alive:
            # double-check via tasklist patterns using powershell-less approach
            r2 = subprocess.run(["powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'pdf_validation' -and $_.CommandLine -match 'deepseek' } | Measure-Object | Select-Object -ExpandProperty Count"],
                capture_output=True, text=True)
            try:
                alive = int((r2.stdout or "0").strip() or "0") > 0
            except Exception:
                alive = False
        if not alive:
            break
        print(f"deepseek still running; stderr={err.stat().st_size if err.exists() else 0}", flush=True)
        time.sleep(30)
    # harvest shared markdown_ prefix results into deepseek dir
    result_dir = EVAL_DIR / "result"
    prefix = "markdown"
    metric = result_dir / f"{prefix}_quick_match_metric_result.json"
    # Only harvest if metric looks fresh / exists
    if not metric.is_file():
        print("deepseek metric missing after exit", flush=True)
        return
    copied = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(result_dir.glob(f"{prefix}_quick_match_*")):
        if src.is_file():
            dst = out_dir / src.name
            shutil.copy2(src, dst)
            copied[src.name] = dst.stat().st_size
    data = json.loads(metric.read_text(encoding="utf-8"))
    (out_dir / "metric_result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    summary = {
        "model": "deepseek_ocr2", "tag": "settled_full_1651", "gt": str(FULL_GT),
        "returncode": 0, "metric_result_exists": True, "copied_artifacts": copied,
        "harvested_by": "parallel_supervisor_orphan", "prefix": prefix,
    }
    extract_into_summary(summary, data)
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"harvested deepseek pages={summary.get('page_count')}", flush=True)
    subprocess.run([str(ARENA_PY), str(REPORT / "_build_comparison.py")], check=False)

def main() -> int:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    models = only or MODELS
    # Start deepseek harvest watcher in background thread
    t = threading.Thread(target=harvest_orphan_deepseek, name="harvest-deepseek", daemon=True)
    t.start()
    results = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futs = {ex.submit(score_one, m, FULL_GT, "settled_full_1651_parallel", WORKERS): m for m in models}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                print(f"FAILED {m}: {exc}", flush=True)
                results.append({"model": m, "error": str(exc)})
    t.join(timeout=10)
    (REPORT / "scoring_progress_parallel.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    subprocess.run([str(ARENA_PY), str(REPORT / "_build_comparison.py")], check=False)
    return 0 if all(r.get("returncode", 1) == 0 for r in results if "error" not in r) else 1

if __name__ == "__main__":
    raise SystemExit(main())
