from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import probe_sfir1_capacity as probe
import sfir1_protocol as sfir1


STAMP = "2026-08-26T12:00:00Z"


def test_frozen_per_root_caps_cannot_trip_total_cap_before_exhaustion() -> None:
    pools = probe.sources.SOURCE_POOLS
    git = pools["git_docs"]
    ecfr = pools["regulation_ecfr"]
    wiki = pools["encyclopedia_wikipedia"]
    assert len(git["repositories"]) * git["max_candidates_per_repository"] <= git["max_total_candidates"]
    assert len(ecfr["titles"]) * ecfr["max_candidates_per_title"] <= ecfr["max_total_candidates"]
    assert len(wiki["category_roots"]) * wiki["max_candidates_per_category"] <= wiki["max_total_candidates"]
    # One repo metadata + one tree + at most 80 two-commit metadata requests.
    assert len(git["repositories"]) * (2 + git["max_candidates_per_repository"]) <= 1640


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _setup(root: Path) -> tuple[Path, dict[str, str]]:
    charter = root / "protocols" / "charter.yaml"
    charter.parent.mkdir(parents=True)
    charter.write_text((NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1_DESIGN_CHARTER.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    authority = root / "receipts" / "charter.json"
    sfir1.freeze_design_charter(root, charter, authority, STAMP)
    old = _write(root / "history" / "sfi3.json", {"schema": "tavonel.sfi3.acquisition.v1", "lineage_id": "old:lineage", "container_id": "old:container", "alias_ids": ["wiki:en:title:spent alias"]})
    spent_path = root / "receipts" / "spent.json"
    sfir1.build_spent_authority(root, [("SFI3", old, sfir1.sha_file(old))], spent_path, STAMP)
    return authority, {"path": spent_path.relative_to(root).as_posix(), "sha256": sfir1.sha_file(spent_path)}


def _wiki_id() -> int:
    return 101


def _item(family: str, index: int = 1) -> dict:
    common = {"timestamp_before": "2026-01-01T00:00:00Z", "timestamp_after": "2026-01-02T00:00:00Z"}
    if family == "git_docs":
        return {**common, "repository": "elastic/docs-content", "path": f"docs/{index}.md", "commit_before": f"a{index}", "commit_after": f"b{index}"}
    if family == "regulation_ecfr":
        return {**common, "title": 1, "part": "1", "section": str(index), "version_before": f"v{index}a", "version_after": f"v{index}b"}
    return {**common, "category": "Software documentation", "page_id": _wiki_id() + index - 1, "title": f"Page {index}", "aliases": [], "redirect": False, "revision_before": f"r{index}a", "revision_after": f"r{index}b"}


def test_probe_exhausts_every_page_and_emits_exact_candidate_contract(tmp_path: Path) -> None:
    charter, spent = _setup(tmp_path)
    calls = {family: 0 for family in probe.sources.FAMILIES}
    def transport(family: str, request: dict) -> dict:
        calls[family] += 1
        page = calls[family]
        return {"items": [_item(family, page)], "next_cursor": "page-2" if page == 1 else None, "snapshot_id": f"snap:{family}", "rate_limited": False}
    destination = tmp_path / "inputs" / "capacity.json"
    probe.probe_capacity(tmp_path, charter, sfir1.sha_file(charter), spent, destination, transport)
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert calls == {family: 2 for family in probe.sources.FAMILIES}
    for block in body["families"].values():
        assert block["pagination"]["exhausted"] is True
        for row in block["candidates"]:
            assert set(row) == set(probe.sources.CANDIDATE_FIELDS)
            assert set(row["payload_ref"]) == set(row["revision_id"]) == set(row["revision_timestamp"]) == {"before", "after"}
    git_row = body["families"]["git_docs"]["candidates"][0]
    ecfr_row = body["families"]["regulation_ecfr"]["candidates"][0]
    assert git_row["container_id"] == git_row["lineage_id"]
    assert git_row["root_container_id"] == "git:elastic/docs-content"
    assert ecfr_row["container_id"] == "ecfr:1:1:1"
    assert ecfr_row["root_container_id"] == "ecfr:1:1"
    assert "/part/1/section/1?version=" in ecfr_row["payload_ref"]["after"]


def test_probe_retries_rate_limit_but_refuses_after_frozen_budget(tmp_path: Path) -> None:
    charter, spent = _setup(tmp_path)
    calls = 0
    def transport(family: str, request: dict) -> dict:
        nonlocal calls
        calls += 1
        return {"items": [], "next_cursor": None, "snapshot_id": "snap", "rate_limited": True}
    with pytest.raises(sfir1.SFIR1Refused, match="rate-limit retry budget exhausted"):
        probe.probe_capacity(tmp_path, charter, sfir1.sha_file(charter), spent, tmp_path / "capacity.json", transport)
    assert calls == probe.sources.PAGINATION_CONTRACT["maximum_retries_per_request"] + 1


def test_probe_refuses_repeated_cursor_and_payload_shaped_response(tmp_path: Path) -> None:
    charter, spent = _setup(tmp_path)
    def repeated(family: str, request: dict) -> dict:
        return {"items": [], "next_cursor": "same", "snapshot_id": "snap", "rate_limited": False}
    with pytest.raises(sfir1.SFIR1Refused, match="cursor repeated"):
        probe.probe_capacity(tmp_path, charter, sfir1.sha_file(charter), spent, tmp_path / "repeat.json", repeated)
    def payload(family: str, request: dict) -> dict:
        return {"items": [], "next_cursor": None, "snapshot_id": "snap", "rate_limited": False, "payload": "forbidden"}
    with pytest.raises(sfir1.SFIR1Refused, match="forbidden field"):
        probe.probe_capacity(tmp_path, charter, sfir1.sha_file(charter), spent, tmp_path / "payload.json", payload)


def test_spent_builder_is_exact_and_fail_closed(tmp_path: Path) -> None:
    source = _write(tmp_path / "history.json", {"schema": "tavonel.sfi1.result.v1", "lineage_ids": ["l1"], "container_ids": ["c1"], "redirect_aliases": ["a1"]})
    out = tmp_path / "spent.json"
    sfir1.build_spent_authority(tmp_path, [("SFI1", source, sfir1.sha_file(source))], out, STAMP)
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["lineage_ids"] == ["l1"] and body["container_ids"] == ["c1"] and body["alias_ids"] == ["a1"]
    with pytest.raises(sfir1.SFIR1Refused, match="explicit digest mismatch"):
        sfir1.build_spent_authority(tmp_path, [("SFI2", source, "sha256:" + "0" * 64)], tmp_path / "bad.json", STAMP)


def test_probe_excludes_spent_root_and_alias(tmp_path: Path) -> None:
    charter, _spent = _setup(tmp_path)
    source = _write(tmp_path / "history-root.json", {
        "schema": "tavonel.test.history.v1",
        "container_ids": ["git:elastic/docs-content"],
        "alias_ids": ["wiki:en:title:page 1"],
    })
    spent_path = tmp_path / "receipts" / "spent-root.json"
    sfir1.build_spent_authority(tmp_path, [("SFI3", source, sfir1.sha_file(source))], spent_path, STAMP)
    spent = {"path": spent_path.relative_to(tmp_path).as_posix(), "sha256": sfir1.sha_file(spent_path)}
    def transport(family: str, _request: dict) -> dict:
        return {"items": [_item(family)], "next_cursor": None, "snapshot_id": f"snap:{family}", "rate_limited": False}
    destination = tmp_path / "inputs" / "root-filter.json"
    probe.probe_capacity(tmp_path, charter, sfir1.sha_file(charter), spent, destination, transport)
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["families"]["git_docs"]["candidates"] == []
    assert body["families"]["encyclopedia_wikipedia"]["candidates"] == []


def test_live_ecfr_adapter_follows_declared_api_pages() -> None:
    urls: list[str] = []
    def fetch(url: str):
        urls.append(url)
        row = {"type": "section", "part": "2", "identifier": "2.1", "removed": False}
        if "?page=2" in url:
            return {"content_versions": [{**row, "date": "2026-01-02"}]}
        return {"content_versions": [{**row, "date": "2026-01-01"}], "meta": {"total_pages": 2, "result_count": 2}}
    result = probe.LiveMetadataTransport(fetch)("regulation_ecfr", {"cursor": None, "pool": probe.sources.SOURCE_POOLS["regulation_ecfr"], "metadata_only": True})
    assert len(urls) == 2 and result["items"][0]["part"] == "2"
    assert result["items"][0]["version_after"] == "2026-01-02"


def test_live_git_adapter_reports_rate_limit_and_refuses_truncated_tree() -> None:
    def limited(_url: str):
        raise probe.RateLimited("429")
    held = probe.LiveMetadataTransport(limited)("git_docs", {"cursor": None, "pool": probe.sources.SOURCE_POOLS["git_docs"], "metadata_only": True})
    assert held["rate_limited"] is True
    calls = 0
    def truncated(_url: str):
        nonlocal calls
        calls += 1
        return {"default_branch": "main"} if calls == 1 else {"tree": [], "truncated": True}
    with pytest.raises(sfir1.SFIR1Refused, match="tree incomplete"):
        probe.LiveMetadataTransport(truncated)("git_docs", {"cursor": None, "pool": probe.sources.SOURCE_POOLS["git_docs"], "metadata_only": True})
