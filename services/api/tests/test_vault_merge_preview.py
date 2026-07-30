from __future__ import annotations

import io
import zipfile

import pytest
from akc_api.vault_merge import (
    VaultZipLimits,
    preview_vault_merge,
    read_exported_vault_zip,
    read_vault_zip,
)
from akc_exporters import MergePolicy


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for path, payload in sorted(files.items()):
            archive.writestr(path, payload)
    return buffer.getvalue()


def test_vault_merge_preview_is_deterministic_and_never_applies_changes() -> None:
    existing = _zip(
        {
            "00-Home/Home.md": b"# User-owned home\n",
            "Personal.md": b"# Personal note\n",
        }
    )
    generated = _zip(
        {
            "manifest.json": b"{}\n",
            "obsidian/00-Home/Home.md": b"# Generated home\n",
            "obsidian/10-Documents/source.md": b"# Source\n",
        }
    )

    blocked, blocked_summary = preview_vault_merge(
        existing_zip=existing,
        export_zip=generated,
        policy=MergePolicy.ERROR,
    )
    repeated, repeated_summary = preview_vault_merge(
        existing_zip=existing,
        export_zip=generated,
        policy=MergePolicy.ERROR,
    )
    assert blocked.safe_to_apply is False
    assert blocked.files["00-Home/Home.md"] == b"# User-owned home\n"
    assert blocked.files["Personal.md"] == b"# Personal note\n"
    assert blocked.conflicts[0].reason == "unresolved_content_conflict"
    assert blocked_summary == repeated_summary
    assert blocked_summary["unresolved_conflict_count"] == 1
    assert blocked_summary["plan_sha256"] == repeated_summary["plan_sha256"]
    assert blocked.files == repeated.files

    renamed, renamed_summary = preview_vault_merge(
        existing_zip=existing,
        export_zip=generated,
        policy=MergePolicy.RENAME_INCOMING,
    )
    assert renamed.safe_to_apply is True
    assert renamed.conflicts[0].resolution == "renamed_incoming"
    assert renamed.conflicts[0].resolved_path != "00-Home/Home.md"
    assert renamed_summary["unresolved_conflict_count"] == 0
    # The preview result is an in-memory plan. The supplied ZIP is unchanged.
    assert read_vault_zip(existing)["00-Home/Home.md"] == b"# User-owned home\n"


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"../escape.md": b"x"}, "vault_archive_unsafe_path"),
        (
            {"Note.md": b"one", "note.md": b"two"},
            "vault_archive_duplicate_path",
        ),
    ],
)
def test_vault_zip_rejects_unsafe_or_case_colliding_paths(
    files: dict[str, bytes],
    code: str,
) -> None:
    with pytest.raises(ValueError, match=code):
        read_vault_zip(_zip(files))


def test_vault_zip_rejects_symlinks_and_compression_bombs() -> None:
    symlink_buffer = io.BytesIO()
    with zipfile.ZipFile(symlink_buffer, "w") as archive:
        entry = zipfile.ZipInfo("linked.md")
        entry.create_system = 3
        entry.external_attr = 0o120777 << 16
        archive.writestr(entry, b"target.md")
    with pytest.raises(ValueError, match="vault_archive_symlink"):
        read_vault_zip(symlink_buffer.getvalue())

    compressed = _zip({"large.md": b"A" * 100_000})
    with pytest.raises(ValueError, match="vault_archive_compression_ratio"):
        read_vault_zip(
            compressed,
            limits=VaultZipLimits(
                max_archive_bytes=len(compressed) + 1,
                max_entries=10,
                max_uncompressed_bytes=200_000,
                max_member_bytes=200_000,
                max_compression_ratio=2,
            ),
        )


def test_generated_bundle_requires_an_obsidian_profile() -> None:
    with pytest.raises(ValueError, match="export_has_no_obsidian_profile"):
        read_exported_vault_zip(_zip({"portable/document.md": b"# Source\n"}))
