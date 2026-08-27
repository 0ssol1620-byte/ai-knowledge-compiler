from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "tools"))

import score_sfir2 as scorer  # noqa: E402
import sfir2_acceptance as acceptance  # noqa: E402
import sfir2_execution as sx  # noqa: E402
import sfir2_worker as worker  # noqa: E402
import verify_sfir2_frame as frame  # noqa: E402


def candidate(index: int = 0, family: str = "git_docs") -> dict:
    repository = "ipython/ipython"
    lineage = f"git:{repository}:docs/{index}.md"
    before = f"{index + 1:040x}"
    after = f"{index + 1001:040x}"
    return {
        "discovery_root_id": "git:ipython/ipython",
        "root_container_id": "git:ipython/ipython",
        "lineage_id": lineage,
        "family": family,
        "container_id": lineage,
        "alias_ids": [],
        "payload_ref": {
            "before": f"github://{repository}/blob/{before}/docs/{index}.md",
            "after": f"github://{repository}/blob/{after}/docs/{index}.md",
        },
        "revision_id": {"before": before, "after": after},
        "revision_timestamp": {"before": "2026-08-24T00:00:00Z", "after": "2026-08-25T00:00:00Z"},
        "capability_exercise": {"E5": True, "E6": True, "E9": True},
    }


def observations(*, exercised: bool = True, violations: int = 0) -> dict:
    rows = {
        endpoint: {"exercised": exercised, "violations": violations, "stages_checked": []}
        for endpoint in sx.ENDPOINTS
    }
    rows[sx.VETO_ENDPOINT]["stages_checked"] = ["post_execution", "pre_activation"]
    return rows


def test_v2_has_distinct_fixed_authorities_and_artifact_namespaces():
    import sfir1_execution as old

    assert sx.PROTOCOL_ID.endswith("V2")
    assert sx.FRAME_AUTHORITY != old.FRAME_AUTHORITY
    assert sx.SCORE_AUTHORITY != old.SCORE_AUTHORITY
    assert sx.ACCEPTANCE_AUTHORITY != old.ACCEPTANCE_AUTHORITY
    assert sx.ACQUISITION_SPENT_AUTHORITY != old.ACQUISITION_SPENT_AUTHORITY
    assert "sfir2" in sx.ACQUISITION.as_posix()
    assert "sfir2_cache" in sx.PAYLOAD_CACHE.as_posix()


def test_closed_manifest_includes_all_v2_and_reused_native_modules():
    manifest = sx.execution_toolchain_manifest()
    names = set(manifest["components"])
    assert {
        "tools/sfir2_protocol.py",
        "tools/sfir2_spent_authority.py",
        "tools/probe_sfir2_capacity.py",
        "tools/sfir2_execution.py",
        "tools/sfir2_worker.py",
        "tools/verify_sfir2_frame.py",
        "tools/score_sfir2.py",
        "tools/sfir2_acceptance.py",
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
        "score_exactly_once": True,
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
    import sfir2_protocol

    monkeypatch.setattr(sfir2_protocol, "verify_spent_authority", lambda *_args: {})
    assert set(sx.verify_design_bindings(specs)) == set(sx.SCHEMAS)

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


def test_roster_revalidates_discovery_root_and_alias_contract(tmp_path, monkeypatch):
    import sfir2_protocol

    monkeypatch.setattr(
        sfir2_protocol,
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
        == "git:ipython/ipython"
    )
    bad = candidate()
    bad["alias_ids"] = [bad["lineage_id"]]
    receipt["families"]["git_docs"] = [bad]
    with pytest.raises(sx.Refused, match="alias collides"):
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
    assert path.name.startswith("sfir2-observation-batch--") and sx.sha_file(path) == digest
    assert len(list((tmp_path / "observations" / "evidence").glob("*.json"))) == 2
    assert "large" not in json.dumps(batch)
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


@pytest.mark.parametrize("workers", [0, 17, True])
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
        "schema": "tavonel.sfir2.acquisition.v1",
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


def test_acceptance_refuses_nonpass_and_alternate_paths(tmp_path, monkeypatch):
    score_path = tmp_path / "score.json"
    alternate = tmp_path / "acceptance.json"
    monkeypatch.setattr(sx, "SCORE_AUTHORITY", score_path)
    sx.exclusive_json(score_path, {"schema": scorer.SCHEMA, "state": "SCORED", "verdict": "FAIL"})
    with pytest.raises(sx.Refused, match="fixed authority paths"):
        acceptance.seal(score_path, sx.sha_file(score_path), alternate)


def test_execution_modules_have_no_glob_latest_or_newest_selection():
    for module in (sx, worker, frame, scorer, acceptance):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert ".glob(" not in source
        assert "rglob(" not in source or module is sx  # closed source tree enumeration only
        assert "latest" not in source.casefold()
