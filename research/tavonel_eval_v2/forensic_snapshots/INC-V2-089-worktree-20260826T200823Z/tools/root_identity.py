"""One canonical root identity, read from every historical source module.

Founder ruling section 11. V2R2 declared 7 CFR 273 as a fresh eCFR root. It was
neither fresh nor unused: SFI1 had already spent its sections and VBC1 named it
as a declared root. The pre-declaration scan missed it because each sources
module encodes roots in its own shape and the scan matched one of them.

    sources_v2r1/v2r2   GIT_ROOTS   tuple(owner, repo, prefix, branch, license)
    sources_sfi1/2/3,
    vbc2, p4g, p4i      GIT_ROOTS / GIT_REPOSITORIES
                                    dict{owner, repo, prefix, license}
    everywhere          ECFR_ROOTS / ECFR_PARTS  tuple(title, part, subject)
    sfi1/2/3, vbc2, p4i WIKIPEDIA_*  bare strings
    v2r1/v2r2           SEC_ISSUER_RULE  a mapping, not a list

Ad-hoc parsing per enumerator is how a shape gets missed. This module is the
single reader, and every source module is converted to ONE canonical identity
before any disjointness comparison:

    ("ecfr", title, part)
    ("git", owner, repo, prefix)
    ("wikipedia", category_or_article)
    ("sec", rule_fingerprint)

UNVERIFIABLE IS NEVER DISJOINT. A root whose shape this module cannot interpret
is returned as `UNVERIFIABLE` and BLOCKS. Treating an unreadable declaration as
"probably fine" is how 7 CFR 273 got through, and the failure has to land on the
side that stops the study rather than the side that admits the material.

READ-ONLY. Nothing here fetches, and nothing here imports a sources module for
any purpose other than reading its declared roots.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]
ACQUISITION = NS / "acquisition"
for _root in (str(NS), str(ACQUISITION)):
    if _root not in sys.path:
        sys.path.insert(0, _root)

#: Every attribute name any sources module has ever used for a root list, with
#: the family it belongs to. Names rather than heuristics: a heuristic that
#: guessed from the shape would have to guess again for the next shape, and the
#: whole point is that guessing is what failed.
ROOT_ATTRIBUTES: dict[str, str] = {
    "GIT_ROOTS": "git",
    "GIT_REPOSITORIES": "git",
    "GIT_REPOSITORIES_RESERVE": "git",
    "GIT_REPOSITORIES_RESERVE_2": "git",
    "GIT_REPOSITORIES_ALL": "git",
    "ECFR_ROOTS": "ecfr",
    "ECFR_PARTS": "ecfr",
    "ECFR_PARTS_RESERVE": "ecfr",
    "ECFR_PARTS_RESERVE_2": "ecfr",
    "ECFR_PARTS_ALL": "ecfr",
    "WIKIPEDIA_CATEGORY_ROOTS": "wikipedia",
    "WIKIPEDIA_ARTICLES": "wikipedia",
    "WIKIPEDIA_ARTICLES_RESERVE": "wikipedia",
    "WIKIPEDIA_ARTICLES_RESERVE_2": "wikipedia",
    "WIKIPEDIA_ARTICLES_ALL": "wikipedia",
    "SEC_ROOTS": "sec",
    "SEC_ISSUER_RULE": "sec",
}

UNVERIFIABLE = "UNVERIFIABLE"


class RootShapeUnreadable(RuntimeError):
    """A declared root could not be converted to a canonical identity."""


def _git_identity(entry: Any) -> tuple[str, ...] | str:
    if isinstance(entry, dict):
        owner, repo = entry.get("owner"), entry.get("repo")
        prefix = (entry.get("prefix") or "").rstrip("/")
        if owner and repo:
            return ("git", str(owner), str(repo), prefix)
        return UNVERIFIABLE
    if isinstance(entry, (tuple, list)) and len(entry) >= 3:
        owner, repo, prefix = entry[0], entry[1], entry[2]
        if owner and repo:
            return ("git", str(owner), str(repo), str(prefix).rstrip("/"))
        return UNVERIFIABLE
    return UNVERIFIABLE


def _ecfr_identity(entry: Any) -> tuple[str, ...] | str:
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        title, part = entry[0], entry[1]
        if title and part:
            #: Title and part are normalised to strings without leading zeros,
            #: so "07"/"7" and 7/"7" are the same container. A comparison that
            #: treated them as different would report disjointness that is not
            #: there, which is the direction that admits spent material.
            return ("ecfr", str(title).lstrip("0") or "0", str(part))
        return UNVERIFIABLE
    return UNVERIFIABLE


def _wikipedia_identity(entry: Any) -> tuple[str, ...] | str:
    if isinstance(entry, str) and entry.strip():
        return ("wikipedia", entry.strip())
    return UNVERIFIABLE


def _sec_identity(entry: Any) -> tuple[str, ...] | str:
    #: SEC roots are a RULE, not a list, in every module that has them, and two
    #: rules over the same issuer universe are compared by their declared start
    #: and forms rather than by expanding 7,998 CIKs into this file.
    if isinstance(entry, dict) or hasattr(entry, "keys"):
        universe = entry.get("universe")
        start = entry.get("start_after_cik")
        forms = tuple(sorted(entry.get("forms") or ()))
        if universe:
            return ("sec", str(universe), str(start), ",".join(forms))
        return UNVERIFIABLE
    if isinstance(entry, (tuple, list)) and len(entry) >= 1 and entry[0]:
        return ("sec", *(str(x) for x in entry))
    return UNVERIFIABLE


_READERS = {
    "git": _git_identity,
    "ecfr": _ecfr_identity,
    "wikipedia": _wikipedia_identity,
    "sec": _sec_identity,
}


def canonical_identity(family: str, entry: Any) -> tuple[str, ...] | str:
    """One declared root, as a canonical identity, or `UNVERIFIABLE`."""
    reader = _READERS.get(family)
    if reader is None:  # pragma: no cover -- ROOT_ATTRIBUTES only names four
        return UNVERIFIABLE
    return reader(entry)


def read_module_roots(module_name: str) -> dict[str, Any]:
    """Every declared root in one sources module, canonicalised.

    Import failure is reported, never swallowed. A module that cannot be read
    contributes no exclusions, and a study that proceeded on that basis would be
    proving disjointness against a set it never saw.
    """
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        return {
            "module": module_name,
            "importable": False,
            "error": str(error),
            "identities": frozenset(),
            "unverifiable": [f"module import failed: {error}"],
        }

    identities: set[tuple[str, ...]] = set()
    unverifiable: list[str] = []
    attributes_found: list[str] = []

    for attribute, family in ROOT_ATTRIBUTES.items():
        if not hasattr(module, attribute):
            continue
        attributes_found.append(attribute)
        value = getattr(module, attribute)
        entries = [value] if family == "sec" and hasattr(value, "keys") else list(value)
        for entry in entries:
            identity = canonical_identity(family, entry)
            if identity == UNVERIFIABLE:
                unverifiable.append(f"{attribute}: {entry!r}")
            else:
                identities.add(identity)  # type: ignore[arg-type]

    return {
        "module": module_name,
        "importable": True,
        "attributes_read": sorted(attributes_found),
        "identities": frozenset(identities),
        "unverifiable": unverifiable,
    }


def all_source_modules(exclude: frozenset[str] | set[str] = frozenset()) -> list[str]:
    """Every `sources_*.py` in the acquisition directory, sorted."""
    return sorted(
        path.stem for path in ACQUISITION.glob("sources_*.py") if path.stem not in exclude
    )


def prior_root_identities(
    exclude_modules: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """The union of every declared root, and every shape that could not be read.

    `exclude_modules` is for the study's OWN frame -- a frame is not disjoint
    from itself and comparing it to itself would exclude every root it declares.
    """
    modules = all_source_modules(exclude_modules)
    identities: set[tuple[str, ...]] = set()
    unverifiable: list[dict[str, Any]] = []
    per_module: dict[str, Any] = {}

    for name in modules:
        report = read_module_roots(name)
        identities |= report["identities"]
        if report["unverifiable"]:
            unverifiable.append({"module": name, "entries": report["unverifiable"]})
        per_module[name] = {
            "importable": report["importable"],
            "root_count": len(report["identities"]),
            "attributes_read": report.get("attributes_read", []),
            "unverifiable_count": len(report["unverifiable"]),
        }

    by_family: dict[str, int] = {}
    for identity in identities:
        by_family[identity[0]] = by_family.get(identity[0], 0) + 1

    return {
        "modules_read": modules,
        "modules_excluded": sorted(exclude_modules),
        "identities": frozenset(identities),
        "identity_count": len(identities),
        "by_family": dict(sorted(by_family.items())),
        "per_module": per_module,
        "unverifiable": unverifiable,
        "unverifiable_count": sum(len(u["entries"]) for u in unverifiable),
        "unverifiable_policy": (
            "a root whose shape cannot be interpreted BLOCKS. It is never assumed "
            "disjoint: that assumption is what let 7 CFR 273 -- SFI1-spent and a "
            "VBC1 declared root -- into the V2R2 frame."
        ),
    }
