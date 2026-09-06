"""Enumerate the frozen SFIR1 metadata universe without opening payloads.

The probe is deliberately adapter-shaped: production transports may call the
three declared metadata APIs, while tests inject deterministic pages.  Neither
interface accepts nor emits document text, diffs, parsed units or SourceFacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import sfir1_protocol as protocol

try:
    from acquisition import sources_sfir1 as sources
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir1 as sources


Transport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class RateLimited(RuntimeError):
    pass


def _http_json(url: str) -> Mapping[str, Any] | list[Any]:
    headers = {"User-Agent": "TAVONEL-SFIR1-capacity-probe/1.0", "Accept": "application/json"}
    if url.startswith("https://api.github.com/"):
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - frozen HTTPS hosts only
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in sources.PAGINATION_CONTRACT["retryable_http_statuses"]:
            raise RateLimited(str(error.code)) from error
        raise protocol.SFIR1Refused(f"metadata API HTTP {error.code}") from error


class LiveMetadataTransport:
    """Audited adapters for the three frozen public metadata APIs.

    Returned pages contain identity/revision metadata only.  Git trees refuse
    GitHub's ``truncated`` flag; eCFR follows ``meta.total_pages``; MediaWiki
    follows its opaque ``continue`` token.
    """

    def __init__(self, fetch_json: Callable[[str], Mapping[str, Any] | list[Any]] = _http_json):
        self.fetch_json = fetch_json
        self._wiki_seen_page_ids: set[int] = set()

    def __call__(self, family: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            if family == "git_docs":
                return self._git(request)
            if family == "regulation_ecfr":
                return self._ecfr(request)
            if family == "encyclopedia_wikipedia":
                return self._wikipedia(request)
        except RateLimited:
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"rate-limited:{family}",
                "rate_limited": True,
            }
        raise protocol.SFIR1Refused(f"unknown metadata family {family}")

    def _git(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        repos = pool["repositories"]
        if index >= len(repos):
            raise protocol.SFIR1Refused("git cursor escaped frozen repositories")
        repo = repos[index]
        meta = self.fetch_json(f"https://api.github.com/repos/{repo}")
        if not isinstance(meta, Mapping):
            raise protocol.SFIR1Refused("GitHub repository metadata malformed")
        branch = meta.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise protocol.SFIR1Refused("GitHub default branch unavailable")
        tree = self.fetch_json(
            f"https://api.github.com/repos/{repo}/git/trees/{urllib.parse.quote(branch, safe='')}?recursive=1"
        )
        if (
            not isinstance(tree, Mapping)
            or tree.get("truncated") is True
            or not isinstance(tree.get("tree"), list)
        ):
            raise protocol.SFIR1Refused(f"GitHub tree incomplete for {repo}")
        eligible = sorted(
            str(node["path"])
            for node in tree["tree"]
            if isinstance(node, Mapping)
            and node.get("type") == "blob"
            and isinstance(node.get("path"), str)
            and str(node["path"]).casefold().endswith(tuple(pool["extensions"]))
        )
        eligible.sort(
            key=lambda path: hashlib.sha256(
                (sources.SELECTION_SALT + "\0" + repo + "\0" + path).encode()
            ).hexdigest()
        )
        items: list[dict[str, Any]] = []
        for path in eligible[: pool["max_candidates_per_repository"]]:
            url = f"https://api.github.com/repos/{repo}/commits?path={urllib.parse.quote(path)}&sha={urllib.parse.quote(branch)}&per_page=2"
            commits = self.fetch_json(url)
            if not isinstance(commits, list) or len(commits) < 2:
                continue
            after, before = commits[0], commits[1]
            try:
                items.append(
                    {
                        "repository": repo,
                        "path": path,
                        "commit_before": before["sha"],
                        "commit_after": after["sha"],
                        "timestamp_before": before["commit"]["committer"]["date"],
                        "timestamp_after": after["commit"]["committer"]["date"],
                    }
                )
            except (KeyError, TypeError) as error:
                raise protocol.SFIR1Refused("GitHub commit metadata malformed") from error
        return {
            "items": items,
            "next_cursor": str(index + 1) if index + 1 < len(repos) else None,
            "snapshot_id": "git-pool:" + sources.SELECTION_SALT,
            "rate_limited": False,
        }

    def _ecfr(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        title = pool["titles"][index]
        base = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json"
        first = self.fetch_json(base)
        if not isinstance(first, Mapping):
            raise protocol.SFIR1Refused("eCFR version metadata malformed")
        rows = list(first.get("content_versions") or [])
        meta = first.get("meta") or {}
        total_pages = int(meta.get("total_pages") or 1)
        if total_pages > pool["max_version_pages_per_title"]:
            raise protocol.SFIR1Refused(f"eCFR title {title} exceeds frozen page ceiling")
        for page in range(2, total_pages + 1):
            body = self.fetch_json(f"{base}?page={page}")
            if not isinstance(body, Mapping):
                raise protocol.SFIR1Refused("eCFR pagination metadata malformed")
            rows.extend(body.get("content_versions") or [])
        if len(rows) < int(meta.get("result_count") or len(rows)):
            raise protocol.SFIR1Refused(f"eCFR title {title} pagination is incomplete")
        by_section: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            if (
                isinstance(row, Mapping)
                and row.get("type") == "section"
                and not row.get("removed")
                and isinstance(row.get("part"), (str, int))
                and isinstance(row.get("identifier"), str)
                and isinstance(row.get("date"), str)
            ):
                by_section.setdefault((str(row["part"]), row["identifier"]), set()).add(row["date"])
        sections = [
            (part, identifier, sorted(dates)[-2:])
            for (part, identifier), dates in by_section.items()
            if len(dates) >= 2
        ]
        sections.sort(
            key=lambda row: hashlib.sha256(
                (
                    sources.SELECTION_SALT + "\0" + str(title) + "\0" + row[0] + "\0" + row[1]
                ).encode()
            ).hexdigest()
        )
        items = [
            {
                "title": title,
                "part": part,
                "section": identifier,
                "version_before": dates[0],
                "version_after": dates[1],
                "timestamp_before": dates[0] + "T00:00:00Z",
                "timestamp_after": dates[1] + "T00:00:00Z",
            }
            for part, identifier, dates in sections[: pool["max_candidates_per_title"]]
        ]
        return {
            "items": items,
            "next_cursor": str(index + 1) if index + 1 < len(pool["titles"]) else None,
            "snapshot_id": "ecfr-pool:" + sources.SELECTION_SALT,
            "rate_limited": False,
        }

    def _wikipedia(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        categories = pool["category_roots"]
        if index >= len(categories):
            raise protocol.SFIR1Refused("MediaWiki cursor escaped frozen categories")
        category = categories[index]
        members: dict[int, str] = {}
        category_continue: Mapping[str, Any] = {}
        pages = 0
        while True:
            params: dict[str, Any] = {
                "action": "query",
                "list": "categorymembers",
                "cmtitle": "Category:" + category,
                "cmnamespace": pool["namespace"],
                "cmtype": "page",
                "cmlimit": pool["category_page_size"],
                "format": "json",
                "formatversion": 2,
            }
            params.update(category_continue)
            body = self.fetch_json(
                "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
            )
            if not isinstance(body, Mapping):
                raise protocol.SFIR1Refused("MediaWiki category metadata malformed")
            pages += 1
            if pages > pool["max_category_pages_per_root"]:
                raise protocol.SFIR1Refused(
                    f"MediaWiki category {category} exceeds frozen page ceiling"
                )
            for member in (body.get("query") or {}).get("categorymembers") or []:
                if isinstance(member.get("pageid"), int) and isinstance(member.get("title"), str):
                    members[member["pageid"]] = member["title"]
            category_continue = body.get("continue") or {}
            if not category_continue:
                break
        ordered = sorted(
            members,
            key=lambda page_id: hashlib.sha256(
                (sources.SELECTION_SALT + "\0" + category + "\0" + str(page_id)).encode()
            ).hexdigest(),
        )
        selected = [page_id for page_id in ordered if page_id not in self._wiki_seen_page_ids][
            : pool["max_candidates_per_category"]
        ]
        items: list[dict[str, Any]] = []
        for start in range(0, len(selected), pool["revision_batch_size"]):
            batch = selected[start : start + pool["revision_batch_size"]]
            aliases: dict[int, set[str]] = {page_id: set() for page_id in batch}
            page_rows: dict[int, Mapping[str, Any]] = {}
            redirect_continue: Mapping[str, Any] = {}
            while True:
                params = {
                    "action": "query",
                    "pageids": "|".join(map(str, batch)),
                    "prop": "revisions|info|redirects",
                    "rvlimit": 2,
                    "rvprop": "ids|timestamp",
                    "rdlimit": "max",
                    "format": "json",
                    "formatversion": 2,
                }
                params.update(redirect_continue)
                body = self.fetch_json(
                    "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
                )
                if not isinstance(body, Mapping):
                    raise protocol.SFIR1Refused("MediaWiki revision metadata malformed")
                for page in (body.get("query") or {}).get("pages") or []:
                    if isinstance(page.get("pageid"), int):
                        page_rows[page["pageid"]] = page
                        aliases[page["pageid"]].update(
                            str(row["title"])
                            for row in page.get("redirects") or []
                            if isinstance(row.get("title"), str)
                        )
                redirect_continue = body.get("continue") or {}
                if not redirect_continue:
                    break
            for page_id in batch:
                page = page_rows.get(page_id) or {}
                revisions = page.get("revisions") or []
                if len(revisions) < 2:
                    continue
                after, before = revisions[0], revisions[1]
                items.append(
                    {
                        "category": category,
                        "page_id": page_id,
                        "title": page.get("title") or members[page_id],
                        "aliases": sorted(aliases[page_id]),
                        "redirect": "redirect" in page,
                        "revision_before": str(before.get("revid") or ""),
                        "revision_after": str(after.get("revid") or ""),
                        "timestamp_before": before.get("timestamp"),
                        "timestamp_after": after.get("timestamp"),
                    }
                )
        self._wiki_seen_page_ids.update(selected)
        return {
            "items": items,
            "next_cursor": str(index + 1) if index + 1 < len(categories) else None,
            "snapshot_id": "mediawiki-en:" + sources.SELECTION_SALT,
            "rate_limited": False,
        }


def _pair(before: Any, after: Any, label: str) -> dict[str, str]:
    if not isinstance(before, str) or not before or not isinstance(after, str) or not after:
        raise protocol.SFIR1Refused(f"{label} revision pair is incomplete")
    return {"before": before, "after": after}


def _flags(lineage_id: str) -> dict[str, bool]:
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + lineage_id).encode()).digest()[0]
    return {"E5": not bool(bits & 1), "E6": not bool(bits & 2), "E9": not bool(bits & 4)}


def _candidate(family: str, item: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]] | None:
    if family == "git_docs":
        repo, path = item.get("repository"), item.get("path")
        if not isinstance(repo, str) or repo not in sources.SOURCE_POOLS[family]["repositories"]:
            raise protocol.SFIR1Refused("git item escaped the frozen repository pool")
        if not isinstance(path, str) or not path.casefold().endswith(
            tuple(sources.SOURCE_POOLS[family]["extensions"])
        ):
            return None
        root_container = sources.root_container_id(family, repository=repo)
        container, lineage = f"git:{repo}:{path}", f"git:{repo}:{path}"
        ids = _pair(item.get("commit_before"), item.get("commit_after"), "git")
        refs = {k: f"github://{repo}/blob/{ids[k]}/{path}" for k in ("before", "after")}
        aliases: set[str] = set()
    elif family == "regulation_ecfr":
        title, part, section = item.get("title"), item.get("part"), item.get("section")
        if (
            title not in sources.SOURCE_POOLS[family]["titles"]
            or not isinstance(part, str)
            or not part
            or not isinstance(section, str)
            or not section
        ):
            raise protocol.SFIR1Refused("eCFR item escaped the frozen title pool")
        root_container = sources.root_container_id(family, title=str(title), part=part)
        container, lineage = f"ecfr:{title}:{part}:{section}", f"ecfr:{title}:{part}:{section}"
        ids = _pair(item.get("version_before"), item.get("version_after"), "eCFR")
        refs = {
            k: f"ecfr://title/{title}/part/{part}/section/{section}?version={ids[k]}"
            for k in ("before", "after")
        }
        aliases = set()
    elif family == "encyclopedia_wikipedia":
        category = item.get("category")
        if (
            not isinstance(category, str)
            or category not in sources.SOURCE_POOLS[family]["category_roots"]
        ):
            raise protocol.SFIR1Refused("Wikipedia item escaped the frozen category-root pool")
        root_container = sources.root_container_id(family, category=category)
        page_id = item.get("page_id")
        if not isinstance(page_id, int):
            raise protocol.SFIR1Refused("Wikipedia page_id is not an integer")
        if item.get("redirect") is True:
            return None
        container = f"wikipedia:en:pageid:{page_id}"
        lineage = f"wiki:en:{page_id}"
        ids = _pair(item.get("revision_before"), item.get("revision_after"), "Wikipedia")
        refs = {
            k: f"mediawiki://en.wikipedia.org/page/{page_id}/revision/{ids[k]}"
            for k in ("before", "after")
        }
        title = item.get("title")
        aliases = {f"wiki:en:title:{str(title).casefold()}"} if isinstance(title, str) else set()
        raw_aliases = item.get("aliases", [])
        if not isinstance(raw_aliases, list) or any(not isinstance(v, str) for v in raw_aliases):
            raise protocol.SFIR1Refused("Wikipedia aliases are malformed")
        aliases.update(f"wiki:en:title:{v.casefold()}" for v in raw_aliases)
    else:
        raise protocol.SFIR1Refused(f"unknown family {family}")
    timestamps = _pair(item.get("timestamp_before"), item.get("timestamp_after"), family)
    if ids["before"] == ids["after"] or timestamps["before"] >= timestamps["after"]:
        raise protocol.SFIR1Refused(f"{family} revisions are not a chronological immutable pair")
    return (
        {
            "root_container_id": root_container,
            "lineage_id": lineage,
            "family": family,
            "container_id": container,
            "alias_ids": sorted(aliases),
            "payload_ref": refs,
            "revision_id": ids,
            "revision_timestamp": timestamps,
            "capability_exercise": _flags(lineage),
        },
        aliases,
    )


def probe_capacity(
    root: Path,
    charter_path: Path,
    charter_sha256: str,
    spent_subject: Mapping[str, str],
    destination: Path,
    transport: Transport,
) -> Path:
    charter = protocol.verify_authority(root, charter_path, charter_sha256, protocol.CHARTER_SCHEMA)
    expected_probe = charter["toolchain"]["probe_sfir1_capacity"]
    if protocol.sha_file(Path(__file__)) != expected_probe["sha256"]:
        raise protocol.SFIR1Refused("running probe differs from the pre-census charter binding")
    spent = protocol._verify_spent_authority(root, spent_subject)
    spent_containers = set(spent["container_ids"])
    spent_lineages = set(spent["lineage_ids"])
    spent_aliases = set(spent["alias_ids"])
    families: dict[str, Any] = {}
    for family in sources.FAMILIES:
        pool = sources.SOURCE_POOLS[family]
        cursor: str | None = None
        pages = total_retries = current_retries = 0
        seen_cursors: set[str] = set()
        accepted: dict[str, dict[str, Any]] = {}
        snapshot_ids: set[str] = set()
        page_ceilings = [int(v) for k, v in pool.items() if "pages" in k and k.startswith("max_")]
        page_ceiling = max(page_ceilings) if page_ceilings else 50000
        while True:
            if pages >= page_ceiling:
                raise protocol.SFIR1Refused(f"{family} exceeded its frozen pagination ceiling")
            response = transport(family, {"cursor": cursor, "pool": pool, "metadata_only": True})
            protocol._assert_metadata_only(response)
            if response.get("rate_limited") is True:
                current_retries += 1
                total_retries += 1
                if current_retries > sources.PAGINATION_CONTRACT["maximum_retries_per_request"]:
                    raise protocol.SFIR1Refused(f"{family} rate-limit retry budget exhausted")
                continue
            if set(response) != {"items", "next_cursor", "snapshot_id", "rate_limited"}:
                raise protocol.SFIR1Refused(f"{family} transport response shape drifted")
            if not isinstance(response["items"], list) or not isinstance(
                response["snapshot_id"], str
            ):
                raise protocol.SFIR1Refused(f"{family} transport metadata is malformed")
            pages += 1
            current_retries = 0
            snapshot_ids.add(response["snapshot_id"])
            for item in response["items"]:
                if not isinstance(item, Mapping):
                    raise protocol.SFIR1Refused(f"{family} emitted a non-object metadata item")
                made = _candidate(family, item)
                if made is None:
                    continue
                row, aliases = made
                candidate_ids = {
                    row["root_container_id"],
                    row["container_id"],
                    row["lineage_id"],
                    *aliases,
                }
                if candidate_ids & (spent_containers | spent_lineages | spent_aliases):
                    continue
                if row["lineage_id"] in accepted:
                    raise protocol.SFIR1Refused(f"{family} repeated a lineage across pages")
                accepted[row["lineage_id"]] = row
                if len(accepted) > pool["max_total_candidates"]:
                    raise protocol.SFIR1Refused(
                        f"{family} candidate cap reached before pagination exhaustion"
                    )
            next_cursor = response["next_cursor"]
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen_cursors:
                raise protocol.SFIR1Refused(f"{family} pagination cursor repeated or malformed")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        if len(snapshot_ids) != 1:
            raise protocol.SFIR1Refused(f"{family} snapshot changed during pagination")
        families[family] = {
            "authority": sources.FAMILY_AUTHORITIES[family],
            "snapshot_id": next(iter(snapshot_ids)),
            "pagination": {
                "pages_fetched": pages,
                "exhausted": True,
                "rate_limit_retries": total_retries,
                "cap_reached": False,
            },
            "candidates": sorted(accepted.values(), key=lambda row: row["lineage_id"]),
        }
    body = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "protocol_id": protocol.PROTOCOL_ID,
        "families": families,
    }
    protocol._assert_metadata_only(body)
    return protocol._write_immutable(destination, body)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--charter", type=Path, required=True)
    parser.add_argument("--charter-sha256", required=True)
    parser.add_argument("--spent", type=Path, required=True)
    parser.add_argument("--spent-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--responses", type=Path)
    args = parser.parse_args(argv)
    spent_ref = protocol.exact_ref(args.root, args.spent, args.spent_sha256)
    if args.live:
        transport: Transport = LiveMetadataTransport()
    else:
        pages = json.loads(args.responses.read_text(encoding="utf-8"))
        positions = {family: 0 for family in sources.FAMILIES}

        def transport(family: str, _request: Mapping[str, Any]) -> Mapping[str, Any]:
            index = positions[family]
            positions[family] += 1
            try:
                return pages[family][index]
            except (KeyError, IndexError) as error:
                raise protocol.SFIR1Refused(
                    f"missing audited response page for {family}"
                ) from error

    path = probe_capacity(
        args.root, args.charter, args.charter_sha256, spent_ref, args.destination, transport
    )
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
