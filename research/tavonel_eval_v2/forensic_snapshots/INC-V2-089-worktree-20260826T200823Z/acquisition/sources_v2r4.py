"""The acquisition frame for IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4.

Rung 0. Sealed BEFORE a single revision is fetched. V2R4 acquires its own
material, so the frame that decides WHAT to acquire has to be pinned before any
content exists -- otherwise selection could be steered, consciously or not, by
what the fetches started returning.

WHAT V2R4 IS. V2R3R1 inherited V2R3's 300 unscored pairs and executed. Its
instrument graded ONE invariant against a pass rule that named EIGHT
(INC-V2-067), so the run establishes nothing about the other seven and the 300
lineages are SPENT: their INVARIANT_6 outcome was read, and a cohort whose
results are known cannot be a prospective confirmatory denominator. V2R4 is a
new instrument over new material. It is not a rescore, not a repair of that run,
and not a repair of production.

    V2R1   read a raw snapshot id as a resolved identity
    V2R2   read a resolver-local decision as a final disposition
    V2R3R1 graded one invariant and reported against a rule naming eight

WHAT IS UNCHANGED, and deliberately. The eight invariants, the zero-tolerance
INVARIANT_6, the >=200 admitted pairs, the >=3 families, the prohibition on
padding after measurement, and the rule that selection may never read an
outcome. The floor is NOT lowered. `tools/v2r4_semantics_delta.py` proves
mechanically that the scientific core crossed from V2R3R1 byte-identical.

WHAT IS NEW. Every graded invariant is now EXECUTED -- the acceptance domain is
obtained by running the grading function, never by reading a declaration -- and
selection is screened against a SECOND, WIDER set than any predecessor used.

TWO SCREENS, AND EVERY ROOT BELOW CLEARED BOTH.

  1. `tools/root_identity.py` canonicalises every root any earlier sources module
     has ever declared -- 960 identities across four families, in seventeen
     attribute shapes -- and every candidate was screened against it BEFORE
     being probed. A root whose shape cannot be interpreted is UNVERIFIABLE and
     BLOCKS; it is never assumed disjoint. That assumption is how 7 CFR 273 --
     SFI1-spent and a VBC1 declared root -- entered the V2R2 frame.

  2. `SFI3_ROOT_RESERVATION_V1`, which is STRICTLY WIDER than screen 1 here. It
     covers SFI3's declared roots AND its predeclared legal replacement pool,
     and the pool is by construction not declared anywhere yet, so screen 1
     cannot see it. A container that is only a replacement candidate is still
     reserved: SFI3 may land there after an availability failure, and a V2R4
     root sitting in the pool would silently narrow SFI3's escape route.

WHY A RESERVATION AND NOT A COHORT COMPARISON. An earlier draft of the V2R4
protocol required INVARIANT_8 to prove disjointness `from_sfi3_material`. SFI3's
cohort does not exist and must not until V2R4 passes, because SFI3's freeze gate
is downstream of MIGRATION_CLOSURE_ACCEPTANCE_V1. That made a circular gate with
only two exits, both forbidden: open SFI3 material early, or let the invariant
pass vacuously over a population that is empty because it cannot yet be
non-empty (INC-V2-036). Separation moved to where it is decidable NOW -- container
identity, at rung 0 -- and INVARIANT_8 no longer names SFI3 at all.

EVERY ROOT BELOW WAS AVAILABILITY-PROBED BEFORE BEING DECLARED, with metadata
questions only: does this repository exist, how many documents does this prefix
hold, how many sections of this CFR part carry two or more distinct dated
versions, do issuers above this CIK carry amendment pairs. No revision content
was read, nothing was diffed, no qualifying change was counted, and no identity
outcome was touched. `tools/probe_v2r4_roots.py` is the probe and it names the
eight questions it refuses to be asked.
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

PROTOCOL_ID = "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R4"

#: Salt for the frozen traversal order. Distinct from every predecessor's --
#: V2R1's was ":icmc-v2r1", V2R2's ":icmc-v2r2", V2R3's ":icmc-v2r3" -- so two
#: studies over overlapping source sets cannot walk them in the same sequence
#: and silently inherit each other's head.
ORDER_SALT = ":icmc-v2r4"


# ---------------------------------------------------------------------------
# families
#
# The same three, and the same omission -- now for a reason that is written
# down in an executable contract rather than only in prose. Wikipedia is an SFI3
# ROOT family whose reservation membership is decided by CATEGORY, and category
# membership is not visible from a root list. `sfi3_root_reservation` declares
# the family UNDECIDABLE and REFUSES rather than reporting it clean, because
# "we could not tell" and "they do not overlap" are different answers and only
# one of them is a proof. Making it decidable would mean expanding an SFI3
# category -- spending the next study's prospective confirmatory material to buy
# a disjointness argument here. Declared and excluded, never quietly dropped.

FAMILIES: tuple[str, ...] = ("git_docs", "regulation_ecfr", "sec_edgar")

EXCLUDED_FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "encyclopedia_wikipedia": (
            "SFI3 root family. Reservation membership is by category, which is not "
            "decidable from identity metadata, so SFI3_ROOT_RESERVATION_V1 declares "
            "the family UNDECIDABLE and fails closed. `root_identity` reads 324 "
            "Wikipedia identities from prior modules and the reservation holds 15 "
            "more, which is why the family is excluded rather than merely unused. "
            "Opening an SFI3 category to prove disjointness here is FORBIDDEN."
        ),
    }
)


# ---------------------------------------------------------------------------
# sampling constants -- literals, every one of them
#
# The basis is grammar breadth and PROBED SOURCE SUPPLY, and explicitly not pass
# yield, violation rate, or any observed outcome. No predecessor's REALISED
# ADMISSION is a basis either: reading how much of V2R3R1 survived filtering and
# sizing V2R4 to match would be selection responding to a spent study's outcome.

#: Admitted-pair floor. The pre-measurement cohort sufficiency gate, carried
#: forward from the founder ruling unchanged and explicitly NOT lowered. It is
#: not a numerator, not a denominator, and appears nowhere in the scorer.
FLOOR = 200
FAMILIES_REQUIRED = 3

#: Candidate pairs to CONSTRUCT, before integrity and disjointness filtering.
#: Over-selection happens BEFORE any outcome exists; padding after measuring is
#: forbidden without exception.
PRIMARY_TARGET = 480

#: Per-family construction ceilings. Each is inside the PROBED capacity of this
#: study's OWN declared containers -- 44 repositories at 5 documents each is
#: 220, 88 CFR parts at 4 sections each is 352, and 7856 issuers above
#: CIK 33213 at 4 pairs each -- so a quota cannot silently demand material the
#: declared roots cannot supply.
#:
#: These are the same three numbers V2R3 declared, and that is a statement about
#: SUPPLY, not about V2R3's result. V2R4's capacity was probed independently and
#: independently clears them; no predecessor's realised yield, violation count or
#: verdict was read to arrive at them.
#:
#: A family that under-delivers anyway is REPORTED SHORT. Redistribution into a
#: family that yields more is FORBIDDEN: topping up from the productive family is
#: selection responding to supply, and supply is not independent of the sources'
#: revision behaviour.
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
            "grammar breadth and PROBED container capacity: 44 repositories x 5, "
            "88 CFR parts x 4, and issuers above CIK 33213 x 4"
        ),
        "explicitly_not_basis": (
            "violation rate, pass yield, closure outcome, or any V1 / V2R1 / V2R2 / "
            "V2R3 / V2R3R1 observation -- including V2R3R1's realised admission and "
            "including its INVARIANT_6 result, which was read and is therefore the "
            "single outcome this programme now knows about that material"
        ),
        "frozen_before": "any V2R4 fetch, any V2R4 diff, any V2R4 score",
        "redistribution": "forbidden; an under-delivering family is reported short",
        "floor_prior": (
            "FLOOR=200 is carried forward from the founder ruling as a "
            "PRE-MEASUREMENT COHORT SUFFICIENCY GATE and is NOT lowered. V1's "
            "published 8/514 sized it as a sample-size planning prior and appears "
            "nowhere else: not in a quota, not in a numerator, not in a "
            "denominator, not in the scorer."
        ),
        "no_selection_for_a_known_shape": (
            "the cohort is NOT selected for quarantine outcomes, ambiguity "
            "outcomes, or any other shape. V2R3R1's INVARIANT_6 outcome is the one "
            "result this programme knows about identity behaviour at scale, and "
            "selecting for or against the shape it revealed would make the next "
            "result a statement about the selection rather than about production."
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
# disjointness -- what V2R4 may not draw from, and why each entry is there
#
# Burn scope belongs to each corpus's OWN predeclared contract, so this is not
# "every study that exists"; it is the studies whose own contracts, or whose role
# in this programme, put their lineages out of reach for a CONFIRMATORY identity
# closure. Everything V2R3 excluded stays excluded -- this study is not narrower
# than its predecessor anywhere -- and two entries are added.

EXCLUDED_SETS: tuple[Mapping[str, str], ...] = (
    MappingProxyType(
        {
            "id": "v2r3_and_v2r3r1_spent_300",
            "why": (
                "the 300 pairs V2R3 acquired and froze UNSCORED, which V2R3R1 "
                "inherited by exact carry-forward and then MEASURED. Their "
                "INVARIANT_6 outcome was read and reported, so the material is "
                "SPENT -- a cohort whose results are known cannot be a prospective "
                "confirmatory denominator. That the run was adjudicated "
                "INCOMPLETE_INSTRUMENT_COVERAGE under INC-V2-067 does not un-spend "
                "it: the instrument graded one invariant of eight, and the one it "
                "graded is the one whose answer is now known. Both universes name "
                "the same 300 lineages and both are excluded."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "v2r2_spent_270",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R2's frozen universe. The run "
                "executed exactly once and its corpus is SPENT. That it was "
                "adjudicated an invalid instrument does not un-spend the material. "
                "Its three violating shapes -- ecfr:47:20:20.19, "
                "ecfr:7:3560:3560.105 and ecfr:7:3560:3560.102 -- are DEVELOPMENT / "
                "FORENSIC regression cases only and may never certify V2R4."
            ),
        }
    ),
    MappingProxyType(
        {
            "id": "v2r1_spent_285",
            "why": (
                "IDENTITY_CHANGE_MIGRATION_CLOSURE_V2R1's frozen universe. Spent for "
                "the same reason, two studies earlier. Its three violating shapes are "
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
                "of it here would spend it. Enforced at CONTAINER level by "
                "SFI3_ROOT_RESERVATION_V1 at rung 0, which is decidable now, rather "
                "than by comparing against an SFI3 cohort that does not exist yet."
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
# root disjointness -- TWO readers, and both BLOCK

ROOT_DISJOINTNESS: Mapping[str, Any] = MappingProxyType(
    {
        "reader": "tools/root_identity.py",
        "prior_modules_read": 14,
        "prior_identities": 960,
        "prior_by_family": {"ecfr": 309, "git": 308, "sec": 19, "wikipedia": 324},
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
        "screened_at_repository_level_not_prefix_level": (
            "the git identity tuple carries a prefix, so the same repository under a "
            "different subtree reads as a different identity. Screening was done on "
            "owner/repo, which is STRICTER: a repository that was ever touched is "
            "not fresh for this study regardless of which subtree was read."
        ),
    }
)


# ---------------------------------------------------------------------------
# the SFI3 reservation -- the second screen, bound by path and digest

SFI3_RESERVATION: Mapping[str, Any] = MappingProxyType(
    {
        "reservation_id": "SFI3_ROOT_RESERVATION_V1",
        "module": "tools/sfi3_root_reservation.py",
        "what_it_reserves": (
            "SFI3's declared roots UNION its predeclared legal replacement pool, per "
            "family, on container identity. The union is the reservation: a container "
            "SFI3 may use, whether it uses it first or only after an availability "
            "failure."
        ),
        "built_from_identity_metadata_only": (
            "source and root IDENTITY METADATA. No revision contents, no qualifying "
            "pair counts, no change outcomes, no source fact transitions, no payload "
            "opening. It pins the SFI3 protocol id, the sha256 of "
            "acquisition/sources_sfi3.py, and the exact git / eCFR / SEC / Wikipedia "
            "root identities."
        ),
        "bound_by": "path and sha256, by BOTH studies, at rung 0",
        "no_post_v2r4_widening": (
            "the replacement pool is PREDECLARED. A root promoted out of it later "
            "cannot widen the reservation, because the pool was inside it from the "
            "start."
        ),
        "reverse_direction": (
            "SFI3's own freeze gate (condition 21) proves the reverse before SFI3 "
            "acquires: its roots lie inside the reservation and outside V2R4's frozen "
            "containers. It resolves the reservation through V2R4's frame attestation "
            "binding, never a stem glob (INC-V2-069), and V2R4's OUTCOMES are never an "
            "input to it."
        ),
        "wikipedia_fails_closed": (
            "reservation membership for encyclopedia_wikipedia is by category and is "
            "NOT decidable from identity metadata. The reservation REFUSES rather "
            "than reporting the family clean, and V2R4 excludes the family."
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
    "sizing a quota from any predecessor's realised admission yield",
    "selecting for or against the shape V2R3R1's INVARIANT_6 result revealed",
    "declaring a container whose enumeration the probe could not complete",
)


# ---------------------------------------------------------------------------
# SOURCE ROOTS -- the WHICH, predeclared
#
# 44 documentation repositories. None appears among the 308 git identities any
# earlier sources module declares, none is an SFI3 declared root, and none is in
# SFI3's predeclared replacement pool. The fifth field is the repository's SPDX
# licence id as GitHub reports it, recorded as PROVENANCE METADATA. It is not a
# clearance: an OSS licence is copyright permission from that contributor and
# settles nothing about a third party's patents, and a repository marked
# NOASSERTION grants no commercial reuse right at all. Nothing here is copied
# into a product; revisions are fetched, hashed, canonicalised and diffed to
# measure this system's own identity behaviour.
#
# Probed document counts live in PROBED_DOCUMENTS below.

GIT_ROOTS: tuple[tuple[str, str, str, str, str], ...] = (
    ("ant-design", "ant-design", "docs", "master", "MIT"),
    ("apache", "tvm", "docs", "main", "Apache-2.0"),
    ("babel", "website", "docs", "main", "MIT"),
    ("chakra-ui", "chakra-ui", "apps/www/content", "main", "MIT"),
    ("cockroachdb", "cockroach", "docs", "master", "NOASSERTION"),
    ("containers", "buildah", "docs", "main", "Apache-2.0"),
    ("crystal-lang", "crystal-book", "docs", "master", "NOASSERTION"),
    ("dask", "dask", "docs", "main", "BSD-3-Clause"),
    ("firecracker-microvm", "firecracker", "docs", "main", "Apache-2.0"),
    ("gradio-app", "gradio", "guides", "main", "Apache-2.0"),
    ("grafana", "pyroscope", "docs", "main", "AGPL-3.0"),
    ("huggingface", "accelerate", "docs", "main", "Apache-2.0"),
    ("huggingface", "datasets", "docs", "main", "Apache-2.0"),
    ("huggingface", "diffusers", "docs", "main", "Apache-2.0"),
    ("jestjs", "jest", "docs", "main", "MIT"),
    ("JuliaLang", "julia", "doc", "master", "MIT"),
    ("k0sproject", "k0s", "docs", "main", "NOASSERTION"),
    ("kata-containers", "kata-containers", "docs", "main", "Apache-2.0"),
    ("kubernetes-sigs", "kustomize", "site/content", "master", "Apache-2.0"),
    ("kubernetes", "ingress-nginx", "docs", "main", "Apache-2.0"),
    ("Lightning-AI", "pytorch-lightning", "docs", "master", "Apache-2.0"),
    ("mui", "material-ui", "docs/data", "master", "MIT"),
    ("networkx", "networkx", "doc", "main", "NOASSERTION"),
    ("oauth2-proxy", "oauth2-proxy", "docs", "master", "MIT"),
    ("ocaml", "ocaml.org", "data", "main", "NOASSERTION"),
    ("onnx", "onnx", "docs", "main", "Apache-2.0"),
    ("open-policy-agent", "gatekeeper", "website/docs", "master", "Apache-2.0"),
    ("open-telemetry", "opentelemetry-specification", "specification", "main", "Apache-2.0"),
    ("openbao", "openbao", "website/content", "main", "MPL-2.0"),
    ("OWASP", "CheatSheetSeries", "cheatsheets", "master", "CC-BY-SA-4.0"),
    ("projectcontour", "contour", "site/content/docs", "main", "Apache-2.0"),
    ("pydata", "xarray", "doc", "main", "Apache-2.0"),
    ("ruby", "ruby", "doc", "master", "NOASSERTION"),
    ("run-llama", "llama_index", "docs", "main", "MIT"),
    ("rust-lang", "edition-guide", "src", "master", "Apache-2.0"),
    ("scipy", "scipy", "doc", "main", "BSD-3-Clause"),
    ("siderolabs", "talos", "website/content", "main", "MPL-2.0"),
    ("statsmodels", "statsmodels", "docs", "main", "BSD-3-Clause"),
    ("storybookjs", "storybook", "docs", "next", "MIT"),
    ("sympy", "sympy", "doc", "master", "NOASSERTION"),
    ("tarantool", "doc", "doc", "latest", "NOASSERTION"),
    ("vitest-dev", "vitest", "docs", "main", "MIT"),
    ("vuejs", "router", "packages/docs", "main", "MIT"),
    ("withastro", "docs", "src/content/docs", "main", "MIT"),
)

#: Candidates that cleared both screens, were probed, and were NOT declared.
#: Recorded because a dropped candidate is a decision, and a frame that showed
#: only its survivors would let a reader think nothing was rejected.
PROBED_AND_NOT_DECLARED: Mapping[str, str] = MappingProxyType(
    {
        "ClickHouse/ClickHouse": (
            "GitHub returned the recursive tree TRUNCATED. The probe counted 18,962 "
            "documents under the declared prefix, but a truncated tree means the "
            "enumeration did not complete, so that number is a lower bound rather "
            "than a measurement -- and the traversal at acquisition time would not "
            "be reproducible from this frame. A container whose capacity was not "
            "measured is not declared. It is excluded by name rather than dropped "
            "silently, and it is not replaced: replacing it would be selection "
            "responding to supply."
        ),
        "21-520": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 1035 rows across 2 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
        "40-52": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 6858 rows across 7 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
        "40-721": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 3722 rows across 4 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
        "42-423": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 1205 rows across 2 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
        "43-4": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 1469 rows across 2 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
        "48-252": (
            "the acquisition fetcher queries this part at one URL and does not "
            "follow pagination; the part returns 1385 rows across 2 pages, "
            "so the fetcher would see only the first. Excluded by name rather than "
            "declared with a traversal the acquisition would not perform."
        ),
    }
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
        "ant-design/ant-design": 196,
        "apache/tvm": 75,
        "babel/website": 89,
        "chakra-ui/chakra-ui": 141,
        "cockroachdb/cockroach": 234,
        "containers/buildah": 35,
        "crystal-lang/crystal-book": 82,
        "dask/dask": 86,
        "firecracker-microvm/firecracker": 42,
        "gradio-app/gradio": 133,
        "grafana/pyroscope": 105,
        "huggingface/accelerate": 45,
        "huggingface/datasets": 57,
        "huggingface/diffusers": 353,
        "jestjs/jest": 30,
        "JuliaLang/julia": 108,
        "k0sproject/k0s": 60,
        "kata-containers/kata-containers": 91,
        "kubernetes-sigs/kustomize": 71,
        "kubernetes/ingress-nginx": 49,
        "Lightning-AI/pytorch-lightning": 136,
        "mui/material-ui": 136,
        "networkx/networkx": 63,
        "oauth2-proxy/oauth2-proxy": 233,
        "ocaml/ocaml.org": 1485,
        "onnx/onnx": 47,
        "open-policy-agent/gatekeeper": 32,
        "open-telemetry/opentelemetry-specification": 68,
        "openbao/openbao": 386,
        "OWASP/CheatSheetSeries": 116,
        "projectcontour/contour": 1191,
        "pydata/xarray": 44,
        "ruby/ruby": 36,
        "run-llama/llama_index": 131,
        "rust-lang/edition-guide": 33,
        "scipy/scipy": 179,
        "siderolabs/talos": 43,
        "statsmodels/statsmodels": 61,
        "storybookjs/storybook": 483,
        "sympy/sympy": 134,
        "tarantool/doc": 364,
        "vitest-dev/vitest": 131,
        "vuejs/router": 81,
        "withastro/docs": 1331,
    }
)

#: 88 CFR parts, none among the 309 eCFR identities already declared and none
#: inside SFI3's reservation. Selected by a stated mechanical rule over a
#: per-title metadata scan of ALL FIFTY TITLES: within each title, the parts that
#: still EXIST in the structure at 2026-08-01 and carry at least 12 sections with
#: two or more distinct dated versions, top two per title by that count. The
#: rule reads SUPPLY and nothing else -- it never asks
#: what changed in a section -- and it was fixed before the scan ran. Part names
#: are the eCFR's own labels at 2026-08-01, copied rather than composed.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    (
        "2",
        "180",
        "OMB Guidelines to Agencies on Government-Wide Debarment and Suspension "
        "(Nonprocurement)",
    ),
    ("2", "182", "Government-Wide Requirements for Drug-Free Workplace (Financial Assistance)"),
    (
        "4",
        "28",
        "Government Accountability Office Personnel Appeals Board; Procedures "
        "Applicable to Claims Concerning Employment Practices at the Government "
        "Accountability Office",
    ),
    ("4", "21", "Bid Protest Regulations"),
    (
        "5",
        "2634",
        "Executive Branch Financial Disclosure, Qualified Trusts, and "
        "Certificates of Divestiture",
    ),
    ("5", "894", "Federal Employees Dental and Vision Insurance Program"),
    ("6", "13", "Administrative Remedies for False Claims and Statements"),
    ("6", "27", "Chemical Facility Anti-Terrorism Standards"),
    ("7", "4290", "Rural Business Investment Company (“Rbic”) Program"),
    ("7", "5001", "Guaranteed Loans"),
    ("8", "1003", "Executive Office for Immigration Review"),
    ("8", "1208", "Procedures for Asylum and Withholding of Removal"),
    ("9", "590", "Inspection of Eggs and Egg Products (Egg Products Inspection Act)"),
    (
        "9",
        "93",
        "Importation of Certain Animals, Birds, Fish, and Poultry, and Certain "
        "Animal, Bird, and Poultry Products; Requirements for Means of Conveyance "
        "and Shipping Containers",
    ),
    ("10", "2", "Agency Rules of Practice and Procedure"),
    ("10", "431", "Energy Efficiency Program for Certain Commercial and Industrial Equipment"),
    ("11", "111", "Compliance Procedure (52 U.S.C. 30109, 30107(a))"),
    ("11", "100", "Scope and Definitions (52 U.S.C. 30101)"),
    ("12", "192", "Conversions from Mutual to Stock Form"),
    ("12", "19", "Rules of Practice and Procedure"),
    ("13", "107", "Small Business Investment Companies"),
    ("13", "124", "8(a) Business Development/Small Disadvantaged Business Status Determinations"),
    ("14", "13", "Investigative and Enforcement Procedures"),
    ("14", "21", "Certification Procedures for Products and Articles"),
    ("15", "904", "Civil Procedures"),
    ("15", "700", "Defense Priorities and Allocations System"),
    ("16", "23", "Guides for the Jewelry, Precious Metals, and Pewter Industries"),
    ("16", "0", "Organization"),
    ("17", "23", "Swap Dealers and Major Swap Participants"),
    ("17", "274", "Forms Prescribed Under the Investment Company Act of 1940"),
    ("18", "385", "Rules of Practice and Procedure"),
    ("18", "12", "Safety of Water Power Projects and Project Works"),
    ("19", "111", "Customs Brokers"),
    ("19", "210", "Adjudication and Enforcement"),
    (
        "20",
        "30",
        "Claims for Compensation Under the Energy Employees Occupational Illness "
        "Compensation Program Act of 2000, as Amended",
    ),
    ("20", "641", "Provisions Governing the Senior Community Service Employment Program"),
    ("21", "522", "Implantation or Injectable Dosage Form New Animal Drugs"),
    ("22", "96", "Intercountry Adoption Accreditation of Agencies and Approval of Persons"),
    ("22", "213", "Claims Collection"),
    ("23", "630", "Preconstruction Procedures"),
    ("23", "1300", "Uniform Procedures for State Highway Safety Grant Programs"),
    ("24", "206", "Home Equity Conversion Mortgage Insurance"),
    ("24", "983", "Project-Based Voucher (PBV) Program"),
    (
        "25",
        "224",
        "Tribal Energy Resource Agreements Under the Indian Tribal Energy "
        "Development and Self Determination Act",
    ),
    (
        "25",
        "1000",
        "Annual Funding Agreements Under the Tribal Self-Government Act "
        "Amendments to the Indian Self-Determination and Education Act",
    ),
    ("26", "49", "Facilities and Services Excise Taxes"),
    ("26", "300", "User Fees"),
    ("27", "26", "Liquors and Articles from Puerto Rico and the Virgin Islands"),
    ("27", "555", "Commerce in Explosives"),
    (
        "28",
        "32",
        "Public Safety Officers' Death, Disability, and Educational Assistance "
        "Benefit Claims",
    ),
    ("28", "0", "Organization of the Department of Justice"),
    ("29", "2200", "Rules of Procedure"),
    ("29", "2700", "Procedural Rules"),
    ("30", "585", "Renewable Energy on the Outer Continental Shelf"),
    ("30", "817", "Permanent Program Performance Standards—Underground Mining Activities"),
    ("31", "50", "Terrorism Risk Insurance Program"),
    ("31", "548", "Belarus Sanctions Regulations"),
    ("32", "37", "Technology Investment Agreements"),
    ("32", "1900", "Public Access to CIA Records Under the Freedom of Information Act (FOIA)"),
    (
        "33",
        "127",
        "Waterfront Facilities Handling Liquefied Natural Gas and Liquefied "
        "Hazardous Gas",
    ),
    ("33", "147", "Safety Zones"),
    ("34", "75", "Direct Grant Programs"),
    ("34", "76", "State-Administered Formula Grant Programs"),
    ("36", "1280", "Use of NARA Facilities"),
    ("36", "228", "Minerals"),
    ("37", "2", "Rules of Practice in Trademark Cases"),
    ("37", "201", "General Provisions"),
    ("38", "20", "Board of Veterans' Appeals: Rules of Practice"),
    ("38", "19", "Board of Veterans' Appeals: Legacy Appeals Regulations"),
    ("39", "955", "Rules of Practice Before the Postal Service Board of Contract Appeals"),
    ("39", "962", "Administrative False Claims Act"),
    ("41", "102-118", "Transportation Payment and Audit"),
    ("41", "102-37", "Donation of Surplus Personal Property"),
    ("42", "405", "Federal Health Insurance for the Aged and Disabled"),
    ("43", "30", "Indian Probate Hearings Procedures"),
    ("44", "206", "Federal Disaster Assistance"),
    ("44", "9", "Floodplain Management and Protection of Wetlands"),
    ("45", "2556", "Volunteers in Service to America"),
    ("45", "2522", "AmeriCorps Participants, Programs, and Applicants"),
    ("46", "56", "Piping Systems and Appurtenances"),
    ("46", "111", "Electric Systems—General Requirements"),
    ("47", "27", "Miscellaneous Wireless Communications Services"),
    (
        "47",
        "74",
        "Experimental Radio, Auxiliary, Special Broadcast and Other Program "
        "Distributional Services",
    ),
    ("48", "552", "Solicitation Provisions and Contract Clauses"),
    ("49", "385", "Safety Fitness Procedures"),
    ("49", "195", "Transportation of Hazardous Liquids by Pipeline"),
    (
        "50",
        "217",
        "Regulations Governing the Take of Marine Mammals Incidental to Specified "
        "Activities",
    ),
    ("50", "665", "Fisheries in the Western Pacific"),
)

#: Sections carrying two or more distinct dated versions, per declared part, from
#: the same scan. The supply number behind the eCFR quota.
PROBED_MULTI_VERSION_SECTIONS: Mapping[str, int] = MappingProxyType(
    {
        "2-180": 117,
        "2-182": 37,
        "4-28": 22,
        "4-21": 15,
        "5-2634": 65,
        "5-894": 33,
        "6-13": 36,
        "6-27": 31,
        "7-4290": 92,
        "7-5001": 69,
        "8-1003": 35,
        "8-1208": 22,
        "9-590": 136,
        "9-93": 53,
        "10-2": 89,
        "10-431": 77,
        "11-111": 18,
        "11-100": 16,
        "12-192": 95,
        "12-19": 84,
        "13-107": 67,
        "13-124": 63,
        "14-13": 87,
        "14-21": 40,
        "15-904": 48,
        "15-700": 34,
        "16-23": 27,
        "16-0": 18,
        "17-23": 41,
        "17-274": 40,
        "18-385": 49,
        "18-12": 24,
        "19-111": 55,
        "19-210": 49,
        "20-30": 81,
        "20-641": 38,
        "21-522": 121,
        "22-96": 55,
        "22-213": 33,
        "23-630": 34,
        "23-1300": 31,
        "24-206": 57,
        "24-983": 51,
        "25-224": 94,
        "25-1000": 41,
        "26-49": 19,
        "26-300": 12,
        "27-26": 59,
        "27-555": 57,
        "28-32": 30,
        "28-0": 28,
        "29-2200": 73,
        "29-2700": 58,
        "30-585": 151,
        "30-817": 55,
        "31-50": 49,
        "31-548": 49,
        "32-37": 24,
        "32-1900": 20,
        "33-127": 65,
        "33-147": 62,
        "34-75": 102,
        "34-76": 81,
        "36-1280": 34,
        "36-228": 17,
        "37-2": 82,
        "37-201": 36,
        "38-20": 71,
        "38-19": 35,
        "39-955": 30,
        "39-962": 27,
        "41-102-118": 90,
        "41-102-37": 87,
        "42-405": 133,
        "43-30": 54,
        "44-206": 26,
        "44-9": 17,
        "45-2556": 66,
        "45-2522": 49,
        "46-56": 102,
        "46-111": 99,
        "47-27": 109,
        "47-74": 94,
        "48-552": 138,
        "49-385": 60,
        "49-195": 55,
        "50-217": 124,
        "50-665": 85,
    }
)

#: The issuer set is a RULE rather than a list, because EDGAR's issuer universe
#: is itself a published, deterministic artifact and copying 8002 CIKs into this
#: file would make the frame less checkable, not more. The rule is fully
#: decidable from metadata and reproducible by anyone.
SEC_ISSUER_RULE: Mapping[str, Any] = MappingProxyType(
    {
        "universe": "https://www.sec.gov/files/company_tickers.json",
        "universe_size_at_declaration": 10388,
        "distinct_ciks_at_declaration": 8002,
        "start_after_cik": 33213,
        "why_start_after": (
            "33213 is the highest CIK any predecessor admitted -- V2R1 stopped at "
            "8177, V2R2 at 21344, V2R3 and V2R3R1 at 33213 over the same 300 pairs. "
            "Starting strictly above it makes the SEC family container-disjoint from "
            "EVERY predecessor by construction, matching the treatment of the other "
            "two families, rather than relying on lineage-level exclusion alone. The "
            "figure was read from the frozen universe receipts, not from memory."
        ),
        "sfi3_reservation": (
            "SFI3 declares no SEC roots, so the reservation reserves nothing in this "
            "family. That is reported as zero rather than treated as absence: a "
            "family the reservation says nothing about would REFUSE, and this one is "
            "covered and empty."
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
            "27 of the first 30 issuers above CIK 33213 carry at least one "
            "amendment pair, 135 pairs among those 30, so the quota is reachable well "
            "inside the ordered universe of 7856 issuers above the start"
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
            "documents counted with acquisition's own predicate. 78 candidates "
            "probed, 6 unreachable at the declared prefix, 27 dropped for holding "
            "fewer than 17 documents, 1 dropped for a truncated tree, 44 declared."
        ),
        "regulation_ecfr": (
            "a PAGINATED metadata scan across ALL FIFTY TITLES. The versions "
            "endpoint gives the number of sections carrying two or more distinct "
            "dated versions, per PART, without asking about any part individually -- "
            "which keeps the probe cheap and, more importantly, blind. The structure "
            "endpoint at 2026-08-01 says whether the part still EXISTS. "
            "872 fresh parts cleared the 12-section rule across 47 titles; "
            "9 were rejected for carrying section history without a live container; "
            "6 were rejected because the acquisition fetcher could not read them "
            "whole; the top two survivors per title were declared, giving 88."
        ),
        "why_existence_is_checked_separately": (
            "the versions endpoint carries section version HISTORY, and a part can "
            "vanish from the structure while that history remains. Title 39 part "
            "3004 has 20 multi-version sections on record and is not in the CFR "
            "today. Supply counted from history is not proof the container is "
            "usable, which is the one question a capacity probe exists to answer."
        ),
        "why_pagination_is_followed": (
            "the versions endpoint pages at 1,000 rows and reports the true total in "
            "`meta.total_pages`. An unpaginated read UNDERSTATES supply, and it "
            "understates it unevenly across titles, so a rule that ranks parts by "
            "supply would be ranking them by supply-visible-on-page-1. Title 2 "
            "carries 3,350 rows across 4 pages, and part 180 read as 20 "
            "multi-version sections when it has 117. The probe now follows every "
            "page and REFUSES a response whose meta says more rows exist than were "
            "read -- a partial supply reading that reports itself as complete is the "
            "defect this repair was for (INC-V2-076)."
        ),
        "every_declared_part_is_readable_in_one_fetcher_page": (
            "the acquisition fetcher queries `versions/title-N.json?part=P` and does "
            "NOT follow pagination. That base is V2R2 tooling and is not edited, so "
            "the constraint is enforced HERE: every part declared below was queried "
            "at exactly the URL the fetcher will use and returned `total_pages` 1. A "
            "part needing more would have its traversal silently restricted to "
            "whatever page 1 held -- deterministic, but not the traversal this frame "
            "declares, and a frame that describes a traversal the acquisition does "
            "not perform describes nothing."
        ),
        "sec_edgar": (
            "the published issuer universe plus the submissions API for the first "
            "30 issuers above the start CIK; form types and period dates only"
        ),
        "never_asked": (
            "what changed in a revision, whether a unit was renamed, whether the "
            "resolver would call anything ambiguous, whether a quarantine would form, "
            "how many qualifying changes a container holds, or what any invariant "
            "would say about it"
        ),
        "probe_tool": (
            "tools/probe_v2r4_roots.py, metadata-only, screening every candidate "
            "through root_identity AND SFI3_ROOT_RESERVATION_V1 before asking "
            "anything. It names the eight questions section F forbids it."
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
                {
                    "title": title,
                    "part": part,
                    "subject": subject,
                    "probed_multi_version_sections": PROBED_MULTI_VERSION_SECTIONS[
                        f"{title}-{part}"
                    ],
                }
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


def declared_containers() -> dict[str, list[str]]:
    """Container identities per family, in the spelling the reservation uses.

    This is what `sfi3_root_reservation.require_separation` is handed. `sec_edgar`
    is a RULE rather than a list and contributes no container identities, so it
    is reported as an empty list -- which the reservation reads as "checked and
    empty", not as "family absent". The difference matters: a family the
    reservation says nothing about REFUSES.
    """
    return {
        "git_docs": [f"{owner}/{repo}" for owner, repo, _p, _b, _l in GIT_ROOTS],
        "regulation_ecfr": [f"{title}-{part}" for title, part, _n in ECFR_ROOTS],
        "sec_edgar": [],
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
        "sfi3_reservation": dict(SFI3_RESERVATION),
        "forbidden_in_selection": list(FORBIDDEN_IN_SELECTION),
        "container_cap": dict(CONTAINER_CAP),
        "availability_probe": dict(AVAILABILITY_PROBE),
        "probed_and_not_declared": dict(PROBED_AND_NOT_DECLARED),
        "source_roots": source_roots(),
    }


def frame_digest() -> str:
    """Canonical digest of the declaration, independent of this file's comments."""
    body = json.dumps(frame_declaration(), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()
