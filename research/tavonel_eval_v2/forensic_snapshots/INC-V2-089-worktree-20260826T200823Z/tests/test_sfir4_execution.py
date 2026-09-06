from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS))
sys.path.insert(0, str(NS / "tools"))

import score_sfir4 as scorer  # noqa: E402
import sfir4_acceptance as acceptance  # noqa: E402
import sfir4_execution as sx  # noqa: E402
import sfir4_worker as worker  # noqa: E402
import verify_sfir4_frame as frame  # noqa: E402


def candidate(index: int = 0, family: str = "git_docs") -> dict:
    from acquisition import sources_sfir4 as sources

    repository = sources.SOURCE_POOLS["git_docs"]["repositories"][0]
    lineage = f"git:{repository}:docs/{index}.md"
    before = f"{index + 1:040x}"
    after = f"{index + 1001:040x}"
    bits = hashlib.sha256((sources.SELECTION_SALT + "\0" + lineage).encode()).digest()[0]
    return {
        "discovery_root_id": f"git:{repository}",
        "root_container_id": f"git:{repository}",
        "lineage_id": lineage,
        "family": family,
        "container_id": f"git:{repository}:document:docs/{index}.md",
        "alias_ids": [],
        "payload_ref": {
            "before": f"github://{repository}/blob/{before}/docs/{index}.md",
            "after": f"github://{repository}/blob/{after}/docs/{index}.md",
        },
        "revision_id": {"before": before, "after": after},
        "revision_timestamp": {"before": "2026-08-24T00:00:00Z", "after": "2026-08-25T00:00:00Z"},
        "capability_exercise": {
            "E5": not bool(bits & 1),
            "E6": not bool(bits & 2),
            "E9": not bool(bits & 4),
        },
    }


def observations(*, exercised: bool = True, violations: int = 0) -> dict:
    rows = {
        endpoint: {"exercised": exercised, "violations": violations, "stages_checked": []}
        for endpoint in sx.ENDPOINTS
    }
    rows[sx.VETO_ENDPOINT]["stages_checked"] = ["post_execution", "pre_activation"]
    return rows


def test_v4_has_distinct_fixed_authorities_and_artifact_namespaces():
    import sfir1_execution as old
    import sfir2_execution as prior

    assert sx.PROTOCOL_ID.endswith("V4")
    assert sx.FRAME_AUTHORITY != old.FRAME_AUTHORITY
    assert sx.SCORE_AUTHORITY != old.SCORE_AUTHORITY
    assert sx.ACCEPTANCE_AUTHORITY != old.ACCEPTANCE_AUTHORITY
    assert sx.ACQUISITION_SPENT_AUTHORITY != old.ACQUISITION_SPENT_AUTHORITY
    assert sx.FRAME_AUTHORITY != prior.FRAME_AUTHORITY
    assert sx.SCORE_AUTHORITY != prior.SCORE_AUTHORITY
    assert sx.ACCEPTANCE_AUTHORITY != prior.ACCEPTANCE_AUTHORITY
    assert sx.ACQUISITION_SPENT_AUTHORITY != prior.ACQUISITION_SPENT_AUTHORITY
    assert "sfir4" in sx.ACQUISITION.as_posix()
    assert "sfir4_cache" in sx.PAYLOAD_CACHE.as_posix()


def test_closed_manifest_includes_all_v3_and_reused_native_modules():
    manifest = sx.execution_toolchain_manifest()
    names = set(manifest["components"])
    assert {
        "tools/sfir4_protocol.py",
        "tools/sfir4_spent_authority.py",
        "tools/probe_sfir4_capacity.py",
        "tools/sfir4_execution.py",
        "tools/sfir4_worker.py",
        "tools/verify_sfir4_frame.py",
        "tools/score_sfir4.py",
        "tools/sfir4_acceptance.py",
        "tools/sfir1_worker.py",
        "acquisition/ecfr_raw_part_cache.py",
        "tools/sfi1_worker.py",
        "tools/sfi2_worker.py",
    } <= names
    assert manifest["coverage"]["component_count"] == len(names)
    assert manifest["content_digest"] == sx.canonical_sha(
        {k: v for k, v in manifest.items() if k != "content_digest"}
    )


