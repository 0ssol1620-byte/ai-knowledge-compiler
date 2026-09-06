#!/usr/bin/env python3
"""Recover SFI3's unavailable declared roots, found by the availability-only
`tools/preflight_sfi3_roots.py` run pinned in `SOURCE_PREFLIGHT_RECEIPT`
below — 12 of 32 `git_docs`, 1 of 36 `regulation_ecfr`, 1 of 10
`encyclopedia_wikipedia` — using ONLY a pre-declared, deterministic,
availability-and-identity criterion, frozen with its own immutable receipt
before a single replacement candidate is ever checked.

Founder framing, repeated here because it is the one rule this module must not
get wrong: **a criterion chosen after seeing which candidates pass is not a
criterion, it is a selection.** So this module runs in a fixed order it cannot
deviate from at call time:

    1. `build_policy()`  — reads only the pinned, already-immutable source
       preflight receipt (no network, no candidate). Computes the frozen
       criterion: the deterministic ordering rule, the bounded transient-retry
       policy, the disjointness rule, and the literal candidate pools —
       exactly the same shape of literal declaration `sources_sfi3.py` uses
       for its own roots, for the same reason: a pool that can be edited after
       seeing a failure is not a pool.
    2. `freeze_policy()` — writes that dict through `evidence.write_immutable`
       as its own receipt (`sfi3-root-replacement-policy`), before step 3 ever
       runs. `main()` calls these in that order and nothing in between reaches
       the network; `tests/test_sfi3_root_replacement.py` asserts this from
       the outside by making a network call raise during the freeze and
       checking it never fires.
    3. `run_replacement()` — retries every already-declared root the pinned
       receipt found `UNREACHABLE` (transient/TLS failures only — see
       `RETRY_POLICY`), then walks each family's candidate pool in the frozen
       deterministic order, checking availability only, accepting the first N
       that qualify where N is the shortfall the pinned receipt (plus any
       retry recovery) leaves. Availability is checked with
       `preflight_sfi3_roots.check_git_root` / `check_ecfr_root` /
       `check_wikipedia_root`, imported and reused unmodified — this module
       adds no new network transport and does not weaken the three structural
       guards those functions already carry (URL whitelist, size cap,
       field-whitelist extraction). See that module's own docstring.

Same scope discipline as the preflight this recovers from: identity and
reachability only. This module opens no revision, estimates no yield, and
chooses no candidate by anything but the frozen criterion above. It does not
touch `tools/freeze_sfi3_lineages.py`, does not freeze the SFI3 frame, and
does not write to `acquisition/sources_sfi3.py` — updating the declared root
lists there, once this module's receipt names which candidates were accepted,
is a separate, manual step, exactly as `sources_sfi3.py`'s own literal-root
declarations always have been.

After `sources_sfi3.py` is updated, re-running the unmodified
`preflight_sfi3_roots.py` over the new declared set is what produces the
receipt the orchestrator's freeze gate actually reads (stem
`sfi3-root-preflight`, keys `valid_root_count_per_family` /
`zero_valid_families` — see that module's `ROOT_PREFLIGHT_STEM` and
`freeze_sfi3_protocol.py`'s `_root_availability_preflight`). This module's own
two receipts (`sfi3-root-replacement-policy`, `sfi3-root-replacement`) are a
different, additional record: the frozen criterion and how each replacement
candidate fared under it. They are not a substitute for that final compatible
preflight receipt, and this module does not write one under that stem itself
— reusing the real tool for the real final check, rather than reimplementing
its aggregation a second time, is the whole point of importing it unmodified.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
for _sub in ("acquisition", "tools"):
    if str(NS / _sub) not in sys.path:
        sys.path.insert(0, str(NS / _sub))

import preflight_sfi3_roots as pre  # noqa: E402
import sources_p4i as p4i  # noqa: E402
import sources_sfi1 as sfi1  # noqa: E402
import sources_sfi2 as sfi2  # noqa: E402
import sources_sfi3 as sfi3  # noqa: E402
import sources_vbc2 as vbc2  # noqa: E402
from common import canonical_sha, now, rel  # noqa: E402
from evidence import write_immutable  # noqa: E402

SCHEMA_POLICY = "tavonel.v2.sfi3_root_replacement_policy.v1"
SCHEMA_RESULT = "tavonel.v2.sfi3_root_replacement.v1"

#: The one availability-only preflight run this recovery is based on. Pinned
#: to the exact filename rather than `receipts/latest/sfi3-root-preflight.json`
#: (a mutable convenience pointer) so a later, unrelated preflight run cannot
#: silently change what this module recovers from. `_load_source_preflight`
#: recomputes the receipt's own self-hash and refuses to proceed if either
#: hash below no longer matches the file on disk.
SOURCE_PREFLIGHT_RECEIPT = (
    NS / "receipts" / "sfi3-root-preflight--20260823T113621Z-39cd4b2447f9.json"
)
SOURCE_PREFLIGHT_RECEIPT_SHA256 = (
    "sha256:9566911edebe7ff01e271442bc85db9ab910464291ca64d1fe6fcb1d064a138f"
)

# ---------------------------------------------------------------------------
# the frozen criterion — literal, declared, checked before any candidate
# ---------------------------------------------------------------------------

#: A fixed, predeclared bounded retry for transient/TLS failures, applied
#: identically to an already-declared root the source receipt found
#: `UNREACHABLE` and to any replacement candidate this module itself finds
#: `UNREACHABLE`. Never applied to `NOT_FOUND`, `INVALID_IDENTIFIER` or
#: `UNEXPECTED_HOST` — those are not transient, and retrying them would not be
#: "bounded retry of a transient failure", it would be re-asking a question
#: that already has an answer.
RETRY_POLICY: dict[str, Any] = MappingProxyType(
    {
        "max_attempts": 4,
        "backoff_seconds": (1.0, 2.0, 4.0),
        "applies_to_state": pre.STATE_UNREACHABLE,
        "basis": (
            "declared here, before any transient failure is observed by this run; "
            "trinodb/trino's TLS handshake timeout is the known case this exists for, "
            "but the policy is applied uniformly to every UNREACHABLE outcome this run "
            "produces, not special-cased to that one root"
        ),
    }
)

#: Salt for the candidate consumption order. Distinct from every SFI-family
#: order salt (`sources_sfi1.ORDER_SALT`, `sources_sfi2.ORDER_SALT`,
#: `sources_sfi3.ORDER_SALT`) because this orders *root candidates*, not
#: lineages, and reusing a salt across the two would not be a meaningful
#: collision but is avoided anyway so the two sequences are never confusable.
REPLACEMENT_ORDER_SALT = ":sfi3-root-replacement-v1"


def candidate_order_key(candidate_id: str, salt: str = REPLACEMENT_ORDER_SALT) -> str:
    """The frozen candidate consumption order — ascending sha256 of the
    candidate id salted with `REPLACEMENT_ORDER_SALT`. Same construction as
    `sources_sfi3.order_key`, reused as a pattern rather than as code because
    it orders a different namespace (root candidates, not lineages)."""
    import hashlib

    return hashlib.sha256((candidate_id + salt).encode("utf-8")).hexdigest()


#: git_docs replacement candidates. Declared exactly like `sources_sfi3.GIT_ROOTS`
#: — a literal tuple of dicts, chosen for plausible documentation-tree
#: structure (the same basis the original 32 roots were chosen on), never for
#: anything this run has observed. 20 candidates against a shortfall of at
#: most 12 (see `build_policy`) is deliberate headroom: the pool is sized
#: before any candidate is checked, so a pool that turns out to be exactly the
#: shortfall would leave no honest way to report a shortfall if one or two
#: candidates failed availability, without silently reaching for "just one
#: more" after seeing a result.
GIT_CANDIDATE_ROOTS: tuple[dict[str, str], ...] = (
    {"owner": "facebook", "repo": "docusaurus", "prefix": "website/docs/", "license": "MIT"},
    {"owner": "oven-sh", "repo": "bun", "prefix": "docs/", "license": "MIT"},
    {"owner": "facebook", "repo": "react-native-website", "prefix": "docs/", "license": "MIT"},
    {"owner": "apache", "repo": "nifi", "prefix": "nifi-docs/", "license": "Apache-2.0"},
    {"owner": "mattermost", "repo": "docs", "prefix": "source/", "license": "Apache-2.0"},
    {"owner": "mkdocs", "repo": "mkdocs", "prefix": "docs/", "license": "BSD-2-Clause"},
    {"owner": "readthedocs", "repo": "readthedocs.org", "prefix": "docs/user/", "license": "MIT"},
    {"owner": "sphinx-doc", "repo": "sphinx", "prefix": "doc/", "license": "BSD-2-Clause"},
    {"owner": "jekyll", "repo": "jekyll", "prefix": "docs/_docs/", "license": "MIT"},
    {"owner": "squidfunk", "repo": "mkdocs-material", "prefix": "docs/", "license": "MIT"},
    {
        "owner": "testing-library",
        "repo": "testing-library-docs",
        "prefix": "docs/",
        "license": "MIT",
    },
    {"owner": "apache", "repo": "tomcat", "prefix": "webapps/docs/", "license": "Apache-2.0"},
    {
        "owner": "spring-projects",
        "repo": "spring-security",
        "prefix": "docs/modules/ROOT/pages/",
        "license": "Apache-2.0",
    },
    {
        "owner": "micrometer-metrics",
        "repo": "micrometer",
        "prefix": "docs/modules/ROOT/pages/",
        "license": "Apache-2.0",
    },
    {"owner": "junit-team", "repo": "junit5", "prefix": "documentation/", "license": "EPL-2.0"},
    {"owner": "elastic", "repo": "kibana", "prefix": "docs/", "license": "Elastic-2.0"},
    {"owner": "fastify", "repo": "fastify", "prefix": "docs/", "license": "MIT"},
    {"owner": "apache", "repo": "dubbo", "prefix": "docs/en/", "license": "Apache-2.0"},
    {
        "owner": "nginx",
        "repo": "documentation",
        "prefix": "xml/en/docs/",
        "license": "BSD-2-Clause",
    },
    {"owner": "trpc", "repo": "trpc.io", "prefix": "www/docs/", "license": "MIT"},
)

#: regulation_ecfr replacement candidates: (title, part, description).
ECFR_CANDIDATE_ROOTS: tuple[tuple[str, str, str], ...] = (
    ("40", "50", "National primary and secondary ambient air quality standards"),
    ("21", "700", "Cosmetic labeling"),
    ("12", "1", "Organization and functions, availability of information"),
    ("17", "200", "Organization; conduct and ethics; and information and requests"),
    ("5", "1201", "Practices and procedures (Merit Systems Protection Board)"),
    ("34", "106", "Nondiscrimination on the basis of sex in education programs"),
)

#: encyclopedia_wikipedia replacement candidates.
WIKIPEDIA_CANDIDATE_ROOTS: tuple[str, ...] = (
    "Category:Municipalities of Sweden",
    "Category:Municipalities of Denmark",
    "Category:Cities and towns in Greece",
    "Category:Municipalities of Austria",
    "Category:Populated places in Serbia",
    "Category:Cities in Hungary",
)

FAMILY_GIT = pre.FAMILY_GIT
FAMILY_ECFR = pre.FAMILY_ECFR
FAMILY_WIKIPEDIA = pre.FAMILY_WIKIPEDIA
FAMILY_QUOTA_FAMILIES: tuple[str, ...] = (FAMILY_GIT, FAMILY_ECFR, FAMILY_WIKIPEDIA)


def _git_key(root: dict[str, str]) -> tuple[str, str]:
    return (root["owner"], root["repo"])


def _ecfr_key(root: tuple[str, str, str]) -> tuple[str, str]:
    return (root[0], root[1])


def already_declared_git() -> set[tuple[str, str]]:
    """Every git (owner, repo) already spoken for — every predecessor study's
    declared roots, plus SFI3's own current declaration (valid or invalid: an
    invalid root being dropped must not be handed back out as a "fresh"
    candidate). Mirrors `tests/test_sfi3_acquisition.py`'s own disjointness
    check exactly, reused as the same four-module comparison rather than
    reinvented."""
    used: set[tuple[str, str]] = set()
    for module in (sfi1, sfi2, vbc2):
        used.update(_git_key(root) for root in module.GIT_ROOTS)
    used.update(_git_key(root) for root in p4i.GIT_REPOSITORIES_ALL)
    used.update(_git_key(root) for root in sfi3.GIT_ROOTS)
    return used


def already_declared_ecfr() -> set[tuple[str, str]]:
    used: set[tuple[str, str]] = set()
    for module in (sfi1, sfi2, vbc2):
        used.update(_ecfr_key(root) for root in module.ECFR_ROOTS)
    used.update(_ecfr_key(root) for root in p4i.ECFR_PARTS_ALL)
    used.update(_ecfr_key(root) for root in sfi3.ECFR_ROOTS)
    return used


def already_declared_wikipedia() -> set[str]:
    used: set[str] = set()
    for module in (sfi1, sfi2, vbc2):
        used.update(module.WIKIPEDIA_CATEGORY_ROOTS)
    used.update(sfi3.WIKIPEDIA_CATEGORY_ROOTS)
    return used


# ---------------------------------------------------------------------------
# step 1 — build_policy(): no network, reads only the pinned source receipt
# ---------------------------------------------------------------------------


def _load_source_preflight() -> dict[str, Any]:
    """Read the one pinned, already-immutable preflight receipt this recovery
    is based on. No network. Verifies the receipt's own self-hash still
    matches its recorded value (the file has not been altered since it was
    written) and matches the hash pinned in this module (the file on disk is
    the exact run this module was written against), and raises rather than
    proceeding on either mismatch."""
    #: `rel()` requires the path to be under ROOT, which holds for the real
    #: pinned receipt but not necessarily for a test double substituted via
    #: monkeypatch; error text uses the plain path so a missing-file or
    #: hash-mismatch test can point `SOURCE_PREFLIGHT_RECEIPT` anywhere.
    display_path = str(SOURCE_PREFLIGHT_RECEIPT)
    if not SOURCE_PREFLIGHT_RECEIPT.exists():
        raise FileNotFoundError(
            f"{display_path} does not exist. This recovery is defined against that "
            "specific availability-only preflight run and cannot proceed without it."
        )
    body = json.loads(SOURCE_PREFLIGHT_RECEIPT.read_text(encoding="utf-8"))
    recorded_hash = body.get("receipt_sha256")
    bare = {key: value for key, value in body.items() if key != "receipt_sha256"}
    recomputed_hash = canonical_sha(bare)
    if recorded_hash != recomputed_hash:
        raise ValueError(
            f"{display_path} carries receipt_sha256={recorded_hash!r} but recomputes to "
            f"{recomputed_hash!r}; the file does not match its own recorded hash and "
            "cannot be trusted as the pinned source receipt."
        )
    if recorded_hash != SOURCE_PREFLIGHT_RECEIPT_SHA256:
        raise ValueError(
            f"{display_path} hashes to {recorded_hash!r}, not the "
            f"{SOURCE_PREFLIGHT_RECEIPT_SHA256!r} pinned in this module. Refusing to treat "
            "an unpinned receipt as the frozen basis for this recovery."
        )
    return body


def build_policy() -> dict[str, Any]:
    """The frozen replacement criterion. Pure: no network call, no random
    choice, no reference to anything but the pinned source receipt (an
    already-immutable prior artifact, not a candidate) and the literal
    declarations above. Calling this twice returns the same dict.
    """
    source = _load_source_preflight()
    invalid_by_family: dict[str, list[dict[str, Any]]] = source["invalid_roots_by_family"]
    declared_totals: dict[str, int] = source["declared_totals"]

    #: Roots the source receipt found invalid, split by whether their state is
    #: the one transient/TLS state this policy retries before treating them as
    #: needing a replacement candidate.
    retry_candidates: dict[str, list[str]] = {family: [] for family in declared_totals}
    replace_candidates: dict[str, list[str]] = {family: [] for family in declared_totals}
    for family, rows in invalid_by_family.items():
        for row in rows:
            bucket = (
                retry_candidates
                if row["state"] == RETRY_POLICY["applies_to_state"]
                else replace_candidates
            )
            bucket.setdefault(family, []).append(row["root_id"])

    policy = {
        "schema": SCHEMA_POLICY,
        "frozen_before_any_network_call": True,
        "source_preflight_receipt": rel(SOURCE_PREFLIGHT_RECEIPT),
        "source_preflight_receipt_sha256": SOURCE_PREFLIGHT_RECEIPT_SHA256,
        "declared_totals": declared_totals,
        "roots_eligible_for_retry": retry_candidates,
        "roots_needing_a_replacement_candidate": replace_candidates,
        "permitted_properties": (
            "repository exists",
            "path prefix exists on the default branch",
            "host/family matches",
            "identifier syntactically valid",
            "disjoint from every spent lineage (every predecessor study's declared roots, "
            "SFI3's own current declaration, and every candidate already accepted earlier "
            "in this run)",
        ),
        "forbidden_properties": (
            "reading revision content",
            "counting or estimating revisions, changes or yield",
            "looking for qualifying transitions",
            "inspecting any fact or value transition",
            "choosing a root because it looks productive or has good history",
        ),
        "retry_policy": dict(RETRY_POLICY),
        "ordering_rule": (
            f"ascending sha256 of (candidate_id + {REPLACEMENT_ORDER_SALT!r}); candidate_id "
            "is 'owner/repo' for git_docs, 'title-{T}-part-{P}' for regulation_ecfr, and the "
            "literal 'Category:...' string for encyclopedia_wikipedia"
        ),
        "selection_rule": (
            "walk each family's candidate pool in the frozen deterministic order; for each "
            "candidate, reject without a network call if it is not disjoint from every spent "
            "lineage or fails syntactic validation; otherwise check availability (with the "
            "retry policy applied to a transient UNREACHABLE result); accept the first N "
            "that confirm VALID or REDIRECTED, where N is this family's post-retry shortfall; "
            "stop consuming the pool once N is reached. Never choose by content, quality or "
            "expected yield — the source of every acceptance and rejection is this receipt's "
            "own state field, nothing else."
        ),
        "candidate_pools": {
            FAMILY_GIT: [dict(root) for root in GIT_CANDIDATE_ROOTS],
            FAMILY_ECFR: [list(root) for root in ECFR_CANDIDATE_ROOTS],
            FAMILY_WIKIPEDIA: list(WIKIPEDIA_CANDIDATE_ROOTS),
        },
    }
    policy["policy_digest"] = canonical_sha(policy)
    return policy


def freeze_policy(*, no_receipt: bool = False) -> tuple[dict[str, Any], dict[str, str] | None]:
    """Step 2: write the frozen criterion as its own immutable receipt.

    No network call anywhere in this function or in anything it calls
    (`build_policy` is pure). Everything after this point in `main()` may
    touch the network; nothing before it does.
    """
    policy = build_policy()
    if no_receipt:
        return policy, None
    written = write_immutable(
        "sfi3-root-replacement-policy", policy, tool=Path(__file__).resolve(), protocol=None
    )
    return policy, written


# ---------------------------------------------------------------------------
# step 3 — run_replacement(): every network call in this module happens here
# ---------------------------------------------------------------------------


def _check_with_retry(
    check_fn: Callable[[Any], dict[str, Any]], candidate: Any
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Call `check_fn(candidate)` up to `RETRY_POLICY["max_attempts"]` times,
    retrying only while the result's state is `RETRY_POLICY["applies_to_state"]`
    (a transient/TLS failure), sleeping the declared backoff between tries.
    Returns the last outcome and the full attempt log."""
    max_attempts = RETRY_POLICY["max_attempts"]
    backoff = RETRY_POLICY["backoff_seconds"]
    attempts: list[dict[str, Any]] = []
    record: dict[str, Any] = {}
    for attempt_index in range(max_attempts):
        if attempt_index > 0:
            time.sleep(backoff[attempt_index - 1])
        record = check_fn(candidate)
        attempts.append(
            {"attempt": attempt_index + 1, "state": record["state"], "reason": record["reason"]}
        )
        if record["state"] != RETRY_POLICY["applies_to_state"]:
            break
    return record, attempts


