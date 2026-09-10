"""Freeze truth-free runtime identities and per-source route predictions."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import re
import sys
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pypdf import PdfReader

from .preflight_mixed_holdout import digest, load_json, load_jsonl

PAGE_LOCATOR = re.compile(r"^page:(\d+):bbox1000:0,0,1000,1000$")
MODEL_KEYS = ("mineru_vlm", "paddleocr_vl_1_6", "ovisocr2")
RUNTIME_ROOTS = (
    "packages/cir-python/src",
    "packages/contracts/python",
    "packages/native-parsers/src",
    "packages/router/src",
)
DEPENDENCIES = (
    "defusedxml",
    "openpyxl",
    "Pillow",
    "pydantic",
    "pypdf",
    "pypdfium2",
    "python-docx",
    "python-pptx",
)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _file_manifest(repo_root: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for relative_root in RUNTIME_ROOTS:
        root = repo_root / relative_root
        for path in sorted(root.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            relative = path.relative_to(repo_root).as_posix()
            rows.append({"path": relative, "sha256": digest(path.read_bytes())})
    if not rows:
        raise ValueError("NATIVE_RUNTIME_FILES_MISSING")
    return rows


def _source_contract() -> dict[str, Any]:
    return {
        "schema": "tavonel.router_mixed_source_contract.v1",
        "state": "FROZEN_PREOPEN",
        "unit_scope": "one selected source-bound target per manifest row",
        "authority": "official source bytes; model agreement is corroboration only",
        "failure": "missing, corrupt, unrenderable, unauthorized or unverified stays unresolved",
        "representations": {
            "native_structured": {
                "native_authority": True,
                "target": "whole source",
                "visual_required": False,
            },
            "born_digital_pdf_table": {
                "native_authority": True,
                "target": "frozen page full bbox1000",
                "visual_required": True,
            },
            "scanned_pdf": {
                "native_authority": False,
                "target": "frozen page full bbox1000",
                "visual_required": True,
            },
            "layout_heavy_pdf": {
                "native_authority": True,
                "target": "frozen page full bbox1000",
                "visual_required": True,
            },
            "office_korean_docx": {
                "native_authority": True,
                "target": "first meaningful document body child",
                "visual_required": True,
            },
            "office_korean_pptx": {
                "native_authority": True,
                "target": "first slide resolved through package relationships",
                "visual_required": True,
            },
            "office_korean_xlsx": {
                "native_authority": True,
                "target": "first worksheet resolved through package relationships",
                "visual_required": True,
            },
            "target_alignment_failure": {
                "native_authority": False,
                "target": "frozen geometry-selected page full bbox1000",
                "visual_required": True,
            },
        },
        "visual_execution_boundary": (
            "derive a raster from the frozen source and locator under an immutable render "
            "receipt; bind its digest in every worker request before model execution"
        ),
        "data_policy": "local_research_evaluation_no_redistribution",
    }


def _router_policy() -> dict[str, Any]:
    return {
        "schema": "tavonel.router_mixed_source_policy.v1",
        "state": "FROZEN_RESEARCH_CANDIDATE",
        "revision": "mixed-source-page-region-v1",
        "calibrated": False,
        "route_time_inputs": [
            "source class",
            "media type",
            "source size",
            "frozen locator",
            "native structural features",
        ],
        "forbidden_route_time_inputs": [
            "annotations",
            "expected values",
            "evaluator outputs",
            "model output quality",
        ],
        "acceptance": (
            "accept only a source-authority witness or independently corroborated declared "
            "scope; otherwise unresolved"
        ),
        "recovery": "source-bound target only; no inferred page or bbox",
        "parallelism": "only the primary and declared peer wave may run together",
        "class_routes": {
            "native_structured": {
                "primary": ["native"],
                "peer": [],
                "recovery": [],
            },
            "born_digital_pdf_table": {
                "primary": ["native", "paddleocr_vl_1_6"],
                "peer": ["mineru_vlm"],
                "recovery": ["ovisocr2"],
            },
            "scanned_pdf": {
                "primary": ["ovisocr2", "paddleocr_vl_1_6"],
                "peer": [],
                "recovery": ["mineru_vlm"],
            },
            "layout_heavy_pdf": {
                "primary": ["native", "ovisocr2"],
                "peer": [],
                "recovery": ["mineru_vlm", "paddleocr_vl_1_6"],
            },
            "office_korean_docx": {
                "primary": ["native", "ovisocr2"],
                "peer": [],
                "recovery": ["mineru_vlm", "paddleocr_vl_1_6"],
            },
            "office_korean_pptx": {
                "primary": ["native", "ovisocr2"],
                "peer": ["mineru_vlm"],
                "recovery": ["paddleocr_vl_1_6"],
            },
            "office_korean_xlsx": {
                "primary": ["native", "paddleocr_vl_1_6"],
                "peer": [],
                "recovery": ["mineru_vlm", "ovisocr2"],
            },
            "target_alignment_failure": {
                "primary": ["ovisocr2", "paddleocr_vl_1_6"],
                "peer": [],
                "recovery": ["mineru_vlm"],
            },
        },
        "dynamic_rules": [
            {
                "when": "PDF selected page embedded_text_chars < 50",
                "action": "remove native from the acceptance set",
            },
            {
                "when": "PDF selected page rotation is nonzero or aspect ratio >= 1.8",
                "action": "require two visual candidates before acceptance",
            },
            {
                "when": "OOXML package contains charts, drawings, media or embeddings",
                "action": "retain the declared visual peer or recovery lane",
            },
            {
                "when": "primary candidates disagree or any required output is missing",
                "action": "run declared recovery; unresolved if no independent corroboration",
            },
        ],
        "public_claim": False,
        "production_authority": False,
    }


def _evaluator() -> dict[str, Any]:
    return {
        "schema": "tavonel.router_mixed_source_evaluator.v1",
        "state": "FROZEN_PREOPEN",
        "primary": "silent_critical_loss_rate",
        "secondary": [
            "information_retention_rate",
            "correct_abstention",
            "unresolved_fraction",
            "route_regret",
            "raw_provider_cost_per_1000_units",
            "end_to_end_p50_ms",
            "end_to_end_p95_ms",
        ],
        "denominator": "all 96 selected units retained in every applicable arm",
        "missing_output": "failure",
        "accepted_wrong_or_missing_critical_item": "silent critical loss",
        "unresolved": "reported separately and never counted correct",
        "oracle": "diagnostic upper bound selected only after sealed evaluation",
        "catastrophic_failures": "reported individually",
        "public_claim": False,
    }


def _statistics() -> dict[str, Any]:
    return {
        "schema": "tavonel.router_mixed_source_statistics.v1",
        "state": "FROZEN_PREOPEN",
        "bootstrap": "paired source-family cluster bootstrap",
        "replicates": 5000,
        "seed": 20260910,
        "interval": "percentile_95",
        "comparisons": [
            "source_aware_page_region_router_vs_best_fixed_visual",
            "source_aware_page_region_router_vs_legacy_router",
            "source_aware_page_region_router_vs_native_only",
            "source_aware_page_region_router_vs_always_all_diagnostic",
        ],
        "promotion_primary": (
            "upper confidence bound for SCLR difference versus best fixed visual is < 0"
        ),
        "promotion_guardrails": [
            "no class has higher observed SCLR than best fixed visual",
            "all missing outputs remain in denominators",
            "cost and p95 are reported from exact execution receipts",
            "no production authority without a separate promotion decision",
        ],
    }


def _pdf_features(path: Path, locator: str) -> dict[str, Any]:
    match = PAGE_LOCATOR.fullmatch(locator)
    if match is None:
        raise ValueError("PDF_LOCATOR_INVALID")
    page_number = int(match.group(1))
    reader = PdfReader(str(path), strict=True)
    if page_number < 1 or page_number > len(reader.pages):
        raise ValueError("PDF_LOCATOR_OUT_OF_RANGE")
    page = reader.pages[page_number - 1]
    text = page.extract_text() or ""
    box = page.mediabox
    width = float(box.width)
    height = float(box.height)
    resources = page.get("/Resources") or {}
    xobjects = resources.get("/XObject") if hasattr(resources, "get") else None
    try:
        image_objects = len(xobjects.get_object()) if xobjects is not None else 0
    except Exception:
        image_objects = 0
    return {
        "page_number": page_number,
        "page_count": len(reader.pages),
        "embedded_text_chars": len(text),
        "rotation_degrees": int(page.get("/Rotate", 0) or 0) % 360,
        "width_pt": round(width, 3),
        "height_pt": round(height, 3),
        "aspect_ratio": round(max(width, height) / max(1.0, min(width, height)), 4),
        "image_objects": image_objects,
    }


def _ooxml_features(path: Path, locator: str) -> dict[str, Any]:
    if not locator.startswith("ooxml:"):
        raise ValueError("OOXML_LOCATOR_INVALID")
    member = locator.removeprefix("ooxml:").split("#", 1)[0]
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        try:
            selected_size = archive.getinfo(member).file_size
        except KeyError as exc:
            raise ValueError("OOXML_LOCATOR_MEMBER_MISSING") from exc
    return {
        "package_entries": len(names),
        "selected_part_bytes": selected_size,
        "media_parts": sum("/media/" in name for name in names),
        "chart_parts": sum("/charts/" in name for name in names),
        "drawing_parts": sum("/drawings/" in name for name in names),
        "embedding_parts": sum("/embeddings/" in name for name in names),
        "comment_parts": sum("comment" in name.lower() for name in names),
    }


def _route_plan(
    source_class: str,
    features: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    class_routes = policy["class_routes"]
    plan = dict(class_routes[source_class])
    reasons = [f"source_class:{source_class}"]
    primary = list(plan["primary"])
    peer = list(plan["peer"])
    recovery = list(plan["recovery"])
    if source_class.endswith("_pdf") or source_class == "target_alignment_failure":
        if int(features.get("embedded_text_chars", 0)) < 50 and "native" in primary:
            primary.remove("native")
            reasons.append("native_text_below_50")
        if int(features.get("rotation_degrees", 0)) != 0 or float(
            features.get("aspect_ratio", 1.0)
        ) >= 1.8:
            reasons.append("alignment_risk_requires_two_visual_candidates")
            for model in ("ovisocr2", "paddleocr_vl_1_6"):
                if model not in primary and model not in peer:
                    peer.append(model)
    if source_class.startswith("office_korean_") and any(
        int(features.get(name, 0)) > 0
        for name in ("media_parts", "chart_parts", "drawing_parts", "embedding_parts")
    ):
        reasons.append("ooxml_visual_parts_present")
    return {
        "policy_revision": policy["revision"],
        "calibrated": False,
        "visible_features": dict(features),
        "primary_wave": primary,
        "peer_wave": peer,
        "recovery_wave": recovery,
        "reason_codes": reasons,
        "stop": "accept_with_independent_evidence_or_unresolved",
        "diagnostic_arms": {
            "native_only": "execute native when the source contract allows it",
            "best_fixed_visual": "execute the frozen best fixed visual baseline",
            "legacy_router": "execute the frozen legacy policy",
            "always_all_diagnostic": list(MODEL_KEYS),
            "oracle_diagnostic": "select from completed outputs only after sealed evaluation",
        },
    }


def freeze(
    *,
    repo_root: Path,
    package_root: Path,
    source_root: Path,
    model_binding_path: Path,
) -> dict[str, str]:
    manifest_path = package_root / "SELECTED_SOURCE_MANIFEST.jsonl"
    manifest = load_jsonl(manifest_path)
    protocol_path = package_root / "MIXED_SOURCE_HOLDOUT_PROTOCOL.json"
    candidate_path = package_root / "FROZEN_CANDIDATE_INVENTORY.json"
    development_path = package_root / "DEVELOPMENT_OVERLAP_INVENTORY.json"
    policy_path = package_root / "ROUTER_POLICY.json"
    contract_path = package_root / "SOURCE_CONTRACT.json"
    evaluator_path = package_root / "EVALUATOR_CONFIG.json"
    statistics_path = package_root / "STATISTICS_CONFIG.json"
    native_runtime_path = package_root / "NATIVE_RUNTIME_BINDING.json"
    model_identity_path = package_root / "MODEL_IDENTITY_SOURCE.json"
    model_snapshot_path = package_root / "MODEL_SNAPSHOT_BINDING.json"
    predictions_path = package_root / "ROUTE_PREDICTIONS.jsonl"
    binding_path = package_root / "RUNTIME_BINDING.json"

    source_contract = _source_contract()
    router_policy = _router_policy()
    evaluator = _evaluator()
    statistics = _statistics()
    _write_json(contract_path, source_contract)
    _write_json(policy_path, router_policy)
    _write_json(evaluator_path, evaluator)
    _write_json(statistics_path, statistics)
    native_runtime = {
        "schema": "tavonel.router_native_runtime_binding.v1",
        "state": "FROZEN_PREOPEN",
        "python": sys.version,
        "dependencies": {
            name: importlib.metadata.version(name) for name in DEPENDENCIES
        },
        "files": _file_manifest(repo_root),
        "source_inspection": "metadata and structure only; extracted text is reduced to a count",
        "calibrated": False,
    }
    _write_json(native_runtime_path, native_runtime)

    prior_model_binding = load_json(model_binding_path)
    models = prior_model_binding.get("models")
    if not isinstance(models, Mapping) or set(models) != set(MODEL_KEYS):
        raise ValueError("MODEL_BINDING_PORTFOLIO_INVALID")
    bound_models = {}
    for key in MODEL_KEYS:
        model = models[key]
        if not isinstance(model, Mapping):
            raise ValueError(f"{key}:MODEL_BINDING_INVALID")
        bound_models[key] = {
            "model_revision": model["model_revision"],
            "runtime_sha256": model["runtime_json_sha256"],
            "bundle_sha256": model["bundle_sha256"],
            "inference_config_sha256": model["inference_config_sha256"],
        }
    _write_json(
        model_identity_path,
        {
            "schema": "tavonel.router_model_identity_source.v1",
            "state": "FROZEN_PREOPEN",
            "provenance_sha256": digest(model_binding_path.read_bytes()),
            "models": bound_models,
        },
    )
    model_snapshot = load_json(model_snapshot_path)
    snapshot_models = model_snapshot.get("models")
    if (
        model_snapshot.get("schema")
        != "tavonel.router_model_snapshot_binding.v1"
        or not isinstance(snapshot_models, Mapping)
        or set(snapshot_models) != set(bound_models)
        or any(
            not isinstance(snapshot_models[key], Mapping)
            or snapshot_models[key].get("revision")
            != bound_models[key]["model_revision"]
            for key in bound_models
        )
    ):
        raise ValueError("MODEL_SNAPSHOT_BINDING_INVALID")

    policy_hash = digest(policy_path.read_bytes())
    prediction_rows = []
    for row in manifest:
        unit_id = str(row["unit_id"])
        source = source_root / (unit_id.replace(":", "_") + ".source")
        if digest(source.read_bytes()) != row["source_sha256"]:
            raise ValueError(f"{unit_id}:SOURCE_DIGEST_MISMATCH")
        source_class = str(row["source_class"])
        if row["media_type"] == "application/pdf":
            features = _pdf_features(source, str(row["target_locator"]))
        elif source_class.startswith("office_korean_"):
            features = _ooxml_features(source, str(row["target_locator"]))
        else:
            features = {
                "media_type": row["media_type"],
                "source_size_bytes": row["source_size_bytes"],
                "target": "whole_source",
            }
        prediction_rows.append(
            {
                "unit_id": unit_id,
                "source_sha256": row["source_sha256"],
                "router_policy_sha256": policy_hash,
                "route_plan": _route_plan(source_class, features, router_policy),
            }
        )
    predictions_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in prediction_rows
        ),
        encoding="utf-8",
    )

    allowed_hosts = sorted(
        {str(urlparse(str(row["source_url"])).hostname).lower() for row in manifest}
    )
    binding = {
        "schema": "tavonel.router_mixed_source_holdout_binding.v1",
        "benchmark_id": "TAVONEL-ROUTER-MIXED-SOURCE-HOLDOUT-20260910-V1",
        "state": "FROZEN_PREOPEN",
        "protocol_sha256": digest(protocol_path.read_bytes()),
        "candidate_inventory_sha256": digest(candidate_path.read_bytes()),
        "source_manifest_sha256": digest(manifest_path.read_bytes()),
        "development_inventory_sha256": digest(development_path.read_bytes()),
        "prediction_manifest_sha256": digest(predictions_path.read_bytes()),
        "preflight_sha256": digest((package_root / "preflight_mixed_holdout.py").read_bytes()),
        "freeze_generator_sha256": digest(Path(__file__).read_bytes()),
        "native_runtime_sha256": digest(native_runtime_path.read_bytes()),
        "source_contract_sha256": digest(contract_path.read_bytes()),
        "router_policy_sha256": policy_hash,
        "evaluator_sha256": digest(evaluator_path.read_bytes()),
        "statistics_sha256": digest(statistics_path.read_bytes()),
        "model_identity_source_sha256": digest(model_binding_path.read_bytes()),
        "model_snapshot_binding_sha256": digest(model_snapshot_path.read_bytes()),
        "models": bound_models,
        "allowed_source_hosts": allowed_hosts,
        "predictions_frozen": True,
        "input_manifest_contains_truth": False,
        "model_calls": 0,
        "new_gpu_spend_usd": 0,
        "public_claim": False,
        "production_promotion": False,
    }
    binding["model_identity_source_sha256"] = digest(model_identity_path.read_bytes())
    binding["artifact_paths"] = {
        "freeze_generator": Path(__file__).name,
        "native_runtime": native_runtime_path.name,
        "source_contract": contract_path.name,
        "router_policy": policy_path.name,
        "evaluator": evaluator_path.name,
        "statistics": statistics_path.name,
        "model_identity_source": model_identity_path.name,
        "model_snapshot_binding": model_snapshot_path.name,
    }
    _write_json(binding_path, binding)
    return {
        "native_runtime_sha256": str(binding["native_runtime_sha256"]),
        "router_policy_sha256": policy_hash,
        "prediction_manifest_sha256": str(binding["prediction_manifest_sha256"]),
        "runtime_binding_sha256": digest(binding_path.read_bytes()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--model-binding", type=Path, required=True)
    args = parser.parse_args(argv)
    result = freeze(
        repo_root=args.repo_root,
        package_root=args.package_root,
        source_root=args.source_root,
        model_binding_path=args.model_binding,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
