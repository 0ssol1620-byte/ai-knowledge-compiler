"""Derive ProductCoreDocument tuples from OSCAL / eCFR bytes and load hash-verified pairs.

Derivation is pure and deterministic, so the cache only needs the upstream bytes; every
derived document hash is re-checked against the frozen manifest and a mismatch refuses.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET
from akc_product_core.contracts import ProductCoreDocument, ProductCoreRegion

DEFAULT_MANIFEST = Path(__file__).with_name("manifest.json")

FamilyDocs = tuple[dict[str, ProductCoreDocument], frozenset[str]]


class CorpusError(RuntimeError):
    """Raised on any integrity, rights or upstream failure; nothing is repaired silently."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def make_doc(
    *,
    connector: str,
    native_id: str,
    title: str,
    parts: list[tuple[str, str]],
    key_prefix: str,
    version: str,
) -> ProductCoreDocument:
    """One document from (native_object_id, text) parts. No bbox is ever created."""
    regions = tuple(
        ProductCoreRegion(
            region_id=oid,
            page_index0=0,
            page_number1=1,
            order=i,
            text=text,
            bbox1000=None,
            native_object_id=oid,
            authority="official",
        )
        for i, (oid, text) in enumerate(parts)
    )
    body = "\n".join(text for _, text in parts)
    # identifier-safe; the manifest keeps the exact upstream version string
    version = re.sub(r"[^A-Za-z0-9._:-]", "-", version)
    return ProductCoreDocument(
        native_id=native_id,
        connector_type=connector,
        source_id=f"{connector}-{native_id}",
        source_version_id=version,
        immutable_object_key=f"{key_prefix}/{version}/{native_id}.json",
        ocr_object_key=f"{key_prefix}/{version}/{native_id}.txt",
        content_sha256=f"sha256:{sha256_hex(body.encode())}",
        title=title,
        source_filename=f"{native_id}.json",
        page_count=1,
        regions=regions,
    )


# --- NIST OSCAL -----------------------------------------------------------------


def _is_withdrawn(control: dict[str, Any]) -> bool:
    return any(
        p.get("name") == "status" and p.get("value") == "withdrawn"
        for p in control.get("props", [])
    )


# Spec 2.3: each statement/guidance part is one region keyed by its OSCAL part id.
# Merged-in SP 800-53A assessment parts are out of scope and are not descended into.
_REGION_PART_NAMES = frozenset({"statement", "item", "guidance"})


def _part_texts(parts: list[dict[str, Any]], out: list[tuple[str, str]], cid: str) -> None:
    for part in parts:
        if part.get("name") not in _REGION_PART_NAMES:
            continue
        prose = (part.get("prose") or "").strip()
        if prose:
            if not part.get("id"):
                raise CorpusError(f"{cid}: {part['name']} part with prose has no OSCAL id")
            out.append((part["id"], prose))
        _part_texts(part.get("parts", []), out, cid)


def _control_parts(control: dict[str, Any]) -> list[tuple[str, str]]:
    cid = control["id"]
    out: list[tuple[str, str]] = []
    _part_texts(control.get("parts", []), out, cid)
    withdrawn = _is_withdrawn(control)
    if withdrawn or not out:
        targets = [
            link["href"].lstrip("#")
            for link in control.get("links", [])
            if link.get("rel") == "incorporated-into"
        ]
        stub = control["title"]
        if withdrawn and targets:
            stub += f" (withdrawn: incorporated into {', '.join(targets)})"
        out.insert(0, (f"{cid}_title", stub))
    for enhancement in control.get("controls", []):
        out.extend(_control_parts(enhancement))
    return out


def docs_from_catalog(catalog: dict[str, Any]) -> dict[str, FamilyDocs]:
    """family id -> ({control id: document}, withdrawn control ids)."""
    cat = catalog["catalog"]
    version = cat["metadata"]["version"]
    result: dict[str, FamilyDocs] = {}
    for group in cat.get("groups", []):
        docs: dict[str, ProductCoreDocument] = {}
        withdrawn: set[str] = set()
        for control in group.get("controls", []):
            cid = control["id"]
            docs[cid] = make_doc(
                connector="nist-oscal",
                native_id=cid,
                title=control["title"],
                parts=_control_parts(control),
                key_prefix="nist-oscal",
                version=version,
            )
            if _is_withdrawn(control):
                withdrawn.add(cid)
        result[group["id"]] = (docs, frozenset(withdrawn))
    return result


