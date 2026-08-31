from __future__ import annotations

import hashlib
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
FREEZE_PATH = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION_PATH = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
ACQUISITION_RECEIPT = EXPERIMENT / "receipts" / "acquisition-receipt.json"
CORPUS = EXPERIMENT / "corpus"
DATASET_ID = "opendatalab/OmniDocBench"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def remote_url(revision: str, dataset_path: str) -> str:
    revision_q = urllib.parse.quote(revision, safe="")
    path_q = urllib.parse.quote(dataset_path.replace("\\", "/"), safe="/")
    return f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision_q}/{path_q}?download=true"


def download_immutable(url: str, target: Path) -> dict[str, Any]:
    if target.exists():
        raise RuntimeError(f"refusing to overwrite existing corpus file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".part")
    if temp.exists():
        temp.unlink()
    request = urllib.request.Request(url, headers={"User-Agent": "tavonel-research-acquire/1"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response, temp.open("xb") as handle:
            length = response.headers.get("Content-Length")
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
        if length is not None and int(length) != temp.stat().st_size:
            raise RuntimeError(f"content-length mismatch for {target.name}")
        os.replace(temp, target)
    except Exception:
        if temp.exists():
            temp.unlink()
        raise
    return {
        "path": target.relative_to(EXPERIMENT).as_posix(),
        "bytes": target.stat().st_size,
        "sha256": sha256_file(target),
    }


def verify_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    for path in (PROTOCOL_PATH, FREEZE_PATH, SELECTION_PATH, SELECTION_SEAL):
        if not path.is_file():
            raise RuntimeError(f"required frozen artifact missing: {path.name}")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    selection_seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL_PATH) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol hash mismatch")
    if sha256_file(SELECTION_PATH) != selection_seal.get("selection_sha256"):
        raise RuntimeError("selection hash mismatch")
    if selection.get("protocol_sha256") != freeze.get("protocol_sha256"):
        raise RuntimeError("selection not bound to frozen protocol")
    return protocol, selection


def main() -> int:
    if ACQUISITION_RECEIPT.exists():
        raise SystemExit("acquisition receipt already exists; input set is immutable")
    if CORPUS.exists() and any(CORPUS.rglob("*")):
        raise SystemExit("corpus directory is not empty; refusing ambiguous resume")
    protocol, selection = verify_frozen_inputs()
    old_rev = protocol["dataset"]["source_native_pre_deletion_revision"]
    current_rev = protocol["dataset"]["current_v1_6_revision"]

    files: list[dict[str, Any]] = []
    for case in selection["lane_a"]:
        stem = str(case["page_stem"])
        image_source = str(case["image_path"])
        pdf_source = str(case["source_pdf_path"])
        image_target = CORPUS / "lane-a" / "images" / Path(image_source).name
        pdf_target = CORPUS / "lane-a" / "source-pdfs" / Path(pdf_source).name
        files.append(
            {
                "lane": "a",
                "kind": "image",
                "page_stem": stem,
                "dataset_path": image_source,
                "dataset_revision": old_rev,
                **download_immutable(remote_url(old_rev, image_source), image_target),
            }
        )
        files.append(
            {
                "lane": "a",
                "kind": "source_pdf",
                "page_stem": stem,
                "dataset_path": pdf_source,
                "dataset_revision": old_rev,
                **download_immutable(remote_url(old_rev, pdf_source), pdf_target),
            }
        )

    for case in selection["lane_b"]:
        stem = str(case["page_stem"])
        image_source = str(case["image_path"])
        image_target = CORPUS / "lane-b" / "images" / Path(image_source).name
        files.append(
            {
                "lane": "b",
                "kind": "image",
                "page_stem": stem,
                "subset": str(case["subset"]),
                "dataset_path": image_source,
                "dataset_revision": current_rev,
                **download_immutable(remote_url(current_rev, image_source), image_target),
            }
        )

    expected = int(selection["counts"]["lane_a"]) * 2 + int(selection["counts"]["lane_b"])
    if len(files) != expected:
        raise RuntimeError("acquired file count mismatch")
    total_bytes = sum(int(item["bytes"]) for item in files)
    receipt = {
        "experiment_id": protocol["experiment_id"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "selection_sha256": sha256_file(SELECTION_PATH),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "ground_truth_acquired": False,
        "files": files,
    }
    ACQUISITION_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    ACQUISITION_RECEIPT.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"file_count": len(files), "total_bytes": total_bytes, "ground_truth_acquired": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
