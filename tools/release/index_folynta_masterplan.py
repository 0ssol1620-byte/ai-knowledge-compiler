"""Create a line-addressable index for the authoritative FOLYNTA masterplan.

The index is evidence of coverage, not evidence that an external gate passed.
It records every heading, checkbox, and normative line without interpreting a
target or legal requirement as a completed production fact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHECKBOX = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
NORMATIVE = re.compile(
    r"\bMUST(?:\s+NOT)?\b|\bSHALL(?:\s+NOT)?\b|필수|반드시|금지|절대|해야\s*한다|하여야\s*한다",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def record(line_number: int, text: str) -> dict[str, object]:
    return {"line": line_number, "text": text}


def main() -> None:
    args = parse_args()
    payload = args.source.read_bytes()
    lines = payload.decode("utf-8").splitlines()
    headings: list[dict[str, object]] = []
    checkboxes: list[dict[str, object]] = []
    normative: list[dict[str, object]] = []

    for line_number, line in enumerate(lines, start=1):
        heading = HEADING.match(line)
        if heading:
            headings.append(
                {
                    "line": line_number,
                    "level": len(heading.group(1)),
                    "text": heading.group(2),
                }
            )
        checkbox = CHECKBOX.match(line)
        if checkbox:
            checkboxes.append(
                {
                    "line": line_number,
                    "checked_in_source": checkbox.group(1).lower() == "x",
                    "text": checkbox.group(2),
                }
            )
        if NORMATIVE.search(line):
            normative.append(record(line_number, line.strip()))

    result = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "source": {
            "path": str(args.source),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "encoding": "utf-8",
            "line_count": len(lines),
        },
        "semantics": {
            "purpose": "coverage_index_only",
            "completion_inference": "prohibited",
            "external_gate_inference": "prohibited",
        },
        "counts": {
            "headings": len(headings),
            "checkboxes": len(checkboxes),
            "normative_lines": len(normative),
        },
        "headings": headings,
        "checkboxes": checkboxes,
        "normative_lines": normative,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
