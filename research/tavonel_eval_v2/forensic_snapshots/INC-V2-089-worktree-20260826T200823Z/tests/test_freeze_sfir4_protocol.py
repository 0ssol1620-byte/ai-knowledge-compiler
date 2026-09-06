from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))
sys.path.insert(0, str(NS / "tools"))

import freeze_sfir4_protocol as freeze  # noqa: E402
import probe_sfir4_capacity as probe  # noqa: E402
import sfir4_execution as sx  # noqa: E402
import sfir4_protocol as protocol  # noqa: E402
from acquisition import sources_sfir4 as sources  # noqa: E402


def _candidate(family: str, index: int) -> dict:
    roots = sources.declared_roots(family)
    root = roots[index % len(roots)]
    if family == "git_docs":
        item = {
            "repository": root,
            "path": f"docs/{index}.md",
            "commit_before": f"{index + 1:040x}",
            "commit_after": f"{index + 1001:040x}",
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    elif family == "regulation_ecfr":
        item = {
            "title": root,
            "part": str(index // 100 + 1),
            "section": str(index + 1),
            "version_before": "2026-08-25",
            "version_after": "2026-08-26",
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    else:
        item = {
            "category": root,
            "page_id": index + 1,
            "title": f"Article {index}",
            "aliases": [],
            "redirect": False,
            "revision_before": str(index + 1),
            "revision_after": str(index + 1001),
            "timestamp_before": "2026-08-25T00:00:00Z",
            "timestamp_after": "2026-08-26T00:00:00Z",
        }
    made = probe._candidate(family, item)
    assert made is not None
    return made[0]


def _fixture():
    families = {}
    arithmetic = {}
    for family in sources.FAMILIES:
        candidates = [_candidate(family, index) for index in range(750)]
        dispositions = [
            {
                "discovery_root_id": sources.discovery_root_id(family, root),
                "state": "COMPLETE",
            }
            for root in sources.declared_roots(family)
        ]
        families[family] = {"root_dispositions": dispositions, "candidates": candidates}
        arithmetic[family] = {
            "complete_roots": len(dispositions),
            "excluded_or_unavailable_roots": 0,
            "candidates_from_complete_roots": 750,
            "candidates_from_incomplete_roots": 0,
        }
    capacity = {
        "state": "CAPACITY_PASS",
        "formula": "Q_f=min(1000,floor(0.8*C_f))",
        "C": {family: 750 for family in sources.FAMILIES},
        "Q": {family: 600 for family in sources.FAMILIES},
        "root_disposition_arithmetic": arithmetic,
    }
    spent = {"container_ids": [], "lineage_ids": [], "alias_ids": []}
    metadata = {
        "schema": protocol.CAPACITY_INPUT_SCHEMA,
        "protocol_id": protocol.PROTOCOL_ID,
        "families": families,
    }
    return capacity, spent, metadata


def test_roster_is_deterministic_capacity_bound_and_immutable(tmp_path, monkeypatch):
    capacity, spent, metadata = _fixture()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    monkeypatch.setattr(
        freeze,
        "_verified_inputs",
        lambda *_args: ({}, capacity, spent, metadata_path, metadata),
    )
    destination = tmp_path / "roster.json"
    freeze.freeze_roster(tmp_path, {}, {}, {}, destination, "2026-08-27T00:00:00Z")
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["Q"] == capacity["Q"]
    assert all(len(body["families"][family]) == 600 for family in sources.FAMILIES)
    for family in sources.FAMILIES:
        expected = sorted(
            metadata["families"][family]["candidates"],
            key=lambda row: freeze._candidate_order(family, row),
        )[:600]
        assert body["families"][family] == expected
    with pytest.raises(protocol.SFIR4Refused, match="existing immutable"):
        freeze.freeze_roster(tmp_path, {}, {}, {}, destination, "2026-08-27T00:00:01Z")


def test_roster_refuses_candidate_from_incomplete_root():
    capacity, spent, metadata = _fixture()
    family = "git_docs"
    root = metadata["families"][family]["root_dispositions"][0]["discovery_root_id"]
    metadata["families"][family]["root_dispositions"][0]["state"] = (
        "EXCLUDED_INCOMPLETE_ROOT_DISPOSITION"
    )
    capacity["root_disposition_arithmetic"][family] = {
        "complete_roots": len(sources.declared_roots(family)) - 1,
        "excluded_or_unavailable_roots": 1,
        "candidates_from_complete_roots": 750,
        "candidates_from_incomplete_roots": 0,
    }
    assert any(
        row["discovery_root_id"] == root for row in metadata["families"][family]["candidates"]
    )
    with pytest.raises(protocol.SFIR4Refused, match="incomplete root contributed"):
        freeze._selected_roster(capacity, spent, metadata)


def test_execution_manifest_closes_freezer_and_current_tree(tmp_path):
    manifest_path = tmp_path / "sfir4-execution-manifest.json"
    body = sx.write_execution_manifest(manifest_path, "2026-08-27T00:00:00Z")
    assert "tools/freeze_sfir4_protocol.py" in body["components"]
    assert freeze._verify_execution_manifest(sx.ROOT, manifest_path) == body


def test_protocol_freeze_binds_roster_manifest_and_exact_execution_policy(tmp_path, monkeypatch):
    capacity, spent, metadata = _fixture()
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    selected, capabilities = freeze._selected_roster(capacity, spent, metadata)
    charter_ref = {"path": "charter.json", "sha256": "sha256:charter"}
    capacity_ref = {"path": "capacity.json", "sha256": "sha256:capacity"}
    spent_ref = {"path": "spent.json", "sha256": "sha256:spent"}
    roster_ref = {"path": "roster.json", "sha256": "sha256:roster"}
    capacity.update(
        {
            "charter": charter_ref,
            "spent_identity_authority": spent_ref,
            "metadata": protocol.exact_ref(tmp_path, metadata_path),
        }
    )
    roster = {
        "state": "LINEAGE_ROSTER_FROZEN",
        "charter": charter_ref,
        "capacity": capacity_ref,
        "spent_identity_authority": spent_ref,
        "metadata": protocol.exact_ref(tmp_path, metadata_path),
        "Q": capacity["Q"],
        "families": selected,
        "capability_exercising_counts": capabilities,
    }
    monkeypatch.setattr(
        freeze,
        "_verified_inputs",
        lambda *_args: ({}, capacity, spent, metadata_path, metadata),
    )
    monkeypatch.setattr(protocol, "verify_authority", lambda *_args: roster)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    manifest = {
        "schema": sx.EXECUTION_TOOLCHAIN_SCHEMA,
        "content_digest": "sha256:manifest",
    }
    monkeypatch.setattr(freeze, "_verify_execution_manifest", lambda *_args: manifest)
    source_protocol = NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4.yaml"
    protocol_path = tmp_path / source_protocol.name
    protocol_path.write_bytes(source_protocol.read_bytes())
    destination = tmp_path / "protocol-freeze.json"
    freeze.freeze_protocol(
        tmp_path,
        protocol_path,
        charter_ref,
        capacity_ref,
        roster_ref,
        spent_ref,
        manifest_path,
        destination,
        "2026-08-27T00:00:00Z",
    )
    body = json.loads(destination.read_text(encoding="utf-8"))
    assert body["acquisition_authorized"] is True
    assert body["scoring_authorized"] is False
    assert body["score_exactly_once"] is True
    assert body["execution_manifest"]["content_digest"] == "sha256:manifest"


def test_worker_default_and_maximum_are_two():
    import inspect

    import sfir4_worker

    assert sfir4_worker.MAX_WORKERS == 2
    workers = inspect.signature(sfir4_worker.produce_observation_batch).parameters["workers"]
    assert workers.default == 2
