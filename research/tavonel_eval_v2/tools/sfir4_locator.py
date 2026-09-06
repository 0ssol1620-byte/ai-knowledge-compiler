"""SFIR4's own immutable payload-locator grammar.

``sfir4_worker.resolve_payload_locator`` delegated to ``sfir1_worker``. That is
the reimplementing-beside class inverted: SFIR4 called a dependency that knows
LESS than SFIR4's own frozen candidate contract, so SFIR4's contract was never
the thing being enforced. The SFIR1 resolver checks the shape of a locator; it
does not check that the locator names an immutable target, and several distinct
locators resolve through it to the same URL.

Seven concrete holes it leaves open, each of which has a negative control in
``tests/test_sfir4_locator.py``:

1. ``github://o/r/blob/<anything>/p`` -- the revision is never checked to be a
   40-hex commit sha, so a mutable ref (``main``) resolves and the "immutable
   target" property of the whole family is lost.
2. ``github://o/r/blob/<sha>/../../etc`` -- path segments are not checked, and
   ``urllib.parse.quote`` leaves ``..`` alone because ``.`` is an unreserved
   character. The traversal survives into the resolved URL.
3. ``github://o/r/blob/<sha>//p`` -- an empty segment passes the ``if not
   document`` test because the list is non-empty, and produces ``//`` in the URL.
4. ``github://user:pw@o/r/blob/<sha>/p`` -- the netloc is used as the owner with
   no check, so credentials ride along inside the resolved URL.
5. ``github://o/r/blob/<sha>/a%2Fb`` -- percent-encoding is never decoded and
   never refused, so ``a%2Fb`` and ``a/b`` are two locators for one document,
   and re-quoting turns ``%`` into ``%25``.
6. ``ecfr://title/5/part/1/section/X`` -- the section is validated to be present
   and then **discarded**, so the resolved URL is not an identifier of the
   candidate. The request legitimately stays part-scoped (see :func:`resolve`),
   but nothing downstream could tell two sections of one part apart from the
   resolution alone. :func:`resolution_identity` is the repair.
7. ``mediawiki://en.wikipedia.org/page/٠١٢/revision/9`` -- ``str.isdigit()`` is
   true for Arabic-Indic digits and ``int()`` parses them, so a non-ASCII
   locator resolves; ``007`` and ``7`` likewise both resolve to page 7.

The grammar here is deliberately narrow. It accepts ASCII only, refuses percent
encoding outright rather than trying to canonicalise it, refuses any component
the frozen candidate contract does not name, and requires every identifier to be
in canonical form so that the locator -> URL map is injective. Injectivity is not
asserted in a docstring; ``test_distinct_locators_never_resolve_to_one_url``
executes the map over a matrix of near-identical locators and compares the
images.

Refusing rather than normalising is the deliberate choice. A resolver that
repairs ``007`` into ``7`` accepts two names for one thing and has to be trusted
to repair them identically forever; a resolver that refuses ``007`` makes the
frozen roster carry exactly one name per thing, which is a property the roster
freeze can check once.
"""

from __future__ import annotations

import datetime as _datetime
import re
import urllib.parse
from dataclasses import dataclass
from typing import Final

#: The families this grammar covers, in the frozen protocol's order.
FAMILIES: Final[tuple[str, ...]] = (
    "git_docs",
    "regulation_ecfr",
    "encyclopedia_wikipedia",
)

SCHEMES: Final[dict[str, str]] = {
    "git_docs": "github",
    "regulation_ecfr": "ecfr",
    "encyclopedia_wikipedia": "mediawiki",
}

NETLOCS: Final[dict[str, str | None]] = {
    "git_docs": None,  # the netloc is the repository owner
    "regulation_ecfr": "title",
    "encyclopedia_wikipedia": "en.wikipedia.org",
}

