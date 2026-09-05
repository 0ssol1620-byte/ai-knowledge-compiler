"""Windows-safe full OmniDoc scoring (file-redirect, no capture hang)."""
from __future__ import annotations
import json, os, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
EVAL_DIR = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc")
OMNI_PY = EVAL_DIR / ".venv" / "Scripts" / "python.exe"
REPORT = ROOT / "reports" / "full_compare_20260905"
RAW_ROOT = REPORT / "omnidoc_raw"
FULL_GT = Path(r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json")

# Settled complete-coverage first, then near-complete, then refs
SETTLED_FULL = [
    "paddleocr_vl_1_6",
    "deepseek_ocr2",
    "hpd_parsing",
    "mineru_pipeline",
    "mineru_vlm",
    "monkeyocrv2_b",
    "ovisocr2",
    "olmocr2",
]
SETTLED_NEAR = ["unlimited_ocr"]  # 1645/1651
REF_NEAR = ["opus5_subscription", "glm_ocr"]  # opus skipped 21; glm empties+pending
# infinity scored on filtered GT only

def yaml_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")

def write_config(model: str, gt: Path, out: Path) -> Path:
    pred = ROOT / "scores" / model / "omnidoc" / "evaluator_input" / "markdown"
    if not pred.is_dir():
        raise FileNotFoundError(pred)
    out.mkdir(parents=True, exist_ok=True)
    cfg = out / "omnidoc-full-config.yaml"
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
    quick_match_polygon_timeout_sec: 60
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
    for k in ("text_block", "display_formula", "table", "reading_order"):
        if k in data:
            out[k] = data[k]
    if "score" in data:
        out["score"] = data["score"]
    for k in ("metrics", "average", "summary"):
        if k in data:
            out[k] = data[k]
    return out

def build_infinity_filtered_gt() -> Path:
    """GT pages whose prediction markdown exists for infinity (avoid empty-page wipeout)."""
    pred = ROOT / "scores" / "infinity_parser2_pro" / "omnidoc" / "evaluator_input" / "markdown"
    stems = {p.stem for p in pred.glob("*.md")}
    full = json.loads(FULL_GT.read_text(encoding="utf-8"))
    filtered = []
    for item in full:
        img = Path(item["page_info"]["image_path"]).name
        stem = img[:-4]  # strip .png/.jpg
        if stem in stems or stem.replace(".pdf", "") in stems or img in stems:
            filtered.append(item)
    out = REPORT / "omnidoc_gt_infinity_available.json"
    out.write_text(json.dumps(filtered, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = {"n": len(filtered), "pred_md": len(stems), "path": str(out)}
    (REPORT / "omnidoc_gt_infinity_available_meta.json").write_text(json.dumps(meta, indent=2)+"\n", encoding="utf-8")
    print("infinity filtered GT", meta, flush=True)
    return out

def score_model(model: str, gt: Path, tag: str) -> dict:
    out_dir = RAW_ROOT / model
    cfg = write_config(model, gt, out_dir)
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
    print(f"==== SCORE {tag} {model} ====", flush=True)
    print(f"gt={gt}", flush=True)
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
        "tag": tag,
        "gt": str(gt),
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
    REPORT.mkdir(parents=True, exist_ok=True)
    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    if not FULL_GT.is_file():
        raise SystemExit(f"missing full gt: {FULL_GT}")
    # optional model filter via argv
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    jobs = []
    for m in SETTLED_FULL:
        jobs.append((m, FULL_GT, "settled_full_1651"))
    for m in SETTLED_NEAR:
        jobs.append((m, FULL_GT, "settled_near_full_gt"))
    for m in REF_NEAR:
        jobs.append((m, FULL_GT, "reference_near_full_gt"))
    inf_gt = build_infinity_filtered_gt()
    jobs.append(("infinity_parser2_pro", inf_gt, "reference_infinity_filtered_gt"))
    if only:
        jobs = [j for j in jobs if j[0] in only]
    results = []
    progress_path = REPORT / "scoring_progress.json"
    # resume: skip models that already have successful run_summary
    rc = 0
    for model, gt, tag in jobs:
        existing = RAW_ROOT / model / "run_summary.json"
        if existing.is_file():
            prev = json.loads(existing.read_text(encoding="utf-8"))
            if prev.get("returncode") == 0 and prev.get("metric_result_exists"):
                print(f"SKIP already scored {model}", flush=True)
                results.append(prev)
                progress_path.write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
                try:
                    subprocess.run([str(Path(r"D:\\CodexProjects\\ai-knowledge-compiler\\.venv\\Scripts\\python.exe")), str(REPORT / "_build_comparison.py")], check=False)
                except Exception as _exc:
                    print(f"comparison rebuild failed: {_exc}", flush=True)
                continue
        try:
            results.append(score_model(model, gt, tag))
            if results[-1].get("returncode", 1) != 0:
                rc = 1
        except Exception as exc:
            print(f"FAILED {model}: {exc}", flush=True)
            results.append({"model": model, "tag": tag, "error": str(exc)})
            rc = 1
        progress_path.write_text(json.dumps(results, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        try:
            subprocess.run([str(Path(r"D:\\CodexProjects\\ai-knowledge-compiler\\.venv\\Scripts\\python.exe")), str(REPORT / "_build_comparison.py")], check=False)
        except Exception as _exc:
            print(f"comparison rebuild failed: {_exc}", flush=True)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
