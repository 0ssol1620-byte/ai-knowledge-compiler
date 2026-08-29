#!/usr/bin/env python3
"""Bind the catalogue, the readers, and the inherited frame, before any roster.

The instrument freeze binds the rule that decides the cohort. It does not bind
the path input travels to reach that rule, and the two are not the same thing:
a frozen selection rule fed by the wrong CSV column produces a roster of real
repositories ranked by something that is not SourceRank, and nothing downstream
can tell. The catalogue parser's own docstring says so.

So roster generation requires two authorities. This is the second. It is
deliberately narrower than a freeze -- it authorises nothing. It records what
the input was and refuses when the bytes are not what was recorded.

Three things stand between the catalogue file and the frozen selection rule.

**The catalogue snapshot.** Libraries.io Open Source Repository and Dependency
Metadata 1.6.0, DOI 10.5281/zenodo.3626071, published 2020-01-12 -- six years
before this study existed, by someone else, ranked by someone else. That is the
whole basis for calling the ordinal independent, so it is pinned by the
publisher's DOI, the archive digest and the member digest, and a third party can
reproduce every one of them. Reusing SFIR7's snapshot is not reusing SFIR7's
findings: the bytes are external data, not a result. What must not carry across
is SFIR7's spent identities, and those the selection rule excludes.

**The readers.** Pinned four ways each -- working bytes, committed blob, the two
compared, and the import origin. A correct hash on disk does not establish which
copy the interpreter loaded.

**The eligibility predicates, which the frozen protocol does not contain.** The
protocol freezes the criterion, the envelope, the salt, the partition and the
ordering. It says nothing about which rows enter the pool at all, and whoever
writes that writes a cohort-determining rule. Writing one now, after the freeze
and before the cohort opens, is the exact move the study forbids.

So SFIR9 does not write one. It inherits SFIR7's, unchanged, and reads them from
SFIR7's committed roster-freeze receipt rather than restating them here -- a
restatement is a copy that can drift, and a copy of an eligibility rule that
drifts is a new eligibility rule. Independence is then checked mechanically
rather than asserted: the receipt must have entered the repository strictly
before the SFIR9 protocol did. Predicates committed a day before the criterion
existed cannot have been chosen to clear it.

**The member is re-hashed, not trusted.** Ten gigabytes, every time. A receipt
saying the file was correct when it was extracted is not evidence about the file
on disk now.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
REPO = NS.parents[1]
OUTPUT = NS / "receipts/sfir9-cohort-input-binding.json"
SCHEMA = "tavonel.sfir9.cohort_input_binding.v1"

#: The receipt that recorded the acquisition. Read for its pins, not trusted.
SNAPSHOT_RECEIPT = "receipts/sfir7-catalog-snapshot.json"

#: SFIR7's sealed frame. SFIR9's eligibility predicates are read from here.
INHERITED_FRAME_RECEIPT = "receipts/sfir7-roster-freeze.json"

#: The artifact whose commit date the frame's must precede. If the predicates
#: entered the repository after the criterion, they could have been chosen to
#: clear it, and no amount of prose about intent would settle that.
PROTOCOL_SOURCE = "research/tavonel_eval_v2/tools/sfir9_protocol.py"
FRAME_SOURCE = "research/tavonel_eval_v2/" + INHERITED_FRAME_RECEIPT

#: Everything outside the frozen closure that stands between the catalogue file
#: and the frozen selection rule.
INPUT_MODULES = (
    # reads the CSV by declared column name
    "research/tavonel_eval_v2/tools/sfir7_catalog_parser.py",
    # maps publisher fields onto the fields a predicate may name, and decides
    # which fields the rule may not see at all
    "research/tavonel_eval_v2/tools/sfir7_projection.py",
    # holds the operator semantics, the licence spellings this catalogue uses,
    # and the selectable-field set
    "research/tavonel_eval_v2/tools/sfir7_frame.py",
    # the spent identities an earlier study already looked at
    "research/tavonel_eval_v2/tools/sfir7_roots.py",
)

#: Identity keys. SFIR7 lets `record_id` order and tie-break, which is not the
#: same as letting it filter: a predicate naming an identity would be a
#: hand-picked roster wearing a rule's clothes.
IDENTITY_FIELDS = frozenset({"record_id", "host_uuid"})

DIGEST_MISMATCH = "REFUSED_CATALOGUE_DIGEST_MISMATCH"
MEMBER_ABSENT = "REFUSED_CATALOGUE_MEMBER_ABSENT"
SNAPSHOT_ABSENT = "REFUSED_SNAPSHOT_RECEIPT_ABSENT"
BYTES_MISMATCH = "REFUSED_INPUT_MODULE_BYTES_MISMATCH"
ORIGIN_MISMATCH = "REFUSED_INPUT_MODULE_ORIGIN_MISMATCH"
FRAME_ABSENT = "REFUSED_INHERITED_FRAME_ABSENT"
FRAME_NOT_INDEPENDENT = "REFUSED_FRAME_NOT_OLDER_THAN_PROTOCOL"
FRAME_SNAPSHOT_MISMATCH = "REFUSED_FRAME_COMPOSED_AGAINST_OTHER_BYTES"
FRAME_NAMES_IDENTITY = "REFUSED_PREDICATE_NAMES_AN_IDENTITY_FIELD"


class CohortInputRefused(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def eligibility_fields() -> frozenset[str]:
    """What a predicate may name, read live from SFIR7 rather than restated.

    An earlier draft listed these by hand and got them wrong in both directions:
    it named the raw publisher fields, so it would have refused a predicate on
    `primary_language` and admitted one on `fork` or `status` -- the two the
    projection deliberately withholds from the rule. Restating a field list is
    the same mistake as restating a predicate, one level down.
    """
    import sfir7_frame

    return frozenset(sfir7_frame.SELECTABLE_FIELDS) - IDENTITY_FIELDS


def _digest(payload: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )


def _git(repository_root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", *args],  # noqa: S607 - git from PATH, as everywhere else here
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise CohortInputRefused(
            BYTES_MISMATCH, f"git {' '.join(args)} failed: {result.stderr.strip()}"
        )
    return result.stdout


def _git_committed_bytes(repository_root: Path, relative_path: str) -> bytes:
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "show", f"HEAD:{relative_path}"],  # noqa: S607 - git from PATH
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise CohortInputRefused(
            BYTES_MISMATCH,
            f"{relative_path} is not in the commit: "
            f"{result.stderr.decode(errors='replace').strip()}",
        )
    return result.stdout


def sha256_of_file(path: Path, *, chunk: int = 1 << 22) -> str:
    """Hash the whole file. Ten gigabytes is not a reason to hash a prefix."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def read_snapshot_pins(namespace: Path) -> dict[str, Any]:
    """The publisher's identifiers and the digests recorded at acquisition."""
    path = namespace / SNAPSHOT_RECEIPT
    if not path.is_file():
        raise CohortInputRefused(
            SNAPSHOT_ABSENT,
            f"{SNAPSHOT_RECEIPT} is absent, so there is nothing to pin against",
        )
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "zenodo_doi": report["zenodo_doi"],
        "archive_filename": report["archive_filename"],
        "archive_bytes": report["archive_bytes"],
        "archive_sha256": report["content_sha256"],
        "member_name": report["extracted_member_name"],
        "member_path": report["extracted_member_path"],
        "member_bytes": report["extracted_member_bytes"],
        "member_sha256": report["extracted_member_sha256"],
    }


