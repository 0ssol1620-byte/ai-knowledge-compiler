from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from benchmark.evaluators.metrics import (
    character_error_rate,
    date_unit_exact_match,
    formula_normalized_edit_score,
    heading_tree_score,
    numeric_exact_match,
    provenance_coverage,
    reading_order_pair_accuracy,
    score_case,
    table_cell_exactness,
    table_structure_similarity,
    unsupported_claim_rate,
    valid_bbox1000,
)

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "schemas"
SOURCE_REFS = [{"page_index": 0, "bbox1000": [10, 10, 990, 990]}]


def table_fixture(*, second_value: str = "10 kg") -> dict:
    return {
        "row_count": 2,
        "column_count": 2,
        "header_row_count": 1,
        "cells": [
            {
                "row_index0": 0,
                "column_index0": 0,
                "row_span": 1,
                "column_span": 1,
                "text": "Item",
            },
            {
                "row_index0": 0,
                "column_index0": 1,
                "row_span": 1,
                "column_span": 1,
                "text": "Amount",
            },
            {
                "row_index0": 1,
                "column_index0": 0,
                "row_span": 1,
                "column_span": 1,
                "text": "A",
            },
            {
                "row_index0": 1,
                "column_index0": 1,
                "row_span": 1,
                "column_span": 1,
                "text": second_value,
            },
        ],
    }


def block_fixture(
    block_id: str,
    block_type: str,
    text: str,
    **structured: object,
) -> dict:
    return {
        "block_id": block_id,
        "type": block_type,
        "text": text,
        "origin": "rule_reconstructed",
        "source_refs": copy.deepcopy(SOURCE_REFS),
        **structured,
    }


def structured_case() -> dict:
    blocks = [
        block_fixture("h1", "heading", "Dosage", heading_level=1),
        block_fixture("t1", "table", "Item | Amount\nA | 10 kg", table=table_fixture()),
        block_fixture("f1", "formula", "x + y", formula_latex=r"\left(x+y\right)"),
    ]
    return {
        "benchmark_case_id": "structured-001",
        "document_id": "urn:akmp:doc:structured-001",
        "page_index": 0,
        "language": "en",
        "document_class": "tables",
        "high_risk": True,
        "text": "Dosage on 2026-07-29 is 10 kg. x + y.",
        "reading_order": ["h1", "t1", "f1"],
        "blocks": blocks,
        "heading_outline": [{"level": 1, "text": "Dosage"}],
        "date_unit_annotations": {"dates": ["2026-07-29"], "units": ["kg"]},
        "generated_claims": [],
        "is_synthetic": True,
    }


def parser_output(case: dict) -> dict:
    return {
        "schema_version": "1.0",
        "benchmark_case_id": case["benchmark_case_id"],
        "provider": "local_mock",
        "model_revision": "1" * 40,
        "text": case["text"],
        "reading_order": copy.deepcopy(case["reading_order"]),
        "blocks": copy.deepcopy(case["blocks"]),
        "heading_outline": copy.deepcopy(case["heading_outline"]),
        "date_unit_annotations": copy.deepcopy(case["date_unit_annotations"]),
        "generated_claims": [],
        "metrics": {},
        "warnings": [],
    }


class CoreMetricsTests(unittest.TestCase):
    def test_exact_text_has_zero_cer(self) -> None:
        self.assertEqual(character_error_rate("한글 42", "한글 42"), 0.0)

    def test_numeric_sequence_is_exact_and_unit_independent(self) -> None:
        self.assertEqual(numeric_exact_match("1,000 kg and 20%", "1000 g and 20 %"), 1.0)
        self.assertEqual(numeric_exact_match("10, 20", "20, 10"), 0.0)

    def test_reading_order_scores_pairs(self) -> None:
        self.assertEqual(
            reading_order_pair_accuracy(["a", "b", "c"], ["a", "b", "c"]),
            1.0,
        )
        self.assertAlmostEqual(
            reading_order_pair_accuracy(["a", "b", "c"], ["b", "a", "c"]),
            2 / 3,
        )

    def test_bbox1000_is_integer_and_non_degenerate(self) -> None:
        self.assertTrue(valid_bbox1000([0, 1, 999, 1000]))
        self.assertFalse(valid_bbox1000([0.0, 1, 999, 1000]))
        self.assertFalse(valid_bbox1000([10, 10, 10, 20]))

    def test_provenance_requires_every_block(self) -> None:
        blocks = [
            {"source_refs": [{"bbox1000": [0, 0, 100, 100]}]},
            {"source_refs": []},
        ]
        self.assertEqual(provenance_coverage(blocks), 0.5)

    def test_claim_support_is_subset(self) -> None:
        claims = [{"source_block_ids": ["b1"]}, {"source_block_ids": ["missing"]}]
        self.assertEqual(unsupported_claim_rate(claims, ["b1"]), 0.5)


