"""Minimal, dependency-free ``.dockerignore``-style pattern matcher.

Docker's own ignore-pattern engine (moby/patternmatcher) is not available on
this Docker-less host, and the lane brief forbids adding a new third-party
dependency (e.g. ``pathspec``) just to simulate it. This module implements
the small subset of gitignore-style syntax this repo's ``.dockerignore``
actually uses:

- ``#`` / blank lines are comments/ignored
- a leading ``/`` anchors the pattern to the context root
- a leading ``**/`` matches at any depth
- a trailing ``/`` matches a directory (and everything under it)
- ``*`` matches within one path segment (never across ``/``)
- everything else is a plain substring-anchored segment match

This is intentionally not a complete reimplementation of Docker's matcher
(no ``!`` negation, no ``**`` in the middle of a pattern beyond the prefix
case above) -- exactly enough to test the one file this lane owns.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IgnorePattern:
    raw: str
    anchored: bool
    dir_only: bool
    regex: re.Pattern[str]

    def matches(self, relpath: str) -> bool:
        """Does this single path segment sequence (a file, or one specific
        directory in a path) match, on its own? Matching a path's *ancestor*
        directories against a ``dir_only`` pattern is ``is_ignored``'s job,
        not this method's -- this only answers "does this exact candidate
        match the pattern text"."""
        candidate = relpath[:-1] if relpath.endswith("/") else relpath
        if self.regex.fullmatch(candidate):
            return True
        if not self.anchored:
            # An unanchored pattern may match starting at any path segment,
            # matching gitignore/dockerignore semantics for a bare name.
            segments = candidate.split("/")
            for start in range(len(segments)):
                if self.regex.fullmatch("/".join(segments[start:])):
                    return True
        return False


def _compile(pattern_body: str) -> re.Pattern[str]:
    """Translate one ``*``/``?``-glob path segment sequence into a regex that
    matches the *whole* candidate string (``fnmatch.translate`` per segment,
    joined back with literal ``/``)."""
    segments = pattern_body.split("/")
    translated = [fnmatch.translate(segment)[:-2] if segment else "" for segment in segments]
    # fnmatch.translate wraps in (?s:...)\Z; strip that and rejoin with '/'.
    cleaned = []
    for segment, original in zip(translated, segments, strict=True):
        if original == "":
            cleaned.append("")
            continue
        cleaned.append(segment.removeprefix("(?s:").removesuffix(")"))
    body = "/".join(cleaned)
    return re.compile(body)


def parse_pattern(line: str) -> IgnorePattern | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    raw = stripped
    dir_only = raw.endswith("/")
    if dir_only:
        raw = raw[:-1]
    anchored = raw.startswith("/")
    if anchored:
        raw = raw[1:]
    if raw.startswith("**/"):
        anchored = False
        raw = raw[3:]
    regex = _compile(raw)
    return IgnorePattern(raw=stripped, anchored=anchored, dir_only=dir_only, regex=regex)


def load_patterns(dockerignore_text: str) -> tuple[IgnorePattern, ...]:
    patterns = []
    for line in dockerignore_text.splitlines():
        parsed = parse_pattern(line)
        if parsed is not None:
            patterns.append(parsed)
    return tuple(patterns)


def is_ignored(relpath: str, patterns: tuple[IgnorePattern, ...]) -> bool:
    """``relpath`` is a forward-slash relative path from the build-context
    root, e.g. ``"runs/paddleocr_vl_1_6/receipts/x.json"``, with no leading
    ``/``. Matches if the path itself, or any parent directory of it,
    matches a pattern (mirrors "excluding a directory excludes its
    contents")."""
    if any(pattern.matches(relpath) for pattern in patterns):
        return True
    # A pattern that matches an *ancestor* directory (whether or not that
    # pattern was written with a trailing '/') excludes everything under it,
    # same as gitignore: "runs/" and "runs" both hide runs/paddleocr/x.json.
    parts = relpath.split("/")
    for depth in range(1, len(parts)):
        parent = "/".join(parts[:depth])
        if any(pattern.matches(parent) for pattern in patterns):
            return True
    return False


__all__ = ["IgnorePattern", "is_ignored", "load_patterns", "parse_pattern"]
