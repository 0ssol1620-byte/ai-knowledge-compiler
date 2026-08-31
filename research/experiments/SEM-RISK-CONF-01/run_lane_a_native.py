from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
FREEZE = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
ACQUISITION = EXPERIMENT / "receipts" / "acquisition-receipt.json"
OUTPUT = EXPERIMENT / "outputs" / "lane-a-native"
SUMMARY = OUTPUT / "run-summary.json"

for source_root in (
    ROOT / "packages" / "cir-python" / "src",
    ROOT / "packages" / "native-parsers" / "src",
):
    sys.path.insert(0, str(source_root))

from akc_native_parsers.models import ParseContext  # noqa: E402
from akc_native_parsers.pdf_parser import parse_pdf_to_cir  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def verify_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    for path in (PROTOCOL, FREEZE, SELECTION, SELECTION_SEAL, ACQUISITION):
        if not path.is_file():
            raise RuntimeError(f"required artifact missing: {path}")
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    acquisition = json.loads(ACQUISITION.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol changed after freeze")
    if sha256_file(SELECTION) != seal.get("selection_sha256"):
        raise RuntimeError("selection changed after seal")
    if acquisition.get("protocol_sha256") != sha256_file(PROTOCOL):
        raise RuntimeError("acquisition not bound to protocol")
    if acquisition.get("selection_sha256") != sha256_file(SELECTION):
        raise RuntimeError("acquisition not bound to selection")
    if acquisition.get("ground_truth_acquired") is not False:
        raise RuntimeError("ground truth isolation invariant violated")
    return protocol, selection, acquisition


def page_text(document: Any) -> str:
    parts: list[str] = []
    for block in sorted(document.blocks, key=lambda item: item.order):
        if not any(ref.page_index0 == 0 for ref in block.source_refs):
            continue
        value = block.markdown or block.normalized_text or block.raw_text or block.formula_latex
        if value and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts).strip()


def main() -> int:
    if OUTPUT.exists():
        raise SystemExit("lane A native output already exists; refusing ambiguous resume")
    protocol, selection, acquisition = verify_inputs()
    acquired = {
        (item["lane"], item["kind"], item["page_stem"]): item
        for item in acquisition["files"]
    }
    OUTPUT.mkdir(parents=True, exist_ok=False)
    cases: list[dict[str, Any]] = []
    failures = 0
    for case in selection["lane_a"]:
        stem = str(case["page_stem"])
        receipt = acquired.get(("a", "source_pdf", stem))
        if receipt is None:
            raise RuntimeError(f"source PDF missing from acquisition receipt: {stem}")
        path = EXPERIMENT / str(receipt["path"])
        if not path.is_file() or sha256_file(path) != receipt["sha256"]:
            raise RuntimeError(f"source PDF integrity mismatch: {stem}")
        data = path.read_bytes()
        started = time.perf_counter()
        error: str | None = None
        text = ""
        block_count = 0
        try:
            document = parse_pdf_to_cir(
                filename=path.name,
                declared_mime="application/pdf",
                data=data,
                context=ParseContext(
                    tenant_id="research-sem-risk-conf-01",
                    document_id=f"doc-{hashlib.sha256(stem.encode()).hexdigest()[:24]}",
                    document_version_id=f"ver-{hashlib.sha256((stem + ':v1').encode()).hexdigest()[:24]}",
                    created_at=datetime(2026, 8, 31, tzinfo=UTC),
                ),
                max_pages=4,
            )
            text = page_text(document)
            block_count = len(document.blocks)
            if not text:
                error = "empty_native_text"
        except Exception as exc:  # receipt records stable class only; no corpus body leaks
            error = f"{type(exc).__name__}:{getattr(exc, 'code', 'native_parse_failed')}"
        latency = time.perf_counter() - started
        record = {
            "case_id": stem,
            "status": "completed" if error is None else "failed",
            "error": error,
            "source_sha256": receipt["sha256"],
            "latency_seconds": latency,
            "gpu_seconds": 0.0,
            "estimated_cost_usd": 0.0,
            "block_count": block_count,
            "text": text,
        }
        output_path = OUTPUT / f"{stem}.json"
        output_path.write_text(
            json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        cases.append({**{k: v for k, v in record.items() if k != "text"}, "artifact_sha256": sha256_file(output_path)})
        failures += int(error is not None)

    summary = {
        "experiment_id": protocol["experiment_id"],
        "provider": "native_document/pypdf",
        "ground_truth_mounted": False,
        "input_count": len(cases),
        "completed": len(cases) - failures,
        "failed": failures,
        "gpu_seconds": 0.0,
        "estimated_cost_usd": 0.0,
        "cases": cases,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"input_count": len(cases), "completed": len(cases) - failures, "failed": failures, "gpu_seconds": 0.0}, sort_keys=True))
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
