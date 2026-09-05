"""Preflight: prove the campaign can reach its providers, and spend nothing.

This is the one command allowed to touch the network in this build phase, and
only for reads (ARENA_CONTRACT section 0):

- ``GET /v2/pods``        how many pods exist right now, and are any tagged for
                          this campaign already
- ``GET /v2/catalog/gpus`` the price snapshot every provisioning decision quotes
- ``GET /v2/billing/pods`` what the account has already spent in the window
- R2 ``head_bucket``      does the transport bucket exist, and may we see it

Creating a pod, a volume or a bucket is not preflight. Nothing here does it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from arena.constants import (
    BUDGET_HARD_CAP_USD,
    BUDGET_SOFT_CAP_USD,
    BUDGET_TARGET_USD,
    CAMPAIGN_ID,
    GPU_MODEL_KEYS,
)
from arena.controller import retry as retry_policy
from arena.controller.gpu_pools import (
    GpuPoolError,
    PoolValidation,
    latest_price_snapshot_path,
    load_price_snapshot,
    validate_pool,
)
from arena.controller.ids_local import ids_source
from arena.controller.paths import CampaignPaths
from arena.controller.runtime_spec import RuntimeSpecError, load_runtime_spec
from arena.provider.r2 import BUCKET_NAME, R2Client, R2Error
from arena.provider.runpod_pods import (
    BillingWindow,
    PriceSnapshot,
    ProviderReceipt,
    RunPodClientError,
    RunPodPodsClient,
)
from arena.provider.safety import (
    read_json,
    sha256_file,
    timestamp_slug,
    utc_now_iso,
    write_json_atomic,
)
from arena.provider.secrets import SecretUnavailable, r2_credentials, runpod_api_key

__all__ = [
    "PreflightReport",
    "PreflightSection",
    "RunConfigAgreement",
    "check_run_config",
    "run_preflight",
]

DEFAULT_BILLING_WINDOW: Final = BillingWindow(bucket_size="hour", last_n=24)


@dataclass(frozen=True, slots=True)
class PreflightSection:
    name: str
    ok: bool
    detail: Mapping[str, object] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "ok": self.ok,
            "detail": dict(self.detail),
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class PreflightReport:
    mode: str
    sections: tuple[PreflightSection, ...]
    checked_at: str
    receipt_path: Path | None = None

    @property
    def ok(self) -> bool:
        return all(section.ok for section in self.sections)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "tavonel.arena.preflight.v1",
            "campaign_id": CAMPAIGN_ID,
            "mode": self.mode,
            "checked_at": self.checked_at,
            "ok": self.ok,
            "ids_source": ids_source(),
            "retry_policy_source": retry_policy.policy_source(),
            "budget": {
                "target_usd": BUDGET_TARGET_USD,
                "soft_cap_usd": BUDGET_SOFT_CAP_USD,
                "hard_cap_usd": BUDGET_HARD_CAP_USD,
            },
            "sections": [section.to_dict() for section in self.sections],
            "secrets_withheld": True,
        }

    def lines(self) -> list[str]:
        rows = [f"preflight ({self.mode}) at {self.checked_at}: {'OK' if self.ok else 'BLOCKED'}"]
        for section in self.sections:
            marker = "ok  " if section.ok else "FAIL"
            rows.append(f"  [{marker}] {section.name}")
            for key, value in sorted(section.detail.items()):
                rows.append(f"          {key}: {value}")
            if section.error:
                rows.append(f"          error: {section.error}")
        return rows


def run_preflight(
    *,
    paths: CampaignPaths,
    execute: bool = False,
    credential_path: Path | None = None,
    billing_window: BillingWindow = DEFAULT_BILLING_WINDOW,
    r2_block: str = "account",
    write_receipt: bool = True,
) -> PreflightReport:
    """Read-only provider checks. Returns a report and writes a receipt."""

    paths.ensure()
    sections: list[PreflightSection] = []
    mode = "live" if execute else "dry_run"

    key = None
    snapshot: PriceSnapshot | None = None
    try:
        key = runpod_api_key(path=credential_path)
        sections.append(
            PreflightSection(
                name="runpod_credential",
                ok=True,
                detail={"source_label": key.label, "value_length": len(key)},
            )
        )
    except SecretUnavailable as exc:
        sections.append(PreflightSection(name="runpod_credential", ok=False, error=str(exc)))

    if key is not None:
        client = RunPodPodsClient(
            key=key,
            execute=execute,
            campaign_id=CAMPAIGN_ID,
            receipts_dir=paths.provider_receipts_dir if execute else None,
        )
        try:
            sections.append(_pods_section(client))
            catalog_section, snapshot = _catalog_section(client)
            sections.append(catalog_section)
            sections.append(_billing_section(client, billing_window))
        finally:
            client.close()

    sections.append(_gpu_pool_section(paths, snapshot))
    sections.append(_registry_agreement_section(paths))
    sections.append(_run_config_section(paths))
    sections.append(_r2_section(execute=execute, block=r2_block, credential_path=credential_path))

    report = PreflightReport(mode=mode, sections=tuple(sections), checked_at=utc_now_iso())
    if not write_receipt:
        return report
    path = paths.preflight_receipt(timestamp_slug())
    write_json_atomic(path, report.to_dict(), context="preflight receipt")
    return PreflightReport(
        mode=report.mode,
        sections=report.sections,
        checked_at=report.checked_at,
        receipt_path=path,
    )


def _pods_section(client: RunPodPodsClient) -> PreflightSection:
    try:
        listed = client.list_pods()
    except RunPodClientError as exc:
        return PreflightSection(name="runpod_pods", ok=False, error=str(exc))
    if isinstance(listed, ProviderReceipt):
        return PreflightSection(
            name="runpod_pods",
            ok=True,
            detail={"dry_run": True, "would_call": f"{listed.method} {listed.url}"},
        )
    campaign_pods = [pod for pod in listed if pod.campaign_id == CAMPAIGN_ID]
    live_campaign_pods = [pod for pod in campaign_pods if pod.is_live]
    return PreflightSection(
        name="runpod_pods",
        ok=True,
        detail={
            "pod_count": len(listed),
            "live_pod_count": sum(1 for pod in listed if pod.is_live),
            "campaign_pod_count": len(campaign_pods),
            "campaign_live_pod_count": len(live_campaign_pods),
            "campaign_live_pod_ids": [pod.pod_id for pod in live_campaign_pods],
        },
    )


def _catalog_section(
    client: RunPodPodsClient,
) -> tuple[PreflightSection, PriceSnapshot | None]:
    try:
        snapshot = client.catalog_gpus()
    except RunPodClientError as exc:
        return PreflightSection(name="runpod_catalog", ok=False, error=str(exc)), None
    if isinstance(snapshot, ProviderReceipt):
        return (
            PreflightSection(
                name="runpod_catalog",
                ok=True,
                detail={"dry_run": True, "would_call": f"{snapshot.method} {snapshot.url}"},
            ),
            None,
        )
    assert isinstance(snapshot, PriceSnapshot)
    # rate_for drops rows the tier does not price; the live catalog returns 0.0
    # for those, and a $0 "cheapest GPU" is a missing price, not a bargain.
    priced = snapshot.priced_rows("COMMUNITY")
    cheapest = min(priced, key=lambda row: row.rate_for("COMMUNITY") or 0.0, default=None)
    section = PreflightSection(
        name="runpod_catalog",
        ok=bool(snapshot.rows),
        detail={
            "row_count": len(snapshot.rows),
            "snapshot_sha256": snapshot.snapshot_sha256(),
            "snapshot_path": None if snapshot.path is None else snapshot.path.name,
            "community_priced_rows": len(priced),
            "cheapest_community_gpu": None if cheapest is None else cheapest.gpu_type_id,
            "cheapest_community_usd_per_hour": (
                None if cheapest is None else cheapest.rate_for("COMMUNITY")
            ),
            "unpriced_community_rows": len(snapshot.rows) - len(priced),
        },
        error=None if snapshot.rows else "the GPU catalog came back empty",
    )
    return section, snapshot


def _billing_section(client: RunPodPodsClient, window: BillingWindow) -> PreflightSection:
    """D11: account-wide 24 h spend as information, never as a gate.

    ``spent_usd`` for the budget watchdog stays campaign-tagged (the pod ledger
    and the campaign's own pods). This line exists so an operator can see what
    the whole account is doing before adding to it -- including spend this
    campaign did not cause, which is precisely why it must not gate anything.
    """

    try:
        billing = client.billing_pods(window)
    except RunPodClientError as exc:
        return PreflightSection(
            name="runpod_billing",
            ok=True,
            detail={
                "account_wide_last_24h": f"billing unavailable: {type(exc).__name__}",
                "gate": "informational only (ARENA_CONTRACT section 11 D11)",
            },
        )
    if isinstance(billing, ProviderReceipt):
        return PreflightSection(
            name="runpod_billing",
            ok=True,
            detail={"dry_run": True, "would_call": f"{billing.method} {billing.url}"},
        )
    return PreflightSection(
        name="runpod_billing",
        ok=True,
        detail={
            "window": f"lastN={window.last_n} bucketSize={window.bucket_size}",
            "record_count": billing.get("record_count"),
            "unique_pod_count": billing.get("unique_pod_count"),
            "account_wide_last_24h_usd": billing.get("total_amount_usd"),
            "gate": "informational only (ARENA_CONTRACT section 11 D11)",
        },
    )


def _gpu_pool_section(paths: CampaignPaths, snapshot: PriceSnapshot | None) -> PreflightSection:
    """D9: every ``gpu_pool_priority`` name must exist in the catalog."""

    if snapshot is None:
        path = latest_price_snapshot_path(paths.provider_receipts_dir)
        if path is None:
            return PreflightSection(
                name="gpu_pool_priority",
                ok=True,
                detail={
                    "validated": False,
                    "reason": (
                        "no catalog snapshot on disk; run `preflight --execute` once to "
                        "capture one, then GPU pools are validated (D9)"
                    ),
                },
            )
        try:
            snapshot = load_price_snapshot(path)
        except GpuPoolError as exc:
            return PreflightSection(name="gpu_pool_priority", ok=False, error=str(exc))

    validations: list[PoolValidation] = []
    unreadable: dict[str, str] = {}
    for model_key in GPU_MODEL_KEYS:
        try:
            runtime = load_runtime_spec(paths.runtime_json(model_key), model_key)
        except RuntimeSpecError as exc:
            unreadable[model_key] = str(exc)
            continue
        validations.append(validate_pool(model_key, runtime.gpu_pool_priority, snapshot))

    failing = [item for item in validations if not item.ok]
    return PreflightSection(
        name="gpu_pool_priority",
        ok=not failing and not unreadable,
        detail={
            "validated": True,
            "catalog_snapshot_sha256": snapshot.snapshot_sha256(),
            "models_checked": len(validations),
            "models_failing": [item.model_key for item in failing],
            "failures": [line for item in failing for line in item.failure_lines()],
            "unreadable_runtimes": unreadable,
        },
        error=(
            None
            if not failing and not unreadable
            else "one or more models name a GPU the catalog does not carry"
        ),
    )


def _registry_agreement_section(paths: CampaignPaths) -> PreflightSection:
    """D16: ``runtime.json`` owns the revision; the registry is a derived copy.

    Read only. This lane never edits ``model_registry.json`` -- lane R does --
    but it must refuse to spend on a model whose two descriptions of *which
    weights to load* disagree, because the pinned revision is an input to
    every ``inference_job_id`` and a mismatch means the pages that come back
    are attributed to a revision the pod never ran.

    The comparison itself is lane R's ``overlay_disagreements``: it owns both
    the regeneration and the field list, and a second implementation of "are
    these the same?" living here would drift in exactly the way that lets a
    mismatch through. A helper that cannot answer **fails** this section --
    an unanswered D16 check is not a passed one.
    """

    if not paths.model_registry.is_file():
        return PreflightSection(
            name="registry_agreement",
            ok=False,
            error=f"{paths.model_registry.name} is absent; lane R writes it (D16)",
        )
    document = read_json(paths.model_registry)

    rule = (
        "runtimes/<key>/runtime.json owns model_repo, model_revision, prompt_id and "
        "license.status; model_registry.json is derived (D16)"
    )
    fix = (
        "lane R regenerates model_registry.json from runtime.json "
        "(`python -m arena.registry resolve --offline`)"
    )
    source = "arena.registry.runtimes.overlay_disagreements"
    try:
        from arena.registry.runtimes import load_overlays, overlay_disagreements

        overlays = load_overlays(namespace_root=paths.root)
        lines = overlay_disagreements(
            document if isinstance(document, Mapping) else {}, overlays
        )
    except Exception as exc:
        return PreflightSection(
            name="registry_agreement",
            ok=False,
            detail={"rule": rule, "compared_by": source, "owner_of_the_fix": fix},
            error=(
                f"{source} could not compare the registry with the runtime files: "
                f"{type(exc).__name__}: {exc}. D16 is unanswered, which is not a pass."
            ),
        )

    return PreflightSection(
        name="registry_agreement",
        ok=not lines,
        detail={
            "rule": rule,
            "compared_by": source,
            "models_compared": len(overlays),
            "disagreements": list(lines),
            "owner_of_the_fix": fix,
        },
        error=(
            None
            if not lines
            else f"{len(lines)} registry/runtime disagreement(s); D16 fails preflight"
        ),
    )


@dataclass(frozen=True, slots=True)
class RunConfigAgreement:
    """What comparing a model's run-config hashes both ways found.

    ``disagreements`` and ``unreadable`` are separate because the two callers
    owe different answers. Preflight fails on either -- an unanswered D16/D17
    check is not a passed one. The ``canary`` gate refuses only on a
    disagreement: a missing ``runtime.json`` or registry is refused a few lines
    later by the provisioning gate, which names the file, and shouting first
    with a vaguer message would hide it.
    """

    model_key: str
    disagreements: tuple[str, ...] = ()
    unreadable: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.disagreements and not self.unreadable

    def lines(self) -> tuple[str, ...]:
        return self.unreadable + self.disagreements


def check_run_config(paths: CampaignPaths, model_key: str) -> RunConfigAgreement:
    """Recompute the three hashes a run request carries, both ways, for one model.

    The controller fills a ``RunRequest`` from ``model_registry.json``; the
    worker recomputes the same three values on the pod from
    ``runtimes/<key>/runtime.json``, ``prompt_registry/<prompt_id>.txt`` and the
    page bytes, and answers HTTP 422 to every page if any of them differs. On
    2026-09-03 that cost a rented RTX 4090 and produced no output at all, so the
    comparison happens here, before a pod is asked for:

    - ``inference_config_sha256`` -- the registry value against
      :func:`arena.worker.util.config_sha256` over runtime.json's
      ``inference_config``, which is the worker's own function over the
      worker's own object;
    - ``prompt_sha256`` -- the registry value against the bytes of the prompt
      file the worker will resolve, and against ``prompt_registry/sha256.json``;
    - ``source_sha256`` -- the spelling of every selected page's digest, which
      the worker rejects as ``INVALID_REQUEST`` before it compares anything.

    Returns human-readable lines. Empty means the two sides agree.
    """

    from arena.controller.canary import CanaryError, load_canary_selection
    from arena.controller.plan import (
        SHA256_REF_RE,
        PlanError,
        load_model_registry,
        load_source_manifest,
    )
    from arena.registry.errors import RegistryError
    from arena.registry.runtimes import build_overlay, load_prompt_sha256
    from arena.worker.util import config_sha256

    problems: list[str] = []
    try:
        entry = load_model_registry(
            paths.model_registry,
            model_key,
            # A bootstrap canary resolves this from the bundle receipt (D15);
            # it is not one of the hashes under test, so any valid digest does.
            runtime_image_digest="bootstrap:sha256:" + "0" * 64,
        )
    except (PlanError, OSError) as exc:
        return RunConfigAgreement(
            model_key, unreadable=(f"{model_key}: model_registry.json is not usable: {exc}",)
        )

    try:
        overlay = build_overlay(
            model_key,
            prompt_shas=load_prompt_sha256(paths.root),
            namespace_root=paths.root,
        )
    except (RegistryError, OSError, ValueError) as exc:
        return RunConfigAgreement(
            model_key,
            unreadable=(f"{model_key}: runtimes/{model_key}/runtime.json is not usable: {exc}",),
        )

    runtime_json = read_json(paths.runtime_json(model_key))
    config = runtime_json.get("inference_config") if isinstance(runtime_json, Mapping) else None
    recomputed_config = config_sha256(config) if isinstance(config, Mapping) else None
    if recomputed_config != entry.inference_config_sha256:
        problems.append(
            f"{model_key}.inference_config_sha256: registry "
            f"{entry.inference_config_sha256!r} != runtimes/{model_key}/runtime.json "
            f"inference_config {recomputed_config!r}. The worker computes the second and "
            "answers CONFIG_MISMATCH to every page."
        )

    prompt_file = paths.prompt_registry_dir / f"{entry.prompt_id}.txt"
    if not prompt_file.is_file():
        problems.append(f"{model_key}: {prompt_file} is missing (D17)")
    else:
        recomputed_prompt = sha256_file(prompt_file)
        if recomputed_prompt != entry.prompt_sha256:
            problems.append(
                f"{model_key}.prompt_sha256: registry {entry.prompt_sha256!r} != "
                f"{prompt_file.name} {recomputed_prompt!r}. The worker hashes the file and "
                "answers PROMPT_MISMATCH to every page."
            )
        if recomputed_prompt != overlay.prompt_sha256:
            problems.append(
                f"{model_key}.prompt_sha256: prompt_registry/sha256.json "
                f"{overlay.prompt_sha256!r} != {prompt_file.name} {recomputed_prompt!r}"
            )

    try:
        selection = load_canary_selection(paths.canary_selection, model_key)
    except (CanaryError, OSError):
        selection = ()
    if selection:
        try:
            by_case = {
                sample.case_key: sample
                for sample in load_source_manifest(paths.source_manifest)
            }
        except (PlanError, OSError) as exc:
            problems.append(f"{model_key}: source_manifest.jsonl is not readable: {exc}")
            by_case = {}
        for case_key in selection:
            sample = by_case.get(case_key)
            if sample is None:
                problems.append(f"{model_key}: selected page {case_key} is not in the manifest")
            elif not SHA256_REF_RE.fullmatch(sample.source_sha256):
                problems.append(
                    f"{model_key}: page {case_key} source_sha256 {sample.source_sha256!r} is "
                    "not 'sha256:<64 lowercase hex>'; the worker rejects it as INVALID_REQUEST"
                )
    return RunConfigAgreement(model_key, disagreements=tuple(problems))


def _run_config_section(paths: CampaignPaths) -> PreflightSection:
    """The D16/D17 hashes a run request carries, recomputed for every model."""

    results = [check_run_config(paths, model_key) for model_key in GPU_MODEL_KEYS]
    disagreements = [line for result in results for line in result.disagreements]
    unreadable = [line for result in results for line in result.unreadable]
    return PreflightSection(
        name="run_config_hashes",
        ok=not disagreements and not unreadable,
        detail={
            "rule": (
                "the inference_config_sha256, prompt_sha256 and source_sha256 the "
                "controller sends must be the values the worker recomputes on the pod"
            ),
            "models_checked": len(results),
            "disagreements": disagreements,
            "unreadable": unreadable,
        },
        error=(
            None
            if not disagreements and not unreadable
            else "; ".join(
                part
                for part in (
                    f"{len(disagreements)} run-config hash disagreement(s), "
                    "every page would come back HTTP 422"
                    if disagreements
                    else "",
                    f"{len(unreadable)} model(s) whose hashes could not be compared at all, "
                    "which is not a pass"
                    if unreadable
                    else "",
                )
                if part
            )
        ),
    )


def _r2_section(
    *, execute: bool, block: str, credential_path: Path | None
) -> PreflightSection:
    try:
        credentials = r2_credentials(block=block, path=credential_path)
    except SecretUnavailable as exc:
        return PreflightSection(name="r2_bucket", ok=False, error=str(exc))
    client = R2Client(credentials, bucket=BUCKET_NAME, execute=execute)
    try:
        receipt = client.preflight_access()
    except R2Error as exc:
        return PreflightSection(name="r2_bucket", ok=False, error=str(exc))
    state = receipt.detail.get("bucket_state")
    # "missing" is a legitimate preflight outcome: bucket creation is a founder
    # decision this phase does not make. It is reported, not repaired.
    ok = state in {"exists", "missing", None}
    return PreflightSection(
        name="r2_bucket",
        ok=ok,
        detail={
            "bucket": BUCKET_NAME,
            "endpoint_host": receipt.endpoint_host,
            "credential_block": block,
            "bucket_state": state,
            "mode": receipt.mode,
            "creation_gate": "bucket creation waits for the orchestrator's go",
        },
        error=None if ok else f"R2 bucket access state is {state!r}",
    )
