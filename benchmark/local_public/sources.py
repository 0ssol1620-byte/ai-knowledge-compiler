"""Hash-verified, read-only access to the local public corpus (WO-LPC-1).

Code reaches the other project's data only through ``open_verified`` /
``verified_path``: each call resolves the name through the pinned manifest,
re-hashes the whole file, and only then hands out a read-only handle.
"""

from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from benchmark.v6.contracts import canonical_sha256

SCHEMA = "tavonel.lpc-sources.v1"
DEFAULT_MANIFEST = Path("D:/CodexProjects/v34-lanes/corpus/lpc-sources.v1.json")
# FRED/ALFRED content is denied for every action (D21-L1): no file, digest or entry of it is pinned.
DENIED_ALFRED_SERIES = ["CPIAUCSL", "UNRATE", "INDPRO", "DFF", "DGS10", "DGS2"]
ALFRED_DENIED_STATEMENT = (
    "denied: FRED/ALFRED content is not used (D21-L1, register row data_alfred_vintages); "
    "no file, digest or entry of it is pinned"
)

_C2 = "raw/v401_text/C2_edgar_docs"
EXCLUDED = [
    {
        "pattern": f"{_C2}/index.jsonl",
        "reason": "available_at wrong on 7,914 of 23,411 rows; manifest.jsonl locates",
    },
    {
        "pattern": f"{_C2}/submissions/*",
        "reason": "per-CIK files of unknown collection time; weakens the two-witness rule",
    },
    {
        "pattern": f"{_C2}/hdr/*",
        "reason": "headers used once in the design probe; not needed by the two-witness rule",
    },
    {"pattern": f"{_C2}/customer_mentions.jsonl", "reason": "derived text"},
    {"pattern": f"{_C2}/text/*", "reason": "derived text"},
    {"pattern": "raw/sec_facts.csv.gz", "reason": "derived table of another project"},
    {"pattern": "raw/sec_events*", "reason": "derived table of another project"},
    {"pattern": "raw/sec_scheduled_events*", "reason": "derived table of another project"},
    {"pattern": "raw/sec_identifier_observations*", "reason": "derived table of another project"},
    {"pattern": "cache/sec_company_facts_kaggle.zip", "reason": "Kaggle mirror, not official"},
    {"pattern": "cache/facts.parquet", "reason": "Kaggle mirror and supplement"},
    {"pattern": "cache/simfin/*", "reason": "not official / not read"},
    {"pattern": "cache/fnspid/*", "reason": "not official / not read"},
    {"pattern": "raw/fnspid_*", "reason": "not official / not read"},
    {"pattern": "historical_news*", "reason": "not official / not read"},
    {"pattern": "external/*", "reason": "not official / not read"},
    {"pattern": "free/*", "reason": "not official / not read"},
    {"pattern": "alfred_vintages*", "reason": "denied for every action (D21-L1)"},
    {"pattern": "terms/data_alfred_vintages*", "reason": "denied for every action (D21-L1)"},
    {"pattern": "alfred_series/BAMLH0A0HYM2", "reason": "third-party owned (ICE)"},
    {"pattern": "alfred_series/VIXCLS", "reason": "third-party owned (Cboe)"},
    {"pattern": "alfred_series/DTWEXBGS", "reason": "terms not read"},
]


class SourceError(Exception):
    pass


class ExcludedSource(SourceError):
    pass


class HashMismatch(SourceError):
    pass


class SourceMissing(SourceError):
    pass


