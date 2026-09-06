"""Availability probe for V2R3's candidate roots. METADATA ONLY.

Founder ruling section 13 requires a NEW universe of at least 200 admitted pairs
across at least 3 families, disjoint from every spent set. A frame that declares
roots it has not checked can only fail late -- V2R1 lost 106 pairs to a
canonicalisation defect discovered after acquisition -- so every root V2R3
declares is probed first.

WHAT THIS MAY ASK, and nothing else:

    does this repository exist, and does this prefix hold documents
    how many sections of this CFR part carry two or more distinct dated versions
    do issuers above this CIK carry amendment pairs

It never reads revision content, never diffs, never touches an identity outcome.
`sources_v2r3.FORBIDDEN_IN_SELECTION` names those acts and this probe performs
none of them: a count of how many section identifiers have two dated versions is
a supply question about the SOURCE, not a question about what changed inside it.

Candidates are screened through `root_identity` BEFORE being probed, so a root
any earlier study declared is never even asked about. UNVERIFIABLE blocks.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import root_identity as ri  # noqa: E402

UA = "TAVONEL-research/1.0 (claude23@vieworks.com)"
SLEEP = 0.35


def get_json(url: str, *, github: bool = False, timeout: int = 45) -> Any:
    headers = {"User-Agent": UA}
    if github:
        headers["Accept"] = "application/vnd.github+json"
        import os

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


PRIOR = ri.prior_root_identities()["identities"]


def already_declared(family: str, entry: Any) -> bool:
    identity = ri.canonical_identity(family, entry)
    if identity == ri.UNVERIFIABLE:
        raise SystemExit(f"UNVERIFIABLE candidate shape, refusing: {family} {entry!r}")
    return identity in PRIOR


# ---------------------------------------------------------------------------
def probe_ecfr(candidates: list[tuple[str, str]]) -> list[dict[str, Any]]:
    out = []
    for title, part in candidates:
        if already_declared("ecfr", (title, part, "")):
            out.append({"title": title, "part": part, "state": "ALREADY_DECLARED"})
            continue
        try:
            rows = get_json(
                f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json?part={part}"
            ).get("content_versions", [])
        except Exception as error:
            out.append({"title": title, "part": part, "state": f"ERROR {error}"})
            time.sleep(SLEEP)
            continue
        by_section: dict[str, set[str]] = {}
        for row in rows:
            if row.get("type") != "section" or row.get("removed"):
                continue
            by_section.setdefault(row["identifier"], set()).add(row["date"])
        multi = sum(1 for dates in by_section.values() if len(dates) >= 2)
        out.append(
            {
                "title": title,
                "part": part,
                "state": "OK" if multi >= 4 else "THIN",
                "sections": len(by_section),
                "multi_version_sections": multi,
            }
        )
        time.sleep(SLEEP)
    return out


def probe_git(candidates: list[tuple[str, str, str, str]]) -> list[dict[str, Any]]:
    out = []
    for owner, repo, prefix, branch in candidates:
        entry = {"owner": owner, "repo": repo, "prefix": prefix}
        if already_declared("git", entry):
            out.append({"repo": f"{owner}/{repo}", "state": "ALREADY_DECLARED"})
            continue
        try:
            meta = get_json(f"https://api.github.com/repos/{owner}/{repo}", github=True)
            listing = get_json(
                f"https://api.github.com/repos/{owner}/{repo}/contents/{prefix}"
                f"?ref={branch or meta.get('default_branch')}",
                github=True,
            )
        except Exception as error:
            out.append({"repo": f"{owner}/{repo}", "state": f"ERROR {error}"})
            time.sleep(SLEEP)
            continue
        files = [e for e in listing if e.get("type") == "file"] if isinstance(listing, list) else []
        dirs = [e for e in listing if e.get("type") == "dir"] if isinstance(listing, list) else []
        out.append(
            {
                "repo": f"{owner}/{repo}",
                "prefix": prefix,
                "state": "OK" if (files or dirs) else "EMPTY",
                "default_branch": meta.get("default_branch"),
                "license": (meta.get("license") or {}).get("spdx_id") or "NOASSERTION",
                "files": len(files),
                "dirs": len(dirs),
            }
        )
        time.sleep(SLEEP)
    return out


def probe_sec(start_after_cik: int, look: int, forms: tuple[str, ...]) -> dict[str, Any]:
    tickers = get_json("https://www.sec.gov/files/company_tickers.json")
    ciks = sorted({int(row["cik_str"]) for row in tickers.values()})
    above = [c for c in ciks if c > start_after_cik][:look]
    with_pairs, total_pairs = 0, 0
    for cik in above:
        try:
            body = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception:
            time.sleep(SLEEP)
            continue
        recent = body.get("filings", {}).get("recent", {})
        seen: dict[tuple[str, str], set[str]] = {}
        for form, period in zip(recent.get("form", []), recent.get("reportDate", []), strict=False):
            base = form[:-2] if form.endswith("/A") else form
            if base not in forms:
                continue
            seen.setdefault((base, period), set()).add("A" if form.endswith("/A") else "O")
        pairs = sum(1 for kinds in seen.values() if kinds == {"A", "O"})
        if pairs:
            with_pairs += 1
            total_pairs += pairs
        time.sleep(SLEEP)
    return {
        "universe_size": len(tickers),
        "distinct_ciks": len(ciks),
        "start_after_cik": start_after_cik,
        "looked_at": len(above),
        "issuers_with_pairs": with_pairs,
        "pairs_found": total_pairs,
    }


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    payload = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else {}
    if which == "ecfr":
        print(json.dumps(probe_ecfr([tuple(c) for c in payload["candidates"]]), indent=1))
    elif which == "git":
        print(json.dumps(probe_git([tuple(c) for c in payload["candidates"]]), indent=1))
    elif which == "sec":
        print(
            json.dumps(
                probe_sec(payload["start_after_cik"], payload["look"], tuple(payload["forms"])),
                indent=1,
            )
        )
