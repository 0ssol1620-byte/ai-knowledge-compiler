# ruff: noqa: E501  -- report strings and frozen-note literals are kept on one line on purpose
"""Render REPORT.md for the Router Oracle Dataset (ROD-v1) from RESULTS.json and SPLIT_MANIFEST.json.

usage: python report.py <out_dir>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
results = json.loads((OUT / "RESULTS.json").read_text(encoding="utf-8"))
manifest = json.loads((OUT / "SPLIT_MANIFEST.json").read_text(encoding="utf-8"))
freeze = results["freeze"]

lines: list[str] = []
w = lines.append
w("# Router Oracle Dataset v1 (ROD-v1) — OmniDocBench surface, spent 2026-09-03 Arena")
w("")
w("**This is development evidence, not a public benchmark result and not a champion promotion.**")
w("Every number is arithmetic over stored campaign files: no inference, no GPU, $0 of new spend.")
w("Page-class features come from OmniDocBench ground-truth attributes, i.e. a *perfect* page")
w(
    "classifier. Every routed arm below is therefore an **upper bound** on what a real preflight can reach."
)
w("")
w("## Dataset")
w("")
w(f"- Campaign `{freeze['campaign_id']}`; dataset id `{freeze['dataset_id']}`.")
w(
    f"- Ground-truth pages {manifest['pages_total_gt']:,}; pages with text ground truth scored by all "
    f"{len(freeze['permitted_sets']['OSS_PORTFOLIO'])} paths **{manifest['pages_in_dataset']:,}** "
    f"({manifest['pages_excluded_no_text_ground_truth']} pages have no text element and are excluded, recorded)."
)
w(f"- Document families {manifest['families_in_dataset']:,} (rule: {freeze['family_rule']}).")
w("- Family-level split (masterplan v5 §8.4), seeded, written before any score was read:")
w("")
w(
    "| split | families | pages | "
    + " | ".join(sorted(next(iter(manifest["page_class_by_split"].values()))))
    + " |"
)
w("|---|---:|---:|" + "---:|" * len(next(iter(manifest["page_class_by_split"].values()))))
for split in ("ROUTER_TRAIN", "ROUTER_CALIBRATION", "ROUTER_HOLDOUT"):
    classes = manifest["page_class_by_split"][split]
    w(
        f"| {split} | {manifest['families_per_split'][split]:,} | {manifest['pages_per_split'][split]:,} | "
        + " | ".join(
            str(classes.get(c, 0))
            for c in sorted(next(iter(manifest["page_class_by_split"].values())))
        )
        + " |"
    )
w("")
w(
    f"- Trusted = text edit distance ≤ {freeze['trusted_tau']}; catastrophic = edit ≥ {freeze['catastrophic_tau']}; "
    "a FAILED/QUARANTINED job is a provider/operational failure and stays in the denominator."
)
w(
    "- Cost and latency come from the campaign queue ledger per job (see POLICY_FREEZE.json notes); "
    f"cost-imputed pages: {results['cost_imputed_pages_by_model'] or 'none'}."
)
w(
    "- Excluded paths and why: "
    + "; ".join(f"`{k}` — {v}" for k, v in freeze["excluded_paths"].items())
    + "."
)
w("")
w("## Method")
w("")
w(
    "1. Bootstrap policy (masterplan v5 §10.5, Minimum Cost to Trusted Output): per page-class cell "
    "(page class x script family) fitted on ROUTER_TRAIN, choose the cheapest permitted path whose trusted "
    f"rate meets the floor; cells with fewer than {freeze['min_cell_pages_train']} TRAIN pages use the global choice."
)
w(
    f"2. The one knob (trust floor ∈ {freeze['required_trust_grid']}) is selected on ROUTER_CALIBRATION by lowest "
    "mean oracle regret. The holdout is opened exactly once per permitted set."
)
w(
    "3. Metrics (masterplan v5 §10.3) on ROUTER_HOLDOUT: mean quality (1 - text edit), trusted rate, trust "
    "violation, catastrophic rate, cost per page, p50/p95 latency, oracle regret under the frozen utility "
    f"policy {freeze['utility_policy']}, cost vs always-X, route mix. `ORACLE_DIAGNOSTIC` reads hidden truth "
    "and is never a router result."
)
w(
    "4. Quality and cost deltas carry a 95% cluster bootstrap interval "
    f"({freeze['bootstrap']['replicates']} replicates, resampling families)."
)
w("")

for set_name, block in results["permitted_sets"].items():
    w(f"## Permitted set `{set_name}`")
    w("")
    w(f"Permitted paths: {', '.join(f'`{p}`' for p in block['permitted'])}.")
    w(
        "Calibration (mean regret on ROUTER_CALIBRATION by trust floor): "
        + ", ".join(
            f"{k} → {v:.4f}" for k, v in block["calibration_regret_by_required_trust"].items()
        )
        + f". Selected floor **{block['selected_required_trust']}**."
    )
    w("")
    w("Fitted policy (page class | script family → path):")
    w("")
    w("| cell | path |")
    w("|---|---|")
    w(f"| default | `{block['policy']['default']}` |")
    for cell, path in block["policy"]["table"].items():
        w(f"| {cell} | `{path}` |")
    w("")
    w("Holdout results (one opening):")
    w("")
    w(
        "| arm | n | mean quality | trusted | trust violation | catastrophic | provider/op failure | $/1k pages | p50 s | p95 s | mean regret | route mix |"
    )
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    ordered = sorted(block["holdout_arms"].items(), key=lambda kv: -kv[1]["mean_quality"])
    for name, arm in ordered:
        mix = ", ".join(
            f"{k} {v}" for k, v in sorted(arm["route_mix"].items(), key=lambda kv: -kv[1])
        )
        w(
            f"| `{name}` | {arm['n_pages']} | {arm['mean_quality']:.4f} | {arm['trusted_rate']:.3f} | "
            f"{arm['trust_violation_rate']:.3f} | {arm['catastrophic_rate']:.3f} | "
            f"{arm['provider_or_operational_failure_rate']:.3f} | {arm['usd_per_1000_pages']:.2f} | "
            f"{arm['latency_p50_s']:.1f} | {arm['latency_p95_s']:.1f} | {arm['mean_oracle_regret_utility']:.4f} | {mix} |"
        )
    w("")
    c = block["comparisons"]
    q = c["quality_delta_vs_best_single"]
    cd = c["cost_delta_usd_vs_current_champion_paddle"]
    w(
        f"- Best single arm: `{c['best_single_arm']}`. BOOTSTRAP_MCTO quality delta vs best single: "
        f"**{q['point']:+.4f}** (95% CI {q['ci95'][0]:+.4f} to {q['ci95'][1]:+.4f})."
    )
    w(
        f"- Cost delta per page vs current production champion `paddleocr_vl_1_6`: {cd['point'] * 1000:+.2f} $/1k "
        f"(95% CI {cd['ci95'][0] * 1000:+.2f} to {cd['ci95'][1] * 1000:+.2f}); cost ratio vs always-champion "
        f"{c['cost_ratio_vs_always_champion']:.2f}x, vs always-cheapest {c['cost_ratio_vs_always_cheapest']:.2f}x, "
        f"vs always-best-quality {c['cost_ratio_vs_always_best_quality']:.2f}x."
    )
    cap = c["oracle_capture_ratio"]
    w(
        f"- Oracle headroom over best single: {c['oracle_headroom_quality']:.4f} quality; oracle capture ratio of "
        f"BOOTSTRAP_MCTO: {f'{cap:.3f}' if cap is not None else 'n/a'} (1.0 = oracle, 0 = best single, negative = worse than best single)."
    )
    w("")

w("## Holdout Document Performance Map (all nine paths, per path)")
w("")
w(
    "| path | n | trusted | semantic fail | provider fail | operational fail | catastrophic | mean quality | mean $/page | mean s |"
)
w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
for s in results["dpm_holdout"]:
    w(
        f"| `{s['path_id']}` | {s['sample_count']} | {s['trusted_count']} | {s['semantic_failure_count']} | "
        f"{s['provider_failure_count']} | {s['operational_failure_count']} | {s['catastrophic_count']} | "
        f"{float(s['mean_quality']):.4f} | {float(s['mean_actual_cost']):.5f} | {float(s['mean_latency_seconds']):.1f} |"
    )
w("")
w("Trusted rate by holdout cell (page class | script family), n ≥ 10 only:")
w("")
paths = [s["path_id"] for s in results["dpm_holdout"]]
w("| cell | n | " + " | ".join(f"`{p}`" for p in paths) + " |")
w("|---|---:|" + "---:|" * len(paths))
for cell, block in results["dpm_holdout_by_cell"].items():
    if block["n_pages"] < 10:
        continue
    w(
        f"| {cell} | {block['n_pages']} | "
        + " | ".join(f"{block['trusted_rate'][p]:.2f}" for p in paths)
        + " |"
    )
w("")
w("## Reading")
w("")
w(
    "- With a perfect page classifier and the production-bound paths, the class-conditional bootstrap policy is "
    "statistically indistinguishable from always-Paddle on quality and costs more (it sends multi-column Han pages to "
    "`hpd_parsing`, which ran on an H100 in this campaign)."
)
w(
    "- With the whole open-source portfolio it does not beat always-`ovisocr2`; the oracle headroom (about 1.3 "
    "quality points) is spread across paths in a way the page class does not predict. This agrees with the "
    "2026-09-08 replay (no runtime-visible arm captured any oracle headroom)."
)
w(
    "- Consequence for the router: on this corpus the value is not in choosing a model per page class. It is in "
    "(a) promoting a better champion when one is licensed and qualified, (b) failure classification and recovery, "
    'and (c) cost. Masterplan v5 §8.3 ("Oracle gain 작음 → Router complexity 재검토") applies.'
)
w(
    "- Nothing here is a fresh holdout: the corpus was spent by earlier research, so this cannot become a "
    "confirmatory result by re-splitting it. A frozen unseen corpus and a paid run with receipts remain required."
)
w("")
w("## Integrity")
w("")
w(
    f"- Dataset rows `router_oracle_dataset.jsonl` (git-ignored, Router Outcome Dataset is trade secret): sha256 `{manifest['dataset_sha256']}`."
)
w(f"- SPLIT_MANIFEST.json sha256 `{results['split_manifest_sha256']}`.")
w("- Inputs (sha256):")
for path, digest in results["inputs_sha256"].items():
    w(f"  - `{Path(path).name}` — `{digest}`")
w("")
(OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("REPORT.md written", len(lines), "lines")
