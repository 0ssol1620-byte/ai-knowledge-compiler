"""Build leaderboard from omnidoc_raw/*/run_summary.json + metric_result.json."""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
REPORT = ROOT / "reports" / "full_compare_20260905"
RAW = REPORT / "omnidoc_raw"
KST = timezone(timedelta(hours=9))

SETTLED = {
    "paddleocr_vl_1_6", "deepseek_ocr2", "hpd_parsing", "mineru_pipeline",
    "mineru_vlm", "monkeyocrv2_b", "ovisocr2", "olmocr2", "unlimited_ocr",
    "infinity_parser2_flash",
}
REF = {"opus5_subscription", "glm_ocr", "infinity_parser2_pro"}

def edit_avg(block: dict | None) -> float | None:
    if not isinstance(block, dict):
        return None
    ed = block.get("Edit_dist") or block.get("all", {}).get("Edit_dist") if isinstance(block.get("all"), dict) else block.get("Edit_dist")
    # shape A: block["all"]["Edit_dist"]["ALL_page_avg"]
    allb = block.get("all")
    if isinstance(allb, dict):
        ed = allb.get("Edit_dist")
        if isinstance(ed, dict) and "ALL_page_avg" in ed:
            return float(ed["ALL_page_avg"])
    # shape B: block["Edit_dist"]["ALL"]["page_avg"]
    ed = block.get("Edit_dist")
    if isinstance(ed, dict):
        if "ALL_page_avg" in ed:
            return float(ed["ALL_page_avg"])
        for k in ("ALL", "all"):
            if isinstance(ed.get(k), dict) and "page_avg" in ed[k]:
                return float(ed[k]["page_avg"])
        if isinstance(ed.get("page_avg"), (int, float)):
            return float(ed["page_avg"])
    return None

def teds_avg(block: dict | None) -> float | None:
    if not isinstance(block, dict):
        return None
    # common: table["all"]["TEDS"]["all"] or table["TEDS"]["all"]
    allb = block.get("all")
    if isinstance(allb, dict):
        te = allb.get("TEDS")
        if isinstance(te, (int, float)):
            return float(te)
        if isinstance(te, dict):
            for k in ("all", "ALL", "avg", "average", "TEDS_all"):
                if isinstance(te.get(k), (int, float)):
                    return float(te[k])
                if isinstance(te.get(k), dict) and isinstance(te[k].get("avg"), (int, float)):
                    return float(te[k]["avg"])
    te = block.get("TEDS")
    if isinstance(te, (int, float)):
        return float(te)
    if isinstance(te, dict):
        for k in ("all", "ALL", "avg", "average"):
            if isinstance(te.get(k), (int, float)):
                return float(te[k])
    return None

def extract_row(summary: dict, metric_path: Path | None) -> dict:
    data = None
    if metric_path and metric_path.is_file():
        data = json.loads(metric_path.read_text(encoding="utf-8"))
    src = data or summary
    row = {
        "model": summary.get("model"),
        "tag": summary.get("tag"),
        "gt": summary.get("gt"),
        "page_count": summary.get("page_count"),
        "elapsed_seconds": summary.get("elapsed_seconds"),
        "returncode": summary.get("returncode"),
        "error": summary.get("error"),
        "text_edit": edit_avg(src.get("text_block") if isinstance(src, dict) else None),
        "formula_edit": edit_avg(src.get("display_formula") if isinstance(src, dict) else None),
        "table_edit": edit_avg(src.get("table") if isinstance(src, dict) else None),
        "table_teds": teds_avg(src.get("table") if isinstance(src, dict) else None),
        "reading_order_edit": edit_avg(src.get("reading_order") if isinstance(src, dict) else None),
    }
    if row["page_count"] is None and isinstance(src, dict):
        md = src.get("match_debug")
        if isinstance(md, dict):
            row["page_count"] = md.get("page_count")
    # debug if missing
    if row["text_edit"] is None and isinstance(src, dict) and "text_block" in src:
        tb = src["text_block"]
        row["_text_block_keys"] = list(tb.keys()) if isinstance(tb, dict) else type(tb).__name__
        if isinstance(tb, dict) and isinstance(tb.get("all"), dict):
            row["_text_all_keys"] = list(tb["all"].keys())
            ed = tb["all"].get("Edit_dist")
            if isinstance(ed, dict):
                row["_edit_keys"] = list(ed.keys())
    return row

def fmt(x, nd=4):
    return "—" if x is None else f"{x:.{nd}f}"

