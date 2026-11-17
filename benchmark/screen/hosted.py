"""Hosted arm ``d10-hosted-arm-v1``: the door, the spend stop, submission, collection, resume.

CLI: ``python -m benchmark.screen.hosted {prepaid,dry,rehearsal,full,collect,score} ...``.
Exit codes: 0 done, 2 refused (a ``ContractError``; nothing further was sent), 3 pending
(a batch is not terminal yet: rerun ``collect``).

* **Door.** ``admit`` lets through only a dev document whose rights class is on
  ``HOSTED_RIGHTS`` (a code constant). The page-list builder calls it, and the Gemini submit
  and the Mistral call call it again for each page before any request is built.
* **Money.** Two ``AuthorizedSpendBudget``s, both rebuilt from the ledger on every start: the
  arm (cap 25, through ``Campaign``) and the prepaid Gemini credit (cap = the draw budget the
  lead records). Every reservation is made before the provider write it covers; a reservation
  larger than what is left is refused before any write; after ``campaign.stopped.v1`` nothing
  is submitted.
* **Resume.** Write-ahead: ``job.dispatch.intent.v1`` -> create -> ``job.dispatched.v1`` (before
  any poll) -> ``job.accepted.v1`` or ``hosted.job.terminal.v1``. A dispatched job is polled,
  never created again; an intent without a dispatch is looked up in the complete batch listing
  and adopted by its display name, or created once (``hosted.resubmit_after_absent.v1``).
* Hosted outputs are never gold and never training data; nothing here is publishable.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from benchmark.runners import base, gemini_api, mistral_ocr, vlm
from benchmark.runners.base import RunnerConfig, RunnerUnavailable, build_provider_payload
from benchmark.screen.campaign import Campaign, CampaignSpec, load_spec
from benchmark.screen.manifest import HoldoutGuard, verify
from benchmark.screen.run_screen import Candidate, _case, _write_once, run_screen
from benchmark.v6.contracts import ContractError, canonical_sha256
from benchmark.v6.ledger import EvidenceLedger
from infra.runpod.v6.authorized_budget import AuthorizedSpendBudget

HOSTED_RIGHTS = frozenset({"public_record", "permissive_licence", "synthetic"})
SPEC_PATH = Path(__file__).with_name("hosted-arm-v1.yaml")
READER_PATH = Path(__file__).with_name("critical_fields.py")
WORKTREE = Path(__file__).resolve().parents[2]
GEMINI, MISTRAL = gemini_api.PROVIDER, mistral_ocr.PROVIDER
PROVIDERS = (MISTRAL, GEMINI)
DISPLAY_PREFIX = "akc-d10h-"
# Batch states: the REST reference spells BATCH_STATE_*, the batch guide JOB_STATE_*.
SUCCEEDED = frozenset({"BATCH_STATE_SUCCEEDED", "JOB_STATE_SUCCEEDED"})
TERMINAL = SUCCEEDED | {
    f"{prefix}_STATE_{state}"
    for prefix in ("BATCH", "JOB")
    for state in ("FAILED", "CANCELLED", "EXPIRED")
}
PENDING = frozenset(
    {"BATCH_STATE_UNSPECIFIED", "BATCH_STATE_PENDING", "BATCH_STATE_RUNNING"}
    | {"JOB_STATE_PENDING", "JOB_STATE_RUNNING"}
)
# ponytail: one re-attempt per Mistral page is reserved; a second one needs the lead.
MISTRAL_ATTEMPTS_RESERVED = 2
PUBLICATION = {
    MISTRAL: {"publishable": False, "reason": "mistral_tos_6_1_b"},
    GEMINI: {"publishable": False, "reason": "§9 claims rule"},
}
RECEIPT_KEYS = (
    "schema",
    "campaign_id",
    "stage",
    "dry_run",
    "spec_sha256",
    "manifest_sha256",
    "git_sha",
    "reader_v1_sha256",
    "environment",
    "snapshots",
    "pins",
    "admitted",
    "refused_documents",
    "page_refusals",
    "pages",
    "chunks",
    "mistral_pages",
    "estimate",
    "budget_before",
    "budget_after",
    "jobs",
    "results",
    "ledger_terminal_sha256",
    "teardown",
    "credential_scan",
    "fake_records",
    "publication",
    "gold_eligible",
    "training_eligible",
)
_loads = json.loads  # the one parser of provider bytes here (tests make it raise)


class HostedPageRefused(ContractError):
    """A document that may not leave the machine for a hosted provider."""


def admit(doc: object) -> None:
    """The door: a dev document whose rights class is on the hosted allow-list, or a refusal."""
    name = doc.get("doc_id") if isinstance(doc, dict) else None
    if not isinstance(doc, dict) or doc.get("split") != "dev":
        raise HostedPageRefused(f"{name!r}: only a dev document may be sent (rule: split)")
    rights = doc.get("rights")
    rights_class = rights.get("rights_class") if isinstance(rights, dict) else None
    if not (isinstance(rights_class, str) and rights_class in HOSTED_RIGHTS):
        raise HostedPageRefused(
            f"{name!r}: rights class {rights_class!r} is not on the hosted list"
        )


# --- spec ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class HostedSpec:
    path: Path
    sha256: str
    campaign: CampaignSpec
    renderer_version: str
    gemini: Mapping[str, Any]
    mistral: Mapping[str, Any]
    gemini_config: Mapping[str, Any]
    mistral_config: Mapping[str, Any]

    def block(self, provider: str) -> Mapping[str, Any]:
        return self.gemini if provider == GEMINI else self.mistral

    def config(self, provider: str) -> Mapping[str, Any]:
        return self.gemini_config if provider == GEMINI else self.mistral_config

    def price(self, provider: str, name: str) -> Decimal:
        return Decimal(self.block(provider)["prices"][name]["value"])

    def endpoint(self, provider: str) -> str:
        block = self.block(provider)
        if provider == GEMINI:
            return f"{block['api_base']}/{block['api_version']}/models/{block['model']}"
        return f"{block['api_base']}/{block['api_version']}/ocr"


def _limit(block: Mapping[str, Any], value: str, documented: str) -> None:
    limits = block["limits"]
    have, doc = limits[value], limits[documented]
    if type(have) is not int or have <= 0:
        raise ContractError(f"{value} must be a positive integer")
    if doc is not None and have * 10 > doc * 8:
        raise ContractError(f"{value} is above 80 % of the documented limit")


def load_hosted_spec(path: Path = SPEC_PATH) -> HostedSpec:
    data = path.read_bytes()
    raw = yaml.safe_load(data)
    campaign = load_spec(path)
    hosted = raw.get("hosted")
    if not isinstance(hosted, dict) or set(hosted) != {GEMINI, MISTRAL}:
        raise ContractError("hosted block must name exactly gemini_api and mistral_ocr_4")
    gemini, mistral = hosted[GEMINI], hosted[MISTRAL]
    options = gemini["options"]
    try:  # the runners' own pins: an alias, a retired id or an unbounded option is refused
        gemini_config = gemini_api.config(
            model=gemini["model"],
            thinking_config=options["thinking_config"],
            media_resolution=options["media_resolution"],
        )
        mistral_config = mistral_ocr.config(model=mistral["model"])
    except RunnerUnavailable as exc:
        raise ContractError(f"hosted pin refused: {exc}") from exc
    if mistral["options"]:
        raise ContractError("mistral_ocr_4 takes no runner options")
    _limit(gemini, "inline_max_bytes", "inline_request_bytes_documented")
    _limit(gemini, "max_requests_per_batch", "max_requests_per_batch_documented")
    _limit(gemini, "max_concurrent_batches", "concurrent_batches_documented")
    _limit(mistral, "max_image_bytes", "image_bytes_documented")
    if type(gemini["input_tokens_bound"]) is not int or gemini["input_tokens_bound"] <= 0:
        raise ContractError("input_tokens_bound must be a positive integer")
    for block in (gemini, mistral):
        for price in block["prices"].values():
            if not isinstance(price["value"], str) or not Decimal(price["value"]).is_finite():
                raise ContractError("a price is a decimal string")
            for field in ("source_url", "snapshot_file", "snapshot_sha256", "retrieved_at"):
                if not isinstance(price.get(field), str) or not price[field]:
                    raise ContractError(f"price field {field} is missing")
    return HostedSpec(
        path=path,
        sha256="sha256:" + hashlib.sha256(data).hexdigest(),
        campaign=campaign,
        renderer_version=str(raw["renderer_version"]),
        gemini=gemini,
        mistral=mistral,
        gemini_config=gemini_config,
        mistral_config=mistral_config,
    )


def check_snapshots(spec: HostedSpec, snapshot_dir: Path) -> list[dict[str, Any]]:
    """Each pinned price: its snapshot exists, has the pinned sha256 and contains "$" + value."""
    rows = []
    for provider in PROVIDERS:
        for name, price in spec.block(provider)["prices"].items():
            path = snapshot_dir / price["snapshot_file"]
            if not path.is_file():
                raise ContractError(f"price snapshot missing for {provider}.{name}")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != price["snapshot_sha256"]:
                raise ContractError(f"price snapshot sha256 differs for {provider}.{name}")
            if ("$" + price["value"]).encode() not in data:
                raise ContractError(
                    f"pinned price {provider}.{name} does not occur in its snapshot"
                )
            rows.append({"provider": provider, "price": name, **price})
    return rows


def thinking_bound(spec: HostedSpec) -> int:
    """The numeric thought-token bound; a thinkingLevel has none and is costed at the maximum."""
    thinking = spec.gemini_config["generation"]["thinkingConfig"]
    return int(thinking.get("thinkingBudget", gemini_api.MAX_THINKING_BUDGET))


def page_worst_usd(spec: HostedSpec, provider: str) -> Decimal:
    if provider == MISTRAL:
        return spec.price(MISTRAL, "usd_per_1000_pages") / 1000
    out_tokens = gemini_api.GENERATION["maxOutputTokens"] + thinking_bound(spec)
    return (
        Decimal(spec.gemini["input_tokens_bound"]) * spec.price(GEMINI, "input_usd_per_1m_tokens")
        + Decimal(out_tokens) * spec.price(GEMINI, "output_usd_per_1m_tokens")
    ) / 1_000_000


def page_expected_usd(spec: HostedSpec, provider: str) -> Decimal:
    if provider == MISTRAL:
        return page_worst_usd(spec, MISTRAL)
    tokens = spec.gemini["expected_tokens_per_page"]
    return (
        Decimal(tokens["input"]) * spec.price(GEMINI, "input_usd_per_1m_tokens")
        + Decimal(tokens["output"]) * spec.price(GEMINI, "output_usd_per_1m_tokens")
    ) / 1_000_000


def gemini_usage_usd(spec: HostedSpec, usage: object) -> Decimal | None:
    """Prompt, candidate and thought tokens at the pinned batch prices; None if not reported."""
    if not isinstance(usage, dict):
        return None
    counts = [usage.get(k, 0) for k in ("promptTokenCount", "candidatesTokenCount")]
    counts.append(usage.get("thoughtsTokenCount", 0))
    if "promptTokenCount" not in usage or any(type(c) is not int or c < 0 for c in counts):
        return None
    return (
        Decimal(counts[0]) * spec.price(GEMINI, "input_usd_per_1m_tokens")
        + Decimal(counts[1] + counts[2]) * spec.price(GEMINI, "output_usd_per_1m_tokens")
    ) / 1_000_000


# --- environment ----------------------------------------------------------------------------


def _pdfium_version() -> str:
    import pypdfium2.version as pdfium_version  # type: ignore[import-untyped]

    return str(pdfium_version.PYPDFIUM_INFO)


def check_environment(
    root: Path,
    renderer_version: str,
    *,
    origin: Callable[[str], str | None] = lambda name: importlib.import_module(name).__file__,
    version: Callable[[], str] = _pdfium_version,
) -> dict[str, Any]:
    """akc_security, akc_quality and benchmark load from this worktree; pypdfium2 is the
    spec's renderer version. Each origin is recorded; a mismatch refuses the stage."""
    origins: dict[str, str] = {}
    for name in ("akc_security", "akc_quality", "benchmark"):
        file = origin(name)
        if not file or not Path(file).resolve().is_relative_to(root.resolve()):
            raise ContractError(f"{name} does not resolve inside the worktree: {file!r}")
        origins[name] = str(Path(file).resolve())
    found = version()
    if found != renderer_version:
        raise ContractError(f"pypdfium2 {found} is not the spec's renderer_version")
    return {"module_origins": origins, "renderer_version": found}


