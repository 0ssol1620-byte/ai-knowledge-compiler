from __future__ import annotations

import pytest

from evaluate_knowledge_compilation import (
    _classify_refusal,
    _looks_like_table,
    canonical_document_from_markdown,
    measure_architecture_determinism,
    measure_merge_safety,
    measure_vault_compilation,
)


def test_document_carries_the_extracted_text_as_blocks() -> None:
    document = canonical_document_from_markdown(
        "case-1", "# Annual Report\n\nThe registrar accepted the filing.\n"
    )
    assert document.document_id == "case-1"
    assert document.title == "Annual Report"
    assert len(document.blocks) == 2
    assert document.blocks[1].raw_text == "The registrar accepted the filing."


def test_document_without_a_heading_falls_back_to_the_case_id() -> None:
    document = canonical_document_from_markdown("case-2", "Just a sentence of body text.")
    assert document.title == "case-2"


def test_empty_extraction_still_produces_a_valid_document() -> None:
    document = canonical_document_from_markdown("case-3", "   \n\n  ")
    assert len(document.blocks) == 1


def test_table_shaped_chunks_are_counted_but_not_typed_as_tables() -> None:
    markdown = "Intro paragraph.\n\n| a | b |\n| 1 | 2 |\n\nOutro."
    document = canonical_document_from_markdown("case-4", markdown)
    # Typing a block as a table without canonical table structure would let raw
    # text pose as structured data, so the count is recorded instead.
    assert document.metadata["table_shaped_chunks"] == 1
    assert all(block.type.value != "table" for block in document.blocks)


def test_looks_like_table_matches_both_pipe_and_html_forms() -> None:
    assert _looks_like_table("| a | b |")
    assert _looks_like_table("<table><tr><td>x</td></tr></table>")
    assert not _looks_like_table("ordinary prose")


def test_architecture_plans_are_stable_and_distinct() -> None:
    result = measure_architecture_determinism(repeats=3)
    assert result["all_plans_stable_across_repeats"] is True
    assert result["distinct_blueprints_produce_distinct_plans"] is True
    assert result["blueprints_measured"] >= 2
    assert result["unstable_blueprints"] == []


def test_refusal_classifier_separates_asset_gaps_from_latex_false_positives() -> None:
    asset = "generated Vault contains broken internal links: a.md -> images/abc (target_missing)"
    latex = "generated Vault contains broken internal links: a.md -> s \\otimes f (target_missing)"
    other = "generated Vault contains broken internal links: a.md -> notes/gone (target_missing)"
    assert _classify_refusal(asset)[0] == "referenced figure asset was not supplied"
    assert _classify_refusal(latex)[0] == "latex fragment parsed as a markdown link"
    assert _classify_refusal(other)[0] == "other unresolved target"


def test_clean_documents_compile_and_emit_no_broken_links() -> None:
    documents = [
        (f"case-{index}", f"# Report {index}\n\nBody text for report {index}.\n")
        for index in range(4)
    ]
    result = measure_vault_compilation(documents, wikilinks=True)
    assert result["documents_compiled"] == 4
    assert result["documents_refused_for_broken_links"] == 0
    assert result["broken_internal_links_in_emitted_vault"] == 0
    assert result["vault_files_emitted"] > 0


def test_a_document_referencing_a_missing_asset_is_refused_not_emitted() -> None:
    documents = [
        ("case-ok", "# Fine\n\nNothing unresolved here.\n"),
        ("case-bad", "# Broken\n\n![figure](images/does-not-exist.png)\n"),
    ]
    result = measure_vault_compilation(documents, wikilinks=True)
    assert result["documents_refused_for_broken_links"] == 1
    assert result["documents_compiled"] == 1
    # The refusal is the guarantee: nothing broken reaches the emitted vault.
    assert result["broken_internal_links_in_emitted_vault"] == 0
    assert result["fail_closed"] is True


def test_merge_surfaces_every_user_edit_as_a_conflict() -> None:
    documents = [
        (f"case-{index}", f"# Report {index}\n\nBody text for report {index}.\n")
        for index in range(8)
    ]
    files = measure_vault_compilation(documents, wikilinks=True)["_files"]
    result = measure_merge_safety(files)
    assert result["user_edited_files"] > 0
    for policy, outcome in result["per_policy"].items():
        assert outcome["conflicts"] == result["user_edited_files"], policy
        assert outcome["existing_files_dropped_without_conflict"] == 0, policy
        assert outcome["existing_files_overwritten_without_conflict"] == 0, policy
    assert result["any_policy_loses_a_file_silently"] is False


def test_rename_incoming_preserves_every_file_by_arithmetic() -> None:
    documents = [
        (f"case-{index}", f"# Report {index}\n\nBody text for report {index}.\n")
        for index in range(8)
    ]
    files = measure_vault_compilation(documents, wikilinks=True)["_files"]
    result = measure_merge_safety(files)
    renamed = result["per_policy"]["rename_incoming"]
    other = result["per_policy"]["keep_existing"]
    # Renaming keeps both copies, so it must emit exactly one extra file per
    # conflict. Any smaller number means a file was dropped.
    assert renamed["output_files"] == other["output_files"] + renamed["conflicts"]


def test_merge_fixture_refuses_to_run_without_overlap() -> None:
    with pytest.raises(ValueError, match="at least four vault files"):
        measure_merge_safety({"a.md": b"x"})
