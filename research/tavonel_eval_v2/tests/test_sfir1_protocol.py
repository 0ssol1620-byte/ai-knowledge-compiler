from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import sfir1_protocol as sfir1


STAMP = "2026-08-26T12:00:00Z"


def _write_json(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _spent(root: Path, containers: list[str] | None = None, lineages: list[str] | None = None):
    body = {
        "schema": sfir1.SPENT_AUTHORITY_SCHEMA,
        "generated_at": STAMP,
        "container_ids": containers or [],
        "lineage_ids": lineages or [],
        "alias_ids": [],
        "sources": [{
            "generation": "SFI3",
            "path": "authorities/spent-source.json",
            "sha256": "",
            "schema": "tavonel.test.spent_source.v1",
        }],
    }
    source = _write_json(root / "authorities" / "spent-source.json", {
        "schema": "tavonel.test.spent_source.v1", "lineage_ids": ["old:seed"]
    })
    body["sources"][0]["sha256"] = sfir1.sha_file(source)
    body["content_digest"] = sfir1._content_digest(body)
    path = _write_json(root / "authorities" / "spent.json", body)
    return {"path": path.relative_to(root).as_posix(), "sha256": sfir1.sha_file(path)}


def _candidate(family: str, index: int) -> dict:
    lineage = (
        f"git:sfir1/test:doc-{index:04d}.md" if family == "git_docs" else
        f"ecfr:1:1:{index:04d}" if family == "regulation_ecfr" else
        f"wiki:en:{index + 10000}"
    )
    return {
        "root_container_id": (
            "git:sfir1/test" if family == "git_docs" else
            "ecfr:1:1" if family == "regulation_ecfr" else
            "wikipedia:en:category:sfir1_test"
        ),
        "lineage_id": lineage,
        "family": family,
        "container_id": f"sfir1:{family}:container-{index // 100:02d}",
        "alias_ids": [],
        "payload_ref": {
            "before": f"metadata://{family}/revision/{index:04d}/before",
            "after": f"metadata://{family}/revision/{index:04d}/after",
        },
        "revision_id": {"before": f"r{index}:0", "after": f"r{index}:1"},
        "revision_timestamp": {"before": "2026-01-01T00:00:00Z", "after": "2026-01-02T00:00:00Z"},
        "capability_exercise": {
            "E5": index % 2 == 0,
            "E6": index % 3 == 0,
            "E9": index % 5 == 0,
        },
    }


def _metadata(count: int = 750) -> dict:
    return {
        "schema": sfir1.CAPACITY_INPUT_SCHEMA,
        "protocol_id": sfir1.PROTOCOL_ID,
        "families": {
            family: {
                "authority": sfir1.sources.FAMILY_AUTHORITIES[family],
                "snapshot_id": f"snapshot:{family}:001",
                "pagination": {"pages_fetched": 2, "exhausted": True, "rate_limit_retries": 0, "cap_reached": False},
                "candidates": [_candidate(family, index) for index in range(count)],
            }
            for family in sfir1.sources.FAMILIES
        },
    }


def _seed(root: Path, count: int = 750):
    charter = root / "protocols" / "charter.yaml"
    charter.parent.mkdir(parents=True)
    charter.write_text(
        (NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1_DESIGN_CHARTER.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    protocol = root / "protocols" / "protocol.yaml"
    protocol.write_text(
        (NS / "protocols" / "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V1.yaml").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    metadata = _write_json(root / "inputs" / "metadata.json", _metadata(count))
    spent = _spent(root)
    charter_authority = root / "receipts" / "charter.json"
    sfir1.freeze_design_charter(root, charter, charter_authority, STAMP)
    return charter, protocol, metadata, spent, charter_authority


def _capacity(root: Path, metadata: Path, spent: dict, charter_authority: Path) -> Path:
    path = root / "receipts" / "capacity.json"
    sfir1.seal_capacity_census(
        root,
        metadata,
        charter_authority,
        sfir1.sha_file(charter_authority),
        spent,
        path,
        STAMP,
    )
    return path


def test_full_pre_payload_authority_chain_is_exact_and_deterministic(tmp_path: Path) -> None:
    charter, protocol, metadata, spent, charter_authority = _seed(tmp_path)
    capacity = _capacity(tmp_path, metadata, spent, charter_authority)
    roster_path = tmp_path / "artifacts" / "roster.json"
    roster_authority = tmp_path / "receipts" / "roster-authority.json"
    sfir1.freeze_roster(
        tmp_path,
        metadata,
        charter_authority,
        sfir1.sha_file(charter_authority),
        capacity,
        sfir1.sha_file(capacity),
        spent,
        roster_path,
        roster_authority,
        STAMP,
    )
    freeze = tmp_path / "receipts" / "protocol-freeze.json"
    sfir1.freeze_protocol(
        tmp_path,
        protocol,
        charter_authority,
        sfir1.sha_file(charter_authority),
        capacity,
        sfir1.sha_file(capacity),
        roster_authority,
        sfir1.sha_file(roster_authority),
        freeze,
        STAMP,
    )

    census = json.loads(capacity.read_text(encoding="utf-8"))
    assert {family: block["Q_f"] for family, block in census["families"].items()} == {
        family: 600 for family in sfir1.sources.FAMILIES
    }
    roster = json.loads(roster_path.read_text(encoding="utf-8"))
    assert len(roster["candidates"]) == 1800
    assert roster["payload_opened"] is False
    for family in sfir1.sources.FAMILIES:
        rows = [row for row in roster["candidates"] if row["family"] == family]
        assert [row["selection_rank"] for row in rows] == list(range(1, 601))
        assert [row["selection_key"] for row in rows] == sorted(
            row["selection_key"] for row in rows
        )
        assert all(set(row["capability_exercise"]) == {"E5", "E6", "E9"} for row in rows)
        assert all(row["provenance"]["capacity_authority_sha256"] == sfir1.sha_file(capacity) for row in rows)
    verified = sfir1.verify_authority(
        tmp_path, freeze, sfir1.sha_file(freeze), sfir1.PROTOCOL_FREEZE_SCHEMA
    )
    assert verified["roster"]["sha256"] == sfir1.sha_file(roster_authority)
    assert verified["roster_subject"]["sha256"] == sfir1.sha_file(roster_path)
    assert verified["gpu_authorized"] is False
    assert verified["scoring_authorized"] is False
    assert verified["scoring_requires_exactly_once_acquisition_authority"] is True


@pytest.mark.parametrize("forbidden", ["payload", "diffs", "source_facts", "parsed_units", "verdict"])
def test_capacity_refuses_pre_freeze_scientific_material(tmp_path: Path, forbidden: str) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    body["families"]["git_docs"]["candidates"][0][forbidden] = "observed"
    _write_json(metadata, body)
    with pytest.raises(sfir1.SFIR1Refused, match="forbidden field"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_capacity_refuses_family_below_predeclared_q_floor(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path, count=749)
    with pytest.raises(sfir1.SFIR1Refused, match="Q_f=599"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_capacity_refuses_wrong_fixed_source_authority(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    body["families"]["git_docs"]["authority"] = "AN_OUTCOME_AWARE_SCRAPER"
    _write_json(metadata, body)
    with pytest.raises(sfir1.SFIR1Refused, match="authority drifted"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_capacity_refuses_incomplete_or_truncated_pagination(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    body["families"]["git_docs"]["pagination"]["exhausted"] = False
    _write_json(metadata, body)
    with pytest.raises(sfir1.SFIR1Refused, match="pagination was not exhausted"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_capacity_refuses_spent_container_and_lineage(tmp_path: Path) -> None:
    _charter, _protocol, metadata, _spent_unused, charter_authority = _seed(tmp_path)
    spent = _spent(
        tmp_path,
        containers=["sfir1:git_docs:container-00"],
        lineages=["old:lineage"],
    )
    with pytest.raises(sfir1.SFIR1Refused, match="spent root/container/lineage/alias collision"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_capacity_refuses_duplicate_lineage_within_family(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    body["families"]["git_docs"]["candidates"][1]["lineage_id"] = body[
        "families"
    ]["git_docs"]["candidates"][0]["lineage_id"]
    _write_json(metadata, body)
    with pytest.raises(sfir1.SFIR1Refused, match="duplicate lineage"):
        _capacity(tmp_path, metadata, spent, charter_authority)


def test_authority_refuses_digest_schema_protocol_and_content_tampering(tmp_path: Path) -> None:
    _charter, _protocol, _metadata, _spent_ref, charter_authority = _seed(tmp_path)
    good_sha = sfir1.sha_file(charter_authority)
    with pytest.raises(sfir1.SFIR1Refused, match="explicit digest mismatch"):
        sfir1.verify_authority(
            tmp_path, charter_authority, "sha256:" + "0" * 64, sfir1.CHARTER_SCHEMA
        )

    body = json.loads(charter_authority.read_text(encoding="utf-8"))
    body["protocol_id"] = "ANOTHER_STUDY"
    _write_json(charter_authority, body)
    with pytest.raises(sfir1.SFIR1Refused, match="another protocol"):
        sfir1.verify_authority(
            tmp_path, charter_authority, sfir1.sha_file(charter_authority), sfir1.CHARTER_SCHEMA
        )
    body["protocol_id"] = sfir1.PROTOCOL_ID
    body["payload_opened"] = True
    _write_json(charter_authority, body)
    with pytest.raises(sfir1.SFIR1Refused, match="content_digest mismatch"):
        sfir1.verify_authority(
            tmp_path, charter_authority, sfir1.sha_file(charter_authority), sfir1.CHARTER_SCHEMA
        )
    assert good_sha.startswith("sha256:")


def test_charter_freeze_refuses_endpoint_or_threshold_drift(tmp_path: Path) -> None:
    charter, _protocol, _metadata, _spent_ref, _charter_authority = _seed(tmp_path)
    body = __import__("yaml").safe_load(charter.read_text(encoding="utf-8"))
    body["analysis_floor"]["capability_exercising_pairs"]["E9"] = 28
    charter.write_text(__import__("yaml").safe_dump(body, sort_keys=False), encoding="utf-8")
    with pytest.raises(sfir1.SFIR1Refused, match="capability exercising floors drifted"):
        sfir1.freeze_design_charter(
            tmp_path, charter, tmp_path / "receipts" / "other-charter.json", STAMP
        )


def test_immutable_destination_refuses_second_authority(tmp_path: Path) -> None:
    charter, _protocol, _metadata, _spent_ref, charter_authority = _seed(tmp_path)
    with pytest.raises(sfir1.SFIR1Refused, match="already exists"):
        sfir1.freeze_design_charter(tmp_path, charter, charter_authority, STAMP)


def test_roster_refuses_capacity_metadata_mutation(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    capacity = _capacity(tmp_path, metadata, spent, charter_authority)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    body["families"]["git_docs"]["candidates"][0]["payload_ref"]["after"] += "?changed"
    _write_json(metadata, body)
    with pytest.raises(sfir1.SFIR1Refused, match="subject digest mismatch|metadata changed"):
        sfir1.freeze_roster(
            tmp_path,
            metadata,
            charter_authority,
            sfir1.sha_file(charter_authority),
            capacity,
            sfir1.sha_file(capacity),
            spent,
            tmp_path / "artifacts" / "roster.json",
            tmp_path / "receipts" / "roster.json",
            STAMP,
        )


def test_roster_refuses_predeclared_capability_underpower(tmp_path: Path) -> None:
    _charter, _protocol, metadata, spent, charter_authority = _seed(tmp_path)
    body = json.loads(metadata.read_text(encoding="utf-8"))
    for family in sfir1.sources.FAMILIES:
        for row in body["families"][family]["candidates"]:
            row["capability_exercise"]["E9"] = False
    _write_json(metadata, body)
    # Re-census the exact modified metadata; capability flags are prospective
    # strata and therefore legal metadata, but an underpowered frozen roster is not.
    capacity = _capacity(tmp_path, metadata, spent, charter_authority)
    with pytest.raises(sfir1.SFIR1Refused, match="capability exercising floors"):
        sfir1.freeze_roster(
            tmp_path,
            metadata,
            charter_authority,
            sfir1.sha_file(charter_authority),
            capacity,
            sfir1.sha_file(capacity),
            spent,
            tmp_path / "artifacts" / "roster.json",
            tmp_path / "receipts" / "roster.json",
            STAMP,
        )
