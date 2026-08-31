from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
FREEZE_PATH = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION_PATH = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
TRANSPORT_AMENDMENT = EXPERIMENT / "transport-amendment.json"
TRANSPORT_FREEZE = EXPERIMENT / "receipts" / "transport-amendment-freeze.json"
ACQUISITION_RECEIPT = EXPERIMENT / "receipts" / "acquisition-receipt.json"
CORPUS = EXPERIMENT / "corpus"
DATASET_ID = "opendatalab/OmniDocBench"
API = f"https://huggingface.co/api/datasets/{DATASET_ID}"
RETRY_STATUSES = {429, 500, 502, 503, 504}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def request_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "tavonel-sem-risk-conf-v02/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), dict(response.headers.items())


def complete_tree(revision: str, folder: str) -> list[dict[str, Any]]:
    revision_q = urllib.parse.quote(revision, safe="")
    url = f"{API}/tree/{revision_q}/{folder}?recursive=true&expand=false&limit=1000"
    items: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    while url:
        if url in seen_urls:
            raise RuntimeError("tree pagination repeated a URL/cursor")
        seen_urls.add(url)
        payload, headers = request_json(url)
        if not isinstance(payload, list):
            raise RuntimeError("tree payload is not a list")
        items.extend(item for item in payload if isinstance(item, dict))
        link = headers.get("Link") or headers.get("link") or ""
        match = re.search(r'<([^>]+)>;\s*rel="next"', link)
        url = match.group(1) if match else ""
    return items


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
    last_error: Exception | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers={"User-Agent": "tavonel-sem-risk-conf-v02/1"})
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
            return {
                "path": target.relative_to(EXPERIMENT).as_posix(),
                "bytes": target.stat().st_size,
                "sha256": sha256_file(target),
            }
        except urllib.error.HTTPError as exc:
            last_error = exc
            if temp.exists():
                temp.unlink()
            if exc.code not in RETRY_STATUSES or attempt == 2:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else float(1 << attempt)
            time.sleep(delay)
        except Exception as exc:
            last_error = exc
            if temp.exists():
                temp.unlink()
            raise
    raise RuntimeError(f"download failed without terminal exception: {last_error!r}")


def verify_frozen_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    required = (
        PROTOCOL_PATH, FREEZE_PATH, SELECTION_PATH, SELECTION_SEAL,
        TRANSPORT_AMENDMENT, TRANSPORT_FREEZE,
    )
    for path in required:
        if not path.is_file():
            raise RuntimeError(f"required frozen artifact missing: {path.name}")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    selection = json.loads(SELECTION_PATH.read_text(encoding="utf-8"))
    selection_seal = json.loads(SELECTION_SEAL.read_text(encoding="utf-8"))
    amendment = json.loads(TRANSPORT_AMENDMENT.read_text(encoding="utf-8"))
    transport_freeze = json.loads(TRANSPORT_FREEZE.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL_PATH) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol hash mismatch")
    if sha256_file(SELECTION_PATH) != selection_seal.get("selection_sha256"):
        raise RuntimeError("selection hash mismatch")
    if sha256_file(TRANSPORT_AMENDMENT) != transport_freeze.get("transport_amendment_sha256"):
        raise RuntimeError("transport amendment hash mismatch")
    expected_self = transport_freeze.get("transport_source_hashes", {}).get("acquire_selected_inputs.py")
    if expected_self != sha256_file(Path(__file__)):
        raise RuntimeError("acquisition transport code changed after V02 freeze")
    if amendment.get("scientific_parameters_changed") is not False or amendment.get("selected_cases_changed") is not False:
        raise RuntimeError("transport amendment is not science-preserving")
    return protocol, selection, amendment


