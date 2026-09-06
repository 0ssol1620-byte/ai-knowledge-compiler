from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import score_sfir1 as scorer  # noqa: E402
import sfir1_acceptance as acceptance  # noqa: E402
import sfir1_execution as sx  # noqa: E402
import sfir1_protocol  # noqa: E402
import sfir1_worker as worker  # noqa: E402
import verify_sfir1_frame as frame  # noqa: E402


def _write(path: Path, body: object) -> str:
    path.write_text(json.dumps(body, sort_keys=True), encoding="utf-8")
    return sx.sha_file(path)


def _receipts(tmp_path: Path, count: int = 300) -> dict[str, tuple[Path, str]]:
    sx.ROOT = tmp_path
    flags = {name: True for requirements in sx.EXERCISE_REQUIREMENTS.values() for name in requirements}
    candidates = [
        {
            "lineage_id": f"L{i:03}",
            "family": ("git", "ecfr", "wiki")[i % 3],
            "container_id": f"C{i:03}",
            "payload_ref": {
                "before": f"metadata://revision/{i:03}/before",
                "after": f"metadata://revision/{i:03}/after",
            },
            "revision_id": {"before": f"r{i:03}-before", "after": f"r{i:03}-after"},
            "revision_timestamp": {
                "before": "2026-08-24T00:00:00Z",
                "after": "2026-08-25T00:00:00Z",
            },
            "capability_exercise": flags,
            "selection_rank": i + 1,
            "selection_key": f"{i:064x}",
            "provenance": {
                "capacity_subject_sha256": "sha256:" + "1" * 64,
                "capacity_authority_sha256": "sha256:" + "2" * 64,
                "candidate_digest": "sha256:" + "3" * 64,
            },
        }
        for i in range(count)
    ]
    roster_artifact = {
        "schema": "tavonel.sfir1.frozen_roster.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "candidates": candidates,
    }
    roster_artifact["content_digest"] = sfir1_protocol.digest(roster_artifact)
    roster_subject = tmp_path / "frozen-roster.json"
    _write(roster_subject, roster_artifact)

    result: dict[str, tuple[Path, str]] = {}
    subjects: dict[str, Path] = {}
    toolchain: dict[str, dict[str, str]] = {}
    for name in ("sources_sfir1", "probe_sfir1_capacity", "sfir1_spent_authority"):
        tool = tmp_path / f"{name}.py"
        _write(tool, {"tool": name})
        toolchain[name] = {
            "path": tool.relative_to(tmp_path).as_posix(),
            "sha256": sx.sha_file(tool),
        }
    for kind in ("charter", "capacity", "protocol_freeze"):
        subject = tmp_path / f"{kind}-subject.json"
        _write(subject, {"kind": kind})
        subjects[kind] = subject
    for kind in ("charter", "capacity", "roster"):
        subject = roster_subject if kind == "roster" else subjects[kind]
        body = {
            "schema": sx.SCHEMAS[kind],
            "protocol_id": sx.PROTOCOL_ID,
            "generated_at": "2026-08-26T00:00:00Z",
            "subject": {"path": subject.relative_to(tmp_path).as_posix(), "sha256": sx.sha_file(subject)},
        }
        if kind == "charter":
            body["toolchain"] = toolchain
        body["content_digest"] = sfir1_protocol.digest(body)
        path = tmp_path / f"{kind}.json"
        result[kind] = (path, _write(path, body))
    protocol_body = {
        "schema": sx.SCHEMAS["protocol_freeze"],
        "protocol_id": sx.PROTOCOL_ID,
        "generated_at": "2026-08-26T00:00:00Z",
        "subject": {"path": subjects["protocol_freeze"].relative_to(tmp_path).as_posix(), "sha256": sx.sha_file(subjects["protocol_freeze"])},
        **{
            kind: {"path": result[kind][0].relative_to(tmp_path).as_posix(), "sha256": result[kind][1]}
            for kind in ("charter", "capacity", "roster")
        },
        "acquisition_authorized": True,
        "score_exactly_once": True,
        "execution_toolchain": sx.execution_toolchain_manifest(),
    }
    protocol_body["content_digest"] = sfir1_protocol.digest(protocol_body)
    protocol_path = tmp_path / "protocol_freeze.json"
    result["protocol_freeze"] = (protocol_path, _write(protocol_path, protocol_body))
    return result


