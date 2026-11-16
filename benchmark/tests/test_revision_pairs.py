from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchmark.revision_pairs import build_corpus as bc
from benchmark.revision_pairs import to_product_core as tpc

SHA_A, SHA_B = "a" * 40, "b" * 40


def _control(cid: str, prose: str, *, withdrawn: bool = False) -> dict:
    if withdrawn:
        return {
            "id": cid,
            "title": f"Title {cid}",
            "props": [{"name": "status", "value": "withdrawn"}],
            "links": [{"href": "#zz-9", "rel": "incorporated-into"}],
        }
    return {
        "id": cid,
        "title": f"Title {cid}",
        "parts": [
            {
                "id": f"{cid}_smt",
                "name": "statement",
                "parts": [{"id": f"{cid}_smt.a", "prose": prose}],
            },
            {"id": f"{cid}_gdn", "name": "guidance", "prose": f"guidance {cid}"},
        ],
    }


def _catalog(version: str, controls: list[dict], published: str | None = None) -> dict:
    meta = {"title": "t", "version": version, "last-modified": "2026-01-01T00:00:00Z"}
    if published:
        meta["published"] = published
    return {"catalog": {"metadata": meta, "groups": [{"id": "sa", "controls": controls}]}}


def _bytes(catalog: dict) -> bytes:
    return json.dumps(catalog, sort_keys=True).encode()


def _fake(releases: dict[str, dict], *, licence: bool = True):
    """releases: tag -> catalog. Commit shas are derived from the tag position."""
    shas = {tag: f"{i:040x}" for i, tag in enumerate(releases, start=1)}

    def fetch(url: str) -> bytes:
        if "/tags?" in url:
            return json.dumps([{"name": t, "commit": {"sha": s}} for t, s in shas.items()]).encode()
        for tag, sha in shas.items():
            if f"/{sha}/{bc.CATALOG_PATH}" in url:
                return _bytes(releases[tag])
            if licence and url.endswith(f"/{sha}/LICENSE.md"):
                return b"\n\nPublic domain notice\nmore"
        raise bc.NotFound(url)

    return fetch


RELEASES = {
    "v1.0.0": _catalog("5.0.0", [_control("sa-1", "one"), _control("sa-2", "two")]),
    "v1.1.0": _catalog(
        "5.1.0",
        [_control("sa-1", "one"), _control("sa-2", "two changed"), _control("sa-3", "three")],
        published="2026-02-02",
    ),
    "v1.2.0": _catalog(
        "5.2.0",
        [
            _control("sa-1", "one"),
            _control("sa-2", "two changed", withdrawn=True),
            _control("sa-3", "three"),
        ],
    ),
}


def test_parts_become_regions_with_stable_native_ids():
    docs, _ = tpc.docs_from_catalog(RELEASES["v1.0.0"])["sa"]
    doc = docs["sa-1"]
    assert doc.connector_type == "nist-oscal" and doc.native_id == "sa-1"
    assert [r.native_object_id for r in doc.regions] == ["sa-1_smt.a", "sa-1_gdn"]
    assert [r.region_id for r in doc.regions] == ["sa-1_smt.a", "sa-1_gdn"]
    assert all(r.authority == "official" and r.page_index0 == 0 for r in doc.regions)
    again, _ = tpc.docs_from_catalog(copy.deepcopy(RELEASES["v1.0.0"]))["sa"]
    assert again["sa-1"].content_sha256 == doc.content_sha256


def test_no_bbox_is_ever_fabricated():
    for docs, _ in tpc.docs_from_catalog(RELEASES["v1.2.0"]).values():
        assert all(r.bbox1000 is None for d in docs.values() for r in d.regions)


def test_stratum_labels_follow_the_diff():
    s = bc.stratum
    base = {"a": "1", "b": "2"}
    none = frozenset()
    assert s(base, dict(base), none, none) == "unchanged"
    assert s(base, {"a": "1", "b": "9"}, none, none) == "modified"
    assert s(base, {**base, "c": "3"}, none, none) == "controls_added"
    assert s(base, {"a": "1", "b": "9"}, none, frozenset({"b"})) == "controls_withdrawn"
    assert s(base, {"a": "1"}, none, none) == "controls_withdrawn"
    assert s(base, {"a": "5", "b": "2", "c": "3"}, none, none) == "mixed"


def test_missing_published_date_stays_null(tmp_path: Path):
    manifest = bc.build(tmp_path, 1, 100, _fake(RELEASES), include_ecfr=False)
    by_version = {s["version"]: s for s in manifest["snapshots"]}
    assert by_version["5.0.0"]["published"] is None
    assert by_version["5.1.0"]["published"] == "2026-02-02"
    assert by_version["5.0.0"]["last_modified"] == "2026-01-01T00:00:00Z"


def test_fewer_real_pairs_than_target_is_reported_not_padded(tmp_path: Path):
    manifest = bc.build(tmp_path, 1, 100, _fake(RELEASES), include_ecfr=False)
    assert manifest["real_pair_count"] == len(manifest["pairs"]) == 3  # 1 family x C(3,2) releases
    assert manifest["shortfall"] == 97
    assert manifest["ecfr_status"] == "not_requested"
    assert {p["stratum"] for p in manifest["pairs"]} == {"mixed", "controls_withdrawn"}
    assert bc.select_pairs(manifest["pairs"], 2, 7) == bc.select_pairs(manifest["pairs"], 2, 7)
    assert len(bc.select_pairs(manifest["pairs"], 2, 7)) == 2


def test_builder_stops_when_the_pinned_commit_has_no_licence(tmp_path: Path):
    with pytest.raises(tpc.CorpusError, match="no LICENSE"):
        bc.build(tmp_path, 1, 100, _fake(RELEASES, licence=False), include_ecfr=False)


def test_load_pair_round_trip_and_refuses_a_hash_mismatch(tmp_path: Path):
    manifest = bc.build(tmp_path, 1, 100, _fake(RELEASES), include_ecfr=False)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    pair_id = manifest["pairs"][0]["pair_id"]
    before, after = tpc.load_pair(pair_id, tmp_path, path)
    assert before and after and bc.verify(path, tmp_path) == 3
    snap = manifest["pairs"][0]["before"]["snapshot"]
    (tmp_path / snap / "catalog.json").write_bytes(b'{"catalog": {"tampered": true}}')
    with pytest.raises(tpc.CorpusError, match="hash mismatch"):
        tpc.load_pair(pair_id, tmp_path, path)
    with pytest.raises(tpc.CorpusError, match="unknown pair"):
        tpc.load_pair("nope", tmp_path, path)


def test_ecfr_sections_become_documents_per_subpart():
    xml = (
        b'<DIV5 N="200" TYPE="PART"><DIV6 N="A" TYPE="SUBPART">'
        b'<DIV8 N="\xc2\xa7 200.1" TYPE="SECTION"><HEAD>\xc2\xa7 200.1 Purpose.</HEAD>'
        b"<P>First.</P><P>Second.</P></DIV8>"
        b'<DIV8 N="200.2" TYPE="SECTION"><HEAD>200.2 Reserved</HEAD></DIV8></DIV6></DIV5>'
    )
    docs, withdrawn = tpc.docs_from_ecfr_xml(xml, "2024-10-01")["A"]
    assert sorted(docs) == ["200.1", "200.2"] and not withdrawn
    assert [r.text for r in docs["200.1"].regions] == ["First.", "Second."]
    assert docs["200.2"].regions[0].native_object_id == "200.2_title"
