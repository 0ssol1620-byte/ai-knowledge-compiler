import json
from pathlib import Path

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903")
RAW = ROOT / "reports" / "partial_score_20260905" / "omnidoc_raw"
REPORT = ROOT / "reports" / "partial_score_20260905"
# include prior reference models if present in triple_overlap
REF = {
    "infinity_parser2_pro": ROOT / "reports/triple_overlap_20260904/omnidoc_raw_infinity_parser2_pro/markdown_quick_match_metric_result.json",
    "opus5_subscription": ROOT / "reports/triple_overlap_20260904/omnidoc_raw_opus5_subscription/markdown_quick_match_metric_result.json",
}
# note: GLM prior result is untrusted — do not include as final

def pull(metric_path: Path):
    d = json.loads(metric_path.read_text(encoding="utf-8"))
    def ed(block, key="ALL_page_avg"):
        try:
            return d[block]["all"]["Edit_dist"][key]
        except Exception:
            return None
    def teds():
        try:
            return d["table"]["all"]["TEDS"]["all"]
        except Exception:
            return None
    return {
        "pages": (d.get("match_debug") or {}).get("page_count"),
        "text_edit": ed("text_block"),
        "formula_edit": ed("display_formula"),
        "table_edit": ed("table"),
        "table_teds": teds(),
        "reading_order_edit": ed("reading_order"),
    }

rows = []
# settled models from this pass
for model_dir in sorted(RAW.iterdir() if RAW.exists() else []):
    if not model_dir.is_dir():
        continue
    mp = model_dir / "markdown_quick_match_metric_result.json"
    if not mp.is_file():
        continue
    row = {"model": model_dir.name, "source": "partial_score_20260905", **pull(mp)}
    rows.append(row)
# references
for name, path in REF.items():
    if path.is_file():
        rows.append({"model": name, "source": "triple_overlap_20260904_reference", **pull(path)})

# sort by text_edit ascending (lower better), None last
rows_sorted = sorted(rows, key=lambda r: (r["text_edit"] is None, r["text_edit"] if r["text_edit"] is not None else 9e9))

out_json = REPORT / "comparison_omnidoc_subset.json"
out_md = REPORT / "comparison_omnidoc_subset.md"
out_json.write_text(json.dumps({"n_models": len(rows_sorted), "gt_pages": 531, "gt": "reports/triple_overlap_20260904/omnidoc_gt_triple_overlap.json", "note": "Edit_dist lower better; TEDS higher better. GLM excluded (deferred/untrusted). Infinity FOUNDER_EXCLUDED from campaign but shown as prior reference only.", "rows": rows_sorted}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

lines = [
    "# OmniDoc subset comparison (531 pages)",
    "",
    "- GT filter: `reports/triple_overlap_20260904/omnidoc_gt_triple_overlap.json` (same 531-page subset as prior Infinity/Opus pass)",
    "- Cloud cost: **$0**",
    "- **GLM deferred** (empty re-run; prior GLM OmniDoc numbers untrusted — omitted)",
    "- Infinity shown as prior reference only (`FOUNDER_EXCLUDED` from this campaign scoring)",
    "- Edit_dist ↓ better; table TEDS ↑ better",
    "",
    "| Model | source | pages | text Edit↓ | formula Edit↓ | table Edit↓ | table TEDS↑ | reading_order Edit↓ |",
    "|---|---|---:|---:|---:|---:|---:|---:|",
]
for r in rows_sorted:
    def fmt(x):
        return f"{x:.4f}" if isinstance(x, (int, float)) else "—"
    lines.append(
        f"| `{r['model']}` | {r['source']} | {r.get('pages') or '—'} | {fmt(r.get('text_edit'))} | {fmt(r.get('formula_edit'))} | {fmt(r.get('table_edit'))} | {fmt(r.get('table_teds'))} | {fmt(r.get('reading_order_edit'))} |"
    )
lines.append("")
out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {out_md} models={len(rows_sorted)}")
for r in rows_sorted:
    print(r["model"], r.get("text_edit"), r.get("table_teds"))