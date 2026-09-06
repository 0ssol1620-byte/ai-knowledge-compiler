"""Availability probe for V2R4's candidate roots. METADATA ONLY.

Founder ruling section F. A capacity probe may answer "is this declared
container usable?" It may NOT answer "does this container contain convenient
V2R4 outcomes?" -- and the difference is not a matter of degree. What this probe
is permitted to ask, and nothing else:

    does this repository exist, and does this prefix hold documents
    how many sections of this CFR part carry two or more distinct dated versions
    do issuers above this CIK carry amendment pairs

It never opens revision content, never diffs, never counts a qualifying change,
never counts an ambiguity or a quarantine, never previews a pair-level result.
A count of how many section identifiers carry two dated versions is a supply
question about the SOURCE; what changed inside them is not asked.

TWO SCREENS, AND A CANDIDATE MUST CLEAR BOTH.

  1. `root_identity` -- every root any earlier sources module has ever declared,
     read through one canonicaliser across every attribute shape. UNVERIFIABLE
     BLOCKS; it is never assumed disjoint. This is the screen V2R2 lacked.

  2. `sfi3_root_reservation` -- SFI3_ROOT_RESERVATION_V1, which is STRICTLY
     WIDER than screen 1 for this purpose. It covers SFI3's declared roots AND
     its predeclared legal replacement pool, and the pool is by construction NOT
     yet declared anywhere, so screen 1 cannot see it. A container that is only
     a replacement candidate is still reserved: SFI3 may land there after an
     availability failure, and a V2R4 root sitting in the pool would silently
     narrow SFI3's escape route.

Screening happens BEFORE the network is touched, so a spent or reserved
container is never even asked about.

`encyclopedia_wikipedia` is not probed and cannot be. Reservation membership
there is by CATEGORY, which is not decidable from a root list, and the only way
to make it decidable would be to expand an SFI3 category -- spending the next
study's prospective confirmatory material to buy a disjointness argument here.
The family fails closed and is excluded, never quietly dropped.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import root_identity as ri  # noqa: E402
import sfi3_root_reservation as reservation  # noqa: E402

UA = "TAVONEL-research/1.0 (claude23@vieworks.com)"
SLEEP = 0.35

#: The study whose own frame must not screen against itself.
SELF_MODULE = "sources_v2r4"

#: Minimum documents under a declared git prefix for the root to be declarable.
#: V2R3's rule, unchanged and applied before declaration rather than after.
MIN_DOCUMENTS = 17

#: Minimum sections carrying two or more distinct dated versions for a CFR part
#: to be declarable.
MIN_MULTI_VERSION_SECTIONS = 12


class ProbeRefused(RuntimeError):
    """A candidate could not be screened, so it is not probed."""


# ---------------------------------------------------------------------------
# the two screens


def screens() -> dict[str, Any]:
    """Both screens, resolved once, before any network call."""
    prior = ri.prior_root_identities(exclude_modules={SELF_MODULE})
    if prior["unverifiable_count"]:
        raise ProbeRefused(
            "root_identity reports "
            f"{prior['unverifiable_count']} root shapes it cannot interpret: "
            f"{prior['unverifiable']}. An uninterpretable root BLOCKS. It is never "
            "assumed disjoint -- that assumption is how 7 CFR 273 entered V2R2."
        )
    held = reservation.reserved()
    return {"prior": prior["identities"], "reserved": held, "prior_report": prior}


def _git_container(owner: str, repo: str) -> str:
    return f"{owner}/{repo}"


def screen_git(candidates, *, state) -> tuple[list, list]:
    """Split git candidates into probeable and rejected, without a fetch.

    Container level, deliberately: the identity tuple carries a prefix, so the
    same repository under a different prefix reads as a different identity. A
    repository that was ever touched is not fresh for this study regardless of
    which subtree was read.
    """
    prior_repos = {
        _git_container(entry[1], entry[2]) for entry in state["prior"] if entry[0] == "git"
    }
    held = state["reserved"][reservation.FAMILY_GIT]
    keep, dropped = [], []
    for owner, repo, prefix, branch in candidates:
        container = _git_container(owner, repo)
        if container in prior_repos:
            dropped.append({"container": container, "why": "declared by an earlier study"})
        elif container in held:
            dropped.append({"container": container, "why": "inside SFI3_ROOT_RESERVATION_V1"})
        else:
            keep.append((owner, repo, prefix, branch))
    return keep, dropped


def screen_ecfr(candidates, *, state) -> tuple[list, list]:
    prior = {(entry[1], entry[2]) for entry in state["prior"] if entry[0] == "ecfr"}
    held = state["reserved"][reservation.FAMILY_ECFR]
    keep, dropped = [], []
    for title, part in candidates:
        identity = ri.canonical_identity("ecfr", (title, part, ""))
        if identity == ri.UNVERIFIABLE:
            raise ProbeRefused(
                f"eCFR candidate {title}-{part} cannot be canonicalised, so it "
                "cannot be screened. UNVERIFIABLE blocks; it is not probed."
            )
        if (title, part) in prior:
            dropped.append(
                {
                    "container": f"{title}-{part}",
                    "why": "declared by an earlier study",
                }
            )
        elif f"{title}-{part}" in held:
            dropped.append(
                {
                    "container": f"{title}-{part}",
                    "why": "inside SFI3_ROOT_RESERVATION_V1",
                }
            )
        else:
            keep.append((title, part))
    return keep, dropped


# ---------------------------------------------------------------------------
# metadata fetches


def get_json(url: str, *, github: bool = False, timeout: int = 60) -> Any:
    headers = {"User-Agent": UA}
    if github:
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


DOC_SUFFIXES = (".md", ".markdown", ".rst", ".mdx", ".adoc")
MIN_BYTES = 2000


def probe_git_root(owner: str, repo: str, prefix: str, branch: str) -> dict[str, Any]:
    """Repository metadata plus the recursive tree. No file content is read."""
    container = _git_container(owner, repo)
    try:
        meta = get_json(f"https://api.github.com/repos/{owner}/{repo}", github=True)
    except urllib.error.HTTPError as error:
        return {"container": container, "reachable": False, "why": f"HTTP {error.code}"}
    except Exception as error:  # pragma: no cover - network shapes vary
        return {"container": container, "reachable": False, "why": str(error)}

    use_branch = branch or meta.get("default_branch") or "main"
    try:
        tree = get_json(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{use_branch}?recursive=1",
            github=True,
        )
    except Exception as error:
        return {"container": container, "reachable": False, "why": f"tree: {error}"}

    wanted = prefix.rstrip("/") + "/" if prefix else ""
    documents = [
        node
        for node in tree.get("tree", [])
        if node.get("type") == "blob"
        and node.get("path", "").startswith(wanted)
        and node.get("path", "").lower().endswith(DOC_SUFFIXES)
        and (node.get("size") or 0) > MIN_BYTES
    ]
    return {
        "container": container,
        "reachable": True,
        "branch": use_branch,
        "prefix": prefix,
        "license_metadata": ((meta.get("license") or {}).get("spdx_id")) or "NOASSERTION",
        "documents": len(documents),
        "truncated": bool(tree.get("truncated")),
        "declarable": len(documents) >= MIN_DOCUMENTS,
    }


#: The versions endpoint pages at 1000 rows and says so in `meta.total_pages`.
#: Title 2 alone carries 3,350 rows across 4 pages.
VERSIONS_PER_PAGE = 1000


def title_versions(title: str) -> list[dict]:
    """EVERY content version in a title, following pagination to the last page.

    The first version of this function read the response and stopped. That is a
    silent truncation with a specific direction: it UNDERSTATES supply, and it
    understates it unevenly across titles, so a rule that ranks parts by supply
    was ranking them by "supply visible on page 1". Title 2 returned 1,000 of
    3,350 rows and part 180 looked like 20 multi-version sections when it has
    117.

    The page count is READ from `meta.total_pages` rather than inferred from a
    short page, because a full last page and a truncated one look identical from
    the row count alone. A response whose meta says more pages exist than were
    fetched RAISES: a partial supply reading that reports itself as complete is
    the defect this function was repaired for.
    """
    base = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json"
    first = get_json(base, timeout=300)
    rows = list(first.get("content_versions", []))
    meta = first.get("meta") or {}
    total_pages = int(meta.get("total_pages") or 1)

    for page in range(2, total_pages + 1):
        body = get_json(f"{base}?page={page}", timeout=300)
        rows.extend(body.get("content_versions", []))
        time.sleep(0.3)

    declared = int(meta.get("result_count") or len(rows))
    if len(rows) < declared:
        raise ProbeRefused(
            f"title {title}: the versions endpoint reports {declared} rows and "
            f"{total_pages} page(s), but only {len(rows)} were read. A supply count "
            "taken from a truncated response understates capacity and silently "
            "re-ranks every part below it."
        )
    return rows


#: The date the structure is read at. A part's existence is a fact about a
#: snapshot, so the snapshot is pinned rather than left as "now".
STRUCTURE_DATE = "2026-08-01"


def live_parts(title: str) -> dict[str, str]:
    """Parts that EXIST in the current structure, mapped to the eCFR's own label.

    The versions endpoint carries section version HISTORY, and a part can vanish
    from the structure while that history remains -- title 39 part 3004 has 20
    multi-version sections on record and is not in the CFR today. Supply counted
    from history is therefore not proof the container is usable, which is the one
    question a capacity probe exists to answer. A part with history and no live
    container is an availability failure, and finding it at declaration time is
    the whole point of probing before declaring.
    """
    url = f"https://www.ecfr.gov/api/versioner/v1/structure/{STRUCTURE_DATE}/title-{title}.json"
    found: dict[str, str] = {}

    def walk(node: Any) -> None:
        if node.get("type") == "part":
            found[str(node.get("identifier"))] = (
                node.get("label_description") or node.get("label") or ""
            )
        for child in node.get("children") or ():
            walk(child)

    walk(get_json(url, timeout=300))
    return found


def probe_ecfr_title(title: str, *, state) -> list[dict[str, Any]]:
    """Supply per PART within one title. Blind by construction.

    Two calls, not one: supply from the versions endpoint, existence and label
    from the structure endpoint. Both are metadata about the SOURCE; neither
    reads what changed inside a section.
    """
    rows = title_versions(title)
    live = live_parts(title)
    by_part: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for row in rows:
        if row.get("type") != "section" or row.get("removed"):
            continue
        by_part[str(row.get("part"))][row["identifier"]].add(row["date"])

    out: list[dict[str, Any]] = []
    for part, sections in by_part.items():
        keep, _dropped = screen_ecfr([(title, part)], state=state)
        if not keep:
            continue
        multi = sum(1 for dates in sections.values() if len(dates) >= 2)
        if multi < MIN_MULTI_VERSION_SECTIONS:
            continue
        label = live.get(part)
        out.append(
            {
                "container": f"{title}-{part}",
                "title": title,
                "part": part,
                "sections": len(sections),
                "multi_version_sections": multi,
                # The eCFR's OWN label, copied. A composed label would be this
                # frame inventing provenance metadata for a container it did not
                # name.
                "subject": label or "",
                "declarable": bool(label),
                "why": None if label else "no longer present in the current CFR structure",
            }
        )
    out.sort(key=lambda row: (-row["multi_version_sections"], row["part"]))
    return out


SEC_UNIVERSE = "https://www.sec.gov/files/company_tickers.json"
SEC_FORMS = ("10-K", "10-Q", "20-F", "8-K")


def probe_sec(start_after_cik: int, sample: int = 30) -> dict[str, Any]:
    """Amendment-pair supply above a CIK. Form types and periods only."""
    universe = get_json(SEC_UNIVERSE)
    ciks = sorted({int(row["cik_str"]) for row in universe.values()})
    above = [cik for cik in ciks if cik > start_after_cik]
    probed, with_pairs, pairs = 0, 0, 0
    unreachable: list[dict[str, str]] = []
    for cik in above[:sample]:
        try:
            body = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception as error:  # the failure is recorded below, never swallowed
            unreachable.append({"cik": f"{cik:010d}", "why": str(error)})
            time.sleep(SLEEP)
            continue
        recent = body.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        periods = recent.get("reportDate", [])
        seen: dict[tuple[str, str], set[bool]] = defaultdict(set)
        for form, period in zip(forms, periods, strict=False):
            base = form[:-2] if form.endswith("/A") else form
            if base in SEC_FORMS and period:
                seen[(base, period)].add(form.endswith("/A"))
        found = sum(1 for states in seen.values() if states == {True, False})
        probed += 1
        if found:
            with_pairs += 1
            pairs += found
        time.sleep(SLEEP)
    return {
        "universe": SEC_UNIVERSE,
        "universe_size": len(universe),
        "distinct_ciks": len(ciks),
        "start_after_cik": start_after_cik,
        "issuers_above": len(above),
        "probed": probed,
        "issuers_with_amendment_pairs": with_pairs,
        "pairs_among_probed": pairs,
        "unreachable": unreachable,
        "forms": list(SEC_FORMS),
    }


# ---------------------------------------------------------------------------
# what this probe refuses to be asked

FORBIDDEN_QUESTIONS: tuple[str, ...] = (
    "revision content",
    "diff content",
    "qualifying change counts",
    "ambiguity counts",
    "quarantine counts",
    "invariant outcomes",
    "facet transitions",
    "pair-level scientific result previews",
)


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - operator entry
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--git", default="", help="owner:repo:prefix:branch, comma separated")
    parser.add_argument("--ecfr-titles", default="", help="CFR titles, comma separated")
    parser.add_argument("--sec-start-after", type=int, default=0)
    parser.add_argument("--sec-sample", type=int, default=30)
    args = parser.parse_args(argv)

    state = screens()
    out: dict[str, Any] = {
        "screens": {
            "prior_identities": len(state["prior"]),
            "reserved_for_sfi3": {k: len(v) for k, v in state["reserved"].items()},
            "reservation_id": reservation.RESERVATION_ID,
        },
        "forbidden_questions": list(FORBIDDEN_QUESTIONS),
    }

    if args.git:
        candidates = [tuple(item.split(":")) for item in args.git.split(",") if item]
        keep, dropped = screen_git(candidates, state=state)
        out["git_screened_out"] = dropped
        rows = []
        for owner, repo, prefix, branch in keep:
            rows.append(probe_git_root(owner, repo, prefix, branch))
            time.sleep(SLEEP)
        out["git"] = rows

    if args.ecfr_titles:
        rows = {}
        for title in args.ecfr_titles.split(","):
            rows[title] = probe_ecfr_title(title.strip(), state=state)
            time.sleep(0.4)
        out["ecfr"] = rows

    if args.sec_start_after:
        out["sec"] = probe_sec(args.sec_start_after, args.sec_sample)

    print(json.dumps(out, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
