"""Public dispatch from untrusted bytes to validated canonical CIR."""

from __future__ import annotations

from akc_cir import CanonicalDocument

from .docx_parser import parse_docx
from .html_parser import parse_html
from .models import CirBuilder, ParseContext, ParserLimits, StructuredParseError
from .pptx_parser import parse_pptx
from .security import SUPPORTED_EXTENSIONS as _SUPPORTED_EXTENSIONS
from .security import validate_source
from .subtitle_parser import parse_subtitles
from .xlsx_parser import parse_xlsx

SUPPORTED_EXTENSIONS = frozenset(extension.removeprefix(".") for extension in _SUPPORTED_EXTENSIONS)


def parse_non_pdf_to_cir(
    *,
    filename: str,
    declared_mime: str,
    data: bytes,
    context: ParseContext,
    limits: ParserLimits | None = None,
) -> CanonicalDocument:
    """Validate and parse one native non-PDF source into immutable CIR.

    The function performs no network calls, subprocess execution, formula
    calculation, macro execution, or archive extraction.
    """

    effective_limits = limits or ParserLimits()
    validated = validate_source(
        filename=filename,
        declared_mime=declared_mime,
        data=data,
        limits=effective_limits,
    )
    document_type = validated.extension.removeprefix(".")
    if document_type == "htm":
        document_type = "html"
    builder = CirBuilder(
        context=context,
        source_filename=validated.normalized_filename,
        source_sha256=validated.source_sha256,
        document_type=document_type,
        limits=effective_limits,
    )
    builder.metadata["declaredMime"] = declared_mime.split(";", 1)[0].strip().casefold()

    try:
        if document_type == "docx":
            title = parse_docx(data, builder)
        elif document_type == "pptx":
            title = parse_pptx(data, builder)
        elif document_type == "xlsx":
            title = parse_xlsx(data, builder)
        elif document_type == "html":
            if validated.text is None:
                raise StructuredParseError("HTML_TEXT_UNAVAILABLE")
            title = parse_html(validated.text, builder)
        elif document_type in {"srt", "vtt"}:
            if validated.text is None:
                raise StructuredParseError("SUBTITLE_TEXT_UNAVAILABLE")
            title = parse_subtitles(
                validated.text,
                document_type=document_type,
                builder=builder,
            )
        else:  # pragma: no cover - validate_source owns this closed set.
            raise StructuredParseError("UNHANDLED_NON_PDF_TYPE")
        return builder.build(title=title)
    except StructuredParseError:
        raise
    except Exception as exc:
        raise StructuredParseError(f"{document_type.upper()}_PARSE_FAILED") from exc
