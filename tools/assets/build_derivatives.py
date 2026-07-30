"""Create web derivatives and a cryptographic manifest for Structara assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "assets" / "3d" / "derivatives"
PUBLIC = ROOT / "apps" / "web" / "public" / "hero"
REGISTRY = ROOT / "assets" / "registry" / "generated-assets.json"
NAME_PATTERN = re.compile(
    r"^STR-[A-Z0-9-]+-T[0-4]-[A-Z0-9-]+-(?:EN|KO|MULTI)-[A-Z0-9-]+-\d+x\d+-v\d{2}\.(?:avif|mp4|webm|webp)$"
)
EXPLICIT_SOURCE_NAMES = {
    "hero-master.blend",
    "hero-master.glb",
    "hero-master-low.glb",
    "hero-poster-2880x1800.png",
    "hero-tablet-1600x1200.png",
    "hero-mobile-1080x1440.png",
    "hero-reduced-motion.png",
    "hero-og-1200x630.png",
    "hero-composition-a.png",
    "hero-composition-b.png",
    "hero-composition-c.png",
    "hero-object-source-pages-transparent.png",
    "hero-object-evidence-blocks-transparent.png",
    "hero-object-knowledge-graph-transparent.png",
    "hero-loop-12s.mp4",
}
DERIVATIVE_NAMES = {
    "hero-poster-2880x1800": "STR-HOME-T2-HERO-EN-DESKTOP-2880x1800-v01",
    "hero-tablet-1600x1200": "STR-HOME-T2-HERO-EN-TABLET-1600x1200-v01",
    "hero-mobile-1080x1440": "STR-HOME-T2-HERO-EN-MOBILE-1080x1440-v01",
    "hero-reduced-motion": "STR-HOME-T2-HERO-EN-REDUCED-1200x750-v01",
    "hero-og-1200x630": "STR-HOME-T2-HERO-EN-OG-1200x630-v01",
    "hero-composition-a": "STR-HOME-T2-HERO-EN-CONCEPT-A-1200x750-v01",
    "hero-composition-b": "STR-HOME-T2-HERO-EN-CONCEPT-B-1200x750-v01",
    "hero-composition-c": "STR-HOME-T2-HERO-EN-CONCEPT-C-1200x750-v01",
    "hero-object-source-pages-transparent": "STR-HOME-T2-OBJECT-EN-SOURCE-1600x1000-v01",
    "hero-object-evidence-blocks-transparent": "STR-HOME-T2-OBJECT-EN-EVIDENCE-1600x1000-v01",
    "hero-object-knowledge-graph-transparent": "STR-HOME-T2-OBJECT-EN-GRAPH-1600x1000-v01",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transcode_image(source: Path, target: Path, image_format: str) -> None:
    with Image.open(source) as image:
        options = {"quality": 82, "speed": 6}
        if image_format == "WEBP":
            options = {"quality": 84, "method": 6}
        image.save(target, image_format, **options)


def webm(ffmpeg: Path, source: Path, target: Path) -> None:
    subprocess.run(  # noqa: S603 - executable path is an explicit operator input
        [
            str(ffmpeg),
            "-y",
            "-i",
            str(source),
            "-an",
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "34",
            "-b:v",
            "0",
            "-row-mt",
            "1",
            "-pix_fmt",
            "yuv420p",
            str(target),
        ],
        check=True,
        capture_output=True,
    )


def validate_names(paths: list[Path]) -> None:
    invalid = sorted(
        path.name
        for path in paths
        if path.name not in EXPLICIT_SOURCE_NAMES and not NAME_PATTERN.fullmatch(path.name)
    )
    if invalid:
        raise SystemExit(f"Invalid asset names: {', '.join(invalid)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", type=Path)
    args = parser.parse_args()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)

    pngs = sorted(SOURCE.glob("hero-*.png"))
    if len(pngs) < 11:
        raise SystemExit(f"Expected at least 11 hero PNG masters, found {len(pngs)}")

    for source in pngs:
        canonical_stem = DERIVATIVE_NAMES.get(source.stem)
        if canonical_stem is None:
            raise SystemExit(f"No canonical derivative name for {source.name}")
        for suffix, image_format in ((".avif", "AVIF"), (".webp", "WEBP")):
            target = PUBLIC / f"{canonical_stem}{suffix}"
            transcode_image(source, target, image_format)

    mp4_source = SOURCE / "hero-loop-12s.mp4"
    if not mp4_source.exists():
        raise SystemExit("Missing hero-loop-12s.mp4")
    mp4_target = PUBLIC / "STR-HOME-T2-HERO-MULTI-LOOP-960x600-v01.mp4"
    shutil.copy2(mp4_source, mp4_target)

    if args.ffmpeg:
        ffmpeg_path = args.ffmpeg.resolve()
        if not ffmpeg_path.exists():
            raise SystemExit(f"FFmpeg not found: {ffmpeg_path}")
        webm(
            ffmpeg_path,
            mp4_source,
            PUBLIC / "STR-HOME-T2-HERO-MULTI-LOOP-960x600-v01.webm",
        )

    source_assets = [
        ROOT / "assets" / "3d" / "master" / "hero-master.blend",
        SOURCE / "hero-master.glb",
        SOURCE / "hero-master-low.glb",
        *pngs,
        mp4_source,
    ]
    public_assets = sorted(PUBLIC.glob("STR-HOME-*"))
    validate_names([*source_assets, *public_assets])
    missing = [str(path.relative_to(ROOT)) for path in source_assets if not path.exists()]
    if missing:
        raise SystemExit(f"Missing source assets: {', '.join(missing)}")

    records = []
    for path in [*source_assets, *public_assets]:
        with (
            Image.open(path)
            if path.suffix in {".png", ".avif", ".webp"}
            else _null_context() as image
        ):
            dimensions = list(image.size) if image else None
        records.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
                "dimensions": dimensions,
                "role": "source" if path in source_assets else "web-derivative",
            }
        )

    REGISTRY.write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "generatedAt": datetime.now(UTC).isoformat(),
                "generator": "tools/assets/build_derivatives.py",
                "namingConvention": NAME_PATTERN.pattern,
                "assets": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Validated {len(records)} assets; wrote {REGISTRY.relative_to(ROOT)}")


class _null_context:
    def __enter__(self):
        return None

    def __exit__(self, *_args):
        return False


if __name__ == "__main__":
    main()
