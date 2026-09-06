from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
sys.path.insert(0, str(NS / "tools"))
sys.path.insert(0, str(NS))

import probe_sfir2_capacity as probe  # noqa: E402
import sfir2_protocol as protocol  # noqa: E402
import sfir2_spent_authority as spent_builder  # noqa: E402
from acquisition import sources_sfir2 as sources  # noqa: E402

STAMP = "2026-08-26T14:00:00Z"


def _isolated(root: Path) -> tuple[Path, dict[str, str]]:
    files = (
        "acquisition/sources_sfir2.py",
        "tools/probe_sfir2_capacity.py",
        "tools/sfir2_spent_authority.py",
        "protocols/SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V2_DESIGN_CHARTER.yaml",
    )
    for relative in files:
        target = root / "research/tavonel_eval_v2" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(NS / relative, target)
    charter_yaml = (
        root
        / "research/tavonel_eval_v2/protocols"
        / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V2_DESIGN_CHARTER.yaml"
    )
    charter = root / "receipts/charter.json"
    protocol.freeze_design_charter(root, charter_yaml, charter, STAMP)
    spent = root / "receipts/spent.json"
    protocol._write_immutable(
        spent,
        {
            "schema": protocol.SPENT_AUTHORITY_SCHEMA,
            "protocol_id": protocol.PROTOCOL_ID,
            "generated_at": STAMP,
            "container_ids": ["old:container"],
            "lineage_ids": ["old:lineage"],
            "alias_ids": ["old:alias"],
        },
    )
    return charter, protocol.exact_ref(root, spent)


def test_static_roots_are_disjoint_from_full_comprehensive_history() -> None:
    body = json.loads(
        (NS / "receipts/sfir1-spent-identity-authority.json").read_text(encoding="utf-8")
    )
    sources.assert_disjoint_from_comprehensive_spent(body["container_ids"], body["alias_ids"])
    assert len(sources.SOURCE_POOLS["git_docs"]["repositories"]) == 30
    assert len(sources.SOURCE_POOLS["encyclopedia_wikipedia"]["category_roots"]) == 30
    assert sources.SOURCE_POOLS["git_docs"]["max_total_candidates"] == 30 * 80
    assert sources.SOURCE_POOLS["encyclopedia_wikipedia"]["max_total_candidates"] == 30 * 150


def test_spent_composition_reserves_git_and_wiki_but_not_unreached_ecfr(tmp_path: Path) -> None:
    refs = [
        protocol.exact_ref(REPO, NS / "receipts/sfir1-spent-identity-authority.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir1-design-charter-freeze.json"),
        protocol.exact_ref(REPO, NS / "receipts/sfir1-capacity-failure-authority.json"),
    ]
    destination = tmp_path / "sfir2-spent.json"
    spent_builder.compose_spent_authority(REPO, *refs, destination, STAMP)
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["derivation"]["failure_stage"] == "GIT_DOCS_FAMILY_BEFORE_FAMILY_EXIT"
    assert body["derivation"]["exact_root_unknown"] is True
    assert body["derivation"]["families_not_reached"] == [
        "regulation_ecfr",
        "encyclopedia_wikipedia",
    ]
    assert len(body["reserved_sfir1_declared_roots"]["git_docs"]) == 20
    assert len(body["reserved_sfir1_declared_roots"]["encyclopedia_wikipedia"]) == 20
    assert body["reserved_sfir1_declared_roots"]["regulation_ecfr"] == []


def test_probe_emits_exhaustive_zero_dispositions_and_continues(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)
    calls = {family: 0 for family in sources.FAMILIES}

    def transport(family: str, request: dict) -> dict:
        index = calls[family]
        calls[family] += 1
        roots = sources.declared_roots(family)
        next_cursor = str(index + 1) if index + 1 < len(roots) else None
        return {
            "items": [],
            "next_cursor": next_cursor,
            "snapshot_id": f"zero:{family}:{index}",
            "response_refs": [f"https://metadata.invalid/{family}/{index}"],
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": request["expected_discovery_root_id"],
                "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                "reason": "HTTP_404",
            },
        }

    destination = tmp_path / "capacity.json"
    probe.probe_capacity(
        tmp_path, charter, protocol.sha_file(charter), spent, destination, transport
    )
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert calls == {family: len(sources.declared_roots(family)) for family in sources.FAMILIES}
    for family, block in body["families"].items():
        assert block["pagination"]["exhausted"] is True
        assert len(block["root_dispositions"]) == len(sources.declared_roots(family))
        assert block["candidates"] == []


