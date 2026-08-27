#!/usr/bin/env python3
"""Acquire the SFIR7 external catalogue snapshot from Zenodo, verifiably.

The catalogue is Libraries.io Open Source Repository and Dependency Metadata
1.6.0 (DOI 10.5281/zenodo.3626071), published 2020-01-12. Zenodo serves it as a
single 24.9 GB `tar.gz`; there is no per-table download, so the whole archive
must pass through this process even though SFIR7 needs one member of it.

**The archive is not kept.** It is streamed, and three things happen to the bytes
as they pass:

1. `md5` and `sha256` are computed over the *compressed archive bytes*, so the
   publisher's digest can be checked and a stronger one recorded. Zenodo
   publishes MD5 only; MD5 is fine for detecting a truncated or corrupted
   transfer and is not relied on for anything else. The SHA-256 is ours, and it
   is what later receipts pin.
2. The stream is decompressed and walked as a tar, and the one member SFIR7
   needs is written to disk with its own SHA-256.
3. Reading continues to the end of the archive **after** the member is
   extracted, because a digest over a prefix is not a digest over the archive.

That last point is the one worth stating plainly: stopping early would save
hours and would produce a number that looks like an archive digest and is not
one. A third party re-downloading this DOI must be able to reproduce every
figure in the receipt, and they can only do that if the figure covers the whole
file.

**Result-blindness.** This runs before the frame rule selects anything. It reads
no capacity number, computes no candidate count, and writes no roster. The only
judgement it makes is which member to extract, and that is fixed by name here
rather than discovered from the data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, BinaryIO

NS = Path(__file__).resolve().parents[1]
for _root in (str(NS), str(NS / "tools"), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sfir7_ranged_fetch as ranged  # noqa: E402 -- needs the sys.path above

SCHEMA = "tavonel.sfir7.catalog_snapshot.v1"
PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V7"

ZENODO_RECORD = "3626071"
DOI = "10.5281/zenodo.3626071"
ARCHIVE_FILENAME = "libraries-1.6.0-2020-01-12.tar.gz"
PUBLISHER_DIGEST = "md5:4f2275284b86827751bb31ce74238b15"

#: The member SFIR7 needs. Named here, before the archive is opened, so the
#: choice is auditable rather than a function of what turned up inside.
WANTED_MEMBER_SUFFIX = "repositories-1.6.0-2020-01-12.csv"

USER_AGENT = "TAVONEL-research-sfir7/1.0 (academic replication study)"
CHUNK = 4 * 1024 * 1024


class CatalogAcquisitionRefused(RuntimeError):
    """The snapshot could not be established as the published one."""


class _HashingReader:
    """A read-only file wrapper that digests every byte on its way through.

    `tarfile` in stream mode pulls from this, so the digests cover exactly the
    bytes the archive was built from -- not a re-read of something on disk that
    might have been written differently.
    """

    def __init__(self, raw: BinaryIO) -> None:
        self._raw = raw
        # MD5 because that is the only digest Zenodo publishes for this record.
        # It is used to check the transfer against the publisher's figure and for
        # nothing else; `sha256` below is the digest later receipts pin.
        self.md5 = hashlib.md5(usedforsecurity=False)
        self.sha256 = hashlib.sha256()
        self.bytes_read = 0
        self._last_report = 0.0

    def read(self, size: int = -1) -> bytes:
        chunk = self._raw.read(size)
        if chunk:
            self.md5.update(chunk)
            self.sha256.update(chunk)
            self.bytes_read += len(chunk)
            now = time.monotonic()
            if now - self._last_report > 30:
                self._last_report = now
                print(
                    f"    ... {self.bytes_read / 1e9:.2f} GB read",
                    flush=True,
                )
        return chunk

    def drain(self) -> None:
        """Read to EOF so the digests cover the whole archive, not a prefix."""
        while self._raw.read(CHUNK):
            pass

    def close(self) -> None:  # pragma: no cover - tarfile may call it
        pass


def _drain_with_hashing(reader: _HashingReader) -> None:
    while True:
        chunk = reader.read(CHUNK)
        if not chunk:
            return


def _https_request(url: str) -> urllib.request.Request:
    """Build a request, refusing any scheme but https.

    Not a lint silencer: this acquisition takes a URL from a JSON document
    fetched over the network, and `urlopen` will happily honour `file:` if one
    ever appears there. A catalogue snapshot read off the local disk while the
    receipt claims a DOI is precisely the kind of quiet substitution the whole
    provenance chain exists to prevent.
    """
    scheme = urllib.parse.urlparse(url).scheme
    if scheme != "https":
        raise CatalogAcquisitionRefused(
            f"catalogue source must be https, got {scheme!r} in {url!r}"
        )
    return urllib.request.Request(  # noqa: S310 -- the scheme check is the line above
        url, headers={"User-Agent": USER_AGENT}
    )


def archive_url() -> str:
    """Ask Zenodo where the file is, rather than hard-coding a CDN path."""
    request = _https_request(f"https://zenodo.org/api/records/{ZENODO_RECORD}")
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 -- scheme checked
        record = json.loads(response.read().decode("utf-8"))
    for entry in record.get("files", []):
        if entry.get("key") == ARCHIVE_FILENAME:
            if entry.get("checksum") != PUBLISHER_DIGEST:
                raise CatalogAcquisitionRefused(
                    "the record's published digest is not the one this tool was "
                    f"written against: record {entry.get('checksum')!r}, "
                    f"expected {PUBLISHER_DIGEST!r}. A DOI is supposed to be "
                    "immutable; refusing rather than acquiring a different file."
                )
            return str(entry["links"]["self"])
    raise CatalogAcquisitionRefused(f"record {ZENODO_RECORD} carries no file {ARCHIVE_FILENAME!r}")


def acquire(
    destination_dir: Path,
    *,
    url: str | None = None,
    parts_dir: Path | None = None,
    connections: int = ranged.DEFAULT_CONNECTIONS,
) -> dict[str, Any]:
    """Fetch the archive, verify it, and extract the one member SFIR7 needs.

    The bytes arrive as ordered ranges over a small connection pool rather than
    one stream, because one stream measured 0.3 MB/s against this endpoint --
    about twenty-four hours. That is a transfer detail and nothing more: the
    parts are concatenated in index order and everything downstream sees the same
    byte sequence a plain download would have produced. The archive digest is the
    proof, and it is checked against the publisher's figure before any of this is
    believed.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    source = url or archive_url()
    parts = parts_dir or (destination_dir / "_parts")
    member_path = destination_dir / Path(WANTED_MEMBER_SUFFIX).name
    member_sha = hashlib.sha256()
    member_bytes = 0
    member_name: str | None = None
    members_seen: list[str] = []

    started = time.monotonic()
    print(f"  fetching {ARCHIVE_FILENAME} in ranges", flush=True)
    part_paths, declared_total = ranged.fetch_ranges(
        source, parts, user_agent=USER_AGENT, connections=connections
    )
    print(f"  all parts present ({declared_total / 1e9:.2f} GB); walking the archive", flush=True)

    stream = ranged.ConcatenatedParts(part_paths)
    reader = _HashingReader(stream)  # type: ignore[arg-type]
    try:
        # `r|gz` is the streaming mode: no seeking, no random access, so the walk
        # sees exactly the byte sequence the digests are taken over.
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:  # type: ignore[arg-type]
            for member in archive:
                members_seen.append(member.name)
                if not member.isfile() or not member.name.endswith(WANTED_MEMBER_SUFFIX):
                    continue
                if member_name is not None:
                    raise CatalogAcquisitionRefused(
                        f"archive carries more than one {WANTED_MEMBER_SUFFIX!r}: "
                        f"{member_name!r} and {member.name!r}. Which one is the "
                        "catalogue is not a guess this tool may make."
                    )
                member_name = member.name
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise CatalogAcquisitionRefused(f"{member.name!r} could not be opened")
                print(f"  extracting {member.name} ({member.size / 1e9:.2f} GB)", flush=True)
                with member_path.open("wb") as handle:
                    while True:
                        chunk = extracted.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        member_sha.update(chunk)
                        member_bytes += len(chunk)
                if member_bytes != member.size:
                    raise CatalogAcquisitionRefused(
                        f"{member.name!r} declared {member.size} bytes, {member_bytes} arrived"
                    )
                print("  member extracted; draining the rest of the archive", flush=True)
        # The tar stream stops at its end-of-archive marker; the gzip trailer and
        # any remaining bytes still have to pass through the hasher, or the digest
        # covers a prefix rather than the file.
        _drain_with_hashing(reader)
    finally:
        stream.close()

    if member_name is None:
        raise CatalogAcquisitionRefused(
            f"archive carries no member ending {WANTED_MEMBER_SUFFIX!r}; "
            f"saw {len(members_seen)} members"
        )
    if reader.bytes_read != declared_total:
        raise CatalogAcquisitionRefused(
            f"walked {reader.bytes_read} bytes, server declared {declared_total}. "
            "A part is missing, duplicated or out of order."
        )
    local_md5 = "md5:" + reader.md5.hexdigest()
    if local_md5 != PUBLISHER_DIGEST:
        raise CatalogAcquisitionRefused(
            f"archive digest mismatch: publisher {PUBLISHER_DIGEST}, computed {local_md5}. "
            "The bytes that arrived are not the bytes the DOI names."
        )
    return {
        "schema": SCHEMA,
        "protocol_id": PROTOCOL_ID,
        "catalog_id": "LIBRARIES_IO_OPEN_DATA_1_6_0",
        "zenodo_doi": DOI,
        "zenodo_record": ZENODO_RECORD,
        "source_url": source,
        "archive_filename": ARCHIVE_FILENAME,
        "archive_bytes": reader.bytes_read,
        "archive_declared_bytes": declared_total,
        "publisher_digest": PUBLISHER_DIGEST,
        "publisher_digest_verified": True,
        "locally_computed_sha256": "sha256:" + reader.sha256.hexdigest(),
        "extracted_member_name": member_name,
        "extracted_member_bytes": member_bytes,
        "extracted_member_sha256": "sha256:" + member_sha.hexdigest(),
        "extracted_member_path": member_path.as_posix(),
        "extraction_tool": "python tarfile (stream mode r|gz) over ordered HTTP byte ranges",
        "extraction_tool_version": sys.version.split()[0],
        "transfer": {
            "mode": "ordered_http_byte_ranges",
            "connections": connections,
            "part_bytes": ranged.PART_BYTES,
            "parts": len(part_paths),
            "why_not_one_stream": (
                "a single connection to this endpoint measured 0.3 MB/s, about "
                "twenty-four hours for 24.9 GB. The per-connection rate is the bound, "
                "so the transfer is split. Parts are concatenated strictly in index "
                "order and the archive digest is what proves the result is identical "
                "to a plain download."
            ),
            "byte_identical_to_a_single_stream": True,
            "resumable": True,
        },
        "members_in_archive": len(members_seen),
        "archive_read_to_end": True,
        "why_read_to_end": (
            "a digest over a prefix is not a digest over the archive. Stopping at the "
            "wanted member would have produced a number that looks like an archive "
            "digest and is not one."
        ),
        "archive_retained_locally": False,
        "wall_clock_seconds": round(time.monotonic() - started, 3),
        "licence": {
            "treat_derived_artifacts_as": "CC-BY-SA-4.0",
            "attribution_required": "Libraries.io",
            "compliance_posture_not_a_legal_determination": True,
            "zenodo_record_metadata_says": "cc-by-4.0",
            "posture": (
                "the stricter of the two readings. Share-alike obligations are a "
                "superset of attribution-only obligations, so operating under CC BY-SA "
                "satisfies either. Which one governs is a legal question, recorded "
                "rather than resolved."
            ),
            "scope_isolated_to_the_derived_data_artifacts": True,
            "external_publication_only_after": "KOREAN_PRIORITY_FILING",
        },
        "result_blind": {
            "capacity_number_read": False,
            "candidate_count_computed": False,
            "roster_written": False,
            "member_chosen_by_name_before_the_archive_was_opened": True,
        },
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--url", default=None)
    parser.add_argument("--parts-dir", default=None, type=Path)
    parser.add_argument("--connections", default=ranged.DEFAULT_CONNECTIONS, type=int)
    args = parser.parse_args()

    body = acquire(
        args.destination,
        url=args.url,
        parts_dir=args.parts_dir,
        connections=args.connections,
    )
    body["content_sha256"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "state": "CATALOG_SNAPSHOT_ACQUIRED",
                "archive_sha256": body["locally_computed_sha256"],
                "member": body["extracted_member_name"],
                "member_sha256": body["extracted_member_sha256"],
                "receipt": args.receipt.as_posix(),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
