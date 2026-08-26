"""Negative controls for SFIR4's own payload-locator grammar.

Every test named ``test_refuses_*`` is a red control. Seven of them are also
checked against the inherited ``sfir1_worker`` resolver by
``test_the_inherited_resolver_accepted_what_this_grammar_refuses``, so this file
records what actually changed rather than asserting a property the previous code
already had.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
for extra in (NS, NS / "tools"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))

import sfir4_locator as loc  # noqa: E402

SHA = "a" * 40

VALID = {
    "git_docs": f"github://octo/docs/blob/{SHA}/reference/api.md",
    "regulation_ecfr": "ecfr://title/29/part/1926/section/1926.1101?version=2026-01-15",
    "encyclopedia_wikipedia": "mediawiki://en.wikipedia.org/page/1234/revision/9876",
}

#: Locators the inherited resolver accepts and this grammar must not. The value
#: is the reason, quoted into the assertion message when a control goes green.
INHERITED_HOLES: dict[str, str] = {
    "github://octo/docs/blob/main/reference/api.md": "mutable ref, not a commit sha",
    f"github://octo/docs/blob/{SHA}/../../etc/passwd": "path traversal",
    f"github://octo/docs/blob/{SHA}//api.md": "empty path segment",
    f"github://user:pw@octo/docs/blob/{SHA}/api.md": "credentials in the netloc",
    f"github://octo/docs/blob/{SHA}/a%2Fb.md": "percent-encoded separator",
    "mediawiki://en.wikipedia.org/page/007/revision/9876": "non-canonical page id",
    "mediawiki://en.wikipedia.org/page/٠١٢/revision/9876": "non-ASCII digits",
}


# ---------------------------------------------------------------------------
# What the grammar accepts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_the_declared_valid_locator_of_every_family_parses(family: str) -> None:
    parsed = loc.parse(family, VALID[family])
    assert parsed.family == family
    assert parsed.text == VALID[family]


def test_git_components_are_recovered_exactly() -> None:
    parsed = loc.parse("git_docs", VALID["git_docs"])
    assert parsed.component("owner") == "octo"
    assert parsed.component("repository") == "docs"
    assert parsed.component("revision") == SHA
    assert parsed.component("path") == "reference/api.md"


def test_ecfr_components_are_recovered_exactly() -> None:
    parsed = loc.parse("regulation_ecfr", VALID["regulation_ecfr"])
    assert parsed.component("title") == "29"
    assert parsed.component("part") == "1926"
    assert parsed.component("section") == "1926.1101"
    assert parsed.component("version") == "2026-01-15"


def test_wikipedia_components_are_recovered_exactly() -> None:
    parsed = loc.parse("encyclopedia_wikipedia", VALID["encyclopedia_wikipedia"])
    assert parsed.component("page_id") == "1234"
    assert parsed.component("revision_id") == "9876"


# ---------------------------------------------------------------------------
# Universal refusals
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_percent_encoding_in_every_family(family: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="percent-encoding"):
        loc.parse(family, VALID[family].replace("/", "%2F", 1))


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_a_fragment_in_every_family(family: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="fragment"):
        loc.parse(family, VALID[family] + "#section-2")


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_non_ascii_in_every_family(family: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="non-ASCII"):
        loc.parse(family, VALID[family] + "é")


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_control_characters_and_whitespace(family: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="whitespace or control"):
        loc.parse(family, VALID[family] + "\n")


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_the_wrong_scheme(family: str) -> None:
    wrong = "https" + VALID[family][VALID[family].index(":") :]
    with pytest.raises(loc.LocatorRefused, match="scheme is"):
        loc.parse(family, wrong)


@pytest.mark.parametrize("family", loc.FAMILIES)
def test_refuses_a_locator_from_another_family(family: str) -> None:
    other = next(name for name in loc.FAMILIES if name != family)
    with pytest.raises(loc.LocatorRefused):
        loc.parse(family, VALID[other])


def test_refuses_an_unknown_family() -> None:
    with pytest.raises(loc.LocatorRefused, match="unknown family"):
        loc.parse("not_a_family", VALID["git_docs"])


@pytest.mark.parametrize("bad", ["", None, 17, b"github://a/b"])
def test_refuses_a_locator_that_is_not_a_non_empty_string(bad: object) -> None:
    with pytest.raises(loc.LocatorRefused, match="non-empty string"):
        loc.parse("git_docs", bad)  # type: ignore[arg-type]


def test_refuses_a_locator_longer_than_the_frozen_bound() -> None:
    long_path = "x" * (loc.MAX_LOCATOR_LENGTH + 1)
    with pytest.raises(loc.LocatorRefused, match="length bound"):
        loc.parse("git_docs", f"github://octo/docs/blob/{SHA}/{long_path}")


# ---------------------------------------------------------------------------
# git_docs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "revision",
    ["main", "HEAD", "a" * 39, "a" * 41, "A" * 40, "g" * 40, "refs/heads/main"],
)
def test_refuses_a_git_revision_that_is_not_a_lowercase_40_hex_sha(revision: str) -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse("git_docs", f"github://octo/docs/blob/{revision}/api.md")


@pytest.mark.parametrize("segment", ["..", ".", ""])
def test_refuses_traversal_and_empty_document_segments(segment: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="empty or traversal"):
        loc.parse("git_docs", f"github://octo/docs/blob/{SHA}/docs/{segment}/api.md")


def test_refuses_a_git_netloc_carrying_credentials() -> None:
    with pytest.raises(loc.LocatorRefused, match="credentials or a port"):
        loc.parse("git_docs", f"github://user:pw@octo/docs/blob/{SHA}/api.md")


def test_refuses_a_git_locator_with_a_query_string() -> None:
    with pytest.raises(loc.LocatorRefused, match="query string"):
        loc.parse("git_docs", f"github://octo/docs/blob/{SHA}/api.md?ref=main")


def test_refuses_a_git_locator_with_no_document_path() -> None:
    with pytest.raises(loc.LocatorRefused, match="missing repository"):
        loc.parse("git_docs", f"github://octo/docs/blob/{SHA}")


def test_refuses_a_git_locator_without_the_blob_keyword() -> None:
    with pytest.raises(loc.LocatorRefused, match="where 'blob' is required"):
        loc.parse("git_docs", f"github://octo/docs/tree/{SHA}/api.md")


@pytest.mark.parametrize("name", ["-bad", ".", "..", "a" * 101, "own er"])
def test_refuses_a_malformed_git_owner(name: str) -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse("git_docs", f"github://{name}/docs/blob/{SHA}/api.md")


def test_refuses_a_document_path_deeper_than_the_frozen_bound() -> None:
    deep = "/".join(["d"] * (loc.MAX_PATH_SEGMENTS + 1))
    with pytest.raises(loc.LocatorRefused, match="segment bound"):
        loc.parse("git_docs", f"github://octo/docs/blob/{SHA}/{deep}")


# ---------------------------------------------------------------------------
# regulation_ecfr
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("title", ["0", "029", "51", "-1", "1x"])
def test_refuses_a_non_canonical_or_out_of_range_ecfr_title(title: str) -> None:
    with pytest.raises(loc.LocatorRefused, match="canonical CFR title"):
        loc.parse(
            "regulation_ecfr",
            f"ecfr://title/{title}/part/1926/section/1926.1101?version=2026-01-15",
        )


def test_refuses_an_ecfr_section_outside_the_part_the_locator_names() -> None:
    with pytest.raises(loc.LocatorRefused, match="inside the part"):
        loc.parse(
            "regulation_ecfr",
            "ecfr://title/29/part/1910/section/1926.1101?version=2026-01-15",
        )


@pytest.mark.parametrize("version", ["2026-13-01", "2026-02-30", "20260115", "2026-1-5", ""])
def test_refuses_an_ecfr_version_that_is_not_a_real_iso_date(version: str) -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse(
            "regulation_ecfr",
            f"ecfr://title/29/part/1926/section/1926.1101?version={version}",
        )


def test_refuses_an_ecfr_locator_with_an_extra_query_parameter() -> None:
    with pytest.raises(loc.LocatorRefused, match="exactly one 'version'"):
        loc.parse(
            "regulation_ecfr",
            "ecfr://title/29/part/1926/section/1926.1101?version=2026-01-15&raw=1",
        )


def test_refuses_an_ecfr_locator_that_repeats_the_version_parameter() -> None:
    with pytest.raises(loc.LocatorRefused, match="repeats the version"):
        loc.parse(
            "regulation_ecfr",
            "ecfr://title/29/part/1926/section/1926.1101?version=2026-01-15&version=2026-02-15",
        )


def test_refuses_an_ecfr_locator_with_no_version_at_all() -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse("regulation_ecfr", "ecfr://title/29/part/1926/section/1926.1101")


def test_refuses_an_ecfr_locator_with_the_wrong_path_keywords() -> None:
    with pytest.raises(loc.LocatorRefused, match="is not title/"):
        loc.parse(
            "regulation_ecfr",
            "ecfr://title/29/chapter/1926/section/1926.1101?version=2026-01-15",
        )


# ---------------------------------------------------------------------------
# encyclopedia_wikipedia
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page_id", ["0", "007", "-1", "1.0", "٠١٢", ""])
def test_refuses_a_non_canonical_wikipedia_page_id(page_id: str) -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse(
            "encyclopedia_wikipedia",
            f"mediawiki://en.wikipedia.org/page/{page_id}/revision/9876",
        )


@pytest.mark.parametrize("revision_id", ["0", "007", "-1", "abc"])
def test_refuses_a_non_canonical_wikipedia_revision_id(revision_id: str) -> None:
    with pytest.raises(loc.LocatorRefused):
        loc.parse(
            "encyclopedia_wikipedia",
            f"mediawiki://en.wikipedia.org/page/1234/revision/{revision_id}",
        )


def test_refuses_a_wikipedia_locator_on_the_wrong_host() -> None:
    with pytest.raises(loc.LocatorRefused, match="netloc is"):
        loc.parse(
            "encyclopedia_wikipedia",
            "mediawiki://de.wikipedia.org/page/1234/revision/9876",
        )


def test_refuses_a_wikipedia_locator_with_a_query_string() -> None:
    with pytest.raises(loc.LocatorRefused, match="query string"):
        loc.parse(
            "encyclopedia_wikipedia",
            "mediawiki://en.wikipedia.org/page/1234/revision/9876?action=raw",
        )


# ---------------------------------------------------------------------------
# Resolution: injective, and every validated component survives into the URL
# ---------------------------------------------------------------------------


def test_the_ecfr_request_stays_part_scoped() -> None:
    """The request is deliberately unchanged; see ``resolve``'s docstring."""
    url = loc.resolve("regulation_ecfr", VALID["regulation_ecfr"])
    assert "part=1926" in url
    assert "section=" not in url
    assert "2026-01-15" in url
    assert "title-29.xml" in url


