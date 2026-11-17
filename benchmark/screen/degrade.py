"""Synthetically degraded prints of the screen pages (section 5H-2, WO-D02-3C).

From a profile directory (``records.jsonl`` + ``corpus/``) write a sibling profile directory with
the source pages unchanged plus, per source page and level, a one-page PDF rendered with pypdfium2
and degraded with Pillow: a grey raster, a seeded skew, and for ``scan_poor`` blur, sensor noise
and a contrast shift, JPEG-encoded into an image-only PDF. These are synthetically degraded
prints, never real scans. Every random choice comes from (seed, source sha256, level); the drawn
parameters are recorded per page; a second run with the same renderer versions is byte-identical.
A derived page must have no text layer, so a candidate cannot read the answer from the file.
Gold is not touched here: ``sec_screen split-gold`` gives a derived page its source's gold rows.

The output directory is one complete profile: ``corpus/`` holds the clean sources (copied byte for
byte, hash-checked after the copy) and the derived pages, ``records.jsonl`` lists all of them
(33 sources -> 99 records with both levels; 225 -> 675, or 450 with ``--levels scan_poor``).
Degrade is all-or-nothing: every source is verified before anything is written, the output is
built in a temporary sibling directory and renamed at the end, so a refusal leaves nothing.

    python -m benchmark.screen.degrade --profile-dir D --out D2 --seed S [--levels scan_poor]

Order: degrade -> freeze (``--records D2/records.jsonl``) -> verify (``--corpus-root D2/corpus``)
-> split-gold once (the sealed gold stays in the source profile directory D).
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import PIL
import pypdfium2 as pdfium  # type: ignore[import-untyped]
from PIL import Image, ImageChops, ImageEnhance, ImageFilter
from pypdf import PdfReader

from benchmark.local_public.sources import _inside_git_tree
from benchmark.screen import manifest as screen_manifest

LABEL = "synthetically degraded print"
ORIGIN = "synthetic_degradation"
STRATUM = "distorted"
# A source page wider or taller than this is refused before rendering. SEC prints are US Letter
# (612 x 792 pt); the bound is the largest common office sheet, US Tabloid (11 x 17 in), so a
# Legal print still passes while a page sized to exhaust memory (150 dpi grey raster, then
# rotate with expand) does not: at the bound a page renders to at most 2,550 px a side.
MAX_PAGE_PT = 1224.0
# fixed values, or (low, high) drawn per page; skew is drawn in [-skew_max_deg, +skew_max_deg]
LEVELS: dict[str, dict[str, Any]] = {
    "scan_fair": {"dpi": 150, "skew_max_deg": 1.0, "jpeg_quality": 60},
    "scan_poor": {
        "dpi": 100,
        "skew_max_deg": 2.5,
        "jpeg_quality": 35,
        "blur_radius": (0.6, 1.2),
        "noise_amplitude": (10, 24),
        "contrast": (0.6, 0.8),
    },
}


class DegradeError(Exception):
    pass


def renderer() -> dict[str, str]:
    """Byte identity holds within these versions only; every receipt names them."""
    return {"pypdfium2": importlib.metadata.version("pypdfium2"), "pillow": PIL.__version__}


def page_seed(seed: str, source_sha256: str, level: str) -> str:
    """Every random choice of one derived page comes from this digest (hash streams, not
    ``random``, so the draw does not depend on the interpreter's generator)."""
    return hashlib.sha256(f"{seed}:{source_sha256}:{level}".encode()).hexdigest()


def _stream(key: str, name: str, n: int) -> bytes:
    return hashlib.shake_256(f"{key}:{name}".encode()).digest(n)


def _uniform(key: str, name: str, lo: float, hi: float) -> float:
    return lo + (hi - lo) * int.from_bytes(_stream(key, name, 8)) / 2**64


def draw(level: str, key: str) -> dict[str, Any]:
    spec = LEVELS[level]
    p: dict[str, Any] = {"dpi": spec["dpi"], "jpeg_quality": spec["jpeg_quality"]}
    p["skew_deg"] = round(_uniform(key, "skew", -spec["skew_max_deg"], spec["skew_max_deg"]), 3)
    if "blur_radius" in spec:
        p["blur_radius"] = round(_uniform(key, "blur", *spec["blur_radius"]), 3)
    if "noise_amplitude" in spec:
        lo, hi = spec["noise_amplitude"]
        p["noise_amplitude"] = min(hi, int(_uniform(key, "noise_amplitude", lo, hi + 1)))
    if "contrast" in spec:
        p["contrast"] = round(_uniform(key, "contrast", *spec["contrast"]), 3)
    return p


def _open(data: bytes, name: str) -> Any:
    """The source as a pdfium document of exactly one page of at most MAX_PAGE_PT a side;
    anything else is a DegradeError, raised before any rendering."""
    try:
        doc = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        raise DegradeError(f"{name}: not a readable PDF ({exc})") from exc
    try:
        if len(doc) != 1:
            raise DegradeError(f"source has {len(doc)} pages; one-page sources only")
        w, h = doc[0].get_size()
        if not (0 < w <= MAX_PAGE_PT and 0 < h <= MAX_PAGE_PT):
            raise DegradeError(f"{name}: page size {w:.0f} x {h:.0f} pt exceeds {MAX_PAGE_PT:.0f}")
    except BaseException:
        doc.close()
        raise
    return doc


def check_source(data: bytes, name: str) -> None:
    """What ``degrade_pdf`` refuses, checked without rendering."""
    _open(data, name).close()


def degrade_pdf(data: bytes, p: dict[str, Any], key: str) -> bytes:
    """One-page PDF in, image-only one-page PDF out; ``key`` (``page_seed``) seeds the noise."""
    doc = _open(data, "source")
    try:
        img = doc[0].render(scale=p["dpi"] / 72, grayscale=True).to_pil()
    finally:
        doc.close()
    if "contrast" in p:
        img = ImageEnhance.Contrast(img).enhance(p["contrast"])
    img = img.rotate(p["skew_deg"], resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255)
    if "blur_radius" in p:
        img = img.filter(ImageFilter.GaussianBlur(p["blur_radius"]))
    if "noise_amplitude" in p:  # centred: + one uniform field, - another, each in [0, amplitude]
        a = p["noise_amplitude"]
        up, down = (
            Image.frombytes("L", img.size, _stream(key, name, img.width * img.height)).point(
                lambda v: v * a // 255
            )
            for name in ("noise_up", "noise_down")
        )
        img = ImageChops.subtract(ImageChops.add(img, up), down)
    buf = io.BytesIO()
    # creationDate/modDate None: Pillow writes no timestamp, so the bytes repeat
    img.save(
        buf,
        "PDF",
        resolution=float(p["dpi"]),
        quality=p["jpeg_quality"],
        creationDate=None,
        modDate=None,
    )
    out = buf.getvalue()
    if (PdfReader(io.BytesIO(out), strict=True).pages[0].extract_text() or "").strip():
        raise DegradeError("derived page still has a text layer")
    return out


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _write_once(path: Path, data: bytes) -> None:
    with path.open("xb") as f:  # a derived name that collides with another file refuses
        f.write(data)


def _source_bytes(profile_dir: Path, r: dict[str, Any]) -> bytes:
    data: bytes = (profile_dir / "corpus" / r["doc_id"]).read_bytes()
    if _sha(data) != r["source_sha256"] or len(data) != r["byte_size"]:
        raise DegradeError(f"{r['doc_id']}: bytes do not match the record")
    return data


def build(
    profile_dir: Path, out: Path, *, seed: str, levels: tuple[str, ...] = tuple(LEVELS)
) -> dict[str, Any]:
    if not seed.strip():
        raise DegradeError("seed is required")
    if not levels or any(lv not in LEVELS for lv in levels) or len(set(levels)) != len(levels):
        raise DegradeError(f"levels must be distinct names from {tuple(LEVELS)}, got {levels}")
    if _inside_git_tree(out):
        raise DegradeError(f"output {out} is inside a git work tree")
    if out.exists():
        raise DegradeError(f"{out} exists; degrade is write-once")
    if not out.parent.is_dir():
        raise DegradeError(f"{out.parent} does not exist")
    text = (profile_dir / "records.jsonl").read_text("utf-8")
    sources = [json.loads(line) for line in text.splitlines() if line.strip()]
    if not sources:
        raise DegradeError("records.jsonl has no records")
    for r in sources:  # every source verified before anything is written
        screen_manifest._check_doc(r)  # also refuses a doc_id that leaves corpus/
        if "derived_from" in r or "degradation" in r or r["page_count"] != 1:
            raise DegradeError(f"{r['doc_id']}: sources are clean one-page records only")
        check_source(_source_bytes(profile_dir, r), r["doc_id"])
    runtime = renderer()
    tmp = Path(tempfile.mkdtemp(prefix=f".{out.name}.", suffix=".partial", dir=out.parent))
    try:
        receipt = _write(profile_dir, tmp, sources, text, seed, levels, runtime)
        tmp.rename(out)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return receipt


def _write(
    profile_dir: Path,
    tmp: Path,
    sources: list[dict[str, Any]],
    text: str,
    seed: str,
    levels: tuple[str, ...],
    runtime: dict[str, str],
) -> dict[str, Any]:
    (tmp / "corpus").mkdir()
    records: list[dict[str, Any]] = []
    for r in sources:
        data = _source_bytes(profile_dir, r)  # read again: refuses a change since the check
        _write_once(tmp / "corpus" / r["doc_id"], data)
        records.append(r)
        for level in levels:
            key = page_seed(seed, r["source_sha256"], level)
            params = draw(level, key)
            pdf = degrade_pdf(data, params, key)
            d = copy.deepcopy(r)  # provenance and rights stay the source's
            d.update(
                doc_id=f"{Path(r['doc_id']).stem}-{level}.pdf",
                source_sha256=_sha(pdf),
                byte_size=len(pdf),
                derived_from=r["source_sha256"],
                page_origin=ORIGIN,
                stratum=STRATUM,
                notes=f"{LABEL} ({level}) of {r['doc_id']}; not a real scan",
                degradation={
                    "label": LABEL,
                    "level": level,
                    "seed": seed,
                    "page_seed_sha256": key,
                    "parameters": params,
                    "renderer": runtime,
                },
            )
            _write_once(tmp / "corpus" / d["doc_id"], pdf)
            records.append(d)
    for d in records:  # every written file, clean copies included, against its record
        got = (tmp / "corpus" / d["doc_id"]).read_bytes()
        if _sha(got) != d["source_sha256"] or len(got) != d["byte_size"]:
            raise DegradeError(
                f"{d['doc_id']}: written bytes do not match the record after the copy"
            )
    records.sort(key=lambda x: x["doc_id"])
    with (tmp / "records.jsonl").open("x", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(x, sort_keys=True, ensure_ascii=False) + "\n" for x in records)
    per_level = [x["degradation"]["level"] for x in records if "degradation" in x]
    receipt = {
        "label": LABEL,
        "statement": (
            "Each derived page is a synthetically degraded print of a source page in this "
            "directory, not a real scan; its gold is the source page's gold (split-gold)."
        ),
        "seed": seed,
        "levels": {lv: LEVELS[lv] for lv in levels},
        "renderer": runtime,
        "source_records_sha256": _sha(text.encode("utf-8")),
        "records_sha256": _sha((tmp / "records.jsonl").read_bytes()),
        "documents": {
            "source": len(sources),
            **{lv: per_level.count(lv) for lv in levels},
        },
    }
    (tmp / "degrade_receipt.json").write_text(
        json.dumps(receipt, indent=1, sort_keys=True) + "\n", "utf-8", newline="\n"
    )
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m benchmark.screen.degrade")
    ap.add_argument("--profile-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", required=True)
    ap.add_argument("--levels", nargs="+", choices=tuple(LEVELS), default=list(LEVELS))
    a = ap.parse_args(argv)
    try:
        rec = build(a.profile_dir, a.out, seed=a.seed, levels=tuple(a.levels))
    except (DegradeError, ValueError, OSError) as exc:  # ContractError is a ValueError
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"documents": rec["documents"], "renderer": rec["renderer"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
