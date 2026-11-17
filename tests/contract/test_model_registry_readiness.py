from __future__ import annotations

import hashlib
import json
import re
import runpy
from pathlib import Path
from typing import Any

import yaml

_VALIDATOR = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "infra/model-registry/validate_registry.py")
)
release_is_attested = _VALIDATOR["release_is_attested"]
validate = _VALIDATOR["validate"]
verify_revision_source = _VALIDATOR["verify_revision_source"]


def _release() -> dict[str, Any]:
    return {
        "upstream_revision": "a" * 40,
        "licenses": {"license_snapshot_sha256": "sha256:" + ("b" * 64)},
        "runtime": {
            "version": "1.0.0",
            "image_digest": "sha256:" + ("c" * 64),
        },
        "internal_validation": {"status": "canary"},
    }


def test_registry_is_locally_valid_with_gemma_challenger_fail_closed() -> None:
    assert validate() == []


def test_revision_source_digest_is_checked_against_committed_bytes(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text('{"model":"pinned"}', encoding="utf-8")
    digest = "sha256:" + hashlib.sha256(registry.read_bytes()).hexdigest()
    source = {"registry": "registry.json", "registry_sha256": digest}
    assert verify_revision_source(source, tmp_path) is None
    registry.write_text('{"model":"drifted"}', encoding="utf-8")
    assert "digest mismatch" in verify_revision_source(source, tmp_path)
    source["registry"] = "../outside.json"
    assert "outside the repository" in verify_revision_source(source, tmp_path)


def test_revision_source_checks_identity_and_weights(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "models": {
                    "sample": {
                        "repo": "owner/model",
                        "revision": "a" * 40,
                        "weights": {"largest_file_sha256": "sha256:" + "b" * 64, "file_count": 2},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    source = {
        "registry": "registry.json",
        "registry_sha256": "sha256:" + hashlib.sha256(registry.read_bytes()).hexdigest(),
        "weights_largest_file_sha256": "sha256:" + "b" * 64,
        "weights_file_count": 2,
    }
    release = {"upstream_id": "owner/model", "upstream_revision": "a" * 40}
    assert verify_revision_source(source, tmp_path, release) is None
    release["upstream_revision"] = "c" * 40
    assert "revision mismatch" in verify_revision_source(source, tmp_path, release)
    release["upstream_revision"] = "a" * 40
    source["weights_file_count"] = 3
    assert "file count mismatch" in verify_revision_source(source, tmp_path, release)


def test_second_reader_adr_evidence_paths_and_digests_are_real() -> None:
    root = Path(__file__).resolve().parents[2]
    adr = (root / "docs/adr/ADR-007-element-aware-second-reader.md").read_text(encoding="utf-8")
    evidence = re.findall(r"^\| `([^`]+)` \| `([0-9a-f]{64})` \|$", adr, flags=re.MULTILINE)
    assert len(evidence) == 4
    for relative, digest in evidence:
        path = (root / relative).resolve()
        assert path.is_relative_to(root)
        assert path.is_file(), relative
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, relative


def test_attestation_requires_license_runtime_image_and_internal_status() -> None:
    release = _release()
    assert release_is_attested(release)
    release["licenses"]["license_snapshot_sha256"] = None
    assert not release_is_attested(release)


def test_strict_promotion_still_rejects_unpinned_candidates() -> None:
    errors = validate(strict=True)
    assert errors
    assert any("exact 40-64 hex revision required" in error for error in errors)


# --- Arena intake (WO-D10-0A) ----------------------------------------------
# The register's `arena_intake` rows and the registry rows they
# name must agree on identity, revision and licence snapshot, and nothing an
# intake row admits may carry traffic or a production status.

_ROOT = Path(__file__).resolve().parents[2]
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_AXES = ("code", "weights", "dataset", "hosted")
_AXIS_VERDICTS = {"cleared_evaluation_only", "review_required", "not_applicable", "blocked"}
_ROW_STATUSES = {"EVALUATION_ONLY", "HELD", "OPENED_NOT_ADMITTED", "EXCLUDED"}
# The licence a row's use rests on follows from what the row is, never from the
# row's own say-so: a model run locally rests on its weights, an API on its
# hosted terms, a dataset on its terms, a tool on its code.
_DECIDING_AXIS = {"model": "weights", "hosted": "hosted", "dataset": "dataset", "tool": "code"}
# Hosted ids are pinned exactly: never an alias, never a retired id.
_HOSTED_PINS = {"mistral_ocr_4": "mistral-ocr-4-1"}
_RETIRED_HOSTED_IDS = {"mistral-ocr-4-0"}
# The nine smoke slots of §5E and the registry rows they run.
_SMOKE_SLOTS = {
    "C0": "mineru",
    "C1": "paddleocr_vl_1_6",
    "C2": "ovisocr2",
    "C3": "mineru_vlm",
    "C4": "minicpm_ocr_1_0",
    "C5": "nemotron_3_5_parse",
    "C6": "teleocr",
    "C7": "ovisocr3",
    "C8": "xiaomi_ocr_0",
}
# C0-C5 of the A2a smoke, C6 TeleOCR (§5B), C7 OvisOCR3 and C8 Xiaomi-OCR-0 (§5E).
_ARENA_PINS = {
    "mineru": ("opendatalab/PDF-Extract-Kit-1.0", "ed6b654c018d742e65a17671e379c5e6ecc87ec9"),
    "paddleocr_vl_1_6": (
        "PaddlePaddle/PaddleOCR-VL-1.6",
        "c5630abae1d940eafe0697512a0325494b02ab42",
    ),
    "ovisocr2": ("ATH-MaaS/OvisOCR2", "1fc9221b7823a371d6e97f92d527cc847e24e107"),
    "mineru_vlm": (
        "opendatalab/MinerU2.5-Pro-2605-1.2B",
        "bff20d4ae2bf202df9f45284b4d43681555a97ed",
    ),
    "minicpm_ocr_1_0": ("openbmb/MiniCPM-OCR-1.0", "883ca368d17335b9ce5aa6fef4d000ef0684fcaa"),
    "nemotron_3_5_parse": ("nvidia/Nemotron-3.5-Parse", "ea2e1fe486bea3e7d0d505df9bafa4ad562407a0"),
    "teleocr": ("XingChen-AGI/TeleOCR", "a32e21d4f766317a6f42f341be57d374362bf843"),
    "ovisocr3": ("ATH-MaaS/OvisOCR3", "5b252386ba615bd464a5a26597560eaba87dae5c"),
    "xiaomi_ocr_0": (
        "xiaomi-research/Xiaomi-OCR-0",
        "bbd8cf8d21f256b3644b44cb860f3a7cecb93c30",
    ),
}


def _yaml(relative: str) -> dict[str, Any]:
    value = yaml.safe_load((_ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _intake_rows() -> list[dict[str, Any]]:
    register = _yaml("docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml")
    rows = register.get("arena_intake")
    assert isinstance(rows, list) and rows, "arena intake rows are missing"
    return rows


def _releases() -> dict[str, dict[str, Any]]:
    return {r["provider_key"]: r for r in _yaml("infra/model-registry/models.yaml")["releases"]}


def test_every_arena_candidate_is_pinned_with_a_licence_snapshot() -> None:
    releases = _releases()
    for key, (upstream_id, revision) in _ARENA_PINS.items():
        release = releases.get(key)
        assert release is not None, key
        assert release["upstream_id"] == upstream_id, key
        assert release["upstream_revision"] == revision, key
        snapshot = release["licenses"]["license_snapshot_sha256"]
        assert isinstance(snapshot, str) and snapshot.startswith("sha256:"), key
    for key, model_id in _HOSTED_PINS.items():
        assert releases[key]["provider_model_id"] == model_id, key
    for key, release in releases.items():
        model_id = release.get("provider_model_id")
        if model_id is not None:
            assert "latest" not in model_id, f"{key} pins an alias"
            assert model_id not in _RETIRED_HOSTED_IDS, f"{key} pins a retired id"
    rows = {row.get("arena_slot"): row for row in _intake_rows()}
    for slot, key in _SMOKE_SLOTS.items():
        row = rows.get(slot)
        assert row is not None, f"smoke slot {slot} has no intake row"
        assert row["registry_provider_key"] == key, slot
        assert row["status"] == "EVALUATION_ONLY", slot


def test_intake_rows_bind_the_registry_rows_they_name() -> None:
    register = _yaml("docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml")
    classifications = set(register["classifications"])
    releases = _releases()
    ids: set[str] = set()
    bound: set[str] = set()
    for row in _intake_rows():
        rid = row["id"]
        assert rid not in ids, f"duplicate intake id {rid}"
        ids.add(rid)
        assert row["classification"] in classifications, rid
        assert row["status"] in _ROW_STATUSES, rid
        assert _HEX64.fullmatch(row["snapshot_sha256"]), rid
        assert row["snapshot_url"].startswith("https://"), rid
        assert row.get("not_cleared"), rid  # each axis below carries its own basis
        axes = row["axes"]
        assert set(axes) == set(_AXES), rid
        for axis in _AXES:
            assert axes[axis]["verdict"] in _AXIS_VERDICTS, f"{rid}.{axis}"
            assert axes[axis].get("basis"), f"{rid}.{axis}"
        snapshot_axes = {_DECIDING_AXIS[row["kind"]]}
        for extra in row.get("other_snapshots", []):
            assert _HEX64.fullmatch(extra["sha256"]), rid
            assert extra["url"].startswith("https://"), rid
            assert extra["axis"] in _AXES, rid
            snapshot_axes.add(extra["axis"])
        for axis in _AXES:
            verdict = axes[axis]["verdict"]
            # A cleared axis rests on captured bytes: the row's main snapshot for
            # its deciding axis, an `other_snapshots` entry for any other axis.
            if verdict == "cleared_evaluation_only":
                assert axis in snapshot_axes, f"{rid}.{axis} is cleared without a snapshot"
            # A blocked axis names what is blocked, so it cannot be quietly swapped.
            if verdict == "blocked":
                assert axes[axis].get("repository"), f"{rid}.{axis} is blocked but names nothing"
        if row["kind"] == "model":
            assert _HEX40.fullmatch(row["upstream_revision"]), rid
        key = row.get("registry_provider_key")
        if key is None:
            continue
        assert key not in bound, f"{key} is bound by two intake rows"
        bound.add(key)
        release = releases.get(key)
        assert release is not None, f"{rid} names unknown registry row {key}"
        snapshot = release["licenses"]["license_snapshot_sha256"]
        assert snapshot == "sha256:" + row["snapshot_sha256"], rid
        if row["kind"] == "hosted":
            assert release["provider_model_id"] == row["provider_model_id"], rid
        else:
            assert release["upstream_id"] == row["upstream_id"], rid
            assert release["upstream_revision"] == row["upstream_revision"], rid
        # Evaluation-only is a property of the registry row too, not just the intake row.
        assert (release.get("rollout") or {}).get("traffic_percent", 0) == 0, rid
        status = (release.get("internal_validation") or {}).get("status")
        assert status not in {"champion", "canary", "fallback", "shadow"}, rid
        assert not release_is_attested(release), rid
    # A captured snapshot digest in the registry is always explained by an intake row.
    for key, release in releases.items():
        if key == "local_mock_parser":
            continue
        if release["licenses"].get("license_snapshot_sha256") is not None:
            assert key in bound, f"{key} carries a snapshot digest no intake row explains"


def test_evaluation_only_requires_its_deciding_axis_cleared() -> None:
    # The deciding axis is the licence the row's use actually rests on: weights
    # for a model run locally, hosted terms for an API, dataset terms for a
    # dataset, code for a tool. A row is admitted only when that axis is cleared;
    # anything less is HELD, OPENED_NOT_ADMITTED or EXCLUDED.
    for row in _intake_rows():
        deciding = row["deciding_axis"]
        assert deciding == _DECIDING_AXIS[row["kind"]], row["id"]
        if row["status"] == "EVALUATION_ONLY":
            assert row["axes"][deciding]["verdict"] == "cleared_evaluation_only", row["id"]
            assert row["classification"] != "RED", row["id"]
        else:
            assert row.get("held_reason"), f"{row['id']} is not admitted and does not say why"
