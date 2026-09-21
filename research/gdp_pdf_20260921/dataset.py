"""Materialize the GDP.pdf task catalog into the out-of-repo evaluation cache.

Licence: MIT on Hugging Face, tagged not-for-training. PDFs, prompts and rubrics stay
under D:\CodexData\gdp-pdf-cache and are never redistributed. Attribution: Surge AI.

DEVIATION (receipted): the sealed revision 400e411f...'s ``data.parquet`` blob is served
only from the retired ``cdn-lfs-us-1.hf.co`` host, which returns 403 AccessDenied to an
authenticated, freshly signed URL. See SEALED_REVISION_NOTE. This run therefore pins the
current head commit and records both digests.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download, list_repo_tree
from pypdf import PdfReader

REPO = "surgeai/GDP.pdf"
SEALED_REVISION = "400e411fc344b1b8dd2a51e70a7ecdf469c05b3c"
SEALED_PARQUET_SHA256 = "2ba18b4facc482a3520a6a6763f0294b0f8f3369f9cf4375b17af8fc0e025704"
RUN_REVISION = "8d1efb32cb57baec2265bb84da03b30654761373"
RUN_PARQUET_SHA256 = "7e022a1e1a9effc5a41f41c9ef9039fae5406172a4e024511e8ae995b66307fa"
SEALED_REVISION_NOTE = (
    "Sealed revision 400e411fc344b1b8dd2a51e70a7ecdf469c05b3c resolves (HTTP 302, "
    "x-linked-etag=2ba18b4f...) but its data.parquet blob is hosted on cdn-lfs-us-1.hf.co, "
    "which returns 403 AccessDenied for the signed URL via requests, huggingface_hub and "
    "curl alike. PDFs at the same revision redirect to us.aws.cdn.hf.co and download fine; "
    "only the parquet blob is stranded. Run pinned to head 8d1efb32... instead. This run is "
    "NOT official-comparable for that reason as well as the surface and judge deviations."
)
CACHE = Path(r"D:\CodexData\gdp-pdf-cache") / RUN_REVISION
MAX_RUBRIC_SLOTS = 30


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(filename: str) -> Path:
    return Path(
        hf_hub_download(
            REPO, filename, repo_type="dataset", revision=RUN_REVISION, local_dir=CACHE / "hf"
        )
    )


def rubric_criteria(row: dict) -> list[str]:
    """Ordered non-empty criterion strings, slot 1..30."""
    out = []
    for slot in range(1, MAX_RUBRIC_SLOTS + 1):
        value = row.get(f"rubric - {slot}. criterion")
        if isinstance(value, str) and value.strip():
            out.append(value.strip())
    return out


def page_count(path: Path) -> int | None:
    try:
        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


def build() -> dict:
    parquet = fetch("data.parquet")
    parquet_sha = sha256_file(parquet)
    if parquet_sha != RUN_PARQUET_SHA256:
        raise SystemExit(f"data.parquet sha256 drifted: {parquet_sha}")

    tree = {
        entry.path: entry
        for entry in list_repo_tree(
            REPO, repo_type="dataset", revision=RUN_REVISION, recursive=True
        )
        if entry.path.startswith("pdfs/")
    }

    rows = pq.read_table(parquet).to_pylist()
    tasks = []
    for row in rows:
        pdf_path = fetch(row["pdf_path"])
        pdf_sha = sha256_file(pdf_path)
        entry = tree.get(row["pdf_path"])
        declared = entry.lfs.sha256 if entry is not None and entry.lfs else None
        if declared and declared != pdf_sha:
            raise SystemExit(f"{row['pdf_path']} sha256 mismatch against the repo tree")
        criteria = rubric_criteria(row)
        tasks.append(
            {
                "task_id": row["task_id"],
                "task_response_id": row["task_response_id"],
                "domain": row["domain"],
                "prompt": row["prompt"],
                "prompt_sha256": sha256_bytes(row["prompt"].encode("utf-8")),
                "pdf_repo_path": row["pdf_path"],
                "pdf_local_path": str(pdf_path),
                "pdf_sha256": pdf_sha,
                "pdf_bytes": pdf_path.stat().st_size,
                "pdf_pages": page_count(pdf_path),
                "criteria": criteria,
                "criteria_count": len(criteria),
                # Ordered rubric digest: sha256 over the criteria joined by \x1e, order-sensitive.
                "rubric_sha256": sha256_bytes("\x1e".join(criteria).encode("utf-8")),
            }
        )

    tasks.sort(key=lambda t: (t["task_id"], t["task_response_id"]))
    catalog_digest = sha256_bytes(
        json.dumps(
            [
                {
                    k: t[k]
                    for k in (
                        "task_id",
                        "task_response_id",
                        "domain",
                        "pdf_sha256",
                        "prompt_sha256",
                        "rubric_sha256",
                        "criteria_count",
                    )
                }
                for t in tasks
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    return {
        "repo": REPO,
        "run_revision": RUN_REVISION,
        "run_parquet_sha256": RUN_PARQUET_SHA256,
        "sealed_revision": SEALED_REVISION,
        "sealed_parquet_sha256": SEALED_PARQUET_SHA256,
        "sealed_revision_unreachable": SEALED_REVISION_NOTE,
        "task_count": len(tasks),
        "task_set_digest": catalog_digest,
        "tasks": tasks,
    }


def main() -> int:
    catalog = build()
    out = CACHE / "task_catalog.json"
    out.write_text(json.dumps(catalog, indent=2, sort_keys=True), encoding="utf-8")
    print(f"tasks={catalog['task_count']} task_set_digest={catalog['task_set_digest']}")
    print(f"pages_total={sum(t['pdf_pages'] or 0 for t in catalog['tasks'])}")
    print(f"catalog -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