#: root_id -> (family, root object) lookup for retrying an already-declared
#: root, built from the module's *current* declared roots (not the source
#: receipt, which never stored the full root object — only whitelisted
#: identity fields).
def _declared_root_lookup() -> dict[str, tuple[str, Any]]:
    lookup: dict[str, tuple[str, Any]] = {}
    for root in sfi3.GIT_ROOTS:
        lookup[f"{root['owner']}/{root['repo']}"] = (FAMILY_GIT, root)
    for root in sfi3.ECFR_ROOTS:
        title, part, _description = root
        lookup[f"title-{title}-part-{part}"] = (FAMILY_ECFR, root)
    for category in sfi3.WIKIPEDIA_CATEGORY_ROOTS:
        lookup[category] = (FAMILY_WIKIPEDIA, category)
    return lookup


_CHECK_FN: dict[str, Callable[[Any], dict[str, Any]]] = {
    FAMILY_GIT: pre.check_git_root,
    FAMILY_ECFR: pre.check_ecfr_root,
    FAMILY_WIKIPEDIA: pre.check_wikipedia_root,
}

_CANDIDATE_ID: dict[str, Callable[[Any], str]] = {
    FAMILY_GIT: lambda root: f"{root['owner']}/{root['repo']}",
    FAMILY_ECFR: lambda root: f"title-{root[0]}-part-{root[1]}",
    FAMILY_WIKIPEDIA: lambda root: root,
}

