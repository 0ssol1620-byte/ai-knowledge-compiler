"""Windows-safe OmniDoc scoring on a filtered GT subset (file-redirect, no capture hang)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
EVAL_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc")
OMNI_PY = EVAL_DIR / ".venv" / "Scripts" / "python.exe"
REPORT = ROOT / "reports" / "partial_score_20260905"
RAW_ROOT = REPORT / "omnidoc_raw"
DEFAULT_GT = ROOT / "reports" / "triple_overlap_20260904" / "omnidoc_gt_triple_overlap.json"
MODELS = [
    "paddleocr_vl_1_6",
    "deepseek_ocr2",
    "hpd_parsing",
    "mineru_pipeline",
    "mineru_vlm",
    "monkeyocrv2_b",
    "ovisocr2",
]

def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")

def write_config(model: str, gt: Path) -> Path:
    pred = ROOT / "scores" / model / "omnidoc" / "evaluator_input" / "markdown"
    if not pred.is_dir():
        raise FileNotFoundError(pred)
    out = RAW_ROOT / model
    out.mkdir(parents=True, exist_ok=True)
    cfg = out / "omnidoc-subset-config.yaml"
    cfg.write_text(
        f"""end2end_eval:
  metrics:
    text_block:
      metric: [Edit_dist]
    display_formula:
      metric: [Edit_dist]
    table:
      metric: [TEDS, Edit_dist]
      teds_workers: 8
    reading_order:
      metric: [Edit_dist]
  dataset:
    dataset_name: end2end_dataset
    ground_truth:
      data_path: '{yaml_path(gt)}'
    prediction:
      data_path: '{yaml_path(pred)}'
    match_method: quick_match
    match_workers: 8
    deterministic_matching: false
    quick_match_tokenize_timeout_sec: 60
    match_timeout_sec: 90
    timeout_fallback_max_chunk_span: 10
    timeout_fallback_order_penalty: 0.10
""",
        encoding="utf-8",
    )
    return cfg

def extract_metrics(data: dict) -> dict:
    out = {"metric_keys": sorted(data.keys())}
    md = data.get("match_debug")
    if isinstance(md, dict):
        out["page_count"] = md.get("page_count")
    # OmniDoc metric_result often has nested averages under each element type
    for k in ("text_block", "display_formula", "table", "reading_order"):
        if k in data:
            out[k] = data[k]
    if "score" in data:
        out["score"] = data["score"]
    # common alternate layout: results list / metrics dict
    for k in ("metrics", "average", "summary"):
        if k in data:
            out[k] = data[k]
    return out

def score_model(model: str, gt: Path) -> dict:
    cfg = write_config(model, gt)
    out_dir = RAW_ROOT / model
    stdout_path = out_dir / "stdout.log"
    stderr_path = out_dir / "stderr.log"
    result_dir = EVAL_DIR / "result"
    if result_dir.is_dir():
        for p in result_dir.glob("markdown_quick_match_*"):
            try:
                p.unlink()
            except OSError:
                pass
    env = os.environ.copy()
    env.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "TQDM_DISABLE": "1", "PYTHONIOENCODING": "utf-8"})
    started = time.time()
    print(f"==== SCORE omnidoc-subset {model} ====", flush=True)
    print(f"gt={gt}", flush=True)
    print(f"config={cfg}", flush=True)
    with stdout_path.open("w", encoding="utf-8", errors="replace") as out_h, stderr_path.open("w", encoding="utf-8", errors="replace") as err_h:
        proc = subprocess.run(
            [str(OMNI_PY), "pdf_validation.py", "--config", str(cfg)],
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
        "gt": str(gt),
        "gt_note": "531-page OmniDoc subset from reports/triple_overlap_20260904 (same filter used for prior Infinity/Opus comparison); NOT full 1651-page corpus",
        "returncode": proc.returncode,
        "elapsed_seconds": elapsed,
        "metric_result_exists": metric.is_file(),
        "copied_artifacts": copied,
    }
    if metric.is_file():
        data = json.loads(metric.read_text(encoding="utf-8"))
        (out_dir / "metric_result.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        summary.update(extract_metrics(data))
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary

def main() -> int:
    gt = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].endswith('.json') else DEFAULT_GT
    models = [a for a in sys.argv[1:] if not a.endswith('.json')] or MODELS
    if not gt.is_file():
        raise SystemExit(f"missing gt: {gt}")
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    results = []
    rc = 0
    for m in models:
        try:
            results.append(score_model(m, gt))
            if results[-1].get("returncode", 1) != 0:
                rc = 1
        except Exception as exc:
            print(f"FAILED {m}: {exc}", flush=True)
            results.append({"model": m, "error": str(exc)})
            rc = 1
        (REPORT / "scoring_progress.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rc

if __name__ == "__main__":
    raise SystemExit(main())