from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import build_gpu_successor_v2_contexts as contexts  # noqa: E402
from common import canonical_sha, sha_file  # noqa: E402


def _write(path: Path, body: dict) -> Path:
    path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return path


def _fixture(tmp_path: Path):
    acceptance = _write(tmp_path / "sfir4.json", {"verdict": "PASS"})
    facts = [{"fact_id": f"f-{index:03d}"} for index in range(450)]
    manifest = {
        "facts": facts,
        "facts_digest": canonical_sha(facts),
        "source_sfir4_acceptance": {"sha256": sha_file(acceptance)},
    }
    manifest_path = _write(tmp_path / "manifest.json", manifest)
    by_fact = {}
    for fact in facts:
        arms = {}
        for arm, (currency, mode) in contexts.ARM_SEMANTICS.items():
            text = f"{fact['fact_id']} {arm}"
            arms[arm] = [
                {
                    "atom_id": arm,
                    "path": f"docs/{arm}.json",
                    "text": text,
                    "text_sha256": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
                    "currency": currency,
                    "representation_mode": mode,
                }
            ]
        by_fact[fact["fact_id"]] = arms
    sources = {
        "schema": contexts.SOURCE_SCHEMA,
        "successor_manifest_sha256": sha_file(manifest_path),
        "sfir4_acceptance_sha256": sha_file(acceptance),
        "context_by_fact": by_fact,
    }
    return manifest_path, _write(tmp_path / "sources.json", sources)


def test_builds_exact_three_arm_context_artifact(tmp_path):
    manifest, sources = _fixture(tmp_path)
    result = contexts.build(manifest_path=manifest, source_path=sources)
    assert len(result["context_by_fact"]) == 450
    assert result["successor_manifest_sha256"] == sha_file(manifest)
    assert result["sfir4_acceptance_sha256"]


def test_refuses_semantic_arm_swap(tmp_path):
    manifest, sources = _fixture(tmp_path)
    body = json.loads(sources.read_text(encoding="utf-8"))
    body["context_by_fact"]["f-000"]["STALE_TYPED"][0]["currency"] = "current"
    _write(sources, body)
    with pytest.raises(contexts.ContextBuildRefused, match="semantics drifted"):
        contexts.build(manifest_path=manifest, source_path=sources)