def _acquisition(tmp_path: Path, *, with_observations: bool = True) -> Path:
    receipts = _receipts(tmp_path)
    path = tmp_path / "acquisition.json"
    observations = None
    if with_observations:
        observations = {
            f"L{i:03}": {
                name: {"exercised": True, "violations": 0, "stages_checked": ["post_execution", "pre_activation"] if name == sx.VETO_ENDPOINT else []}
                for name in sx.ENDPOINTS
            }
            for i in range(300)
        }
    worker.build(receipts, observations=observations, target=path)
    return path


def test_reducer_is_deterministic_and_outcome_blind(tmp_path):
    receipts = _receipts(tmp_path)
    first = worker.build(receipts, target=tmp_path / "one.json")
    second = worker.build(receipts, target=tmp_path / "two.json")
    assert first["reduction_digest"] == second["reduction_digest"]
    assert first["outcome_blind_reduction"] is True


def test_worker_refuses_wrong_exact_hash(tmp_path):
    receipts = _receipts(tmp_path)
    receipts["charter"] = (receipts["charter"][0], "sha256:" + "0" * 64)
    with pytest.raises(sx.Refused, match="digest mismatch"):
        worker.build(receipts, target=tmp_path / "never.json")


def test_frame_thresholds_and_pre_score_power(tmp_path, monkeypatch):
    acquired = _acquisition(tmp_path, with_observations=True)
    authority = tmp_path / "sfir1-frame-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", authority)
    body = frame.seal(acquired, authority)
    assert body["state"] == "SCORABLE"
    assert body["counts"]["total"] == 300
    assert all(value >= 29 for value in body["exercise_power"].values())
    assert body["exercise_definition"]["score_outcomes_inspected"] is False


def test_frame_uses_actual_exercise_not_hash_derived_sampling_strata(tmp_path, monkeypatch):
    receipts = _receipts(tmp_path)
    path = tmp_path / "acquisition.json"
    observations = {
        f"L{i:03}": {
            name: {
                "exercised": not name.startswith("E5_"),
                "violations": 0,
                "stages_checked": ["post_execution", "pre_activation"] if name == sx.VETO_ENDPOINT else [],
            }
            for name in sx.ENDPOINTS
        }
        for i in range(300)
    }
    worker.build(receipts, observations=observations, target=path)
    authority = tmp_path / "sfir1-frame-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", authority)
    body = frame.seal(path, authority)
    assert body["predeclared_sampling_strata"]["E5_no_confirmed_selective_stale_escape"] == 300
    assert body["exercise_power"]["E5_no_confirmed_selective_stale_escape"] == 0
    assert body["state"] == "NOT_SCORABLE"


def test_scorer_independently_enforces_actual_exercise_floor():
    admitted = []
    for index in range(300):
        blocks = {
            endpoint: {
                "exercised": not endpoint.startswith("E5_") or index < sx.MIN_EXERCISING - 1,
                "violations": 0,
                "stages_checked": ["post_execution", "pre_activation"] if endpoint == sx.VETO_ENDPOINT else [],
            }
            for endpoint in sx.ENDPOINTS
        }
        admitted.append({"lineage_id": f"L{index:03}", "endpoint_observations": blocks})
    result = scorer._score({"admitted": admitted})
    endpoint = result["endpoints"]["E5_no_confirmed_selective_stale_escape"]
    assert endpoint["pairs_exercising"] == sx.MIN_EXERCISING - 1
    assert endpoint["underpowered"] is True
    assert endpoint["verdict"] == "FAILED"
    assert result["verdict"] == "FAIL"


def test_frame_refuses_alternate_authority(tmp_path):
    acquired = _acquisition(tmp_path, with_observations=False)
    with pytest.raises(sx.Refused, match="only be sealed"):
        frame.seal(acquired, tmp_path / "alternate.json")