# --- eCFR -----------------------------------------------------------------------


def _squash(text: str) -> str:
    return " ".join(text.split())


def docs_from_ecfr_xml(xml: bytes, version: str) -> dict[str, FamilyDocs]:
    """subpart letter -> ({section id: document}, empty: eCFR XML carries no withdrawn marker)."""
    root = ET.fromstring(xml)
    result: dict[str, FamilyDocs] = {}
    for subpart in root.iter():
        if subpart.get("TYPE") != "SUBPART":
            continue
        docs: dict[str, ProductCoreDocument] = {}
        for section in subpart.iter():
            if section.get("TYPE") != "SECTION":
                continue
            sid = re.sub(r"[^A-Za-z0-9._-]", "", (section.get("N") or "").replace("§", ""))
            head_el = section.find("HEAD")
            head = _squash("".join(head_el.itertext())) if head_el is not None else sid
            paras = [t for t in (_squash("".join(p.itertext())) for p in section.findall("P")) if t]
            parts = [(f"{sid}_p{i}", t) for i, t in enumerate(paras)] or [(f"{sid}_title", head)]
            if sid in docs:
                raise CorpusError(f"duplicate eCFR section id {sid!r} in subpart")
            docs[sid] = make_doc(
                connector="ecfr",
                native_id=sid,
                title=head,
                parts=parts,
                key_prefix="ecfr",
                version=version,
            )
        result[subpart.get("N") or "unknown"] = (docs, frozenset())
    return result


# --- loading --------------------------------------------------------------------


def read_verified(path: Path, expected_sha: str) -> bytes:
    if not path.is_file():
        raise CorpusError(f"cache file missing: {path}")
    data = path.read_bytes()
    if sha256_hex(data) != expected_sha:
        raise CorpusError(
            f"hash mismatch for {path}: manifest {expected_sha}, file {sha256_hex(data)}"
        )
    return data


def family_docs(
    manifest: dict[str, Any], source: str, snapshot_key: str, family: str, cache_dir: Path
) -> FamilyDocs:
    """Verified upstream bytes -> (docs, withdrawn) for one family at one snapshot."""
    if source == "nist-oscal":
        snap = next((s for s in manifest["snapshots"] if s["commit_sha"] == snapshot_key), None)
        if snap is None:
            raise CorpusError(f"snapshot {snapshot_key} not in manifest")
        raw = read_verified(cache_dir / snap["commit_sha"] / "catalog.json", snap["sha256"])
        fams = docs_from_catalog(json.loads(raw))
    else:
        esnap = next((s for s in manifest["ecfr_snapshots"] if s["date"] == snapshot_key), None)
        if esnap is None:
            raise CorpusError(f"eCFR snapshot {snapshot_key} not in manifest")
        raw = read_verified(cache_dir / "ecfr" / f"{esnap['date']}.xml", esnap["sha256"])
        fams = docs_from_ecfr_xml(raw, esnap["date"])
    if family not in fams:
        raise CorpusError(f"family {family} absent from snapshot {snapshot_key}")
    return fams[family]


def _side(
    manifest: dict[str, Any], pair: dict[str, Any], side: str, cache_dir: Path
) -> tuple[ProductCoreDocument, ...]:
    ref = pair[side]
    docs, _ = family_docs(manifest, pair["source"], ref["snapshot"], pair["family"], cache_dir)
    if {k: d.content_sha256 for k, d in docs.items()} != ref["docs"]:
        raise CorpusError(
            f"{pair['pair_id']} {side}: derived document hashes differ from the manifest"
        )
    return tuple(docs[k] for k in sorted(docs))


def load_pair(
    pair_id: str, cache_dir: Path | str, manifest_path: Path | str = DEFAULT_MANIFEST
) -> tuple[tuple[ProductCoreDocument, ...], tuple[ProductCoreDocument, ...]]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    pair = next((p for p in manifest["pairs"] if p["pair_id"] == pair_id), None)
    if pair is None:
        raise CorpusError(f"unknown pair {pair_id}")
    cache = Path(cache_dir)
    return _side(manifest, pair, "before", cache), _side(manifest, pair, "after", cache)
