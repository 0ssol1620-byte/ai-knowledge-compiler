"""Verify stored Paddle blocks for frozen ParseBench table regions."""

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

EXPECTED_TARGETS = "sha256:1c55470e8a21c96e583dc3289a332c18125faf63115d5bec85b96c0e3c14bb79"
EXPECTED_MANIFEST = (
    "sha256:0fff25a57c1727905e877a5c9c3d5841cfe0534574701219242ecb9eaeb7692c"
)
MODEL_REVISION = "c5630abae1d940eafe0697512a0325494b02ab42"
RUNTIME_IMAGE = "bootstrap:sha256:06849dac601360301ae68d44b4b737c8bb549009579b00b6a04353b86294feda"
MODEL = "paddleocr_vl_1_6"
EXPECTED_TARGET_COUNT = 4


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def token_fingerprint(text: str) -> Counter[str]:
    report = verify_critical_tokens(text, "")
    return Counter(
        {
            "sha256:"
            + hashlib.sha256(
                f"{item.kind.value}\x1f{item.token}".encode()
            ).hexdigest(): item.source_count
            for item in report.mismatches
        }
    )


def normalized_bbox(
    raw: object, *, width: int, height: int
) -> tuple[int, int, int, int] | None:
    if (
        not isinstance(raw, list)
        or len(raw) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in raw)
        or width < 1
        or height < 1
    ):
        return None
    values = tuple(float(value) for value in raw)
    if not all(math.isfinite(value) for value in values):
        return None
    left, top, right, bottom = values
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
        if not isinstance(block, dict) or not isinstance(block.get("block_content"), str):
            continue
        content = str(block["block_content"])
        bbox = normalized_bbox(block.get("block_bbox"), width=width, height=height)
        if not content.strip() or bbox is None:
            continue
        if bbox[0] <= center_x <= bbox[2] and bbox[1] <= center_y <= bbox[3]:
            area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
            candidates.append((area, content, bbox))
    candidates.sort(key=lambda item: (item[0], text_digest(item[1])))
    if not candidates or (
        len(candidates) > 1 and candidates[0][0] == candidates[1][0]
    ):
        return None
    return candidates[0][1], candidates[0][2]


def run(args: argparse.Namespace) -> None:
    arena = args.arena.resolve(strict=True)
    sources = args.sources.resolve(strict=True)
    targets_path = args.targets.resolve(strict=True)
    if digest(targets_path) != EXPECTED_TARGETS:
        raise ValueError("PARSEBENCH_TABLE_TARGETS_MISMATCH")
    targets = [
        json.loads(line) for line in targets_path.read_text(encoding="utf-8").splitlines()
    ]
    if len(targets) != EXPECTED_TARGET_COUNT:
        raise ValueError("PARSEBENCH_TABLE_TARGET_DENOMINATOR_MISMATCH")
    manifest_path = arena / f"frozen_outputs/{MODEL}/manifest.jsonl"
    if digest(manifest_path) != EXPECTED_MANIFEST:
        raise ValueError("PARSEBENCH_TABLE_PADDLE_MANIFEST_MISMATCH")
    manifest = {
        str(row["case_key"]): row
        for row in (
            json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines()
        )
    }

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
        receipt_path = arena / f"runs/{MODEL}/receipts/{case_key}.json"
        native_path = arena / f"runs/{MODEL}/raw/{case_key}.native.json"
        if (
            digest(raw_path) != frozen["raw_sha256"]
            or digest(receipt_path) != frozen["receipt_sha256"]
        ):
            raise ValueError("PARSEBENCH_TABLE_PADDLE_ARTIFACT_MISMATCH")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt.get("model_revision") != MODEL_REVISION
            or receipt.get("runtime_image_digest") != RUNTIME_IMAGE
            or receipt.get("status") != "SUCCESS"
        ):
            raise ValueError("PARSEBENCH_TABLE_PADDLE_RUNTIME_MISMATCH")
        native = json.loads(native_path.read_text(encoding="utf-8"))
        raw_text = raw_path.read_text(encoding="utf-8")
        if native.get("page_markdown") != [raw_text]:
            raise ValueError("PARSEBENCH_TABLE_PADDLE_NATIVE_BINDING_MISMATCH")
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
        source = (sources / "parsebench" / relative).resolve(strict=True)
        data = source.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != target["source_sha256"]:
            raise ValueError("PARSEBENCH_TABLE_SOURCE_MISMATCH")
        document = parse_pdf_to_cir(
            filename=source.name,
            declared_mime="application/pdf",
            data=data,
            max_pages=128,
            context=ParseContext(
                tenant_id="parsebench-table-paddle-reuse",
                document_id="table-" + hashlib.sha256(case_key.encode()).hexdigest()[:24],
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
            raise ValueError("PARSEBENCH_TABLE_SOURCE_REGION_MISSING")
        source_tokens = token_fingerprint(source_region.witness.observation.text)
        target_hashes = target.get("critical_token_hashes")
        if not isinstance(target_hashes, list) or not all(
            isinstance(value, str) and value in source_tokens for value in target_hashes
        ):
            raise ValueError("PARSEBENCH_TABLE_TOKEN_BINDING_MISMATCH")
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
        model_tokens = token_fingerprint(model_text)
        exact = all(
            model_tokens[token] == source_tokens[token] for token in target_hashes
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
        raise ValueError("PARSEBENCH_TABLE_PADDLE_OUTPUT_MUST_BE_NEW")
    output.mkdir(parents=True)
    records_path = output / "RECORDS.jsonl"
    with records_path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    statuses = Counter(str(record["status"]) for record in records)
    reasons = Counter(str(record.get("reason")) for record in records if record.get("reason"))
    result: dict[str, Any] = {
        "targets": len(targets),
        "status_counts": dict(sorted(statuses.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "records_sha256": digest(records_path),
        "hidden_table_truth_visible": False,
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
