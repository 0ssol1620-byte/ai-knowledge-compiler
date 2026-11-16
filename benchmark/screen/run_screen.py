"""Screen runner: paired, resumable, failure-preserving, immutable raw output.

Every page of the requested split yields exactly one record per candidate. A provider
failure or a schema failure is a record (``accepted=false``), never a skipped page:
``provider_unavailable`` (RunnerUnavailable), ``provider_error`` (any other exception the
candidate raised on the page) or ``contract_failed``. A provider exception also records its
type as ``provider_error_type`` (``module.QualName``, never the message, which may quote the
document); it is null when the call returned. A missing or changed source file is an
integrity violation and stops the run before any call.
Raw output is written once per (page, candidate, revision, image digest, config); the
same bytes are a cache hit, different bytes raise ``ImmutableOutputError``.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmark.evaluators.metrics import score_case
from benchmark.run_benchmark import parser_output_validator
from benchmark.runners.base import RunnerUnavailable, build_provider_payload
from benchmark.runners.native import run as run_native
from benchmark.runners.registry import EXTERNAL_RUNNERS
from benchmark.screen.critical_fields import gold_value, score_critical_fields
from benchmark.screen.manifest import HoldoutGuard
from benchmark.v6.contracts import ContractError, canonical_sha256, require_sha256

_REVISION = re.compile(r"^[0-9a-f]{40,64}$")
_REPO = Path(__file__).resolve().parents[2]
NATIVE = "native_document"


class ImmutableOutputError(RuntimeError):
    """Raw output for a key already exists with different bytes."""


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    provider: str
    revision: str
    image_digest: str
    config_sha256: str
    endpoint: str | None = None
    allow_network: bool = False

    def validate(self) -> None:
        if not self.candidate_id:
            raise ContractError("candidate_id is empty")
        if self.provider != NATIVE and self.provider not in EXTERNAL_RUNNERS:
            raise ContractError(f"unknown provider {self.provider!r}")
        if not _REVISION.fullmatch(self.revision):
            raise ContractError("candidate needs an exact 40-64 hex revision")
        require_sha256(self.image_digest, "image_digest")
        require_sha256(self.config_sha256, "config_sha256")


def _case(doc: dict[str, Any], page: int) -> dict[str, Any]:
    """Provider input built from the manifest only; gold is never read here."""
    page_id = f"{doc['doc_id']}#{page}"
    return {
        "benchmark_case_id": "page-" + hashlib.sha256(page_id.encode()).hexdigest()[:24],
        "page_index": page,
        "language": doc["language"],
        "document_class": doc["document_class"],
        "source": {
            "path": doc["doc_id"],
            "filename": doc["doc_id"],
            "content_type": mimetypes.guess_type(doc["doc_id"])[0] or "",
            "sha256": doc["source_sha256"].removeprefix("sha256:"),
        },
    }


def _call(candidate: Candidate, case: dict[str, Any], corpus_root: Path) -> dict[str, Any]:
    if candidate.provider == NATIVE:
        return run_native(case, corpus_root=corpus_root)
    payload = build_provider_payload(case, corpus_root=corpus_root)
    return EXTERNAL_RUNNERS[candidate.provider](
        payload,
        endpoint=candidate.endpoint,
        revision=candidate.revision,
        allow_network=candidate.allow_network,
    )


def _write_once(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ImmutableOutputError(f"{path.name}: raw output differs from the stored bytes")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _num(metrics: Any, key: str) -> float | None:
    v = metrics.get(key) if isinstance(metrics, dict) else None
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def run_screen(
    *,
    guard: HoldoutGuard,
    split: str,
    purpose: str,
    candidate: Candidate,
    corpus_root: Path,
    gold: Mapping[str, dict[str, Any]],
    raw_dir: Path,
    records_path: Path,
    frozen_recipe_sha256: str | None = None,
    call: Callable[[Candidate, dict[str, Any], Path], dict[str, Any]] = _call,
) -> list[dict[str, Any]]:
    """Run one candidate over a split; returns the latest record of every page.

    ``gold`` maps ``doc_id#page`` to the page ground truth (kept outside the repository).
    ``records_path`` is an append-only JSONL ledger: a rerun skips pages that already hold
    raw output (verifying its hash) and retries pages that failed before producing any.
    """
    candidate.validate()
    docs = guard.load(split, purpose, frozen_recipe_sha256)
    pages = [(d, p) for d in docs for p in range(d["page_count"])]
    missing = [f"{d['doc_id']}#{p}" for d, p in pages if f"{d['doc_id']}#{p}" not in gold]
    if missing:
        raise ContractError(f"gold missing for {len(missing)} page(s), first {missing[0]!r}")
    for d, p in pages:  # an unparseable gold field must stop the run before any paid call
        for f in gold[f"{d['doc_id']}#{p}"].get("critical_fields") or []:
            gold_value(f)
    for d in docs:  # integrity violation, not a page failure: stop before any call
        src = corpus_root / d["doc_id"]
        if not src.is_file() or _sha(src.read_bytes()) != d["source_sha256"]:
            raise ContractError(f"{d['doc_id']}: source missing or hash differs from manifest")
    validator = parser_output_validator(_REPO / "benchmark" / "manifest.yaml")
    ledger: dict[str, dict[str, Any]] = {}
    if records_path.is_file():
        for line in records_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                ledger[rec["record_key"]] = rec
    records_path.parent.mkdir(parents=True, exist_ok=True)
    out: list[dict[str, Any]] = []
    for doc, page in pages:
        page_id = f"{doc['doc_id']}#{page}"
        key = canonical_sha256(
            [
                page_id,
                candidate.candidate_id,
                candidate.revision,
                candidate.image_digest,
                candidate.config_sha256,
            ]
        )
        raw_path = raw_dir / (key.removeprefix("sha256:") + ".json")
        prior = ledger.get(key)
        if prior is not None and prior["raw_sha256"] is not None:
            if _sha(raw_path.read_bytes()) != prior["raw_sha256"]:
                raise ImmutableOutputError(f"{page_id}: raw output changed since it was recorded")
            out.append(prior)
            continue
        case = _case(doc, page)
        truth = gold[page_id]
        fields = truth.get("critical_fields") or []
        started = time.perf_counter()
        parsed: Any = None
        failures: list[str] = []
        raw_sha: str | None = None
        error_type: str | None = None
        data: bytes | None = None
        if raw_path.is_file():
            data = raw_path.read_bytes()
        else:
            try:
                result = call(candidate, case, corpus_root)
            except RunnerUnavailable as exc:
                failures = ["provider_unavailable"]  # operational: nothing came back
                error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
            except Exception as exc:
                # Any parser crash on hostile input is a page result. The source bytes were
                # verified above, so what is left is the candidate failing on this page
                # (e.g. pypdf PdfReadError on a malformed PDF). Local writes happen below,
                # outside this try, so a disk fault still propagates.
                failures = ["provider_error"]
                error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
            else:
                try:
                    data = (
                        json.dumps(
                            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                        )
                        + "\n"
                    ).encode()
                except (TypeError, ValueError):
                    failures = ["contract_failed"]  # semantic: the output cannot be recorded
        if data is not None:
            parsed = json.loads(data)
            _write_once(raw_path, data)  # a local write error propagates, never a record
            raw_sha = _sha(data)
        wall_ms = (time.perf_counter() - started) * 1000.0
        output: dict[str, Any] | None = None
        if raw_sha is not None:
            if (
                not isinstance(parsed, dict)
                or parsed.get("benchmark_case_id") != case["benchmark_case_id"]
                or any(validator.iter_errors(parsed))
            ):
                failures = ["contract_failed"]
            else:
                output = parsed
        crit = {"n": len(fields), "exact": 0, "accepted_errors": 0}
        metrics: dict[str, Any] = {}
        if output is not None:
            metrics, failures = score_case(truth, output, output.get("metrics"))
            score = score_critical_fields(fields, str(output.get("text") or ""))
            crit["exact"] = score.exact
            if not failures:
                crit["accepted_errors"] = score.n - score.exact
        runtime = output.get("metrics") if output else None
        latency = _num(runtime, "latency_ms")
        record = {
            "page_id": page_id,
            "doc_id": doc["doc_id"],
            "stratum": doc["stratum"],
            "split": split,
            "candidate_id": candidate.candidate_id,
            "revision": candidate.revision,
            "image_digest": candidate.image_digest,
            "config_sha256": candidate.config_sha256,
            "raw_sha256": raw_sha,
            "metrics": metrics,
            "critical": crit,
            "hard_failures": sorted(set(failures)),
            "provider_error_type": error_type,
            "accepted": output is not None and not failures,
            "gpu_seconds": _num(runtime, "gpu_seconds"),
            "provider_cost_usd": _num(runtime, "estimated_cost_usd"),
            "latency_ms": latency if latency is not None else wall_ms,
            "record_key": key,
        }
        with records_path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        out.append(record)
    return out
