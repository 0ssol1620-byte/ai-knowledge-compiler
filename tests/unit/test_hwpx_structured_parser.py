"""HWPX (OWPML) bounded reader: package gate, extraction profile and fences.

Every package here is synthetic, written for this file from the public OWPML
package layout. No third-party HWPX file or fixture is used.
"""

from __future__ import annotations

import hashlib
import io
import stat
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_api.parsers import FileValidationError, parse_document, validate_file
from akc_api.settings import Settings
from akc_cir import BlockType, CanonicalBlock, CanonicalDocument, canonical_json
from akc_native_parsers import (
    ParseContext,
    ParserLimits,
    StructuredParseError,
    parse_non_pdf_to_cir,
)
from akc_security.hwpx import HwpxLimits, HwpxPackageError, inspect_hwpx_package

HWPX_MIME = "application/hwp+zip"
P2011 = "http://www.hancom.co.kr/hwpml/2011/paragraph"
P2016 = "http://www.hancom.co.kr/hwpml/2016/paragraph"
P2021 = "http://www.owpml.org/owpml/2021/paragraph"
S2011 = "http://www.hancom.co.kr/hwpml/2011/section"
S2021 = "http://www.owpml.org/owpml/2021/section"
S2024 = "http://www.owpml.org/owpml/2024/section"
H2011 = "http://www.hancom.co.kr/hwpml/2011/head"
OPF = "http://www.idpf.org/2007/opf/"
OCF = "urn:oasis:names:tc:opendocument:xmlns:container"
ODF_MANIFEST = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
XLINK = "http://www.w3.org/1999/xlink"
RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FIXED_TIME = (2026, 10, 9, 0, 0, 0)
PARTIAL_WARNINGS = {
    "hwpx_partial_fidelity",
    "hwpx_physical_pagination_unavailable",
    "hwpx_styling_not_preserved",
    "hwpx_layout_not_preserved",
}
DTD = '<!DOCTYPE x [<!ENTITY e "expanded">]>'


# --- synthetic package builder ------------------------------------------------


def t(text: str) -> str:
    return f"<hp:t>{text}</hp:t>"


def run(*content: str) -> str:
    return f"<hp:run>{''.join(content)}</hp:run>"


def para(*content: str) -> str:
    return f"<hp:p>{''.join(content)}</hp:p>"


def text_para(text: str) -> str:
    return para(run(t(text)))


def cell(
    text: str,
    row: int,
    column: int,
    *,
    header: bool = False,
    span: tuple[int, int] = (1, 1),
    inner: str | None = None,
) -> str:
    body = inner if inner is not None else text_para(text)
    return (
        f'<hp:tc header="{1 if header else 0}">'
        f'<hp:cellAddr colAddr="{column}" rowAddr="{row}"/>'
        f'<hp:cellSpan colSpan="{span[0]}" rowSpan="{span[1]}"/>'
        f"<hp:subList>{body}</hp:subList></hp:tc>"
    )


def table(
    rows: list[list[str]],
    *,
    row_count: str | None = None,
    col_count: str | None = None,
) -> str:
    attributes = ""
    if row_count is not None:
        attributes += f' rowCnt="{row_count}"'
    if col_count is not None:
        attributes += f' colCnt="{col_count}"'
    body = "".join(f"<hp:tr>{''.join(row)}</hp:tr>" for row in rows)
    return f"<hp:tbl{attributes}>{body}</hp:tbl>"


def grid(texts: list[list[str]], *, header_rows: int = 0) -> list[list[str]]:
    return [
        [cell(value, r, c, header=r < header_rows) for c, value in enumerate(row)]
        for r, row in enumerate(texts)
    ]


def section(body: str, *, sec_ns: str = S2011, para_ns: str = P2011) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<hs:sec xmlns:hs="{sec_ns}" xmlns:hp="{para_ns}">{body}</hs:sec>'
    )


def container(*rootfiles: tuple[str, str]) -> bytes:
    entries = rootfiles or (("Contents/content.hpf", "application/hwpml-package+xml"),)
    body = "".join(
        f'<ocf:rootfile full-path="{path}" media-type="{media}"/>' for path, media in entries
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><ocf:container xmlns:ocf="{OCF}">'
        f"<ocf:rootfiles>{body}</ocf:rootfiles></ocf:container>"
    ).encode()


def content_hpf(items: list[tuple[str, str, str]], spine: list[str]) -> bytes:
    manifest = "".join(
        f'<opf:item id="{item_id}" href="{href}" media-type="{media}"/>'
        for item_id, href, media in items
    )
    references = "".join(f'<opf:itemref idref="{ref}" linear="yes"/>' for ref in spine)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><opf:package xmlns:opf="{OPF}" version="">'
        f"<opf:manifest>{manifest}</opf:manifest><opf:spine>{references}</opf:spine>"
        "</opf:package>"
    ).encode()


HEADER = f'<?xml version="1.0" encoding="UTF-8"?><hh:head xmlns:hh="{H2011}" secCnt="1"/>'
HEADER_ITEM = ("header", "Contents/header.xml", "application/xml")
SECTION_ITEM = ("section0", "Contents/section0.xml", "application/xml")


def package_parts(*sections: str, spine: list[int] | None = None) -> dict[str, bytes]:
    parts: dict[str, bytes] = {
        "mimetype": HWPX_MIME.encode(),
        "META-INF/container.xml": container(),
        "Contents/header.xml": HEADER.encode(),
    }
    items = [HEADER_ITEM]
    for index, source in enumerate(sections):
        parts[f"Contents/section{index}.xml"] = source.encode()
        items.append((f"section{index}", f"Contents/section{index}.xml", "application/xml"))
    order = spine if spine is not None else list(range(len(sections)))
    parts["Contents/content.hpf"] = content_hpf(
        items, ["header", *(f"section{index}" for index in order)]
    )
    return parts


def zip_parts(
    parts: dict[str, bytes],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
    symlinks: tuple[str, ...] = (),
) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, payload in parts.items():
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_STORED if name == "mimetype" else compression
            if name in symlinks:
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, payload)
    return output.getvalue()


