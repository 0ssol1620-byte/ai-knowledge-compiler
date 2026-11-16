"""Screen corpus manifest: deterministic 300/100 split, freeze, verify, holdout guard.

Whole documents only; pages are addressed as ``doc_id#p``. The rights fields record
what a person decided; this module never infers them.
"""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from benchmark.v6.contracts import ContractError, canonical_sha256, require_sha256

RIGHTS_CLASSES = ("owned", "public_domain", "permissive_licence", "synthetic")
SPLITS = ("dev", "holdout")
PURPOSES = ("tune", "calibrate", "evaluate_frozen")
PROFILES = ("screen", "eg04")
_DOC_FIELDS = (
    "doc_id", "source_sha256", "byte_size", "page_count", "stratum", "language",
    "document_class", "rights",
)
_RIGHTS_FIELDS = (
    "source_url", "licence_id", "licence_snapshot_sha256", "rights_class",
    "redistribution", "recorded_by", "recorded_at",
)
HOLDOUT_MAX_OVERSHOOT = 10
EG04_MIN_PAGES, EG04_MIN_DOCS, EG04_MIN_CLASSES = 1500, 150, 10


class HoldoutSealedError(RuntimeError):
    """Holdout already evaluated under another frozen recipe, or asked for tuning."""


def _check_doc(doc: dict[str, Any]) -> None:
    for f in _DOC_FIELDS:
        if f not in doc:
            raise ContractError(f"document missing field {f!r}")
    name = doc["doc_id"]
    if not isinstance(name, str) or not name:
        raise ContractError("doc_id must be a non-empty string")
    if "/" in name or "\\" in name or name in (".", "..") or Path(name).is_absolute():
        raise ContractError(f"doc_id {name!r} must be a plain file name inside the corpus root")
    require_sha256(doc["source_sha256"], "source_sha256")
    for f in ("byte_size", "page_count"):
        if not isinstance(doc[f], int) or isinstance(doc[f], bool) or doc[f] < 1:
            raise ContractError(f"{name}: {f} must be a positive integer")
    for f in ("stratum", "language", "document_class"):
        if not isinstance(doc[f], str) or not doc[f]:
            raise ContractError(f"{name}: {f} must be a non-empty string")
    rights = doc["rights"]
    if not isinstance(rights, dict):
        raise ContractError(f"{name}: rights must be an object")
    for f in _RIGHTS_FIELDS:
        if f not in rights:
            raise ContractError(f"{name}: rights missing field {f!r}")
    if rights["rights_class"] not in RIGHTS_CLASSES:
        raise ContractError(f"{name}: rights_class {rights['rights_class']!r} not allowed")
    if not isinstance(rights["redistribution"], bool):
        raise ContractError(f"{name}: rights.redistribution must be a boolean")
    snap = rights["licence_snapshot_sha256"]
    if snap is None:
        if rights["rights_class"] not in ("owned", "synthetic"):
            raise ContractError(f"{name}: licence snapshot required for {rights['rights_class']}")
    else:
        require_sha256(snap, "licence_snapshot_sha256")
    for f in ("source_url", "licence_id", "recorded_by", "recorded_at"):
        if not isinstance(rights[f], str) or not rights[f]:
            raise ContractError(f"{name}: rights.{f} must be a non-empty string")
    if "split" in doc and doc["split"] not in SPLITS:
        raise ContractError(f"{name}: split {doc['split']!r} not in {SPLITS}")


def _check_unique(docs: list[dict[str, Any]]) -> None:
    ids: set[str] = set()
    hashes: set[str] = set()
    for d in docs:
        if d["doc_id"] in ids:
            raise ContractError(f"duplicate doc_id {d['doc_id']!r}")
        if d["source_sha256"] in hashes:
            # the same bytes under two ids would put one document in both splits
            raise ContractError(f"source {d['source_sha256']} appears in more than one document")
        ids.add(d["doc_id"])
        hashes.add(d["source_sha256"])


def _order_key(salt: str, doc: dict[str, Any]) -> tuple[str, str]:
    return hashlib.sha256((salt + doc["source_sha256"]).encode()).hexdigest(), doc["doc_id"]


