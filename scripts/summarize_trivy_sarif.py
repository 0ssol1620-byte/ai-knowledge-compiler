"""Print finding identities and paths without echoing potentially sensitive messages."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def summarize(path: Path) -> list[str]:
    report = json.loads(path.read_text(encoding="utf-8"))
    findings = []
    for run in report.get("runs", []):
        for result in run.get("results", []):
            locations = result.get("locations", [])
            paths = [
                item.get("physicalLocation", {}).get("artifactLocation", {}).get("uri", "unknown")
                for item in locations
            ]
            findings.append(
                json.dumps(
                    {
                        "ruleId": result.get("ruleId", "unknown"),
                        "level": result.get("level", "unknown"),
                        "paths": paths,
                    },
                    sort_keys=True,
                )
            )
    return sorted(findings)


if __name__ == "__main__":
    for finding in summarize(Path(sys.argv[1])):
        print(finding)
