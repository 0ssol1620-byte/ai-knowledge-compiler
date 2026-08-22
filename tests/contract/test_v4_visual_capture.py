from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from infra.release.validate_v4_visual_capture import (
    EXPECTED_LOCALES,
    EXPECTED_MOTION,
    EXPECTED_SCENES,
    EXPECTED_SIGNATURES,
    EXPECTED_VIEWPORTS,
    validate,
)


def _manifest(root: Path) -> Path:
    records: list[dict[str, object]] = []
    image_bytes: dict[tuple[int, int], bytes] = {}
    for route_index, (route, scene) in enumerate(EXPECTED_SCENES):
        for locale in EXPECTED_LOCALES:
            for motion in EXPECTED_MOTION:
                for width, height in EXPECTED_VIEWPORTS:
                    name = f"capture-{route_index}-{locale}-{motion}-{width}x{height}.webp"
                    path = root / name
                    size = (width, height)
                    if size not in image_bytes:
                        buffer = io.BytesIO()
                        Image.new("RGB", size, color=(242, 244, 247)).save(
                            buffer,
                            format="WEBP",
                            quality=5,
                            method=0,
                        )
                        image_bytes[size] = buffer.getvalue()
                    path.write_bytes(image_bytes[size])
                    signature_fields = (
                        {
                            "asset_width_px": width,
                            "asset_height_px": height,
                            "asset_text_length": 100,
                            "asset_truth_label_present": True,
                        }
                        if scene.startswith("signature_")
                        else {}
                    )
                    records.append(
                        {
                            "route": route,
                            "scene": scene,
                            "locale": locale,
                            "motion": motion,
                            "viewport": {"width": width, "height": height},
                            "response_status": 200,
                            "file": name,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "console_errors": [],
                            "inspection": {
                                "main_present": True,
                                "body_text_length": 100,
                                "main_text_length": 100,
                                "html_lang": locale,
                                "cumulative_layout_shift": 0.0,
                                "truth_label_present": True,
                                "horizontal_overflow_px": 0,
                                "visible_broken_images": [],
                                "visible_text_below_12px": [],
                                "core_text_below_14px": [],
                                "undersized_core_targets": [],
                                "clipped_core_text": [],
                                **signature_fields,
                            },
                        }
                    )
    count = len(records)
    payload = {
        "schema_version": "1.0",
        "captured_at": "2026-07-31T23:59:59+09:00",
        "capture_contract": {
            "actual_routes_only": True,
            "current_worktree_only": True,
            "screenshot_kind": "named_scene_crop",
            "scenes": [
                "above_fold",
                *(f"signature_{asset_id}" for asset_id in EXPECTED_SIGNATURES),
            ],
            "exact_widths_px": [width for width, _ in EXPECTED_VIEWPORTS],
            "languages": list(EXPECTED_LOCALES),
            "modes": list(EXPECTED_MOTION),
            "signature_assets": list(EXPECTED_SIGNATURES),
            "expected_capture_count": count,
            "computed_text_floor_px": 12,
            "computed_core_text_floor_px": 14,
            "core_target_floor_px": {"desktop": 24, "mobile": 44},
        },
        "application": {
            "base_url": "http://127.0.0.1:3100",
            "demo_disclosure": (
                "Demo mode is a deterministic reference workspace, not production or customer "
                "evidence."
            ),
            "revision": "a" * 40,
            "worktree_status_sha256": "b" * 64,
            "worktree_diff_sha256": "c" * 64,
            "worktree_untracked_sha256": "d" * 64,
            "next_build_id": "test-build",
        },
        "summary": {
            "capture_count": count,
            "blocking_finding_count": 0,
            "approval": True,
        },
        "blocking_findings": [],
        "records": records,
    }
    manifest = root / "capture-manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    (root / "hashes.sha256").write_text(
        "".join(f"{record['sha256']}  {record['file']}\n" for record in records),
        encoding="utf-8",
    )
    return manifest


def test_complete_visual_matrix_passes(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    assert validate(manifest) == []


def test_tampered_capture_fails_closed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["records"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert any("hash mismatch" in error for error in validate(manifest))


def test_legibility_and_truth_findings_fail_closed(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    inspection = payload["records"][0]["inspection"]
    inspection["visible_text_below_12px"] = [{"tag": "small", "font_size_px": 10}]
    inspection["truth_label_present"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    errors = validate(manifest)
    assert any("visible text below 12px" in error for error in errors)
    assert any("truth label is missing" in error for error in errors)


def test_signature_crop_must_be_real_webp_with_bound_dimensions(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    signature = next(
        record for record in payload["records"] if record["scene"].startswith("signature_")
    )
    signature["inspection"]["asset_width_px"] += 1
    signature["inspection"]["asset_truth_label_present"] = False
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    errors = validate(manifest)
    assert any("signature capture dimensions differ" in error for error in errors)
    assert any("signature asset truth boundary is missing" in error for error in errors)
