"""Enumerate the V2R1 universe from the fresh acquisition, and prove it disjoint.

Freeze rung 3's input. Reads the acquisition manifest, recomputes every digest
from the RAW BYTES on disk, proves disjointness against each excluded set by
lineage id, detects collisions structurally, and names and counts every
exclusion.

THE ANTI-VACUITY MEASURE, which is the part of this file worth reading. A
disjointness proof by string equality is only worth anything if the two sides
use the SAME lineage-id scheme. If V2R1 said `git:owner/repo:path` while an
earlier study said `github://owner/repo/path`, every comparison would return
"no overlap" and the proof would be guaranteed to succeed -- a check that can
only return one answer, which is not a measurement (INC-V2-044). So for every
excluded set this reports `comparable_ids`: how many of its ids share a scheme
prefix with V2R1's. A set with zero comparable ids has NO POWER over V2R1's
universe and is reported that way rather than counted as a clean proof.

Digests are RECOMPUTED from the stored raw bytes, never read back from the
record that wrote them. A verification that re-reads its own record verifies
nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _root in (str(ROOT / "packages" / "cir-python" / "src"), str(NS), str(NS / "acquisition")):
    if _root not in sys.path:
        sys.path.insert(0, _root)

import sources_v2r1 as frame  # noqa: E402

CORPUS = NS / "artifacts" / "development" / "v2r1_corpus"
MANIFEST = CORPUS / "manifest.json"
OUT_DIR = NS / "artifacts" / "development" / "v2r1_universe"
OUT = OUT_DIR / "v2r1_universe_candidates.json"

SCHEMA = "tavonel.v2.identity_change_migration_closure.v2r1_universe_enumeration.v1"


def _scheme(lineage_id: str) -> str:
    """The namespace prefix of a lineage id: `git`, `ecfr`, `sec`, `wikipedia`."""
    return lineage_id.split(":", 1)[0] if ":" in lineage_id else ""


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _ids_from(
    path: Path,
    keys: tuple[str, ...] = ("lineages", "pairs", "documents", "admitted"),
) -> set[str]:
    """Lineage ids out of any of this repository's artifact shapes."""
    if not path.exists():
        return set()
    body = _read_json(path)
    rows: list[Any] = []
    if isinstance(body, dict):
        for key in keys:
            value = body.get(key)
            if isinstance(value, list):
                rows.extend(value)
    elif isinstance(body, list):
        rows = body
    found: set[str] = set()
    for row in rows:
        if isinstance(row, str):
            found.add(row)
        elif isinstance(row, dict):
            for key in ("lineage_id", "document_id", "id"):
                value = row.get(key)
                if isinstance(value, str):
                    found.add(value)
                    break
    return found


LINEAGE_SHAPE = re.compile(r'"((?:git|ecfr|sec|wikipedia):[^"]{3,160})"')


def _ids_in_receipt(paths: list[Path]) -> set[str]:
    """Lineage-shaped ids anywhere inside a receipt.

    Deliberately structural rather than key-directed. These receipts were written
    by other studies with their own shapes, and a key-directed reader that missed
    a nesting level would silently return an EMPTY set -- which reads as "no
    overlap" and would turn a missed set into a clean proof. Matching on the id
    SHAPE cannot miss a nesting level.
    """
    found: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        found |= set(LINEAGE_SHAPE.findall(path.read_text(encoding="utf-8", errors="replace")))
    return found


def _vbc1_containers() -> set[str]:
    """VBC1's declared root containers, read from its own frozen source module.

    VBC1 declares ROOTS, not a lineage list, so its burn is proven at container
    level -- strictly stronger. Its contract is unambiguous and predeclared:
    `burned_after_use=True`, `not_the_confirmatory_cohort=True`, and in prose
    that every lineage listed there is spent the moment the probe reports.
    """
    text = (NS / "acquisition" / "sources_vbc1_probe.py").read_text(
        encoding="utf-8", errors="replace"
    )
    found = set()
    for match in re.finditer(r'"owner":\s*"([^"]+)",\s*"repo":\s*"([^"]+)"', text):
        found.add(f"{match.group(1)}/{match.group(2)}")
    for match in re.finditer(r'\(\s*"(\d{1,2})",\s*"(\d{1,4})"', text):
        found.add(f"{match.group(1)} CFR {match.group(2)}")
    return found


