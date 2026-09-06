"""``python -m arena.controller <command> [--execute] [--model KEY]``.

Every command is a dry run unless ``--execute`` is passed. A dry run prints the
exact provider requests it would make and writes a receipt; nothing paid
happens. That is ARENA_CONTRACT section 5 and section 9's "every CLI defaults to
dry run" in one place.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from arena.constants import CAMPAIGN_ID, GPU_MODEL_KEYS, STAGED_PUBLIC_CORE_ROOT
from arena.controller import cost as cost_module
from arena.controller.authorization_gate import (
    AuthorizationDecision,
    CostEstimate,
    GateError,
    LicenseDecision,
    authorize,
    effective_pod_lifetime_hours,
    estimate_pod_cost,
    license_gate,
)
from arena.controller.bundle import (
    BundleError,
    bundle_object_key,
    publish_bundle,
    resolve_bundle_sha256,
)
from arena.controller.canary import CanaryError, load_canary_selection
from arena.controller.cleanup import clean_up_campaign, verify_cleanup
from arena.controller.driver import (
    DEFAULT_BOOTSTRAP_DEADLINE_SECONDS,
    DEFAULT_READY_POLL_SECONDS,
    run_canary,
)
from arena.controller.events import EventLog
from arena.controller.freeze import FreezeError, freeze_model
from arena.controller.full_run import _with_runtime_modes, run_full
from arena.controller.gpu_pools import (
    MAX_PRICE_SNAPSHOT_AGE_HOURS,
    GpuPoolError,
    PoolValidation,
    latest_price_snapshot_path,
    load_price_snapshot,
    snapshot_age_hours,
    validate_pool,
)
from arena.controller.paths import CampaignPaths
from arena.controller.plan import (
    ModelPlanEntry,
    PlanError,
    build_plan,
    load_model_registry,
    load_source_manifest,
)
from arena.controller.preflight import check_run_config, run_preflight
from arena.controller.prompts import PromptRef, resolve_prompt
from arena.controller.provision import (
    DEFAULT_CONTAINER_DISK_GB,
    CudaConstraint,
    ProvisionError,
    ProvisionResult,
    build_pod_spec,
    check_cuda_constraint,
    check_runtime_mode,
    provision_pod,
    record_provisioning,
    record_provisioning_intent,
)
from arena.controller.queue import CampaignQueue, PodRecord
from arena.controller.run import (
    eligibility,
    entry_with_canary_verdict,
)
from arena.controller.runtime_spec import (
    RuntimeSpecError,
    RuntimeSpecView,
    load_runtime_spec,
    registry_license_status,
)
from arena.core.ids import bootstrap_image_digest
from arena.provider.r2 import BUCKET_NAME, R2Client, R2Error
from arena.provider.runpod_pods import (
    PodSpec,
    PriceSnapshot,
    RunPodClientError,
    RunPodPodsClient,
)
from arena.provider.runpod_v1 import RunPodV1Client
from arena.provider.safety import read_json, utc_now_iso, write_json_atomic
from arena.provider.secrets import (
    Secret,
    SecretUnavailable,
    r2_credentials,
    runpod_api_key,
    worker_bearer,
)
from arena.provider.worker_client import WorkerClient, worker_base_url

__all__ = ["build_parser", "main"]

COMMANDS: Final = (
    "preflight",
    "plan",
    "bundle",
    "canary",
    "run",
    "status",
    "pause",
    "resume",
    "drain",
    "freeze",
    "cleanup-verify",
    "cost",
)

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 2
EXIT_BLOCKED: Final = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena.controller",
        description=f"Campaign controller for {CAMPAIGN_ID}. Dry run unless --execute.",
    )
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="actually contact the provider. Without it nothing paid happens.",
    )
    parser.add_argument("--model", dest="model_key", default=None, help="model_key to act on")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="campaign root (defaults to the namespace root)",
    )
    parser.add_argument(
        "--credentials",
        type=Path,
        default=None,
        help="credential file override, for tests",
    )
    parser.add_argument(
        "--bundle-sha256",
        dest="bundle_sha256",
        default=None,
        help=(
            "sha256 (64 hex) of the worker bundle in R2. Required for a bootstrap pod: "
            "it is pinned into the start command so a wrong bundle never starts."
        ),
    )
    parser.add_argument(
        "--bundle-key",
        dest="bundle_key",
        default=None,
        help="R2 object key of the worker bundle (default: bundles/<campaign>/<model>.tar.gz)",
    )
    parser.add_argument(
        "--replica-index",
        dest="replica_index",
        type=int,
        default=None,
        help=(
            "which replica of this model to provision (pod name suffix). Defaults to "
            "--shard-index when a run is sliced, so each slice gets its own pod, and "
            "to 0 otherwise (D83)."
        ),
    )
    parser.add_argument(
        "--volume-gb",
        dest="volume_gb",
        type=int,
        default=0,
        help=(
            "persistent network-volume size at /workspace. 0 (the default) means none: "
            "weights land on the container disk and are wiped with the pod."
        ),
    )
    parser.add_argument(
        "--container-disk-gb",
        dest="container_disk_gb",
        type=int,
        default=DEFAULT_CONTAINER_DISK_GB,
        help=(
            f"container disk size in GB (default {DEFAULT_CONTAINER_DISK_GB}). Anything other "
            "than the default is priced into required_usd (D24)."
        ),
    )
    parser.add_argument(
        "--cloud",
        dest="cloud",
        choices=("SECURE", "COMMUNITY"),
        default="SECURE",
        help="cloud tier to price and rent (default SECURE, per the plan)",
    )
    parser.add_argument(
        "--bootstrap-deadline-minutes",
        dest="bootstrap_deadline_minutes",
        type=float,
        default=DEFAULT_BOOTSTRAP_DEADLINE_SECONDS / 60.0,
        help=(
            "how long a bootstrap pod may take to reach READY before the canary gives up "
            "and returns the pod (D20)"
        ),
    )
    parser.add_argument(
        "--lifetime-hours",
        dest="lifetime_hours",
        type=float,
        default=None,
        help=(
            "watchdog: stop and delete the pod at this age regardless (D10, D20). "
            "Defaults to the phase ceiling -- 2 h for a canary, 6 h for a full run. "
            "A shorter value is enforced on the pod and reserved against the budget, "
            "so it frees headroom it also honours; a longer one is clamped (D84)."
        ),
    )
    parser.add_argument(
        "--ready-poll-seconds",
        dest="ready_poll_seconds",
        type=float,
        default=DEFAULT_READY_POLL_SECONDS,
        help=(
            "seconds between /v1/ready polls while a bootstrap pod installs and loads "
            "(default 20). The bootstrap deadline, not this, is what gives up."
        ),
    )
    parser.add_argument(
        "--staged-root",
        dest="staged_root",
        type=Path,
        default=STAGED_PUBLIC_CORE_ROOT,
        help=(
            "directory holding the staged public-core page PNGs the canary dispatches "
            "(default: benchmark/datasets/staged-public-core). Ground truth is never read "
            "from the inference plane."
        ),
    )
    parser.add_argument(
        "--max-pods",
        type=int,
        default=1,
        help=(
            "run: how many pods this invocation may rent in sequence (D72). Each one "
            "beyond the first goes back through the authorization gate."
        ),
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=None,
        help=(
            "run: stop after this many pages in this invocation (a rehearsal of the "
            "full path on a handful of pages; default: no limit)."
        ),
    )
    parser.add_argument(
        "--shard-count",
        type=int,
        default=None,
        help=(
            "run: split this model's shards into this many disjoint slices, so that "
            "many drivers can run its pages at the same time, one pod each (D76). "
            "Given together with --shard-index."
        ),
    )
    parser.add_argument(
        "--shard-index",
        type=int,
        default=None,
        help="run: which slice this driver owns, 0-based, below --shard-count (D76).",
    )
    parser.add_argument(
        "--allow-incomplete",
        dest="allow_incomplete",
        action="store_true",
        help=(
            "seal a manifest for a model whose run has not finished. The marker records "
            "planned and settled counts and complete=false, so nothing downstream reads a "
            "partial run as a whole one (D87)."
        ),
    )
    parser.add_argument(
        "--drive",
        dest="drive",
        action="store_true",
        default=True,
        help="run the whole canary in this process (default; D20)",
    )
    parser.add_argument(
        "--no-drive",
        dest="drive",
        action="store_false",
        help=(
            "gate and provision only, without dispatching. Dry-run rehearsal of the gate; "
            "refused with --execute, because a live pod nobody drives is the exact finding "
            "D20 exists to close."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = CampaignPaths(root=args.root) if args.root else CampaignPaths.default()
    paths.ensure()

    handlers = {
        "preflight": _preflight,
        "plan": _plan,
        "bundle": _bundle,
        "canary": _canary,
        "run": _run,
        "status": _status,
        "pause": _pause,
        "resume": _resume,
        "drain": _drain,
        "freeze": _freeze,
        "cleanup-verify": _cleanup_verify,
        "cost": _cost,
    }
    return handlers[args.command](args, paths)


# --------------------------------------------------------------- commands


def _preflight(args: argparse.Namespace, paths: CampaignPaths) -> int:
    report = run_preflight(paths=paths, execute=args.execute, credential_path=args.credentials)
    for line in report.lines():
        print(line)
    if report.receipt_path is not None:
        print(f"receipt: {report.receipt_path}")
    return EXIT_OK if report.ok else EXIT_BLOCKED


def _plan(args: argparse.Namespace, paths: CampaignPaths) -> int:
    model_keys = _model_keys(args)
    try:
        samples = load_source_manifest(paths.source_manifest)
    except PlanError as exc:
        print(f"plan refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    snapshot = _price_snapshot(paths)
    with CampaignQueue(paths.queue_db) as queue:
        events = EventLog(paths.events_log)
        for model_key in model_keys:
            try:
                entry = load_model_registry(paths.model_registry, model_key)
            except PlanError as exc:
                print(f"{model_key}: {exc}", file=sys.stderr)
                return EXIT_REFUSED
            # D9: a GPU id the catalog does not carry fails this model here,
            # not after the whole plan has been enqueued and a pod refused.
            if snapshot is not None:
                validation = validate_pool(model_key, entry.gpu_pool_priority, snapshot)
                if not validation.ok:
                    for line in validation.failure_lines():
                        print(f"  {line}", file=sys.stderr)
                    return EXIT_BLOCKED
            plan = build_plan(model_key=model_key, samples=samples, entry=entry)
            queue.upsert_shards(plan.shards)
            added, skipped = queue.enqueue(plan.jobs)
            queue.set_model_state(
                model_key,
                state="QUEUED",
                canary_status=entry.canary_status,
                full_run_eligible=entry.full_run_eligible,
            )
            events.append(
                entity_kind="model",
                entity_id=model_key,
                to_state="QUEUED",
                reason="plan built",
                detail={
                    "shards": len(plan.shards),
                    "jobs_added": added,
                    "jobs_already_present": skipped,
                    "ids_source": plan.ids_source,
                },
            )
            write_json_atomic(
                paths.receipts_dir / f"plan-{model_key}.json",
                {**plan.to_dict(), "jobs_added": added, "jobs_already_present": skipped},
                context="plan receipt",
            )
            print(
                f"{model_key}: {len(plan.shards)} shard(s), {len(plan.jobs)} job(s) "
                f"({added} new, {skipped} already queued), ids from {plan.ids_source}"
            )
    return EXIT_OK


def _bundle(args: argparse.Namespace, paths: CampaignPaths) -> int:
    """D21: build, verify, upload, prove and receipt one model's bundle."""

    model_key = args.model_key
    if model_key is None:
        print("bundle needs --model", file=sys.stderr)
        return EXIT_REFUSED
    try:
        publication = publish_bundle(
            paths,
            model_key=model_key,
            execute=bool(args.execute),
            credential_path=args.credentials,
        )
    except (BundleError, R2Error, SecretUnavailable) as exc:
        print(f"bundle refused: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    print(
        f"{model_key}: {publication.file_count} file(s), {publication.size_bytes} bytes, "
        f"sha256 {publication.bundle_sha256}"
    )
    print(f"  object: {publication.bundle_reference}")
    if publication.uploaded:
        print(f"  digest confirmed against the object ({publication.verified_against})")
    else:
        print("  dry run: nothing was uploaded; pass --execute to publish")
    print(f"  receipt: {publication.receipt_path}")
    return EXIT_OK


