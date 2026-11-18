"""Markup normaliser v2 (WO-D10-0V, decision 5H-11): v1 plus the markup v1 left on real pages.

S0 ran on v1 and stays on it; S1 reads records re-derived offline with this module
(``benchmark.screen.rederive``). v2 is v1's behaviour plus, and nothing else:

* ``nemotron``: ``\\mbox{}`` and ``\\linebreak{}`` become one space, before v1's own steps, so
  the wrapper fixed point (``\\thead``, ``\\textbf``, ``\\textit``, ``\\text``,
  ``\\multirow{a}{b}{X}``, ``\\multicolumn{a}{b}{X}``) then unwraps a wrapper that held one, and a
  cell that held only an empty box is an empty cell for the symbol join. A box after an odd run
  of backslashes is not a command (``\\\\mbox{}`` is a row end, then text) and is left alone.
* every profile: ``<sup ...>``, ``</sup>`` and ``<img ...>`` become one space, before the
  profile's step, so a footnote marker is its own token, not glued to the label or number
  before it.

Digits, signs, currency symbols and words are never added, removed or reordered; only the
command and tag names above (and their bounded arguments) go. v2 imports v1 and extends it
rather than copying it: the joins, the profiles and the residual count are v1's code, and v1 is
pinned by its digest at import (a changed v1 refuses to load), so ``MODULE_SHA256`` of this
file together with ``V1_SHA256`` names the whole behaviour.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from benchmark.screen import normalise_v1 as _v1
from benchmark.screen.normalise_v1 import PROFILES, TEX_PASSES, dash_cell_before_number, profile_of

MODULE_SHA256 = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
V1_SHA256 = "sha256:94bfe9f5a1065bd56a01392e53f6a5c2bcf0981907e1e15150484f0b0e6526ab"
if _v1.MODULE_SHA256 != V1_SHA256:
    raise ImportError("normalise_v1.py is not the v1 that normalise_v2 extends")

__all__ = [
    "MODULE_SHA256",
    "PROFILES",
    "TEX_PASSES",
    "V1_SHA256",
    "dash_cell_before_number",
    "normalise",
    "profile_of",
]

_SUP_IMG = re.compile(r"</?sup\b[^<>]{0,200}>|<img\b[^<>]{0,200}>", re.IGNORECASE)
# after an even run of backslashes, as v1's ``&`` rule: ``\\mbox{}`` is a row end, then text
_EMPTY_BOX = re.compile(r"(?<!\\)((?:\\\\){0,50})\\(?:mbox|linebreak)\{\}")


def _nemotron(text: str) -> str:
    return _v1._nemotron(_EMPTY_BOX.sub(r"\1 ", text))


_STEPS = {**_v1._STEPS, "nemotron": _nemotron}


def normalise(provider: str, text: str) -> tuple[str, int]:
    """(normalised text, residual): v1's ``normalise`` with the two additions above."""
    text = _STEPS[profile_of(provider)](_SUP_IMG.sub(" ", text)).replace("\u00a0", " ")
    text = "\n".join(_v1._join_symbol_cells(x) if "|" in x else x for x in text.split("\n"))
    return text, len(_v1._RESIDUAL.findall(text))
