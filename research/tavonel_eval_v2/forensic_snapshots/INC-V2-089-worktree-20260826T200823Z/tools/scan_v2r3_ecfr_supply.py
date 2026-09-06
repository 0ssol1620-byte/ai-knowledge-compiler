"""Per-title eCFR supply scan for V2R3 candidate selection. METADATA ONLY.

One call per CFR title returns every content version in that title, so the
number of sections carrying two or more distinct dated versions is computable
per PART without asking about any part individually. That keeps the probe cheap
and, more importantly, keeps it blind: the scan cannot be steered toward a part
because nothing here reads what changed in any section.

Parts already declared by any earlier sources module are removed through
`root_identity` before anything is reported, so a spent container never even
appears as a candidate.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import root_identity as ri  # noqa: E402

UA = "TAVONEL-research/1.0 (claude23@vieworks.com)"
PRIOR = ri.prior_root_identities()["identities"]


def title_versions(title: str) -> list[dict]:
    url = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json"
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8")).get("content_versions", [])


def scan(titles: list[str], min_multi: int = 6) -> dict[str, list]:
    out: dict[str, list] = {}
    for title in titles:
        try:
            rows = title_versions(title)
        except Exception as error:
            out[title] = [{"error": str(error)}]
            continue
        by_part: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
        for row in rows:
            if row.get("type") != "section" or row.get("removed"):
                continue
            by_part[str(row.get("part"))][row["identifier"]].add(row["date"])
        rows_out = []
        for part, sections in by_part.items():
            identity = ri.canonical_identity("ecfr", (title, part, ""))
            if identity == ri.UNVERIFIABLE or identity in PRIOR:
                continue
            multi = sum(1 for dates in sections.values() if len(dates) >= 2)
            if multi >= min_multi:
                rows_out.append({"part": part, "sections": len(sections), "multi": multi})
        rows_out.sort(key=lambda r: (-r["multi"], r["part"]))
        out[title] = rows_out
        time.sleep(0.4)
    return out


if __name__ == "__main__":
    titles = sys.argv[1].split(",")
    result = scan(titles, int(sys.argv[2]) if len(sys.argv) > 2 else 6)
    for title, rows in result.items():
        head = rows[:12] if isinstance(rows, list) else rows
        print(title, json.dumps(head))
