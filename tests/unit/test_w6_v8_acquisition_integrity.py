"""Break controls for the v8 holdout acquisition integrity gate.

The gate stands between a finished acquisition and the question set. Every
condition it claims is falsified here against a synthetic corpus written to a
temporary directory: a fail-closed gate that has never closed is
indistinguishable from `assert True`, and this programme has already shipped one
guard that read a key the seal does not have and therefore passed everything.

The synthetic corpus is deliberately built to satisfy every check, so that each
test breaks exactly one thing and the gate must name that one.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "research" / "experiments" / "H1-W6-SAME-INTELLIGENCE-01"
GATE = EXP / "scripts" / "verify_holdout_corpus_v8.py"


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("w6_integrity_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["w6_integrity_gate"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A corpus, a receipt, a sidecar and a manifest that all agree."""
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    # The gate resolves record paths against the experiment root, so point it at
    # the temporary tree rather than the real corpus.
    monkeypatch.setattr(gate, "EXP", tmp_path)

    records = []
    for index, title in enumerate(["Alpha article", "Beta article"], start=1):
        digest = hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
        directory = corpus / f"{index:05d}-{digest}"
        directory.mkdir()
        before = directory / "before.wikitext"
        after = directory / "after.wikitext"
        before.write_text(f"{title} before\n", encoding="utf-8")
        after.write_text(f"{title} after\n", encoding="utf-8")
        record = {
            "manifest_index": index,
            "title": title,
            "before_revision_id": 100 + index,
            "after_revision_id": 200 + index,
            "before_sha256": _sha256(before),
            "after_sha256": _sha256(after),
            "relative_before_path": str(before.relative_to(tmp_path)).replace("\\", "/"),
            "relative_after_path": str(after.relative_to(tmp_path)).replace("\\", "/"),
        }
        (directory / "metadata.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        records.append(record)

    manifest = tmp_path / "manifest.json"
    manifest_body = {
        "receipt_sha256": "sha256:manifest-receipt",
        "titles": [{"index": 1, "title": "Alpha article"},
                   {"index": 2, "title": "Beta article"},
                   {"index": 3, "title": "Gamma article"}],
    }
    manifest.write_text(json.dumps(manifest_body, indent=2), encoding="utf-8")

    acquisition = tmp_path / "acquisition.json"
    acquisition.write_text(json.dumps({
        "schema": "tavonel.w6-v3-acquisition.v1",
        "protocol_sha256": gate.file_sha256(gate.V3_PROTOCOL),
        "acquisition_script_sha256": gate.file_sha256(gate.V3_SCRIPT),
        "title_manifest_receipt_sha256": "sha256:manifest-receipt",
        "title_manifest_file_sha256": gate.file_sha256(manifest),
        "cohorts_completed": 1,
        "cohort_size": 3,
        "eligible_records": 2,
        "excluded_records": 1,
        "records": records,
        "exclusions": [{"index": 3, "title": "Gamma article",
                        "reason": "missing_snapshot_revision"}],
    }, indent=2), encoding="utf-8")

    sidecar = tmp_path / "sidecar.json"
    sidecar.write_text(json.dumps({"return_code": 0}), encoding="utf-8")

    seal = tmp_path / "seal.json"
    seal.write_text(json.dumps({
        "development_titles_excluded_from_v8": {"count": 1, "titles": ["Delta article"]},
    }), encoding="utf-8")
    monkeypatch.setattr(gate, "SEAL", seal)

    return {"corpus": corpus, "manifest": manifest, "acquisition": acquisition,
            "sidecar": sidecar, "seal": seal, "tmp": tmp_path}


def run(world: dict[str, Any]) -> dict[str, Any]:
    return gate.evaluate(acquisition=world["acquisition"], sidecar=world["sidecar"],
                         corpus=world["corpus"], manifest=world["manifest"])


def rewrite(path: Path, mutate: Any) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    mutate(body)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def test_clean_world_passes(world: dict[str, Any]) -> None:
    result = run(world)
    assert result["passes"], result["failed"]
    assert result["pairs_verified"] == 2
    assert result["corpus_root_hash"].startswith("sha256:")


def test_root_hash_is_order_independent_but_content_sensitive(world: dict[str, Any]) -> None:
    first = run(world)["corpus_root_hash"]
    assert run(world)["corpus_root_hash"] == first
    target = next(world["corpus"].glob("*/after.wikitext"))
    target.write_text("something else\n", encoding="utf-8")
    assert run(world)["corpus_root_hash"] != first


def test_missing_sidecar_refuses(world: dict[str, Any]) -> None:
    world["sidecar"].unlink()
    assert "process_exit_status" in run(world)["failed"]


def test_nonzero_exit_refuses(world: dict[str, Any]) -> None:
    rewrite(world["sidecar"], lambda b: b.update({"return_code": 1}))
    assert "process_exit_status" in run(world)["failed"]


def test_receipt_not_bound_to_manifest_refuses(world: dict[str, Any]) -> None:
    rewrite(world["acquisition"],
            lambda b: b.update({"title_manifest_receipt_sha256": "sha256:other"}))
    assert "acquisition_receipt" in run(world)["failed"]


def test_receipt_not_bound_to_script_bytes_refuses(world: dict[str, Any]) -> None:
    rewrite(world["acquisition"],
            lambda b: b.update({"acquisition_script_sha256": "sha256:other"}))
    assert "acquisition_receipt" in run(world)["failed"]


def test_unaccounted_title_refuses(world: dict[str, Any]) -> None:
    """A title that is neither eligible nor excluded has vanished silently."""
    rewrite(world["acquisition"], lambda b: (b.__setitem__("exclusions", []),
                                             b.__setitem__("excluded_records", 0)))
    assert "accounting_reconciles" in run(world)["failed"]


def test_incomplete_directory_refuses(world: dict[str, Any]) -> None:
    next(world["corpus"].glob("*/metadata.json")).unlink()
    assert "no_incomplete_directories" in run(world)["failed"]


def test_empty_corpus_refuses(world: dict[str, Any]) -> None:
    for directory in world["corpus"].iterdir():
        for child in directory.iterdir():
            child.unlink()
        directory.rmdir()
    result = run(world)
    assert "no_incomplete_directories" in result["failed"]


def test_duplicate_record_refuses(world: dict[str, Any]) -> None:
    rewrite(world["acquisition"],
            lambda b: b.__setitem__("records", b["records"] + [b["records"][0]]))
    assert "no_duplicates" in run(world)["failed"]


def test_metadata_older_than_payload_refuses(world: dict[str, Any]) -> None:
    directory = next(iter(sorted(world["corpus"].iterdir())))
    meta = directory / "metadata.json"
    payload = directory / "after.wikitext"
    stamp = payload.stat().st_mtime
    os.utime(meta, (stamp - 60, stamp - 60))
    assert "metadata_written_last" in run(world)["failed"]


def test_content_changed_after_hashing_refuses(world: dict[str, Any]) -> None:
    next(world["corpus"].glob("*/before.wikitext")).write_text("tampered\n", encoding="utf-8")
    assert "per_pair_hashes_match" in run(world)["failed"]


def test_missing_payload_file_refuses(world: dict[str, Any]) -> None:
    next(world["corpus"].glob("*/before.wikitext")).unlink()
    result = run(world)
    assert "per_pair_hashes_match" in result["failed"]


def test_development_overlap_refuses(world: dict[str, Any]) -> None:
    world["seal"].write_text(json.dumps({
        "development_titles_excluded_from_v8": {"count": 1, "titles": ["Alpha article"]},
    }), encoding="utf-8")
    assert "untouched_disjointness" in run(world)["failed"]


def test_empty_development_seal_refuses(world: dict[str, Any]) -> None:
    """An empty list would make the check inert, which is worse than no check."""
    world["seal"].write_text(json.dumps({
        "development_titles_excluded_from_v8": {"count": 0, "titles": []},
    }), encoding="utf-8")
    assert "untouched_disjointness" in run(world)["failed"]


def test_title_from_outside_the_manifest_refuses(world: dict[str, Any]) -> None:
    def mutate(body: dict[str, Any]) -> None:
        body["records"][0]["title"] = "Smuggled article"
    rewrite(world["acquisition"], mutate)
    assert "untouched_disjointness" in run(world)["failed"]


def test_underscore_titles_normalize_the_same_way(world: dict[str, Any]) -> None:
    """Wikipedia titles arrive both ways; the disjointness check must not be
    fooled by an underscore."""
    def mutate(body: dict[str, Any]) -> None:
        body["records"][0]["title"] = "Alpha_article"
    rewrite(world["acquisition"], mutate)
    assert "untouched_disjointness" not in run(world)["failed"]
    world["seal"].write_text(json.dumps({
        "development_titles_excluded_from_v8": {"count": 1, "titles": ["Alpha_article"]},
    }), encoding="utf-8")
    assert "untouched_disjointness" in run(world)["failed"]


def test_gate_decides_nothing_about_the_endpoint() -> None:
    """The gate must not be able to influence a result: it holds no threshold,
    no scoring and no arm."""
    source = GATE.read_text(encoding="utf-8")
    for forbidden in ("score_answer", "BM25", "rm3", "top_k", "temperature",
                      "McNemar", "holm"):
        assert forbidden not in source
