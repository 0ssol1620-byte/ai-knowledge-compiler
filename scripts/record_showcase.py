"""Record the cinematic showcase fixture with the REAL compiler runtime.

Master spec: TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_FINAL_KO
(§3.1 Comprehension World, §9.4 canonical envelope, §11.2 fixture paths,
Phase 2 "Showcase corpus + recorded replay").

The recorder never invents an event. It copies the pristine corpus under
``packages/compiler-runtime/src/akc_compiler_runtime/showcase/Launch`` into a
scratch workspace, compiles that copy with ``akc_compiler_runtime.Pipeline``
(the p0-e2e-spine compile_workspace/recompile spine, vendored verbatim until it
merges), derives every envelope payload from actual pipeline artifacts, then:

    v1 compile (WS-1) -> mutate the scratch tree
    (official launch date October 15 -> November 3 + exact-content rename)
    -> incremental recompile with the §44 selective-vs-full oracle (WS-2)

and writes apps/web/src/fixtures/showcase-world/v1/:
manifest.json, events.jsonl, world-v1.json, world-v2.json, receipts.json.

Every envelope uses mode="demo" and scope={"kind": "demo",
"fixture_id": "showcase-world-v1"} per §9.4.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import tempfile
import time
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The compiler-runtime package is vendored from agent/p0-e2e-spine (764741c)
# until it merges; make it importable without requiring an editable install.
for _rel in ("packages/cir-python/src", "packages/compiler-runtime/src"):
    _path = ROOT / _rel
    if _path.is_dir() and str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from akc_compiler_runtime import CompileOptions, Pipeline  # noqa: E402
from akc_compiler_runtime.extraction import parse_workspace  # noqa: E402

FIXTURE_ID = "showcase-world-v1"
SCHEMA_VERSION = "1.0"
SPEC_NAME = "TAVONEL_CINEMATIC_COMPILATION_REPLAY_MASTER_SPEC_v2.0_FINAL_KO_2026-08-23"
SAMPLE_NOTICE = "SAMPLE WORLD - FICTIONAL CONTENT - REAL COMPILER RUN"

CORPUS = (
    ROOT
    / "packages"
    / "compiler-runtime"
    / "src"
    / "akc_compiler_runtime"
    / "showcase"
    / "Launch"
)
OUTPUT_DIR = ROOT / "apps" / "web" / "src" / "fixtures" / "showcase-world" / "v1"

TENANT_ID = "showcase"
WORKSPACE_ID = "showcase-launch"

LAUNCH_QUESTION = "What is the current launch date?"

PLAN_FILE = "approved-launch-plan.md"
OLD_DATE = "October 15, 2026"
NEW_DATE = "November 3, 2026"
RENAME_FROM = "codename-brief.md"
RENAME_TO = "lp01-naming-brief.md"


def _now_iso() -> str:
    return (
        datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


def _jsonable(value: object) -> object:
    """Dataclasses/enums/tuples -> plain JSON types, recursively."""
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class EventRecorder:
    """Serializes real pipeline artifacts into §9.4 canonical envelopes."""

    def __init__(self) -> None:
        self._sequence = 0
        self._t0 = time.monotonic()
        self.events: list[dict[str, object]] = []

    def emit(self, event_type: str, payload: MappingPayload) -> dict[str, object]:
        self._sequence += 1
        envelope = {
            "schema_version": SCHEMA_VERSION,
            "event_id": f"evt-{self._sequence:04d}-{event_type.replace('.', '-')}",
            "event_type": event_type,
            "sequence": self._sequence,
            "occurred_at": _now_iso(),
            "monotonic_offset_ms": int((time.monotonic() - self._t0) * 1000),
            "mode": "demo",
            "scope": {"kind": "demo", "fixture_id": FIXTURE_ID},
            "payload": _jsonable(payload),
        }
        self.events.append(envelope)
        return envelope


MappingPayload = dict[str, object]


def _cursor_of(world) -> dict[str, str]:
    return dict(world.cursor)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _classify_against(
    documents, previous_cursor: dict[str, str]
) -> dict[str, object]:
    """Mirror the pipeline's cursor diff from real hashes (for revision events)."""
    current = {doc.file.rel_path: doc.file.sha256 for doc in documents}
    removed = sorted(set(previous_cursor) - set(current))
    added = sorted(set(current) - set(previous_cursor))
    changed = sorted(
        path
        for path, sha in current.items()
        if path in previous_cursor and previous_cursor[path] != sha
    )
    sha_to_removed: dict[str, str] = {}
    for path in removed:
        sha_to_removed.setdefault(previous_cursor[path], path)
    renames: dict[str, str] = {}
    for path in added:
        old = sha_to_removed.pop(current[path], None)
        if old is not None:
            renames[path] = old
    return {
        "current": current,
        "changed": sorted(set(changed)),
        "added": sorted(set(added) - set(renames)),
        "removed": sorted(set(removed) - set(renames.values())),
        "renamed": {new: old for new, old in renames.items()},
    }


