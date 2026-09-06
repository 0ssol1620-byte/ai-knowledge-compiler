"""The frozen acquisition frame for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3.

Rung 0. Sealed BEFORE a single revision is fetched. V2R3 acquires its own
material, so the frame that decides WHAT to acquire has to be pinned before any
content exists -- otherwise selection could be steered, consciously or not, by
what the fetches started returning.

WHAT V2R3 IS. V2R2 executed exactly once and returned FAIL. The founder
adjudicated that run INVALID_INSTRUMENT_CONTRACT: for a unit the resolver called
NEW while the identity-uncertainty quarantine held it, the frozen instrument
simultaneously REQUIRED and FORBADE `unit_added`. No production behaviour could
have satisfied it. The run stands, the receipt is untouched, its 270 lineages
are SPENT, and no rescore is permitted. V2R3 is a new instrument over new
material -- not a repair of that run, and not a repair of production.

    V2R1  read a raw snapshot id as a resolved identity
    V2R2  read a resolver-local decision as a final disposition

Both collapsed a layer production keeps separate. The repaired instrument keeps
three: the resolver's decision, the independent quarantine overlay, and the
EFFECTIVE disposition that composes them -- which is the only one anybody is
entitled to assert. `tools/v2r3_state_table.py` proves, before this frame is
frozen, that no reachable combination carries contradictory obligations.

WHAT IS UNCHANGED, and deliberately. The eight invariants, the zero-tolerance
INVARIANT_6, the >=200 admitted pairs, the >=3 families, the prohibition on
padding after measurement, and the rule that selection may never read an
outcome. The floor is not lowered and the cohort is not selected for quarantine
or ambiguity outcomes -- selecting for the shape that broke V2R2 would make the
next result a statement about the selection.

DISJOINTNESS IS ESTABLISHED AT CONTAINER LEVEL and proved through ONE reader.
`tools/root_identity.py` canonicalises every root any earlier sources module has
ever declared -- 875 identities across four families, in seventeen different
attribute shapes -- and every candidate below was screened against it BEFORE
being probed. V2R2 needed that reader and did not have it: it declared 7 CFR 273
as fresh when SFI1 had already spent its sections and VBC1 named it as a root,
because the pre-declaration scan matched one tuple shape out of many. A root
whose shape cannot be interpreted is UNVERIFIABLE and BLOCKS. It is never
assumed disjoint.

EVERY ROOT BELOW WAS AVAILABILITY-PROBED BEFORE BEING DECLARED, with metadata
questions only: does this repository exist, how many documents does this prefix
hold, how many sections of this CFR part carry two or more distinct dated
versions, do issuers above this CIK carry amendment pairs. No revision content
was read, nothing was diffed, and no identity outcome was touched. A count of
how many section identifiers have two dated versions is a supply question about
the SOURCE, not a question about what changed inside it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R3"

#: Salt for the frozen traversal order. Distinct from every predecessor's --
#: V2R1's was ":icmc-v2r1", V2R2's ":icmc-v2r2" -- so two studies over
#: overlapping source sets cannot walk them in the same sequence and silently
#: inherit each other's head.
ORDER_SALT = ":icmc-v2r3"


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
            "material of another study to buy a disjointness argument here. "
            "`root_identity` reads 324 Wikipedia identities from prior modules, "
            "which is why the family is excluded rather than merely unused."
        ),
    }
)


# ---------------------------------------------------------------------------
# sampling constants -- literals, every one of them
#
# The basis is grammar breadth and PROBED SOURCE SUPPLY, and explicitly not pass
# yield, violation rate, or any observed outcome. V2R2's realised admission
# yield of 270 from 460 constructed candidates is NOT a basis: reading how much
# of V2R2 survived filtering and sizing V2R3 to match would be selection
# responding to a spent study's outcome, which is the same error one level up
# from reading a lineage's result.

#: Admitted-pair floor. The pre-measurement cohort sufficiency gate, carried
#: forward from the founder ruling unchanged and explicitly NOT lowered. It is
#: not a numerator, not a denominator, and appears nowhere in the scorer.
FLOOR = 200
FAMILIES_REQUIRED = 3

#: Candidate pairs to CONSTRUCT, before integrity and disjointness filtering.
#: Over-selection happens BEFORE any outcome exists; padding after measuring is
#: forbidden without exception.
PRIMARY_TARGET = 480

#: Per-family construction ceilings. Each is inside the PROBED capacity of its
#: family's declared containers -- 40 repositories at 5 documents each, 44 CFR
#: parts at 4 sections each, and issuers above CIK 21344 at 4 pairs each -- so a
#: quota cannot silently demand material the declared roots cannot supply.
#: A family that under-delivers anyway is REPORTED SHORT. Redistribution into a
#: family that yields more is FORBIDDEN: topping up from the productive family
#: is selection responding to supply, and supply is not independent of the
#: sources' revision behaviour.
FAMILY_QUOTA: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 170,
        "regulation_ecfr": 150,
        "sec_edgar": 160,
    }
)

#: The same composition as a share, DERIVED from the quota rather than declared
#: beside it. V2R2 declared both by hand and they disagreed -- its shares summed
#: to 0.99 against a quota that summed to its target -- which is what a
#: hand-maintained duplicate truth does. There is one authoritative declaration
#: here, FAMILY_QUOTA, and this is a rendering of it.
#:
#: Exact rationals rather than rounded floats, because a rounded share cannot sum
#: to one and a test that allowed it to be close would be a test with a tolerance
#: in a file that has no tolerances.
FAMILY_SHARE: Mapping[str, str] = MappingProxyType(
    {
        family: str(Fraction(quota, PRIMARY_TARGET))
        for family, quota in FAMILY_QUOTA.items()
    }
)


def family_share_fractions() -> dict[str, Fraction]:
    """`FAMILY_SHARE` as arithmetic, for anything that needs to add it up."""
    return {family: Fraction(text) for family, text in FAMILY_SHARE.items()}

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
            "grammar breadth and PROBED container capacity: 40 repositories x 5, "
            "44 CFR parts x 4, and issuers above CIK 21344 x 4"
        ),
        "explicitly_not_basis": (
            "violation rate, pass yield, closure outcome, or any V1 / V2R1 / V2R2 "
            "observation -- including V2R2's realised admission of 270 from 460 "
            "constructed candidates, and including the 13 units that produced its "
            "raw violations"
        ),
        "frozen_before": "any V2R3 fetch, any V2R3 diff, any V2R3 score",
        "redistribution": "forbidden; an under-delivering family is reported short",
        "floor_prior": (
            "FLOOR=200 is carried forward from the founder ruling as a "
            "PRE-MEASUREMENT COHORT SUFFICIENCY GATE and is NOT lowered. V1's "
            "published 8/514 sized it as a sample-size planning prior and appears "
            "nowhere else: not in a quota, not in a numerator, not in a "
            "denominator, not in the scorer."
        ),
        "no_selection_for_the_v2r2_shape": (
            "the cohort is NOT selected for quarantine outcomes, ambiguity "
            "outcomes, or any other shape. Selecting for the state that broke V2R2 "
            "would make the next result a statement about the selection rather "
            "than about production, and the frame forbids probing for it."
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
            "`selective_build.snapshots` reads, mirrored field-for-field from "
            "`canonical_document` and never reinvented per family. V2R1's first "
            "eCFR canonicalisation invented `heading_path` with no `heading` and no "
            "`text_sha256`, which made 106 pairs unmeasurable for a reason "
            "unrelated to the migration (INC-V2-058.2)."
        ),
    }
)


# ---------------------------------------------------------------------------
# cache identity -- INC-V2-046 is not repeated

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
        "historical_artifacts": "UNTOUCHED. Not rewritten, not re-keyed, not migrated.",
    }
)


# ---------------------------------------------------------------------------
# disjointness -- what V2R3 may not draw from, and why each entry is there
#
# The founder declined a universal doctrine that any read burns a lineage for
# every future question. Burn scope belongs to each corpus's OWN predeclared
# contract. So this is not "every study that exists"; it is the studies whose
# own contracts, or whose role in this programme, put their lineages out of
# reach for a CONFIRMATORY identity closure.

EXCLUDED_SETS: tuple[Mapping[str, str], ...] = (
    MappingProxyType(
        {
            "id": "v2r2_spent_270",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2's frozen universe. The run "
                "executed exactly once and its corpus is SPENT. That it was "
                "adjudicated an invalid instrument does not un-spend the material: "
                "the lineages were measured, their outcomes were read, and a cohort "
                "whose results are known cannot be a prospective confirmatory "
                "denominator. All 270 are excluded by name. The three that produced "
                "its thirteen violations -- ecfr:47:20:20.19, ecfr:7:3560:3560.105 "
                "and ecfr:7:3560:3560.102 -- are DEVELOPMENT / FORENSIC regression "
                "cases only and may never certify V2R3."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "v2r1_spent_285",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1's frozen universe. Spent for "
                "the same reason, one study earlier. Its three violating shapes are "
                "likewise development regressions only."
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
# root disjointness -- ONE reader, and it BLOCKS

ROOT_DISJOINTNESS: Mapping[str, Any] = MappingProxyType(
    {
        "reader": "tools/root_identity.py",
        "prior_modules_read": 12,
        "prior_identities": 875,
        "prior_by_family": {"ecfr": 265, "git": 268, "sec": 18, "wikipedia": 324},
        "unverifiable_at_declaration": 0,
        "screening": (
            "every candidate below was canonicalised and checked against the prior "
            "set BEFORE it was probed, so a spent container was never even asked "
            "about"
        ),
        "unverifiable_policy": (
            "a root whose shape the reader cannot interpret returns UNVERIFIABLE and "
            "BLOCKS. It is NEVER assumed disjoint -- that assumption is exactly how "
            "7 CFR 273, SFI1-spent and a VBC1 declared root, entered the V2R2 frame."
        ),
        "enumerator_obligation": (
            "reporting an overlap is not enough. The enumerator REMOVES or "
            "named-excludes every overlapping row before universe admission and then "
            "RE-PROVES disjointness over the survivors. A report that leaves the row "
            "in the universe is a note, not a control."
        ),
        "container_level_is_stronger_than_lineage_level": (
            "not one repository, CFR part or CIK below appears among the prior "
            "identities. A container that was never touched cannot hold a lineage "
            "that was. Lineage-level exclusion still runs on top of it -- a stronger "
            "proof does not license skipping the weaker check."
        ),
    }
)


# ---------------------------------------------------------------------------
# what selection may never do

FORBIDDEN_IN_SELECTION: tuple[str, ...] = (
    "inspecting revision content in order to choose a candidate",
    "inspecting any identity outcome",
    "probing for ambiguity",
    "probing for quarantine membership",
    "probing for changed facets",
    "acquiring until a quarantine case appears",
    "removing a pair after seeing its outcome",
    "adding a pair after seeing any outcome",
    "replacing a family after seeing its yield",
    "adjusting a quota, the floor or a threshold after acquisition",
    "adding an ignore entry",
    "sizing a quota from V2R1's or V2R2's realised admission yield",
    "selecting for the resolver/quarantine state that broke V2R2",
)


# ---------------------------------------------------------------------------
# SOURCE ROOTS -- the WHICH, predeclared
#
# 40 documentation repositories, none of them among the 268 git identities any
# earlier sources module declares, and none of them an SFI3 root repository. The
# fifth field is the repository's SPDX licence id as GitHub reports it, recorded
# as PROVENANCE METADATA. It is not a clearance: an OSS licence is copyright
# permission from that contributor and settles nothing about a third party's
# patents, and a repository marked NOASSERTION grants no commercial reuse right
# at all. Nothing here is copied into a product; revisions are fetched, hashed,
# canonicalised and diffed to measure this system's own identity behaviour.
#
# Probed document counts live in PROBED_DOCUMENTS below.

GIT_ROOTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("metallb", "metallb", "website/content", "main", "Apache-2.0"),
    ("karmada-io", "website", "docs", "main", "CC-BY-4.0"),
    ("kubeedge", "website", "docs", "master", "Apache-2.0"),
    ("volcano-sh", "website", "docs", "master", "Apache-2.0"),
    ("goharbor", "website", "docs", "main", "Apache-2.0"),
    ("vmware-tanzu", "velero", "site/content/docs", "main", "Apache-2.0"),
    ("spinnaker", "spinnaker.io", "content/en/docs", "master", "NOASSERTION"),
    ("gravitational", "teleport", "docs/pages", "master", "AGPL-3.0"),
    ("goauthentik", "authentik", "website/docs", "main", "NOASSERTION"),
    ("camunda", "camunda-docs", "docs", "main", "NOASSERTION"),
    ("windmill-labs", "windmill", "docs", "main", "NOASSERTION"),
    ("refinedev", "refine", "documentation/docs", "main", "MIT"),
    ("payloadcms", "payload", "docs", "main", "MIT"),
    ("checkmk", "checkmk", "doc", "master", "GPL-2.0"),
    ("zeek", "zeek-docs", "scripts", "master", "NOASSERTION"),
    ("scylladb", "scylladb", "docs", "master", "NOASSERTION"),
    ("janusgraph", "janusgraph", "docs", "master", "NOASSERTION"),
    ("memgraph", "documentation", "pages", "main", "MIT"),
    ("chroma-core", "docs", "docs", "main", "NOASSERTION"),
    ("vllm-project", "vllm", "docs", "main", "Apache-2.0"),
    ("keras-team", "keras-io", "templates", "master", "Apache-2.0"),
    ("iterative", "dvc.org", "content/docs", "main", "Apache-2.0"),
    ("kedro-org", "kedro", "docs", "main", "NOASSERTION"),
    ("feast-dev", "feast", "docs", "master", "Apache-2.0"),
    ("airbytehq", "airbyte", "docs", "master", "NOASSERTION"),
    ("meltano", "meltano", "docs/docs", "main", "MIT"),
    ("osquery", "osquery", "docs", "master", "NOASSERTION"),
    ("Icinga", "icinga2", "doc", "master", "GPL-3.0"),
    ("librenms", "librenms", "doc", "master", "NOASSERTION"),
    ("opnsense", "docs", "source", "master", "NOASSERTION"),
    ("kubevirt", "user-guide", "docs", "main", "Apache-2.0"),
    ("external-secrets", "external-secrets", "docs", "main", "Apache-2.0"),
    ("cert-manager", "website", "content/docs", "master", "Apache-2.0"),
    ("kubernetes-sigs", "cluster-api", "docs", "main", "Apache-2.0"),
    ("tikv", "website", "content/docs", "master", "NOASSERTION"),
    ("pingcap", "docs", "develop", "master", "NOASSERTION"),
    ("MaterializeInc", "materialize", "doc/user/content", "main", "NOASSERTION"),
    ("VictoriaMetrics", "VictoriaMetrics", "docs", "master", "Apache-2.0"),
    ("semgrep", "semgrep-docs", "docs", "main", "LGPL-2.1"),
    ("aquasecurity", "trivy", "docs", "main", "Apache-2.0"),
)

#: Documents found under each declared prefix by the availability probe, using
#: acquisition's OWN predicate -- blob, documentation suffix, larger than 2000
#: bytes. Kept BESIDE the root tuple rather than inside it so the tuple shape
#: stays the one every earlier frame used: a study-specific sixth field would
#: force a second implementation of the fetcher, and a second implementation of
#: machinery that must behave identically is free to drift.
#:
#: Recorded so that "supply was checked" is a number a later reader can
#: re-derive rather than a claim. Every candidate probed below 17 was dropped
#: before declaration, by that rule and no other.
PROBED_DOCUMENTS: Mapping[str, int] = MappingProxyType(
    {
        "metallb/metallb": 24,
        "karmada-io/website": 228,
        "kubeedge/website": 48,
        "volcano-sh/website": 65,
        "goharbor/website": 66,
        "vmware-tanzu/velero": 1181,
        "spinnaker/spinnaker.io": 218,
        "gravitational/teleport": 747,
        "goauthentik/authentik": 273,
        "camunda/camunda-docs": 1269,
        "windmill-labs/windmill": 22,
        "refinedev/refine": 315,
        "payloadcms/payload": 147,
        "checkmk/checkmk": 33,
        "zeek/zeek-docs": 333,
        "scylladb/scylladb": 280,
        "janusgraph/janusgraph": 58,
        "memgraph/documentation": 333,
        "chroma-core/docs": 28,
        "vllm-project/vllm": 178,
        "keras-team/keras-io": 17,
        "iterative/dvc.org": 142,
        "kedro-org/kedro": 95,
        "feast-dev/feast": 191,
        "airbytehq/airbyte": 1392,
        "meltano/meltano": 108,
        "osquery/osquery": 31,
        "Icinga/icinga2": 25,
        "librenms/librenms": 136,
        "opnsense/docs": 294,
        "kubevirt/user-guide": 87,
        "external-secrets/external-secrets": 93,
        "cert-manager/website": 145,
        "kubernetes-sigs/cluster-api": 152,
        "tikv/website": 302,
        "pingcap/docs": 82,
        "MaterializeInc/materialize": 346,
        "VictoriaMetrics/VictoriaMetrics": 126,
        "semgrep/semgrep-docs": 358,
        "aquasecurity/trivy": 109,
    }
)

#: 44 CFR parts, none among the 265 eCFR identities already declared. Selected
#: by a stated mechanical rule over a per-title metadata scan: within each
#: scanned title, the parts with at least twelve sections carrying two or more
#: distinct dated versions, top two per title by that count. The rule reads
#: SUPPLY and nothing else -- it never asks what changed in a section, and it
#: was fixed before the scan ran. Part names are the eCFR's own labels at
#: 2026-08-01, copied rather than composed.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("7", "1", "Administrative Regulations"),
    ("9", "145", "National Poultry Improvement Plan for Breeding Poultry"),
    ("9", "2", "Regulations"),
    ("10", "1016", "Safeguarding of Restricted Data by Access Permittees"),
    ("10", "1003", "Office of Hearings and Appeals Procedural Regulations"),
    ("14", "1206", "Procedures for Disclosure of Records Under the FOIA"),
    ("14", "1204", "Administrative Authority and Policy"),
    ("15", "27", "Protection of Human Subjects"),
    ("16", "1", "General Procedures"),
    ("16", "1028", "Protection of Human Subjects"),
    ("17", "12", "Rules Relating to Reparations"),
    ("17", "140", "Organization, Functions, and Procedures of the Commission"),
    ("21", "1", "General Enforcement Regulations"),
    ("21", "10", "Administrative Practices and Procedures"),
    ("22", "123", "Licenses for the Export and Temporary Import of Defense Articles"),
    ("24", "1006", "Native Hawaiian Housing Block Grant Program"),
    ("29", "102", "Rules and Regulations, Series 8"),
    ("29", "1404", "Arbitration Services"),
    ("30", "1206", "Product Valuation"),
    ("30", "1210", "Forms and Reports"),
    ("31", "1", "Disclosure of Records"),
    ("32", "161", "Identification (ID) Cards for Members of the Uniformed Services"),
    ("33", "100", "Safety of Life on Navigable Waters"),
    ("33", "110", "Anchorage Regulations"),
    ("34", "200", "Title I - Improving the Academic Achievement of the Disadvantaged"),
    ("36", "1194", "Information and Communication Technology Standards and Guidelines"),
    ("37", "11", "Representation of Others Before the USPTO"),
    ("38", "1", "General Provisions"),
    ("38", "16", "Protection of Human Subjects"),
    ("40", "1036", "Control of Emissions from New and In-Use Heavy-Duty Highway Engines"),
    ("40", "1037", "Control of Emissions from New Heavy-Duty Motor Vehicles"),
    ("42", "1001", "Program Integrity - Medicare and State Health Care Programs"),
    ("42", "1003", "Civil Money Penalties, Assessments and Exclusions"),
    ("45", "101", "Health Resources Priorities and Allocations System (HRPAS)"),
    ("45", "1177", "Claims Collection"),
    ("46", "11", "Requirements for Officer Endorsements"),
    ("46", "10", "Merchant Mariner Credential"),
    ("47", "1", "Practice and Procedure"),
    ("47", "0", "Commission Organization"),
    ("48", "12", "Acquisition of Commercial Products and Commercial Services"),
    ("48", "1201", "Federal Acquisition Regulations System"),
    ("49", "11", "Protection of Human Subjects"),
    ("49", "107", "Hazardous Materials Program Procedures"),
    ("50", "12", "Seizure and Forfeiture Procedures"),
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
        "start_after_cik": 21344,
        "why_start_after": (
            "21344 is the highest CIK V2R2 admitted, and V2R2's own start was above "
            "the highest V2R1 admitted. Starting strictly above it makes the SEC "
            "family container-disjoint from BOTH predecessors by construction, "
            "matching the treatment of the other two families, rather than relying "
            "on lineage-level exclusion alone."
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
            "26 of the first 30 issuers above CIK 21344 carry at least one amendment "
            "pair, 152 pairs among those 30, so the quota is reachable well inside "
            "the ordered universe"
        ),
        "stopping": "walk in CIK order until the family quota is met or the universe ends",
    }
)

#: Per-family container caps. Different per family because the containers are
#: different kinds of thing -- a repository holds hundreds of documents, a CFR
#: part holds tens of sections, an issuer holds a handful of amendment pairs --
#: and a single number would either starve one family or let another dominate.
CONTAINER_CAP: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 5,
        "regulation_ecfr": 4,
        "sec_edgar": 4,
    }
)

#: How each family's roots were probed, and what the probe was allowed to ask.
#: Recorded in the frame so the claim "availability was checked" is auditable
#: rather than asserted.
AVAILABILITY_PROBE: Mapping[str, Any] = MappingProxyType(
    {
        "git_docs": (
            "repository metadata plus the recursive tree at the declared branch; "
            "documents counted with acquisition's own predicate. 44 candidates "
            "probed, 10 unreachable at the declared prefix, 4 dropped for holding "
            "fewer than 17 documents, 40 declared."
        ),
        "regulation_ecfr": (
            "one versions call per CFR title, from which the number of sections "
            "carrying two or more distinct dated versions is computable per PART "
            "without asking about any part individually -- which keeps the probe "
            "cheap and, more importantly, blind"
        ),
        "sec_edgar": (
            "the published issuer universe plus the submissions API for the first 30 "
            "issuers above the start CIK; form types and period dates only"
        ),
        "never_asked": (
            "what changed in a revision, whether a unit was renamed, whether the "
            "resolver would call anything ambiguous, whether a quarantine would form"
        ),
        "probe_tools": (
            "tools/probe_v2r3_roots.py and tools/scan_v2r3_ecfr_supply.py, both "
            "metadata-only and both screening candidates through root_identity "
            "before asking anything"
        ),
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
                    "probed_documents": PROBED_DOCUMENTS[f"{owner}/{repo}"],
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
        "root_disjointness": dict(ROOT_DISJOINTNESS),
        "forbidden_in_selection": list(FORBIDDEN_IN_SELECTION),
        "container_cap": dict(CONTAINER_CAP),
        "availability_probe": dict(AVAILABILITY_PROBE),
        "source_roots": source_roots(),
    }


def frame_digest() -> str:
    """Canonical digest of the declaration, independent of this file's comments."""
    body = json.dumps(frame_declaration(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