def test_malformed_partial_spends_exactly_one_score_attempt(tmp_path, monkeypatch):
    acquired = _acquisition(tmp_path, with_observations=True)
    frame_authority = tmp_path / "sfir1-frame-authority.json"
    score_authority = tmp_path / "sfir1-score-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_authority)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_authority)
    frame.seal(acquired, frame_authority)
    digest = sx.sha_file(frame_authority)
    acquired.write_text("{malformed", encoding="utf-8")
    first = scorer.score(frame_authority, digest, score_authority)
    assert first["state"] == "MALFORMED_PARTIAL_REFUSED"
    with pytest.raises(sx.Refused, match="already exists"):
        scorer.score(frame_authority, digest, score_authority)


def test_score_refuses_wrong_frame_hash_without_writing(tmp_path, monkeypatch):
    authority = tmp_path / "sfir1-score-authority.json"
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", authority)
    with pytest.raises(sx.Refused, match="exact fixed frame"):
        scorer.score(tmp_path / "missing.json", "sha256:" + "0" * 64, authority)
    assert not authority.exists()


def test_acceptance_refuses_nonpass_and_alternate_paths(tmp_path, monkeypatch):
    score_path = tmp_path / "sfir1-score-authority.json"
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    monkeypatch.setattr(sx, "ACCEPTANCE_AUTHORITY", tmp_path / "sfir1-acceptance-authority.json")
    sx.exclusive_json(score_path, {"schema": scorer.SCHEMA, "state": "SCORED", "verdict": "FAIL"})
    with pytest.raises(sx.Refused, match="SCORED/FAIL"):
        acceptance.seal(score_path, sx.sha_file(score_path), sx.ACCEPTANCE_AUTHORITY)
    with pytest.raises(sx.Refused, match="fixed SFIR1 score authority"):
        acceptance.seal(tmp_path / "alternate.json", "sha256:x", sx.ACCEPTANCE_AUTHORITY)


def test_pass_seals_one_acceptance_authority(tmp_path, monkeypatch):
    acquired = _acquisition(tmp_path, with_observations=True)
    frame_authority = tmp_path / "sfir1-frame-authority.json"
    score_authority = tmp_path / "sfir1-score-authority.json"
    acceptance_authority = tmp_path / "sfir1-acceptance-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_authority)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_authority)
    monkeypatch.setattr(sx, "ACCEPTANCE_AUTHORITY", acceptance_authority)
    frame.seal(acquired, frame_authority)
    result = scorer.score(frame_authority, sx.sha_file(frame_authority), score_authority)
    assert result["verdict"] == "PASS"
    held = acceptance.seal(score_authority, sx.sha_file(score_authority), acceptance_authority)
    assert held["state"] == "ACCEPTED"
    assert acceptance.verify(acceptance_authority)["verdict"] == "PASS"


def test_modules_contain_no_glob_or_latest_selection():
    for module in (sx, worker, frame, scorer, acceptance):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert ".glob(" not in source
        assert "latest" not in source.lower()


def test_execution_manifest_closes_dynamic_and_transitive_source_trees():
    manifest = sx.execution_toolchain_manifest()
    components = set(manifest["components"])
    # Self-bind both the producer and verifier, then bind the dynamic cache,
    # lane loader, canonicaliser and rebuild engine reached after payload open.
    assert {
        "tools/sfir1_execution.py",
        "tools/sfir1_protocol.py",
        "tools/sfir1_worker.py",
        "tools/verify_sfir1_frame.py",
        "tools/score_sfir1.py",
        "tools/sfir1_acceptance.py",
        "acquisition/payload_cache.py",
        "source_fact_ir/compile.py",
        "source_fact_ir/core_extractor.py",
        "canonicalization/provenance_document.py",
        "canonicalization/source_map.py",
        "compiler/rebuild_equivalence.py",
        "compiler/selective_build.py",
    } <= components
    for tree in sx.EXECUTION_SOURCE_TREES:
        expected = {
            path.resolve().relative_to(sx.NS.resolve()).as_posix()
            for path in tree.rglob("*.py")
            if "__pycache__" not in path.parts
        }
        assert expected <= components
    assert manifest["coverage"]["component_count"] == len(components)


