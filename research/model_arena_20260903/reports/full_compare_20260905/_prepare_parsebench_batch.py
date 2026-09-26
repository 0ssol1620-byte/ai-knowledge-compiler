import subprocess
from pathlib import Path
py = r"D:\CodexProjects\ai-knowledge-compiler\.venv\Scripts\python.exe"
gt = r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\parsebench\docs"
root = r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
models = ["paddleocr_vl_1_6","deepseek_ocr2","hpd_parsing","mineru_pipeline","mineru_vlm","monkeyocrv2_b","ovisocr2"]
log = Path(root)/"reports"/"full_compare_20260905"/"prepare_parsebench.log"
with log.open("w", encoding="utf-8") as f:
    for m in models:
        print(f"PREPARE parsebench {m}", flush=True)
        f.write(f"==== PREPARE parsebench {m} ====\n"); f.flush()
        p = subprocess.run([py,"-m","arena.scoring","prepare","--model",m,"--benchmark","parsebench","--gt-path",gt], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace")
        f.write(p.stdout or ""); f.write(p.stderr or ""); f.write(f"\nrc={p.returncode}\n"); f.flush()
        print(f"rc={p.returncode}", flush=True)
print("DONE", flush=True)
