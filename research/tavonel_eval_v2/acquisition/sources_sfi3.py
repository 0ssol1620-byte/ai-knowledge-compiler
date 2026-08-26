"""Acquisition frame for SOURCE_FACT_IR_HELDOUT_V3 (SFI3). Frozen before acquisition.

The founder rule this file exists to obey, quoted so it cannot be paraphrased
away by whoever edits it next:

    Freeze sampling quotas and family composition from the acquisition frame
    before scoring. Do not tune them against pass yield.

Every sampling constant below is a literal, declared here, with a basis that
names a property of the *frame* — grammar breadth, API availability, payload
distribution — and never a property of a result. `tests/test_sfi3_acquisition.py`
parses this module and fails if any of them stops being a literal, because a
quota computed at import time is a quota that can be computed from a receipt.

Why SFI3 needs a new corpus at all
-----------------------------------
`SOURCE_FACT_IR_HELDOUT_V2` was executed against its own frame — every
candidate `sfi2_lineages.json` listed was walked, and every one of those the
worker actually fetched, canonicalised and scored is named in
`artifacts/development/sfi2/sfi2_acquisition.json`'s `admitted` and `rejected`
lists. Both are spent for the same reason SFI1's were: a candidate that was
listed but never admitted was still looked at, and looking at it during SFI2
is enough to disqualify it from a study that is supposed to be held out from
that look. `spent_lineages()` unions both rather than only the admitted set.

SFI2's E5/E6 rebuild additionally produced fourteen confirmed cases of a
selective stale escape — the defect `SOURCE_FACT_IR_HELDOUT_V2` was rebuilt to
diagnose. Two repair lanes now use those fourteen as development fixtures. The
same rule that kept SFI1's four forensic cases out of SFI2 keeps these
fourteen out of SFI3: a case used to diagnose a defect cannot certify its
repair. They are read from
`receipts/latest/sfi2-native-provenance.json`'s
`rebuild.E5_confirmed_selective_stale_escape.confirmed` rather than retyped by
hand, because that receipt is the artifact that names them — SFI1's original
four had no such artifact and were named by hand for exactly that reason; these
fourteen do have one, and reading it is the reuse the earlier modules could not
do.

`spent_lineages()` reuses `sources_sfi2.spent_lineages()` for everything SFI2
inherited from SFI1, SFH1 and VBC2, and adds only what SFI2 itself spent: its
own frame, its own executor output, and the fourteen E5/E6 forensic cases.
Reuse is the whole point: one function, one place that can be wrong.

Roots, not lineages
--------------------
Like SFI1 and SFI2, this module declares *roots*. The lineage list is expanded
from them by `freeze_sfi3_lineages.py`, which needs the network and must run
after the protocol freeze and before any history is read. `frame()` reads the
sealed expansion and refuses, loudly, if it is absent: an acquisition frame
that silently evaluates to nothing would report a clean empty cohort, which is
the worst failure this study can have.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import sources_sfi2 as sfi2

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

PROTOCOL_ID = "SOURCE_FACT_IR_HELDOUT_V3"

#: The sealed lineage expansion. Produced by the freeze step from the roots
#: below, after the protocol freeze. Absent until then, and `frame()` says so.
FRAME = NS / "artifacts" / "development" / "sfi3_lineages.json"

#: SFI2's own sealed frame and executor output. Both name lineages SFI2 looked
#: at, and both are read here rather than restated — see the module docstring.
SFI2_FRAME = sfi2.FRAME
SFI2_ACQUISITION = NS / "artifacts" / "development" / "sfi2" / "sfi2_acquisition.json"

#: The receipt naming the fourteen lineages SFI2's E5/E6 rebuild used to
#: confirm the selective stale escape. A mutable convenience pointer — see its
#: own `note` field — but the identities it names do not change once written,
#: and this is the path the founder named.
SFI2_FORENSIC_RECEIPT = NS / "receipts" / "latest" / "sfi2-native-provenance.json"

#: Salt for the frozen consumption order. Distinct from every predecessor's,
#: so two studies over overlapping frames cannot walk them in the same
#: sequence and inherit each other's head.
ORDER_SALT = ":sfi-v3"


class FrameNotFrozen(RuntimeError):
    """The lineage expansion has not been sealed yet.

    Deliberately an exception. A frame module that returned `[]` here would let
    a run report a cohort of zero as a successful acquisition.
    """


class ContractBroken(RuntimeError):
    """A borrowed contract no longer says what this frame assumed it said."""


def _require_sfi2_e5_block(body: dict[str, Any]) -> str:
    """The E5 block key, taken from SFI2's scorer and checked against the receipt.

    The key belongs to SFI2, so it comes from SFI2 rather than being re-spelled
    here: a copy of another study's contract is the thing that drifts. But
    importing from a study that is already spent is a promise about a module
    nobody maintains for us any more, so the borrowed key is checked against the
    receipt it is about to index rather than trusted -- a bare `KeyError` from a
    renamed block would say nothing about which of the two moved.
    """
    import score_sfi2

    candidates = [
        block
        for endpoint, block, _count, _names in score_sfi2.REBUILD_BLOCKS
        if endpoint.startswith("E5_")
    ]
    if len(candidates) != 1:
        raise ContractBroken(
            f"score_sfi2.REBUILD_BLOCKS names {len(candidates)} E5 blocks, not one: "
            f"{candidates}. SFI3's exclusion set cannot pick one on its own."
        )
    block = candidates[0]
    rebuild = body.get("rebuild") or {}
    if block not in rebuild:
        raise ContractBroken(
            f"score_sfi2 says SFI2's E5 block is {block!r}, and the receipt carries "
            f"{sorted(rebuild)}. One of the two moved, and guessing which would "
            "silently change SFI3's exclusion set."
        )
    return block


def _load_sfi2_e5e6_forensic_lineages(path: Path) -> tuple[str, ...]:
    """The fourteen lineages SFI2's E5/E6 rebuild used to confirm the
    selective stale escape (INC-V2-006's successor defect under the V2 IR).

    Read from the receipt rather than retyped: SFI1's four forensic cases had
    no artifact naming them as a set and were named by hand for that reason;
    these fourteen do have one, and typing them out by hand here would be a
    second, driftable copy of what the receipt already states. A missing
    receipt raises rather than silently producing an empty forensic set,
    because a forensic set that quietly shrinks re-admits a diagnostic case.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist. SFI2's E5/E6 forensic set is one of the sources SFI3's "
            "forensic exclusion and spent set are derived from; it cannot be computed "
            "without it."
        )
    body = json.loads(path.read_text(encoding="utf-8"))
    if body.get("schema") == "tavonel.v2.receipt_pointer.v1":
        #: `receipts/latest/*.json` is a mutable convenience pointer — see its
        #: own `note` field: "cite the file it names, never this one." Follow
        #: it to the immutable receipt it points to, resolved against ROOT the
        #: same way `points_to` is written (repo-relative).
        pointed = ROOT / body["points_to"]
        if not pointed.exists():
            raise FileNotFoundError(
                f"{path} points to {pointed}, which does not exist. SFI2's E5/E6 forensic "
                "set cannot be computed without the receipt it names."
            )
        body = json.loads(pointed.read_text(encoding="utf-8"))
    confirmed = body["rebuild"][_require_sfi2_e5_block(body)]["confirmed"]
    return tuple(sorted({row["lineage_id"] for row in confirmed}))


