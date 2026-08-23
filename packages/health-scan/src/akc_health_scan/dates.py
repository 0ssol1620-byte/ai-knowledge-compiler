"""§5.2 (6) unresolved dates — conservative detection only.

Two detectors, both low-false-positive by construction:
  * frontmatter date-labeled keys whose value matches no known format;
  * body tokens that LOOK like calendar dates but are impossible dates
    (e.g. month 13, Feb 30) — merely unusual formats are NOT flagged.
"""

from __future__ import annotations

import re
from datetime import datetime

from . import inventory
from .config import HealthScanConfig
from .inventory import FileRecord
from .models import HEURISTIC_LABEL

MD_FAMILY = frozenset({".md", ".markdown", ".mdx"})

FRONTMATTER_DATE_KEY = re.compile(
    r"^\s{0,3}(date|created|created_at|updated|updated_at|modified|published"
    r"|reviewed|last_reviewed)\s*:\s*(.+?)\s*$",
    re.IGNORECASE,
)
BODY_TOKEN = re.compile(r"\b(\d{4})([-/.])(\d{1,2})\2(\d{1,2})\b")
FENCE_TOGGLE = re.compile(r"^\s{0,3}(?:```|~~~)")
YEAR_ONLY = re.compile(r"\d{4}")
YEAR_MONTH = re.compile(r"\d{4}-\d{2}")

FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
    "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S",
)


def _parsable(value: str) -> bool:
    text = value.strip().strip("'\"").rstrip("Zz")
    if YEAR_ONLY.fullmatch(text):
        return True
    if YEAR_MONTH.fullmatch(text):
        try:
            datetime.strptime(text + "-01", "%Y-%m-%d")
            return True
        except ValueError:
            return False
    for fmt in FORMATS:
        try:
            datetime.strptime(text, fmt)
            return True
        except ValueError:
            continue
    return False


def analyze(records: list[FileRecord], config: HealthScanConfig) -> dict:
    findings: list[dict[str, object]] = []
    for record in records:
        if record.suffix not in MD_FAMILY:
            continue
        text = inventory.read_text(record, config)
        if text is None:
            continue
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if FENCE_TOGGLE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            keyed = FRONTMATTER_DATE_KEY.match(line)
            if keyed and not _parsable(keyed.group(2)):
                findings.append(
                    {
                        "file": record.rel_path,
                        "line": lineno,
                        "token": keyed.group(2),
                        "context": "frontmatter-field",
                    }
                )
            for match in BODY_TOKEN.finditer(line):
                year, _sep, month, day = match.groups()
                try:
                    datetime(int(year), int(month), int(day))
                except ValueError:
                    findings.append(
                        {
                            "file": record.rel_path,
                            "line": lineno,
                            "token": match.group(0),
                            "context": "body-token",
                        }
                    )
    return {
        "label": HEURISTIC_LABEL,
        "unresolved": findings,
        "note": "conservative: only unparseable frontmatter date fields and "
                "impossible calendar tokens are flagged",
    }
