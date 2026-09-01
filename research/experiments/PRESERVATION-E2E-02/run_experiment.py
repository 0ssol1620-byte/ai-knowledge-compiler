"""PRESERVATION-E2E-02 -- fault injection against the Semantic Preservation
Contract, on canonical documents built from real parser output.

Audit section 28-B asks for realistic parser outputs, critical fault
injection, detection metrics, and repair-locality metrics.
tests/unit/test_semantic_preservation.py already covers the invariants, but
on hand-authored fixtures built to trip them. This runner builds every
document from research/experiments/SEM-RISK-CONF-02/outputs/lane-a-native/ --
64 completed real extraction outputs over the frozen Lane A corpus -- and
injects faults into those.

Usage:
    python run_experiment.py --freeze   # seal protocol + this runner
    python run_experiment.py --run      # execute and write the receipt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXPERIMENT_DIR.parents[2]
PARSER_OUTPUTS = (
    REPO_ROOT
    / "research"
    / "experiments"
    / "SEM-RISK-CONF-02"
    / "outputs"
    / "lane-a-native"
)
RECEIPTS = EXPERIMENT_DIR / "receipts"

sys.path.insert(0, str(REPO_ROOT / "packages" / "cir-python" / "src"))

from akc_cir import (  # noqa: E402
    BBox1000,
    BlockOrigin,
    BlockType,
    CanonicalBlock,
    CanonicalCell,
    CanonicalDocument,
    CanonicalTable,
    ContentLayer,
    SemanticEvidenceBinding,
    SourceRef,
    sha256_digest,
    verify_semantic_preservation,
)

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9'-]{3,}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_protocol() -> dict[str, Any]:
    return json.loads((EXPERIMENT_DIR / "protocol.json").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Construction: real parser output -> CanonicalDocument + bindings
# --------------------------------------------------------------------------


def _ref(doc_id: str, version: str, page: int) -> SourceRef:
    return SourceRef(
        document_id=doc_id,
        document_version_id=version,
        page_index0=page,
        page_number1=page + 1,
        bbox1000=BBox1000([100, 100, 900, 300]),
    )


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def build_case(record: dict[str, Any]) -> tuple[CanonicalDocument, list[SemanticEvidenceBinding]] | None:
    """Build one document + bindings from a real parser output record."""
    text = record.get("text") or ""
    paragraphs = _paragraphs(text)
    if len(paragraphs) < 4:
        return None

    case_id = str(record["case_id"])
    digest = hashlib.sha256(case_id.encode()).hexdigest()[:12]
    doc_id = f"doc_{digest}"
    version = f"docver_{digest}"

    blocks: list[CanonicalBlock] = []
    bindings: list[SemanticEvidenceBinding] = []

    for index, paragraph in enumerate(paragraphs):
        block_id = f"blk_{digest}_{index:03d}"
        page = index // 4  # spread blocks over pages so locality is measurable
        blocks.append(
            CanonicalBlock(
                id=block_id,
                order=index,
                type=BlockType.PARAGRAPH,
                content_layer=ContentLayer.EXTRACTED,
                raw_text=paragraph,
                normalized_text=paragraph,
                content_hash=sha256_digest(paragraph),
                origin=BlockOrigin.NATIVE_EXTRACTED,
                source_refs=(_ref(doc_id, version, page),),
            )
        )
        tokens = tuple(dict.fromkeys(_TOKEN.findall(paragraph)))[:2]
        if tokens:
            bindings.append(
                SemanticEvidenceBinding(
                    knowledge_id=f"kn_{digest}_{index:03d}",
                    knowledge_kind="claim",
                    source_block_ids=(block_id,),
                    critical_tokens=tokens,
                )
            )

    if not bindings:
        return None

    document = CanonicalDocument(
        tenant_id="tenant_preservation_e2e",
        document_id=doc_id,
        document_version_id=version,
        title=case_id[:120],
        source_filename=f"{case_id[:100]}.pdf",
        source_sha256=record["source_sha256"],
        content_layer=ContentLayer.EXTRACTED,
        blocks=tuple(blocks),
        created_at=datetime.now(UTC),
    )
    return document, bindings


# --------------------------------------------------------------------------
# Fault injection
# --------------------------------------------------------------------------


def inject_missing_source_block(doc, bindings):
    """F1: a binding cites a block id that is not in the document."""
    target = bindings[0]
    mutated = SemanticEvidenceBinding(
        knowledge_id=target.knowledge_id,
        knowledge_kind=target.knowledge_kind,
        source_block_ids=(target.source_block_ids[0] + "_vanished",),
        critical_tokens=(),
    )
    return doc, [mutated, *bindings[1:]]


def _first_cited_block_id(bindings) -> str | None:
    """The first block id any binding actually cites."""
    for binding in bindings:
        if binding.source_block_ids:
            return binding.source_block_ids[0]
    return None


def inject_cross_version_evidence(doc, bindings):
    """F2: rewrite the SourceRef of a block a binding CITES.

    V01 mutated blocks[0] unconditionally and detected only 18 of 49, because
    31 cases had no binding citing blocks[0]. The contract checks evidence
    that is cited; an uncited mutation is out of its scope by construction,
    not a miss. See PRESERVATION-E2E-02/protocol.json supersedes block.
    """
    cited_id = _first_cited_block_id(bindings)
    if cited_id is None:
        return None
    blocks = list(doc.blocks)
    index = next((i for i, b in enumerate(blocks) if b.id == cited_id), None)
    if index is None:
        return None
    victim = blocks[index]
    bad_ref = SourceRef(
        document_id=victim.source_refs[0].document_id,
        document_version_id=victim.source_refs[0].document_version_id + "_other",
        page_index0=victim.source_refs[0].page_index0,
        page_number1=victim.source_refs[0].page_number1,
        bbox1000=victim.source_refs[0].bbox1000,
    )
    blocks[index] = victim.model_copy(update={"source_refs": (bad_ref,)})
    return doc.model_copy(update={"blocks": tuple(blocks)}), bindings


def control_uncited_version_mutation(doc, bindings):
    """N1: mutate a block NO binding cites; the contract must stay silent."""
    cited = {bid for b in bindings for bid in b.source_block_ids}
    blocks = list(doc.blocks)
    index = next((i for i, b in enumerate(blocks) if b.id not in cited), None)
    if index is None:
        return None
    victim = blocks[index]
    ref = victim.source_refs[0]
    bad_ref = SourceRef(
        document_id=ref.document_id,
        document_version_id=ref.document_version_id + "_other",
        page_index0=ref.page_index0,
        page_number1=ref.page_number1,
        bbox1000=ref.bbox1000,
    )
    blocks[index] = victim.model_copy(update={"source_refs": (bad_ref,)})
    return doc.model_copy(update={"blocks": tuple(blocks)}), bindings


def inject_detached_table_cell(doc, bindings):
    """F3: a binding cites a table cell belonging to no attached block."""
    target = bindings[0]
    mutated = SemanticEvidenceBinding(
        knowledge_id=target.knowledge_id,
        knowledge_kind=target.knowledge_kind,
        source_block_ids=target.source_block_ids,
        source_cell_ids=("cell_not_in_any_attached_block",),
        critical_tokens=(),
    )
    return doc, [mutated, *bindings[1:]]


def inject_critical_token_dropped(doc, bindings):
    """F4: a declared critical token is removed from its evidence text."""
    target = next((b for b in bindings if b.critical_tokens), None)
    if target is None:
        return None
    block_id = target.source_block_ids[0]
    token = target.critical_tokens[0]
    blocks = []
    for block in doc.blocks:
        if block.id == block_id:
            stripped = (block.normalized_text or "").replace(token, "")
            block = block.model_copy(
                update={
                    "raw_text": stripped,
                    "normalized_text": stripped,
                    "content_hash": sha256_digest(stripped),
                }
            )
        blocks.append(block)
    return doc.model_copy(update={"blocks": tuple(blocks)}), bindings


FAULTS = {
    "F1_MISSING_SOURCE_BLOCK": inject_missing_source_block,
    "F2_CROSS_VERSION_EVIDENCE": inject_cross_version_evidence,
    "F3_DETACHED_TABLE_CELL": inject_detached_table_cell,
    "F4_CRITICAL_TOKEN_DROPPED": inject_critical_token_dropped,
}


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def run() -> dict[str, Any]:
    protocol = _load_protocol()
    records = []
    for path in sorted(PARSER_OUTPUTS.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("status") == "completed" and (record.get("block_count") or 0) >= 4:
            records.append(record)

    cases = []
    for record in records:
        built = build_case(record)
        if built is not None:
            cases.append((record["case_id"], built))

    clean_violations = 0
    n1_total = [0]
    n1_fired = [0]
    detected = Counter()
    injected = Counter()
    locality_blocks: list[float] = []
    locality_pages: list[float] = []
    undetected_examples: list[dict[str, Any]] = []

    for case_id, (doc, bindings) in cases:
        # Negative control: the unmodified document must be silent.
        clean = verify_semantic_preservation(doc, tuple(bindings))
        if clean.violations:
            clean_violations += 1

        total_blocks = len(doc.blocks)
        total_pages = len({ref.page_index0 for b in doc.blocks for ref in b.source_refs})

        # N1 control: an uncited mutation must NOT fire.
        n1 = control_uncited_version_mutation(doc, list(bindings))
        if n1 is not None:
            n1_total[0] += 1
            n1_doc, n1_bind = n1
            if verify_semantic_preservation(n1_doc, tuple(n1_bind)).violations:
                n1_fired[0] += 1

        for fault_id, injector in FAULTS.items():
            outcome = injector(doc, list(bindings))
            if outcome is None:
                continue
            faulty_doc, faulty_bindings = outcome
            injected[fault_id] += 1
            report = verify_semantic_preservation(faulty_doc, tuple(faulty_bindings))
            if report.violations:
                detected[fault_id] += 1
                if total_blocks:
                    locality_blocks.append(len(report.quarantine_block_ids) / total_blocks)
                if total_pages:
                    locality_pages.append(len(report.quarantine_page_indexes0) / total_pages)
            elif len(undetected_examples) < 5:
                undetected_examples.append({"case_id": case_id, "fault": fault_id})

    def mean(values: list[float]) -> float | None:
        return round(sum(values) / len(values), 6) if values else None

    gates = protocol["preregistered_gates"]
    per_family = {
        fault_id: {
            "injected": injected[fault_id],
            "detected": detected[fault_id],
            "detection_rate": (
                round(detected[fault_id] / injected[fault_id], 6) if injected[fault_id] else None
            ),
        }
        for fault_id in FAULTS
    }
    false_positive_rate = round(clean_violations / len(cases), 6) if cases else None
    n1_rate = round(n1_fired[0] / n1_total[0], 6) if n1_total[0] else None
    mean_locality_blocks = mean(locality_blocks)

    gate_results = {
        "cases_evaluated": {
            "value": len(cases),
            "minimum": gates["minimum_cases"],
            "pass": len(cases) >= gates["minimum_cases"],
        },
        "detection_rate_per_family": {
            "value": {k: v["detection_rate"] for k, v in per_family.items()},
            "minimum": gates["detection_rate_min_per_family"],
            "pass": all(
                (v["detection_rate"] is not None)
                and v["detection_rate"] >= gates["detection_rate_min_per_family"]
                for v in per_family.values()
            ),
        },
        "false_positive_rate": {
            "value": false_positive_rate,
            "maximum": gates["false_positive_rate_max"],
            "pass": (false_positive_rate is not None)
            and false_positive_rate <= gates["false_positive_rate_max"],
        },
        "uncited_mutation_false_positive_rate": {
            "value": n1_rate,
            "maximum": gates["uncited_mutation_false_positive_rate_max"],
            "pass": (n1_rate is not None)
            and n1_rate <= gates["uncited_mutation_false_positive_rate_max"],
        },
        "repair_locality_blocks_mean": {
            "value": mean_locality_blocks,
            "maximum": gates["repair_locality_blocks_max_mean"],
            "pass": (mean_locality_blocks is not None)
            and mean_locality_blocks <= gates["repair_locality_blocks_max_mean"],
        },
    }

    return {
        "schema": "tavonel.preservation.fault-injection.result.v2",
        "experiment_id": protocol["experiment_id"],
        "generated_at": datetime.now(UTC).isoformat(),
        "closes_audit_section": protocol["closes_audit_section"],
        "parser_output_source": str(PARSER_OUTPUTS.relative_to(REPO_ROOT)).replace("\\", "/"),
        "parser_outputs_considered": len(records),
        "cases_evaluated": len(cases),
        "clean_documents_with_violations": clean_violations,
        "per_family": per_family,
        "false_positive_rate": false_positive_rate,
        "n1_uncited_controls": n1_total[0],
        "n1_uncited_false_positives": n1_fired[0],
        "uncited_mutation_false_positive_rate": n1_rate,
        "repair_locality_blocks_mean": mean_locality_blocks,
        "repair_locality_pages_mean": mean(locality_pages),
        "undetected_examples": undetected_examples,
        "gates": gate_results,
        "verdict": "PASS" if all(g["pass"] for g in gate_results.values()) else "FAIL",
        "gpu_seconds": 0.0,
        "estimated_cost_usd": 0.0,
    }


def freeze() -> dict[str, Any]:
    RECEIPTS.mkdir(parents=True, exist_ok=True)
    seal_path = RECEIPTS / "pre-run-seal.json"
    if seal_path.exists():
        raise SystemExit(f"already sealed: {seal_path}")
    payload = {
        "schema": "tavonel.preservation.fault-injection.seal.v2",
        "sealed_at": datetime.now(UTC).isoformat(),
        "protocol_sha256": f"sha256:{_sha256(EXPERIMENT_DIR / 'protocol.json')}",
        "runner_sha256": f"sha256:{_sha256(Path(__file__))}",
    }
    body = json.dumps(payload, indent=2, sort_keys=True).encode()
    seal = hashlib.sha256(body).hexdigest()
    seal_path.write_bytes(body)
    (RECEIPTS / "pre-run-seal.sha256").write_text(f"sha256:{seal}\n", encoding="utf-8")
    return {"sealed": True, "seal_sha256": f"sha256:{seal}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    if args.freeze:
        print(json.dumps(freeze(), indent=2))
        return 0

    if args.run:
        if not (RECEIPTS / "pre-run-seal.json").exists():
            raise SystemExit("refusing to run before --freeze")
        result = run()
        RECEIPTS.mkdir(parents=True, exist_ok=True)
        out = RECEIPTS / "result.json"
        if out.exists():
            raise SystemExit(f"refusing to overwrite {out}")
        out.write_text(
            json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(json.dumps(result, indent=2, sort_keys=True)[:2600])
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
