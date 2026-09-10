"""Evaluate already-spent Paddle native regions against frozen source targets.

This runtime-visible diagnostic opens no labels or scorer. It verifies only the
declared critical-token hashes and emits no source/model text or literal token.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akc_cir.critical_tokens import verify_critical_tokens
from akc_native_parsers.models import ParseContext
from akc_native_parsers.pdf_parser import parse_pdf_to_cir
from akc_router.region_recovery import project_source_bound_text_regions

TARGETS_SHA = "sha256:a508297876676ed9fae15fb666a33e8903cbf8cf6ebbea9abfbe7247f1270110"
FROZEN_MANIFEST_SHA = (
    "sha256:0fff25a57c1727905e877a5c9c3d5841cfe0534574701219242ecb9eaeb7692c"
)
MODEL_REVISION = "c5630abae1d940eafe0697512a0325494b02ab42"
RUNTIME_IMAGE = "bootstrap:sha256:06849dac601360301ae68d44b4b737c8bb549009579b00b6a04353b86294feda"


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_fingerprint(text: str) -> Counter[str]:
    report = verify_critical_tokens(text, "")
    result: Counter[str] = Counter()
    for mismatch in report.mismatches:
        key = "sha256:" + hashlib.sha256(
            f"{mismatch.kind.value}\x1f{mismatch.token}".encode()
        ).hexdigest()
        result[key] = mismatch.source_count
    return result


def normalized_bbox(raw: object, *, width: int, height: int) -> tuple[int, int, int, int] | None:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw)
        or width < 1
        or height < 1
    ):
        return None
    left, top, right, bottom = (float(value) for value in raw)
    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        return None
    result = (
        max(0, min(1000, math.floor(left / width * 1000))),
        max(0, min(1000, math.floor(top / height * 1000))),
        max(0, min(1000, math.ceil(right / width * 1000))),
        max(0, min(1000, math.ceil(bottom / height * 1000))),
    )
    return result if result[0] < result[2] and result[1] < result[3] else None


def containing_block(
    blocks: object,
    *,
    width: int,
    height: int,
    source_bbox: tuple[int, int, int, int],
) -> tuple[str, tuple[int, int, int, int]] | None:
    if not isinstance(blocks, list):
        return None
    center_x = (source_bbox[0] + source_bbox[2]) / 2
    center_y = (source_bbox[1] + source_bbox[3]) / 2
    candidates: list[tuple[int, str, tuple[int, int, int, int]]] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        content = block.get("block_content")
        bbox = normalized_bbox(block.get("block_bbox"), width=width, height=height)
        if not isinstance(content, str) or not content.strip() or bbox is None:
            continue
        if bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]:
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            candidates.append((area, content, bbox))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], text_digest(item[1])))
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1], candidates[0][2]


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    sources = args.sources.resolve(strict=True)
    targets_path = args.targets.resolve(strict=True)
    if digest(targets_path) != TARGETS_SHA:
        raise ValueError("PADDLE_REGION_TARGETS_MISMATCH")
    manifest_path = arena / "frozen_outputs/paddleocr_vl_1_6/manifest.jsonl"
    if digest(manifest_path) != FROZEN_MANIFEST_SHA:
        raise ValueError("PADDLE_FROZEN_MANIFEST_MISMATCH")
    manifest: dict[str, dict[str, Any]] = {}
    with manifest_path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            manifest[str(row["case_key"])] = row

    targets = [json.loads(line) for line in targets_path.read_text(encoding="utf-8").splitlines()]
    records: list[dict[str, object]] = []
    for target in targets:
        case_key = str(target["case_key"])
        frozen = manifest.get(case_key)
        record: dict[str, object] = {
            "case_key": case_key,
            "region_id": target["region_id"],
            "status": "unresolved",
        }
        if frozen is None or frozen.get("status") != "SUCCESS":
            record["reason"] = "PADDLE_FROZEN_OUTPUT_UNAVAILABLE"
            records.append(record)
            continue
        raw_path = (arena / str(frozen["raw_path"])).resolve(strict=True)
        receipt_path = arena / f"runs/paddleocr_vl_1_6/receipts/{case_key}.json"
        native_path = arena / f"runs/paddleocr_vl_1_6/raw/{case_key}.native.json"
        if digest(raw_path) != frozen["raw_sha256"] or digest(receipt_path) != frozen[
            "receipt_sha256"
        ]:
            raise ValueError("PADDLE_FROZEN_ARTIFACT_MISMATCH")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt.get("model_revision") != MODEL_REVISION
            or receipt.get("runtime_image_digest") != RUNTIME_IMAGE
            or receipt.get("status") != "SUCCESS"
        ):
            raise ValueError("PADDLE_RUNTIME_IDENTITY_MISMATCH")
        native = json.loads(native_path.read_text(encoding="utf-8"))
        raw_text = raw_path.read_text(encoding="utf-8")
        if native.get("page_markdown") != [raw_text]:
            raise ValueError("PADDLE_NATIVE_JSON_OUTPUT_MISMATCH")
        pages = native.get("pages")
        if not isinstance(pages, list) or len(pages) != 1 or not isinstance(pages[0], dict):
            record["reason"] = "PADDLE_NATIVE_PAGE_UNAVAILABLE"
            records.append(record)
            continue
        page = pages[0].get("res")
        if not isinstance(page, dict):
            record["reason"] = "PADDLE_NATIVE_PAGE_UNAVAILABLE"
            records.append(record)
            continue
        width, height = page.get("width"), page.get("height")
        if type(width) is not int or type(height) is not int:
            record["reason"] = "PADDLE_NATIVE_GEOMETRY_UNAVAILABLE"
            records.append(record)
            continue

        relative = Path(str(target["source_relative_path"]))
        source = (sources / "olmocr-bench" / relative).resolve(strict=True)
        data = source.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != target["source_sha256"]:
            raise ValueError("PADDLE_REGION_SOURCE_MISMATCH")
        document = parse_pdf_to_cir(
            filename=source.name,
            declared_mime="application/pdf",
            data=data,
            max_pages=128,
            context=ParseContext(
                tenant_id="paddle-region-reuse-development",
                document_id="region-" + hashlib.sha256(case_key.encode()).hexdigest()[:24],
                document_version_id=str(target["source_sha256"]),
                created_at=datetime(2026, 9, 10, tzinfo=UTC),
            ),
        )
        inventory = project_source_bound_text_regions(
            document,
            expected_source_sha256=str(target["source_sha256"]),
            representation_sha256=str(target["source_sha256"]),
        )
        source_region = next(
            (
                region
                for region in inventory.regions
                if region.binding.region_id == target["region_id"]
            ),
            None,
        )
        if source_region is None:
            raise ValueError("PADDLE_SOURCE_REGION_MISSING")
        source_fingerprint = token_fingerprint(source_region.witness.observation.text)
        target_hashes = target.get("critical_token_hashes")
        if not isinstance(target_hashes, list) or not all(
            isinstance(value, str) and value in source_fingerprint for value in target_hashes
        ):
            raise ValueError("PADDLE_TARGET_TOKEN_BINDING_MISMATCH")
        matched = containing_block(
            page.get("parsing_res_list"),
            width=width,
            height=height,
            source_bbox=source_region.binding.bbox1000,
        )
        if matched is None:
            record["reason"] = "PADDLE_CONTAINING_BLOCK_UNRESOLVED"
            records.append(record)
            continue
        model_text, model_bbox = matched
        model_fingerprint = token_fingerprint(model_text)
        exact = all(
            model_fingerprint[token_hash] == source_fingerprint[token_hash]
            for token_hash in target_hashes
        )
        record.update(
            status="verified_critical_region" if exact else "unresolved",
            reason=None if exact else "PADDLE_CRITICAL_TOKEN_MISMATCH",
            source_bbox1000=source_region.binding.bbox1000,
            matched_bbox1000=model_bbox,
            target_token_count=len(target_hashes),
            model_native_json_sha256=digest(native_path),
            model_region_text_sha256=text_digest(model_text),
            verification_scope="declared_critical_tokens_only",
        )
        records.append(record)

    output = args.output.resolve()
    if output.exists():
        raise ValueError("PADDLE_REGION_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    records_path = output / "RECORDS.jsonl"
    with records_path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    counts = Counter(str(record["status"]) for record in records)
    reasons = Counter(str(record.get("reason")) for record in records if record.get("reason"))
    result = {
        "targets": len(targets),
        "records": len(records),
        "status_counts": dict(sorted(counts.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "records_sha256": digest(records_path),
        "hidden_evaluation_visible": False,
        "verification_scope": "declared_critical_tokens_only",
        "quality_claim": False,
        "gpu_cost_usd": 0,
    }
    (output / "RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