def test_live_git_unavailable_and_truncated_are_zero_not_global_failure() -> None:
    pool = sources.SOURCE_POOLS["git_docs"]
    request = {
        "cursor": None,
        "pool": pool,
        "metadata_only": True,
        "expected_discovery_root_id": sources.discovery_root_id(
            "git_docs", pool["repositories"][0]
        ),
    }

    def missing(url: str):
        raise probe.RootUnavailable(404, url)

    missing_result = probe.LiveMetadataTransport(missing)("git_docs", request)
    assert missing_result["root_disposition"]["state"] == "ZERO_CANDIDATE_ROOT_DISPOSITION"
    calls = 0

    def truncated(_url: str):
        nonlocal calls
        calls += 1
        return {"default_branch": "main"} if calls == 1 else {"tree": [], "truncated": True}

    truncated_result = probe.LiveMetadataTransport(truncated)("git_docs", request)
    assert truncated_result["root_disposition"]["reason"] == "TRUNCATED_OR_INCOMPLETE_ENUMERATION"


def test_probe_refuses_malformed_or_exhausted_rate_limit(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)

    def malformed(_family: str, _request: dict) -> dict:
        return {"items": [], "next_cursor": None}

    with pytest.raises(protocol.SFIR2Refused, match="response shape malformed"):
        probe.probe_capacity(
            tmp_path,
            charter,
            protocol.sha_file(charter),
            spent,
            tmp_path / "malformed.json",
            malformed,
        )

    def limited(_family: str, request: dict) -> dict:
        return {
            "items": [],
            "next_cursor": request.get("cursor"),
            "snapshot_id": "rate",
            "response_refs": [],
            "rate_limited": True,
            "root_disposition": None,
        }

    with pytest.raises(protocol.SFIR2Refused, match="rate-limit retry budget exhausted"):
        probe.probe_capacity(
            tmp_path, charter, protocol.sha_file(charter), spent, tmp_path / "limited.json", limited
        )


def test_zero_disposition_cannot_emit_or_contribute_items(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)

    def hidden_partial(family: str, request: dict) -> dict:
        root = sources.declared_roots(family)[0]
        item = (
            {
                "repository": root,
                "path": "docs/a.md",
                "commit_before": "1" * 40,
                "commit_after": "2" * 40,
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            }
            if family == "git_docs"
            else {"partial": "metadata"}
        )
        return {
            "items": [item],
            "next_cursor": None,
            "snapshot_id": "partial:snapshot",
            "response_refs": ["https://metadata.invalid/partial"],
            "rate_limited": False,
            "root_disposition": {
                "discovery_root_id": request["expected_discovery_root_id"],
                "state": "ZERO_CANDIDATE_ROOT_DISPOSITION",
                "reason": "TRUNCATED_OR_INCOMPLETE_ENUMERATION",
            },
        }

    with pytest.raises(protocol.SFIR2Refused, match="zero-candidate root emitted candidates"):
        probe.probe_capacity(
            tmp_path,
            charter,
            protocol.sha_file(charter),
            spent,
            tmp_path / "hidden-partial.json",
            hidden_partial,
        )


def test_candidate_exactly_binds_revision_and_payload_locator() -> None:
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    made = probe._candidate(
        "git_docs",
        {
            "repository": repo,
            "path": "docs/a.md",
            "commit_before": "1" * 40,
            "commit_after": "2" * 40,
            "timestamp_before": "2026-01-01T00:00:00Z",
            "timestamp_after": "2026-01-02T00:00:00Z",
        },
    )
    assert made is not None
    row = made[0]
    declared = {
        sources.discovery_root_id("git_docs", value)
        for value in sources.declared_roots("git_docs")
    }
    protocol._validate_candidate("git_docs", row, declared, set())
    row["payload_ref"]["after"] = row["payload_ref"]["after"].replace("2" * 40, "3" * 40)
    with pytest.raises(protocol.SFIR2Refused, match="locator binding"):
        protocol._validate_candidate("git_docs", row, declared, set())


