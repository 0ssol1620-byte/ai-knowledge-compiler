"""Byte-for-byte deterministic ZIP packaging."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Mapping

from akc_security import safe_relative_path


def deterministic_zip(files: Mapping[str, bytes]) -> bytes:
    output = io.BytesIO()
    seen: set[str] = set()
    with zipfile.ZipFile(
        output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as archive:
        ordered = sorted(
            files.items(),
            key=lambda item: (item[0] == "manifest.json", item[0]),
        )
        for path, content in ordered:
            safe = safe_relative_path(path)
            folded = safe.casefold()
            if folded in seen:
                raise ValueError("case-insensitive duplicate ZIP path")
            seen.add(folded)
            info = zipfile.ZipInfo(safe, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(
                info, bytes(content), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9
            )
    return output.getvalue()
