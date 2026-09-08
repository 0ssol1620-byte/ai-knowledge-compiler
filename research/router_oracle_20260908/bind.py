"""WP-R0 — bind the 2026-09-03 Model Arena artifacts to this analysis.

Emits ``ARENA_BIND.json``: for every model x benchmark, the exact artifact
paths, their sha256, the registry pins (model revision / runtime image /
evaluator), the per-unit counts available and the per-model output
availability from the frozen manifests.

Fail closed: if a required artifact is missing, or if any path this binder
chose to record cannot be hashed, the run exits non-zero and writes nothing.
A model that simply has no artifact for a benchmark is recorded as
``available: false`` with a reason -- that is incompleteness, not a digest
failure, and it is reported rather than dropped (blueprint section 37).

Read-only. Nothing under the arena tree is ever written.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# The arena tree lives untracked in the MAIN core checkout and is READ-ONLY.
DEFAULT_ARENA_ROOT = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\research\model_arena_20260903"
)
CAMPAIGN_ID = "TAVONEL-MODEL-ARENA-PUBLIC-20260903-V1"

# Founder decision 2026-09-04 21:04 KST (FOUNDER_EXCLUDE_INFINITY_2026-09-04.md).
FOUNDER_EXCLUDED = ("infinity_parser2_pro",)

BENCHMARKS = ("omnidoc", "olmocr", "parsebench")

# OmniDocBench per-page element files. Two file-name prefixes exist in the
# tree: the models scored by the original driver use ``markdown_``, the ones
# scored by the per-model drivers use ``md_<model>_``.
OMNIDOC_ELEMENTS = {
    "text": "text_block_per_page_edit.json",
    "formula": "display_formula_per_page_edit.json",
    "table": "table_per_page_edit.json",
    "reading_order": "reading_order_per_page_edit.json",
}
OMNIDOC_TABLE_TEDS = "table_per_table_TEDS.json"

# Artifacts without which the bind is meaningless.
REQUIRED = (
    "model_registry.json",
    "evaluator_registry.json",
    "source_manifest.jsonl",
    "reports/full_compare_20260905/comparison_omnidoc_full.json",
    "reports/full_compare_20260905/chain_state.json",
    "reports/full_compare_20260905/LEADERBOARD_QUALITY_SPEED.json",
    "reports/partial_score_20260905/comparison_speed.json",
)


class BindRefusal(RuntimeError):
    """A referenced artifact has no digest source. Fail closed."""


def sha256_file(path: Path) -> str:
    """sha256 of a file, streamed. Raises BindRefusal if it cannot be read."""
    if not path.is_file():
        raise BindRefusal(f"no digest source for referenced path: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def write_text_lf(path: Path, text: str) -> str:
    """Write UTF-8 with LF endings and return the digest of the bytes on disk.

    Path.write_text would translate newlines on Windows, so a digest printed
    from the in-memory string would not match the file. A receipt that does
    not verify is worse than no receipt.
    """
    data = text.encode("utf-8")
    path.write_bytes(data)
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def arena_root() -> Path:
    return Path(os.environ.get("ARENA_ROOT", str(DEFAULT_ARENA_ROOT)))


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@dataclass(frozen=True)
class ArtifactRef:
    """One bound artifact: relative path plus its digest."""

    relative_path: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "sha256": self.sha256,
            "bytes": self.bytes,
        }


def bind_artifact(root: Path, relative: str) -> ArtifactRef:
    path = root / relative
    return ArtifactRef(
        relative_path=relative.replace("\\", "/"),
        sha256=sha256_file(path),
        bytes=path.stat().st_size,
    )


def omnidoc_prefix(model_dir: Path, model_key: str) -> str | None:
    """Return the per-page file-name prefix this model's scorer used."""
    for prefix in (f"md_{model_key}_quick_match_", "markdown_quick_match_"):
        if (model_dir / f"{prefix}{OMNIDOC_ELEMENTS['text']}").is_file():
            return prefix
    return None


