from __future__ import annotations

from pathlib import Path

from infra.security.validate_repository import scan_browser_secret_exports


def write_source(root: Path, name: str, value: str) -> None:
    source = root / "apps/web/src" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(value, encoding="utf-8")


def test_browser_secret_export_scan_accepts_public_nonsecret_configuration(
    tmp_path: Path,
) -> None:
    write_source(
        tmp_path,
        "safe.ts",
        "const api = process.env.NEXT_PUBLIC_AKC_API_URL;",
    )
    errors: list[str] = []
    scan_browser_secret_exports(errors, root=tmp_path)
    assert errors == []


def test_browser_secret_export_scan_rejects_public_or_direct_server_secrets(
    tmp_path: Path,
) -> None:
    write_source(
        tmp_path,
        "unsafe.ts",
        "const a = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_SECRET;\n"
        "const b = process.env.OIDC_CLIENT_SECRET;",
    )
    errors: list[str] = []
    scan_browser_secret_exports(errors, root=tmp_path)
    assert [error.replace("\\", "/") for error in errors] == [
        "browser secret export marker in apps/web/src/unsafe.ts"
    ]
