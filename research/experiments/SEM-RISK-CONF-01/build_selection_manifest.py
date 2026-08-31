from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL_PATH = EXPERIMENT / "protocol.json"
FREEZE_PATH = EXPERIMENT / "receipts" / "protocol-freeze.json"
SELECTION_PATH = EXPERIMENT / "selection-manifest.json"
SELECTION_SEAL = EXPERIMENT / "receipts" / "selection-seal.json"
DATASET_ID = "opendatalab/OmniDocBench"
API = f"https://huggingface.co/api/datasets/{DATASET_ID}"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": "tavonel-research-selection/1"})
    with urllib.request.urlopen(req, timeout=120) as response:
        return json.load(response)


def get_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tavonel-research-selection/1"})
    with urllib.request.urlopen(req, timeout=180) as response:
        return response.read()


def tree(revision: str, folder: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(revision, safe="")
    payload = get_json(
        f"{API}/tree/{encoded}/{folder}?recursive=true&expand=false&limit=1000"
    )
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected tree response for {folder}")
    return [item for item in payload if isinstance(item, dict) and item.get("type") == "file"]


def rank(salt: str, key: str) -> str:
    return hashlib.sha256((salt + "\0" + key).encode()).hexdigest()


def stem_from_dataset_path(path: str) -> str:
    return Path(path).stem


def main() -> int:
    if SELECTION_PATH.exists() or SELECTION_SEAL.exists():
        raise SystemExit("selection already exists; confirmatory selection is immutable")
    if not PROTOCOL_PATH.is_file() or not FREEZE_PATH.is_file():
        raise SystemExit("freeze protocol before building selection")
    protocol = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if sha256_file(PROTOCOL_PATH) != freeze.get("protocol_sha256"):
        raise RuntimeError("protocol hash changed after freeze")

    exclusions = set(protocol["development_exclusion"]["page_stems"])
    lane_a_cfg = protocol["selection"]["lane_a"]
    lane_b_cfg = protocol["selection"]["lane_b"]
    old_rev = protocol["dataset"]["source_native_pre_deletion_revision"]
    current_rev = protocol["dataset"]["current_v1_6_revision"]

    old_pdf_files = tree(old_rev, "ori_pdfs")
    old_image_files = tree(old_rev, "images")
    pdf_by_stem = {stem_from_dataset_path(str(item["path"])): str(item["path"]) for item in old_pdf_files}
    image_by_stem = {stem_from_dataset_path(str(item["path"])): str(item["path"]) for item in old_image_files}
    lane_a_universe = sorted((set(pdf_by_stem) & set(image_by_stem)) - exclusions)
    lane_a_ranked = sorted(
        lane_a_universe,
        key=lambda key: (rank(str(lane_a_cfg["salt"]), key), key),
    )
    lane_a_count = int(lane_a_cfg["sample_size"])
    if len(lane_a_ranked) < lane_a_count:
        raise RuntimeError("lane A universe smaller than frozen sample size")
    lane_a_keys = lane_a_ranked[:lane_a_count]
    lane_a = [
        {
            "page_stem": key,
            "image_path": image_by_stem[key],
            "source_pdf_path": pdf_by_stem[key],
            "rank_sha256": rank(str(lane_a_cfg["salt"]), key),
        }
        for key in lane_a_keys
    ]

    gt_url = (
        f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{urllib.parse.quote(current_rev, safe='')}/"
        "OmniDocBench.json?download=true"
    )
    gt_bytes = get_bytes(gt_url)
    current_gt_sha = sha256_bytes(gt_bytes)
    current_items = json.loads(gt_bytes.decode("utf-8"))
    if not isinstance(current_items, list):
        raise RuntimeError("current annotation payload is not a list")

    # Selection reads ONLY the two whitelisted page_info fields.  Layout/text/table/formula
    # annotations are deliberately not copied into any selection artifact or log.
    subset_candidates: dict[str, list[str]] = {name: [] for name in lane_b_cfg["subsets"]}
    path_by_stem: dict[str, str] = {}
    lane_a_set = set(lane_a_keys)
    for item in current_items:
        page_info = item.get("page_info") if isinstance(item, dict) else None
        if not isinstance(page_info, dict):
            continue
        image_path = str(page_info.get("image_path") or "")
        attributes = page_info.get("page_attribute")
        subset = str(attributes.get("subset") or "") if isinstance(attributes, dict) else ""
        if subset not in subset_candidates or not image_path:
            continue
        stem = stem_from_dataset_path(image_path)
        if stem in exclusions or stem in lane_a_set:
            continue
        subset_candidates[subset].append(image_path)
        path_by_stem[stem] = image_path

    per_subset = int(lane_b_cfg["sample_per_subset"])
    lane_b: list[dict[str, str]] = []
    for subset in lane_b_cfg["subsets"]:
        candidates = sorted(
            set(subset_candidates[subset]),
            key=lambda path: (rank(str(lane_b_cfg["salt"]), path), path),
        )
        if len(candidates) < per_subset:
            raise RuntimeError(f"lane B subset {subset} smaller than frozen sample size")
        for path in candidates[:per_subset]:
            stem = stem_from_dataset_path(path)
            lane_b.append(
                {
                    "page_stem": stem,
                    "image_path": path,
                    "subset": subset,
                    "rank_sha256": rank(str(lane_b_cfg["salt"]), path),
                }
            )

    if len(lane_b) != int(lane_b_cfg["total_sample_size"]):
        raise RuntimeError("lane B selected count does not equal frozen total")
    if set(item["page_stem"] for item in lane_b) & lane_a_set:
        raise RuntimeError("cross-lane disjointness violated")
    if exclusions & (lane_a_set | {item["page_stem"] for item in lane_b}):
        raise RuntimeError("development page leaked into confirmatory selection")

    manifest = {
        "experiment_id": protocol["experiment_id"],
        "protocol_sha256": freeze["protocol_sha256"],
        "dataset": {
            "current_revision": current_rev,
            "source_native_revision": old_rev,
            "current_annotation_sha256_selection_only": current_gt_sha,
        },
        "lane_a": lane_a,
        "lane_b": lane_b,
        "counts": {
            "lane_a": len(lane_a),
            "lane_b": len(lane_b),
            "total": len(lane_a) + len(lane_b),
            "development_exclusions": len(exclusions),
        },
        "selection_ground_truth_boundary": {
            "lane_a": "tree metadata only; no ground truth",
            "lane_b": "only page_info.image_path and page_info.page_attribute.subset consumed",
            "annotation_content_emitted": False,
        },
    }
    SELECTION_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    seal = {
        "protocol_sha256": freeze["protocol_sha256"],
        "selection_sha256": sha256_file(SELECTION_PATH),
        "current_annotation_sha256_selection_only": current_gt_sha,
        "counts": manifest["counts"],
    }
    SELECTION_SEAL.write_text(
        json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "selected": manifest["counts"],
                "selection_sha256": seal["selection_sha256"],
                "sealed": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
