#!/usr/bin/env python3
"""SFIR6's capacity seal: INC-V2-107 repaired without editing a frozen module.

`seal_capacity` compares a census's pagination block against
`CAPACITY_PAGINATION_FIELDS` by **strict set equality**. The INC-V2-098 repair
added `retries_total` and `transport_retries` to the block that `probe_capacity`
writes, so producer and consumer disagreed and the seal refused every census, for
every family, whatever the data said. It went unseen for four studies because no
census had ever completed far enough to reach it.

**Why the frozen module is not edited.** `tools/sfir4_protocol.py` is pinned by
SFIR5's sealed charter freeze. Editing it would not rewrite any receipt -- but it
would make a sealed authority fail its own re-verification, which is worse than
the defect. A pin records what the bytes were; changing the bytes afterwards
turns an auditable record into a mismatch that looks like tampering.

So the repair lives in the successor, exactly as the Wikipedia adapter does. The
corrected field set is declared here, applied for the duration of one seal, and
restored. `frozen_module_is_byte_identical_after` is asserted by a control, not
assumed.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir4_protocol as protocol  # noqa: E402

PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V6"

#: The two fields INC-V2-098 added to the pagination block and never told the
#: seal about. Named individually rather than derived from the census, so a
#: census that grows a third field refuses instead of being silently accepted --
#: the drift is the defect, and a self-widening contract cannot detect it.
FIELDS_ADDED_BY_INC_V2_098 = frozenset({"retries_total", "transport_retries"})

CORRECTED_PAGINATION_FIELDS = frozenset(
    protocol.CAPACITY_PAGINATION_FIELDS | FIELDS_ADDED_BY_INC_V2_098
)


@contextmanager
def corrected_pagination_contract() -> Iterator[frozenset[str]]:
    """Apply the corrected field set for one operation, then restore it.

    Scoped rather than assigned at import, so nothing else in the process
    silently inherits a contract SFIR6 chose. A module-level patch would make
    every other study's seal behave differently depending on whether this module
    happened to be imported.
    """
    original = protocol.CAPACITY_PAGINATION_FIELDS
    protocol.CAPACITY_PAGINATION_FIELDS = set(CORRECTED_PAGINATION_FIELDS)
    try:
        yield CORRECTED_PAGINATION_FIELDS
    finally:
        protocol.CAPACITY_PAGINATION_FIELDS = original


def frozen_module_digest() -> str:
    return hashlib.sha256((NS / "tools" / "sfir4_protocol.py").read_bytes()).hexdigest()


def seal_capacity(
    root: Path,
    charter_ref: Any,
    spent_ref: Any,
    metadata_path: Path,
    destination: Path,
    generated_at: str,
) -> Path:
    """`protocol.seal_capacity` under the corrected contract.

    Everything else is the frozen implementation, unchanged: the same identity
    proof, the same C/Q arithmetic, the same `C>=750` and `Q>=600`, the same
    refusal on shortfall. SFIR6 repairs a schema comparison. It does not touch
    the criterion.
    """
    before = frozen_module_digest()
    with corrected_pagination_contract():
        written = protocol.seal_capacity(
            root, charter_ref, spent_ref, metadata_path, destination, generated_at
        )
    if frozen_module_digest() != before:
        raise protocol.SFIR4Refused("the frozen protocol module changed during a seal")
    return written