class StructuredMetricTests(unittest.TestCase):
    def test_table_structure_is_text_independent_but_cells_are_exact(self) -> None:
        reference = [table_fixture()]
        candidate = [table_fixture(second_value="11 kg")]
        self.assertEqual(table_structure_similarity(reference, candidate), 1.0)
        self.assertEqual(table_cell_exactness(reference, candidate), 0.75)

    def test_table_structure_detects_spans_and_missing_tables(self) -> None:
        reference = [table_fixture()]
        merged = table_fixture()
        merged["cells"] = [
            {
                "row_index0": 0,
                "column_index0": 0,
                "row_span": 1,
                "column_span": 2,
                "text": "Item Amount",
            },
            *merged["cells"][2:],
        ]
        structure_score = table_structure_similarity(reference, [merged])
        self.assertIsNotNone(structure_score)
        self.assertGreater(structure_score or 0.0, 0.0)
        self.assertLess(structure_score or 1.0, 1.0)
        self.assertEqual(table_structure_similarity(reference, []), 0.0)
        self.assertEqual(table_cell_exactness(reference, []), 0.0)

    def test_table_scores_penalize_extra_or_missing_tables_by_order(self) -> None:
        reference = [table_fixture(), table_fixture()]
        self.assertEqual(table_structure_similarity(reference, [table_fixture()]), 0.5)
        self.assertEqual(table_cell_exactness(reference, [table_fixture()]), 0.5)
        self.assertEqual(
            table_structure_similarity([table_fixture()], [table_fixture(), table_fixture()]),
            0.5,
        )

    def test_invalid_reference_table_is_unavailable(self) -> None:
        invalid = table_fixture()
        invalid["cells"][1]["column_index0"] = 0
        self.assertIsNone(table_structure_similarity([invalid], [table_fixture()]))
        self.assertIsNone(table_cell_exactness([invalid], [table_fixture()]))

    def test_formula_normalization_and_count_penalty(self) -> None:
        self.assertEqual(
            formula_normalized_edit_score(
                [r"\left( x + y \right)"],
                ["$$(x+y)$$"],
            ),
            1.0,
        )
        self.assertEqual(
            formula_normalized_edit_score(
                [r"a \times b"],
                ["a \N{MULTIPLICATION SIGN} b"],
            ),
            1.0,
        )
        self.assertEqual(
            formula_normalized_edit_score(["x+y"], ["x+y", "z"]),
            0.5,
        )
        changed = formula_normalized_edit_score(["x+y"], ["x-y"])
        self.assertIsNotNone(changed)
        self.assertGreater(changed or 0.0, 0.0)
        self.assertLess(changed or 1.0, 1.0)
        self.assertEqual(formula_normalized_edit_score(["x+y"], []), 0.0)
        self.assertIsNone(formula_normalized_edit_score([], []))

    def test_heading_score_combines_level_and_label_edit_cost(self) -> None:
        reference = [{"level": 1, "text": "A"}, {"level": 2, "text": "Details"}]
        self.assertEqual(heading_tree_score(reference, copy.deepcopy(reference)), 1.0)
        wrong_level = [{"level": 1, "text": "A"}, {"level": 3, "text": "Details"}]
        self.assertEqual(heading_tree_score(reference, wrong_level), 0.75)
        label_edit = heading_tree_score(
            reference,
            [{"level": 1, "text": "A"}, {"level": 2, "text": "Detail"}],
        )
        self.assertIsNotNone(label_edit)
        self.assertGreater(label_edit or 0.0, 0.75)
        self.assertLess(label_edit or 1.0, 1.0)
        self.assertEqual(heading_tree_score(reference, []), 0.0)
        self.assertIsNone(heading_tree_score([], []))

    def test_date_and_unit_annotations_are_exact_and_numeric_independent(self) -> None:
        reference = {"dates": ["2026-07-29"], "units": ["mg"]}
        same = {"dates": ["  2026-07-29 "], "units": ["mg"]}
        different_unit = {"dates": ["2026-07-29"], "units": ["g"]}
        self.assertEqual(date_unit_exact_match(reference, same), 1.0)
        self.assertEqual(date_unit_exact_match(reference, different_unit), 0.0)
        self.assertEqual(date_unit_exact_match(reference, {"dates": ["2026-07-29"]}), 0.0)
        self.assertIsNone(date_unit_exact_match(None, different_unit))