# --- pages ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Page:
    page_id: str
    doc: Mapping[str, Any]
    index: int

    @property
    def case(self) -> dict[str, Any]:
        return _case(dict(self.doc), self.index)

    @property
    def case_id(self) -> str:
        return str(self.case["benchmark_case_id"])


def page_list(docs: Iterable[Mapping[str, Any]]) -> tuple[list[Page], list[dict[str, str]]]:
    """The canonical admitted page list (sorted page_id) and the refused documents."""
    pages: list[Page] = []
    refused: list[dict[str, str]] = []
    for doc in docs:
        try:
            admit(doc)
        except HostedPageRefused as exc:
            refused.append({"doc_id": str(doc.get("doc_id")), "rule": str(exc)})
            continue
        pages += [Page(f"{doc['doc_id']}#{p}", doc, p) for p in range(int(doc["page_count"]))]
    return sorted(pages, key=lambda p: p.page_id), refused


def rehearsal_pages(pages: Sequence[Page]) -> list[Page]:
    """The first admitted page of three different strata in canonical order, with a Korean
    stratum among them when one is admitted."""
    firsts: dict[str, Page] = {}
    for page in pages:
        firsts.setdefault(str(page.doc["stratum"]), page)
    chosen = sorted(firsts.values(), key=lambda p: p.page_id)[:3]
    korean = [
        p for p in sorted(firsts.values(), key=lambda p: p.page_id) if p.doc["language"] == "ko"
    ]
    if korean and not any(p.doc["language"] == "ko" for p in chosen):
        chosen[-1] = korean[0]
    return sorted(chosen, key=lambda p: p.page_id)


def _render(page: Page, corpus_root: Path) -> tuple[dict[str, Any], str, bytes, Any]:
    payload = build_provider_payload(page.case, corpus_root=corpus_root)
    mime, image, render = vlm.page_image(payload)
    return payload, mime, image, render


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Chunk:
    key: str
    pages: tuple[dict[str, Any], ...]  # page_id, case_id, image_sha256, image_mime, request_sha256

    @property
    def display_name(self) -> str:
        return DISPLAY_PREFIX + self.key.removeprefix("sha256:")[:32]


def chunk_key(spec: HostedSpec, pages: Iterable[tuple[str, str]]) -> str:
    """Stable across input order; moves with the model, prompt, options and every image."""
    return canonical_sha256(
        {
            "campaign": spec.campaign.campaign_id,
            "provider": GEMINI,
            "model": spec.gemini["model"],
            "api_version": spec.gemini["api_version"],
            "config_sha256": vlm.config_sha256(dict(spec.gemini_config)),
            "pages": sorted([page_id, image_sha] for page_id, image_sha in pages),
        }
    )


def _entry(spec: HostedSpec, case_id: str, mime: str, image: bytes) -> dict[str, Any]:
    request = gemini_api.request_body(spec.gemini_config, mime, image)
    return {"request": request, "metadata": {"key": case_id}}