#: The fourteen SFI2 E5/E6 forensic cases, read once at import time from the
#: receipt named above. See `_load_sfi2_e5e6_forensic_lineages`.
SFI2_E5E6_FORENSIC_LINEAGES: tuple[str, ...] = _load_sfi2_e5e6_forensic_lineages(
    SFI2_FORENSIC_RECEIPT
)

#: The original four cases (SFI1's, reused unchanged through SFI2) plus the
#: fourteen SFI2 added. A case used to diagnose a defect cannot certify its
#: repair — the reason does not expire when a second defect is found by a
#: second forensic pass; it just adds a second set of cases the reason covers.
FORENSIC_LINEAGES: tuple[str, ...] = tuple(
    sorted(set(sfi2.FORENSIC_LINEAGES) | set(SFI2_E5E6_FORENSIC_LINEAGES))
)


#: Where the spent set is derived from. Listed so a reader can check the
#: derivation without reading the function.
SPENT_SOURCES: tuple[str, ...] = (
    "acquisition/sources_sfi2.py spent_lineages()  (SFH1, VBC2, the four SFI1 forensic "
    "cases, every candidate SFI1's frame listed, every lineage SFI1's executor evaluated — "
    "reused, not reimplemented)",
    "artifacts/development/sfi2_lineages.json  (every candidate identity SFI2's frame listed)",
    "artifacts/development/sfi2/sfi2_acquisition.json  (every lineage SFI2's executor "
    "admitted or rejected)",
    "receipts/latest/sfi2-native-provenance.json rebuild.E5_confirmed_selective_stale_escape"
    ".confirmed  (the fourteen SFI2 E5/E6 forensic diagnostic cases)",
)