def bind_omnidoc(root: Path, model_key: str) -> dict[str, Any]:
    rel_dir = f"reports/full_compare_20260905/omnidoc_raw/{model_key}"
    model_dir = root / rel_dir
    if not model_dir.is_dir():
        return {
            "available": False,
            "reason": "no omnidoc_raw directory for this model",
            "artifacts": {},
            "unit_counts": {},
        }
    prefix = omnidoc_prefix(model_dir, model_key)
    if prefix is None:
        return {
            "available": False,
            "reason": (
                "omnidoc_raw directory exists but holds no per-page edit files "
                "(aggregate metric_result.json only)"
            ),
            "artifacts": {},
            "unit_counts": {},
        }
    artifacts: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    for element, suffix in OMNIDOC_ELEMENTS.items():
        relative = f"{rel_dir}/{prefix}{suffix}"
        if not (root / relative).is_file():
            continue
        artifacts[element] = bind_artifact(root, relative).as_dict()
        counts[element] = len(load_json(root / relative))
    teds_rel = f"{rel_dir}/{prefix}{OMNIDOC_TABLE_TEDS}"
    if (root / teds_rel).is_file():
        artifacts["table_teds"] = bind_artifact(root, teds_rel).as_dict()
        counts["table_teds"] = len(load_json(root / teds_rel))
    return {
        "available": bool(artifacts),
        "reason": None,
        "file_prefix": prefix,
        "artifacts": artifacts,
        "unit_counts": counts,
    }


def bind_olmocr(root: Path, model_key: str) -> dict[str, Any]:
    relative = f"reports/full_compare_20260905/olmocr_raw/{model_key}/official_result.json"
    if not (root / relative).is_file():
        return {
            "available": False,
            "reason": "no olmocr official_result.json",
            "artifacts": {},
            "unit_counts": {},
        }
    ref = bind_artifact(root, relative)
    payload = load_json(root / relative)
    tests = payload.get("tests") or []
    return {
        "available": bool(tests),
        "reason": None if tests else "official_result.json holds no per-test rows",
        "artifacts": {"official_result": ref.as_dict()},
        "unit_counts": {
            "tests": len(tests),
            "pdfs": payload.get("pdf_count"),
            "candidate_errors": len(payload.get("candidate_errors") or []),
        },
        "overall_score": payload.get("overall_score"),
    }


def bind_parsebench(root: Path, model_key: str) -> dict[str, Any]:
    rel_dir = f"reports/full_compare_20260905/parsebench_raw/{model_key}"
    model_dir = root / rel_dir
    if not model_dir.is_dir():
        return {
            "available": False,
            "reason": "no parsebench_raw directory",
            "artifacts": {},
            "unit_counts": {},
        }
    artifacts: dict[str, dict[str, Any]] = {}
    counts: dict[str, int] = {}
    # Two layouts exist: flat ``<facet>_evaluation_results.csv`` and nested
    # ``<facet>/_evaluation_results.csv``.
    for facet in ("chart", "layout", "table", "text_content", "text_formatting"):
        for candidate in (
            f"{rel_dir}/{facet}_evaluation_results.csv",
            f"{rel_dir}/{facet}/_evaluation_results.csv",
        ):
            if (root / candidate).is_file():
                artifacts[facet] = bind_artifact(root, candidate).as_dict()
                with (root / candidate).open(encoding="utf-8", newline="") as handle:
                    counts[facet] = max(sum(1 for _ in handle) - 1, 0)
                break
    return {
        "available": bool(artifacts),
        "reason": None if artifacts else "no per-example evaluation CSV",
        "artifacts": artifacts,
        "unit_counts": counts,
    }


def bind_frozen_outputs(root: Path, model_key: str) -> dict[str, Any]:
    """Per-benchmark SUCCESS/FAILED counts from the model's frozen manifest."""
    rel_dir = f"frozen_outputs/{model_key}"
    marker_rel = f"{rel_dir}/FROZEN.json"
    manifest_rel = f"{rel_dir}/manifest.jsonl"
    if not (root / marker_rel).is_file() or not (root / manifest_rel).is_file():
        return {"available": False, "reason": "no frozen output marker/manifest"}
    marker = load_json(root / marker_rel)
    per_bench: dict[str, Counter[str]] = {b: Counter() for b in BENCHMARKS}
    with (root / manifest_rel).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            bench = row.get("benchmark")
            if bench in per_bench:
                per_bench[bench][str(row.get("status"))] += 1
    return {
        "available": True,
        "reason": None,
        "marker": bind_artifact(root, marker_rel).as_dict(),
        "manifest": bind_artifact(root, manifest_rel).as_dict(),
        "manifest_sha256_declared": marker.get("manifest_sha256"),
        "frozen_at": marker.get("frozen_at"),
        "complete": marker.get("complete"),
        "sample_count": marker.get("sample_count"),
        "success_count": marker.get("success_count"),
        "failed_count": marker.get("failed_count"),
        "model_revision_declared": marker.get("model_revision"),
        "runtime_image_digest_declared": marker.get("runtime_image_digest"),
        "status_by_benchmark": {b: dict(c) for b, c in per_bench.items()},
    }