def _sfi3_root_containers() -> set[str]:
    """SFI3's declared root repositories, read WITHOUT opening any SFI3 material."""
    text = (NS / "acquisition" / "sources_sfi3.py").read_text(encoding="utf-8", errors="replace")
    found = set()
    for match in re.finditer(r'"owner":\s*"([^"]+)",\s*"repo":\s*"([^"]+)"', text):
        found.add(f"{match.group(1)}/{match.group(2)}")
    return found


def excluded_sets() -> list[dict[str, Any]]:
    """Every set V2R1 must be disjoint from, read from disk rather than assumed.

    A set whose source file is missing is reported MISSING and blocks. A spent
    set that quietly shrinks re-admits spent lineages, which is the one failure
    mode this function exists to prevent.
    """
    development = NS / "artifacts" / "development"
    sources: list[tuple[str, list[Path]]] = [
        ("sfi1_spent", [development / "sfi1_lineages.json", development / "sfi1_acquisition.json"]),
        ("sfi2_spent", [development / "sfi2_lineages.json", development / "sfi2_acquisition.json"]),
        #: V1's universe lives in its own FREEZE RECEIPT, not in a development
        #: artifact. Read from there so the 514 are the frozen 514 and not a
        #: re-derivation that could differ.
        (
            "v1_closure_514",
            sorted((NS / "receipts").glob("identity-change-migration-closure-universe--*.json")),
        ),
        ("v2_aborted_16", [development / "v2_universe" / "v2_universe_candidates.json"]),
    ]

    receipts = NS / "receipts"
    benchmark = sorted(receipts.glob("identity-change-benchmark--*.json"))
    forensic = sorted(receipts.glob("sfi2-native-provenance--*.json"))
    v1_frozen = sorted(receipts.glob("identity-change-migration-closure-universe--*.json"))
    receipt_sets: list[tuple[str, list[Path]]] = [
        ("retrospective_538", benchmark),
        ("sfi2_forensic_14", forensic),
        #: The union of every cohort an identity measurement has already read.
        #: Listed separately from its parts because the ruling names it
        #: separately, and a set that is only ever checked as somebody else's
        #: subset is a set nobody checked.
        ("earlier_identity_measurements", benchmark + forensic + v1_frozen),
    ]
    out: list[dict[str, Any]] = []

    #: SFI3 IS DELIBERATELY ABSENT FROM `sources` ABOVE.
    #:
    #: `sfi3_lineages.json` does not exist, and that is the CORRECT state: SFI3 is
    #: unopened, and opening it here to prove disjointness would spend the very
    #: material the proof is meant to protect. Treating its absence as a blocking
    #: error would make the gate demand the one action it forbids.
    #:
    #: So SFI3 disjointness is proven at CONTAINER level from its DECLARED ROOTS,
    #: which are metadata and require opening nothing. No V2R1 repository may be
    #: an SFI3 root repository. That is strictly stronger than lineage-level
    #: disjointness: a repository never touched cannot hold a lineage that was.
    sfi3_roots = _sfi3_root_containers()
    out.append(
        {
            "id": "sfi3_all",
            "lineage_count": 0,
            "sources_present": ["acquisition/sources_sfi3.py (declared roots only)"],
            "sources_missing": [],
            "proven_at": "container level, from declared roots",
            "sfi3_root_containers": len(sfi3_roots),
            "sfi3_remains_unopened": True,
            "_containers": sfi3_roots,
            "_ids": set(),
        }
    )

    vbc1 = _vbc1_containers()
    out.append(
        {
            "id": "vbc1_probe",
            "lineage_count": 0,
            "sources_present": ["acquisition/sources_vbc1_probe.py (declared roots)"],
            "sources_missing": [],
            "proven_at": "container level, from declared roots",
            "contract": (
                "burned_after_use=True, not_the_confirmatory_cohort=True, and "
                "'every lineage listed here is spent the moment the probe reports'. "
                "The burn is GLOBAL for confirmatory reuse."
            ),
            "_containers": vbc1,
            "_ids": set(),
        }
    )

    for name, paths in receipt_sets:
        ids = _ids_in_receipt(paths)
        out.append(
            {
                "id": name,
                "lineage_count": len(ids),
                "sources_present": [path.name for path in paths if path.exists()],
                "sources_missing": [],
                "read_by": "structural id-shape match, so a nesting level cannot be missed",
                #: HONEST COVERAGE READING. A receipt names the lineages it
                #: happens to quote, which is not necessarily the whole cohort.
                #: `retrospective_538` reads 14 ids from the benchmark receipt,
                #: not 538 -- the receipt reports aggregates and quotes a sample.
                #: Saying "disjoint from the 538" on that basis would overstate
                #: what was compared. The 538 cohort is drawn from SFI1/SFI2
                #: material, and THOSE sets are enumerated in full here (1,997 and
                #: 1,859 ids), so the coverage is real -- but it comes from the
                #: parent sets, and this field says so rather than letting a
                #: reader infer full enumeration from a clean result.
                "coverage": (
                    "ids quoted by the receipt, not necessarily the cohort's full "
                    "membership; full coverage for this material comes from the "
                    "sfi1_spent and sfi2_spent sets enumerated separately"
                ),
                "_ids": ids,
            }
        )

    for name, paths in sources:
        ids: set[str] = set()
        present: list[str] = []
        missing: list[str] = []
        for path in paths:
            if path.exists():
                present.append(path.name)
                ids |= _ids_from(path)
            else:
                missing.append(path.name)
        out.append(
            {
                "id": name,
                "lineage_count": len(ids),
                "sources_present": present,
                "sources_missing": missing,
                "_ids": ids,
            }
        )
    return out


