"""Bounded Markdown remaining-state extraction; executable with stdlib unittest.

These cases check retained source text and parser metadata, not the truth of a
statement or downstream semantic accuracy. No provider or customer calls occur.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from akc_compiler_runtime import Pipeline
from akc_compiler_runtime.extraction import (
    PARSER_CACHE_VERSION,
    UNMAPPED_ACL,
    AuthorityClass,
    ParsedDocument,
    ParsedFile,
    SourceStatus,
    TemporalSource,
    anchored_evidence_id,
    parse_file,
    parsed_document_from_record,
    parsed_document_record,
)


def _parse(text: str, rel_path: str = "policies/availability.md") -> ParsedDocument:
    file = ParsedFile(
        rel_path=rel_path,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )
    return parse_file(file, tenant_id="remaining-state-test")


class TestDocumentRemainingStateExtraction(unittest.TestCase):
    def test_present_statement_retains_text_section_line_and_evidence_anchor(self) -> None:
        statement = "The shared entity Lantern remains available through October 2026."
        text = f"# Shared Entity\n\n## Availability\n\n{statement}\n"
        document = _parse(text)
        self.assertEqual(len(document.claims), 1)
        claim = document.claims[0]
        self.assertEqual(claim.text, statement)
        self.assertEqual(
            claim.anchor, "the shared entity lantern remains available through october 2026"
        )
        self.assertEqual(claim.line_number, 5)
        self.assertEqual(claim.section_path, ("policies", "shared entity", "availability"))
        self.assertEqual(claim.subject, "availability")
        self.assertEqual(claim.kind, "fact")
        self.assertEqual(document.authority, AuthorityClass.OFFICIAL)
        evidence = anchored_evidence_id(
            document_version=document.document_version, text=claim.text, line_number=5
        )
        repeated = _parse(text)
        self.assertEqual(repeated, document)
        self.assertEqual(
            anchored_evidence_id(
                document_version=repeated.document_version,
                text=repeated.claims[0].text,
                line_number=repeated.claims[0].line_number,
            ),
            evidence,
        )
        self.assertNotEqual(
            anchored_evidence_id(
                document_version=document.document_version, text=claim.text, line_number=6
            ),
            evidence,
        )

    def test_singular_plural_and_case_are_retained(self) -> None:
        statements = (
            "The shared entity remains available.",
            "The shared entities remain available.",
            "The shared entity REMAINS unavailable.",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                self.assertEqual([c.text for c in _parse(statement).claims], [statement])

    def test_negative_and_qualified_text_is_not_reinterpreted(self) -> None:
        statements = (
            "The shared entity does not remain available.",
            "The shared entity remains not available.",
            "The shared entity remains available only if approval arrives.",
            "The shared entity may remain available pending review.",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                document = _parse(statement)
                self.assertEqual(len(document.claims), 1)
                claim = document.claims[0]
                self.assertEqual(claim.text, statement)
                self.assertEqual(claim.kind, "fact")
                self.assertEqual(claim.source_status, SourceStatus.ACTIVE)
                self.assertEqual(claim.temporal_source, TemporalSource.UNKNOWN)
                self.assertIsNone(claim.valid_from)
                self.assertIsNone(claim.valid_to)
                self.assertIsNone(claim.recorded_at)

    def test_common_nouns_word_fragments_and_nonclaim_prose_stay_unextracted(self) -> None:
        statements = (
            "The remains of the old bridge beside the river.",
            "The remains from yesterday beside the river.",
            "The remains were carefully collected.",
            "The remains have archaeological significance.",
            "The archived remains.",
            "A note about remaining availability.",
            "A note about pre_remains_available terminology.",
            "A retrospective about last autumn.",
            "# The shared entity remains available",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                self.assertEqual(_parse(statement).claims, ())

    def test_incomplete_or_unstated_dates_stay_unknown(self) -> None:
        for suffix in ("", " through October 2026", " until October 2026", " until TBD"):
            with self.subTest(suffix=suffix):
                statement = f"The shared entity remains available{suffix}."
                document = _parse(statement)
                self.assertEqual(len(document.claims), 1)
                claim = document.claims[0]
                self.assertEqual(claim.text, statement)
                self.assertEqual(claim.temporal_source, TemporalSource.UNKNOWN)
                self.assertIsNone(claim.valid_from)
                self.assertIsNone(claim.valid_to)
                self.assertIsNone(claim.recorded_at)

    def test_existing_explicit_date_rule_still_applies(self) -> None:
        statement = "The shared entity remains available until October 15, 2026."
        document = _parse(statement)
        self.assertEqual(len(document.claims), 1)
        claim = document.claims[0]
        self.assertEqual(claim.text, statement)
        self.assertEqual(claim.valid_to, datetime(2026, 10, 15, tzinfo=UTC))
        self.assertEqual(claim.temporal_source, TemporalSource.EXPLICIT)
        self.assertIsNone(claim.valid_from)

    def test_acl_and_authority_metadata_are_preserved(self) -> None:
        statement = "The shared entity remains available pending review."
        cases = (
            ("", None),
            ("---\nrequired_permission: entity.read\n---\n", "entity.read"),
            ("---\nrequired_permission: [entity.read]\n---\n", UNMAPPED_ACL),
        )
        for frontmatter, permission in cases:
            with self.subTest(permission=permission):
                document = _parse(frontmatter + "Authority: contractual\n" + statement)
                self.assertEqual(document.required_permission, permission)
                self.assertEqual(document.authority, AuthorityClass.CONTRACTUAL)
                self.assertEqual([c.text for c in document.claims], [statement])

    def test_code_comments_and_existing_markdown_verbs_are_unchanged(self) -> None:
        remaining = "The shared entity remains available pending review."
        existing = "The nearby entity is available pending review."
        code = _parse(f"# {remaining}\n# {existing}\n", "notes/availability.py")
        self.assertEqual([c.text for c in code.claims], [existing])
        markdown = _parse(f"{remaining}\n{existing}\n")
        self.assertEqual([c.text for c in markdown.claims], [remaining, existing])
        self.assertEqual([c.line_number for c in markdown.claims], [1, 2])

    def test_retained_statement_roundtrips_through_parser_record(self) -> None:
        document = _parse("# Availability\nThe shared entity remains available.\n")
        self.assertEqual(len(document.claims), 1)
        record = parsed_document_record(document)
        restored = parsed_document_from_record(
            record, document.file, tenant_id="remaining-state-test"
        )
        self.assertEqual(restored, document)

    def test_parser_context_disallows_schema_one_cache_for_new_fixture(self) -> None:
        self.assertGreater(PARSER_CACHE_VERSION, 1)
        with tempfile.TemporaryDirectory(prefix="remaining-state-cache-") as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            statement = "The shared entity remains available pending review."
            (source / "availability.md").write_text(statement + "\n", encoding="utf-8")
            pipeline = Pipeline(root / "store")
            result = pipeline.compile_workspace(source)
            self.assertTrue(result.published)
            world = pipeline.store.load_world()
            self.assertIsNotNone(world)
            assert world is not None
            context = pipeline._parser_context()
            self.assertEqual(context["parser_schema"], PARSER_CACHE_VERSION)
            current = pipeline.store.load_parsed_cache(world, context=context)
            self.assertEqual(current["availability.md"]["claims"][0]["text"], statement)
            legacy_context = {**context, "parser_schema": 1}
            self.assertEqual(pipeline.store.load_parsed_cache(world, context=legacy_context), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
