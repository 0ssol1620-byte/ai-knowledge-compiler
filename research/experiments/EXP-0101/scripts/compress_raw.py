"""Pack `raw/` and `normalized/` without losing them, and bind both forms by sha256.

    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/compress_raw.py
    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/compress_raw.py --restore
    .venv/Scripts/python.exe research/experiments/EXP-0101/scripts/compress_raw.py --verify

Run order is `run_experiment.py` -> this -> `verify_receipts.py --full`.

**Raw evidence is never discarded, and least of all because a result was
unfavourable.** What is avoided here is committing 16 MB of JSONL, not keeping
it. Every original is restorable and the manifest records what a restore must
produce:

    raw evidence -> deterministic compression -> sha256 manifest -> receipt

**The raw digest is the authority, not the compressed one.** A future zstd
release may emit different bytes for the same input, which would change the
compressed digest while the evidence is untouched. So the check that matters is
the round trip: decompress, hash, compare against `raw_sha256`. The compressed
digest is recorded to detect a corrupted or swapped stored artifact, not to
define what the evidence is. `--verify` runs exactly that round trip and never
trusts the compressed digest alone.

An original is deleted only after its round trip has already passed in this same
run. If compression or verification fails, the original stays and the script
exits non-zero.

The manifest carries `artifact_uri` for every entry. It is a repository-relative
path today; if policy later moves these artifacts to object storage, the field
becomes the object URI and **no other field changes** — the same manifest works
in both worlds, which is why the fields the directive lists are all here
(uri, raw sha256, compressed sha256, byte counts, record count, schema version,
experiment id).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import zstandard

EXPERIMENT = Path(__file__).resolve().parents[1]
MANIFEST = EXPERIMENT / "receipts" / "raw-evidence-manifest.json"

#: Both bulk directories, not just `raw/`. `normalized/` holds §9.5 conversions
#: rather than raw evidence, so the *evidence* argument for keeping it does not
#: apply to it -- but "do not bloat git history" does, and at 1.9 MB it was the
#: single largest file in the experiment. The same discipline covers both.
BULK_DIRECTORIES = ("raw", "normalized")

EXPERIMENT_ID = "EXP-0101"
MANIFEST_SCHEMA_VERSION = "raw-evidence-manifest/2"

#: Level 19 is chosen once and recorded. It is not tuned per file: a level that
#: varied by file would make the stored bytes depend on something the manifest
#: does not capture.
COMPRESSION_LEVEL = 19

#: What each raw artifact *is*, so a restore can be checked for shape and not
#: only for bytes. Bumped by whoever changes the producing script's output.
SCHEMAS: dict[str, str] = {
    "raw/arm-outcomes.jsonl": "exp0101/arm-outcome/1",
    "raw/knowledge-evolution-suite.json": "exp0101/knowledge-evolution-suite/kes-1",
    "raw/sample-case.json": "exp0101/sample-case/1",
    "normalized/case-scores.jsonl": "exp0101/case-score/1",
}


def _bulk_files() -> tuple[list[Path], list[Path]]:
    """Everything to record, split into what still needs packing and what does not.

    Both halves are returned because the manifest describes the whole
    experiment, not the subset this invocation happened to act on. An earlier
    version rebuilt the manifest from the loose files alone, so running this a
    second time -- after the first run had already packed `raw/` -- would have
    written a manifest naming only `normalized/` and quietly dropped the three
    raw-evidence entries. A manifest that loses evidence is worse than no
    manifest, because it looks complete.
    """
    loose: list[Path] = []
    packed: list[Path] = []
    for directory in BULK_DIRECTORIES:
        base = EXPERIMENT / directory
        if not base.is_dir():
            continue
        for path in base.glob("*"):
            (packed if path.suffix == ".zst" else loose).append(path)
    return sorted(loose), sorted(packed)


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _record_count(name: str, payload: bytes) -> int:
    """How many records the artifact holds, so a truncated restore is visible."""
    if name.endswith(".jsonl"):
        return sum(1 for line in payload.decode("utf-8").splitlines() if line.strip())
    document = json.loads(payload.decode("utf-8"))
    if isinstance(document, dict) and isinstance(document.get("cases"), list):
        return len(document["cases"])
    return 1


def _write_manifest(entries: list[dict[str, object]]) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(
            {
                "experiment_id": EXPERIMENT_ID,
                "schema_version": MANIFEST_SCHEMA_VERSION,
                "codec": {
                    "name": "zstd",
                    "level": COMPRESSION_LEVEL,
                    "library": "python-zstandard",
                    "library_version": zstandard.__version__,
                    "frame_checksum": True,
                },
                "authority": (
                    "raw_sha256 defines the evidence. compressed_sha256 detects a "
                    "corrupted or swapped stored artifact and does not define it: "
                    "a different zstd build may produce different bytes for the "
                    "same input. Verify by decompressing and hashing."
                ),
                "restore": (
                    "research/experiments/EXP-0101/scripts/compress_raw.py --restore"
                ),
                "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
                "artifacts": entries,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
        # LF explicitly -- see the note in run_experiment._write_json.
        newline="\n",
    )


def _entry(relative: str, uri: Path, payload: bytes, packed: bytes) -> dict[str, object]:
    return {
        "name": relative,
        "artifact_uri": uri.relative_to(EXPERIMENT.parents[2]).as_posix(),
        "schema_version": SCHEMAS.get(relative, "UNREGISTERED"),
        "raw_sha256": _sha256(payload),
        "raw_bytes": len(payload),
        "compressed_sha256": _sha256(packed),
        "compressed_bytes": len(packed),
        "record_count": _record_count(relative, payload),
    }


def compress() -> int:
    originals, already_packed = _bulk_files()
    if not originals and not already_packed:
        print("nothing to record: no bulk artifact exists")
        return 0

    compressor = zstandard.ZstdCompressor(level=COMPRESSION_LEVEL, write_checksum=True)
    decompressor = zstandard.ZstdDecompressor()
    entries: list[dict[str, object]] = []
    failures: list[str] = []

    # Artifacts a previous run already packed still belong in the manifest.
    # Their raw digest is recovered by decompressing, which is the same check
    # `--verify` performs, so a stored artifact that no longer restores is
    # caught here rather than being copied forward on trust.
    for path in already_packed:
        packed = path.read_bytes()
        payload = decompressor.decompress(packed)
        relative = path.relative_to(EXPERIMENT).with_suffix("").as_posix()
        entries.append(_entry(relative, path, payload, packed))

    for path in originals:
        payload = path.read_bytes()
        raw_digest = _sha256(payload)
        packed = compressor.compress(payload)

        # Round trip before anything is deleted. An artifact that cannot be
        # restored is not compressed evidence, it is lost evidence.
        if _sha256(decompressor.decompress(packed, max_output_size=len(payload))) != raw_digest:
            failures.append(path.name)
            continue

        relative = path.relative_to(EXPERIMENT).as_posix()
        target = path.with_suffix(path.suffix + ".zst")
        target.write_bytes(packed)
        entries.append(_entry(relative, target, payload, packed))
        path.unlink()

    if failures:
        print(f"FAILED to round-trip, originals kept: {', '.join(failures)}")
        return 1

    entries.sort(key=lambda item: str(item["name"]))
    _write_manifest(entries)
    raw_total = sum(int(entry["raw_bytes"]) for entry in entries)
    packed_total = sum(int(entry["compressed_bytes"]) for entry in entries)
    print(
        f"recorded {len(entries)} artifacts ({len(originals)} packed this run): "
        f"{raw_total:,} -> {packed_total:,} bytes ({packed_total / raw_total:.1%})"
    )
    return 0


def _load_manifest() -> dict[str, object]:
    if not MANIFEST.is_file():
        raise SystemExit(f"no manifest at {MANIFEST}; run without a flag first")
    loaded: dict[str, object] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return loaded


def restore(*, keep_compressed: bool = True) -> int:
    manifest = _load_manifest()
    decompressor = zstandard.ZstdDecompressor()
    entries = manifest["artifacts"]
    assert isinstance(entries, list)
    for entry in entries:
        packed_path = EXPERIMENT / f"{entry['name']}.zst"
        payload = decompressor.decompress(
            packed_path.read_bytes(), max_output_size=int(entry["raw_bytes"])
        )
        if _sha256(payload) != entry["raw_sha256"]:
            print(f"RESTORE FAILED for {entry['name']}: digest does not match manifest")
            return 1
        (EXPERIMENT / str(entry["name"])).write_bytes(payload)
        if not keep_compressed:
            packed_path.unlink()
        print(f"restored {entry['name']} ({int(entry['raw_bytes']):,} bytes)")
    return 0


def verify() -> int:
    """Decompress every artifact in memory and check it against the manifest."""
    manifest = _load_manifest()
    decompressor = zstandard.ZstdDecompressor()
    entries = manifest["artifacts"]
    assert isinstance(entries, list)
    problems: list[str] = []
    for entry in entries:
        packed_path = EXPERIMENT / f"{entry['name']}.zst"
        if not packed_path.is_file():
            problems.append(f"{entry['name']}: stored artifact is missing")
            continue
        packed = packed_path.read_bytes()
        if _sha256(packed) != entry["compressed_sha256"]:
            problems.append(
                f"{entry['name']}: stored bytes differ from the manifest. This is "
                "not automatically corruption - a different zstd build compresses "
                "differently - so the round trip below decides."
            )
        payload = decompressor.decompress(packed, max_output_size=int(entry["raw_bytes"]))
        if _sha256(payload) != entry["raw_sha256"]:
            problems.append(f"{entry['name']}: RESTORED CONTENT DOES NOT MATCH raw_sha256")
            continue
        if _record_count(str(entry["name"]), payload) != int(entry["record_count"]):
            problems.append(f"{entry['name']}: restored record count differs")
    for problem in problems:
        print(problem)
    if any("DOES NOT MATCH" in problem or "missing" in problem for problem in problems):
        return 1
    print(f"round trip verified for {len(entries)} artifacts against raw_sha256")
    return 0


def main(argv: list[str]) -> int:
    if "--restore" in argv:
        return restore()
    if "--verify" in argv:
        return verify()
    return compress()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
