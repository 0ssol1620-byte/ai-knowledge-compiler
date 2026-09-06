"""Acquisition frame for SOURCE_FACT_IR_HELDOUT_V2 (SFI2). Frozen before acquisition.

The founder rule this file exists to obey, quoted so it cannot be paraphrased
away by whoever edits it next:

    Freeze sampling quotas and family composition from the acquisition frame
    before scoring. Do not tune them against pass yield.

Every sampling constant below is a literal, declared here, with a basis that
names a property of the *frame* — grammar breadth, API availability, payload
distribution — and never a property of a result. `tests/test_sfi2_acquisition.py`
parses this module and fails if any of them stops being a literal, because a
quota computed at import time is a quota that can be computed from a receipt.

Why SFI2 needs a new corpus at all
-----------------------------------
`SOURCE_FACT_IR_HELDOUT_V1` returned a held-out FAIL and is FROZEN — the
founder has ruled it "must never be rescored". Its frame is now development
material only, and V2 needs a corpus SFI1 never touched.

SFI1 spent two things arithmetically: the *frame* it froze
(`artifacts/development/sfi1_lineages.json`, 1,997 candidate identities, walked
and coded whether or not each one was ultimately admitted) and the *executor*
run against it (`artifacts/development/sfi1/sfi1_acquisition.json`, whose
`admitted` and `rejected` lists name every lineage the worker actually fetched,
canonicalised and scored). Both are spent: a candidate that was listed but
never admitted was still looked at, and looking at it during SFI1 is enough to
disqualify it from a study that is supposed to be held out from that look.
`spent_lineages()` unions both rather than only the admitted set, because a
held-out corpus is defined by what was inspected, not by what passed.

SFH1's spend and the four forensic cases are pulled in through
`sources_sfi1.spent_lineages()` rather than rederived — that function is
already the union of SFH1's receipts, SFH1's published pairs and VBC2's three
cohorts, and reimplementing it here would be a second copy of the same
derivation that could silently drift from the first. Reuse is the whole point:
one function, one place that can be wrong.

The four forensic cases are excluded for a reason distinct from "spent": a
case used to diagnose a defect cannot certify its repair. They are the
documents whose stale escapes produced INC-V2-006 and the SFH1 demotion, and
their behaviour under the new IR was reasoned about while the IR was being
designed — first for SFI1, and that reasoning did not change for SFI2. Scoring
them now, in *any* version of this IR, measures the design against its own
worked examples rather than against something it has never seen.

Roots, not lineages
--------------------
Like SFI1, this module declares *roots*. The lineage list is expanded from
them by `freeze_sfi2_lineages.py`, which needs the network and must run after
the protocol freeze and before any history is read. `frame()` reads the sealed
expansion and refuses, loudly, if it is absent: an acquisition frame that
silently evaluates to nothing would report a clean empty cohort, which is the
worst failure this study can have.
"""

from __future__ import annotations

import ast
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import sources_sfi1 as sfi1

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

PROTOCOL_ID = "SOURCE_FACT_IR_HELDOUT_V2"

#: The sealed lineage expansion. Produced by the freeze step from the roots
#: below, after the protocol freeze. Absent until then, and `frame()` says so.
FRAME = NS / "artifacts" / "development" / "sfi2_lineages.json"

#: SFI1's own sealed frame and executor output. Both name lineages SFI1 looked
#: at, and both are read here rather than restated — see the module docstring.
SFI1_FRAME = sfi1.FRAME
SFI1_ACQUISITION = NS / "artifacts" / "development" / "sfi1" / "sfi1_acquisition.json"

#: Salt for the frozen consumption order. Distinct from SFI1's ORDER_SALT, so
#: two studies over overlapping frames cannot walk them in the same sequence
#: and inherit each other's head.
ORDER_SALT = ":sfi-v2"

#: The four cases that diagnosed the defect. Not retyped: reused from
#: sources_sfi1, where they are named by hand because no artifact records them
#: as a set. Reused rather than copied so the two studies cannot silently
#: disagree about which four documents they are.
#:
#: A case used to diagnose a defect cannot certify its repair: the IR was
#: designed while reasoning about exactly these stale escapes, first for SFI1
#: and unchanged for SFI2. Scoring them now would measure the design against
#: its own worked examples rather than against held-out source, in any
#: version of the IR.
FORENSIC_LINEAGES: tuple[str, ...] = sfi1.FORENSIC_LINEAGES


class FrameNotFrozen(RuntimeError):
    """The lineage expansion has not been sealed yet.

    Deliberately an exception. A frame module that returned `[]` here would let
    a run report a cohort of zero as a successful acquisition.
    """


