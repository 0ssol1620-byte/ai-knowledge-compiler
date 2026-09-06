"""Acquisition frame for SOURCE_FACT_IR_HELDOUT_V1 (SFI1). Frozen before acquisition.

The founder rule this file exists to obey, quoted so it cannot be paraphrased
away by whoever edits it next:

    Freeze sampling quotas and family composition from the acquisition frame
    before scoring. Do not tune them against pass yield.

Every sampling constant below is a literal, declared here, with a basis that
names a property of the *frame* — grammar breadth, API availability, payload
distribution — and never a property of a result. `tests/test_sfi_acquisition.py`
parses this module and fails if any of them stops being a literal, because a
quota computed at import time is a quota that can be computed from a receipt.

Why SFI1 needs a new corpus at all
----------------------------------
SFH1 walked its entire frame. Its receipt says so arithmetically: the second
run reports ``lineages_considered == frame.candidates == 2268``, so every
lineage in ``artifacts/development/vbc2_lineages.json`` had its revisions
listed, its payloads fetched and — for the 1,161 that reached the classifier —
its canonical documents built and scored. Whether an individual outcome was
published (310 were, per-lineage, in ``sfh1_pairs.json``) does not restore the
held-out property: the corpus was spent by being executed against.

`spent_lineages()` derives that set from the receipts and the artifacts rather
than restating it, so the exclusion cannot drift away from what actually ran.

The four forensic cases are excluded by name for a different reason: a case used
to diagnose the defect cannot be used to certify the repair. They are the
documents whose stale escapes produced INC-V2-006 and the SFH1 demotion, and
their behaviour under the new IR was reasoned about while the IR was being
designed. Scoring them now measures the design against its own worked examples.

Roots, not lineages
-------------------
Like VBC2, this module declares *roots*. The lineage list is expanded from them
by a freeze step that needs the network, and that step must run before scoring
and after the protocol freeze — not from here. `frame()` reads the sealed
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

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

PROTOCOL_ID = "SOURCE_FACT_IR_HELDOUT_V1"

#: The sealed lineage expansion. Produced by the freeze step from the roots
#: below, after the protocol freeze. Absent until then, and `frame()` says so.
FRAME = NS / "artifacts" / "development" / "sfi1_lineages.json"

#: Salt for the frozen consumption order. Distinct from every predecessor's, so
#: two studies over overlapping frames cannot walk them in the same sequence and
#: inherit each other's head.
ORDER_SALT = ":sfi-v1"


class FrameNotFrozen(RuntimeError):
    """The lineage expansion has not been sealed yet.

    Deliberately an exception. A frame module that returned `[]` here would let
    a run report a cohort of zero as a successful acquisition.
    """


# ---------------------------------------------------------------------------
# what SFI1 may not touch


#: The four cases that diagnosed the defect. Named, not derived, because they
#: were selected by hand during the forensic pass and no artifact records them
#: as a set. A case used to diagnose the defect cannot be used to certify the
#: repair: the new IR was designed while reasoning about exactly these stale
#: escapes, so a pass on them measures the design against its own worked
#: examples rather than against held-out source.
FORENSIC_LINEAGES: tuple[str, ...] = (
    "wikipedia:en:Three Villages",
    "wikipedia:en:Monteceneri",
    "wikipedia:en:Locarno",
    "git:pnpm/pnpm.io:docs/cli/change.md",
)

#: Where the spent set is derived from. Listed so a reader can check the
#: derivation without reading the function.
SPENT_SOURCES: tuple[str, ...] = (
    "receipts/sfh1-source-faithfulness--*.json  (the frame each run walked, and how much of it)",
    "artifacts/development/sfh1/sfh1_pairs.json  (the lineages whose outcomes were published)",
    "artifacts/development/vbc2_cohorts/vbc2_cohort.*.json  (the three VBC2 admissions)",
    "acquisition/sources_sfi1.py FORENSIC_LINEAGES  (the four diagnostic cases)",
)


def _resolve(repo_relative: str, root: Path) -> Path:
    return root / repo_relative


def _lineage_ids(path: Path) -> set[str]:
    body = json.loads(path.read_text(encoding="utf-8"))
    return {lineage["lineage_id"] for lineage in body["lineages"]}


def spent_lineages(
    *,
    receipts: Path | None = None,
    artifacts: Path | None = None,
    root: Path | None = None,
) -> frozenset[str]:
    """Every lineage a predecessor study already executed against.

    Three independent derivations, unioned, because each is incomplete alone:

    * a receipt that considered its whole frame spends that whole frame, and the
      receipt states both numbers, so the claim is checkable arithmetic rather
      than an assumption about how the driver loops;
    * ``sfh1_pairs.json`` names the lineages whose per-lineage outcomes were
      *published*, which is spent under any reading of held-out;
    * the VBC2 cohort names the three lineages whose canonical documents were
      built by the VBC2 preflight.

    A receipt naming a frame file that is not on disk raises rather than being
    skipped: a spent set that quietly shrinks re-admits spent lineages.
    """
    receipts = receipts if receipts is not None else NS / "receipts"
    artifacts = artifacts if artifacts is not None else NS / "artifacts" / "development"
    root = root if root is not None else ROOT

    spent: set[str] = set(FORENSIC_LINEAGES)

    for receipt_path in sorted(receipts.glob("sfh1-source-faithfulness--*.json")):
        body = json.loads(receipt_path.read_text(encoding="utf-8"))
        block = body.get("frame") or {}
        spent.update(block.get("spent_excluded") or ())
        source = block.get("source")
        candidates = block.get("candidates")
        considered = body.get("lineages_considered")
        if not source or candidates is None or considered is None:
            continue
        if considered < candidates:
            #: A partial walk. The receipt does not say *which* prefix it
            #: covered, so nothing can be admitted from this frame on its
            #: evidence; the full-walk receipt below is what spends it.
            continue
        listing = _resolve(source, root)
        if not listing.exists():
            raise FileNotFoundError(
                f"{receipt_path.name} names frame {source!r}, which is not on disk. "
                "The spent set cannot be derived without it."
            )
        spent.update(_lineage_ids(listing))

    pairs = artifacts / "sfh1" / "sfh1_pairs.json"
    if pairs.exists():
        spent.update(
            row["lineage_id"]
            for row in json.loads(pairs.read_text(encoding="utf-8"))
            if row.get("lineage_id")
        )

    cohorts = artifacts / "vbc2_cohorts"
    if cohorts.exists():
        for cohort in sorted(cohorts.glob("vbc2_cohort.*.json")):
            if ".partial." in cohort.name:
                continue
            body = json.loads(cohort.read_text(encoding="utf-8"))
            spent.update(
                document["lineage_id"]
                for document in body.get("documents", ())
                if document.get("lineage_id")
            )

    return frozenset(spent)


# ---------------------------------------------------------------------------
# sampling constants
#
# Literals. Every one of them. See the module docstring and the AST test.


#: Per-family admission ceilings. Carried forward unchanged from
#: SOURCE_FAITHFULNESS_HELDOUT_V1, whose basis was grammar breadth: three
#: distinct scanners are exercised — markdown, MediaWiki-rendered HTML and eCFR
#: XML — and the shares reflect how much of each grammar a frame of this size
#: can supply, not how much of it passes anything. A family that yields zero is
#: reported as zero and its quota is never redistributed into a family that
#: yields more.
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
            "grammar breadth and frame supply, carried forward from "
            "SOURCE_FAITHFULNESS_HELDOUT_V1"
        ),
        "explicitly_not_basis": (
            "pass yield, classification outcome or gate result, in SFH1 or in SFI1"
        ),
        "frozen_before": "any SFI1 acquisition, any SFI1 classification, any SFI1 score",
        "redistribution": (
            "forbidden; an under-delivering family is reported short, never topped up "
            "from another"
        ),
        "carried_from": "acquisition/sources_sfh1.py FAMILY_QUOTA",
    }
)

#: sec_edgar is NOT in this frame, and its absence is declared rather than
#: silent. Every SEC issuer VBC2 declared is exhausted at the lineage level —
#: each of the sixteen produced exactly eight filing-series lineages and SFH1
#: walked all 128 — so a fresh SEC cohort needs new issuers, and an issuer is
#: addressed by a ten-digit CIK. This lane cannot verify a CIK without the
#: network and will not invent one to fill a slot.
#:
#: The cost is stated so nobody has to rediscover it: SEC HTML was the only
#: long-form filing grammar in the predecessor frame, so SFI1 does not exercise
#: it. The orchestrator may add verified issuers before the protocol freeze; it
#: may not add them after, and it may not move the three quotas above to
#: compensate.
UNEXERCISED_FAMILIES: Mapping[str, str] = MappingProxyType(
    {
        "sec_edgar": (
            "no fresh issuer available without fabricating a CIK; long-form filing "
            "grammar is not exercised by SFI1"
        )
    }
)

#: Inherited from VALUE_BEARING_COHORT_V2 through SFH1, unchanged, and for the
#: reasons those protocols declared: API availability, compute, reproducibility.
#: STOP-V2-005 forbids refitting them to an observed result.
HISTORY: Mapping[str, Any] = MappingProxyType(
    {
        "horizon_days": 1460,
        "acquisition_cutoff": "2026-08-23T00:00:00Z",
        "max_revisions_inspected_per_lineage": 12,
        "walk_order": "newest first, stopping at the first adjacent pair whose raw bytes differ",
        "basis": "API availability, compute and reproducibility",
        "explicitly_not_basis": "observed extraction outcome",
        "inherited_from": "VALUE_BEARING_COHORT_V2 via SOURCE_FAITHFULNESS_HELDOUT_V1",
    }
)

#: A revision larger than this is not extracted from, and is reported under
#: PAYLOAD_TOO_LARGE_TO_CLASSIFY rather than dropped.
#:
#: The basis is the *source payload distribution*, which is a property of these
#: four grammars and not of any instrument, so it survives the instrument change
#: from the span scanner to the SOURCE_FACT_IR extractors. SFH1 published it:
#: sizes are bimodal, the 95th percentile is 0.49 MB and the next populated band
#: starts above 3 MB, so every cap between 1 MB and 3 MB excludes the same
#: revisions. In SFH1 that was 44 lineages of 2,268 considered — 1.94% of the
#: frame — recorded as `rejected_by_code.PAYLOAD_TOO_LARGE_TO_CLASSIFY` in
#: receipts/sfh1-source-faithfulness--20260823T031017Z-329258f9ec8a.json.
#:
#: A bound that cannot be moved usefully across a 3x range is a bound that was
#: not tuned, and the range is published with it so a reader can check that.
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
#: selection by yield.
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
# Disjoint from VBC2's declared roots and from P4i's, by construction. The
# freeze step checks it again against the expanded lineages, because a root that
# happens to contain a spent lineage is not caught by a root-level check.


#: Documentation trees carrying labelled structure, none of which appears in
#: VBC2's GIT_ROOTS or P4i's GIT_REPOSITORIES_ALL.
GIT_ROOTS: tuple[dict[str, str], ...] = (
    {"owner": "django", "repo": "django", "prefix": "docs/", "license": "BSD-3-Clause"},
    {"owner": "rails", "repo": "rails", "prefix": "guides/source/", "license": "MIT"},
    {"owner": "symfony", "repo": "symfony-docs", "prefix": "components/",
     "license": "CC-BY-SA-3.0"},
    {"owner": "laravel", "repo": "docs", "prefix": "", "license": "MIT"},
    {"owner": "spring-projects", "repo": "spring-boot",
     "prefix": "spring-boot-project/spring-boot-docs/", "license": "Apache-2.0"},
    {"owner": "ansible", "repo": "ansible-documentation", "prefix": "docs/docsite/rst/",
     "license": "GPL-3.0"},
    {"owner": "puppetlabs", "repo": "puppet", "prefix": "documentation/", "license": "Apache-2.0"},
    {"owner": "saltstack", "repo": "salt", "prefix": "doc/topics/", "license": "Apache-2.0"},
    {"owner": "openstack", "repo": "nova", "prefix": "doc/source/", "license": "Apache-2.0"},
    {"owner": "ceph", "repo": "ceph", "prefix": "doc/", "license": "LGPL-2.1"},
    {"owner": "redis", "repo": "redis-doc", "prefix": "docs/", "license": "CC-BY-SA-4.0"},
    {"owner": "mongodb", "repo": "docs", "prefix": "source/", "license": "CC-BY-NC-SA-3.0"},
    {"owner": "influxdata", "repo": "docs-v2", "prefix": "content/", "license": "MIT"},
    {"owner": "timescale", "repo": "docs", "prefix": "use-timescale/", "license": "Apache-2.0"},
    {"owner": "cilium", "repo": "cilium", "prefix": "Documentation/", "license": "Apache-2.0"},
    {"owner": "containerd", "repo": "containerd", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "containers", "repo": "podman", "prefix": "docs/source/", "license": "Apache-2.0"},
    {"owner": "moby", "repo": "moby", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "buildpacks", "repo": "docs", "prefix": "content/docs/", "license": "Apache-2.0"},
    {"owner": "argoproj", "repo": "argo-cd", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "fluxcd", "repo": "website", "prefix": "content/en/", "license": "Apache-2.0"},
    {"owner": "tektoncd", "repo": "pipeline", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "vitessio", "repo": "website", "prefix": "content/en/docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "spark", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "airflow", "prefix": "docs/", "license": "Apache-2.0"},
    {"owner": "apache", "repo": "beam", "prefix": "website/www/site/content/en/",
     "license": "Apache-2.0"},
    {"owner": "scikit-learn", "repo": "scikit-learn", "prefix": "doc/", "license": "BSD-3-Clause"},
    {"owner": "numpy", "repo": "numpy", "prefix": "doc/source/", "license": "BSD-3-Clause"},
    {"owner": "pandas-dev", "repo": "pandas", "prefix": "doc/source/", "license": "BSD-3-Clause"},
    {"owner": "pytorch", "repo": "pytorch", "prefix": "docs/source/", "license": "BSD-3-Clause"},
    {"owner": "huggingface", "repo": "transformers", "prefix": "docs/source/en/",
     "license": "Apache-2.0"},
    {"owner": "matplotlib", "repo": "matplotlib", "prefix": "doc/users/", "license": "PSF-2.0"},
    {"owner": "jupyter", "repo": "notebook", "prefix": "docs/source/", "license": "BSD-3-Clause"},
    {"owner": "gohugoio", "repo": "hugoDocs", "prefix": "content/en/", "license": "Apache-2.0"},
    {"owner": "sveltejs", "repo": "svelte", "prefix": "documentation/", "license": "MIT"},
    {"owner": "nushell", "repo": "nushell.github.io", "prefix": "book/", "license": "MIT"},
)

#: CFR parts carrying labelled quantities. Disjoint from VBC2's ECFR_ROOTS and
#: from P4i's ECFR_PARTS_ALL.
ECFR_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("7", "273", "Certification of eligible households"),
    ("9", "318", "Entry into official establishments; reinspection and preparation of products"),
    ("9", "381", "Poultry products inspection regulations"),
    ("10", "71", "Physical protection of plants and materials"),
    ("12", "204", "Reserve requirements of depository institutions"),
    ("12", "225", "Bank holding companies and change in bank control"),
    ("13", "121", "Small business size regulations"),
    ("14", "23", "Airworthiness standards: normal category airplanes"),
    ("14", "36", "Noise standards: aircraft type and airworthiness certification"),
    ("15", "774", "The commerce control list"),
    ("16", "305", "Energy and water use labeling for consumer products"),
    ("17", "1", "General regulations under the Commodity Exchange Act"),
    ("20", "404", "Federal old-age, survivors and disability insurance"),
    ("21", "172", "Food additives permitted for direct addition to food"),
    ("21", "606", "Current good manufacturing practice for blood and blood components"),
    ("22", "62", "Exchange visitor program"),
    ("24", "5", "General HUD program requirements; waivers"),
    ("26", "301", "Procedure and administration"),
    ("27", "24", "Wine"),
    ("29", "1915", "Occupational safety and health standards for shipyard employment"),
    ("30", "56", "Safety and health standards, surface metal and nonmetal mines"),
    ("31", "1010", "General provisions, financial recordkeeping and reporting"),
    ("33", "117", "Drawbridge operation regulations"),
    ("34", "668", "Student assistance general provisions"),
    ("38", "3", "Adjudication; pension, compensation, dependency"),
    ("40", "86", "Control of emissions from new and in-use highway vehicles"),
    ("40", "98", "Mandatory greenhouse gas reporting"),
    ("40", "112", "Oil pollution prevention"),
    ("41", "60", "Office of federal contract compliance programs"),
    ("42", "412", "Prospective payment systems for inpatient hospital services"),
    ("42", "493", "Laboratory requirements"),
    ("43", "3809", "Surface management, mining claims under the general mining law"),
    ("45", "46", "Protection of human subjects"),
    ("46", "108", "Fire protection equipment"),
    ("47", "25", "Satellite communications"),
    ("48", "52", "Solicitation provisions and contract clauses"),
    ("49", "173", "Shippers, general requirements for shipments and packagings"),
    ("49", "393", "Parts and accessories necessary for safe operation"),
    ("50", "679", "Fisheries of the exclusive economic zone off Alaska"),
)

#: Categories expanded into article lineages before any history is read.
#: Disjoint from VBC2's ten. Ticino is deliberately absent: two of the four
#: forensic cases are Ticino municipalities, and excluding those two articles
#: while admitting their neighbours would leave the diagnosis adjacent to the
#: certification.
WIKIPEDIA_CATEGORY_ROOTS: tuple[str, ...] = (
    "Category:Municipalities of the Province of Bolzano",
    "Category:Cities in Saxony",
    "Category:Communes of Haute-Savoie",
    "Category:Municipalities of the Province of Pontevedra",
    "Category:Cities and towns in Kyoto Prefecture",
    "Category:Municipalities of the canton of Grisons",
    "Category:Cities in South Australia",
    "Category:Municipalities of Slovenia",
    "Category:Cities and towns in Latvia",
    "Category:Populated places in Cyprus",
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
            f"{listing} does not exist. The SFI1 lineage expansion has not been sealed; "
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
