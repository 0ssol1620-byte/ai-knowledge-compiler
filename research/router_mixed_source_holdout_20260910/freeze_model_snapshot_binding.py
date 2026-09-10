"""Freeze official Hugging Face snapshot file hashes before model execution."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

from .preflight_mixed_holdout import digest, load_json

MAX_NON_LFS_FILE_BYTES = 64 * 1024 * 1024
REVISION_FILE = "arena-weights-revision.txt"


class SnapshotFreezeError(ValueError):
    pass


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SnapshotFreezeError("SNAPSHOT_FILE_PATH_INVALID")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or "\\" in value:
        raise SnapshotFreezeError("SNAPSHOT_FILE_PATH_INVALID")
    return path.as_posix()


def _fetch(url: str, *, maximum_bytes: int) -> bytes:
    if not url.startswith("https://huggingface.co/"):
        raise SnapshotFreezeError("REMOTE_URL_NOT_OFFICIAL_HTTPS")
    request = Request(  # noqa: S310 - URL is restricted above
        url, headers={"User-Agent": "TAVONEL-Router-Holdout/1.0"}
    )
    with urlopen(request, timeout=60) as response:  # noqa: S310 - restricted above
        if response.status != 200:
            raise SnapshotFreezeError(f"HTTP_{response.status}")
        value = bytes(response.read(maximum_bytes + 1))
    if len(value) > maximum_bytes:
        raise SnapshotFreezeError("REMOTE_FILE_SIZE_LIMIT_EXCEEDED")
    return value


def build_snapshot_binding(
    *,
    identity: Mapping[str, Any],
    runtime_root: Path,
    fetch: Callable[..., bytes] = _fetch,
) -> dict[str, object]:
    raw_models = identity.get("models")
    if not isinstance(raw_models, Mapping) or not raw_models:
        raise SnapshotFreezeError("MODEL_IDENTITIES_REQUIRED")
    frozen_models: dict[str, object] = {}
    for model_key in sorted(raw_models):
        identity_row = raw_models[model_key]
        if not isinstance(model_key, str) or not isinstance(identity_row, Mapping):
            raise SnapshotFreezeError("MODEL_IDENTITY_INVALID")
        runtime_path = runtime_root / model_key / "runtime.json"
        runtime = load_json(runtime_path)
        repository = runtime.get("model_repo")
        revision = runtime.get("model_revision")
        if (
            not isinstance(repository, str)
            or not repository
            or not isinstance(revision, str)
            or len(revision) != 40
            or revision != identity_row.get("model_revision")
            or digest(runtime_path.read_bytes()) != identity_row.get("runtime_sha256")
        ):
            raise SnapshotFreezeError(f"{model_key}:RUNTIME_IDENTITY_MISMATCH")
        api_url = (
            "https://huggingface.co/api/models/"
            + quote(repository, safe="/")
            + "/revision/"
            + quote(revision, safe="")
            + "?blobs=true"
        )
        api_bytes = fetch(api_url, maximum_bytes=8 * 1024 * 1024)
        try:
            api = json.loads(api_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SnapshotFreezeError(f"{model_key}:API_JSON_INVALID") from exc
        if not isinstance(api, dict) or api.get("sha") != revision:
            raise SnapshotFreezeError(f"{model_key}:API_REVISION_MISMATCH")
        siblings = api.get("siblings")
        if not isinstance(siblings, list) or not siblings:
            raise SnapshotFreezeError(f"{model_key}:API_FILES_REQUIRED")
        files: list[dict[str, object]] = []
        descriptor_rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for sibling in siblings:
            if not isinstance(sibling, Mapping):
                raise SnapshotFreezeError(f"{model_key}:API_FILE_INVALID")
            relative = _safe_relative(sibling.get("rfilename"))
            if relative in seen:
                raise SnapshotFreezeError(f"{model_key}:API_FILE_DUPLICATE")
            seen.add(relative)
            lfs = sibling.get("lfs")
            if isinstance(lfs, Mapping):
                sha = lfs.get("sha256")
                size = lfs.get("size", sibling.get("size"))
                if (
                    not isinstance(sha, str)
                    or len(sha) != 64
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                ):
                    raise SnapshotFreezeError(f"{model_key}:LFS_METADATA_INVALID")
                content_hash = "sha256:" + sha
                descriptor_rows.append(
                    {"rfilename": relative, "size": size, "lfs_sha256": sha}
                )
            else:
                file_url = (
                    "https://huggingface.co/"
                    + quote(repository, safe="/")
                    + "/resolve/"
                    + quote(revision, safe="")
                    + "/"
                    + quote(relative, safe="/")
                    + "?download=true"
                )
                content = fetch(file_url, maximum_bytes=MAX_NON_LFS_FILE_BYTES)
                size = len(content)
                content_hash = digest(content)
                descriptor_rows.append(
                    {
                        "rfilename": relative,
                        "size": size,
                        "content_sha256": content_hash,
                    }
                )
            files.append(
                {
                    "relative_path": f"{model_key}/weights/{relative}",
                    "sha256": content_hash,
                    "size_bytes": size,
                }
            )
        revision_bytes = revision.encode("utf-8")
        files.append(
            {
                "relative_path": f"{model_key}/weights/{REVISION_FILE}",
                "sha256": digest(revision_bytes),
                "size_bytes": len(revision_bytes),
            }
        )
        files.sort(key=lambda row: str(row["relative_path"]))
        descriptor_rows.sort(key=lambda row: str(row["rfilename"]))
        descriptor_bytes = json.dumps(
            {"sha": revision, "siblings": descriptor_rows},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        frozen_models[model_key] = {
            "repository": repository,
            "revision": revision,
            "official_api_url": api_url,
            "official_snapshot_descriptor_sha256": digest(descriptor_bytes),
            "official_file_count": len(siblings),
            "files": files,
        }
    return {
        "schema": "tavonel.router_model_snapshot_binding.v1",
        "state": "FROZEN_BEFORE_REMOTE_EXECUTION",
        "source": "official_huggingface_revision_api_and_resolve_endpoints",
        "models": frozen_models,
        "truth_opened": False,
        "model_calls": 0,
        "production_promotion": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    value = build_snapshot_binding(
        identity=load_json(args.identity), runtime_root=args.runtime_root
    )
    payload = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        args.output.write_bytes(payload) if not args.output.exists() else None
    except OSError as exc:
        raise SnapshotFreezeError("SNAPSHOT_BINDING_WRITE_FAILED") from exc
    if args.output.read_bytes() != payload:
        raise SnapshotFreezeError("SNAPSHOT_BINDING_ALREADY_EXISTS_DIFFERENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
