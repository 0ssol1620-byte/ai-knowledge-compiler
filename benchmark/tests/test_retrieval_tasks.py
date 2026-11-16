from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchmark.retrieval_baselines import build_tasks as bt
from benchmark.retrieval_baselines.metrics import parse_task
from benchmark.retrieval_baselines.run_baselines import Corpus
from benchmark.revision_pairs import build_corpus as bc

FAMILIES = [f"f{c}" for c in "abcdefghijkl"]
DATES = {
    "5.0.0": "2021-06-08T13:57:33-04:00",
    "5.1.0": "2023-10-12T00:00:00-04:00",
    "5.2.0": "2025-08-26T14:33:16-00:00",
}


def _control(fam: str, i: int, rel: int) -> dict:
    prose = f"The organization shall enforce the policy for tok{fam}{i} access."
    if rel >= 1 and i % 3 == 0:
        prose = prose[:-1] + " during the amended review."
    if rel >= 2 and i % 7 == 1:  # withdrawn at the last release, never one of the modified
        return {
            "id": f"{fam}-{i}", "title": f"The organization shall manage {fam} {i}.",
            "props": [{"name": "status", "value": "withdrawn"}],
            "links": [{"href": "#fa-2", "rel": "incorporated-into"}],
        }  # fmt: skip
    return {
        "id": f"{fam}-{i}", "title": f"The organization shall manage {fam} {i}.",
        "parts": [{"id": f"{fam}-{i}_smt", "name": "statement", "prose": prose}],
    }  # fmt: skip


def _catalog(rel: int, version: str) -> dict:
    n = 20 + (2 if rel >= 1 else 0)
    meta = {"title": "t", "version": version, "last-modified": DATES[version]}
    if version == "5.1.0":
        meta["published"] = "2023-10-13T00:00:00Z"
    groups = [
        {"id": f, "controls": [_control(f, i, rel) for i in range(1, n + 1)]} for f in FAMILIES
    ]
    return {"catalog": {"metadata": meta, "groups": groups}}


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    cache = tmp_path_factory.mktemp("cache")
    releases = {f"v{i}": _catalog(i, v) for i, v in enumerate(DATES)}
    shas = {t: f"{i:040x}" for i, t in enumerate(releases, start=1)}

    def fetch(url: str) -> bytes:
        if "/tags?" in url:
            return json.dumps([{"name": t, "commit": {"sha": s}} for t, s in shas.items()]).encode()
        for t, s in shas.items():
            if f"/{s}/{bc.CATALOG_PATH}" in url:
                return json.dumps(releases[t], sort_keys=True).encode()
            if url.endswith(f"/{s}/LICENSE.md"):
                return b"Public domain\n"
        raise bc.NotFound(url)

    manifest = bc.build(cache, 7, 100, fetch, include_ecfr=False)
    path = cache / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, cache, path


@pytest.fixture(scope="module")
def result(frozen):
    manifest, cache, _ = frozen
    return bt.build(manifest, cache, 11)


def _by(result, **eq):
    return [t for t in result["tasks"] if all(t[k] == v for k, v in eq.items())]


def test_counts_meet_the_floors(frozen, result, tmp_path: Path):
    _, _, path = frozen
    summary = bt.write(result, tmp_path, path, 11)
    kinds, strata = summary["counts_by_kind"], summary["counts_by_stratum"]
    assert kinds["retrieval"] >= 200 and kinds["temporal"] >= 200
    assert strata["acl_base"] >= 50 and strata["acl_variant"] >= 1000
    assert summary["shortfall"] == {}
    assert set(strata) >= {
        "added_later",
        "withdrawn",
        "modified",
        "late_recorded",
        "unknown_availability",
    }
    assert "backdated: source carries no recorded_at later than valid_from" in summary["skipped"]
    assert summary["corpus_manifest_sha256"] and summary["provenance"] == "generated"


