"""Validate the complete current-worktree Structara v4 visual capture matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image, UnidentifiedImageError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = REPOSITORY_ROOT / "artifacts" / "v4-brand-captures" / "capture-manifest.json"
EXPECTED_ROUTES = (
    "/",
    "/product",
    "/benchmarks",
    "/security",
    "/pricing",
    "/intake",
    "/workspace",
    "/integrity",
    "/knowledge-bases",
    "/app/projects/project_research/graph",
    "/app/projects/project_research/exports",
    "/demo/dart",
    "/demo/sec",
)
EXPECTED_VIEWPORTS = (
    (1920, 1080),
    (1440, 900),
    (1280, 800),
    (1024, 768),
    (768, 1024),
    (390, 844),
    (360, 800),
)
EXPECTED_LOCALES = ("en", "ko")
EXPECTED_MOTION = ("default", "reduced-motion")
EXPECTED_SIGNATURES = ("A01", "A02", "A03", "A04", "A05", "A06")
EXPECTED_SCENES = tuple((route, "above_fold") for route in EXPECTED_ROUTES) + tuple(
    ("/", f"signature_{asset_id}") for asset_id in EXPECTED_SIGNATURES
)
EXPECTED_COUNT = (
    len(EXPECTED_SCENES) * len(EXPECTED_VIEWPORTS) * len(EXPECTED_LOCALES) * len(EXPECTED_MOTION)
)


def _is_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_worktree_evidence() -> dict[str, object]:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise OSError("git executable is unavailable")

    def git(*args: str) -> str:
        result = subprocess.run(  # noqa: S603 - executable is resolved and arguments are internal constants.
            [git_executable, *args],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout

    status = git("status", "--short")
    diff = git(
        "diff",
        "--binary",
        "--no-ext-diff",
        "HEAD",
        "--",
        ".",
        ":(exclude)artifacts",
    )
    untracked_paths = sorted(
        path for path in git("ls-files", "--others", "--exclude-standard", "-z").split("\0") if path
    )
    untracked_digest = hashlib.sha256()
    for relative_path in untracked_paths:
        untracked_digest.update(relative_path.encode("utf-8"))
        untracked_digest.update(b"\0")
        untracked_digest.update((REPOSITORY_ROOT / relative_path).read_bytes())
        untracked_digest.update(b"\0")
    return {
        "revision": git("rev-parse", "HEAD").strip(),
        "worktree_status_sha256": hashlib.sha256(
            status.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest(),
        "worktree_diff_sha256": hashlib.sha256(
            diff.replace("\r\n", "\n").encode("utf-8")
        ).hexdigest(),
        "worktree_untracked_sha256": untracked_digest.hexdigest(),
        "untracked_path_count": len(untracked_paths),
        "dirty_path_count": len([line for line in status.splitlines() if line]),
    }


def validate(
    manifest_path: Path,
    *,
    require_current_build: bool = False,
    require_current_worktree: bool = False,
) -> list[str]:
    errors: list[str] = []
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest cannot be read: {exc}"]
    if not isinstance(payload, Mapping):
        return ["manifest root must be an object"]
    if payload.get("schema_version") != "1.0":
        errors.append("manifest schema_version must be 1.0")
    captured_at = payload.get("captured_at")
    if not isinstance(captured_at, str):
        errors.append("captured_at must be an RFC 3339 timestamp")
    else:
        try:
            captured_timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
        except ValueError:
            errors.append("captured_at must be an RFC 3339 timestamp")
        else:
            if captured_timestamp.tzinfo is None:
                errors.append("captured_at must include a timezone")

    contract = payload.get("capture_contract")
    summary = payload.get("summary")
    application = payload.get("application")
    records = payload.get("records")
    if not isinstance(contract, Mapping):
        errors.append("capture_contract must be an object")
    else:
        if contract.get("actual_routes_only") is not True:
            errors.append("actual_routes_only must be true")
        if contract.get("current_worktree_only") is not True:
            errors.append("current_worktree_only must be true")
        if contract.get("screenshot_kind") != "named_scene_crop":
            errors.append("screenshot_kind must be named_scene_crop")
        if tuple(contract.get("scenes", ())) != (
            "above_fold",
            *(f"signature_{asset_id}" for asset_id in EXPECTED_SIGNATURES),
        ):
            errors.append("capture scenes must include above_fold and A01 through A06")
        if tuple(contract.get("exact_widths_px", ())) != tuple(
            width for width, _ in EXPECTED_VIEWPORTS
        ):
            errors.append("capture widths do not match the seven-width v4 matrix")
        if tuple(contract.get("languages", ())) != EXPECTED_LOCALES:
            errors.append("capture languages must be en and ko")
        if tuple(contract.get("modes", ())) != EXPECTED_MOTION:
            errors.append("capture modes must be default and reduced-motion")
        if tuple(contract.get("signature_assets", ())) != EXPECTED_SIGNATURES:
            errors.append("capture signature_assets must enumerate A01 through A06")
        if contract.get("expected_capture_count") != EXPECTED_COUNT:
            errors.append(f"expected_capture_count must be {EXPECTED_COUNT}")
        if contract.get("computed_text_floor_px") != 12:
            errors.append("computed_text_floor_px must be 12")
        if contract.get("computed_core_text_floor_px") != 14:
            errors.append("computed_core_text_floor_px must be 14")
        if contract.get("core_target_floor_px") != {"desktop": 24, "mobile": 44}:
            errors.append("core_target_floor_px must bind desktop 24 and mobile 44")

    if not isinstance(summary, Mapping):
        errors.append("summary must be an object")
    else:
        if summary.get("capture_count") != EXPECTED_COUNT:
            errors.append(f"capture_count must be {EXPECTED_COUNT}")
        if summary.get("blocking_finding_count") != 0:
            errors.append("blocking_finding_count must be zero")
        if summary.get("approval") is not True:
            errors.append("capture approval must be true")
    if payload.get("blocking_findings") != []:
        errors.append("blocking_findings must be empty")

    if not isinstance(application, Mapping):
        errors.append("application must be an object")
    else:
        base_url = application.get("base_url")
        if not isinstance(base_url, str):
            errors.append("application.base_url must be an HTTP(S) origin")
        else:
            parsed_url = urlsplit(base_url)
            if (
                parsed_url.scheme not in {"http", "https"}
                or not parsed_url.hostname
                or parsed_url.username is not None
                or parsed_url.password is not None
                or parsed_url.path not in {"", "/"}
                or parsed_url.query
                or parsed_url.fragment
            ):
                errors.append("application.base_url must be an HTTP(S) origin")
        if application.get("demo_disclosure") != (
            "Demo mode is a deterministic reference workspace, not production or customer evidence."
        ):
            errors.append("application.demo_disclosure must preserve the evidence boundary")
        build_id = application.get("next_build_id")
        if not isinstance(build_id, str) or not (1 <= len(build_id) <= 200):
            errors.append("application.next_build_id must be present and bounded")
        for field in (
            "worktree_status_sha256",
            "worktree_diff_sha256",
            "worktree_untracked_sha256",
        ):
            if not _is_sha256(application.get(field)):
                errors.append(f"application.{field} must be a sha256")
        revision = application.get("revision")
        if not isinstance(revision, str) or len(revision) != 40:
            errors.append("application.revision must be a 40-character git revision")
        if require_current_build:
            build_id_path = REPOSITORY_ROOT / "apps" / "web" / ".next" / "BUILD_ID"
            try:
                current_build = build_id_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                errors.append(f"current Next build id cannot be read: {exc}")
            else:
                if application.get("next_build_id") != current_build:
                    errors.append("capture next_build_id does not match the current build")
        if require_current_worktree:
            try:
                current_worktree = _current_worktree_evidence()
            except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
                errors.append(f"current worktree evidence cannot be calculated: {exc}")
            else:
                for field, value in current_worktree.items():
                    if application.get(field) != value:
                        errors.append(f"capture application.{field} is stale")

    if not isinstance(records, list):
        errors.append("records must be an array")
        return errors
    if len(records) != EXPECTED_COUNT:
        errors.append(f"records must contain {EXPECTED_COUNT} entries")

    expected = {
        (route, scene, locale, motion, width, height)
        for route, scene in EXPECTED_SCENES
        for locale in EXPECTED_LOCALES
        for motion in EXPECTED_MOTION
        for width, height in EXPECTED_VIEWPORTS
    }
    observed: set[tuple[str, str, str, str, int, int]] = set()
    observed_files: set[str] = set()
    capture_root = manifest_path.resolve().parent
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"records[{index}] must be an object")
            continue
        viewport = record.get("viewport")
        if not isinstance(viewport, Mapping):
            errors.append(f"records[{index}].viewport must be an object")
            continue
        key = (
            str(record.get("route", "")),
            str(record.get("scene", "")),
            str(record.get("locale", "")),
            str(record.get("motion", "")),
            int(viewport.get("width", -1)),
            int(viewport.get("height", -1)),
        )
        if key in observed:
            errors.append(f"duplicate capture tuple: {key}")
        observed.add(key)
        status = record.get("response_status")
        if not isinstance(status, int) or status >= 400:
            errors.append(f"capture response failed for {key}: {status}")
        if record.get("console_errors") != []:
            errors.append(f"capture contains console errors for {key}")
        inspection = record.get("inspection")
        if not isinstance(inspection, Mapping):
            errors.append(f"capture inspection missing for {key}")
        else:
            if inspection.get("main_present") is not True:
                errors.append(f"main content is missing for {key}")
            if (
                not isinstance(inspection.get("main_text_length"), int)
                or int(inspection["main_text_length"]) <= 0
            ):
                errors.append(f"main content is empty for {key}")
            if inspection.get("horizontal_overflow_px") != 0:
                errors.append(f"horizontal overflow detected for {key}")
            if inspection.get("visible_broken_images") != []:
                errors.append(f"visible broken image detected for {key}")
            if not str(inspection.get("html_lang", "")).startswith(key[2]):
                errors.append(f"locale mismatch detected for {key}")
            cls = inspection.get("cumulative_layout_shift")
            if not isinstance(cls, (int, float)) or isinstance(cls, bool) or cls > 0.1:
                errors.append(f"layout shift guardrail failed for {key}")
            if inspection.get("truth_label_present") is not True:
                errors.append(f"product/proof truth label is missing for {key}")
            for field, description in (
                ("visible_text_below_12px", "visible text below 12px"),
                ("core_text_below_14px", "core text below 14px"),
                ("undersized_core_targets", "undersized core target"),
                ("clipped_core_text", "clipped core text"),
            ):
                if inspection.get(field) != []:
                    errors.append(f"{description} detected for {key}")
        file_name = record.get("file")
        digest = record.get("sha256")
        if not isinstance(file_name, str) or Path(file_name).name != file_name:
            errors.append(f"unsafe capture file path for {key}")
            continue
        if file_name in observed_files:
            errors.append(f"capture file is reused by multiple records: {file_name}")
        observed_files.add(file_name)
        if not file_name.endswith(".webp"):
            errors.append(f"capture file must use WebP: {file_name}")
        file_path = (capture_root / file_name).resolve()
        if file_path.parent != capture_root:
            errors.append(f"capture escapes evidence directory for {key}")
            continue
        if not file_path.is_file():
            errors.append(f"capture file missing for {key}: {file_name}")
        else:
            if file_path.stat().st_size <= 0:
                errors.append(f"capture file is empty for {key}: {file_name}")
            if not _is_sha256(digest) or _sha256(file_path) != digest:
                errors.append(f"capture hash mismatch for {key}: {file_name}")
            try:
                with Image.open(file_path) as screenshot:
                    image_format = screenshot.format
                    image_size = screenshot.size
                    screenshot.verify()
            except (OSError, UnidentifiedImageError) as exc:
                errors.append(f"capture is not a decodable image for {key}: {exc}")
            else:
                if image_format != "WEBP":
                    errors.append(f"capture image format must be WEBP for {key}")
                if key[1] == "above_fold":
                    if image_size != (key[4], key[5]):
                        errors.append(f"above-fold capture dimensions differ for {key}")
                else:
                    expected_asset_size = (
                        inspection.get("asset_width_px")
                        if isinstance(inspection, Mapping)
                        else None,
                        inspection.get("asset_height_px")
                        if isinstance(inspection, Mapping)
                        else None,
                    )
                    if not all(
                        isinstance(value, int) and not isinstance(value, bool) and value > 0
                        for value in expected_asset_size
                    ):
                        errors.append(f"signature asset dimensions are missing for {key}")
                    elif image_size != expected_asset_size:
                        errors.append(f"signature capture dimensions differ for {key}")
                    if (
                        not isinstance(inspection, Mapping)
                        or not isinstance(inspection.get("asset_text_length"), int)
                        or int(inspection["asset_text_length"]) <= 0
                    ):
                        errors.append(f"signature asset text is empty for {key}")
                    if (
                        not isinstance(inspection, Mapping)
                        or inspection.get("asset_truth_label_present") is not True
                    ):
                        errors.append(f"signature asset truth boundary is missing for {key}")

    missing = expected - observed
    unexpected = observed - expected
    if missing:
        errors.append(f"capture matrix is missing {len(missing)} tuples")
    if unexpected:
        errors.append(f"capture matrix has {len(unexpected)} unexpected tuples")
    actual_capture_files = {path.name for path in capture_root.glob("*.webp") if path.is_file()}
    if actual_capture_files != observed_files:
        errors.append("capture directory contains missing or stale WebP files")
    expected_hash_index = "".join(
        f"{record.get('sha256')}  {record.get('file')}\n"
        for record in records
        if isinstance(record, Mapping)
    )
    try:
        actual_hash_index = (capture_root / "hashes.sha256").read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"capture hash index cannot be read: {exc}")
    else:
        if actual_hash_index != expected_hash_index:
            errors.append("capture hash index does not match the manifest records")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--require-current-build", action="store_true")
    parser.add_argument("--require-current-worktree", action="store_true")
    args = parser.parse_args()
    errors = validate(
        args.manifest,
        require_current_build=args.require_current_build,
        require_current_worktree=args.require_current_worktree,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print(f"Structara v4 visual capture evidence passed ({EXPECTED_COUNT} captures).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