def _lineage_ids_from_acquisition(path: Path) -> set[str]:
    """Every lineage id in an executor output's `admitted` and `rejected` lists.

    SFI2's acquisition artifact is ~80MB because each admitted row carries its
    full extracted fact content alongside the identity. This reads the whole
    file (there is no cheaper way to reach the last row without one), but
    trims every row down to `{"lineage_id": ...}` as soon as it is parsed, via
    `object_hook`, rather than holding the parsed tree — including every
    extracted fact — in memory at once. This function never inspects any
    field but `lineage_id`; nothing here reads, canonicalises or scores a
    revision body.
    """
    ids: set[str] = set()

    def _strip(obj: dict[str, Any]) -> dict[str, Any]:
        if "lineage_id" in obj:
            ids.add(obj["lineage_id"])
            return {"lineage_id": obj["lineage_id"]}
        return obj

    with path.open(encoding="utf-8") as handle:
        json.load(handle, object_hook=_strip)
    return ids


def spent_lineages(
    *,
    sfi1_frame: Path | None = None,
    sfi1_acquisition: Path | None = None,
    sfi2_frame: Path | None = None,
    sfi2_acquisition: Path | None = None,
    sfi2_forensic_receipt: Path | None = None,
) -> frozenset[str]:
    """Every lineage a predecessor study already looked at.

    Four sources, unioned:

    * everything SFI2 inherited spent — SFH1, VBC2, the four SFI1 forensic
      cases, everything SFI1's frame listed and everything SFI1's executor
      evaluated — via `sources_sfi2.spent_lineages()`, reused here.
      `sfi1_frame` and `sfi1_acquisition` pass straight through to that call
      so a test can substitute a small fixture for SFI1's real ~100MB
      executor output the same way `sources_sfi2`'s own test suite does;
    * every candidate identity SFI2's own frame listed, whether or not it was
      admitted — `sfi2_lineages.json`'s `lineages`;
    * every lineage SFI2's executor actually evaluated —
      `sfi2_acquisition.json`'s `admitted` and `rejected`, which between them
      cover everything the worker considered;
    * the fourteen SFI2 E5/E6 forensic diagnostic cases.

    All three of SFI3's own files are read from disk rather than assumed
    present: a missing file raises rather than silently shrinking the spent
    set, because a spent set that quietly shrinks re-admits spent lineages.
    """
    frame_path = sfi2_frame if sfi2_frame is not None else SFI2_FRAME
    acquisition_path = sfi2_acquisition if sfi2_acquisition is not None else SFI2_ACQUISITION
    forensic_path = (
        sfi2_forensic_receipt if sfi2_forensic_receipt is not None else SFI2_FORENSIC_RECEIPT
    )

    spent: set[str] = set(sfi2.spent_lineages(frame=sfi1_frame, acquisition=sfi1_acquisition))
    spent.update(FORENSIC_LINEAGES)

    if not frame_path.exists():
        raise FileNotFoundError(
            f"{frame_path} does not exist. SFI2's sealed frame is one of the sources SFI3's "
            "spent set is derived from; it cannot be computed without it."
        )
    frame_body = json.loads(frame_path.read_text(encoding="utf-8"))
    spent.update(lineage["lineage_id"] for lineage in frame_body["lineages"])

    if not acquisition_path.exists():
        raise FileNotFoundError(
            f"{acquisition_path} does not exist. SFI2's executor output is one of the "
            "sources SFI3's spent set is derived from; it cannot be computed without it."
        )
    spent.update(_lineage_ids_from_acquisition(acquisition_path))

    spent.update(_load_sfi2_e5e6_forensic_lineages(forensic_path))

    return frozenset(spent)


# ---------------------------------------------------------------------------
# sampling constants
#
# Literals. Every one of them. See the module docstring and the AST test.
# Preserved unchanged from SOURCE_FACT_IR_HELDOUT_V2: the same three grammars
# are exercised by the same three families, so the outcome-independent basis
# — grammar breadth — has not changed, and nothing here is tuned against
# SFI2's observed yield.