def _emit_discovery(recorder: EventRecorder, stage: Path) -> None:
    documents = parse_workspace(stage, tenant_id=TENANT_ID)
    recorder.emit(
        "collection.discovery.progress.v1",
        {"files_discovered": len(documents)},
    )
    for doc in documents:
        size_bytes = (stage / doc.file.rel_path).stat().st_size
        recorder.emit(
            "file.discovered.v1",
            {
                "rel_path": doc.file.rel_path,
                "sha256": doc.file.sha256,
                "size_bytes": size_bytes,
            },
        )
    for doc in documents:
        recorder.emit(
            "document.profiled.v1",
            {
                "rel_path": doc.file.rel_path,
                "document_version_id": doc.document_version,
                "authority": doc.authority.value,
                "claim_count": len(doc.claims),
            },
        )
        recorder.emit(
            "authority.resolved.v1",
            {
                "rel_path": doc.file.rel_path,
                "authority": doc.authority.value,
            },
        )


def _emit_world_units(recorder: EventRecorder, world) -> None:
    """knowledge.unit.created / relation.created straight off the claim table."""
    for logical_id in sorted(world.claims):
        row = world.claims[logical_id]
        recorder.emit(
            "knowledge.unit.created.v1",
            {
                "logical_id": logical_id,
                "subject": row["subject"],
                "kind": row["kind"],
                "value": row["value"],
                "rel_path": row["rel_path"],
                "line_number": row["line_number"],
                "anchor": row["anchor"],
                "evidence_id": row["evidence_id"],
            },
        )
    for logical_id in sorted(world.claims):
        row = world.claims[logical_id]
        for target in sorted(row["dependencies"]):
            recorder.emit(
                "relation.created.v1",
                {
                    "from_logical_id": logical_id,
                    "from_document": row["rel_path"],
                    "edge_type": "DEPENDS_ON",
                    "to_document_node": target,
                },
            )


def _emit_answer_event(
    recorder: EventRecorder, compiled_answer, world, question: str
) -> dict[str, object]:
    winner_rows = []
    for claim_id in compiled_answer.claim_ids:
        row = world.claims.get(claim_id)
        if row is not None:
            winner_rows.append(row)
    value = winner_rows[0]["value"] if winner_rows else None
    payload: dict[str, object] = {
        "question": question,
        "outcome": compiled_answer.outcome.value,
        "claim_ids": list(compiled_answer.claim_ids),
        "value": value,
        "world_state_id": compiled_answer.world_state_id,
        "reason": compiled_answer.reason,
        "evidence_occurrences": [
            {
                "claim_id": occ.claim_id,
                "evidence_id": occ.evidence_id,
                "source_status": occ.source_status.value,
            }
            for occ in compiled_answer.evidence_occurrences
        ],
    }
    recorder.emit("answer.emitted.v1", payload)
    return payload


def _answer_block(compiled_answer, payload: dict[str, object]) -> dict[str, object]:
    return {
        "question": payload["question"],
        "outcome": payload["outcome"],
        "value": payload["value"],
        "claim_ids": payload["claim_ids"],
        "world_state_id": payload["world_state_id"],
        "intent": compiled_answer.intent.value,
        "reason": compiled_answer.reason,
        "evidence_occurrences": payload["evidence_occurrences"],
    }


