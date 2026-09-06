"""File-redirect olmOCR scoring via arena.scoring.drivers.olmocr_driver (no capture hang)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
REPORT = ROOT / "reports" / "full_compare_20260905"
RAW = REPORT / "olmocr_raw"
ARENA_PY = Path(r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe")
BENCH = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\olmocr-bench\bench_data")
# evaluator checkout under scores/_evaluators or cache
CANDIDATES = [
    ROOT / "scores" / "_evaluators" / "olmocr",
    Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\olmocr"),
]

MODELS = [
    "paddleocr_vl_1_6","deepseek_ocr2","hpd_parsing","mineru_pipeline","mineru_vlm",
    "monkeyocrv2_b","ovisocr2","olmocr2","unlimited_ocr","opus5_subscription",
    "glm_ocr","infinity_parser2_flash",
]
MAX_PARALLEL = 3

def find_evaluator() -> Path:
    for base in CANDIDATES:
        if (base / "benchmark.py").is_file():
            return base
        # maybe revision subdirs
        if base.is_dir():
            for p in base.rglob("benchmark.py"):
                return p.parent
    raise FileNotFoundError("olmocr evaluator checkout not found")

def score_one(model: str, evaluator_dir: Path) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    out_dir = RAW / model
    out_dir.mkdir(parents=True, exist_ok=True)
    rs = out_dir / "run_summary.json"
    if rs.exists():
        prev = json.loads(rs.read_text(encoding="utf-8"))
        if prev.get("returncode") == 0:
            print(f"SKIP olmocr {model}", flush=True)
            return prev
    # Stage: evaluator_input should contain candidate dir; stage_olmocr_bench_root links pdfs+jsonl
    input_root = ROOT / "scores" / model / "olmocr" / "evaluator_input"
    if not input_root.is_dir():
        return {"model": model, "error": f"missing evaluator_input {input_root}"}
    # find candidate folder name (not pdfs)
    cands = [p.name for p in input_root.iterdir() if p.is_dir() and p.name not in {"pdfs"}]
    if not cands:
        return {"model": model, "error": "no candidate dir in evaluator_input"}
    candidate = cands[0]
    # Ensure pdfs/jsonl staged
    sys.path.insert(0, str(ROOT))
    from arena.scoring.evaluators import stage_olmocr_bench_root
    stage_olmocr_bench_root(input_root, BENCH)
    out_json = out_dir / "official_result.json"
    stdout_path = out_dir / "stdout.log"
    stderr_path = out_dir / "stderr.log"
    driver = ROOT / "arena" / "scoring" / "drivers" / "olmocr_driver.py"
    env = os.environ.copy()
    env.update({"PYTHONUTF8":"1","PYTHONUNBUFFERED":"1","PYTHONIOENCODING":"utf-8"})
    started = time.time()
    print(f"==== SCORE olmocr {model} candidate={candidate} ====", flush=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out_h, stderr_path.open("w", encoding="utf-8", errors="replace") as err_h:
        proc = subprocess.run(
            [str(ARENA_PY), str(driver),
             "--evaluator-dir", str(evaluator_dir),
             "--bench-dir", str(input_root),
             "--candidate", candidate,
             "--out", str(out_json)],
            cwd=str(evaluator_dir), stdout=out_h, stderr=err_h, text=True,
            encoding="utf-8", errors="replace", env=env,
        )
    elapsed = time.time() - started
    summary = {
        "model": model, "benchmark": "olmocr", "returncode": proc.returncode,
        "elapsed_seconds": elapsed, "out": str(out_json), "candidate": candidate,
        "result_exists": out_json.is_file(),
    }
    if out_json.is_file():
        data = json.loads(out_json.read_text(encoding="utf-8"))
        summary["overall"] = data.get("overall") or data.get("score") or data.get("overall_score")
        summary["keys"] = sorted(data.keys())[:30]
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"DONE olmocr {model} rc={proc.returncode} elapsed={elapsed:.1f}", flush=True)
    return summary

def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    models = only or MODELS
    evaluator = find_evaluator()
    print("evaluator", evaluator, flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as ex:
        futs = {ex.submit(score_one, m, evaluator): m for m in models}
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append({"model": m, "error": str(exc)})
                print(f"FAILED {m}: {exc}", flush=True)
    (REPORT / "olmocr_progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
