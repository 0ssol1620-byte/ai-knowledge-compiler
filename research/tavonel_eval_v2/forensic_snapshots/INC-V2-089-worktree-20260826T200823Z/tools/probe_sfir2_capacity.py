"""Enumerate SFIR2's finite metadata universe with per-root dispositions.

HTTP 404/409/451 and demonstrably unavailable/truncated roots become explicit
ZERO_CANDIDATE_ROOT_DISPOSITION records.  Authentication failure, exhausted
rate limits, malformed metadata and unknown partial state terminate the study.
No adapter reads payload text or revision diffs.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import sfir2_protocol as protocol

try:
    from acquisition import sources_sfir2 as sources
except ImportError:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from acquisition import sources_sfir2 as sources

Transport = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]


class RateLimited(RuntimeError):
    pass


class RootUnavailable(RuntimeError):
    def __init__(self, status: int, response_ref: str):
        self.status, self.response_ref = status, response_ref
        super().__init__(f"HTTP_{status}")


def _http_json(url: str) -> Mapping[str, Any] | list[Any]:
    headers = {"User-Agent": "TAVONEL-SFIR2-capacity-probe/1.0", "Accept": "application/json"}
    if url.startswith("https://api.github.com/"):
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 -- frozen HTTPS hosts
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- frozen HTTPS hosts
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_size = int(declared)
                except (TypeError, ValueError) as error:
                    raise protocol.SFIR2Refused("metadata Content-Length is malformed") from error
                if declared_size < 0 or declared_size > sources.MAX_METADATA_RESPONSE_BYTES:
                    raise protocol.SFIR2Refused("metadata Content-Length exceeds the frozen bound")
            raw = bytearray()
            while True:
                block = response.read(sources.METADATA_READ_BLOCK_BYTES)
                if not block:
                    break
                raw.extend(block)
                if len(raw) > sources.MAX_METADATA_RESPONSE_BYTES:
                    raise protocol.SFIR2Refused(
                        "streamed metadata response exceeds the frozen bound"
                    )
            if declared is not None and len(raw) != declared_size:
                raise protocol.SFIR2Refused(
                    "metadata response ended before declared Content-Length"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in sources.PAGINATION_CONTRACT["zero_candidate_http_statuses"]:
            raise RootUnavailable(error.code, url) from error
        if error.code in sources.PAGINATION_CONTRACT["terminal_http_statuses"]:
            raise protocol.SFIR2Refused(
                f"authenticated metadata access failed: HTTP {error.code}"
            ) from error
        if error.code in sources.PAGINATION_CONTRACT["retryable_http_statuses"]:
            raise RateLimited(str(error.code)) from error
        raise protocol.SFIR2Refused(f"unknown metadata HTTP state {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise protocol.SFIR2Refused("unknown partial metadata response") from error


def _zero(
    discovery_root: str, reason: str, refs: list[str], next_cursor: str | None
) -> dict[str, Any]:
    return {
        "items": [],
        "next_cursor": next_cursor,
        "snapshot_id": f"zero:{discovery_root}:{reason}",
        "response_refs": refs,
        "rate_limited": False,
        "root_disposition": {
            "discovery_root_id": discovery_root,
            "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
            "reason": reason,
        },
    }


class LiveMetadataTransport:
    def __init__(self, fetch_json: Callable[[str], Mapping[str, Any] | list[Any]] = _http_json):
        self.fetch_json = fetch_json
        self._wiki_seen: set[int] = set()

    def __call__(self, family: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            return {
                "git_docs": self._git,
                "regulation_ecfr": self._ecfr,
                "encyclopedia_wikipedia": self._wiki,
            }[family](request)
        except RateLimited:
            root = request["expected_discovery_root_id"]
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"rate-limited:{root}",
                "response_refs": [],
                "rate_limited": True,
                "root_disposition": None,
            }

    @staticmethod
    def _next(index: int, length: int) -> str | None:
        return str(index + 1) if index + 1 < length else None

    def _git(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        repos = pool["repositories"]
        if index >= len(repos):
            raise protocol.SFIR2Refused("Git cursor escaped the frozen roots")
        repo = repos[index]
        root_id = sources.discovery_root_id("git_docs", repo)
        refs: list[str] = []
        meta_url = f"https://api.github.com/repos/{repo}"
        refs.append(meta_url)
        try:
            meta = self.fetch_json(meta_url)
            if not isinstance(meta, Mapping) or not isinstance(meta.get("default_branch"), str):
                raise protocol.SFIR2Refused("Git repository metadata malformed")
            branch = str(meta["default_branch"])
            encoded_branch = urllib.parse.quote(branch, safe="")
            tree_url = f"https://api.github.com/repos/{repo}/git/trees/{encoded_branch}?recursive=1"
            refs.append(tree_url)
            tree = self.fetch_json(tree_url)
        except RootUnavailable as error:
            return _zero(
                root_id,
                f"HTTP_{error.status}",
                [*refs, error.response_ref],
                self._next(index, len(repos)),
            )
        if not isinstance(tree, Mapping) or not isinstance(tree.get("tree"), list):
            raise protocol.SFIR2Refused("Git tree response malformed")
        if tree.get("truncated") is True:
            return _zero(
                root_id, "TRUNCATED_OR_INCOMPLETE_ENUMERATION", refs, self._next(index, len(repos))
            )
        paths = sorted(
            (
                str(node["path"])
                for node in tree["tree"]
                if isinstance(node, Mapping)
                and node.get("type") == "blob"
                and isinstance(node.get("path"), str)
                and str(node["path"]).casefold().endswith(tuple(pool["extensions"]))
            ),
            key=lambda path: hashlib.sha256(
                (sources.SELECTION_SALT + "\0" + repo + "\0" + path).encode()
            ).hexdigest(),
        )
        items: list[dict[str, Any]] = []
        for path in paths[: pool["max_candidates_per_repository"]]:
            url = f"https://api.github.com/repos/{repo}/commits?path={urllib.parse.quote(path)}&sha={urllib.parse.quote(branch)}&per_page=2"
            refs.append(url)
            try:
                commits = self.fetch_json(url)
            except RootUnavailable as error:
                return _zero(
                    root_id,
                    f"HTTP_{error.status}_DURING_ROOT_ENUMERATION",
                    [*refs, error.response_ref],
                    self._next(index, len(repos)),
                )
            if not isinstance(commits, list):
                raise protocol.SFIR2Refused("Git commit metadata malformed")
            if len(commits) < 2:
                continue
            try:
                after, before = commits[0], commits[1]
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
                raise protocol.SFIR2Refused("Git commit metadata malformed") from error
        snapshot_version = tree.get("sha") or meta.get("updated_at") or sources.SELECTION_SALT
        snapshot = f"github:{repo}:{branch}:{snapshot_version}"
        return {
            "items": items,
            "next_cursor": self._next(index, len(repos)),
            "snapshot_id": snapshot,
            "response_refs": refs,
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": root_id,
                "state": "COMPLETE",
                "reason": "ENUMERATION_EXHAUSTED",
            },
        }

    def _ecfr(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        titles = pool["titles"]
        if index >= len(titles):
            raise protocol.SFIR2Refused("eCFR cursor escaped frozen roots")
        title = titles[index]
        root_id = sources.discovery_root_id("regulation_ecfr", title)
        base = f"https://www.ecfr.gov/api/versioner/v1/versions/title-{title}.json"
        refs = [base]
        try:
            first = self.fetch_json(base)
        except RootUnavailable as error:
            return _zero(
                root_id,
                f"HTTP_{error.status}",
                [*refs, error.response_ref],
                self._next(index, len(titles)),
            )
        if not isinstance(first, Mapping) or not isinstance(
            first.get("content_versions", []), list
        ):
            raise protocol.SFIR2Refused("eCFR metadata malformed")
        rows = list(first.get("content_versions") or [])
        record_bound = pool["max_version_records_per_title"]
        if len(rows) > record_bound:
            raise protocol.SFIR2Refused("eCFR version-record bound exceeded")
        meta = first.get("meta") or {}
        if not isinstance(meta, Mapping):
            raise protocol.SFIR2Refused("eCFR pagination metadata malformed")
        pages = int(meta.get("total_pages") or 1)
        if pages > pool["max_version_pages_per_title"]:
            return _zero(
                root_id, "TRUNCATED_OR_INCOMPLETE_ENUMERATION", refs, self._next(index, len(titles))
            )
        for page in range(2, pages + 1):
            url = f"{base}?page={page}"
            refs.append(url)
            try:
                body = self.fetch_json(url)
            except RootUnavailable as error:
                return _zero(
                    root_id,
                    f"HTTP_{error.status}_DURING_ROOT_ENUMERATION",
                    [*refs, error.response_ref],
                    self._next(index, len(titles)),
                )
            if not isinstance(body, Mapping) or not isinstance(
                body.get("content_versions", []), list
            ):
                raise protocol.SFIR2Refused("eCFR page malformed")
            rows.extend(body.get("content_versions") or [])
            if len(rows) > record_bound:
                raise protocol.SFIR2Refused("eCFR version-record bound exceeded")
        if len(rows) < int(meta.get("result_count") or len(rows)):
            return _zero(
                root_id, "TRUNCATED_OR_INCOMPLETE_ENUMERATION", refs, self._next(index, len(titles))
            )
        versions: dict[tuple[str, str], set[str]] = {}
        for row in rows:
            if (
                isinstance(row, Mapping)
                and row.get("type") == "section"
                and not row.get("removed")
                and isinstance(row.get("part"), (str, int))
                and isinstance(row.get("identifier"), str)
                and isinstance(row.get("date"), str)
            ):
                versions.setdefault((str(row["part"]), str(row["identifier"])), set()).add(
                    str(row["date"])
                )
        eligible = [
            (part, section, sorted(dates)[-2:])
            for (part, section), dates in versions.items()
            if len(dates) >= 2
        ]
        eligible.sort(
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
                "section": section,
                "version_before": dates[0],
                "version_after": dates[1],
                "timestamp_before": dates[0] + "T00:00:00Z",
                "timestamp_after": dates[1] + "T00:00:00Z",
            }
            for part, section, dates in eligible[: pool["max_candidates_per_title"]]
        ]
        return {
            "items": items,
            "next_cursor": self._next(index, len(titles)),
            "snapshot_id": (
                f"ecfr:title:{title}:{meta.get('latest_date') or sources.SELECTION_SALT}"
            ),
            "response_refs": refs,
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": root_id,
                "state": "COMPLETE",
                "reason": "ENUMERATION_EXHAUSTED",
            },
        }

    def _wiki(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        index = int(request.get("cursor") or 0)
        categories = pool["category_roots"]
        if index >= len(categories):
            raise protocol.SFIR2Refused("Wikipedia cursor escaped frozen roots")
        category = categories[index]
        root_id = sources.discovery_root_id("encyclopedia_wikipedia", category)
        refs: list[str] = []
        members: dict[int, str] = {}
        continuation: Mapping[str, Any] = {}
        page_count = 0
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
            params.update(continuation)
            url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
            refs.append(url)
            try:
                body = self.fetch_json(url)
            except RootUnavailable as error:
                return _zero(
                    root_id,
                    f"HTTP_{error.status}",
                    [*refs, error.response_ref],
                    self._next(index, len(categories)),
                )
            if not isinstance(body, Mapping) or not isinstance(
                (body.get("query") or {}).get("categorymembers", []), list
            ):
                raise protocol.SFIR2Refused("Wikipedia category metadata malformed")
            page_count += 1
            if page_count > pool["max_category_pages_per_root"]:
                return _zero(
                    root_id,
                    "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
                    refs,
                    self._next(index, len(categories)),
                )
            for member in (body.get("query") or {}).get("categorymembers") or []:
                if (
                    isinstance(member, Mapping)
                    and isinstance(member.get("pageid"), int)
                    and isinstance(member.get("title"), str)
                ):
                    members[int(member["pageid"])] = str(member["title"])
            continuation = body.get("continue") or {}
            if not isinstance(continuation, Mapping):
                raise protocol.SFIR2Refused("Wikipedia continuation malformed")
            if not continuation:
                break
        ordered = sorted(
            members,
            key=lambda page_id: hashlib.sha256(
                (sources.SELECTION_SALT + "\0" + category + "\0" + str(page_id)).encode()
            ).hexdigest(),
        )
        selected = [page_id for page_id in ordered if page_id not in self._wiki_seen][
            : pool["max_candidates_per_category"]
        ]
        items: list[dict[str, Any]] = []
        for start in range(0, len(selected), pool["revision_batch_size"]):
            batch = selected[start : start + pool["revision_batch_size"]]
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
            url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
            refs.append(url)
            try:
                body = self.fetch_json(url)
            except RootUnavailable as error:
                return _zero(
                    root_id,
                    f"HTTP_{error.status}_DURING_ROOT_ENUMERATION",
                    [*refs, error.response_ref],
                    self._next(index, len(categories)),
                )
            if not isinstance(body, Mapping) or not isinstance(
                (body.get("query") or {}).get("pages", []), list
            ):
                raise protocol.SFIR2Refused("Wikipedia revision metadata malformed")
            seen_batch: set[int] = set()
            for page in (body.get("query") or {}).get("pages") or []:
                if not isinstance(page, Mapping) or not isinstance(page.get("pageid"), int):
                    raise protocol.SFIR2Refused("Wikipedia page metadata malformed")
                page_id = int(page["pageid"])
                seen_batch.add(page_id)
                revisions = page.get("revisions") or []
                if page.get("redirect") is True or len(revisions) < 2:
                    continue
                after, before = revisions[0], revisions[1]
                aliases = [
                    str(row["title"])
                    for row in page.get("redirects") or []
                    if isinstance(row, Mapping) and isinstance(row.get("title"), str)
                ]
                items.append(
                    {
                        "category": category,
                        "page_id": page_id,
                        "title": page.get("title") or members[page_id],
                        "aliases": aliases,
                        "redirect": False,
                        "revision_before": str(before.get("revid") or ""),
                        "revision_after": str(after.get("revid") or ""),
                        "timestamp_before": before.get("timestamp"),
                        "timestamp_after": after.get("timestamp"),
                    }
                )
            if seen_batch != set(batch):
                return _zero(
                    root_id,
                    "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
                    refs,
                    self._next(index, len(categories)),
                )
        self._wiki_seen.update(selected)
        return {
            "items": items,
            "next_cursor": self._next(index, len(categories)),
            "snapshot_id": f"mediawiki:{category}:{sources.SELECTION_SALT}",
            "response_refs": refs,
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": root_id,
                "state": "COMPLETE",
                "reason": "ENUMERATION_EXHAUSTED",
            },
        }


def _pair(before: Any, after: Any, label: str) -> dict[str, str]:
    if not isinstance(before, str) or not before or not isinstance(after, str) or not after:
        raise protocol.SFIR2Refused(f"{label} revision pair incomplete")
    return {"before": before, "after": after}


def _candidate(family: str, item: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]] | None:
    if family == "git_docs":
        repo, path = item.get("repository"), item.get("path")
        if repo not in sources.SOURCE_POOLS[family]["repositories"] or not isinstance(path, str):
            raise protocol.SFIR2Refused("Git item escaped frozen roots")
        root = discovery = sources.discovery_root_id(family, repo)
        container = lineage = f"git:{repo}:{path}"
        ids = _pair(item.get("commit_before"), item.get("commit_after"), family)
        aliases: set[str] = set()
        refs = {key: f"github://{repo}/blob/{ids[key]}/{path}" for key in ids}
    elif family == "regulation_ecfr":
        title, part, section = item.get("title"), item.get("part"), item.get("section")
        if (
            title not in sources.SOURCE_POOLS[family]["titles"]
            or not isinstance(part, str)
            or not isinstance(section, str)
        ):
            raise protocol.SFIR2Refused("eCFR item escaped frozen roots")
        discovery = sources.discovery_root_id(family, title)
        root = sources.root_container_id(family, title=str(title), part=part)
        container = lineage = f"ecfr:{title}:{part}:{section}"
        ids = _pair(item.get("version_before"), item.get("version_after"), family)
        aliases = set()
        refs = {
            key: f"ecfr://title/{title}/part/{part}/section/{section}?version={ids[key]}"
            for key in ids
        }
    else:
        category, page_id = item.get("category"), item.get("page_id")
        if category not in sources.SOURCE_POOLS[family]["category_roots"] or not isinstance(
            page_id, int
        ):
            raise protocol.SFIR2Refused("Wikipedia item escaped frozen roots")
        if item.get("redirect") is True:
            return None
        discovery = root = sources.discovery_root_id(family, category)
        container = f"wikipedia:en:pageid:{page_id}"
        lineage = f"wiki:en:{page_id}"
        ids = _pair(item.get("revision_before"), item.get("revision_after"), family)
        refs = {
            key: f"mediawiki://en.wikipedia.org/page/{page_id}/revision/{ids[key]}" for key in ids
        }
        aliases = {f"wiki:en:title:{str(item.get('title')).casefold()}"}
        aliases.update(f"wiki:en:title:{str(v).casefold()}" for v in item.get("aliases", []))
    timestamps = _pair(item.get("timestamp_before"), item.get("timestamp_after"), family)
    if ids["before"] == ids["after"] or timestamps["before"] >= timestamps["after"]:
        raise protocol.SFIR2Refused(f"{family} revision chronology invalid")
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + lineage).encode()).digest()[0]
    row = {
        "discovery_root_id": discovery,
        "root_container_id": root,
        "lineage_id": lineage,
        "family": family,
        "container_id": container,
        "alias_ids": sorted(aliases),
        "payload_ref": refs,
        "revision_id": ids,
        "revision_timestamp": timestamps,
        "capability_exercise": {
            "E5": not bool(bits & 1),
            "E6": not bool(bits & 2),
            "E9": not bool(bits & 4),
        },
    }
    return row, aliases


def probe_capacity(
    root: Path,
    charter_path: Path,
    charter_sha256: str,
    spent_ref: Mapping[str, Any],
    destination: Path,
    transport: Transport,
) -> Path:
    charter = protocol.verify_authority(root, charter_path, charter_sha256, protocol.CHARTER_SCHEMA)
    if protocol.sha_file(Path(__file__)) != charter["toolchain"]["probe_sfir2_capacity"]["sha256"]:
        raise protocol.SFIR2Refused("running probe differs from frozen charter")
    spent = protocol.verify_spent_authority(root, spent_ref)
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    families: dict[str, Any] = {}
    for family in sources.FAMILIES:
        roots = sources.declared_roots(family)
        cursor: str | None = None
        retries = pages = 0
        seen: set[str] = set()
        candidates: dict[str, dict[str, Any]] = {}
        dispositions: list[dict[str, Any]] = []
        snapshots: list[str] = []
        response_refs: list[str] = []
        for index, declared_root in enumerate(roots):
            expected = sources.discovery_root_id(family, declared_root)
            current_retries = 0
            while True:
                response = transport(
                    family,
                    {
                        "cursor": cursor,
                        "pool": sources.SOURCE_POOLS[family],
                        "metadata_only": True,
                        "expected_discovery_root_id": expected,
                    },
                )
                protocol._assert_metadata_only(response)
                if response.get("rate_limited") is True:
                    current_retries += 1
                    retries += 1
                    if current_retries > sources.PAGINATION_CONTRACT["maximum_retries_per_request"]:
                        raise protocol.SFIR2Refused(f"{family} rate-limit retry budget exhausted")
                    continue
                required = {
                    "items",
                    "next_cursor",
                    "snapshot_id",
                    "response_refs",
                    "rate_limited",
                    "root_disposition",
                }
                if (
                    set(response) != required
                    or not isinstance(response["items"], list)
                    or not isinstance(response["response_refs"], list)
                ):
                    raise protocol.SFIR2Refused(f"{family} response shape malformed")
                disposition = response["root_disposition"]
                if (
                    not isinstance(disposition, Mapping)
                    or disposition.get("discovery_root_id") != expected
                    or disposition.get("state")
                    not in {"COMPLETE", "ZERO_CANDIDATE_ROOT_DISPOSITION"}
                ):
                    raise protocol.SFIR2Refused(f"{family} root disposition malformed")
                if disposition["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION" and response["items"]:
                    raise protocol.SFIR2Refused("zero-candidate root emitted candidates")
                if (
                    not isinstance(response.get("snapshot_id"), str)
                    or not response["snapshot_id"]
                    or not response["response_refs"]
                    or any(
                        not isinstance(value, str) or not value
                        for value in response["response_refs"]
                    )
                ):
                    raise protocol.SFIR2Refused(
                        f"{family} root response lacks exact snapshot/response references"
                    )
                accepted_for_root = 0
                for item in response["items"]:
                    if not isinstance(item, Mapping):
                        raise protocol.SFIR2Refused("non-object candidate metadata")
                    made = _candidate(family, item)
                    if made is None:
                        continue
                    row, aliases = made
                    if row["discovery_root_id"] != expected:
                        raise protocol.SFIR2Refused("candidate escaped current root")
                    if {
                        row["root_container_id"],
                        row["container_id"],
                        row["lineage_id"],
                        *aliases,
                    } & spent_ids:
                        continue
                    if row["lineage_id"] in candidates:
                        raise protocol.SFIR2Refused("duplicate lineage")
                    candidates[row["lineage_id"]] = row
                    accepted_for_root += 1
                per_root_cap = {
                    "git_docs": "max_candidates_per_repository",
                    "regulation_ecfr": "max_candidates_per_title",
                    "encyclopedia_wikipedia": "max_candidates_per_category",
                }[family]
                if accepted_for_root > sources.SOURCE_POOLS[family][per_root_cap]:
                    raise protocol.SFIR2Refused(f"{family} per-root candidate cap exceeded")
                dispositions.append(
                    {
                        **dict(disposition),
                        "snapshot_ref": str(response["snapshot_id"]),
                        "response_refs": [str(value) for value in response["response_refs"]],
                    }
                )
                snapshots.append(str(response["snapshot_id"]))
                response_refs.extend(str(v) for v in response["response_refs"])
                pages += 1
                next_cursor = response["next_cursor"]
                expected_next = str(index + 1) if index + 1 < len(roots) else None
                if next_cursor != expected_next:
                    raise protocol.SFIR2Refused(f"{family} cursor does not exhaust finite roots")
                if next_cursor is not None and next_cursor in seen:
                    raise protocol.SFIR2Refused(f"{family} repeated cursor")
                if next_cursor is not None:
                    seen.add(next_cursor)
                cursor = next_cursor
                break
        if cursor is not None or len(dispositions) != len(roots):
            raise protocol.SFIR2Refused(f"{family} finite root enumeration incomplete")
        if len(candidates) > sources.SOURCE_POOLS[family]["max_total_candidates"]:
            raise protocol.SFIR2Refused(f"{family} candidate cap exceeded")
        families[family] = {
            "authority": sources.FAMILY_AUTHORITIES[family],
            "snapshot_refs": snapshots,
            "response_refs": response_refs,
            "root_dispositions": dispositions,
            "pagination": {
                "pages_fetched": pages,
                "exhausted": True,
                "rate_limit_retries": retries,
                "cap_reached": False,
            },
            "candidates": sorted(candidates.values(), key=lambda row: row["lineage_id"]),
        }
    body = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "protocol_id": protocol.PROTOCOL_ID,
        "families": families,
    }
    protocol._assert_metadata_only(body)
    return protocol._write_immutable(destination, body)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--charter", type=Path, required=True)
    parser.add_argument("--charter-sha256", required=True)
    parser.add_argument("--spent", type=Path, required=True)
    parser.add_argument("--spent-sha256", required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--live", action="store_true", required=True)
    args = parser.parse_args(argv)
    path = probe_capacity(
        args.root,
        args.charter,
        args.charter_sha256,
        protocol.exact_ref(args.root, args.spent, args.spent_sha256),
        args.destination,
        LiveMetadataTransport(),
    )
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