def _world_document(world, compiled_answer_block: dict[str, object] | None) -> dict[str, object]:
    summary = {
        "documents": len(world.cursor),
        "knowledge_units": len(world.claims),
        "relations": sum(
            len(row["dependencies"]) for row in world.claims.values()
        ),
        "invalidated_units": sum(
            1 for row in world.claims.values() if row["invalidated_by"]
        ),
        "review_queue_entries": len(world.review_queue),
    }
    return {
        "fixture_id": FIXTURE_ID,
        "sample_notice": SAMPLE_NOTICE,
        "world_state_id": world.world_state_id,
        "workspace_id": world.workspace_id,
        "parent_world_state_id": None,
        "built_at": world.built_at.isoformat().replace("+00:00", "Z"),
        "compiler_version": world.manifest.compiler_version,
        "summary": summary,
        "answers": [compiled_answer_block] if compiled_answer_block else [],
        "manifest": {
            "world_state_id": world.manifest.world_state_id,
            "compiler_version": world.manifest.compiler_version,
            "artifact_hashes": dict(world.manifest.artifact_hashes),
            "manifest_hash": world.manifest.manifest_hash,
        },
        "receipt": {
            "receipt_id": world.receipt.receipt_id,
            "checksums_verified": world.receipt.checksums_verified,
            "permission_checked": world.receipt.permission_checked,
            "integrity_passed": world.receipt.integrity_passed,
            "equivalence": (
                world.receipt.equivalence.as_record()
                if world.receipt.equivalence is not None
                else None
            ),
        },
        "cursor": dict(world.cursor),
        "review_queue": [dict(item) for item in world.review_queue],
        "claims": {
            logical_id: dict(row) for logical_id, row in sorted(world.claims.items())
        },
    }


def record(stage: Path, store_root: Path) -> tuple[EventRecorder, dict[str, object]]:
    recorder = EventRecorder()
    options = CompileOptions(tenant_id=TENANT_ID, workspace_id=WORKSPACE_ID)
    pipeline = Pipeline(store_root, options=options)

    # ---------------- world v1: first full compile -------------------------
    _emit_discovery(recorder, stage)

    result1 = pipeline.compile_workspace(stage)
    if not result1.published or result1.no_op:
        raise RuntimeError(f"v1 compile did not publish: {result1}")
    world1 = pipeline.store.load_world(result1.world_state_id)
    if world1 is None:
        raise RuntimeError("WS-1 could not be loaded back")

    _emit_world_units(recorder, world1)

    answer1 = pipeline.answer(LAUNCH_QUESTION)
    answer1_block = _answer_block(
        answer1,
        _emit_answer_event(recorder, answer1, world1, LAUNCH_QUESTION),
    )

    recorder.emit(
        "world_state.activated.v1",
        {
            "world_state_id": world1.world_state_id,
            "previous_world_state_id": None,
            "manifest_hash": world1.manifest.manifest_hash,
            "built_at": world1.built_at.isoformat().replace("+00:00", "Z"),
            "activated_at": world1.built_at.isoformat().replace("+00:00", "Z"),
            "knowledge_units_total": len(world1.claims),
        },
    )

    # ---------------- mutation: authoritative edit + exact-content rename ---
    plan_path = stage / PLAN_FILE
    original_plan = plan_path.read_bytes().decode("utf-8")
    if OLD_DATE not in original_plan:
        raise RuntimeError(f"{OLD_DATE!r} not found in {PLAN_FILE}")
    plan_path.write_text(
        original_plan.replace(OLD_DATE, NEW_DATE), encoding="utf-8", newline=""
    )
    shutil.move(stage / RENAME_FROM, stage / RENAME_TO)

    documents2 = parse_workspace(stage, tenant_id=TENANT_ID)
    classification = _classify_against(documents2, _cursor_of(world1))

    for path in classification["changed"]:
        recorder.emit(
            "source.revision.created.v1",
            {
                "change_kind": "edited",
                "rel_path": path,
                "previous_sha256": _cursor_of(world1)[path],
                "new_sha256": classification["current"][path],
            },
        )
    for new_path, old_path in sorted(classification["renamed"].items()):
        recorder.emit(
            "source.revision.created.v1",
            {
                "change_kind": "renamed",
                "rel_path": new_path,
                "previous_rel_path": old_path,
                "sha256": classification["current"][new_path],
            },
        )

    # ---------------- world v2: incremental recompile (oracle-guarded) -----
    result2 = pipeline.recompile(stage)
    if result2.no_op or not result2.published:
        raise RuntimeError("v2 recompile unexpectedly did not publish WS-2")
    world2 = pipeline.store.load_world(result2.world_state_id)
    if world2 is None:
        raise RuntimeError("WS-2 could not be loaded back")
    if result2.plan is None or result2.equivalence is None:
        raise RuntimeError("v2 recompile missing plan or equivalence report")

    plan_targets = result2.plan.as_record().get("targets", [])
    rebuilt_count = len(result2.plan.to_rebuild)
    recorder.emit(
        "impact.detected.v1",
        {
            "change_id": result2.plan.change_id,
            "sources_changed": len(classification["changed"])
            + len(classification["renamed"]),
            "knowledge_units_affected": len(result2.plan.stale),
            "affected_artifacts": plan_targets,
        },
    )
    recorder.emit(
        "recompile.progress.v1",
        {
            "change_id": result2.plan.change_id,
            "targets_total": len(plan_targets),
            "to_rebuild": rebuilt_count,
            "work_avoided": result2.plan.work_avoided,
        },
    )
    recorder.emit(
        "recompile.completed.v1",
        {
            "recompiled": rebuilt_count,
            "world_units_total": len(world2.claims),
            "candidate_world_state_id": world2.world_state_id,
            "equivalence_receipt_id": world2.receipt.receipt_id,
            "equivalent": result2.equivalence.equivalent,
        },
    )

    answer2 = pipeline.answer(LAUNCH_QUESTION)
    answer2_block = _answer_block(
        answer2,
        _emit_answer_event(recorder, answer2, world2, LAUNCH_QUESTION),
    )

    recorder.emit(
        "world_state.activated.v1",
        {
            "world_state_id": world2.world_state_id,
            "previous_world_state_id": world1.world_state_id,
            "manifest_hash": world2.manifest.manifest_hash,
            "built_at": world2.built_at.isoformat().replace("+00:00", "Z"),
            "activated_at": world2.built_at.isoformat().replace("+00:00", "Z"),
            "knowledge_units_total": len(world2.claims),
        },
    )

    world1_doc = _world_document(world1, answer1_block)
    world1_doc["parent_world_state_id"] = None
    world2_doc = _world_document(world2, answer2_block)
    world2_doc["parent_world_state_id"] = world1.world_state_id

    outputs: dict[str, object] = {
        "world-v1": world1_doc,
        "world-v2": world2_doc,
        "classification": classification,
        "plan_file_original": original_plan,
    }
    return recorder, outputs