def _sha256_file(path: Path) -> tuple[str, int]:
    h, n = hashlib.sha256(), 0
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def _sha256_gz_content(path: Path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _inside_git_tree(path: Path) -> bool:
    return any((p / ".git").exists() for p in [path.resolve(), *path.resolve().parents])


def _git_sha(cwd: Path) -> str:
    out = subprocess.run(
        [shutil.which("git") or "git", "-C", str(cwd), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if out.returncode != 0:
        raise SourceError(f"cannot read core git sha: {out.stderr.strip()}")
    return out.stdout.strip()


def _digest(manifest: dict[str, Any]) -> str:
    return canonical_sha256({k: v for k, v in manifest.items() if k != "manifest_sha256"})


# ---------------------------------------------------------------- build


def build(
    source_root: Path,
    out: Path,
    terms_json: Path,
    *,
    renderer: Path | None = None,
    renderer_version: str | None = None,
    renderer_licence_sha256: str | None = None,
) -> dict[str, Any]:
    """Pin every local source. Any cross-check disagreement raises HashMismatch."""
    if _inside_git_tree(out):
        raise SourceError(f"manifest output {out} is inside a git work tree")
    if not terms_json.is_file():
        raise SourceMissing(f"terms snapshots missing: {terms_json}")
    root = source_root.resolve()
    entries: list[dict[str, Any]] = []

    def pin(name: str, role: str, path: Path, **extra: Any) -> dict[str, Any]:
        if not path.is_file():
            raise SourceMissing(f"{name}: {path}")
        if any(x["name"] == name for x in entries):
            raise SourceError(f"duplicate manifest entry name: {name}")
        sha, size = _sha256_file(path)
        e = {
            "name": name,
            "role": role,
            "path": path.resolve().as_posix(),
            "bytes": size,
            "sha256": sha,
            **extra,
        }
        entries.append(e)
        return e

    # FSDS ZIPs vs the collector manifest
    fsds_dir = root / "cache/sec_fsds_official"
    collector = fsds_dir / "manifest.json"
    if not collector.is_file():
        raise SourceMissing(str(collector))
    for f in json.loads(collector.read_text("utf-8"))["files"]:
        q = f["quarter"]
        e = pin(
            f"sec_fsds/{q}",
            "gold_values",
            fsds_dir / f"{q}.zip",
            upstream_url=f["url"],
            collector_manifest_sha256=f["sha256"],
        )
        if e["sha256"] != f["sha256"]:
            raise HashMismatch(f"sec_fsds/{q}: file differs from the collector manifest")

    # filings vs the C2 manifest (hash of the decompressed HTML)
    c2 = root / _C2
    pin("c2_manifest", "locator", c2 / "manifest.jsonl")
    seen: set[str] = set()
    with (c2 / "manifest.jsonl").open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            adsh = r["adsh"]
            if adsh in seen:
                raise SourceError(f"duplicate adsh in C2 manifest: {adsh}")
            seen.add(adsh)
            p = c2 / r["path"]
            if not p.is_file():
                raise SourceMissing(f"sec_filing/{adsh}: {p}")
            content = _sha256_gz_content(p)
            if content != r["sha256"]:
                raise HashMismatch(
                    f"sec_filing/{adsh}: decompressed content differs from the C2 manifest"
                )
            pin(
                f"sec_filing/{adsh}",
                "rendering",
                p,
                content_sha256=content,
                upstream_url=r["url"],
                cik=r["cik"],
            )

    pin("sec_submissions_bulk", "acceptance_witness", root / "raw/sec_submissions_20260816.zip")

    if renderer is not None:
        if not (renderer_version and renderer_licence_sha256):
            raise SourceError("renderer needs --renderer-version and --renderer-licence-sha256")
        pin(
            "tool/chrome-headless-shell",
            "renderer",
            renderer,
            version=renderer_version,
            licence_file_sha256=renderer_licence_sha256,
        )

    # terms snapshots written by WO-LPC-1T
    raw = json.loads(terms_json.read_text("utf-8"))
    for t in raw["snapshots"] if isinstance(raw, dict) else raw:
        # Denied sources: skipped before the snapshot is opened or hashed (D21-L1).
        if any(fnmatch.fnmatchcase(f"terms/{t['source_id']}", x["pattern"]) for x in EXCLUDED):
            continue
        snap = terms_json.parent / f"{t['sha256']}.html"
        e = pin(
            f"terms/{t['source_id']}",
            "licence_snapshot",
            snap,
            url=t["url"],
            fetched_at=t["fetched_at"],
        )
        if e["sha256"] != t["sha256"]:
            raise HashMismatch(f"terms/{t['source_id']}: snapshot differs from terms.json")

    manifest: dict[str, Any] = {
        "schema": SCHEMA,
        "source_root": root.as_posix(),
        "built_by": f"benchmark.local_public.sources@{_git_sha(Path(__file__).parent)}",
        "entries": entries,
        "excluded": EXCLUDED,
        "alfred": ALFRED_DENIED_STATEMENT,
    }
    manifest["manifest_sha256"] = _digest(manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True), "utf-8")
    return manifest


# ---------------------------------------------------------------- loader


class InputLedger:
    """Every verified read of this process, as {name, sha256, bytes}."""

    def __init__(self, manifest_sha256: str) -> None:
        self.manifest_sha256 = manifest_sha256
        self._seen: dict[str, dict[str, Any]] = {}

    def record(self, name: str, sha256: str, size: int) -> None:
        self._seen[name] = {"name": name, "sha256": sha256, "bytes": size}

    @property
    def consumed(self) -> list[dict[str, Any]]:
        return sorted(self._seen.values(), key=lambda e: e["name"])


class Loader:
    def __init__(
        self, manifest_path: Path = DEFAULT_MANIFEST, ledger: InputLedger | None = None
    ) -> None:
        m = json.loads(Path(manifest_path).read_text("utf-8"))
        if m.get("schema") != SCHEMA or _digest(m) != m.get("manifest_sha256"):
            raise HashMismatch(f"manifest {manifest_path} is not a valid pinned manifest")
        self.manifest = m
        self.ledger = ledger or InputLedger(m["manifest_sha256"])
        self._by_name: dict[str, dict[str, Any]] = {e["name"]: e for e in m["entries"]}

    def resolve(self, name: str) -> dict[str, Any]:
        # The module's EXCLUDED decides, not the manifest's copy (an old one may lack rows).
        for ex in EXCLUDED:
            if fnmatch.fnmatchcase(name, ex["pattern"]):
                raise ExcludedSource(f"{name}: {ex['reason']}")
        stale = sorted(
            n for n in self._by_name if any(fnmatch.fnmatchcase(n, x["pattern"]) for x in EXCLUDED)
        )
        if stale:
            raise ExcludedSource(f"manifest lists excluded sources {stale}: rebuild the manifest")
        if name not in self._by_name:
            raise SourceMissing(f"{name} is not in the manifest")
        return self._by_name[name]

    def verified_path(self, name: str) -> Path:
        e = self.resolve(name)
        p = Path(e["path"])
        if not p.is_file():
            raise SourceMissing(f"{name}: {p}")
        # ponytail: swap window between hash and open; lock the file if it matters
        sha, size = _sha256_file(p)
        if sha != e["sha256"]:
            raise HashMismatch(f"{name}: expected {e['sha256']}, found {sha}")
        self.ledger.record(name, sha, size)
        return p

    def open_verified(self, name: str) -> BinaryIO:
        return self.verified_path(name).open("rb")


_default: Loader | None = None


def configure(manifest_path: Path = DEFAULT_MANIFEST, ledger: InputLedger | None = None) -> Loader:
    global _default
    _default = Loader(manifest_path, ledger)
    return _default


def _loader() -> Loader:
    return _default if _default is not None else configure()


def open_verified(name: str) -> BinaryIO:
    return _loader().open_verified(name)


def verified_path(name: str) -> Path:
    return _loader().verified_path(name)


# ---------------------------------------------------------------- receipts


def receipt(ledger: InputLedger, outputs: list[Path], statements: list[str]) -> dict[str, Any]:
    return {
        "lpc_manifest_sha256": ledger.manifest_sha256,
        "core_git_sha": _git_sha(Path(__file__).parent),
        "created_at": datetime.now(UTC).isoformat(),
        "inputs_consumed": ledger.consumed,
        "outputs": [
            {"path": Path(o).resolve().as_posix(), "sha256": _sha256_file(Path(o))[0]}
            for o in outputs
        ],
        "statements": statements,
    }


def write_receipt(
    rec: dict[str, Any], run_dir: Path, private_audit_dir: Path | None = None
) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    dest = run_dir / "receipt.json"
    copy = private_audit_dir / dest.name if private_audit_dir is not None else None
    for d in (dest, copy):  # evidence is never overwritten; check both before writing either
        if d is not None and d.exists():
            raise SourceError(f"receipt already exists, refusing to overwrite: {d}")
    with dest.open("x", encoding="utf-8") as f:
        f.write(json.dumps(rec, indent=1, sort_keys=True))
    if copy is not None:
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, copy)
    return dest


def verify_receipt(path: Path, manifest_path: Path = DEFAULT_MANIFEST) -> None:
    """Recompute the manifest digest and re-hash every consumed input and output."""
    rec = json.loads(Path(path).read_text("utf-8"))
    loader = Loader(manifest_path)
    if loader.manifest["manifest_sha256"] != rec["lpc_manifest_sha256"]:
        raise HashMismatch("receipt was produced against a different manifest")
    for c in rec["inputs_consumed"]:
        if loader.resolve(c["name"])["sha256"] != c["sha256"]:
            raise HashMismatch(f"{c['name']}: receipt hash is not the pinned hash")
        loader.verified_path(c["name"])  # re-hashes the file; raises if it changed
    for o in rec["outputs"]:
        if not Path(o["path"]).is_file():
            raise SourceMissing(o["path"])
        if _sha256_file(Path(o["path"]))[0] != o["sha256"]:
            raise HashMismatch(f"output {o['path']} changed")


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sources")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--source-root", type=Path, required=True)
    b.add_argument("--out", type=Path, default=DEFAULT_MANIFEST)
    b.add_argument("--terms", type=Path, required=True)
    b.add_argument("--renderer", type=Path)
    b.add_argument("--renderer-version")
    b.add_argument("--renderer-licence-sha256")
    v = sub.add_parser("verify")
    v.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    v.add_argument("--receipt", type=Path)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "build":
            m = build(
                a.source_root,
                a.out,
                a.terms,
                renderer=a.renderer,
                renderer_version=a.renderer_version,
                renderer_licence_sha256=a.renderer_licence_sha256,
            )
            print(f"built {len(m['entries'])} entries {m['manifest_sha256']}")
        elif a.receipt:
            verify_receipt(a.receipt, a.manifest)
            print("receipt verified")
        else:
            lo = Loader(a.manifest)
            for e in lo.manifest["entries"]:
                lo.verified_path(e["name"])
            print(f"verified {len(lo.manifest['entries'])} entries")
    except SourceError as exc:
        print(f"REFUSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
