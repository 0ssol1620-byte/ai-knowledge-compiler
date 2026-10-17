"""Tests for the KB1 item-level rights manifest tool (design §3, §5.10, §5.11, KB-F2, KB-A5).

Every entry below is SYNTHETIC: hosts are under the reserved ``.invalid`` TLD (or name a
denied host only to prove the denial), and every sha256 is the hash of a SYNTHETIC byte
string. No real item was fetched, hashed or recorded.
"""

from __future__ import annotations

import ast
import hashlib
import json
import socket
from pathlib import Path
from typing import Any

import pytest

from research.kb1_korean_bench import rights_manifest as rm
from research.kb1_korean_bench.rights_manifest import Reject


def _sha(label: str) -> str:
    return hashlib.sha256(f"SYNTHETIC {label}".encode()).hexdigest()


def _entry(n: int, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "item_id": f"SYNTHETIC-item-{n:03d}",
        "url": f"https://synthetic-agency.invalid/board/view.do?id=SYNTHETIC-{n}",
        "kogl_type": "1",
        "marking_scope": "item",
        "retrieved_on": "2026-10-17",
        "sha256": _sha(f"item {n}"),
        "family_id": f"SYNTHETIC-family-{n % 2}",
    }
    entry.update(overrides)
    return entry


def _doc(*items: object) -> dict[str, Any]:
    return {"schema": rm.INPUT_SCHEMA, "items": list(items)}


def _codes(manifest: dict[str, Any], index: int) -> set[tuple[str, str | None]]:
    rows = [row for row in manifest["rejected"] if row["index"] == index]
    assert len(rows) == 1, f"entry {index} was not rejected"
    return {(r["code"], r.get("field")) for r in rows[0]["reasons"]}


def test_valid_kogl_0_and_1_item_entries_are_accepted_with_the_prereg_schema() -> None:
    manifest = rm.build_manifest(_doc(_entry(2), _entry(1, kogl_type="0")), "0" * 64)
    assert manifest["rejected"] == []
    assert manifest["counts"] == {"input_entries": 2, "accepted": 2, "rejected": 0}
    assert [row["item_id"] for row in manifest["rights_by_item"]] == [
        "SYNTHETIC-item-001",
        "SYNTHETIC-item-002",
    ]
    assert all(tuple(row) == rm.FIELDS for row in manifest["rights_by_item"])
    assert manifest["policy_status"].startswith("PROPOSED_NOT_FOUNDER_ACCEPTED")
    assert manifest["terms_receipt"]["sha256"].startswith("2f29a949")


@pytest.mark.parametrize(
    ("kogl_type", "code"),
    [
        ("2", Reject.KOGL_TYPE_2_NC),
        ("3", Reject.KOGL_TYPE_3_ND),
        ("4", Reject.KOGL_TYPE_4_NC_ND),
        ("ai_only", Reject.KOGL_AI_TYPE_ONLY),
        ("nc", Reject.LICENCE_NC),
        ("nd", Reject.LICENCE_ND),
        ("ai_hub", Reject.AI_HUB_TERMS),
        ("unlicensed", Reject.UNLICENSED),
        ("expired", Reject.FOUNDER_DECISION_PENDING),
        ("copyright_act_art7", Reject.FOUNDER_DECISION_PENDING),
        ("other", Reject.KOGL_TYPE_UNKNOWN),
        ("KOGL-1", Reject.KOGL_TYPE_UNKNOWN),
        ("CC-BY-NC-SA-4.0", Reject.KOGL_TYPE_UNKNOWN),
    ],
)
def test_every_licence_outside_kogl_0_1_is_rejected_with_its_code(
    kogl_type: str, code: Reject
) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, kogl_type=kogl_type)), "0" * 64)
    assert manifest["rights_by_item"] == []
    assert _codes(manifest, 0) == {(code.value, "kogl_type")}


@pytest.mark.parametrize("scope", ["site", "board", "ITEM", ""])
def test_marking_scope_other_than_item_is_rejected(scope: str) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, marking_scope=scope)), "0" * 64)
    assert manifest["rights_by_item"] == []
    expected = Reject.FIELD_EMPTY_OR_NOT_STRING if scope == "" else Reject.MARKING_SCOPE_NOT_ITEM
    assert _codes(manifest, 0) == {(expected.value, "marking_scope")}


