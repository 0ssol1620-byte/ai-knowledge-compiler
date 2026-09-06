#!/usr/bin/env python3
"""Source-derived expected state. ORACLE_INDEPENDENCE_V2.

The v1 oracle took the canonical document the engine had already produced. That
made it an independent implementation of the *artifact* rules and nothing more:
a defect in canonicalisation was common-mode across both sides, and neither
could see it. This one starts at raw bytes.

It implements the specification written out in ORACLE_INDEPENDENCE_V2 section 2
from that text. It is a different implementation of the same rules — a
line-classifier followed by a fold, rather than the engine's block-emitter
followed by an assembler — so a slip in one is unlikely to be the same slip in
the other.

Two rules it obeys without asking:

* it imports no project module. A meta-path guard raises if anything tries, so
  the rule is enforced rather than trusted.
* it does not hash the comparison. It emits CONTENT. Whichever side hashes
  becomes the standard, and the point is that neither side is.

Run it as a subprocess under ``python -I -S``. It is not importable from the
engine side: importing it arms the guard against the importer.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser
from typing import Any

BLOCKED = (
    "akc_cir",
    "tavonel_eval_v2",
    "selective_build",
    "canonical_document",
    "changed_regions",
    "source_map",
    "source_map_v2",
    "markup_policy",
    "markup_semantics",
    "common",
    "evidence",
    "compare_states",
    "compare_recompilation",
)


class EnginePathBlocked(ImportError):
    """Raised when the oracle process reaches for the implementation it audits."""


class ImportGuard:
    triggered: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname.split(".")[0] in BLOCKED:
            ImportGuard.triggered.append(fullname)
            raise EnginePathBlocked("the independent oracle may not import " + fullname)
        return None


_GUARD = ImportGuard()
sys.meta_path.insert(0, _GUARD)

# --- specification section 2, re-implemented ---------------------------------

MIN_TEXT = 120
DROP_HEADINGS = frozenset(
    {"references", "external links", "see also", "further reading", "notes"}
)

_SHORTCODE = re.compile(r"\{\{[<%].*?[>%]\}\}", re.DOTALL)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(?:```|~~~)")
_DASHES = re.compile(r"^---\s*$")
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_TAG = re.compile(r"<[^>]+>")
_MARK = re.compile(r"(\*\*|\*|__|_|`)")
_GAP = re.compile(r"\s+")

#: Reference targets, for the reference/locator change type. Read from raw
#: bytes, because the compiled state has nowhere to put them.
_MD_TARGET = re.compile(r"\]\(([^)\s]+)")
_HTML_TARGET = re.compile(r"(?:href|src|cite|data|action|poster)\s*=\s*[\"']([^\"']+)")

#: Explicit effective/filing dates the oracle can read without help. Anything
#: else is UNSUPPORTED rather than assumed.
_DATE = re.compile(r"\b(19|20)\d{2}-\d{2}-\d{2}\b")


def flatten(value: str) -> str:
    return _GAP.sub(" ", value).strip()


def strip_markup(value: str) -> str:
    return flatten(_MARK.sub("", _TAG.sub(" ", _LINK.sub(r"\1", value))))


class _Blocks(HTMLParser):
    """HTML to a (level, text) stream. Deliberately not the engine's reader."""

    _LEVELS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
    _SKIP = frozenset({"script", "style", "head", "title"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[int | None, str]] = []
        self._heading: int | None = None
        self._buffer: list[str] = []
        self._muted = 0

    def _flush(self, level: int | None) -> None:
        text = flatten(" ".join(self._buffer))
        self._buffer = []
        if text:
            self.blocks.append((level, text))

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._SKIP:
            self._muted += 1
            return
        if tag in self._LEVELS:
            self._flush(None)
            self._heading = self._LEVELS[tag]

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._muted = max(0, self._muted - 1)
            return
        if tag in self._LEVELS and self._heading is not None:
            self._flush(self._heading)
            self._heading = None

    def handle_data(self, data: str) -> None:
        if not self._muted:
            self._buffer.append(data)

    def close(self) -> None:  # type: ignore[override]
        super().close()
        self._flush(None)


def blocks_from_html(text: str) -> list[tuple[int | None, str]]:
    reader = _Blocks()
    reader.feed(text)
    reader.close()
    return reader.blocks


def blocks_from_markdown(text: str) -> list[tuple[int | None, str]]:
    """A line classifier, then a fold. The engine emits blocks as it scans."""
    text = _SHORTCODE.sub(" ", text)
    lines = text.splitlines()
    classified: list[tuple[str, int, str]] = []
    fenced = False
    front = False
    for position, line in enumerate(lines):
        if _DASHES.match(line) and (position == 0 or front):
            front = not front
            continue
        if front:
            continue
        if _FENCE.match(line):
            fenced = not fenced
            classified.append(("body", 0, line))
            continue
        heading = None if fenced else _HEADING.match(line)
        if heading is None:
            classified.append(("body", 0, line))
        else:
            classified.append(("heading", len(heading.group(1)), heading.group(2)))

    blocks: list[tuple[int | None, str]] = []
    body: list[str] = []
    for kind, level, payload in classified:
        if kind == "body":
            body.append(payload)
            continue
        joined = strip_markup("\n".join(body))
        body = []
        if joined:
            blocks.append((None, joined))
        blocks.append((level, strip_markup(payload)))
    joined = strip_markup("\n".join(body))
    if joined:
        blocks.append((None, joined))
    return blocks


def units_from_blocks(blocks: list[tuple[int | None, str]]) -> list[dict[str, Any]]:
    """Fold the block stream into heading-path units, section 2 assembly rules."""
    open_headings: list[tuple[int, str]] = []
    heading = "lead"
    pending: list[str] = []
    units: list[dict[str, Any]] = []

    def close() -> None:
        text = flatten(" ".join(pending))
        if len(text) < MIN_TEXT:
            return
        if heading.casefold() in DROP_HEADINGS:
            return
        path = [name for _, name in open_headings] or [heading]
        units.append({"path": path, "heading": heading, "text": text})

    for level, payload in blocks:
        if level is None:
            pending.append(payload)
            continue
        close()
        pending = []
        heading = payload or "untitled"
        while open_headings and open_headings[-1][0] >= level:
            open_headings.pop()
        open_headings.append((level, heading))
    close()

    #: repeated heading paths are disambiguated by occurrence, exactly as the
    #: engine's explicit_path does. Same rule, derived separately.
    counts: dict[tuple[str, ...], int] = {}
    for unit in units:
        key = tuple(unit["path"])
        seen = counts.get(key, 0)
        counts[key] = seen + 1
        explicit = list(unit["path"])
        if seen:
            explicit[-1] = explicit[-1] + "#" + str(seen)
        unit["explicit_path"] = explicit
    return units


# --- artifact identity, section 2 --------------------------------------------


def logical_of(source_id: str, explicit_path: list[str]) -> str:
    material = "%s\n%s" % (source_id, "/".join(explicit_path))
    return "u:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def bucket_of(logical: str) -> int:
    return int(hashlib.sha256(logical.encode("utf-8")).hexdigest()[:8], 16) % 4


def portable_state(source_id: str, units: list[dict[str, Any]]) -> dict[str, Any]:
    """Artifact CONTENT keyed by portable identity. No digests: that is the comparator's job."""
    paths = ["/".join(unit["explicit_path"]) for unit in units]
    logicals = [logical_of(source_id, unit["explicit_path"]) for unit in units]

    state: dict[str, Any] = {}
    for unit, path in zip(units, paths):
        state["section:" + path] = {"path": path, "text": unit["text"]}
    state["document-index"] = {"members": paths}
    state["structure-map"] = {"paths": paths}
    ordered = sorted(set(zip(logicals, paths)))
    for bucket in range(4):
        members = [path for logical, path in ordered if bucket_of(logical) == bucket]
        if members:
            state["topic-bucket:" + str(bucket)] = {"bucket": bucket, "members": members}
    return state


# --- change typing, from raw bytes -------------------------------------------


def targets(text: str, suffix: str) -> list[str]:
    pattern = _MD_TARGET if suffix == ".md" else _HTML_TARGET
    return sorted(set(match.group(1) for match in pattern.finditer(text)))


def dates(text: str) -> list[str]:
    return sorted(set(match.group(0) for match in _DATE.finditer(text)))


def change_type(
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    before_raw: str,
    after_raw: str,
    suffix: str,
) -> dict[str, Any]:
    before_paths = before_state.get("structure-map", {}).get("paths", [])
    after_paths = after_state.get("structure-map", {}).get("paths", [])
    structural = before_paths != after_paths

    shared = set(before_state) & set(after_state)
    lexical = any(
        key.startswith("section:") and before_state[key] != after_state[key]
        for key in shared
    )

    reference = targets(before_raw, suffix) != targets(after_raw, suffix)
    before_dates, after_dates = dates(before_raw), dates(after_raw)
    temporal_supported = bool(before_dates or after_dates)
    temporal = temporal_supported and before_dates != after_dates

    kinds = []
    if structural:
        kinds.append("structural")
    if lexical:
        kinds.append("lexical")
    if reference:
        kinds.append("reference_locator")
    if temporal:
        kinds.append("temporal_authority")

    if not kinds:
        label = "no_modelled_change"
    elif kinds == ["structural"]:
        label = "structural_only"
    elif kinds == ["lexical"]:
        label = "lexical_only"
    elif kinds == ["reference_locator"]:
        label = "reference_locator_only"
    elif kinds == ["temporal_authority"]:
        label = "temporal_authority_only"
    else:
        label = "mixed"

    return {
        "label": label,
        "kinds": kinds,
        "structural": structural,
        "lexical": lexical,
        "reference_locator": reference,
        "temporal_authority": "UNSUPPORTED" if not temporal_supported else temporal,
    }


# --- driver -------------------------------------------------------------------


def derive(job: dict[str, Any]) -> dict[str, Any]:
    suffix = job["suffix"]
    family = job["family"]
    source_id = job["source_id"]

    def state_of(blob: str) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
        raw = base64.b64decode(blob).decode("utf-8", errors="replace")
        reader = blocks_from_html if family == "sec_edgar" else blocks_from_markdown
        units = units_from_blocks(reader(raw))
        return portable_state(source_id, units), raw, units

    unresolved: list[str] = []
    try:
        after_state, after_raw, after_units = state_of(job["after_payload_b64"])
        before_state, before_raw, before_units = state_of(job["before_payload_b64"])
    except Exception as error:
        return {
            "judgeable": False,
            "unresolved": ["READER_FAILED: %s" % type(error).__name__],
            "source_id": source_id,
        }

    if not after_units:
        unresolved.append("AFTER_REVISION_HAS_NO_UNITS")
    if not before_units:
        unresolved.append("BEFORE_REVISION_HAS_NO_UNITS")

    must_change = sorted(
        key
        for key in set(before_state) | set(after_state)
        if before_state.get(key) != after_state.get(key)
    )

    return {
        "judgeable": not unresolved,
        "unresolved": unresolved,
        "source_id": source_id,
        "family": family,
        "suffix": suffix,
        "oracle": "source_derived_expected.v2",
        "pid": os.getpid(),
        "flags": {"isolated": sys.flags.isolated, "no_site": sys.flags.no_site},
        "import_guard": {
            "armed": _GUARD in sys.meta_path,
            "blocked_prefixes": list(BLOCKED),
            "triggered": list(ImportGuard.triggered),
            "project_modules_imported": sorted(
                name
                for name in sys.modules
                if name.split(".")[0] in BLOCKED
            ),
        },
        "after_unit_count": len(after_units),
        "before_unit_count": len(before_units),
        "expected_state": after_state,
        "must_change": must_change,
        "change_type": change_type(
            before_state, after_state, before_raw, after_raw, suffix
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    with open(arguments.job, encoding="utf-8") as handle:
        job = json.load(handle)
    result = derive(job)
    with open(arguments.output, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"judgeable": result["judgeable"], "pid": result.get("pid")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