def test_design_binding_recomputes_exact_external_manifest(tmp_path, monkeypatch):
    manifest_path = tmp_path / "execution-manifest.json"
    manifest = sx.write_execution_manifest(manifest_path, "2026-08-26T13:00:00Z")
    specs = {name: (tmp_path / f"{name}.json", f"sha256:{name}") for name in sx.SCHEMAS}
    refs = {
        name: {
            "path": sx.relative(path),
            "sha256": digest,
            "schema": sx.SCHEMAS[name],
        }
        for name, (path, digest) in specs.items()
    }
    frozen = {
        "charter": {key: refs["charter"][key] for key in ("path", "sha256")},
        "capacity": {key: refs["capacity"][key] for key in ("path", "sha256")},
        "roster": {key: refs["roster"][key] for key in ("path", "sha256")},
        "spent_identity_authority": {"path": "spent.json", "sha256": "sha256:spent"},
        "execution_manifest": {
            "path": sx.relative(manifest_path),
            "sha256": sx.sha_file(manifest_path),
            "content_digest": manifest["content_digest"],
            "schema": manifest["schema"],
        },
        "acquisition_authorized": True,
        "scoring_authorized": False,
        "score_exactly_once": True,
        "scoring_requires_exactly_once_acquisition_authority": True,
    }

    def fake_receipt(kind, *_args):
        bodies = {
            "charter": {"schema": sx.SCHEMAS["charter"]},
            "capacity": {
                "schema": sx.SCHEMAS["capacity"],
                "charter": frozen["charter"],
                "spent_identity_authority": frozen["spent_identity_authority"],
            },
            "roster": {
                "schema": sx.SCHEMAS["roster"],
                "charter": frozen["charter"],
                "capacity": frozen["capacity"],
                "spent_identity_authority": frozen["spent_identity_authority"],
            },
        }
        return {
            **refs[kind],
            "kind": kind,
            "body": frozen if kind == "protocol_freeze" else bodies[kind],
        }

    monkeypatch.setattr(sx, "verify_receipt", fake_receipt)
    import sfir4_protocol

    monkeypatch.setattr(sfir4_protocol, "verify_spent_authority", lambda *_args: {})
    assert set(sx.verify_design_bindings(specs)) == set(sx.SCHEMAS)

    frozen["scoring_authorized"] = True
    with pytest.raises(sx.Refused, match="authorization flags"):
        sx.verify_design_bindings(specs)
    frozen["scoring_authorized"] = False

    tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
    first = next(iter(tampered["components"].values()))
    first["sha256"] = "sha256:" + "0" * 64
    tampered["content_digest"] = sx.canonical_sha(
        {key: value for key, value in tampered.items() if key != "content_digest"}
    )
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    frozen["execution_manifest"].update(
        {
            "sha256": sx.sha_file(manifest_path),
            "content_digest": tampered["content_digest"],
        }
    )
    with pytest.raises(sx.Refused, match="exact current closed"):
        sx.verify_design_bindings(specs)


def test_acquisition_spent_binding_is_fixed_exact_and_cross_bound(tmp_path, monkeypatch):
    spent = tmp_path / "sfir4-acquisition-spent-authority.json"
    monkeypatch.setattr(sx, "ACQUISITION_SPENT_AUTHORITY", spent)
    design = {
        name: {"path": f"{name}.json", "sha256": f"sha256:{name}", "schema": schema}
        for name, schema in sx.SCHEMAS.items()
    }
    sx.exclusive_json(
        spent,
        {
            "schema": sx.ACQUISITION_SPENT_SCHEMA,
            "protocol_id": sx.PROTOCOL_ID,
            "design_bindings": design,
            "state": "PAYLOAD_READ_AUTHORIZED_CORPUS_SPENT",
            "single_writer": True,
        },
    )
    binding = {
        "path": sx.relative(spent),
        "sha256": sx.sha_file(spent),
        "schema": sx.ACQUISITION_SPENT_SCHEMA,
    }
    assert sx.verify_acquisition_spent_binding(binding, design)["single_writer"] is True
    with pytest.raises(sx.Refused, match="design chain"):
        sx.verify_acquisition_spent_binding(binding, {})


