"""WO-D12-5: deterministic generated fault cases for the U06 equivalence gate.

Every case is labelled ``provenance="generated"``. Mutations are applied to the *after* side of a
base pair; each mutated document gets a recomputed ``content_sha256`` (and its content-addressed
object keys follow) and is re-validated through ``ProductCoreDocument``.

CLI: ``py -3.13 -m benchmark.u06_equivalence.faults --pairs P.json --out DIR [--seed N] [--n N]``
where pairs.json is ``[{"before": [<doc wire>...], "after": [<doc wire>...]}, ...]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from akc_cir.identity import document_version_id
from akc_product_core.contracts import ProductCoreDocument

Docs = tuple[ProductCoreDocument, ...]
GENERATOR = "u06-faults"
GENERATOR_VERSION = "1"


class _Rng:
    """Tiny deterministic generator (sha256 counter): stable across Python versions."""

    def __init__(self, seed: int) -> None:
        self._seed, self._n = seed, 0

    def randrange(self, n: int) -> int:
        self._n += 1
        digest = hashlib.sha256(f"{self._seed}:{self._n}".encode()).digest()
        return int.from_bytes(digest[:8], "big") % n

    def choice(self, items: Sequence[Any]) -> Any:
        return items[self.randrange(len(items))]


@dataclass(frozen=True)
class FaultCase:
    case_id: str
    fault_class: str
    seed: int
    parent_pair_id: int
    before_docs: Docs
    after_docs: Docs
    expected: Literal["equal_or_hold", "hold"]
    provenance: Literal["generated"] = "generated"
    generator: str = GENERATOR
    generator_version: str = GENERATOR_VERSION


def _content_hash(doc: ProductCoreDocument) -> str:
    payload = [
        [r.region_id, r.page_number1, r.order, r.block_type.value, r.text, r.authority]
        for r in sorted(doc.regions, key=lambda r: r.order)
    ]
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(blob).hexdigest()


def _rebuild(doc: ProductCoreDocument, **changes: Any) -> ProductCoreDocument:
    """Apply changes, recompute the content hash and re-key the content-addressed object keys."""
    data = {name: getattr(doc, name) for name in type(doc).model_fields} | changes
    data["regions"] = [
        r if isinstance(r, dict) else r.model_dump(by_alias=False) for r in data["regions"]
    ]
    out = ProductCoreDocument.model_validate(data)
    new = _content_hash(out)
    if new == _content_hash(doc):
        return out  # same content: keep the original hash, keys and derived version id
    old_hex, new_hex = doc.content_sha256.removeprefix("sha256:"), new.removeprefix("sha256:")
    data["content_sha256"] = new
    for key in ("immutable_object_key", "ocr_object_key"):
        data[key] = data[key].replace(old_hex, new_hex)
    # the compiler requires source_version_id == document_version_id(source, content_sha256)
    data["source_version_id"] = (
        document_version_id(source=data["source_id"], content_sha256=new)
        if data["source_id"]
        else None
    )
    return ProductCoreDocument.model_validate(data)


def _edit_region(doc: ProductCoreDocument, index: int, **changes: Any) -> ProductCoreDocument:
    regions = [r.model_dump(by_alias=False) for r in doc.regions]
    regions[index] |= changes
    return _rebuild(doc, regions=regions)


def _replace(docs: Docs, i: int, doc: ProductCoreDocument) -> Docs:
    return (*docs[:i], doc, *docs[i + 1 :])


def _pick(rng: _Rng, docs: Docs, ok: Callable[[ProductCoreDocument], bool]) -> int | None:
    eligible = [i for i, d in enumerate(docs) if ok(d)]
    return rng.choice(eligible) if eligible else None


def _region_pick(rng: _Rng, docs: Docs, ok: Callable[[Any], bool]) -> tuple[int, int] | None:
    eligible = [(i, j) for i, d in enumerate(docs) for j, r in enumerate(d.regions) if ok(r)]
    return rng.choice(eligible) if eligible else None


def _text_edit(
    docs: Docs, rng: _Rng, ok: Callable[[str], bool], fn: Callable[[str], str]
) -> Docs | None:
    hit = _region_pick(rng, docs, lambda r: ok(r.text) and fn(r.text) != r.text)
    if hit is None:
        return None
    i, j = hit
    return _replace(docs, i, _edit_region(docs[i], j, text=fn(docs[i].regions[j].text)))


def _delete(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    if len(after) < 2:
        return None
    k = rng.randrange(len(after))
    return after[:k] + after[k + 1 :]


def _empty_after(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    # one document loses every region, i.e. disappears; a one-document pair ends empty
    if not after:
        return None
    k = rng.randrange(len(after))
    return after[:k] + after[k + 1 :]


def _add(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    if not after:
        return None
    src = after[rng.randrange(len(after))]
    regions = [r.model_dump(by_alias=False) for r in src.regions]
    regions[0]["text"] += " (added source)"
    # identity is left for the compiler to derive from native_id; none is invented here
    kw: dict[str, Any] = {
        "native_id": f"{src.native_id}-added",
        "source_filename": ("added-" + src.source_filename)[:500],
        "source_id": None,
        "source_version_id": None,
    }
    return (*after, _rebuild(src, regions=regions, **kw))


def _reorder(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: len(d.regions) >= 2)
    if i is None:
        return None
    orders = [r.order for r in after[i].regions]
    regions = [
        r.model_dump(by_alias=False) | {"order": o}
        for r, o in zip(after[i].regions, reversed(orders), strict=True)
    ]
    return _replace(after, i, _rebuild(after[i], regions=regions))


def _duplicate(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: True)
    if i is None:
        return None
    doc = after[i]
    src = doc.regions[rng.randrange(len(doc.regions))]
    dup = src.model_dump(by_alias=False) | {
        "region_id": f"{src.region_id}-dup"[:256],
        "native_object_id": f"{src.native_object_id}-dup" if src.native_object_id else None,
        "order": max(r.order for r in doc.regions) + 1,
    }
    return _replace(
        after, i, _rebuild(doc, regions=[*(r.model_dump(by_alias=False) for r in doc.regions), dup])
    )


def _nfd(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    return _text_edit(after, rng, lambda t: True, lambda t: unicodedata.normalize("NFD", t))


def _whitespace(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    return _text_edit(after, rng, lambda t: " " in t, lambda t: t.replace(" ", "  ", 1))


def _bump(match: re.Match[str]) -> str:
    return str(int(match.group()) + 1)


def _numeric(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    return _text_edit(
        after, rng, lambda t: bool(re.search(r"\d", t)), lambda t: re.sub(r"\d+", _bump, t, count=1)
    )


def _flip(text: str) -> str:
    return text.replace(" not ", " ", 1) if " not " in text else text.replace(" ", " not ", 1)


def _negation(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    return _text_edit(after, rng, lambda t: " " in t, _flip)


def _title(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: True)
    if i is None:
        return None
    return _replace(after, i, _rebuild(after[i], title=after[i].title[:480] + " (renamed)"))


def _page_move(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: True)
    if i is None:
        return None
    doc = after[i]
    j = rng.randrange(len(doc.regions))
    r = doc.regions[j]
    regions = [x.model_dump(by_alias=False) for x in doc.regions]
    regions[j] |= {"page_index0": r.page_index0 + 1, "page_number1": r.page_number1 + 1}
    count = max(doc.page_count, r.page_number1 + 1)
    return _replace(after, i, _rebuild(doc, regions=regions, page_count=count))


def _authority(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    hit = _region_pick(rng, after, lambda r: True)
    if hit is None:
        return None
    i, j = hit
    now = "authoritative" if after[i].regions[j].authority == "informal" else "informal"
    return _replace(after, i, _edit_region(after[i], j, authority=now))


def _truncate(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: len(d.regions) >= 2)
    if i is None:
        return None
    keep = sorted(after[i].regions, key=lambda r: r.order)[: len(after[i].regions) // 2]
    return _replace(
        after, i, _rebuild(after[i], regions=[r.model_dump(by_alias=False) for r in keep])
    )


def _rename(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: True)
    if i is None:
        return None
    # the content hash covers the regions only, so a pure rename keeps it unchanged
    name = after[i].source_filename[:490] + ".renamed"
    return _replace(after, i, _rebuild(after[i], source_filename=name))


def _swap(_b: Docs, after: Docs, rng: _Rng) -> Docs | None:
    i = _pick(rng, after, lambda d: len({r.text for r in d.regions}) >= 2)
    if i is None:
        return None
    doc = after[i]
    while True:
        a, b = rng.randrange(len(doc.regions)), rng.randrange(len(doc.regions))
        if doc.regions[a].text != doc.regions[b].text:
            break
    regions = [r.model_dump(by_alias=False) for r in doc.regions]
    regions[a]["text"], regions[b]["text"] = regions[b]["text"], regions[a]["text"]
    return _replace(after, i, _rebuild(doc, regions=regions))


def _revert(before: Docs, _a: Docs, _rng: _Rng) -> Docs | None:
    return before


_Mutation = Callable[[Docs, Docs, _Rng], Docs | None]
FAULT_CLASSES: dict[str, tuple[_Mutation, Literal["equal_or_hold", "hold"]]] = {
    "delete_source": (_delete, "equal_or_hold"),
    "add_source": (_add, "equal_or_hold"),
    "reorder_regions": (_reorder, "equal_or_hold"),
    "duplicate_region_text": (_duplicate, "hold"),
    "unicode_nfc_nfd_variant": (_nfd, "equal_or_hold"),
    "whitespace_only": (_whitespace, "equal_or_hold"),
    "numeric_change": (_numeric, "equal_or_hold"),
    "negation_flip": (_negation, "equal_or_hold"),
    "title_rename": (_title, "equal_or_hold"),
    "region_page_move": (_page_move, "equal_or_hold"),
    "authority_change": (_authority, "equal_or_hold"),
    "truncate_document": (_truncate, "equal_or_hold"),
    "source_rename_same_content": (_rename, "equal_or_hold"),
    "empty_after_revision": (_empty_after, "equal_or_hold"),
    "swap_two_regions_text": (_swap, "equal_or_hold"),
    "revert_to_before": (_revert, "equal_or_hold"),
}


def generate(
    base_pairs: Sequence[tuple[Docs, Docs]], *, n: int = 1000, seed: int
) -> list[FaultCase]:
    if not base_pairs:
        raise ValueError("no base pairs supplied")
    for k, (before, after) in enumerate(base_pairs):
        if not any(d.regions for d in (*before, *after)):
            raise ValueError(f"base pair {k} has no regions")
    classes = list(FAULT_CLASSES)
    cases: list[FaultCase] = []
    for i in range(n):
        name = classes[i % len(classes)]
        mutate, expected = FAULT_CLASSES[name]
        case_seed = seed * 1_000_003 + i
        rng = _Rng(case_seed)
        start = rng.randrange(len(base_pairs))
        for off in range(len(base_pairs)):
            k = (start + off) % len(base_pairs)
            before, after = base_pairs[k]
            result = mutate(tuple(before), tuple(after), rng)
            if result is not None:
                break
        else:
            raise ValueError(f"fault class {name} applies to none of the base pairs")
        cases.append(
            FaultCase(f"u06-fault-{i:04d}", name, case_seed, k, tuple(before), result, expected)
        )
    return cases


def _doc_hash(doc: ProductCoreDocument) -> str:
    return "sha256:" + hashlib.sha256(doc.model_dump_json(by_alias=True).encode()).hexdigest()


def manifest(cases: Sequence[FaultCase], seed: int) -> dict[str, Any]:
    return {
        "generator": GENERATOR,
        "generatorVersion": GENERATOR_VERSION,
        "provenance": "generated",
        "seed": seed,
        "caseCount": len(cases),
        "cases": [
            {
                "caseId": c.case_id,
                "faultClass": c.fault_class,
                "seed": c.seed,
                "parentPairId": c.parent_pair_id,
                "expected": c.expected,
                "beforeDocHashes": [_doc_hash(d) for d in c.before_docs],
                "afterDocHashes": [_doc_hash(d) for d in c.after_docs],
            }
            for c in cases
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pairs", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--n", type=int, default=1000)
    a = p.parse_args(argv)
    raw = json.loads(a.pairs.read_text(encoding="utf-8"))
    pairs = [
        (
            tuple(ProductCoreDocument.model_validate(d) for d in x["before"]),
            tuple(ProductCoreDocument.model_validate(d) for d in x["after"]),
        )
        for x in raw
    ]
    cases = generate(pairs, n=a.n, seed=a.seed)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "faults_manifest.json").write_text(
        json.dumps(manifest(cases, a.seed), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
