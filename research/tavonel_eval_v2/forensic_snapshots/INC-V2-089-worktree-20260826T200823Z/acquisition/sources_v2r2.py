"""The frozen acquisition frame for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2.

Rung 0. Sealed BEFORE a single revision is fetched, because V2R2 acquires its
own material and a frame written after the fetches it authorises is a record of
what was done rather than a constraint on what may be done.

WHAT V2R2 IS. V2R1 executed, returned FAIL, and was adjudicated
INVALID_INSTRUMENT_CONTRACT: its frozen INVARIANT_6(d) equated raw
revision-local logical-id equality with resolver-established cross-revision
identity, so a path rename was scored as a silent appearance plus a silent
disappearance. The clause measured the wrong property. The run stands, the
receipt is untouched, its 285 lineages are SPENT, and no rescore is permitted.
V2R2 is a new instrument over new material -- not a repair of that run.

WHAT IS UNCHANGED, and deliberately. The eight invariants, the zero-tolerance
INVARIANT_6, the >=200 admitted pairs, the >=3 families, the prohibition on
padding after measurement, and the rule that selection may never read an
outcome. Only clause (d)'s ontology moved, and it moved before any V2R2 material
existed.

DISJOINTNESS IS ESTABLISHED AT CONTAINER LEVEL, which is stronger than the
lineage-level disjointness the ruling requires and much easier to prove: not one
repository below appears among the 235 that any earlier sources module names,
not one CFR part below appears among the 215 already consumed, and the SEC rule
starts strictly above the highest CIK V2R1 consumed. A container that was never
touched cannot hold a lineage that was. Lineage-level exclusion still runs on
top of it -- a stronger proof does not license skipping the weaker check.

EVERY ROOT BELOW WAS AVAILABILITY-PROBED BEFORE BEING DECLARED, with metadata
questions only: does this repository exist, does this prefix hold documents, how
many sections of this CFR part carry two or more distinct dated versions, do
issuers above this CIK carry amendment pairs. No revision content was read,
nothing was diffed, and no identity outcome was touched.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2"

#: Salt for the frozen traversal order. Distinct from every predecessor's --
#: V2R1's was ":icmc-v2r1" -- so two studies over overlapping source sets cannot
#: walk them in the same sequence and silently inherit each other's head.
ORDER_SALT = ":icmc-v2r2"


# ---------------------------------------------------------------------------
# families
#
# The same three, and the same omission for the same reason. Wikipedia is an
# SFI3 ROOT family; metadata-only disjointness from SFI3 roots is not reliably
# provable for it, and the only way to make it provable would be to expand an
# SFI3 category -- spending another study's prospective confirmatory material to
# buy a disjointness argument here. Declared and excluded, never quietly
# dropped.

FAMILIES: tuple[str, ...] = ("git_docs", "regulation_ecfr", "sec_edgar")

EXCLUDED_FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "encyclopedia_wikipedia": (
            "SFI3 root family. Metadata-only disjointness from SFI3 roots is not "
            "reliably provable for it, and expanding an SFI3 category to make it "
            "provable is forbidden -- that would spend the prospective confirmatory "
            "material of another study to buy a disjointness argument here."
        ),
    }
)


# ---------------------------------------------------------------------------
# sampling constants -- literals, every one of them
#
# The basis is grammar breadth and PROBED SOURCE SUPPLY, and explicitly not pass
# yield, violation rate, or any observed outcome of V1, V2R1 or anything else.
# V2R1's realised yield is not a basis either: reading how much of V2R1 survived
# filtering and sizing V2R2 to match would be selection responding to a spent
# study's outcome.

#: Admitted-pair floor. The pre-measurement cohort sufficiency gate, carried
#: forward from the founder ruling unchanged. It is not a numerator, not a
#: denominator, and appears nowhere in the scorer.
FLOOR = 200
FAMILIES_REQUIRED = 3

#: Candidate pairs to CONSTRUCT, before integrity and disjointness filtering.
#: Over-selection happens BEFORE any outcome exists; padding after measuring is
#: forbidden without exception.
PRIMARY_TARGET = 460

#: Per-family construction ceilings. Each is inside the probed capacity of its
#: family's declared containers -- 35 repositories at 5 documents each, 34 CFR
#: parts at 4 sections each, and issuers above CIK 8177 at 4 pairs each -- so a
#: quota cannot silently demand material the declared roots cannot supply.
#: A family that under-delivers anyway is REPORTED SHORT. Redistribution into a
#: family that yields more is FORBIDDEN: topping up from the productive family
#: is selection responding to supply, and supply is not independent of the
#: sources' revision behaviour.
FAMILY_QUOTA: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 170,
        "regulation_ecfr": 130,
        "sec_edgar": 160,
    }
)

#: The same composition as a share, declared rather than computed so the two
#: cannot disagree after an edit to one of them.
FAMILY_SHARE: Mapping[str, float] = MappingProxyType(
    {
        "git_docs": 0.37,
        "regulation_ecfr": 0.28,
        "sec_edgar": 0.35,
    }
)

#: Minimum admitted pairs per family. Three families are required, so a cohort
#: that reaches 200 by drawing 198 from one family and one from each of the
#: others satisfies the count while defeating the point of the count.
FAMILY_FLOOR: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 40,
        "regulation_ecfr": 40,
        "sec_edgar": 25,
    }
)

QUOTA_BASIS: Mapping[str, Any] = MappingProxyType(
    {
        "basis": (
            "grammar breadth and PROBED container capacity: 35 repositories x 5, "
            "34 CFR parts x 4, and issuers above CIK 8177 x 4"
        ),
        "explicitly_not_basis": (
            "violation rate, pass yield, closure outcome, or any V1 / V2R1 "
            "observation including V2R1's realised admission yield"
        ),
        "frozen_before": "any V2R2 fetch, any V2R2 diff, any V2R2 score",
        "redistribution": "forbidden; an under-delivering family is reported short",
        "floor_prior": (
            "FLOOR=200 is carried forward from the founder ruling as a "
            "PRE-MEASUREMENT COHORT SUFFICIENCY GATE. V1's published 8/514 sized it "
            "as a sample-size planning prior and appears nowhere else: not in a "
            "quota, not in a numerator, not in a denominator, not in the scorer."
        ),
    }
)


TRAVERSAL: Mapping[str, Any] = MappingProxyType(
    {
        "order": (
            "families in the order FAMILIES declares; within a family, containers "
            "sorted lexicographically by container id; within a container, source "
            "documents sorted lexicographically by source id. Deterministic, and "
            "reproducible from this file without a fetch."
        ),
        "container_cap": (
            "per-family, from CONTAINER_CAP -- repository, CFR part, issuer -- so no "
            "single container dominates the cohort"
        ),
        "pair_construction": (
            "one revision pair per source document: the two most recent DISTINCT "
            "revisions by the source's own revision metadata, before-side older. "
            "Ties broken by the lexicographically smallest revision identifier. "
            "Chosen without reading either revision's content."
        ),
        "oversampling": (
            "construct up to PRIMARY_TARGET candidates in this order, then filter. "
            "Over-selection precedes every outcome. Padding after measurement is "
            "forbidden without exception."
        ),
        "stopping_rule": (
            "stop when the family quota is met or the family's declared roots are "
            "exhausted, whichever comes first. NEVER 'keep acquiring until a "
            "quarantine case appears', and never 'until the cohort looks balanced' "
            "-- a stopping rule that reads the outcome makes selection a function "
            "of the result."
        ),
        "duplicate_rule": (
            "deduplicate by lineage id, keeping the first occurrence in traversal "
            "order. A lineage reachable from two containers is admitted once."
        ),
        "attrition": (
            "a candidate lost to fetch failure, parse failure or integrity "
            "rejection is RECORDED with its reason and never silently replaced. "
            "The realised count is whatever survives; the gate is FLOOR."
        ),
        "insufficient_cohort": (
            "if fewer than FLOOR pairs are admitted, or fewer than "
            "FAMILIES_REQUIRED families clear their FAMILY_FLOOR, the study STOPS "
            "as INSUFFICIENT_COHORT. It does not proceed with a power disclaimer "
            "beside a verdict, and it does not pad after measuring outcomes."
        ),
    }
)

INTEGRITY_REJECTION: Mapping[str, Any] = MappingProxyType(
    {
        "raw_digest": "recomputed for every revision side; a mismatch rejects the pair",
        "canonical_digest": "recomputed for every revision side; a mismatch rejects the pair",
        "parse": "both sides must parse and yield at least 3 canonical units",
        "identical_sides": (
            "a pair whose two sides carry the same raw digest is rejected as not a "
            "revision pair. This is a metadata-level identity check, not a content "
            "judgement about whether anything meaningful changed."
        ),
        "collision_groups": (
            "collisions are detected STRUCTURALLY. If a cache-key or slug collision "
            "makes provenance ambiguous, the ENTIRE collision group is excluded -- "
            "never whichever member is convenient. Every exclusion is named and "
            "counted."
        ),
        "canonical_shape": (
            "both sides must canonicalise into the shape production's "
            "`selective_build.snapshots` reads. V2R1's first eCFR canonicalisation "
            "invented `heading_path` with no `heading` and no `text_sha256`, which "
            "made 106 pairs unmeasurable for a reason unrelated to the migration "
            "(INC-V2-058.2). The shape is mirrored field-for-field from "
            "`canonical_document`, never reinvented per family."
        ),
    }
)


# ---------------------------------------------------------------------------
# cache identity -- INC-V2-046 is not repeated
#
# The abandoned route inherited an 80-character TRUNCATED readable slug as cache
# identity, which is how two distinct lineages came to share a key and how nine
# collision groups had to be excluded whole. A truncated human-readable string
# is a LABEL. It was never an identity and it must not be used as one.

CACHE_IDENTITY: Mapping[str, Any] = MappingProxyType(
    {
        "scheme": "content_addressed",
        "key": (
            "sha256 over the full, untruncated lineage/source identity tuple, plus "
            "the revision's raw content digest. No truncation anywhere in the path."
        ),
        "readable_slug_is": "a LABEL only, never a key, never compared for identity",
        "truncation": "FORBIDDEN in any identity-bearing position",
        "raw_bytes_retained": (
            "every side stores its RAW fetched bytes alongside the canonical "
            "document, so a canonicalisation defect can be repaired by RECOMPUTING "
            "rather than by re-fetching. INC-V2-058.3 is what the alternative "
            "costs: a re-canonicalisation that had to re-read the sources destroyed "
            "`known_at` across 564 documents and the corpus was discarded."
        ),
        "still_required": (
            "structural collision detection, raw digest verification, canonical "
            "digest verification, and whole-collision-group exclusion. A better key "
            "reduces collisions; it does not license skipping the check that finds "
            "them."
        ),
        "historical_p4i_artifacts": "UNTOUCHED. Not rewritten, not re-keyed, not migrated.",
    }
)


# ---------------------------------------------------------------------------
# disjointness -- what V2R2 may not draw from, and why each entry is there
#
# The founder declined a universal doctrine that any read burns a lineage for
# every future question. Burn scope belongs to each corpus's OWN predeclared
# contract. So this is not "every study that exists"; it is the studies whose
# own contracts, or whose role in this programme, put their lineages out of
# reach for a CONFIRMATORY identity closure.

EXCLUDED_SETS: tuple[Mapping[str, str], ...] = (
    MappingProxyType(
        {
            "id": "v2r1_spent_285",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1's frozen universe. The run "
                "executed exactly once and its corpus is SPENT. That it was "
                "adjudicated an invalid instrument does not un-spend the material: "
                "the lineages were measured, their outcomes were read, and a cohort "
                "whose results are known cannot be a prospective confirmatory "
                "denominator. All 285 are excluded by name."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "sfi1_spent",
            "why": "spent by SOURCE_FACT_IR_HELDOUT_V1's own frame and executor",
        }
    ),
    MappingProxyType(
        {
            "id": "sfi2_spent",
            "why": "spent by SOURCE_FACT_IR_HELDOUT_V2's own frame and executor",
        }
    ),
    MappingProxyType(
        {
            "id": "retrospective_538",
            "why": (
                "the retrospective migration-safety regression cohort, reclassified "
                "by founder ruling as retrospective rather than prospective "
                "qualification"
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "sfi2_forensic_14",
            "why": (
                "the fourteen cases that DIAGNOSED the INC-V2-037 defect. A case used "
                "to find a defect cannot certify its repair."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "v1_closure_514",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V1's universe. V1 is a permanent "
                "FAIL and its universe may never become a positive migration-closure "
                "denominator after repair."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "vbc1_probe",
            "why": (
                "sources_vbc1_probe.py declares BEFORE use that every lineage listed "
                "there is spent the moment the probe reports, and that it is not the "
                "confirmatory cohort and must never become it, with "
                "burned_after_use=True and not_the_confirmatory_cohort=True. That "
                "burn is GLOBAL for confirmatory reuse."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "earlier_identity_measurements",
            "why": (
                "any lineage an earlier identity closure or identity regression "
                "already measured; burned for THIS question specifically"
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "sfi3_all",
            "why": (
                "SFI3 roots and every SFI3 lineage, payload and expansion. SFI3 is "
                "the next study's prospective confirmatory material and opening any "
                "of it here would spend it."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "contract_declared_spent",
            "why": (
                "any source whose OWN predeclared contract says it is spent for "
                "confirmatory reuse. Read that contract; do not assume, and do not "
                "generalise from another corpus's contract."
            ),
        }
    ),
)

#: Corpora read and found NOT to declare a confirmatory burn. Recorded so the
#: absence of a declaration is a finding on the record rather than an omission a
#: later reader has to re-derive.
BURN_SCOPE_READ_AND_FOUND_NONE: Mapping[str, str] = MappingProxyType(
    {
        "p4c": (
            "acquisition/sources_p4c.py contains no burn, spent or "
            "confirmatory-reuse declaration of any kind; its frozen SELECTION_RULE "
            "speaks only to cohort construction. Declared burn scope: NONE_DECLARED. "
            "Reported exactly and generalised into nothing. Its individual "
            "disposition is moot regardless -- one lineage cannot constitute a "
            "confirmatory cohort."
        ),
    }
)


# ---------------------------------------------------------------------------
# what selection may never do

FORBIDDEN_IN_SELECTION: tuple[str, ...] = (
    "inspecting revision content in order to choose a candidate",
    "inspecting any identity outcome",
    "probing for ambiguity",
    "probing for changed facets",
    "acquiring until a quarantine case appears",
    "removing a pair after seeing its outcome",
    "adding a pair after seeing any outcome",
    "replacing a family after seeing its yield",
    "adjusting a quota, the floor or a threshold after acquisition",
    "adding an ignore entry",
    "sizing a quota from V2R1's realised admission yield",
)


# ---------------------------------------------------------------------------
# SOURCE ROOTS -- the WHICH, predeclared as founder ruling section 7 requires
#
# 35 documentation repositories, none of them among the 235 any earlier sources
# module names, and none of them one of SFI3's declared root repositories. The
# fifth field is the repository's SPDX licence id as GitHub reports it, recorded
# as PROVENANCE METADATA. It is not a clearance: an OSS licence is copyright
# permission from that contributor and settles nothing about a third party's
# patents, and a repository marked NOASSERTION grants no commercial reuse right
# at all. Nothing here is copied into a product; revisions are fetched, hashed,
# canonicalised and diffed to measure this system's own identity behaviour.

GIT_ROOTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("strimzi", "strimzi-kafka-operator", "documentation", "main", "Apache-2.0"),
    ("hasura", "graphql-engine", "docs/docs", "master", "Apache-2.0"),
    ("appwrite", "appwrite", "docs", "main", "BSD-3-Clause"),
    ("dbt-labs", "docs.getdbt.com", "website/docs", "current", "Apache-2.0"),
    ("great-expectations", "great_expectations", "docs", "develop", "Apache-2.0"),
    ("open-telemetry", "opentelemetry.io", "content/en/docs", "main", "CC-BY-4.0"),
    ("openfaas", "docs", "docs", "master", "MIT"),
    ("tektoncd", "website", "content/en/docs", "main", "Apache-2.0"),
    ("open-policy-agent", "opa", "docs", "main", "Apache-2.0"),
    ("spiffe", "spiffe.io", "content/docs", "master", "NOASSERTION"),
    ("gruntwork-io", "terragrunt", "docs", "main", "MIT"),
    ("opentofu", "opentofu", "website/docs", "main", "MPL-2.0"),
    ("chef", "chef-web-docs", "content", "main", "NOASSERTION"),
    ("apache", "pulsar-site", "docs", "main", "NOASSERTION"),
    ("apache", "flink-web", "docs", "asf-site", "Apache-2.0"),
    ("apache", "druid-website-src", "docs", "master", "NOASSERTION"),
    ("neo4j", "docs-cypher", "modules", "dev", "Apache-2.0"),
    ("surrealdb", "docs.surrealdb.com", "src/content", "main", "NOASSERTION"),
    ("typesense", "typesense-website", "docs-site", "master", "NOASSERTION"),
    ("vespa-engine", "documentation", "en", "master", "NOASSERTION"),
    ("keploy", "docs", "versioned_docs", "main", "Apache-2.0"),
    ("novuhq", "docs", "content", "main", "NOASSERTION"),
    ("formbricks", "formbricks", "docs", "main", "NOASSERTION"),
    ("PostHog", "posthog.com", "contents/docs", "master", "NOASSERTION"),
    ("plausible", "docs", "docs", "master", "CC-BY-SA-4.0"),
    ("matomo-org", "developer-documentation", "docs", "live", "NOASSERTION"),
    ("sveltejs", "svelte.dev", "apps/svelte.dev/content", "main", "NOASSERTION"),
    ("nuxt", "nuxt.com", "content", "main", "MIT"),
    ("nodejs", "nodejs.org", "apps/site/pages/en", "main", "MIT"),
    ("golang", "website", "_content", "master", "BSD-3-Clause"),
    ("tailwindlabs", "tailwindcss.com", "src/docs", "main", "NOASSERTION"),
    ("radix-ui", "website", "data", "main", "MIT"),
    ("micropython", "micropython", "docs", "master", "NOASSERTION"),
    ("espressif", "esp-idf", "docs/en", "master", "Apache-2.0"),
    ("raspberrypi", "documentation", "documentation/asciidoc", "master", "CC-BY-SA-4.0"),
)

#: 34 CFR parts, none among the 215 already consumed. The probe found 1,629
#: sections carrying two or more distinct dated versions across them, so supply
#: is not the binding constraint here; the container cap is.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("7", "1400", "Payment limitation and eligibility"),
    ("7", "273", "Food and nutrition service certification"),
    ("7", "3560", "Direct multi-family housing loans and grants"),
    ("9", "310", "Post-mortem inspection"),
    ("14", "139", "Certification of airports"),
    ("14", "145", "Repair stations"),
    ("15", "30", "Foreign trade regulations"),
    ("19", "181", "USMCA rules of origin"),
    ("21", "1141", "Cigarette and smokeless tobacco labelling"),
    ("21", "888", "Orthopedic devices"),
    ("22", "126", "Prohibited exports and sales to certain countries"),
    ("23", "771", "Environmental impact and related procedures"),
    ("24", "203", "Single family mortgage insurance"),
    ("25", "273", "Education contracts under Johnson-O Malley"),
    ("26", "54", "Pension excise taxes"),
    ("28", "16", "Production or disclosure of material or information"),
    ("29", "2590", "Group health plan requirements"),
    ("29", "4022", "Benefits payable in terminated single-employer plans"),
    ("30", "57", "Safety and health standards for underground metal mines"),
    ("32", "310", "Protection of privacy and access to records"),
    ("33", "151", "Vessels carrying oil and noxious liquid substances"),
    ("37", "401", "Rights to inventions made by contractors"),
    ("38", "21", "Veteran readiness and employment"),
    ("39", "3001", "Rules of practice and procedure"),
    ("40", "745", "Lead-based paint poisoning prevention"),
    ("41", "102-38", "Sale of personal property"),
    ("43", "10", "Native American graves protection and repatriation"),
    ("45", "1321", "Grants to state and community programs on aging"),
    ("46", "28", "Requirements for commercial fishing industry vessels"),
    ("47", "20", "Commercial mobile radio services"),
    ("48", "215", "Contracting by negotiation"),
    ("49", "390", "Federal motor carrier safety regulations, general"),
    ("49", "659", "Rail fixed guideway systems state safety oversight"),
    ("50", "300", "International fisheries regulations"),
)

#: The issuer set is a RULE rather than a list, because EDGAR's issuer universe
#: is itself a published, deterministic artifact and copying 7,998 CIKs into
#: this file would make the frame less checkable, not more. The rule is fully
#: decidable from metadata and reproducible by anyone.
SEC_ISSUER_RULE: Mapping[str, Any] = MappingProxyType(
    {
        "universe": "https://www.sec.gov/files/company_tickers.json",
        "universe_size_at_declaration": 10403,
        "distinct_ciks_at_declaration": 7998,
        "start_after_cik": 8177,
        "why_start_after": (
            "8177 is the highest CIK V2R1 admitted. Starting strictly above it makes "
            "the SEC family container-disjoint from V2R1 by construction, matching "
            "the treatment of the other two families, rather than relying on "
            "lineage-level exclusion alone."
        ),
        "order": "ascending by CIK above the start, which is stable and not chosen by us",
        "pair_construction": (
            "a source document is (CIK, base form, period of report). An amendment "
            "pair exists where the same (CIK, base form, period) carries both an "
            "original filing and its /A amendment. Both sides are named by "
            "accession number from the submissions API -- metadata only."
        ),
        "forms": ["10-K", "10-Q", "20-F", "8-K"],
        "submissions_api": "https://data.sec.gov/submissions/CIK##########.json",
        "availability_probe": (
            "26 of the first 30 issuers above CIK 8177 carry at least one amendment "
            "pair, 146 pairs among those 30, so the quota is reachable well inside "
            "the ordered universe"
        ),
        "stopping": "walk in CIK order until the family quota is met or the universe ends",
    }
)

#: Per-family container caps. Different per family because the containers are
#: different kinds of thing -- a repository holds thousands of documents, a CFR
#: part holds tens of sections, an issuer holds a handful of amendment pairs --
#: and a single number would either starve one family or let another dominate.
CONTAINER_CAP: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 5,
        "regulation_ecfr": 4,
        "sec_edgar": 4,
    }
)


def source_roots() -> dict[str, Any]:
    """The declared roots, assembled from the literals above."""
    return {
        "git_docs": {
            "containers": [f"{owner}/{repo}" for owner, repo, _p, _b, _l in GIT_ROOTS],
            "roots": [
                {
                    "owner": owner,
                    "repo": repo,
                    "prefix": prefix,
                    "branch": branch,
                    "license_metadata": license_id,
                }
                for owner, repo, prefix, branch, license_id in GIT_ROOTS
            ],
            "container_count": len(GIT_ROOTS),
        },
        "regulation_ecfr": {
            "containers": [f"{title}-{part}" for title, part, _n in ECFR_ROOTS],
            "roots": [
                {"title": title, "part": part, "subject": subject}
                for title, part, subject in ECFR_ROOTS
            ],
            "container_count": len(ECFR_ROOTS),
        },
        "sec_edgar": {
            "containers": "RULE",
            "rule": dict(SEC_ISSUER_RULE),
            "container_count": None,
        },
    }


def frame_declaration() -> dict[str, Any]:
    """Everything rung 0 seals, as one JSON-shaped object."""
    return {
        "protocol_id": PROTOCOL_ID,
        "order_salt": ORDER_SALT,
        "families": list(FAMILIES),
        "excluded_families": dict(EXCLUDED_FAMILIES),
        "floor": FLOOR,
        "families_required": FAMILIES_REQUIRED,
        "primary_target": PRIMARY_TARGET,
        "family_quota": dict(FAMILY_QUOTA),
        "family_share": dict(FAMILY_SHARE),
        "family_floor": dict(FAMILY_FLOOR),
        "quota_basis": dict(QUOTA_BASIS),
        "traversal": dict(TRAVERSAL),
        "integrity_rejection": dict(INTEGRITY_REJECTION),
        "cache_identity": dict(CACHE_IDENTITY),
        "excluded_sets": [dict(entry) for entry in EXCLUDED_SETS],
        "burn_scope_read_and_found_none": dict(BURN_SCOPE_READ_AND_FOUND_NONE),
        "forbidden_in_selection": list(FORBIDDEN_IN_SELECTION),
        "container_cap": dict(CONTAINER_CAP),
        "source_roots": source_roots(),
    }


def frame_digest() -> str:
    """Canonical digest of the declaration, independent of this file's comments."""
    body = json.dumps(frame_declaration(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