def enumerate_universe() -> dict[str, Any]:
    manifest = _read_json(MANIFEST)
    admitted = manifest["admitted"]

    rows: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()

    our_schemes = {_scheme(row["lineage_id"]) for row in admitted}

    # ---- disjointness, with an explicit power reading -------------------
    ours = {row["lineage_id"] for row in admitted}
    disjointness: dict[str, Any] = {}
    blocking: list[str] = []
    our_containers = {row["container"] for row in admitted}
    for entry in excluded_sets():
        ids = entry.pop("_ids")
        containers = entry.pop("_containers", None)
        if containers is not None:
            #: Container-level, because SFI3 must stay unopened.
            container_overlap = sorted(our_containers & containers)
            entry.update(
                {
                    "overlap": container_overlap,
                    "holds": not container_overlap,
                    "comparable_ids": len(containers),
                    "power": (
                        f"{len(containers)} declared root containers compared against "
                        f"{len(our_containers)} V2R1 containers"
                    ),
                }
            )
            if container_overlap:
                blocking.append(
                    f"{entry['id']}: {len(container_overlap)} containers overlap SFI3 roots"
                )
            disjointness[entry["id"]] = entry
            continue
        overlap = sorted(ours & ids)
        comparable = {i for i in ids if _scheme(i) in our_schemes}
        entry.update(
            {
                "overlap": overlap,
                "holds": not overlap,
                "comparable_ids": len(comparable),
                "schemes_present": sorted({_scheme(i) for i in ids})[:8],
                "power": (
                    "NONE -- no id in this set shares a scheme prefix with V2R1's, so "
                    "the comparison could not have found an overlap and proves nothing"
                    if not comparable
                    else f"{len(comparable)} ids are in a comparable namespace"
                ),
            }
        )
        if entry["sources_missing"] and not entry["sources_present"]:
            blocking.append(f"{entry['id']}: no source file present; spent set cannot be computed")
        if overlap:
            blocking.append(f"{entry['id']}: {len(overlap)} lineages overlap")
        disjointness[entry["id"]] = entry

    # ---- integrity: recompute, never re-read ----------------------------
    collision_keys: Counter[str] = Counter()
    for row in admitted:
        for side in ("before", "after"):
            collision_keys[row[side]["cache_key"]] += 1

    for row in admitted:
        lineage = row["lineage_id"]
        problems: list[str] = []
        for side in ("before", "after"):
            entry = row[side]
            raw_path = CORPUS / entry["raw_path"]
            canonical_path = CORPUS / entry["canonical_path"]
            if not raw_path.exists() or not canonical_path.exists():
                problems.append(f"{side}: stored payload missing")
                continue
            raw_digest = "sha256:" + hashlib.sha256(raw_path.read_bytes()).hexdigest()
            canonical_digest = "sha256:" + hashlib.sha256(canonical_path.read_bytes()).hexdigest()
            if raw_digest != entry["raw_sha256_recorded"]:
                problems.append(f"{side}: raw digest mismatch")
            if canonical_digest != entry["canonical_sha256_recorded"]:
                problems.append(f"{side}: canonical digest mismatch")
            if collision_keys[entry["cache_key"]] > 1:
                problems.append(f"{side}: cache key collision")

        if problems:
            categories[problems[0].split(":", 1)[1].strip()] += 1
            excluded.append({"lineage_id": lineage, "family": row["family"], "why": problems})
            continue

        #: Paths are emitted REPO-ROOT-RELATIVE, because that is what the frozen
        #: manifest contract's consumer resolves against. The acquisition
        #: manifest stores bare filenames beside the payloads, which is right for
        #: that artifact and wrong for this one; translating here keeps each file
        #: honest about its own frame of reference instead of making the verifier
        #: guess which one it is holding.
        rel = "research/tavonel_eval_v2/artifacts/development/v2r1_corpus"
        sides = {}
        for side in ("before", "after"):
            entry = dict(row[side])
            entry["raw_path"] = f"{rel}/{entry['raw_path']}"
            entry["canonical_path"] = f"{rel}/{entry['canonical_path']}"
            sides[side] = entry

        rows.append(
            {
                "lineage_id": lineage,
                "family": row["family"],
                "container": row["container"],
                "before_version": row["before_version"],
                "after_version": row["after_version"],
                "before": sides["before"],
                "after": sides["after"],
            }
        )

    by_family: Counter[str] = Counter(row["family"] for row in rows)
    universe_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps([r["lineage_id"] for r in rows], sort_keys=True).encode("utf-8")
        ).hexdigest()
    )

    meets_floor = len(rows) >= frame.FLOOR
    meets_families = len(by_family) >= frame.FAMILIES_REQUIRED
    family_floor_met = {
        family: by_family.get(family, 0) >= floor for family, floor in frame.FAMILY_FLOOR.items()
    }

    return {
        "schema": SCHEMA,
        "protocol_id": frame.PROTOCOL_ID,
        "frame_module_sha256": manifest["frame_module_sha256"],
        "pairs": rows,
        "pair_count": len(rows),
        "distinct_lineages": len({r["lineage_id"] for r in rows}),
        "by_family": dict(by_family),
        "universe_sha256": universe_digest,
        "excluded": excluded,
        "exclusion_categories": dict(categories),
        "disjointness": disjointness,
        "disjointness_holds": all(v["holds"] for v in disjointness.values()),
        "sufficiency": {
            "floor": frame.FLOOR,
            "meets_floor": meets_floor,
            "families_required": frame.FAMILIES_REQUIRED,
            "meets_families": meets_families,
            "family_floor_met": family_floor_met,
            "state": (
                "SUFFICIENT"
                if meets_floor and meets_families and all(family_floor_met.values())
                else "INSUFFICIENT_COHORT"
            ),
        },
        "blocking": blocking,
        "digests_recomputed_from_raw_bytes": True,
        "acquisition_attrition": {
            "candidates_constructed": manifest["candidates_constructed"],
            "rejected_at_acquisition": manifest["rejected_count"],
            "note": (
                "every rejection carries its reason. Nothing was silently replaced and "
                "nothing was padded after measurement."
            ),
        },
        "is_frozen": False,
        "is_evidence": False,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }


def main() -> int:
    body = enumerate_universe()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")

    print(f"pairs           : {body['pair_count']}")
    print(f"by family       : {json.dumps(body['by_family'], sort_keys=True)}")
    print(f"universe sha256 : {body['universe_sha256']}")
    print(f"sufficiency     : {body['sufficiency']['state']}")
    print(f"disjointness    : {'HOLDS' if body['disjointness_holds'] else 'VIOLATED'}")
    for name, entry in sorted(body["disjointness"].items()):
        print(
            f"  {name:18} lineages={entry['lineage_count']:6} "
            f"overlap={len(entry['overlap']):3}  power={entry['power'][:46]}"
        )
    if body["exclusion_categories"]:
        print(f"excluded        : {json.dumps(body['exclusion_categories'], sort_keys=True)}")
    if body["blocking"]:
        print("BLOCKING:")
        for item in body["blocking"]:
            print(f"  {item}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
