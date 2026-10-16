"""Materialize real historical parser fixtures from local, pinned Git objects.

Never fetches. The v2 extraction file is the explicitly unpublished original
remaining-state change, deterministically reconstructed and SHA-256 checked.
Both fixture trees otherwise contain the exact621 Python import sources.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from pathlib import Path

HISTORICAL_COMMIT = "621b7d692d21ca73e133010e7e234cc0ffe28086"
HISTORICAL_TREE = "be7d4a6a5166b4b6a31372d1496fa3d7a26e65c8"
EXTRACTION_PATH = "packages/compiler-runtime/src/akc_compiler_runtime/extraction.py"
PIPELINE_PATH = "packages/compiler-runtime/src/akc_compiler_runtime/pipeline.py"
V1_EXTRACTION_SHA256 = "3c5bf8c24e9cd4a12f380ec396ea0a3941e9f94d8b0d0b0530fc9d91d3066312"
V2_EXTRACTION_SHA256 = "45e9179ee9886b500986ef8314293c77e90acabc14c0420eabed78171edc5ae0"
LEGACY_PIPELINE_SHA256 = "d794d9e7d1a5ac064ce27dfe6a1d5ba1c512993f88ea419e9c9b97f77f2dd154"
SOURCE_PREFIXES = (
    "packages/compiler-runtime/src/akc_compiler_runtime/",
    "packages/cir-python/src/akc_cir/",
)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw: bytes) -> str:
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode() + b"\0" + raw, usedforsecurity=False,
    ).hexdigest()


def reconstruct_v2(raw: bytes) -> bytes:
    """Fixed historical transformation, independent of the current parser file."""
    if sha256(raw) != V1_EXTRACTION_SHA256:
        raise ValueError("Unpinned historical v1 extraction bytes")
    replacements = (
        (b"PARSER_CACHE_VERSION = 1\n", b"PARSER_CACHE_VERSION = 2\n"),
        (
            b'    re.IGNORECASE,\n)\n\n\nclass AuthorityClass',
            b'    re.IGNORECASE,\n)\n\n'
            b'# Markdown remaining-state predicates require a complement. Exclude common\n'
            b'# noun constructions ("remains of/from", "remains were/have ..."); this is a\n'
            b'# finite extraction rule, not a grammatical or truth/negation classifier.\n'
            b'# Keep code comments on their existing vocabulary.\n'
            b'_MD_REMAINING_STATE_RE = re.compile(\n'
            b'    r"\\bremains?\\b(?!\\s+(?:of|from|was|were|has|have|had)\\b)(?=\\s+\\S)",\n'
            b'    re.IGNORECASE,\n)\n\n\nclass AuthorityClass',
        ),
        (
            b'        states_something = bool(status_line) or bool(_CLAIM_VERB_RE.search(body))\n',
            b'        states_something = (\n'
            b'            bool(status_line)\n'
            b'            or bool(_CLAIM_VERB_RE.search(body))\n'
            b'            or bool(_MD_REMAINING_STATE_RE.search(body))\n'
            b'        )\n',
        ),
    )
    for before, after in replacements:
        if raw.count(before) != 1:
            raise ValueError("Historical v2 transformation preimage mismatch")
        raw = raw.replace(before, after, 1)
    if sha256(raw) != V2_EXTRACTION_SHA256:
        raise ValueError("Historical reconstructed v2 extraction hash mismatch")
    return raw


def _git(repo: Path, *arguments: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise RuntimeError("Git is required for local pinned historical objects")
    # Fixed Git operations and pinned revisions; never shell execution or fetch.
    return subprocess.run(  # noqa: S603
        [executable, "-C", str(repo), *arguments],
        check=True, capture_output=True,
    ).stdout


def historical_sources(repo: Path) -> tuple[dict[str, bytes], dict[str, str]]:
    actual_tree = _git(repo, "rev-parse", f"{HISTORICAL_COMMIT}^{{tree}}").decode().strip()
    if actual_tree != HISTORICAL_TREE:
        raise ValueError("Historical commit/tree mismatch")
    tree = _git(repo, "ls-tree", "-r", "-z", HISTORICAL_COMMIT, "--", *SOURCE_PREFIXES)
    blobs = {}
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        metadata, relative = entry.decode().split("\t", 1)
        mode, kind, blob = metadata.split()
        if not relative.endswith(".py"):
            continue
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError("Historical import source must be a regular Git blob")
        blobs[relative] = blob
    if not blobs or EXTRACTION_PATH not in blobs or PIPELINE_PATH not in blobs:
        raise ValueError("Historical import source tree is incomplete")
    archive = _git(repo, "archive", "--format=tar", HISTORICAL_COMMIT, *SOURCE_PREFIXES)
    sources = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as tar:
        for member in tar.getmembers():
            if member.name not in blobs:
                continue
            if not member.isfile():
                raise ValueError("Historical import source archive is not a regular file")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("Historical import source archive is incomplete")
            raw = stream.read()
            if git_blob(raw) != blobs[member.name]:
                raise ValueError("Historical import source blob mismatch")
            sources[member.name] = raw
    if sources.keys() != blobs.keys():
        raise ValueError("Historical archive does not cover every Python import source")
    if sha256(sources[PIPELINE_PATH]) != LEGACY_PIPELINE_SHA256:
        raise ValueError("Unpinned historical pipeline bytes")
    if sha256(sources[EXTRACTION_PATH]) != V1_EXTRACTION_SHA256:
        raise ValueError("Unpinned historical v1 extraction bytes")
    return sources, blobs


def prepare(repo: Path, output: Path, github_env: Path | None = None) -> dict:
    output = output.resolve()
    if output.exists():
        raise ValueError("Fixture destination already exists; refuse mixed historical sources")
    roots = {str(schema): str(output / f"v{schema}") for schema in (1, 2)}
    if any("\n" in root or "\r" in root for root in roots.values()):
        raise ValueError("Fixture root cannot contain environment-file line breaks")
    sources, blobs = historical_sources(repo)
    v2_extraction = reconstruct_v2(sources[EXTRACTION_PATH])
    records = []
    for relative, raw in sorted(sources.items()):
        for schema in (1, 2):
            candidate = v2_extraction if schema == 2 and relative == EXTRACTION_PATH else raw
            path = Path(roots[str(schema)]) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(candidate)
            path.chmod(0o444)
            records.append({
                "schema": schema, "path": relative, "source_git_blob": blobs[relative],
                "source_sha256": sha256(raw), "fixture_sha256": sha256(candidate),
                "fixture_git_blob": git_blob(candidate),
            })
    manifest = {
        "kind": "hash-pinned-parser-upgrade-fixtures", "historical_commit": HISTORICAL_COMMIT,
        "historical_tree": HISTORICAL_TREE, "roots": roots, "files": records,
        "v2_origin": "unpublished original remaining-state extraction transformation",
        "v2_extraction_sha256": V2_EXTRACTION_SHA256,
        "legacy_pipeline_sha256": LEGACY_PIPELINE_SHA256,
    }
    receipt = output / "fixture-manifest.json"
    receipt.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    receipt.chmod(0o444)
    if github_env is not None:
        with github_env.open("a", encoding="utf-8", newline="\n") as handle:
            for schema in (1, 2):
                handle.write(f"AKC_UPGRADE_LEGACY_V{schema}_ROOT={roots[str(schema)]}\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--github-env", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(prepare(arguments.repo, arguments.output, arguments.github_env)))


if __name__ == "__main__":
    main()
