"""Bounded, extraction-free inspection of HWPX (OWPML) packages.

One inspector serves both the upload gate and the native parser, so the two
cannot drift apart on what a valid package is. Nothing is extracted to disk and
no reference is followed outside the archive: every href is validated as a
package-root-relative part name and only ever looked up in the in-memory member
table. Reading order comes from the ``Contents/content.hpf`` spine, never from
ZIP order or filename order. Every packaged XML part -- referenced or not -- is
parsed once under the same DTD, entity, node and depth fences.
"""

from __future__ import annotations

import io
import stat
import zipfile
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, BinaryIO

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

HWPX_MEDIA_TYPE = "application/hwp+zip"
_MIMETYPE_PAYLOAD = HWPX_MEDIA_TYPE.encode("ascii")
_PACKAGE_MANIFEST_MEDIA_TYPE = "application/hwpml-package+xml"
_CONTAINER_PART = "META-INF/container.xml"
# The OWPML package root is fixed; a container naming any other root is rejected.
HWPX_PACKAGE_ROOT = "Contents/content.hpf"
_OCF_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:container"
# Hancom writes the OPF namespace with a trailing slash; the IDPF spelling has none.
_OPF_NAMESPACES = frozenset({"http://www.idpf.org/2007/opf/", "http://www.idpf.org/2007/opf"})
_SPINE_MEDIA_TYPES = frozenset({"application/xml", "text/xml"})

# Official OWPML namespace families, matched by exact URI and never by prefix.
HWPX_PARAGRAPH_NAMESPACES = frozenset(
    {
        "http://www.hancom.co.kr/hwpml/2011/paragraph",
        "http://www.hancom.co.kr/hwpml/2016/paragraph",
        "http://www.owpml.org/owpml/2021/paragraph",
    }
)
HWPX_SECTION_NAMESPACES = frozenset(
    {
        "http://www.hancom.co.kr/hwpml/2011/section",
        "http://www.owpml.org/owpml/2021/section",
        "http://www.owpml.org/owpml/2024/section",
    }
)
HWPX_HEAD_NAMESPACES = frozenset({"http://www.hancom.co.kr/hwpml/2011/head"})

# Encryption metadata is rejected even when no ZIP entry carries the encryption
# flag: OCF ``META-INF/encryption.xml``, any XML-Encryption element, or an ODF
# manifest ``encryption-data`` entry.
_ENCRYPTION_PART = "meta-inf/encryption.xml"
_XMLENC_NAMESPACE = "http://www.w3.org/2001/04/xmlenc#"
_ODF_MANIFEST_NAMESPACE = "urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"

# Compound File Binary: legacy HWP, OLE objects, encrypted OOXML.
_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_EXECUTABLE_MAGIC = (
    b"MZ",
    b"\x7fELF",
    b"\xca\xfe\xba\xbe",
    b"\xcf\xfa\xed\xfe",
    b"\xce\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xfe\xed\xfa\xce",
    b"#!",
)
_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".bat",
        ".cmd",
        ".com",
        ".dll",
        ".exe",
        ".hta",
        ".jar",
        ".js",
        ".jse",
        ".msi",
        ".ps1",
        ".scr",
        ".sh",
        ".vbe",
        ".vbs",
        ".wsf",
    }
)
_XML_SUFFIXES = (".xml", ".hpf", ".rdf")
_SCRIPT_MEDIA_MARKERS = ("javascript", "ecmascript", "vbscript")
_BLANK_BYTES = b" \t\r\n\x00"
_BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
_HEAD_BYTES = 4096
_READ_CHUNK = 1024 * 1024