#: Per-family admission ceilings. Carried forward unchanged from
#: SOURCE_FACT_IR_HELDOUT_V2 (itself carried unchanged from V1), whose basis
#: was grammar breadth: three distinct scanners are exercised — markdown,
#: MediaWiki-rendered HTML and eCFR XML — and the shares reflect how much of
#: each grammar a frame of this size can supply, not how much of it passes
#: anything. A family that yields zero is reported as zero and its quota is
#: never redistributed into a family that yields more. The frame is sized
#: generously below so the floor is reachable at SFI2's observed yield
#: without moving these numbers to reach it.
FAMILY_QUOTA: Mapping[str, int] = MappingProxyType(
    {
        "git_docs": 120,
        "regulation_ecfr": 100,
        "encyclopedia_wikipedia": 70,
    }
)

#: The same composition as a share, declared rather than computed so the two
#: cannot disagree after an edit to one of them.
FAMILY_SHARE: Mapping[str, float] = MappingProxyType(
    {
        "git_docs": 0.41,
        "regulation_ecfr": 0.35,
        "encyclopedia_wikipedia": 0.24,
    }
)

PRIMARY_TARGET = 290
FLOOR = 200
FAMILIES_REQUIRED = 3

QUOTA_BASIS: Mapping[str, Any] = MappingProxyType(
    {
        "basis": (
            "grammar breadth and frame supply, carried forward unchanged from "
            "SOURCE_FACT_IR_HELDOUT_V1 through SOURCE_FACT_IR_HELDOUT_V2"
        ),
        "explicitly_not_basis": (
            "pass yield, classification outcome or gate result, in SFH1, SFI1, SFI2 or SFI3"
        ),
        "frozen_before": "any SFI3 acquisition, any SFI3 classification, any SFI3 score",
        "redistribution": (
            "forbidden; an under-delivering family is reported short, never topped up "
            "from another"
        ),
        "reachability": (
            "SFI2 admitted 278 of 1,859 candidates (15%) at these same quotas, with "
            "TOO_FEW_REVISIONS the dominant rejection code (1,082 of 1,859); the SFI3 "
            "FRAME is sized generously in freeze_sfi3_lineages.py so the 200 floor is "
            "comfortably reachable at that yield. The quotas themselves are not moved to "
            "reach it — only the candidate supply is."
        ),
        "carried_from": "acquisition/sources_sfi2.py FAMILY_QUOTA",
    }
)

#: sec_edgar is NOT in this frame, and its absence is declared rather than
#: silent, for the same reason SFI1 and SFI2 declared it absent: this lane has
#: no network access here and will not invent a CIK to fill a slot. A fresh
#: SEC cohort needs verified issuers, and verifying one means fetching
#: EDGAR's company index and checking a ten-digit CIK resolves to a real
#: registrant — work this module cannot do without the network it
#: deliberately does not have. The orchestrator may add verified issuers
#: before the protocol freeze; it may not add them after, and it may not move
#: the three quotas above to compensate.
UNEXERCISED_FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "sec_edgar": (
            "no CIK can be verified without the network this module does not have; "
            "long-form filing grammar is not exercised by SFI3"
        )
    }
)

#: Inherited from VALUE_BEARING_COHORT_V2 through SFH1, SFI1 and SFI2,
#: unchanged, and for the reasons those protocols declared: API availability,
#: compute, reproducibility. STOP-V2-005 forbids refitting them to an
#: observed result.
HISTORY: Mapping[str, Any] = MappingProxyType(
    {
        "horizon_days": 1460,
        "acquisition_cutoff": "2026-08-23T00:00:00Z",
        "max_revisions_inspected_per_lineage": 12,
        "walk_order": "newest first, stopping at the first adjacent pair whose raw bytes differ",
        "basis": "API availability, compute and reproducibility",
        "explicitly_not_basis": "observed extraction outcome",
        "inherited_from": (
            "VALUE_BEARING_COHORT_V2 via SOURCE_FAITHFULNESS_HELDOUT_V1, "
            "SOURCE_FACT_IR_HELDOUT_V1 and SOURCE_FACT_IR_HELDOUT_V2"
        ),
    }
)