def hwpx(*sections: str, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    return zip_parts(package_parts(*sections), compression=compression)


def table_doc(table_xml: str) -> bytes:
    return hwpx(section(para(run(table_xml))))


def set_part(parts: dict[str, bytes], name: str, payload: bytes | None) -> dict[str, bytes]:
    updated = dict(parts)
    if payload is None:
        del updated[name]
    else:
        updated[name] = payload
    return updated


def flag_encrypted(data: bytes, name: str) -> bytes:
    """Set the ZIP encryption bit on one central-directory record."""

    target = name.encode()
    patched = bytearray(data)
    offset = patched.find(b"PK\x01\x02")
    while offset != -1:
        name_length = int.from_bytes(patched[offset + 28 : offset + 30], "little")
        if bytes(patched[offset + 46 : offset + 46 + name_length]) == target:
            patched[offset + 8] |= 0x1
            return bytes(patched)
        offset = patched.find(b"PK\x01\x02", offset + 46)
    raise AssertionError(name)


# --- parse helpers --------------------------------------------------------------


@pytest.fixture
def parse_context() -> ParseContext:
    return ParseContext(
        tenant_id="tenant_fixture",
        document_id="document_fixture",
        document_version_id="version_fixture",
        created_at=datetime(2026, 10, 9, 12, 0, tzinfo=UTC),
    )


def parse(
    data: bytes,
    context: ParseContext,
    limits: ParserLimits | None = None,
) -> CanonicalDocument:
    return parse_non_pdf_to_cir(
        filename="업무_보고서.hwpx",
        declared_mime=HWPX_MIME,
        data=data,
        context=context,
        limits=limits,
    )


def rejection(data: bytes, context: ParseContext, limits: ParserLimits | None = None) -> str:
    with pytest.raises(StructuredParseError) as failure:
        parse(data, context, limits)
    return failure.value.code


def anchor(block: CanonicalBlock) -> str:
    native = block.source_refs[0].native_object_id
    assert native is not None
    return native


def texts(document: CanonicalDocument) -> list[str]:
    return [block.raw_text or "" for block in document.blocks]


def occurrences(document: CanonicalDocument, needle: str) -> int:
    # Counted over the extracted blocks' raw text, never over canonical JSON,
    # which carries each block's text twice (rawText and normalizedText).
    return sum(text.count(needle) for text in texts(document))


# --- extraction profile ---------------------------------------------------------


def test_korean_paragraphs_and_basic_table_keep_document_order_and_anchors(
    parse_context: ParseContext,
) -> None:
    scores = table(
        grid([["항목", "값"], ["점수", "0.94"]], header_rows=1), row_count="2", col_count="2"
    )
    body = (
        text_para("첫 문단입니다.")
        + para(run(t("표 앞 문장"), scores, t("표 뒤 문장")))
        + para(run(t("가<hp:tab/>나<hp:lineBreak/>다<hp:nbSpace/>라<hp:fwSpace/>마")))
    )
    document = parse(hwpx(section(body)), parse_context)

    assert [block.type for block in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
    ]
    assert [anchor(block) for block in document.blocks] == [
        "hwpx/section/0000/p/000000/text/000",
        "hwpx/section/0000/p/000001/text/000",
        "hwpx/section/0000/p/000001/tbl/000",
        "hwpx/section/0000/p/000001/text/001",
        "hwpx/section/0000/p/000002/text/000",
    ]
    assert texts(document)[0] == "첫 문단입니다."
    assert texts(document)[1] == "표 앞 문장"
    assert texts(document)[3] == "표 뒤 문장"
    assert texts(document)[4] == "가\t나\n다\N{NO-BREAK SPACE}라\N{IDEOGRAPHIC SPACE}마"
    table_block = document.blocks[2]
    assert table_block.table is not None
    assert (table_block.table.row_count, table_block.table.column_count) == (2, 2)
    assert table_block.table.header_row_count == 1
    assert [(c.row_index0, c.column_index0, c.raw_text) for c in table_block.table.cells] == [
        (0, 0, "항목"),
        (0, 1, "값"),
        (1, 0, "점수"),
        (1, 1, "0.94"),
    ]
    assert table_block.table.cells[3].source_refs[0].native_object_id == (
        "hwpx/section/0000/p/000001/tbl/000/tr/000001/tc/000001"
    )
    # Sections are not physical pages: everything sits on one logical page.
    assert {ref.page_index0 for block in document.blocks for ref in block.source_refs} == {0}
    # Nothing is duplicated across blocks.
    assert occurrences(document, "표 앞 문장") == 1
    assert occurrences(document, "표 뒤 문장") == 1


def test_metadata_declares_partial_profile_and_parser_version_is_unchanged(
    parse_context: ParseContext,
) -> None:
    document = parse(hwpx(section(text_para("본문"))), parse_context)
    metadata = document.metadata
    assert metadata["documentType"] == "hwpx"
    assert metadata["nativeParserVersion"] == "1.2.0"
    assert set(metadata["warnings"]) >= PARTIAL_WARNINGS
    assert "hwpx_unsupported_content_omitted" not in metadata["warnings"]
    assert metadata["sourceLocationScheme"].startswith("hwpx/section/")
    profile = metadata["hwpx"]
    assert profile["extractionProfile"] == "text-basic-tables-v1"
    assert profile["supportStatus"] == "partial"
    assert profile["logicalPageModel"] == "single-logical-page"
    assert profile["headPartCount"] == 1
    assert profile["spineItemCount"] == 2
    assert profile["sections"] == [
        {"index": 0, "idref": "section0", "part": "Contents/section0.xml"}
    ]
    assert document.title == "업무 보고서"


def test_reading_order_follows_the_spine_not_zip_or_filename_order(
    parse_context: ParseContext,
) -> None:
    parts = package_parts(
        section(text_para("첫째 파일")), section(text_para("둘째 파일")), spine=[1, 0]
    )
    document = parse(zip_parts(parts), parse_context)
    assert texts(document) == ["둘째 파일", "첫째 파일"]
    assert anchor(document.blocks[0]).startswith("hwpx/section/0000/")
    assert document.metadata["hwpx"]["sections"][0]["part"] == "Contents/section1.xml"


def test_parsing_is_deterministic_and_round_trips(parse_context: ParseContext) -> None:
    data = hwpx(section(text_para("결정성") + para(run(table(grid([["a", "b"]]))))))
    first = parse(data, parse_context)
    second = parse(data, parse_context)
    wire = canonical_json(first)
    assert wire == canonical_json(second)
    assert CanonicalDocument.model_validate_json(wire) == first


@pytest.mark.parametrize("para_ns", [P2011, P2016, P2021])
@pytest.mark.parametrize("sec_ns", [S2011, S2021, S2024])
def test_every_official_namespace_family_is_read_by_uri(
    parse_context: ParseContext,
    sec_ns: str,
    para_ns: str,
) -> None:
    body = text_para("네임스페이스") + para(run(table(grid([["x"]]))))
    document = parse(hwpx(section(body, sec_ns=sec_ns, para_ns=para_ns)), parse_context)
    assert texts(document)[0] == "네임스페이스"
    assert document.blocks[1].type == BlockType.TABLE


@pytest.mark.parametrize("para_ns", [P2011, P2016, P2021])
def test_prefixes_are_never_consulted(parse_context: ParseContext, para_ns: str) -> None:
    renamed = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<zz:sec xmlns:zz="{S2024}" xmlns:q9="{para_ns}">'
        + text_para("임의 접두사").replace("hp:", "q9:")
        + "</zz:sec>"
    )
    default_prefix = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<s:sec xmlns:s="{S2011}" xmlns="{para_ns}"><p><run><t>기본 접두사</t></run></p></s:sec>'
    )
    assert texts(parse(hwpx(renamed), parse_context)) == ["임의 접두사"]
    assert texts(parse(hwpx(default_prefix), parse_context)) == ["기본 접두사"]


