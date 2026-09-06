"""Fixed synthetic qualification for Product-Core multilingual retrieval.

This is a regression fixture, not an external benchmark or a claim about
customer-corpus quality. It compares the shipped adaptive materialized signals
with an exact-token baseline over a preregistered mixed-language mini-corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    ROOT / "packages" / "cir-python" / "src",
    ROOT / "packages" / "product-core" / "src",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from akc_product_core.retrieval import (  # noqa: E402
    rank_exact_token_baseline,
    rank_semantic_candidates,
    retrieval_candidates,
)
from akc_product_core.semantics import SemanticSource, compile_semantics  # noqa: E402

_CORPUS = {
    "a-distractor": "Unrelated operational memo for archive retention.",
    "b-informal": "Security policy requires a quarterly access review.",
    "v-entity": "TAVONEL Research Institute published an audit.",
    "w-research": "이 연구는 공개 데이터셋을 사용해 모델을 평가했다.",
    "x-security": "Security policy requires a quarterly access review.",
    "y-legal": "The Agreement termination period is 30 days.",
    "z-finance": "Revenue increased during the 2025 fiscal quarter.",
}
_AUTHORITIES = {"b-informal": "informal"}
_QUERIES = (
    ("2025 매출 증가", "z-finance"),
    ("계약 해지 기간", "y-legal"),
    ("research dataset", "w-research"),
    ("security policy", "x-security"),
    ("TAVONEL", "v-entity"),
)


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode()


def run_qualification() -> dict[str, Any]:
    fixture_payload = {
        "corpus": _CORPUS,
        "authorities": _AUTHORITIES,
        "queries": _QUERIES,
    }
    semantics = compile_semantics(
        tuple(
            SemanticSource(
                logical_id=logical_id,
                source_id=f"source-{logical_id}",
                source_version_id=f"version-{logical_id}",
                evidence_id=f"evidence-{logical_id}",
                text=text,
                authority=_AUTHORITIES.get(logical_id, "official"),
            )
            for logical_id, text in _CORPUS.items()
        )
    )
    candidates = retrieval_candidates(semantics)
    cases: list[dict[str, object]] = []
    baseline_hits = 0
    adaptive_hits = 0
    for query, expected in _QUERIES:
        baseline = rank_exact_token_baseline(query, candidates, top_k=1)[0]
        adaptive = rank_semantic_candidates(query, candidates, top_k=1)[0]
        baseline_correct = baseline == expected
        adaptive_correct = adaptive.logical_id == expected
        baseline_hits += baseline_correct
        adaptive_hits += adaptive_correct
        cases.append(
            {
                "query": query,
                "expectedLogicalId": expected,
                "baselineTop1": baseline,
                "baselineCorrect": baseline_correct,
                "adaptiveTop1": adaptive.logical_id,
                "adaptiveCorrect": adaptive_correct,
                "adaptiveScore": adaptive.as_record(),
            }
        )
    count = len(_QUERIES)
    baseline_precision = baseline_hits / count
    adaptive_precision = adaptive_hits / count
    algorithm_files = (
        ROOT / "packages" / "product-core" / "src" / "akc_product_core" / "semantics.py",
        ROOT / "packages" / "product-core" / "src" / "akc_product_core" / "retrieval.py",
    )
    return {
        "schemaVersion": "tavonel.product_core_semantic_qualification.v1",
        "qualificationDate": "2026-08-29",
        "scope": "fixed_synthetic_mixed_language_regression",
        "externalGeneralizationClaim": False,
        "corpusDocuments": len(_CORPUS),
        "queries": count,
        "fixtureSha256": _sha256(_canonical(fixture_payload)),
        "algorithmSha256": {path.name: _sha256(path.read_bytes()) for path in algorithm_files},
        "baseline": {
            "name": "exact_token_overlap_v1",
            "top1Correct": baseline_hits,
            "precisionAt1": baseline_precision,
        },
        "candidate": {
            "name": "adaptive_multilingual_lexical_graph_authority_v1",
            "top1Correct": adaptive_hits,
            "precisionAt1": adaptive_precision,
            "absoluteDelta": adaptive_precision - baseline_precision,
            "vectorMaterialization": "not_used_in_provider_free_qualification",
        },
        "cases": cases,
        "qualification": {
            "status": "passed"
            if adaptive_hits == count and adaptive_hits > baseline_hits
            else "failed",
            "required": {
                "allCandidateTop1Correct": True,
                "strictImprovementOverBaseline": True,
            },
        },
        "limitations": [
            "synthetic fixture only",
            "the fixed query set is not a customer-corpus estimate",
            "no embedding provider or generative answer model is exercised",
            "human promotion and semantic acceptance remain separate gates",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT
        / "benchmark"
        / "reports"
        / "generated"
        / "product-core-semantic-qualification-2026-08-29.json",
    )
    args = parser.parse_args()
    report = run_qualification()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    )
    print(json.dumps({"output": str(args.output), **report["qualification"]}, ensure_ascii=False))
    return 0 if report["qualification"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