#: A revision larger than this is not extracted from, and is reported under
#: PAYLOAD_TOO_LARGE_TO_CLASSIFY rather than dropped.
#:
#: Carried forward unchanged from SFI2, whose basis was the *source payload
#: distribution* — a property of these four grammars, not of any instrument —
#: measured in SFH1: sizes are bimodal, the 95th percentile is 0.49 MB and the
#: next populated band starts above 3 MB, so every cap between 1 MB and 3 MB
#: excludes the same revisions. In SFH1 that was 44 lineages of 2,268
#: considered — 1.94% of the frame. A bound that cannot be moved usefully
#: across a 3x range is a bound that was not tuned, and the range is
#: published with it so a reader can check that.
MAX_PAYLOAD_BYTES = 2_000_000
MAX_PAYLOAD_BASIS = (
    "source payload distribution: bimodal, p95 0.49 MB, next band above 3 MB, so any "
    "cap in [1 MB, 3 MB] excludes the same revisions"
)
MAX_PAYLOAD_INSENSITIVE_RANGE = (1_000_000, 3_000_000)
MAX_PAYLOAD_EXCLUDED_FRACTION_IN_SFH1 = 0.0194
MAX_PAYLOAD_NOT_BASIS = "observed extraction outcome"

#: Why a lineage produced no scored result. Every non-admitted lineage carries
#: exactly one of these; none is a reason to reach back into the frame for a
#: replacement, because replacing a silent lineage with a talkative one is
#: selection by yield. The same eleven codes SFI1 and SFI2 declared: the
#: failure modes are properties of the executor and the grammars, not of the
#: study version.
FAILURE_CODES: tuple[str, ...] = (
    "SPENT_IN_PREDECESSOR_STUDY",
    "FORENSIC_DIAGNOSTIC_CASE",
    "FAMILY_NOT_DECLARED",
    "LISTING_FAILED",
    "TOO_FEW_REVISIONS",
    "NO_RAW_DIFFERENCE",
    "PAYLOAD_UNAVAILABLE",
    "PAYLOAD_TOO_LARGE_TO_CLASSIFY",
    "CANONICALISATION_EMPTY",
    "NO_SOURCE_FACTS_EXTRACTED",
    "BEYOND_FAMILY_QUOTA",
)

SPENT = "SPENT_IN_PREDECESSOR_STUDY"
FORENSIC = "FORENSIC_DIAGNOSTIC_CASE"
UNDECLARED_FAMILY = "FAMILY_NOT_DECLARED"


# ---------------------------------------------------------------------------
# roots
#
# Disjoint from SFI1's, SFI2's, VBC2's and P4i's declared roots, by
# construction. `tests/test_sfi3_acquisition.py` checks this programmatically
# rather than by eye. The freeze step checks it again against the expanded
# lineages, because a root that happens to contain a spent lineage is not
# caught by a root-level check.