def _canary(args: argparse.Namespace, paths: CampaignPaths) -> int:
    model_key = args.model_key
    if model_key is None:
        print("canary needs --model", file=sys.stderr)
        return EXIT_REFUSED
    if args.execute and not getattr(args, "drive", True):
        # The whole of D20 is "the pod comes back". `--no-drive --execute`
        # would rent a GPU and return, which is the exact NO-GO finding.
        print(
            "canary refused: --no-drive is a dry-run rehearsal of the gate. With --execute "
            "it would provision a pod and return without dispatching, evaluating or "
            "deleting it -- the finding ARENA_CONTRACT 11.5 D20 exists to close.",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    try:
        selection = load_canary_selection(paths.canary_selection, model_key)
    except CanaryError as exc:
        print(f"canary refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(
        f"canary for {model_key}: {len(selection)} page(s) selected -> "
        f"receipts/canary-{model_key}.json, receipts/registry-updates/{model_key}.json"
    )
    print("  pages: " + ", ".join(selection[:5]) + (" ..." if len(selection) > 5 else ""))
    # The three hashes a run request carries, recomputed both ways. A canary
    # whose registry and runtime.json disagree rents a GPU, reaches READY and
    # then answers HTTP 422 to every page -- which is what pod 27f6f6dif3jcp6
    # did on 2026-09-03. A model whose files are missing entirely is refused a
    # few lines below by the provisioning gate, which names the file.
    agreement = check_run_config(paths, model_key)
    if agreement.disagreements:
        print(
            f"canary refused: {model_key}'s run-config hashes disagree with its runtime. "
            "Every page would come back HTTP 422 and the pod would produce no output.",
            file=sys.stderr,
        )
        for line in agreement.disagreements:
            print(f"  {line}", file=sys.stderr)
        print(
            "  fix: `python -m arena.registry resolve --offline` regenerates "
            "model_registry.json from runtimes/<key>/runtime.json (D16/D17)",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    return _provision(args, paths, model_key=model_key, phase="phase1_canary")


def _registry_entry_for_run(
    args: argparse.Namespace, paths: CampaignPaths, *, model_key: str
) -> tuple[ModelPlanEntry, str | None]:
    """The registry entry a Full Run is judged on (D72).

    A baked runtime carries its image digest in the registry. A bootstrap
    runtime carries ``null`` there by design (D15) and its identity is the
    published bundle (D21), so the digest is derived from the publish receipt
    exactly as the canary driver derives it; the two must agree or section
    9.3's job ids would not line up with the canary's.
    """

    try:
        runtime = load_runtime_spec(paths.runtime_json(model_key), model_key)
    except RuntimeSpecError:
        # No runtime.json: the registry alone decides, and the gate that
        # follows names the missing file the way it always has.
        return load_model_registry(paths.model_registry, model_key), None
    mode = _runtime_mode(args, paths, model_key=model_key, runtime=runtime)
    if mode != "bootstrap":
        return load_model_registry(paths.model_registry, model_key), mode
    published, _receipt = resolve_bundle_sha256(paths, model_key, argv_sha256=args.bundle_sha256)
    digest = bootstrap_image_digest(
        published if published.startswith("sha256:") else f"sha256:{published}"
    )
    prompt = resolve_prompt(
        paths.root, prompt_id=runtime.prompt_id, prompt_kind=runtime.prompt_kind
    )
    entry = load_model_registry(
        paths.model_registry,
        model_key,
        runtime_image_digest=digest,
        prompt_id=prompt.prompt_id,
        prompt_sha256=prompt.prompt_sha256,
    )
    return entry, mode


def _run(args: argparse.Namespace, paths: CampaignPaths) -> int:
    model_key = args.model_key
    if model_key is None:
        print("run needs --model", file=sys.stderr)
        return EXIT_REFUSED
    try:
        entry, mode = _registry_entry_for_run(args, paths, model_key=model_key)
    except (PlanError, BundleError, RuntimeSpecError) as exc:
        print(f"run refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    entry, verdict_note = entry_with_canary_verdict(entry, paths)
    if verdict_note is not None:
        print(f"  {verdict_note}")
    with contextlib.suppress(RuntimeSpecError):
        # No runtime.json: the registry's list is all there is.
        entry = _with_runtime_modes(
            entry,
            load_runtime_spec(paths.runtime_json(model_key), model_key),
            lambda note: print(f"  {note}"),
        )
    gate = eligibility(entry, paths, runtime_mode=mode)
    print(f"{model_key}: full-run eligibility {'ALLOWED' if gate.allowed else 'REFUSED'}")
    print(f"  {gate.reason}")
    if not gate.allowed:
        # D6's second half: a Full Run needs a baked image or a founder waiver.
        # `eligibility` is that check, and it runs before any money is asked for.
        return EXIT_BLOCKED
    with CampaignQueue(paths.queue_db) as queue:
        counts = queue.counts_by_state(model_key=model_key)
    print(f"  queue holds {counts}")
    return _provision(args, paths, model_key=model_key, phase="phase2_full_run")


# ------------------------------------------------------- authorization gate


def _provision(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    phase: str,
) -> int:
    """The D6/D7/D9/D10 gate, then one pod create (dry or live).

    A dry run walks the whole gate and prints the redacted payload it would
    send. That is deliberate: the founder writing an authorization receipt
    needs the same ``required_usd`` the gate will later demand, and a dry run
    that skipped the gate would not produce it.
    """

    now = datetime.now(tz=UTC)
    try:
        runtime = load_runtime_spec(paths.runtime_json(model_key), model_key)
    except RuntimeSpecError as exc:
        print(f"{model_key}: {exc}", file=sys.stderr)
        return EXIT_REFUSED

    # D23: --execute refreshes the catalog live and receipts it; a dry run
    # prices from the newest snapshot on disk and refuses one older than six
    # hours, recording the age either way.
    snapshot, age_hours, snapshot_note = _price_snapshot_for_pricing(paths, args=args, now=now)
    if snapshot_note:
        print(f"  catalog: {snapshot_note}")
    if snapshot is None:
        print(
            f"{model_key}: {snapshot_note or 'no usable catalog price snapshot'}. Run "
            "`python -m arena.controller preflight --execute` first; a pod is never "
            "priced from memory (MP section 13.2, D23).",
            file=sys.stderr,
        )
        return EXIT_BLOCKED

    validation = validate_pool(
        model_key,
        runtime.gpu_pool_priority,
        snapshot,
        gpu_count_min=runtime.gpu_count_min,
        gpu_min_vram_gb=runtime.gpu_min_vram_gb,
    )
    if not validation.ok:
        for line in validation.failure_lines():
            print(f"  {line}", file=sys.stderr)
        return EXIT_BLOCKED
    for line in validation.failure_lines():
        # A partially undersized pool is a warning, not a refusal: the
        # provider rents in list order and the large entries are still valid.
        print(f"  warning: {line}")

    try:
        cuda = _cuda_constraint(model_key, runtime)
    except ProvisionError as exc:
        print(f"{model_key}: {exc}", file=sys.stderr)
        return EXIT_BLOCKED
    print(
        f"  host CUDA: >= {cuda.min_cuda_version} -> allowedCudaVersions "
        f"{list(cuda.allowed_cuda_versions)}"
    )

    licence = license_gate(
        paths=paths,
        model_key=model_key,
        statuses=(runtime.license_status, _registry_license_status(paths, model_key)),
    )
    print(f"  licence: {licence.reason}")
    if not licence.allowed:
        return EXIT_BLOCKED

    hours = effective_pod_lifetime_hours(phase, getattr(args, "lifetime_hours", None))
    try:
        estimate = estimate_pod_cost(
            model_key=model_key,
            snapshot=snapshot,
            gpu_pool_priority=runtime.gpu_pool_priority,
            cloud=str(args.cloud),
            gpu_count=runtime.gpu_count_min,
            hours=float(hours),
            container_disk_gb=int(args.container_disk_gb),
            volume_gb=int(args.volume_gb),
            replicas=1,
            now=now,
        )
        decision = authorize(
            paths=paths,
            phase=phase,
            model_key=model_key,
            required_usd=estimate.required_usd,
            now=now,
            estimate=estimate,
        )
    except GateError as exc:
        print(f"{model_key}: {exc}", file=sys.stderr)
        return EXIT_BLOCKED

    print(
        f"  cost ceiling: {estimate.gpu_count} x {estimate.gpu_type_id} on "
        f"{estimate.cloud} at ${estimate.hourly_rate_usd}/h for {hours}h "
        f"+ disk = ${estimate.required_usd:,.2f}"
    )
    if decision.budget is not None:
        print(f"  budget: {decision.budget.reason()}")
    # ASCII only: the orchestrator's console is cp949 and an em dash here
    # aborts the command with a UnicodeEncodeError after the gate has run.
    verdict = "GRANTED" if decision.allowed else "BLOCKED"
    print(f"  authorization: {verdict}: {decision.reason}")
    if not decision.allowed:
        _write_gate_receipt(
            paths,
            model_key,
            phase,
            decision,
            licence,
            validation,
            cuda=cuda,
            snapshot_age_hours=age_hours,
        )
        return EXIT_BLOCKED

    # D72: a live Full Run is the same shape as a live canary -- provision,
    # dispatch, teardown in one process -- over every page the queue still
    # holds, pod after pod, until nothing is left or a stop rule fires.
    if args.command == "run" and args.execute and getattr(args, "drive", True):
        return _drive_full_run(
            args,
            paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            estimate=estimate,
            decision=decision,
            licence=licence,
            validation=validation,
            cuda=cuda,
            snapshot_age_hours=age_hours,
        )

    # D20: a live canary runs the whole phase here, and the pod comes back in
    # the driver's `finally` no matter how it ends.
    if args.command == "canary" and args.execute and getattr(args, "drive", True):
        return _drive_canary(
            args,
            paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            estimate=estimate,
            decision=decision,
            licence=licence,
            validation=validation,
            cuda=cuda,
            snapshot_age_hours=age_hours,
        )

    try:
        result = _create_pod(args, paths, model_key=model_key, runtime=runtime, snapshot=snapshot)
    except (
        # `BundleError` reaches here whenever the D21 receipt is absent, is a
        # dry run, or disagrees with `--bundle-sha256`. It is a refusal like
        # any other and must print like one -- a traceback out of a dry run
        # tells the operator nothing about which command to run next.
        BundleError,
        ProvisionError,
        PlanError,
        RunPodClientError,
        R2Error,
        SecretUnavailable,
    ) as exc:
        print(f"{model_key}: provisioning refused: {exc}", file=sys.stderr)
        return EXIT_BLOCKED

    record = record_provisioning(
        paths,
        result=result.result,
        spec=result.spec,
        phase=phase,
        authorization_receipt_path=(
            None if decision.receipt is None else str(decision.receipt.path)
        ),
        authorization_receipt_sha256=(
            None if decision.receipt is None else decision.receipt.sha256
        ),
        price_snapshot_sha256=estimate.price_snapshot_sha256,
        price_row_sha256=estimate.price_row_sha256,
        listed_rate_usd_per_hour=estimate.hourly_rate_usd,
        required_usd=estimate.required_usd,
    )
    print(f"  provider API: REST {result.result.provider_api_version} ({result.result.mode})")
    print("  redacted create payload:")
    rendered = json.dumps(record["create_payload_redacted"], indent=2, sort_keys=True)
    for line in rendered.splitlines():
        print(f"    {line}")

    if result.result.pod_id is not None:
        with CampaignQueue(paths.queue_db) as queue:
            queue.upsert_pod(
                PodRecord(
                    pod_id=result.result.pod_id,
                    model_key=model_key,
                    name=result.spec.name,
                    state="PROVISIONING",
                    gpu_type=estimate.gpu_type_id,
                    cloud_type=result.spec.cloud_type,
                    runtime_mode=result.spec.runtime_mode,
                    listed_rate_usd_per_hour=estimate.hourly_rate_usd,
                    gpu_count=result.spec.gpu_count,
                    price_snapshot_sha256=estimate.price_snapshot_sha256,
                    provider_api_version=result.result.provider_api_version,
                    authorization_receipt_path=(
                        None if decision.receipt is None else str(decision.receipt.path)
                    ),
                    authorization_receipt_sha256=(
                        None if decision.receipt is None else decision.receipt.sha256
                    ),
                    provisioned_at=utc_now_iso(),
                )
            )
        print(f"  pod {result.result.pod_id} recorded in the queue and the pod ledger")
    _write_gate_receipt(
        paths,
        model_key,
        phase,
        decision,
        licence,
        validation,
        cuda=cuda,
        record=record,
        snapshot_age_hours=age_hours,
    )
    return EXIT_OK


@dataclass(frozen=True, slots=True)
class _CreatedPod:
    spec: PodSpec
    result: ProvisionResult


def _runtime_mode(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    runtime: RuntimeSpecView,
) -> str:
    """Which mode this pod runs in, decided from what actually exists (D15, D21).

    Before D21 the answer was "bootstrap if ``--bundle-sha256`` was typed",
    which stopped being true the moment the digest moved into the publish
    receipt: a model that allows both modes then fell through to ``baked`` and
    was refused for a ``container_digest`` the registry deliberately keeps
    ``null`` until an image is actually baked (D15).

    The order now is: what the runtime permits, then what exists on disk.
    """

    allowed = runtime.runtime_mode_allowed
    if args.bundle_sha256 is not None:
        # An explicit digest is an explicit request for the bootstrap path.
        # It is answered even when the runtime forbids bootstrap, because
        # D25's refusal -- naming the file that forbids it -- is a better
        # answer than quietly building a baked pod the operator did not ask
        # for (D36: infinity_parser2_pro is baked-only, and must say so).
        return "bootstrap"
    if "bootstrap" not in allowed:
        return "baked"
    if "baked" not in allowed:
        return "bootstrap"
    if paths.bundle_receipt(model_key).is_file():
        return "bootstrap"
    # Both modes are permitted, nothing was published: only a baked image can
    # answer, and `load_model_registry` refuses if there is no digest for one.
    return "baked"


def _cuda_constraint(model_key: str, runtime: RuntimeSpecView) -> CudaConstraint:
    """The host CUDA floor this runtime asked for, or a refusal naming its file."""

    return check_cuda_constraint(
        model_key=model_key,
        runtime_json=f"runtimes/{model_key}/runtime.json",
        min_cuda_version=runtime.min_cuda_version,
        gpu_pool_priority=runtime.gpu_pool_priority,
    )


def _build_spec(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    runtime: RuntimeSpecView,
) -> tuple[PodSpec, str]:
    """The pod spec plus the runtime mode it was built for (D15, D21, D25)."""

    runtime_mode = _runtime_mode(args, paths, model_key=model_key, runtime=runtime)
    check_runtime_mode(
        runtime_mode,
        runtime.runtime_mode_allowed,
        runtime_json=f"runtimes/{model_key}/runtime.json",
    )
    cuda = _cuda_constraint(model_key, runtime)
    bundle_url = None
    bundle_sha256 = None
    image_name = runtime.base_image
    image_digest = runtime.base_image

    if runtime_mode == "bootstrap":
        # D21: the digest comes from the publish receipt, and --bundle-sha256
        # is only accepted when it equals it.
        published, receipt = resolve_bundle_sha256(paths, model_key, argv_sha256=args.bundle_sha256)
        bundle_sha256 = (
            published[len("sha256:") :] if published.startswith("sha256:") else published
        )
        # D15: a bootstrap pod's runtime identity is its bundle, not its base
        # image; the base image is recorded separately.
        image_digest = bootstrap_image_digest(
            published if published.startswith("sha256:") else f"sha256:{published}"
        )
        key = str(receipt.get("r2_key") or args.bundle_key or bundle_object_key(model_key))
        bundle_url = _bundle_url(paths, key=key, execute=bool(args.execute), args=args)
    else:
        try:
            entry = load_model_registry(paths.model_registry, model_key)
        except PlanError as exc:
            if "bootstrap" in runtime.runtime_mode_allowed:
                # The registry keeps container_digest null until an image is
                # baked (D15), so "no digest" here usually means the bundle
                # was never published -- name that fix rather than leaving the
                # operator to infer it from a registry field.
                raise ProvisionError(
                    f"{exc} No bundle has been published for {model_key} either, so there "
                    "is no bootstrap digest to fall back on. Run `python -m arena.controller "
                    f"bundle --model {model_key} --execute` first (D21)."
                ) from exc
            raise
        image_name = entry.runtime_image_digest
        image_digest = entry.runtime_image_digest

    # D83: the pod name carries the replica index, and RunPod hands back the
    # existing pod when a name is already up. A sliced run therefore has to
    # name its pod after its slice or every slice shares one pod.
    replica_index = args.replica_index
    if replica_index is None:
        replica_index = int(getattr(args, "shard_index", None) or 0)
    spec = build_pod_spec(
        model_key=model_key,
        replica_index=int(replica_index),
        image_name=image_name,
        image_digest=image_digest,
        model_revision=runtime.model_revision,
        runtime_mode=runtime_mode,
        gpu_type_ids=runtime.gpu_pool_priority,
        gpu_count=runtime.gpu_count_min,
        max_lifetime_hours=effective_pod_lifetime_hours(
            "phase1_canary" if args.command == "canary" else "phase2_full_run",
            getattr(args, "lifetime_hours", None),
        ),
        cloud_type=str(args.cloud),
        container_disk_gb=int(args.container_disk_gb),
        volume_gb=int(args.volume_gb),
        worker_token=_worker_token(execute=bool(args.execute)),
        bundle_url=bundle_url,
        bundle_sha256=bundle_sha256,
        prompt_id=runtime.prompt_id,
        allowed_cuda_versions=cuda.allowed_cuda_versions,
    )
    return spec, runtime_mode


def _create_pod(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    runtime: RuntimeSpecView,
    snapshot: PriceSnapshot,
    required_usd: float | None = None,
    authorization_receipt_path: str | None = None,
    authorization_receipt_sha256: str | None = None,
) -> _CreatedPod:
    """Build the spec and hand it to the API its runtime mode requires."""

    spec, runtime_mode = _build_spec(args, paths, model_key=model_key, runtime=runtime)

    key_secret = runpod_api_key(path=args.credentials)
    receipts_dir = paths.provider_receipts_dir if args.execute else None
    if args.execute:
        # D24: the provisional line names the pod *before* the POST, so an
        # ambiguous create leaves a record even when no response arrives.
        record_provisioning_intent(
            paths,
            spec=spec,
            phase="phase1_canary" if args.command == "canary" else "phase2_full_run",
            provider_api_version="v1" if runtime_mode == "bootstrap" else "v2",
            required_usd=required_usd,
            authorization_receipt_path=authorization_receipt_path,
            authorization_receipt_sha256=authorization_receipt_sha256,
        )
    if runtime_mode == "bootstrap":
        client_v1 = make_v1_client(
            key=key_secret, execute=bool(args.execute), receipts_dir=receipts_dir
        )
        try:
            result = provision_pod(spec, v1_client=client_v1, price_snapshot=snapshot)
        finally:
            client_v1.close()
    else:
        client_v2 = make_v2_client(
            key=key_secret, execute=bool(args.execute), receipts_dir=receipts_dir
        )
        try:
            result = provision_pod(spec, v2_client=client_v2, price_snapshot=snapshot)
        finally:
            client_v2.close()
    return _CreatedPod(spec=spec, result=result)


def _drive_canary(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    runtime: RuntimeSpecView,
    snapshot: PriceSnapshot,
    estimate: CostEstimate,
    decision: AuthorizationDecision,
    licence: LicenseDecision,
    validation: PoolValidation,
    cuda: CudaConstraint,
    snapshot_age_hours: float | None,
) -> int:
    """D20: one process runs provision -> dispatch -> evaluate -> teardown."""

    receipt_path = None if decision.receipt is None else str(decision.receipt.path)
    receipt_sha = None if decision.receipt is None else decision.receipt.sha256
    key_secret = runpod_api_key(path=args.credentials)
    receipts_dir = paths.provider_receipts_dir
    client_v1 = make_v1_client(key=key_secret, execute=True, receipts_dir=receipts_dir)
    client_v2 = make_v2_client(key=key_secret, execute=True, receipts_dir=receipts_dir)
    worker_token = _worker_token(execute=True)

    def create(image_digest: str, prompt: PromptRef) -> tuple[str | None, dict[str, object]]:
        created = _create_pod(
            args,
            paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            required_usd=estimate.required_usd,
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
        )
        record = record_provisioning(
            paths,
            result=created.result,
            spec=created.spec,
            phase="phase1_canary",
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
            price_snapshot_sha256=estimate.price_snapshot_sha256,
            price_row_sha256=estimate.price_row_sha256,
            listed_rate_usd_per_hour=estimate.hourly_rate_usd,
            required_usd=estimate.required_usd,
        )
        print(f"  provider API: REST {created.result.provider_api_version} ({created.result.mode})")
        if created.result.pod_id is not None:
            print(f"  pod {created.result.pod_id} created and recorded in the pod ledger")
        payload = record.get("create_payload_redacted")
        summary: dict[str, object] = dict(payload) if isinstance(payload, Mapping) else {}
        # D48: the pool walk decides which GPU was rented, and the estimate
        # only named the ceiling. The driver prices the pod ledger from this.
        created_gpu = record.get("gpu_type_id_created")
        if isinstance(created_gpu, str) and created_gpu:
            summary["gpu_type_id_created"] = created_gpu
        return created.result.pod_id, summary

    def worker_factory(pod_id: str) -> WorkerClient:
        return make_worker_client(pod_id, bearer=worker_token)

    try:
        result = run_canary(
            paths=paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            gpu_type=estimate.gpu_type_id,
            hourly_rate_usd=estimate.hourly_rate_usd,
            price_row_sha256=estimate.price_row_sha256,
            cloud=estimate.cloud,
            v1_client=client_v1,
            v2_client=client_v2,
            create_pod=create,
            worker_factory=worker_factory,
            staged_root=Path(args.staged_root),
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
            bundle_sha256_argv=args.bundle_sha256,
            bootstrap_deadline_seconds=float(args.bootstrap_deadline_minutes) * 60.0,
            ready_poll_seconds=float(args.ready_poll_seconds),
            lifetime_seconds=effective_pod_lifetime_hours(
                "phase1_canary", getattr(args, "lifetime_hours", None)
            )
            * 3600.0,
        )
    finally:
        client_v1.close()
        client_v2.close()

    _write_gate_receipt(
        paths,
        model_key,
        "phase1_canary",
        decision,
        licence,
        validation,
        cuda=cuda,
        snapshot_age_hours=snapshot_age_hours,
        driver=result.to_dict(),
    )
    print(f"  canary {result.status}: {result.pages_succeeded}/{result.pages_attempted} page(s)")
    for note in result.notes:
        print(f"    {note}")
    if result.canary_receipt_path is not None:
        print(f"  canary receipt: {result.canary_receipt_path}")
    if result.registry_update_path is not None:
        print(f"  registry update: {result.registry_update_path}")
    if result.ledger_path is not None:
        print(f"  pod ledger: {result.ledger_path}")
    print(f"  driver receipt: {result.driver_receipt_path}")
    print(
        f"  pod returned: {result.pod_return.returned} "
        f"(v1 clear={result.pod_return.gone_from_v1}, v2 clear={result.pod_return.gone_from_v2})"
    )
    if not result.pod_return.returned:
        # A pod that is still listed is still billing. That outranks the
        # canary verdict: the operator must clean up before anything else.
        print(
            "  pod NOT confirmed gone; run `python -m arena.controller cleanup-verify --execute`",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    if result.status == "ERROR":
        print(f"  canary errored: {result.error}", file=sys.stderr)
        return EXIT_BLOCKED
    return EXIT_OK if result.passed else EXIT_BLOCKED


def _drive_full_run(
    args: argparse.Namespace,
    paths: CampaignPaths,
    *,
    model_key: str,
    runtime: RuntimeSpecView,
    snapshot: PriceSnapshot,
    estimate: CostEstimate,
    decision: AuthorizationDecision,
    licence: LicenseDecision,
    validation: PoolValidation,
    cuda: CudaConstraint,
    snapshot_age_hours: float | None,
) -> int:
    """D72: provision -> dispatch every pending page -> teardown, pod after pod.

    Every additional pod goes back through the D6 gate with the money already
    spent counted, so a receipt written for one pod's ceiling never pays for
    six of them by accident.
    """

    receipt_path = None if decision.receipt is None else str(decision.receipt.path)
    receipt_sha = None if decision.receipt is None else decision.receipt.sha256
    key_secret = runpod_api_key(path=args.credentials)
    receipts_dir = paths.provider_receipts_dir
    client_v1 = make_v1_client(key=key_secret, execute=True, receipts_dir=receipts_dir)
    client_v2 = make_v2_client(key=key_secret, execute=True, receipts_dir=receipts_dir)
    worker_token = _worker_token(execute=True)

    def create(image_digest: str, prompt: PromptRef) -> tuple[str | None, dict[str, object]]:
        created = _create_pod(
            args,
            paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            required_usd=estimate.required_usd,
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
        )
        record = record_provisioning(
            paths,
            result=created.result,
            spec=created.spec,
            phase="phase2_full_run",
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
            price_snapshot_sha256=estimate.price_snapshot_sha256,
            price_row_sha256=estimate.price_row_sha256,
            listed_rate_usd_per_hour=estimate.hourly_rate_usd,
            required_usd=estimate.required_usd,
        )
        print(f"  provider API: REST {created.result.provider_api_version} ({created.result.mode})")
        if created.result.pod_id is not None:
            print(f"  pod {created.result.pod_id} created and recorded in the pod ledger")
        payload = record.get("create_payload_redacted")
        summary: dict[str, object] = dict(payload) if isinstance(payload, Mapping) else {}
        created_gpu = record.get("gpu_type_id_created")
        if isinstance(created_gpu, str) and created_gpu:
            summary["gpu_type_id_created"] = created_gpu
        return created.result.pod_id, summary

    def worker_factory(pod_id: str) -> WorkerClient:
        return make_worker_client(pod_id, bearer=worker_token)

    def next_pod_allowed(pod_index: int) -> tuple[bool, str]:
        # The first pod was authorized by the gate that brought us here. Each
        # later one is authorized afresh against what has been spent since.
        if pod_index == 0:
            return True, decision.reason
        again = authorize(
            paths=paths,
            phase="phase2_full_run",
            model_key=model_key,
            required_usd=estimate.required_usd,
            now=datetime.now(tz=UTC),
            estimate=estimate,
        )
        return again.allowed, again.reason

    try:
        result = run_full(
            paths=paths,
            model_key=model_key,
            runtime=runtime,
            snapshot=snapshot,
            gpu_type=estimate.gpu_type_id,
            hourly_rate_usd=estimate.hourly_rate_usd,
            price_row_sha256=estimate.price_row_sha256,
            cloud=estimate.cloud,
            v1_client=client_v1,
            v2_client=client_v2,
            create_pod=create,
            worker_factory=worker_factory,
            staged_root=Path(args.staged_root),
            authorization_receipt_path=receipt_path,
            authorization_receipt_sha256=receipt_sha,
            bundle_sha256_argv=args.bundle_sha256,
            bootstrap_deadline_seconds=float(args.bootstrap_deadline_minutes) * 60.0,
            ready_poll_seconds=float(args.ready_poll_seconds),
            lifetime_seconds=effective_pod_lifetime_hours(
                "phase2_full_run", getattr(args, "lifetime_hours", None)
            )
            * 3600.0,
            max_pods=int(args.max_pods),
            page_limit=args.page_limit,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            next_pod_allowed=next_pod_allowed,
        )
    finally:
        client_v1.close()
        client_v2.close()

    _write_gate_receipt(
        paths,
        model_key,
        "phase2_full_run",
        decision,
        licence,
        validation,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        cuda=cuda,
        snapshot_age_hours=snapshot_age_hours,
        driver=result.to_dict(),
    )
    print(
        f"  full run {result.status}: {result.pages_succeeded}/{result.pages_attempted} "
        f"page(s) this invocation across {len(result.pods)} pod(s); "
        f"stop_reason={result.stop_reason}; queue {result.job_counts}"
    )
    for note in result.notes:
        print(f"    {note}")
    if result.run_summary_path is not None:
        print(f"  run summary: {result.run_summary_path}")
    if result.freeze is not None:
        print(
            f"  frozen: {result.freeze.get('frozen')} "
            f"({result.freeze.get('success_count')} SUCCESS / "
            f"{result.freeze.get('failed_count')} FAILED); "
            f"manifest {result.freeze.get('manifest_sha256')}"
        )
    print(f"  driver receipt: {result.driver_receipt_path}")
    if not result.all_pods_returned:
        print(
            "  a pod is NOT confirmed gone; run `python -m arena.controller cleanup-verify "
            "--execute`",
            file=sys.stderr,
        )
        return EXIT_BLOCKED
    if result.status == "ERROR":
        print(f"  full run errored: {result.error}", file=sys.stderr)
        return EXIT_BLOCKED
    return EXIT_OK if result.status == "COMPLETE" else EXIT_BLOCKED


def _price_snapshot_for_pricing(
    paths: CampaignPaths, *, args: argparse.Namespace, now: datetime
) -> tuple[PriceSnapshot | None, float | None, str]:
    """D23. ``--execute`` refreshes live; a dry run refuses a stale snapshot."""

    if args.execute:
        try:
            key = runpod_api_key(path=args.credentials)
        except SecretUnavailable as exc:
            return None, None, f"no provider credential to refresh the catalog: {exc}"
        client = make_v2_client(key=key, execute=True, receipts_dir=paths.provider_receipts_dir)
        try:
            refreshed = client.catalog_gpus()
        except RunPodClientError as exc:
            return None, None, f"catalog refresh failed: {exc}"
        finally:
            client.close()
        if isinstance(refreshed, PriceSnapshot):
            return refreshed, 0.0, "refreshed live and receipted (D23)"
        return None, None, "catalog refresh returned a dry-run receipt while executing"

    snapshot = _price_snapshot(paths)
    if snapshot is None:
        return None, None, "no catalog snapshot on disk"
    age = snapshot_age_hours(snapshot, now=now)
    if age is None:
        return None, None, "the snapshot's captured_at is unreadable"
    if age > MAX_PRICE_SNAPSHOT_AGE_HOURS:
        return (
            None,
            age,
            f"the snapshot is {age:.1f} h old, past the "
            f"{MAX_PRICE_SNAPSHOT_AGE_HOURS:.0f} h dry-run freshness limit (D23)",
        )
    return snapshot, age, f"snapshot on disk is {age:.2f} h old"


def make_worker_client(pod_id: str, *, bearer: Secret) -> WorkerClient:
    """Seam for tests: the worker API client the driver dispatches through."""

    return WorkerClient(worker_base_url(pod_id), bearer=bearer)


def make_v1_client(*, key: Secret, execute: bool, receipts_dir: Path | None) -> RunPodV1Client:
    """Seam for tests: the REST v1 client the CLI provisions bootstrap pods on."""

    return RunPodV1Client(key=key, execute=execute, receipts_dir=receipts_dir)


def make_v2_client(*, key: Secret, execute: bool, receipts_dir: Path | None) -> RunPodPodsClient:
    """Seam for tests: the REST v2 client the CLI provisions baked pods on."""

    return RunPodPodsClient(key=key, execute=execute, receipts_dir=receipts_dir)


def _worker_token(*, execute: bool) -> Secret:
    """The per-campaign worker bearer, from the environment.

    On ``--execute`` it must exist: a pod started without it would run an
    unauthenticated worker. A dry run uses a marked placeholder so the payload
    shape is visible without inventing a credential.
    """

    value = os.environ.get("ARENA_WORKER_TOKEN", "")
    if value:
        return worker_bearer(value)
    if execute:
        raise SecretUnavailable(
            "ARENA_WORKER_TOKEN is unset; a worker pod without a bearer would accept "
            "unauthenticated requests"
        )
    return worker_bearer("DRY-RUN-PLACEHOLDER-NOT-A-CREDENTIAL")


def _bundle_url(
    paths: CampaignPaths, *, key: str, execute: bool, args: argparse.Namespace
) -> Secret:
    """A presigned GET for the bundle on execute; an unsigned reference on dry.

    Contract 11.3(1) asks for at least two hours of validity, which is the
    canary pod's whole permitted lifetime (D10).
    """

    credentials = r2_credentials(block="account", path=args.credentials)
    client = R2Client(credentials, bucket=BUCKET_NAME, execute=execute)
    if not execute:
        host = client.endpoint_host
        return worker_bearer(f"https://{host}/{BUCKET_NAME}/{key}")
    url = client.presign_get(key, expires_seconds=2 * 3600)
    return worker_bearer(url)


def _registry_license_status(paths: CampaignPaths, model_key: str) -> str | None:
    document = read_json(paths.model_registry) if paths.model_registry.is_file() else None
    if not isinstance(document, dict):
        return None
    models = document.get("models", document)
    record = models.get(model_key) if isinstance(models, dict) else None
    return registry_license_status(record if isinstance(record, dict) else None)


def _price_snapshot(paths: CampaignPaths) -> PriceSnapshot | None:
    path = latest_price_snapshot_path(paths.provider_receipts_dir)
    if path is None:
        return None
    try:
        return load_price_snapshot(path)
    except GpuPoolError as exc:
        print(f"  catalog snapshot unusable: {exc}", file=sys.stderr)
        return None


def _write_gate_receipt(
    paths: CampaignPaths,
    model_key: str,
    phase: str,
    decision: AuthorizationDecision,
    licence: LicenseDecision,
    validation: PoolValidation,
    *,
    cuda: CudaConstraint | None = None,
    record: dict[str, object] | None = None,
    snapshot_age_hours: float | None = None,
    driver: dict[str, object] | None = None,
    shard_index: int | None = None,
    shard_count: int | None = None,
) -> Path:
    path = paths.provision_gate_receipt(
        model_key, phase, shard_index=shard_index, shard_count=shard_count
    )
    write_json_atomic(
        path,
        {
            "schema": "tavonel.arena.provision_gate.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": model_key,
            "phase": phase,
            "evaluated_at": utc_now_iso(),
            "authorization": decision.to_dict(),
            "license": licence.to_dict(),
            "gpu_pool": validation.to_dict(),
            # The host CUDA floor the create payload carried. null only when
            # the gate refused before it could be evaluated.
            "cuda": None if cuda is None else cuda.to_dict(),
            # D23: the age is recorded whether or not it was acceptable.
            "price_snapshot_age_hours": (
                None if snapshot_age_hours is None else round(snapshot_age_hours, 3)
            ),
            "price_snapshot_max_age_hours": MAX_PRICE_SNAPSHOT_AGE_HOURS,
            "provisioning": record,
            "canary_driver": driver,
        },
        context="provision gate receipt",
    )
    return path


def _status(args: argparse.Namespace, paths: CampaignPaths) -> int:
    with CampaignQueue(paths.queue_db) as queue:
        print(f"campaign {CAMPAIGN_ID}")
        flag = queue.flag("budget_state", "NORMAL")
        print(f"  budget state: {flag}")
        overall = queue.counts_by_state()
        print(f"  jobs: {overall}")
        for model in queue.model_states():
            print(
                f"  {model['model_key']}: state={model['state']} "
                f"canary={model['canary_status']} "
                f"full_run_eligible={bool(model['full_run_eligible'])}"
            )
        workers = queue.workers()
        if workers:
            for worker in workers:
                print(
                    f"  worker {worker.worker_id}: {worker.state} "
                    f"done={worker.jobs_done} failed={worker.jobs_failed}"
                )
        pods = queue.pods(live_only=True)
        print(f"  live pods on record: {len(pods)}")
    return EXIT_OK


def _pause(args: argparse.Namespace, paths: CampaignPaths) -> int:
    with CampaignQueue(paths.queue_db) as queue:
        paused = queue.pause_pending(model_key=args.model_key)
        queue.set_flag("queue_paused", "true")
        EventLog(paths.events_log).append(
            entity_kind="campaign",
            entity_id=CAMPAIGN_ID,
            to_state="BUDGET_PAUSED" if args.model_key is None else "QUEUED",
            reason="operator pause",
            detail={"paused_jobs": paused, "model_key": args.model_key},
        )
    print(f"paused {paused} pending job(s); in-flight pages continue to their checkpoint")
    return EXIT_OK


def _resume(args: argparse.Namespace, paths: CampaignPaths) -> int:
    with CampaignQueue(paths.queue_db) as queue:
        resumed = queue.resume_paused(model_key=args.model_key)
        queue.set_flag("queue_paused", "false")
        EventLog(paths.events_log).append(
            entity_kind="campaign",
            entity_id=CAMPAIGN_ID,
            to_state="RUNNING",
            reason="operator resume",
            detail={"resumed_jobs": resumed, "model_key": args.model_key},
        )
    print(f"resumed {resumed} paused job(s)")
    return EXIT_OK


def _drain(args: argparse.Namespace, paths: CampaignPaths) -> int:
    with CampaignQueue(paths.queue_db) as queue:
        workers = queue.workers(model_key=args.model_key)
        events = EventLog(paths.events_log)
        for worker in workers:
            if worker.state in {"TERMINATED", "DRAINING"}:
                continue
            if args.execute:
                queue.set_worker_state(worker.worker_id, "DRAINING")
            events.append(
                entity_kind="worker",
                entity_id=worker.worker_id,
                from_state=worker.state,
                to_state="DRAINING",
                reason="operator drain" + ("" if args.execute else " (dry run)"),
            )
            print(f"  {worker.worker_id}: {worker.state} -> DRAINING")
    if not args.execute:
        print("dry run: no /v1/drain call was made")
    return EXIT_OK


def _freeze(args: argparse.Namespace, paths: CampaignPaths) -> int:
    model_key = args.model_key
    if model_key is None:
        print("freeze needs --model", file=sys.stderr)
        return EXIT_REFUSED
    # D87: a manifest is what the scoring lane reads to decide these outputs
    # are final. Sealing a run that is still dispatching pages produces one
    # that a complete run cannot be told apart from.
    with CampaignQueue(paths.queue_db) as queue:
        raw_counts = dict(queue.counts_by_state(model_key=model_key))
    counts = {str(k): int(v) for k, v in raw_counts.items()}
    planned = sum(counts.values())
    # In flight, not "not successful". SUCCESS and QUARANTINED are the queue's
    # own terminal states, and a job resting in FAILED has spent the retries
    # D81 gives it -- all three have reached an answer this manifest can seal.
    # PAUSED is counted as in flight because it is waiting to be resumed.
    outstanding = sum(
        counts.get(state, 0) for state in ("PENDING", "ASSIGNED", "RUNNING", "PAUSED")
    )
    settled = planned - outstanding
    if outstanding > 0 and not getattr(args, "allow_incomplete", False):
        print(
            f"freeze refused for {model_key}: {outstanding} of {planned} page(s) have not "
            f"settled ({counts}). Wait for the run, or pass --allow-incomplete to seal a "
            f"partial manifest that says so (D87).",
            file=sys.stderr,
        )
        return EXIT_REFUSED
    revision: str | None = None
    digest: str | None = None
    try:
        entry = load_model_registry(paths.model_registry, model_key)
        revision, digest = entry.model_revision, entry.runtime_image_digest
    except PlanError:
        # Freezing does not require the registry; the marker records the gap.
        pass
    try:
        result = freeze_model(
            model_key,
            paths=paths,
            model_revision=revision,
            runtime_image_digest=digest,
            planned_count=planned,
            settled_count=settled,
        )
    except FreezeError as exc:
        print(f"freeze refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    if not result.frozen:
        print(f"freeze REFUSED for {model_key}: hashes do not match their files", file=sys.stderr)
        for mismatch in result.mismatches:
            print(
                f"  {mismatch.case_key} {mismatch.field_name}: receipt says "
                f"{mismatch.recorded}, file hashes to {mismatch.recomputed}",
                file=sys.stderr,
            )
        for missing in result.missing_files:
            print(f"  {missing}", file=sys.stderr)
        return EXIT_BLOCKED
    print(
        f"{model_key}: froze {result.sample_count} case(s) "
        f"({result.success_count} SUCCESS, {result.failed_count} not) -> "
        f"{result.manifest_sha256}"
    )
    return EXIT_OK


def _cleanup_verify(args: argparse.Namespace, paths: CampaignPaths) -> int:
    """D20: enumerate v1 **and** v2, delete every campaign pod, prove it worked.

    A dry run lists what it would delete and sends nothing. ``--execute``
    deletes and keeps re-reading both listings until no campaign pod is left;
    an ``EXITED`` pod is not cleaned up while its record is still there.
    """

    try:
        key = runpod_api_key(path=args.credentials)
    except SecretUnavailable as exc:
        print(f"cleanup-verify refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    receipts_dir = paths.provider_receipts_dir if args.execute else None
    client_v2 = make_v2_client(key=key, execute=bool(args.execute), receipts_dir=receipts_dir)
    client_v1 = make_v1_client(key=key, execute=bool(args.execute), receipts_dir=receipts_dir)
    try:
        if args.execute:
            result = clean_up_campaign(
                receipt_path=paths.cleanup_receipt,
                v2_client=client_v2,
                v1_client=client_v1,
                delete=True,
            )
        else:
            result = verify_cleanup(
                client_v2, receipt_path=paths.cleanup_receipt, v1_client=client_v1
            )
    finally:
        client_v1.close()
        client_v2.close()
    for note in result.notes:
        print(f"  {note}")
    for pod in result.remaining:
        print(
            f"  still listed: {pod.pod_id} {pod.name} status={pod.status} "
            f"api={pod.api_version} matched_by={pod.matched_by}"
        )
    if result.deleted:
        print(f"  deleted: {', '.join(result.deleted)}")
    for failure in result.delete_failures:
        print(f"  delete failed: {failure}", file=sys.stderr)
    print(
        f"cleanup verified={result.verified} after {result.attempts} attempt(s) "
        f"across {', '.join(result.apis_read) or 'no'} API listing(s); "
        f"receipt at {paths.cleanup_receipt}"
    )
    return EXIT_OK if result.verified else EXIT_BLOCKED


def _cost(args: argparse.Namespace, paths: CampaignPaths) -> int:
    rows: list[cost_module.PodLedgerRow] = []
    receipts: list[dict[str, object]] = []
    model_keys = _model_keys(args)
    for model_key in model_keys:
        receipt_dir = paths.receipt_dir(model_key)
        if not receipt_dir.is_dir():
            continue
        for path in sorted(receipt_dir.glob("*.json")):
            document = read_json(path)
            if isinstance(document, dict):
                receipts.append(document)

    useful = cost_module.useful_seconds_by_pod(receipts)
    retried = cost_module.retry_seconds_by_pod(receipts)
    with CampaignQueue(paths.queue_db) as queue:
        for pod in queue.pods():
            if args.model_key and pod.model_key != args.model_key:
                continue
            rows.append(
                cost_module.build_ledger_row(
                    pod,
                    useful_inference_seconds=useful.get(pod.pod_id, 0.0),
                    retry_seconds=retried.get(pod.pod_id, 0.0),
                )
            )
        successes = sum(
            queue.counts_by_state(model_key=model_key)["SUCCESS"] for model_key in model_keys
        )
        attempted = sum(
            sum(queue.counts_by_state(model_key=model_key).values()) for model_key in model_keys
        )

    for row in rows:
        write_json_atomic(
            paths.cost_dir / f"pod-{row.pod_id}.json", row.to_dict(), context="pod ledger row"
        )
    summary = cost_module.summarize(
        rows,
        successful_pages=successes,
        attempted_pages=attempted,
        model_key=args.model_key,
    )
    for line in summary.table_lines():
        print(line)
    for note in summary.notes:
        print(f"  note: {note}")
    write_json_atomic(
        paths.cost_dir / "campaign-cost.json", summary.to_dict(), context="campaign cost"
    )
    return EXIT_OK


def _model_keys(args: argparse.Namespace) -> tuple[str, ...]:
    if args.model_key:
        return (str(args.model_key),)
    return GPU_MODEL_KEYS
