from __future__ import annotations

import json
import sys
import types
from pathlib import Path

numpy = types.ModuleType("numpy")
pypdf = types.ModuleType("pypdf")
pypdf.PdfReader = object  # type: ignore[attr-defined]

# The module under test imports numpy and pypdf at module scope, which this
# suite does not need installed. Stubs make the import succeed, but leaving them
# in sys.modules hands every later test in the session an empty numpy, which is
# how this file used to break unrelated suites that only fail when run together.
# Install the stubs, import, then take them back out.
_stubbed = [
    name
    for name, stub in (("numpy", numpy), ("pypdf", pypdf))
    if sys.modules.setdefault(name, stub) is stub
]

from evaluate_olmocr_official import _case_lookup  # noqa: E402

for _name in _stubbed:
    del sys.modules[_name]


def test_frozen_olmocr_source_manifest_schema_is_supported(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "folynta.public-core-source-manifest.v1",
                "source_count": 2,
                "sources": [
                    {
                        "case_id": "olm-a",
                        "source_relative_path": "bench_data/pdfs/a.pdf",
                    },
                    {
                        "case_id": "olm-b",
                        "source_relative_path": "bench_data/pdfs/nested/b.pdf",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    assert _case_lookup(manifest) == {"a.pdf": "olm-a", "nested/b.pdf": "olm-b"}
