#!/usr/bin/env python3
"""Measure the compilation stages that no public benchmark scores.

The public benchmarks stop where extraction stops. They score whether a sentence
was read correctly; they say nothing about whether the resulting corpus was
organised into something a person or an agent can navigate. That leaves the
larger half of this product unmeasured, and "no benchmark exists" is not the
same as "no claim can be made".

What can be established here is different in kind from an accuracy score. The
compilation stages are deterministic, so their properties are provable rather
than estimated: the same corpus must always produce the same architecture, a
compiled vault must contain no link that resolves nowhere, and merging into a
user's existing vault must never lose a file silently. Those are the promises a
regulated buyer actually needs, and unlike an accuracy percentage they are
either true or false.

Documents are drawn from the campaign's own extraction output rather than from
fixtures, so the measurement runs on the same text the benchmark scored.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from akc_cir import (
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalDocument,
    ContentLayer,
    SourceRef,
    sha256_digest,
)
from akc_domain_packs.blueprints import (
    ArchitectureProfile,
    builtin_blueprints,
    plan_architecture,
)
from akc_exporters.markdown import MarkdownArtifact
from akc_exporters.vault import (
    MergePolicy,
    compile_vault,
    plan_vault_merge,
    validate_internal_links,
)
from akc_cir.exports import SourceMap

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _block_type(text: str) -> BlockType:
    """Classify a chunk, without claiming table structure this harness has not built.

    The schema refuses a TABLE block that carries no canonical table, which is
    the correct behaviour: a block typed as a table but holding only a string of
    pipes would let unstructured text masquerade as structured data downstream.
    This harness reconstructs no table structure, so table-shaped chunks stay
    paragraphs and are counted separately rather than mislabelled.
    """
    if _HEADING.match(text):
        return BlockType.HEADING
    if text.lstrip().startswith(("- ", "* ", "1. ")):
        return BlockType.LIST
    return BlockType.PARAGRAPH


def _looks_like_table(text: str) -> bool:
    # A pipe table arrives as a multi-line chunk, so the row pattern has to be
    # matched against its first line rather than against the whole block.
    first_line = text.lstrip().split("\n", 1)[0]
    return bool(_TABLE_ROW.match(first_line)) or first_line.startswith("<table")


def canonical_document_from_markdown(
    case_id: str, markdown: str, *, tenant_id: str = "benchmark"
) -> CanonicalDocument:
    """Turn one extracted document into the canonical form the exporters consume.

    Blocks are split on blank lines, which is the structure the extractor already
    emits. The point is not to re-derive layout but to carry real extracted text
    through the compilation stages so the properties measured downstream are
    measured on real content.
    """
    chunks = [chunk.strip() for chunk in markdown.split("\n\n") if chunk.strip()]
    if not chunks:
        chunks = ["(empty extraction)"]
    table_shaped = sum(1 for chunk in chunks if _looks_like_table(chunk))
    blocks = []
    for order, chunk in enumerate(chunks):
        reference = SourceRef(
            document_id=case_id,
            document_version_id=f"{case_id}-v1",
            page_index0=0,
            page_number1=1,
            bbox1000=BBox1000([0, 0, 1000, 1000]),
        )
        blocks.append(
            CanonicalBlock(
                id=f"blk_{order:05d}",
                order=order,
                type=_block_type(chunk),
                content_layer=ContentLayer.EXTRACTED,
                raw_text=chunk,
                normalized_text=chunk,
                # The campaign's text came from an OCR/VLM extractor, and the
                # provenance model distinguishes that from native text layers
                # and from anything a model reconstructed or inferred.
                origin=BlockOrigin.OCR_EXTRACTED,
                source_refs=(reference,),
                content_hash=sha256_digest(chunk),
            )
        )
    heading = next((c for c in chunks if _HEADING.match(c)), None)
    title = _HEADING.match(heading).group(2).strip() if heading else case_id
    return CanonicalDocument(
        tenant_id=tenant_id,
        document_id=case_id,
        document_version_id=f"{case_id}-v1",
        title=title or case_id,
        source_filename=f"{case_id}.pdf",
        source_sha256=sha256_digest(markdown.encode("utf-8")),
        content_layer=ContentLayer.EXTRACTED,
        blocks=tuple(blocks),
        created_at=datetime(2026, 8, 8, tzinfo=UTC),
        metadata={"table_shaped_chunks": table_shaped},
    )


def measure_architecture_determinism(repeats: int) -> dict[str, Any]:
    """The same corpus description must always yield the same architecture.

    A plan that drifts between runs cannot be audited, cannot be reproduced by a
    customer, and cannot support a claim that two corpora were organised alike.
    """
    registry = builtin_blueprints()
    blueprint_ids = [b["id"] for b in registry.model_dump()["blueprints"]]
    per_blueprint = []
    all_digests: dict[str, str] = {}
    unstable: list[str] = []
    for blueprint_id in blueprint_ids:
        profile = ArchitectureProfile(
            domain="benchmark-corpus",
            object_types=("document", "entity"),
            user_goal="Compile the public benchmark corpus into a navigable vault.",
            corpus_size=5131,
            temporal_structure="single-snapshot",
            existing_folders=(),
            requested_blueprint=blueprint_id,
        )
        digests = {
            plan_architecture(profile, registry=registry).plan_sha256
            for _ in range(repeats)
        }
        stable = len(digests) == 1
        if not stable:
            unstable.append(blueprint_id)
        digest = next(iter(digests))
        all_digests[blueprint_id] = digest
        plan = plan_architecture(profile, registry=registry)
        per_blueprint.append(
            {
                "blueprint": blueprint_id,
                "stable_across_repeats": stable,
                "plan_sha256": digest,
                "folder_paths": list(plan.folder_paths),
                "folder_depth": plan.folder_depth,
                "naming_policy": plan.naming_policy,
            }
        )
    # Distinct blueprints must not collapse onto one plan, or the choice is
    # decorative and the architecture claim is empty.
    distinct = len(set(all_digests.values())) == len(all_digests)
    return {
        "repeats_per_blueprint": repeats,
        "blueprints_measured": len(blueprint_ids),
        "all_plans_stable_across_repeats": not unstable,
        "unstable_blueprints": unstable,
        "distinct_blueprints_produce_distinct_plans": distinct,
        "per_blueprint": per_blueprint,
    }


def _artifact_for(document: CanonicalDocument, markdown: str) -> MarkdownArtifact:
    return MarkdownArtifact(
        path=f"{document.document_id}.md",
        markdown=markdown,
        source_map=SourceMap(
            document_id=document.document_id,
            document_version_id=document.document_version_id,
            source_sha256=document.source_sha256,
            entries=(),
        ),
    )


_BROKEN_TARGET = re.compile(r"-> (.+?) \((\w+)\)")


def _classify_refusal(message: str) -> tuple[str, str]:
    match = _BROKEN_TARGET.search(message)
    target = match.group(1) if match else "(unparsed)"
    if target.startswith("images/"):
        # The benchmark lane extracted text only and carried no figure crops, so
        # a reference to one cannot resolve. Refusing is the correct outcome.
        return "referenced figure asset was not supplied", target
    if "\\" in target or any(character in target for character in "${}^_"):
        # A LaTeX fragment such as ``s \otimes f`` matches the markdown link
        # grammar. This one is a link-detection false positive, not a real
        # dangling link, and it blocks a document that should have compiled.
        return "latex fragment parsed as a markdown link", target
    return "other unresolved target", target


def measure_vault_compilation(
    documents: list[tuple[str, str]], *, wikilinks: bool
) -> dict[str, Any]:
    """Compile real documents and record what the compiler refuses to emit.

    The interesting property is not that the emitted vault has no broken links.
    It is that a vault with a broken link cannot be emitted at all: compilation
    raises rather than writing a document whose reference resolves nowhere. That
    makes the refusals the evidence, so they are categorised rather than counted.
    """
    files: dict[str, bytes] = {}
    compiled = 0
    refusals: list[dict[str, str]] = []
    other_errors: list[dict[str, str]] = []
    for case_id, markdown in documents:
        try:
            document = canonical_document_from_markdown(case_id, markdown)
            artifact = _artifact_for(document, markdown)
            emitted = compile_vault(
                document,
                artifact,
                quality_report=None,
                knowledge_bundle=None,
                wikilinks=wikilinks,
                binary_assets=None,
            )
        except ValueError as error:
            message = str(error)
            if "broken internal links" not in message:
                other_errors.append({"case_id": case_id, "error": message[:300]})
                continue
            cause, target = _classify_refusal(message)
            refusals.append({"case_id": case_id, "cause": cause, "target": target[:120]})
            continue
        except Exception as error:  # noqa: BLE001 - an unexpected failure is a finding
            other_errors.append(
                {"case_id": case_id, "error": f"{type(error).__name__}: {error}"[:300]}
            )
            continue
        compiled += 1
        files.update(emitted)

    by_cause: dict[str, int] = {}
    for refusal in refusals:
        by_cause[refusal["cause"]] = by_cause.get(refusal["cause"], 0) + 1

    broken = validate_internal_links(files)
    return {
        "documents_offered": len(documents),
        "documents_compiled": compiled,
        "documents_refused_for_broken_links": len(refusals),
        "documents_failed_for_other_reasons": len(other_errors),
        "vault_files_emitted": len(files),
        "broken_internal_links_in_emitted_vault": len(broken),
        "refusals_by_cause": dict(sorted(by_cause.items())),
        "refusal_samples": refusals[:10],
        "other_error_samples": other_errors[:10],
        "fail_closed": len(broken) == 0 and bool(refusals),
        "candidate_defect": {
            "description": (
                "A LaTeX fragment that matches the markdown link grammar is treated "
                "as a dangling link, which refuses a document that has no real "
                "broken reference."
            ),
            "documents_affected": by_cause.get(
                "latex fragment parsed as a markdown link", 0
            ),
        },
        "_files": files,
    }


def measure_merge_safety(files: dict[str, bytes]) -> dict[str, Any]:
    """Merging into a user's existing vault must never lose a file silently.

    A note the user already had must come out of the merge either byte-identical,
    or renamed, or named in the conflict list. Anything else is data loss.
    """
    if len(files) < 4:
        raise ValueError("need at least four vault files to exercise a merge")

    ordered = sorted(files)
    half = len(ordered) // 2
    quarter = max(1, half // 2)
    # The vault the user already has, and the one we want to write into it, must
    # genuinely overlap, or the merge is never asked to resolve anything.
    existing = {path: files[path] for path in ordered[:half]}
    incoming = {path: files[path] for path in ordered[quarter:]}
    overlap = sorted(set(existing) & set(incoming))
    if not overlap:
        raise ValueError("merge fixture produced no overlap, so nothing is tested")

    # The user's copy of a shared note differs from ours. This is the case a
    # merge has to surface rather than silently overwrite, so the edits are
    # applied inside the overlap where the merge will actually meet them.
    edited = dict(existing)
    for path in overlap:
        edited[path] = files[path] + b"\n\n<!-- edited by the user -->\n"
    shared = overlap

    results = {}
    for policy in MergePolicy:
        plan = plan_vault_merge(edited, incoming, policy=policy)
        conflicted = {c.existing_path for c in plan.conflicts}
        lost = [
            path
            for path, content in edited.items()
            if path not in plan.files and path not in conflicted
        ]
        overwritten = [
            path
            for path, content in edited.items()
            if path in plan.files
            and plan.files[path] != content
            and path not in conflicted
        ]
        results[str(policy)] = {
            "conflicts": len(plan.conflicts),
            "safe_to_apply": plan.safe_to_apply,
            "existing_files_dropped_without_conflict": len(lost),
            "existing_files_overwritten_without_conflict": len(overwritten),
            "output_files": len(plan.files),
        }
    silent_loss = any(
        r["existing_files_dropped_without_conflict"] > 0 for r in results.values()
    )
    return {
        "existing_vault_files": len(edited),
        "incoming_files": len(incoming),
        "user_edited_files": len(shared),
        "per_policy": results,
        "any_policy_loses_a_file_silently": silent_loss,
    }


def load_documents(roots: list[Path], limit: int) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for root in roots:
        for markdown in sorted(root.rglob("markdown-repeat-1/*.md")):
            text = markdown.read_text(encoding="utf-8", errors="replace")
            if not text.strip():
                continue
            seen.setdefault(markdown.stem, text)
            if len(seen) >= limit:
                return sorted(seen.items())
    return sorted(seen.items())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prediction-root", required=True, type=Path, nargs="+")
    parser.add_argument("--documents", type=int, default=200)
    parser.add_argument("--architecture-repeats", type=int, default=5)
    parser.add_argument("--receipt", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    documents = load_documents(args.prediction_root, args.documents)
    if not documents:
        raise ValueError("no extracted documents found under the supplied roots")

    architecture = measure_architecture_determinism(args.architecture_repeats)
    vault = measure_vault_compilation(documents, wikilinks=True)
    files = vault.pop("_files")
    merge = measure_merge_safety(files) if len(files) >= 4 else None

    receipt = {
        "schema": "folynta.knowledge-compilation-properties.v1",
        "question": (
            "The public benchmarks score extraction only. What can be established "
            "about the compilation stages that follow it?"
        ),
        "why_not_an_accuracy_score": (
            "No public benchmark scores whether a corpus was organised well, and "
            "inventing one would be marking our own homework. The compilation "
            "stages are deterministic, so their properties are provable instead: "
            "reproducible architecture, no unresolved links, no silent data loss."
        ),
        "documents_sampled_from": [str(p) for p in args.prediction_root],
        "architecture_determinism": architecture,
        "vault_compilation": vault,
        "merge_safety": merge,
        "claims_supported": {
            "architecture_is_reproducible": architecture["all_plans_stable_across_repeats"],
            "blueprint_choice_is_meaningful": architecture[
                "distinct_blueprints_produce_distinct_plans"
            ],
            "a_vault_with_a_broken_link_cannot_be_emitted": vault["fail_closed"],
            "emitted_vault_has_no_unresolved_internal_links": vault[
                "broken_internal_links_in_emitted_vault"
            ]
            == 0,
            "merge_never_loses_a_file_silently": (
                merge is not None and not merge["any_policy_loses_a_file_silently"]
            ),
        },
        "interpretation_boundary": (
            "These are structural guarantees about the compiled output. They say "
            "nothing about whether the extracted text is correct, which the public "
            "benchmark results measure separately."
        ),
        "score_inflation_allowed": False,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        k: v
        for k, v in receipt.items()
        if k not in {"architecture_determinism", "vault_compilation", "merge_safety"}
    }
    summary["architecture"] = {
        k: v for k, v in architecture.items() if k != "per_blueprint"
    }
    summary["vault"] = {k: v for k, v in vault.items() if not k.startswith("_")}
    summary["merge"] = merge
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
