"""Windows-safe OmniDoc scoring: redirect stdout/stderr to files (no capture_output hang)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
EVAL_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc")
OMNI_PY = EVAL_DIR / ".venv" / "Scripts" / "python.exe"
REPORT = ROOT / "reports" / "partial_score_20260905"
RAW_ROOT = REPORT / "omnidoc_raw"
MODELS = [
    "paddleocr_vl_1_6",
    "deepseek_ocr2",
    "hpd_parsing",
    "mineru_pipeline",
    "mineru_vlm",
    "monkeyocrv2_b",
    "ovisocr2",
]

def score_model(model: str) -> dict:
    config = ROOT / "scores" / model / "omnidoc" / "evaluator_raw" / "omnidoc-config.yaml"
    if not config.is_file():
        raise FileNotFoundError(config)
    out_dir = RAW_ROOT / model
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = out_dir / "stdout.log"
    stderr_path = out_dir / "stderr.log"
    # Clear prior evaluator result artifacts for this prediction prefix
    result_dir = EVAL_DIR / "result"
    if result_dir.is_dir():
        for p in result_dir.glob("markdown_quick_match_*"):
            try:
                p.unlink()
            except OSError:
                pass
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["TQDM_DISABLE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    started = time.time()
    print(f"==== SCORE omnidoc {model} ====", flush=True)
    print(f"config={config}", flush=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out_h, stderr_path.open("w", encoding="utf-8", errors="replace") as err_h:
        proc = subprocess.run(
            [str(OMNI_PY), "pdf_validation.py", "--config", str(config)],
            cwd=str(EVAL_DIR),
            stdout=out_h,
            stderr=err_h,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    elapsed = time.time() - started
    print(f"returncode={proc.returncode} elapsed_s={elapsed:.1f}", flush=True)
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
        "returncode": proc.returncode,
        "elapsed_seconds": elapsed,
        "metric_result_exists": metric.is_file(),
        "copied_artifacts": copied,
        "stdout_log": str(stdout_path),
        "stderr_log": str(stderr_path),
    }
    if metric.is_file():
        data = json.loads(metric.read_text(encoding="utf-8"))
        # extract aggregate-ish fields commonly present
        summary["metric_keys"] = sorted(data.keys())
        if isinstance(data.get("match_debug"), dict):
            summary["page_count"] = data["match_debug"].get("page_count")
        # keep a compact metrics slice if present
        for k in ("text_block", "display_formula", "table", "reading_order"):
            if k in data:
                summary[k] = data[k]
        # Some OmniDoc results nest under score / metrics
        if "score" in data:
            summary["score"] = data["score"]
        (out_dir / "metric_result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary

def main() -> int:
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    models = MODELS
    if len(sys.argv) > 1:
        models = sys.argv[1:]
    results = []
    rc = 0
    for m in models:
        try:
            results.append(score_model(m))
            if results[-1]["returncode"] != 0:
                rc = 1
        except Exception as exc:
            print(f"FAILED {m}: {exc}", flush=True)
            results.append({"model": m, "error": str(exc)})
            rc = 1
        (REPORT / "scoring_progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rc

if __name__ == "__main__":
    raise SystemExit(main())