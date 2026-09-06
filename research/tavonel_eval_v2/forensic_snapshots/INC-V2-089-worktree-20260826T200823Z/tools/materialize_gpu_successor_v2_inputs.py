#!/usr/bin/env python3
"""Fail-closed GPU successor V2 input materialization.

Unlike ``materialize_successor_inputs``, this module has no approximate token
counter.  It accepts only an SFIR4-bound successor manifest, a separately
hashed context artifact, and a complete local tokenizer artifact manifest.
The pinned tokenizer is loaded with ``local_files_only=True`` and its chat
template produces the exact input token sequence recorded for each arm.

This is an export tool, not an authority writer.  The CLI exclusive-creates a
caller-selected output path and never writes under ``receipts``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_TOOLS = Path(__file__).resolve().parent
_NS = _TOOLS.parent
_ROOT = _NS.parents[1]
for _path in (_TOOLS, _NS / "endpoint", _NS / "source_fact_ir"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import build_gpu_successor_v2_cohort as cohort_v2  # noqa: E402
import gpu_successor_v2_prompt_schema as sps  # noqa: E402
from common import canonical_json, sha_bytes  # noqa: E402

SCHEMA = "tavonel.v2.gpu_successor_materialized_inputs.v2"
CONTEXT_SCHEMA = "tavonel.v2.gpu_successor_context_artifact.v2"
TOKENIZER_MANIFEST_SCHEMA = "tavonel.v2.tokenizer_artifact_manifest.v1"
SFIR4_PROTOCOL_ID = "SOURCE_FACT_IR_INDEPENDENT_REPLICATION_V4"
ACCEPTED_VERDICT = "PASS"


class MaterializationV2Refused(RuntimeError):
    """An input was not exactly pinned, complete, or internally consistent."""


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MaterializationV2Refused(
            f"{label} is not readable canonical input: {error}"
        ) from error
    if not isinstance(value, dict):
        raise MaterializationV2Refused(f"{label} must be a JSON object")
    return value


def _canonical_digest(value: Any) -> str:
    return sha_bytes(canonical_json(value).encode("utf-8"))


def _resolve_bound_path(value: Any, *, manifest_path: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise MaterializationV2Refused(f"{label}.path is absent")
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [_ROOT / raw, manifest_path.parent / raw]
    existing = {candidate.resolve() for candidate in candidates if candidate.is_file()}
    if len(existing) != 1:
        raise MaterializationV2Refused(
            f"{label}.path must resolve to exactly one existing file; found {len(existing)}"
        )
    return existing.pop()


def _verify_sfir4_binding(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    binding = manifest.get("source_sfir4_acceptance")
    if not isinstance(binding, dict):
        raise MaterializationV2Refused(
            "manifest is not explicitly bound to source_sfir4_acceptance"
        )
    if (
        binding.get("protocol_id") != SFIR4_PROTOCOL_ID
        or binding.get("verdict") != ACCEPTED_VERDICT
    ):
        raise MaterializationV2Refused("manifest's SFIR4 binding is not an exact SFIR4 PASS")
    acceptance_path = _resolve_bound_path(
        binding.get("path"), manifest_path=manifest_path, label="source_sfir4_acceptance"
    )
    observed_sha = sha_file(acceptance_path)
    if binding.get("sha256") != observed_sha:
        raise MaterializationV2Refused("SFIR4 acceptance bytes do not match the manifest binding")
    acceptance = _load_json(acceptance_path, "SFIR4 acceptance")
    if (
        acceptance.get("protocol_id") != SFIR4_PROTOCOL_ID
        or acceptance.get("verdict") != ACCEPTED_VERDICT
    ):
        raise MaterializationV2Refused("bound acceptance file does not itself report SFIR4 PASS")
    return {"path": str(acceptance_path), "sha256": observed_sha}


def _verify_manifest(manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    if manifest.get("schema") != cohort_v2.MANIFEST_SCHEMA:
        raise MaterializationV2Refused("successor manifest is not the V2 authority schema")
    if manifest.get("feasible") is not True:
        raise MaterializationV2Refused("successor manifest is not feasible=True")
    facts = manifest.get("facts")
    if not isinstance(facts, list) or not facts:
        raise MaterializationV2Refused("successor manifest has no facts")
    fact_ids = [fact.get("fact_id") for fact in facts if isinstance(fact, dict)]
    if len(fact_ids) != len(facts) or any(
        not isinstance(value, str) or not value for value in fact_ids
    ):
        raise MaterializationV2Refused("every manifest fact must have a non-empty fact_id")
    if len(set(fact_ids)) != len(fact_ids):
        raise MaterializationV2Refused("manifest fact_id values are not unique")
    observed_facts_digest = _canonical_digest(facts)
    if manifest.get("facts_digest") != observed_facts_digest:
        raise MaterializationV2Refused("manifest facts_digest does not match its facts")
    lineages = [fact.get("lineage_id") for fact in facts]
    if any(not isinstance(value, str) or not value for value in lineages):
        raise MaterializationV2Refused("every selected question requires an exact lineage_id")
    if len(set(lineages)) != len(lineages):
        raise MaterializationV2Refused("manifest contains more than one question per lineage")
    if manifest.get("eligible_count") != cohort_v2.FLOOR or len(facts) != cohort_v2.FLOOR:
        raise MaterializationV2Refused("manifest must contain exactly 450 selected lineages")
    selection = manifest.get("question_selection")
    if not isinstance(selection, list) or manifest.get(
        "question_selection_digest"
    ) != _canonical_digest(selection):
        raise MaterializationV2Refused("question-selection authority is absent or drifted")
    selected_by_lineage = {fact["lineage_id"]: fact for fact in facts}
    if len(selection) != len(facts):
        raise MaterializationV2Refused("question-selection rows do not partition selected facts")
    for row in selection:
        if not isinstance(row, dict) or row.get("lineage_id") not in selected_by_lineage:
            raise MaterializationV2Refused("question-selection row names an unknown lineage")
        fact = selected_by_lineage[row["lineage_id"]]
        expected = cohort_v2.canonical_sha(
            {
                "rule": cohort_v2.QUESTION_SELECTION_RULE,
                "lineage_id": fact["lineage_id"],
                "fact_id": fact.get("fact_id"),
                "kind": fact.get("kind"),
            }
        )
        if row.get("fact_id") != fact.get("fact_id") or row.get("selection_sha256") != expected:
            raise MaterializationV2Refused("question-selection row does not bind the selected fact")
    if manifest.get("prompt_schema_digest") != sps.schema_digest():
        raise MaterializationV2Refused(
            "manifest prompt_schema_digest does not match the loaded schema"
        )
    sfir4 = _verify_sfir4_binding(manifest, manifest_path)
    return {
        "sha256": sha_file(manifest_path),
        "facts_digest": observed_facts_digest,
        "sfir4_acceptance": sfir4,
    }


def _verify_contexts(
    context: dict[str, Any], *, manifest: dict[str, Any], manifest_sha256: str
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    if context.get("schema") != CONTEXT_SCHEMA:
        raise MaterializationV2Refused(f"context schema must be {CONTEXT_SCHEMA}")
    if context.get("successor_manifest_sha256") != manifest_sha256:
        raise MaterializationV2Refused(
            "context artifact is bound to a different successor manifest"
        )
    if context.get("facts_digest") != manifest.get("facts_digest"):
        raise MaterializationV2Refused("context artifact facts_digest does not match the manifest")
    if context.get("sfir4_acceptance_sha256") != manifest.get("source_sfir4_acceptance", {}).get(
        "sha256"
    ):
        raise MaterializationV2Refused("context artifact binds a different SFIR4 acceptance")
    by_fact = context.get("context_by_fact")
    if not isinstance(by_fact, dict):
        raise MaterializationV2Refused("context_by_fact must be an object")
    expected_ids = {fact["fact_id"] for fact in manifest["facts"]}
    if set(by_fact) != expected_ids:
        raise MaterializationV2Refused("context fact ids must equal the manifest fact ids exactly")
    if context.get("contexts_digest") != _canonical_digest(by_fact):
        raise MaterializationV2Refused("contexts_digest does not match all context bytes")

    for fact_id, arms in by_fact.items():
        if not isinstance(arms, dict) or set(arms) != set(sps.ARMS):
            raise MaterializationV2Refused(f"{fact_id}: context arms must equal {sps.ARMS}")
        for arm, atoms in arms.items():
            if not isinstance(atoms, list):
                raise MaterializationV2Refused(f"{fact_id}/{arm}: atoms must be a list")
            seen: set[str] = set()
            for atom in atoms:
                if not isinstance(atom, dict):
                    raise MaterializationV2Refused(f"{fact_id}/{arm}: atom must be an object")
                atom_id, path, text = atom.get("atom_id"), atom.get("path"), atom.get("text")
                if not all(isinstance(value, str) and value for value in (atom_id, path, text)):
                    raise MaterializationV2Refused(
                        f"{fact_id}/{arm}: atom identity/path/text is incomplete"
                    )
                if atom_id in seen:
                    raise MaterializationV2Refused(
                        f"{fact_id}/{arm}: duplicate atom_id {atom_id!r}"
                    )
                seen.add(atom_id)
                if atom.get("text_sha256") != sha_bytes(text.encode("utf-8")):
                    raise MaterializationV2Refused(
                        f"{fact_id}/{arm}/{atom_id}: text_sha256 mismatch"
                    )
    return by_fact


def _safe_relative_file(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise MaterializationV2Refused(
            "tokenizer file paths must be non-empty POSIX-relative paths"
        )
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise MaterializationV2Refused(f"unsafe tokenizer file path {relative!r}")
    path = root.joinpath(*rel.parts)
    if path.is_symlink() or not path.is_file():
        raise MaterializationV2Refused(f"tokenizer file {relative!r} is absent or a symlink")
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise MaterializationV2Refused(f"tokenizer file escapes its root: {relative!r}") from error
    return path


def _verify_tokenizer_artifact(root: Path, token_manifest: dict[str, Any]) -> dict[str, Any]:
    if token_manifest.get("schema") != TOKENIZER_MANIFEST_SCHEMA:
        raise MaterializationV2Refused(
            f"tokenizer manifest schema must be {TOKENIZER_MANIFEST_SCHEMA}"
        )
    if token_manifest.get("repository") != sps.MODEL_REPOSITORY:
        raise MaterializationV2Refused(
            "tokenizer repository does not equal the pinned model repository"
        )
    if token_manifest.get("revision") != sps.MODEL_REVISION:
        raise MaterializationV2Refused(
            "tokenizer revision does not equal the exact pinned model revision"
        )
    files = token_manifest.get("files")
    if not isinstance(files, list) or not files:
        raise MaterializationV2Refused("tokenizer manifest has no files")
    declared: dict[str, str] = {}
    normalized: list[dict[str, str]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise MaterializationV2Refused("tokenizer file entry must be an object")
        relative, expected = entry.get("path"), entry.get("sha256")
        path = _safe_relative_file(root, relative)
        if relative in declared:
            raise MaterializationV2Refused(f"duplicate tokenizer file entry {relative!r}")
        observed = sha_file(path)
        if expected != observed:
            raise MaterializationV2Refused(f"tokenizer file digest mismatch: {relative}")
        declared[relative] = observed
        normalized.append({"path": relative, "sha256": observed})

    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if actual != set(declared):
        raise MaterializationV2Refused(
            "tokenizer file manifest must enumerate every regular file exactly; "
            f"missing={sorted(actual - set(declared))}, extra={sorted(set(declared) - actual)}"
        )
    normalized.sort(key=lambda entry: entry["path"])
    files_digest = _canonical_digest(normalized)
    if token_manifest.get("files_digest") != files_digest:
        raise MaterializationV2Refused(
            "tokenizer files_digest does not match the complete file manifest"
        )
    return {
        "repository": sps.MODEL_REPOSITORY,
        "revision": sps.MODEL_REVISION,
        "files": normalized,
        "files_digest": files_digest,
    }


def _load_real_tokenizer(root: Path, revision: str) -> Any:
    try:
        from transformers import AutoTokenizer
    except ImportError as error:
        raise MaterializationV2Refused(
            "transformers is required; approximation is forbidden"
        ) from error
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            str(root),
            revision=revision,
            local_files_only=True,
            trust_remote_code=False,
            use_fast=True,
        )
    except Exception as error:  # transformers exposes several backend-specific exceptions
        raise MaterializationV2Refused(
            f"pinned local tokenizer could not be loaded offline: {error}"
        ) from error
    if not callable(getattr(tokenizer, "apply_chat_template", None)):
        raise MaterializationV2Refused(
            "tokenizer has no chat template implementation; approximation is forbidden"
        )
    return tokenizer


def _token_ids(tokenizer: Any, system: str, user: str) -> list[int]:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        token_ids = tokenizer.apply_chat_template(
            messages, tokenize=True, add_generation_prompt=True, return_tensors=None
        )
    except Exception as error:
        raise MaterializationV2Refused(
            f"exact tokenizer chat-template application failed: {error}"
        ) from error
    if hasattr(token_ids, "tolist"):
        token_ids = token_ids.tolist()
    if token_ids and isinstance(token_ids[0], list):
        if len(token_ids) != 1:
            raise MaterializationV2Refused("tokenizer unexpectedly returned more than one sequence")
        token_ids = token_ids[0]
    if not isinstance(token_ids, list) or any(type(value) is not int for value in token_ids):
        raise MaterializationV2Refused("tokenizer did not return one exact integer token sequence")
    return token_ids


def _fit_exact(
    *, tokenizer: Any, fact: dict[str, Any], arm: str, atoms: list[dict[str, Any]], budget: int
) -> tuple[Any, list[dict[str, Any]], list[int]]:
    kept: list[dict[str, Any]] = []
    last_request = sps.build_arm_request(
        arm=arm, kind=fact["kind"], representation=fact.get("representation"), context_blocks=[]
    )
    last_ids = _token_ids(tokenizer, last_request.system_prompt, last_request.user_prompt)
    if len(last_ids) > budget:
        raise MaterializationV2Refused(
            f"{fact['fact_id']}/{arm}: empty prompt exceeds context budget"
        )
    for atom in atoms:
        trial = [*kept, atom]
        request = sps.build_arm_request(
            arm=arm,
            kind=fact["kind"],
            representation=fact.get("representation"),
            context_blocks=[candidate["text"] for candidate in trial],
        )
        ids = _token_ids(tokenizer, request.system_prompt, request.user_prompt)
        if len(ids) > budget:
            break
        kept, last_request, last_ids = trial, request, ids
    return last_request, kept, last_ids


def materialize_from_paths(
    manifest_path: Path, context_path: Path, tokenizer_root: Path, tokenizer_manifest_path: Path
) -> dict[str, Any]:
    manifest_path, context_path = manifest_path.resolve(), context_path.resolve()
    tokenizer_root, tokenizer_manifest_path = (
        tokenizer_root.resolve(),
        tokenizer_manifest_path.resolve(),
    )
    manifest = _load_json(manifest_path, "successor manifest")
    manifest_attestation = _verify_manifest(manifest, manifest_path)
    context = _load_json(context_path, "context artifact")
    context_by_fact = _verify_contexts(
        context, manifest=manifest, manifest_sha256=manifest_attestation["sha256"]
    )
    token_manifest = _load_json(tokenizer_manifest_path, "tokenizer artifact manifest")
    tokenizer_attestation = _verify_tokenizer_artifact(tokenizer_root, token_manifest)
    tokenizer = _load_real_tokenizer(tokenizer_root, tokenizer_attestation["revision"])

    items: list[dict[str, Any]] = []
    facts = sorted(manifest["facts"], key=lambda fact: (fact["kind"], fact["fact_id"]))
    for fact in facts:
        arms: dict[str, Any] = {}
        built: dict[str, Any] = {}
        for arm in sps.ARMS:
            atoms = context_by_fact[fact["fact_id"]][arm]
            request, kept, ids = _fit_exact(
                tokenizer=tokenizer,
                fact=fact,
                arm=arm,
                atoms=atoms,
                budget=sps.CONTEXT_BUDGET_TOKENS,
            )
            built[arm] = request
            arm_body = {
                **request.as_dict(),
                "kept_atom_ids": [atom["atom_id"] for atom in kept],
                "dropped_atom_ids": [atom["atom_id"] for atom in atoms[len(kept) :]],
                "input_token_count": len(ids),
                "input_token_ids_sha256": _canonical_digest(ids),
                "token_count_method": (
                    "pinned local tokenizer apply_chat_template; no approximation"
                ),
            }
            arms[arm] = arm_body
        comparison = sps.assert_all_arms_identical_except_context(built)
        if comparison.get("identical_except_context") is not True:
            raise MaterializationV2Refused(
                f"{fact['fact_id']}: arm requests differ outside context: "
                f"{comparison.get('mismatches')}"
            )
        item = {
            "fact_id": fact["fact_id"],
            "kind": fact["kind"],
            "lineage_id": fact.get("lineage_id"),
            "representation": fact.get("representation"),
            "current_expected_value": fact.get("representation"),
            "arms": arms,
            "identical_except_context": comparison,
        }
        item["item_digest"] = _canonical_digest(item)
        items.append(item)

    set_digest = _canonical_digest([item["item_digest"] for item in items])
    return {
        "schema": SCHEMA,
        "study_id": manifest.get("study_id"),
        "manifest": manifest_attestation,
        "context_artifact": {
            "sha256": sha_file(context_path),
            "contexts_digest": context["contexts_digest"],
            "sfir4_acceptance_sha256": context["sfir4_acceptance_sha256"],
        },
        "tokenizer": {
            **tokenizer_attestation,
            "manifest_sha256": sha_file(tokenizer_manifest_path),
            "class": type(tokenizer).__name__,
            "offline_local_files_only": True,
        },
        "ordering": "sorted by (kind, fact_id); candidate atoms retain artifact order",
        "item_count": len(items),
        "items": items,
        "set_digest": set_digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("context", type=Path)
    parser.add_argument("tokenizer_root", type=Path)
    parser.add_argument("tokenizer_manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        body = materialize_from_paths(
            args.manifest, args.context, args.tokenizer_root, args.tokenizer_manifest
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n")
    except (MaterializationV2Refused, FileExistsError) as error:
        print(json.dumps({"state": "REFUSED", "why": str(error)}, indent=2))
        return 4
    print(
        json.dumps(
            {"state": "MATERIALIZED", "output": str(args.output), "set_digest": body["set_digest"]},
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
