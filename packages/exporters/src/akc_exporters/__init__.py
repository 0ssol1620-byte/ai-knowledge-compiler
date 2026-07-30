"""Deterministic compilers from CIR to portable output profiles."""

from .chunks import Tokenizer, UnicodeEstimateTokenizer, adaptive_chunks
from .filenames import (
    collision_key,
    portable_slug,
    stable_markdown_filename,
    with_collision_suffix,
)
from .jsonld import (
    AKMP_CONTEXT,
    KNOWLEDGE_NOTE_SHACL,
    chunks_jsonl,
    context_jsonld,
    documents_jsonl,
    knowledge_jsonld,
)
from .markdown import (
    MarkdownArtifact,
    MarkdownExportOptions,
    export_markdown,
    source_map_json,
)
from .package import deterministic_zip
from .tables import table_to_csv, table_to_gfm, table_to_html
from .vault import (
    BrokenVaultLink,
    MergePolicy,
    VaultConflict,
    VaultMergePlan,
    compile_vault,
    plan_vault_merge,
    validate_internal_links,
)

__all__ = [
    "AKMP_CONTEXT",
    "KNOWLEDGE_NOTE_SHACL",
    "BrokenVaultLink",
    "MarkdownArtifact",
    "MarkdownExportOptions",
    "MergePolicy",
    "Tokenizer",
    "UnicodeEstimateTokenizer",
    "VaultConflict",
    "VaultMergePlan",
    "adaptive_chunks",
    "chunks_jsonl",
    "collision_key",
    "compile_vault",
    "context_jsonld",
    "deterministic_zip",
    "documents_jsonl",
    "export_markdown",
    "knowledge_jsonld",
    "plan_vault_merge",
    "portable_slug",
    "source_map_json",
    "stable_markdown_filename",
    "table_to_csv",
    "table_to_gfm",
    "table_to_html",
    "validate_internal_links",
    "with_collision_suffix",
]
