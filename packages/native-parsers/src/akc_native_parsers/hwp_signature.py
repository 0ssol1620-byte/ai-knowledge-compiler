"""Content-based HWP family detection. The file name and extension are never read.

Constants, from the HWP format documents (BLUE intake class, see
docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml; the spec documents' exact version/date and
usage notice are NOT yet recorded there and these constants have not been checked
against the published PDFs in this work order):

- HWP 3.x: file begins with the ASCII signature "HWP Document File V3.00" + 0x1A 01 02 03 04 05.
- HWP 5.x: OLE2/CFB container (D0 CF 11 E0 A1 B1 1A E1) with a "FileHeader" stream whose
  first 17 bytes spell "HWP Document File" (NUL padded to 32).
- HWPX (OWPML, KS X 6101): ZIP whose first-class `mimetype` member is "application/hwp+zip"
  and which carries `Contents/content.hpf` and `META-INF/container.xml`.
- HWPML: XML document whose root element is `HWPML`.

Any OLE file that is not HWP5 is held; it is never handed to another parser.
"""

from __future__ import annotations

import io
import zipfile

from defusedxml import ElementTree as SafeElementTree
from defusedxml.common import DefusedXmlException

from .hwp_contract import Held, HwpFormat
from .models import ParserLimits, StructuredParseError
from .security import _check_zip_members

HWP3_SIGNATURE = b"HWP Document File V3.00 \x1a\x01\x02\x03\x04\x05"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
HWP5_FILE_HEADER = b"HWP Document File"
HWPX_MIMETYPE = b"application/hwp+zip"
HWPX_REQUIRED_MEMBERS = frozenset({"mimetype", "contents/content.hpf", "meta-inf/container.xml"})
MAX_XML_DEPTH = 256

DetectedFormat = HwpFormat


def detect_hwp_format(data: bytes, limits: ParserLimits | None = None) -> DetectedFormat | Held:
    limits = limits or ParserLimits()
    if not data or len(data) > limits.max_input_bytes:
        return Held(reason_code="HWP_CONTAINER_LIMIT" if data else "HWP_SIGNATURE_MISMATCH")
    if data.startswith(HWP3_SIGNATURE):
        return "hwp3"
    if data.startswith(OLE_MAGIC):
        return _detect_ole(data)
    if data.startswith(b"PK\x03\x04"):
        return _detect_hwpx(data, limits)
    return _detect_hwpml(data)


def _detect_ole(data: bytes) -> DetectedFormat | Held:
    # ponytail: substring check of the directory entry name and the header stream text, not a
    # CFB walk; a crafted OLE can pass it, which only means "hold for the real reader", never
    # "accept". Upgrade to a bounded CFB directory walk when a real engine lands.
    if "FileHeader".encode("utf-16-le") in data and HWP5_FILE_HEADER in data:
        return "hwp5"
    return Held(reason_code="HWP_NOT_HWP_OLE")


def _detect_hwpx(data: bytes, limits: ParserLimits) -> DetectedFormat | Held:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile):
        return Held(reason_code="HWP_SIGNATURE_MISMATCH", detail="INVALID_ARCHIVE")
    with archive:
        try:
            names = _check_zip_members(archive, limits)
            if not names >= HWPX_REQUIRED_MEMBERS:
                return Held(reason_code="HWP_SIGNATURE_MISMATCH", detail="NOT_HWPX_PACKAGE")
            mimetype = next(i for i in archive.infolist() if i.filename.casefold() == "mimetype")
            if archive.read(mimetype).strip() != HWPX_MIMETYPE:
                return Held(reason_code="HWP_SIGNATURE_MISMATCH", detail="NOT_HWPX_PACKAGE")
            for entry in archive.infolist():
                if entry.filename.casefold().endswith((".xml", ".hpf")):
                    upper = archive.read(entry).upper()
                    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                        return Held(reason_code="HWP_XML_UNSAFE")
        except StructuredParseError as exc:
            return Held(reason_code="HWP_CONTAINER_LIMIT", detail=exc.code)
        except (OSError, zipfile.BadZipFile, EOFError, NotImplementedError):
            # truncated member data, bad CRC, unsupported compression
            return Held(reason_code="HWP_SIGNATURE_MISMATCH", detail="INVALID_ARCHIVE")
    return "hwpx"


def _detect_hwpml(data: bytes) -> DetectedFormat | Held:
    head = data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1]
    if head != b"<" and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return Held(reason_code="HWP_SIGNATURE_MISMATCH")
    depth = 0
    root: str | None = None
    try:
        for event, element in SafeElementTree.iterparse(
            io.BytesIO(data), events=("start", "end"), forbid_dtd=True, forbid_entities=True
        ):
            if event == "start":
                depth += 1
                if depth > MAX_XML_DEPTH:
                    return Held(reason_code="HWP_XML_UNSAFE", detail="XML_DEPTH_LIMIT")
                if root is None:
                    root = element.tag
                    if root != "HWPML":
                        return Held(reason_code="HWP_SIGNATURE_MISMATCH")
            else:
                depth -= 1
                element.clear()
    except DefusedXmlException:
        return Held(reason_code="HWP_XML_UNSAFE")
    except (SafeElementTree.ParseError, UnicodeError):
        return Held(reason_code="HWP_SIGNATURE_MISMATCH", detail="XML_MALFORMED")
    return "hwpml" if root == "HWPML" else Held(reason_code="HWP_SIGNATURE_MISMATCH")