def plan_chunks(spec: HostedSpec, sized: Sequence[tuple[dict[str, Any], int]]) -> list[Chunk]:
    """Consecutive chunks of the canonical list within inline_max_bytes and the request cap."""
    limits = spec.gemini["limits"]
    overhead = len(gemini_api.batch_create_body(DISPLAY_PREFIX + "0" * 32, []))
    chunks: list[list[dict[str, Any]]] = [[]]
    used = overhead
    for info, size in sized:
        if overhead + size > limits["inline_max_bytes"]:
            raise ContractError(f"{info['page_id']}: one request is over the inline limit")
        full = len(chunks[-1]) >= limits["max_requests_per_batch"]
        if chunks[-1] and (full or used + size + 1 > limits["inline_max_bytes"]):
            chunks.append([])
            used = overhead
        chunks[-1].append(info)
        used += size + 1
    return [
        Chunk(chunk_key(spec, [(i["page_id"], i["image_sha256"]) for i in group]), tuple(group))
        for group in chunks
        if group
    ]


# --- ledger-backed arm ----------------------------------------------------------------------


class NoNetwork:
    """Teardown provider for a stage that makes no provider resource (prepaid, dry)."""

    def delete(self, resource_id: str) -> None:
        raise ContractError("a no-network stage has no provider resource to delete")

    def exists(self, resource_id: str) -> bool:
        raise ContractError("a no-network stage has no provider resource")

    def tagged_resource_ids(self, run_tag: str) -> Sequence[str]:
        return ()


def _rest(out: dict[str, Any]) -> tuple[int, bytes]:
    """The sealed result of a batch REST call; a credential in the response is a stop."""
    if "failure" in out:
        raise CredentialHit("a batch response carried a credential; withheld")
    return int(out["http_status"]), base64.b64decode(out["raw_b64"])


class CredentialHit(ContractError):
    pass


def _meta(op: Mapping[str, Any]) -> dict[str, Any]:
    meta = op.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _resource_id(name: str) -> str:
    """The campaign's resource id of a batch: its id without ``batches/`` (the campaign's
    resource-id alphabet has no slash)."""
    return gemini_api.job_name(name).removeprefix("batches/")


class GeminiBatches:
    """``CampaignProvider`` over Gemini batches: tagged = non-terminal ``akc-d10h-`` batches.
    Resource ids are bare batch ids (``_resource_id``)."""

    def __init__(self, allow_network: bool = True) -> None:
        self.allow_network = allow_network

    def list_all(self) -> list[dict[str, Any]]:
        """Every page of the listing; an incomplete listing raises."""
        operations: list[dict[str, Any]] = []
        token: str | None = None
        for _ in range(1000):
            status, raw = _rest(gemini_api.batch_list(token, allow_network=self.allow_network))
            if status != 200:
                raise RunnerUnavailable("batch listing did not answer 200")
            page = _loads(raw)
            found = page.get("operations", []) if isinstance(page, dict) else None
            if not isinstance(found, list):
                raise ContractError("batch listing is not a list of operations")
            operations += [op for op in found if isinstance(op, dict)]
            token = page.get("nextPageToken") or None
            if token is None:
                return operations
        raise ContractError("batch listing did not end")

    def tagged_resource_ids(self, run_tag: str) -> Sequence[str]:
        ids = []
        for op in self.list_all():
            meta = _meta(op)
            name = str(meta.get("displayName", ""))
            if name.startswith(DISPLAY_PREFIX) and meta.get("state") not in TERMINAL:
                ids.append(_resource_id(str(op.get("name"))))
        return ids

    def delete(self, resource_id: str) -> None:
        name = "batches/" + resource_id
        status, _ = _rest(gemini_api.batch_delete(name, allow_network=self.allow_network))
        if status != 200:
            raise RunnerUnavailable("batch delete did not answer 200")

    def exists(self, resource_id: str) -> bool:
        name = "batches/" + resource_id
        status, _ = _rest(gemini_api.batch_get(name, allow_network=self.allow_network))
        if status == 404:
            return False
        if status == 200:
            return True
        raise RunnerUnavailable("batch get answered neither 200 nor 404")


def _settle(budget: AuthorizedSpendBudget, key: str, amount: object) -> None:
    # an overspend is recorded by settle before it raises; the arm is stopped for it
    with contextlib.suppress(ContractError):
        budget.settle(allocation_id=key, actual_cost_usd=str(amount))


class Arm:
    def __init__(self, spec: HostedSpec, out: Path, provider: Any = None) -> None:
        self.spec, self.out = spec, out
        self.ledger = EvidenceLedger(
            out / "ledger.jsonl", cohort_id=spec.campaign.campaign_id, run_tag=spec.campaign.run_tag
        )
        self.campaign = Campaign(spec.campaign, self.ledger, provider)
        self.credit = self._credit_budget()

    def events(self, kind: str) -> list[Mapping[str, Any]]:
        return [e.payload for e in self.ledger.iter_type(kind)]

    def stop(self, reason: str, **detail: Any) -> None:
        self.ledger.append("campaign.stopped.v1", {"reason": reason, **detail})

    def _credit_budget(self) -> AuthorizedSpendBudget | None:
        records = self.events("hosted.credit.recorded.v1")
        if not records:
            return None
        budget = AuthorizedSpendBudget(
            campaign_id=self.spec.campaign.campaign_id + "-gemini-credit",
            hard_cap_usd=str(records[-1]["draw_usd"]),
        )
        for event in self.ledger.replay():
            payload = event.payload
            if payload.get("provider") != GEMINI:
                continue
            if event.event_type == "job.dispatch.intent.v1":
                budget.reserve(
                    allocation_id=str(payload["idempotency_key"]),
                    maximum_cost_usd=str(payload["reserved_usd"]),
                )
            elif event.event_type in ("job.accepted.v1", "hosted.job.terminal.v1"):
                _settle(budget, str(payload["idempotency_key"]), payload["actual_usd"])
        return budget

    def mistral_budget(self, stage: str) -> AuthorizedSpendBudget:
        reserved = [p for p in self.events("campaign.stage_reserved.v1") if p["stage"] == stage]
        if not reserved or Decimal(str(reserved[0]["reserved_usd"])) <= 0:
            raise ContractError(f"stage {stage} holds no reservation for Mistral calls")
        budget = AuthorizedSpendBudget(
            campaign_id=f"{self.spec.campaign.campaign_id}-{stage}-mistral",
            hard_cap_usd=str(reserved[0]["reserved_usd"]),
        )
        for event in self.ledger.replay():
            payload = event.payload
            if payload.get("provider") != MISTRAL or payload.get("stage") != stage:
                continue
            if event.event_type == "job.dispatch.intent.v1":
                budget.reserve(
                    allocation_id=str(payload["idempotency_key"]),
                    maximum_cost_usd=str(payload["reserved_usd"]),
                )
            elif event.event_type == "hosted.page.settled.v1":
                _settle(budget, str(payload["idempotency_key"]), payload["actual_usd"])
        return budget

    def ensure_reserved(self, stage: str, amount: Decimal) -> None:
        if not any(p["stage"] == stage for p in self.events("campaign.stage_reserved.v1")):
            self.campaign.reserve_stage(stage, amount)

    def require(self, stage: str) -> None:
        """Each predecessor's receipt: in the ledger and on disk, under this spec."""
        for needed in self.spec.campaign.stage(stage).requires:
            path = self.out / needed / "receipt.json"
            if not self.campaign.has_receipt(needed) or not path.is_file():
                raise ContractError(f"stage {stage} requires the {needed} stage receipt")
            if json.loads(path.read_bytes()).get("spec_sha256") != self.spec.sha256:
                raise ContractError(f"the {needed} receipt was written under another spec")


# --- Gemini: submit, poll, collect ----------------------------------------------------------


def _intents(arm: Arm, provider: str) -> dict[str, Mapping[str, Any]]:
    return {
        str(p["idempotency_key"]): p
        for p in arm.events("job.dispatch.intent.v1")
        if p.get("provider") == provider
    }


