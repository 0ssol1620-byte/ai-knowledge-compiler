from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import sfir1_spent_authority as spent  # noqa: E402


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _inventory(root: Path) -> list[dict[str, str]]:
    rows = []
    for index, generation in enumerate(sorted(spent.REQUIRED_GENERATIONS)):
        path = root / f"source-{index}.json"
        path.write_text(
            json.dumps(
                {"schema": "tavonel.test.identities.v1", "lineage_id": f"git:o/r:p{index}.md"}
            ),
            encoding="utf-8",
        )
        rows.append(
            {
                "generation": generation,
                "role": f"{generation}:mandatory",
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha(path),
                "kind": "json",
            }
        )
    return rows


def test_complete_inventory_builds_protocol_compatible_body_and_aliases(tmp_path: Path) -> None:
    rows = _inventory(tmp_path)
    special = tmp_path / rows[0]["path"]
    special.write_text(
        json.dumps(
            {
                "schema": "tavonel.test.identities.v1",
                "lineage_id": "ecfr:07:273:273.1",
                "source_id": "wikipedia:en:Old Title",
            }
        ),
        encoding="utf-8",
    )
    rows[0]["sha256"] = _sha(special)
    # A second synthetic looked-at lineage exercises container mirroring without
    # importing live root modules.
    root_row = rows[1]
    root_json = tmp_path / root_row["path"]
    root_json.write_text(
        json.dumps(
            {
                "schema": "tavonel.test.identities.v1",
                "lineage_id": "git:owner/repo:README.md",
                "container_id": "git:owner:repo:docs",
            }
        ),
        encoding="utf-8",
    )
    root_row["sha256"] = _sha(root_json)

    body = spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)
    assert "ecfr:7:273.1" in body["alias_ids"]
    assert "wiki:en:title:old title" in body["alias_ids"]
    assert "git:owner/repo:README.md" in body["container_ids"]
    assert set(body) == {
        "schema",
        "generated_at",
        "container_ids",
        "lineage_ids",
        "alias_ids",
        "sources",
        "content_digest",
    }


def test_root_module_emits_exact_root_container_namespaces() -> None:
    root = NS.parents[1]
    body = spent.assemble_spent_authority(root, "2026-08-26T00:00:00Z")
    assert "git:apache/kudu" in body["container_ids"]
    assert "ecfr:10:72" in body["container_ids"]
    assert "wikipedia:en:category:cities_in_chile" in body["container_ids"]
    assert "wikipedia:en:category:cities_in_chile" in body["alias_ids"]


def test_missing_generation_refuses(tmp_path: Path) -> None:
    rows = _inventory(tmp_path)[:-1]
    with pytest.raises(spent.SpentAuthorityRefused, match="generations"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)


def test_missing_or_drifted_mandatory_source_refuses(tmp_path: Path) -> None:
    rows = _inventory(tmp_path)
    Path(tmp_path / rows[0]["path"]).unlink()
    with pytest.raises(spent.SpentAuthorityRefused, match="absent"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)
    rows = _inventory(tmp_path)
    rows[0]["sha256"] = "sha256:" + "0" * 64
    with pytest.raises(spent.SpentAuthorityRefused, match="digest drift"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)


def test_duplicate_role_or_path_refuses_as_ambiguous(tmp_path: Path) -> None:
    rows = _inventory(tmp_path)
    rows[1]["role"] = rows[0]["role"]
    with pytest.raises(spent.SpentAuthorityRefused, match="ambiguous role"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)
    rows = _inventory(tmp_path)
    rows[1]["path"] = rows[0]["path"]
    with pytest.raises(spent.SpentAuthorityRefused, match="ambiguous path"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)


def test_json_without_identity_refuses(tmp_path: Path) -> None:
    rows = _inventory(tmp_path)
    path = tmp_path / rows[0]["path"]
    path.write_text(json.dumps({"schema": "tavonel.test.empty.v1", "count": 4}), encoding="utf-8")
    rows[0]["sha256"] = _sha(path)
    with pytest.raises(spent.SpentAuthorityRefused, match="contributes no identity"):
        spent.assemble_spent_authority(tmp_path, "2026-08-26T00:00:00Z", rows)


def test_normalises_historical_ecfr_and_wikipedia_aliases(tmp_path: Path) -> None:
    path = tmp_path / "ids.json"
    path.write_text(
        json.dumps(
            {
                "schema": "tavonel.test.ids.v1",
                "lineage_id": "ecfr:07:273:273.1",
                "source_id": "wikipedia:en:Old Title",
            }
        ),
        encoding="utf-8",
    )
    schema, lineages, aliases = spent._json_identities(path)
    assert schema == "tavonel.test.ids.v1"
    assert "ecfr:07:273:273.1" in lineages
    assert "ecfr:7:273.1" in aliases
    assert "wiki:en:title:old title" in aliases


def test_write_is_create_only(tmp_path: Path) -> None:
    destination = tmp_path / "authority.json"
    body = {"schema": spent.SCHEMA}
    spent.write_spent_authority(destination, body)
    with pytest.raises(spent.SpentAuthorityRefused, match="already exists"):
        spent.write_spent_authority(destination, body)


def test_live_default_inventory_is_exact_complete_and_protocol_digest_compatible() -> None:
    root = NS.parents[1]
    body = spent.assemble_spent_authority(root, "2026-08-26T00:00:00Z")
    assert len(body["sources"]) == len(spent.DEFAULT_INVENTORY) == 40
    assert len(body["container_ids"]) >= 9000
    assert len(body["lineage_ids"]) >= 9000
    assert len(body["alias_ids"]) >= len(body["lineage_ids"])
    assert {row["generation"] for row in body["sources"]} == spent.REQUIRED_GENERATIONS
    without_digest = {key: value for key, value in body.items() if key != "content_digest"}
    expected = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                without_digest, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
        ).hexdigest()
    )
    assert body["content_digest"] == expected