#: Where the spent set is derived from. Listed so a reader can check the
#: derivation without reading the function.
SPENT_SOURCES: tuple[str, ...] = (
    "artifacts/development/sfi1_lineages.json  (every candidate identity SFI1's frame listed)",
    "artifacts/development/sfi1/sfi1_acquisition.json  (every lineage SFI1's executor "
    "admitted or rejected)",
    "acquisition/sources_sfi1.py spent_lineages()  (SFH1's receipts, SFH1's published "
    "pairs, VBC2's three cohorts — reused, not reimplemented)",
    "acquisition/sources_sfi1.py FORENSIC_LINEAGES  (the four diagnostic cases)",
)


def spent_lineages(
    *,
    frame: Path | None = None,
    acquisition: Path | None = None,
) -> frozenset[str]:
    """Every lineage a predecessor study already looked at.

    Three sources, unioned:

    * SFH1's spend, VBC2's three cohorts and the four forensic cases, via
      `sources_sfi1.spent_lineages()` — computed there, reused here;
    * every candidate identity SFI1's own frame listed, whether or not it was
      admitted — `sfi1_lineages.json`'s `lineages`;
    * every lineage SFI1's executor actually evaluated — `sfi1_acquisition.json`'s
      `admitted` and `rejected`, which between them cover everything the worker
      considered.

    Both SFI1 files are read from disk rather than assumed present: a missing
    file raises rather than silently shrinking the spent set, because a spent
    set that quietly shrinks re-admits spent lineages.
    """
    frame_path = frame if frame is not None else SFI1_FRAME
    acquisition_path = acquisition if acquisition is not None else SFI1_ACQUISITION

    spent: set[str] = set(sfi1.spent_lineages())

    if not frame_path.exists():
        raise FileNotFoundError(
            f"{frame_path} does not exist. SFI1's sealed frame is one of the sources SFI2's "
            "spent set is derived from; it cannot be computed without it."
        )
    frame_body = json.loads(frame_path.read_text(encoding="utf-8"))
    spent.update(lineage["lineage_id"] for lineage in frame_body["lineages"])

    if not acquisition_path.exists():
        raise FileNotFoundError(
            f"{acquisition_path} does not exist. SFI1's executor output is one of the "
            "sources SFI2's spent set is derived from; it cannot be computed without it."
        )
    spent.update(_lineage_ids_from_acquisition(acquisition_path))

    return frozenset(spent)