def _pages(docs: Iterable[dict[str, Any]]) -> int:
    return sum(d["page_count"] for d in docs)


def assign_split(
    docs: list[dict[str, Any]], salt: str, dev_pages: int = 300, holdout_pages: int = 100
) -> list[dict[str, Any]]:
    """Return copies with ``split`` set. Independent of input order; whole documents only."""
    docs = [dict(d) for d in docs]
    for d in docs:
        _check_doc(d)
    _check_unique(docs)
    total = _pages(docs)
    cap = holdout_pages + HOLDOUT_MAX_OVERSHOOT
    ordered = sorted(docs, key=lambda x: _order_key(salt, x))
    by_stratum: dict[str, list[dict[str, Any]]] = {}
    for d in ordered:
        d["split"] = "dev"
        by_stratum.setdefault(d["stratum"], []).append(d)
    held = 0
    for name, group in by_stratum.items():  # every stratum first gets its smallest document
        if len(group) < 2:
            raise ContractError(f"stratum {name!r} has one document and cannot land in both splits")
        small = min(group[:-1], key=lambda x: x["page_count"])  # last doc stays in dev
        small["split"] = "holdout"
        held += small["page_count"]
    if held > cap:
        raise ContractError(f"one document per stratum already puts {held} pages in the holdout")
    for group in by_stratum.values():
        quota = holdout_pages * _pages(group) / total
        got = sum(d["page_count"] for d in group if d["split"] == "holdout")
        for d in group[:-1]:
            if got >= quota:
                break
            if d["split"] == "dev" and got + d["page_count"] <= quota and (
                held + d["page_count"] <= cap
            ):
                d["split"] = "holdout"
                got += d["page_count"]
                held += d["page_count"]
    for d in ordered:  # top up to the floor, never emptying a stratum's dev side
        if held >= holdout_pages:
            break
        if (
            d["split"] == "dev"
            and held + d["page_count"] <= cap
            and sum(x["split"] == "dev" for x in by_stratum[d["stratum"]]) > 1
        ):
            d["split"] = "holdout"
            held += d["page_count"]
    return docs


def _counts(docs: list[dict[str, Any]]) -> dict[str, int]:
    dev = [d for d in docs if d.get("split") == "dev"]
    hold = [d for d in docs if d.get("split") == "holdout"]
    return {
        "documents": len(docs), "pages": _pages(docs),
        "dev_documents": len(dev), "dev_pages": _pages(dev),
        "holdout_documents": len(hold), "holdout_pages": _pages(hold),
        "korean_pages": _pages(d for d in docs if d["language"] == "ko"),
        "document_classes": len({d["document_class"] for d in docs}),
    }


