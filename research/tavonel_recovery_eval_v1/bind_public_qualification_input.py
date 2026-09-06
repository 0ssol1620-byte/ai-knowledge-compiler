#!/usr/bin/env python3
"""Bind one deterministic already-spent OmniDocBench page for runtime qualification."""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "PUBLIC_QUALIFICATION_INPUT.json"
DATASET_ID = "opendatalab/OmniDocBench"
DATASET_API = f"https://huggingface.co/api/datasets/{DATASET_ID}"
FILENAME = "PPT_1001115_eng_page_003.png"
USER_AGENT = "TAVONEL-research-runtime-qualification/1.0"


class BindingRefused(RuntimeError):
    pass


def _get_json(url: str) -> dict[str, Any]:
    if not url.startswith("https://huggingface.co/"):
        raise BindingRefused("qualification source must remain on huggingface.co")
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS Hugging Face origin
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            value = json.load(response)
    except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
        raise BindingRefused(f"dataset metadata fetch failed: {type(error).__name__}") from None
    if not isinstance(value, dict):
        raise BindingRefused("dataset metadata must be an object")
    return value


def _get_bytes(url: str) -> bytes:
    if not url.startswith("https://huggingface.co/"):
        raise BindingRefused("qualification bytes must remain on huggingface.co")
    request = urllib.request.Request(  # noqa: S310 - fixed HTTPS Hugging Face origin
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
            data = response.read(5 * 1024 * 1024)
    except (OSError, urllib.error.HTTPError) as error:
        raise BindingRefused(f"qualification input fetch failed: {type(error).__name__}") from None
    if not data or len(data) >= 5 * 1024 * 1024:
        raise BindingRefused("qualification input size is invalid")
    return data


def build_binding() -> dict[str, Any]:
    metadata = _get_json(DATASET_API)
    revision = str(metadata.get("sha") or "")
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision.lower()):
        raise BindingRefused("Hugging Face dataset revision is not an exact git SHA")
    encoded_name = urllib.parse.quote(FILENAME, safe="")
    url = (
        f"https://huggingface.co/datasets/{DATASET_ID}/resolve/{revision}/"
        f"images/{encoded_name}?download=true"
    )
    data = _get_bytes(url)
    digest = "sha256:" + hashlib.sha256(data).hexdigest()
    return {
        "schema": "tavonel.recovery.public_qualification_input.v1",
        "evidence_class": "SPENT_DEVELOPMENT_ONLY",
        "dataset_id": DATASET_ID,
        "dataset_revision": revision,
        "selection_rule": "LEXICOGRAPHIC_FIRST_PUBLIC_IMAGE_NAME",
        "filename": FILENAME,
        "url": url,
        "bytes": len(data),
        "sha256": digest,
        "historical_family": "OMNIDOCBENCH_2026_08_09_1651",
        "fresh": False,
        "confirmatory_eligible": False,
    }


def main() -> int:
    payload = build_binding()
    if OUTPUT.exists():
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
        if existing != payload:
            raise BindingRefused("existing public qualification binding differs from current bytes")
        print(json.dumps({"status": "ALREADY_BOUND", "sha256": payload["sha256"]}, sort_keys=True))
        return 0
    OUTPUT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BOUND", "sha256": payload["sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
