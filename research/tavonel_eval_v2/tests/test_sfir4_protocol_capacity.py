from __future__ import annotations

import hashlib
import json
import shutil
import sys
import urllib.error
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
sys.path.insert(0, str(NS))
sys.path.insert(0, str(NS / "tools"))

import freeze_sfir4_protocol as freezer  # noqa: E402
import probe_sfir4_capacity as probe  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
import sfir4_response_evidence as evidence  # noqa: E402
import sfir4_spent_authority as spent_builder  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402

STAMP = "2026-08-27T00:00:00Z"
SHA_HEAD = "1" * 40
SHA_ROOT = "2" * 40
SHA_CHILD = "3" * 40


def _fake_git(url: str):
    """The same metadata shape the BFS control above drives, reusable."""
    if url.endswith("/commits/main"):
        return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
    if url.endswith("/git/trees/" + SHA_ROOT):
        return {
            "sha": SHA_ROOT,
            "truncated": False,
            "tree": [{"path": "README.md", "type": "blob", "sha": "4" * 40}],
        }
    if "/commits?path=" in url:
        return _commits()
    return {"default_branch": "main"}


def _response_evidence(requests: int = 3, root: str = "git:octo/docs") -> dict:
    """A minimal but genuinely valid response-evidence block.

    Built through the real ledger rather than hand-written, so a test body can
    never assert against a shape the production writer would not emit.
    """
    ledger = evidence.ResponseLedger()
    for index in range(requests):
        raw = f"body-{index}".encode()
        ledger.record(
            family="git_docs",
            root_id=root,
            purpose="tree",
            url=f"https://api.github.com/repos/octo/docs/git/trees/{index:040x}",
            status=200,
            content_digest=evidence.digest_bytes(raw),
            observed_length=len(raw),
            declared_length=len(raw),
            observed_bytes=True,
        )
    return ledger.proof()


def _request() -> dict[str, object]:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    return {
        "pool": sources.SOURCE_POOLS["git_docs"],
        "repository": repo,
        "expected_discovery_root_id": sources.discovery_root_id("git_docs", repo),
    }


def _commits() -> list[dict[str, object]]:
    return [
        {"sha": "a" * 40, "commit": {"committer": {"date": "2026-01-02T00:00:00Z"}}},
        {"sha": "b" * 40, "commit": {"committer": {"date": "2026-01-01T00:00:00Z"}}},
    ]


def _git_proof(index: int, *, queue_exhausted: bool = True) -> dict[str, object]:
    return {
        "algorithm": "IMMUTABLE_NONRECURSIVE_TREE_BFS",
        "queue_exhausted": queue_exhausted,
        "tree_objects_fetched": 1,
        "api_requests": 1,
        "global_requests_before_root": index,
        "global_api_requests": index + 1,
        "response_ref_count": 1,
        "remaining_queue_entries": 0 if queue_exhausted else 1,
        "aggregate_tree_metadata_bytes": 10,
        "discovered_doc_paths": 0,
        "retained_doc_paths": 0,
        "path_to_sha_entries": 1,
        "peak_queue_entries": 1,
        "peak_path_to_sha_entries": 1,
        "history_paths_completed": 0,
    }


def _git_block(dispositions: list[dict], candidates: list[dict] | None = None) -> dict:
    return {
        "authority": sources.FAMILY_AUTHORITIES["git_docs"],
        "snapshot_refs": [row["snapshot_ref"] for row in dispositions],
        "response_refs": [ref for row in dispositions for ref in row["response_refs"]],
        "root_dispositions": dispositions,
        "pagination": {
            "roots_processed": len(sources.declared_roots("git_docs")),
            "exhausted": True,
            "rate_limit_retries": 0,
            "rate_limit_wait_seconds": 0,
            "cap_reached": False,
        },
        "candidates": candidates or [],
    }


def _complete_dispositions(family: str) -> list[dict]:
    rows = []
    for index, root in enumerate(sources.declared_roots(family)):
        row = {
            "discovery_root_id": sources.discovery_root_id(family, root),
            "state": "COMPLETE",
            "reason": (
                "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED"
                if family == "git_docs"
                else "ENUMERATION_EXHAUSTED"
            ),
            "snapshot_ref": f"snapshot:{family}:{index}",
            "response_refs": [f"metadata://{family}/{index}"],
        }
        if family == "git_docs":
            row["traversal_proof"] = _git_proof(index)
        rows.append(row)
    return rows


def _family_block(family: str, candidates: list[dict] | None = None) -> dict:
    dispositions = _complete_dispositions(family)
    return {
        "authority": sources.FAMILY_AUTHORITIES[family],
        "snapshot_refs": [row["snapshot_ref"] for row in dispositions],
        "response_refs": [ref for row in dispositions for ref in row["response_refs"]],
        "root_dispositions": dispositions,
        "pagination": {
            "roots_processed": len(dispositions),
            "exhausted": True,
            "rate_limit_retries": 0,
            "rate_limit_wait_seconds": 0,
            "cap_reached": False,
        },
        "candidates": candidates or [],
    }


