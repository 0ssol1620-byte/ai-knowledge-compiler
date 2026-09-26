"""QA then prepare olmOCR+ParseBench for opus5_subscription + glm_ocr."""
import subprocess
from pathlib import Path

py = r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe"
root = r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
olm_gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\olmocr-bench\bench_data"
pb_gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\parsebench\docs"
models = ["opus5_subscription", "glm_ocr"]
report = Path(root) / "reports" / "full_compare_20260905"
log = report / "qa_prepare_opus_glm_corpus.log"

with log.open("w", encoding="utf-8") as f:
    for bench, gt in [("olmocr", olm_gt), ("parsebench", pb_gt)]:
        for m in models:
            for step, args in [
                ("QA", [py, "-m", "arena.scoring", "qa", "--model", m, "--benchmark", bench]),
                ("PREPARE", [py, "-m", "arena.scoring", "prepare", "--model", m, "--benchmark", bench, "--gt-path", gt]),
            ]:
                msg = f"==== {step} {bench} {m} ===="
                print(msg, flush=True)
                f.write(msg + "\n"); f.flush()
                p = subprocess.run(args, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
                f.write(p.stdout or ""); f.write(p.stderr or ""); f.write(f"\nrc={p.returncode}\n"); f.flush()
                print(f"rc={p.returncode}", flush=True)
                if step == "QA" and p.returncode != 0:
                    # still try prepare; may refuse on red gate — log and continue
                    f.write("(QA non-zero; attempting prepare anyway)\n"); f.flush()
print("DONE qa+prepare opus+glm", flush=True)