@pytest.mark.parametrize("field", rm.FIELDS)
def test_every_field_is_required(field: str) -> None:
    entry = _entry(1)
    del entry[field]
    manifest = rm.build_manifest(_doc(entry), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.FIELD_MISSING.value, field)}


@pytest.mark.parametrize("bad", [None, 1, True, " SYNTHETIC-family-1", "", ["x"]])
def test_family_id_must_be_a_clean_non_empty_string(bad: object) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, family_id=bad)), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.FIELD_EMPTY_OR_NOT_STRING.value, "family_id")}


def test_integer_kogl_type_is_not_silently_coerced() -> None:
    manifest = rm.build_manifest(_doc(_entry(1, kogl_type=1)), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.FIELD_EMPTY_OR_NOT_STRING.value, "kogl_type")}


@pytest.mark.parametrize(
    "url",
    [
        "https://synthetic-agency.invalid/",
        "https://synthetic-agency.invalid",
        "ftp://synthetic-agency.invalid/item.pdf",
        "file:///D:/SYNTHETIC/item.pdf",
        "D:\\SYNTHETIC\\item.pdf",
        "https:///SYNTHETIC/item.pdf",
        "https://user:secret@synthetic-agency.invalid/item.pdf",
        "https://synthetic-agency.invalid:99999/item.pdf",
        "https://[::1/item.pdf",
        "https://synthetic-agency.invalid/item\n.pdf",
        "https://synthetic-agency.invalid/it em.pdf",
    ],
)
def test_url_must_be_an_absolute_http_item_url(url: str) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, url=url)), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.ITEM_URL_INVALID.value, "url")}


def test_site_root_with_an_item_query_is_an_item_url() -> None:
    url = "https://synthetic-agency.invalid/?nttId=SYNTHETIC-1"
    assert rm.build_manifest(_doc(_entry(1, url=url)), "0" * 64)["rejected"] == []


@pytest.mark.parametrize(
    ("url", "code"),
    [
        ("https://www.aihub.or.kr/SYNTHETIC/item.do", Reject.AI_HUB_TERMS),
        ("https://AIHUB.OR.KR/SYNTHETIC/item.do", Reject.AI_HUB_TERMS),
        (
            "https://huggingface.co/datasets/SYNTHETIC/x/resolve/main/p.png",
            Reject.ITEM_URL_NOT_ORIGINAL_SOURCE,
        ),
        ("https://hf.co/datasets/SYNTHETIC/x", Reject.ITEM_URL_NOT_ORIGINAL_SOURCE),
    ],
)
def test_denied_hosts_are_rejected_whatever_kogl_type_claims(url: str, code: Reject) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, url=url, kogl_type="1")), "0" * 64)
    assert _codes(manifest, 0) == {(code.value, "url")}


_DENIED_HOST_CODES = [
    ("aihub.or.kr", Reject.AI_HUB_TERMS),
    ("www.aihub.or.kr", Reject.AI_HUB_TERMS),
    ("huggingface.co", Reject.ITEM_URL_NOT_ORIGINAL_SOURCE),
    ("hf.co", Reject.ITEM_URL_NOT_ORIGINAL_SOURCE),
]


@pytest.mark.parametrize("spelling", ["{h}.", "{H}", "{H}.", "{h}.:443"])
@pytest.mark.parametrize(("host", "code"), _DENIED_HOST_CODES)
def test_denied_hosts_are_rejected_in_every_spelling_of_the_host(
    host: str, code: Reject, spelling: str
) -> None:
    # A trailing root dot names the same host (aihub.or.kr. is aihub.or.kr), and so does
    # upper case. Either one passing the denial would be fail-open.
    netloc = spelling.format(h=host, H=host.upper())
    url = f"https://{netloc}/datasets/SYNTHETIC/item.do"
    manifest = rm.build_manifest(_doc(_entry(1, url=url, kogl_type="1")), "0" * 64)
    assert _codes(manifest, 0) == {(code.value, "url")}


