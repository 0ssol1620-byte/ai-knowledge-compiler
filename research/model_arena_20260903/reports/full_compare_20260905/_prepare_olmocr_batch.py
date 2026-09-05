import subprocess
from pathlib import Path
py = r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe"
# override path: directory containing pdfs/ (because --gt-path skips the .parent adjust)
gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\olmocr-bench\bench_data"
root = r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
assert (Path(gt)/"pdfs").is_dir(), gt
models = ["paddleocr_vl_1_6","deepseek_ocr2","hpd_parsing","mineru_pipeline","mineru_vlm","monkeyocrv2_b","ovisocr2"]
log = Path(root)/"reports"/"full_compare_20260905"/"prepare_olmocr.log"
with log.open("w", encoding="utf-8") as f:
    for m in models:
        print(f"PREPARE olmocr {m}", flush=True)
        f.write(f"==== PREPARE olmocr {m} ====\n"); f.flush()
        p = subprocess.run([py,"-m","arena.scoring","prepare","--model",m,"--benchmark","olmocr","--gt-path",gt], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        f.write(p.stdout or ""); f.write(p.stderr or ""); f.write(f"\nrc={p.returncode}\n"); f.flush()
        print(f"rc={p.returncode}", flush=True)
print("DONE", flush=True)
