"""Declared acquisition inputs for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1.

Written and hashed BEFORE any V2R1 fetch. This module is freeze rung 0, and it
exists because V2R1 differs from every identity closure before it in one way
that matters: it ACQUIRES its material. V1 and the abandoned V2 both drew from a
cache that already existed, so the earliest thing they could pin was the
protocol. Here the fetches have not happened yet, which means selection could be
steered -- consciously or not -- by what the sources started returning. Pinning
the frame first is what makes that impossible rather than merely unlikely.

WHY V2 WAS ABANDONED, in one paragraph, because a reader of this file needs it.
Metadata-only enumeration over the existing cache left 16 eligible pairs. At the
8/514 violated-lineage rate V1 published, a 16-pair cohort observes at least one
old-rate violation with probability 0.222 -- so a clean reading would have been
about 78% likely even if the defect were completely untouched. Zero-tolerance
acceptance does not repair an underpowered denominator. That route was
classified ABORTED_BEFORE_FREEZE / INSUFFICIENT_FRESH_CONFIRMATORY_MATERIAL and
preserved rather than mutated into this one.

EVERYTHING HERE IS DECIDABLE FROM METADATA AND SOURCE IDENTITY ALONE. No clause
below can be evaluated only by reading a revision's content, and none of them
mentions a diff, a change, an ambiguity, a facet or an outcome. That is the
property that makes V2R1 prospective.
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

PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1"

#: Salt for the frozen traversal order. Distinct from every predecessor's, so
#: two studies over overlapping source sets cannot walk them in the same
#: sequence and silently inherit each other's head.
ORDER_SALT = ":icmc-v2r1"


# ---------------------------------------------------------------------------
# families
#
# Three, and the omission of a fourth is recorded here rather than in a
# footnote. Wikipedia is an SFI3 ROOT family. Proving V2R1's disjointness from
# SFI3 roots using metadata alone is not reliably possible for it, and the only
# way to make it provable would be to expand an SFI3 category -- which would
# spend the prospective confirmatory material of another study to buy a
# disjointness argument here. Forbidden outright. Wikipedia is therefore
# declared and excluded, never quietly dropped.

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
# The basis is grammar breadth and source supply, exactly as SFI1 through SFI3
# used, and explicitly NOT pass yield, violation rate, or any observed outcome.
# The 8/514 rate that sized the FLOOR is a sample-size planning prior and
# appears nowhere else: not in a quota, not in a numerator, not in a
# denominator, not in the scorer.

#: Admitted-pair floor. The pre-measurement cohort sufficiency gate.
FLOOR = 200
FAMILIES_REQUIRED = 3

#: Candidate pairs to CONSTRUCT, before integrity and disjointness filtering.
#: Over-selection happens BEFORE any outcome exists; padding after measuring is
#: forbidden. SFI3 ran 290 -> 200 (1.45x). V2R1 uses a wider margin because its
#: filtering is heavier: every candidate must additionally clear disjointness
#: against nine excluded sets and whole-group collision exclusion.
PRIMARY_TARGET = 460

#: Per-family construction ceilings. A family that under-delivers is reported
#: short. Redistribution into a family that yields more is FORBIDDEN -- topping
#: up from the productive family is selection responding to supply, and supply
#: is not independent of the sources' revision behaviour.
FAMILY_QUOTA: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 190,
        "regulation_ecfr": 160,
        "sec_edgar": 110,
    }
)

#: The same composition as a share, declared rather than computed so the two
#: cannot disagree after an edit to one of them.
FAMILY_SHARE: Mapping[str, float] = MappingProxyType(
    {
        "git_docs": 0.41,
        "regulation_ecfr": 0.35,
        "sec_edgar": 0.24,
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
        "basis": "grammar breadth and source supply, carried forward from SFI1 through SFI3",
        "explicitly_not_basis": (
            "violation rate, pass yield, closure outcome or any V1/V2 observation"
        ),
        "frozen_before": "any V2R1 fetch, any V2R1 diff, any V2R1 score",
        "redistribution": "forbidden; an under-delivering family is reported short",
        "floor_prior": (
            "FLOOR=200 sized from V1's published 8/514 as a SAMPLE-SIZE PLANNING "
            "PRIOR only: 191 pairs reaches about 95.0% and 200 reaches about 95.66% "
            "chance of observing at least one old-rate violation. The ratio sizes "
            "the experiment and never scores it."
        ),
    }
)


# ---------------------------------------------------------------------------
# traversal, pair construction, and the rules that reject
#
# Every clause is decidable from metadata. None reads a revision's content in
# order to select; the integrity rules read BYTES to verify a digest, which is a
# different act from inspecting content to choose.

TRAVERSAL: Mapping[str, Any] = MappingProxyType(
    {
        "order": (
            "families in the order FAMILIES declares; within a family, containers "
            "sorted lexicographically by container id; within a container, source "
            "documents sorted lexicographically by source id. Deterministic, and "
            "reproducible from this file without a fetch."
        ),
        "container_cap": (
            "at most 4 source documents per container -- repository, CFR part, "
            "issuer -- so no single container dominates the cohort"
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
            "stop when PRIMARY_TARGET candidates are constructed or the declared "
            "sources are exhausted, whichever comes first. NEVER 'keep acquiring "
            "until a quarantine case appears' -- a stopping rule that reads the "
            "outcome makes selection a function of the result."
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
# disjointness -- what V2R1 may not draw from, and why each entry is there
#
# The founder declined a universal doctrine that any read burns a lineage for
# every future question. Burn scope belongs to each corpus's OWN predeclared
# contract. So this is not "every study that exists"; it is the studies whose
# own contracts, or whose role in this programme, put their lineages out of
# reach for a CONFIRMATORY identity closure.

EXCLUDED_SETS: tuple[Mapping[str, str], ...] = (
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
                "burn is GLOBAL for confirmatory reuse. Reinterpreting it now as "
                "spent-only-for-the-value-bearing-question would narrow a predeclared "
                "burn after observing the material."
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
)


# ---------------------------------------------------------------------------
# SOURCE ROOTS -- the WHICH, which the first frame was missing
#
# Founder ruling section 7 requires source repositories, CFR parts and issuer
# sets predeclared. The first V2R1 frame declared families, quotas and traversal
# rules but none of these, so the traversal knew HOW to walk the sources without
# knowing WHICH -- underdetermined, and still able to reach for convenient
# material. That frame was superseded before a single fetch. The error is
# recorded in the incident ledger rather than smoothed away.
#
# EVERY ROOT BELOW WAS AVAILABILITY-PROBED BEFORE BEING DECLARED, and the probes
# asked only metadata questions: does this repository exist, does this prefix
# hold documents, how many sections of this CFR part carry two or more distinct
# dated versions. No revision content was read, nothing was diffed, and no
# identity outcome was touched. That is the same class of question the founder
# restricted candidate enumeration to.
#
# DISJOINTNESS IS ESTABLISHED AT CONTAINER LEVEL, which is stronger than the
# lineage-level disjointness the ruling requires and far easier to prove: not one
# of these repositories appears among the 176 any earlier sources module names,
# and not one of these CFR parts appears among the ~185 already consumed. A
# container that was never touched cannot contain a lineage that was.

#: 38 documentation repositories, none of them among the 176 already used,
#: and none of them one of SFI3's 32 declared root repositories.
GIT_ROOTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("apache", "answer", "docs", "main", "Apache-2.0"),
    ("authelia", "authelia", "docs/content", "master", "Apache-2.0"),
    ("celery", "celery", "docs", "main", "NOASSERTION"),
    ("cue-lang", "cue", "doc/tutorial", "master", "Apache-2.0"),
    ("directus", "docs", "content", "main", "NOASSERTION"),
    ("dotnet", "aspnetcore", "docs", "main", "MIT"),
    ("element-hq", "synapse", "docs", "develop", "AGPL-3.0"),
    ("falcosecurity", "falco-website", "content/en/docs", "master", "CC-BY-4.0"),
    ("godotengine", "godot-docs", "tutorials", "master", "NOASSERTION"),
    ("JetBrains", "kotlin-web-site", "docs/topics", "master", "Apache-2.0"),
    ("keycloak", "keycloak", "docs/documentation", "main", "Apache-2.0"),
    ("ktorio", "ktor-documentation", "topics", "main", "Apache-2.0"),
    ("kubeflow", "website", "content/en/docs", "master", "CC-BY-4.0"),
    ("longhorn", "website", "content/docs", "master", "Apache-2.0"),
    ("matrix-org", "matrix-spec", "content", "main", "Apache-2.0"),
    ("medusajs", "medusa", "www/apps/book/app", "develop", "NOASSERTION"),
    ("milvus-io", "milvus-docs", "site/en", "v3.0.x", "Apache-2.0"),
    ("minio", "minio", "docs", "master", "AGPL-3.0"),
    ("mlflow", "mlflow", "docs/docs", "master", "Apache-2.0"),
    ("n8n-io", "n8n-docs", "docs", "main", "NOASSERTION"),
    ("netdata", "netdata", "docs", "master", "GPL-3.0"),
    ("nginx", "documentation", "content", "main", "BSD-2-Clause"),
    ("ory", "docs", "docs", "master", "Apache-2.0"),
    ("outline", "outline", "docs", "main", "NOASSERTION"),
    ("psf", "requests", "docs", "main", "Apache-2.0"),
    ("qdrant", "landing_page", "qdrant-landing/content/documentation", "master", "NOASSERTION"),
    ("ray-project", "ray", "doc/source", "master", "Apache-2.0"),
    ("rook", "rook", "Documentation", "master", "Apache-2.0"),
    ("saleor", "saleor-docs", "docs", "main", "NOASSERTION"),
    ("SigNoz", "signoz", "frontend/src", "main", "NOASSERTION"),
    ("sigstore", "docs", "content/en/about", "main", "MIT"),
    ("sqlalchemy", "sqlalchemy", "doc/build", "main", "MIT"),
    ("strapi", "documentation", "docusaurus/docs", "main", "NOASSERTION"),
    ("tokio-rs", "website", "content", "master", "MIT"),
    ("wazuh", "wazuh-documentation", "source", "main", "NOASSERTION"),
    ("weaviate", "docs", "docs", "main", "NOASSERTION"),
    ("woodpecker-ci", "woodpecker", "docs/docs", "main", "Apache-2.0"),
    ("zulip", "zulip", "docs", "main", "Apache-2.0"),
)

#: 40 CFR parts, none among the ~185 already consumed. The probe found
#: 1,636 sections carrying two or more distinct dated versions across them, so
#: supply is not the binding constraint here; the container cap is.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("7", "760", "Emergency livestock assistance"),
    ("9", "417", "HACCP systems"),
    ("10", "73", "Physical protection of plants and materials"),
    ("12", "1006", "Debt collection practices"),
    ("14", "43", "Maintenance, rebuilding and alteration"),
    ("14", "107", "Small unmanned aircraft systems"),
    ("15", "922", "National marine sanctuary program"),
    ("17", "232", "Electronic filing rules"),
    ("19", "24", "Customs financial and accounting procedure"),
    ("20", "655", "Temporary employment of foreign workers"),
    ("21", "312", "Investigational new drug application"),
    ("21", "807", "Establishment registration and device listing"),
    ("22", "41", "Visas: documentation of nonimmigrants"),
    ("24", "570", "Community development block grants"),
    ("26", "20", "Estate tax"),
    ("27", "19", "Distilled spirits plants"),
    ("28", "36", "Nondiscrimination on the basis of disability"),
    ("29", "1630", "Regulations to implement the ADA"),
    ("30", "285", "Renewable energy on the outer continental shelf"),
    ("31", "800", "Foreign investment regulations"),
    ("33", "155", "Oil or hazardous material pollution prevention"),
    ("34", "106", "Nondiscrimination on the basis of sex"),
    ("37", "1", "Rules of practice in patent cases"),
    ("38", "17", "Medical benefits"),
    ("40", "82", "Protection of stratospheric ozone"),
    ("40", "122", "EPA administered permit programs"),
    ("40", "273", "Standards for universal waste management"),
    ("42", "424", "Conditions for Medicare payment"),
    ("42", "438", "Managed care"),
    ("43", "2800", "Rights-of-way under FLPMA"),
    ("45", "156", "Health insurance issuer standards"),
    ("46", "199", "Lifesaving systems"),
    ("47", "54", "Universal service"),
    ("47", "97", "Amateur radio service"),
    ("48", "16", "Types of contracts"),
    ("49", "40", "Drug and alcohol testing programs"),
    ("49", "172", "Hazardous materials tables"),
    ("49", "236", "Rules for railroad signal systems"),
    ("50", "216", "Taking marine mammals incidental"),
    ("50", "660", "Fisheries off west coast states"),
)

#: The issuer set is a RULE rather than a list, because EDGAR's issuer universe
#: is itself a published, deterministic artifact and copying 10,403 rows into
#: this file would make the frame less checkable, not more. The rule is fully
#: decidable from metadata and reproducible by anyone.
SEC_ISSUER_RULE: Mapping[str, Any] = MappingProxyType(
    {
        "universe": "https://www.sec.gov/files/company_tickers.json",
        "universe_size_at_declaration": 10403,
        "order": "ascending by CIK, which is stable and not chosen by us",
        "pair_construction": (
            "a source document is (CIK, base form, period of report). An amendment "
            "pair exists where the same (CIK, base form, period) carries both an "
            "original filing and its /A amendment. Both sides are named by "
            "accession number from the submissions API -- metadata only."
        ),
        "forms": ["10-K", "10-Q", "20-F", "8-K"],
        "submissions_api": "https://data.sec.gov/submissions/CIK##########.json",
        "availability_probe": (
            "20 of the first 25 issuers by CIK carry at least one amendment pair, so "
            "the quota is reachable well inside the ordered universe"
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
            "containers": [
                {
                    "owner": owner,
                    "repo": repo,
                    "prefix": prefix,
                    "default_branch": branch,
                    "licence": licence,
                }
                for owner, repo, prefix, branch, licence in GIT_ROOTS
            ],
            "container_count": len(GIT_ROOTS),
            "container_cap": CONTAINER_CAP["git_docs"],
            "max_candidates": len(GIT_ROOTS) * CONTAINER_CAP["git_docs"],
        },
        "regulation_ecfr": {
            "containers": [
                {"title": title, "part": part, "name": name}
                for title, part, name in ECFR_ROOTS
            ],
            "container_count": len(ECFR_ROOTS),
            "container_cap": CONTAINER_CAP["regulation_ecfr"],
            "max_candidates": len(ECFR_ROOTS) * CONTAINER_CAP["regulation_ecfr"],
        },
        "sec_edgar": {
            "rule": dict(SEC_ISSUER_RULE),
            "container_cap": CONTAINER_CAP["sec_edgar"],
        },
        "availability_probed_before_declaration": True,
        "probe_asked_only": (
            "existence, prefix contents, revision counts and amendment-pair presence "
            "-- all metadata. No revision content was read and no identity outcome "
            "was inspected."
        ),
        "container_level_disjointness": (
            "no declared repository appears among the 176 named by any earlier "
            "sources module, and no declared CFR part appears among the ~185 already "
            "consumed. SEC disjointness is proven per-lineage at enumeration, since "
            "its issuer set is a rule rather than a fixed list."
        ),
    }


def frame_declaration() -> dict[str, Any]:
    """The complete frame, as the object freeze rung 0 seals.

    Assembled from the literals above rather than restated, so the receipt and
    this module cannot drift apart after an edit to one of them.
    """
    return {
        "protocol_id": PROTOCOL_ID,
        "order_salt": ORDER_SALT,
        "families": list(FAMILIES),
        "excluded_families": dict(EXCLUDED_FAMILIES),
        "family_quota": dict(FAMILY_QUOTA),
        "family_share": dict(FAMILY_SHARE),
        "family_floor": dict(FAMILY_FLOOR),
        "primary_target": PRIMARY_TARGET,
        "floor": FLOOR,
        "families_required": FAMILIES_REQUIRED,
        "quota_basis": dict(QUOTA_BASIS),
        "traversal": dict(TRAVERSAL),
        "integrity_rejection": dict(INTEGRITY_REJECTION),
        "cache_identity": dict(CACHE_IDENTITY),
        "excluded_sets": [dict(entry) for entry in EXCLUDED_SETS],
        "burn_scope_read_and_found_none": dict(BURN_SCOPE_READ_AND_FOUND_NONE),
        "forbidden_in_selection": list(FORBIDDEN_IN_SELECTION),
        "source_roots": source_roots(),
    }


def frame_digest() -> str:
    """Content digest of the frame declaration, stable across runs."""
    body = json.dumps(frame_declaration(), sort_keys=True, ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