def test_roster_revalidates_discovery_root_and_alias_contract(tmp_path, monkeypatch):
    import sfir4_protocol

    monkeypatch.setattr(
        sfir4_protocol,
        "verify_spent_authority",
        lambda *_args: {"container_ids": [], "lineage_ids": [], "alias_ids": []},
    )
    good = candidate()
    receipt = {
        "schema": sx.SCHEMAS["roster"],
        "protocol_id": sx.PROTOCOL_ID,
        "spent_identity_authority": {"path": "spent.json", "sha256": "sha256:spent"},
        "Q": {"git_docs": 1, "regulation_ecfr": 0, "encyclopedia_wikipedia": 0},
        "families": {
            "git_docs": [good],
            "regulation_ecfr": [],
            "encyclopedia_wikipedia": [],
        },
    }
    assert (
        sx.roster_candidates(receipt, tmp_path / "receipt.json")[0]["discovery_root_id"]
        == good["discovery_root_id"]
    )
    bad = candidate()
    bad["alias_ids"] = [bad["lineage_id"]]
    receipt["families"]["git_docs"] = [bad]
    with pytest.raises(sx.Refused, match="alias collides with a core identity"):
        sx.roster_candidates(receipt, tmp_path / "receipt.json")


def test_roster_refuses_case_variant_of_spent_identity(tmp_path, monkeypatch):
    import sfir4_protocol

    row = candidate()
    monkeypatch.setattr(
        sfir4_protocol,
        "verify_spent_authority",
        lambda *_args: {
            "container_ids": [row["container_id"].upper()],
            "lineage_ids": [],
            "alias_ids": [],
        },
    )
    receipt = {
        "schema": sx.SCHEMAS["roster"],
        "protocol_id": sx.PROTOCOL_ID,
        "spent_identity_authority": {"path": "spent.json", "sha256": "sha256:spent"},
        "Q": {"git_docs": 1, "regulation_ecfr": 0, "encyclopedia_wikipedia": 0},
        "families": {
            "git_docs": [row],
            "regulation_ecfr": [],
            "encyclopedia_wikipedia": [],
        },
    }
    with pytest.raises(sx.Refused, match="normalized spent"):
        sx.roster_candidates(receipt, tmp_path / "receipt.json")


def test_worker_uses_native_stack_without_caller_outcomes():
    before = b"""# Handbook

## Overview

This paragraph is deliberately long enough to clear the minimum text threshold.
It contains a [link](https://old.invalid/spec) whose native source span must be preserved.

## Details

A second substantial paragraph is also long enough to be admitted on its own.
This fixture exercises a structural pair rather than an empty document.
"""
    after = before.replace(b"old.invalid", b"new.invalid").replace(
        b"A second substantial", b"A second revised substantial"
    )
    row = candidate()
    payloads = {
        row["payload_ref"]["before"]: before,
        row["payload_ref"]["after"]: after,
    }
    result = worker._observe_one(row, lambda _family, locator: payloads[locator])
    assert result["status"] == "OBSERVED"
    assert set(result["observations"]) == set(sx.ENDPOINTS)
    source = Path(worker.__file__).read_text(encoding="utf-8")
    assert "caller-supplied" not in source
    assert "--observations" not in source