def test_static_roots_are_fresh_against_all_predecessors_and_spent() -> None:
    current = {v.casefold() for v in sources.SOURCE_POOLS["git_docs"]["repositories"]}
    prior = {
        v.casefold()
        for v in (*sources.SFIR1_GIT_ROOTS, *sources.SFIR2_GIT_ROOTS, *sources.SFIR3_GIT_ROOTS)
    }
    assert len(current) == 20
    assert not current & prior
    body = json.loads(
        (NS / "receipts/sfir3-spent-identity-authority.json").read_text(encoding="utf-8")
    )
    sources.assert_disjoint_from_comprehensive_spent(body["container_ids"], body["alias_ids"])


def test_spent_authority_binds_exact_sfir3_failure_and_reserves_all_git_roots(
    tmp_path: Path,
) -> None:
    refs = [
        protocol.exact_ref(REPO, NS / "receipts/sfir3-spent-identity-authority.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir3-design-charter-freeze.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir3-capacity-failure-authority.json"),
    ]
    destination = tmp_path / "spent.json"
    spent_builder.compose_spent_authority(REPO, *refs, destination, STAMP)
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["derivation"]["reserve_all_sfir3_git_roots"] is True
    assert len(body["reserved_sfir3_declared_roots"]["git_docs"]) == 30
    assert body["reserved_sfir3_declared_roots"]["regulation_ecfr"] == []
    assert body["reserved_sfir3_declared_roots"]["encyclopedia_wikipedia"] == []
    assert (
        body["predecessor_sources"]["sfir3_terminal_failure"]["sha256"]
        == spent_builder.SFIR3_FAILURE_SHA256
    )


