"""Grouped cross-fit DEVELOPMENT diagnostic. Never imported by the live router.

Reads old evaluator scores only in this offline module. Policy receives just
primary-output/source-render features. Prior Arena evidence is spent: no number
from this program is a fresh confirmation or a production model promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import random
import re
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from policy import FEATURE_NAMES, Decision, visible_features

PRIMARY = "ovisocr2"
ALTERNATE = "paddleocr_vl_1_6"
FOLDS = 5
MAX_DEPTH = 2
MIN_LEAF = 64
QUANTILES = tuple(i / 8 for i in range(1, 8))
BOOTSTRAPS = 2000
SEED = 20260909


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def leaf_loss(rows: list[tuple[tuple[float, ...], tuple[float, float]]]) -> tuple[float, int]:
    totals = [sum(y[action] for _, y in rows) for action in (0, 1)]
    action = int(totals[1] < totals[0])
    return totals[action], action


def fit(rows: list[tuple[tuple[float, ...], tuple[float, float]]], depth: int = 0) -> Decision:
    if not rows:
        raise ValueError("EMPTY_TRAINING_FOLD")
    best_loss, action = leaf_loss(rows)
    best: tuple[int, float, list[Any], list[Any]] | None = None
    if depth < MAX_DEPTH and len(rows) >= 2 * MIN_LEAF:
        for feature in range(len(FEATURE_NAMES)):
            ordered = sorted(x[feature] for x, _ in rows)
            thresholds = sorted({ordered[int((len(ordered) - 1) * q)] for q in QUANTILES})
            for threshold in thresholds:
                left = [row for row in rows if row[0][feature] <= threshold]
                right = [row for row in rows if row[0][feature] > threshold]
                if min(len(left), len(right)) < MIN_LEAF:
                    continue
                score = leaf_loss(left)[0] + leaf_loss(right)[0]
                if score + 1e-12 < best_loss:
                    best_loss, best = score, (feature, threshold, left, right)
    if best is None:
        return Decision(action)
    feature, threshold, left, right = best
    return Decision(action, feature, threshold, fit(left, depth + 1), fit(right, depth + 1))


def family_of(source_path: str) -> str:
    stem = Path(source_path).stem
    return re.sub(r"[_-](?:page|pg|p)[_-]?\d+$", "", stem, flags=re.I) or stem


def grouped_interval(differences: list[float], groups: list[str]) -> list[float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for difference, group in zip(differences, groups, strict=True):
        grouped[group].append(difference)
    sums = [(sum(values), len(values)) for values in grouped.values()]
    rng = random.Random(SEED)  # noqa: S311 — reproducible bootstrap, not security randomness
    estimates = []
    for _ in range(BOOTSTRAPS):
        chosen = [sums[rng.randrange(len(sums))] for _ in sums]
        estimates.append(sum(x for x, _ in chosen) / sum(n for _, n in chosen))
    estimates.sort()
    return [estimates[int(BOOTSTRAPS * 0.025)], estimates[int(BOOTSTRAPS * 0.975)]]


def run(args: argparse.Namespace) -> dict[str, Any]:
    began = time.monotonic()
    here = Path(__file__).resolve().parent
    output = Path(args.output).resolve()
    allowed = here.parents[1] / ".chatgpt2codex"
    if not output.is_relative_to(allowed):
        raise ValueError("OUTPUT_MUST_BE_NEW_ISOLATED_SCRATCH")
    output.mkdir(parents=True, exist_ok=False)
    replay_root = Path(args.replay_root).resolve(strict=True)
    features_dir = replay_root / "research/router_replay_20260908"
    oracle_dir = replay_root / "research/router_oracle_20260908"
    sys.path[:0] = [str(features_dir), str(oracle_dir)]
    visible = importlib.import_module("features")
    arena = visible.arena_root()
    rows = sorted(visible.load_manifest(arena, "omnidoc"), key=lambda r: r["case_key"])
    assert rows and len({r["case_key"] for r in rows}) == len(rows)
    groups = [family_of(row["original_source_relative_path"]) for row in rows]
    # Exact duplicate source bytes may use different names. Merge their groups
    # before assigning folds; source hashes, not labels, determine this step.
    parents: dict[str, str] = {}

    def leader(group: str) -> str:
        parents.setdefault(group, group)
        if parents[group] != group:
            parents[group] = leader(parents[group])
        return parents[group]

    first_hash: dict[str, str] = {}
    for row, group in zip(rows, groups, strict=True):
        source_hash = row["original_source_sha256"]
        earlier = first_hash.setdefault(source_hash, group)
        a, b = leader(earlier), leader(group)
        parents[max(a, b)] = min(a, b)
    groups = [leader(group) for group in groups]
    assignments = [int(digest(group.encode())[:16], 16) % FOLDS for group in groups]
    # Immutable parameters, split and source manifest binding precede any label read.
    freeze = {
        "schema": "tavonel-selector-development-v1",
        "public_claim": False,
        "confirmatory_eligible": False,
        "primary": PRIMARY,
        "alternate": ALTERNATE,
        "folds": FOLDS,
        "max_depth": MAX_DEPTH,
        "min_leaf": MIN_LEAF,
        "quantiles": QUANTILES,
        "bootstrap_replicates": BOOTSTRAPS,
        "seed": SEED,
        "features": FEATURE_NAMES,
        "missing_score_loss": 1.0,
        "code": {
            p.name: digest(p.read_bytes()) for p in (here / "policy.py", here / "evaluate.py")
        },
        "legacy_code": {
            p.name: digest(p.read_bytes())
            for p in (
                features_dir / "features.py",
                oracle_dir / "oracle.py",
                oracle_dir / "loss_vector.py",
            )
        },
        "source_manifest_sha256": digest((arena / "source_manifest.jsonl").read_bytes()),
        "legacy_binding_sha256": digest((oracle_dir / "ARENA_BIND.json").read_bytes()),
        "units": [
            {
                "case_key": r["case_key"],
                "group": g,
                "fold": f,
                "input_sha256": r["original_source_sha256"],
            }
            for r, g, f in zip(rows, groups, assignments, strict=True)
        ],
        "group_limit": (
            "Source basename with page suffix stripped; not an independently verified "
            "publisher-family or near-duplicate split"
        ),
    }
    (output / "FREEZE.json").write_text(json.dumps(freeze, indent=2) + "\n", encoding="utf-8")
    status = visible.load_frozen_status(arena, PRIMARY, "omnidoc")

    def observe(row: dict[str, Any]):
        entry = status.get(row["case_key"])
        text = None
        if entry and entry["status"] == "SUCCESS" and entry["canonical_path"]:
            p = arena / entry["canonical_path"]
            if p.is_file():
                text = visible.read_visible_text(p)
        pre = row.get("preflight") or {}
        vector = visible_features(
            text,
            width=int(row.get("width") or 0),
            height=int(row.get("height") or 0),
            edge_density=pre.get("edge_density"),
            near_white_ratio=pre.get("near_white_ratio"),
            render_entropy=pre.get("render_entropy"),
        )
        return vector, digest(text.encode()) if text is not None else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        observed = list(pool.map(observe, rows))
    x = [record[0] for record in observed]
    (output / "VISIBLE_FEATURES.json").write_text(
        json.dumps(
            [
                {"case_key": r["case_key"], "features": v, "primary_output_sha256": sha}
                for r, (v, sha) in zip(rows, observed, strict=True)
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    # Evaluator/training boundary. This data is NEVER passed into policy.choose.
    oracle = importlib.import_module("oracle")
    binding = json.loads((oracle_dir / "ARENA_BIND.json").read_text(encoding="utf-8"))
    surface = oracle.load_omnidoc(arena, binding)
    keys = [Path(row["original_source_relative_path"]).name for row in rows]
    y = [
        (
            float(surface.loss.get(PRIMARY, {}).get(key, 1.0)),
            float(surface.loss.get(ALTERNATE, {}).get(key, 1.0)),
        )
        for key in keys
    ]
    if not all(math.isfinite(value) and 0 <= value <= 1 for loss in y for value in loss):
        raise ValueError("INVALID_EVALUATION_LOSS")
    selected: list[int | None] = [None] * len(rows)
    train_constant: list[int | None] = [None] * len(rows)
    models = []
    for fold in range(FOLDS):
        train = [i for i, f in enumerate(assignments) if f != fold]
        test = [i for i, f in enumerate(assignments) if f == fold]
        if not train or not test or {groups[i] for i in train} & {groups[i] for i in test}:
            raise ValueError("INVALID_GROUP_SPLIT")
        tree = fit([(x[i], y[i]) for i in train])
        constant = leaf_loss([(x[i], y[i]) for i in train])[1]
        # Only measured runtime-visible numeric vectors cross this boundary.
        for i in test:
            selected[i] = tree.choose(x[i])
            train_constant[i] = constant
        models.append(
            {
                "fold": fold,
                "train_units": len(train),
                "evaluation_units": len(test),
                "tree": asdict(tree),
                "constant_action": constant,
            }
        )
    assert all(action in (0, 1) for action in selected)
    prediction_payload = json.dumps(
        {"models": models, "actions": selected, "train_constant": train_constant}, sort_keys=True
    )
    (output / "OOF_PREDICTIONS.json").write_text(prediction_payload + "\n", encoding="utf-8")
    primary = [loss[0] for loss in y]
    alternate = [loss[1] for loss in y]
    chosen = [loss[int(action)] for loss, action in zip(y, selected, strict=True)]
    difference = [a - b for a, b in zip(primary, chosen, strict=True)]

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    interval = grouped_interval(difference, groups)
    result = {
        "status": "DEVELOPMENT_ONLY_NOT_PROMOTED",
        "public_claim": False,
        "confirmatory_eligible": False,
        "units": len(rows),
        "groups": len(set(groups)),
        "primary_output_missing": sum(sha is None for _, sha in observed),
        "score_missing": {
            model: sum(key not in surface.loss.get(model, {}) for key in keys)
            for model in (PRIMARY, ALTERNATE)
        },
        "loss": {
            PRIMARY: mean(primary),
            ALTERNATE: mean(alternate),
            "grouped_selector": mean(chosen),
            "training_selected_constant": mean(
                [loss[int(action)] for loss, action in zip(y, train_constant, strict=True)]
            ),
            "two_model_oracle_diagnostic": mean([min(loss) for loss in y]),
        },
        "mean_loss_reduction_vs_primary": mean(difference),
        "conditional_group_bootstrap_95_interval": interval,
        "alternate_fraction": sum(action == 1 for action in selected) / len(rows),
        "model_invocation_proxy_per_input": 1 + sum(action == 1 for action in selected) / len(rows),
        "counterfactual_helped": sum(b < a for a, b in zip(primary, chosen, strict=True)),
        "counterfactual_harmed": sum(b > a for a, b in zip(primary, chosen, strict=True)),
        "unchanged": sum(b == a for a, b in zip(primary, chosen, strict=True)),
        "measured_gpu_cost": None,
        "measured_live_latency": None,
        "sclr": None,
        "elapsed_local_seconds": time.monotonic() - began,
        "oof_predictions_sha256": digest(prediction_payload.encode()),
        "interpretation": (
            "Directional diagnostic only. Interval conditions on already-fit cross-fold "
            "predictions; it does not include full training-selection uncertainty. "
            "Missing scores are charged loss=1 by the inherited convention and separately "
            "counted. No region verifier, Native arm, live model or customer processing was used."
        ),
        "next_gate": (
            "Independent source-family/near-duplicate calibration and runtime/SCLR/cost "
            "qualification still required even if the interval is positive."
        ),
    }
    (output / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-root", required=True)
    parser.add_argument("--output", required=True)
    run(parser.parse_args())