def test_a_floor_that_is_not_met_is_reported_and_exits_nonzero(frozen, tmp_path: Path):
    _, cache, path = frozen
    small = json.loads(path.read_text())
    small["pairs"] = small["pairs"][:2]
    small_path = tmp_path / "m.json"
    small_path.write_text(json.dumps(small))
    code = bt.main(
        ["--cache-dir", str(cache), "--manifest", str(small_path), "--out", str(tmp_path / "o")]
    )
    assert code == 1
    assert json.loads((tmp_path / "o/tasks_manifest.json").read_text())["shortfall"]["temporal"] > 0


def test_no_task_uses_a_date_the_source_did_not_carry(frozen, result):
    manifest, _, _ = frozen
    carried = {
        datetime.fromisoformat(s["last_modified"]).isoformat() for s in manifest["snapshots"]
    }
    for t in result["tasks"]:
        for key, value in (t["cut"] or {}).items():
            assert key in ("valid_at", "known_at", "available_at")
            assert value in carried, (t["task_id"], value)
    for row in result["corpus"]:
        meta = row["metadata"]
        assert meta["valid_from"] in carried and meta["recorded_at"] == meta["valid_from"]
        assert meta["valid_to"] is None or meta["valid_to"] in carried
        assert meta["available_at"] in (
            None,
            "2023-10-13T00:00:00Z",
        )  # never filled from last_modified
    unknown = _by(result, stratum="unknown_availability")
    assert unknown and all(not t["answerable"] for t in unknown)


def test_added_later_tasks_are_unanswerable(result):
    tasks = _by(result, stratum="added_later")
    assert tasks and all(not t["answerable"] and t["gold_evidence_ids"] == [] for t in tasks)
    assert all(t["cut"]["valid_at"] == t["cut"]["known_at"] for t in tasks)
    modified = _by(result, stratum="modified")
    pairs: dict[tuple, set] = {}
    for t in modified:
        pairs.setdefault((t["family"], t["control_id"]), set()).add(
            frozenset(t["gold_evidence_ids"])
        )
    assert all(len(g) == 2 for g in pairs.values())  # different gold at r and r'
    assert all(t["answerable"] for t in _by(result, stratum="withdrawn"))


def test_acl_tasks_never_have_gold_in_the_asking_tenant(result):
    acl = _by(result, kind="acl_negative")
    assert len(acl) >= 1050 and all(
        t["gold_evidence_ids"] == [] and not t["answerable"] for t in acl
    )
    own: dict[str, str] = {}
    for r in result["corpus"]:
        own[r["tenant"]] = own.get(r["tenant"], "") + " " + r["text"].lower()
    templates = [x.replace("{t}", "").strip() for x in bt.ACL_VARIANTS]
    for t in acl:
        term = next(
            w
            for w in t["query"].split()
            if w.startswith("tok") or w not in " ".join(templates).split()
        )
        assert term not in own[t["tenant"]].split(), t["query"]


def test_generation_is_deterministic(frozen, result):
    manifest, cache, _ = frozen
    again = bt.build(manifest, cache, 11)
    assert bt._jsonl(again["tasks"]) == bt._jsonl(result["tasks"])
    assert bt._jsonl(again["corpus"]) == bt._jsonl(result["corpus"])
    assert bt._jsonl(bt.build(manifest, cache, 12)["tasks"]) != bt._jsonl(result["tasks"])


def test_every_task_is_labelled_generated_and_parses_against_the_harness_contract(result):
    corpus = Corpus(result["corpus"])
    known = {e for ids in corpus.evidence_of.values() for e in ids}
    for row in result["tasks"]:
        task = parse_task(row)
        assert task.provenance == "generated" and task.generator == bt.GENERATOR and task.seed == 11
        assert task.gold_evidence_ids <= known
        assert {
            corpus.tenant_of[lid]
            for lid, e in corpus.evidence_of.items()
            if e & task.gold_evidence_ids
        } <= {task.tenant}
