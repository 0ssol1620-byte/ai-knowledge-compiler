"""Verify receipts against the bytes another machine receives, not the ones we wrote.

    SCRIPTS=research/experiments/EXP-0101/scripts
    .venv/Scripts/python.exe $SCRIPTS/verify_committed_bytes.py
    .venv/Scripts/python.exe $SCRIPTS/verify_committed_bytes.py --worktree

**This script exists because the check it replaces passed while the evidence was
broken.** `verify_receipts.py` hashes the working tree. On Windows the artifact
writers emitted CRLF, so every text artifact was hashed CRLF into
`receipts.json` and then stored by git as LF, because `.gitattributes` says
`* text=auto eol=lf`. Seventeen of twenty-five entries verified on the machine
that wrote them and would have failed on every clone. A receipt with that
property is worse than no receipt: it is green exactly where nobody needs it and
red exactly where somebody does.

So the rule here is narrow and deliberate: **never hash a file this process
wrote.** Two modes, both reading through git:

`--index` (default) hashes `git cat-file blob :<path>` -- the content staged for
commit, after git has applied `.gitattributes`. It runs before a commit exists,
which is what makes it usable as a gate.

`--worktree` checks out `HEAD` into a throwaway `git worktree` and hashes the
files there. That is literally what a clone materialises, `.gitattributes`
filters and all, and it is the mode whose result is worth recording.

For `.zst` artifacts the authority stays where `compress_raw.py` put it: the
decompressed **raw** sha256. Git stores those bytes untouched (`*.zst binary`),
so the stored digest should match too, but the round trip is what decides.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import zstandard

ROOT = Path(__file__).resolve().parents[4]

#: Defaults to the experiment this script sits in; `--experiment PATH` points it
#: at another. One implementation rather than a copy per experiment: two copies
#: of a check drift, and a drifted verifier is how the defect this script exists
#: to catch got past the first one.
EXPERIMENT = Path(__file__).resolve().parents[1]


def _select_experiment(argv: list[str]) -> None:
    global EXPERIMENT, RELATIVE, REPORT
    if "--experiment" in argv:
        EXPERIMENT = (ROOT / argv[argv.index("--experiment") + 1]).resolve()
    RELATIVE = EXPERIMENT.relative_to(ROOT).as_posix()
    REPORT = EXPERIMENT / "receipts" / "committed-bytes-verification.json"


RELATIVE = EXPERIMENT.relative_to(ROOT).as_posix()
REPORT = EXPERIMENT / "receipts" / "committed-bytes-verification.json"


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _git(*args: str) -> bytes:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    return result.stdout


def _index_bytes(path: str) -> bytes | None:
    """The content staged for commit, after git's own filters."""
    try:
        return _git("cat-file", "blob", f":{RELATIVE}/{path}")
    except subprocess.CalledProcessError:
        return None


def _checkout_bytes(source: Path, path: str) -> bytes | None:
    target = source / path
    return target.read_bytes() if target.is_file() else None


def _receipts_from(source: Path) -> list[dict[str, str]]:
    payload = json.loads((source / "receipts" / "receipts.json").read_text(encoding="utf-8"))
    entries = payload["artifacts"]
    assert isinstance(entries, list)
    return entries


def _raw_manifest_from(source: Path) -> list[dict[str, object]]:
    manifest = source / "receipts" / "raw-evidence-manifest.json"
    if not manifest.is_file():
        return []
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    entries = payload["artifacts"]
    assert isinstance(entries, list)
    return entries


def _check_bytes(entries: list[dict[str, str]], fetch) -> tuple[int, int, list[dict[str, str]]]:
    green = 0
    red = 0
    failures: list[dict[str, str]] = []
    for entry in entries:
        payload = fetch(entry["path"])
        if payload is None:
            red += 1
            failures.append({"path": entry["path"], "problem": "not present in git"})
            continue
        actual = _sha256(payload)
        if actual == entry["sha256"]:
            green += 1
            continue
        red += 1
        failures.append(
            {
                "path": entry["path"],
                "problem": "digest differs from receipts.json",
                "receipt": entry["sha256"],
                "actual": actual,
            }
        )
    return green, red, failures