class HwpxPackageError(ValueError):
    """A stable, body-free rejection code for an HWPX package."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class HwpxLimits:
    max_input_bytes: int = 50 * 1024 * 1024
    max_entries: int = 2_000
    max_uncompressed_bytes: int = 250 * 1024 * 1024
    max_member_bytes: int = 64 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_xml_bytes: int = 64 * 1024 * 1024
    max_xml_nodes: int = 1_000_000
    max_xml_depth: int = 256
    max_sections: int = 1_000


@dataclass(frozen=True, slots=True)
class HwpxSpineItem:
    idref: str
    part_name: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class HwpxPackage:
    spine: tuple[HwpxSpineItem, ...]
    manifest_item_count: int
    binary_part_count: int
    empty_script_placeholder_count: int


def qualified_name(element: Any) -> tuple[str, str]:
    """Return ``(namespace URI, local name)``; prefixes are never consulted."""

    tag = element.tag
    if not isinstance(tag, str):
        return "", ""
    if tag.startswith("{"):
        namespace, _, local = tag[1:].partition("}")
        return namespace, local
    return "", tag


def parse_bounded_xml(
    payload: bytes,
    *,
    max_bytes: int,
    max_nodes: int,
    max_depth: int,
    on_start: Callable[[str, str], None] | None = None,
) -> Any:
    """Parse one XML part with DTDs, entities and external references forbidden.

    Node and depth budgets are checked on every start event, so a hostile part
    is abandoned within one parser chunk of crossing a budget instead of after
    the whole tree has been built. Encodings expat recognises from the BOM or
    declaration (UTF-8, UTF-16) go through the same DTD prohibition. ``on_start``
    sees every element's ``(namespace, local name)`` and may raise.
    """

    if len(payload) > max_bytes:
        raise HwpxPackageError("hwpx_xml_too_large")
    root: Any = None
    nodes = 0
    depth = 0
    try:
        for event, element in SafeElementTree.iterparse(
            io.BytesIO(payload),
            events=("start", "end"),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        ):
            if event == "end":
                depth -= 1
                continue
            nodes += 1
            depth += 1
            if nodes > max_nodes:
                raise HwpxPackageError("hwpx_xml_node_limit")
            if depth > max_depth:
                raise HwpxPackageError("hwpx_xml_depth_limit")
            if on_start is not None:
                on_start(*qualified_name(element))
            if root is None:
                root = element
    except DefusedXmlException as exc:
        raise HwpxPackageError("hwpx_xml_unsafe") from exc
    except SafeElementTree.ParseError as exc:
        raise HwpxPackageError("hwpx_xml_malformed") from exc
    if root is None:
        raise HwpxPackageError("hwpx_xml_malformed")
    return root


def inspect_hwpx_package(
    source: bytes | BinaryIO,
    limits: HwpxLimits | None = None,
) -> HwpxPackage:
    """Validate an HWPX package and return its spine-ordered XML parts."""

    effective = limits or HwpxLimits()
    stream: BinaryIO = io.BytesIO(source) if isinstance(source, bytes) else source
    size = stream.seek(0, io.SEEK_END)
    stream.seek(0)
    if size > effective.max_input_bytes:
        raise HwpxPackageError("hwpx_input_too_large")
    magic = stream.read(len(_CFB_MAGIC))
    stream.seek(0)
    if magic.startswith(_CFB_MAGIC):
        # Legacy binary HWP, or anything else in a compound file renamed .hwpx.
        raise HwpxPackageError("hwpx_cfb_container_unsupported")
    if not magic.startswith(b"PK\x03\x04"):
        raise HwpxPackageError("hwpx_magic_mismatch")
    try:
        archive = zipfile.ZipFile(stream)
    except (OSError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise HwpxPackageError("hwpx_archive_invalid") from exc
    with archive:
        members = _validated_members(archive, effective)
        xml_parts, heads = _read_members(archive, members, effective)
    return _assemble(members, xml_parts, heads, effective)


def _check_part_name(value: str, code: str) -> str:
    """Accept only a package-root-relative part name: no scheme, escape or traversal."""

    if (
        not value
        or len(value) > 1024
        or value.startswith("/")
        or any(character in value for character in "\\:%?#")
        or any(ord(character) < 0x20 or ord(character) == 0x7F for character in value)
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise HwpxPackageError(code)
    return value


def _validated_members(
    archive: zipfile.ZipFile,
    limits: HwpxLimits,
) -> dict[str, zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > limits.max_entries:
        raise HwpxPackageError("hwpx_archive_entry_limit")
    members: dict[str, zipfile.ZipInfo] = {}
    folded_names: set[str] = set()
    total_uncompressed = 0
    total_compressed = 0
    for entry in entries:
        name = entry.filename
        part_name = name.removesuffix("/") if entry.is_dir() else name
        _check_part_name(part_name, "hwpx_archive_path_unsafe")
        folded = name.casefold()
        if folded in folded_names:
            raise HwpxPackageError("hwpx_archive_duplicate_entry")
        folded_names.add(folded)
        if stat.S_ISLNK(entry.external_attr >> 16):
            raise HwpxPackageError("hwpx_archive_symlink")
        if entry.flag_bits & 0x1:
            raise HwpxPackageError("hwpx_archive_encrypted_entry")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise HwpxPackageError("hwpx_archive_compression_unsupported")
        if entry.file_size > limits.max_member_bytes:
            raise HwpxPackageError("hwpx_archive_member_limit")
        total_uncompressed += entry.file_size
        total_compressed += entry.compress_size
        if total_uncompressed > limits.max_uncompressed_bytes:
            raise HwpxPackageError("hwpx_archive_size_limit")
        if not entry.is_dir():
            members[name] = entry
    if total_uncompressed / max(total_compressed, 1) > limits.max_compression_ratio:
        raise HwpxPackageError("hwpx_archive_ratio_limit")
    return members


def _is_xml_part(name: str) -> bool:
    return name.casefold().endswith(_XML_SUFFIXES)


def _read_members(
    archive: zipfile.ZipFile,
    members: dict[str, zipfile.ZipInfo],
    limits: HwpxLimits,
) -> tuple[dict[str, bytes], dict[str, bytes]]:
    """Read every member to its end so each CRC-32 is verified.

    XML parts are kept whole, after their declared size is fenced and before a
    single byte is buffered; every other member keeps only its first bytes,
    enough to recognise an executable, an OLE container or a non-empty script.
    """

    xml_parts: dict[str, bytes] = {}
    heads: dict[str, bytes] = {}
    for name, entry in members.items():
        keep_whole = _is_xml_part(name)
        if keep_whole and entry.file_size > limits.max_xml_bytes:
            raise HwpxPackageError("hwpx_xml_too_large")
        chunks: list[bytes] = []
        kept = 0
        head = b""
        try:
            with archive.open(entry, "r") as member:
                while chunk := member.read(_READ_CHUNK):
                    if keep_whole:
                        kept += len(chunk)
                        if kept > limits.max_xml_bytes:
                            raise HwpxPackageError("hwpx_xml_too_large")
                        chunks.append(chunk)
                    elif len(head) < _HEAD_BYTES:
                        head += chunk[: _HEAD_BYTES - len(head)]
        except HwpxPackageError:
            raise
        except (
            EOFError,
            NotImplementedError,
            OSError,
            RuntimeError,
            ValueError,
            zipfile.BadZipFile,
            zlib.error,
        ) as exc:
            raise HwpxPackageError("hwpx_archive_corrupt") from exc
        if keep_whole:
            payload = b"".join(chunks)
            xml_parts[name] = payload
            head = payload[:_HEAD_BYTES]
        heads[name] = head
    return xml_parts, heads


def _proven_empty(entry: zipfile.ZipInfo, head: bytes) -> bool:
    if entry.file_size > _HEAD_BYTES:
        return False
    content = head
    for bom in _BOMS:
        content = content.removeprefix(bom)
    return not content.strip(_BLANK_BYTES)


def _reject_active_markup(namespace: str, local: str) -> None:
    if namespace == _XMLENC_NAMESPACE or (
        namespace == _ODF_MANIFEST_NAMESPACE and local == "encryption-data"
    ):
        raise HwpxPackageError("hwpx_encrypted_content")
    if namespace in HWPX_PARAGRAPH_NAMESPACES and local == "ole":
        raise HwpxPackageError("hwpx_embedded_ole")


def _reject_unsafe_hrefs(root: Any) -> None:
    """Hold every ``href`` attribute to the package part-name rules.

    Any attribute whose local name is ``href`` -- unqualified, ``xlink:href`` or
    in any other namespace -- on any element of any parsed part, referenced or
    not, must be a package-root-relative part name. Links are never resolved or
    followed; this only refuses values that could point outside the archive
    (scheme, absolute path, traversal). Namespace declarations are not
    attributes of the parsed tree, so a namespace URI is never checked. Policy:
    fragment-only references (``#name``) are rejected as well -- the reader
    resolves no in-document link, so admitting a fragment grammar buys nothing.
    """

    for element in root.iter():
        for key, value in element.attrib.items():
            if str(key).rpartition("}")[2] == "href":
                _check_part_name(str(value), "hwpx_unsafe_href")


def _assemble(
    members: dict[str, zipfile.ZipInfo],
    xml_parts: dict[str, bytes],
    heads: dict[str, bytes],
    limits: HwpxLimits,
) -> HwpxPackage:
    if any(name.casefold() == "[content_types].xml" for name in members):
        # An OOXML package renamed .hwpx.
        raise HwpxPackageError("hwpx_package_kind_mismatch")
    if "mimetype" not in members:
        raise HwpxPackageError("hwpx_mimetype_missing")
    if (
        members["mimetype"].file_size != len(_MIMETYPE_PAYLOAD)
        or heads["mimetype"] != _MIMETYPE_PAYLOAD
    ):
        raise HwpxPackageError("hwpx_mimetype_invalid")
    if any(name.casefold() == _ENCRYPTION_PART for name in members):
        raise HwpxPackageError("hwpx_encrypted_content")

    empty_scripts = 0
    for name, entry in members.items():
        folded = name.casefold()
        suffix = PurePosixPath(folded).suffix
        head = heads[name]
        if folded.startswith("scripts/"):
            # Policy: a script part is accepted only as an inert placeholder that
            # is provably empty (whitespace and a BOM at most). Anything else is
            # treated as active content; scripts are never parsed or executed.
            if not _proven_empty(entry, head):
                raise HwpxPackageError("hwpx_active_script")
            empty_scripts += 1
            continue
        if suffix == ".ole" or head.startswith(_CFB_MAGIC):
            raise HwpxPackageError("hwpx_embedded_ole")
        if suffix in _EXECUTABLE_SUFFIXES or head.lstrip(b"\xef\xbb\xbf\t\r\n ").startswith(
            _EXECUTABLE_MAGIC
        ):
            raise HwpxPackageError("hwpx_embedded_executable")

    # Every packaged XML part is parsed under the fences, referenced or not, so
    # an unreferenced header or META-INF part cannot smuggle a DTD, encryption
    # metadata or an OLE control past the gate.
    roots: dict[str, Any] = {}
    for name, payload in xml_parts.items():
        if name.casefold().startswith("scripts/"):
            continue  # Already proven empty; never parsed.
        root = parse_bounded_xml(
            payload,
            max_bytes=limits.max_xml_bytes,
            max_nodes=limits.max_xml_nodes,
            max_depth=limits.max_xml_depth,
            on_start=_reject_active_markup,
        )
        _reject_unsafe_hrefs(root)
        if name in {_CONTAINER_PART, HWPX_PACKAGE_ROOT}:
            roots[name] = root

    if _CONTAINER_PART not in members:
        raise HwpxPackageError("hwpx_container_missing")
    if _CONTAINER_PART not in roots:
        raise HwpxPackageError("hwpx_container_invalid")
    _check_container(roots[_CONTAINER_PART])
    if HWPX_PACKAGE_ROOT not in members:
        raise HwpxPackageError("hwpx_manifest_missing")
    items, spine_refs = _read_manifest(roots[HWPX_PACKAGE_ROOT], limits)

    for href, media_type in items.values():
        if any(marker in media_type.casefold() for marker in _SCRIPT_MEDIA_MARKERS) and (
            href in members and not _proven_empty(members[href], heads[href])
        ):
            raise HwpxPackageError("hwpx_active_script")

    if not spine_refs:
        raise HwpxPackageError("hwpx_spine_empty")
    # Every spine reference and target is validated before any part is used.
    if len(set(spine_refs)) != len(spine_refs) or any(ref not in items for ref in spine_refs):
        raise HwpxPackageError("hwpx_spine_invalid")
    targets: set[str] = set()
    for ref in spine_refs:
        href, media_type = items[ref]
        if href in targets or media_type.strip().casefold() not in _SPINE_MEDIA_TYPES:
            raise HwpxPackageError("hwpx_spine_invalid")
        targets.add(href)
        if href not in members:
            raise HwpxPackageError("hwpx_spine_target_missing")
        if href not in xml_parts or href == HWPX_PACKAGE_ROOT:
            raise HwpxPackageError("hwpx_spine_invalid")

    return HwpxPackage(
        spine=tuple(
            HwpxSpineItem(idref=ref, part_name=items[ref][0], payload=xml_parts[items[ref][0]])
            for ref in spine_refs
        ),
        manifest_item_count=len(items),
        binary_part_count=sum(1 for name in members if name.casefold().startswith("bindata/")),
        empty_script_placeholder_count=empty_scripts,
    )


def _check_container(root: Any) -> None:
    if qualified_name(root) != (_OCF_NAMESPACE, "container"):
        raise HwpxPackageError("hwpx_container_invalid")
    package_paths: list[str] = []
    for element in root.iter():
        if qualified_name(element) != (_OCF_NAMESPACE, "rootfile"):
            continue
        # Every rootfile href is validated, including ones that are never read.
        full_path = _check_part_name(str(element.attrib.get("full-path", "")), "hwpx_unsafe_href")
        media_type = str(element.attrib.get("media-type", "")).strip().casefold()
        if media_type == _PACKAGE_MANIFEST_MEDIA_TYPE:
            package_paths.append(full_path)
    if package_paths != [HWPX_PACKAGE_ROOT]:
        raise HwpxPackageError("hwpx_container_invalid")


def _read_manifest(
    root: Any,
    limits: HwpxLimits,
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    namespace, local = qualified_name(root)
    if namespace not in _OPF_NAMESPACES or local != "package":
        raise HwpxPackageError("hwpx_manifest_invalid")
    items: dict[str, tuple[str, str]] = {}
    folded_hrefs: set[str] = set()
    spine_refs: list[str] = []
    manifests = 0
    spines = 0
    for child in root:
        child_namespace, child_local = qualified_name(child)
        if child_namespace not in _OPF_NAMESPACES:
            continue
        if child_local == "manifest":
            manifests += 1
            for item in child:
                item_namespace, item_local = qualified_name(item)
                if item_namespace not in _OPF_NAMESPACES or item_local != "item":
                    continue
                item_id = str(item.attrib.get("id", ""))
                if not item_id or item_id in items:
                    raise HwpxPackageError("hwpx_manifest_invalid")
                href = _check_part_name(str(item.attrib.get("href", "")), "hwpx_unsafe_href")
                media_type = str(item.attrib.get("media-type", "")).strip()
                if not media_type or href.casefold() in folded_hrefs:
                    raise HwpxPackageError("hwpx_manifest_invalid")
                folded_hrefs.add(href.casefold())
                items[item_id] = (href, media_type)
        elif child_local == "spine":
            spines += 1
            for reference in child:
                reference_namespace, reference_local = qualified_name(reference)
                if reference_namespace not in _OPF_NAMESPACES or reference_local != "itemref":
                    continue
                spine_refs.append(str(reference.attrib.get("idref", "")))
                if len(spine_refs) > limits.max_sections:
                    raise HwpxPackageError("hwpx_section_limit")
    if manifests != 1 or spines != 1:
        raise HwpxPackageError("hwpx_manifest_invalid")
    return items, spine_refs