def bind_cost_and_latency(root: Path, model_keys: list[str]) -> dict[str, Any]:
    """Per-model GPU cost and latency, from the campaign's own ledgers.

    Nothing is modelled here: the numbers are sums over ``cost/pod-*.json``
    (RunPod billed seconds x the listed rate snapshot) and medians from
    ``comparison_speed.json``. Opus is a subscription API and has no pod, so it
    has no cost row -- that is recorded, not imputed.
    """
    speed_rel = "reports/partial_score_20260905/comparison_speed.json"
    speed = load_json(root / speed_rel)
    per_model: dict[str, dict[str, Any]] = {key: {} for key in model_keys}
    for row in speed.get("models") or []:
        per_model[str(row["model_key"])] = {
            "median_sec_per_page": row.get("median_sec_per_page"),
            "p90_sec_per_page": row.get("p90_sec_per_page"),
            "mean_sec_per_page": row.get("mean_sec_per_page"),
            "n_success_timed": row.get("n_success_timed"),
            "speed_role": row.get("role"),
        }

    pods = sorted((root / "cost").glob("pod-*.json"))
    unterminated: dict[str, int] = {}
    for pod_path in pods:
        pod = load_json(pod_path)
        key = pod.get("model_key")
        if not key:
            continue
        row = per_model.setdefault(str(key), {})
        row["billed_seconds"] = row.get("billed_seconds", 0.0) + float(
            pod.get("billed_seconds") or 0.0
        )
        row["provider_cost_usd"] = row.get("provider_cost_usd", 0.0) + float(
            pod.get("estimated_provider_cost_usd") or 0.0
        )
        row["pod_count"] = row.get("pod_count", 0) + 1
        if pod.get("deleted_at") is None and pod.get("last_job_finished_at") is None:
            unterminated[str(key)] = unterminated.get(str(key), 0) + 1

    campaign_rel = "cost/campaign-cost.json"
    campaign = load_json(root / campaign_rel)
    for key, row in per_model.items():
        cost = row.get("provider_cost_usd")
        if cost is None:
            row["cost_per_1000_pages_usd"] = None
            row["cost_note"] = (
                "UNMEASURED: no pod ledger rows. opus5_subscription runs on a "
                "subscription API with no pod; a missing row is not a zero cost."
            )
            continue
        pages = campaign.get("successful_pages")
        marker = root / "frozen_outputs" / key / "FROZEN.json"
        if marker.is_file():
            pages = load_json(marker).get("success_count") or pages
        row["pages_basis"] = pages
        row["cost_per_1000_pages_usd"] = (cost / pages * 1000.0) if pages else None
        row["unterminated_pods_still_billing"] = unterminated.get(key, 0)

    return {
        "sources": {
            "speed": bind_artifact(root, speed_rel).as_dict(),
            "campaign_cost": bind_artifact(root, campaign_rel).as_dict(),
            "pod_ledger_files": len(pods),
        },
        "campaign_totals": {
            "total_cost_usd": campaign.get("total_cost_usd"),
            "cost_per_1000_pages_usd": campaign.get("cost_per_1000_pages_usd"),
            "gpu_seconds_per_page": campaign.get("gpu_seconds_per_page"),
            "successful_pages": campaign.get("successful_pages"),
            "idle_overhead_ratio": campaign.get("idle_overhead_ratio"),
            "notes": campaign.get("notes"),
        },
        "per_model": per_model,
        "caveats": [
            "Cost is raw GPU provider cost from the campaign ledger. It never "
            "sits beside a retail price.",
            "Latency is per-job wall time from the queue database, not pure GPU "
            "kernel time, and the hardware mix differs across models.",
            "opus5_subscription is a subscription API: it has no pod ledger and "
            "no speed row. Its cost is UNMEASURED here, not zero.",
            "Some pods had not terminated when the ledger was written; their "
            "billed seconds are measured to that moment, not to teardown.",
            "The campaign idle_overhead_ratio is 0.66: two thirds of the billed "
            "GPU time was idle pod time, not inference. cost_per_1000_pages_usd "
            "here is therefore CAMPAIGN OPERATIONAL cost under an exploratory "
            "scheduling pattern, not a steady-state serving cost, and it must "
            "never be quoted as a per-page price.",
            "infinity_parser2_pro was FOUNDER_EXCLUDED part way through, so its "
            "per-1k figure divides real pod cost by a truncated page count and "
            "is not comparable to the others.",
        ],
    }