_CANDIDATE_POOL: dict[str, tuple[Any, ...]] = {
    FAMILY_GIT: GIT_CANDIDATE_ROOTS,
    FAMILY_ECFR: ECFR_CANDIDATE_ROOTS,
    FAMILY_WIKIPEDIA: WIKIPEDIA_CANDIDATE_ROOTS,
}

_ALREADY_DECLARED: dict[str, Callable[[], set[Any]]] = {
    FAMILY_GIT: already_declared_git,
    FAMILY_ECFR: already_declared_ecfr,
    FAMILY_WIKIPEDIA: already_declared_wikipedia,
}

_CANDIDATE_KEY: dict[str, Callable[[Any], Any]] = {
    FAMILY_GIT: _git_key,
    FAMILY_ECFR: _ecfr_key,
    FAMILY_WIKIPEDIA: lambda category: category,
}


def run_replacement(policy: dict[str, Any]) -> dict[str, Any]:
    """Step 3. Every network call this module makes happens in here.

    First retries every already-declared root the policy names as
    retry-eligible; then, for each family, walks its frozen candidate pool in
    frozen order and accepts the first N that confirm, where N is the
    post-retry shortfall.
    """
    started = now()

    retry_outcomes: dict[str, dict[str, Any]] = {}
    recovered_via_retry: dict[str, list[str]] = {family: [] for family in FAMILY_QUOTA_FAMILIES}
    still_needs_replacement: dict[str, list[str]] = {
        family: list(policy["roots_needing_a_replacement_candidate"].get(family, []))
        for family in FAMILY_QUOTA_FAMILIES
    }

    lookup = _declared_root_lookup()
    for family, root_ids in policy["roots_eligible_for_retry"].items():
        for root_id in root_ids:
            if root_id not in lookup:
                #: the pinned receipt named a root the current module no
                #: longer declares at all; nothing to retry against.
                retry_outcomes[root_id] = {
                    "family": family,
                    "attempts": [],
                    "recovered": False,
                    "note": "root_id not found in the current sources_sfi3 declaration",
                }
                still_needs_replacement.setdefault(family, []).append(root_id)
                continue
            found_family, root_obj = lookup[root_id]
            record, attempts = _check_with_retry(_CHECK_FN[found_family], root_obj)
            recovered = record["state"] in pre.CONFIRMED_STATES
            retry_outcomes[root_id] = {
                "family": found_family,
                "attempts": attempts,
                "recovered": recovered,
                "final_state": record["state"],
                "final_reason": record["reason"],
            }
            if recovered:
                recovered_via_retry[found_family].append(root_id)
            else:
                still_needs_replacement.setdefault(found_family, []).append(root_id)

    shortfall = {
        family: len(still_needs_replacement.get(family, [])) for family in FAMILY_QUOTA_FAMILIES
    }

    candidates_considered: list[dict[str, Any]] = []
    accepted: dict[str, list[Any]] = {family: [] for family in FAMILY_QUOTA_FAMILIES}
    accepted_ids: dict[str, list[str]] = {family: [] for family in FAMILY_QUOTA_FAMILIES}

    for family in FAMILY_QUOTA_FAMILIES:
        needed = shortfall[family]
        if needed <= 0:
            continue
        pool = sorted(
            _CANDIDATE_POOL[family],
            key=lambda candidate: candidate_order_key(_CANDIDATE_ID[family](candidate)),
        )
        already_used = _ALREADY_DECLARED[family]()
        for candidate in pool:
            if len(accepted[family]) >= needed:
                break
            candidate_id = _CANDIDATE_ID[family](candidate)
            key = _CANDIDATE_KEY[family](candidate)
            if key in already_used:
                candidates_considered.append(
                    {
                        "family": family,
                        "candidate_id": candidate_id,
                        "state": "REJECTED_NOT_DISJOINT",
                        "reason": (
                            "candidate identity already declared by a predecessor study, by "
                            "SFI3's own current declaration, or by an earlier acceptance in "
                            "this run; rejected before any network call"
                        ),
                        "accepted": False,
                        "attempts": [],
                    }
                )
                continue
            record, attempts = _check_with_retry(_CHECK_FN[family], candidate)
            is_accepted = record["state"] in pre.CONFIRMED_STATES
            candidates_considered.append(
                {
                    "family": family,
                    "candidate_id": candidate_id,
                    "state": record["state"],
                    "reason": record["reason"],
                    "accepted": is_accepted,
                    "attempts": attempts,
                }
            )
            if is_accepted:
                accepted[family].append(candidate)
                accepted_ids[family].append(candidate_id)
                already_used.add(key)

    shortfall_after = {
        family: shortfall[family] - len(accepted[family]) for family in FAMILY_QUOTA_FAMILIES
    }

    valid_root_count_per_family = {
        family: (policy["declared_totals"][family] - shortfall[family] + len(accepted[family]))
        for family in FAMILY_QUOTA_FAMILIES
    }
    zero_valid_families = [
        family for family, count in valid_root_count_per_family.items() if count == 0
    ]

    return {
        "schema": SCHEMA_RESULT,
        "started_at": started,
        "ended_at": now(),
        "scope": "identity and reachability only — no revision content opened, no yield estimated",
        "policy_digest": policy["policy_digest"],
        "declared_totals": policy["declared_totals"],
        "retry_outcomes": retry_outcomes,
        "recovered_via_retry": recovered_via_retry,
        "shortfall_before_replacement": shortfall,
        "candidates_considered": candidates_considered,
        "accepted_replacements": accepted_ids,
        "shortfall_after_replacement": shortfall_after,
        "fully_recovered": all(count == 0 for count in shortfall_after.values()),
        "valid_root_count_per_family": valid_root_count_per_family,
        "zero_valid_families": zero_valid_families,
        "no_revision_content_opened": True,
        "note_on_final_verification": (
            "this receipt is this module's own record of the frozen criterion and how each "
            "candidate fared under it. The receipt the orchestrator's freeze gate reads "
            "(stem sfi3-root-preflight, keys valid_root_count_per_family / "
            "zero_valid_families) is produced by re-running the unmodified "
            "tools/preflight_sfi3_roots.py over sources_sfi3.py's updated declared roots, "
            "after this receipt's accepted_replacements are applied there"
        ),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-receipt",
        action="store_true",
        help="print the run result without writing either immutable receipt",
    )
    args = parser.parse_args(argv)

    policy, policy_written = freeze_policy(no_receipt=args.no_receipt)
    result = run_replacement(policy)

    if args.no_receipt:
        print(json.dumps({"policy": policy, "result": result}, indent=2))
        return 0

    result["policy_receipt"] = policy_written
    result_written = write_immutable(
        "sfi3-root-replacement", result, tool=Path(__file__).resolve(), protocol=None
    )
    summary = {
        **result_written,
        "policy_receipt": policy_written,
        "accepted_replacements": result["accepted_replacements"],
        "recovered_via_retry": result["recovered_via_retry"],
        "shortfall_after_replacement": result["shortfall_after_replacement"],
        "valid_root_count_per_family": result["valid_root_count_per_family"],
        "fully_recovered": result["fully_recovered"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
