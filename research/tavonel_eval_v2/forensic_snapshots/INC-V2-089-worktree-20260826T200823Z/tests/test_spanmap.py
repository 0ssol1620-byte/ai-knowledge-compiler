"""The provenance spine. Every other provenance claim rests on these properties.

SFI1's 1,284 failures came from searching canonical text back inside raw bytes.
The replacement records provenance as it emits, so the interesting tests are not
"does it find the text" — nothing searches any more — but the three ways a
built-by-construction map can still lie:

* it can claim a span it cannot back up. `verify` exists to refuse that.
* it can attribute inserted text to a neighbour's bytes. `to_source` returning
  None is the whole defence, and None must never be quietly upgraded.
* it can look complete while covering only part of its output. `is_fully_sourced`
  is a different question from `to_source` being non-None, and conflating them
  would let a half-invented unit claim provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

NS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(NS / "source_fact_ir"))

import spanmap as sm  # noqa: E402

RAW = b"# Title\n\nHello &amp; welcome   here\n"
#      0123456789...


def tracked() -> sm.TrackedText:
    """The fixture, written the way a canonicaliser would write it.

    `Hello ` copied, `&amp;` replaced by `&`, ` welcome` copied, the three-space
    run replaced by one space, `here` copied.
    """
    text = sm.TrackedText()
    text.copy("Hello", 9, 14)
    text.copy(" ", 14, 15)
    text.replace("&", 15, 20)
    text.copy(" welcome", 20, 28)
    text.replace(" ", 28, 31)
    text.copy("here", 31, 35)
    return text


# ---------------------------------------------------------------------------
# segments refuse what they cannot mean


def test_an_inserted_run_may_not_carry_a_source():
    """Giving a separator a source attributes text the source never contained."""
    with pytest.raises(ValueError, match="no source"):
        sm.Segment(out_start=0, out_end=1, source_start=5, source_end=6, kind=sm.INSERT)


def test_a_backwards_span_is_refused():
    with pytest.raises(ValueError, match="not a span"):
        sm.Segment(out_start=0, out_end=4, source_start=9, source_end=2, kind=sm.COPY)


def test_overlapping_output_is_refused():
    """Two sources for one character means one is wrong and nothing says which."""
    with pytest.raises(ValueError, match="overlap"):
        sm.SpanMap(
            [
                sm.Segment(out_start=0, out_end=5, source_start=0, source_end=5, kind=sm.COPY),
                sm.Segment(out_start=3, out_end=8, source_start=9, source_end=14, kind=sm.COPY),
            ]
        )


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown segment kind"):
        sm.Segment(out_start=0, out_end=1, source_start=0, source_end=1, kind="guessed")


# ---------------------------------------------------------------------------
# the map answers in raw bytes


def test_the_whole_text_maps_to_the_bytes_it_came_from():
    text = tracked()
    assert text.text == "Hello & welcome here"
    assert text.source_span() == (9, 35)


def test_a_word_maps_to_its_own_bytes_and_not_a_neighbour_s():
    text = tracked()
    start = text.text.index("welcome")
    span = text.span_of(start, start + len("welcome"))
    assert span is not None
    assert RAW[span[0] : span[1]] == b" welcome"


def test_a_decoded_entity_maps_to_the_entity_not_the_word_beside_it():
    """The case a searching implementation gets wrong every time: `&` does not
    appear in the source at all, so there is nothing to find."""
    text = tracked()
    at = text.text.index("&")
    span = text.span_of(at, at + 1)
    assert span == (15, 20)
    assert RAW[span[0] : span[1]] == b"&amp;"


def test_a_collapsed_whitespace_run_maps_to_the_whole_run():
    text = tracked()
    at = text.text.index("welcome") + len("welcome")
    span = text.span_of(at, at + 1)
    assert span == (28, 31)
    assert RAW[span[0] : span[1]] == b"   "


def test_an_empty_range_has_no_source():
    assert tracked().span_of(4, 4) is None


# ---------------------------------------------------------------------------
# inserted text, and the refusal that protects everything


def test_inserted_text_alone_maps_to_nothing():
    """An honest None is a fact the study can count. A confident wrong answer is
    a mis-attribution nothing downstream can detect."""
    text = sm.TrackedText()
    text.copy("first", 0, 5)
    separator = text.mark()
    text.insert(" ")
    text.copy("second", 10, 16)
    assert text.span_of(separator, separator + 1) is None


def test_a_range_straddling_an_insert_reports_the_sourced_part_only():
    text = sm.TrackedText()
    text.copy("first", 0, 5)
    text.insert(" ")
    text.copy("second", 10, 16)
    #: deliberate: the span is the minimal enclosure of what DID have a source.
    #: It is not a claim that the separator came from those bytes.
    assert text.span_of(0, len(text)) == (0, 16)


def test_unsourced_runs_are_reportable():
    text = sm.TrackedText()
    text.copy("a", 0, 1)
    text.insert("|")
    text.copy("b", 5, 6)
    assert text.map.unsourced_runs() == ((1, 2),)


def test_full_sourcing_is_a_different_question_from_having_a_span():
    """A half-invented unit still has a source span. Calling that its provenance
    would overstate what is known about it."""
    text = sm.TrackedText()
    text.copy("a", 0, 1)
    text.insert("|")
    text.copy("b", 5, 6)
    assert text.map.to_source(0, len(text)) is not None
    assert text.map.is_fully_sourced(0, len(text)) is False
    assert text.map.is_fully_sourced(0, 1) is True


def test_a_gap_in_coverage_is_not_fully_sourced():
    """Output no segment accounts for is output nothing claims to have made."""
    gapped = sm.SpanMap(
        [
            sm.Segment(out_start=0, out_end=2, source_start=0, source_end=2, kind=sm.COPY),
            sm.Segment(out_start=4, out_end=6, source_start=4, source_end=6, kind=sm.COPY),
        ]
    )
    assert gapped.is_fully_sourced(0, 6) is False


# ---------------------------------------------------------------------------
# composition, for staged pipelines


def test_composition_answers_in_raw_bytes_not_in_the_middle_stage():
    """After composing, no intermediate offset may survive into the answer."""
    first = sm.TrackedText()          # raw -> middle
    first.replace("&", 15, 20)
    first.copy(" welcome", 20, 28)

    second = sm.TrackedText()         # middle -> final
    second.copy("&", 0, 1)
    second.replace("_", 1, 9)

    composed = first.map.compose(second.map)
    assert composed.to_source(0, 1) == (15, 20)
    assert composed.to_source(1, 2) == (20, 28)


def test_composition_keeps_inserted_text_unsourced():
    first = sm.TrackedText()
    first.copy("ab", 0, 2)
    second = sm.TrackedText()
    second.copy("a", 0, 1)
    second.insert("!")
    composed = first.map.compose(second.map)
    assert composed.to_source(1, 2) is None


# ---------------------------------------------------------------------------
# verification: a map is only worth having if something can refuse it


def test_verify_accepts_an_honest_map():
    text = tracked()
    report = sm.verify(text.map, RAW, text.text)
    assert report["ok"] is True
    assert report["fully_covered"] is True
    assert report["problems"] == []


def test_verify_catches_a_copy_segment_whose_bytes_do_not_match():
    """The exact failure a searching implementation produced silently."""
    lying = sm.SpanMap(
        [sm.Segment(out_start=0, out_end=5, source_start=0, source_end=5, kind=sm.COPY)]
    )
    report = sm.verify(lying, RAW, "Hello")
    assert report["ok"] is False
    assert any("do not decode" in problem["why"] for problem in report["problems"])


def test_verify_catches_a_span_past_the_end_of_the_payload():
    overrun = sm.SpanMap(
        [sm.Segment(out_start=0, out_end=4, source_start=900, source_end=904, kind=sm.COPY)]
    )
    report = sm.verify(overrun, RAW, "here")
    assert report["ok"] is False
    assert any("outside the payload" in problem["why"] for problem in report["problems"])


def test_verify_does_not_hold_replace_segments_to_byte_equality():
    """A replaced run's output differs from its input by definition. Checking it
    for equality would make correct normalisation unverifiable."""
    text = sm.TrackedText()
    text.replace("&", 15, 20)
    assert sm.verify(text.map, RAW, text.text)["ok"] is True


def test_verify_notices_output_nothing_accounts_for():
    text = sm.TrackedText()
    text.copy("Hello", 9, 14)
    report = sm.verify(text.map, RAW, "Hello there")
    assert report["fully_covered"] is False
    assert report["ok"] is False


# ---------------------------------------------------------------------------
# multi-byte, where a char/byte confusion shows


def test_multibyte_sources_map_by_bytes_not_by_characters():
    raw = "안녕 world".encode()
    text = sm.TrackedText()
    text.copy("안녕", 0, 6)
    text.copy(" world", 6, 12)
    span = text.span_of(0, 2)
    assert span == (0, 6)
    assert raw[span[0] : span[1]].decode("utf-8") == "안녕"
    assert sm.verify(text.map, raw, text.text)["ok"] is True


def test_the_api_has_no_way_to_emit_text_from_a_source_it_did_not_read():
    """`insert` is the only unsourced path, and it must be explicit.

    A `write(text)` convenience would let a canonicaliser add an untraceable
    character by accident, which is the whole class of defect being removed.
    """
    assert not hasattr(sm.TrackedText, "write")
    assert not hasattr(sm.TrackedText, "append")
    assert {"copy", "replace", "insert"} <= set(dir(sm.TrackedText))