@pytest.mark.parametrize(
    ("netloc", "code"),
    [
        # IDNA maps the ideographic full stop and fullwidth letters to aihub.or.kr.
        ("aihub\u3002or\u3002kr", Reject.AI_HUB_TERMS),
        ("\uff41\uff49hub.or.kr", Reject.AI_HUB_TERMS),
        ("HF\uff0eCO", Reject.ITEM_URL_NOT_ORIGINAL_SOURCE),
        # A percent-escape in the host is not a host this tool can name: refuse it.
        ("aihub%2Eor.kr", Reject.ITEM_URL_INVALID),
        ("huggingface%2eco", Reject.ITEM_URL_INVALID),
        ("synthetic_agency.invalid", Reject.ITEM_URL_INVALID),
        ("synthetic-agency..invalid", Reject.ITEM_URL_INVALID),
        (".", Reject.ITEM_URL_INVALID),
    ],
)
def test_a_host_is_compared_in_one_spelling_or_refused(netloc: str, code: Reject) -> None:
    url = f"https://{netloc}/datasets/SYNTHETIC/item.do"
    manifest = rm.build_manifest(_doc(_entry(1, url=url, kogl_type="1")), "0" * 64)
    assert _codes(manifest, 0) == {(code.value, "url")}


def test_an_idn_item_host_is_not_refused() -> None:
    url = "https://가상기관.invalid/board/view.do?id=SYNTHETIC-1"
    assert rm.build_manifest(_doc(_entry(1, url=url)), "0" * 64)["rejected"] == []


def test_lookalike_host_is_not_denied() -> None:
    url = "https://notaihub.or.kr.invalid/SYNTHETIC/item.do"
    assert rm.build_manifest(_doc(_entry(1, url=url)), "0" * 64)["rejected"] == []


@pytest.mark.parametrize("day", ["2026-02-30", "20261017", "2026-10-17T00:00:00", "17.10.2026"])
def test_retrieved_on_must_be_a_real_iso_date(day: str) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, retrieved_on=day)), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.RETRIEVED_ON_INVALID.value, "retrieved_on")}


@pytest.mark.parametrize("digest", ["ab" * 31, _sha("x").upper(), "g" * 64, _sha("x") + "0"])
def test_sha256_must_be_64_lower_hex(digest: str) -> None:
    manifest = rm.build_manifest(_doc(_entry(1, sha256=digest)), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.SHA256_INVALID.value, "sha256")}


def test_unknown_field_and_non_object_entry_are_rejected() -> None:
    manifest = rm.build_manifest(_doc(_entry(1, note="SYNTHETIC"), "not an entry"), "0" * 64)
    assert _codes(manifest, 0) == {(Reject.FIELD_UNKNOWN.value, "note")}
    assert _codes(manifest, 1) == {(Reject.ENTRY_NOT_OBJECT.value, None)}
    assert manifest["rejected"][1]["item_id"] is None


def test_duplicates_reject_every_copy_never_first_wins() -> None:
    same_file = _sha("shared file")
    manifest = rm.build_manifest(
        _doc(
            _entry(1, sha256=same_file),
            _entry(2, sha256=same_file, family_id="SYNTHETIC-family-9"),
            _entry(3),
            _entry(3, sha256=_sha("other copy")),
            _entry(4),
        ),
        "0" * 64,
    )
    assert [row["item_id"] for row in manifest["rights_by_item"]] == ["SYNTHETIC-item-004"]
    assert _codes(manifest, 0) == {(Reject.SHA256_DUPLICATE.value, "sha256")}
    assert _codes(manifest, 1) == {(Reject.SHA256_DUPLICATE.value, "sha256")}
    assert _codes(manifest, 2) == {(Reject.ITEM_ID_DUPLICATE.value, "item_id")}
    assert _codes(manifest, 3) == {(Reject.ITEM_ID_DUPLICATE.value, "item_id")}
    assert manifest["counts"] == {"input_entries": 5, "accepted": 1, "rejected": 4}