def verify_member(pins: dict[str, Any], *, member_path: Path | None = None) -> dict[str, Any]:
    """Re-hash the file on disk and compare with what was recorded."""
    path = member_path or Path(pins["member_path"])
    if not path.is_file():
        raise CohortInputRefused(
            MEMBER_ABSENT,
            f"{path} is not on disk. The catalogue member must be present and "
            "re-hashable; a receipt about it is not the file.",
        )
    observed_bytes = path.stat().st_size
    observed_sha = sha256_of_file(path)
    if observed_sha != pins["member_sha256"]:
        raise CohortInputRefused(
            DIGEST_MISMATCH,
            f"{path} hashes to {observed_sha}, not the recorded "
            f"{pins['member_sha256']}. These are not the catalogue bytes.",
        )
    return {
        "path": str(path),
        "bytes_on_disk": observed_bytes,
        "bytes_recorded": pins["member_bytes"],
        "sha256_recomputed": observed_sha,
        "sha256_recorded": pins["member_sha256"],
        # No "rehashed_in_full" flag. It could only ever be True -- the function
        # raises above when the digest disagrees -- and a reader who wants to
        # know whether the whole file was read can compare these two values and
        # recompute the digest themselves. A boolean cannot be recomputed.
    }


def _added_at(repository_root: Path, relative_path: str) -> str:
    """When this path first entered the repository, by author date."""
    log = _git(
        repository_root,
        "log",
        "--diff-filter=A",
        "--format=%aI",
        "--",
        relative_path,
    ).split()
    if not log:
        raise CohortInputRefused(
            FRAME_ABSENT, f"{relative_path} has no commit that added it, so it has no age"
        )
    return log[-1]