def model_pins(entry: dict[str, Any]) -> dict[str, Any]:
    repos = entry.get("code_repositories") or []
    return {
        "display_name": entry.get("display_name"),
        "license": entry.get("license"),
        "container_image": entry.get("container_image"),
        "container_digest": entry.get("container_digest"),
        "container_digest_unresolved_reason": entry.get("container_digest_unresolved_reason"),
        "cuda": entry.get("cuda"),
        "inference_config_sha256": entry.get("inference_config_sha256"),
        "identity_source": entry.get("identity_source"),
        "identity_pinned_behind_upstream": entry.get("identity_pinned_behind_upstream"),
        "weights": entry.get("weights") or entry.get("model_artifacts"),
        "code_repositories": [
            {
                "repo": repo.get("repo"),
                "revision": repo.get("revision"),
                "tag": repo.get("tag"),
                "role": repo.get("role"),
                "license_spdx_id": repo.get("license_spdx_id"),
            }
            for repo in repos
        ],
    }


def evaluator_pins(registry: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, entry in (registry.get("evaluators") or {}).items():
        out[name] = {
            "benchmark": entry.get("benchmark"),
            "main_pin": entry.get("main_pin"),
            "historical_pin": entry.get("historical_pin"),
            "dataset_repository": entry.get("dataset_repository"),
            "dataset_revision": entry.get("dataset_revision"),
            "dataset_manifest_sha256": entry.get("dataset_manifest_sha256"),
            "dataset_license": entry.get("dataset_license"),
            "dataset_redistribution": entry.get("dataset_redistribution"),
            "license": entry.get("license"),
            "frozen": entry.get("frozen"),
        }
    return out


def build_bind(root: Path) -> dict[str, Any]:
    required = {rel: bind_artifact(root, rel).as_dict() for rel in REQUIRED}
    registry = load_json(root / "model_registry.json")
    evaluators = load_json(root / "evaluator_registry.json")

    manifest_rows = 0
    manifest_benchmarks: Counter[str] = Counter()
    with (root / "source_manifest.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            manifest_rows += 1
            manifest_benchmarks[str(json.loads(line).get("benchmark"))] += 1

    models: dict[str, Any] = {}
    for model_key, entry in sorted((registry.get("models") or {}).items()):
        excluded = model_key in FOUNDER_EXCLUDED
        benchmarks = {
            "omnidoc": bind_omnidoc(root, model_key),
            "olmocr": bind_olmocr(root, model_key),
            "parsebench": bind_parsebench(root, model_key),
        }
        missing = [b for b, v in benchmarks.items() if not v["available"]]
        models[model_key] = {
            "founder_excluded": excluded,
            "founder_exclusion_receipt": (
                "FOUNDER_EXCLUDE_INFINITY_2026-09-04.md" if excluded else None
            ),
            "pins": model_pins(entry),
            "frozen_outputs": bind_frozen_outputs(root, model_key),
            "benchmarks": benchmarks,
            "incomplete": bool(missing),
            "missing_benchmarks": missing,
        }

    return {
        "schema": "tavonel.router_oracle.arena_bind.v1",
        "campaign_id": CAMPAIGN_ID,
        "arena_root": str(root),
        "phase": "A",
        "gpu_spend_usd": 0,
        "paid_actions": "none — stored outputs only",
        "required_artifacts": required,
        "corpus": {
            "source_manifest_rows": manifest_rows,
            "rows_by_benchmark": dict(manifest_benchmarks),
        },
        "evaluators": evaluator_pins(evaluators),
        "cost_and_latency": bind_cost_and_latency(root, sorted(registry.get("models") or {})),
        "founder_excluded_models": list(FOUNDER_EXCLUDED),
        "models": models,
        "notes": [
            "Read-only bind. No file under the arena tree is modified.",
            "container_digest is null for every model: lane F never resolved the "
            "immutable image digest, so runtime identity is pinned by "
            "identity_source + inference_config_sha256, not by an image digest.",
            "A model with available=false for a benchmark is INCOMPLETE, not "
            "dropped. Section 37 requires both the intersection cohort and the "
            "missing-as-failure cohort to be reported.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    out_path = Path(__file__).with_name("ARENA_BIND.json")
    if argv and argv[0] == "--out":
        out_path = Path(argv[1])
    root = arena_root()
    try:
        payload = build_bind(root)
    except BindRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    digest = write_text_lf(out_path, text)
    n_models = len(payload["models"])
    n_incomplete = sum(1 for m in payload["models"].values() if m["incomplete"])
    print(f"wrote {out_path} {digest}")
    print(f"models={n_models} incomplete={n_incomplete} excluded={len(FOUNDER_EXCLUDED)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
