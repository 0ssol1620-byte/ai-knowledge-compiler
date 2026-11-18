"""Same-condition comparison of the three entity resolvers on one synthetic fixture.

Resolvers measured, each through its real entry point (no re-implementation):
  * ``akc_cir.entity.resolve_mention``   - AUTO_MERGE = merge, REVIEW = abstain
  * ``akc_retrieval.resolve_entities``   - merge / review (abstain) / reject
  * product-core shipped rule            - ``compile_semantics`` on two one-sentence
                                           sources; merge iff an entity id is shared

Synthetic development fixture; not U07 holdout evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from akc_cir import entity as cir_entity
from akc_product_core import semantics as pc_semantics
from akc_retrieval import entity_resolution as retrieval_er

MERGE, SPLIT, ABSTAIN = "merge", "split", "abstain"
REQUIRED = ("pair_id", "stratum", "provenance", "left", "right", "gold")


def load_fixture(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        missing = [key for key in REQUIRED if key not in row]
        if missing:
            raise ValueError(f"{path.name}:{number}: missing {missing}")
        if row["provenance"] != "synthetic":
            raise ValueError(
                f"{path.name}:{number}: row {row['pair_id']} is not provenance=synthetic"
            )
        if row["gold"] not in ("same", "different"):
            raise ValueError(f"{path.name}:{number}: gold must be same|different")
        rows.append(row)
    return rows


def _mention(side: dict[str, Any], mention_id: str) -> Any:
    return cir_entity.EntityMention(
        mention_id=mention_id,
        text=side["text"],
        evidence_id=side["evidence_id"],
        type_candidate=side.get("type", ""),
        attributes=side.get("attributes", {}),
        external_ids=side.get("external_ids", {}),
        context_ids=frozenset(side.get("context_ids", ())),
    )


def cir_adapter(row: dict[str, Any]) -> str:
    decision = cir_entity.resolve_mention(
        _mention(row["left"], "L"),
        [("R", _mention(row["right"], "R"))],
        aliases=row.get("approved_aliases"),
    )
    if decision.verdict is cir_entity.MergeVerdict.AUTO_MERGE:
        return MERGE
    return ABSTAIN if decision.verdict is cir_entity.MergeVerdict.REVIEW else SPLIT


def _record(side: dict[str, Any], entity_id: str) -> Any:
    ids = side.get("external_ids", {})
    attrs = side.get("attributes", {})
    return retrieval_er.EntityRecord(
        entity_id=entity_id,
        name=side["text"],
        registration_id=ids[sorted(ids)[0]] if ids else None,
        jurisdiction=attrs.get("jurisdiction"),
        address=attrs.get("address"),
        authoritative=bool(ids),
    )


def retrieval_adapter(row: dict[str, Any]) -> str:
    decision = retrieval_er.resolve_entities(_record(row["left"], "L"), _record(row["right"], "R"))
    return {"merge": MERGE, "review": ABSTAIN}.get(decision.disposition, SPLIT)


def _entity_ids(side: dict[str, Any], tag: str) -> set[str]:
    source = pc_semantics.SemanticSource(
        logical_id=f"ku-{tag}",
        source_id=f"src-{tag}",
        source_version_id=f"sv-{tag}",
        evidence_id=side["evidence_id"],
        text=f"{side['text']} reported results.",
        authority="informal",
    )
    return {entity.entity_id for entity in pc_semantics.compile_semantics((source,)).entities}


def product_core_adapter(row: dict[str, Any]) -> str:
    return MERGE if _entity_ids(row["left"], "L") & _entity_ids(row["right"], "R") else SPLIT


ADAPTERS: dict[str, Callable[[dict[str, Any]], str]] = {
    "akc_cir.entity": cir_adapter,
    "akc_retrieval.entity_resolution": retrieval_adapter,
    "product_core.label_hash": product_core_adapter,
}


def _cell() -> dict[str, Any]:
    keys = ("n", "merges", "true_merges", "false_merges", "false_splits", "abstentions")
    return dict.fromkeys(keys, 0)


def evaluate(
    rows: list[dict[str, Any]],
    adapters: dict[str, Callable[[dict[str, Any]], str]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, adapter in (adapters or ADAPTERS).items():
        cells: dict[str, dict[str, Any]] = {}
        try:
            for row in rows:
                outcome = adapter(row)
                for key in (row["stratum"], "ALL"):
                    cell = cells.setdefault(key, _cell())
                    cell["n"] += 1
                    if outcome == ABSTAIN:
                        cell["abstentions"] += 1
                    elif outcome == MERGE:
                        cell["merges"] += 1
                        cell["true_merges" if row["gold"] == "same" else "false_merges"] += 1
                    elif row["gold"] == "same":
                        cell["false_splits"] += 1
        except Exception as error:  # reported as errored, never as zeros
            result[name] = {"error": f"{type(error).__name__}: {error}"}
            continue
        for cell in cells.values():
            merges = cell["merges"]
            cell["merge_precision"] = cell["true_merges"] / merges if merges else None
            cell["coverage"] = (cell["n"] - cell["abstentions"]) / cell["n"]
        result[name] = {"strata": cells}
    return result


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Entity resolver comparison",
        "",
        "synthetic development fixture; not U07 holdout evidence.",
        "",
        f"- fixture sha256: `{report['fixture_sha256']}`",
        f"- git SHA: `{report['git_sha']}`",
        f"- pairs: {report['pairs']}",
        "- abstention = REVIEW / possible-match; approved aliases are passed to akc_cir only.",
        "",
    ]
    for name, data in report["resolvers"].items():
        lines += [f"## {name}", ""]
        if "error" in data:
            lines += [f"ERRORED: {data['error']}", ""]
            continue
        lines += [
            "| stratum | n | merges | false merges | false splits | abstentions "
            "| merge precision | coverage |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for key, c in sorted(data["strata"].items(), key=lambda kv: (kv[0] == "ALL", kv[0])):
            lines.append(
                f"| {key} | {c['n']} | {c['merges']} | {c['false_merges']} | {c['false_splits']} | "
                f"{c['abstentions']} | {_fmt(c['merge_precision'])} | {_fmt(c['coverage'])} |"
            )
        lines.append("")
    return "\n".join(lines)


def _git_sha() -> str:
    git = shutil.which("git")
    if git is None:
        return "unknown"
    here = str(Path(__file__).resolve().parent)
    try:
        sha = subprocess.run(
            [git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True, cwd=here
        ).stdout.strip()
        dirty = subprocess.run(
            [git, "status", "--porcelain"], capture_output=True, text=True, check=True, cwd=here
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def run(fixture: Path, out: Path) -> dict[str, Any]:
    rows = load_fixture(fixture)
    report = {
        "fixture": fixture.name,
        "fixture_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
        "git_sha": _git_sha(),
        "pairs": len(rows),
        "note": "synthetic development fixture; not U07 holdout evidence",
        "resolvers": evaluate(rows),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    report = run(args.fixture, args.out)
    return 1 if any("error" in d for d in report["resolvers"].values()) else 0


if __name__ == "__main__":
    sys.exit(main())
