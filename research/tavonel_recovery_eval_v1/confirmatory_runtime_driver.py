#!/usr/bin/env python3
"""Post-freeze, ground-truth-isolated runtime driver for TAVONEL-R Stage 1.

The GPU/model runners intentionally do not mount hidden evaluator truth.  This
module consumes only their sealed Markdown outputs plus production-visible peer
and trigger evidence, binds every page back to the frozen cohort, executes the
five prospectively declared primary arms, and writes immutable per-page receipts
before sealing the complete runtime output set.

It does *not* evaluate correctness.  Hidden evaluation is a separate later step.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from confirmatory_execution import PageRuntimeInputs, TriggerEvidence, execute_all_primary_arms
from recovery_protocol import PRIMARY_ARMS

HERE = Path(__file__).resolve().parent
DEFAULT_FREEZE = HERE / "receipts" / "confirmatory-freeze.json"
DEFAULT_RECEIPT_ROOT = HERE / "receipts" / "confirmatory-runtime"

SCHEMA = "tavonel.recovery.runtime_input_manifest.v1"
PAGE_SCHEMA = "tavonel.recovery.runtime_page_receipt.v1"
SEAL_SCHEMA = "tavonel.recovery.runtime_output_seal.v1"

_HIDDEN_KEY_MARKERS = (
    "ground_truth",
    "groundtruth",
    "evaluator",
    "evaluation_label",
    "reference_answer",
    "correctness",
    "accuracy",
    "p_value",
    "confidence_interval",
    "winner",
)
_TRIGGER_KEYS = frozenset(
    {
        "risk",
        "uncertainty",
        "native_or_source_text",
        "structural_failure",
        "critical_token_constraint_failure",
        "visual_round_trip_failure",
        "cross_page_failure",
        "strong_verified_by_independent_evidence",
    }
)
_ENTRY_KEYS = frozenset(
    {
        "selection_ordinal",
        "page_id",
        "benchmark_id",
        "source_sha256",
        "primary_markdown",
        "peer_text",
        "strong_markdown",
        "trigger",
        "primary_gpu_seconds",
        "strong_gpu_seconds",
        "primary_cost_usd",
        "strong_cost_usd",
    }
)
_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "freeze_digest",
        "cohort_manifest_sha256",
        "primary_attestation_sha256",
        "strong_attestation_sha256",
        "entries",
        "hidden_evaluation_mounted",
        "fresh_confirmatory_observation",
    }
)


class RuntimeDriverRefused(RuntimeError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeDriverRefused(f"{label} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeDriverRefused(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeDriverRefused(f"{label} must be a JSON object")
    return value


def _write_once(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise RuntimeDriverRefused(f"immutable runtime artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(raw)


def _reject_hidden_keys(value: Any, *, path: str = "runtime_manifest") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            folded = str(key).casefold()
            if any(marker in folded for marker in _HIDDEN_KEY_MARKERS):
                raise RuntimeDriverRefused(f"hidden evaluation-like field is forbidden at {path}.{key}")
            _reject_hidden_keys(nested, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_hidden_keys(nested, path=f"{path}[{index}]")


def _require_exact_keys(value: Mapping[str, Any], allowed: frozenset[str], *, label: str) -> None:
    extras = sorted(set(map(str, value)) - allowed)
    if extras:
        raise RuntimeDriverRefused(f"{label} contains undeclared fields: {extras}")


def _safe_artifact_path(root: Path, relative: str | None, *, label: str) -> Path | None:
    if relative in {None, ""}:
        return None
    candidate = Path(str(relative))
    if candidate.is_absolute() or ".." in candidate.parts:
        raise RuntimeDriverRefused(f"{label} must be a relative artifact path")
    resolved_root = root.resolve()
    resolved = (resolved_root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeDriverRefused(f"{label} escapes artifact root") from exc
    if not resolved.is_file():
        raise RuntimeDriverRefused(f"{label} artifact is missing: {relative}")
    return resolved


def _read_text(root: Path, relative: str | None, *, label: str) -> str | None:
    path = _safe_artifact_path(root, relative, label=label)
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeDriverRefused(f"{label} is not UTF-8 text") from exc


def _text_digest(text: str | None) -> str | None:
    if text is None:
        return None
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_freeze(path: Path = DEFAULT_FREEZE) -> dict[str, Any]:
    freeze = _load_object(path, label="confirmatory freeze")
    if freeze.get("schema") != "tavonel.recovery.confirmatory_freeze.v1":
        raise RuntimeDriverRefused("confirmatory freeze schema is unsupported")
    body = {key: value for key, value in freeze.items() if key != "freeze_digest"}
    if _digest(body) != freeze.get("freeze_digest"):
        raise RuntimeDriverRefused("confirmatory freeze digest does not recompute")
    if freeze.get("state") != "FROZEN":
        raise RuntimeDriverRefused("confirmatory protocol is not frozen")
    if freeze.get("fresh_outcomes_observed_before_freeze") is not False:
        raise RuntimeDriverRefused("freeze reports fresh outcome observation before freeze")
    if freeze.get("threshold_retuning_after_freeze") is not False:
        raise RuntimeDriverRefused("freeze permits or reports post-freeze threshold retuning")
    if freeze.get("oracle_primary_eligible") is not False:
        raise RuntimeDriverRefused("oracle is primary-eligible in freeze")
    return freeze


def _verify_cohort(path: Path, freeze: Mapping[str, Any]) -> dict[str, Any]:
    cohort = _load_object(path, label="fresh cohort")
    if _sha(path) != freeze.get("cohort_manifest_sha256"):
        raise RuntimeDriverRefused("cohort bytes differ from frozen cohort manifest")
    body = {key: value for key, value in cohort.items() if key != "cohort_seal_digest"}
    if _digest(body) != cohort.get("cohort_seal_digest"):
        raise RuntimeDriverRefused("cohort seal does not recompute")
    if cohort.get("cohort_seal_digest") != freeze.get("cohort_seal_digest"):
        raise RuntimeDriverRefused("cohort seal differs from frozen authority")
    entries = cohort.get("entries")
    if not isinstance(entries, list) or len(entries) != cohort.get("entry_count"):
        raise RuntimeDriverRefused("cohort entry count is malformed")
    if len({str(row.get("page_id")) for row in entries if isinstance(row, Mapping)}) != len(entries):
        raise RuntimeDriverRefused("cohort page identities are not unique")
    return cohort


def _verify_runtime_manifest(
    path: Path, freeze: Mapping[str, Any], cohort: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = _load_object(path, label="runtime input manifest")
    _reject_hidden_keys(manifest)
    _require_exact_keys(manifest, _TOP_LEVEL_KEYS, label="runtime input manifest")
    if manifest.get("schema") != SCHEMA:
        raise RuntimeDriverRefused("runtime input manifest schema is unsupported")
    if manifest.get("hidden_evaluation_mounted") is not False:
        raise RuntimeDriverRefused("runtime input manifest does not attest hidden-evaluation isolation")
    if manifest.get("fresh_confirmatory_observation") is not True:
        raise RuntimeDriverRefused("runtime manifest is not marked as fresh confirmatory runtime evidence")
    if manifest.get("freeze_digest") != freeze.get("freeze_digest"):
        raise RuntimeDriverRefused("runtime manifest belongs to a different freeze")
    if manifest.get("cohort_manifest_sha256") != freeze.get("cohort_manifest_sha256"):
        raise RuntimeDriverRefused("runtime manifest belongs to a different cohort")
    frozen_attestations = freeze.get("runtime_attestation_sha256")
    if not isinstance(frozen_attestations, Mapping):
        raise RuntimeDriverRefused("freeze lacks runtime attestation pins")
    if manifest.get("primary_attestation_sha256") != frozen_attestations.get("primary"):
        raise RuntimeDriverRefused("runtime manifest primary attestation pin drifted")
    if manifest.get("strong_attestation_sha256") != frozen_attestations.get("strong"):
        raise RuntimeDriverRefused("runtime manifest strong attestation pin drifted")

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise RuntimeDriverRefused("runtime input manifest entries must be a list")
    cohort_entries = cohort.get("entries", [])
    if len(entries) != len(cohort_entries):
        raise RuntimeDriverRefused("runtime input manifest does not cover the complete frozen cohort")
    by_page: dict[str, Mapping[str, Any]] = {}
    for row in entries:
        if not isinstance(row, Mapping):
            raise RuntimeDriverRefused("runtime input manifest contains a non-object page entry")
        _require_exact_keys(row, _ENTRY_KEYS, label="runtime page entry")
        page_id = str(row.get("page_id") or "")
        if not page_id or page_id in by_page:
            raise RuntimeDriverRefused("runtime input manifest page identities are missing or duplicated")
        trigger = row.get("trigger")
        if not isinstance(trigger, Mapping):
            raise RuntimeDriverRefused(f"runtime trigger evidence is missing for {page_id}")
        _require_exact_keys(trigger, _TRIGGER_KEYS, label=f"runtime trigger for {page_id}")
        by_page[page_id] = row

    for cohort_row in cohort_entries:
        if not isinstance(cohort_row, Mapping):
            raise RuntimeDriverRefused("cohort contains a non-object entry")
        page_id = str(cohort_row.get("page_id") or "")
        row = by_page.get(page_id)
        if row is None:
            raise RuntimeDriverRefused(f"runtime input is missing frozen page {page_id}")
        if int(row.get("selection_ordinal", -1)) != int(cohort_row.get("selection_ordinal", -2)):
            raise RuntimeDriverRefused(f"selection ordinal drifted for {page_id}")
        if str(row.get("source_sha256") or "") != str(cohort_row.get("source_sha256") or ""):
            raise RuntimeDriverRefused(f"source hash drifted for {page_id}")
    return manifest


def _trigger(value: Mapping[str, Any], *, peer_text: str | None) -> TriggerEvidence:
    native = value.get("native_or_source_text")
    if native not in {None, ""} and peer_text not in {None, ""} and str(native) != str(peer_text):
        raise RuntimeDriverRefused("trigger native/source text differs from separately bound peer text")
    return TriggerEvidence(
        risk=float(value.get("risk")),
        uncertainty=float(value.get("uncertainty")),
        native_or_source_text=None if native in {None, ""} else str(native),
        structural_failure=bool(value.get("structural_failure", False)),
        critical_token_constraint_failure=bool(
            value.get("critical_token_constraint_failure", False)
        ),
        visual_round_trip_failure=bool(value.get("visual_round_trip_failure", False)),
        cross_page_failure=bool(value.get("cross_page_failure", False)),
        strong_verified_by_independent_evidence=bool(
            value.get("strong_verified_by_independent_evidence", False)
        ),
    )


def _serialize_arm(output: Any) -> dict[str, Any]:
    value = asdict(output)
    value["arm"] = output.arm.value
    return value


def _verify_page_receipt(path: Path, *, expected_manifest_sha: str, expected_freeze: str) -> dict[str, Any]:
    value = _load_object(path, label="runtime page receipt")
    if value.get("schema") != PAGE_SCHEMA:
        raise RuntimeDriverRefused("runtime page receipt schema is unsupported")
    body = {key: item for key, item in value.items() if key != "page_receipt_digest"}
    if _digest(body) != value.get("page_receipt_digest"):
        raise RuntimeDriverRefused(f"runtime page receipt digest does not recompute: {path.name}")
    if value.get("runtime_manifest_sha256") != expected_manifest_sha:
        raise RuntimeDriverRefused("existing runtime page receipt belongs to another manifest")
    if value.get("freeze_digest") != expected_freeze:
        raise RuntimeDriverRefused("existing runtime page receipt belongs to another freeze")
    return value


def execute_runtime(
    *,
    cohort_path: Path,
    runtime_manifest_path: Path,
    artifact_root: Path,
    freeze_path: Path = DEFAULT_FREEZE,
    receipt_root: Path = DEFAULT_RECEIPT_ROOT,
) -> dict[str, Any]:
    freeze = verify_freeze(freeze_path)
    cohort = _verify_cohort(cohort_path, freeze)
    manifest = _verify_runtime_manifest(runtime_manifest_path, freeze, cohort)
    manifest_sha = _sha(runtime_manifest_path)
    page_root = receipt_root / "pages"
    page_root.mkdir(parents=True, exist_ok=True)

    by_page = {str(row["page_id"]): row for row in manifest["entries"]}
    page_receipts: list[dict[str, Any]] = []
    for cohort_row in sorted(cohort["entries"], key=lambda row: int(row["selection_ordinal"])):
        page_id = str(cohort_row["page_id"])
        row = by_page[page_id]
        receipt_path = page_root / f"{int(row['selection_ordinal']):04d}.json"
        if receipt_path.exists():
            existing = _verify_page_receipt(
                receipt_path,
                expected_manifest_sha=manifest_sha,
                expected_freeze=str(freeze["freeze_digest"]),
            )
            if existing.get("page_id") != page_id:
                raise RuntimeDriverRefused("existing page receipt ordinal maps to another page")
            page_receipts.append(existing)
            continue

        primary_text = _read_text(
            artifact_root, row.get("primary_markdown"), label=f"primary output {page_id}"
        )
        peer_text = _read_text(artifact_root, row.get("peer_text"), label=f"peer output {page_id}")
        strong_text = _read_text(
            artifact_root, row.get("strong_markdown"), label=f"strong output {page_id}"
        )
        trigger = _trigger(row["trigger"], peer_text=peer_text)
        inputs = PageRuntimeInputs(
            page_id=page_id,
            benchmark_id=str(row["benchmark_id"]),
            primary_text=primary_text,
            peer_text=peer_text,
            strong_text=strong_text,
            trigger=trigger,
            primary_gpu_seconds=float(row.get("primary_gpu_seconds", 0.0)),
            strong_gpu_seconds=float(row.get("strong_gpu_seconds", 0.0)),
            primary_cost_usd=float(row.get("primary_cost_usd", 0.0)),
            strong_cost_usd=float(row.get("strong_cost_usd", 0.0)),
        )
        outputs = execute_all_primary_arms(inputs)
        if tuple(output.arm for output in outputs) != tuple(PRIMARY_ARMS):
            raise RuntimeDriverRefused("runtime arm execution order differs from frozen primary arms")
        body = {
            "schema": PAGE_SCHEMA,
            "freeze_digest": freeze["freeze_digest"],
            "cohort_seal_digest": cohort["cohort_seal_digest"],
            "runtime_manifest_sha256": manifest_sha,
            "selection_ordinal": int(row["selection_ordinal"]),
            "page_id": page_id,
            "benchmark_id": str(row["benchmark_id"]),
            "source_sha256": str(row["source_sha256"]),
            "input_text_sha256": {
                "primary": _text_digest(primary_text),
                "peer": _text_digest(peer_text),
                "strong": _text_digest(strong_text),
            },
            "trigger": asdict(trigger),
            "runtime_cost_inputs": {
                "primary_gpu_seconds": inputs.primary_gpu_seconds,
                "strong_gpu_seconds": inputs.strong_gpu_seconds,
                "primary_cost_usd": inputs.primary_cost_usd,
                "strong_cost_usd": inputs.strong_cost_usd,
            },
            "arms": [_serialize_arm(output) for output in outputs],
            "hidden_evaluation_opened": False,
        }
        receipt = {**body, "page_receipt_digest": _digest(body)}
        _write_once(receipt_path, receipt)
        page_receipts.append(receipt)

    if len(page_receipts) != int(cohort["entry_count"]):
        raise RuntimeDriverRefused("runtime page receipts do not cover the full frozen cohort")
    final_path = receipt_root / "runtime-output-seal.json"
    final_body = {
        "schema": SEAL_SCHEMA,
        "state": "RUNTIME_OUTPUTS_SEALED",
        "freeze_digest": freeze["freeze_digest"],
        "cohort_seal_digest": cohort["cohort_seal_digest"],
        "runtime_manifest_sha256": manifest_sha,
        "page_count": len(page_receipts),
        "primary_arms": [arm.value for arm in PRIMARY_ARMS],
        "page_receipts": [
            {
                "selection_ordinal": int(receipt["selection_ordinal"]),
                "page_id": str(receipt["page_id"]),
                "page_receipt_digest": str(receipt["page_receipt_digest"]),
            }
            for receipt in sorted(page_receipts, key=lambda item: int(item["selection_ordinal"]))
        ],
        "hidden_evaluation_opened": False,
        "fresh_confirmatory_runtime_complete": True,
    }
    final = {**final_body, "runtime_output_seal_digest": _digest(final_body)}
    if final_path.exists():
        observed = verify_runtime_seal(final_path, receipt_root=receipt_root)
        if observed != final:
            raise RuntimeDriverRefused("existing runtime output seal differs from recomputed seal")
        return observed
    _write_once(final_path, final)
    return final


def verify_runtime_seal(
    path: Path | None = None, *, receipt_root: Path = DEFAULT_RECEIPT_ROOT
) -> dict[str, Any]:
    seal_path = path or (receipt_root / "runtime-output-seal.json")
    seal = _load_object(seal_path, label="runtime output seal")
    if seal.get("schema") != SEAL_SCHEMA or seal.get("state") != "RUNTIME_OUTPUTS_SEALED":
        raise RuntimeDriverRefused("runtime output seal state/schema is invalid")
    body = {key: value for key, value in seal.items() if key != "runtime_output_seal_digest"}
    if _digest(body) != seal.get("runtime_output_seal_digest"):
        raise RuntimeDriverRefused("runtime output seal digest does not recompute")
    if seal.get("hidden_evaluation_opened") is not False:
        raise RuntimeDriverRefused("runtime output seal reports hidden evaluation opened")
    pages = seal.get("page_receipts")
    if not isinstance(pages, list) or len(pages) != int(seal.get("page_count", -1)):
        raise RuntimeDriverRefused("runtime output seal page list is malformed")
    for item in pages:
        if not isinstance(item, Mapping):
            raise RuntimeDriverRefused("runtime output seal page entry is malformed")
        path = receipt_root / "pages" / f"{int(item['selection_ordinal']):04d}.json"
        receipt = _verify_page_receipt(
            path,
            expected_manifest_sha=str(seal["runtime_manifest_sha256"]),
            expected_freeze=str(seal["freeze_digest"]),
        )
        if receipt.get("page_receipt_digest") != item.get("page_receipt_digest"):
            raise RuntimeDriverRefused("runtime output seal page receipt digest drifted")
        if receipt.get("page_id") != item.get("page_id"):
            raise RuntimeDriverRefused("runtime output seal page identity drifted")
    return seal


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    execute = sub.add_parser("execute")
    execute.add_argument("--cohort", type=Path, required=True)
    execute.add_argument("--runtime-manifest", type=Path, required=True)
    execute.add_argument("--artifact-root", type=Path, required=True)
    execute.add_argument("--freeze", type=Path, default=DEFAULT_FREEZE)
    execute.add_argument("--receipt-root", type=Path, default=DEFAULT_RECEIPT_ROOT)
    verify = sub.add_parser("verify")
    verify.add_argument("--seal", type=Path)
    verify.add_argument("--receipt-root", type=Path, default=DEFAULT_RECEIPT_ROOT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        if args.command == "execute":
            value = execute_runtime(
                cohort_path=args.cohort,
                runtime_manifest_path=args.runtime_manifest,
                artifact_root=args.artifact_root,
                freeze_path=args.freeze,
                receipt_root=args.receipt_root,
            )
        else:
            value = verify_runtime_seal(args.seal, receipt_root=args.receipt_root)
    except RuntimeDriverRefused as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
