"""Bounded, fail-closed Obsidian Vault ZIP merge previews."""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from dataclasses import dataclass

from akc_exporters import MergePolicy, VaultMergePlan, plan_vault_merge
from akc_security import safe_relative_path


@dataclass(frozen=True, slots=True)
class VaultZipLimits:
    max_archive_bytes: int = 32 * 1024 * 1024
    max_entries: int = 5_000
    max_uncompressed_bytes: int = 128 * 1024 * 1024
    max_member_bytes: int = 16 * 1024 * 1024
    max_compression_ratio: float = 100.0

    def __post_init__(self) -> None:
        if (
            self.max_archive_bytes <= 0
            or self.max_entries <= 0
            or self.max_uncompressed_bytes <= 0
            or self.max_member_bytes <= 0
            or self.max_compression_ratio < 1
        ):
            raise ValueError("Vault ZIP limits must be positive and bounded")
        if self.max_member_bytes > self.max_uncompressed_bytes:
            raise ValueError("Vault ZIP member limit exceeds total limit")


DEFAULT_VAULT_ZIP_LIMITS = VaultZipLimits()


def _archive(data: bytes, limits: VaultZipLimits) -> zipfile.ZipFile:
    if not data or len(data) > limits.max_archive_bytes:
        raise ValueError("vault_archive_size_invalid")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("vault_archive_invalid") from exc
    return archive


def read_vault_zip(
    data: bytes,
    *,
    limits: VaultZipLimits = DEFAULT_VAULT_ZIP_LIMITS,
) -> dict[str, bytes]:
    """Read an untrusted Vault ZIP without extracting it to the filesystem."""

    archive = _archive(data, limits)
    with archive:
        entries = archive.infolist()
        if len(entries) > limits.max_entries:
            raise ValueError("vault_archive_entry_limit")
        files: dict[str, bytes] = {}
        folded_paths: set[str] = set()
        uncompressed_total = 0
        compressed_total = 0
        for entry in entries:
            raw_name = entry.filename.replace("\\", "/")
            if entry.is_dir():
                safe_relative_path(raw_name.rstrip("/"))
                continue
            try:
                path = safe_relative_path(raw_name)
            except ValueError as exc:
                raise ValueError("vault_archive_unsafe_path") from exc
            folded = path.casefold()
            if folded in folded_paths:
                raise ValueError("vault_archive_duplicate_path")
            folded_paths.add(folded)
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("vault_archive_symlink")
            if entry.flag_bits & 0x1:
                raise ValueError("vault_archive_encrypted")
            if entry.file_size < 0 or entry.file_size > limits.max_member_bytes:
                raise ValueError("vault_archive_member_limit")
            uncompressed_total += entry.file_size
            compressed_total += max(0, entry.compress_size)
            if uncompressed_total > limits.max_uncompressed_bytes:
                raise ValueError("vault_archive_uncompressed_limit")
            if uncompressed_total / max(1, compressed_total) > limits.max_compression_ratio:
                raise ValueError("vault_archive_compression_ratio")
            try:
                payload = archive.read(entry)
            except (RuntimeError, zipfile.BadZipFile, OSError) as exc:
                raise ValueError("vault_archive_member_invalid") from exc
            if len(payload) != entry.file_size:
                raise ValueError("vault_archive_member_size_mismatch")
            files[path] = payload
    return dict(sorted(files.items()))


def read_exported_vault_zip(
    data: bytes,
    *,
    limits: VaultZipLimits = DEFAULT_VAULT_ZIP_LIMITS,
) -> dict[str, bytes]:
    """Read only the ``obsidian/`` profile from a generated export bundle."""

    bundle = read_vault_zip(data, limits=limits)
    prefix = "obsidian/"
    files = {
        safe_relative_path(path.removeprefix(prefix)): payload
        for path, payload in bundle.items()
        if path.startswith(prefix) and len(path) > len(prefix)
    }
    if not files:
        raise ValueError("export_has_no_obsidian_profile")
    return dict(sorted(files.items()))


def preview_vault_merge(
    *,
    existing_zip: bytes,
    export_zip: bytes,
    policy: MergePolicy,
    limits: VaultZipLimits = DEFAULT_VAULT_ZIP_LIMITS,
) -> tuple[VaultMergePlan, dict[str, int | str | bool]]:
    existing = read_vault_zip(existing_zip, limits=limits)
    incoming = read_exported_vault_zip(export_zip, limits=limits)
    plan = plan_vault_merge(existing, incoming, policy=policy)
    digest = hashlib.sha256()
    for path, payload in sorted(plan.files.items()):
        encoded_path = path.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(hashlib.sha256(payload).digest())
    unresolved = sum(conflict.resolution is None for conflict in plan.conflicts)
    return plan, {
        "schema_version": "vault-merge-preview-1.0.0",
        "policy": policy.value,
        "existing_file_count": len(existing),
        "incoming_file_count": len(incoming),
        "output_file_count": len(plan.files),
        "conflict_count": len(plan.conflicts),
        "unresolved_conflict_count": unresolved,
        "broken_link_count": len(plan.broken_links),
        "safe_to_apply": plan.safe_to_apply,
        "plan_sha256": digest.hexdigest(),
    }
