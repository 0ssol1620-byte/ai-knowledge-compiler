"""Stage the six-family M1 source-only inference bundle deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import yaml


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, required=True)
    parser.add_argument("--source-images", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = yaml.safe_load(args.cohort.read_text(encoding="utf-8"))
    if raw.get("ground_truth_in_inference_bundle") is not False:
        raise ValueError("M1 inference bundle must explicitly forbid ground truth")
    cases = raw.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("M1 cohort must contain exactly six cases")
    if args.output.exists():
        raise FileExistsError(args.output)
    images_dir = args.output / "images"
    images_dir.mkdir(parents=True)
    staged: list[dict[str, str]] = []
    families: set[str] = set()
    for case in cases:
        family = str(case["family"])
        filename = str(case["filename"])
        if family in families or Path(filename).name != filename:
            raise ValueError("M1 families and filenames must be unique and flat")
        families.add(family)
        source = args.source_images / filename
        if not source.is_file():
            raise FileNotFoundError(source)
        target = images_dir / filename
        shutil.copyfile(source, target)
        staged.append(
            {"family": family, "filename": filename, "source_sha256": sha256_file(target)}
        )
    manifest = {
        "schema_version": "1.0.0",
        "cohort_id": str(raw["cohort_id"]),
        "claim_scope": "runtime_smoke_only",
        "source_license": str(raw["source_license"]),
        "ground_truth_mounted": False,
        "case_count": len(staged),
        "cases": staged,
    }
    manifest_path = args.output / "inference-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"manifest": str(manifest_path), "sha256": sha256_file(manifest_path)}))


if __name__ == "__main__":
    main()