def _lineage_ids_from_acquisition(path: Path) -> set[str]:
    """Every lineage id in an executor output's `admitted` and `rejected` lists.

    SFI1's acquisition artifact is ~100MB because each admitted row carries its
    full extracted fact content alongside the identity. Holding that parsed tree
    in memory made the test suite fail with `MemoryError` at a different test on
    every run once several such loads co-resided — a suite that cannot give a
    stable answer cannot serve as an integration gate.

    This still reads the whole file, since there is no cheaper way to reach the
    last row, but trims each row to `{"lineage_id": ...}` as it is parsed rather
    than retaining the facts. Nothing here reads, canonicalises or scores a
    revision body; `lineage_id` is the only field consulted.

    The pattern is Lane E's, proven on SFI2's 80MB artifact for the same reason.
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


# ---------------------------------------------------------------------------
# sampling constants
#
# Literals. Every one of them. See the module docstring and the AST test.

#: Per-family admission ceilings. Carried forward unchanged from
#: SOURCE_FACT_IR_HELDOUT_V1, whose basis was grammar breadth: three distinct
#: scanners are exercised — markdown, MediaWiki-rendered HTML and eCFR XML —
#: and the shares reflect how much of each grammar a frame of this size can
#: supply, not how much of it passes anything. A family that yields zero is
#: reported as zero and its quota is never redistributed into a family that
#: yields more. The frame is sized generously below so the floor is reachable
#: at SFI1's observed yield without moving these numbers to reach it.
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
            "SOURCE_FACT_IR_HELDOUT_V1"
        ),
        "explicitly_not_basis": (
            "pass yield, classification outcome or gate result, in SFH1, in SFI1 or in SFI2"
        ),
        "frozen_before": "any SFI2 acquisition, any SFI2 classification, any SFI2 score",
        "redistribution": (
            "forbidden; an under-delivering family is reported short, never topped up "
            "from another"
        ),
        "reachability": (
            "SFI1 admitted 260 of 1,997 candidates (13%) at these same quotas; the SFI2 "
            "FRAME is sized generously in freeze_sfi2_lineages.py so the 200 floor is "
            "comfortably reachable at that yield. The quotas themselves are not moved to "
            "reach it — only the candidate supply is."
        ),
        "carried_from": "acquisition/sources_sfi1.py FAMILY_QUOTA",
    }
)

#: sec_edgar is NOT in this frame, and its absence is declared rather than
#: silent, for the same reason SFI1 declared it absent: this lane has no
#: network access here and will not invent a CIK to fill a slot. A fresh SEC
#: cohort needs verified issuers, and verifying one means fetching EDGAR's
#: company index and checking a ten-digit CIK resolves to a real registrant —
#: work this module cannot do without the network it deliberately does not
#: have. The orchestrator may add verified issuers before the protocol
#: freeze; it may not add them after, and it may not move the three quotas
#: above to compensate.
UNEXERCISED_FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "sec_edgar": (
            "no CIK can be verified without the network this module does not have; "
            "long-form filing grammar is not exercised by SFI2"
        )
    }
)

#: Inherited from VALUE_BEARING_COHORT_V2 through SFH1 and SFI1, unchanged,
#: and for the reasons those protocols declared: API availability, compute,
#: reproducibility. STOP-V2-005 forbids refitting them to an observed result.
HISTORY: Mapping[str, Any] = MappingProxyType(
    {
        "horizon_days": 1460,
        "acquisition_cutoff": "2026-08-23T00:00:00Z",
        "max_revisions_inspected_per_lineage": 12,
        "walk_order": "newest first, stopping at the first adjacent pair whose raw bytes differ",
        "basis": "API availability, compute and reproducibility",
        "explicitly_not_basis": "observed extraction outcome",
        "inherited_from": (
            "VALUE_BEARING_COHORT_V2 via SOURCE_FAITHFULNESS_HELDOUT_V1 and "
            "SOURCE_FACT_IR_HELDOUT_V1"
        ),
    }
)

#: A revision larger than this is not extracted from, and is reported under
#: PAYLOAD_TOO_LARGE_TO_CLASSIFY rather than dropped.
#:
#: Carried forward unchanged from SFI1, whose basis was the *source payload
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
#: selection by yield. The same eleven codes SFI1 declared: the failure modes
#: are properties of the executor and the grammars, not of the study version.
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
# Disjoint from SFI1's declared roots, from VBC2's and from P4i's, by
# construction. `tests/test_sfi2_acquisition.py` checks this programmatically
# rather than by eye. The freeze step checks it again against the expanded
# lineages, because a root that happens to contain a spent lineage is not
# caught by a root-level check.


#: Documentation trees carrying labelled structure, none of which appears in
#: SFI1's GIT_ROOTS, VBC2's GIT_ROOTS or P4i's GIT_REPOSITORIES_ALL.
GIT_ROOTS: tuple[dict[str, str], ...] = (
    {"owner": "hashicorp", "repo": "vault", "prefix": "website/content/docs/",
     "license": "MPL-2.0"},
    {"owner": "hashicorp", "repo": "consul", "prefix": "website/content/docs/",
     "license": "MPL-2.0"},
    {"owner": "hashicorp", "repo": "nomad", "prefix": "website/content/docs/",
     "license": "MPL-2.0"},
    {"owner": "hashicorp", "repo": "packer", "prefix": "website/content/docs/",
     "license": "MPL-2.0"},
    {"owner": "hashicorp", "repo": "terraform-cdk", "prefix": "docs/", "license": "MPL-2.0"},
    {"owner": "apache", "repo": "pulsar", "prefix": "site2/docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "druid", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "hudi", "prefix": "website/docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "iceberg", "prefix": "docs/docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "superset", "prefix": "docs/docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "zeppelin", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "skywalking", "prefix": "docs/en/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "dolphinscheduler", "prefix": "docs/docs/en/",
     "license": "Apache-2.0"},
    {"owner": "jenkins-infra", "repo": "jenkins.io", "prefix": "content/en/doc/",
     "license": "CC-BY-SA-4.0"},
    {"owner": "getsentry", "repo": "sentry-docs", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "cypress-io", "repo": "cypress-documentation", "prefix": "content/",
     "license": "MIT"},
    {"owner": "microsoft", "repo": "playwright", "prefix": "docs/src/",
     "license": "Apache-2.0"},
    {"owner": "microsoft", "repo": "vscode-docs", "prefix": "docs/", "license": "CC-BY-4.0"},
    {"owner": "webpack", "repo": "webpack.js.org", "prefix": "content/", "license": "MIT"},
    {"owner": "vitejs", "repo": "vite", "prefix": "docs/guide/", "license": "MIT"},
    {"owner": "nuxt", "repo": "nuxt", "prefix": "docs/", "license": "MIT"},
    {"owner": "sveltejs", "repo": "kit", "prefix": "documentation/docs/", "license": "MIT"},
    {"owner": "remix-run", "repo": "remix", "prefix": "docs/", "license": "MIT"},
    {"owner": "tiangolo", "repo": "fastapi", "prefix": "docs/en/docs/", "license": "MIT"},
    {"owner": "encode", "repo": "django-rest-framework", "prefix": "docs/",
     "license": "BSD-3-Clause"},
    {"owner": "pydantic", "repo": "pydantic", "prefix": "docs/", "license": "MIT"},
    {"owner": "prefecthq", "repo": "prefect", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "dagster-io", "repo": "dagster", "prefix": "docs/content/",
     "license": "Apache-2.0"},
    {"owner": "eslint", "repo": "eslint", "prefix": "docs/src/", "license": "MIT"},
    {"owner": "netlify", "repo": "docs", "prefix": "src/", "license": "CC-BY-4.0"},
    {"owner": "cloudflare", "repo": "cloudflare-docs", "prefix": "src/content/docs/",
     "license": "CC-BY-4.0"},
    {"owner": "supabase", "repo": "supabase", "prefix": "apps/docs/content/",
     "license": "Apache-2.0"},
    {"owner": "metabase", "repo": "metabase", "prefix": "docs/", "license": "AGPL-3.0"},
)

#: CFR parts carrying labelled quantities. Disjoint from SFI1's ECFR_ROOTS,
#: VBC2's ECFR_ROOTS and P4i's ECFR_PARTS_ALL.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("40", "262", "Standards for generators of hazardous waste"),
    ("40", "761", "Polychlorinated biphenyls (PCBs) manufacturing and processing"),
    ("21", "111", "Current good manufacturing practice for dietary supplements"),
    ("21", "117", "Hazard analysis and preventive controls for human food"),
    ("29", "1917", "Marine terminals"),
    ("29", "1928", "Occupational safety and health standards for agriculture"),
    ("14", "61", "Certification: pilots, flight instructors and ground instructors"),
    ("14", "141", "Pilot schools"),
    ("12", "3", "Capital adequacy standards for national banks"),
    ("17", "210", "Form and content of financial statements"),
    ("17", "229", "Standard instructions for filing forms under Regulation S-K"),
    ("19", "141", "Entry of merchandise"),
    ("22", "121", "The United States Munitions List"),
    ("24", "200", "Introduction to FHA programs"),
    ("26", "25", "Gift tax"),
    ("27", "478", "Commerce in firearms and ammunition"),
    ("29", "825", "The Family and Medical Leave Act of 1993"),
    ("30", "816", "Permanent program performance standards, surface coal mining"),
    ("31", "515", "Cuban Assets Control Regulations"),
    ("33", "401", "Great Lakes Pilotage"),
    ("34", "300", "Assistance to states for the education of children with disabilities"),
    ("36", "1191", "Americans with Disabilities Act accessibility guidelines"),
    ("38", "4", "Schedule for rating disabilities"),
    ("40", "51", "Requirements for preparation, adoption and submittal of implementation plans"),
    ("41", "102", "Federal management regulation"),
    ("42", "447", "Payment for services, Medicaid"),
    ("43", "3160", "Onshore oil and gas operations"),
    ("45", "155", "Exchange establishment standards under the Affordable Care Act"),
    ("46", "15", "Manning requirements"),
    ("47", "90", "Private land mobile radio services"),
    ("48", "15", "Contracting by negotiation"),
    ("49", "383", "Commercial driver's license standards"),
    ("50", "224", "Endangered marine and anadromous fish"),
    ("7", "51", "Fresh fruits, vegetables and other products, standards and inspection"),
    ("12", "1030", "Reserve requirements of depository institutions - overdrafts"),
    ("21", "801", "Labeling of medical devices"),
    ("40", "72", "Underground injection control program"),
)

#: Categories expanded into article lineages before any history is read.
#: Disjoint from SFI1's ten and VBC2's ten.
WIKIPEDIA_CATEGORY_ROOTS: tuple[str, ...] = (
    "Category:Municipalities of Norway",
    "Category:Cities in South Korea",
    "Category:Municipalities of the Faroe Islands",
    "Category:Communes of the Somme department",
    "Category:Municipalities of the Braga District",
    "Category:Cities in New Zealand",
    "Category:Municipalities of Croatia",
    "Category:Populated places in Lithuania",
    "Category:Municipalities of the Province of Girona",
    "Category:Cities in Western Australia",
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
            f"{listing} does not exist. The SFI2 lineage expansion has not been sealed; "
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