def test_roster_order_is_bound_to_predeclared_salt(monkeypatch) -> None:
    row = {"lineage_id": "lineage:1"}
    before = protocol._candidate_order("git_docs", row)
    monkeypatch.setattr(sources, "SELECTION_SALT", "different-prospective-salt")
    assert protocol._candidate_order("git_docs", row) != before


def test_metadata_http_body_has_a_hard_stream_bound(monkeypatch) -> None:
    class Oversized:
        headers = {"Content-Length": str(sources.MAX_METADATA_RESPONSE_BYTES + 1)}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *_args, **_kwargs: Oversized())
    with pytest.raises(protocol.SFIR2Refused, match="exceeds the frozen bound"):
        probe._http_json("https://api.github.com/repos/example/example")


def test_capacity_seal_independently_refuses_per_root_cap(tmp_path: Path) -> None:
    charter, spent = _isolated(tmp_path)
    families = {}
    for family in sources.FAMILIES:
        roots = sources.declared_roots(family)
        response_refs = [
            f"https://metadata.invalid/{family}/{index}" for index in range(len(roots))
        ]
        dispositions = [
            {
                "discovery_root_id": sources.discovery_root_id(family, root),
                "state": "COMPLETE",
                "reason": "ENUMERATION_EXHAUSTED",
                "snapshot_ref": f"snap:{family}:{index}",
                "response_refs": [response_refs[index]],
            }
            for index, root in enumerate(roots)
        ]
        families[family] = {
            "authority": sources.FAMILY_AUTHORITIES[family],
            "snapshot_refs": [row["snapshot_ref"] for row in dispositions],
            "response_refs": response_refs,
            "root_dispositions": dispositions,
            "pagination": {"pages_fetched": len(roots), "exhausted": True},
            "candidates": [],
        }
    repo = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    for index in range(81):
        made = probe._candidate(
            "git_docs",
            {
                "repository": repo,
                "path": f"docs/{index}.md",
                "commit_before": f"{index + 1:040x}",
                "commit_after": f"{index + 1001:040x}",
                "timestamp_before": "2026-01-01T00:00:00Z",
                "timestamp_after": "2026-01-02T00:00:00Z",
            },
        )
        assert made is not None
        families["git_docs"]["candidates"].append(made[0])
    metadata = tmp_path / "capacity-input.json"
    metadata.write_text(
        json.dumps(
            {
                "schema": protocol.CAPACITY_INPUT_SCHEMA,
                "protocol_id": protocol.PROTOCOL_ID,
                "families": families,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(protocol.SFIR2Refused, match="per-root candidate cap exceeded"):
        protocol.seal_capacity_census(
            tmp_path,
            protocol.exact_ref(tmp_path, charter),
            spent,
            metadata,
            tmp_path / "capacity-authority.json",
            STAMP,
        )


def test_execution_manifest_enriched_reference_is_exact(tmp_path: Path, monkeypatch) -> None:
    import sfir2_execution

    component = tmp_path / "tools/worker.py"
    component.parent.mkdir(parents=True)
    component.write_text("# frozen worker\n", encoding="utf-8")
    body = {
        "schema": "tavonel.sfir2.execution_manifest.v1",
        "protocol_id": protocol.PROTOCOL_ID,
        "coverage": {"acquisition": True, "scoring": True},
        "components": {"worker": protocol.exact_ref(tmp_path, component)},
        "generated_at": STAMP,
    }
    body["content_digest"] = protocol.digest(body)
    manifest = tmp_path / "receipts/execution-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(body), encoding="utf-8")
    ref = {
        **protocol.exact_ref(tmp_path, manifest),
        "content_digest": body["content_digest"],
        "schema": body["schema"],
    }
    monkeypatch.setattr(sfir2_execution, "ROOT", tmp_path)
    monkeypatch.setattr(
        sfir2_execution, "execution_toolchain_manifest", lambda _generated_at: body
    )
    assert protocol.verify_execution_manifest_ref(tmp_path, ref) == body
    with pytest.raises(protocol.SFIR2Refused, match="enriched reference mismatch"):
        protocol.verify_execution_manifest_ref(
            tmp_path, {**ref, "content_digest": "sha256:" + "0" * 64}
        )