def inherited_frame(
    *, namespace: Path, repository_root: Path, snapshot_sha256: str
) -> dict[str, Any]:
    """SFIR7's eligibility predicates, read from its sealed receipt.

    Read rather than restated. A restatement is a copy, and a copy of an
    eligibility rule that drifts is a new eligibility rule -- authored after the
    freeze, by someone who by then could see what the cohort needed.
    """
    path = namespace / INHERITED_FRAME_RECEIPT
    if not path.is_file():
        raise CohortInputRefused(
            FRAME_ABSENT,
            f"{INHERITED_FRAME_RECEIPT} is absent. SFIR9 has no eligibility rule "
            "of its own and will not write one now.",
        )
    raw = path.read_bytes()
    rule = json.loads(raw.decode("utf-8"))["frame_rule"]

    if rule["snapshot_sha256"] != snapshot_sha256:
        raise CohortInputRefused(
            FRAME_SNAPSHOT_MISMATCH,
            f"the frame was composed against {rule['snapshot_sha256']}, not the "
            f"catalogue being bound here ({snapshot_sha256}). Predicates written "
            "against different bytes are not the predicates this cohort inherits.",
        )

    allowed = eligibility_fields()
    for predicate in rule["predicates"]:
        if predicate["field"] not in allowed:
            raise CohortInputRefused(
                FRAME_NAMES_IDENTITY,
                f"predicate names {predicate['field']!r}, which is not one of the "
                f"fields SFIR7's rule may filter on ({sorted(allowed)}). A rule "
                "that filtered on identity, or on a field the projection withholds "
                "from it, would be a hand-picked roster wearing a rule's clothes.",
            )

    frame_added = _added_at(repository_root, FRAME_SOURCE)
    protocol_added = _added_at(repository_root, PROTOCOL_SOURCE)
    if not frame_added < protocol_added:
        raise CohortInputRefused(
            FRAME_NOT_INDEPENDENT,
            f"the frame entered the repository at {frame_added} and the SFIR9 "
            f"protocol at {protocol_added}. Predicates that are not older than "
            "the criterion could have been chosen to clear it.",
        )

    return {
        "inherited_from": "SFIR7",
        "receipt": INHERITED_FRAME_RECEIPT,
        "receipt_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "predicates": rule["predicates"],
        "ranking": rule["ranking"],
        "tie_breaker": rule["tie_breaker"],
        "composed_against_snapshot": rule["snapshot_sha256"],
        "independence": {
            "frame_entered_repository_at": frame_added,
            "protocol_entered_repository_at": protocol_added,
            # The two timestamps are the proof; a third field asserting their
            # order would restate what the reader can already compare, and could
            # only ever say one thing because the function raises otherwise.
            "why_this_is_checked_mechanically": (
                "an eligibility rule written after the criterion could have been "
                "chosen to clear it, and no statement of intent settles that. "
                "Commit order does."
            ),
        },
        "what_is_not_inherited": {
            "n": (
                "SFIR7 derived N=50 as min(6*5000, 12000)//240 from GitHub's "
                "published rate limit and SFIR6's per-root bound. SFIR9 derives "
                "N=50 as (6*4500)//540 from its charge envelope. The arithmetic "
                "is unrelated and the agreement is a coincidence, recorded here "
                "so it is not mistaken for SFIR9 having copied a number."
            ),
            "roots": (
                "SFIR7's selected identities are excluded by the selection rule "
                "as spent, not inherited."
            ),
            "findings": "nothing SFIR7 or SFIR8 measured reaches this cohort.",
        },
    }


def bind_input_modules(
    *, repository_root: Path, import_origins: dict[str, str]
) -> list[dict[str, Any]]:
    """Pin each reader four ways, the same four the upstream binding uses."""
    records = []
    for relative_path in INPUT_MODULES:
        module = Path(relative_path).stem
        path = (repository_root / relative_path).resolve()
        if not path.is_file():
            raise CohortInputRefused(BYTES_MISMATCH, f"{relative_path} does not exist")
        working = path.read_bytes()
        committed = _git_committed_bytes(repository_root, relative_path)
        if committed != working:
            raise CohortInputRefused(
                BYTES_MISMATCH,
                f"{relative_path} differs between the commit and the working tree",
            )
        origin = import_origins.get(module)
        if origin is None or Path(origin).resolve() != path:
            raise CohortInputRefused(
                ORIGIN_MISMATCH,
                f"{module} resolves to {origin}, not {path}. A correct hash on "
                "disk does not establish which copy the interpreter loaded.",
            )
        header = f"blob {len(working)}\0".encode()
        records.append(
            {
                "module": module,
                "relative_path": relative_path,
                "sha256": "sha256:" + hashlib.sha256(working).hexdigest(),
                "git_blob_id": hashlib.sha1(header + working).hexdigest(),  # noqa: S324
                "working_tree_bytes": len(working),
                # No "committed_bytes_equal_working_bytes" flag either, for the
                # same reason. `git_blob_id` is the check: a reader compares it
                # with `git rev-parse HEAD:<relative_path>`.
                "import_origin": str(Path(origin).resolve()),
            }
        )
    return records


