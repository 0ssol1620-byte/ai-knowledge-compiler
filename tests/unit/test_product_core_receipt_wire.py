"""The /v2/compile wire is the candidate Core hashed, checked the way the site checks it.

The site (Foundation `dispatchProductCoreV2`) verifies `receipt.outputSha256` over
`canonicalJsonWireField(responseText, "candidate")`: it keeps every number token exactly as it
arrived. So the bytes Core sends must be the bytes Core hashed -- an OCR confidence hashed as `1`
and sent as `1.0` is CORE_V2_RECEIPT_INVALID.
"""

from __future__ import annotations

import hashlib
import json
import re

from akc_cir.base import canonical_json
from akc_product_core.api import create_product_core_app
from fastapi.testclient import TestClient

from .test_product_core_api import SECRET, _signed
from .test_product_core_bridge import RELEASE, _document, _request

_NUMBER = re.compile(r"(?:-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null)")


def _site_wire_field(raw: str, field: str) -> str | None:
    """Port of Foundation `nextjs/lib/canonical-json-wire.ts` (c1253462), rule for rule.

    Number tokens keep their wire spelling, keys sort by code point, duplicate keys and trailing
    text are refused (None). Strings are re-written as `JSON.stringify` writes them; Python's
    `ensure_ascii=False` writes the same bytes for every well-formed string.
    """
    offset = 0
    entries = 0
    selected: str | None = None

    def whitespace() -> None:
        nonlocal offset
        while offset < len(raw) and raw[offset] in " \t\r\n":
            offset += 1

    def string_token() -> str:
        nonlocal offset
        start = offset
        offset += 1
        while offset < len(raw):
            character = raw[offset]
            offset += 1
            if character == "\\":
                offset += 1
            elif character == '"':
                value = json.loads(raw[start:offset])
                if not isinstance(value, str):
                    raise ValueError("string required")
                return value
        raise ValueError("unterminated string")

    def value(depth: int) -> str:
        nonlocal offset, entries, selected
        entries += 1
        if depth > 128 or entries > 2_000_000:
            raise ValueError("JSON complexity exceeded")
        whitespace()
        character = raw[offset] if offset < len(raw) else ""
        if character == '"':
            return json.dumps(string_token(), ensure_ascii=False)
        if character == "{":
            offset += 1
            whitespace()
            fields: dict[str, str] = {}
            if raw[offset : offset + 1] != "}":
                while True:
                    whitespace()
                    if raw[offset : offset + 1] != '"':
                        raise ValueError("object key required")
                    key = string_token()
                    whitespace()
                    colon = raw[offset : offset + 1]
                    offset += 1
                    if key in fields or colon != ":":
                        raise ValueError("duplicate key or missing colon")
                    item = value(depth + 1)
                    fields[key] = item
                    if depth == 0 and key == field:
                        selected = item
                    whitespace()
                    if raw[offset : offset + 1] != ",":
                        break
                    offset += 1
            end = raw[offset : offset + 1]
            offset += 1
            if end != "}":
                raise ValueError("object end required")
            pairs = (f"{json.dumps(k, ensure_ascii=False)}:{fields[k]}" for k in sorted(fields))
            return "{" + ",".join(pairs) + "}"
        if character == "[":
            offset += 1
            whitespace()
            values: list[str] = []
            if raw[offset : offset + 1] != "]":
                while True:
                    values.append(value(depth + 1))
                    whitespace()
                    if raw[offset : offset + 1] != ",":
                        break
                    offset += 1
            end = raw[offset : offset + 1]
            offset += 1
            if end != "]":
                raise ValueError("array end required")
            return "[" + ",".join(values) + "]"
        token = _NUMBER.match(raw, offset)
        if token is None:
            raise ValueError("JSON value required")
        offset = token.end()
        return token.group(0)

    try:
        whitespace()
        if raw[offset : offset + 1] != "{":
            return None
        value(0)
        whitespace()
        return selected if offset == len(raw) else None
    except ValueError:
        return None


def _site_accepts(raw: str) -> bool:
    """The site's receipt check: outputSha256 over the candidate exactly as it is on the wire."""
    canonical = _site_wire_field(raw, "candidate")
    receipt = json.loads(raw)["receipt"]
    return canonical is not None and receipt["outputSha256"] == (
        "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    )


def _compile(client: TestClient, request_id: str, *, confidence: float, authority: str) -> str:
    document = _document("filing-a", "Revenue is 100 million won.")
    region = document.regions[0].model_copy(
        update={"confidence": confidence, "authority": authority}
    )
    request = _request(
        (document.model_copy(update={"regions": (region,)}),), request_id=request_id
    ).model_copy(update={"idempotency_key": "idem-receipt-wire"})
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))
    response = client.post(
        "/v2/compile", content=body.encode(), headers=_signed(body.encode(), request_id)
    )
    assert response.status_code == 200, response.text
    raw: str = response.text
    return raw


def _client() -> TestClient:
    return TestClient(create_product_core_app(hmac_secret=SECRET, core_release_digest=RELEASE))


def test_confidence_one_round_trips_through_the_sites_receipt_check() -> None:
    client = _client()
    raw = _compile(client, "wire-1", confidence=1.0, authority="official")

    assert _site_accepts(raw)
    # The integral floats reached the candidate, spelled as Core hashed them.
    assert '"confidence":1,' in raw or '"confidence":1}' in raw
    assert re.search(r'"(?:confidence|authorityScore)":-?[0-9]+\.0\b', raw) is None

    # The idempotent replay is a second return path; it must send the same bytes it hashed too.
    replay = _compile(client, "wire-2", confidence=1.0, authority="official")
    assert json.loads(replay)["receipt"]["requestId"] == "wire-2"
    assert _site_wire_field(replay, "candidate") == _site_wire_field(raw, "candidate")
    assert _site_accepts(replay)


def test_a_tampered_candidate_still_fails_the_receipt() -> None:
    raw = _compile(_client(), "wire-1", confidence=1.0, authority="official")
    assert _site_accepts(raw)

    changed = re.sub(r'"confidence":1([,}])', r'"confidence":0.9\1', raw, count=1)
    respelled = re.sub(r'"confidence":1([,}])', r'"confidence":1.0\1', raw, count=1)
    assert changed != raw and respelled != raw
    # A changed value fails, and so does the same value spelled differently: the check is on
    # the bytes, which is why Core has to send the bytes it hashed.
    assert not _site_accepts(changed)
    assert not _site_accepts(respelled)
    # A duplicate candidate key is refused outright, never resolved to either copy.
    assert _site_wire_field(raw[:-1] + ',"candidate":{}}', "candidate") is None


def test_non_integral_floats_and_ints_keep_their_spelling_and_round_trip() -> None:
    raw = _compile(_client(), "wire-1", confidence=0.5, authority="informal")

    assert '"confidence":0.5' in raw
    assert '"pageNumber1":1' in raw
    candidate = json.loads(raw)["candidate"]
    assert '"confidence":0.5' in canonical_json(candidate)
    assert _site_accepts(raw)
