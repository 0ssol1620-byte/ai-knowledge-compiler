"""SFIR4 capacity transport with immutable non-recursive Git-tree BFS.

The unchanged eCFR/Wikipedia metadata algorithms are reused through an exact
charter-bound adapter.  No payload text or revision diff is opened here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import probe_sfir3_capacity as legacy_metadata
import sfir4_protocol as protocol
from acquisition import sources_sfir4 as sources


class RateLimited(RuntimeError):
    def __init__(self, retry_after_seconds: int):
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate limited; retry after {retry_after_seconds}s")


class MetadataResponseBoundExceeded(RuntimeError):
    pass


class GitRequestBoundExceeded(RuntimeError):
    pass


class RootUnavailable(RuntimeError):
    def __init__(self, status: int, response_ref: str):
        self.status, self.response_ref = status, response_ref
        super().__init__(f"HTTP_{status}")


def _http_json(url: str) -> Mapping[str, Any] | list[Any]:
    headers = {"User-Agent": "TAVONEL-SFIR4-capacity-probe/1.0", "Accept": "application/json"}
    if url.startswith("https://api.github.com/"):
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    size = int(declared)
                except (TypeError, ValueError) as error:
                    raise protocol.SFIR4Refused("metadata Content-Length is malformed") from error
                if size < 0 or size > sources.MAX_METADATA_RESPONSE_BYTES:
                    raise MetadataResponseBoundExceeded(
                        "metadata Content-Length exceeds the frozen bound"
                    )
            raw = bytearray()
            while True:
                block = response.read(sources.METADATA_READ_BLOCK_BYTES)
                if not block:
                    break
                raw.extend(block)
                if len(raw) > sources.MAX_METADATA_RESPONSE_BYTES:
                    raise MetadataResponseBoundExceeded(
                        "streamed metadata response exceeds the frozen bound"
                    )
            if declared is not None and len(raw) != size:
                raise protocol.SFIR4Refused(
                    "metadata response ended before declared Content-Length"
                )
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.code in sources.PAGINATION_CONTRACT["unavailable_http_statuses"]:
            raise RootUnavailable(error.code, url) from error
        if error.code in {403, 429}:
            remaining = error.headers.get("X-RateLimit-Remaining") if error.headers else None
            retry_after = error.headers.get("Retry-After") if error.headers else None
            reset = error.headers.get("X-RateLimit-Reset") if error.headers else None
            if error.code == 429 or remaining == "0" or retry_after is not None:
                try:
                    if retry_after is not None:
                        delay = max(1, int(float(retry_after)))
                    elif reset is not None:
                        delay = max(1, int(reset) - int(time.time()) + 1)
                    else:
                        delay = sources.MAX_RATE_LIMIT_WAIT_SECONDS + 1
                except (TypeError, ValueError):
                    delay = sources.MAX_RATE_LIMIT_WAIT_SECONDS + 1
                raise RateLimited(delay) from error
        if error.code in sources.PAGINATION_CONTRACT["terminal_http_statuses"]:
            raise protocol.SFIR4Refused(
                f"authenticated metadata access failed: HTTP {error.code}"
            ) from error
        if error.code in sources.PAGINATION_CONTRACT["retryable_http_statuses"]:
            raise RateLimited(sources.RETRYABLE_HTTP_BACKOFF_SECONDS) from error
        raise protocol.SFIR4Refused(f"unknown metadata HTTP state {error.code}") from error
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise protocol.SFIR4Refused("unknown partial metadata response") from error


def _response_size(value: object) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _disposition(
    root_id: str, state: str, reason: str, refs: list[str], proof: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "items": [],
        "snapshot_id": f"sfir4:{root_id}:{state}:{reason}",
        "response_refs": refs,
        "rate_limited": False,
        "root_disposition": {
            "discovery_root_id": root_id,
            "state": state,
            "reason": reason,
            "traversal_proof": dict(proof),
        },
    }


class LiveMetadataTransport:
    def __init__(self, fetch_json: Callable[[str], Mapping[str, Any] | list[Any]] = _http_json):
        self.fetch_json = fetch_json
        self._global_git_request_count = 0

        def legacy_fetch(url: str) -> Mapping[str, Any] | list[Any]:
            try:
                return fetch_json(url)
            except RootUnavailable as error:
                raise legacy_metadata.RootUnavailable(error.status, error.response_ref) from error
            except RateLimited as error:
                raise legacy_metadata.RateLimited(str(error.retry_after_seconds)) from error

        self._legacy = legacy_metadata.LiveMetadataTransport(legacy_fetch)

    def __call__(self, family: str, request: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            if family == "git_docs":
                return self._git(request)
            # These algorithms and their exact file hash are bound into the SFIR4
            # charter. Their frozen roots are identical and SFIR3 never reached them.
            if family == "regulation_ecfr":
                return self._legacy._ecfr(request)
            if family == "encyclopedia_wikipedia":
                return self._legacy._wiki(request)
            raise protocol.SFIR4Refused("unknown family")
        except RateLimited as error:
            root = str(request["expected_discovery_root_id"])
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"rate-limited:{root}",
                "response_refs": [],
                "rate_limited": True,
                "retry_after_seconds": error.retry_after_seconds,
                "root_disposition": None,
            }
        except legacy_metadata.RateLimited:
            root = str(request["expected_discovery_root_id"])
            return {
                "items": [],
                "next_cursor": request.get("cursor"),
                "snapshot_id": f"rate-limited:{root}",
                "response_refs": [],
                "rate_limited": True,
                "retry_after_seconds": sources.RETRYABLE_HTTP_BACKOFF_SECONDS,
                "root_disposition": None,
            }

    def _git(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        pool = request["pool"]
        repo = str(request["repository"])
        root_id = sources.discovery_root_id("git_docs", repo)
        if request.get("expected_discovery_root_id") != root_id or repo not in pool["repositories"]:
            raise protocol.SFIR4Refused("Git request escaped frozen roots")
        refs: list[str] = []
        request_count = 0
        global_requests_before_root = self._global_git_request_count

        def fetch(url: str) -> Mapping[str, Any] | list[Any]:
            nonlocal request_count
            if "recursive" in url.casefold():
                raise protocol.SFIR4Refused("recursive Git tree request is forbidden")
            if (
                request_count >= sources.MAX_GIT_API_REQUESTS_PER_ROOT
                or self._global_git_request_count >= sources.MAX_GIT_API_REQUESTS_GLOBAL
            ):
                raise GitRequestBoundExceeded("Git API request bound exceeded")
            request_count += 1
            self._global_git_request_count += 1
            refs.append(url)
            return self.fetch_json(url)

        proof: dict[str, Any] = {
            "algorithm": "IMMUTABLE_NONRECURSIVE_TREE_BFS",
            "queue_exhausted": False,
            "tree_objects_fetched": 0,
            "api_requests": 0,
            "global_requests_before_root": global_requests_before_root,
            "global_api_requests": global_requests_before_root,
            "response_ref_count": 0,
            "remaining_queue_entries": 0,
            "aggregate_tree_metadata_bytes": 0,
            "discovered_doc_paths": 0,
            "retained_doc_paths": 0,
            "path_to_sha_entries": 0,
            "peak_queue_entries": 0,
            "peak_path_to_sha_entries": 0,
            "history_paths_completed": 0,
        }

        def excluded_or_unavailable(state: str, reason: str) -> dict[str, Any]:
            proof.update(
                {
                    "api_requests": request_count,
                    "global_api_requests": self._global_git_request_count,
                    "response_ref_count": len(refs),
                }
            )
            return _disposition(root_id, state, reason, refs, proof)

        try:
            meta = fetch(f"https://api.github.com/repos/{repo}")
            if not isinstance(meta, Mapping) or not isinstance(meta.get("default_branch"), str):
                raise protocol.SFIR4Refused("Git repository metadata malformed")
            branch = urllib.parse.quote(str(meta["default_branch"]), safe="")
            head = fetch(f"https://api.github.com/repos/{repo}/commits/{branch}")
        except RootUnavailable as error:
            return excluded_or_unavailable("UNAVAILABLE_ROOT_DISPOSITION", f"HTTP_{error.status}")
        try:
            head_sha = str(head["sha"])
            root_tree_sha = str(head["commit"]["tree"]["sha"])
        except (KeyError, TypeError) as error:
            raise protocol.SFIR4Refused("Git immutable head/tree metadata malformed") from error
        if len(head_sha) != 40 or len(root_tree_sha) != 40:
            raise protocol.SFIR4Refused("Git immutable head/tree identity malformed")

        queue: deque[tuple[str, str]] = deque([(root_tree_sha, "")])
        path_to_sha = {"": root_tree_sha}
        peak_queue_entries = 1
        peak_path_to_sha_entries = 1
        proof.update(
            {
                "remaining_queue_entries": 1,
                "path_to_sha_entries": 1,
                "peak_queue_entries": 1,
                "peak_path_to_sha_entries": 1,
            }
        )
        visited: set[tuple[str, str]] = set()
        retained_doc_paths: dict[str, str] = {}
        doc_paths_seen = 0
        aggregate_bytes = 0
        while queue:
            if (
                len(visited) >= sources.MAX_GIT_TREE_OBJECTS_PER_ROOT
                or len(queue) > sources.MAX_GIT_TREE_QUEUE_ENTRIES
                or len(visited) + len(queue) > sources.MAX_GIT_TRAVERSAL_IDENTITIES_PER_ROOT
            ):
                proof.update(
                    {
                        "tree_objects_fetched": len(visited),
                        "api_requests": request_count,
                        "remaining_queue_entries": len(queue),
                        "path_to_sha_entries": len(path_to_sha),
                        "peak_queue_entries": peak_queue_entries,
                        "peak_path_to_sha_entries": peak_path_to_sha_entries,
                    }
                )
                return excluded_or_unavailable(
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "TREE_BFS_BOUND_BEFORE_QUEUE_EXHAUSTION",
                )
            tree_sha, prefix = queue.popleft()
            try:
                tree = fetch(f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}")
            except (MetadataResponseBoundExceeded, GitRequestBoundExceeded):
                proof.update(
                    {
                        "tree_objects_fetched": len(visited),
                        "api_requests": min(request_count, sources.MAX_GIT_API_REQUESTS_PER_ROOT),
                        "remaining_queue_entries": len(queue) + 1,
                    }
                )
                return excluded_or_unavailable(
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "TREE_RESPONSE_OR_REQUEST_BOUND_BEFORE_QUEUE_EXHAUSTION",
                )
            size = _response_size(tree)
            aggregate_bytes += size
            proof["aggregate_tree_metadata_bytes"] = aggregate_bytes
            if (
                size > sources.MAX_METADATA_RESPONSE_BYTES
                or aggregate_bytes > sources.MAX_GIT_TREE_AGGREGATE_BYTES_PER_ROOT
            ):
                proof.update(
                    {
                        "tree_objects_fetched": len(visited),
                        "api_requests": request_count,
                        "remaining_queue_entries": len(queue) + 1,
                    }
                )
                return excluded_or_unavailable(
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "TREE_METADATA_BOUND_BEFORE_QUEUE_EXHAUSTION",
                )
            if (
                not isinstance(tree, Mapping)
                or tree.get("sha") != tree_sha
                or not isinstance(tree.get("tree"), list)
            ):
                raise protocol.SFIR4Refused("Git tree response identity or shape malformed")
            if tree.get("truncated") is True:
                proof.update(
                    {
                        "tree_objects_fetched": len(visited),
                        "api_requests": request_count,
                        "remaining_queue_entries": len(queue) + 1,
                    }
                )
                return excluded_or_unavailable(
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "NONRECURSIVE_TREE_RESPONSE_TRUNCATED",
                )
            visit_identity = (tree_sha, prefix)
            if visit_identity in visited:
                raise protocol.SFIR4Refused("Git tree SHA/prefix revisited")
            visited.add(visit_identity)
            for node in tree["tree"]:
                if not isinstance(node, Mapping) or node.get("type") not in {
                    "blob",
                    "tree",
                    "commit",
                }:
                    raise protocol.SFIR4Refused("Git tree entry malformed")
                name, child_sha = node.get("path"), node.get("sha")
                if (
                    not isinstance(name, str)
                    or not name
                    or "/" in name
                    or not isinstance(child_sha, str)
                    or len(child_sha) != 40
                ):
                    raise protocol.SFIR4Refused("Git tree entry identity malformed")
                full_path = f"{prefix}/{name}" if prefix else name
                if node["type"] == "blob" and full_path.casefold().endswith(
                    tuple(pool["extensions"])
                ):
                    doc_paths_seen += 1
                    proof["discovered_doc_paths"] = doc_paths_seen
                    rank = hashlib.sha256(
                        (sources.SELECTION_SALT + "\0" + repo + "\0" + full_path).encode()
                    ).hexdigest()
                    retained_doc_paths[full_path] = rank
                    if len(retained_doc_paths) > sources.MAX_GIT_RETAINED_DOC_PATHS_PER_ROOT:
                        worst_path = max(
                            retained_doc_paths, key=lambda value: (retained_doc_paths[value], value)
                        )
                        del retained_doc_paths[worst_path]
                    proof["retained_doc_paths"] = len(retained_doc_paths)
                elif node["type"] == "tree":
                    if full_path in path_to_sha and path_to_sha[full_path] != child_sha:
                        raise protocol.SFIR4Refused("Git tree path/SHA conflict")
                    if full_path in path_to_sha:
                        continue
                    if (
                        len(queue) >= sources.MAX_GIT_TREE_QUEUE_ENTRIES
                        or len(path_to_sha) >= sources.MAX_GIT_TREE_QUEUE_ENTRIES
                    ):
                        proof.update(
                            {
                                "tree_objects_fetched": len(visited),
                                "api_requests": request_count,
                                "remaining_queue_entries": len(queue),
                                "path_to_sha_entries": len(path_to_sha),
                                "peak_queue_entries": peak_queue_entries,
                                "peak_path_to_sha_entries": peak_path_to_sha_entries,
                            }
                        )
                        return excluded_or_unavailable(
                            "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                            "TREE_QUEUE_OR_PATH_MAP_BOUND_BEFORE_ENQUEUE",
                        )
                    path_to_sha[full_path] = child_sha
                    queue.append((child_sha, full_path))
                    peak_queue_entries = max(peak_queue_entries, len(queue))
                    peak_path_to_sha_entries = max(peak_path_to_sha_entries, len(path_to_sha))
        proof.update(
            {
                "queue_exhausted": True,
                "tree_objects_fetched": len(visited),
                "api_requests": request_count,
                "global_api_requests": self._global_git_request_count,
                "remaining_queue_entries": 0,
                "path_to_sha_entries": len(path_to_sha),
                "peak_queue_entries": peak_queue_entries,
                "peak_path_to_sha_entries": peak_path_to_sha_entries,
                "aggregate_tree_metadata_bytes": aggregate_bytes,
                "discovered_doc_paths": doc_paths_seen,
                "retained_doc_paths": len(retained_doc_paths),
            }
        )

        ordered = sorted(retained_doc_paths, key=lambda path: (retained_doc_paths[path], path))
        items: list[dict[str, Any]] = []
        for path in ordered[: pool["max_candidates_per_repository"]]:
            try:
                commits = fetch(
                    f"https://api.github.com/repos/{repo}/commits?path={urllib.parse.quote(path)}&sha={head_sha}&per_page=2"
                )
            except (MetadataResponseBoundExceeded, GitRequestBoundExceeded):
                proof.update(
                    {
                        "api_requests": min(request_count, sources.MAX_GIT_API_REQUESTS_PER_ROOT),
                        "history_paths_completed": len(items),
                    }
                )
                return excluded_or_unavailable(
                    "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                    "COMMIT_HISTORY_RESPONSE_OR_REQUEST_BOUND",
                )
            if not isinstance(commits, list):
                raise protocol.SFIR4Refused("Git commit metadata malformed")
            if len(commits) < 2:
                continue
            try:
                after, before = commits[0], commits[1]
                before_sha, after_sha = str(before["sha"]), str(after["sha"])
                before_ts = str(before["commit"]["committer"]["date"])
                after_ts = str(after["commit"]["committer"]["date"])
            except (KeyError, TypeError) as error:
                raise protocol.SFIR4Refused("Git commit metadata malformed") from error
            if before_sha == after_sha or before_ts >= after_ts:
                continue
            items.append(
                {
                    "repository": repo,
                    "path": path,
                    "commit_before": before_sha,
                    "commit_after": after_sha,
                    "timestamp_before": before_ts,
                    "timestamp_after": after_ts,
                }
            )
            proof["history_paths_completed"] = len(items)
        proof["api_requests"] = request_count
        proof["global_api_requests"] = self._global_git_request_count
        proof["response_ref_count"] = len(refs)
        return {
            "items": items,
            "next_cursor": None,
            "snapshot_id": f"github:{repo}:head:{head_sha}:tree:{root_tree_sha}",
            "response_refs": refs,
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": root_id,
                "state": "COMPLETE",
                "reason": "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED",
                "traversal_proof": proof,
            },
        }


def _pair(before: object, after: object, family: str) -> dict[str, str]:
    if not isinstance(before, str) or not before or not isinstance(after, str) or not after:
        raise protocol.SFIR4Refused(f"{family} revision pair malformed")
    return {"before": before, "after": after}


def _candidate(family: str, item: Mapping[str, Any]) -> tuple[dict[str, Any], set[str]] | None:
    if family == "git_docs":
        repo, path = item.get("repository"), item.get("path")
        if repo not in sources.SOURCE_POOLS[family]["repositories"] or not isinstance(path, str):
            raise protocol.SFIR4Refused("Git item escaped frozen roots")
        root = discovery = sources.discovery_root_id(family, repo)
        lineage = f"git:{repo}:{path}"
        container = f"git:{repo}:document:{path}"
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
            raise protocol.SFIR4Refused("eCFR item escaped frozen roots")
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
            raise protocol.SFIR4Refused("Wikipedia item escaped frozen roots")
        if item.get("redirect") is True:
            return None
        discovery = root = sources.discovery_root_id(family, category)
        container, lineage = f"wikipedia:en:pageid:{page_id}", f"wiki:en:{page_id}"
        ids = _pair(item.get("revision_before"), item.get("revision_after"), family)
        refs = {
            key: f"mediawiki://en.wikipedia.org/page/{page_id}/revision/{ids[key]}" for key in ids
        }
        aliases = {f"wiki:en:title:{str(item.get('title')).casefold()}"}
        aliases.update(
            f"wiki:en:title:{str(value).casefold()}" for value in item.get("aliases", [])
        )
    timestamps = _pair(item.get("timestamp_before"), item.get("timestamp_after"), family)
    if ids["before"] == ids["after"] or timestamps["before"] >= timestamps["after"]:
        if family == "git_docs":
            return None
        raise protocol.SFIR4Refused(f"{family} revision chronology invalid")
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
    charter_ref: Mapping[str, Any],
    spent_ref: Mapping[str, Any],
    destination: Path,
    transport: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
) -> Path:
    charter = protocol.verify_authority(root, charter_ref, protocol.CHARTER_SCHEMA)
    expected_probe = charter["toolchain"]["probe_sfir4_capacity"]
    if protocol.sha_file(Path(__file__)) != expected_probe["sha256"]:
        raise protocol.SFIR4Refused("running probe differs from frozen charter")
    spent = protocol.verify_spent(root, spent_ref)
    spent_ids = set(spent["container_ids"]) | set(spent["lineage_ids"]) | set(spent["alias_ids"])
    families: dict[str, Any] = {}
    for family in sources.FAMILIES:
        roots = sources.declared_roots(family)
        candidates: dict[str, dict[str, Any]] = {}
        dispositions: list[dict[str, Any]] = []
        snapshots: list[str] = []
        response_refs: list[str] = []
        retries = 0
        total_wait_seconds = 0
        for index, declared_root in enumerate(roots):
            expected = sources.discovery_root_id(family, declared_root)
            current_retries = 0
            while True:
                request: dict[str, Any] = {
                    "cursor": str(index),
                    "pool": sources.SOURCE_POOLS[family],
                    "metadata_only": True,
                    "expected_discovery_root_id": expected,
                }
                if family == "git_docs":
                    request["repository"] = declared_root
                response = transport(family, request)
                protocol._assert_metadata_only(response)
                if response.get("rate_limited") is True:
                    current_retries += 1
                    retries += 1
                    if current_retries > sources.PAGINATION_CONTRACT["maximum_retries_per_request"]:
                        raise protocol.SFIR4Refused(f"{family} rate-limit retry budget exhausted")
                    delay = response.get("retry_after_seconds")
                    if (
                        not isinstance(delay, int)
                        or delay < 1
                        or delay > sources.MAX_RATE_LIMIT_WAIT_SECONDS
                        or total_wait_seconds + delay > sources.MAX_TOTAL_RATE_LIMIT_WAIT_SECONDS
                    ):
                        raise protocol.SFIR4Refused(
                            f"{family} rate-limit wait exceeds frozen fail-safe bound"
                        )
                    time.sleep(delay)
                    total_wait_seconds += delay
                    continue
                break
            disposition = response.get("root_disposition")
            if (
                not isinstance(disposition, Mapping)
                or disposition.get("discovery_root_id") != expected
            ):
                raise protocol.SFIR4Refused(f"{family} root disposition malformed")
            if disposition.get("state") not in {
                "COMPLETE",
                "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION",
                "UNAVAILABLE_ROOT_DISPOSITION",
                "ZERO_CANDIDATE_ROOT_DISPOSITION",
            }:
                raise protocol.SFIR4Refused(f"{family} root disposition state malformed")
            items = response.get("items")
            if not isinstance(items, list) or (disposition["state"] != "COMPLETE" and items):
                raise protocol.SFIR4Refused("incomplete root emitted candidates")
            accepted = 0
            for item in items:
                if not isinstance(item, Mapping):
                    raise protocol.SFIR4Refused("candidate metadata is not an object")
                made = _candidate(family, item)
                if made is None:
                    continue
                row, aliases = made
                identities = {
                    row["root_container_id"],
                    row["container_id"],
                    row["lineage_id"],
                    *aliases,
                }
                if identities & spent_ids:
                    continue
                if row["lineage_id"] in candidates:
                    raise protocol.SFIR4Refused("duplicate lineage")
                candidates[row["lineage_id"]] = row
                accepted += 1
            cap_key = {
                "git_docs": "max_candidates_per_repository",
                "regulation_ecfr": "max_candidates_per_title",
                "encyclopedia_wikipedia": "max_candidates_per_category",
            }[family]
            if accepted > sources.SOURCE_POOLS[family][cap_key]:
                raise protocol.SFIR4Refused(f"{family} per-root candidate cap exceeded")
            snapshot = response.get("snapshot_id")
            refs = response.get("response_refs")
            if (
                not isinstance(snapshot, str)
                or not snapshot
                or not isinstance(refs, list)
                or not refs
            ):
                raise protocol.SFIR4Refused(f"{family} root lacks exact response evidence")
            dispositions.append(
                {**dict(disposition), "snapshot_ref": snapshot, "response_refs": list(refs)}
            )
            snapshots.append(snapshot)
            response_refs.extend(refs)
        if len(candidates) > sources.SOURCE_POOLS[family]["max_total_candidates"]:
            raise protocol.SFIR4Refused(f"{family} candidate cap exceeded")
        families[family] = {
            "authority": sources.FAMILY_AUTHORITIES[family],
            "snapshot_refs": snapshots,
            "response_refs": response_refs,
            "root_dispositions": dispositions,
            "pagination": {
                "roots_processed": len(roots),
                "exhausted": True,
                "rate_limit_retries": retries,
                "rate_limit_wait_seconds": total_wait_seconds,
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
    return protocol.write_immutable(destination, body)


def main(argv: list[str] | None = None) -> int:
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
    if (
        protocol.sha_file(args.charter) != args.charter_sha256
        or protocol.sha_file(args.spent) != args.spent_sha256
    ):
        raise protocol.SFIR4Refused("CLI exact digest arguments differ")
    path = probe_capacity(
        args.root,
        protocol.exact_ref(args.root, args.charter),
        protocol.exact_ref(args.root, args.spent),
        args.destination,
        LiveMetadataTransport(),
    )
    print(path.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