#: Documentation trees carrying labelled structure, none of which appears in
#: SFI1's, SFI2's, VBC2's or P4i's git roots.
#: 12 of the original 32 roots below were found unavailable by the
#: availability-only preflight in
#: `receipts/sfi3-root-preflight--20260823T113621Z-39cd4b2447f9.json`: 2 repos
#: 404'd outright, 9 had a declared `prefix` no longer present on the default
#: branch, and 1 (`trinodb/trino`) was a transient TLS handshake timeout.
#: `tools/replace_sfi3_roots.py` recovered them under a criterion frozen
#: *before* any replacement candidate was checked (its own receipts:
#: `sfi3-root-replacement-policy` and `sfi3-root-replacement`,
#: `receipts/latest/`): `trinodb/trino` recovered on retry (the TLS timeout
#: was transient, confirmed reachable on retry) and is unchanged below; the
#: other 11 (`gitlab-org/gitlab`, `hashicorp/boundary`,
#: `open-policy-agent/opa`, `apache/pinot`, `questdb/questdb`,
#: `arangodb/docs`, `emberjs/guides-source`, `tailwindlabs/tailwindcss.com`,
#: `twbs/bootstrap`, `micronaut-projects/micronaut-docs`,
#: `hasura/graphql-engine`) were replaced with the 11 candidates the frozen
#: criterion accepted, marked `# replacement, sfi3-root-replacement` below.
#: Disjointness from SFI1's, SFI2's, VBC2's and P4i's git roots holds for the
#: replacements too — `tests/test_sfi3_acquisition.py` checks it
#: programmatically, not by eye, same as it always has.
GIT_ROOTS: tuple[dict[str, str], ...] = (
    {"owner": "github", "repo": "docs", "prefix": "content/", "license": "CC-BY-4.0"},
    {"owner": "hashicorp", "repo": "waypoint", "prefix": "website/content/docs/",
     "license": "MPL-2.0"},
    {"owner": "pulumi", "repo": "docs", "prefix": "content/docs/", "license": "Apache-2.0"},
    {"owner": "argoproj", "repo": "argo-workflows", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "kudu", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "trinodb", "repo": "trino", "prefix": "docs/src/main/sphinx/",
     "license": "Apache-2.0"},
    {"owner": "yugabyte", "repo": "yugabyte-db", "prefix": "docs/content/",
     "license": "Apache-2.0"},
    {"owner": "caddyserver", "repo": "website", "prefix": "src/docs/markdown/",
     "license": "Apache-2.0"},
    {"owner": "gatsbyjs", "repo": "gatsby", "prefix": "docs/docs/", "license": "MIT"},
    {"owner": "solidjs", "repo": "solid-docs", "prefix": "src/routes/", "license": "MIT"},
    {"owner": "preactjs", "repo": "preact-www", "prefix": "content/en/", "license": "MIT"},
    {"owner": "rollup", "repo": "rollup", "prefix": "docs/", "license": "MIT"},
    {"owner": "prettier", "repo": "prettier", "prefix": "docs/", "license": "MIT"},
    {"owner": "typescript-eslint", "repo": "typescript-eslint", "prefix": "docs/",
     "license": "MIT"},
    {"owner": "phoenixframework", "repo": "phoenix", "prefix": "guides/", "license": "MIT"},
    {"owner": "spring-projects", "repo": "spring-framework",
     "prefix": "framework-docs/modules/ROOT/pages/", "license": "Apache-2.0"},
    {"owner": "quarkusio", "repo": "quarkus", "prefix": "docs/src/main/asciidoc/",
     "license": "Apache-2.0"},
    {"owner": "bazelbuild", "repo": "bazel", "prefix": "site/en/docs/", "license": "Apache-2.0"},
    {"owner": "gradle", "repo": "gradle",
     "prefix": "platforms/documentation/docs/src/docs/userguide/", "license": "Apache-2.0"},
    {"owner": "scala", "repo": "docs.scala-lang", "prefix": "_overviews/",
     "license": "BSD-3-Clause"},
    {"owner": "odoo", "repo": "documentation", "prefix": "content/", "license": "LGPL-3.0"},
    # replacement, sfi3-root-replacement
    {"owner": "micrometer-metrics", "repo": "micrometer",
     "prefix": "docs/modules/ROOT/pages/", "license": "Apache-2.0"},
    {"owner": "sphinx-doc", "repo": "sphinx", "prefix": "doc/", "license": "BSD-2-Clause"},
    {"owner": "apache", "repo": "nifi", "prefix": "nifi-docs/", "license": "Apache-2.0"},
    {"owner": "oven-sh", "repo": "bun", "prefix": "docs/", "license": "MIT"},
    {"owner": "spring-projects", "repo": "spring-security",
     "prefix": "docs/modules/ROOT/pages/", "license": "Apache-2.0"},
    {"owner": "fastify", "repo": "fastify", "prefix": "docs/", "license": "MIT"},
    {"owner": "facebook", "repo": "docusaurus", "prefix": "website/docs/", "license": "MIT"},
    {"owner": "jekyll", "repo": "jekyll", "prefix": "docs/_docs/", "license": "MIT"},
    {"owner": "mkdocs", "repo": "mkdocs", "prefix": "docs/", "license": "BSD-2-Clause"},
    {"owner": "readthedocs", "repo": "readthedocs.org", "prefix": "docs/user/",
     "license": "MIT"},
    {"owner": "mattermost", "repo": "docs", "prefix": "source/", "license": "Apache-2.0"},
)

