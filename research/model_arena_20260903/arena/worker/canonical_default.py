"""Passthrough canonicalizer.

Used only when ``runtimes/<model_key>/canonical.py`` is absent. It copies the
model's verbatim text into the canonical markdown slot and says so: nothing is
reordered, relabelled, added or dropped, so the conversion cannot be lossy.
A runtime whose native format is not markdown must ship its own converter —
this module is honest, not correct-for-every-model.
"""

from __future__ import annotations

from arena.worker.adapter_api import CanonicalOutput, RawOutput

PASSTHROUGH_NOTE = "passthrough"


def canonicalize(raw: RawOutput) -> CanonicalOutput:
    return CanonicalOutput(
        markdown=raw.raw_text,
        elements=None,
        conversion_notes=(PASSTHROUGH_NOTE,),
        lossy=False,
    )


__all__ = ["PASSTHROUGH_NOTE", "canonicalize"]