def test_producer_spends_before_payload_and_spools_each_row(tmp_path, monkeypatch):
    rows = [candidate(0), candidate(1)]
    verified = {
        name: {"path": f"{name}.json", "sha256": f"sha256:{name}", "schema": schema}
        for name, schema in sx.SCHEMAS.items()
    }
    monkeypatch.setattr(sx, "verify_design_bindings", lambda _bindings: verified)
    monkeypatch.setattr(
        sx,
        "verify_receipt",
        lambda kind, *_args: {
            "body": {"acquisition_authorized": True}
            if kind == "protocol_freeze"
            else {"subject": {}}
        },
    )
    monkeypatch.setattr(sx, "roster_candidates", lambda *_args: rows)
    opened: list[str] = []

    def observe(row, fetcher):
        fetcher(row["family"], row["payload_ref"]["after"])
        return {
            "status": "OBSERVED",
            "observations": observations(),
            "evidence": {"pair": {"large": "x" * 10000}, "rebuild": {}},
        }

    monkeypatch.setattr(worker, "_observe_one", observe)
    bindings = {name: (tmp_path / f"{name}.json", f"sha256:{name}") for name in sx.SCHEMAS}
    batch, path, digest = worker.produce_observation_batch(
        bindings,
        payload_fetcher=lambda _family, locator: opened.append(locator) or b"payload",
        workers=1,
        spent_authority=tmp_path / "spent.json",
        observation_dir=tmp_path / "observations",
        acquisition_target=tmp_path / "acquisition.json",
        allow_test_paths=True,
    )
    assert (tmp_path / "spent.json").is_file() and opened
    assert batch["acquisition_spent_authority"] == {
        "path": sx.relative(tmp_path / "spent.json"),
        "sha256": sx.sha_file(tmp_path / "spent.json"),
        "schema": sx.ACQUISITION_SPENT_SCHEMA,
    }
    assert path.name.startswith("sfir4-observation-batch--") and sx.sha_file(path) == digest
    assert len(list((tmp_path / "observations" / "evidence").glob("*.json"))) == 2
    assert "large" not in json.dumps(batch)
    monkeypatch.setattr(sx, "OBSERVATION_DIR", tmp_path / "observations")
    monkeypatch.setattr(sx, "ACQUISITION_SPENT_AUTHORITY", tmp_path / "spent.json")
    held = worker._verify_observation_batch(
        {"path": sx.relative(path), "sha256": digest},
        verified,
        batch["acquisition_spent_authority"],
    )
    assert held["observations"] == batch["observations"]
    with pytest.raises(sx.Refused, match="already exists"):
        worker.produce_observation_batch(
            bindings,
            payload_fetcher=lambda *_args: (_ for _ in ()).throw(AssertionError("must not fetch")),
            workers=1,
            spent_authority=tmp_path / "spent.json",
            observation_dir=tmp_path / "second",
            acquisition_target=tmp_path / "acquisition.json",
            allow_test_paths=True,
        )


def test_producer_refuses_alternate_authority_paths_before_spending(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sx, "verify_design_bindings", lambda *_args: (_ for _ in ()).throw(AssertionError())
    )
    with pytest.raises(sx.Refused, match="fixed spent/observation/output paths"):
        worker.produce_observation_batch(
            {},
            spent_authority=tmp_path / "spent.json",
            observation_dir=tmp_path / "observations",
            acquisition_target=tmp_path / "acquisition.json",
        )