@pytest.mark.parametrize(
    ("sec_ns", "para_ns"),
    [
        (S2011, "http://www.hancom.co.kr/hwpml/2011/paragraph/"),
        (S2011, "http://www.hancom.co.kr/hwpml/2011/paragraphs"),
        (S2011, "http://www.owpml.org/owpml/2022/paragraph"),
        (S2011, "urn:example:paragraph"),
        ("http://www.hancom.co.kr/hwpml/2011/section/", P2011),
        ("http://www.owpml.org/owpml/2016/section", P2011),
    ],
)
def test_lookalike_namespaces_are_not_read(
    parse_context: ParseContext,
    sec_ns: str,
    para_ns: str,
) -> None:
    data = hwpx(section(text_para("가짜 본문"), sec_ns=sec_ns, para_ns=para_ns))
    with pytest.raises(StructuredParseError) as failure:
        parse(data, parse_context)
    assert failure.value.code == "HWPX_EMPTY_DOCUMENT"
    assert "가짜 본문" not in str(failure.value)


def test_decoy_paragraph_beside_real_content_is_counted_not_read(
    parse_context: ParseContext,
) -> None:
    decoy = '<x:p xmlns:x="urn:example:paragraph"><x:run><x:t>숨은 글</x:t></x:run></x:p>'
    document = parse(hwpx(section(text_para("진짜 글") + decoy)), parse_context)
    assert texts(document) == ["진짜 글"]
    assert "숨은 글" not in canonical_json(document)
    assert document.metadata["hwpx"]["unsupportedFeatures"] == {"other": 1}


def test_direct_paragraph_and_run_text_and_tails_are_preserved_in_order(
    parse_context: ParseContext,
) -> None:
    body = (
        "<hp:p>문단 직접 "
        "<hp:run>런 직접 <hp:t>본문</hp:t> 런 꼬리</hp:run>"
        " 문단 꼬리<hp:linesegarray/> 끝</hp:p>"
    )
    document = parse(hwpx(section(body)), parse_context)
    assert texts(document) == ["문단 직접 런 직접 본문 런 꼬리 문단 꼬리 끝"]


def test_pretty_printing_whitespace_between_elements_is_not_text(
    parse_context: ParseContext,
) -> None:
    body = (
        "\n  <hp:p>\n    <hp:run>\n      <hp:t>들여쓰기 무시</hp:t>\n    </hp:run>\n"
        "    <hp:linesegarray/>\n  </hp:p>\n"
    )
    document = parse(hwpx(section(body)), parse_context)
    assert texts(document) == ["들여쓰기 무시"]


