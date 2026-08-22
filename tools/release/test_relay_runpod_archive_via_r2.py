from __future__ import annotations

import hashlib
from pathlib import Path

from tools.release.relay_runpod_archive_via_r2 import (
    parse_env,
    parse_r2_credentials,
    sha256_file,
)


def test_parse_r2_credentials_is_bounded_to_cloudflare_block(tmp_path: Path) -> None:
    path = tmp_path / "credentials.txt"
    path.write_text(
        "Cloudflare R2:\n"
        "Access Key ID: access-value\n"
        "Secret Access Key: secret-value\n"
        "Use jurisdiction-specific endpoints for S3 clients: "
        "https://account.apac.r2.cloudflarestorage.com\n"
        "User API Tokens:\n"
        "Access Key ID: wrong-value\n",
        encoding="utf-8",
    )

    assert parse_r2_credentials(path) == (
        "access-value",
        "secret-value",
        "https://account.apac.r2.cloudflarestorage.com",
    )


def test_parse_env_and_streaming_hash(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("A=one\nB='two'\n", encoding="utf-8")
    archive = tmp_path / "archive.bin"
    archive.write_bytes(b"bounded evidence")

    assert parse_env(env_path) == {"A": "one", "B": "two"}
    assert sha256_file(archive) == hashlib.sha256(b"bounded evidence").hexdigest()
