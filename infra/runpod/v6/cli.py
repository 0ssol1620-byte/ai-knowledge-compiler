"""Command line interface for the strict RunPod v2 client.

Every command is a network-free dry run unless ``--execute`` is present.  The
flag may appear before or after the subcommand.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchmark.v6.contracts import ContractError

from .client import (
    BillingQuery,
    EndpointCreateSpec,
    EndpointPatch,
    QueuePolicy,
    RunPodClientError,
    RunPodV2Client,
)

if TYPE_CHECKING:
    from benchmark.v6.runpod_coordinator import ExactThreeRunPodCoordinator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m infra.runpod.v6",
        description="Dry-run-first RunPod REST API v2 operations for FOLYNTA.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Enable real provider calls using only RUNPOD_API_KEY from the environment.",
    )
    parser.add_argument(
        "--receipt-out",
        type=Path,
        help="Create one immutable JSON receipt file; existing files are never overwritten.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("inventory", help="List serverless endpoints.")

    create = commands.add_parser("create", help="Create a pinned serverless endpoint.")
    create.add_argument("--spec", type=Path, required=True)
    create.add_argument("--idempotency-key", required=True)

    get = commands.add_parser("get", help="Get one serverless endpoint.")
    get.add_argument("endpoint_id")

    update = commands.add_parser("update", help="Patch worker/scaling/timeout settings.")
    update.add_argument("endpoint_id")
    update.add_argument("--patch", type=Path, required=True)
    update.add_argument("--run-tag", required=True)
    update.add_argument("--idempotency-key", required=True)

    drain = commands.add_parser("drain", help="Set endpoint worker bounds to zero.")
    drain.add_argument("endpoint_id")
    drain.add_argument("--run-tag", required=True)
    drain.add_argument("--idempotency-key", required=True)

    delete = commands.add_parser("delete", help="Permanently delete an endpoint.")
    delete.add_argument("endpoint_id")
    delete.add_argument("--confirm-endpoint-id", required=True)
    delete.add_argument("--run-tag", required=True)
    delete.add_argument("--idempotency-key", required=True)

    absent = commands.add_parser(
        "verify-absent", help="Emit a terminal receipt only after provider GET returns 404."
    )
    absent.add_argument("endpoint_id")

    audit = commands.add_parser(
        "audit-orphans",
        help="Inventory one run tag and prove expected deletions with endpoint GET 404.",
    )
    audit.add_argument("--run-tag", required=True)
    audit.add_argument("--active-endpoint-id", action="append", default=[])
    audit.add_argument("--deleted-endpoint-id", action="append", default=[])

    run = commands.add_parser("run", help="Submit one asynchronous queue job.")
    run.add_argument("endpoint_id")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--run-tag", required=True)
    run.add_argument("--idempotency-key", required=True)
    run.add_argument("--execution-timeout-ms", type=int, default=600_000)
    run.add_argument("--ttl-ms", type=int, default=86_400_000)
    run.add_argument("--low-priority", action="store_true")

    status = commands.add_parser("status", help="Read an asynchronous queue job status.")
    status.add_argument("endpoint_id")
    status.add_argument("job_id")

    cancel = commands.add_parser("cancel", help="Cancel an asynchronous queue job.")
    cancel.add_argument("endpoint_id")
    cancel.add_argument("job_id")
    cancel.add_argument("--run-tag", required=True)
    cancel.add_argument("--idempotency-key", required=True)

    billing = commands.add_parser("billing", help="Read serverless provider billing history.")
    billing.add_argument("--bucket-size", default="day")
    billing.add_argument("--last-n", type=int, default=30)
    billing.add_argument("--start-time")
    billing.add_argument("--end-time")
    billing.add_argument("--endpoint-id")

    cohort_dispatch = commands.add_parser(
        "cohort-dispatch",
        help="Dispatch or safely resume one frozen exactly-three cohort manifest.",
    )
    cohort_dispatch.add_argument("--manifest", type=Path, required=True)

    cohort_status = commands.add_parser(
        "cohort-status", help="Refresh all three acknowledged jobs in a cohort ledger."
    )
    cohort_status.add_argument("--manifest", type=Path, required=True)

    cohort_report = commands.add_parser(
        "cohort-report", help="Rebuild accepted/user/provider accounting from a cohort ledger."
    )
    cohort_report.add_argument("--manifest", type=Path, required=True)

    cohort_cleanup = commands.add_parser(
        "cohort-cleanup",
        help="Drain, delete, and require provider 404 for a completed cohort endpoint.",
    )
    cohort_cleanup.add_argument("--manifest", type=Path, required=True)
    cohort_cleanup.add_argument("--confirm-endpoint-id", required=True)
    cohort_cleanup.add_argument("--evidence-receipt-sha256", required=True)
    cohort_cleanup.add_argument("--artifacts-uploaded", action="store_true")
    cohort_cleanup.add_argument("--grace-window-elapsed", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    values = list(argv if argv is not None else sys.argv[1:])
    # argparse normally requires a global option before the subcommand.  Move
    # this single capability flag so operators cannot accidentally lose it.
    execute = "--execute" in values
    values = [item for item in values if item != "--execute"]
    if execute:
        values.insert(0, "--execute")
    parser = build_parser()
    args = parser.parse_args(values)
    reservation: Path | None = None
    try:
        if args.receipt_out is not None:
            reservation = _reserve_receipt(args.receipt_out)
        with RunPodV2Client(execute=bool(args.execute)) as client:
            result = _dispatch(args, client)
        rendered = (
            json.dumps(_json_safe(result), ensure_ascii=False, sort_keys=True, indent=2)
            + "\n"
        )
        if args.receipt_out is not None:
            _write_receipt(args.receipt_out, rendered)
    except (ContractError, RunPodClientError, OSError, json.JSONDecodeError) as exc:
        error = {
            "ok": False,
            "error_type": type(exc).__name__,
            "message": str(exc),
            "redacted": True,
        }
        print(json.dumps(error, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    finally:
        if reservation is not None:
            reservation.unlink(missing_ok=True)
    print(rendered, end="")
    return 0


def _dispatch(args: argparse.Namespace, client: RunPodV2Client) -> object:
    if args.command == "inventory":
        return client.inventory_endpoints()
    if args.command == "create":
        spec = EndpointCreateSpec.from_mapping(_read_object(args.spec))
        return client.create_endpoint(spec, idempotency_key=args.idempotency_key)
    if args.command == "get":
        return client.get_endpoint(args.endpoint_id)
    if args.command == "update":
        patch = EndpointPatch.from_mapping(_read_object(args.patch))
        return client.update_endpoint(
            args.endpoint_id,
            patch,
            run_tag=args.run_tag,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "drain":
        return client.drain_endpoint(
            args.endpoint_id,
            run_tag=args.run_tag,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "delete":
        return client.delete_endpoint(
            args.endpoint_id,
            confirmation_endpoint_id=args.confirm_endpoint_id,
            run_tag=args.run_tag,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "verify-absent":
        return client.verify_endpoint_absent(args.endpoint_id)
    if args.command == "audit-orphans":
        return client.audit_orphans(
            run_tag=args.run_tag,
            active_endpoint_ids=args.active_endpoint_id,
            deleted_endpoint_ids=args.deleted_endpoint_id,
        )
    if args.command == "run":
        return client.run_job(
            args.endpoint_id,
            _read_object(args.input),
            run_tag=args.run_tag,
            idempotency_key=args.idempotency_key,
            policy=QueuePolicy(
                execution_timeout_ms=args.execution_timeout_ms,
                ttl_ms=args.ttl_ms,
                low_priority=args.low_priority,
            ),
        )
    if args.command == "status":
        return client.job_status(args.endpoint_id, args.job_id)
    if args.command == "cancel":
        return client.cancel_job(
            args.endpoint_id,
            args.job_id,
            run_tag=args.run_tag,
            idempotency_key=args.idempotency_key,
        )
    if args.command == "billing":
        explicit = args.start_time is not None or args.end_time is not None
        return client.billing_history(
            BillingQuery(
                bucket_size=args.bucket_size,
                start_time=args.start_time,
                end_time=args.end_time,
                last_n=None if explicit else args.last_n,
                endpoint_id=args.endpoint_id,
            )
        )
    if args.command in {
        "cohort-dispatch",
        "cohort-status",
        "cohort-report",
        "cohort-cleanup",
    }:
        coordinator, manifest = _load_coordinator(args.manifest, client)
        if args.command == "cohort-dispatch":
            inputs = manifest.get("inputs_by_run")
            if not isinstance(inputs, Mapping) or any(
                not isinstance(key, str) or not isinstance(item, Mapping)
                for key, item in inputs.items()
            ):
                raise ContractError("cohort manifest inputs_by_run must be an object of objects")
            outcomes = coordinator.dispatch_exact_three(inputs)
            return {
                "outcomes": outcomes,
                "coordinator_report": coordinator.report(),
                "ledger_path": str(coordinator.ledger.path),
            }
        if args.command == "cohort-status":
            return {
                "statuses": coordinator.refresh_statuses(),
                "coordinator_report": coordinator.report(),
                "ledger_path": str(coordinator.ledger.path),
            }
        if args.command == "cohort-report":
            return {
                "coordinator_report": coordinator.report(),
                "ledger_path": str(coordinator.ledger.path),
            }
        if args.confirm_endpoint_id != coordinator.endpoint_id:
            raise ContractError("cohort cleanup confirmation must exactly match endpoint_id")
        absence = coordinator.cleanup_endpoint(
            artifacts_uploaded=args.artifacts_uploaded,
            evidence_receipt_sha256=args.evidence_receipt_sha256,
            grace_window_elapsed=args.grace_window_elapsed,
        )
        return {
            "cleanup_receipt": absence,
            "coordinator_report": coordinator.report(),
            "ledger_path": str(coordinator.ledger.path),
        }
    raise ContractError(f"unsupported command: {args.command}")


def _read_object(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ContractError(f"{path} must contain one JSON object")
    return value


def _json_safe(value: object) -> object:
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_safe(to_dict())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ContractError(f"CLI result type is not serializable: {type(value).__name__}")


def _write_receipt(path: Path, rendered: str) -> None:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError(
            f"receipt already exists and will not be overwritten: {target}"
        ) from exc


def _reserve_receipt(path: Path) -> Path:
    target = path.resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise ContractError(f"receipt already exists and will not be overwritten: {target}")
    reservation = target.with_name(target.name + ".lock")
    try:
        with reservation.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(f"pid={os.getpid()}\n")
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise ContractError(f"receipt path is reserved by another writer: {target}") from exc
    return reservation


def _load_coordinator(
    manifest_path: Path, client: RunPodV2Client
) -> tuple[ExactThreeRunPodCoordinator, Mapping[str, Any]]:
    # Imports stay local so low-level client commands never pull the benchmark
    # coordinator (and its filesystem contracts) into their import path.
    from benchmark.v6.ledger import EvidenceLedger
    from benchmark.v6.repeats import RepeatRun
    from benchmark.v6.runpod_coordinator import ExactThreeRunPodCoordinator, make_run_tag
    from infra.runpod.v6.orchestration import SpendGuard, SpendPolicy

    manifest = _read_object(manifest_path)
    allowed = {
        "schema_version",
        "endpoint_id",
        "ledger_path",
        "expected_cost_usd",
        "runs",
        "inputs_by_run",
    }
    unknown = set(manifest) - allowed
    if unknown or manifest.get("schema_version") != "6.0.0":
        raise ContractError(f"invalid cohort manifest fields: {sorted(unknown)}")
    rows = manifest.get("runs")
    if not isinstance(rows, list):
        raise ContractError("cohort manifest runs must be an array")
    run_keys = {
        "cohort_id",
        "run_id",
        "repeat_index",
        "candidate_id",
        "benchmark_id",
        "environment_sha256",
        "repeat_root",
        "prediction_root",
        "log_root",
        "official_result_root",
        "critical_result_root",
    }
    runs: list[RepeatRun] = []
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != run_keys:
            raise ContractError("cohort run record shape drift")
        path_keys = (
                "repeat_root",
                "prediction_root",
                "log_root",
                "official_result_root",
                "critical_result_root",
            )
        raw_paths = {key: Path(str(row[key])) for key in path_keys}
        if any(not path.is_absolute() for path in raw_paths.values()):
            raise ContractError("cohort run artifact paths must be absolute")
        try:
            runs.append(
                RepeatRun(
                    cohort_id=str(row["cohort_id"]),
                    run_id=str(row["run_id"]),
                    repeat_index=int(row["repeat_index"]),
                    candidate_id=str(row["candidate_id"]),
                    benchmark_id=str(row["benchmark_id"]),
                    environment_sha256=str(row["environment_sha256"]),
                    repeat_root=raw_paths["repeat_root"].resolve(strict=False),
                    prediction_root=raw_paths["prediction_root"].resolve(strict=False),
                    log_root=raw_paths["log_root"].resolve(strict=False),
                    official_result_root=raw_paths["official_result_root"].resolve(
                        strict=False
                    ),
                    critical_result_root=raw_paths["critical_result_root"].resolve(
                        strict=False
                    ),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ContractError("cohort run contains invalid scalar values") from exc
    endpoint_id = str(manifest.get("endpoint_id", ""))
    ledger_path = Path(str(manifest.get("ledger_path", "")))
    if not ledger_path.is_absolute():
        raise ContractError("cohort manifest ledger_path must be absolute")
    try:
        expected_cost = Decimal(str(manifest.get("expected_cost_usd", "")))
    except InvalidOperation as exc:
        raise ContractError("cohort expected_cost_usd must be a finite decimal") from exc
    if not expected_cost.is_finite() or expected_cost <= 0:
        raise ContractError("cohort expected_cost_usd must be positive and finite")
    run_tag = make_run_tag(runs)
    ledger = EvidenceLedger(ledger_path, cohort_id=runs[0].cohort_id, run_tag=run_tag)
    coordinator = ExactThreeRunPodCoordinator(
        runs=runs,
        endpoint_id=endpoint_id,
        client=client,
        ledger=ledger,
        spend_guard=SpendGuard(
            run_id=runs[0].cohort_id,
            policy=SpendPolicy(
                expected_cost_usd=expected_cost,
                provider_retry_count=0,
            ),
        ),
    )
    return coordinator, manifest


if __name__ == "__main__":  # pragma: no cover - exercised via package entry point
    raise SystemExit(main())