def main():
    rows = []
    for d in sorted(RAW.iterdir()) if RAW.exists() else []:
        if not d.is_dir():
            continue
        sp = d / "run_summary.json"
        if not sp.is_file():
            continue
        summary = json.loads(sp.read_text(encoding="utf-8"))
        rows.append(extract_row(summary, d / "metric_result.json"))

    settled = [r for r in rows if r["model"] in SETTLED and r.get("returncode") == 0 and r.get("text_edit") is not None]
    refs = [r for r in rows if r["model"] in REF and r.get("returncode") == 0 and r.get("text_edit") is not None]
    settled.sort(key=lambda r: (r["text_edit"], -(r["table_teds"] or -1)))
    refs.sort(key=lambda r: (r["text_edit"] if r["text_edit"] is not None else 9e9))

    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    lines = [
        f"# OmniDoc full-corpus comparison — {now}",
        "",
        "Edit↓ lower better; TEDS↑ higher better.",
        "GT = full OmniDocBench **1651** pages unless tag says filtered.",
        "Driver: file-redirect OmniDoc (`_win_omnidoc_score_full.py`). Cloud cost **$0**.",
        "",
        "## Settled leaderboard",
        "",
        "| Rank | Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ | pages | elapsed_min | tag |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for i, r in enumerate(settled, 1):
        em = None if not r.get("elapsed_seconds") else round(r["elapsed_seconds"] / 60, 1)
        lines.append(
            f"| {i} | `{r['model']}` | {fmt(r['text_edit'])} | {fmt(r['formula_edit'])} | {fmt(r['table_edit'])} | {fmt(r['table_teds'])} | {fmt(r['reading_order_edit'])} | {r.get('page_count') or '—'} | {em or '—'} | {r.get('tag')} |"
        )
    if not settled:
        lines.append("| — | *(none scored yet)* | | | | | | | | |")
    lines += [
        "",
        "## Reference / deferred",
        "",
        "| Model | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ | pages | notes |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    note = {
        "opus5_subscription": "REF; 21 prepare-skipped under full GT",
        "glm_ocr": "DEFERRED INVALIDATED; empty/PENDING residual; nonempty included",
        "infinity_parser2_pro": "FOUNDER_EXCLUDED; filtered GT of available preds only",
    }
    for r in refs:
        lines.append(
            f"| `{r['model']}` *(ref)* | {fmt(r['text_edit'])} | {fmt(r['formula_edit'])} | {fmt(r['table_edit'])} | {fmt(r['table_teds'])} | {fmt(r['reading_order_edit'])} | {r.get('page_count') or '—'} | {note.get(r['model'],'')} |"
        )
    if not refs:
        lines.append("| *(none scored yet)* | | | | | | | |")

    pending = []
    for m in sorted(SETTLED | REF):
        if not any(r["model"] == m and r.get("returncode") == 0 and r.get("text_edit") is not None for r in rows):
            pending.append(m)
    lines += ["", "## Pending", ", ".join(f"`{m}`" for m in pending) if pending else "_all models scored_", ""]

    # highlights
    if settled:
        best_text = settled[0]
        best_teds = max(settled, key=lambda r: r["table_teds"] or -1)
        lines += [
            "## Highlights (settled so far)",
            f"- Best text Edit↓: `{best_text['model']}` = {fmt(best_text['text_edit'])}",
            f"- Best table TEDS↑: `{best_teds['model']}` = {fmt(best_teds['table_teds'])}",
            "",
        ]

    md_path = REPORT / "comparison_omnidoc_full.md"
    json_path = REPORT / "comparison_omnidoc_full.json"
    payload = {
        "generated_at_kst": now,
        "cloud_cost_usd": 0,
        "gt_full_pages": 1651,
        "settled_leaderboard": settled,
        "reference": refs,
        "pending": pending,
        "raw_rows_debug": [r for r in rows if r.get("text_edit") is None],
        "methodology": {
            "evaluator": "OmniDocBench end2end quick_match",
            "driver": "reports/full_compare_20260905/_win_omnidoc_score_full.py",
            "gt": r"D:\CodexProjects\ai-knowledge-compiler\benchmark\datasets\acquired\public-core\omnidocbench\OmniDocBench.json",
            "no_capture_output": True,
            "gpu_spend_usd": 0,
        },
    }
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {md_path}")
    print(f"settled_scored={len(settled)} refs_scored={len(refs)} pending={pending}")
    for r in settled + refs:
        print(r["model"], "text", r["text_edit"], "teds", r["table_teds"], "pages", r["page_count"])
    for r in rows:
        if r.get("text_edit") is None:
            print("DEBUG fail", r.get("model"), {k: r[k] for k in r if k.startswith("_") or k in ("returncode","error")})

if __name__ == "__main__":
    main()