def test_tails_of_text_and_inline_table_keep_text_table_text_order(
    parse_context: ParseContext,
) -> None:
    body = para(
        run(
            t("앞"),
            "T꼬리",
            table(grid([["셀"]])),
            "표꼬리",
            t("뒤<hp:tab/>탭꼬리<hp:lineBreak/>줄꼬리"),
        )
    )
    document = parse(hwpx(section(body)), parse_context)
    assert [block.type for block in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert texts(document)[0] == "앞T꼬리"
    assert texts(document)[2] == "표꼬리뒤\t탭꼬리\n줄꼬리"
    assert occurrences(document, "T꼬리") == 1
    assert occurrences(document, "표꼬리") == 1


def test_unsupported_controls_are_counted_and_never_flattened(
    parse_context: ParseContext,
) -> None:
    footnote = (
        "<hp:ctrl><hp:footNote><hp:subList>"
        + text_para("각주 비밀")
        + "</hp:subList></hp:footNote>컨트롤 내부 꼬리</hp:ctrl>"
    )
    body = para(
        run(
            t("본문 시작"),
            footnote,
            "컨트롤 꼬리",
            "<hp:pic><hp:t>그림 비밀</hp:t></hp:pic>",
            "그림 꼬리",
            "<hp:equation><hp:script>x over y 수식 비밀</hp:script></hp:equation>",
        )
    )
    document = parse(hwpx(section(body)), parse_context)
    assert texts(document) == ["본문 시작컨트롤 꼬리그림 꼬리"]
    wire = canonical_json(document)
    for hidden in ("각주 비밀", "컨트롤 내부 꼬리", "그림 비밀", "수식 비밀"):
        assert hidden not in wire
    profile = document.metadata["hwpx"]
    assert profile["unsupportedFeatures"] == {"equation": 1, "footNote": 1, "pic": 1}
    assert "hwpx_unsupported_content_omitted" in document.metadata["warnings"]
    assert "hwpx_unsupported_content_omitted" in document.blocks[0].quality_flags


def test_equation_script_is_inert_markup_not_an_active_script(
    parse_context: ParseContext,
) -> None:
    equation = "<hp:equation><hp:script>sum from i to n</hp:script></hp:equation>"
    document = parse(hwpx(section(text_para("식") + para(run(equation)))), parse_context)
    assert document.metadata["hwpx"]["unsupportedFeatures"] == {"equation": 1}
    assert "sum from" not in canonical_json(document)


def test_tracked_deletions_are_omitted_and_reported(parse_context: ParseContext) -> None:
    body = para(
        run(
            t('유지<hp:deleteBegin Id="1"/>삭제됨'),
            table(grid([["삭제된 표"]])),
            t('<hp:deleteEnd Id="1"/>남음<hp:insertBegin Id="2"/>추가<hp:insertEnd Id="2"/>'),
        )
    )
    document = parse(hwpx(section(body)), parse_context)
    assert texts(document) == ["유지남음추가"]
    assert "삭제된 표" not in canonical_json(document)
    profile = document.metadata["hwpx"]
    assert profile["deletedRevisionCharsOmitted"] == len("삭제됨")
    assert profile["trackedChangeMarkerCount"] == 4
    assert profile["unsupportedTables"] == {"deleted_revision": 1}
    assert "hwpx_tracked_changes_present" in document.metadata["warnings"]
    assert "hwpx_tracked_change_markers" in document.blocks[0].quality_flags


def cell_texts(block: CanonicalBlock) -> list[str]:
    assert block.table is not None
    return [c.raw_text or "" for c in block.table.cells]


def cell_flags(block: CanonicalBlock) -> list[tuple[str, ...]]:
    assert block.table is not None
    return [tuple(c.quality_flags) for c in block.table.cells]


def test_visible_table_before_a_later_deletion_keeps_its_cells(
    parse_context: ParseContext,
) -> None:
    # The deletion opens after the table, in the same paragraph, and closes in
    # the next one: it must not reach back into the table's cells.
    with_table = para(
        run(
            t("표 앞"),
            table(grid([["보임 하나", "보임 둘"]])),
            t('표 뒤<hp:deleteBegin Id="1"/>지움 하나'),
        )
    )
    closing = para(run(t('지움 둘<hp:deleteEnd Id="1"/>되살림')))
    document = parse(hwpx(section(with_table + closing)), parse_context)
    assert [block.type for block in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
    ]
    assert [anchor(block) for block in document.blocks] == [
        "hwpx/section/0000/p/000000/text/000",
        "hwpx/section/0000/p/000000/tbl/000",
        "hwpx/section/0000/p/000000/text/001",
        "hwpx/section/0000/p/000001/text/000",
    ]
    assert cell_texts(document.blocks[1]) == ["보임 하나", "보임 둘"]
    assert cell_flags(document.blocks[1]) == [(), ()]
    assert [texts(document)[index] for index in (0, 2, 3)] == ["표 앞", "표 뒤", "되살림"]
    assert occurrences(document, "보임 하나") == 1
    assert occurrences(document, "보임 둘") == 1
    assert occurrences(document, "지움") == 0
    profile = document.metadata["hwpx"]
    assert profile["deletedRevisionCharsOmitted"] == len("지움 하나") + len("지움 둘")
    assert profile["trackedChangeMarkerCount"] == 2
    assert profile["tableCount"] == 1
    assert profile["unsupportedTables"] == {}
    assert "hwpx_tracked_changes_present" in document.metadata["warnings"]
    assert "hwpx_tracked_change_markers" in document.blocks[2].quality_flags
    assert "hwpx_tracked_change_markers" in document.blocks[3].quality_flags


def test_deletion_spanning_ordinary_paragraphs_hides_only_what_lies_inside(
    parse_context: ParseContext,
) -> None:
    body = (
        text_para("처음")
        + para(run(t('살림<hp:deleteBegin Id="1"/>지움 가')))
        + text_para("지움 나")
        + para(run(t('지움 다<hp:deleteEnd Id="1"/>끝')))
        + text_para("마지막")
    )
    document = parse(hwpx(section(body)), parse_context)
    assert texts(document) == ["처음", "살림", "끝", "마지막"]
    assert [anchor(block) for block in document.blocks] == [
        "hwpx/section/0000/p/000000/text/000",
        "hwpx/section/0000/p/000001/text/000",
        "hwpx/section/0000/p/000003/text/000",
        "hwpx/section/0000/p/000004/text/000",
    ]
    assert occurrences(document, "지움") == 0
    profile = document.metadata["hwpx"]
    assert profile["paragraphCount"] == 5
    assert profile["trackedChangeMarkerCount"] == 2
    assert profile["deletedRevisionCharsOmitted"] == sum(
        len(text) for text in ("지움 가", "지움 나", "지움 다")
    )


def test_markers_inside_and_beside_table_cells_follow_source_order(
    parse_context: ParseContext,
) -> None:
    rows = [
        [
            cell("", 0, 0, inner=para(run(t('가<hp:deleteBegin Id="1"/>지운 가')))),
            cell("지운 나", 0, 1),
        ],
        [
            cell("", 1, 0, inner=para(run(t('지운 다<hp:deleteEnd Id="1"/>다')))),
            cell("라", 1, 1),
        ],
    ]
    body = para(
        run(
            t('<hp:insertBegin Id="2"/>삽입<hp:insertEnd Id="2"/>표 앞'),
            table(rows),
            t("표 뒤"),
        )
    )
    document = parse(hwpx(section(body)), parse_context)
    assert [block.type for block in document.blocks] == [
        BlockType.PARAGRAPH,
        BlockType.TABLE,
        BlockType.PARAGRAPH,
    ]
    assert texts(document)[0] == "삽입표 앞"
    assert texts(document)[2] == "표 뒤"
    assert cell_texts(document.blocks[1]) == ["가", "", "다", "라"]
    assert cell_flags(document.blocks[1]) == [
        ("hwpx_tracked_change_markers", "hwpx_tracked_deletion_omitted"),
        ("hwpx_tracked_deletion_omitted",),
        ("hwpx_tracked_change_markers", "hwpx_tracked_deletion_omitted"),
        (),
    ]
    assert occurrences(document, "지운") == 0
    assert "지운" not in canonical_json(document)
    profile = document.metadata["hwpx"]
    assert profile["trackedChangeMarkerCount"] == 4
    assert profile["deletedRevisionCharsOmitted"] == sum(
        len(text) for text in ("지운 가", "지운 나", "지운 다")
    )
    assert profile["unsupportedTables"] == {}


def test_later_delete_end_never_reveals_earlier_deleted_cells(
    parse_context: ParseContext,
) -> None:
    # A deletion opened inside the first cell hides the later cells; the
    # deleteEnd that follows the table closes it from there on only, and
    # nothing after it is hidden.
    opening_cell = cell("", 0, 0, inner=para(run(t('보이는<hp:deleteBegin Id="1"/>숨김0'))))
    later_cells = cell("숨김1", 0, 1) + cell("숨김2", 0, 2)
    table_xml = f"<hp:tbl><hp:tr>{opening_cell}{later_cells}</hp:tr></hp:tbl>"
    opened_in_cell = para(run(table_xml, t('<hp:deleteEnd Id="1"/>보임')))
    # A deletion opened in an earlier paragraph hides a whole table that sits
    # before its deleteEnd, even though the deleteEnd shares the table's paragraph.
    opening = para(run(t('앞<hp:deleteBegin Id="2"/>지움')))
    closing = para(run(table(grid([["숨은 셀"]])), t('<hp:deleteEnd Id="2"/>복귀')))
    body = opened_in_cell + text_para("다음") + opening + closing + text_para("끝")
    document = parse(hwpx(section(body)), parse_context)
    assert [block.type for block in document.blocks] == [
        BlockType.TABLE,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
        BlockType.PARAGRAPH,
    ]
    assert cell_texts(document.blocks[0]) == ["보이는", "", ""]
    assert texts(document)[1:] == ["보임", "다음", "앞", "복귀", "끝"]
    assert occurrences(document, "숨김") == 0
    assert occurrences(document, "숨은 셀") == 0
    wire = canonical_json(document)
    for hidden in ("숨김", "숨은 셀", "지움"):
        assert hidden not in wire
    profile = document.metadata["hwpx"]
    assert profile["tableCount"] == 1
    assert profile["unsupportedTables"] == {"deleted_revision": 1}
    assert profile["trackedChangeMarkerCount"] == 4
    assert profile["deletedRevisionCharsOmitted"] == sum(
        len(text) for text in ("숨김0", "숨김1", "숨김2", "지움")
    )


TABLE_LAYOUT_XML = '<hp:sz width="100" height="50"/><hp:pos treatAsChar="1"/><hp:outMargin/>'
CELL_LAYOUT_XML = '<hp:cellSz width="10" height="5"/><hp:cellMargin/>'


def with_cell_children(cell_xml: str, children: str) -> str:
    return cell_xml.replace("<hp:subList>", f"{children}<hp:subList>")


def test_captions_and_non_grid_children_are_counted_never_read(
    parse_context: ParseContext,
) -> None:
    caption = f"<hp:caption><hp:subList>{text_para('캡션 비밀')}</hp:subList></hp:caption>"
    picture = "<hp:pic><hp:t>셀 그림 비밀</hp:t></hp:pic>"
    row_extra = '<x:note xmlns:x="urn:example:row">행 비밀</x:note>'
    row = (
        cell("보이는 셀", 0, 0)
        + with_cell_children(cell("그림 옆 셀", 0, 1), CELL_LAYOUT_XML + picture)
        + row_extra
    )
    table_xml = f"<hp:tbl>{TABLE_LAYOUT_XML}<hp:inMargin/>{caption}<hp:tr>{row}</hp:tr></hp:tbl>"
    document = parse(hwpx(section(text_para("본문") + para(run(table_xml)))), parse_context)
    assert [block.type for block in document.blocks] == [BlockType.PARAGRAPH, BlockType.TABLE]
    table_block = document.blocks[1]
    assert cell_texts(table_block) == ["보이는 셀", "그림 옆 셀"]
    assert cell_flags(table_block) == [(), ("hwpx_unsupported_content_omitted",)]
    assert "hwpx_unsupported_content_omitted" in table_block.quality_flags
    wire = canonical_json(document)
    for hidden in ("캡션 비밀", "셀 그림 비밀", "행 비밀"):
        assert hidden not in wire
    profile = document.metadata["hwpx"]
    # One count per omitted element, by its own name; nothing inside is visited.
    assert profile["unsupportedFeatures"] == {"caption": 1, "other": 1, "pic": 1}
    # Two body paragraphs and two cell paragraphs; the caption's is never walked.
    assert profile["paragraphCount"] == 4
    assert profile["tableCount"] == 1
    assert "hwpx_unsupported_content_omitted" in document.metadata["warnings"]


def test_table_and_cell_layout_children_are_structural_not_omissions(
    parse_context: ParseContext,
) -> None:
    sized = with_cell_children(cell("크기만", 0, 0), CELL_LAYOUT_XML)
    table_xml = f"<hp:tbl>{TABLE_LAYOUT_XML}<hp:inMargin/><hp:tr>{sized}</hp:tr></hp:tbl>"
    document = parse(hwpx(section(para(run(table_xml)))), parse_context)
    table_block = document.blocks[0]
    assert cell_texts(table_block) == ["크기만"]
    assert cell_flags(table_block) == [()]
    assert tuple(table_block.quality_flags) == ()
    profile = document.metadata["hwpx"]
    assert profile["unsupportedFeatures"] == {}
    assert profile["tableCount"] == 1
    assert "hwpx_unsupported_content_omitted" not in document.metadata["warnings"]


@pytest.mark.parametrize(
    ("table_xml", "reason"),
    [
        (table([[cell("병합", 0, 0, span=(2, 1)), cell("옆", 0, 1)]]), "merged_cells"),
        (
            table([[cell("", 0, 0, inner=para(run(table(grid([["중첩 비밀"]])))))]]),
            "nested_table",
        ),
        (table([[cell("a", 0, 0)], [cell("b", 1, 0), cell("c", 1, 1)]]), "irregular_grid"),
        (table([[cell("주소", 3, 0)]]), "cell_address_mismatch"),
        (table(grid([["행 불일치"]]), row_count="3", col_count="1"), "dimension_mismatch"),
        (table(grid([["숫자 아님"]]), row_count="1x", col_count="1"), "dimension_mismatch"),
        ("<hp:tbl/>", "empty_table"),
    ],
)
def test_tables_outside_the_unit_span_profile_are_omitted_whole(
    parse_context: ParseContext,
    table_xml: str,
    reason: str,
) -> None:
    document = parse(hwpx(section(text_para("본문") + para(run(table_xml)))), parse_context)
    assert texts(document) == ["본문"]
    assert document.metadata["hwpx"]["unsupportedTables"] == {reason: 1}
    assert document.metadata["hwpx"]["tableCount"] == 0
    assert "hwpx_unsupported_content_omitted" in document.metadata["warnings"]
    wire = canonical_json(document)
    for hidden in ("병합", "중첩 비밀", "행 불일치", "숫자 아님", "주소"):
        assert hidden not in wire


@pytest.mark.parametrize(
    "body",
    [
        para(run("<hp:ctrl><hp:colPr/></hp:ctrl>")),
        para(run("<hp:pic><hp:t>그림 속 비밀</hp:t></hp:pic>")),
        para(run(t(""))),
        para(run(table(grid([["", ""]])))),
        "",
    ],
)
def test_empty_or_unsupported_only_documents_fail_with_a_body_free_code(
    parse_context: ParseContext,
    body: str,
) -> None:
    with pytest.raises(StructuredParseError) as failure:
        parse(hwpx(section(body)), parse_context)
    assert failure.value.code == "HWPX_EMPTY_DOCUMENT"
    assert str(failure.value) == "HWPX_EMPTY_DOCUMENT"


# --- package gate ----------------------------------------------------------------


def test_archive_corruption_fails_closed(parse_context: ParseContext) -> None:
    valid = hwpx(section(text_para("CRCMARK")), compression=zipfile.ZIP_STORED)
    assert rejection(valid[: len(valid) // 2], parse_context) == "HWPX_ARCHIVE_INVALID"
    corrupted = valid.replace(b"CRCMARK", b"CRCMARX", 1)
    assert corrupted != valid
    assert rejection(corrupted, parse_context) == "HWPX_ARCHIVE_CORRUPT"


def test_malformed_xml_fails_closed(parse_context: ParseContext) -> None:
    broken = f'<hs:sec xmlns:hs="{S2011}" xmlns:hp="{P2011}"><hp:p>'
    assert rejection(hwpx(broken), parse_context) == "HWPX_XML_MALFORMED"


@pytest.mark.parametrize(
    "part",
    [
        "Contents/section0.xml",
        "Contents/content.hpf",
        "Contents/header.xml",
        "Contents/unreferenced.xml",
        "META-INF/manifest.xml",
        "META-INF/container.rdf",
    ],
)
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16"])
def test_dtd_in_any_packaged_xml_part_is_rejected(
    parse_context: ParseContext,
    part: str,
    encoding: str,
) -> None:
    hostile = f'<?xml version="1.0" encoding="{encoding.upper()}"?>{DTD}<x>&e;</x>'
    parts = set_part(package_parts(section(text_para("본문"))), part, hostile.encode(encoding))
    assert rejection(zip_parts(parts), parse_context) == "HWPX_XML_UNSAFE"


@pytest.mark.parametrize(
    "href",
    [
        "../Contents/section0.xml",
        "/Contents/section0.xml",
        "http://example.test/section0.xml",
        "file:Contents/section0.xml",
        "Contents/section%30.xml",
        "Contents\\section0.xml",
        "Contents/./section0.xml",
        "Contents//section0.xml",
    ],
)
def test_unsafe_manifest_hrefs_are_rejected_before_lookup(
    parse_context: ParseContext,
    href: str,
) -> None:
    manifest = content_hpf([HEADER_ITEM, ("s", href, "application/xml")], ["header", "s"])
    parts = set_part(package_parts(section(text_para("본문"))), "Contents/content.hpf", manifest)
    assert rejection(zip_parts(parts), parse_context) == "HWPX_UNSAFE_HREF"


@pytest.mark.parametrize(
    ("part", "payload"),
    [
        # Header metadata the reader never reads.
        (
            "Contents/header.xml",
            f'<hh:head xmlns:hh="{H2011}"><hh:link href="../../outside.xml"/></hh:head>',
        ),
        # An omitted control inside a section that is read, via xlink:href.
        (
            "Contents/section0.xml",
            section(
                text_para("본문")
                + para(run(f'<hp:pic xmlns:xlink="{XLINK}" xlink:href="https://example.test/a"/>'))
            ),
        ),
        # Unreferenced metadata parts.
        ("META-INF/container.rdf", f'<m xmlns:xlink="{XLINK}"><r xlink:href="file:///C:/x"/></m>'),
        ("Contents/unreferenced.xml", '<x href="/Contents/section0.xml"/>'),
        ("Contents/unreferenced.xml", '<x href="Contents/../../x.xml"/>'),
        # Policy: fragment-only references are rejected conservatively.
        ("Contents/unreferenced.xml", '<x href="#bookmark"/>'),
    ],
)
def test_unsafe_hrefs_anywhere_in_packaged_xml_are_rejected(
    parse_context: ParseContext,
    part: str,
    payload: str,
) -> None:
    parts = set_part(package_parts(section(text_para("본문"))), part, payload.encode())
    assert rejection(zip_parts(parts), parse_context) == "HWPX_UNSAFE_HREF"


def test_local_package_hrefs_and_namespace_uris_are_accepted(parse_context: ParseContext) -> None:
    body = text_para("본문") + para(
        run(f'<hp:pic xmlns:xlink="{XLINK}" xlink:href="BinData/image1.png"/>')
    )
    parts = package_parts(section(body))
    parts["BinData/image1.png"] = b"\x89PNG\r\n\x1a\n"
    parts["META-INF/container.rdf"] = (
        f'<rdf:RDF xmlns:rdf="{RDF}"><rdf:Description href="Contents/section0.xml"/></rdf:RDF>'
    ).encode()
    assert texts(parse(zip_parts(parts), parse_context)) == ["본문"]


def test_package_root_must_be_exactly_contents_content_hpf(parse_context: ParseContext) -> None:
    root = ("Contents/content.hpf", "application/hwpml-package+xml")
    base = package_parts(section(text_para("본문")))

    moved = set_part(base, "Contents/content.hpf", None)
    moved["Contents/other.hpf"] = base["Contents/content.hpf"]
    moved["META-INF/container.xml"] = container(
        ("Contents/other.hpf", "application/hwpml-package+xml")
    )
    assert rejection(zip_parts(moved), parse_context) == "HWPX_CONTAINER_INVALID"

    twice = set_part(base, "META-INF/container.xml", container(root, root))
    assert rejection(zip_parts(twice), parse_context) == "HWPX_CONTAINER_INVALID"

    unsafe_secondary = set_part(
        base,
        "META-INF/container.xml",
        container(root, ("../Preview/PrvText.txt", "text/plain")),
    )
    assert rejection(zip_parts(unsafe_secondary), parse_context) == "HWPX_UNSAFE_HREF"

    with_preview = set_part(
        base,
        "META-INF/container.xml",
        container(root, ("Preview/PrvText.txt", "text/plain")),
    )
    with_preview["Preview/PrvText.txt"] = "미리보기".encode()
    assert texts(parse(zip_parts(with_preview), parse_context)) == ["본문"]


@pytest.mark.parametrize(
    ("items", "spine", "code"),
    [
        ([HEADER_ITEM, SECTION_ITEM], ["header", "section0", "section0"], "HWPX_SPINE_INVALID"),
        ([HEADER_ITEM, SECTION_ITEM], ["header", "missing"], "HWPX_SPINE_INVALID"),
        (
            [HEADER_ITEM, ("section0", "Contents/section0.xml", "image/png")],
            ["section0"],
            "HWPX_SPINE_INVALID",
        ),
        (
            [HEADER_ITEM, SECTION_ITEM, ("p", "Preview/PrvText.txt", "application/xml")],
            ["p"],
            "HWPX_SPINE_INVALID",
        ),
        (
            [HEADER_ITEM, SECTION_ITEM, ("again", "Contents/section0.xml", "application/xml")],
            ["section0"],
            "HWPX_MANIFEST_INVALID",
        ),
        (
            [HEADER_ITEM, SECTION_ITEM, ("case", "contents/SECTION0.xml", "application/xml")],
            ["section0"],
            "HWPX_MANIFEST_INVALID",
        ),
        (
            [HEADER_ITEM, ("section0", "Contents/section0.xml", "")],
            ["section0"],
            "HWPX_MANIFEST_INVALID",
        ),
        (
            [HEADER_ITEM, SECTION_ITEM, ("header", "Contents/x.xml", "application/xml")],
            ["section0"],
            "HWPX_MANIFEST_INVALID",
        ),
        ([HEADER_ITEM, SECTION_ITEM], [], "HWPX_SPINE_EMPTY"),
        (
            [HEADER_ITEM, ("gone", "Contents/gone.xml", "application/xml")],
            ["gone"],
            "HWPX_SPINE_TARGET_MISSING",
        ),
    ],
)
def test_manifest_and_spine_integrity_rules(
    parse_context: ParseContext,
    items: list[tuple[str, str, str]],
    spine: list[str],
    code: str,
) -> None:
    parts = set_part(
        package_parts(section(text_para("본문"))),
        "Contents/content.hpf",
        content_hpf(items, spine),
    )
    parts["Preview/PrvText.txt"] = b"preview"
    assert rejection(zip_parts(parts), parse_context) == code


def test_two_manifest_ids_naming_one_section_cannot_both_enter_the_spine(
    parse_context: ParseContext,
) -> None:
    # Two distinct, valid ids that name the same existing section, both listed in
    # the spine. The manifest refuses the second href before the spine is read,
    # so the section can never be emitted twice; the spine's own target check
    # stays behind it as a second fence.
    manifest = content_hpf(
        [HEADER_ITEM, SECTION_ITEM, ("alias", "Contents/section0.xml", "application/xml")],
        ["header", "section0", "alias"],
    )
    parts = set_part(package_parts(section(text_para("본문"))), "Contents/content.hpf", manifest)
    data = zip_parts(parts)
    assert rejection(data, parse_context) == "HWPX_MANIFEST_INVALID"
    with pytest.raises(HwpxPackageError) as failure:
        inspect_hwpx_package(data)
    assert failure.value.code == "hwpx_manifest_invalid"


@pytest.mark.parametrize(
    ("name", "payload", "code"),
    [
        ("mimetype", None, "HWPX_MIMETYPE_MISSING"),
        ("mimetype", b"application/zip", "HWPX_MIMETYPE_INVALID"),
        ("mimetype", HWPX_MIME.encode() + b"\n", "HWPX_MIMETYPE_INVALID"),
        ("META-INF/container.xml", None, "HWPX_CONTAINER_MISSING"),
        ("META-INF/container.xml", b"<other/>", "HWPX_CONTAINER_INVALID"),
        ("Contents/content.hpf", None, "HWPX_MANIFEST_MISSING"),
        ("Contents/content.hpf", b'<package xmlns="urn:wrong"/>', "HWPX_MANIFEST_INVALID"),
        ("[Content_Types].xml", b"<Types/>", "HWPX_PACKAGE_KIND_MISMATCH"),
    ],
)
def test_package_kind_mimetype_and_container_are_required(
    parse_context: ParseContext,
    name: str,
    payload: bytes | None,
    code: str,
) -> None:
    parts = set_part(package_parts(section(text_para("본문"))), name, payload)
    assert rejection(zip_parts(parts), parse_context) == code


def test_cfb_container_renamed_hwpx_is_not_parsed(parse_context: ParseContext) -> None:
    legacy = CFB_MAGIC + b"\x00" * 504
    assert rejection(legacy, parse_context) == "HWPX_CFB_CONTAINER_UNSUPPORTED"


def test_archive_member_hazards_are_rejected(parse_context: ParseContext) -> None:
    base = package_parts(section(text_para("본문")))
    for name, code in (
        ("../escape.xml", "HWPX_ARCHIVE_PATH_UNSAFE"),
        ("/abs.xml", "HWPX_ARCHIVE_PATH_UNSAFE"),
        ("contents/SECTION0.xml", "HWPX_ARCHIVE_DUPLICATE_ENTRY"),
    ):
        assert rejection(zip_parts(set_part(base, name, b"<x/>")), parse_context) == code

    linked = zip_parts(
        set_part(base, "BinData/link.png", b"/etc/passwd"), symlinks=("BinData/link.png",)
    )
    assert rejection(linked, parse_context) == "HWPX_ARCHIVE_SYMLINK"

    encrypted = flag_encrypted(zip_parts(base), "Contents/section0.xml")
    assert rejection(encrypted, parse_context) == "HWPX_ARCHIVE_ENCRYPTED_ENTRY"

    bzip = zip_parts(base, compression=zipfile.ZIP_BZIP2)
    assert rejection(bzip, parse_context) == "HWPX_ARCHIVE_COMPRESSION_UNSUPPORTED"


def test_encryption_metadata_is_rejected_without_the_zip_flag(
    parse_context: ParseContext,
) -> None:
    base = package_parts(section(text_para("본문")))
    odf_manifest = (
        f'<odf:manifest xmlns:odf="{ODF_MANIFEST}">'
        '<odf:file-entry odf:full-path="Contents/section0.xml" odf:media-type="application/xml">'
        "<odf:encryption-data/></odf:file-entry></odf:manifest>"
    ).encode()
    xmlenc = b'<e:EncryptedData xmlns:e="http://www.w3.org/2001/04/xmlenc#"/>'
    for name, payload in (
        ("META-INF/manifest.xml", odf_manifest),
        ("META-INF/encryption.xml", b"<encryption/>"),
        ("Contents/settings.xml", xmlenc),
    ):
        parts = set_part(base, name, payload)
        assert rejection(zip_parts(parts), parse_context) == "HWPX_ENCRYPTED_CONTENT", name

    plain_manifest = (
        f'<odf:manifest xmlns:odf="{ODF_MANIFEST}">'
        '<odf:file-entry odf:full-path="/" odf:media-type="application/hwp+zip"/>'
        "</odf:manifest>"
    ).encode()
    accepted = set_part(base, "META-INF/manifest.xml", plain_manifest)
    assert texts(parse(zip_parts(accepted), parse_context)) == ["본문"]


def test_embedded_ole_and_executables_are_rejected(parse_context: ParseContext) -> None:
    base = package_parts(section(text_para("본문")))
    xml_ole = section(text_para("본문") + para(run('<hp:ole binaryItemIDRef="b1"/>'))).encode()
    for name, payload, code in (
        ("Contents/section0.xml", xml_ole, "HWPX_EMBEDDED_OLE"),
        # An OLE control in a part the spine never names is still found.
        ("Contents/unreferenced.xml", xml_ole, "HWPX_EMBEDDED_OLE"),
        ("BinData/object.ole", b"opaque", "HWPX_EMBEDDED_OLE"),
        ("BinData/image1.bin", CFB_MAGIC + b"rest", "HWPX_EMBEDDED_OLE"),
        ("BinData/tool.exe", b"anything", "HWPX_EMBEDDED_EXECUTABLE"),
        ("BinData/image2.png", b"MZ\x90\x00", "HWPX_EMBEDDED_EXECUTABLE"),
    ):
        assert rejection(zip_parts(set_part(base, name, payload)), parse_context) == code, name


def test_script_policy_accepts_only_provably_empty_placeholders(
    parse_context: ParseContext,
) -> None:
    base = package_parts(section(text_para("본문")))
    placeholder = set_part(base, "Scripts/headerScripts", b"\xef\xbb\xbf  \r\n")
    document = parse(zip_parts(placeholder), parse_context)
    assert document.metadata["hwpx"]["emptyScriptPlaceholderCount"] == 1

    active = set_part(base, "Scripts/sourceScripts", b"function OnDocument_New() {}")
    assert rejection(zip_parts(active), parse_context) == "HWPX_ACTIVE_SCRIPT"

    declared = set_part(base, "Contents/macro.dat", b"alert(1)")
    declared["Contents/content.hpf"] = content_hpf(
        [HEADER_ITEM, SECTION_ITEM, ("macro", "Contents/macro.dat", "application/x-javascript")],
        ["header", "section0"],
    )
    assert rejection(zip_parts(declared), parse_context) == "HWPX_ACTIVE_SCRIPT"


# --- resource fences -------------------------------------------------------------


def _paragraphs(count: int) -> str:
    return "".join(text_para(f"문단{index}") for index in range(count))


def _ragged() -> str:
    return table([[cell("a", 0, 0)], [cell("b", 1, 0), cell("c", 1, 1), cell("d", 1, 2)]])


@pytest.mark.parametrize(
    ("limits", "data_factory", "code"),
    [
        (
            ParserLimits(max_archive_entries=3),
            lambda: hwpx(section(_paragraphs(1))),
            "HWPX_ARCHIVE_ENTRY_LIMIT",
        ),
        (
            ParserLimits(max_archive_member_bytes=64),
            lambda: hwpx(section(_paragraphs(1))),
            "HWPX_ARCHIVE_MEMBER_LIMIT",
        ),
        (
            ParserLimits(max_archive_uncompressed_bytes=200),
            lambda: hwpx(section(_paragraphs(1))),
            "HWPX_ARCHIVE_SIZE_LIMIT",
        ),
        (
            ParserLimits(max_compression_ratio=2.0),
            lambda: hwpx(section(text_para("가" * 3000))),
            "HWPX_ARCHIVE_RATIO_LIMIT",
        ),
        (
            ParserLimits(max_hwpx_xml_nodes=10),
            lambda: hwpx(section(_paragraphs(5))),
            "HWPX_XML_NODE_LIMIT",
        ),
        (
            ParserLimits(max_hwpx_xml_depth=4),
            lambda: table_doc(table(grid([["깊이"]]))),
            "HWPX_XML_DEPTH_LIMIT",
        ),
        (
            ParserLimits(max_hwpx_xml_bytes=2_000),
            lambda: hwpx(section(text_para("나" * 1_000)), compression=zipfile.ZIP_STORED),
            "HWPX_XML_TOO_LARGE",
        ),
        (
            # The spine holds the header and two sections: three items.
            ParserLimits(max_hwpx_sections=2),
            lambda: hwpx(section(_paragraphs(1)), section(_paragraphs(1))),
            "HWPX_SECTION_LIMIT",
        ),
        (
            ParserLimits(max_hwpx_paragraphs=2),
            lambda: hwpx(section(_paragraphs(3))),
            "HWPX_PARAGRAPH_LIMIT",
        ),
        (
            ParserLimits(max_hwpx_tables=1),
            lambda: table_doc(table(grid([["a"]])) + table(grid([["b"]]))),
            "HWPX_TABLE_LIMIT",
        ),
        (ParserLimits(max_blocks=2), lambda: hwpx(section(_paragraphs(3))), "BLOCK_LIMIT"),
        (
            ParserLimits(max_total_text_chars=40),
            lambda: hwpx(section(text_para("다" * 60))),
            "EXTRACTED_TEXT_LIMIT",
        ),
        (
            ParserLimits(max_total_text_chars=40),
            lambda: table_doc(table(grid([["라" * 60]]))),
            "EXTRACTED_TEXT_LIMIT",
        ),
        (
            ParserLimits(max_table_rows=1),
            lambda: table_doc(table(grid([["a"], ["b"]]))),
            "TABLE_ROW_LIMIT",
        ),
        (
            ParserLimits(max_table_columns=1),
            lambda: table_doc(table(grid([["a", "b"]]))),
            "TABLE_COLUMN_LIMIT",
        ),
        (
            ParserLimits(max_table_cells=3),
            lambda: table_doc(table(grid([["a", "b"], ["c", "d"]]))),
            "TABLE_CELL_LIMIT",
        ),
        # A ragged later row is fenced on its own width, not the first row's.
        (ParserLimits(max_table_columns=2), lambda: table_doc(_ragged()), "TABLE_COLUMN_LIMIT"),
        # Declared dimensions are fenced before any row is counted or allocated.
        (
            None,
            lambda: table_doc(table(grid([["a"]]), row_count="9" * 40)),
            "TABLE_ROW_LIMIT",
        ),
        (
            None,
            lambda: table_doc(table(grid([["a"]]), col_count="2000")),
            "TABLE_COLUMN_LIMIT",
        ),
        (
            None,
            lambda: table_doc(table(grid([["a"]]), row_count="600", col_count="1000")),
            "TABLE_CELL_LIMIT",
        ),
    ],
)
def test_resource_fences_fail_closed(
    parse_context: ParseContext,
    limits: ParserLimits | None,
    data_factory: Callable[[], bytes],
    code: str,
) -> None:
    assert rejection(data_factory(), parse_context, limits) == code


def test_configured_limits_never_widen_the_hwpx_ceilings(parse_context: ParseContext) -> None:
    parts = package_parts(section(text_para("본문")))
    parts["BinData/padding.bin"] = b"\x00" * 2_000_000
    widened = ParserLimits(max_compression_ratio=10_000.0)
    assert rejection(zip_parts(parts), parse_context, widened) == "HWPX_ARCHIVE_RATIO_LIMIT"


def test_shared_inspector_accepts_streams_and_fences_input_size() -> None:
    data = hwpx(section(text_para("본문")))
    package = inspect_hwpx_package(io.BytesIO(data))
    assert [item.part_name for item in package.spine] == [
        "Contents/header.xml",
        "Contents/section0.xml",
    ]
    for source, limits, code in (
        (data, HwpxLimits(max_input_bytes=100), "hwpx_input_too_large"),
        (b"not a zip at all", None, "hwpx_magic_mismatch"),
    ):
        with pytest.raises(HwpxPackageError) as failure:
            inspect_hwpx_package(source, limits)
        assert failure.value.code == code


# --- legacy API path -------------------------------------------------------------


def test_legacy_page_parser_never_reads_hwpx(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path)
    with pytest.raises(FileValidationError) as failure:
        parse_document("report.hwpx", hwpx(section(text_para("본문"))), settings)
    assert failure.value.code == "STRUCTURED_PARSER_REQUIRED"


def test_api_upload_validation_runs_the_shared_inspector(tmp_path: Path) -> None:
    settings = Settings(env="test", data_dir=tmp_path)
    valid = hwpx(section(text_para("본문")))
    digest = hashlib.sha256(valid).hexdigest()
    assert validate_file(
        filename="report.hwpx",
        declared_mime=HWPX_MIME,
        data=valid,
        expected_sha256=digest,
        settings=settings,
    ) == (".hwpx", digest)

    hostile = set_part(
        package_parts(section(text_para("본문"))),
        "Contents/unreferenced.xml",
        f"{DTD}<x/>".encode(),
    )
    outbound = set_part(
        package_parts(section(text_para("본문"))),
        "Contents/unreferenced.xml",
        f'<x xmlns:xlink="{XLINK}"><y xlink:href="https://example.test/"/></x>'.encode(),
    )
    for data, code in (
        (zip_parts(hostile), "HWPX_XML_UNSAFE"),
        (zip_parts(outbound), "HWPX_UNSAFE_HREF"),
        (CFB_MAGIC + b"\x00" * 504, "HWPX_CFB_CONTAINER_UNSUPPORTED"),
    ):
        with pytest.raises(FileValidationError) as failure:
            validate_file(
                filename="report.hwpx",
                declared_mime=HWPX_MIME,
                data=data,
                expected_sha256=hashlib.sha256(data).hexdigest(),
                settings=settings,
            )
        assert failure.value.code == code