def import_origins() -> dict[str, str]:
    origins = {}
    for relative_path in INPUT_MODULES:
        module_name = Path(relative_path).stem
        module = __import__(module_name)
        origins[module_name] = module.__file__
    return origins


def binding(
    *,
    namespace: Path = NS,
    repository_root: Path | None = None,
    member_path: Path | None = None,
    origins: dict[str, str] | None = None,
) -> dict[str, Any]:
    repository_root = repository_root or namespace.resolve().parents[1]
    sys.path.insert(0, str(namespace / "tools"))
    pins = read_snapshot_pins(namespace)
    member = verify_member(pins, member_path=member_path)
    modules = bind_input_modules(
        repository_root=repository_root,
        import_origins=origins if origins is not None else import_origins(),
    )
    frame = inherited_frame(
        namespace=namespace,
        repository_root=repository_root,
        snapshot_sha256=pins["member_sha256"],
    )
    body = {
        "schema": SCHEMA,
        "catalogue": pins,
        "member_verification": member,
        "input_modules": modules,
        "inherited_frame": frame,
        "eligibility_fields": sorted(eligibility_fields()),
        "why_this_is_separate_from_the_instrument_freeze": (
            "the freeze binds the rule that decides the cohort. It does not bind "
            "the path input travels to reach that rule, and it does not contain "
            "an eligibility predicate at all. A frozen rule fed by the wrong "
            "column produces a roster ranked by something that is not SourceRank, "
            "and nothing downstream can tell."
        ),
        "why_the_member_is_rehashed": (
            "a receipt saying the file was correct when it was extracted is not "
            "evidence about the file on disk now."
        ),
        "this_binding_authorises_nothing": (
            "it records what the input was and refuses when the bytes are not "
            "what was recorded. Authority to generate a roster comes from the "
            "instrument freeze, and requires this binding as well."
        ),
    }
    return {**body, "binding_digest": _digest(body)}


def verify(report: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in report.items() if key != "binding_digest"}
    problems = []
    if _digest(body) != report.get("binding_digest"):
        problems.append("binding_digest does not recompute; the receipt was edited")
    if not report.get("input_modules"):
        problems.append("no input modules are bound")
    member = report.get("member_verification", {})
    if member.get("sha256_recomputed") != report.get("catalogue", {}).get("member_sha256"):
        problems.append("the recomputed member digest is not the one the catalogue pins")
    if not report.get("inherited_frame", {}).get("predicates"):
        problems.append("no eligibility predicates are bound")
    return {
        "schema": SCHEMA + ".verification",
        "verified": not problems,
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bind the SFIR9 cohort input")
    parser.add_argument("--namespace", type=Path, default=NS)
    parser.add_argument("--member", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        report = binding(namespace=args.namespace, member_path=args.member)
    except CohortInputRefused as error:
        print(f"REFUSED  {error}")
        return 1
    frame = report["inherited_frame"]
    print(f"catalogue    {report['catalogue']['zenodo_doi']}")
    print(f"member       {report['catalogue']['member_name']}")
    print(f"re-hashed    {report['member_verification']['sha256_recomputed']}")
    print(f"bytes        {report['member_verification']['bytes_on_disk']:,}")
    for record in report["input_modules"]:
        print(f"reader       {record['module']:<22} {record['sha256'][:23]}")
    print(f"frame        {len(frame['predicates'])} predicates inherited from SFIR7")
    for predicate in frame["predicates"]:
        value = predicate["value"]
        shown = value if not isinstance(value, list) else f"{len(value)} values"
        print(f"  predicate  {predicate['field']:<20} {predicate['op']:<14} {shown}")
    print(f"independence frame {frame['independence']['frame_entered_repository_at']}"
          f" < protocol {frame['independence']['protocol_entered_repository_at']}")
    print(f"binding      {report['binding_digest']}")
    print(f"verify       {verify(report)}")
    OUTPUT.write_bytes(json.dumps(report, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(f"written to   {OUTPUT.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
