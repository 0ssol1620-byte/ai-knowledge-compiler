"""§5.2 (5) stale references: relative markdown links to missing targets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import inventory
from .config import HealthScanConfig
from .inventory import FileRecord
from .models import HEURISTIC_LABEL

MD_FAMILY = frozenset({".md", ".markdown", ".mdx"})

INLINE_LINK = re.compile(r"\[[^\]\n]*\]\(\s*<?([^)<>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?([^\s>]+?)>?\s*$")
FENCE_TOGGLE = re.compile(r"^\s{0,3}(?:```|~~~)")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_PERCENT = re.compile(r"%([0-9A-Fa-f]{2})")


def _percent_decode(target: str) -> str:
    return _PERCENT.sub(lambda m: chr(int(m.group(1), 16)), target)


def analyze(md_records: list[FileRecord], config: HealthScanConfig) -> dict[str, Any]:
    stale: list[dict[str, object]] = []
    checked = 0
    skipped_external = 0
    for record in md_records:
        if record.suffix not in MD_FAMILY:
            continue
        text = inventory.read_text(record, config)
        if text is None:
            continue
        base_dir = Path(record.abs_path).parent
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FENCE_TOGGLE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            targets = [(m.group(1), lineno) for m in INLINE_LINK.finditer(line)]
            ref_def = REF_DEF.match(line)
            if ref_def:
                targets.append((ref_def.group(1), lineno))
            for raw_target, lineno_no in targets:
                target = _percent_decode(raw_target.split("#", 1)[0].split("?", 1)[0].strip())
                if not target:
                    continue
                if SCHEME.match(target) or target.startswith(("#", "/")):
                    skipped_external += 1
                    continue
                candidate = base_dir / Path(target)
                exists = candidate.is_dir() if target.endswith("/") else (
                    candidate.is_file() or candidate.is_dir()
                )
                checked += 1
                if not exists:
                    stale.append(
                        {"file": record.rel_path, "line": lineno_no, "target": target}
                    )
    return {
        "label": HEURISTIC_LABEL,
        "checked_links": checked,
        "stale": stale,
        "skipped_external": skipped_external,
        "note": "relative markdown links only; code fences and external/absolute/"
                "anchor targets are skipped",
    }