def _closed(arm: Arm) -> set[str]:
    keys = {str(p["idempotency_key"]) for p in arm.events("job.accepted.v1")}
    return keys | {str(p["idempotency_key"]) for p in arm.events("hosted.job.terminal.v1")}


def _dispatched(arm: Arm) -> dict[str, str]:
    return {
        str(p["idempotency_key"]): str(p["provider_job_id"])
        for p in arm.events("job.dispatched.v1")
    }


def _create(arm: Arm, chunk: Chunk, body: bytes) -> str | None:
    """One create call. Returns the job name, or None when the provider did not take it."""
    spec = arm.spec
    status, raw = _rest(gemini_api.batch_create(spec.gemini["model"], body, allow_network=True))
    if status == 429:
        raise RunnerUnavailable("batch create was rate-limited; rerun later")
    if status != 200:
        arm.ledger.append(
            "hosted.job.terminal.v1",
            {
                "idempotency_key": chunk.key,
                "provider": GEMINI,
                "state": f"CREATE_HTTP_{status}",
                "actual_usd": "0",
                "flagged": "create_refused_no_job",
            },
        )
        arm.stop("create_refused", http_status=status)
        return None
    try:
        return gemini_api.job_name(_loads(raw).get("name"))
    except Exception:
        arm.stop("create_response_unrecognised", idempotency_key=chunk.key)
        return None


def _dispatch(arm: Arm, chunk: Chunk, name: str, input_sha: str, **extra: Any) -> None:
    arm.ledger.append(
        "job.dispatched.v1",
        {
            "idempotency_key": chunk.key,
            "logical_work_id": f"{GEMINI}:{chunk.key}",
            "input_sha256": input_sha,
            "provider": GEMINI,
            "provider_job_id": name,
            **extra,
        },
    )


def _build_create(
    arm: Arm, chunk: Chunk, pages: Mapping[str, Page], corpus_root: Path
) -> tuple[bytes, str]:
    """Re-render the chunk's pages (each image must match the planned sha256) into the body."""
    entries = []
    for info in chunk.pages:
        page = pages[info["page_id"]]
        admit(page.doc)  # the door, before this page's request is built
        _, mime, image, _ = _render(page, corpus_root)
        if _sha(image) != info["image_sha256"]:
            raise ContractError(f"{page.page_id}: the page image changed since it was planned")
        entries.append(_entry(arm.spec, page.case_id, mime, image))
    body = gemini_api.batch_create_body(chunk.display_name, entries)
    return body, _sha(body)


def submit_chunk(
    arm: Arm, stage: str, chunk: Chunk, pages: Mapping[str, Page], corpus_root: Path
) -> None:
    if arm.campaign.stopped:
        raise ContractError("the arm is stopped; nothing is submitted")
    for info in chunk.pages:  # the door first: a list that skipped the builder stops here
        admit(pages[info["page_id"]].doc)
    if chunk.key in _dispatched(arm) or chunk.key in _closed(arm):
        return  # polled, never created again
    intent = _intents(arm, GEMINI).get(chunk.key)
    if intent is not None:  # crashed between intent and dispatch
        for op in GeminiBatches().list_all():
            if _meta(op).get("displayName") == chunk.display_name:
                found = gemini_api.job_name(op.get("name"))
                _dispatch(arm, chunk, found, str(intent["input_sha256"]), adopted=True)
                return
        body, request_sha = _build_create(arm, chunk, pages, corpus_root)
        if request_sha != intent["input_sha256"]:
            raise ContractError("the recreated request differs from its intent")
        arm.ledger.append(
            "hosted.resubmit_after_absent.v1",
            {"idempotency_key": chunk.key, "display_name": chunk.display_name},
        )
        created = _create(arm, chunk, body)
        if created is not None:
            _dispatch(arm, chunk, created, request_sha, resubmitted=True)
        return
    body, request_sha = _build_create(arm, chunk, pages, corpus_root)
    if arm.credit is None:
        raise ContractError("no prepaid credit is recorded; nothing paid runs")
    worst = page_worst_usd(arm.spec, GEMINI) * len(chunk.pages)
    arm.credit.reserve(allocation_id=chunk.key, maximum_cost_usd=worst)  # refused before any write
    arm.ledger.append(
        "job.dispatch.intent.v1",
        {
            "idempotency_key": chunk.key,
            "logical_work_id": f"{GEMINI}:{chunk.key}",
            "input_sha256": request_sha,
            "provider": GEMINI,
            "stage": stage,
            "display_name": chunk.display_name,
            "reserved_usd": str(worst),
            "pages": list(chunk.pages),
        },
    )
    created = _create(arm, chunk, body)
    if created is not None:
        _dispatch(arm, chunk, created, request_sha)


def _raw_dir(arm: Arm, stage: str) -> Path:
    return arm.out / stage / "raw" / "batches"


def _collected(arm: Arm, provider: str, case_id: str) -> Path:
    return arm.out / "collected" / provider / f"{case_id}.json"


def _store(path: Path, result: Mapping[str, Any]) -> None:
    data = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    _write_once(path, data.encode("utf-8"))


def _entries(op: Any) -> list[Any] | None:
    response = op.get("response") if isinstance(op, dict) else None
    outer = response.get("inlinedResponses") if isinstance(response, dict) else None
    inner = outer.get("inlinedResponses") if isinstance(outer, dict) else None
    return inner if isinstance(inner, list) else None


def _mapping(entries: list[Any] | None, sent: Sequence[str]) -> dict[str, tuple[int, Any]] | None:
    """Entries by the echoed metadata key; None unless every sent key comes back exactly once."""
    if entries is None or len(entries) != len(sent):
        return None
    mapped: dict[str, tuple[int, Any]] = {}
    for index, entry in enumerate(entries):
        meta = entry.get("metadata") if isinstance(entry, dict) else None
        key = meta.get("key") if isinstance(meta, dict) else None
        if not isinstance(key, str) or key in mapped or key not in sent:
            return None
        mapped[key] = (index, entry)
    return mapped


def _count(usage: object, key: str) -> int:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if type(value) is int else 0


def _entry_result(
    config: RunnerConfig,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    entry: Mapping[str, Any],
    entry_raw: bytes,
) -> Callable[[], dict[str, Any]]:
    """One batch entry as the sync path would answer it: an entry error is a failure row with
    its bytes kept; a response goes through the same ``vlm.finish`` as a sync call."""
    if "error" in entry or entry.get("response") is None:

        def failed() -> dict[str, Any]:
            kept = {
                **receipt,
                "http_status": None,
                "raw_response_sha256": hashlib.sha256(entry_raw).hexdigest(),
                "raw_response_b64": base64.b64encode(entry_raw).decode("ascii"),
            }
            return vlm.failure(config, payload, "batch_entry_error", kept)

        return failed
    extract = gemini_api._extract(config.model_revision)
    return lambda: vlm.finish(
        config, payload, receipt, 200, "application/json", entry_raw, 0.0, extract
    )