#: CFR parts carrying labelled quantities. Disjoint from SFI1's, SFI2's,
#: VBC2's and P4i's ECFR roots.
#:
#: title-41-part-301 was found to carry no recorded content_versions by the
#: same preflight named in `GIT_ROOTS`'s comment, and was replaced by
#: title-17-part-200 under the same frozen `tools/replace_sfi3_roots.py`
#: criterion — see that comment for the receipts.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("5", "2635", "Standards of ethical conduct for employees of the executive branch"),
    ("7", "301", "Domestic quarantine notices"),
    ("8", "204", "Immigrant petitions"),
    ("9", "3", "Diseases and disabilities generally"),
    ("10", "72", "Licenses to possess special nuclear materials"),
    ("11", "104", "Reports by political committees and other persons"),
    ("12", "1041", "Payday, vehicle title and certain high-cost installment loans"),
    ("13", "120", "Business loans"),
    ("14", "71", "Designation of class A, B, C, D and E airspace areas"),
    ("15", "740", "License exceptions"),
    ("16", "444", "Credit practices rule"),
    ("17", "249", "Rules relating to over-the-counter markets"),
    ("18", "35", "Filing of rate schedules and tariffs"),
    ("19", "10", "Articles conditionally free, subject to a reduced rate, etc."),
    ("20", "416", "Supplemental security income for the aged, blind and disabled"),
    ("21", "1301", "Registration of manufacturers, distributors and dispensers of "
     "controlled substances"),
    ("22", "120", "Purpose and definitions"),
    ("23", "650", "Bridges, structures and hydraulics"),
    ("24", "3282", "Manufactured home procedural and enforcement regulations"),
    ("25", "151", "Land acquisitions"),
    ("26", "31", "Employment taxes and collection of income tax at source"),
    ("27", "9", "American viticultural areas"),
    ("28", "35", "Nondiscrimination on the basis of disability in state and local "
     "government services"),
    ("29", "1602", "Recordkeeping and reporting requirements under Title VII, the ADA "
     "and GINA"),
    ("30", "550", "Oil and gas and sulfur operations in the outer continental shelf"),
    ("31", "560", "Iranian Transactions and Sanctions Regulations"),
    ("32", "2001", "Classified national security information"),
    ("33", "334", "Danger zone and restricted area regulations"),
    ("34", "685", "William D. Ford Federal Direct Loan Program"),
    ("36", "7", "Special regulations, areas of the National Park System"),
    ("37", "202", "Preregistration and registration of claims to copyright"),
    ("38", "36", "Loan guaranty"),
    ("40", "125", "Criteria and standards for the National Pollutant Discharge "
     "Elimination System"),
    ("42", "84", "Approval of respiratory protective devices"),
    ("45", "75", "Uniform administrative requirements, cost principles for HHS awards"),
    # replacement, sfi3-root-replacement
    ("17", "200", "Organization; conduct and ethics; and information and requests"),
)

#: Categories expanded into article lineages before any history is read.
#: Disjoint from SFI1's, SFI2's and VBC2's ten each.
#:
#: Category:Cities and towns in Hyogo Prefecture was found not to exist by the
#: same preflight named in `GIT_ROOTS`'s comment, and was replaced by
#: Category:Cities in Hungary under the same frozen criterion.
WIKIPEDIA_CATEGORY_ROOTS: tuple[str, ...] = (
    "Category:Municipalities of Finland",
    "Category:Cities in Poland",
    "Category:Municipalities of the Netherlands",
    "Category:Towns in Ireland",
    "Category:Municipalities of Portugal",
    "Category:Cities in Chile",
    "Category:Municipalities of Slovakia",
    "Category:Municipalities of Belgium",
    "Category:Populated places in Bulgaria",
    # replacement, sfi3-root-replacement
    "Category:Cities in Hungary",
)

#: Empty by declaration, not by omission. See UNEXERCISED_FAMILIES.
SEC_ROOTS: tuple[tuple[str, str], ...] = ()

CONSUMPTION_ORDER: Mapping[str, Any] = MappingProxyType(
    {
        "frozen_before_any_history_read": True,
        "frozen_before_any_value_read": True,
        "rule": f"ascending sha256 of (lineage_id + {ORDER_SALT!r})",
        "git_docs": tuple(root["owner"] + "/" + root["repo"] for root in GIT_ROOTS),
        "regulation_ecfr": tuple(title + "-" + part for title, part, _ in ECFR_ROOTS),
        "encyclopedia_wikipedia": WIKIPEDIA_CATEGORY_ROOTS,
        "sec_edgar": (),
    }
)


# ---------------------------------------------------------------------------
# the frame


def order_key(lineage_id: str, salt: str = ORDER_SALT) -> str:
    """The frozen consumption order.

    Salted so the sequence is a declared slice of the frame rather than a
    chosen one, and so it is not the sequence any predecessor walked.
    """
    return hashlib.sha256((lineage_id + salt).encode("utf-8")).hexdigest()


