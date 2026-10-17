"""KB1 item-level rights manifest: validate and write, never fetch.

Design: KOREAN-BENCHMARK-DESIGN-2026-10-17.md §3 (corpus terms), §5.10 (fail-closed),
§5.11 (leakage), §8 KB-F2, §9 KB-A5. Output entries follow ``KB1-PREREG.json``
``dataset.rights_item_schema`` (revision ``kb1-prereg-draft-r1``, sha256 ``cb51fd44…``),
so ``rights_by_item`` can be copied into the preregistration as is.

The person who retrieved an item writes one input entry per item; this tool checks it
and writes the manifest. It has no network code path: it never resolves, opens or
fetches a URL and never re-hashes the item. ``sha256`` is the hash the person recorded
when they saved the file; this tool cannot check that the file behind ``url`` still
has it.

**The licence bar below is a proposal, not a founder decision.** KB-F2 (D-31) is
undecided. "Accepted" means "passes the proposed KB-F2 bar", not "cleared". Every
manifest carries ``policy_status`` saying so. No data licence below says anything
about model weights, code, hosted-API terms or third-party patents: those are separate
licences and a KOGL marking clears none of them (design §3 FTO rule).

Licence bar (``kogl_type`` token -> verdict). Terms quotes: design §3 table rows
C1-C22 and ``korean-benchmark-receipts/TERMS-QUOTES-20261017.json`` (sha256
``2f29a949…``, retrieved 2026-10-17 by WebFetch, quotes extracted by a small model;
re-read the live page before any legal reliance; not legal advice).

========================  =======  ============================  ==================================
``kogl_type``             verdict  rejection code                basis
========================  =======  ============================  ==================================
``"0"``                   accept   -                             §3 C2 (kogl.or.kr/info/license.do,
                                                                 "출처표시 조건 없음"; the receipt
                                                                 holds no type-0 quote)
``"1"``                   accept   -                             §3 C1; receipt ``kogl-type1``
                                                                 ("상업적 활용 여부에 관계없이 ...
                                                                 변형하여 이용할 수 있습니다.")
``"2"``                   reject   ``KOGL_TYPE_2_NC``            §3 C3 (출처표시 + 상업적 이용금지)
``"3"``                   reject   ``KOGL_TYPE_3_ND``            §3 C4 (출처표시 + 변경금지;
                                                                 internal use is a founder call,
                                                                 not taken)
``"4"``                   reject   ``KOGL_TYPE_4_NC_ND``         §3 C3 (상업적 이용금지 + 변경금지)
``"ai_only"``             reject   ``KOGL_AI_TYPE_ONLY``         §3 C5; receipt ``kogl-types-ai``
                                                                 (AI type alone covers AI training
                                                                 data only; evaluation is not
                                                                 training. AI type next to type 0/1
                                                                 is recorded as that type)
``"nc"``                  reject   ``LICENCE_NC``                §3 C19 (any non-commercial licence)
``"nd"``                  reject   ``LICENCE_ND``                §3 (any no-derivatives licence)
``"ai_hub"``              reject   ``AI_HUB_TERMS``              §3 C14; receipt
                                                                 ``aihub-usage-policy``
                                                                 ("학습용으로만", 제5항 열람·제공
                                                                 금지, 국외 반출)
``"unlicensed"``          reject   ``UNLICENSED``                §3 C15-C18 (readable is not
                                                                 reusable)
``"expired"``             reject   ``FOUNDER_DECISION_PENDING``  §3 C2; receipt ``kogl-expired``.
                                                                 KB-F2 recommends accepting it;
                                                                 undecided, outside the KB-A5 bar
``"copyright_act_art7"``  reject   ``FOUNDER_DECISION_PENDING``  §3 C10-C12; receipt
                                                                 ``copyright-act-art7`` (easylaw
                                                                 quote, not checked against
                                                                 law.go.kr). A statute carries no
                                                                 marking, so ``marking_scope``
                                                                 does not fit it; KB-F2 decides
anything else             reject   ``KOGL_TYPE_UNKNOWN``         includes the preregistration's
                                                                 ``"other"``
========================  =======  ============================  ==================================

Other rules the code enforces:

* ``marking_scope`` must be ``"item"``. A board- or site-level statement is not
  item-level evidence (§3 C1 note, §5.10, ``specimen-candidates.json`` ``koreanRule``):
  ``MARKING_SCOPE_NOT_ITEM`` until the founder accepts it.
* ``url`` must be an absolute http(s) URL with a host and an item path or query (a
  bare site root is not an item), no user-info and no whitespace or control character:
  ``ITEM_URL_INVALID``. A URL on ``aihub.or.kr`` is ``AI_HUB_TERMS`` whatever
  ``kogl_type`` claims. A URL on a dataset mirror (``huggingface.co``, ``hf.co``) is
  ``ITEM_URL_NOT_ORIGINAL_SOURCE``: KB-F2 says KoOCR-Bench originals are re-fetched
  from the government source, and a page already public in a benchmark may have leaked
  into training (§5.11).
* ``retrieved_on`` is ``YYYY-MM-DD``; ``sha256`` is 64 lower-case hex; every field is a
  non-empty string with no surrounding whitespace; no field outside the schema.
* An ``item_id`` or ``sha256`` that appears in more than one entry rejects every one of
  those entries (``ITEM_ID_DUPLICATE``, ``SHA256_DUPLICATE``): exact duplicates are merged
  by a person before the family split (§5.2), never resolved by input order here.
* A rejected entry is kept, with every reason, in ``rejected``; it never reaches
  ``rights_by_item``. A malformed input document writes nothing (exit 2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

INPUT_SCHEMA = "tavonel.kb1.rights_input.v1"
MANIFEST_SCHEMA = "tavonel.kb1.rights_manifest.v1"
TOOL_REVISION = "kb1-rights-r1"
POLICY_STATUS = (
    "PROPOSED_NOT_FOUNDER_ACCEPTED: KB-F2 / D-31 undecided; accepted = KOGL type 0 or 1 "
    "marked on the item itself"
)
TERMS_RECEIPT = {
    "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/"
    "korean-benchmark-receipts/TERMS-QUOTES-20261017.json",
    "sha256": "2f29a94901aa959261978be79c50a945deedf8983851fe81d24c62240acb5e7e",
}
FIELDS = ("item_id", "url", "kogl_type", "marking_scope", "retrieved_on", "sha256", "family_id")


class Reject(StrEnum):
    ENTRY_NOT_OBJECT = "ENTRY_NOT_OBJECT"
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_EMPTY_OR_NOT_STRING = "FIELD_EMPTY_OR_NOT_STRING"
    FIELD_UNKNOWN = "FIELD_UNKNOWN"
    ITEM_ID_DUPLICATE = "ITEM_ID_DUPLICATE"
    ITEM_URL_INVALID = "ITEM_URL_INVALID"
    ITEM_URL_NOT_ORIGINAL_SOURCE = "ITEM_URL_NOT_ORIGINAL_SOURCE"
    KOGL_TYPE_2_NC = "KOGL_TYPE_2_NC"
    KOGL_TYPE_3_ND = "KOGL_TYPE_3_ND"
    KOGL_TYPE_4_NC_ND = "KOGL_TYPE_4_NC_ND"
    KOGL_AI_TYPE_ONLY = "KOGL_AI_TYPE_ONLY"
    LICENCE_NC = "LICENCE_NC"
    LICENCE_ND = "LICENCE_ND"
    AI_HUB_TERMS = "AI_HUB_TERMS"
    UNLICENSED = "UNLICENSED"
    FOUNDER_DECISION_PENDING = "FOUNDER_DECISION_PENDING"
    KOGL_TYPE_UNKNOWN = "KOGL_TYPE_UNKNOWN"
    MARKING_SCOPE_NOT_ITEM = "MARKING_SCOPE_NOT_ITEM"
    RETRIEVED_ON_INVALID = "RETRIEVED_ON_INVALID"
    SHA256_INVALID = "SHA256_INVALID"
    SHA256_DUPLICATE = "SHA256_DUPLICATE"


ACCEPTED_KOGL_TYPES = frozenset({"0", "1"})
REJECTED_KOGL_TYPES = {
    "2": Reject.KOGL_TYPE_2_NC,
    "3": Reject.KOGL_TYPE_3_ND,
    "4": Reject.KOGL_TYPE_4_NC_ND,
    "ai_only": Reject.KOGL_AI_TYPE_ONLY,
    "nc": Reject.LICENCE_NC,
    "nd": Reject.LICENCE_ND,
    "ai_hub": Reject.AI_HUB_TERMS,
    "unlicensed": Reject.UNLICENSED,
    "expired": Reject.FOUNDER_DECISION_PENDING,
    "copyright_act_art7": Reject.FOUNDER_DECISION_PENDING,
}
DENIED_HOSTS = {
    "aihub.or.kr": Reject.AI_HUB_TERMS,
    "huggingface.co": Reject.ITEM_URL_NOT_ORIGINAL_SOURCE,
    "hf.co": Reject.ITEM_URL_NOT_ORIGINAL_SOURCE,
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_URL_FORBIDDEN = re.compile(r"[\s\x00-\x1f\x7f]")


class ManifestInputError(ValueError):
    """The input is not a rights input document; no manifest is written."""


def _reason(code: Reject, field: str | None = None) -> dict[str, str]:
    return {"code": code.value} if field is None else {"code": code.value, "field": field}


def _url_reasons(url: str) -> list[dict[str, str]]:
    if _URL_FORBIDDEN.search(url):  # urlsplit would silently drop tabs and newlines
        return [_reason(Reject.ITEM_URL_INVALID, "url")]
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        has_userinfo = parts.username is not None or parts.password is not None
        _ = parts.port  # raises ValueError on a malformed port
    except ValueError:
        return [_reason(Reject.ITEM_URL_INVALID, "url")]
    if (
        parts.scheme not in ("http", "https")
        or not host
        or has_userinfo
        or (parts.path in ("", "/") and not parts.query)
    ):
        return [_reason(Reject.ITEM_URL_INVALID, "url")]
    return [
        _reason(code, "url")
        for domain, code in DENIED_HOSTS.items()
        if host == domain or host.endswith("." + domain)
    ]


def _entry_reasons(entry: object) -> list[dict[str, str]]:
    if not isinstance(entry, dict):
        return [_reason(Reject.ENTRY_NOT_OBJECT)]
    reasons = [_reason(Reject.FIELD_UNKNOWN, str(k)) for k in entry if k not in FIELDS]
    ok: dict[str, str] = {}
    for field in FIELDS:
        if field not in entry:
            reasons.append(_reason(Reject.FIELD_MISSING, field))
            continue
        value = entry[field]
        if not isinstance(value, str) or not value or value != value.strip():
            reasons.append(_reason(Reject.FIELD_EMPTY_OR_NOT_STRING, field))
            continue
        ok[field] = value
    if "url" in ok:
        reasons += _url_reasons(ok["url"])
    if "kogl_type" in ok and ok["kogl_type"] not in ACCEPTED_KOGL_TYPES:
        code = REJECTED_KOGL_TYPES.get(ok["kogl_type"], Reject.KOGL_TYPE_UNKNOWN)
        reasons.append(_reason(code, "kogl_type"))
    if "marking_scope" in ok and ok["marking_scope"] != "item":
        reasons.append(_reason(Reject.MARKING_SCOPE_NOT_ITEM, "marking_scope"))
    if "retrieved_on" in ok:
        try:
            if not _DATE.fullmatch(ok["retrieved_on"]):
                raise ValueError
            date.fromisoformat(ok["retrieved_on"])
        except ValueError:
            reasons.append(_reason(Reject.RETRIEVED_ON_INVALID, "retrieved_on"))
    if "sha256" in ok and not _SHA256.fullmatch(ok["sha256"]):
        reasons.append(_reason(Reject.SHA256_INVALID, "sha256"))
    return reasons


def _string_field(entry: object, field: str) -> str | None:
    value = entry.get(field) if isinstance(entry, dict) else None
    return value if isinstance(value, str) else None


def build_manifest(document: Any, input_sha256: str) -> dict[str, Any]:
    """Validate a rights input document and return the manifest (pure; no I/O)."""
    if not isinstance(document, dict) or document.get("schema") != INPUT_SCHEMA:
        raise ManifestInputError(f"input must be an object with schema {INPUT_SCHEMA!r}")
    if set(document) != {"schema", "items"} or not isinstance(document["items"], list):
        raise ManifestInputError("input must have exactly 'schema' and an 'items' list")
    items: list[object] = document["items"]
    if not items:
        raise ManifestInputError("input has no items; an empty manifest is not written")

    reasons = [_entry_reasons(entry) for entry in items]
    for field, code in (("item_id", Reject.ITEM_ID_DUPLICATE), ("sha256", Reject.SHA256_DUPLICATE)):
        values = [_string_field(entry, field) for entry in items]
        seen = Counter(v for v in values if v is not None)
        for index, value in enumerate(values):
            if value is not None and seen[value] > 1:
                reasons[index].append(_reason(code, field))

    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, Any]] = []
    for index, (entry, entry_reasons) in enumerate(zip(items, reasons, strict=True)):
        if entry_reasons:
            rejected.append(
                {
                    "index": index,
                    "item_id": _string_field(entry, "item_id"),
                    "reasons": entry_reasons,
                }
            )
        else:
            assert isinstance(entry, dict)
            accepted.append({field: entry[field] for field in FIELDS})
    accepted.sort(key=lambda row: row["item_id"])
    return {
        "schema": MANIFEST_SCHEMA,
        "tool_revision": TOOL_REVISION,
        "policy_status": POLICY_STATUS,
        "terms_receipt": TERMS_RECEIPT,
        "input_sha256": input_sha256,
        "counts": {
            "input_entries": len(items),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "rights_by_item": accepted,
        "rejected": rejected,
    }


def render(manifest: dict[str, Any]) -> bytes:
    """Deterministic UTF-8, LF-only bytes of a manifest."""
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    return text.encode("utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a KB1 rights input JSON and write the manifest. Never fetches."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    raw = args.input.read_bytes()
    try:
        manifest = build_manifest(json.loads(raw), hashlib.sha256(raw).hexdigest())
    except (ManifestInputError, json.JSONDecodeError, UnicodeDecodeError) as error:
        print(f"REFUSED: {error}")
        return 2
    payload = render(manifest)
    args.out.write_bytes(payload)
    counts = manifest["counts"]
    by_code = Counter(r["code"] for row in manifest["rejected"] for r in row["reasons"])
    print(f"accepted {counts['accepted']} / {counts['input_entries']} input entries")
    print(f"rejected {counts['rejected']} / {counts['input_entries']} input entries")
    for code, n in sorted(by_code.items()):
        print(f"  {code}: {n}")
    print(f"policy_status {manifest['policy_status']}")
    print(f"manifest_sha256 {hashlib.sha256(payload).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