class ScoreCaseTests(unittest.TestCase):
    def test_score_case_wires_all_structured_evaluators(self) -> None:
        truth = structured_case()
        output = parser_output(truth)
        metrics, failures = score_case(
            truth,
            output,
            {"latency_ms": 12, "normalized_speed": 0.8},
        )
        for name in (
            "table_teds",
            "table_cell_exactness",
            "formula_edit_score",
            "heading_tree_score",
            "numeric_exact_match",
            "date_unit_exact_match",
        ):
            self.assertEqual(metrics[name], 1.0, name)
        self.assertEqual(metrics["latency_ms"], 12.0)
        self.assertEqual(metrics["normalized_speed"], 0.8)
        self.assertEqual(failures, [])

    def test_missing_reference_annotations_remain_unavailable(self) -> None:
        truth = {
            "high_risk": False,
            "text": "Plain prose",
            "reading_order": ["h1"],
            "blocks": [block_fixture("h1", "heading", "Plain prose")],
        }
        output = {
            "text": "Plain prose",
            "reading_order": ["h1"],
            "blocks": copy.deepcopy(truth["blocks"]),
            "generated_claims": [],
        }
        metrics, _ = score_case(truth, output)
        for name in (
            "table_teds",
            "table_cell_exactness",
            "formula_edit_score",
            "heading_tree_score",
            "numeric_exact_match",
            "date_unit_exact_match",
        ):
            self.assertIsNone(metrics[name], name)

    def test_annotated_structure_missing_from_output_scores_zero(self) -> None:
        truth = structured_case()
        output = parser_output(truth)
        output["blocks"] = [
            block_fixture("p1", "paragraph", "unstructured output"),
        ]
        output.pop("heading_outline")
        output.pop("date_unit_annotations")
        metrics, failures = score_case(truth, output)
        self.assertEqual(metrics["table_teds"], 0.0)
        self.assertEqual(metrics["table_cell_exactness"], 0.0)
        self.assertEqual(metrics["formula_edit_score"], 0.0)
        self.assertEqual(metrics["heading_tree_score"], 0.0)
        self.assertEqual(metrics["date_unit_exact_match"], 0.0)
        self.assertIn("severe_table_error", failures)
        self.assertIn("high_risk_date_unit_below_threshold", failures)

    def test_quality_metrics_cannot_be_overridden_by_runtime_payload(self) -> None:
        truth = structured_case()
        output = parser_output(truth)
        metrics, _ = score_case(
            truth,
            output,
            {
                "table_teds": 0.0,
                "formula_edit_score": 0.0,
                "latency_ms": 9.0,
            },
        )
        self.assertEqual(metrics["table_teds"], 1.0)
        self.assertEqual(metrics["formula_edit_score"], 1.0)
        self.assertEqual(metrics["latency_ms"], 9.0)

    def test_high_risk_numeric_and_unit_mismatches_hard_fail_separately(self) -> None:
        truth = structured_case()
        output = parser_output(truth)
        output["text"] = output["text"].replace("10 kg", "11 g")
        output["date_unit_annotations"]["units"] = ["g"]
        _, failures = score_case(truth, output)
        self.assertIn("high_risk_numeric_below_threshold", failures)
        self.assertIn("high_risk_date_unit_below_threshold", failures)

    def test_severe_table_threshold_is_strictly_below_half(self) -> None:
        truth = structured_case()
        truth["high_risk"] = False
        two_cell_table = {
            "row_count": 1,
            "column_count": 2,
            "header_row_count": 0,
            "cells": table_fixture()["cells"][:2],
        }
        for index, cell in enumerate(two_cell_table["cells"]):
            cell["row_index0"] = 0
            cell["column_index0"] = index
        truth["blocks"][1]["table"] = two_cell_table
        output = parser_output(truth)
        output["blocks"][1]["table"]["cells"][1]["text"] = "changed"
        metrics, failures = score_case(truth, output)
        self.assertEqual(metrics["table_teds"], 1.0)
        self.assertEqual(metrics["table_cell_exactness"], 0.5)
        self.assertNotIn("severe_table_error", failures)


