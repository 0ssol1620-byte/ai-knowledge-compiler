"""§5.2 (8)+(9): projection readiness ratios and byte-based compile estimate."""

from __future__ import annotations

import math

from . import inventory
from .config import HealthScanConfig
from .inventory import FileRecord
from .models import HEURISTIC_LABEL

MD_FAMILY = frozenset({".md", ".markdown", ".mdx"})
FRONTMATTER_SCAN_LINES = 80


def _has_frontmatter(text: str) -> bool:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    return any(line.strip() == "---" for line in lines[1:FRONTMATTER_SCAN_LINES])


def analyze_readiness(records: list[FileRecord], config: HealthScanConfig) -> dict:
    total = len(records)
    md_recs = [r for r in records if r.suffix in MD_FAMILY]
    texts: dict[str, str] = {}
    for record in md_recs:
        text = inventory.read_text(record, config)
        if text is not None:
            texts[record.rel_path] = text
    with_frontmatter = sum(1 for text in texts.values() if _has_frontmatter(text))
    md_ratio = len(md_recs) / total if total else 0.0
    fm_rate = with_frontmatter / len(texts) if texts else 0.0
    return {
        "label": HEURISTIC_LABEL,
        "discovered_files": total,
        "markdown_files": len(md_recs),
        "markdown_file_ratio": md_ratio,
        "markdown_scanned": len(texts),
        "markdown_with_frontmatter": with_frontmatter,
        "frontmatter_rate_among_markdown": fm_rate,
        "note": "frontmatter = leading '---' block within the first 80 lines",
    }


def analyze_estimate(records: list[FileRecord], config: HealthScanConfig) -> dict:
    md_bytes = sum(r.size_bytes for r in records if r.suffix in MD_FAMILY)
    tokens = int(md_bytes / config.bytes_per_token * config.compile_overhead_factor)
    chunks = math.ceil(tokens / config.chunk_target_tokens) if tokens > 0 else 0
    return {
        "label": HEURISTIC_LABEL,
        "basis": "summed bytes of markdown-family files (.md/.markdown/.mdx)",
        "markdown_bytes": md_bytes,
        "coefficients": {
            "bytes_per_token": config.bytes_per_token,
            "chunk_target_tokens": config.chunk_target_tokens,
            "compile_overhead_factor": config.compile_overhead_factor,
        },
        "estimated_tokens": tokens,
        "estimated_chunks": chunks,
        "estimated_compile_calls": chunks,
    }
