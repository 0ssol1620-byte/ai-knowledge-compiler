"""Fresh prospective acquisition for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.

AN ADAPTER, NOT A FORK, for the reason the freeze ladder is one. The V2R2
fetcher is ~635 lines of traversal, pair construction, integrity rejection,
content-addressed caching and canonicalisation that must behave IDENTICALLY
here; copying it would create a second implementation of the same machinery,
free to drift, and drift between two copies of "the same" acquisition is not
something a later reader could detect from the corpus.

WHAT DIFFERS IS THREE NAMES, and they are named rather than patched silently:

    frame            sources_v2r3 instead of sources_v2r2
    OUT              artifacts/development/v2r3_corpus
    FRAME_FREEZE     the V2R3 rung-0 receipt glob and the V2R3 frame module

THE BINDINGS ARE SCOPED, exactly as the freeze adapter's are. A permanent rebind
at import makes correctness depend on which adapter imported last, and this
programme has now paid for that twice: 21 of 24 V2R2 gate tests silently
asserting things about V2R1, and eight V2R2 adapter tests going red when the
V2R3 freezer first rebound at import. `_bound()` holds the names for the
duration of one call and restores them afterwards, on the error path too.

WHY THE FRAME TUPLE SHAPE WAS KEPT. `GIT_ROOTS` carries five fields here, the
same five every earlier frame used, and the probed document counts live beside
it in `PROBED_DOCUMENTS`. A study-specific sixth field would have forced a
V2R3-only fetcher -- the frame would have dictated a fork.

RUNS ONLY AGAINST THE FROZEN FRAME. Before a single request goes out, the
inherited `require_frozen_frame` checks that `sources_v2r3.py` still matches the
digest rung 0 sealed. An acquisition that ran first would make the freeze a
record of what was done rather than a constraint on what may be done.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (
    str(NS),
    str(NS / "acquisition"),
    str(NS / "canonicalization"),
    str(NS / "compiler"),
):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import fetch_v2r2_corpus as base  # noqa: E402
import sources_v2r3 as frame  # noqa: E402

FrameNotFrozen = base.FrameNotFrozen

OUT = NS / "artifacts" / "development" / "v2r3_corpus"
FRAME_MODULE = NS / "acquisition" / "sources_v2r3.py"
FRAME_FREEZE_GLOB = "identity-change-migration-closure-v2r3-acquisition-frame-freeze--*.json"

_OVERRIDE_TARGETS = ("frame", "OUT", "require_frozen_frame", "acquire", "main")


def _verify_override_targets() -> None:
    missing = [name for name in _OVERRIDE_TARGETS if not hasattr(base, name)]
    if missing:
        raise RuntimeError(
            f"the V2R2 fetcher no longer defines {missing}. An override that lands "
            "on nothing is not an override, and a V2R3 acquisition would silently "
            "write into another study's corpus. Fix the adapter rather than the "
            "base: V2R2's tooling is spent-run evidence."
        )


_verify_override_targets()


def require_frozen_frame() -> dict[str, Any]:
    """Refuse to fetch anything unless the V2R3 frame matches its rung-0 receipt.

    Reimplemented rather than adapted because it is six lines of path literals
    and the base's version hardcodes V2R2's receipt name and module. Sharing it
    would mean rebinding two more strings to make six lines behave; writing them
    out is smaller and says plainly which receipt authorises this fetch.
    """
    import hashlib
    import json

    receipts = sorted((NS / "receipts").glob(FRAME_FREEZE_GLOB))
    if not receipts:
        raise FrameNotFrozen(
            "no rung-0 V2R3 acquisition frame receipt exists. The frame is sealed "
            "BEFORE acquisition; fetching first would make the freeze a record of "
            "what was done rather than a constraint on what may be done."
        )
    body = json.loads(receipts[-1].read_text(encoding="utf-8"))
    current = "sha256:" + hashlib.sha256(FRAME_MODULE.read_bytes()).hexdigest()
    if body.get("frame_module_sha256") != current:
        raise FrameNotFrozen(
            "the acquisition frame changed after it was frozen.\n"
            f"  frozen:  {body.get('frame_module_sha256')}\n"
            f"  current: {current}"
        )
    if body.get("protocol_id") != frame.PROTOCOL_ID:
        raise FrameNotFrozen(
            f"the rung-0 receipt names {body.get('protocol_id')}, not "
            f"{frame.PROTOCOL_ID}. A fetch authorised by another study's frame is "
            "not authorised."
        )
    return body


def _bindings() -> dict[str, Any]:
    return {
        "frame": frame,
        "OUT": OUT,
        "require_frozen_frame": require_frozen_frame,
    }


@contextmanager
def _bound() -> Iterator[None]:
    """Point the shared fetcher at V2R3 for one call, then hand it back."""
    previous = {name: getattr(base, name) for name in _bindings()}
    for name, value in _bindings().items():
        setattr(base, name, value)
    try:
        wrong = [
            name for name, value in _bindings().items() if getattr(base, name, None) is not value
        ]
        if wrong:
            raise FrameNotFrozen(
                f"the shared fetcher did not take this adapter's bindings: {wrong}. "
                "Proceeding would acquire into another study's corpus."
            )
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def main(argv: list[str] | None = None) -> int:
    """The V2R3 acquisition, run against the V2R3 frame and corpus."""
    with _bound():
        return int(base.main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