#: A GitHub owner or repository name.  Anchored, ASCII, no dot-only names.
_GH_NAME = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")
#: A full commit sha.  Lowercase only: the roster carries one spelling per commit.
_GIT_SHA = re.compile(r"\A[0-9a-f]{40}\Z")
#: A canonical positive integer -- no leading zero, no sign, no separators.
_POSITIVE = re.compile(r"\A[1-9][0-9]{0,11}\Z")
#: An eCFR part designator, e.g. ``1``, ``50``, ``1926``, ``4A``.
_ECFR_PART = re.compile(r"\A[1-9][0-9]{0,3}[A-Z]?\Z")
#: An eCFR section designator, e.g. ``1.1``, ``1926.1101``, ``50.204-1``.
_ECFR_SECTION = re.compile(r"\A[0-9]+\.[0-9]+(?:-[0-9]+)?[a-z]?\Z")
#: An ISO calendar date.  Membership is necessary but not sufficient; the value
#: is also parsed, so ``2026-02-30`` is refused.
_ISO_DATE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")

#: Segments that must never appear in a document path.
_TRAVERSAL: Final[frozenset[str]] = frozenset({"", ".", ".."})

MAX_LOCATOR_LENGTH: Final[int] = 512
MAX_PATH_SEGMENTS: Final[int] = 32
MAX_SEGMENT_LENGTH: Final[int] = 128


class LocatorRefused(ValueError):
    """The locator is not in SFIR4's frozen grammar.

    Raised for every rejection. There is no partial acceptance and no repaired
    value: a locator either names exactly one immutable target or it names
    nothing this instrument will read.
    """


@dataclass(frozen=True, slots=True)
class Locator:
    """The parsed, validated components of one immutable locator."""

    family: str
    #: The verbatim locator, which is also its canonical spelling.
    text: str
    #: Family-specific components, all ASCII and all canonical.
    parts: tuple[tuple[str, str], ...]

    def component(self, name: str) -> str:
        for key, value in self.parts:
            if key == name:
                return value
        raise KeyError(name)


def _refuse(reason: str) -> LocatorRefused:
    return LocatorRefused(f"SFIR4 locator refused: {reason}")


def _check_universal(family: str, locator: str) -> urllib.parse.ParseResult:
    """Checks that hold for every family, before any family-specific shape."""
    if family not in FAMILIES:
        raise _refuse(f"unknown family {family!r}")
    if not isinstance(locator, str) or not locator:
        raise _refuse("locator is not a non-empty string")
    if len(locator) > MAX_LOCATOR_LENGTH:
        raise _refuse("locator exceeds the frozen length bound")
    if not locator.isascii():
        raise _refuse("locator contains non-ASCII characters")
    if any(char.isspace() or ord(char) < 0x20 or ord(char) == 0x7F for char in locator):
        raise _refuse("locator contains whitespace or control characters")
    if "%" in locator:
        # Refused rather than decoded. Decoding introduces a second spelling for
        # every separator, and this grammar has no character that needs escaping.
        raise _refuse("locator contains percent-encoding, which is ambiguous here")
    if "\\" in locator:
        raise _refuse("locator contains a backslash")

    parsed = urllib.parse.urlparse(locator)
    if parsed.scheme != SCHEMES[family]:
        raise _refuse(f"scheme is {parsed.scheme!r}, not {SCHEMES[family]!r}")
    if parsed.fragment:
        raise _refuse("locator carries a fragment")
    if parsed.params:
        raise _refuse("locator carries path parameters")
    if "@" in parsed.netloc or ":" in parsed.netloc:
        raise _refuse("locator netloc carries credentials or a port")
    expected_netloc = NETLOCS[family]
    if expected_netloc is not None and parsed.netloc != expected_netloc:
        raise _refuse(f"netloc is {parsed.netloc!r}, not {expected_netloc!r}")
    if not parsed.netloc:
        raise _refuse("locator has an empty netloc")
    if urllib.parse.urlunparse(parsed) != locator:
        raise _refuse("locator is not in canonical form")
    return parsed


