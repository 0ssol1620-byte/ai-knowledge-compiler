# ruff: noqa: E501  -- report strings and frozen-note literals are kept on one line on purpose
"""Router Oracle Dataset v1 (ROD-v1) from the spent 2026-09-03 Arena, OmniDocBench surface.

Builds masterplan v5 PART 10.2 oracle rows with a family-level 60/20/20 split (8.4), fits the
PART 10.5 bootstrap policy (Minimum Cost to Trusted Output) on ROUTER_TRAIN, selects its one
knob on ROUTER_CALIBRATION, evaluates every arm once on ROUTER_HOLDOUT with the 10.3 metrics.

Everything is arithmetic over stored files: no inference, no GPU, $0.
Page-class features come from OmniDocBench ground-truth attributes, i.e. a PERFECT page
classifier.  Every routed number is therefore an upper bound on what a real preflight can reach.

usage: python build.py <arena_root> <omnidocbench_json> <parallel_runtime_src> <out_dir>
(from the repo root: packages/parallel-runtime/src is the third argument, this directory the fourth)
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from random import Random

ARENA, GT_PATH, PRT_SRC, OUT = (Path(p) for p in sys.argv[1:5])
sys.path.insert(0, str(PRT_SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from akc_parallel_runtime.evaluation import (  # noqa: E402
    MeasuredRouteOutcome,
    OutcomeStatus,
    UtilityPolicy,
    allowed_oracle,
    document_performance_map,
    oracle_regret,
)
from rules import SPLIT_SEED, family_of, page_class, script_family, split_of  # noqa: E402

OUT.mkdir(parents=True, exist_ok=True)

# ----------------------------------------------------------------------------- freeze (written first)
FREEZE = {
    "schema": "tavonel.router_oracle_dataset.freeze.v1",
    "dataset_id": "ROD-v1-omnidoc-20260918",
    "campaign_id": "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1",
    "surface": "omnidocbench text_block per-page edit (primary); formula/table/reading_order carried as extra fields",
    "trusted_tau": 0.05,
    "catastrophic_tau": 0.50,
    "required_trust_grid": [0.80, 0.85, 0.90, 0.95],
    "min_cell_pages_train": 20,
    "split_seed": SPLIT_SEED,
    "split_fractions": {"ROUTER_TRAIN": 0.60, "ROUTER_CALIBRATION": 0.20, "ROUTER_HOLDOUT": 0.20},
    "family_rule": "image stem with a trailing _page_NNN or .pdf_NNN page suffix removed (same source document = same family); a page without such a suffix is its own family",
    "utility_policy": {
        "quality_reward": "1",
        "cost_penalty": "10",
        "latency_penalty": "0",
        "untrusted_penalty": "0.2",
        "catastrophic_penalty": "0.5",
    },
    "bootstrap": {
        "replicates": 2000,
        "seed": "ROD-v1-cluster-bootstrap-2026-09-18",
        "cluster": "family_id",
    },
    "permitted_sets": {
        "PRODUCTION_BOUND": ["paddleocr_vl_1_6", "hpd_parsing"],
        "OSS_PORTFOLIO": [
            "deepseek_ocr2",
            "glm_ocr",
            "hpd_parsing",
            "infinity_parser2_flash",
            "mineru_pipeline",
            "mineru_vlm",
            "monkeyocrv2_b",
            "ovisocr2",
            "paddleocr_vl_1_6",
        ],
    },
    "excluded_paths": {
        "olmocr2": "no per-page OmniDoc edit file in the campaign (aggregate only)",
        "unlimited_ocr": "no per-page OmniDoc edit file in the campaign (aggregate only)",
        "opus5_subscription": "closed API on a subscription surface: cost unmeasured (never zero), external egress not permitted by default",
        "infinity_parser2_pro": "FOUNDER_EXCLUDED 2026-09-04",
    },
    "feature_source": "OmniDocBench page_attribute (ground truth) = PERFECT page classifier; upper bound only",
    "notes": [
        "Thresholds and weights above were written before any score was read.",
        "Cost = job seconds x listed pod USD/h x gpu_count / 3600 from the campaign queue ledger; hpd_parsing ran on H100 ($3.49/h), most others on RTX 4090 ($0.74/h), mineru_vlm on A40 ($0.49/h). Cost reflects the campaign's GPU choice, not a price.",
        "Latency = per-job seconds (started_at to finished_at) from the campaign queue; queue wait and cold start excluded.",
        "This is a spent corpus already used by earlier research; it is development evidence, never a public benchmark result.",
    ],
}
(OUT / "POLICY_FREEZE.json").write_text(json.dumps(FREEZE, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


inputs: dict[str, str] = {}

# ----------------------------------------------------------------------------- ground truth features
gt = json.loads(GT_PATH.read_text(encoding="utf-8"))
inputs[str(GT_PATH)] = sha256_file(GT_PATH)

pages: dict[str, dict] = {}
for p in gt:
    name = p["page_info"]["image_path"]
    attr = p["page_info"].get("page_attribute", {})
    pages[name] = {
        "case_id": name,
        "family_id": family_of(name),
        "document_kind": attr.get("data_source"),
        "language": attr.get("language"),
        "layout": attr.get("layout"),
        "subset": attr.get("subset"),
        "special_issue": sorted(attr.get("special_issue") or []),
        "page_class": page_class(attr),
        "script_family": script_family(attr.get("language")),
    }


for row in pages.values():
    row["split"] = split_of(row["family_id"])

# ----------------------------------------------------------------------------- per-page edits
RAW = ARENA / "reports" / "full_compare_20260905" / "omnidoc_raw"
ELEMENTS = {
    "text": "text_block",
    "formula": "display_formula",
    "table": "table",
    "reading_order": "reading_order",
}
MODELS = sorted(set(FREEZE["permitted_sets"]["OSS_PORTFOLIO"]))
edits: dict[str, dict[str, dict[str, float]]] = {m: {} for m in MODELS}
for m in MODELS:
    for el, tag in ELEMENTS.items():
        candidates = list((RAW / m).glob(f"*quick_match_{tag}_per_page_edit.json"))
        if len(candidates) != 1:
            raise SystemExit(f"{m}/{tag}: expected one per-page file, found {candidates}")
        f = candidates[0]
        inputs[str(f)] = sha256_file(f)
        edits[m][el] = {k: float(v) for k, v in json.loads(f.read_text(encoding="utf-8")).items()}

universe = sorted(set.intersection(*(set(edits[m]["text"]) for m in MODELS)) & set(pages))
text_any = set.union(*(set(edits[m]["text"]) for m in MODELS))
assert len(universe) == len(text_any & set(pages)), "text page sets differ across models"

# ----------------------------------------------------------------------------- cost & latency
db = ARENA / "queue" / "campaign.sqlite"
inputs[str(db)] = sha256_file(db)
con = sqlite3.connect(db)
pods = {
    r[0]: r
    for r in con.execute("select pod_id, gpu_type, listed_rate_usd_per_hour, gpu_count from pods")
}
jobs: dict[tuple[str, str], dict] = {}
for model_key, sample_id, state, secs, worker in con.execute(
    "select model_key, sample_id, state, "
    "(julianday(finished_at)-julianday(started_at))*86400, worker_id from jobs "
    "where benchmark='omnidoc' order by finished_at"
).fetchall():
    stem = sample_id.split("omnidoc:images/", 1)[1]
    key = (model_key, stem)
    seconds = max(0.0, float(secs)) if secs is not None else None
    pod = pods.get((worker or "").split("-")[-1])
    cost = None
    if seconds is not None and pod is not None:
        cost = seconds * float(pod[2]) * int(pod[3] or 1) / 3600.0
    prev = jobs.get(key)
    if prev is None or state == "SUCCESS" or prev["state"] != "SUCCESS":
        jobs[key] = {
            "state": state,
            "seconds": seconds,
            "cost": cost,
            "gpu": pod[1] if pod else None,
        }

median_cost = {}
median_sec = {}
for m in MODELS:
    costs = [j["cost"] for (mk, _), j in jobs.items() if mk == m and j["cost"] is not None]
    secs = [j["seconds"] for (mk, _), j in jobs.items() if mk == m and j["seconds"] is not None]
    median_cost[m] = statistics.median(costs)
    median_sec[m] = statistics.median(secs)

# ----------------------------------------------------------------------------- oracle rows
TAU = FREEZE["trusted_tau"]
CAT = FREEZE["catastrophic_tau"]
rows: list[dict] = []
imputed = Counter()
for name in universe:
    page = pages[name]
    outcomes = []
    for m in MODELS:
        e = edits[m]
        text_edit = min(1.0, max(0.0, e["text"][name]))
        job = jobs.get((m, name.rsplit(".", 1)[0]))
        status = "TRUSTED" if text_edit <= TAU else "SEMANTIC_FAILURE"
        code = (
            None
            if status == "TRUSTED"
            else ("catastrophic_edit" if text_edit >= CAT else "edit_above_tau")
        )
        if job is not None and job["state"] != "SUCCESS":
            status = "PROVIDER_FAILURE" if job["state"] == "FAILED" else "OPERATIONAL_FAILURE"
            code = f"job_{job['state'].lower()}"
        cost = job["cost"] if job and job["cost"] is not None else None
        secs = job["seconds"] if job and job["seconds"] is not None else None
        if cost is None:
            cost = median_cost[m]
            imputed[m] += 1
        if secs is None:
            secs = median_sec[m]
        outcomes.append(
            {
                "path": m,
                "text_edit": text_edit,
                "formula_edit": e["formula"].get(name),
                "table_edit": e["table"].get(name),
                "reading_order_edit": e["reading_order"].get(name),
                "quality": 1.0 - text_edit,
                "status": status,
                "failure_code": code,
                "catastrophic": text_edit >= CAT,
                "latency_seconds": secs,
                "cost_usd": cost,
                "gpu": job["gpu"] if job else None,
            }
        )
    rows.append({**page, "path_outcomes": outcomes})

ds_path = OUT / "router_oracle_dataset.jsonl"
with ds_path.open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")

# ----------------------------------------------------------------------------- split manifest
fam_split: dict[str, str] = {}
for r in rows:
    fam_split[r["family_id"]] = r["split"]
split_counts = Counter(r["split"] for r in rows)
split_fam_counts = Counter(fam_split.values())
manifest = {
    "schema": "tavonel.router_oracle_dataset.split_manifest.v1",
    "dataset_id": FREEZE["dataset_id"],
    "pages_total_gt": len(pages),
    "pages_in_dataset": len(rows),
    "pages_excluded_no_text_ground_truth": len(pages) - len(rows),
    "families_in_dataset": len(fam_split),
    "pages_per_split": dict(split_counts),
    "families_per_split": dict(split_fam_counts),
    "family_ids_per_split": {
        s: sorted(f for f, sp in fam_split.items() if sp == s) for s in split_fam_counts
    },
    "page_class_by_split": {
        s: dict(Counter(r["page_class"] for r in rows if r["split"] == s)) for s in split_counts
    },
    "dataset_sha256": sha256_file(ds_path),
}
(OUT / "SPLIT_MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------- policies
def measured(r: dict, o: dict, permitted: set[str]) -> MeasuredRouteOutcome:
    return MeasuredRouteOutcome(
        case_id=r["case_id"],
        family_id=r["family_id"],
        path_id=o["path"],
        permitted=o["path"] in permitted,
        status=OutcomeStatus(o["status"].lower()),
        quality=Decimal(repr(round(o["quality"], 6))),
        actual_cost=Decimal(repr(round(o["cost_usd"], 8))),
        latency_seconds=Decimal(repr(round(o["latency_seconds"], 3))),
        catastrophic=o["catastrophic"] if o["status"] != "TRUSTED" else False,
        failure_code=o["failure_code"] if o["status"] != "TRUSTED" else None,
    )


UTIL = UtilityPolicy(**{k: Decimal(v) for k, v in FREEZE["utility_policy"].items()})
by_split = defaultdict(list)
for r in rows:
    by_split[r["split"]].append(r)


def cell(r: dict) -> tuple[str, str]:
    return (r["page_class"], r["script_family"])


def fit_bootstrap(train: list[dict], permitted: list[str], required_trust: float) -> dict:
    """PART 10.5: per page-class cell, cheapest permitted path whose trusted rate meets the floor."""

    def choose(subset: list[dict]) -> str:
        stats = []
        for m in permitted:
            outs = [next(o for o in r["path_outcomes"] if o["path"] == m) for r in subset]
            trusted = sum(o["status"] == "TRUSTED" for o in outs) / len(outs)
            cost = statistics.fmean(o["cost_usd"] for o in outs)
            stats.append((m, trusted, cost))
        eligible = [s for s in stats if s[1] >= required_trust]
        if eligible:
            return min(eligible, key=lambda s: (s[2], -s[1], s[0]))[0]
        return max(stats, key=lambda s: (s[1], -s[2]))[0]

    default = choose(train)
    table = {}
    groups = defaultdict(list)
    for r in train:
        groups[cell(r)].append(r)
    for c, subset in groups.items():
        table[c] = choose(subset) if len(subset) >= FREEZE["min_cell_pages_train"] else default
    return {"default": default, "table": table}


def apply_policy(policy: dict, rs: list[dict]) -> dict[str, str]:
    return {r["case_id"]: policy["table"].get(cell(r), policy["default"]) for r in rs}


def evaluate(rs: list[dict], selected: dict[str, str], permitted: set[str], label: str) -> dict:
    measured_rows = tuple(
        measured(r, o, permitted) for r in rs for o in r["path_outcomes"] if o["path"] in permitted
    )
    regrets = oracle_regret(measured_rows, selected_paths=selected, policy=UTIL)
    chosen = []
    for r in rs:
        o = next(o for o in r["path_outcomes"] if o["path"] == selected[r["case_id"]])
        chosen.append((r["family_id"], o))
    lat = [o["latency_seconds"] for _, o in chosen]
    n = len(chosen)
    return {
        "arm": label,
        "n_pages": n,
        "mean_quality": statistics.fmean(o["quality"] for _, o in chosen),
        "trusted_rate": sum(o["status"] == "TRUSTED" for _, o in chosen) / n,
        "trust_violation_rate": sum(o["status"] != "TRUSTED" for _, o in chosen) / n,
        "catastrophic_rate": sum(o["catastrophic"] for _, o in chosen) / n,
        "provider_or_operational_failure_rate": sum(
            o["status"] in {"PROVIDER_FAILURE", "OPERATIONAL_FAILURE"} for _, o in chosen
        )
        / n,
        "mean_cost_usd": statistics.fmean(o["cost_usd"] for _, o in chosen),
        "usd_per_1000_pages": 1000 * statistics.fmean(o["cost_usd"] for _, o in chosen),
        "latency_p50_s": statistics.median(lat),
        "latency_p95_s": statistics.quantiles(lat, n=20)[18],
        "mean_oracle_regret_utility": float(sum(x.regret for x in regrets) / len(regrets)),
        "route_mix": dict(Counter(selected.values())),
        "_chosen": chosen,
    }


def cluster_bootstrap_delta(
    a: list[tuple[str, dict]], b: list[tuple[str, dict]], key: str
) -> tuple[float, float, float]:
    """95% CI of mean(a.key) - mean(b.key) resampling families with replacement (paired by page order)."""
    fams = defaultdict(list)
    for (fa, oa), (_fb, ob) in zip(a, b, strict=True):
        fams[fa].append(oa[key] - ob[key])
    keys = sorted(fams)
    rng = Random(FREEZE["bootstrap"]["seed"])  # noqa: S311 - bootstrap resampling, not cryptography
    point = statistics.fmean(d for f in keys for d in fams[f])
    reps = []
    for _ in range(FREEZE["bootstrap"]["replicates"]):
        sample = [rng.choice(keys) for _ in keys]
        vals = [d for f in sample for d in fams[f]]
        reps.append(statistics.fmean(vals))
    reps.sort()
    return point, reps[int(0.025 * len(reps))], reps[int(0.975 * len(reps)) - 1]


results = {
    "freeze": FREEZE,
    "split_manifest_sha256": sha256_file(OUT / "SPLIT_MANIFEST.json"),
    "permitted_sets": {},
}
train, calib, hold = (
    by_split["ROUTER_TRAIN"],
    by_split["ROUTER_CALIBRATION"],
    by_split["ROUTER_HOLDOUT"],
)
dpm_hold = document_performance_map(
    tuple(measured(r, o, set(MODELS)) for r in hold for o in r["path_outcomes"])
)
results["dpm_holdout"] = [
    {k: (str(v) if isinstance(v, Decimal) else v) for k, v in dataclasses.asdict(s).items()}
    for s in dpm_hold
]
results["dpm_holdout_by_cell"] = {}
for c in sorted({cell(r) for r in hold}):
    subset = [r for r in hold if cell(r) == c]
    results["dpm_holdout_by_cell"]["|".join(c)] = {
        "n_pages": len(subset),
        "trusted_rate": {
            m: sum(
                next(o for o in r["path_outcomes"] if o["path"] == m)["status"] == "TRUSTED"
                for r in subset
            )
            / len(subset)
            for m in MODELS
        },
    }

for set_name, permitted_list in FREEZE["permitted_sets"].items():
    permitted = set(permitted_list)
    # calibration: pick the trust floor on ROUTER_CALIBRATION by lowest mean regret
    calib_scores = {}
    for t in FREEZE["required_trust_grid"]:
        pol = fit_bootstrap(train, permitted_list, t)
        calib_scores[str(t)] = evaluate(
            calib, apply_policy(pol, calib), permitted, f"BOOTSTRAP@{t}"
        )["mean_oracle_regret_utility"]
    best_t = float(min(calib_scores, key=lambda k: (calib_scores[k], -float(k))))
    policy = fit_bootstrap(train, permitted_list, best_t)
    arms = {}
    arms["BOOTSTRAP_MCTO"] = evaluate(hold, apply_policy(policy, hold), permitted, "BOOTSTRAP_MCTO")
    for m in permitted_list:
        arms[f"ALWAYS:{m}"] = evaluate(
            hold, {r["case_id"]: m for r in hold}, permitted, f"ALWAYS:{m}"
        )
    oracle = {
        c.case_id: c.path_id
        for c in allowed_oracle(
            tuple(
                measured(r, o, permitted)
                for r in hold
                for o in r["path_outcomes"]
                if o["path"] in permitted
            ),
            policy=UTIL,
        )
    }
    arms["ORACLE_DIAGNOSTIC"] = evaluate(hold, oracle, permitted, "ORACLE_DIAGNOSTIC")
    best_single = max(
        (a for k, a in arms.items() if k.startswith("ALWAYS:")), key=lambda a: a["mean_quality"]
    )
    champion = arms["ALWAYS:paddleocr_vl_1_6"]
    cheapest = min(
        (a for k, a in arms.items() if k.startswith("ALWAYS:")), key=lambda a: a["mean_cost_usd"]
    )
    boot = arms["BOOTSTRAP_MCTO"]
    q_point, q_lo, q_hi = cluster_bootstrap_delta(
        boot["_chosen"], best_single["_chosen"], "quality"
    )
    c_point, c_lo, c_hi = cluster_bootstrap_delta(boot["_chosen"], champion["_chosen"], "cost_usd")
    results["permitted_sets"][set_name] = {
        "permitted": permitted_list,
        "calibration_regret_by_required_trust": calib_scores,
        "selected_required_trust": best_t,
        "policy": {
            "default": policy["default"],
            "table": {"|".join(k): v for k, v in sorted(policy["table"].items())},
        },
        "holdout_arms": {
            k: {kk: vv for kk, vv in a.items() if kk != "_chosen"} for k, a in arms.items()
        },
        "comparisons": {
            "best_single_arm": best_single["arm"],
            "quality_delta_vs_best_single": {"point": q_point, "ci95": [q_lo, q_hi]},
            "cost_delta_usd_vs_current_champion_paddle": {"point": c_point, "ci95": [c_lo, c_hi]},
            "cost_ratio_vs_always_champion": boot["mean_cost_usd"] / champion["mean_cost_usd"],
            "cost_ratio_vs_always_cheapest": boot["mean_cost_usd"] / cheapest["mean_cost_usd"],
            "cost_ratio_vs_always_best_quality": boot["mean_cost_usd"]
            / best_single["mean_cost_usd"],
            "oracle_headroom_quality": arms["ORACLE_DIAGNOSTIC"]["mean_quality"]
            - best_single["mean_quality"],
            "oracle_capture_ratio": (
                (boot["mean_quality"] - best_single["mean_quality"])
                / (arms["ORACLE_DIAGNOSTIC"]["mean_quality"] - best_single["mean_quality"])
                if arms["ORACLE_DIAGNOSTIC"]["mean_quality"] > best_single["mean_quality"]
                else None
            ),
        },
    }

results["inputs_sha256"] = inputs
results["cost_imputed_pages_by_model"] = dict(imputed)
results["median_cost_usd_by_model"] = median_cost
results["median_latency_s_by_model"] = median_sec
(OUT / "RESULTS.json").write_text(
    json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
)
print(
    json.dumps(
        {
            "pages": len(rows),
            "splits": dict(split_counts),
            "families": len(fam_split),
            "imputed": dict(imputed),
        },
        indent=1,
    )
)
for set_name, res in results["permitted_sets"].items():
    print("==", set_name, "required_trust", res["selected_required_trust"], "policy", res["policy"])
    for k, a in res["holdout_arms"].items():
        print(
            f"  {k:32s} q={a['mean_quality']:.4f} trusted={a['trusted_rate']:.3f} cat={a['catastrophic_rate']:.3f} $/1k={a['usd_per_1000_pages']:.2f} p50={a['latency_p50_s']:.1f}s regret={a['mean_oracle_regret_utility']:.4f} mix={a['route_mix']}"
        )
    print("  comparisons", json.dumps(res["comparisons"]))
