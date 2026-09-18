"""Score a frozen source-bound region recovery policy on spent development data.

The runtime half consumes only frozen source, Native, MinerU and Paddle
artifacts. Hidden olmOCR truth is opened only after those dispositions have
been materialized. The output contains aggregate counts and hashes, never text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPLAY = HERE.parent / "router_replay_20260908"
ORACLE = HERE.parent / "router_oracle_20260908"
for module_root in (REPLAY, ORACLE):
    if str(module_root) not in sys.path:
        sys.path.insert(0, str(module_root))

import features as F  # type: ignore[import-not-found]  # noqa: E402
import native_visible as N  # type: ignore[import-not-found]  # noqa: E402
from bind import load_json, sha256_file  # type: ignore[import-not-found]  # noqa: E402

EXPECTED_TARGETS = "sha256:a508297876676ed9fae15fb666a33e8903cbf8cf6ebbea9abfbe7247f1270110"
EXPECTED_DISPOSITIONS = "sha256:d7e4b7737510128409461026ec5e2a84ec390a583b87f0cc1b219df2ba411a91"
EXPECTED_PRIMARY_MANIFEST = (
    "sha256:2fe463087233a29cd7bf4d619e534a25727adf99588249b5dd70fa6569118b1d"
)
EXPECTED_SPECIALIST_MANIFEST = (
    "sha256:0fff25a57c1727905e877a5c9c3d5841cfe0534574701219242ecb9eaeb7692c"
)
EXPECTED_NATIVE_OBSERVATIONS = (
    "sha256:ac4b4e669eb4b2d09913b77dd0420d779866f4adc00edc69e799cd85c39512a8"
)
EXPECTED_PAGES = 1403
EXPECTED_TARGET_COUNT = 31
PRIMARY = "mineru_vlm"
SPECIALIST = "paddleocr_vl_1_6"
BOOTSTRAP_REPLICATES = 5000
BOOTSTRAP_SEED = "TAVONEL-SOURCE-BOUND-REGION-RECOVERY-20260910-V1"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_hash(kind: str, token: str) -> str:
    return "sha256:" + hashlib.sha256(f"{kind}\x1f{token}".encode()).hexdigest()


def normalized_bbox(
    raw: object, *, width: int, height: int
) -> tuple[int, int, int, int] | None:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw)
        or width < 1
        or height < 1
    ):
        return None
    values = tuple(float(value) for value in raw)
    if not all(math.isfinite(value) for value in values):
        return None
    left, top, right, bottom = values
    result = (
        max(0, min(1000, math.floor(left / width * 1000))),
        max(0, min(1000, math.floor(top / height * 1000))),
        max(0, min(1000, math.ceil(right / width * 1000))),
        max(0, min(1000, math.ceil(bottom / height * 1000))),
    )
    return result if result[0] < result[2] and result[1] < result[3] else None


def load_runtime_dispositions(
    *, arena: Path, targets_path: Path, dispositions_path: Path
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Seal runtime-visible dispositions and verified supplement text."""
    if digest(targets_path) != EXPECTED_TARGETS:
        raise ValueError("REGION_ROUTER_TARGETS_MISMATCH")
    if digest(dispositions_path) != EXPECTED_DISPOSITIONS:
        raise ValueError("REGION_ROUTER_DISPOSITIONS_MISMATCH")
    targets = {
        str(row["case_key"]): row
        for row in (
            json.loads(line) for line in targets_path.read_text(encoding="utf-8").splitlines()
        )
    }
    dispositions = {
        str(row["case_key"]): row
        for row in (
            json.loads(line)
            for line in dispositions_path.read_text(encoding="utf-8").splitlines()
        )
    }
    if (
        len(targets) != EXPECTED_TARGET_COUNT
        or set(targets) != set(dispositions)
        or len(dispositions) != EXPECTED_TARGET_COUNT
    ):
        raise ValueError("REGION_ROUTER_TARGET_DENOMINATOR_MISMATCH")

    specialist_manifest_path = arena / f"frozen_outputs/{SPECIALIST}/manifest.jsonl"
    primary_manifest_path = arena / f"frozen_outputs/{PRIMARY}/manifest.jsonl"
    if digest(specialist_manifest_path) != EXPECTED_SPECIALIST_MANIFEST:
        raise ValueError("REGION_ROUTER_SPECIALIST_MANIFEST_MISMATCH")
    if digest(primary_manifest_path) != EXPECTED_PRIMARY_MANIFEST:
        raise ValueError("REGION_ROUTER_PRIMARY_MANIFEST_MISMATCH")

    supplements: dict[str, str] = {}
    for case_key, disposition in dispositions.items():
        status = disposition.get("status")
        if status == "unresolved":
            continue
        if status != "verified_critical_region":
            raise ValueError("REGION_ROUTER_DISPOSITION_INVALID")
        expected_bbox = tuple(disposition.get("matched_bbox1000") or ())
        expected_text_hash = disposition.get("model_region_text_sha256")
        native_path = arena / f"runs/{SPECIALIST}/raw/{case_key}.native.json"
        native = load_json(native_path)
        pages = native.get("pages")
        if not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict):
            raise ValueError("REGION_ROUTER_SPECIALIST_PAGE_INVALID")
        page = pages[0].get("res")
        if not isinstance(page, dict):
            raise ValueError("REGION_ROUTER_SPECIALIST_PAGE_INVALID")
        width, height = page.get("width"), page.get("height")
        if type(width) is not int or type(height) is not int:
            raise ValueError("REGION_ROUTER_SPECIALIST_GEOMETRY_INVALID")
        matches: list[str] = []
        for block in page.get("parsing_res_list") or []:
            if not isinstance(block, dict) or not isinstance(block.get("block_content"), str):
                continue
            content = str(block["block_content"])
            bbox = normalized_bbox(block.get("block_bbox"), width=width, height=height)
            if bbox == expected_bbox and text_digest(content) == expected_text_hash:
                matches.append(content)
        if len(matches) != 1:
            raise ValueError("REGION_ROUTER_VERIFIED_SUPPLEMENT_NOT_UNIQUE")
        supplements[case_key] = matches[0]
    return targets, supplements


