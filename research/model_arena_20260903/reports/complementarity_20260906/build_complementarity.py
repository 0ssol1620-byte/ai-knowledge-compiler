# -*- coding: utf-8 -*-
"""Build Model Complementarity Matrix from OmniDoc per-page edit distances.
NO re-inference. Reads existing per-page edit JSONs only.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\full_compare_20260905\omnidoc_raw")
OUT = Path(r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903\reports\complementarity_20260906")

MODELS = [
    "paddleocr_vl_1_6",
    "ovisocr2",
    "infinity_parser2_flash",
    "deepseek_ocr2",
    "glm_ocr",
    "opus5_subscription",
]
SHORT = {
    "paddleocr_vl_1_6": "paddle",
    "ovisocr2": "ovis",
    "infinity_parser2_flash": "flash",
    "deepseek_ocr2": "deepseek",
    "glm_ocr": "glm",
    "opus5_subscription": "opus",
}
BASELINE = "paddleocr_vl_1_6"

ELEMENTS = {
    "text": "text_block",
    "formula": "display_formula",
    "table": "table",
    "reading_order": "reading_order",
}

TAU = 0.05
EPS = 1e-9


def find_per_page_file(model: str, element_key: str) -> Path:
    d = ROOT / model
    # Prefer exact suffix match
    candidates = list(d.glob(f"*{element_key}_per_page_edit.json"))
    if not candidates:
        raise FileNotFoundError(f"No {element_key} per_page_edit for {model}")
    if len(candidates) > 1:
        # Prefer markdown_quick_match / md_*_quick_match
        preferred = [c for c in candidates if "quick_match" in c.name]
        candidates = preferred or candidates
    return candidates[0]


def load_edits(model: str, element_key: str) -> Dict[str, float]:
    path = find_per_page_file(model, element_key)
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for k, v in data.items():
        try:
            e = float(v)
        except (TypeError, ValueError):
            continue
        if math.isnan(e) or math.isinf(e):
            continue
        # clip to [0,1]
        e = max(0.0, min(1.0, e))
        out[str(k)] = e
    return out


def clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def mean(xs: List[float]) -> float:
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


def fmt(x: Optional[float], digits: int = 4) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{x:.{digits}f}"


def pct(x: Optional[float], digits: int = 1) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "n/a"
    return f"{100.0 * x:.{digits}f}%"


def pair_oracle(edits_a: Dict[str, float], edits_b: Dict[str, float]) -> dict:
    shared = sorted(set(edits_a) & set(edits_b))
    if not shared:
        return {
            "n_pages": 0,
            "alone_mean_edit_A": float("nan"),
            "alone_mean_edit_B": float("nan"),
            "alone_score_A": float("nan"),
            "alone_score_B": float("nan"),
            "oracle_edit": float("nan"),
            "oracle_score": float("nan"),
            "oracle_gain_A": float("nan"),
            "oracle_gain_B": float("nan"),
        }
    ea = [edits_a[p] for p in shared]
    eb = [edits_b[p] for p in shared]
    omin = [min(a, b) for a, b in zip(ea, eb)]
    alone_a = mean(ea)
    alone_b = mean(eb)
    oracle_e = mean(omin)
    score_a = 1.0 - alone_a
    score_b = 1.0 - alone_b
    oracle_s = 1.0 - oracle_e
    return {
        "n_pages": len(shared),
        "alone_mean_edit_A": alone_a,
        "alone_mean_edit_B": alone_b,
        "alone_score_A": score_a,
        "alone_score_B": score_b,
        "oracle_edit": oracle_e,
        "oracle_score": oracle_s,
        "oracle_gain_A": oracle_s - score_a,
        "oracle_gain_B": oracle_s - score_b,
    }


def pair_rescue(edits_a: Dict[str, float], edits_b: Dict[str, float], tau: float = TAU, eps: float = EPS) -> dict:
    shared = sorted(set(edits_a) & set(edits_b))
    n = len(shared)
    if n == 0:
        return {
            "n_pages": 0,
            "tau": tau,
            "n_A_wrong": 0,
            "n_B_wrong": 0,
            "n_both_wrong": 0,
            "n_A_wrong_B_correct": 0,
            "n_B_wrong_A_correct": 0,
            "n_disagree_wrong": 0,
            "n_disagree_edit": 0,
            "P_B_wrong_given_A_wrong": float("nan"),
            "P_B_correct_given_A_wrong": float("nan"),  # rescue rate
            "P_A_wrong_given_B_wrong": float("nan"),
            "P_A_correct_given_B_wrong": float("nan"),
            "P_both_wrong": float("nan"),
            "P_A_wrong": float("nan"),
            "P_B_wrong": float("nan"),
            "P_A_wrong_given_disagreement": float("nan"),
            "P_disagree": float("nan"),
        }
    a_wrong = []
    b_wrong = []
    both_wrong = 0
    a_wrong_b_ok = 0
    b_wrong_a_ok = 0
    disagree_wrong = 0
    disagree_edit = 0
    for p in shared:
        ea = edits_a[p]
        eb = edits_b[p]
        aw = ea > tau
        bw = eb > tau
        a_wrong.append(aw)
        b_wrong.append(bw)
        if aw and bw:
            both_wrong += 1
        if aw and not bw:
            a_wrong_b_ok += 1
        if bw and not aw:
            b_wrong_a_ok += 1
        if aw != bw:
            disagree_wrong += 1
        if abs(ea - eb) > eps:
            disagree_edit += 1
    n_aw = sum(a_wrong)
    n_bw = sum(b_wrong)
    # disagreement for conditional: wrong-label disagree OR edit differ by >eps
    # User asked: P(A wrong | A!=B disagreement) where disagreement = (A wrong)!=(B wrong) OR edits differ by >eps
    disagree_pages = []
    for p in shared:
        ea = edits_a[p]
        eb = edits_b[p]
        aw = ea > tau
        bw = eb > tau
        if (aw != bw) or (abs(ea - eb) > eps):
            disagree_pages.append(aw)
    n_dis = len(disagree_pages)
    n_a_wrong_on_dis = sum(1 for aw in disagree_pages if aw)

    def safe_div(num, den):
        return (num / den) if den else float("nan")

    return {
        "n_pages": n,
        "tau": tau,
        "n_A_wrong": n_aw,
        "n_B_wrong": n_bw,
        "n_both_wrong": both_wrong,
        "n_A_wrong_B_correct": a_wrong_b_ok,
        "n_B_wrong_A_correct": b_wrong_a_ok,
        "n_disagree_wrong": disagree_wrong,
        "n_disagree_edit": disagree_edit,
        "P_B_wrong_given_A_wrong": safe_div(both_wrong, n_aw),
        "P_B_correct_given_A_wrong": safe_div(a_wrong_b_ok, n_aw),  # rescue by B when A wrong
        "P_A_wrong_given_B_wrong": safe_div(both_wrong, n_bw),
        "P_A_correct_given_B_wrong": safe_div(b_wrong_a_ok, n_bw),
        "P_both_wrong": safe_div(both_wrong, n),
        "P_A_wrong": safe_div(n_aw, n),
        "P_B_wrong": safe_div(n_bw, n),
        "P_A_wrong_given_disagreement": safe_div(n_a_wrong_on_dis, n_dis),
        "P_disagree": safe_div(n_dis, n),
    }


def md_table(headers: List[str], rows: List[List[str]]) -> str:
    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def main():
    OUT.mkdir(parents=True, exist_ok=True)

    # Load all edits
    data: Dict[str, Dict[str, Dict[str, float]]] = {}  # element -> model -> page -> edit
    page_counts = {}
    file_map = {}
    for elem_name, elem_key in ELEMENTS.items():
        data[elem_name] = {}
        page_counts[elem_name] = {}
        file_map[elem_name] = {}
        for m in MODELS:
            path = find_per_page_file(m, elem_key)
            edits = load_edits(m, elem_key)
            data[elem_name][m] = edits
            page_counts[elem_name][m] = len(edits)
            file_map[elem_name][m] = str(path)

    # Intersection page counts per element
    intersections = {}
    for elem_name in ELEMENTS:
        sets = [set(data[elem_name][m].keys()) for m in MODELS]
        inter = set.intersection(*sets) if sets else set()
        intersections[elem_name] = sorted(inter)

    # Pairwise oracle & rescue for each element
    oracle_results = {}  # elem -> {pair_key -> metrics}
    rescue_results = {}
    alone_scores = {}  # elem -> model -> {n, mean_edit, score} on full model pages and on all-model intersection

    for elem_name in list(ELEMENTS.keys()):
        oracle_results[elem_name] = {}
        rescue_results[elem_name] = {}
        alone_scores[elem_name] = {}
        inter_pages = set(intersections[elem_name])
        for m in MODELS:
            edits = data[elem_name][m]
            # alone on model's own pages
            vals = list(edits.values())
            # alone on full intersection of all models
            vals_inter = [edits[p] for p in inter_pages if p in edits]
            alone_scores[elem_name][m] = {
                "n_pages_model": len(vals),
                "mean_edit_model": mean(vals),
                "score_model": 1.0 - mean(vals) if vals else float("nan"),
                "n_pages_all_intersect": len(vals_inter),
                "mean_edit_all_intersect": mean(vals_inter),
                "score_all_intersect": 1.0 - mean(vals_inter) if vals_inter else float("nan"),
            }
        for i, a in enumerate(MODELS):
            for b in MODELS[i + 1 :]:
                key = f"{SHORT[a]}__{SHORT[b]}"
                oa = pair_oracle(data[elem_name][a], data[elem_name][b])
                oa["model_A"] = a
                oa["model_B"] = b
                oa["short_A"] = SHORT[a]
                oa["short_B"] = SHORT[b]
                oracle_results[elem_name][key] = oa
                rb = pair_rescue(data[elem_name][a], data[elem_name][b], tau=TAU)
                rb["model_A"] = a
                rb["model_B"] = b
                rb["short_A"] = SHORT[a]
                rb["short_B"] = SHORT[b]
                rescue_results[elem_name][key] = rb

    # ---- Build oracle matrix MD/JSON ----
    # Full pairwise oracle score matrix per element + paddle-baseline gains

    oracle_json = {
        "methodology": {
            "score": "1 - clip(edit, [0,1])",
            "oracle_edit": "mean(min(edit_A, edit_B)) on page intersection",
            "oracle_gain_vs_A": "oracle_score - alone_score_A",
            "primary": "continuous oracle (no hard threshold)",
            "baseline": BASELINE,
            "models": MODELS,
            "elements": list(ELEMENTS.keys()),
        },
        "page_counts": page_counts,
        "all_model_intersections": {e: len(intersections[e]) for e in ELEMENTS},
        "file_map": file_map,
        "alone_scores": alone_scores,
        "pairwise": oracle_results,
        "oracle_score_matrices": {},
        "oracle_gain_vs_paddle": {},
    }

    md_oracle_parts = []
    md_oracle_parts.append("# Complementarity Oracle Matrix")
    md_oracle_parts.append("")
    md_oracle_parts.append("Continuous oracle (primary router ceiling). Page score = `1 - edit` (edit clipped to [0,1]).")
    md_oracle_parts.append("`oracle_edit = mean(min(edit_A, edit_B))` on shared pages; `oracle_gain_A = oracle_score - alone_score_A`.")
    md_oracle_parts.append("")
    md_oracle_parts.append("## Page counts")
    md_oracle_parts.append("")
    pc_headers = ["element"] + [SHORT[m] for m in MODELS] + ["all_intersect"]
    pc_rows = []
    for e in ELEMENTS:
        pc_rows.append([e] + [str(page_counts[e][m]) for m in MODELS] + [str(len(intersections[e]))])
    md_oracle_parts.append(md_table(pc_headers, pc_rows))
    md_oracle_parts.append("")

    for elem_name in ELEMENTS:
        md_oracle_parts.append(f"## Element: `{elem_name}`")
        md_oracle_parts.append("")
        # Alone scores on pairwise will differ; show all-intersect alone
        alone_headers = ["model", "n_pages", "alone_mean_edit", "alone_score (all-intersect)"]
        alone_rows = []
        for m in MODELS:
            s = alone_scores[elem_name][m]
            alone_rows.append([
                SHORT[m],
                str(s["n_pages_all_intersect"]),
                fmt(s["mean_edit_all_intersect"]),
                fmt(s["score_all_intersect"]),
            ])
        md_oracle_parts.append("### Alone scores (all-model page intersection)")
        md_oracle_parts.append("")
        md_oracle_parts.append(md_table(alone_headers, alone_rows))
        md_oracle_parts.append("")

        # Oracle score matrix (symmetric)
        labels = [SHORT[m] for m in MODELS]
        mat = {a: {b: None for b in MODELS} for a in MODELS}
        for m in MODELS:
            # diagonal = alone on all-intersect
            mat[m][m] = alone_scores[elem_name][m]["score_all_intersect"]
        for key, oa in oracle_results[elem_name].items():
            a, b = oa["model_A"], oa["model_B"]
            mat[a][b] = oa["oracle_score"]
            mat[b][a] = oa["oracle_score"]
        oracle_json["oracle_score_matrices"][elem_name] = {
            SHORT[a]: {SHORT[b]: mat[a][b] for b in MODELS} for a in MODELS
        }

        headers = ["oracle_score"] + labels
        rows = []
        for a in MODELS:
            rows.append([SHORT[a]] + [fmt(mat[a][b]) for b in MODELS])
        md_oracle_parts.append("### Pairwise oracle scores (diag = alone)")
        md_oracle_parts.append("")
        md_oracle_parts.append(md_table(headers, rows))
        md_oracle_parts.append("")

        # Gain vs paddle matrix: for each peer, oracle_gain when paddle is baseline
        # Also full pairwise gain when row is baseline
        gain_mat = {a: {b: 0.0 if a == b else None for b in MODELS} for a in MODELS}
        for key, oa in oracle_results[elem_name].items():
            a, b = oa["model_A"], oa["model_B"]
            # gain for A as baseline pairing with B
            gain_mat[a][b] = oa["oracle_gain_A"]
            gain_mat[b][a] = oa["oracle_gain_B"]
        oracle_json["oracle_gain_vs_paddle"][elem_name] = {}
        for m in MODELS:
            if m == BASELINE:
                continue
            # find pair
            for key, oa in oracle_results[elem_name].items():
                if {oa["model_A"], oa["model_B"]} == {BASELINE, m}:
                    if oa["model_A"] == BASELINE:
                        g = oa["oracle_gain_A"]
                        alone_p = oa["alone_score_A"]
                        alone_peer = oa["alone_score_B"]
                        n = oa["n_pages"]
                        oscore = oa["oracle_score"]
                    else:
                        g = oa["oracle_gain_B"]
                        alone_p = oa["alone_score_B"]
                        alone_peer = oa["alone_score_A"]
                        n = oa["n_pages"]
                        oscore = oa["oracle_score"]
                    oracle_json["oracle_gain_vs_paddle"][elem_name][SHORT[m]] = {
                        "n_pages": n,
                        "paddle_alone_score": alone_p,
                        "peer_alone_score": alone_peer,
                        "oracle_score": oscore,
                        "oracle_gain_vs_paddle": g,
                    }

        headers = ["oracle_gain (row=baseline)"] + labels
        rows = []
        for a in MODELS:
            rows.append([SHORT[a]] + [fmt(gain_mat[a][b]) if gain_mat[a][b] is not None else "—" for b in MODELS])
        md_oracle_parts.append("### Oracle gain (row = baseline model)")
        md_oracle_parts.append("")
        md_oracle_parts.append(md_table(headers, rows))
        md_oracle_parts.append("")

        # Focus table: paddle + each peer
        md_oracle_parts.append("### Paddle baseline + peer")
        md_oracle_parts.append("")
        ph = ["peer", "n_pages", "paddle_alone", "peer_alone", "oracle_score", "oracle_gain_vs_paddle"]
        pr = []
        for m in MODELS:
            if m == BASELINE:
                continue
            info = oracle_json["oracle_gain_vs_paddle"][elem_name].get(SHORT[m], {})
            pr.append([
                SHORT[m],
                str(info.get("n_pages", "")),
                fmt(info.get("paddle_alone_score")),
                fmt(info.get("peer_alone_score")),
                fmt(info.get("oracle_score")),
                fmt(info.get("oracle_gain_vs_paddle")),
            ])
        md_oracle_parts.append(md_table(ph, pr))
        md_oracle_parts.append("")

    (OUT / "complementarity_oracle_matrix.md").write_text("\n".join(md_oracle_parts), encoding="utf-8")
    (OUT / "complementarity_oracle_matrix.json").write_text(
        json.dumps(oracle_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- Rescue matrix ----
    rescue_json = {
        "methodology": {
            "tau": TAU,
            "wrong": f"edit > {TAU}",
            "rescue_rate": "P(B correct | A wrong) = P(edit_B <= tau | edit_A > tau)",
            "overlap": f"P(B wrong | A wrong), P(both wrong)",
            "disagreement": f"(A wrong)!=(B wrong) OR |edit_A-edit_B| > {EPS}",
            "baseline": BASELINE,
            "models": MODELS,
            "note_tau0": "Primary discrete tables use tau=0.05. Strict tau=0.0 (any nonzero edit=wrong) is more brittle; continuous oracle is preferred for router ceiling.",
        },
        "pairwise": rescue_results,
        "rescue_matrices_given_row_wrong": {},
        "paddle_rescue_by_peer": {},
    }

    md_rescue_parts = []
    md_rescue_parts.append("# Complementarity Rescue / Overlap Matrix")
    md_rescue_parts.append("")
    md_rescue_parts.append(f"Discrete metrics at **tau={TAU}** (wrong if edit > tau).")
    md_rescue_parts.append("Rescue rate = `P(B correct | A wrong)`. Overlap = `P(B wrong | A wrong)`.")
    md_rescue_parts.append("")

    for elem_name in ELEMENTS:
        md_rescue_parts.append(f"## Element: `{elem_name}`")
        md_rescue_parts.append("")

        # Matrix: cell (A,B) = P(B correct | A wrong) when A!=B; diag = P(A wrong)
        rescue_mat = {a: {b: None for b in MODELS} for a in MODELS}
        overlap_mat = {a: {b: None for b in MODELS} for a in MODELS}
        both_mat = {a: {b: None for b in MODELS} for a in MODELS}

        for m in MODELS:
            # need P(A wrong) — use pair with any other, or compute on all-intersect
            edits = data[elem_name][m]
            inter = intersections[elem_name]
            n_wrong = sum(1 for p in inter if edits.get(p, 0) > TAU)
            p_wrong = (n_wrong / len(inter)) if inter else float("nan")
            rescue_mat[m][m] = p_wrong  # diag shows P(wrong)
            overlap_mat[m][m] = p_wrong
            both_mat[m][m] = p_wrong

        for key, rb in rescue_results[elem_name].items():
            a, b = rb["model_A"], rb["model_B"]
            # P(B correct | A wrong)
            rescue_mat[a][b] = rb["P_B_correct_given_A_wrong"]
            rescue_mat[b][a] = rb["P_A_correct_given_B_wrong"]
            overlap_mat[a][b] = rb["P_B_wrong_given_A_wrong"]
            overlap_mat[b][a] = rb["P_A_wrong_given_B_wrong"]
            both_mat[a][b] = rb["P_both_wrong"]
            both_mat[b][a] = rb["P_both_wrong"]

        rescue_json["rescue_matrices_given_row_wrong"][elem_name] = {
            "rescue_P_col_correct_given_row_wrong": {
                SHORT[a]: {SHORT[b]: rescue_mat[a][b] for b in MODELS} for a in MODELS
            },
            "overlap_P_col_wrong_given_row_wrong": {
                SHORT[a]: {SHORT[b]: overlap_mat[a][b] for b in MODELS} for a in MODELS
            },
            "P_both_wrong": {
                SHORT[a]: {SHORT[b]: both_mat[a][b] for b in MODELS} for a in MODELS
            },
        }

        labels = [SHORT[m] for m in MODELS]
        headers = ["rescue P(col OK|row wrong); diag=P(wrong)"] + labels
        rows = []
        for a in MODELS:
            rows.append([SHORT[a]] + [pct(rescue_mat[a][b]) for b in MODELS])
        md_rescue_parts.append("### Rescue rate matrix (diag = P(wrong) at tau)")
        md_rescue_parts.append("")
        md_rescue_parts.append(md_table(headers, rows))
        md_rescue_parts.append("")

        headers = ["overlap P(col wrong|row wrong)"] + labels
        rows = []
        for a in MODELS:
            rows.append([SHORT[a]] + [pct(overlap_mat[a][b]) for b in MODELS])
        md_rescue_parts.append("### Overlap P(B wrong | A wrong)")
        md_rescue_parts.append("")
        md_rescue_parts.append(md_table(headers, rows))
        md_rescue_parts.append("")

        headers = ["P(both wrong)"] + labels
        rows = []
        for a in MODELS:
            rows.append([SHORT[a]] + [pct(both_mat[a][b]) for b in MODELS])
        md_rescue_parts.append("### P(both wrong) on shared pages")
        md_rescue_parts.append("")
        md_rescue_parts.append(md_table(headers, rows))
        md_rescue_parts.append("")

        # Disagreement conditional
        md_rescue_parts.append("### Disagreement stats (pairwise)")
        md_rescue_parts.append("")
        dh = ["pair", "n_pages", "P_disagree", "P(A wrong|disagree)", "P_both_wrong", "rescue_B|A_wrong", "rescue_A|B_wrong"]
        dr = []
        for key, rb in sorted(rescue_results[elem_name].items()):
            dr.append([
                f"{rb['short_A']}+{rb['short_B']}",
                str(rb["n_pages"]),
                pct(rb["P_disagree"]),
                pct(rb["P_A_wrong_given_disagreement"]),
                pct(rb["P_both_wrong"]),
                pct(rb["P_B_correct_given_A_wrong"]),
                pct(rb["P_A_correct_given_B_wrong"]),
            ])
        md_rescue_parts.append(md_table(dh, dr))
        md_rescue_parts.append("")

        # Paddle-focused rescue
        rescue_json["paddle_rescue_by_peer"][elem_name] = {}
        md_rescue_parts.append("### When Paddle is wrong: peer rescue")
        md_rescue_parts.append("")
        ph = ["peer", "n_pages", "n_paddle_wrong", "rescue_rate", "P(peer wrong|paddle wrong)", "P(both wrong)"]
        pr = []
        for m in MODELS:
            if m == BASELINE:
                continue
            for key, rb in rescue_results[elem_name].items():
                if {rb["model_A"], rb["model_B"]} == {BASELINE, m}:
                    if rb["model_A"] == BASELINE:
                        rescue_rate = rb["P_B_correct_given_A_wrong"]
                        overlap = rb["P_B_wrong_given_A_wrong"]
                        n_pw = rb["n_A_wrong"]
                    else:
                        rescue_rate = rb["P_A_correct_given_B_wrong"]
                        overlap = rb["P_A_wrong_given_B_wrong"]
                        n_pw = rb["n_B_wrong"]
                    rescue_json["paddle_rescue_by_peer"][elem_name][SHORT[m]] = {
                        "n_pages": rb["n_pages"],
                        "n_paddle_wrong": n_pw,
                        "rescue_rate": rescue_rate,
                        "P_peer_wrong_given_paddle_wrong": overlap,
                        "P_both_wrong": rb["P_both_wrong"],
                    }
                    pr.append([
                        SHORT[m],
                        str(rb["n_pages"]),
                        str(n_pw),
                        pct(rescue_rate),
                        pct(overlap),
                        pct(rb["P_both_wrong"]),
                    ])
        md_rescue_parts.append(md_table(ph, pr))
        md_rescue_parts.append("")

    (OUT / "complementarity_rescue_matrix.md").write_text("\n".join(md_rescue_parts), encoding="utf-8")
    (OUT / "complementarity_rescue_matrix.json").write_text(
        json.dumps(rescue_json, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---- Leaderboard ----
    lb_parts = []
    lb_parts.append("# Complementarity Leaderboard")
    lb_parts.append("")
    lb_parts.append("Peers ranked vs **paddle** baseline. Higher rescue / higher oracle gain = more complementary.")
    lb_parts.append("")

    for elem_name in ELEMENTS:
        lb_parts.append(f"## `{elem_name}`")
        lb_parts.append("")

        # By rescue rate
        peers_rescue = []
        for peer, info in rescue_json["paddle_rescue_by_peer"][elem_name].items():
            peers_rescue.append((peer, info.get("rescue_rate") or float("nan"), info))
        peers_rescue.sort(key=lambda x: (-(x[1] if not math.isnan(x[1]) else -1), x[0]))

        lb_parts.append("### Rank by rescue rate (P(peer OK | paddle wrong), tau=0.05)")
        lb_parts.append("")
        rh = ["rank", "peer", "rescue_rate", "n_paddle_wrong", "n_pages"]
        rr = []
        for i, (peer, rate, info) in enumerate(peers_rescue, 1):
            rr.append([str(i), peer, pct(rate), str(info.get("n_paddle_wrong")), str(info.get("n_pages"))])
        lb_parts.append(md_table(rh, rr))
        lb_parts.append("")

        # By oracle gain
        peers_oracle = []
        for peer, info in oracle_json["oracle_gain_vs_paddle"][elem_name].items():
            peers_oracle.append((peer, info.get("oracle_gain_vs_paddle") or float("nan"), info))
        peers_oracle.sort(key=lambda x: (-(x[1] if not math.isnan(x[1]) else -1), x[0]))

        lb_parts.append("### Rank by oracle gain vs paddle")
        lb_parts.append("")
        oh = ["rank", "peer", "oracle_gain", "oracle_score", "paddle_alone", "peer_alone", "n_pages"]
        orows = []
        for i, (peer, gain, info) in enumerate(peers_oracle, 1):
            orows.append([
                str(i), peer, fmt(gain), fmt(info.get("oracle_score")),
                fmt(info.get("paddle_alone_score")), fmt(info.get("peer_alone_score")),
                str(info.get("n_pages")),
            ])
        lb_parts.append(md_table(oh, orows))
        lb_parts.append("")

    (OUT / "complementarity_leaderboard.md").write_text("\n".join(lb_parts), encoding="utf-8")

    # ---- NOTES ----
    notes = []
    notes.append("# NOTES — Model Complementarity Matrix")
    notes.append("")
    notes.append("## Scope")
    notes.append("- Built from existing OmniDocBench-style **per-page edit distances** under `omnidoc_raw/`.")
    notes.append("- **No re-inference.** Sequential scoring chain left untouched.")
    notes.append("- Models: paddleocr_vl_1_6, infinity_parser2_flash, deepseek_ocr2, glm_ocr, opus5_subscription.")
    notes.append("- Elements: text_block → text, display_formula → formula, table, reading_order.")
    notes.append("- **ALL / overall** surface: **text_block is primary** (most pages). Separate matrices per element; there is no synthetic average-of-elements ALL matrix — use the `text` section as the overall complementarity surface.")
    notes.append("")
    notes.append("## Continuous oracle (primary for router ceiling)")
    notes.append("- Clip each page edit to [0,1].")
    notes.append("- `alone_mean_edit = mean(edit)` on shared pages of the pair (or all-model intersection for alone tables).")
    notes.append("- `alone_score = 1 - alone_mean_edit`.")
    notes.append("- `oracle_edit = mean(min(edit_A, edit_B))` — perfect page-wise router picking the better model.")
    notes.append("- `oracle_score = 1 - oracle_edit`.")
    notes.append("- `oracle_gain_A = oracle_score - alone_score_A` (gain when A is baseline).")
    notes.append("- No hard threshold; uses continuous edits.")
    notes.append("")
    notes.append("## Discrete rescue / overlap (tau=0.05)")
    notes.append("- Wrong if `edit > 0.05`.")
    notes.append("- Rescue rate: `P(B correct | A wrong)`.")
    notes.append("- Overlap: `P(B wrong | A wrong)`, `P(both wrong)`.")
    notes.append("- Disagreement: `(A wrong) != (B wrong)` OR `|edit_A - edit_B| > 1e-9`.")
    notes.append("- Report `P(A wrong | disagreement)` on those pages.")
    notes.append("- **tau=0.0 sensitivity:** any nonzero edit = wrong is extremely strict and noisy for near-zero floating edits; we keep tau=0.05 for discrete tables and rely on continuous oracle for ceiling. Primary tables use tau=0.05.")
    notes.append("")
    notes.append("## Pairwise page intersection")
    notes.append("- Every pair metric uses **intersection of pages present in both models' per-page JSON** for that element.")
    notes.append("- Alone score tables labeled all-intersect use intersection of **all five** models for that element.")
    notes.append("- Page-count mismatches across models are expected if some pages failed scoring for one model; see page_counts in JSON.")
    notes.append("")
    notes.append("## File prefixes")
    notes.append("- paddle / deepseek: `markdown_quick_match_*_per_page_edit.json`")
    notes.append("- flash / glm / opus: `md_<model>_quick_match_*_per_page_edit.json`")
    notes.append("")
    notes.append("## Outputs")
    notes.append("- `complementarity_oracle_matrix.md` / `.json`")
    notes.append("- `complementarity_rescue_matrix.md` / `.json`")
    notes.append("- `complementarity_leaderboard.md`")
    notes.append("- `NOTES.md` (this file)")
    notes.append("")
    (OUT / "NOTES.md").write_text("\n".join(notes), encoding="utf-8")

    # ---- ASCII Korean-friendly summary ----
    def best_peer(elem, kind):
        if kind == "rescue":
            items = rescue_json["paddle_rescue_by_peer"][elem]
            ranked = sorted(items.items(), key=lambda kv: (-(kv[1].get("rescue_rate") or -1), kv[0]))
            if not ranked:
                return None, None
            return ranked[0][0], ranked[0][1].get("rescue_rate")
        else:
            items = oracle_json["oracle_gain_vs_paddle"][elem]
            ranked = sorted(items.items(), key=lambda kv: (-(kv[1].get("oracle_gain_vs_paddle") or -1), kv[0]))
            if not ranked:
                return None, None
            return ranked[0][0], ranked[0][1].get("oracle_gain_vs_paddle")

    paddle_text_alone = alone_scores["text"][BASELINE]["score_all_intersect"]
    paddle_text_edit = alone_scores["text"][BASELINE]["mean_edit_all_intersect"]

    print("=" * 60)
    print("COMPLEMENTARITY SUMMARY (Korean-friendly)")
    print("=" * 60)
    print(f"Paddle alone (text / ALL-primary): score={fmt(paddle_text_alone)}  mean_edit={fmt(paddle_text_edit)}  n={alone_scores['text'][BASELINE]['n_pages_all_intersect']}")
    print()
    print("Oracle gains vs Paddle (text):")
    for peer in ["flash", "deepseek", "glm", "opus"]:
        info = oracle_json["oracle_gain_vs_paddle"]["text"].get(peer, {})
        print(f"  Paddle+{peer:8s}: gain={fmt(info.get('oracle_gain_vs_paddle'))}  oracle={fmt(info.get('oracle_score'))}  peer_alone={fmt(info.get('peer_alone_score'))}  n={info.get('n_pages')}")
    print()
    print("Oracle gains vs Paddle by element (gain only):")
    for elem in ELEMENTS:
        bits = []
        for peer in ["flash", "deepseek", "glm", "opus"]:
            g = oracle_json["oracle_gain_vs_paddle"][elem].get(peer, {}).get("oracle_gain_vs_paddle")
            bits.append(f"{peer}={fmt(g)}")
        pa = alone_scores[elem][BASELINE]["score_all_intersect"]
        print(f"  {elem:14s} paddle_alone={fmt(pa)} | " + " ".join(bits))
    print()
    br, brv = best_peer("text", "rescue")
    bo, bov = best_peer("text", "oracle")
    print(f"Best peer for Paddle (text) by rescue rate : {br} ({pct(brv)})")
    print(f"Best peer for Paddle (text) by oracle gain : {bo} (+{fmt(bov)})")
    print()
    print("Page-count mismatches (per element, model n_pages):")
    for e in ELEMENTS:
        counts = [page_counts[e][m] for m in MODELS]
        mismatch = len(set(counts)) > 1
        print(f"  {e}: { {SHORT[m]: page_counts[e][m] for m in MODELS} } all_intersect={len(intersections[e])} mismatch={mismatch}")
    print()
    print("Written:")
    for f in [
        "complementarity_oracle_matrix.md",
        "complementarity_oracle_matrix.json",
        "complementarity_rescue_matrix.md",
        "complementarity_rescue_matrix.json",
        "complementarity_leaderboard.md",
        "NOTES.md",
    ]:
        print(f"  {OUT / f}")
    print("=" * 60)


if __name__ == "__main__":
    main()