def freeze(
    records: list[dict[str, Any]], salt: str, profile: str = "screen",
    screen_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and freeze; refuses a short or overlapping corpus (ContractError)."""
    if profile not in PROFILES:
        raise ContractError(f"profile {profile!r} not in {PROFILES}")
    docs = sorted((dict(d) for d in records), key=lambda d: d["doc_id"])
    for d in docs:
        _check_doc(d)
    _check_unique(docs)
    c = _counts(docs)
    if profile == "screen":
        if any("split" not in d for d in docs):
            raise ContractError("screen profile needs every document assigned to a split")
        if c["dev_pages"] < 300 or c["holdout_pages"] < 100:
            raise ContractError(
                f"below 300/100 pages: dev={c['dev_pages']} holdout={c['holdout_pages']}"
            )
        if c["holdout_pages"] > 100 + HOLDOUT_MAX_OVERSHOOT:
            raise ContractError(
                f"holdout overshoots 100 by more than {HOLDOUT_MAX_OVERSHOOT}: {c['holdout_pages']}"
            )
        stripped = [{k: v for k, v in d.items() if k != "split"} for d in docs]
        for want in assign_split(stripped, salt):
            got = next(d for d in docs if d["doc_id"] == want["doc_id"])
            if got["split"] != want["split"]:
                raise ContractError(
                    f"{want['doc_id']}: split {got['split']!r} is not what salt {salt!r} assigns"
                )
    else:
        if screen_manifest is None:
            raise ContractError("eg04 profile needs the screen manifest to prove no overlap")
        if (
            c["pages"] < EG04_MIN_PAGES
            or c["documents"] < EG04_MIN_DOCS
            or c["document_classes"] < EG04_MIN_CLASSES
        ):
            raise ContractError(f"eg04 minimums not met: {c}")
        if c["korean_pages"] * 2 < c["pages"]:
            raise ContractError(f"eg04 needs >=50% Korean pages: {c['korean_pages']}/{c['pages']}")
        body = {k: v for k, v in screen_manifest.items() if k != "manifest_sha256"}
        if screen_manifest.get("profile") != "screen" or (
            canonical_sha256(body) != screen_manifest.get("manifest_sha256")
        ):
            raise ContractError("eg04 needs an intact manifest with profile 'screen'")
        screen_sources = {d["source_sha256"] for d in screen_manifest["documents"]}
        shared = {d["source_sha256"] for d in docs} & screen_sources
        if shared:
            raise ContractError(f"eg04 shares {len(shared)} source(s) with the screen manifest")
    body = {"profile": profile, "salt": salt, "counts": c, "documents": docs}
    return {**body, "manifest_sha256": canonical_sha256(body)}


def _default_pages(data: bytes) -> int:
    if not data.startswith(b"%PDF"):
        return 1
    from pypdf import PdfReader

    return len(PdfReader(io.BytesIO(data)).pages)


def verify(
    manifest: dict[str, Any],
    corpus_root: Path,
    page_counter: Callable[[bytes], int] = _default_pages,
) -> None:
    """Recompute manifest digest, byte hashes, sizes and page counts (file = root/doc_id)."""
    body = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if canonical_sha256(body) != manifest.get("manifest_sha256"):
        raise ContractError("manifest_sha256 does not match manifest content")
    for d in manifest["documents"]:
        path = Path(corpus_root) / d["doc_id"]
        if not path.is_file():
            raise ContractError(f"{d['doc_id']}: file missing under corpus root")
        data = path.read_bytes()
        if "sha256:" + hashlib.sha256(data).hexdigest() != d["source_sha256"]:
            raise ContractError(f"{d['doc_id']}: byte hash mismatch")
        if len(data) != d["byte_size"]:
            raise ContractError(f"{d['doc_id']}: byte size mismatch")
        if page_counter(data) != d["page_count"]:
            raise ContractError(f"{d['doc_id']}: page count mismatch")


class HoldoutGuard:
    """Holdout opens for one frozen recipe only; the first evaluation is logged."""

    def __init__(self, manifest: dict[str, Any], access_log_path: Path) -> None:
        self._manifest = manifest
        self._log = Path(access_log_path)

    def _first_recipe(self) -> str | None:
        if not self._log.is_file():
            return None
        for line in self._log.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return str(json.loads(line)["frozen_recipe_sha256"])
        return None

    def load(
        self, split: str, purpose: str, frozen_recipe_sha256: str | None = None
    ) -> list[dict[str, Any]]:
        if split not in SPLITS:
            raise ValueError(f"split {split!r} not in {SPLITS}")
        if purpose not in PURPOSES:
            raise ValueError(f"purpose {purpose!r} not in {PURPOSES}")
        docs = [d for d in self._manifest["documents"] if d.get("split") == split]
        if split == "dev":
            return docs
        if purpose != "evaluate_frozen":
            raise HoldoutSealedError(f"holdout is sealed for purpose {purpose!r}")
        if frozen_recipe_sha256 is None:
            raise HoldoutSealedError("holdout evaluation needs frozen_recipe_sha256")
        require_sha256(frozen_recipe_sha256, "frozen_recipe_sha256")
        first = self._first_recipe()
        if first is None:
            self._log.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "manifest_sha256": self._manifest["manifest_sha256"],
                "frozen_recipe_sha256": frozen_recipe_sha256,
            }
            with self._log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, sort_keys=True) + "\n")
        elif first != frozen_recipe_sha256:
            raise HoldoutSealedError("holdout already evaluated under a different frozen recipe")
        return docs
