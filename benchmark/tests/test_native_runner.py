from __future__ import annotations

import hashlib
import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from benchmark.run_benchmark import main as run_benchmark_main
from benchmark.runners.base import RunnerUnavailable
from benchmark.runners.native import run

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def native_pdf(text: str) -> bytes:
    writer = PdfWriter()
    font = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
    )
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    content = DecodedStreamObject()
    content.set_data(f"BT /F1 11 Tf 36 740 Td ({escaped}) Tj ET".encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(content)
    payload = io.BytesIO()
    writer.write(payload)
    return payload.getvalue()


def benchmark_case(payload: bytes, *, source_path: str = "source.pdf") -> dict:
    return {
        "benchmark_case_id": "native-real-001",
        "document_id": "urn:akmp:doc:native-real-001",
        "page_index": 0,
        "language": "en",
        "document_class": "en_native",
        "high_risk": False,
        # This deliberately differs from the file and proves the runner does
        # not copy ground truth into its candidate output.
        "text": "Ground truth must never be copied into candidate output.",
        "reading_order": ["expected-1"],
        "blocks": [
            {
                "block_id": "expected-1",
                "type": "paragraph",
                "text": "Ground truth must never be copied into candidate output.",
                "origin": "native_extracted",
                "source_refs": [{"page_index": 0, "bbox1000": [0, 0, 1000, 1000]}],
            }
        ],
        "generated_claims": [],
        "is_synthetic": False,
        "source": {
            "path": source_path,
            "filename": "source.pdf",
            "content_type": "application/pdf",
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    }


class NativeRunnerTests(unittest.TestCase):
    def test_real_source_bytes_are_parsed_without_ground_truth_copy(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = native_pdf("Actual immutable source text 42.")
            (root / "source.pdf").write_bytes(payload)
            output = run(benchmark_case(payload), corpus_root=root)

        self.assertEqual(output["provider"], "native_document")
        self.assertRegex(output["model_revision"], r"^[0-9a-f]{64}$")
        self.assertIn("Actual immutable source text 42", output["text"])
        self.assertNotIn("Ground truth must never", output["text"])
        self.assertEqual(output["source_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(output["blocks"][0]["source_refs"][0]["page_index"], 0)
        self.assertGreater(output["metrics"]["latency_ms"], 0)

    def test_source_path_cannot_escape_approved_corpus_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = native_pdf("Bounded source.")
            case = benchmark_case(payload, source_path="../outside.pdf")
            with self.assertRaisesRegex(RunnerUnavailable, "unsafe"):
                run(case, corpus_root=root)

    def test_cli_persists_hashed_raw_result_and_internal_claim_class(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = native_pdf("Actual benchmark source.")
            (root / "source.pdf").write_bytes(payload)
            truth = root / "truth.jsonl"
            truth.write_text(
                json.dumps(benchmark_case(payload), sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            output = root / "scores.jsonl"
            raw = root / "raw"
            arguments = [
                "run_benchmark.py",
                "--manifest",
                str(REPOSITORY_ROOT / "benchmark" / "manifest.yaml"),
                "--ground-truth",
                str(truth),
                "--provider",
                "native_document",
                "--corpus-root",
                str(root),
                "--raw-output-dir",
                str(raw),
                "--output",
                str(output),
            ]
            with patch.object(sys, "argv", arguments):
                self.assertEqual(run_benchmark_main(), 0)
            record = json.loads(output.read_text(encoding="utf-8"))
            raw_result = raw / "native-real-001" / "native_document.json"

            self.assertEqual(record["claim_class"], "internal_result")
            self.assertTrue(raw_result.is_file())
            digest = "sha256:" + hashlib.sha256(raw_result.read_bytes()).hexdigest()
            self.assertEqual(record["reproducibility"]["raw_result_sha256"], digest)
            self.assertEqual(
                record["reproducibility"]["source_sha256"],
                f"sha256:{hashlib.sha256(payload).hexdigest()}",
            )


if __name__ == "__main__":
    unittest.main()
