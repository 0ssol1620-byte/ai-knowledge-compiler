"""Stage 0 capability smoke (masterplan v5 section 9.7): 50 cases per task, one candidate.

Stage 0 runs on the CALIBRATION split only. It checks that the schema works,
the modality is what the registry says, outputs are reasonable, cost and
tokens are measured and nothing catastrophic happens -- and it leaves the
EVALUATION split unseen, so a later prompt change cannot have been fitted to it.

Stop conditions, checked between every batch of cases:

* a ``STOP`` file at the namespace root or in the run directory;
* the Arena's ``BudgetWatchdog`` reaching the lane cap (pod rate x billed time
  plus everything already in ``cost/pod_ledger.jsonl``);
* the Arena's ``CircuitBreaker`` tripping on *operational* failures
  (provider/transport errors). A wrong or unparseable answer is a semantic
  failure: it is recorded and scored, never a reason to retry or stop.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final, Protocol

from arena.controller.cost import build_ledger_row
from arena.controller.queue import PodRecord
from arena.controller.watchdogs import BudgetWatchdog, CircuitBreaker
from arena.provider.runpod_pods import Pod, PriceSnapshot, RunPodPodsClient, pod_name
from arena.provider.safety import (
    atomic_write_bytes,
    sha256_bytes,
    sha256_file,
    sha256_text,
    timestamp_slug,
    utc_now_iso,
    write_json_atomic,
    write_jsonl_append,
)
from arena.provider.secrets import runpod_api_key

from karena import CAMPAIGN_ID, CAMPAIGN_SHORT, NAMESPACE_ROOT
from karena.corpus import Case, check_split_integrity, read_jsonl
from karena.freeze import verify_frozen
from karena.registry import load_registry
from karena.serving import (
    ChatResult,
    LlmPodSpec,
    VllmEndpoint,
    new_api_key,
    vllm_args,
    wait_until_ready,
)
from karena.tasks import TASKS, Normalised, TaskAdapter, load_task, task_config

__all__ = ["Guard", "StopRun", "load_cases", "run_stage0", "run_tasks", "score_run"]

LEDGER: Final = NAMESPACE_ROOT / "cost" / "pod_ledger.jsonl"
GLOBAL_STOP: Final = NAMESPACE_ROOT / "STOP"
FREEZE_VERSION: Final = "v1"
#: Measured, not assumed: on 2026-11-04 pod njcoez8hxpyahs (A100-SXM4-80GB, host CUDA
#: 13.2) died in vLLM warm-up with "CUDA error: no kernel image is available for
#: execution on the device" on this image, so Ampere is not in the list. Ada (sm_89)
#: ran this exact image for the 2026-09-03 Arena; Hopper and Blackwell are tried
#: when Ada has no stock on a CUDA >= 12.9 host.
GPU_PRIORITY: Final = (
    "NVIDIA GeForce RTX 4090",
    "NVIDIA L40S",
    "NVIDIA RTX 6000 Ada Generation",
    "NVIDIA RTX PRO 4500 Blackwell Server Edition",
    "NVIDIA RTX PRO 4500 Blackwell",
    "NVIDIA RTX PRO 5000 Blackwell",
    "NVIDIA H100 PCIe",
)
#: Host CUDA versions the pinned image (CUDA 12.9.1) can run on.
ALLOWED_CUDA: Final = ("12.9", "13.0", "13.1", "13.2")
CHAT_TEMPLATE_KWARGS: Final = {"enable_thinking": False}
MAX_MODEL_LEN: Final = 16384


class StopRun(RuntimeError):
    pass


class Endpoint(Protocol):
    def chat(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        schema: Mapping[str, Any],
        schema_name: str,
        params: Mapping[str, Any],
        chat_template_kwargs: Mapping[str, Any],
    ) -> ChatResult: ...


@dataclass
class Guard:
    run_dir: Path
    budget_usd: float
    prior_spend_usd: float
    rate_usd_per_hour: float
    started: datetime
    max_seconds: float
    breaker: CircuitBreaker
    reason: str | None = None

    def spent(self) -> float:
        hours = (datetime.now(tz=UTC) - self.started).total_seconds() / 3600.0
        return self.prior_spend_usd + hours * self.rate_usd_per_hour

    def check(self) -> None:
        if self.reason is not None:
            raise StopRun(self.reason)
        if GLOBAL_STOP.exists() or (self.run_dir / "STOP").exists():
            self.reason = "STOP file present"
        elif self.breaker.tripped is not None:
            self.reason = f"circuit breaker: {self.breaker.tripped.reason}"
        elif (datetime.now(tz=UTC) - self.started).total_seconds() > self.max_seconds:
            self.reason = "pod lifetime limit reached"
        else:
            assessment = BudgetWatchdog(
                soft_cap_usd=self.budget_usd, hard_cap_usd=self.budget_usd
            ).evaluate(
                spent_usd=self.spent(),
                running_worker_rates_usd_per_hour=[self.rate_usd_per_hour],
                seconds_to_next_checkpoint=300.0,
            )
            if not assessment.allow_new_replicas:
                self.reason = f"budget: {assessment.reason}"
        if self.reason is not None:
            raise StopRun(self.reason)


def load_cases(task: str, split: str, limit: int) -> list[Case]:
    path = NAMESPACE_ROOT / "cases" / f"{task}.{split}.jsonl"
    cases = [Case.from_dict(row) for row in read_jsonl(path)][:limit]
    check_split_integrity(cases)
    if len(cases) < limit:
        raise StopRun(f"{task}: only {len(cases)} {split} cases, Stage 0 needs {limit}")
    return cases


def prior_spend() -> float:
    if not LEDGER.is_file():
        return 0.0
    return sum(float(row.get("estimated_provider_cost_usd") or 0.0) for row in read_jsonl(LEDGER))


def _prompt_sha(adapter: TaskAdapter) -> str:
    system, user = adapter.prompt_paths
    return sha256_text(json.dumps([sha256_file(system), sha256_file(user)], separators=(",", ":")))


def _case_slug(case: Case) -> str:
    return sha256_text(case.case_id).removeprefix("sha256:")[:24]


def run_one(
    endpoint: Endpoint,
    adapter: TaskAdapter,
    case: Case,
    *,
    repeat: int,
    run_dir: Path,
    row: Mapping[str, Any],
    price_snapshot_sha256: str | None,
) -> dict[str, Any]:
    messages = adapter.messages(case)
    result = endpoint.chat(
        messages,
        schema=adapter.output_schema,
        schema_name=f"karena_{adapter.name}",
        params=adapter.params,
        chat_template_kwargs=CHAT_TEMPLATE_KWARGS,
    )
    slug = f"{_case_slug(case)}.r{repeat}"
    raw_sha = atomic_write_bytes(
        run_dir / "raw" / adapter.name / f"{slug}.json", result.raw_body.encode("utf-8")
    )
    if result.error is not None:
        normalised = Normalised("PROVIDER_ERROR", None, result.error)
    else:
        normalised = adapter.normalise(result.content, result.finish_reason)
    normalised_sha = atomic_write_bytes(
        run_dir / "normalized" / adapter.name / f"{slug}.json",
        json.dumps(
            {"status": normalised.status, "value": normalised.value, "problem": normalised.problem},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8"),
    )
    # Masterplan v5 Appendix A.2, plus the fields a text task needs to be replayed.
    receipt: dict[str, Any] = {
        "schema": "tavonel.karena.run_receipt.v1",
        "campaign_id": CAMPAIGN_ID,
        "run_id": f"{row['model_key']}:{case.case_id}:r{repeat}",
        "case_id": case.case_id,
        "task": adapter.name,
        "split": case.split,
        "repeat_index": repeat,
        "model_registry_id": row["registry_id"],
        "exact_model_id": row["exact_model_id"],
        "exact_revision": row["exact_revision"],
        "input_track": "STANDARD_TEXT",
        "prompt_track": "STANDARD",
        "batch_mode": False,
        "prompt_sha256": _prompt_sha(adapter),
        "schema_sha256": sha256_bytes(
            json.dumps(adapter.output_schema, sort_keys=True).encode("utf-8")
        ),
        "rendered_messages_sha256": sha256_text(
            json.dumps(messages, sort_keys=True, ensure_ascii=False)
        ),
        "input_artifact_sha256": case.input_sha256(),
        "raw_output_sha256": raw_sha,
        "normalized_output_sha256": normalised_sha,
        "status": normalised.status,
        "problem": normalised.problem,
        "http_status": result.http_status,
        "finish_reason": result.finish_reason,
        "latency_ms": result.latency_ms,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "sampling": dict(adapter.params),
        "chat_template_kwargs": CHAT_TEMPLATE_KWARGS,
        "cost": {
            "actual_usd": None,
            "method": "pod time; allocated per task in summary.json",
            "price_snapshot_id": price_snapshot_sha256,
        },
        "finished_at": utc_now_iso(),
    }
    return receipt


def run_tasks(
    endpoint: Endpoint,
    adapters: Sequence[TaskAdapter],
    cases: Mapping[str, Sequence[Case]],
    *,
    run_dir: Path,
    row: Mapping[str, Any],
    guard: Guard,
    concurrency: int,
    repeat_subset: int,
    repeats: int,
    price_snapshot_sha256: str | None = None,
) -> dict[str, Any]:
    """Run every task's cases, then the repeat subset. Returns per-task wall seconds."""

    wall: dict[str, float] = {}
    plan: list[tuple[TaskAdapter, Case, int]] = []
    for adapter in adapters:
        plan += [(adapter, case, 0) for case in cases[adapter.name]]
    for repeat in range(1, repeats):
        for adapter in adapters:
            plan += [(adapter, case, repeat) for case in cases[adapter.name][:repeat_subset]]
    stopped: str | None = None
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for start in range(0, len(plan), concurrency):
            try:
                guard.check()
            except StopRun as exc:
                stopped = str(exc)
                break
            batch = plan[start : start + concurrency]
            began = datetime.now(tz=UTC)
            futures = [
                pool.submit(
                    run_one,
                    endpoint,
                    adapter,
                    case,
                    repeat=repeat,
                    run_dir=run_dir,
                    row=row,
                    price_snapshot_sha256=price_snapshot_sha256,
                )
                for adapter, case, repeat in batch
            ]
            for future in futures:
                receipt = future.result()
                # Written here, on one thread: concurrent appends from the pool lost one
                # line of 280 in the first Stage 0 run (Windows, 2026-11-04).
                write_jsonl_append(run_dir / "receipts.jsonl", receipt, context="run receipt")
                operational = receipt["status"] == "PROVIDER_ERROR"
                guard.breaker.record(failed=operational, error_signature=receipt["problem"])
            seconds = (datetime.now(tz=UTC) - began).total_seconds()
            for adapter_name in {adapter.name for adapter, _, _ in batch}:
                wall[adapter_name] = wall.get(adapter_name, 0.0) + seconds / len(
                    {a.name for a, _, _ in batch}
                )
    return {"wall_seconds": wall, "stopped": stopped, "planned": len(plan)}


