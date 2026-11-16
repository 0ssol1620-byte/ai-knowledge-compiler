"""WO-D07-10: every pattern applied to subtitle cue text is linear on hostile input."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from akc_cir.base import canonical_json
from akc_native_parsers import ParseContext, parse_non_pdf_to_cir

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures" / "nonpdf"
MIME = {"srt": "application/x-subrip", "vtt": "text/vtt"}


def _bounded_child(code: str, timeout: float) -> None:
    # spawn hands the child this sys.path; a failing assert there exits non-zero and
    # its traceback lands in the captured output. An exponential pattern is killed at
    # the deadline and fails the test instead of hanging the suite.
    import multiprocessing

    child = multiprocessing.get_context("spawn").Process(target=exec, args=(code, {}))
    child.start()
    child.join(timeout)
    if child.is_alive():
        child.kill()
        child.join()
        pytest.fail(f"subtitle parse did not finish within {timeout}s on hostile cue text")
    assert child.exitcode == 0, "hostile-cue child failed; see its traceback above"


_PRELUDE = r"""
import time
from datetime import UTC, datetime
from akc_native_parsers import ParseContext, StructuredParseError, parse_non_pdf_to_cir

CAP = 20_000  # ParserLimits.max_cue_chars: the longest cue the parser accepts
MIME = {"srt": "application/x-subrip", "vtt": "text/vtt"}
BOUND_S = 5.0


def parse_cue(ext, cue):
    assert len(cue) <= CAP, len(cue)
    if ext == "vtt":
        data = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n" + cue + "\n").encode()
    else:
        data = ("1\n00:00:00,000 --> 00:00:01,000\n" + cue + "\n").encode()
    started = time.perf_counter()
    try:
        parse_non_pdf_to_cir(
            filename="hostile." + ext, declared_mime=MIME[ext], data=data,
            context=ParseContext(tenant_id="tenant_fixture", document_id="document_fixture",
                                 document_version_id="version_fixture",
                                 created_at=datetime(2026, 7, 29, tzinfo=UTC)))
    except StructuredParseError:
        pass  # a fail-closed refusal is fine; a stall is not
    elapsed = time.perf_counter() - started
    assert elapsed < BOUND_S, (ext, cue[:60], elapsed)
"""

_PUMP_CHILD = (
    _PRELUDE
    + r"""
import random

TOKENS = ["<v", ".", " ", "\t", "<", ">", "a", ":", "5", "<v.a", "<b>", "<>", "<v.a "]