def _collect_job(arm: Arm, stage: str, intent: Mapping[str, Any], name: str, raw: bytes) -> None:
    """Terminal success: raw written once, then parsed, mapped and stored page by page."""
    spec = arm.spec
    key = str(intent["idempotency_key"])
    job_file = _raw_dir(arm, stage) / (name.removeprefix("batches/") + ".json")
    _write_once(job_file, raw)
    op = _loads(raw)
    sent = [str(p["case_id"]) for p in intent["pages"]]
    mapped = _mapping(_entries(op), sent)
    if mapped is None:
        arm.ledger.append("hosted.batch.mapping_failed.v1", {"idempotency_key": key, "job": name})
        arm.stop("mapping_failed", job=name)
        return
    model = spec.gemini["model"]
    config = RunnerConfig(GEMINI, model, spec.endpoint(GEMINI) + ":batchGenerateContent")
    receipt_base = {
        **spec.gemini_config,
        "config_sha256": vlm.config_sha256(dict(spec.gemini_config)),
        "model_revision": model,
        "endpoint": config.endpoint,
        "render": None,
    }
    total, flagged, stops = Decimal(0), [], set()
    for info in intent["pages"]:
        index, entry = mapped[str(info["case_id"])]
        payload = {"benchmark_case_id": info["case_id"]}
        receipt = {
            **receipt_base,
            "image_mime": info["image_mime"],
            "image_sha256": info["image_sha256"].removeprefix("sha256:"),
            "request_sha256": info["request_sha256"].removeprefix("sha256:"),
            "submission": {
                "mode": "batch",
                "job": name,
                "idempotency_key": key,
                "batch_raw_sha256": _sha(raw),
                "entry_index": index,
            },
        }
        response = entry.get("response")
        entry_raw = _canonical(entry if "error" in entry or response is None else response)
        result = base.seal(
            config, payload, _entry_result(config, payload, receipt, entry, entry_raw)
        )
        usage = response.get("usageMetadata") if isinstance(response, dict) else None
        cost = gemini_usage_usd(spec, usage)
        if cost is None:
            cost = page_worst_usd(spec, GEMINI)
            flagged.append(str(info["page_id"]))
        total += cost
        reason = (result.get("failure") or {}).get("reason")
        if reason in ("served_model_differs", base.CREDENTIAL_IN_RESULT):
            stops.add(str(reason))
        if _count(usage, "thoughtsTokenCount") > thinking_bound(spec):
            stops.add("thoughts_over_budget")
        if _count(usage, "promptTokenCount") > spec.gemini["input_tokens_bound"]:
            stops.add("prompt_tokens_over_bound")
        _store(_collected(arm, GEMINI, str(info["case_id"])), result)
    meta = op.get("metadata") if isinstance(op.get("metadata"), dict) else {}
    if meta.get("model") != f"models/{model}":
        stops.add("served_model_differs")
    arm.ledger.append(
        "job.accepted.v1",
        {
            "idempotency_key": key,
            "logical_work_id": f"{GEMINI}:{key}",
            "provider_job_id": name,
            "provider": GEMINI,
            "stage": stage,
            "actual_usd": str(total),
            "flagged_no_usage": flagged,
            "batch_raw_sha256": _sha(raw),
        },
    )
    if arm.credit is not None:
        _settle(arm.credit, key, total)
    if total > Decimal(str(intent["reserved_usd"])):
        stops.add("chunk_cost_over_reservation")
    for reason in sorted(stops):
        arm.stop(reason, job=name)


def poll(
    arm: Arm,
    stage: str,
    *,
    max_wait: float,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Poll this stage's open jobs until each is terminal or max_wait passes; returns how many
    are still pending. Every GET response is written under raw/batches before it is parsed."""
    started = clock()
    while True:
        intents = _intents(arm, GEMINI)
        open_jobs = [
            (intents[k], n)
            for k, n in _dispatched(arm).items()
            if k in intents and k not in _closed(arm) and intents[k].get("stage") == stage
        ]
        for intent, name in open_jobs:
            status, raw = _rest(gemini_api.batch_get(name, allow_network=True))
            snap = (
                _raw_dir(arm, stage) / name.removeprefix("batches/") / (_sha(raw)[7:23] + ".json")
            )
            _write_once(snap, raw)
            if status != 200:
                arm.stop("batch_get_failed", job=name, http_status=status)
                return len(open_jobs)
            op = _loads(raw)
            meta = op.get("metadata") if isinstance(op, dict) else None
            state = meta.get("state") if isinstance(meta, dict) else None
            arm.ledger.append(
                "hosted.job.polled.v1", {"job": name, "state": str(state), "raw_sha256": _sha(raw)}
            )
            if state in SUCCEEDED:
                if op.get("done") is True:  # otherwise: not complete yet, poll again
                    _collect_job(arm, stage, intent, name, raw)
            elif state in TERMINAL:
                arm.ledger.append(
                    "hosted.job.terminal.v1",
                    {
                        "idempotency_key": intent["idempotency_key"],
                        "provider": GEMINI,
                        "provider_job_id": name,
                        "state": str(state),
                        "actual_usd": str(intent["reserved_usd"]),
                        "flagged": "no_usage_reported_charged_worst_case",
                    },
                )
                if arm.credit is not None:
                    _settle(arm.credit, str(intent["idempotency_key"]), intent["reserved_usd"])
                arm.stop("job_not_succeeded", job=name, state=str(state))
            elif state not in PENDING:
                arm.stop("unknown_batch_state", job=name)
                return len(open_jobs)
        remaining = [
            k
            for k, _ in _dispatched(arm).items()
            if k in intents and k not in _closed(arm) and intents[k].get("stage") == stage
        ]
        if not remaining or clock() - started >= max_wait:
            return len(remaining)
        sleep(interval)


# --- Mistral: one synchronous call per page -------------------------------------------------


def settle_open_mistral(arm: Arm, stage: str) -> None:
    """An intent with no outcome at restart is settled at its worst case."""
    done = {str(p["idempotency_key"]) for p in arm.events("hosted.page.settled.v1")}
    for key, intent in _intents(arm, MISTRAL).items():
        if key not in done and intent.get("stage") == stage:
            arm.ledger.append(
                "hosted.page.settled.v1",
                {
                    "idempotency_key": key,
                    "provider": MISTRAL,
                    "stage": stage,
                    "actual_usd": str(intent["reserved_usd"]),
                    "outcome": "no_outcome_at_restart",
                    "flagged": True,
                },
            )


def call_mistral(
    arm: Arm,
    stage: str,
    page: Page,
    corpus_root: Path,
    *,
    call: Callable[..., dict[str, Any]] = mistral_ocr.run,
) -> None:
    if arm.campaign.stopped:
        raise ContractError("the arm is stopped; nothing is submitted")
    admit(page.doc)  # the door, before the request is built
    spec = arm.spec
    attempt = 1 + sum(
        1 for p in _intents(arm, MISTRAL).values() if p.get("page_id") == page.page_id
    )
    key = canonical_sha256(
        {
            "campaign": spec.campaign.campaign_id,
            "provider": MISTRAL,
            "model": spec.mistral["model"],
            "config_sha256": vlm.config_sha256(dict(spec.mistral_config)),
            "page_id": page.page_id,
            "attempt": attempt,
        }
    )
    worst = page_worst_usd(spec, MISTRAL)
    arm.mistral_budget(stage).reserve(allocation_id=key, maximum_cost_usd=worst)
    payload = build_provider_payload(page.case, corpus_root=corpus_root)
    arm.ledger.append(
        "job.dispatch.intent.v1",
        {
            "idempotency_key": key,
            "logical_work_id": f"{MISTRAL}:{page.page_id}:{attempt}",
            "input_sha256": canonical_sha256([payload["source"]["sha256"], page.index]),
            "provider": MISTRAL,
            "stage": stage,
            "page_id": page.page_id,
            "attempt": attempt,
            "reserved_usd": str(worst),
        },
    )
    outcome, actual, flagged = "result", worst, True
    try:
        result = call(
            payload,
            endpoint=spec.endpoint(MISTRAL),
            model=spec.mistral["model"],
            allow_network=True,
        )
    except vlm.PageRefused as exc:
        outcome, actual, flagged = f"page_refused:{exc.reason}", Decimal(0), False
        result = None
    except RunnerUnavailable:
        outcome = "unavailable"  # e.g. 429: nothing stored, retried as the next attempt
        result = None
    if result is not None:
        usage = (result.get("metrics") or {}).get("receipt", {}).get("usage", {})
        pages = usage.get("pages_processed") if isinstance(usage, dict) else None
        if type(pages) is int and pages >= 0:
            actual, flagged = (
                Decimal(pages) * spec.price(MISTRAL, "usd_per_1000_pages") / 1000,
                False,
            )
        _store(_collected(arm, MISTRAL, page.case_id), result)
    arm.ledger.append(
        "hosted.page.settled.v1",
        {
            "idempotency_key": key,
            "provider": MISTRAL,
            "stage": stage,
            "actual_usd": str(actual),
            "outcome": outcome,
            "flagged": flagged,
        },
    )
    reason = ((result or {}).get("failure") or {}).get("reason")
    if reason in ("served_model_differs", "malformed_response", base.CREDENTIAL_IN_RESULT) or (
        isinstance(reason, str) and reason.startswith("http_4") and reason != "http_429"
    ):
        arm.stop(f"mistral_{reason}", page_id=page.page_id)


# --- stages ---------------------------------------------------------------------------------


class DryTransport:
    """The dry stage's only transport: canned answers made in-process, never sent anywhere."""

    TEXT = "dry-run placeholder, not a provider result"

    def __call__(self, provider: str, model: str) -> bytes:
        if provider == GEMINI:
            body: dict[str, Any] = {
                "modelVersion": model,
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": self.TEXT}]}}
                ],
                "usageMetadata": {"promptTokenCount": 0, "candidatesTokenCount": 0},
            }
        else:
            body = {
                "model": model,
                "pages": [{"index": 0, "markdown": self.TEXT}],
                "usage_info": {"pages_processed": 1},
            }
        return _canonical(body)