def _segments(parsed: urllib.parse.ParseResult) -> list[str]:
    """Path segments with NO stripping, so an empty segment stays observable."""
    path = parsed.path
    if not path.startswith("/"):
        raise _refuse("locator path is not absolute")
    return path[1:].split("/")


def _check_document_segments(segments: list[str]) -> None:
    if not segments:
        raise _refuse("document path is empty")
    if len(segments) > MAX_PATH_SEGMENTS:
        raise _refuse("document path exceeds the frozen segment bound")
    for segment in segments:
        if segment in _TRAVERSAL:
            raise _refuse(f"document path segment {segment!r} is empty or traversal")
        if len(segment) > MAX_SEGMENT_LENGTH:
            raise _refuse("document path segment exceeds the frozen length bound")
        if any(char in segment for char in "?#[]"):
            raise _refuse("document path segment carries a reserved character")


def _parse_git(parsed: urllib.parse.ParseResult, locator: str) -> Locator:
    if parsed.query:
        raise _refuse("github locator carries a query string")
    owner = parsed.netloc
    if not _GH_NAME.match(owner) or owner in {".", ".."}:
        raise _refuse("github owner is not a well-formed name")
    segments = _segments(parsed)
    if len(segments) < 4:
        raise _refuse("github locator is missing repository, blob, revision or path")
    repository, blob, revision = segments[0], segments[1], segments[2]
    document = segments[3:]
    if not _GH_NAME.match(repository) or repository in {".", ".."}:
        raise _refuse("github repository is not a well-formed name")
    if blob != "blob":
        raise _refuse(f"github locator has {blob!r} where 'blob' is required")
    if not _GIT_SHA.match(revision):
        raise _refuse("github revision is not a lowercase 40-hex commit sha")
    _check_document_segments(document)
    return Locator(
        family="git_docs",
        text=locator,
        parts=(
            ("owner", owner),
            ("repository", repository),
            ("revision", revision),
            ("path", "/".join(document)),
        ),
    )


def _parse_ecfr(parsed: urllib.parse.ParseResult, locator: str) -> Locator:
    segments = _segments(parsed)
    if len(segments) != 5 or segments[1] != "part" or segments[3] != "section":
        raise _refuse("ecfr locator is not title/<id>/part/<part>/section/<section>")
    title, part, section = segments[0], segments[2], segments[4]
    if not _POSITIVE.match(title) or int(title) > 50:
        raise _refuse("ecfr title is not a canonical CFR title number")
    if not _ECFR_PART.match(part):
        raise _refuse("ecfr part is not a canonical part designator")
    if not _ECFR_SECTION.match(section):
        raise _refuse("ecfr section is not a canonical section designator")
    if not section.startswith(f"{part}."):
        # A section number is prefixed by its part. Without this, a locator can
        # name part 1 and section 1926.1101, and the two components disagree
        # about which document is meant.
        raise _refuse("ecfr section is not inside the part the locator names")

    query = urllib.parse.parse_qs(parsed.query, strict_parsing=True, keep_blank_values=True)
    if set(query) != {"version"}:
        raise _refuse("ecfr locator query is not exactly one 'version'")
    if len(query["version"]) != 1:
        raise _refuse("ecfr locator repeats the version parameter")
    version = query["version"][0]
    if not _ISO_DATE.match(version):
        raise _refuse("ecfr version is not an ISO YYYY-MM-DD date")
    try:
        _datetime.date.fromisoformat(version)
    except ValueError as error:
        raise _refuse("ecfr version is not a real calendar date") from error
    return Locator(
        family="regulation_ecfr",
        text=locator,
        parts=(
            ("title", title),
            ("part", part),
            ("section", section),
            ("version", version),
        ),
    )


