"""Freeze the real revision-pair corpus.

    py -3.13 -m benchmark.revision_pairs.build_corpus --cache-dir <outside repo> \
        --seed 20261116 --target-pairs 100 --write-manifest benchmark/revision_pairs/manifest.json
    py -3.13 -m benchmark.revision_pairs.build_corpus --cache-dir <...> --verify

Upstream is only ever fetched by commit SHA (NIST) or dated point (eCFR). Dates the
upstream does not state stay null. Pairs are never padded: a short corpus is reported.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import http.client
import itertools
import json
import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from benchmark.revision_pairs.to_product_core import (
    DEFAULT_MANIFEST,
    CorpusError,
    docs_from_catalog,
    docs_from_ecfr_xml,
    family_docs,
    read_verified,
    sha256_hex,
)

Fetch = Callable[[str], bytes]

REPO = "usnistgov/oscal-content"
CATALOG_PATH = "nist.gov/SP800-53/rev5/json/NIST_SP-800-53_rev5_catalog.json"
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.MD", "LICENSE.rst")
ECFR = "https://www.ecfr.gov/api/versioner/v1"


class NotFound(CorpusError):
    """HTTP 404 - distinct so callers can decide whether absence is a fact or a failure."""


def http_fetch(url: str) -> bytes:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise CorpusError(f"refusing non-https url {url}")
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    connection = http.client.HTTPSConnection(parts.hostname, timeout=120)
    try:
        connection.request(
            "GET", path, headers={"User-Agent": "tavonel-corpus", "Accept-Encoding": "gzip"}
        )
        response = connection.getresponse()
        body = response.read()
        if response.status == 404:
            raise NotFound(f"404 {url}")
        if response.status != 200:
            raise CorpusError(f"HTTP {response.status} for {url}")
        return gzip.decompress(body) if response.getheader("content-encoding") == "gzip" else body
    except (OSError, http.client.HTTPException) as error:
        raise CorpusError(f"fetch failed for {url}: {error}") from error
    finally:
        connection.close()


def _tag_key(name: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", name))


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fetch_nist(fetch: Fetch, cache_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    tags: list[dict[str, Any]] = []
    page = 1
    while True:
        chunk = json.loads(
            fetch(f"https://api.github.com/repos/{REPO}/tags?per_page=100&page={page}")
        )
        tags += chunk
        if len(chunk) < 100:
            break
        page += 1
    snapshots: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in sorted(
        tags, key=lambda t: _tag_key(t["name"])
    ):  # oldest first: earliest tag per version wins
        sha = tag["commit"]["sha"]
        url = f"https://raw.githubusercontent.com/{REPO}/{sha}/{CATALOG_PATH}"
        try:
            raw = fetch(url)
        except NotFound:
            skipped.append(
                {"tag": tag["name"], "commit_sha": sha, "reason": "no rev5 catalog at this commit"}
            )
            continue
        meta = json.loads(raw)["catalog"]["metadata"]
        version = meta["version"]
        if version in seen:
            continue
        seen.add(version)
        _write(cache_dir / sha / "catalog.json", raw)
        snapshots.append(
            {
                "tag": tag["name"],
                "commit_sha": sha,
                "url": url,
                "sha256": sha256_hex(raw),
                "version": version,
                "published": meta.get("published"),
                "last_modified": meta.get("last-modified"),
                "license": fetch_license(fetch, sha, cache_dir),
            }
        )
    return snapshots, skipped


def fetch_license(fetch: Fetch, sha: str, cache_dir: Path) -> dict[str, str]:
    for name in LICENSE_NAMES:
        try:
            raw = fetch(f"https://raw.githubusercontent.com/{REPO}/{sha}/{name}")
        except NotFound:
            continue
        _write(cache_dir / sha / name, raw)
        first = next(
            (ln.strip() for ln in raw.decode("utf-8", "replace").splitlines() if ln.strip()), ""
        )
        return {"file": name, "sha256": sha256_hex(raw), "first_line": first}
    raise CorpusError(f"no LICENSE at pinned commit {sha}; stopping (readable is not reusable)")


def fetch_ecfr(fetch: Fetch, cache_dir: Path) -> list[dict[str, Any]]:
    rows = json.loads(fetch(f"{ECFR}/versions/title-2.json?part=200"))["content_versions"]
    snapshots: list[dict[str, Any]] = []
    for date in sorted({r["amendment_date"] for r in rows if r.get("amendment_date")}):
        issued = {
            r["issue_date"] for r in rows if r.get("amendment_date") == date and r.get("issue_date")
        }
        raw = fetch(f"{ECFR}/full/{date}/title-2.xml?part=200")
        _write(cache_dir / "ecfr" / f"{date}.xml", raw)
        snapshots.append(
            {
                "date": date,
                "url": f"{ECFR}/full/{date}/title-2.xml?part=200",
                "sha256": sha256_hex(raw),
                "valid_from": date,
                "available_at": next(iter(issued)) if len(issued) == 1 else None,
            }
        )
    return snapshots


def stratum(
    before: dict[str, str], after: dict[str, str], before_w: frozenset[str], after_w: frozenset[str]
) -> str:
    added = set(after) - set(before)
    withdrawn = ((after_w - before_w) & set(after)) | (set(before) - set(after))
    modified = {k for k in set(before) & set(after) if before[k] != after[k]} - withdrawn
    kinds = [
        n
        for n, s in (
            ("modified", modified),
            ("controls_added", added),
            ("controls_withdrawn", withdrawn),
        )
        if s
    ]
    return "unchanged" if not kinds else kinds[0] if len(kinds) == 1 else "mixed"


def candidates(manifest: dict[str, Any], cache_dir: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source, snaps, key in (
        ("nist-oscal", manifest["snapshots"], "commit_sha"),
        ("ecfr", manifest["ecfr_snapshots"], "date"),
    ):
        if not snaps:
            continue
        derived = {s[key]: _all_families(manifest, source, s[key], cache_dir) for s in snaps}
        keys = [s[key] for s in snaps]
        # NIST: every release pair; eCFR: consecutive amendment dates only.
        pairs = (
            itertools.combinations(keys, 2) if source == "nist-oscal" else itertools.pairwise(keys)
        )
        prefix = "nist" if source == "nist-oscal" else "ecfr"
        for a, b in pairs:
            for family in sorted(set(derived[a]) & set(derived[b])):
                (da, wa), (db, wb) = derived[a][family], derived[b][family]
                ha = {k: d.content_sha256 for k, d in da.items()}
                hb = {k: d.content_sha256 for k, d in db.items()}
                va = _label(manifest, source, a)
                vb = _label(manifest, source, b)
                out.append(
                    {
                        "pair_id": f"{prefix}-{family}-{va}-{vb}",
                        "source": source,
                        "family": family,
                        "stratum": stratum(ha, hb, wa, wb),
                        "before": {"snapshot": a, "docs": ha},
                        "after": {"snapshot": b, "docs": hb},
                    }
                )
    return out


def _all_families(
    manifest: dict[str, Any], source: str, key: str, cache_dir: Path
) -> dict[str, Any]:
    if source == "nist-oscal":
        snap = next((s for s in manifest["snapshots"] if s["commit_sha"] == key), None)
        if snap is None:
            raise CorpusError(f"snapshot {key} not in manifest")
        raw = read_verified(cache_dir / key / "catalog.json", snap["sha256"])
        return docs_from_catalog(json.loads(raw))
    snap = next((s for s in manifest["ecfr_snapshots"] if s["date"] == key), None)
    if snap is None:
        raise CorpusError(f"eCFR snapshot {key} not in manifest")
    return docs_from_ecfr_xml(read_verified(cache_dir / "ecfr" / f"{key}.xml", snap["sha256"]), key)


def _label(manifest: dict[str, Any], source: str, key: str) -> str:
    if source == "nist-oscal":
        return str(next(s["version"] for s in manifest["snapshots"] if s["commit_sha"] == key))
    return key


def select_pairs(cands: list[dict[str, Any]], target: int, seed: int) -> list[dict[str, Any]]:
    """Changed pairs first, unchanged fill; each group in a seed-keyed hash order; never padded."""

    def order(c: dict[str, Any]) -> str:
        return hashlib.sha256(f"{seed}:{c['pair_id']}".encode()).hexdigest()

    changed = sorted((c for c in cands if c["stratum"] != "unchanged"), key=order)
    same = sorted((c for c in cands if c["stratum"] == "unchanged"), key=order)
    return sorted((changed + same)[:target], key=lambda c: c["pair_id"])


def build(
    cache_dir: Path,
    seed: int,
    target_pairs: int,
    fetch: Fetch = http_fetch,
    *,
    include_ecfr: bool = True,
) -> dict[str, Any]:
    snapshots, skipped = fetch_nist(fetch, cache_dir)
    manifest: dict[str, Any] = {
        "schema": "tavonel.revision_pairs.manifest.v1",
        "provenance": "real_published_revision",
        "seed": seed,
        "target_pairs": target_pairs,
        "snapshots": snapshots,
        "skipped_tags": skipped,
        "ecfr_snapshots": [],
        "ecfr_status": "not_needed",
    }
    cands = candidates(manifest, cache_dir)
    if len(cands) < target_pairs:
        if include_ecfr:
            manifest["ecfr_snapshots"] = fetch_ecfr(fetch, cache_dir)
            manifest["ecfr_status"] = "added_because_nist_pairs_below_target"
            cands = candidates(manifest, cache_dir)
        else:
            manifest["ecfr_status"] = "not_requested"
    chosen = select_pairs(cands, target_pairs, seed)
    manifest["pairs"] = chosen
    manifest["real_pair_count"] = len(chosen)
    manifest["shortfall"] = max(0, target_pairs - len(chosen))
    return manifest


def verify(manifest_path: Path, cache_dir: Path) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for pair in manifest["pairs"]:
        for side in ("before", "after"):
            ref = pair[side]
            docs, _ = family_docs(
                manifest, pair["source"], ref["snapshot"], pair["family"], cache_dir
            )
            if {k: d.content_sha256 for k, d in docs.items()} != ref["docs"]:
                raise CorpusError(
                    f"{pair['pair_id']} {side}: document hashes differ from the manifest"
                )
    return len(manifest["pairs"])


def render_rights(manifest: dict[str, Any]) -> str:
    lines = [
        "# Revision-pair corpus rights record",
        "",
        "Dataset row only. Code, model-weight and hosted-API terms are separate licences.",
        "A public repository without a LICENSE grants no reuse;",
        "the builder stops if one is missing.",
        "",
        "## NIST SP 800-53 Rev. 5 OSCAL (usnistgov/oscal-content, pinned by commit SHA)",
        "",
        "| tag | commit | version | LICENSE file | LICENSE sha256 | first line |",
        "|---|---|---|---|---|---|",
    ]
    for s in manifest["snapshots"]:
        lic = s["license"]
        lines.append(
            f"| {s['tag']} | {s['commit_sha']} | {s['version']} | {lic['file']} "
            f"| {lic['sha256']} | {lic['first_line'].lstrip('# ')} |"
        )
    if manifest["ecfr_snapshots"]:
        lines += [
            "",
            "## eCFR 2 CFR Part 200 (versioner API)",
            "",
            "No LICENSE file exists for this source. The work order treats it as a",
            "US-government work;",
            "that premise is not verified by this builder and the register row must say so.",
        ]
    lines += [
        "",
        "The technology-intake register row is requested from the lead (shared file).",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=20261116)
    ap.add_argument("--target-pairs", type=int, default=100)
    ap.add_argument("--write-manifest", type=Path)
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="manifest for --verify")
    ap.add_argument("--no-ecfr", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    if args.verify:
        print(f"verified {verify(args.manifest, args.cache_dir)} pairs")
        return 0
    manifest = build(args.cache_dir, args.seed, args.target_pairs, include_ecfr=not args.no_ecfr)
    print(
        f"real pairs: {manifest['real_pair_count']} / target {args.target_pairs} "
        f"(shortfall {manifest['shortfall']})"
    )
    if args.write_manifest:
        args.write_manifest.write_text(
            json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.write_manifest.parent / "RIGHTS.md").write_text(
            render_rights(manifest), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