def build_frame(
    source: Path | None = None,
    *,
    spent: frozenset[str] | None = None,
    salt: str = ORDER_SALT,
) -> dict[str, Any]:
    """Eligible lineages in frozen order, plus every exclusion with its code.

    Nothing leaves this function uncoded. A lineage is either in `lineages` or
    in `dropped` with one of `FAILURE_CODES`, and the two partition the input.
    """
    listing = source if source is not None else FRAME
    if not listing.exists():
        raise FrameNotFrozen(
            f"{listing} does not exist. The SFI3 lineage expansion has not been sealed; "
            "run the freeze step after the protocol freeze. Refusing to return an empty frame."
        )
    spent = spent if spent is not None else spent_lineages()

    body = json.loads(listing.read_text(encoding="utf-8"))
    eligible: list[dict[str, Any]] = []
    dropped: list[dict[str, str]] = []
    for lineage in body["lineages"]:
        lineage_id = lineage["lineage_id"]
        if lineage_id in FORENSIC_LINEAGES:
            dropped.append({"lineage_id": lineage_id, "code": FORENSIC})
        elif lineage_id in spent:
            dropped.append({"lineage_id": lineage_id, "code": SPENT})
        elif lineage["family"] not in FAMILY_QUOTA:
            dropped.append({"lineage_id": lineage_id, "code": UNDECLARED_FAMILY})
        else:
            eligible.append(lineage)

    eligible.sort(key=lambda lineage: order_key(lineage["lineage_id"], salt))
    dropped.sort(key=lambda row: (row["code"], row["lineage_id"]))
    return {"source": str(listing), "lineages": eligible, "dropped": dropped}


def frame(source: Path | None = None, **kwargs: Any) -> list[dict[str, Any]]:
    """Every eligible lineage, in frozen order. The house-pattern accessor."""
    return build_frame(source, **kwargs)["lineages"]


def frame_digest(rows: list[dict[str, Any]]) -> str:
    """Pins the frame — which lineages, in which order — before scoring."""
    payload = json.dumps(
        [row["lineage_id"] for row in rows], separators=(",", ":"), ensure_ascii=False
    )
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def family_composition(rows: list[dict[str, Any]]) -> dict[str, int]:
    """How many eligible lineages each declared family supplies.

    Frame composition, not an outcome: it counts what may be looked at, and
    nothing here has been fetched, canonicalised or classified.
    """
    counts = {family: 0 for family in FAMILY_QUOTA}
    for row in rows:
        counts[row["family"]] = counts.get(row["family"], 0) + 1
    return counts


def quota_digest() -> str:
    """Pins the sampling constants so the protocol freeze can seal them.

    Anything that changes a quota, a share, the target, the floor or the payload
    bound after the freeze changes this digest and is therefore visible.
    """
    return "sha256:" + hashlib.sha256(
        json.dumps(
            {
                "family_quota": dict(FAMILY_QUOTA),
                "family_share": dict(FAMILY_SHARE),
                "primary_target": PRIMARY_TARGET,
                "floor": FLOOR,
                "families_required": FAMILIES_REQUIRED,
                "unexercised_families": dict(UNEXERCISED_FAMILIES),
                "max_payload_bytes": MAX_PAYLOAD_BYTES,
                "history": dict(HISTORY),
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def sampling_constants_are_literal() -> dict[str, bool]:
    """Parse this module and report whether each sampling constant is a literal.

    A quota that is a literal cannot have been computed from a receipt, and this
    is the only check that stays true when someone edits the file. It reads the
    source rather than the imported values, because an imported value has
    already lost the distinction between `120` and `int(receipt["by_family"])`.
    """
    names = (
        "FAMILY_QUOTA",
        "FAMILY_SHARE",
        "PRIMARY_TARGET",
        "FLOOR",
        "FAMILIES_REQUIRED",
        "MAX_PAYLOAD_BYTES",
    )
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    found: dict[str, bool] = {name: False for name in names}
    for node in tree.body:
        targets = (
            [node.target] if isinstance(node, ast.AnnAssign) else getattr(node, "targets", [])
        )
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in found:
                continue
            value = node.value
            if value is None:  # a bare annotation declares nothing
                continue
            #: MappingProxyType({...}) is still a literal declaration; the
            #: wrapper only makes the mapping read-only.
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Name)
                and value.func.id == "MappingProxyType"
                and len(value.args) == 1
            ):
                value = value.args[0]
            try:
                ast.literal_eval(value)
            except (ValueError, SyntaxError, TypeError):
                found[target.id] = False
            else:
                found[target.id] = True
    return found