def _parse_wikipedia(parsed: urllib.parse.ParseResult, locator: str) -> Locator:
    if parsed.query:
        raise _refuse("mediawiki locator carries a query string")
    segments = _segments(parsed)
    if len(segments) != 4 or segments[0] != "page" or segments[2] != "revision":
        raise _refuse("mediawiki locator is not page/<id>/revision/<id>")
    page_id, revision_id = segments[1], segments[3]
    if not _POSITIVE.match(page_id):
        raise _refuse("mediawiki page id is not a canonical positive integer")
    if not _POSITIVE.match(revision_id):
        raise _refuse("mediawiki revision id is not a canonical positive integer")
    return Locator(
        family="encyclopedia_wikipedia",
        text=locator,
        parts=(("page_id", page_id), ("revision_id", revision_id)),
    )


def parse(family: str, locator: str) -> Locator:
    """Validate one locator against SFIR4's grammar and return its components."""
    parsed = _check_universal(family, locator)
    if family == "git_docs":
        return _parse_git(parsed, locator)
    if family == "regulation_ecfr":
        return _parse_ecfr(parsed, locator)
    return _parse_wikipedia(parsed, locator)


def resolve(family: str, locator: str) -> str:
    """Resolve one locator to the immutable URL its authority serves.

    For ``git_docs`` and ``encyclopedia_wikipedia`` this URL alone identifies the
    payload, and the map is injective.

    For ``regulation_ecfr`` it deliberately is **not**. The eCFR versioner serves
    a whole part, and every section of that part shares one request URL; the
    section is isolated locally afterwards by ``sfir1_worker._stream_ecfr_section``.
    Forcing ``section`` into the query would make this function injective on its
    own, but it would also change what the live API is asked for, and an
    unverified change to a live API contract immediately before a frozen census
    is the failure mode that ended SFIR1, SFIR2 and SFIR3. The request stays as
    it was; injectivity is recovered by :func:`resolution_identity`, which is
    what a candidate must be bound to.
    """
    parts = parse(family, locator)
    if family == "git_docs":
        document = parts.component("path")
        return (
            "https://raw.githubusercontent.com/"
            f"{parts.component('owner')}/{parts.component('repository')}/"
            f"{parts.component('revision')}/{document}"
        )
    if family == "regulation_ecfr":
        query = urllib.parse.urlencode({"part": parts.component("part")})
        return (
            "https://www.ecfr.gov/api/versioner/v1/full/"
            f"{parts.component('version')}/title-{parts.component('title')}.xml?{query}"
        )
    return "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
        {
            "action": "parse",
            "pageid": parts.component("page_id"),
            "oldid": parts.component("revision_id"),
            "prop": "text",
            "format": "json",
            "formatversion": 2,
        }
    )


def selector(family: str, locator: str) -> str | None:
    """The post-fetch selection a family applies to a shared response.

    ``None`` means the response IS the payload. A non-None selector means the
    request URL is shared with other candidates and the payload is the part of
    the response this names -- so the URL alone must never be treated as the
    candidate's identity.
    """
    parts = parse(family, locator)
    if family == "regulation_ecfr":
        return parts.component("section")
    return None


def resolution_identity(family: str, locator: str) -> str:
    """The injective identity of what one locator actually reads.

    This is the value a candidate is bound to and the value a roster proves
    distinct. It is the request URL when the response is the payload, and the
    request URL plus the local selector when it is not.
    """
    url = resolve(family, locator)
    chosen = selector(family, locator)
    return url if chosen is None else f"{url}#select={chosen}"


def grammar() -> dict[str, str]:
    """The grammar as a receipt-recordable statement, one line per family."""
    return {
        "git_docs": "github://<owner>/<repo>/blob/<40 lowercase hex>/<path>",
        "regulation_ecfr": (
            "ecfr://title/<title>/part/<part>/section/<part>.<n>?version=<YYYY-MM-DD>"
        ),
        "encyclopedia_wikipedia": (
            "mediawiki://en.wikipedia.org/page/<positive id>/revision/<positive id>"
        ),
    }
