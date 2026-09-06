#!/usr/bin/env python3
"""Rung 3 of the Protected Core ladder: does the structural channel help, and what does it cost?

The defect is established (`reproduce_structure_only_stale.py`) and the change
is written. Neither of those is permission to switch it on. `akc_cir.recompilation`
is Protected Core, and the rule is that the legacy path stays authoritative until
a benchmark says the new one is not worse.

So this runs **both arms over the same frozen revisions** -- the legacy planner
and the structural-channel planner -- on the corpora already on disk. No network
call, no refetch, no new revision selection: re-selecting revisions after seeing
a failure would be choosing the data to suit the answer.

Three things are reported, and the third is the one that could sink the change:

  * does `stale_left_behind` reach zero, and does every changed pair become
    equivalent -- the correctness the fix exists for;
  * does the corpus that already passed still pass -- a fix that repairs one
    corpus by breaking another is not a fix;
  * **how much more gets rebuilt.** Structural seeding necessarily widens the
    dirty set. Reporting only the correctness would be advertising the benefit
    and hiding the price, and the price is what makes selective recompilation
    worth claiming at all.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "research" / "experiments" / "H1-B-REAL-REVISION-01"
ADAPTER = EXP / "scripts" / "run_public_real_revision_holdout_v3.py"
sys.path.insert(0, str(ROOT / "packages" / "cir-python" / "src"))

from akc_cir.recompilation import (  # noqa: E402
    plan_recompilation,
    verify_equivalence,
)
from akc_cir.semantic_diff import DiffLevel, diff_documents  # noqa: E402


def canonical_sha256(value: Any) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(body.encode("utf-8")).hexdigest()


def load_adapter() -> Any:
    spec = importlib.util.spec_from_file_location("real_revision_v3_bench", ADAPTER)
    if spec is None or spec.loader is None:
        raise SystemExit("the v3 adapter cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def replay_pair(adapter: Any, corpus: Path, record: dict[str, Any]) -> tuple[Any, Any]:
    """Rebuild the two Revisions from disk, exactly as the run that produced the record saw them.

    The text is verified against the sha256 already in the receipt rather than
    trusted, because a replay that silently scored different bytes than the
    original run would produce a comparison of two different experiments.
    """
    title = record["title"]
    directory = corpus / adapter.slug(title)
    revisions = []
    for side in ("before", "after"):
        revid = record[f"{side}_revision_id"]
        path = directory / f"{revid}.wikitext"
        if not path.is_file():
            raise SystemExit(f"missing frozen revision text: {path}")
        text = path.read_text(encoding="utf-8")
        actual = adapter.sha_text(text)
        expected = record[f"{side}_sha256"]
        if actual != expected:
            raise SystemExit(
                f"{title} {side} revision {revid} does not match the receipt: "
                f"{actual} != {expected}"
            )
        revisions.append(
            adapter.Revision(
                title=title,
                revid=revid,
                parentid=0,
                timestamp=record[f"{side}_timestamp"],
                mw_sha1=record[f"{side}_mw_sha1"],
                text=text,
            )
        )
    return revisions[0], revisions[1]



def discover_pairs(adapter: Any, protocol_path: str, corpus_dir: str) -> list[dict[str, Any]]:
    """Build the pair list from frozen text on disk, for a corpus never scored.

    The titles come from the protocol that was frozen before acquisition, so the
    set cannot be narrowed here; a directory present on disk but absent from the
    protocol would be an acquisition that was never authorised, and a title in
    the protocol with no directory is reported rather than skipped silently.

    Ordering is by revision id, which is monotonic in MediaWiki, so "before" and
    "after" are decided by the data rather than by the reader.
    """
    protocol = json.loads(Path(protocol_path).read_text(encoding="utf-8"))
    titles = protocol.get("titles") or []
    by_slug = {adapter.slug(title): title for title in titles}
    root = Path(corpus_dir)
    records: list[dict[str, Any]] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        title = by_slug.get(directory.name)
        if title is None:
            raise SystemExit(
                f"{directory.name} is on disk but not in the frozen protocol; "
                "scoring it would be scoring data nobody authorised"
            )
        revisions = sorted(int(f.stem) for f in directory.glob("*.wikitext"))
        if len(revisions) != 2:
            raise SystemExit(
                f"{title} has {len(revisions)} revisions on disk, expected 2"
            )
        before, after = revisions
        record: dict[str, Any] = {"title": title}
        for side, revid in (("before", before), ("after", after)):
            text = (directory / f"{revid}.wikitext").read_text(encoding="utf-8")
            record[f"{side}_revision_id"] = revid
            record[f"{side}_sha256"] = adapter.sha_text(text)
            record[f"{side}_timestamp"] = ""
            record[f"{side}_mw_sha1"] = ""
        records.append(record)
    missing = sorted(set(by_slug) - {adapter.slug(r["title"]) for r in records})
    if missing:
        print(f"note: {len(missing)} frozen title(s) were never acquired: {missing}")
    return records

def score(
    adapter: Any,
    before: Any,
    after: Any,
    *,
    structural_channel: bool,
    seed_unresolved_incoming: bool,
) -> dict[str, Any]:
    before_units, before_shape = adapter.section_units(before)
    after_units, after_shape = adapter.section_units(after)
    diff = diff_documents(
        before_sha256=adapter.sha_text(before.text),
        after_sha256=adapter.sha_text(after.text),
        level=DiffLevel.SEMANTIC,
        before_shape=before_shape,
        after_shape=after_shape,
        before_units=before_units,
        after_units=after_units,
        source=f"wikipedia:{before.title}",
    )
    graph, inventory, dependencies = adapter.make_graph_and_inventory(
        before.title, before_units, after_units
    )
    plan = plan_recompilation(
        diff=diff,
        graph=graph,
        artifacts=inventory,
        structural_channel=structural_channel,
        seed_unresolved_incoming=seed_unresolved_incoming,
    )
    before_hashes = adapter.artifact_hashes(dependencies, before_units)
    full_hashes = adapter.artifact_hashes(dependencies, after_units)
    planned = set(plan.to_rebuild)
    equivalence = verify_equivalence(
        full_rebuild=full_hashes,
        selective_rebuild={a: full_hashes[a] for a in inventory if a in planned},
        carried_over={a: before_hashes[a] for a in inventory if a not in planned},
        plan=plan,
    )
    # Precision of the dirty set. An artifact whose full-rebuild bytes equal its
    # previous bytes did not need rebuilding; rebuilding it anyway is invisible
    # in an equivalence check, because the result is identical either way. It is
    # the cost side of the claim and it has to be counted separately or the
    # rebuild fraction reads as if every rebuild were necessary.
    genuinely_changed = {a for a in inventory if before_hashes[a] != full_hashes[a]}
    falsely_invalidated = sorted(planned - genuinely_changed)
    missed = sorted(genuinely_changed - planned)
    return {
        "title": before.title,
        "content_changed": diff.content_changed,
        "artifacts_genuinely_changed": len(genuinely_changed),
        "falsely_invalidated": len(falsely_invalidated),
        "necessarily_rebuilt": len(planned & genuinely_changed),
        "missed_genuinely_changed": len(missed),
        "changed_logical_ids": len(diff.changed_logical_ids),
        "structural_change_present": diff.structural_change_present,
        "change_kinds": sorted({c.kind.value for c in diff.changes}),
        "artifact_count": len(inventory),
        "rebuild_count": len(plan.to_rebuild),
        "rebuild_fraction": len(plan.to_rebuild) / len(inventory) if inventory else 0.0,
        "equivalent": equivalence.equivalent,
        "stale_left_behind": len(equivalence.stale_left_behind),
        "diverged": list(equivalence.diverged),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = [r for r in rows if r["content_changed"]]
    rebuilt = sum(r["rebuild_count"] for r in rows)
    needed = sum(r["artifacts_genuinely_changed"] for r in rows)
    false_invalidations = sum(r["falsely_invalidated"] for r in rows)
    return {
        "pairs": len(rows),
        "changed_pairs": len(changed),
        "artifacts_genuinely_changed": needed,
        "necessarily_rebuilt": sum(r["necessarily_rebuilt"] for r in rows),
        "falsely_invalidated": false_invalidations,
        # Of everything the plan rebuilt, the share that did not need it.
        "false_invalidation_rate_over_rebuilt": (
            false_invalidations / rebuilt if rebuilt else 0.0
        ),
        # Of everything that genuinely changed, the share the plan missed. This
        # is the number the equivalence check already forces to zero, restated
        # so the two error directions sit beside each other.
        "stale_escape_rate": (
            sum(r["missed_genuinely_changed"] for r in rows) / needed if needed else 0.0
        ),
        "all_equivalent": all(r["equivalent"] for r in rows),
        "stale_left_behind_total": sum(r["stale_left_behind"] for r in rows),
        "non_equivalent_titles": sorted(r["title"] for r in rows if not r["equivalent"]),
        "mean_rebuild_fraction_over_changed_pairs": (
            sum(r["rebuild_fraction"] for r in changed) / len(changed) if changed else 0.0
        ),
        "total_artifacts": sum(r["artifact_count"] for r in rows),
        "total_rebuilt": sum(r["rebuild_count"] for r in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        action="append",
        nargs=3,
        metavar=("NAME", "RECEIPT", "CORPUS_DIR"),
        default=[],
        help=(
            "one frozen corpus to replay: a label, the receipt naming its "
            "pairs, and its text directory"
        ),
    )
    parser.add_argument(
        "--disk-corpus",
        action="append",
        nargs=3,
        metavar=("NAME", "PROTOCOL", "CORPUS_DIR"),
        default=[],
        help=(
            "a corpus whose pairs were frozen but never scored, discovered from "
            "disk rather than from a prior receipt. Used for the untouched "
            "holdout: there is no earlier result to replay against, which is "
            "the point of it."
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.corpus and not args.disk_corpus:
        raise SystemExit("at least one --corpus or --disk-corpus is required")

    adapter = load_adapter()
    corpora: dict[str, Any] = {}

    sources: list[tuple[str, str, str, list[dict[str, Any]] | None]] = [
        (name, receipt, directory, None) for name, receipt, directory in args.corpus
    ]
    for name, protocol_path, corpus_dir in args.disk_corpus:
        sources.append(
            (name, protocol_path, corpus_dir, discover_pairs(adapter, protocol_path, corpus_dir))
        )

    for name, receipt_path, corpus_dir, discovered in sources:
        if discovered is None:
            receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
            records = receipt["records"]
        else:
            records = discovered
        # Four arms so each fix is attributable rather than merely bundled. The
        # structural-only arm exists specifically to show whether that channel
        # repairs the failure on its own merits or only by rebuilding enough to
        # cover it -- the difference between a fix and a mask.
        arms = {
            "legacy": dict(structural_channel=False, seed_unresolved_incoming=False),
            "unresolved_incoming_only": dict(
                structural_channel=False, seed_unresolved_incoming=True
            ),
            "structural_only": dict(
                structural_channel=True, seed_unresolved_incoming=False
            ),
            "both": dict(structural_channel=True, seed_unresolved_incoming=True),
        }
        scored: dict[str, list[dict[str, Any]]] = {name: [] for name in arms}
        for record in records:
            before, after = replay_pair(adapter, Path(corpus_dir), record)
            for arm_name, options in arms.items():
                scored[arm_name].append(score(adapter, before, after, **options))

        legacy = scored["legacy"]
        corrected = scored["unresolved_incoming_only"]
        legacy_summary = summarise(legacy)
        corrected_summary = summarise(corrected)

        # A pair whose plan the change did not touch is the majority case, and
        # saying so is part of the cost story: the widening is concentrated.
        widened = [
            {
                "title": lo["title"],
                "rebuild_count_before": lo["rebuild_count"],
                "rebuild_count_after": co["rebuild_count"],
                "artifact_count": lo["artifact_count"],
            }
            for lo, co in zip(legacy, corrected, strict=True)
            if co["rebuild_count"] != lo["rebuild_count"]
        ]
        repaired = [
            lo["title"]
            for lo, co in zip(legacy, corrected, strict=True)
            if not lo["equivalent"] and co["equivalent"]
        ]
        broken = [
            lo["title"]
            for lo, co in zip(legacy, corrected, strict=True)
            if lo["equivalent"] and not co["equivalent"]
        ]

        corpora[name] = {
            "receipt": str(receipt_path),
            "corpus_dir": str(corpus_dir),
            "arms": {arm: summarise(rows) for arm, rows in scored.items()},
            "legacy": legacy_summary,
            "structural_channel": corrected_summary,
            "pairs_repaired": repaired,
            "pairs_broken": broken,
            "pairs_whose_rebuild_set_widened": widened,
            "records_legacy": legacy,
            "records_structural_channel": corrected,
        }

    all_repaired = [t for c in corpora.values() for t in c["pairs_repaired"]]
    all_broken = [t for c in corpora.values() for t in c["pairs_broken"]]
    stale_after = sum(c["structural_channel"]["stale_left_behind_total"] for c in corpora.values())
    equivalent_after = all(c["structural_channel"]["all_equivalent"] for c in corpora.values())

    receipt = {
        "schema": "tavonel.structural-channel-shadow-benchmark.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "what_changed": (
            "plan_recompilation gained an opt-in structural traversal; a structural "
            "change now seeds it with the document's units on the STRUCTURAL "
            "dependency channel. Nothing else moved: no metric, no threshold, no "
            "identity rule, and the default remains the legacy path."
        ),
        "corpora": corpora,
        "acceptance": {
            "C2_stale_left_behind_zero": stale_after == 0,
            "C3_no_pair_broken": all_broken == [],
            "pairs_repaired": all_repaired,
            "pairs_broken": all_broken,
            "all_pairs_equivalent_after": equivalent_after,
        },
        "the_cost": (
            "structural seeding necessarily widens the dirty set. "
            "pairs_whose_rebuild_set_widened and the two mean rebuild fractions "
            "are the price, reported beside the correctness rather than after it."
        ),
        "external_gpu_cost_usd": 0.0,
        "claim_boundary": (
            "Public Wikipedia revision pairs, replayed from frozen local text. "
            "This supports selective/full artifact equivalence on these pairs "
            "under this adapter, not universal domain or production performance."
        ),
    }
    receipt["receipt_sha256"] = canonical_sha256(receipt)

    args.output.resolve().parent.mkdir(parents=True, exist_ok=True)
    args.output.resolve().write_text(
        json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for name, block in corpora.items():
        lo, co = block["legacy"], block["structural_channel"]
        print(f"== {name}: {lo['pairs']} pairs, {lo['changed_pairs']} changed")
        print(f"  {'arm':28}{'equiv':>7}{'stale':>7}{'rebuilt':>9}{'of':>6}")
        for arm, summary in block["arms"].items():
            print(
                f"  {arm:28}{summary['all_equivalent']!s:>7}"
                f"{summary['stale_left_behind_total']:>7}"
                f"{summary['total_rebuilt']:>9}{summary['total_artifacts']:>6}"
            )
        print(f"{'':24}{'legacy':>12}{'structural':>12}")
        for label, key in (
            ("all equivalent", "all_equivalent"),
            ("stale left behind", "stale_left_behind_total"),
            ("total rebuilt", "total_rebuilt"),
            ("total artifacts", "total_artifacts"),
        ):
            print(f"  {label:22}{lo[key]!s:>12}{co[key]!s:>12}")
        print(
            f"  {'mean rebuild frac':22}"
            f"{lo['mean_rebuild_fraction_over_changed_pairs']:>12.4f}"
            f"{co['mean_rebuild_fraction_over_changed_pairs']:>12.4f}"
        )
        if block["pairs_repaired"]:
            print(f"  repaired: {block['pairs_repaired']}")
        if block["pairs_broken"]:
            print(f"  BROKEN:   {block['pairs_broken']}")

    print(f"\nC2 stale_left_behind == 0 : {stale_after == 0}")
    print(f"C3 no pair broken         : {all_broken == []}")
    print(f"receipt: {args.output.resolve()}")

    if all_broken:
        raise SystemExit(
            f"the structural channel broke {len(all_broken)} previously-equivalent "
            "pairs; it must not be recommended for rollout"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
