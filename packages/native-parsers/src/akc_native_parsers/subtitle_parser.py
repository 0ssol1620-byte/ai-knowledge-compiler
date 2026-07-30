"""SRT and WebVTT cue parsing with deterministic time provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass

from akc_cir import BlockType

from .models import CirBuilder, SourceLocation, StructuredParseError, normalize_text

_TIMING_LINE = re.compile(
    r"^(?P<start>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[,.]\d{3})(?:\s+.*)?$"
)
_TAG = re.compile(r"<[^>]+>")
_VTT_SPEAKER = re.compile(r"^<v(?:\.[^ >]+)*\s+([^>]+)>(.*)$", re.DOTALL)
_TEXT_SPEAKER = re.compile(r"^([^\n:]{1,80}):\s+(.+)$", re.DOTALL)


@dataclass(frozen=True, slots=True)
class Cue:
    first_index: int
    last_index: int
    identifier: str | None
    start_ms: int
    end_ms: int
    raw_text: str
    normalized_text: str
    speaker: str | None


@dataclass(frozen=True, slots=True)
class Segment:
    cues: tuple[Cue, ...]
    boundary_reason: str

    @property
    def start_ms(self) -> int:
        return self.cues[0].start_ms

    @property
    def end_ms(self) -> int:
        return self.cues[-1].end_ms


def parse_subtitles(
    source: str,
    *,
    document_type: str,
    builder: CirBuilder,
) -> str:
    if document_type == "vtt":
        cues, skipped_blocks = _parse_vtt(source, builder)
    elif document_type == "srt":
        cues = _parse_srt(source, builder)
        skipped_blocks = 0
    else:
        raise StructuredParseError("UNSUPPORTED_SUBTITLE_TYPE")
    merged = _merge_repeated_cues(cues)
    segments = _segment_cues(merged)
    title = _filename_title(builder.source_filename)
    root = builder.add_block(
        block_type=BlockType.TITLE,
        location=SourceLocation(
            page_index0=0,
            native_object_id=f"{document_type}/document",
        ),
        raw_text=title,
        markdown=f"# {title}",
    )
    segment_metadata: list[dict[str, int | str | bool]] = []
    for segment_index, segment in enumerate(segments):
        duration_ms = segment.end_ms - segment.start_ms
        segment_flags = [
            "subtitle_segment",
            f"boundary:{segment.boundary_reason}",
        ]
        within_target = 30_000 <= duration_ms <= 90_000
        if not within_target:
            segment_flags.append("segment_duration_outside_target")
        segment_block = builder.add_block(
            block_type=BlockType.HEADING,
            location=SourceLocation(
                page_index0=0,
                native_object_id=f"{document_type}/segment/{segment_index:06d}",
                time_start_ms=segment.start_ms,
                time_end_ms=segment.end_ms,
            ),
            raw_text=(
                f"Segment {segment_index + 1} · "
                f"{_format_time(segment.start_ms)}-{_format_time(segment.end_ms)}"
            ),
            markdown=(
                f"## Segment {segment_index + 1} "
                f"({_format_time(segment.start_ms)}-{_format_time(segment.end_ms)})"
            ),
            parent_id=root.id,
            quality_flags=tuple(segment_flags),
        )
        for cue in segment.cues:
            native_suffix = (
                f"{cue.first_index:06d}"
                if cue.first_index == cue.last_index
                else f"{cue.first_index:06d}-{cue.last_index:06d}"
            )
            quality_flags: list[str] = []
            if cue.speaker:
                quality_flags.append("speaker_label_detected")
            if cue.first_index != cue.last_index:
                quality_flags.append("repeated_cues_merged")
            markdown_text = (
                f"**{cue.speaker}:** {cue.normalized_text}" if cue.speaker else cue.normalized_text
            )
            builder.add_block(
                block_type=BlockType.PARAGRAPH,
                location=SourceLocation(
                    page_index0=0,
                    native_object_id=f"{document_type}/cue/{native_suffix}",
                    time_start_ms=cue.start_ms,
                    time_end_ms=cue.end_ms,
                ),
                raw_text=cue.raw_text,
                normalized_text=cue.normalized_text,
                markdown=(
                    f"[{_format_time(cue.start_ms)} - {_format_time(cue.end_ms)}] {markdown_text}"
                ),
                parent_id=segment_block.id,
                quality_flags=tuple(quality_flags),
            )
        segment_metadata.append(
            {
                "index0": segment_index,
                "startMs": segment.start_ms,
                "endMs": segment.end_ms,
                "durationMs": duration_ms,
                "cueCount": len(segment.cues),
                "boundaryReason": segment.boundary_reason,
                "within30To90Seconds": within_target,
            }
        )
    builder.metadata["subtitles"] = {
        "sourceCueCount": len(cues),
        "canonicalCueCount": len(merged),
        "mergedRepeatedCueCount": len(cues) - len(merged),
        "skippedMetadataBlockCount": skipped_blocks,
        "timestampsPreserved": True,
        "segmentation": {
            "strategy": "deterministic-topic-boundary-30-90s",
            "targetSeconds": 60,
            "minimumSeconds": 30,
            "maximumSeconds": 90,
            "segmentCount": len(segments),
            "segments": segment_metadata,
        },
    }
    if skipped_blocks:
        builder.add_warning("vtt_metadata_blocks_not_executed")
    return title


def _parse_srt(source: str, builder: CirBuilder) -> tuple[Cue, ...]:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n").strip()
    blocks = re.split(r"\n{2,}", normalized)
    cues: list[Cue] = []
    for source_index, block in enumerate(blocks):
        lines = block.splitlines()
        if not lines:
            continue
        identifier: str | None = None
        timing_index = 0
        if not _TIMING_LINE.match(lines[0].strip()):
            identifier = lines[0].strip()
            timing_index = 1
        if timing_index >= len(lines):
            raise StructuredParseError("SRT_INVALID_CUE")
        timing = _TIMING_LINE.match(lines[timing_index].strip())
        if timing is None:
            raise StructuredParseError("SRT_INVALID_TIMING")
        raw_text = normalize_text("\n".join(lines[timing_index + 1 :]))
        if not raw_text:
            continue
        if len(raw_text) > builder.limits.max_cue_chars:
            raise StructuredParseError("SUBTITLE_CUE_TEXT_LIMIT")
        start_ms = _parse_time(timing.group("start"))
        end_ms = _parse_time(timing.group("end"))
        cues.append(
            _cue(
                source_index=source_index,
                identifier=identifier,
                start_ms=start_ms,
                end_ms=end_ms,
                raw_text=raw_text,
            )
        )
        if len(cues) > builder.limits.max_subtitle_cues:
            raise StructuredParseError("SUBTITLE_CUE_LIMIT")
    if not cues:
        raise StructuredParseError("SRT_NO_CUES")
    return tuple(cues)


def _parse_vtt(
    source: str,
    builder: CirBuilder,
) -> tuple[tuple[Cue, ...], int]:
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.lstrip("\ufeff").startswith("WEBVTT"):
        raise StructuredParseError("VTT_SIGNATURE_MISMATCH")
    body = normalized.lstrip("\ufeff").split("\n", 1)
    payload = body[1] if len(body) == 2 else ""
    blocks = re.split(r"\n{2,}", payload.strip())
    cues: list[Cue] = []
    skipped_blocks = 0
    for block in blocks:
        lines = block.splitlines()
        if not lines:
            continue
        first = lines[0].strip()
        if first.startswith(("NOTE", "STYLE", "REGION")):
            skipped_blocks += 1
            continue
        if not any(_TIMING_LINE.match(line.strip()) for line in lines):
            if cues:
                raise StructuredParseError("VTT_INVALID_CUE")
            skipped_blocks += 1
            continue
        identifier: str | None = None
        timing_index = 0
        if not _TIMING_LINE.match(first):
            identifier = first
            timing_index = 1
        if timing_index >= len(lines):
            raise StructuredParseError("VTT_INVALID_CUE")
        timing = _TIMING_LINE.match(lines[timing_index].strip())
        if timing is None:
            raise StructuredParseError("VTT_INVALID_TIMING")
        raw_text = normalize_text("\n".join(lines[timing_index + 1 :]))
        if not raw_text:
            continue
        if len(raw_text) > builder.limits.max_cue_chars:
            raise StructuredParseError("SUBTITLE_CUE_TEXT_LIMIT")
        cues.append(
            _cue(
                source_index=len(cues),
                identifier=identifier,
                start_ms=_parse_time(timing.group("start")),
                end_ms=_parse_time(timing.group("end")),
                raw_text=raw_text,
            )
        )
        if len(cues) > builder.limits.max_subtitle_cues:
            raise StructuredParseError("SUBTITLE_CUE_LIMIT")
    if not cues:
        raise StructuredParseError("VTT_NO_CUES")
    return tuple(cues), skipped_blocks


def _cue(
    *,
    source_index: int,
    identifier: str | None,
    start_ms: int,
    end_ms: int,
    raw_text: str,
) -> Cue:
    if end_ms < start_ms:
        raise StructuredParseError("SUBTITLE_TIME_ORDER")
    speaker, text = _speaker_and_text(raw_text)
    normalized = normalize_text(_TAG.sub("", text))
    if not normalized:
        raise StructuredParseError("SUBTITLE_EMPTY_CUE")
    return Cue(
        first_index=source_index,
        last_index=source_index,
        identifier=identifier,
        start_ms=start_ms,
        end_ms=end_ms,
        raw_text=raw_text,
        normalized_text=normalized,
        speaker=speaker,
    )


def _speaker_and_text(raw_text: str) -> tuple[str | None, str]:
    vtt_match = _VTT_SPEAKER.match(raw_text)
    if vtt_match:
        return normalize_text(vtt_match.group(1)), vtt_match.group(2)
    plain = _TAG.sub("", raw_text)
    text_match = _TEXT_SPEAKER.match(plain)
    if text_match:
        return normalize_text(text_match.group(1)), text_match.group(2)
    return None, raw_text


def _merge_repeated_cues(cues: tuple[Cue, ...]) -> tuple[Cue, ...]:
    merged: list[Cue] = []
    for cue in cues:
        if (
            merged
            and merged[-1].normalized_text == cue.normalized_text
            and merged[-1].speaker == cue.speaker
            and cue.start_ms <= merged[-1].end_ms + 1_000
        ):
            previous = merged[-1]
            merged[-1] = Cue(
                first_index=previous.first_index,
                last_index=cue.last_index,
                identifier=previous.identifier,
                start_ms=previous.start_ms,
                end_ms=max(previous.end_ms, cue.end_ms),
                raw_text=previous.raw_text,
                normalized_text=previous.normalized_text,
                speaker=previous.speaker,
            )
        else:
            merged.append(cue)
    return tuple(merged)


def _segment_cues(cues: tuple[Cue, ...]) -> tuple[Segment, ...]:
    if not cues:
        return ()
    segments: list[Segment] = []
    current: list[Cue] = []
    next_boundary_reason = "document_start"
    for cue in cues:
        if current:
            duration_with_cue = cue.end_ms - current[0].start_ms
            current_duration = current[-1].end_ms - current[0].start_ms
            gap_ms = max(0, cue.start_ms - current[-1].end_ms)
            split_reason: str | None = None
            if duration_with_cue > 90_000:
                split_reason = "maximum_duration"
            elif current_duration >= 60_000 and _is_topic_boundary(current[-1], cue):
                split_reason = "topic_boundary"
            elif current_duration >= 30_000 and gap_ms >= 5_000:
                split_reason = "long_pause"
            if split_reason is not None:
                segments.append(
                    Segment(
                        cues=tuple(current),
                        boundary_reason=next_boundary_reason,
                    )
                )
                current = []
                next_boundary_reason = split_reason
        current.append(cue)
    if current:
        segments.append(
            Segment(
                cues=tuple(current),
                boundary_reason=next_boundary_reason,
            )
        )

    if len(segments) >= 2:
        last = segments[-1]
        previous = segments[-2]
        combined_duration = last.end_ms - previous.start_ms
        if last.end_ms - last.start_ms < 30_000 and combined_duration <= 90_000:
            segments[-2:] = [
                Segment(
                    cues=(*previous.cues, *last.cues),
                    boundary_reason=previous.boundary_reason,
                )
            ]
    return tuple(segments)


def _is_topic_boundary(previous: Cue, following: Cue) -> bool:
    gap_ms = max(0, following.start_ms - previous.end_ms)
    speaker_changed = (
        previous.speaker is not None
        and following.speaker is not None
        and previous.speaker != following.speaker
    )
    sentence_ended = previous.normalized_text.rstrip().endswith(
        (".", "!", "?", "\u3002", "\uff01", "\uff1f")
    )
    return gap_ms >= 2_500 or speaker_changed or sentence_ended


def _parse_time(value: str) -> int:
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_part = parts[2]
    elif len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds_part = parts[1]
    else:
        raise StructuredParseError("SUBTITLE_INVALID_TIMESTAMP")
    seconds_text, milliseconds_text = seconds_part.split(".", 1)
    seconds = int(seconds_text)
    milliseconds = int(milliseconds_text)
    if minutes >= 60 or seconds >= 60 or milliseconds >= 1000:
        raise StructuredParseError("SUBTITLE_INVALID_TIMESTAMP")
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _format_time(value_ms: int) -> str:
    hours, remaining = divmod(value_ms, 3_600_000)
    minutes, remaining = divmod(remaining, 60_000)
    seconds, milliseconds = divmod(remaining, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{milliseconds:03d}"


def _filename_title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].replace("_", " ")
    return normalize_text(stem) or "Transcript"
