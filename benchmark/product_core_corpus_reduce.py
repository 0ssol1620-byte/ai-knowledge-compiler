"""Split/whole equivalence benchmark for Product-Core `corpus_reduce` (ADR-008, B3 gate).

For each corpus and each split strategy: compile the whole corpus once, compile every part,
reduce the parts, and compare the two canonical forms. The gate is 100%: one divergent case
fails it. A negative control (a naive concatenating "reduce") must be *detected* as divergent,
or the comparator is not trusted and the run fails too.

The built-in corpora are synthetic regression fixtures, not evidence about customer documents.
A real corpus is a JSON file `{"documents": [<ProductCoreDocument wire objects>]}` passed with
`--corpus`; keep it and its receipt under `outputs/` (never committed).

    python benchmark/product_core_corpus_reduce.py --synthetic --out <receipt.json>
    python benchmark/product_core_corpus_reduce.py --corpus <corpus.json> --out <receipt.json>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for source_root in (
    ROOT / "packages" / "cir-python" / "src",
    ROOT / "packages" / "domain-packs" / "src",
    ROOT / "packages" / "product-core" / "src",
):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from akc_cir.base import canonical_json, sha256_digest  # noqa: E402
from akc_cir.models import BBox1000, BlockType  # noqa: E402
from akc_product_core.compiler import ProductCoreCompiler, wire_payload  # noqa: E402
from akc_product_core.contracts import (  # noqa: E402
    BlueprintId,
    ProductCoreCompileRequest,
    ProductCoreDocument,
    ProductCoreRegion,
    ProductCoreRoute,
)
from akc_product_core.corpus_reduce import (  # noqa: E402
    ReducePart,
    canonical_form_of_compile,
    canonical_form_of_corpus_world,
    corpus_reduce,
)

RECEIPT_SCHEMA = "tavonel.product_core.corpus_reduce_equivalence.v1"
RELEASE = "sha256:" + "b3" * 32
TENANT = "tenant-corpus-reduce-bench"
WORKSPACE = "workspace-corpus-reduce-bench"
COLLECTION = "collection-corpus-reduce-bench"
T0 = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)

Split = list[list[int]]


# --- split strategies -----------------------------------------------------------------------


def _contiguous(n: int, k: int) -> Split:
    size, extra = divmod(n, k)
    parts, start = [], 0
    for index in range(k):
        end = start + size + (1 if index < extra else 0)
        parts.append(list(range(start, end)))
        start = end
    return parts


def split_strategies(n: int) -> dict[str, tuple[Split, bool]]:
    """name -> (parts as indexes into the key-sorted documents, pass parts reversed?)."""
    strategies: dict[str, tuple[Split, bool]] = {
        # Foundation's own partition (corpus-batching.ts): sorted, full parts of twelve.
        "foundation-12": ([list(range(s, min(s + 12, n))) for s in range(0, n, 12)], False),
    }
    for k in (2, 3, 4, 6):
        if k <= n:
            strategies[f"contiguous-k{k}"] = (_contiguous(n, k), False)
    if n >= 3:
        # Non-contiguous: every neighbouring pair of documents straddles a seam.
        strategies["interleaved-k2"] = ([list(range(0, n, 2)), list(range(1, n, 2))], False)
        strategies["interleaved-k3"] = ([list(range(r, n, 3)) for r in range(3)], False)
        strategies["reversed-input-k3"] = (_contiguous(n, 3), True)
        # Overlap: each part also carries the next part's first document (identical union).
        base = _contiguous(n, 3)
        strategies["overlap-k3"] = (
            [part + base[i + 1][:1] if i + 1 < len(base) else part for i, part in enumerate(base)],
            False,
        )
    if n >= 2:
        strategies["singletons"] = ([[i] for i in range(n)], False)
    return strategies


# --- compile helpers ------------------------------------------------------------------------


def _key(document: ProductCoreDocument) -> tuple[str, str]:
    return (document.connector_type, document.native_id)


def compile_wire(
    compiler: ProductCoreCompiler,
    documents: Sequence[ProductCoreDocument],
    *,
    request_id: str,
    requested_at: datetime,
    blueprint: BlueprintId | None = None,
) -> tuple[ProductCoreCompileRequest, str, dict[str, Any]]:
    request = ProductCoreCompileRequest(
        request_id=request_id,
        idempotency_key=f"idem-{request_id}",
        tenant_id=TENANT,
        workspace_id=WORKSPACE,
        collection_id=COLLECTION,
        requested_at=requested_at,
        requested_blueprint=blueprint,
        route=ProductCoreRoute(
            operation_class="initial_compile",
            quality_requirement="standard",
            max_cost_credits=100,
            max_latency_ms=60_000,
            privacy_policy="foundation_synthetic_only",
        ),
        documents=tuple(documents),
    )
    body = canonical_json(request.model_dump(mode="json", by_alias=True, exclude_none=True))
    input_sha256 = sha256_digest(body.encode("utf-8"))
    response = compiler.compile(request, input_sha256=input_sha256)
    return request, input_sha256, wire_payload(response)


def compile_parts(
    compiler: ProductCoreCompiler,
    documents: Sequence[ProductCoreDocument],
    split: Split,
    *,
    corpus_id: str,
    blueprint: BlueprintId | None = None,
) -> list[ReducePart]:
    ordered = sorted(documents, key=_key)
    parts = []
    for index, members in enumerate(split):
        request, digest, payload = compile_wire(
            compiler,
            [ordered[i] for i in members],
            request_id=f"{corpus_id}-part-{index}",
            # A different attempt per part: request time and activity must not matter.
            requested_at=T0 + timedelta(minutes=index + 1),
            blueprint=blueprint,
        )
        parts.append(
            ReducePart.from_compile(
                corpus_id=corpus_id,
                part_index=index,
                part_count=len(split),
                request=request,
                input_sha256=digest,
                response=payload,
            )
        )
    return parts


# --- comparator -----------------------------------------------------------------------------


def compare_forms(whole: Mapping[str, Any], reduced: Mapping[str, Any]) -> dict[str, Any]:
    """Equal or not, and where they differ. Objects are compared by ID, bytes and order."""
    sections = [
        key for key in sorted(set(whole) | set(reduced)) if whole.get(key) != reduced.get(key)
    ]
    diff: dict[str, Any] = {"equal": not sections, "sections": sections}
    for section, id_key in (
        ("objects", "stableId"),
        ("documents", "documentId"),
        ("units", "logicalId"),
    ):
        if section not in sections:
            continue
        left = {item[id_key]: canonical_json(item) for item in whole.get(section, [])}
        right = {item[id_key]: canonical_json(item) for item in reduced.get(section, [])}
        diff[section] = {
            "missingFromReduce": sorted(set(left) - set(right))[:5],
            "extraInReduce": sorted(set(right) - set(left))[:5],
            "changed": sorted(key for key in set(left) & set(right) if left[key] != right[key])[:5],
            "orderDiffers": [item[id_key] for item in whole.get(section, [])]
            != [item[id_key] for item in reduced.get(section, [])],
        }
    return diff


def naive_concat_form(parts: Sequence[ReducePart]) -> dict[str, Any]:
    """The reduce this benchmark exists to reject: concatenate part Worlds, recompute nothing.

    Used only as a negative control. Entities are not merged, cross-part contradictions are
    missing, and the semantic profile is the first part's.
    """
    forms = [canonical_form_of_compile(part.response) for part in parts]
    seen: set[str] = set()
    objects = []
    for form in forms:
        for item in form["objects"]:
            if item["stableId"] not in seen:
                seen.add(item["stableId"])
                objects.append(item)
    return {
        **forms[0],
        "documents": [item for form in forms for item in form["documents"]],
        "units": [item for form in forms for item in form["units"]],
        "objects": objects,
        "reviewReasons": sorted({reason for form in forms for reason in form["reviewReasons"]}),
    }


# --- synthetic corpora ----------------------------------------------------------------------

_SENTENCES = (
    "Acme Holdings reported revenue of {n} million in 2025.",
    "ACME HOLDINGS reported revenue of {m} million in 2025.",
    "The Agreement is binding on both parties.",
    "The Agreement is not binding on both parties.",
    "Globex-Corp International has signed the supply contract in 2024.",
    "Globex Corp International has signed the supply contract in 2024.",
    "Northwind Traders must file the annual report.",
    "The Research Institute published the dataset and method.",
    "The API architecture requires a component review.",
    "삼성전자 주식회사는 2025년 매출이 {n}억원 증가했다.",
    "삼성전자 주식회사는 2025년 매출이 {m}억원 증가했다.",
    "Lecture notes describe the course syllabus and assignment.",
    "continuation of an unfinished ocr line without a predicate",
    "Contoso Ltd reported operating income of {n} percent.",
)


def _document(
    rng: random.Random,
    corpus: int,
    index: int,
    *,
    sentences: Sequence[str] | None = None,
) -> ProductCoreDocument:
    connector = rng.choice(("foundation-r2", "foundation-r2", "drive"))
    native = f"doc-{rng.getrandbits(40):010x}"
    pages = rng.randint(1, 3)
    chosen = list(sentences) if sentences is not None else rng.sample(_SENTENCES, rng.randint(2, 5))
    regions = []
    for order, template in enumerate(chosen):
        page = min(pages, 1 + order % pages)
        text = template.format(n=rng.choice((100, 120)), m=rng.choice((100, 130)))
        regions.append(
            ProductCoreRegion(
                region_id=f"region-{order}",
                page_index0=page - 1,
                page_number1=page,
                order=order,
                block_type=BlockType.PARAGRAPH,
                text=text,
                bbox1000=None
                if rng.random() < 0.1
                else BBox1000((80, 100 + order * 40, 920, 130 + order * 40)),
                confidence=rng.choice((0.9, 0.97, 1.0)),
                authority=rng.choice(("regulatory_filing", "contract", "informal", "unclassified")),
            )
        )
    digest = sha256_digest(f"{corpus}:{index}:{native}".encode())
    return ProductCoreDocument(
        native_id=native,
        connector_type=connector,
        immutable_object_key=f"immutable/{TENANT}/{native}/source.pdf",
        ocr_object_key=f"immutable/{TENANT}/{native}/ocr.json",
        content_sha256=digest,
        title=f"Synthetic {corpus}-{index}",
        source_filename=f"{native}.pdf",
        page_count=pages,
        regions=tuple(regions),
    )


def synthetic_corpora(
    count: int = 24, seed: int = 20261108
) -> dict[str, list[ProductCoreDocument]]:
    rng = random.Random(seed)  # noqa: S311 - a fixed fixture seed, not a secret
    corpora: dict[str, list[ProductCoreDocument]] = {}
    for corpus in range(count):
        size = 3 + corpus % 10  # 3..12 documents, the per-compile ceiling
        corpora[f"synthetic-{corpus:02d}"] = [_document(rng, corpus, i) for i in range(size)]
    # Hand-built seams: every document contradicts or shares an entity with its neighbour.
    corpora["seam-contradictions"] = [
        _document(rng, 90, i, sentences=(_SENTENCES[i % 2], _SENTENCES[2 + i % 2]))
        for i in range(6)
    ]
    # No claim anywhere: the corpus must still reduce, and say SEMANTIC_CLAIMS_EMPTY.
    corpora["no-claims"] = [_document(rng, 91, i, sentences=(_SENTENCES[12],)) for i in range(4)]
    return corpora


# --- runner ---------------------------------------------------------------------------------


def whole_form_of(
    compiler: ProductCoreCompiler, name: str, documents: Sequence[ProductCoreDocument]
) -> dict[str, Any]:
    _, _, whole = compile_wire(compiler, documents, request_id=f"{name}-whole", requested_at=T0)
    form: dict[str, Any] = canonical_form_of_compile(whole)
    return form


def run_case(
    compiler: ProductCoreCompiler,
    name: str,
    documents: Sequence[ProductCoreDocument],
    strategy: str,
    split: Split,
    reverse: bool,
    whole_form: Mapping[str, Any],
    *,
    reducer: Callable[[Sequence[ReducePart]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    parts = compile_parts(compiler, documents, split, corpus_id=f"{name}-{strategy}")
    supplied = list(reversed(parts)) if reverse else parts
    receipt: dict[str, Any] | None = None
    if reducer is None:
        world, receipt = corpus_reduce(supplied)
        reduced_form = canonical_form_of_corpus_world(world)
    else:
        reduced_form = reducer(supplied)
    diff = compare_forms(whole_form, reduced_form)
    return {
        "corpus": name,
        "strategy": strategy,
        "documents": len(documents),
        "parts": len(split),
        "pass": diff["equal"],
        "wholeCanonicalSha256": sha256_digest(canonical_json(whole_form).encode()),
        "reducedCanonicalSha256": sha256_digest(canonical_json(reduced_form).encode()),
        "diff": diff,
        "reduce": None
        if receipt is None
        else {
            key: receipt[key]
            for key in (
                "outputSha256",
                "objectCount",
                "crossPartEntityCount",
                "crossPartContradictionCount",
                "reviewCandidateCount",
            )
        },
    }


def run_benchmark(
    corpora: Mapping[str, Sequence[ProductCoreDocument]], kind: str
) -> dict[str, Any]:
    compiler = ProductCoreCompiler(core_release_digest=RELEASE)
    cases: list[dict[str, Any]] = []
    for name, documents in corpora.items():
        whole_form = whole_form_of(compiler, name, documents)
        cases.extend(
            run_case(compiler, name, documents, strategy, split, reverse, whole_form)
            for strategy, (split, reverse) in split_strategies(len(documents)).items()
        )
    # Negative control: the comparator must see that naive concatenation is not a reduce.
    seam = corpora.get("seam-contradictions") or next(iter(corpora.values()))
    control = run_case(
        compiler,
        "negative-control",
        seam,
        "interleaved-k2",
        split_strategies(len(seam))["interleaved-k2"][0],
        False,
        whole_form_of(compiler, "negative-control", seam),
        reducer=naive_concat_form,
    )
    passed = sum(1 for case in cases if case["pass"])
    control_detected = not control["pass"]
    return {
        "schemaVersion": RECEIPT_SCHEMA,
        "corpusKind": kind,
        "coreReleaseDigest": RELEASE,
        "gate": "100% of cases equal; negative control detected",
        "summary": {
            "corpora": len(corpora),
            "cases": len(cases),
            "passed": passed,
            "failed": len(cases) - passed,
            "negativeControlDetected": control_detected,
            "gatePassed": passed == len(cases) and control_detected,
        },
        "cases": cases,
        "negativeControl": control,
    }


def _load_corpus(path: Path) -> list[ProductCoreDocument]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ProductCoreDocument.model_validate(item) for item in data["documents"]]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--synthetic", action="store_true", help="run the built-in fixtures")
    parser.add_argument("--corpus", type=Path, action="append", default=[], help="corpus JSON")
    parser.add_argument("--out", type=Path, required=True, help="receipt JSON path")
    args = parser.parse_args(argv)
    if not args.synthetic and not args.corpus:
        parser.error("pass --synthetic or at least one --corpus")
    corpora: dict[str, Sequence[ProductCoreDocument]] = {}
    if args.synthetic:
        corpora.update(synthetic_corpora())
    for path in args.corpus:
        corpora[path.stem] = _load_corpus(path)
    receipt = run_benchmark(corpora, "synthetic" if not args.corpus else "real")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = receipt["summary"]
    print(json.dumps(summary, separators=(",", ":")))
    return 0 if summary["gatePassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