def score_run(run_dir: Path) -> dict[str, Any]:
    """Re-score a run from its files alone (no network): repeat 0 for quality, all for repro."""

    receipts = list(read_jsonl(run_dir / "receipts.jsonl"))
    summary: dict[str, Any] = {}
    for task in TASKS:
        adapter = load_task(task)
        by_case = {
            Case.from_dict(row).case_id: Case.from_dict(row)
            for row in read_jsonl(NAMESPACE_ROOT / "cases" / f"{task}.CALIBRATION.jsonl")
        }
        mine = [r for r in receipts if r["task"] == task]
        if not mine:
            summary[task] = {"status": "NOT_RUN"}
            continue
        rows: list[tuple[Case, Normalised]] = []
        repro: dict[str, list[tuple[str, str]]] = {}
        for receipt in mine:
            slug = f"{_case_slug(by_case[receipt['case_id']])}.r{receipt['repeat_index']}"
            body = json.loads(
                (run_dir / "normalized" / task / f"{slug}.json").read_text(encoding="utf-8")
            )
            if receipt["repeat_index"] == 0:
                rows.append(
                    (
                        by_case[receipt["case_id"]],
                        Normalised(body["status"], body["value"], body["problem"]),
                    )
                )
            repro.setdefault(receipt["case_id"], []).append(
                (receipt["raw_output_sha256"], receipt["normalized_output_sha256"])
            )
        statuses: dict[str, int] = {}
        for receipt in mine:
            if receipt["repeat_index"] == 0:
                statuses[receipt["status"]] = statuses.get(receipt["status"], 0) + 1
        repeated = {k: v for k, v in repro.items() if len(v) > 1}
        latencies = sorted(r["latency_ms"] for r in mine if r["repeat_index"] == 0)
        summary[task] = {
            "cases_scored": len(rows),
            "status_counts": statuses,
            "scores": adapter.score(rows),
            "reproducibility": {
                "cases_repeated": len(repeated),
                "repeats_per_case": max((len(v) for v in repeated.values()), default=0),
                "raw_body_identical": "not comparable: the envelope carries ids and timestamps",
                "normalized_identical": sum(
                    1 for v in repeated.values() if len({n for _, n in v}) == 1
                ),
            },
            "latency_ms": {
                "p50": latencies[len(latencies) // 2] if latencies else None,
                "max": latencies[-1] if latencies else None,
            },
            "tokens": {
                "prompt": sum(r["prompt_tokens"] or 0 for r in mine),
                "completion": sum(r["completion_tokens"] or 0 for r in mine),
            },
        }
    return summary


def _choose_gpus(snapshot: PriceSnapshot, cloud: str) -> tuple[tuple[str, ...], float]:
    """Every priced, available GPU in priority order, and the highest rate among them."""

    chosen: list[str] = []
    worst = 0.0
    for gpu in GPU_PRIORITY:
        try:
            row = snapshot.row(gpu)
        except Exception:  # noqa: S112 - a GPU missing from the catalog is skipped
            continue
        available = row.secure_available if cloud == "SECURE" else row.community_available
        rate = row.rate_for(cloud)
        if available and rate is not None:
            chosen.append(gpu)
            worst = max(worst, rate)
    if chosen:
        return tuple(chosen), worst
    raise StopRun(f"none of {GPU_PRIORITY} is priced and available on {cloud}")


def run_stage0(
    model_key: str,
    *,
    execute: bool,
    budget_usd: float = 60.0,
    cloud: str = "SECURE",
    max_pod_hours: int = 3,
    readiness_minutes: float = 40.0,
    progress: Callable[[str], None] = print,
) -> Path:
    frozen = verify_frozen(FREEZE_VERSION)
    row = load_registry()[model_key]
    if row["role"] != "CANDIDATE":
        raise StopRun(f"{model_key} is {row['role']}; Stage 0 runs candidates only")
    stage = task_config()["stage0"]
    adapters = [load_task(task) for task in TASKS]
    cases = {task: load_cases(task, stage["split"], stage["cases_per_task"]) for task in TASKS}
    spent_before = prior_spend()
    run_dir = NAMESPACE_ROOT / "runs" / "stage0" / model_key / timestamp_slug()
    run_dir.mkdir(parents=True, exist_ok=False)
    key = runpod_api_key()
    client = RunPodPodsClient(
        key=key,
        execute=execute,
        campaign_id=CAMPAIGN_ID,
        receipts_dir=NAMESPACE_ROOT / "receipts" / "provider",
    )
    plan: dict[str, Any] = {
        "schema": "tavonel.karena.stage0_plan.v1",
        "campaign_id": CAMPAIGN_ID,
        "model_registry_row": row,
        "freeze": {"version": frozen["version"], "sha256": frozen["freeze_file_sha256"]},
        "cases": {task: len(items) for task, items in cases.items()},
        "stage": stage,
        "budget_usd": budget_usd,
        "prior_spend_usd": spent_before,
        "runpod_key_source": key.label,
        "execute": execute,
        "created_at": utc_now_iso(),
    }
    if not execute:
        write_json_atomic(run_dir / "plan.dry.json", plan, context="stage0 dry plan")
        progress(f"dry run: plan written to {run_dir}")
        return run_dir
    snapshot = client.catalog_gpus()
    if not isinstance(snapshot, PriceSnapshot):  # pragma: no cover - execute guarded
        raise StopRun("catalog read did not return a price snapshot")
    gpus, rate = _choose_gpus(snapshot, cloud)
    worst_case = spent_before + rate * max_pod_hours
    plan.update(
        {
            "gpu_priority": list(gpus),
            "cloud": cloud,
            "highest_listed_rate_usd_per_hour": rate,
            "price_snapshot_sha256": snapshot.snapshot_sha256(),
            "price_rows": [snapshot.row(g).to_dict() for g in gpus],
            "worst_case_spend_usd": round(worst_case, 4),
        }
    )
    if worst_case > budget_usd:
        write_json_atomic(run_dir / "plan.refused.json", plan, context="stage0 plan")
        raise StopRun(f"worst case ${worst_case:.2f} exceeds the ${budget_usd:.2f} lane cap")
    write_json_atomic(run_dir / "plan.json", plan, context="stage0 plan")
    served = model_key.replace("_", "-")
    api_key = new_api_key()
    spec = LlmPodSpec(
        name=pod_name(model_key, 0, campaign_short=CAMPAIGN_SHORT),
        image_name=str(row["serving"]["image"]),
        gpu_type_ids=gpus,
        model_key=model_key,
        model_revision=str(row["exact_revision"]),
        runtime_mode="baked",
        image_digest=str(row["serving"]["image"]).split("@", 1)[1],
        cloud_type=cloud,
        container_disk_gb=80,
        ports=("8000/http",),
        allowed_cuda_versions=ALLOWED_CUDA,
        max_lifetime_hours=max_pod_hours,
        campaign_id=CAMPAIGN_ID,
        args=vllm_args(row, served_name=served, max_model_len=MAX_MODEL_LEN),
        api_key=api_key,
    )
    record: dict[str, Any] = {"execute": True}
    pod: Pod | None = None
    endpoint: VllmEndpoint | None = None
    outcome: dict[str, Any] = {}
    try:
        created = client.create_pod(spec, price_snapshot=snapshot)
        if not isinstance(created, Pod):  # pragma: no cover - execute guarded
            raise StopRun("create_pod returned a dry receipt under --execute")
        pod = created
        record["provisioned_at"] = utc_now_iso()
        record["pod"] = pod.to_summary()
        progress(f"pod {pod.pod_id} created on {pod.gpu_type_id} at ${pod.cost_usd_per_hour}/h")
        endpoint = VllmEndpoint(pod.pod_id, api_key=api_key, served_name=served)
        stage_name, observed = wait_until_ready(
            client, pod, endpoint, deadline_seconds=readiness_minutes * 60, progress=progress
        )
        record["model_ready_at"] = utc_now_iso()
        record["readiness"] = {"stage": stage_name, "observed": list(observed)}
        progress(f"vLLM READY; running {sum(len(v) for v in cases.values())} cases")
        guard = Guard(
            run_dir=run_dir,
            budget_usd=budget_usd,
            prior_spend_usd=spent_before,
            rate_usd_per_hour=pod.cost_usd_per_hour or rate,
            started=datetime.fromisoformat(record["provisioned_at"].replace("Z", "+00:00")),
            max_seconds=max_pod_hours * 3600.0,
            breaker=CircuitBreaker(model_key),
        )
        outcome = run_tasks(
            endpoint,
            adapters,
            cases,
            run_dir=run_dir,
            row=row,
            guard=guard,
            concurrency=int(stage["concurrency"]),
            repeat_subset=int(stage["repeat_subset"]),
            repeats=int(stage["repeats"]),
            price_snapshot_sha256=snapshot.snapshot_sha256(),
        )
        record["last_job_finished_at"] = utc_now_iso()
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {str(exc)[:2000]}"
        # ReadinessError carries the scrubbed container-log tail; keep it as the incident.
        record["log_tail"] = list(getattr(exc, "log_tail", ()) or ())[-80:]
        raise
    finally:
        if endpoint is not None:
            endpoint.close()
        if pod is not None:
            client.delete_pod(pod.pod_id)
            record["deleted_at"] = utc_now_iso()
            record["terminated_at"] = record["deleted_at"]
            remaining = [p.pod_id for p in client.campaign_pods(live_only=True)]
            record["live_campaign_pods_after_delete"] = remaining
            _ledger(pod, record, outcome, str(pod.gpu_type_id), rate, snapshot)
        record["outcome"] = outcome
        write_json_atomic(run_dir / "pod_record.json", record, context="stage0 pod record")
        client.close()
    summary = score_run(run_dir)
    write_json_atomic(
        run_dir / "summary.json",
        {
            "schema": "tavonel.karena.stage0_summary.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_registry_id": row["registry_id"],
            "status_vocabulary": "RUNPOD_E2E_SMOKE only when real GPU inference happened",
            "pod_record": "pod_record.json",
            "tasks": summary,
            "stopped": outcome.get("stopped"),
            "wall_seconds": outcome.get("wall_seconds"),
        },
        context="stage0 summary",
    )
    return run_dir


def _ledger(
    pod: Pod,
    record: Mapping[str, Any],
    outcome: Mapping[str, Any],
    gpu: str,
    rate: float,
    snapshot: PriceSnapshot,
) -> None:
    """The Arena's billed/useful/idle split, written to this namespace's own ledger.

    ``append_pod_ledger`` is not used: its schema enumerates the OCR Arena's model
    keys and would route every row here to the rejected file.
    """

    pod_record = PodRecord(
        pod_id=pod.pod_id,
        model_key=pod.model_key or "unknown",
        name=pod.name,
        state="TERMINATED",
        gpu_type=gpu,
        cloud_type=pod.cloud,
        data_center_id=pod.data_center_id,
        runtime_mode="baked",
        listed_rate_usd_per_hour=pod.cost_usd_per_hour or rate,
        gpu_count=max(1, pod.gpu_count),
        price_snapshot_sha256=snapshot.snapshot_sha256(),
        provider_api_version="v2",
        provisioned_at=record.get("provisioned_at"),
        model_ready_at=record.get("model_ready_at"),
        last_job_finished_at=record.get("last_job_finished_at"),
        terminated_at=record.get("terminated_at"),
    )
    useful = sum((outcome.get("wall_seconds") or {}).values())
    row = replace(
        build_ledger_row(
            pod_record,
            useful_inference_seconds=useful,
            deleted_at=record.get("deleted_at"),
        ),
        campaign_id=CAMPAIGN_ID,
    )
    write_jsonl_append(LEDGER, row.to_dict(), context="karena pod ledger")
