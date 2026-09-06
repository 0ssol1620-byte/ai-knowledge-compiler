#!/usr/bin/env python3
"""Why the four confirmed stale escapes happened. Diagnostic, computed not narrated.

`forensic-stale-escape` established *that* the production selective path carried
a stale artifact in four named cases. This asks *what kind* of source difference
did it, and it answers mechanically: for every artifact the clean full rebuild
moved, the two texts are pushed through a fixed ladder of normalisations and the
first rung at which they become equal names the difference.

    identical                  the texts already agree
    whitespace                 collapsing runs of whitespace makes them agree
    html_entities              unescaping character references makes them agree
    unicode_nfkc               compatibility normalisation makes them agree
    typographic_punctuation    mapping curly quotes and dashes to ASCII does it
    case                       casefolding does it
    alphanumeric               dropping all non-alphanumerics does it
    substantive                nothing on the ladder makes them agree

The ladder is applied cumulatively and in a fixed order declared here, so the
answer is a property of the pair rather than of the analyst. This is a
diagnostic on four named cases: not a rate, not a rescore, and it changes no
gate anywhere.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

NS = Path(__file__).resolve().parents[1]
for _sub in ("tools", "acquisition", "canonicalization", "compiler"):
    sys.path.insert(0, str(NS / _sub))

from canonical_document import canonical_document  # noqa: E402
from common import canonical_sha, now, rel, sha_file  # noqa: E402
from evidence import write_immutable  # noqa: E402
from http_pool import HttpPool, install  # noqa: E402
import selective_build as engine  # noqa: E402

FORENSIC = sorted((NS / "receipts").glob("forensic-stale-escape--*.json"))[-1]
FRAME = NS / "artifacts" / "development" / "vbc2_lineages.json"
USER_AGENT = "tavonel-eval-v2 forensic-root-cause (research; contact via repository)"

_SPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)

#: Curly quotes, dashes and the other characters a source may substitute for an
#: ASCII equivalent without any editorial change.
_TYPOGRAPHIC = {
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "–": "-",
    "—": "-",
    "‒": "-",
    "―": "-",
    "−": "-",
    "…": "...",
    " ": " ",
    " ": " ",
    " ": " ",
    "­": "",
    "​": "",
    "﻿": "",
}


def _typographic(text: str) -> str:
    return "".join(_TYPOGRAPHIC.get(character, character) for character in text)


#: Cumulative and ordered. The first rung at which the two texts agree is the
#: answer, so the order is part of the finding and is declared, not tuned.
LADDER: tuple[tuple[str, Any], ...] = (
    ("identical", lambda text: text),
    ("whitespace", lambda text: _SPACE.sub(" ", text).strip()),
    ("html_entities", lambda text: _SPACE.sub(" ", html.unescape(text)).strip()),
    (
        "unicode_nfkc",
        lambda text: _SPACE.sub(" ", unicodedata.normalize("NFKC", html.unescape(text))).strip(),
    ),
    (
        "typographic_punctuation",
        lambda text: _SPACE.sub(
            " ", _typographic(unicodedata.normalize("NFKC", html.unescape(text)))
        ).strip(),
    ),
    (
        "case",
        lambda text: (
            _SPACE.sub(" ", _typographic(unicodedata.normalize("NFKC", html.unescape(text))))
            .strip()
            .casefold()
        ),
    ),
    (
        "alphanumeric",
        lambda text: _NON_ALNUM.sub(
            "", _typographic(unicodedata.normalize("NFKC", html.unescape(text)))
        ).casefold(),
    ),
)

SUBSTANTIVE = "substantive"


def difference_class(before: str, after: str) -> str:
    for name, rule in LADDER:
        if rule(before) == rule(after):
            return name
    return SUBSTANTIVE


def sample(before: str, after: str, width: int = 90) -> dict[str, str]:
    """The first place the two texts part company, with a little context."""
    limit = min(len(before), len(after))
    cut = next((index for index in range(limit) if before[index] != after[index]), limit)
    low = max(0, cut - 30)
    return {
        "at": cut,
        "before": before[low : low + width],
        "after": after[low : low + width],
    }


def lineages() -> dict[str, dict[str, Any]]:
    return {
        row["lineage_id"]: row for row in json.loads(FRAME.read_text(encoding="utf-8"))["lineages"]
    }


def document(lineage: dict[str, Any], revision: dict[str, str], raw: bytes) -> dict[str, Any]:
    return canonical_document(
        source_family=lineage["family"],
        source_id=lineage["lineage_id"],
        version_id=revision["version"],
        payload=raw,
        source_digest="sha256:" + hashlib.sha256(raw).hexdigest(),
        known_at=revision.get("known_at"),
        valid_from=revision.get("known_at"),
        licence=lineage.get("licence", "unknown"),
    )


def analyse(case: dict[str, Any], lineage: dict[str, Any]) -> dict[str, Any]:
    import run_vbc2_acquire as serial  # noqa: PLC0415

    revisions = {row["version"]: row for row in serial.ENUMERATORS[lineage["family"]](lineage)}
    after = document(
        lineage,
        revisions[case["after_version"]],
        serial._payload(lineage, revisions[case["after_version"]]),
    )
    before = document(
        lineage,
        revisions[case["before_version"]],
        serial._payload(lineage, revisions[case["before_version"]]),
    )

    clean_after = engine.build_all(after)
    clean_before = engine.build_all(before)
    selective = engine.run_pair(before, after)
    carried = set(selective["carried_forward_set"])

    after_text = {
        "section:" + engine.logical_id(after["source_id"], unit["explicit_path"]): unit["text"]
        for unit in after["units"]
    }
    before_text = {
        "section:" + engine.logical_id(before["source_id"], unit["explicit_path"]): unit["text"]
        for unit in before["units"]
    }

    findings: list[dict[str, Any]] = []
    for artifact in sorted(set(clean_after) | set(clean_before)):
        if clean_after.get(artifact) == clean_before.get(artifact):
            continue
        row: dict[str, Any] = {
            "artifact": artifact,
            "kind": artifact.split(":")[0],
            "carried_forward_by_selective": artifact in carried,
        }
        if artifact in after_text and artifact in before_text:
            row["difference_class"] = difference_class(before_text[artifact], after_text[artifact])
            row["first_divergence"] = sample(before_text[artifact], after_text[artifact])
            row["length_before"] = len(before_text[artifact])
            row["length_after"] = len(after_text[artifact])
        else:
            row["difference_class"] = "artifact_membership_or_order"
        findings.append(row)

    stale = [row for row in findings if row["carried_forward_by_selective"]]
    return {
        "lineage_id": case["lineage_id"],
        "family": case["family"],
        "after_version": case["after_version"],
        "before_version": case["before_version"],
        "selective_detected_change_kinds": selective["detected_change_kinds"],
        "selective_structural_change_present": selective["structural_change_present"],
        "selective_rebuilt": len(selective["selective_rebuild_set"]),
        "selective_carried_forward": len(carried),
        "artifacts_moved_by_clean_rebuild": len(findings),
        "artifacts_carried_though_moved": [row["artifact"] for row in stale],
        "difference_classes_of_stale_artifacts": sorted({row["difference_class"] for row in stale}),
        "findings": findings,
    }


def main() -> int:
    started = now()
    clock = time.time()

    import fetch_p4c_corpus as p4c  # noqa: PLC0415
    import fetch_p4g_corpus as p4g  # noqa: PLC0415

    pool = HttpPool()
    install(pool, p4c, p4g, USER_AGENT)

    forensic = json.loads(FORENSIC.read_text(encoding="utf-8"))
    frame = lineages()
    rows = [
        analyse(case, frame[case["lineage_id"]])
        for case in forensic["cases"]
        if case["verdict"] == "CONFIRMED_SELECTIVE_STALE_ESCAPE"
    ]
    for row in rows:
        print(
            "  %-46s stale=%d classes=%s detected=%s"
            % (
                row["lineage_id"][:46],
                len(row["artifacts_carried_though_moved"]),
                row["difference_classes_of_stale_artifacts"],
                row["selective_detected_change_kinds"],
            ),
            flush=True,
        )

    classes: dict[str, int] = {}
    for row in rows:
        for name in row["difference_classes_of_stale_artifacts"]:
            classes[name] = classes.get(name, 0) + 1

    body: dict[str, Any] = {
        "schema": "tavonel.v2.forensic_stale_escape_root_cause.v1",
        "what_this_is": (
            "a diagnostic on the four cases forensic-stale-escape confirmed. It "
            "names the class of source difference that produced each stale "
            "artifact, using a fixed and declared normalisation ladder."
        ),
        "what_this_is_not": [
            "a rate. Four named cases are not a denominator.",
            "a rescore. No gate anywhere is recomputed.",
            "a repair. Nothing is normalised, aligned or fixed by this tool.",
        ],
        "confirms": rel(FORENSIC),
        "confirms_sha256": sha_file(FORENSIC),
        "ladder": [name for name, _ in LADDER] + [SUBSTANTIVE],
        "ladder_is_cumulative_and_ordered": True,
        "started_at": started,
        "ended_at": now(),
        "wall_seconds": round(time.time() - clock, 1),
        "cases": rows,
        "stale_artifact_difference_classes": dict(sorted(classes.items())),
        "reading": (
            "where a stale artifact's difference class is anything other than "
            "'substantive', the semantic diff correctly judged the edit "
            "non-semantic and the artifact fingerprint moved anyway. The two "
            "notions of 'changed' are not aligned, and the selective path is "
            "where the gap shows."
        ),
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
    }
    body["result_digest"] = canonical_sha(
        {
            "classes": body["stale_artifact_difference_classes"],
            "cases": [row["artifacts_carried_though_moved"] for row in rows],
        }
    )

    written = write_immutable(
        "forensic-stale-escape-root-cause",
        body,
        tool=Path(__file__).resolve(),
        protocol=None,
    )
    print(json.dumps({**written, "classes": body["stale_artifact_difference_classes"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
