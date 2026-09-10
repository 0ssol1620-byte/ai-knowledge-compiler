"""Bind the spent Native capture to replay features without opening labels.

This module is part of the runtime-visible half of the development replay.  It
accepts only the sealed Native capture (source inventory, observations and
local timing).  Evaluator rules and scores belong to :mod:`scorer` and are not
read or imported here.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import features as F

NATIVE_MODEL = "native"
EXPECTED_UNITS = 1403
_WORD = re.compile(r"\w+", re.UNICODE)
_REPLACEMENT = re.compile(r"[\ufffd]")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ALLOWED_STATUSES = {
    "native_text_observed",
    "native_text_unobserved",
    "native_runtime_unqualified",
    "native_parser_refused",
    "native_parser_failed",
}


def digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("NATIVE_CAPTURE_OBJECT_REQUIRED")
    return value


@dataclass(frozen=True, slots=True)
class NativeCapture:
    root: Path
    source_manifest_sha256: str
    freeze_sha256: str
    observations_sha256: str
    records: Mapping[str, Mapping[str, Any]]

    @property
    def binding(self) -> dict[str, Any]:
        return {
            "source_manifest_sha256": self.source_manifest_sha256,
            "freeze_sha256": self.freeze_sha256,
            "observations_sha256": self.observations_sha256,
            "units": len(self.records),
            "hidden_evaluation_visible_to_runtime": False,
        }


def load_capture(root: Path) -> NativeCapture:
    """Load and hash-check one complete, already-spent Native capture."""
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("NATIVE_CAPTURE_DIRECTORY_REQUIRED")
    freeze_path = (root / "FREEZE.json").resolve(strict=True)
    result_path = (root / "RESULT.json").resolve(strict=True)
    observations_path = (root / "observations.jsonl").resolve(strict=True)
    for path in (freeze_path, result_path, observations_path):
        if path.parent != root:
            raise ValueError("NATIVE_CAPTURE_PATH_ESCAPE")

    freeze = _read_json(freeze_path)
    result = _read_json(result_path)
    if (
        freeze.get("confirmatory_eligible") is not False
        or freeze.get("quality_verified") is not False
    ):
        raise ValueError("SPENT_NATIVE_CAPTURE_REQUIRED")
    if freeze.get("hidden_evaluation_visible_to_runtime") is not False:
        raise ValueError("NATIVE_CAPTURE_LEAKAGE_BOUNDARY_INVALID")
    if (
        freeze.get("eligible_units") != EXPECTED_UNITS
        or freeze.get("selected_units") != EXPECTED_UNITS
    ):
        raise ValueError("NATIVE_CAPTURE_DENOMINATOR_MISMATCH")
    if result.get("selected") != EXPECTED_UNITS or result.get("output_rows") != EXPECTED_UNITS:
        raise ValueError("NATIVE_CAPTURE_RESULT_DENOMINATOR_MISMATCH")
    observations_sha256 = digest(observations_path)
    if result.get("observations_sha256") != observations_sha256:
        raise ValueError("NATIVE_OBSERVATIONS_HASH_MISMATCH")

    selected = freeze.get("selected_source_rows")
    if not isinstance(selected, list) or len(selected) != EXPECTED_UNITS:
        raise ValueError("NATIVE_CAPTURE_SOURCE_ROWS_MISSING")
    source_rows: dict[str, Mapping[str, Any]] = {}
    for row in selected:
        if not isinstance(row, dict):
            raise ValueError("NATIVE_CAPTURE_SOURCE_ROW_INVALID")
        case_key = row.get("case_key")
        if not isinstance(case_key, str) or not case_key or case_key in source_rows:
            raise ValueError("NATIVE_CAPTURE_SOURCE_ID_INVALID")
        source_rows[case_key] = row

    records: dict[str, Mapping[str, Any]] = {}
    with observations_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("NATIVE_OBSERVATION_INVALID")
            case_key = row.get("case_key")
            if not isinstance(case_key, str) or case_key in records or case_key not in source_rows:
                raise ValueError("NATIVE_OBSERVATION_ID_INVALID")
            source = source_rows[case_key]
            if (
                row.get("sample_id") != source.get("sample_id")
                or row.get("source_sha256") != source.get("original_source_sha256")
                or row.get("route") != NATIVE_MODEL
                or row.get("confirmatory_eligible") is not False
                or row.get("quality_verified") is not False
                or row.get("status") not in _ALLOWED_STATUSES
            ):
                raise ValueError("NATIVE_OBSERVATION_BINDING_MISMATCH")
            text = row.get("text")
            if not isinstance(text, str):
                raise ValueError("NATIVE_OBSERVATION_TEXT_REQUIRED")
            output_sha256 = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
            if row.get("output_sha256") != output_sha256:
                raise ValueError("NATIVE_OBSERVATION_OUTPUT_HASH_MISMATCH")
            wall = row.get("local_wall_seconds")
            if not isinstance(wall, (int, float)) or not 0 <= float(wall) <= 300:
                raise ValueError("NATIVE_OBSERVATION_TIMING_INVALID")
            records[case_key] = row
    if set(records) != set(source_rows):
        raise ValueError("NATIVE_OBSERVATION_DENOMINATOR_INCOMPLETE")
    return NativeCapture(
        root=root,
        source_manifest_sha256=str(freeze["source_manifest_sha256"]),
        freeze_sha256=digest(freeze_path),
        observations_sha256=observations_sha256,
        records=records,
    )


def augment_units(
    units: Sequence[F.UnitFeatures],
    text_index: Mapping[tuple[str, str], str],
    capture: NativeCapture,
) -> tuple[list[F.UnitFeatures], dict[tuple[str, str], str]]:
    """Attach Native output and measured local latency to every replay unit."""
    if len(units) != EXPECTED_UNITS:
        raise ValueError("NATIVE_REPLAY_UNIT_DENOMINATOR_MISMATCH")
    updated_texts = dict(text_index)
    updated_units: list[F.UnitFeatures] = []
    consumed: set[str] = set()
    for unit in units:
        row = capture.records.get(unit.case_key)
        if row is None:
            raise ValueError("NATIVE_REPLAY_UNIT_UNBOUND")
        consumed.add(unit.case_key)
        text = str(row["text"])
        status = str(row["status"])
        present = status == "native_text_observed" and bool(text.strip())
        chars = len(text)
        located = int(row.get("located_blocks") or 0)
        unlocated = int(row.get("unlocated_blocks") or 0)
        locator_total = located + unlocated
        outputs = dict(unit.outputs)
        outputs[NATIVE_MODEL] = F.OutputFeatures(
            model=NATIVE_MODEL,
            status=status,
            present=present,
            chars=chars,
            words=len(_WORD.findall(text)),
            lines=len(text.splitlines()),
            table_rows=len(F._TABLE_ROW.findall(text)),
            replacement_ratio=(len(_REPLACEMENT.findall(text)) / chars if chars else 0.0),
            control_ratio=(len(_CONTROL.findall(text)) / chars if chars else 0.0),
            inference_ms=float(row["local_wall_seconds"]) * 1000.0,
            queue_ms=0.0,
            load_ms=None,
            peak_vram_mb=None,
        )
        similarities = dict(unit.similarity)
        native_tokens = F.normalize(text)
        for model, output in unit.outputs.items():
            other = text_index.get((model, unit.unit_key))
            if output.present and other is not None:
                key = "|".join(sorted((NATIVE_MODEL, model)))
                similarities[key] = F.similarity(native_tokens, F.normalize(other))
        updated_texts[(NATIVE_MODEL, unit.unit_key)] = text
        updated_units.append(
            replace(
                unit,
                native_text_chars=chars,
                native_word_count=len(_WORD.findall(text)),
                native_invalid_unicode_ratio=(
                    len(_CONTROL.findall(text)) / chars if chars else 0.0
                ),
                native_replacement_ratio=(
                    len(_REPLACEMENT.findall(text)) / chars if chars else 0.0
                ),
                native_text_available=present,
                native_locator_coverage=(
                    located / locator_total if locator_total else None
                ),
                outputs=outputs,
                similarity=similarities,
            )
        )
    if consumed != set(capture.records):
        raise ValueError("NATIVE_CAPTURE_ROWS_UNUSED")
    return updated_units, updated_texts


__all__ = ["EXPECTED_UNITS", "NATIVE_MODEL", "NativeCapture", "augment_units", "load_capture"]
