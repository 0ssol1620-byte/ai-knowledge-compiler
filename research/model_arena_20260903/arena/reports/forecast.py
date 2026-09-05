"""Full-run forecast from real canary measurements (masterplan section 32 gate).

The phase-2 full run (5,132 pages per model) needs its own founder authorization
receipt (``receipts/authorizations/phase2_full_run-*.json``; ARENA_CONTRACT D6).
That receipt carries a number, and nobody should sign a number that was not
derived from same-condition evidence. This module turns the canary proofs
(``evidence/canary-proof-<model_key>.json``, written by the smoke-proof
assembler after a real RunPod canary) into a per-model forecast and says, in
the output itself, what the forecast rests on.

Everything here is a FORECAST from a 10-20 page canary, never a measurement of
the full run. Each row names its sample size, the pod it came from and the
assumptions (one pod per model, pages run back to back, one model load, a
fixed safety margin). A model without a PASS canary gets a row that says so
and no number.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SAFETY_MARGIN = 0.15  # 15 %: retries, queue gaps, teardown; a guess, stated as one
DEFAULT_PAGES = 5132
POD_FANOUTS = (1, 2, 4)


@dataclass(frozen=True, slots=True)
class ModelForecast:
    model_key: str
    canary_verdict: str | None
    canary_pod_id: str | None
    canary_pages: int
    gpu_type: str | None
    gpu_count: int
    listed_rate_usd_per_hour: float | None
    mean_page_seconds: float | None
    p_max_page_seconds: float | None
    model_loading_seconds: float | None
    full_run_pages: int
    inference_hours_1_pod: float | None
    wall_hours_by_pods: dict[str, float] | None
    gpu_hours_total: float | None
    forecast_usd: float | None
    forecast_usd_with_margin: float | None
    basis: str
    reason_if_missing: str | None


def _load_proofs(evidence_dir: Path) -> dict[str, dict[str, Any]]:
    proofs: dict[str, dict[str, Any]] = {}
    for path in sorted(evidence_dir.glob("canary-proof-*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        key = str(data.get("model_key") or path.stem.removeprefix("canary-proof-"))
        proofs[key] = data
    return proofs


def forecast_model(
    model_key: str, proof: dict[str, Any] | None, *, pages: int
) -> ModelForecast:
    if proof is None:
        return ModelForecast(
            model_key=model_key, canary_verdict=None, canary_pod_id=None, canary_pages=0,
            gpu_type=None, gpu_count=1, listed_rate_usd_per_hour=None,
            mean_page_seconds=None, p_max_page_seconds=None, model_loading_seconds=None,
            full_run_pages=pages, inference_hours_1_pod=None, wall_hours_by_pods=None,
            gpu_hours_total=None, forecast_usd=None, forecast_usd_with_margin=None,
            basis="none", reason_if_missing="no canary proof file; the canary has not passed",
        )
    verdict = proof.get("canary_verdict")
    runtime = proof.get("page_runtime_seconds") or {}
    mean = runtime.get("mean")
    rate = proof.get("listed_rate_usd_per_hour")
    gpu_count = int(proof.get("gpu_count") or 1)
    loading = proof.get("model_loading_seconds")
    attempted = int(proof.get("pages_attempted") or 0)
    if (
        verdict != "PASS"
        or not isinstance(mean, (int, float))
        or not isinstance(rate, (int, float))
    ):
        return ModelForecast(
            model_key=model_key, canary_verdict=verdict, canary_pod_id=proof.get("pod_id"),
            canary_pages=attempted, gpu_type=proof.get("gpu_type"), gpu_count=gpu_count,
            listed_rate_usd_per_hour=rate if isinstance(rate, (int, float)) else None,
            mean_page_seconds=mean if isinstance(mean, (int, float)) else None,
            p_max_page_seconds=runtime.get("max"), model_loading_seconds=loading,
            full_run_pages=pages, inference_hours_1_pod=None, wall_hours_by_pods=None,
            gpu_hours_total=None, forecast_usd=None, forecast_usd_with_margin=None,
            basis="canary present but not PASS or unpriced",
            reason_if_missing=f"canary_verdict={verdict!r}; no forecast without a PASS",
        )
    load_s = float(loading or 0.0)
    inference_hours = pages * float(mean) / 3600.0
    wall: dict[str, float] = {}
    for n in POD_FANOUTS:
        wall[str(n)] = round((pages / n) * float(mean) / 3600.0 + load_s / 3600.0, 3)
    gpu_hours = inference_hours + load_s / 3600.0  # one load per pod; fan-out adds loads
    usd = gpu_hours * float(rate) * gpu_count
    return ModelForecast(
        model_key=model_key, canary_verdict=verdict, canary_pod_id=proof.get("pod_id"),
        canary_pages=attempted, gpu_type=proof.get("gpu_type"), gpu_count=gpu_count,
        listed_rate_usd_per_hour=float(rate), mean_page_seconds=round(float(mean), 3),
        p_max_page_seconds=runtime.get("max"), model_loading_seconds=loading,
        full_run_pages=pages, inference_hours_1_pod=round(inference_hours, 3),
        wall_hours_by_pods=wall, gpu_hours_total=round(gpu_hours, 3),
        forecast_usd=round(usd, 2), forecast_usd_with_margin=round(usd * (1 + SAFETY_MARGIN), 2),
        basis=(
            f"{attempted}-page real canary on pod {proof.get('pod_id')} "
            f"({proof.get('gpu_type')} x{gpu_count} at ${rate}/h per GPU); mean page "
            f"runtime x {pages} pages + one model load; margin {int(SAFETY_MARGIN * 100)}%"
        ),
        reason_if_missing=None,
    )


def build(root: Path, *, model_keys: tuple[str, ...], pages: int) -> dict[str, Any]:
    proofs = _load_proofs(root / "evidence")
    rows = [forecast_model(k, proofs.get(k), pages=pages) for k in model_keys]
    priced = [r for r in rows if r.forecast_usd_with_margin is not None]
    auth_dir = root / "receipts" / "authorizations"
    phase2 = sorted(auth_dir.glob("phase2_full_run-*.json")) if auth_dir.is_dir() else []
    return {
        "schema": "tavonel.arena.full-run-forecast.v1",
        "kind": "FORECAST",
        "not_a_measurement": (
            "Every number is extrapolated from a 10-20 page canary. Nothing here is a "
            "measured full-run cost; the full run has not been executed."
        ),
        "full_run_pages_per_model": pages,
        "safety_margin": SAFETY_MARGIN,
        "authorization_state": (
            f"phase2_full_run receipt present: {[p.name for p in phase2]}"
            if phase2 else "phase2_full_run authorization receipt ABSENT - full run may not start"
        ),
        "models": [asdict(r) for r in rows],
        "totals": {
            "models_with_forecast": len(priced),
            "models_without_forecast": [r.model_key for r in rows if r.forecast_usd is None],
            "sum_forecast_usd": round(sum(r.forecast_usd or 0.0 for r in priced), 2),
            "sum_forecast_usd_with_margin": round(
                sum(r.forecast_usd_with_margin or 0.0 for r in priced), 2
            ),
            "sum_gpu_hours": round(sum(r.gpu_hours_total or 0.0 for r in priced), 2),
        },
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Full-run forecast (FORECAST, not measured)",
        "",
        payload["not_a_measurement"],
        "",
        f"- pages per model: {payload['full_run_pages_per_model']}",
        f"- safety margin: {int(payload['safety_margin'] * 100)}%",
        f"- authorization: {payload['authorization_state']}",
        "",
        "| model | canary | GPU | $/h/GPU | mean s/page | load s | GPU-h (1 pod) "
        "| wall h @1/2/4 pods | forecast $ | with margin $ |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in payload["models"]:
        if m["forecast_usd"] is None:
            lines.append(
                f"| {m['model_key']} | {m['canary_verdict'] or '-'} | {m['gpu_type'] or '-'} "
                f"| - | - | - | - | - | - | - ({m['reason_if_missing']}) |"
            )
            continue
        w = m["wall_hours_by_pods"]
        lines.append(
            f"| {m['model_key']} | {m['canary_verdict']} ({m['canary_pages']}p) | "
            f"{m['gpu_type']} x{m['gpu_count']} | {m['listed_rate_usd_per_hour']} | "
            f"{m['mean_page_seconds']} | {m['model_loading_seconds']} | {m['gpu_hours_total']} | "
            f"{w['1']}/{w['2']}/{w['4']} | {m['forecast_usd']} | {m['forecast_usd_with_margin']} |"
        )
    t = payload["totals"]
    lines += [
        "",
        f"Sum over {t['models_with_forecast']} forecastable model(s): "
        f"${t['sum_forecast_usd']} (with margin ${t['sum_forecast_usd_with_margin']}), "
        f"{t['sum_gpu_hours']} GPU-h.",
        f"Without a forecast: {', '.join(t['models_without_forecast']) or 'none'}.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from arena.constants import GPU_MODEL_KEYS

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES)
    args = parser.parse_args(argv)
    payload = build(args.root, model_keys=tuple(GPU_MODEL_KEYS), pages=args.pages)
    out_json = args.root / "evidence" / "full-run-forecast.json"
    out_md = args.root / "evidence" / "full-run-forecast.md"
    out_json.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(payload), encoding="utf-8")
    sys.stdout.write(render_markdown(payload))
    sys.stdout.write(f"wrote {out_json}\nwrote {out_md}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