def test_ecfr_declares_a_selector_and_the_other_families_do_not() -> None:
    assert loc.selector("regulation_ecfr", VALID["regulation_ecfr"]) == "1926.1101"
    assert loc.selector("git_docs", VALID["git_docs"]) is None
    assert loc.selector("encyclopedia_wikipedia", VALID["encyclopedia_wikipedia"]) is None


def test_two_sections_of_one_part_share_a_url_but_not_an_identity() -> None:
    """The exact collision the inherited resolver left unobservable."""
    one = "ecfr://title/29/part/1926/section/1926.1101?version=2026-01-15"
    two = "ecfr://title/29/part/1926/section/1926.1102?version=2026-01-15"
    assert loc.resolve("regulation_ecfr", one) == loc.resolve("regulation_ecfr", two)
    assert loc.resolution_identity("regulation_ecfr", one) != loc.resolution_identity(
        "regulation_ecfr", two
    )


def test_distinct_locators_never_share_a_resolution_identity() -> None:
    """Injectivity, executed rather than asserted.

    The matrix varies one component at a time, including the eCFR section, which
    the inherited resolver validated and then dropped.
    """
    matrix = [
        ("git_docs", f"github://octo/docs/blob/{SHA}/a.md"),
        ("git_docs", f"github://octo/docs/blob/{SHA}/b.md"),
        ("git_docs", f"github://octo/docs/blob/{'b' * 40}/a.md"),
        ("git_docs", f"github://octo/other/blob/{SHA}/a.md"),
        ("git_docs", f"github://other/docs/blob/{SHA}/a.md"),
        ("git_docs", f"github://octo/docs/blob/{SHA}/sub/a.md"),
        ("regulation_ecfr", "ecfr://title/29/part/1926/section/1926.1101?version=2026-01-15"),
        ("regulation_ecfr", "ecfr://title/29/part/1926/section/1926.1102?version=2026-01-15"),
        ("regulation_ecfr", "ecfr://title/29/part/1926/section/1926.1101?version=2026-02-15"),
        ("regulation_ecfr", "ecfr://title/21/part/1926/section/1926.1101?version=2026-01-15"),
        ("encyclopedia_wikipedia", "mediawiki://en.wikipedia.org/page/1234/revision/9876"),
        ("encyclopedia_wikipedia", "mediawiki://en.wikipedia.org/page/1234/revision/9877"),
        ("encyclopedia_wikipedia", "mediawiki://en.wikipedia.org/page/1235/revision/9876"),
    ]
    assert len({text for _, text in matrix}) == len(matrix), "the matrix repeats a locator"
    identities = [loc.resolution_identity(family, text) for family, text in matrix]
    assert len(set(identities)) == len(identities), (
        "two distinct locators share one resolution identity"
    )