def build_manifest(
    recorder: EventRecorder,
    outputs: dict[str, object],
    events_bytes: bytes,
    recorded_at: str,
) -> dict[str, object]:
    world1 = outputs["world-v1"]
    world2 = outputs["world-v2"]
    sequences = [int(event["sequence"]) for event in recorder.events]
    source_files = [
        {"rel_path": rel_path, "sha256": sha256}
        for rel_path, sha256 in sorted(outputs["classification"]["current"].items())  # type: ignore[union-attr]
    ]
    return {
        "fixture_id": FIXTURE_ID,
        "schema_version": SCHEMA_VERSION,
        "sample_notice": SAMPLE_NOTICE,
        "generated_at": recorded_at,
        "spec": {
            "document": SPEC_NAME,
            "sections": ["3.1", "9.4", "11.2", "Phase 2"],
            "phase": 2,
        },
        "compiler": {
            "package": "akc_compiler_runtime",
            "version": world1["compiler_version"],  # type: ignore[index]
            "pipeline_entrypoints": [
                "Pipeline.compile_workspace",
                "Pipeline.recompile",
                "Pipeline.answer",
            ],
            "provenance": "vendored verbatim from agent/p0-e2e-spine 764741c",
        },
        "source_files": source_files,
        "mutations_applied": [
            {
                "kind": "authoritative-edit",
                "file": PLAN_FILE,
                "field": "launch date",
                "before": OLD_DATE,
                "after": NEW_DATE,
            },
            {
                "kind": "exact-content-rename",
                "from": RENAME_FROM,
                "to": RENAME_TO,
            },
        ],
        "worlds": [
            {
                "world_state_id": world1["world_state_id"],  # type: ignore[index]
                "manifest_hash": world1["manifest"]["manifest_hash"],  # type: ignore[index]
                "built_at": world1["built_at"],  # type: ignore[index]
                "knowledge_units": world1["summary"]["knowledge_units"],  # type: ignore[index]
                "artifact": "world-v1.json",
            },
            {
                "world_state_id": world2["world_state_id"],  # type: ignore[index]
                "parent_world_state_id": world1["world_state_id"],  # type: ignore[index]
                "manifest_hash": world2["manifest"]["manifest_hash"],  # type: ignore[index]
                "built_at": world2["built_at"],  # type: ignore[index]
                "knowledge_units": world2["summary"]["knowledge_units"],  # type: ignore[index]
                "artifact": "world-v2.json",
            },
        ],
        "events": {
            "count": len(recorder.events),
            "sequence_range": [min(sequences), max(sequences)],
            "sha256": _sha256_bytes(events_bytes),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument(
        "--scratch-root",
        type=Path,
        default=None,
        help="optional directory for the mutable workspace copy (default: tmp)",
    )
    args = parser.parse_args(argv)

    if not CORPUS.is_dir():
        raise SystemExit(f"corpus missing: {CORPUS}")

    recorded_at = _now_iso()
    with tempfile.TemporaryDirectory(prefix="akc-showcase-") as tmp:
        scratch = Path(args.scratch_root) if args.scratch_root else Path(tmp)
        scratch.mkdir(parents=True, exist_ok=True)
        stage = scratch / "workspace"
        store_root = scratch / "world-store"
        shutil.copytree(CORPUS, stage)

        recorder, outputs = record(stage, store_root)

    events_text = "".join(
        json.dumps(event, sort_keys=False, ensure_ascii=False) + "\n"
        for event in recorder.events
    )
    events_bytes = events_text.encode("utf-8")

    manifest = build_manifest(recorder, outputs, events_bytes, recorded_at)

    out_dir: Path = args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "events.jsonl").write_bytes(events_bytes)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for name in ("world-v1", "world-v2"):
        (out_dir / f"{name}.json").write_text(
            json.dumps(outputs[name], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    world1 = outputs["world-v1"]
    world2 = outputs["world-v2"]
    receipts = {
        "fixture_id": FIXTURE_ID,
        "recording": {
            "recording_id": "rec-"
            + _sha256_bytes(events_bytes)[:16],
            "recorded_at": recorded_at,
            "source": "RECORDED_FICTIONAL_SAMPLE",
            "truth_class_default": "OBSERVED",
            "privacy_class": "PUBLIC",
            "envelope_schema_version": SCHEMA_VERSION,
            "mode": "demo",
            "scope": {"kind": "demo", "fixture_id": FIXTURE_ID},
        },
        "publications": [
            {
                "world_state_id": world1["world_state_id"],  # type: ignore[index]
                "receipt": world1["receipt"],  # type: ignore[index]
            },
            {
                "world_state_id": world2["world_state_id"],  # type: ignore[index]
                "receipt": world2["receipt"],  # type: ignore[index]
            },
        ],
    }
    (out_dir / "receipts.json").write_text(
        json.dumps(receipts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    counts: dict[str, int] = {}
    for event in recorder.events:
        counts[event["event_type"]] = counts.get(event["event_type"], 0) + 1  # type: ignore[arg-type]
    print(f"recorded {len(recorder.events)} events -> {out_dir / 'events.jsonl'}")
    for event_type, count in sorted(counts.items()):
        print(f"  {event_type}: {count}")
    print(
        "v1:",
        world1["world_state_id"],  # type: ignore[index]
        world1["manifest"]["manifest_hash"],  # type: ignore[index]
        "| answer:",
        outputs["world-v1"]["answers"][0]["outcome"],  # type: ignore[index]
        outputs["world-v1"]["answers"][0]["value"],  # type: ignore[index]
    )
    print(
        "v2:",
        world2["world_state_id"],  # type: ignore[index]
        world2["manifest"]["manifest_hash"],  # type: ignore[index]
        "| answer:",
        outputs["world-v2"]["answers"][0]["outcome"],  # type: ignore[index]
        outputs["world-v2"]["answers"][0]["value"],  # type: ignore[index]
    )
    print(f"manifest: {out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
