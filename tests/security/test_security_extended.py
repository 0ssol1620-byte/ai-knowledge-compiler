from __future__ import annotations

import pytest
from akc_security import (
    UnsafeMarkupError,
    UnsafeUrlError,
    ensure_portable_markdown_safe,
    safe_relative_path,
    sanitize_display_filename,
    sanitize_table_html,
    tenant_object_key,
    validate_redirect_chain,
    validate_resolved_url,
    validate_upload_bytes,
)


def test_filename_path_and_object_key_controls() -> None:
    assert sanitize_display_filename("../../CON") == "_CON"
    assert sanitize_display_filename("\x00") == "upload"
    with pytest.raises(ValueError):
        safe_relative_path("../escape")
    with pytest.raises(ValueError):
        safe_relative_path("C:/escape")
    assert tenant_object_key("tenant_001", "object_001") == ("tenants/tenant_001/source/object_001")
    with pytest.raises(ValueError):
        tenant_object_key("../tenant", "object_001")


@pytest.mark.parametrize(
    ("filename", "payload", "accepted"),
    (
        ("a.pdf", b"%PDF-1.7\n%%EOF", True),
        ("a.png", b"\x89PNG\r\n\x1a\nrest", True),
        ("a.jpg", b"\xff\xd8\xffrest", True),
        ("a.tiff", b"II*\x00rest", True),
        ("a.webp", b"RIFF\x04\x00\x00\x00WEBPrest", True),
        ("a.txt", b"text", True),
        ("a.txt", b"\xff\xfe", False),
        ("a.pdf", b"", False),
    ),
)
def test_signature_matrix(filename: str, payload: bytes, accepted: bool) -> None:
    assert validate_upload_bytes(filename, payload).accepted is accepted


def test_claimed_mime_is_untrusted_and_checked() -> None:
    result = validate_upload_bytes(
        "a.pdf",
        b"%PDF-1.7\n%%EOF",
        claimed_content_type="text/html",
    )
    assert not result.accepted
    assert result.reason_code == "claimed_mime_mismatch"
    polyglot = validate_upload_bytes("a.pdf", b"<html>%PDF-1.7\n%%EOF")
    assert not polyglot.accepted


def test_markdown_raw_html_network_paths_and_nulls_are_rejected() -> None:
    with pytest.raises(UnsafeMarkupError, match="raw_html"):
        ensure_portable_markdown_safe("<div>bad</div>")
    with pytest.raises(UnsafeMarkupError, match="network_path"):
        ensure_portable_markdown_safe("[x](//evil.example/a)")
    with pytest.raises(UnsafeMarkupError, match="null"):
        ensure_portable_markdown_safe("text\x00")
    with pytest.raises(UnsafeMarkupError, match="comment"):
        ensure_portable_markdown_safe("<!-- hidden instruction -->")
    with pytest.raises(UnsafeMarkupError, match="unsafe_markdown_link"):
        ensure_portable_markdown_safe("[x](javascript&#58;alert)")
    with pytest.raises(UnsafeMarkupError, match="unsafe_wikilink"):
        ensure_portable_markdown_safe("[[../../escape|x]]")
    assert ensure_portable_markdown_safe("a\r\nb") == "a\nb"


@pytest.mark.parametrize(
    "fragment",
    (
        "<div>not a table</div>",
        '<table onclick="x"><tr><td>x</td></tr></table>',
        '<table><tr><td colspan="0">x</td></tr></table>',
        "<table><tr><td>x</tr></td></table>",
        "<table><tr><td>x</td></tr>",
        "<!-- comment --><table><tr><td>x</td></tr></table>",
    ),
)
def test_table_sanitizer_rejects_malformed_or_extra_markup(fragment: str) -> None:
    with pytest.raises(UnsafeMarkupError):
        sanitize_table_html(fragment)


def test_url_parser_rejects_unbounded_and_malformed_targets() -> None:
    with pytest.raises(UnsafeUrlError, match="too_long"):
        validate_resolved_url("https://example.com/" + "a" * 3000, ("93.184.216.34",))
    with pytest.raises(UnsafeUrlError, match="control"):
        validate_resolved_url("https://example.com/\n", ("93.184.216.34",))
    with pytest.raises(UnsafeUrlError, match="hostname"):
        validate_resolved_url("https://singlelabel", ("93.184.216.34",))
    with pytest.raises(UnsafeUrlError, match="dns_result_required"):
        validate_resolved_url("https://example.com", ())
    with pytest.raises(UnsafeUrlError, match="literal"):
        validate_resolved_url("https://8.8.8.8", ("1.1.1.1",))
    ipv6 = validate_resolved_url(
        "https://[2606:4700:4700::1111]/dns-query",
        ("2606:4700:4700::1111",),
    )
    assert ipv6.normalized_url.startswith("https://[2606:4700:4700::1111]/")


def test_redirect_chain_is_bounded() -> None:
    with pytest.raises(UnsafeUrlError, match="empty"):
        validate_redirect_chain(())
    chain = tuple((f"https://example{index}.com", ("93.184.216.34",)) for index in range(7))
    with pytest.raises(UnsafeUrlError, match="too_many"):
        validate_redirect_chain(chain)