def main() -> int:
    if ACQUISITION_RECEIPT.exists():
        raise SystemExit("acquisition receipt already exists; input set is immutable")
    if CORPUS.exists() and any(CORPUS.rglob("*")):
        raise SystemExit("V02 corpus directory is not empty; refusing ambiguous resume")

    protocol, selection, amendment = verify_frozen_inputs()
    old_rev = str(protocol["dataset"]["source_native_pre_deletion_revision"])
    current_rev = str(protocol["dataset"]["current_v1_6_revision"])

    current_tree = complete_tree(current_rev, "images")
    by_basename: dict[str, list[str]] = defaultdict(list)
    for item in current_tree:
        if item.get("type") != "file":
            continue
        path = str(item.get("path") or "")
        if path:
            by_basename[Path(path).name].append(path)

    lane_b_resolution: dict[str, str] = {}
    for case in selection["lane_b"]:
        stem = str(case["page_stem"])
        selected_path = str(case["image_path"])
        matches = sorted(set(by_basename[Path(selected_path).name]))
        if len(matches) != 1:
            raise RuntimeError(f"Lane B transport resolution is not unique for selected case {stem}: {len(matches)}")
        lane_b_resolution[stem] = matches[0]
    if len(lane_b_resolution) != int(selection["counts"]["lane_b"]):
        raise RuntimeError("Lane B transport resolution count mismatch")

    files: list[dict[str, Any]] = []
    for case in selection["lane_a"]:
        stem = str(case["page_stem"])
        image_source = str(case["image_path"])
        pdf_source = str(case["source_pdf_path"])
        image_target = CORPUS / "lane-a" / "images" / Path(image_source).name
        pdf_target = CORPUS / "lane-a" / "source-pdfs" / Path(pdf_source).name
        files.append({
            "lane": "a", "kind": "image", "page_stem": stem,
            "selected_dataset_path": image_source, "resolved_dataset_path": image_source,
            "dataset_revision": old_rev,
            **download_immutable(remote_url(old_rev, image_source), image_target),
        })
        files.append({
            "lane": "a", "kind": "source_pdf", "page_stem": stem,
            "selected_dataset_path": pdf_source, "resolved_dataset_path": pdf_source,
            "dataset_revision": old_rev,
            **download_immutable(remote_url(old_rev, pdf_source), pdf_target),
        })

    for case in selection["lane_b"]:
        stem = str(case["page_stem"])
        selected_path = str(case["image_path"])
        resolved_path = lane_b_resolution[stem]
        image_target = CORPUS / "lane-b" / "images" / Path(resolved_path).name
        files.append({
            "lane": "b", "kind": "image", "page_stem": stem, "subset": str(case["subset"]),
            "selected_dataset_path": selected_path, "resolved_dataset_path": resolved_path,
            "dataset_revision": current_rev,
            **download_immutable(remote_url(current_rev, resolved_path), image_target),
        })

    expected = int(selection["counts"]["lane_a"]) * 2 + int(selection["counts"]["lane_b"])
    if len(files) != expected:
        raise RuntimeError("acquired file count mismatch")
    if len(current_tree) != 1651:
        raise RuntimeError(f"exact-revision current image tree size changed from preregistered observation: {len(current_tree)}")
    total_bytes = sum(int(item["bytes"]) for item in files)
    receipt = {
        "scientific_experiment_id": protocol["experiment_id"],
        "transport_version": amendment["transport_version"],
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "selection_sha256": sha256_file(SELECTION_PATH),
        "transport_amendment_sha256": sha256_file(TRANSPORT_AMENDMENT),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "complete_current_image_tree_count": len(current_tree),
        "lane_b_unique_transport_resolutions": len(lane_b_resolution),
        "scientific_parameters_changed": False,
        "selected_cases_changed": False,
        "ground_truth_acquired": False,
        "gpu_seconds": 0.0,
        "files": files,
    }
    ACQUISITION_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    ACQUISITION_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "transport_version": "V02",
        "file_count": len(files),
        "lane_b_unique_transport_resolutions": len(lane_b_resolution),
        "ground_truth_acquired": False,
        "gpu_seconds": 0.0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