def test_the_url_alone_is_injective_wherever_there_is_no_selector() -> None:
    """Where the response is the payload, the URL is allowed to be the identity."""
    matrix = [
        ("git_docs", f"github://octo/docs/blob/{SHA}/a.md"),
        ("git_docs", f"github://octo/docs/blob/{SHA}/sub/a.md"),
        ("git_docs", f"github://octo/docs/blob/{'b' * 40}/a.md"),
        ("encyclopedia_wikipedia", "mediawiki://en.wikipedia.org/page/1234/revision/9876"),
        ("encyclopedia_wikipedia", "mediawiki://en.wikipedia.org/page/1235/revision/9876"),
    ]
    for family, text in matrix:
        assert loc.selector(family, text) is None
    urls = [loc.resolve(family, text) for family, text in matrix]
    assert len(set(urls)) == len(urls)


def test_resolution_refuses_everything_parsing_refuses() -> None:
    for text in INHERITED_HOLES:
        family = "git_docs" if text.startswith("github://") else "encyclopedia_wikipedia"
        with pytest.raises(loc.LocatorRefused):
            loc.resolve(family, text)


def test_no_resolved_url_ever_contains_a_traversal_or_credential() -> None:
    for family, text in VALID.items():
        url = loc.resolve(family, text)
        assert "/../" not in url
        assert "@" not in url
        assert "//" not in url.removeprefix("https://")


# ---------------------------------------------------------------------------
# The comparison against what was inherited
# ---------------------------------------------------------------------------


def test_the_inherited_resolver_accepted_what_this_grammar_refuses() -> None:
    """The finding itself, executed.

    If a future change to ``sfir1_worker`` closes one of these holes, this test
    fails and the docstring above it has to be corrected -- which is the point.
    A control written against a moment expires; this one reports when it has.
    """
    sfir1 = pytest.importorskip("sfir1_worker")
    still_open: list[str] = []
    for text, reason in INHERITED_HOLES.items():
        family = "git_docs" if text.startswith("github://") else "encyclopedia_wikipedia"
        try:
            sfir1.resolve_payload_locator(family, text)
        except Exception:  # noqa: S112 - any refusal means the hole is closed
            continue
        still_open.append(f"{reason}: {text}")
        with pytest.raises(loc.LocatorRefused):
            loc.resolve(family, text)

    assert still_open, (
        "every hole this grammar was written against is now closed in "
        "sfir1_worker; INHERITED_HOLES and the module docstring are stale"
    )
