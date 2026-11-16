"""WO-D07-10: every pattern applied to subtitle cue text is linear on hostile input."""

from __future__ import annotations

import itertools
import re
import time
from datetime import UTC, datetime

import pytest
from akc_native_parsers import ParseContext, parse_non_pdf_to_cir
from akc_native_parsers import subtitle_parser as sp

# The pre-fix patterns, kept verbatim as the byte-identity oracle (small inputs only).
_OLD_VTT_SPEAKER = re.compile(r"^<v(?:\.[^ >]+)*\s+([^>]+)>(.*)$", re.DOTALL)
_OLD_TAG = re.compile(r"<[^>]+>")
_BUDGET_S = 2.0
_N = 20_000  # ParserLimits.max_cue_chars default


def _old_speaker_and_text(raw: str) -> tuple[str | None, str]:
    match = _OLD_VTT_SPEAKER.match(raw)
    if match:
        return sp.normalize_text(match.group(1)), match.group(2)
    plain = _OLD_TAG.sub("", raw)
    text_match = sp._TEXT_SPEAKER.match(plain)
    if text_match:
        return sp.normalize_text(text_match.group(1)), text_match.group(2)
    return None, raw


HOSTILE = {
    "dots": "<v" + "." * _N,
    "dots_then_char": "<v" + "." * (_N - 3) + "5",
    "dot_runs": "<v" + ".a" * (_N // 2),
    "tabs_after_dot": "<v." + "\t" * _N,
    "spaces": "<v" + " " * _N,
    "no_gt_after_name": "<v.a " + "x" * _N,
    "lt_flood": "<" * _N,
    "lt_a_flood": "<a" * (_N // 2),
    "gt_lt_flood": "<>" * (_N // 2),
    "v_tag_flood": "<v x" * (_N // 4),
    "colon_ws": "a:" + " " * _N,
    "ws_before_colon": " " * _N + ":",
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_cue_text_patterns_are_linear_on_hostile_input(name: str) -> None:
    text = HOSTILE[name]
    started = time.perf_counter()
    sp._speaker_and_text(text)
    sp._strip_tags(text)
    assert time.perf_counter() - started < _BUDGET_S


@pytest.mark.parametrize("name", ["dots", "tabs_after_dot", "lt_flood", "v_tag_flood"])
def test_hostile_vtt_document_parses_quickly(name: str) -> None:
    data = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n" + HOSTILE[name] + "\n").encode()
    context = ParseContext(
        tenant_id="tenant_fixture",
        document_id="document_fixture",
        document_version_id="version_fixture",
        created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
        source_url="https://ingest.example.test/source",
        retrieved_at=datetime(2026, 7, 29, 11, 59, tzinfo=UTC),
    )
    started = time.perf_counter()
    try:
        document = parse_non_pdf_to_cir(
            filename="hostile.vtt", declared_mime="text/vtt", data=data, context=context
        )
    except Exception as error:  # a fail-closed refusal is fine; a hang is not
        assert type(error).__name__ == "StructuredParseError"
    else:
        assert document.metadata["subtitles"]["sourceCueCount"] == 1
    assert time.perf_counter() - started < _BUDGET_S


def test_new_matchers_are_byte_identical_to_the_old_patterns() -> None:
    alphabet = ["<", "v", ".", " ", "\t", ">", "a", ":"]
    checked = 0
    for length in range(0, 7):
        for combo in itertools.product(alphabet, repeat=length):
            raw = "".join(combo)
            assert sp._strip_tags(raw) == _OLD_TAG.sub("", raw), raw
            assert sp._speaker_and_text(raw) == _old_speaker_and_text(raw), raw
            checked += 1
    assert checked > 100_000


@pytest.mark.parametrize(
    "raw",
    [
        "<v Roger Bingham>We are in New York",
        "<v.loud.first Esme>It's a blue apple tree!",
        "<v   >text",
        "<v.a\tb>text",
        "<v Roger>hi <b>bold</b> <c.x>y</c>",
        "Speaker: line <i>one</i>",
        "<v>text",
        "<v. x>text",
        "<v\n>text",
        "<v.a\n b>text",
    ],
)
def test_well_formed_and_edge_cues_are_unchanged(raw: str) -> None:
    assert sp._speaker_and_text(raw) == _old_speaker_and_text(raw)