def test_execution_manifest_refuses_hash_set_coverage_and_path_relabel_drift():
    manifest = sx.execution_toolchain_manifest()

    bad_hash = copy.deepcopy(manifest)
    victim = "source_fact_ir/compile.py"
    bad_hash["components"][victim]["sha256"] = "sha256:" + "0" * 64
    unsigned = {key: value for key, value in bad_hash.items() if key != "content_digest"}
    bad_hash["content_digest"] = sx.canonical_sha(unsigned)
    with pytest.raises(sfir1_protocol.SFIR1Refused, match="binding drifted"):
        sfir1_protocol._verify_execution_toolchain(sx.ROOT, bad_hash)

    missing = copy.deepcopy(manifest)
    missing["components"].pop(victim)
    missing["coverage"]["component_count"] -= 1
    unsigned = {key: value for key, value in missing.items() if key != "content_digest"}
    missing["content_digest"] = sx.canonical_sha(unsigned)
    with pytest.raises(sfir1_protocol.SFIR1Refused, match="component set drifted"):
        sfir1_protocol._verify_execution_toolchain(sx.ROOT, missing)

    coverage = copy.deepcopy(manifest)
    coverage["coverage"]["strategy"] = "hand_selected_files"
    unsigned = {key: value for key, value in coverage.items() if key != "content_digest"}
    coverage["content_digest"] = sx.canonical_sha(unsigned)
    with pytest.raises(sfir1_protocol.SFIR1Refused, match="coverage policy drifted"):
        sfir1_protocol._verify_execution_toolchain(sx.ROOT, coverage)

    relabelled = copy.deepcopy(manifest)
    first = "source_fact_ir/compile.py"
    second = "source_fact_ir/ir.py"
    relabelled["components"][first] = copy.deepcopy(relabelled["components"][second])
    unsigned = {key: value for key, value in relabelled.items() if key != "content_digest"}
    relabelled["content_digest"] = sx.canonical_sha(unsigned)
    with pytest.raises(sfir1_protocol.SFIR1Refused, match="binding drifted"):
        sfir1_protocol._verify_execution_toolchain(sx.ROOT, relabelled)


def test_post_frame_code_drift_refuses_before_spending_score_attempt(tmp_path, monkeypatch):
    acquired = _acquisition(tmp_path, with_observations=True)
    frame_authority = tmp_path / "sfir1-frame-authority.json"
    score_authority = tmp_path / "sfir1-score-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_authority)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_authority)
    frame.seal(acquired, frame_authority)

    original = sx.execution_component_paths
    monkeypatch.setattr(
        sx,
        "execution_component_paths",
        lambda: {
            name: path
            for name, path in original().items()
            if name != "source_fact_ir/compile.py"
        },
    )
    with pytest.raises(sx.Refused, match="component set drifted"):
        scorer.score(frame_authority, sx.sha_file(frame_authority), score_authority)
    assert not score_authority.exists()


def test_acceptance_verification_rechecks_frozen_execution_chain(tmp_path, monkeypatch):
    acquired = _acquisition(tmp_path, with_observations=True)
    frame_authority = tmp_path / "sfir1-frame-authority.json"
    score_authority = tmp_path / "sfir1-score-authority.json"
    acceptance_authority = tmp_path / "sfir1-acceptance-authority.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_authority)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_authority)
    monkeypatch.setattr(sx, "ACCEPTANCE_AUTHORITY", acceptance_authority)
    frame.seal(acquired, frame_authority)
    scorer.score(frame_authority, sx.sha_file(frame_authority), score_authority)
    acceptance.seal(score_authority, sx.sha_file(score_authority), acceptance_authority)

    original = sx.execution_component_paths
    monkeypatch.setattr(
        sx,
        "execution_component_paths",
        lambda: {
            name: path
            for name, path in original().items()
            if name != "compiler/rebuild_equivalence.py"
        },
    )
    with pytest.raises(sx.Refused, match="component set drifted"):
        acceptance.verify(acceptance_authority)
