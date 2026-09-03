"""Canonical bytes for the revision digest, matched to the Node client.

`nextjs/lib/core-runtime-revision.ts` recomputes `receipt.outputSha256` over the
revision body it received and refuses the response if it disagrees. That check is
only worth having if both sides serialise the same object to the same bytes, and
the two obvious ways to get that wrong are both live here.

The first is key ordering. The initial-compile path in `core-runtime-v2.ts` sorts
with `String.prototype.localeCompare`, whose answer depends on the ICU locale of
the process. That is survivable when both ends are the same Node process and is
not survivable across a language boundary, so the revision path sorts by code
point on both sides -- `left < right` in TypeScript, `sorted()` here.

The second is floats. `JSON.stringify(1)` is `"1"` and `json.dumps(1.0)` is
`"1.0"`, so a single float anywhere under the digest makes the two disagree for
reasons that have nothing to do with the compile. Rather than write a JS number
formatter in Python, this refuses floats outright and the contract carries
coverage as an integer permille.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

CANONICAL_FLOAT_REFUSED = (
    "the revision digest carries no floats; express a ratio as an integer permille"
)


def canonicalize(value: Any) -> str:
    """Serialise exactly as `canonicalizeRevision` in the Node client does."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None or isinstance(value, (str, int)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, float):
        raise TypeError(CANONICAL_FLOAT_REFUSED)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonicalize(item) for item in value) + "]"
    if isinstance(value, dict):
        body = ",".join(
            json.dumps(str(key), ensure_ascii=False, separators=(",", ":"))
            + ":"
            + canonicalize(item)
            for key, item in sorted(value.items())
            if item is not None
        )
        return "{" + body + "}"
    raise TypeError(f"not canonicalisable: {type(value).__name__}")


def digest(payload: str) -> str:
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def artifact_content(body: Any) -> str:
    """The bytes an artifact body stands for.

    A string body is the content itself. Half the package a caller assembles is
    CSV, JSON Lines and Turtle, and wrapping those in JSON quoting to force one
    convention would make the digest of a rebuilt file disagree with the digest
    of the file it replaces. Anything else is a document, and its content is its
    canonical form -- the same form the receipt is sealed over.
    """
    return body if isinstance(body, str) else canonicalize(body)