def test_ecfr_cache_total_bound_refuses_before_materialization(tmp_path, monkeypatch):
    monkeypatch.setattr(sx, "ECFR_PART_CACHE_ROOT", tmp_path / "ecfr")
    monkeypatch.setattr(worker, "_ecfr_blob_bytes", lambda: worker.MAX_ECFR_TOTAL_CACHE_BYTES)
    monkeypatch.setattr(
        worker.native,
        "_stream_ecfr_section",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    locator = "ecfr://title/1/part/1/section/1.1?version=2026-01-01"
    with pytest.raises(sx.Refused, match="cannot admit another bounded raw part"):
        worker._default_payload_fetcher("regulation_ecfr", locator)


def test_payload_cache_refuses_oversized_preexisting_blob_before_read(tmp_path, monkeypatch):
    cache = worker.BoundedPayloadCache(tmp_path / "cache", "sha256:extractor")
    url = "https://example.invalid/immutable"
    digest = "a" * 64
    pointer = cache._cache._pointer(url)
    blob = cache._cache._blob(digest)
    pointer.write_text(digest, encoding="ascii")
    with blob.open("wb") as handle:
        handle.truncate(worker.MAX_PAYLOAD_BYTES + 1)
    original = Path.read_bytes

    def guarded_read(path):
        if path == blob:
            raise AssertionError("oversized blob must not be read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)
    with pytest.raises(sx.Refused, match="target blob size"):
        cache.payload(url, lambda _url: (_ for _ in ()).throw(AssertionError("must not fetch")))


def test_payload_cache_aggregate_tree_quota_refuses_prewrite(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, "MAX_ACQUISITION_PAYLOAD_CACHE_BYTES", 100)
    cache = worker.BoundedPayloadCache(tmp_path / "cache", "sha256:extractor")
    (cache.root / "states" / "held.json").write_bytes(b"x" * 80)
    with pytest.raises(sx.Refused, match="cannot admit another payload"):
        cache.payload("https://example.invalid/new", lambda _url: b"y" * 10)
    assert not cache._cache._pointer("https://example.invalid/new").exists()


def test_scientific_evidence_per_file_and_total_spool_bounds(tmp_path, monkeypatch):
    row = candidate()
    result = {
        "status": "OBSERVED",
        "observations": observations(),
        "evidence": {"large": "x" * 1000},
    }
    monkeypatch.setattr(worker, "MAX_SCIENTIFIC_EVIDENCE_BYTES", 256)
    with pytest.raises(sx.Refused, match=r"frozen .*bound"):
        worker._write_scientific_evidence(tmp_path / "oversized", row, result)
    assert not (tmp_path / "oversized" / "evidence").exists()

    monkeypatch.setattr(worker, "MAX_SCIENTIFIC_EVIDENCE_BYTES", 4096)
    monkeypatch.setattr(worker, "MAX_OBSERVATION_SPOOL_BYTES", 100)
    spool = tmp_path / "full"
    spool.mkdir()
    (spool / "held.json").write_bytes(b"z" * 90)
    with pytest.raises(sx.Refused, match="cannot admit another file"):
        worker._write_scientific_evidence(spool, row, {"status": "REJECTED"})


def test_observation_batch_verification_recounts_entire_spool(tmp_path, monkeypatch):
    spool = tmp_path / "observations"
    spool.mkdir()
    (spool / "unbound.bin").write_bytes(b"x" * 101)
    monkeypatch.setattr(sx, "OBSERVATION_DIR", spool)
    monkeypatch.setattr(worker, "MAX_OBSERVATION_SPOOL_BYTES", 100)
    with pytest.raises(sx.Refused, match="aggregate bound"):
        worker._verify_observation_batch(
            {"path": str(spool / "missing.json"), "sha256": "sha256:missing"},
            {},
            {},
        )


@pytest.mark.parametrize("workers", [0, 3, True])
def test_worker_bound_refuses_unbounded_counts(tmp_path, workers):
    with pytest.raises(sx.Refused, match="workers must be"):
        worker._bounded_observe([], lambda *_args: b"", workers=workers, observation_dir=tmp_path)


def test_frame_uses_actual_exercise_floor_not_capability_flags(tmp_path, monkeypatch):
    rows = []
    families = ["git_docs", "regulation_ecfr", "encyclopedia_wikipedia"]
    for index in range(300):
        row = candidate(index)
        row["family"] = families[index % 3]
        row["endpoint_observations"] = observations(exercised=index < 28)
        row["exercise_eligibility"] = sx.exercise_eligibility(row["capability_exercise"])
        rows.append(row)
    acquired = {
        "schema": "tavonel.sfir4.acquisition.v1",
        "protocol_id": sx.PROTOCOL_ID,
        "design_bindings": {},
        "admitted": rows,
        "frame": {"candidates": 300},
        "lineages_considered": 300,
        "acquisition_state": "ACQUIRED",
    }
    path = tmp_path / "acquisition.json"
    path.write_text(json.dumps(acquired), encoding="utf-8")
    verified = {"protocol_freeze": {"path": "freeze.json", "sha256": "sha256:freeze"}}
    monkeypatch.setattr(sx, "reverify_recorded_bindings", lambda _value: verified)
    monkeypatch.setattr(sx, "verify_acquisition_spent_binding", lambda *_args: {})
    monkeypatch.setattr(frame, "_verify_acquisition_chain", lambda *_args: None)
    monkeypatch.setattr(
        sx,
        "verify_receipt",
        lambda *_args: {"body": {"acquisition_authorized": True, "score_exactly_once": True}},
    )
    assessed = frame.assess(acquired, path)
    assert assessed["state"] == "NOT_SCORABLE"
    assert all(value == 28 for value in assessed["exercise_power"].values())


def test_scorer_enforces_actual_e5_e6_e9_floor():
    rows = [{"endpoint_observations": observations()} for _ in range(28)]
    result = scorer._score({"admitted": rows})
    assert result["verdict"] == "FAIL"
    assert all(
        result["endpoints"][endpoint]["underpowered"] for endpoint in sx.EXERCISE_REQUIREMENTS
    )


def test_malformed_first_score_spends_attempt(tmp_path, monkeypatch):
    frame_path = tmp_path / "frame.json"
    frame_path.write_text("{}", encoding="utf-8")
    acquisition = tmp_path / "acquisition.json"
    acquisition.write_text(json.dumps({"admitted": "malformed"}), encoding="utf-8")
    score_path = tmp_path / "score.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_path)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    monkeypatch.setattr(
        frame,
        "verify",
        lambda _path: {
            "acquisition": str(acquisition),
            "acquisition_sha256": sx.sha_file(acquisition),
        },
    )
    first = scorer.score(frame_path, sx.sha_file(frame_path), score_path)
    assert first["state"] == "MALFORMED_PARTIAL_REFUSED"
    with pytest.raises(sx.Refused, match="already exists"):
        scorer.score(frame_path, sx.sha_file(frame_path), score_path)


def test_non_scorable_frame_never_spends_a_score_authority(tmp_path, monkeypatch):
    frame_path = tmp_path / "frame.json"
    frame_path.write_text("{}", encoding="utf-8")
    score_path = tmp_path / "score.json"
    monkeypatch.setattr(sx, "FRAME_AUTHORITY", frame_path)
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    monkeypatch.setattr(
        frame,
        "verify",
        lambda *_args: (_ for _ in ()).throw(sx.Refused("frame is NOT_SCORABLE")),
    )
    with pytest.raises(sx.Refused, match="NOT_SCORABLE"):
        scorer.score(frame_path, sx.sha_file(frame_path), score_path)
    assert not score_path.exists()


def test_acceptance_refuses_nonpass_and_alternate_paths(tmp_path, monkeypatch):
    score_path = tmp_path / "score.json"
    alternate = tmp_path / "acceptance.json"
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    sx.exclusive_json(score_path, {"schema": scorer.SCHEMA, "state": "SCORED", "verdict": "FAIL"})
    with pytest.raises(sx.Refused, match="fixed authority paths"):
        acceptance.seal(score_path, sx.sha_file(score_path), alternate)


def test_acceptance_is_exactly_once_and_only_from_exact_pass(tmp_path, monkeypatch):
    score_path = tmp_path / "score.json"
    acceptance_path = tmp_path / "acceptance.json"
    frame_path = tmp_path / "frame.json"
    acquisition_path = tmp_path / "acquisition.json"
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    monkeypatch.setattr(sx, "ACCEPTANCE_AUTHORITY", acceptance_path)
    score = {
        "schema": scorer.SCHEMA,
        "protocol_id": sx.PROTOCOL_ID,
        "state": "SCORED",
        "verdict": "PASS",
        "frame_authority": sx.relative(frame_path),
        "frame_authority_sha256": "sha256:frame",
        "acquisition": sx.relative(acquisition_path),
        "acquisition_sha256": "sha256:acquisition",
        "endpoints": {
            endpoint: {
                "verdict": "VETO_CLEAR_NO_POSITIVE_CREDIT"
                if endpoint == sx.VETO_ENDPOINT
                else "MET"
            }
            for endpoint in sx.ENDPOINTS
        },
    }
    sx.exclusive_json(score_path, score)
    monkeypatch.setattr(scorer, "verify", lambda *_args: sx.read_json(score_path))
    sealed = acceptance.seal(score_path, sx.sha_file(score_path), acceptance_path)
    assert sealed["state"] == "ACCEPTED" and sealed["verdict"] == "PASS"
    with pytest.raises(sx.Refused, match="already exists"):
        acceptance.seal(score_path, sx.sha_file(score_path), acceptance_path)


def test_execution_modules_have_no_glob_latest_or_newest_selection():
    for module in (sx, worker, frame, scorer, acceptance):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert ".glob(" not in source
        assert "rglob(" not in source or module is sx  # closed source tree enumeration only
        assert "latest" not in source.casefold()
