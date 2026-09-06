#!/usr/bin/env python3
"""Exercise the whole post-fetch half of acquire() offline, before spending network.

No W6 acquisition run has ever executed past the first eligible page. Both the v5
and the v6 runs raised at the same expression on page 0, so everything after that
line -- the cohort accounting, the availability rule, the record construction, the
metadata.json write, the final receipt and the wrapper's completion sidecar -- has
never run at all. Relaunching against the live API would spend hours of heavily
rate-limited fetching only to discover a second latent defect, if one exists.

This runs the real `acquire()` from the sealed script with `revision_batch`
replaced by a deterministic synthetic source, so the entire post-fetch path
executes in seconds with no network. It is a positive control for the harness,
not evidence about Wikipedia: nothing here says anything about the corpus, the
cutoffs, or the endpoint.

What a pass means:  the code path completes and writes both receipts.
What a pass does not mean:  that the live fetch will succeed, that the real
corpus will reach the availability thresholds, or that the endpoint will run.

The sealed script is imported unmodified -- its own hash self-checks must pass for
this to run at all, which is itself part of the test.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
sys.path.insert(0, str(HERE))

SCRATCH = Path(
    "C:/Users/yspow/AppData/Local/Temp/claude/D--CodexProjects-ai-knowledge-compiler"
    "/c0da6064-96ac-4c7f-b6e2-06f1c2a55833/scratchpad"
)

# The synthetic corpus must live under EXP, because the expression under test is
# `path.relative_to(EXP)`. A scratch-directory corpus would fail for the very
# reason this dry run exists to rule out, and would prove nothing.
DRY_CORPUS = EXP / "corpus-dryrun-synthetic"

BEFORE_TS = "2023-06-01T00:00:00Z"
AFTER_TS = "2026-06-01T00:00:00Z"
ELIGIBLE_EVERY = 25


def page_text(title: str, revision: str) -> str:
    """Synthetic wikitext with an infobox the real parser accepts.

    Three attributes move between revisions and two hold still, so both the
    primary-attribute path and the unchanged-control path are exercised.
    """
    moved = "first" if revision == "before" else "second"
    return (
        f"'''{title}''' is a synthetic fixture.\n"
        "{{Infobox test\n"
        f"| population = {1000 if revision == 'before' else 2000}\n"
        f"| leader = {moved} holder\n"
        f"| area = {50 if revision == 'before' else 75} km2\n"
        "| founded = 1801\n"
        "| country = Testland\n"
        "}}\n\n"
        f"Body text for the {revision} revision of {title}.\n"
    )


def synthetic_revision_batch(titles: list[str], cutoff: str) -> dict[str, Any]:
    """Stand in for the live MediaWiki query.

    Eligibility is keyed off a stable hash of the title rather than off position,
    so the choice of which titles resolve does not depend on cohort slicing.
    """
    revision = "before" if cutoff.startswith("2023") else "after"
    timestamp = BEFORE_TS if revision == "before" else AFTER_TS
    out: dict[str, Any] = {}
    for title in titles:
        if sum(title.encode("utf-8")) % ELIGIBLE_EVERY:
            out[title] = None
            continue
        out[title] = {
            "resolved_title": title,
            "revision_id": abs(hash(title)) % 10**9,
            "timestamp": timestamp,
            "mw_sha1": None,
            "content": page_text(title, revision),
        }
    return out


def load_sealed_v3():
    spec = importlib.util.spec_from_file_location(
        "acquire_w6_v3_dryrun", HERE / "acquire_w6_v3.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if DRY_CORPUS.exists():
        shutil.rmtree(DRY_CORPUS)

    v3 = load_sealed_v3()
    v3.revision_batch = synthetic_revision_batch

    manifest = EXP / "receipts" / "title-manifest-v3-2026-08-19.json"
    output = SCRATCH / "dryrun-acquisition-receipt.json"
    output.parent.mkdir(parents=True, exist_ok=True)

    started = datetime.now(UTC)
    error: str | None = None
    try:
        rc = v3.acquire(manifest, DRY_CORPUS, output)
    except BaseException as exc:  # catching everything is the point of a control run
        rc, error = None, f"{type(exc).__name__}: {exc}"

    receipt_written = output.exists()
    acq: dict[str, Any] = {}
    if receipt_written:
        acq = json.loads(output.read_text(encoding="utf-8"))

    dirs = sorted(p for p in DRY_CORPUS.iterdir()) if DRY_CORPUS.exists() else []
    complete = [d for d in dirs if (d / "metadata.json").exists()]
    incomplete = [d for d in dirs if not (d / "metadata.json").exists()]

    passed = (
        error is None
        and receipt_written
        and bool(complete)
        and not incomplete
        and acq.get("eligible_records", 0) == len(complete)
    )

    result: dict[str, Any] = {
        "schema": "tavonel.w6-acquisition-postfetch-dryrun.v1",
        "experiment": "H1-W6-SAME-INTELLIGENCE-01",
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": (
            "Execute the post-fetch half of the sealed acquire() offline. No W6 run has "
            "ever passed the first eligible page, so this path was entirely untested."
        ),
        "method": (
            "Import the sealed acquire_w6_v3.py unmodified -- its internal protocol and "
            "script hash self-checks must pass -- then replace only revision_batch with a "
            "deterministic synthetic source and run acquire() against the real frozen "
            "manifest with an ABSOLUTE corpus path."
        ),
        "sealed_script_sha256": v3.file_sha256(HERE / "acquire_w6_v3.py"),
        "sealed_script_modified": False,
        "elapsed_seconds": round((datetime.now(UTC) - started).total_seconds(), 3),
        "return_code": rc,
        "exception": error,
        "acquisition_receipt_written": receipt_written,
        "pair_directories": len(dirs),
        "complete_pairs": len(complete),
        "incomplete_pairs": len(incomplete),
        "eligible_records": acq.get("eligible_records"),
        "excluded_records": acq.get("excluded_records"),
        "cohorts_completed": acq.get("cohorts_completed"),
        "availability_reached": acq.get("availability_reached"),
        "primary_endpoint_status": acq.get("primary_endpoint_status"),
        "sample_relative_path": (
            acq.get("records", [{}])[0].get("relative_before_path") if acq.get("records") else None
        ),
        "result": "POSTFETCH_PATH_EXECUTES" if passed else "POSTFETCH_PATH_DEFECTIVE",
        "scope_limitation": (
            "This is a harness control, not evidence about Wikipedia. It says the code path "
            "completes; it says nothing about whether the live corpus reaches the "
            "availability thresholds, and nothing about the endpoint. The synthetic pages "
            "were built to satisfy the thresholds, so availability_reached here is a "
            "property of the fixture and must never be cited as a corpus result."
        ),
        "synthetic_corpus_removed_after_run": True,
        "network_access": False,
        "corpus_v5_modified": False,
        "corpus_v6_modified": False,
        "external_gpu_cost_usd": 0.0,
    }
    result["receipt_sha256"] = "sha256:" + v3.canonical_sha256(result).removeprefix("sha256:")

    out = EXP / "receipts" / "acquisition-postfetch-dryrun-2026-08-19.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if DRY_CORPUS.exists():
        shutil.rmtree(DRY_CORPUS)

    print(f"result:               {result['result']}")
    print(f"  return code:        {rc}")
    print(f"  exception:          {error}")
    print(f"  complete pairs:     {len(complete)}")
    print(f"  incomplete pairs:   {len(incomplete)}")
    print(f"  eligible/excluded:  {acq.get('eligible_records')}/{acq.get('excluded_records')}")
    print(f"  availability:       {acq.get('availability_reached')}")
    print(f"  sample rel path:    {result['sample_relative_path']}")
    print(f"wrote {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