def _require_real_transport() -> None:
    used = (vars(gemini_api)["request_bytes"], vars(vlm)["post_bytes"], base.request_bytes)
    for transport in used:
        if isinstance(transport, DryTransport):
            raise ContractError("a paid stage refuses the dry stage's fake transport")


def scan_credentials(arm: Arm, roots: Iterable[Path]) -> dict[str, Any]:
    """Every file under the roots through ``carries_credential``; only names are reported.
    A hit stops the arm and moves the file to quarantine/."""
    checked, hits = 0, []
    for root in roots:
        files = sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else [root]
        for path in (f for f in files if f.is_file()):
            checked += 1
            text = path.read_bytes().decode("utf-8", "replace")
            views = [text]
            with contextlib.suppress(ValueError, RecursionError, TypeError):
                views.append(base._result_text(json.loads(text)))
            if any(base.carries_credential(v) for v in views):
                target = arm.out / "quarantine" / path.relative_to(arm.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(path), str(target))
                hits.append(str(path.relative_to(arm.out)))
                print(f"credential found in {path.name}; moved to quarantine")
    if hits:
        arm.stop("credential_in_stage_file", files=hits)
    return {"files_checked": checked, "hits": hits}


def _git_sha() -> str | None:
    git = shutil.which("git")
    if git is None:
        return None
    try:
        out = subprocess.run(
            [git, "rev-parse", "HEAD"], cwd=WORKTREE, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _receipt(arm: Arm, stage: str, **values: Any) -> dict[str, Any]:
    unknown = set(values) - set(RECEIPT_KEYS)
    if unknown:
        raise ContractError(f"unknown receipt keys {sorted(unknown)}")
    receipt: dict[str, Any] = dict.fromkeys(RECEIPT_KEYS)
    receipt.update(
        schema="tavonel.hosted-arm-receipt.v1",
        campaign_id=arm.spec.campaign.campaign_id,
        stage=stage,
        dry_run=stage == "dry",
        spec_sha256=arm.spec.sha256,
        git_sha=_git_sha(),
        reader_v1_sha256=_sha(READER_PATH.read_bytes()),
        publication=PUBLICATION,
        gold_eligible=False,
        training_eligible=False,
        pins={
            provider: {
                "model": arm.spec.block(provider)["model"],
                "api_base": arm.spec.block(provider)["api_base"],
                "api_version": arm.spec.block(provider)["api_version"],
                "submission": arm.spec.block(provider)["submission"],
                "config": dict(arm.spec.config(provider)),
                "config_sha256": vlm.config_sha256(dict(arm.spec.config(provider))),
                "thinking_bound_tokens": thinking_bound(arm.spec) if provider == GEMINI else None,
            }
            for provider in PROVIDERS
        },
    )
    receipt.update(values)
    return receipt


def _write_receipt(arm: Arm, stage: str, receipt: Mapping[str, Any]) -> Path:
    path = arm.out / stage / "receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=1, sort_keys=True), "utf-8")
    return path


def _budgets(arm: Arm) -> dict[str, Any]:
    return {
        "arm": arm.campaign.budget.report(),
        "credit": arm.credit.report() if arm.credit is not None else None,
    }


def record_prepaid(
    spec: HostedSpec, out: Path, credit_usd: str, draw_usd: str, source: str
) -> Path:
    """Stage 0: the lead's USD value of the prepaid credit and the Gemini draw budget."""
    arm = Arm(spec, out, NoNetwork())
    credit, draw = Decimal(credit_usd), Decimal(draw_usd)
    if not (credit.is_finite() and draw.is_finite() and Decimal(0) < draw <= credit):
        raise ContractError("the draw budget must be positive and at most the credit")
    if not source.strip():
        raise ContractError("the credit's source is required")
    if arm.campaign.has_receipt("prepaid"):
        raise ContractError("the prepaid stage is already recorded")
    arm.ensure_reserved("prepaid", credit)
    if not arm.events("hosted.credit.recorded.v1"):
        arm.ledger.append(
            "hosted.credit.recorded.v1",
            {"credit_usd": str(credit), "draw_usd": str(draw), "source": source},
        )
    arm.campaign.complete_stage(
        "prepaid", actual_cost_usd=credit, partial_results={"source": source}, resource_ids=[]
    )
    arm = Arm(spec, out, NoNetwork())
    return _write_receipt(
        arm,
        "prepaid",
        _receipt(arm, "prepaid", budget_after=_budgets(arm), teardown="no_network_stage"),
    )


def _load_manifest(manifest_path: Path, corpus_root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    verify(manifest, corpus_root)
    return dict(manifest)


@dataclass
class Plan:
    pages: list[Page]
    refused: list[dict[str, str]]
    page_refusals: list[dict[str, str]]
    rendered: list[dict[str, Any]]
    chunks: list[Chunk]
    mistral_pages: list[Page]


def build_plan(spec: HostedSpec, pages: Sequence[Page], corpus_root: Path) -> Plan:
    """Render each page once: image sha256, the Gemini request entry and its size, the Mistral
    image size. A page that cannot become an image is a page refusal with its own reason."""
    rendered, refusals, sized, mistral = [], [], [], []
    limit = spec.mistral["limits"]["max_image_bytes"]
    for page in pages:
        try:
            _, mime, image, render = _render(page, corpus_root)
        except vlm.PageRefused as exc:
            refusals.append({"page_id": page.page_id, "provider": "both", "reason": exc.reason})
            continue
        entry = _entry(spec, page.case_id, mime, image)
        info = {
            "page_id": page.page_id,
            "case_id": page.case_id,
            "image_sha256": _sha(image),
            "image_mime": mime,
            "request_sha256": _sha(_canonical(entry["request"])),
        }
        rendered.append({**info, "render": render, "image_bytes": len(image)})
        sized.append((info, len(_canonical(entry))))
        if len(image) > limit:
            refusals.append(
                {"page_id": page.page_id, "provider": MISTRAL, "reason": "page_over_image_limit"}
            )
        else:
            mistral.append(page)
    limits = spec.gemini["limits"]
    room = limits["inline_max_bytes"] - len(
        gemini_api.batch_create_body(DISPLAY_PREFIX + "0" * 32, [])
    )
    fits = []
    for info, size in sized:
        if size <= room:
            fits.append((info, size))
        else:
            refusals.append(
                {"page_id": info["page_id"], "provider": GEMINI, "reason": "page_over_inline_limit"}
            )
    chunks = plan_chunks(spec, fits)
    if len(chunks) > limits["max_concurrent_batches"]:
        raise ContractError("the chunk plan exceeds the concurrent batch limit")
    return Plan(list(pages), [], refusals, rendered, chunks, mistral)


def _fake_records(arm: Arm, plan: Plan, out_dir: Path) -> dict[str, Any]:
    fake = DryTransport()
    count = 0
    for provider in PROVIDERS:
        model = arm.spec.block(provider)["model"]
        config = RunnerConfig(provider, model, None)
        extract = gemini_api._extract(model) if provider == GEMINI else mistral_ocr._extract(model)
        pages = [
            r
            for r in plan.rendered
            if provider == GEMINI or r["page_id"] in {p.page_id for p in plan.mistral_pages}
        ]
        for info in pages:
            payload = {"benchmark_case_id": info["case_id"]}
            receipt = {
                "config_sha256": vlm.config_sha256(dict(arm.spec.config(provider))),
                "dry_run": True,
            }
            result = vlm.finish(
                config,
                payload,
                receipt,
                200,
                "application/json",
                fake(provider, model),
                0.0,
                extract,
            )
            _store(out_dir / provider / f"{info['case_id']}.json", result)
            count += 1
    return {"count": count, "scored": False, "reason": "gold_missing", "text": DryTransport.TEXT}


def run_dry(
    spec: HostedSpec,
    out: Path,
    manifest_path: Path,
    corpus_root: Path,
    snapshot_dir: Path,
    *,
    environment: Callable[[], dict[str, Any]] | None = None,
) -> Path:
    for name in ("GEMINI_API_KEY", "MISTRAL_API_KEY"):
        if name in os.environ:
            raise ContractError(f"dry runs with no key; {name} is set")
    arm = Arm(spec, out, NoNetwork())
    arm.require("dry")
    env = (environment or (lambda: check_environment(WORKTREE, spec.renderer_version)))()
    snapshots = check_snapshots(spec, snapshot_dir)
    manifest = _load_manifest(manifest_path, corpus_root)
    pages, refused = page_list(manifest["documents"])
    if not pages:
        raise ContractError("0 admitted pages")
    plan = build_plan(spec, pages, corpus_root)
    plan.refused = refused
    estimate: dict[str, dict[str, Any]] = {
        provider: {
            "pages": len(plan.mistral_pages)
            if provider == MISTRAL
            else sum(len(c.pages) for c in plan.chunks),
            "worst_per_page_usd": str(page_worst_usd(spec, provider)),
            "expected_per_page_usd": str(page_expected_usd(spec, provider)),
        }
        for provider in PROVIDERS
    }
    for row in estimate.values():
        row["worst_usd"] = str(Decimal(row["worst_per_page_usd"]) * row["pages"])
        row["expected_usd"] = str(Decimal(row["expected_per_page_usd"]) * row["pages"])
    before = _budgets(arm)
    credit_left = arm.credit.remaining_usd if arm.credit is not None else Decimal(0)
    if Decimal(estimate[GEMINI]["worst_usd"]) > credit_left:
        raise ContractError("the Gemini worst case is above the credit left")
    full_cap = spec.campaign.stage("full").cap_usd
    mistral_reserve = Decimal(estimate[MISTRAL]["worst_usd"]) * MISTRAL_ATTEMPTS_RESERVED
    if mistral_reserve > min(arm.campaign.budget.remaining_usd, full_cap):
        raise ContractError("the Mistral worst case is above what the arm has left")
    fake = _fake_records(arm, plan, out / "dry" / "fake")
    arm.ensure_reserved("dry", Decimal(0))
    arm.campaign.complete_stage(
        "dry", actual_cost_usd=Decimal(0), partial_results={"pages": len(pages)}, resource_ids=[]
    )
    arm = Arm(spec, out, NoNetwork())
    receipt = _receipt(
        arm,
        "dry",
        manifest_sha256=manifest.get("manifest_sha256"),
        environment=env,
        snapshots=snapshots,
        admitted=_admitted_summary(pages),
        refused_documents=plan.refused,
        page_refusals=plan.page_refusals,
        pages=plan.rendered,
        chunks=[
            {"idempotency_key": c.key, "display_name": c.display_name, "requests": len(c.pages)}
            for c in plan.chunks
        ],
        mistral_pages=[p.page_id for p in plan.mistral_pages],
        estimate=estimate,
        budget_before=before,
        budget_after=_budgets(arm),
        ledger_terminal_sha256=arm.ledger.terminal_sha256(),
        teardown="no_network_stage",
        fake_records=fake,
    )
    return _write_receipt(arm, "dry", receipt)


def _admitted_summary(pages: Sequence[Page]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for page in pages:
        cell = f"{page.doc['rights']['rights_class']}|{page.doc['stratum']}|{page.doc['language']}"
        counts[cell] = counts.get(cell, 0) + 1
    ids = [p.page_id for p in pages]
    return {
        "page_ids": ids,
        "digest": canonical_sha256(ids),
        "count": len(ids),
        "by_rights_stratum_language": counts,
    }


def run_paid(
    spec: HostedSpec,
    out: Path,
    stage: str,
    manifest_path: Path,
    corpus_root: Path,
    snapshot_dir: Path,
    *,
    environment: Callable[[], dict[str, Any]] | None = None,
    max_wait: float = 600.0,
    interval: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
    mistral_call: Callable[..., dict[str, Any]] = mistral_ocr.run,
) -> int:
    """rehearsal or full (a rerun resumes; ``collect`` reruns the stage in progress)."""
    if stage not in ("rehearsal", "full"):
        raise ContractError(f"{stage} is not a paid stage")
    _require_real_transport()
    arm = Arm(spec, out, GeminiBatches())
    try:
        return _run_paid(
            arm,
            stage,
            manifest_path,
            corpus_root,
            snapshot_dir,
            environment=environment,
            max_wait=max_wait,
            interval=interval,
            sleep=sleep,
            mistral_call=mistral_call,
        )
    except CredentialHit:
        arm.stop("credential_in_response")
        raise


def _run_paid(
    arm: Arm,
    stage: str,
    manifest_path: Path,
    corpus_root: Path,
    snapshot_dir: Path,
    *,
    environment: Callable[[], dict[str, Any]] | None,
    max_wait: float,
    interval: float,
    sleep: Callable[[float], None],
    mistral_call: Callable[..., dict[str, Any]],
) -> int:
    spec, out = arm.spec, arm.out
    if arm.campaign.has_receipt(stage):
        raise ContractError(f"the {stage} stage is already complete")
    arm.require(stage)
    env = (environment or (lambda: check_environment(WORKTREE, spec.renderer_version)))()
    snapshots = check_snapshots(spec, snapshot_dir)
    manifest = _load_manifest(manifest_path, corpus_root)
    admitted, refused = page_list(manifest["documents"])
    dry_ids = set(json.loads((out / "dry" / "receipt.json").read_bytes())["mistral_pages"] or [])
    dry_ids |= {
        p["page_id"] for p in json.loads((out / "dry" / "receipt.json").read_bytes())["pages"]
    }
    chosen = rehearsal_pages(admitted) if stage == "rehearsal" else admitted
    if not {p.page_id for p in chosen} <= dry_ids:
        raise ContractError("the stage's pages are not a subset of the dry list")
    settle_open_mistral(arm, stage)
    open_pages = {
        str(i["page_id"])
        for k, p in _intents(arm, GEMINI).items()
        if k not in _closed(arm)
        for i in p["pages"]
    }
    todo_g = [
        p
        for p in chosen
        if not _collected(arm, GEMINI, p.case_id).exists() and p.page_id not in open_pages
    ]
    todo_m = [p for p in chosen if not _collected(arm, MISTRAL, p.case_id).exists()]
    before = _budgets(arm)
    reserve = page_worst_usd(spec, MISTRAL) * max(len(todo_m), 1) * MISTRAL_ATTEMPTS_RESERVED
    arm.ensure_reserved(stage, reserve)
    by_id = {p.page_id: p for p in admitted}
    for intent in [p for k, p in _intents(arm, GEMINI).items() if k not in _closed(arm)]:
        chunk = Chunk(str(intent["idempotency_key"]), tuple(intent["pages"]))
        submit_chunk(arm, str(intent["stage"]), chunk, by_id, corpus_root)
    plan = build_plan(spec, todo_g, corpus_root)
    for chunk in plan.chunks:
        submit_chunk(arm, stage, chunk, by_id, corpus_root)
    for page in todo_m:
        if arm.campaign.stopped:
            break
        call_mistral(arm, stage, page, corpus_root, call=mistral_call)
    pending = poll(arm, stage, max_wait=max_wait, interval=interval, sleep=sleep)
    if pending:
        return 3
    return _finish_stage(arm, stage, env, snapshots, manifest, refused, before)


def _finish_stage(
    arm: Arm,
    stage: str,
    env: dict[str, Any],
    snapshots: list[dict[str, Any]],
    manifest: Mapping[str, Any],
    refused: list[dict[str, str]],
    before: dict[str, Any],
) -> int:
    settled = [p for p in arm.events("hosted.page.settled.v1") if p.get("stage") == stage]
    actual = sum((Decimal(str(p["actual_usd"])) for p in settled), Decimal(0))
    jobs: list[dict[str, Any]] = [
        {"job": n, "idempotency_key": k}
        for k, n in _dispatched(arm).items()
        if _intents(arm, GEMINI).get(k, {}).get("stage") == stage
    ]
    arm.campaign.complete_stage(
        stage,
        actual_cost_usd=actual,
        partial_results={"mistral_attempts": len(settled), "gemini_jobs": len(jobs)},
        resource_ids=[_resource_id(j["job"]) for j in jobs],
    )
    teardown = [p for p in arm.events("campaign.teardown.v1") if p["stage"] == stage]
    timeline = arm.events("hosted.job.polled.v1")
    for job in jobs:
        job["states"] = [p["state"] for p in timeline if p["job"] == job["job"]]
    scan = scan_credentials(arm, [arm.out / stage, arm.out / "collected"])
    arm = Arm(arm.spec, arm.out, NoNetwork())
    receipt = _receipt(
        arm,
        stage,
        manifest_sha256=manifest.get("manifest_sha256"),
        environment=env,
        snapshots=snapshots,
        refused_documents=refused,
        jobs=jobs,
        results={
            "accepted": [p for p in arm.events("job.accepted.v1") if p.get("stage") == stage],
            "mistral": settled,
            "mistral_actual_usd": str(actual),
            "stops": arm.events("campaign.stopped.v1"),
        },
        budget_before=before,
        budget_after=_budgets(arm),
        ledger_terminal_sha256=arm.ledger.terminal_sha256(),
        teardown=teardown[-1] if teardown else None,
        credential_scan=scan,
    )
    path = _write_receipt(arm, stage, receipt)
    scan_credentials(arm, [path])  # the last step, in the same process
    return 0


def in_progress_stage(arm: Arm) -> str:
    for stage in ("rehearsal", "full"):
        reserved = any(p["stage"] == stage for p in arm.events("campaign.stage_reserved.v1"))
        if reserved and not arm.campaign.has_receipt(stage):
            return stage
    raise ContractError("no paid stage is in progress")


# --- score ----------------------------------------------------------------------------------


def hosted_candidate(spec: HostedSpec, provider: str) -> Candidate:
    block = spec.block(provider)
    options = (
        {k: block["options"][k] for k in ("thinking_config", "media_resolution")}
        if provider == GEMINI
        else {}
    )
    image_digest = canonical_sha256(
        {
            "provider": provider,
            "model": block["model"],
            "api_base": block["api_base"],
            "api_version": block["api_version"],
            "submission": block["submission"],
        }
    )
    return Candidate(
        str(block["candidate_id"]),
        provider,
        "",
        image_digest,
        vlm.config_sha256(dict(spec.config(provider))),
        model=str(block["model"]),
        runner_options=options,
    )


def collected_lookup(root: Path) -> Callable[[Candidate, dict[str, Any], Path], dict[str, Any]]:
    def lookup(candidate: Candidate, case: dict[str, Any], corpus_root: Path) -> dict[str, Any]:
        path = root / candidate.provider / f"{case['benchmark_case_id']}.json"
        if not path.is_file():
            raise RunnerUnavailable("page was never collected")
        result = json.loads(path.read_bytes())
        if not isinstance(result, dict):
            raise ContractError("a collected result is not an object")
        return result

    return lookup


def score(
    spec: HostedSpec,
    out: Path,
    manifest_path: Path,
    corpus_root: Path,
    gold: Mapping[str, dict[str, Any]],
    collected_root: Path | None = None,
) -> dict[str, Any]:
    """No network: run_screen over the admitted documents, reading collected results only.
    Records stay in the stage directory; they are never gold or training data."""
    manifest = _load_manifest(manifest_path, corpus_root)
    docs = []
    for doc in manifest["documents"]:
        try:
            admit(doc)
        except HostedPageRefused:
            continue
        docs.append(doc)
    guard = HoldoutGuard(
        {"documents": docs, "manifest_sha256": manifest["manifest_sha256"]},
        out / "score" / "holdout-access.log",
    )
    lookup = collected_lookup(collected_root or out / "collected")
    files = {}
    for provider in PROVIDERS:
        records = out / "score" / f"{provider}.jsonl"
        run_screen(
            guard=guard,
            split="dev",
            purpose="tune",
            candidate=hosted_candidate(spec, provider),
            corpus_root=corpus_root,
            gold=gold,
            raw_dir=out / "score" / "raw" / provider,
            records_path=records,
            call=lookup,
        )
        files[provider] = _sha(records.read_bytes())
    return {"records_sha256": files, "publication": PUBLICATION, "gold_eligible": False}


# --- CLI ------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="benchmark.screen.hosted")
    parser.add_argument(
        "stage", choices=["prepaid", "dry", "rehearsal", "full", "collect", "score"]
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=SPEC_PATH)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--snapshot-dir", type=Path)
    parser.add_argument("--gold", type=Path)
    parser.add_argument("--credit-usd")
    parser.add_argument("--draw-usd")
    parser.add_argument("--credit-source", default="")
    parser.add_argument("--max-wait", type=float, default=600.0)
    parser.add_argument("--interval", type=float, default=60.0)
    args = parser.parse_args(argv)
    try:
        spec = load_hosted_spec(args.spec)
        if args.stage == "prepaid":
            if args.credit_usd is None or args.draw_usd is None:
                raise ContractError("prepaid needs --credit-usd and --draw-usd")
            print(
                record_prepaid(spec, args.out, args.credit_usd, args.draw_usd, args.credit_source)
            )
            return 0
        if args.manifest is None or args.corpus_root is None:
            raise ContractError("--manifest and --corpus-root are required")
        if args.stage == "score":
            if args.gold is None:
                raise ContractError("score needs --gold")
            gold = json.loads(args.gold.read_text(encoding="utf-8"))
            result = score(spec, args.out, args.manifest, args.corpus_root, gold)
            _write_receipt(Arm(spec, args.out, NoNetwork()), "score", result)
            return 0
        if args.snapshot_dir is None:
            raise ContractError("--snapshot-dir is required")
        if args.stage == "dry":
            print(run_dry(spec, args.out, args.manifest, args.corpus_root, args.snapshot_dir))
            return 0
        stage = args.stage
        if stage == "collect":
            stage = in_progress_stage(Arm(spec, args.out, NoNetwork()))
        code = run_paid(
            spec,
            args.out,
            stage,
            args.manifest,
            args.corpus_root,
            args.snapshot_dir,
            max_wait=args.max_wait,
            interval=args.interval,
        )
        if code == 3:
            print("pending: rerun collect")
        return code
    except ContractError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
