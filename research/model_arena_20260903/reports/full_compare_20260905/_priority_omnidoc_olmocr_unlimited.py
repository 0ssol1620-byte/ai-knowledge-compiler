"""Priority OmniDoc for olmocr2 + unlimited_ocr if not already scored (workers=2)."""
from __future__ import annotations
import json, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import importlib.util

REPORT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905")
spec = importlib.util.spec_from_file_location("pod", REPORT / "_parallel_omnidoc.py")
pod = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(pod)

MODELS = ["olmocr2", "unlimited_ocr"]
WORKERS = 2

def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    models = only or MODELS
    print(f"PRIORITY OmniDoc models={models} workers={WORKERS}", flush=True)
    results = []
    with ThreadPoolExecutor(max_workers=len(models)) as ex:
        futs = {
            ex.submit(pod.score_one, m, pod.FULL_GT, "settled_full_1651_priority_remaining", WORKERS): m
            for m in models
        }
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                print(f"FAILED {m}: {exc}", flush=True)
                results.append({"model": m, "error": str(exc)})
    out = REPORT / "scoring_progress_priority_olmocr_unlimited.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r.get("returncode", 1) == 0 for r in results if "error" not in r) else 1

if __name__ == "__main__":
    raise SystemExit(main())