def _check_round_trip(source: Path) -> tuple[int, int, list[dict[str, str]]]:
    """Decompress each stored artifact and compare against its raw digest."""
    decompressor = zstandard.ZstdDecompressor()
    green = 0
    red = 0
    failures: list[dict[str, str]] = []
    for entry in _raw_manifest_from(source):
        packed_path = source / f"{entry['name']}.zst"
        if not packed_path.is_file():
            red += 1
            failures.append({"path": str(entry["name"]), "problem": "stored artifact missing"})
            continue
        payload = decompressor.decompress(packed_path.read_bytes())
        if _sha256(payload) == entry["raw_sha256"]:
            green += 1
            continue
        red += 1
        failures.append(
            {"path": str(entry["name"]), "problem": "restored content differs from raw_sha256"}
        )
    return green, red, failures


def _write_report(payload: dict[str, object]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        # LF explicitly -- the defect this script exists to catch.
        newline="\n",
    )


def verify_index() -> int:
    entries = _receipts_from(EXPERIMENT)
    green, red, failures = _check_bytes(entries, _index_bytes)
    print(f"index blobs: {green}/{green + red} match receipts.json")
    for failure in failures[:10]:
        print(f"  {failure['path']}: {failure['problem']}")
    return 0 if red == 0 else 1


def verify_worktree() -> int:
    """Check out HEAD somewhere clean and verify there. The definitive mode."""
    head = _git("rev-parse", "HEAD").decode().strip()
    with tempfile.TemporaryDirectory(prefix=f"{EXPERIMENT.name}-verify-") as temporary:
        checkout = Path(temporary) / "checkout"
        _git("worktree", "add", "--detach", str(checkout), head)
        try:
            source = checkout / RELATIVE
            entries = _receipts_from(source)
            green, red, failures = _check_bytes(
                entries, lambda path: _checkout_bytes(source, path)
            )
            packed_green, packed_red, packed_failures = _check_round_trip(source)
        finally:
            _git("worktree", "remove", "--force", str(checkout))

    total = green + red
    verdict = "GREEN" if red == 0 and packed_red == 0 else "RED"
    print(f"clean checkout of {head[:12]}: {green}/{total} receipts match")
    print(f"  zstd round trip against raw_sha256: {packed_green}/{packed_green + packed_red}")
    for failure in (failures + packed_failures)[:10]:
        print(f"  {failure['path']}: {failure['problem']}")

    _write_report(
        {
            "experiment": EXPERIMENT.name,
            "check": "receipt digests against a clean git checkout",
            "why": (
                "verify_receipts.py hashes the working tree, which is what passed "
                "while 17 of 25 receipts described CRLF bytes that no checkout of "
                "this repository produces. This mode hashes what a clone "
                "materialises instead: git applies .gitattributes on checkout, so "
                "these are the bytes another machine receives."
            ),
            "commit": head,
            "verdict": verdict,
            "receipts_matched": green,
            "receipts_total": total,
            "zstd_round_trip_matched": packed_green,
            "zstd_round_trip_total": packed_green + packed_red,
            "zstd_authority": (
                "the decompressed raw sha256 in raw-evidence-manifest.json remains "
                "authoritative for packed artifacts; git stores them untouched "
                "under the *.zst binary rule"
            ),
            "failures": failures + packed_failures,
            "disclosure": "NOT CLEARED FOR EXTERNAL DISCLOSURE",
        }
    )
    return 0 if verdict == "GREEN" else 1


def main(argv: list[str]) -> int:
    _select_experiment(argv)
    if "--worktree" in argv:
        return verify_worktree()
    return verify_index()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
