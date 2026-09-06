"""Prepare olmOCR + ParseBench evaluator inputs for opus5_subscription + glm_ocr."""
import subprocess
from pathlib import Path

py = r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe"
root = r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
olm_gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\olmocr-bench\bench_data"
pb_gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\parsebench\docs"
models = ["opus5_subscription", "glm_ocr"]
report = Path(root) / "reports" / "full_compare_20260905"
log = report / "prepare_opus_glm_corpus.log"

with log.open("w", encoding="utf-8") as f:
    for bench, gt in [("olmocr", olm_gt), ("parsebench", pb_gt)]:
        for m in models:
            msg = f"==== PREPARE {bench} {m} ===="
            print(msg, flush=True)
            f.write(msg + "\n"); f.flush()
            p = subprocess.run(
                [py, "-m", "arena.scoring", "prepare", "--model", m, "--benchmark", bench, "--gt-path", gt],
                cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            f.write(p.stdout or ""); f.write(p.stderr or ""); f.write(f"\nrc={p.returncode}\n"); f.flush()
            print(f"rc={p.returncode}", flush=True)
print("DONE prepare opus+glm corpus", flush=True)