def test_one_entry_collects_every_reason() -> None:
    entry = _entry(1, kogl_type="4", marking_scope="site", sha256="nope", retrieved_on="x")
    codes = {code for code, _ in _codes(rm.build_manifest(_doc(entry), "0" * 64), 0)}
    assert codes == {
        Reject.KOGL_TYPE_4_NC_ND.value,
        Reject.MARKING_SCOPE_NOT_ITEM.value,
        Reject.SHA256_INVALID.value,
        Reject.RETRIEVED_ON_INVALID.value,
    }


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"items": [_entry(1)]},
        {"schema": "tavonel.kb1.rights_input.v0", "items": [_entry(1)]},
        {"schema": rm.INPUT_SCHEMA, "items": {}},
        {"schema": rm.INPUT_SCHEMA, "items": []},
        {"schema": rm.INPUT_SCHEMA, "items": [_entry(1)], "extra": 1},
    ],
)
def test_malformed_input_document_is_refused(document: object) -> None:
    with pytest.raises(rm.ManifestInputError):
        rm.build_manifest(document, "0" * 64)


def test_reject_codes_are_a_closed_enumeration() -> None:
    used = set(rm.REJECTED_KOGL_TYPES.values()) | set(rm.DENIED_HOSTS.values())
    assert used <= set(Reject)
    assert all(code.value == code.name for code in Reject)
    assert not rm.ACCEPTED_KOGL_TYPES & set(rm.REJECTED_KOGL_TYPES)


# --- no network code path -------------------------------------------------------------

_ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "collections",
    "collections.abc",
    "datetime",
    "enum",
    "hashlib",
    "json",
    "pathlib",
    "re",
    "typing",
    "urllib.parse",
}


def test_module_imports_nothing_that_can_reach_the_network() -> None:
    tree = ast.parse(Path(rm.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import widens the reachable code"
            imported.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"__import__", "eval", "exec", "open"}
    assert imported <= _ALLOWED_IMPORTS, imported - _ALLOWED_IMPORTS


class _NetworkBlocked(AssertionError):
    pass


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise _NetworkBlocked("network access attempted")

    monkeypatch.setattr(socket.socket, "__init__", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "gethostbyname", refuse)


def test_socket_block_is_live(no_network: None) -> None:
    with pytest.raises(_NetworkBlocked):
        socket.socket()
    with pytest.raises(_NetworkBlocked):
        socket.getaddrinfo("synthetic-agency.invalid", 443)


def test_cli_writes_manifest_with_sockets_blocked(
    no_network: None, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "SYNTHETIC-rights-input.json"
    source.write_text(
        json.dumps(_doc(_entry(1), _entry(2, kogl_type="2"), _entry(3, marking_scope="site"))),
        encoding="utf-8",
    )
    out = tmp_path / "SYNTHETIC-rights-manifest.json"
    assert rm.main(["--input", str(source), "--out", str(out)]) == 0

    payload = out.read_bytes()
    assert b"\r" not in payload
    manifest = json.loads(payload)
    assert manifest["input_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert [row["item_id"] for row in manifest["rights_by_item"]] == ["SYNTHETIC-item-001"]
    stdout = capsys.readouterr().out
    assert "accepted 1 / 3 input entries" in stdout
    assert "rejected 2 / 3 input entries" in stdout
    assert f"manifest_sha256 {hashlib.sha256(payload).hexdigest()}" in stdout
    assert rm.render(rm.build_manifest(json.loads(source.read_bytes()), "x")) == rm.render(
        rm.build_manifest(json.loads(source.read_bytes()), "x")
    )


@pytest.mark.parametrize(
    "content",
    [b"{not json", b"\xff\xfe", json.dumps({"schema": rm.INPUT_SCHEMA, "items": []}).encode()],
)
def test_cli_refuses_bad_input_and_writes_nothing(
    no_network: None, tmp_path: Path, content: bytes
) -> None:
    source = tmp_path / "SYNTHETIC-bad-input.json"
    source.write_bytes(content)
    out = tmp_path / "SYNTHETIC-never-written.json"
    assert rm.main(["--input", str(source), "--out", str(out)]) == 2
    assert not out.exists()
