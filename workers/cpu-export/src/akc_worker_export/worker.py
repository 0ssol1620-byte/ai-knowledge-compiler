"""Pure deterministic ZIP compiler for isolated export execution."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile


def compile_markdown_zip(files: dict[str, str]) -> tuple[bytes, str]:
    normalized = {
        name.replace("\\", "/").lstrip("/"): value.replace("\r\n", "\n")
        for name, value in files.items()
    }
    if any(".." in name.split("/") for name in normalized):
        raise ValueError("unsafe_export_path")
    manifest = {
        "schema_version": "1.0",
        "exporter_version": "cpu-export-1",
        "files": sorted(normalized),
    }
    payloads = {
        **{name: value.encode("utf-8") for name, value in normalized.items()},
        "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode(),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(payloads):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payloads[name], compresslevel=9)
    data = buffer.getvalue()
    return data, hashlib.sha256(data).hexdigest()
