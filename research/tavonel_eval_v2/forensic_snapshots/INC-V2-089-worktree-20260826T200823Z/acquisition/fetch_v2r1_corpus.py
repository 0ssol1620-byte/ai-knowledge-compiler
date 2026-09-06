"""Fresh prospective acquisition for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1.

Runs ONLY against the frozen frame. Before a single request goes out it checks
that `sources_v2r1.py` still matches the digest rung 0 sealed -- an acquisition
that could edit its own frame mid-run would make the freeze decorative.

WHAT THIS MAY NOT DO, restated here because it is the whole point of the rung-0
freeze and a reader should not have to reconstruct it from the frame module:

  * choose a candidate by looking at revision CONTENT;
  * inspect any identity outcome, ambiguity or changed facet;
  * keep acquiring until an interesting case turns up;
  * drop a candidate because of what it turned out to contain;
  * top up an under-delivering family from a productive one.

Every rejection below is a metadata or integrity rejection, recorded with its
reason. Attrition is reported, never silently replaced.

CACHE IDENTITY IS CONTENT-ADDRESSED. INC-V2-046 is what happens when an
80-character truncated readable slug is used as a key: two distinct lineages
collided and nine collision groups had to be excluded whole. Readable slugs
survive here as labels only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(ROOT / "packages" / "cir-python" / "src"),
    str(NS),
    str(NS / "acquisition"),
    str(NS / "canonicalization"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sources_v2r1 as frame  # noqa: E402
from canonical_document import canonical_document, sha_text  # noqa: E402
from fetch_p4c_corpus import ecfr_sections  # noqa: E402

OUT = NS / "artifacts" / "development" / "v2r1_corpus"
UA = "TAVONEL Research claude23@vieworks.com"

GITHUB_SLEEP = 0.12
ECFR_SLEEP = 0.35
SEC_SLEEP = 0.20

DOC_SUFFIXES = (".md", ".mdx", ".rst", ".adoc")


class FrameNotFrozen(RuntimeError):
    """The frame on disk is not the frame rung 0 sealed."""


# --------------------------------------------------------------------------
# frame verification
# --------------------------------------------------------------------------


def require_frozen_frame() -> dict[str, Any]:
    """Refuse to fetch anything unless the frame matches its rung-0 receipt."""
    receipts = sorted(
        (NS / "receipts").glob(
            "identity-change-migration-closure-v2r1-acquisition-frame-freeze--*.json"
        )
    )
    if not receipts:
        raise FrameNotFrozen(
            "no rung-0 acquisition frame receipt exists. The frame is sealed BEFORE "
            "acquisition; fetching first would make the freeze a record of what was "
            "done rather than a constraint on what may be done."
        )
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    module = NS / "acquisition" / "sources_v2r1.py"
    current = "sha256:" + hashlib.sha256(module.read_bytes()).hexdigest()
    if body.get("frame_module_sha256") != current:
        raise FrameNotFrozen(
            "the acquisition frame changed after it was frozen.\n"
            f"  frozen:  {body.get('frame_module_sha256')}\n"
            f"  current: {current}"
        )
    return body


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------


def _headers(github: bool = False) -> dict[str, str]:
    headers = {"User-Agent": UA}
    if github:
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def get_bytes(url: str, *, github: bool = False, timeout: int = 45) -> bytes:
    request = urllib.request.Request(url, headers=_headers(github))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def get_json(url: str, *, github: bool = False, timeout: int = 45) -> Any:
    return json.loads(get_bytes(url, github=github, timeout=timeout).decode("utf-8"))


def sha_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def cache_key(lineage_id: str, side: str, raw_digest: str) -> str:
    """Content-addressed, untruncated. See INC-V2-046."""
    material = f"{lineage_id}\x00{side}\x00{raw_digest}".encode()
    return hashlib.sha256(material).hexdigest()


# --------------------------------------------------------------------------
# candidate construction -- METADATA ONLY
# --------------------------------------------------------------------------


def git_candidates(cap: int, quota: int, rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for owner, repo, prefix, branch, licence in frame.GIT_ROOTS:
        if len(out) >= quota:
            break
        container = f"{owner}/{repo}"
        try:
            tree = get_json(
                f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
                github=True,
            )
        except Exception as error:
            rejected.append(
                {"family": "git_docs", "container": container, "why": f"tree: {error}"}
            )
            continue
        time.sleep(GITHUB_SLEEP)

        paths = sorted(
            node["path"]
            for node in tree.get("tree", [])
            if node.get("type") == "blob"
            and node["path"].startswith(prefix)
            and node["path"].endswith(DOC_SUFFIXES)
            and node.get("size", 0) > 2000
        )
        taken = 0
        for path in paths:
            if taken >= cap or len(out) >= quota:
                break
            try:
                commits = get_json(
                    f"https://api.github.com/repos/{owner}/{repo}/commits"
                    f"?path={urllib.parse.quote(path)}&sha={branch}&per_page=2",
                    github=True,
                )
            except Exception as error:
                rejected.append(
                    {"family": "git_docs", "container": container, "path": path,
                     "why": f"commits: {error}"}
                )
                continue
            time.sleep(GITHUB_SLEEP)
            if not isinstance(commits, list) or len(commits) < 2:
                rejected.append(
                    {"family": "git_docs", "container": container, "path": path,
                     "why": "fewer than two revisions"}
                )
                continue
            after, before = commits[0], commits[1]
            out.append(
                {
                    "family": "git_docs",
                    "container": container,
                    "lineage_id": f"git:{owner}/{repo}:{path}",
                    "licence": licence,
                    "before": {
                        "version": before["sha"],
                        "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{before['sha']}/{path}",
                        "known_at": before["commit"]["committer"]["date"],
                    },
                    "after": {
                        "version": after["sha"],
                        "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{after['sha']}/{path}",
                        "known_at": after["commit"]["committer"]["date"],
                    },
                }
            )
            taken += 1
    return out


def ecfr_candidates(cap: int, quota: int, rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for title, part, _name in frame.ECFR_ROOTS:
        if len(out) >= quota:
            break
        container = f"{title} CFR {part}"
        try:
            rows = get_json(
                "https://www.ecfr.gov/api/versioner/v1/versions/"
                f"title-{title}.json?part={part}"
            ).get("content_versions", [])
        except Exception as error:
            rejected.append(
                {"family": "regulation_ecfr", "container": container, "why": f"versions: {error}"}
            )
            continue
        time.sleep(ECFR_SLEEP)

        by_section: dict[str, set[str]] = {}
        for row in rows:
            if row.get("type") != "section" or row.get("removed"):
                continue
            by_section.setdefault(row["identifier"], set()).add(row["date"])

        taken = 0
        for identifier in sorted(by_section):
            if taken >= cap or len(out) >= quota:
                break
            dates = sorted(by_section[identifier])
            if len(dates) < 2:
                continue
            base = (
                "https://www.ecfr.gov/api/versioner/v1/full/%s/title-%s.xml"
                "?part=%s&section=%s"
            )
            out.append(
                {
                    "family": "regulation_ecfr",
                    "container": container,
                    "lineage_id": f"ecfr:{title}:{part}:{identifier}",
                    "licence": "public domain (US government work)",
                    "before": {
                        "version": dates[-2],
                        "url": base % (dates[-2], title, part, identifier),
                    },
                    "after": {
                        "version": dates[-1],
                        "url": base % (dates[-1], title, part, identifier),
                    },
                }
            )
            taken += 1
    return out


def sec_candidates(cap: int, quota: int, rejected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rule = frame.SEC_ISSUER_RULE
    forms = set(rule["forms"])
    try:
        tickers = get_json(rule["universe"])
    except Exception as error:
        rejected.append({"family": "sec_edgar", "why": f"issuer universe: {error}"})
        return []
    issuers = sorted(tickers.values(), key=lambda row: int(row["cik_str"]))

    out: list[dict[str, Any]] = []
    for row in issuers:
        if len(out) >= quota:
            break
        cik = int(row["cik_str"])
        try:
            submissions = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        except Exception:
            time.sleep(SEC_SLEEP)
            continue
        time.sleep(SEC_SLEEP)
        recent = submissions.get("filings", {}).get("recent", {})
        zipped = zip(
            recent.get("form", []),
            recent.get("reportDate", []),
            recent.get("accessionNumber", []),
            recent.get("primaryDocument", []),
            recent.get("filingDate", []),
            strict=False,
        )
        pairs: dict[tuple[str, str], dict[str, Any]] = {}
        for form, period, accession, document, filed in zipped:
            if not period or not document:
                continue
            base_form = form[:-2] if form.endswith("/A") else form
            if base_form not in forms:
                continue
            slot = "amended" if form.endswith("/A") else "original"
            pairs.setdefault((base_form, period), {}).setdefault(
                slot, {"accession": accession, "document": document, "filed": filed}
            )

        taken = 0
        for (base_form, period), sides in sorted(pairs.items()):
            if taken >= cap or len(out) >= quota:
                break
            if "original" not in sides or "amended" not in sides:
                continue

            def url_for(entry: dict[str, Any], _cik: int = cik) -> str:
                #: `_cik` is bound at definition rather than closed over. The
                #: call happens in the same iteration today, so the closure
                #: would be correct by accident; binding makes it correct on
                #: purpose, which is the difference that survives an edit.
                accession = entry["accession"].replace("-", "")
                return (
                    f"https://www.sec.gov/Archives/edgar/data/{_cik}/"
                    f"{accession}/{entry['document']}"
                )

            out.append(
                {
                    "family": "sec_edgar",
                    "container": f"CIK{cik:010d}",
                    "lineage_id": f"sec:{cik}:{base_form}:{period}",
                    "licence": "public domain (US government work)",
                    "before": {
                        "version": sides["original"]["accession"],
                        "url": url_for(sides["original"]),
                        "known_at": sides["original"]["filed"],
                    },
                    "after": {
                        "version": sides["amended"]["accession"],
                        "url": url_for(sides["amended"]),
                        "known_at": sides["amended"]["filed"],
                    },
                }
            )
            taken += 1
    return out


# --------------------------------------------------------------------------
# fetch, verify, canonicalise
# --------------------------------------------------------------------------


def canonicalise(candidate: dict[str, Any], side: str, payload: bytes) -> dict[str, Any]:
    family = candidate["family"]
    digest = sha_bytes(payload)
    if family != "regulation_ecfr":
        return canonical_document(
            source_family=family,
            source_id=candidate["lineage_id"],
            version_id=candidate[side]["version"],
            payload=payload,
            source_digest=digest,
            known_at=candidate[side].get("known_at"),
            valid_from=None,
            licence=candidate["licence"],
        )

    #: eCFR is XML, so it cannot go through `canonical_document`'s markdown or
    #: HTML readers -- but its OUTPUT SHAPE must be identical, because
    #: `selective_build.snapshots` is what production reads and it wants
    #: `heading` and `text_sha256` on every unit.
    #:
    #: The first version of this function invented its own shape
    #: (`heading_path`, no `heading`, no `text_sha256`), which made all 106 eCFR
    #: pairs unreadable by the scorer. They would have failed as a block for a
    #: reason that has nothing to do with the migration -- the same trap
    #: INC-V2-053 records for INVARIANT_6(d). Mirrored field for field instead.
    sections = ecfr_sections(payload)
    seen: dict[tuple[str, ...], int] = {}
    units: list[dict[str, Any]] = []
    for ordinal, section in enumerate(sections):
        count = seen.get(section.path, 0)
        seen[section.path] = count + 1
        explicit = list(section.path)
        if count:
            explicit[-1] = explicit[-1] + "#" + str(count)
        units.append(
            {
                "explicit_path": explicit,
                "heading": section.heading,
                "ordinal": ordinal,
                "text": section.text,
                "text_sha256": sha_text(section.text),
            }
        )
    return {
        "schema": "tavonel.v2.canonical_document.v1",
        "source_family": family,
        "source_id": candidate["lineage_id"],
        "version_id": candidate[side]["version"],
        "version_time": {"valid_from": None, "known_at": candidate[side].get("known_at")},
        "source_digest": digest,
        "license": candidate["licence"],
        "units": units,
        "structure": {
            "order": ["/".join(unit["explicit_path"]) for unit in units],
            "block_count": len(units),
        },
    }


def acquire(
    candidates: list[dict[str, Any]], rejected: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    OUT.mkdir(parents=True, exist_ok=True)
    admitted: list[dict[str, Any]] = []
    seen_lineages: set[str] = set()

    for candidate in candidates:
        lineage = candidate["lineage_id"]
        if lineage in seen_lineages:
            rejected.append({**_slim(candidate), "why": "duplicate lineage id"})
            continue

        sides: dict[str, Any] = {}
        failed = False
        for side in ("before", "after"):
            github = candidate["family"] == "git_docs"
            try:
                payload = get_bytes(candidate[side]["url"], github=github)
            except Exception as error:
                rejected.append({**_slim(candidate), "why": f"{side} fetch: {error}"})
                failed = True
                break
            if candidate["family"] == "sec_edgar":
                time.sleep(SEC_SLEEP)
            elif candidate["family"] == "regulation_ecfr":
                time.sleep(ECFR_SLEEP)

            raw_digest = sha_bytes(payload)
            try:
                document = canonicalise(candidate, side, payload)
            except Exception as error:
                rejected.append({**_slim(candidate), "why": f"{side} canonicalise: {error}"})
                failed = True
                break
            if len(document.get("units", [])) < 3:
                rejected.append(
                    {**_slim(candidate), "why": f"{side} yielded fewer than 3 canonical units"}
                )
                failed = True
                break
            #: Recomputed, not trusted. Both digests, both sides.
            if document["source_digest"] != raw_digest:
                rejected.append({**_slim(candidate), "why": f"{side} raw digest mismatch"})
                failed = True
                break
            key = cache_key(lineage, side, raw_digest)

            #: The RAW bytes are kept beside the canonical document, not
            #: discarded. Without them "recompute the digest" degrades into
            #: "re-read the digest we wrote down", and a verification that reads
            #: back its own record verifies nothing. The freeze gate recomputes
            #: from these files.
            raw_path = OUT / f"{key}.raw"
            raw_path.write_bytes(payload)

            canonical_bytes = json.dumps(
                document, sort_keys=True, ensure_ascii=False
            ).encode("utf-8")
            canonical_path = OUT / f"{key}.json"
            canonical_path.write_bytes(canonical_bytes)

            sides[side] = {
                "cache_key": key,
                "raw_path": raw_path.name,
                "canonical_path": canonical_path.name,
                "raw_sha256_recorded": raw_digest,
                "canonical_sha256_recorded": sha_bytes(canonical_bytes),
                "canonical_digest_convention": (
                    "sha256 over json.dumps(document, sort_keys=True, "
                    "ensure_ascii=False).encode('utf-8')"
                ),
                "version": candidate[side]["version"],
                "units": len(document["units"]),
            }
        if failed:
            continue

        if sides["before"]["raw_sha256_recorded"] == sides["after"]["raw_sha256_recorded"]:
            rejected.append({**_slim(candidate), "why": "both sides carry the same raw digest"})
            continue

        seen_lineages.add(lineage)
        admitted.append(
            {
                "lineage_id": lineage,
                "family": candidate["family"],
                "container": candidate["container"],
                "licence": candidate["licence"],
                #: Named at the row level too, because the frozen
                #: `manifest_contract.required_row_fields` asks for them there.
                "before_version": candidate["before"]["version"],
                "after_version": candidate["after"]["version"],
                "before": sides["before"],
                "after": sides["after"],
            }
        )
    return admitted


def _slim(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": candidate["family"],
        "container": candidate["container"],
        "lineage_id": candidate["lineage_id"],
    }


# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--families", default="git_docs,regulation_ecfr,sec_edgar")
    args = parser.parse_args(argv)

    receipt = require_frozen_frame()
    wanted = tuple(f.strip() for f in args.families.split(",") if f.strip())

    rejected: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    builders = {
        "git_docs": git_candidates,
        "regulation_ecfr": ecfr_candidates,
        "sec_edgar": sec_candidates,
    }
    for family in frame.FAMILIES:
        if family not in wanted:
            continue
        cap = frame.CONTAINER_CAP[family]
        quota = frame.FAMILY_QUOTA[family]
        built = builders[family](cap, quota, rejected)
        print(f"[candidates] {family}: {len(built)} (quota {quota}, cap {cap})", flush=True)
        candidates.extend(built)

    print(
        f"[candidates] total {len(candidates)} (PRIMARY_TARGET {frame.PRIMARY_TARGET})",
        flush=True,
    )
    admitted = acquire(candidates, rejected)

    by_family: dict[str, int] = {}
    for row in admitted:
        by_family[row["family"]] = by_family.get(row["family"], 0) + 1

    manifest = {
        "protocol_id": frame.PROTOCOL_ID,
        "frame_module_sha256": receipt["frame_module_sha256"],
        "frame_receipt": (
            receipt.get("_receipt_path")
            or receipt.get("provenance", {}).get("run_id")
        ),
        "candidates_constructed": len(candidates),
        "admitted": admitted,
        "admitted_count": len(admitted),
        "admitted_by_family": by_family,
        "families_present": sorted(by_family),
        "rejected": rejected,
        "rejected_count": len(rejected),
        "floor": frame.FLOOR,
        "families_required": frame.FAMILIES_REQUIRED,
        "meets_floor": len(admitted) >= frame.FLOOR,
        "meets_families": len(by_family) >= frame.FAMILIES_REQUIRED,
        "attrition_note": (
            "every rejection carries its reason and nothing was silently replaced. "
            "Padding after measurement is forbidden; the realised count is whatever "
            "survived integrity and metadata filtering."
        ),
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"[admitted] {len(admitted)} across {sorted(by_family)} "
        f"-> floor {frame.FLOOR}: {'MET' if manifest['meets_floor'] else 'NOT MET'}",
        flush=True,
    )
    print(json.dumps(by_family, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