class BenchmarkSchemaTests(unittest.TestCase):
    def test_schemas_publish_structured_inputs_and_metric_semantics(self) -> None:
        page_schema = json.loads(
            (SCHEMA_DIR / "page-ground-truth.schema.json").read_text(encoding="utf-8")
        )
        output_schema = json.loads(
            (SCHEMA_DIR / "parser-output.schema.json").read_text(encoding="utf-8")
        )
        score_schema = json.loads(
            (SCHEMA_DIR / "score-record.schema.json").read_text(encoding="utf-8")
        )
        page_properties = page_schema["properties"]
        block_properties = page_schema["$defs"]["block"]["properties"]
        output_properties = output_schema["properties"]
        metric_contract = score_schema["properties"]["metrics"]

        self.assertIn("date_unit_annotations", page_properties)
        self.assertIn("heading_outline", page_properties)
        self.assertIn("token_annotations", page_properties)
        self.assertIn("knowledge_evaluation", page_properties)
        self.assertIn("rag_evaluation", page_properties)
        self.assertIn("router_evaluation", page_properties)
        self.assertIn("table", block_properties)
        self.assertIn("formula_latex", block_properties)
        self.assertIn("heading_level", block_properties)
        self.assertIn("caption_for_block_id", block_properties)
        self.assertIn("date_unit_annotations", output_properties)
        self.assertIn("heading_outline", output_properties)
        self.assertIn("verified_human_metrics", output_properties)
        self.assertEqual(
            score_schema["properties"]["evaluator_version"]["const"],
            "22.4-22.8-v1.0.0",
        )
        self.assertFalse(metric_contract["additionalProperties"])
        for name in (
            "table_teds",
            "table_cell_exactness",
            "formula_edit_score",
            "heading_tree_score",
            "date_unit_exact_match",
        ):
            self.assertIn(name, metric_contract["required"])
            self.assertTrue(metric_contract["properties"][name]["description"])
        for name in (
            "hangul_jamo_corruption_rate",
            "block_type_macro_f1_iou50",
            "rag_ndcg_at_10",
            "router_route_regret",
            "router_cost_per_page_by_class",
        ):
            self.assertIn(name, metric_contract["required"])
            self.assertIn(name, metric_contract["properties"])

    def test_extended_annotations_and_score_record_validate(self) -> None:
        page_schema = json.loads(
            (SCHEMA_DIR / "page-ground-truth.schema.json").read_text(encoding="utf-8")
        )
        output_schema = json.loads(
            (SCHEMA_DIR / "parser-output.schema.json").read_text(encoding="utf-8")
        )
        score_schema = json.loads(
            (SCHEMA_DIR / "score-record.schema.json").read_text(encoding="utf-8")
        )
        truth = structured_case()
        truth.update(
            {
                "token_annotations": {
                    "dates": ["2026-07-29"],
                    "units": ["kg"],
                    "versions": ["v1"],
                },
                "multi_page_table_merges": [["t1", "t2"]],
                "knowledge_evaluation": {"notes": [{"source_block_ids": ["h1"]}]},
                "rag_evaluation": {
                    "queries": [
                        {
                            "query_id": "q1",
                            "relevant_ids": ["h1"],
                            "unanswerable": False,
                        }
                    ]
                },
                "router_evaluation": {"pages": []},
            }
        )
        Draft202012Validator(page_schema).validate(truth)

        output = parser_output(truth)
        for name in (
            "token_annotations",
            "multi_page_table_merges",
            "knowledge_evaluation",
            "rag_evaluation",
            "router_evaluation",
        ):
            output[name] = copy.deepcopy(truth[name])
        output["verified_human_metrics"] = {
            "title_quality_human_score": {
                "value": 0.75,
                "reviewer_count": 2,
                "rubric_version": "rubric-1",
                "evidence_sha256": "sha256:" + "a" * 64,
            }
        }
        registry = Registry().with_resource(
            page_schema["$id"],
            Resource.from_contents(page_schema),
        )
        Draft202012Validator(output_schema, registry=registry).validate(output)

        metrics, hard_failures = score_case(truth, output)
        Draft202012Validator(score_schema).validate(
            {
                "benchmark_id": "test",
                "evaluator_version": "22.4-22.8-v1.0.0",
                "corpus_version": "test",
                "benchmark_case_id": truth["benchmark_case_id"],
                "provider": output["provider"],
                "model_revision": output["model_revision"],
                "claim_class": "contract_test",
                "is_synthetic": True,
                "metrics": metrics,
                "utility": None,
                "hard_failures": hard_failures,
                "reproducibility": {
                    "started_at": "2026-07-29T00:00:00Z",
                    "finished_at": "2026-07-29T00:00:01Z",
                    "input_sha256": "sha256:" + "b" * 64,
                    "prompt_schema_version": "benchmark-contract-1.0",
                },
            }
        )


if __name__ == "__main__":
    unittest.main()
