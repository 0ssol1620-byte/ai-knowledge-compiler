#!/usr/bin/env python3
"""W6 v6 post-mortem -- what actually killed the v5 and v6 acquisitions.

The v5 death was recorded as a killed worker. That was an inference from an
ambiguous on-disk signature (one directory, two wikitext files, no metadata.json,
no completion sidecar), and the static resume audit adopted it:

    "This matches the observed v5 death: 1 pair on disk, no completion sidecar."

The v6 run reproduced that signature exactly -- and this time with a traceback.
It was not killed. It raised ValueError at acquire_w6_v3.py:376:

    before_path.relative_to(EXP)

`EXP` is absolute. `before_path` descends from `page_dir(corpus, ...)`, i.e. from
whatever was passed to `--corpus`. Both runs passed a repository-relative corpus
path, so the expression compares a relative path against an absolute root and
raises on the first eligible page -- after both wikitext files are written and
before metadata.json. That is precisely the observed signature.

Two consequences, established here by measurement rather than by argument:

1. The two corpora are byte-identical, so both runs died at the same page for the
   same reason. The killed-worker diagnosis is superseded.
2. The defect is in the INVOCATION, not in the frozen bytes. An absolute
   `--corpus` makes the same expression succeed, so the seal does not have to be
   broken to recover W6.

Point 2 is the one that matters, and it is checked rather than assumed --
asserting a mechanism instead of measuring it is the defect this programme has
now recorded three times (P14, the H1-I wording, P15).

Offline. No network, and no writes into any corpus.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(HERE))

from acquire_w6_v3 import EXP as SCRIPT_EXP  # noqa: E402
from acquire_w6_v3 import page_dir  # noqa: E402


def sha256_file(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def probe(corpus_arg: str) -> dict[str, Any]:
    """Reproduce the crashing expression for one --corpus spelling.

    Uses the real `page_dir` and the real `EXP` imported from the sealed script,
    so this exercises the shipped code path rather than a paraphrase of it. A
    paraphrased harness is what produced the void receipt in the H1-I ordering
    experiment, and that is not repeated here.
    """
    corpus = Path(corpus_arg)
    before_path = page_dir(corpus, 0, "Anarchism") / "before.wikitext"
    try:
        rel = str(before_path.relative_to(SCRIPT_EXP)).replace("\\", "/")
        return {
            "corpus_arg": corpus_arg,
            "is_absolute": corpus.is_absolute(),
            "raises": False,
            "relative_before_path": rel,
        }
    except ValueError as exc:
        return {
            "corpus_arg": corpus_arg,
            "is_absolute": corpus.is_absolute(),
            "raises": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def pair_state(directory: Path) -> dict[str, Any]:
    before, after = directory / "before.wikitext", directory / "after.wikitext"
    return {
        "directory": directory.name,
        "files": sorted(p.name for p in directory.iterdir()) if directory.exists() else [],
        "before_sha256": sha256_file(before) if before.exists() else None,
        "after_sha256": sha256_file(after) if after.exists() else None,
        "metadata_json_present": (directory / "metadata.json").exists(),
    }


def main() -> int:
    rel_arg = "research/experiments/H1-W6-SAME-INTELLIGENCE-01/corpus-v7"
    abs_arg = str(EXP / "corpus-v7")
    probes = [probe(rel_arg), probe(abs_arg)]

    pairs = {
        "corpus_v5": pair_state(EXP / "corpus-v5" / "00000-c29ae214bf37"),
        "corpus_v6": pair_state(EXP / "corpus-v6" / "00000-c29ae214bf37"),
    }
    identical = (
        pairs["corpus_v5"]["before_sha256"] == pairs["corpus_v6"]["before_sha256"]
        and pairs["corpus_v5"]["after_sha256"] == pairs["corpus_v6"]["after_sha256"]
        and pairs["corpus_v5"]["files"] == pairs["corpus_v6"]["files"]
    )

    relative_raises = probes[0]["raises"]
    absolute_succeeds = not probes[1]["raises"]
    invocation_defect = relative_raises and absolute_succeeds

    receipt: dict[str, Any] = {
        "schema": "tavonel.w6-acquisition-failure-diagnosis.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "trigger": "the v6 background acquisition exited 1 after ~5.5 hours of fetching",
        "observed_traceback_site": "scripts/acquire_w6_v3.py:376 before_path.relative_to(EXP)",
        "observed_error_summary": (
            "ValueError: the corpus-v6 before.wikitext path 'is not in the subpath of' the "
            "absolute experiment root, because --corpus was given as a repository-relative "
            "path while EXP is resolved absolute."
        ),
        "invocation_probes": probes,
        "relative_corpus_raises": relative_raises,
        "absolute_corpus_succeeds": absolute_succeeds,
        "defect_location": "INVOCATION" if invocation_defect else "UNDETERMINED",
        "frozen_bytes_change_required": not invocation_defect,
        "corpus_pair_state": pairs,
        "v5_and_v6_first_pair_byte_identical": identical,
        "supersedes": {
            "receipt": "acquisition-resume-audit-2026-08-19.json",
            "sha256": sha256_file(EXP / "receipts" / "acquisition-resume-audit-2026-08-19.json"),
            "field": "checks.checkpointing.evidence",
            "superseded_text": (
                "This matches the observed v5 death: 1 pair on disk, no completion sidecar."
            ),
            "why": (
                "That signature was read as a kill. v6 reproduced it byte-for-byte with a "
                "traceback showing a deterministic ValueError, so the cause was a defect and "
                "not an interruption. The earlier receipt is NOT edited; this one refines it. "
                "Its other eleven checks are static properties of the script and are "
                "unaffected -- including state_after_exception=UNDEFINED, which described "
                "this failure mode correctly while the diagnosis named the wrong cause."
            ),
            "scope": (
                "A single-field retraction, not a wholesale one. The superseded receipt "
                "must still be read for its other findings, and the repository contract "
                "requires it to be cited only alongside this correction."
            ),
        },
        "what_this_does_not_establish": [
            "that the acquisition will complete -- only that it will not fail at this site",
            "that no other latent defect exists later in the cohort loop; no run has ever "
            "executed past the first eligible page write, so everything after it is untested",
            "that the observed HTTP 429 rate limiting is survivable within a single run",
        ],
        "why_the_freeze_survives": (
            "The sealed script is unchanged, so the wrapper's frozen-bytes check still passes "
            "and the manifest's acquisition_script_sha256 pin still holds. The repair is to "
            "pass --corpus as an absolute path. Editing the sealed script would have broken "
            "the seal to fix a defect that does not live in it."
        ),
        "latent_precondition_now_documented": (
            "acquire_w6_v3.acquire() requires an absolute --corpus. It neither resolves nor "
            "validates the path, and the requirement surfaces only as an exception raised "
            "after two files are already on disk. Recorded as a known property of the frozen "
            "script; deliberately not repaired in it."
        ),
        "network_access": False,
        "corpus_v5_modified": False,
        "corpus_v6_modified": False,
        "external_gpu_cost_usd": 0.0,
    }
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()

    out = EXP / "receipts" / "v6-acquisition-failure-diagnosis-2026-08-19.json"
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"defect_location:            {receipt['defect_location']}")
    print(f"relative --corpus raises:   {relative_raises}")
    print(f"absolute --corpus succeeds: {absolute_succeeds}")
    print(f"v5/v6 first pair identical: {identical}")
    print(f"frozen bytes change needed: {receipt['frozen_bytes_change_required']}")
    print(f"wrote {out}")
    return 0 if invocation_defect else 1


if __name__ == "__main__":
    raise SystemExit(main())