def test_nonrecursive_bfs_exhausts_queue_before_complete_and_pins_tree_sha() -> None:
    seen: list[str] = []

    def fetch(url: str):
        seen.append(url)
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if url.endswith("/git/trees/" + SHA_ROOT):
            return {
                "sha": SHA_ROOT,
                "truncated": False,
                "tree": [
                    {"path": "README.md", "type": "blob", "sha": "4" * 40},
                    {"path": "docs", "type": "tree", "sha": SHA_CHILD},
                ],
            }
        if url.endswith("/git/trees/" + SHA_CHILD):
            return {
                "sha": SHA_CHILD,
                "truncated": False,
                "tree": [
                    {"path": "guide.rst", "type": "blob", "sha": "5" * 40},
                ],
            }
        if "/commits?path=" in url:
            return _commits()
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert all("recursive" not in url.casefold() for url in seen)
    assert result["root_disposition"]["state"] == "COMPLETE"
    proof = result["root_disposition"]["traversal_proof"]
    assert proof["queue_exhausted"] is True
    assert proof["remaining_queue_entries"] == 0
    assert proof["tree_objects_fetched"] == 2
    assert proof["path_to_sha_entries"] == 2
    assert proof["peak_queue_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
    assert proof["peak_path_to_sha_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
    assert proof["api_requests"] == len(result["response_refs"])
    assert proof["global_api_requests"] == (
        proof["global_requests_before_root"] + proof["api_requests"]
    )
    assert {row["path"] for row in result["items"]} == {"README.md", "docs/guide.rst"}
    assert f":head:{SHA_HEAD}:tree:{SHA_ROOT}" in result["snapshot_id"]


def test_truncated_nonrecursive_tree_excludes_root_without_candidates() -> None:
    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if "/git/trees/" in url:
            return {"sha": SHA_ROOT, "truncated": True, "tree": []}
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert result["items"] == []
    assert result["root_disposition"]["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert result["root_disposition"]["traversal_proof"]["queue_exhausted"] is False


def test_identical_subtree_sha_may_be_mounted_at_distinct_prefixes() -> None:
    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if url.endswith("/git/trees/" + SHA_ROOT):
            return {
                "sha": SHA_ROOT,
                "truncated": False,
                "tree": [
                    {"path": "one", "type": "tree", "sha": SHA_CHILD},
                    {"path": "two", "type": "tree", "sha": SHA_CHILD},
                ],
            }
        if url.endswith("/git/trees/" + SHA_CHILD):
            return {
                "sha": SHA_CHILD,
                "truncated": False,
                "tree": [
                    {"path": "guide.md", "type": "blob", "sha": "8" * 40},
                ],
            }
        if "/commits?path=" in url:
            return _commits()
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert result["root_disposition"]["state"] == "COMPLETE"
    assert {row["path"] for row in result["items"]} == {"one/guide.md", "two/guide.md"}


def test_same_tree_path_with_different_sha_refuses() -> None:
    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if "/git/trees/" in url:
            return {
                "sha": SHA_ROOT,
                "truncated": False,
                "tree": [
                    {"path": "docs", "type": "tree", "sha": SHA_CHILD},
                    {"path": "docs", "type": "tree", "sha": "9" * 40},
                ],
            }
        return {"default_branch": "main"}

    with pytest.raises(protocol.SFIR4Refused, match="path/SHA conflict"):
        probe.LiveMetadataTransport(fetch)._git(_request())


def test_tree_response_bound_is_root_exclusion_not_global_refusal() -> None:
    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if "/git/trees/" in url:
            raise probe.MetadataResponseBoundExceeded("oversize")
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert result["items"] == []
    assert result["root_disposition"]["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"


def test_commit_history_request_bound_discards_partial_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sources, "MAX_GIT_API_REQUESTS_PER_ROOT", 3)

    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if "/git/trees/" in url:
            return {
                "sha": SHA_ROOT,
                "truncated": False,
                "tree": [
                    {"path": "README.md", "type": "blob", "sha": "8" * 40},
                ],
            }
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert result["items"] == []
    assert result["root_disposition"]["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert result["root_disposition"]["reason"] == "COMMIT_HISTORY_RESPONSE_OR_REQUEST_BOUND"


def test_tree_bound_before_queue_exhaustion_is_excluded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "MAX_GIT_TREE_OBJECTS_PER_ROOT", 1)

    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if url.endswith("/git/trees/" + SHA_ROOT):
            return {
                "sha": SHA_ROOT,
                "truncated": False,
                "tree": [{"path": "docs", "type": "tree", "sha": SHA_CHILD}],
            }
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    assert result["root_disposition"]["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert result["root_disposition"]["traversal_proof"]["queue_exhausted"] is False
    assert result["items"] == []


def test_subtree_enqueue_refuses_before_queue_or_path_map_exceeds_bound() -> None:
    children = [
        {"path": f"d{index:03d}", "type": "tree", "sha": f"{index + 10:040x}"}
        for index in range(sources.MAX_GIT_TREE_QUEUE_ENTRIES)
    ]

    def fetch(url: str):
        if url.endswith("/commits/main"):
            return {"sha": SHA_HEAD, "commit": {"tree": {"sha": SHA_ROOT}}}
        if url.endswith("/git/trees/" + SHA_ROOT):
            return {"sha": SHA_ROOT, "truncated": False, "tree": children}
        return {"default_branch": "main"}

    result = probe.LiveMetadataTransport(fetch)._git(_request())
    disposition = result["root_disposition"]
    proof = disposition["traversal_proof"]
    assert disposition["state"] == "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    assert disposition["reason"] == "TREE_QUEUE_OR_PATH_MAP_BOUND_BEFORE_ENQUEUE"
    assert result["items"] == []
    assert proof["remaining_queue_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
    assert proof["path_to_sha_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
    assert proof["peak_queue_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES
    assert proof["peak_path_to_sha_entries"] <= sources.MAX_GIT_TREE_QUEUE_ENTRIES


def _isolated_freeze(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    for relative in (
        "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml",
        "acquisition/sources_sfir4.py",
        "tools/probe_sfir4_capacity.py",
        "tools/sfir4_spent_authority.py",
        "tools/sfir4_protocol.py",
        "tools/probe_sfir3_capacity.py",
        "acquisition/sources_sfir3.py",
        "receipts/sfir3-spent-identity-authority.json",
        "receipts/sfir3-design-charter-freeze.json",
        "receipts/sfir3-capacity-failure-authority.json",
    ):
        target = tmp_path / "research/tavonel_eval_v2" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(NS / relative, target)
    base = tmp_path / "research/tavonel_eval_v2"
    receipt = base / "receipts/charter.json"
    protocol.freeze_design_charter(
        tmp_path,
        base / "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4_DESIGN_CHARTER.yaml",
        base / "tools/sfir4_protocol.py",
        base / "acquisition/sources_sfir4.py",
        base / "tools/probe_sfir4_capacity.py",
        base / "tools/sfir4_spent_authority.py",
        base / "acquisition/sources_sfir3.py",
        base / "tools/probe_sfir3_capacity.py",
        receipt,
        STAMP,
    )
    return receipt, protocol.exact_ref(tmp_path, receipt)


def _isolated_spent(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    base = tmp_path / "research/tavonel_eval_v2"
    destination = base / "receipts/sfir4-spent.json"
    refs = [
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-spent-identity-authority.json"),
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-design-charter-freeze.json"),
        protocol.exact_ref(tmp_path, base / "receipts/sfir3-capacity-failure-authority.json"),
    ]
    spent_builder.compose_spent_authority(tmp_path, *refs, destination, STAMP)
    return destination, protocol.exact_ref(tmp_path, destination)


def test_charter_freeze_is_semantic_content_bound_and_exclusive(tmp_path: Path) -> None:
    receipt, ref = _isolated_freeze(tmp_path)
    body = protocol.verify_authority(tmp_path, ref, protocol.CHARTER_SCHEMA)
    assert body["content_sha256"].startswith("sha256:")
    with pytest.raises(protocol.SFIR4Refused, match="existing immutable"):
        protocol.freeze_design_charter(
            tmp_path,
            tmp_path / body["charter"]["path"],
            tmp_path / body["toolchain"]["sfir4_protocol"]["path"],
            tmp_path / body["toolchain"]["sources_sfir4"]["path"],
            tmp_path / body["toolchain"]["probe_sfir4_capacity"]["path"],
            tmp_path / body["toolchain"]["sfir4_spent_authority"]["path"],
            tmp_path / body["toolchain"]["bound_sfir3_ecfr_wikipedia_sources"]["path"],
            tmp_path / body["toolchain"]["bound_sfir3_ecfr_wikipedia_adapter"]["path"],
            receipt,
            STAMP,
        )


def test_capacity_seal_rejects_forbidden_fields_before_scoring(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "payload_text": "forbidden",
            "families": {},
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="forbidden field"):
        protocol.seal_capacity(
            tmp_path, charter_ref, spent_ref, metadata, tmp_path / "out.json", STAMP
        )


def test_capacity_seal_requires_exact_unique_declared_root_dispositions(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "families": {"git_docs": _git_block([])},
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="exactly cover"):
        protocol.seal_capacity(
            tmp_path, charter_ref, spent_ref, metadata, tmp_path / "out.json", STAMP
        )


def test_capacity_seal_refuses_extra_fields_and_inexact_aggregates(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    base = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "response_evidence": _response_evidence(),
        "protocol_id": protocol.PROTOCOL_ID,
        "families": {"git_docs": _family_block("git_docs")},
    }
    cases = []

    body = json.loads(json.dumps(base))
    body["extra"] = True
    cases.append((body, "schema moved"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["authority"] = "WRONG"
    cases.append((body, "authority or fields"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["extra"] = True
    cases.append((body, "authority or fields"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["root_dispositions"][0]["extra"] = True
    cases.append((body, "disposition fields"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["root_dispositions"][0]["traversal_proof"]["extra"] = True
    cases.append((body, "transport request arithmetic"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["snapshot_refs"][0] = "snapshot:wrong"
    cases.append((body, "aggregate evidence refs"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["response_refs"].append("metadata://extra")
    cases.append((body, "aggregate evidence refs"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["pagination"]["extra"] = True
    cases.append((body, "pagination proof"))

    body = json.loads(json.dumps(base))
    body["families"]["git_docs"]["pagination"]["rate_limit_wait_seconds"] = 1
    cases.append((body, "pagination proof"))

    for index, (body, match) in enumerate(cases):
        metadata = tmp_path / f"research/tavonel_eval_v2/receipts/metadata-hostile-{index}.json"
        protocol.write_immutable(metadata, body)
        with pytest.raises(protocol.SFIR4Refused, match=match):
            protocol.seal_capacity(
                tmp_path,
                charter_ref,
                spent_ref,
                metadata,
                tmp_path / f"out-hostile-{index}.json",
                STAMP,
            )


def test_capacity_seal_rechecks_per_root_candidate_cap(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    repo = sources.declared_roots("git_docs")[0]
    cap = sources.SOURCE_POOLS["git_docs"]["max_candidates_per_repository"]
    candidates = []
    for index in range(cap + 1):
        made = probe._candidate(
            "git_docs",
            {
                "repository": repo,
                "path": f"docs/cap-{index}.md",
                "commit_before": f"{index + 1:040x}",
                "commit_after": f"{index + 1001:040x}",
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            },
        )
        assert made is not None
        candidates.append(made[0])
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata-cap.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "families": {"git_docs": _family_block("git_docs", candidates)},
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="per-root candidate cap"):
        protocol.seal_capacity(
            tmp_path, charter_ref, spent_ref, metadata, tmp_path / "out-cap.json", STAMP
        )


def test_capacity_seal_refuses_case_only_identity_variants(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    category = sources.declared_roots("encyclopedia_wikipedia")[0]
    candidates = []
    for index, title in enumerate(("Article", "Other"), start=1):
        made = probe._candidate(
            "encyclopedia_wikipedia",
            {
                "category": category,
                "page_id": index,
                "title": title,
                "aliases": [],
                "redirect": False,
                "revision_before": str(index),
                "revision_after": str(index + 100),
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            },
        )
        assert made is not None
        candidates.append(made[0])
    candidates[1]["alias_ids"] = ["wiki:en:title:ARTICLE"]
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata-casefold.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "families": {
                "encyclopedia_wikipedia": _family_block("encyclopedia_wikipedia", candidates)
            },
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="differ only by case or normalisation"):
        protocol.seal_capacity(
            tmp_path,
            charter_ref,
            spent_ref,
            metadata,
            tmp_path / "out-casefold.json",
            STAMP,
        )


def test_git_document_container_is_semantically_distinct_and_alias_may_not_collide() -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "README.md",
            "commit_before": "a" * 40,
            "commit_after": "b" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row, _ = made
    assert row["container_id"] == row["lineage_id"].replace(
        f"git:{repo}:", f"git:{repo}:document:", 1
    )
    protocol._validate_candidate(
        "git_docs", row, {sources.discovery_root_id("git_docs", repo)}, set()
    )
    hostile = dict(row)
    hostile["alias_ids"] = [row["lineage_id"]]
    with pytest.raises(protocol.SFIR4Refused, match="alias collides"):
        protocol._validate_candidate(
            "git_docs", hostile, {sources.discovery_root_id("git_docs", repo)}, set()
        )


@pytest.mark.parametrize(
    "mutation,match",
    [
        ("evil_locator", "payload locator"),
        ("equal_revision", "empty or equal"),
        ("reversed_time", "strictly increasing"),
        ("offset_time", "canonical UTC Z"),
    ],
)
def test_candidate_validator_refuses_evil_locator_revision_and_time(
    mutation: str, match: str
) -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "docs/guide.md",
            "commit_before": "a" * 40,
            "commit_after": "b" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    if mutation == "evil_locator":
        row["payload_ref"]["after"] = "https://evil.invalid/payload"
    elif mutation == "equal_revision":
        row["revision_id"]["after"] = row["revision_id"]["before"]
    elif mutation == "reversed_time":
        row["revision_timestamp"] = {
            "before": "2026-01-03T00:00:00Z",
            "after": "2026-01-02T00:00:00Z",
        }
    else:
        row["revision_timestamp"]["after"] = "2026-01-02T00:00:00+00:00"
    with pytest.raises(protocol.SFIR4Refused, match=match):
        protocol._validate_candidate(
            "git_docs", row, {sources.discovery_root_id("git_docs", repo)}, set()
        )


def test_candidate_validator_refuses_capability_bit_flip() -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "docs/guide.md",
            "commit_before": "a" * 40,
            "commit_after": "b" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    row["capability_exercise"]["E5"] = not row["capability_exercise"]["E5"]
    with pytest.raises(protocol.SFIR4Refused, match="differs from frozen salt"):
        protocol._validate_candidate(
            "git_docs", row, {sources.discovery_root_id("git_docs", repo)}, set()
        )


def test_candidate_validator_refuses_nondate_ecfr_revision() -> None:
    title = sources.SOURCE_POOLS["regulation_ecfr"]["titles"][0]
    made = probe._candidate(
        "regulation_ecfr",
        {
            "title": title,
            "part": "1",
            "section": "1.1",
            "version_before": "2026-01-01",
            "version_after": "2026-01-02",
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    row["revision_id"]["after"] = "revision-two"
    row["payload_ref"]["after"] = f"ecfr://title/{title}/part/1/section/1.1?version=revision-two"
    with pytest.raises(protocol.SFIR4Refused, match="exact date"):
        protocol._validate_candidate(
            "regulation_ecfr",
            row,
            {sources.discovery_root_id("regulation_ecfr", title)},
            set(),
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        ("invalid_calendar", "calendar date"),
        ("reversed_revision", "strictly increasing"),
        ("timestamp_mismatch", "bound to revision date"),
    ],
)
def test_candidate_validator_enforces_ecfr_calendar_and_timestamp_binding(
    mutation: str, match: str
) -> None:
    title = sources.SOURCE_POOLS["regulation_ecfr"]["titles"][0]
    made = probe._candidate(
        "regulation_ecfr",
        {
            "title": title,
            "part": "1",
            "section": "1.1",
            "version_before": "2026-01-01",
            "version_after": "2026-01-02",
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    if mutation == "invalid_calendar":
        row["revision_id"]["after"] = "2026-02-30"
        row["payload_ref"]["after"] = f"ecfr://title/{title}/part/1/section/1.1?version=2026-02-30"
    elif mutation == "reversed_revision":
        row["revision_id"] = {"before": "2026-01-03", "after": "2026-01-02"}
        row["revision_timestamp"] = {
            "before": "2026-01-03T00:00:00Z",
            "after": "2026-01-02T00:00:00Z",
        }
        row["payload_ref"]["before"] = f"ecfr://title/{title}/part/1/section/1.1?version=2026-01-03"
    else:
        row["revision_timestamp"]["after"] = "2026-01-02T01:00:00Z"
    with pytest.raises(protocol.SFIR4Refused, match=match):
        protocol._validate_candidate(
            "regulation_ecfr",
            row,
            {sources.discovery_root_id("regulation_ecfr", title)},
            set(),
        )


def test_candidate_validator_refuses_nonpositive_wikipedia_revision() -> None:
    category = sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"][0]
    made = probe._candidate(
        "encyclopedia_wikipedia",
        {
            "category": category,
            "page_id": 1,
            "title": "Article",
            "aliases": [],
            "redirect": False,
            "revision_before": "1",
            "revision_after": "2",
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    row["revision_id"]["before"] = "0"
    row["payload_ref"]["before"] = "mediawiki://en.wikipedia.org/page/1/revision/0"
    with pytest.raises(protocol.SFIR4Refused, match="positive numeric"):
        protocol._validate_candidate(
            "encyclopedia_wikipedia",
            row,
            {sources.discovery_root_id("encyclopedia_wikipedia", category)},
            set(),
        )


def test_candidate_validator_refuses_wikipedia_leading_zero_ids() -> None:
    category = sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"][0]
    made = probe._candidate(
        "encyclopedia_wikipedia",
        {
            "category": category,
            "page_id": 1,
            "title": "Article",
            "aliases": [],
            "redirect": False,
            "revision_before": "1",
            "revision_after": "2",
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    row["revision_id"]["before"] = "01"
    row["payload_ref"]["before"] = "mediawiki://en.wikipedia.org/page/1/revision/01"
    with pytest.raises(protocol.SFIR4Refused, match="positive numeric"):
        protocol._validate_candidate(
            "encyclopedia_wikipedia",
            row,
            {sources.discovery_root_id("encyclopedia_wikipedia", category)},
            set(),
        )

    row["revision_id"]["before"] = "1"
    row["payload_ref"]["before"] = "mediawiki://en.wikipedia.org/page/01/revision/1"
    row["container_id"] = "wikipedia:en:pageid:01"
    row["lineage_id"] = "wiki:en:01"
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + row["lineage_id"]).encode()).digest()[0]
    row["capability_exercise"] = {
        "E5": not bool(bits & 1),
        "E6": not bool(bits & 2),
        "E9": not bool(bits & 4),
    }
    with pytest.raises(protocol.SFIR4Refused, match="locator identity shape"):
        protocol._validate_candidate(
            "encyclopedia_wikipedia",
            row,
            {sources.discovery_root_id("encyclopedia_wikipedia", category)},
            set(),
        )


def test_real_ecfr_404_is_translated_to_zero_disposition() -> None:
    def missing(url: str):
        raise probe.RootUnavailable(404, url)

    pool = sources.SOURCE_POOLS["regulation_ecfr"]
    result = probe.LiveMetadataTransport(missing)(
        "regulation_ecfr",
        {
            "cursor": "0",
            "pool": pool,
            "metadata_only": True,
            "expected_discovery_root_id": sources.discovery_root_id(
                "regulation_ecfr", pool["titles"][0]
            ),
        },
    )
    assert result["items"] == []
    assert result["root_disposition"]["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    assert result["root_disposition"]["reason"] == "HTTP_404_DURING_ROOT_ENUMERATION"


def test_retryable_server_error_has_integer_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = urllib.error.HTTPError("https://api.github.com/x", 503, "busy", {}, None)
    monkeypatch.setattr(
        probe.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
    )
    with pytest.raises(probe.RateLimited) as caught:
        probe._http_json("https://api.github.com/x")
    assert caught.value.retry_after_seconds == sources.RETRYABLE_HTTP_BACKOFF_SECONDS
    assert isinstance(caught.value.retry_after_seconds, int)


def test_frozen_theoretical_git_request_plan_is_globally_feasible() -> None:
    root_count = len(sources.SOURCE_POOLS["git_docs"]["repositories"])
    per_root = (
        2
        + sources.MAX_GIT_TREE_OBJECTS_PER_ROOT
        + sources.SOURCE_POOLS["git_docs"]["max_candidates_per_repository"]
    )
    assert per_root == sources.MAX_GIT_API_REQUESTS_PER_ROOT
    assert root_count * per_root <= sources.MAX_GIT_API_REQUESTS_GLOBAL


def test_freezer_parses_zero_dispositions_before_enforcing_capacity_floor() -> None:
    metadata = {"families": {}}
    for family in sources.FAMILIES:
        metadata["families"][family] = {
            "candidates": [],
            "root_dispositions": [
                {
                    "discovery_root_id": sources.discovery_root_id(family, root),
                    "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                }
                for root in sources.declared_roots(family)
            ],
        }
    with pytest.raises(protocol.SFIR4Refused, match="capacity C/Q arithmetic drifted"):
        freezer._selected_roster(
            {
                "C": {family: 0 for family in sources.FAMILIES},
                "Q": {family: 0 for family in sources.FAMILIES},
            },
            {"container_ids": [], "lineage_ids": [], "alias_ids": []},
            metadata,
        )


def test_verify_spent_rejects_sorted_but_unbound_authority(tmp_path: Path) -> None:
    path = tmp_path / "unbound.json"
    protocol.write_immutable(
        path,
        {
            "schema": protocol.SPENT_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "state": "COMPLETE_COMPOSED_SPENT_AUTHORITY",
            "container_ids": ["c"],
            "lineage_ids": ["l"],
            "alias_ids": ["a"],
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="predecessor set"):
        protocol.verify_spent(tmp_path, protocol.exact_ref(tmp_path, path))


def test_capacity_seal_refuses_fake_git_complete_proof(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    roots = list(sources.declared_roots("git_docs"))
    dispositions = []
    for index, root_value in enumerate(roots):
        dispositions.append(
            {
                "discovery_root_id": sources.discovery_root_id("git_docs", root_value),
                "state": "COMPLETE" if index == 0 else "UNAVAILABLE_ROOT_DISPOSITION",
                "reason": "NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED" if index == 0 else "HTTP_404",
                "traversal_proof": _git_proof(index, queue_exhausted=index != 0),
                "snapshot_ref": f"snapshot:{index}",
                "response_refs": [f"https://api.github.com/root/{index}"],
            }
        )
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata-proof.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "families": {"git_docs": _git_block(dispositions)},
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="COMPLETE traversal proof"):
        protocol.seal_capacity(
            tmp_path, charter_ref, spent_ref, metadata, tmp_path / "out.json", STAMP
        )


def test_capacity_seal_refuses_stale_git_global_request_proof(tmp_path: Path) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    dispositions = []
    for index, root_value in enumerate(sources.declared_roots("git_docs")):
        dispositions.append(
            {
                "discovery_root_id": sources.discovery_root_id("git_docs", root_value),
                "state": "COMPLETE" if index == 0 else "UNAVAILABLE_ROOT_DISPOSITION",
                "reason": ("NONRECURSIVE_TREE_BFS_QUEUE_EXHAUSTED" if index == 0 else "HTTP_404"),
                "traversal_proof": {
                    **_git_proof(index),
                    "global_api_requests": index,
                },
                "snapshot_ref": f"snapshot:{index}",
                "response_refs": [f"https://api.github.com/root/{index}"],
            }
        )
    metadata = tmp_path / "research/tavonel_eval_v2/receipts/metadata-stale-global.json"
    protocol.write_immutable(
        metadata,
        {
            "schema": protocol.CAPACITY_INPUT_SCHEMA,
            "response_evidence": _response_evidence(),
            "protocol_id": protocol.PROTOCOL_ID,
            "families": {"git_docs": _git_block(dispositions)},
        },
    )
    with pytest.raises(protocol.SFIR4Refused, match="transport request arithmetic"):
        protocol.seal_capacity(
            tmp_path,
            charter_ref,
            spent_ref,
            metadata,
            tmp_path / "out-stale.json",
            STAMP,
        )


def test_github_403_rate_limit_is_distinguished_from_permission_403(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limited = urllib.error.HTTPError(
        "https://api.github.com/x",
        403,
        "rate",
        {"X-RateLimit-Remaining": "0", "Retry-After": "2"},
        None,
    )
    monkeypatch.setattr(
        probe.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(limited)
    )
    with pytest.raises(probe.RateLimited) as caught:
        probe._http_json("https://api.github.com/x")
    assert caught.value.retry_after_seconds == 2

    denied = urllib.error.HTTPError("https://api.github.com/x", 403, "denied", {}, None)
    monkeypatch.setattr(
        probe.urllib.request, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(denied)
    )
    with pytest.raises(protocol.SFIR4Refused, match="authenticated metadata access failed"):
        probe._http_json("https://api.github.com/x")


# ---------------------------------------------------------------------------
# The census must carry response evidence, and it must be real
# ---------------------------------------------------------------------------


def _census(tmp_path: Path, name: str, block: object) -> Path:
    metadata = tmp_path / f"research/tavonel_eval_v2/receipts/{name}.json"
    body = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "protocol_id": protocol.PROTOCOL_ID,
        "families": {"git_docs": _git_block(_complete_dispositions("git_docs"))},
    }
    if block is not ...:
        body["response_evidence"] = block
    protocol.write_immutable(metadata, body)
    return metadata


def _seal(tmp_path: Path, metadata: Path, name: str) -> None:
    _, charter_ref = _isolated_freeze(tmp_path)
    _, spent_ref = _isolated_spent(tmp_path)
    protocol.seal_capacity(
        tmp_path, charter_ref, spent_ref, metadata, tmp_path / f"{name}.json", STAMP
    )


def test_a_census_with_no_response_evidence_refuses(tmp_path: Path) -> None:
    metadata = _census(tmp_path, "no-evidence", ...)
    with pytest.raises(protocol.SFIR4Refused, match="schema moved"):
        _seal(tmp_path, metadata, "out")


def test_a_census_whose_evidence_chain_was_reordered_refuses(tmp_path: Path) -> None:
    """The property a flat list of URLs could not have."""
    block = _response_evidence(requests=3)
    block["observations"][0], block["observations"][1] = (
        block["observations"][1],
        block["observations"][0],
    )
    metadata = _census(tmp_path, "reordered", block)
    with pytest.raises(protocol.SFIR4Refused, match="chain does not recompute"):
        _seal(tmp_path, metadata, "out")


def test_a_census_with_a_deleted_observation_refuses(tmp_path: Path) -> None:
    block = _response_evidence(requests=3)
    del block["observations"][1]
    metadata = _census(tmp_path, "deleted", block)
    with pytest.raises(protocol.SFIR4Refused, match="chain does not recompute"):
        _seal(tmp_path, metadata, "out")


def test_a_census_whose_request_arithmetic_does_not_reconcile_refuses(
    tmp_path: Path,
) -> None:
    block = _response_evidence(requests=3)
    block["per_root_requests_sum"] = 99
    metadata = _census(tmp_path, "arithmetic", block)
    # The refusal now fires one step earlier and for a stronger reason. The
    # aggregates are recomputed from `observations` before anything compares
    # them to each other, so an edited `per_root_requests_sum` is caught as
    # arithmetic that was not derived from this chain rather than as arithmetic
    # that failed to reconcile with a sibling field. Both are refusals; only the
    # second could be satisfied by editing the sibling too.
    with pytest.raises(protocol.SFIR4Refused, match="does not match the observations"):
        _seal(tmp_path, metadata, "out")


def test_a_synthesised_census_is_not_accepted_as_a_live_one(tmp_path: Path) -> None:
    """The control that stops an injected fetcher from manufacturing evidence."""
    ledger = evidence.ResponseLedger()
    ledger.record(
        family="git_docs",
        root_id="git:octo/docs",
        purpose="tree",
        url="https://api.github.com/repos/octo/docs/git/trees/" + "a" * 40,
        status=200,
        content_digest=evidence.digest_parsed({"tree": []}),
        observed_length=0,
        declared_length=None,
        observed_bytes=False,
    )
    metadata = _census(tmp_path, "synthesised", ledger.proof())
    with pytest.raises(protocol.SFIR4Refused, match="simulated census"):
        _seal(tmp_path, metadata, "out")


def test_a_census_that_observed_nothing_refuses(tmp_path: Path) -> None:
    metadata = _census(tmp_path, "empty", evidence.ResponseLedger().proof())
    # Refused for observing nothing, which is now stated as what it is: the head
    # of an empty chain is a public constant and certifies no request at all.
    with pytest.raises(protocol.SFIR4Refused, match="records no observations"):
        _seal(tmp_path, metadata, "out")


def test_the_probe_records_one_observation_per_git_request() -> None:
    """The ledger is fed by the real traversal, not only by tests."""
    transport = probe.LiveMetadataTransport(fetch_json=lambda url: _fake_git(url))
    request = _request()
    transport("git_docs", request)
    assert len(transport.ledger) > 0
    proof = transport.ledger.proof()
    assert proof["per_root_requests_sum"] == proof["global"]["requests"]
    assert evidence.verify_chain(proof)
    assert proof["global"]["all_observed"] is False, (
        "an injected fetcher must never produce observed-byte evidence"
    )
    purposes = {row["purpose"] for row in proof["observations"]}
    assert purposes <= {"repository", "commit", "tree"}


# ---------------------------------------------------------------------------
# The pre-freeze audit finding: charter toolchain pins were written once and
# never read again
# ---------------------------------------------------------------------------


def test_the_charter_toolchain_is_reverified_and_a_drifted_module_refuses_the_seal(
    tmp_path: Path,
) -> None:
    """Post-hoc root addition, wearing an already-frozen charter.

    ``acquisition/sources_sfir4.py`` holds ``SOURCE_POOLS``, ``declared_roots``
    and ``SELECTION_SALT`` -- the roots, the per-root caps and the deterministic
    ordering. Until ``verify_toolchain`` existed, exactly one of the charter's
    six pins was ever checked again (the probe checks its own file), so a census
    that came up short for a family could be rescued by widening a root list in
    that module, re-running the probe in a fresh process, and sealing against the
    SAME frozen charter. Nothing compared the new bytes to the pinned hash.

    The mutation here is a comment, not a behaviour change, precisely so that
    what the seal refuses is the DRIFT and not its consequences.
    """
    charter_path, charter_ref = _isolated_freeze(tmp_path)
    spent_path, spent_ref = _isolated_spent(tmp_path)
    base = tmp_path / "research/tavonel_eval_v2"

    pinned = base / "acquisition/sources_sfir4.py"
    pinned.write_text(
        pinned.read_text(encoding="utf-8") + "\n# widened after the charter froze\n",
        encoding="utf-8",
    )

    metadata = base / "metadata.json"
    metadata.write_text(json.dumps({"schema": "x"}), encoding="utf-8")
    with pytest.raises(protocol.SFIR4Refused, match="toolchain drifted"):
        protocol.seal_capacity(
            tmp_path, charter_ref, spent_ref, metadata, tmp_path / "out.json", STAMP
        )
    assert charter_path.is_file() and spent_path.is_file()


def test_verify_toolchain_accepts_the_charter_it_was_frozen_against(tmp_path: Path) -> None:
    """The other direction, so the refusal above is a rule rather than a veto."""
    charter_path, _ = _isolated_freeze(tmp_path)
    charter = json.loads(charter_path.read_text(encoding="utf-8"))
    verified = protocol.verify_toolchain(tmp_path, charter)
    assert set(verified) == set(charter["toolchain"])
    assert all(value.startswith("sha256:") for value in verified.values())


def test_verify_toolchain_refuses_when_a_pinned_module_is_absent(tmp_path: Path) -> None:
    charter_path, _ = _isolated_freeze(tmp_path)
    charter = json.loads(charter_path.read_text(encoding="utf-8"))
    (tmp_path / "research/tavonel_eval_v2/tools/sfir4_spent_authority.py").unlink()
    with pytest.raises(protocol.SFIR4Refused, match="pinned file is absent"):
        protocol.verify_toolchain(tmp_path, charter)


def test_verify_toolchain_refuses_a_charter_with_no_pins(tmp_path: Path) -> None:
    with pytest.raises(protocol.SFIR4Refused, match="no toolchain pins"):
        protocol.verify_toolchain(tmp_path, {"toolchain": {}})