def missing_events(scorer: Any, gt_text: str, output_text: str) -> Counter[str]:
    events: Counter[str] = Counter()
    for kind, pattern in scorer.OPPORTUNITY_PATTERNS:
        expected = scorer._ct._counter(pattern, gt_text)
        produced = scorer._ct._counter(pattern, output_text)
        for token, count in expected.items():
            missing = count - produced.get(token, 0)
            if missing > 0:
                events[token_hash(kind, token)] += missing
    return events


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = (len(ordered) - 1) * q
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - index) + ordered[upper] * (index - lower)


def paired_bootstrap(
    rows: list[tuple[int, int, int]], *, seed: str, replicates: int
) -> dict[str, float]:
    rng = random.Random(seed)  # noqa: S311 - deterministic statistical bootstrap
    n = len(rows)
    deltas: list[float] = []
    for _ in range(replicates):
        baseline = candidate = opportunities = 0
        for _ in range(n):
            base, cand, opp = rows[rng.randrange(n)]
            baseline += base
            candidate += cand
            opportunities += opp
        deltas.append((candidate - baseline) / opportunities if opportunities else 0.0)
    return {
        "delta_point": sum(row[1] - row[0] for row in rows)
        / sum(row[2] for row in rows),
        "delta_ci95_low": percentile(deltas, 0.025),
        "delta_ci95_high": percentile(deltas, 0.975),
        "replicates": replicates,
    }


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    targets_path = args.targets.resolve(strict=True)
    dispositions_path = args.dispositions.resolve(strict=True)
    native_capture = N.load_capture(args.native_capture)
    if native_capture.observations_sha256 != EXPECTED_NATIVE_OBSERVATIONS:
        raise ValueError("REGION_ROUTER_NATIVE_BINDING_MISMATCH")

    # Runtime-visible policy is fully sealed before the hidden scorer is imported.
    targets, supplements = load_runtime_dispositions(
        arena=arena,
        targets_path=targets_path,
        dispositions_path=dispositions_path,
    )
    bind_path = ORACLE / "ARENA_BIND.json"
    bind = load_json(bind_path)
    models = sorted(
        model
        for model, entry in bind["models"].items()
        if not entry["founder_excluded"] and entry["frozen_outputs"]["available"]
    )
    units, texts = F.load_or_build_units(arena, "olmocr", models, args.replay_cache)
    units, texts = N.augment_units(units, texts, native_capture)
    if len(units) != EXPECTED_PAGES:
        raise ValueError("REGION_ROUTER_PAGE_DENOMINATOR_MISMATCH")
    by_case = {unit.case_key: unit for unit in units}
    if not set(targets).issubset(by_case):
        raise ValueError("REGION_ROUTER_TARGET_PAGE_MISSING")

    import scorer as S  # type: ignore[import-not-found]

    surface = S.load_surfaces(arena, bind)["olmocr"]
    gt = S.ground_truth("olmocr")
    opportunity_freeze = S.build_opportunity_freeze(["olmocr"])
    opportunities = opportunity_freeze["surfaces"]["olmocr"]["per_unit"]

    baseline_events = candidate_events = 0
    baseline_silent_units = candidate_silent_units = 0
    recovered_events = locally_refused_events = 0
    bootstrap_rows: list[tuple[int, int, int]] = []
    main_losses: list[float] = []
    hard_fail = 0
    for unit in units:
        key = unit.unit_key
        primary = texts.get((PRIMARY, key))
        if primary is None:
            primary = ""
        gt_text = gt.get(key, "")
        base_missing = missing_events(S, gt_text, primary) if gt_text else Counter()
        remaining = base_missing.copy()
        target = targets.get(unit.case_key)
        if target is not None:
            supplement = supplements.get(unit.case_key)
            if supplement is not None:
                recovered_missing = missing_events(S, gt_text, primary + "\n" + supplement)
                recovered_events += sum(base_missing.values()) - sum(recovered_missing.values())
                remaining = recovered_missing
            else:
                for exact_hash in target["critical_token_hashes"]:
                    locally_refused_events += remaining.pop(str(exact_hash), 0)
        base_count = sum(base_missing.values())
        candidate_count = sum(remaining.values())
        opp_count = sum((opportunities.get(key) or {}).values())
        baseline_events += base_count
        candidate_events += candidate_count
        baseline_silent_units += int(base_count > 0)
        candidate_silent_units += int(candidate_count > 0)
        bootstrap_rows.append((base_count, candidate_count, opp_count))
        loss = S.unit_loss(surface, PRIMARY, key)
        main_losses.append(loss)
        hard_fail += int(loss > S.HARD_FAIL_TAU)

    total_opportunities = sum(row[2] for row in bootstrap_rows)
    primary_cost = float(bind["cost_and_latency"]["per_model"][PRIMARY]["cost_per_1000_pages_usd"])
    specialist_cost = float(
        bind["cost_and_latency"]["per_model"][SPECIALIST]["cost_per_1000_pages_usd"]
    )
    mean_loss = statistics.fmean(main_losses)
    result: dict[str, Any] = {
        "schema": "tavonel.router.region_recovery_replay.v1",
        "status": "SPENT_DEVELOPMENT_DIAGNOSTIC",
        "pages": len(units),
        "targets": len(targets),
        "verified_regions": len(supplements),
        "localized_unresolved_regions": len(targets) - len(supplements),
        "specialist_invocation_fraction": len(targets) / len(units),
        "baseline": {
            "primary": PRIMARY,
            "main_representation_mean_loss": mean_loss,
            "main_representation_irr": 1.0 - mean_loss,
            "hard_fail_pages": hard_fail,
            "sclr_silent_units": baseline_silent_units,
            "sclr_silent_events": baseline_events,
            "sclr_unit_rate": baseline_silent_units / len(units),
            "sclr_opportunity_rate": baseline_events / total_opportunities,
            "historical_raw_provider_usd_per_1000_pages": primary_cost,
        },
        "candidate": {
            "main_representation_mean_loss": mean_loss,
            "main_representation_irr": 1.0 - mean_loss,
            "bundle_irr": None,
            "bundle_irr_reason": "no official multi-representation page scorer is frozen",
            "hard_fail_pages_on_main_representation": hard_fail,
            "sclr_silent_units": candidate_silent_units,
            "sclr_silent_events": candidate_events,
            "sclr_unit_rate": candidate_silent_units / len(units),
            "sclr_opportunity_rate": candidate_events / total_opportunities,
            "critical_events_recovered_by_verified_supplement": recovered_events,
            "critical_events_detected_by_local_refusal": locally_refused_events,
            "localized_unresolved_page_fraction": (len(targets) - len(supplements))
            / len(units),
            "historical_raw_provider_usd_per_1000_pages": primary_cost
            + specialist_cost * len(targets) / len(units),
            "region_runtime_p95": None,
            "region_runtime_p95_reason": (
                "stored specialist evidence is full-page, not crop runtime"
            ),
        },
        "paired_bootstrap": paired_bootstrap(
            bootstrap_rows, seed=BOOTSTRAP_SEED, replicates=BOOTSTRAP_REPLICATES
        ),
        "critical_opportunities": total_opportunities,
        "input_bindings": {
            "arena_bind_sha256": sha256_file(bind_path),
            "targets_sha256": digest(targets_path),
            "runtime_dispositions_sha256": digest(dispositions_path),
            "native_observations_sha256": native_capture.observations_sha256,
            "primary_manifest_sha256": EXPECTED_PRIMARY_MANIFEST,
            "specialist_manifest_sha256": EXPECTED_SPECIALIST_MANIFEST,
        },
        "hidden_evaluation_visible_to_runtime": False,
        "quality_claim": False,
        "confirmatory_eligible": False,
        "production_promotion": False,
        "fresh_holdout_opened": False,
        "new_gpu_cost_usd": 0,
        "limitations": [
            "targets and policy were developed on this spent corpus",
            "olmOCR critical-token ground truth is a partial lower bound",
            "the broad IRR score applies only to the unchanged MinerU main representation",
            "stored full-page specialist cost is charged; crop latency and cost are unmeasured",
        ],
    }
    output = args.output.resolve()
    if output.exists():
        raise ValueError("REGION_ROUTER_REPLAY_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    output_path = output / "RESULT.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    receipt = {
        "result_sha256": digest(output_path),
        "policy_freeze_sha256": digest(HERE / "REGION_ROUTER_REPLAY_FREEZE.json"),
        "records_disclosed": 0,
        "text_disclosed": False,
    }
    (output / "RECEIPT.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--dispositions", type=Path, required=True)
    parser.add_argument("--native-capture", type=Path, required=True)
    parser.add_argument("--replay-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