def pump(token):
    return (token * (CAP // len(token) + 1))[:CAP]


cues = [pump(t) for t in TOKENS]
cues += [("<v" + pump(t))[:CAP] for t in TOKENS]  # <v then a flood, at the cap
cues += [("<v" + "." * (CAP - 3) + "5")[:CAP], "<v" + "." * (CAP - 2)]  # dots, at the cap
cues += [(pump(a)[: CAP // 2] + pump(b))[:CAP] for a in TOKENS for b in TOKENS]
rng = random.Random(20261116)
for _ in range(40):
    cues.append("".join(rng.choice(TOKENS) for _ in range(CAP))[:CAP])
for cue in cues:
    for ext in ("vtt", "srt"):
        parse_cue(ext, cue)
"""
)

_REVIEWER_CHILD = (
    _PRELUDE
    + r"""
cue = "<v" + "." * 40 + "5"
for ext in ("vtt", "srt"):
    parse_cue(ext, cue)
"""
)


def test_hostile_cue_text_costs_linear_time_property() -> None:
    _bounded_child(_PUMP_CHILD, timeout=600)


def test_voice_tag_of_forty_dots_parses_in_bounded_time() -> None:
    # reviewer's case: `<v` + 40 dots + `5` took ~8 s in the old regex and grows 2x per dot
    _bounded_child(_REVIEWER_CHILD, timeout=60)


def _parse(filename: str, mime: str, data: bytes):  # type: ignore[no-untyped-def]
    return parse_non_pdf_to_cir(
        filename=filename,
        declared_mime=mime,
        data=data,
        context=ParseContext(
            tenant_id="tenant_fixture",
            document_id="document_fixture",
            document_version_id="version_fixture",
            created_at=datetime(2026, 7, 29, 12, 0, tzinfo=UTC),
            source_url="https://ingest.example.test/source",
            retrieved_at=datetime(2026, 7, 29, 11, 59, tzinfo=UTC),
        ),
    )


_VOICE_VTT = (
    b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n"
    b"<v.loud.first Esme>It's a blue <b>apple</b> tree!\n\n"
    b"00:00:01.000 --> 00:00:02.000\n<v Roger Bingham>We are in New York</v>\n"
)
_TEXT_SPEAKER_SRT = (
    b"1\n00:00:00,000 --> 00:00:01,000\nHost: line <i>one</i>\n\n"
    b"2\n00:00:01,000 --> 00:00:02,000\nplain 5 text\n"
)
_MALFORMED_VTT = (
    b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n<v>text\n\n"
    b"00:00:01.000 --> 00:00:02.000\na < b > c <>x\n"
)

# Recorded from the pre-fix module (core-int 9fdea49) as literals: the sha256 of the
# canonical JSON of the whole parsed document, plus the readable block text and merge
# counts it was derived from. The fixed module must reproduce them exactly.
_DIFFERENTIAL = {
    "sample.srt": (
        "captions.srt",
        "srt",
        (FIXTURES / "sample.srt").read_bytes,
        "f171c1a57573bcda5701bc0438dab77ba75d51b5cd093d128db5f39689da7f3d",
        [
            "captions",
            "Segment 1 · 00:00:01.000-00:00:09.000",
            "첫 번째 문장입니다.",
            "반복 문장",
            "마지막 문장입니다.",
        ],
        (4, 3, 1),
    ),
    "sample.vtt": (
        "captions.vtt",
        "vtt",
        (FIXTURES / "sample.vtt").read_bytes,
        "a2b9aa087e4ea6b1b9591b68ef397d715775a22e30f2acd6c195a7fe9b562993",
        [
            "captions",
            "Segment 1 · 00:00:01.000-00:00:06.500",
            "첫 번째 관찰입니다.",
            "두 번째 관찰입니다.",
        ],
        (2, 2, 0),
    ),
    "voice_classes": (
        "v.vtt",
        "vtt",
        lambda: _VOICE_VTT,
        "c8385fedef99f8be0fe82ba4171f2bf630fb16ab1a76e668ffb4047c1d7db609",
        [
            "v",
            "Segment 1 · 00:00:00.000-00:00:02.000",
            "It's a blue apple tree!",
            "We are in New York",
        ],
        (2, 2, 0),
    ),
    "text_speaker": (
        "t.srt",
        "srt",
        lambda: _TEXT_SPEAKER_SRT,
        "baf20bd5fdb171f65b0dc84285d844d449ba5454f50b42167a52f7d9fa669e85",
        ["t", "Segment 1 · 00:00:00.000-00:00:02.000", "line one", "plain 5 text"],
        (2, 2, 0),
    ),
    "malformed": (
        "m.vtt",
        "vtt",
        lambda: _MALFORMED_VTT,
        "0bcb1c8e8c1a5a7fa93cbdb7c3274bf1a5184bf5e582196211d4667b03a2e843",
        ["m", "Segment 1 · 00:00:00.000-00:00:02.000", "text", "a  c <>x"],
        (2, 2, 0),
    ),
}


@pytest.mark.parametrize("name", sorted(_DIFFERENTIAL))
def test_existing_fixtures_parse_exactly_as_before_the_fix(name: str) -> None:
    filename, ext, read, digest, texts, (source, canonical, merged) = _DIFFERENTIAL[name]
    document = _parse(filename, MIME[ext], read())
    assert [block.normalized_text for block in document.blocks] == texts
    meta = document.metadata["subtitles"]
    assert (meta["sourceCueCount"], meta["canonicalCueCount"], meta["mergedRepeatedCueCount"]) == (
        source,
        canonical,
        merged,
    )
    actual = hashlib.sha256(canonical_json(document.model_dump(mode="json")).encode()).hexdigest()
    assert actual == digest
