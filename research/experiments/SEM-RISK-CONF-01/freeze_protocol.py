from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT = Path(__file__).resolve().parent
PROTOCOL = EXPERIMENT / "protocol.json"
RECEIPTS = EXPERIMENT / "receipts"
DEV_GT = Path(
    r"D:\CodexProjects\ai-knowledge-compiler\benchmark\cache\omnidoc\demo_data\omnidocbench_demo\OmniDocBench_demo.json"
)
DATASET_ID = "opendatalab/OmniDocBench"
API = f"https://huggingface.co/api/datasets/{DATASET_ID}"
DELETE_ORI_TITLE = "Delete folder ori_pdfs with huggingface_hub"


def _get_json(url: str) -> tuple[Any, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "tavonel-research-protocol/1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response), dict(response.headers.items())


def _tree(revision: str, folder: str) -> list[dict[str, Any]]:
    encoded = urllib.parse.quote(revision, safe="")
    url = f"{API}/tree/{encoded}/{folder}?recursive=true&expand=false&limit=1000"
    payload, _ = _get_json(url)
    if not isinstance(payload, list):
        raise RuntimeError(f"unexpected tree payload for {folder}")
    return [item for item in payload if isinstance(item, dict)]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _development_exclusions() -> list[str]:
    if not DEV_GT.is_file():
        raise RuntimeError(f"development exclusion source missing: {DEV_GT}")
    items = json.loads(DEV_GT.read_text(encoding="utf-8"))
    if not isinstance(items, list) or len(items) != 18:
        raise RuntimeError("expected the already-open 18-page development cohort")
    stems = sorted(
        Path(str(item["page_info"]["image_path"])).stem
        for item in items
        if isinstance(item, dict)
    )
    if len(stems) != 18 or len(set(stems)) != 18:
        raise RuntimeError("development exclusion page keys are not 18 unique stems")
    return stems


def main() -> int:
    if PROTOCOL.exists():
        raise SystemExit("protocol.json already exists; confirmatory protocol is immutable")

    metadata, _ = _get_json(API)
    current_revision = str(metadata.get("sha") or "")
    if len(current_revision) < 7:
        raise RuntimeError("dataset current revision could not be resolved")

    commits, _ = _get_json(f"{API}/commits/main?limit=100")
    if not isinstance(commits, list):
        raise RuntimeError("dataset commit history is not a list")
    delete_index = next(
        (index for index, item in enumerate(commits) if item.get("title") == DELETE_ORI_TITLE),
        None,
    )
    if delete_index is None or delete_index + 1 >= len(commits):
        raise RuntimeError("could not resolve the last pre-deletion ori_pdfs revision")
    source_native_revision = str(commits[delete_index + 1].get("id") or "")
    if len(source_native_revision) < 7:
        raise RuntimeError("pre-deletion ori_pdfs revision is malformed")

    current_root = _tree(current_revision, "images")
    native_pdfs = _tree(source_native_revision, "ori_pdfs")
    native_images = _tree(source_native_revision, "images")
    if len(native_pdfs) < 900 or len(native_images) < 900:
        raise RuntimeError("source-native lane public universe unexpectedly small")
    if len(current_root) < 1000:
        raise RuntimeError("current v1.6 image universe unexpectedly small")

    exclusions = _development_exclusions()
    source_files = [
        "research/experiments/SEM-RISK-CONF-01/freeze_protocol.py",
        "research/experiments/SEM-RISK-CONF-01/build_selection_manifest.py",
        "research/experiments/SEM-RISK-CONF-01/acquire_selected_inputs.py",
        "research/experiments/SEM-RISK-CONF-01/run_lane_a_native.py",
        "research/experiments/SEM-RISK-CONF-01/build_inference_manifests.py",
        "research/experiments/SEM-RISK-CONF-01/evaluate_confirmatory.py",
        "tests/unit/test_sem_risk_confirmatory_protocol.py",
        "packages/cir-python/src/akc_cir/semantic_risk.py",
        "packages/quality/src/akc_quality/agreement.py",
        "packages/quality/src/akc_quality/semantic_signals.py",
        "packages/native-parsers/src/akc_native_parsers/pdf_parser.py",
        "benchmark/runners/native.py",
        "benchmark/runpod_eval/input_contract.py",
        "benchmark/runpod_eval/isolated_case_process.py",
        "benchmark/runpod_eval/paddleocr_vl_stage2.py",
        "benchmark/runpod_eval/mineru_stage2.py",
        "benchmark/v6/candidate-registry.yaml",
    ]
    source_hashes = {path: _sha256_file(ROOT / path) for path in source_files}

    protocol: dict[str, Any] = {
        "experiment_id": "SEM-RISK-CONF-01",
        "classification": "PROSPECTIVE_CONFIRMATORY_TWO_LANE",
        "date_utc": "2026-08-31",
        "claim_boundary": (
            "Confirms (A) whether a deterministic source-native PDF parser can serve as a cheap, "
            "ground-truth-independent disagreement signal on born-digital PDFs and (B) whether a "
            "fixed failure-class specialist policy improves current OCR parsing on a fresh v1.6 "
            "stratified cohort. It does not prove universal routing across scans, handwriting, or "
            "all enterprise domains."
        ),
        "forbidden": {
            "threshold_selection_from_sem_risk_dev_cal_01": True,
            "development_pages_in_confirmatory_cohort": True,
            "ground_truth_visible_to_inference_workers": True,
            "post_result_threshold_or_specialist_mapping_changes": True,
            "mineru_commercial_promotion_from_this_experiment": True,
        },
        "development_exclusion": {
            "count": len(exclusions),
            "page_stems": exclusions,
            "sha256": _canonical_sha(exclusions),
            "reason": "All pages used by SEM-RISK-DEV-CAL-01 are excluded before confirmatory selection.",
        },
        "dataset": {
            "repository": DATASET_ID,
            "current_v1_6_revision": current_revision,
            "source_native_pre_deletion_revision": source_native_revision,
            "source_native_revision_resolution_rule": (
                "first commit immediately older than the commit titled 'Delete folder ori_pdfs with huggingface_hub'"
            ),
            "observed_metadata_only_universe": {
                "current_images_first_tree_page": len(current_root),
                "source_native_ori_pdfs": len(native_pdfs),
                "source_native_images": len(native_images),
            },
        },
        "selection": {
            "cross_lane_disjoint": True,
            "lane_a": {
                "name": "born_digital_native_peer_signal",
                "sample_size": 64,
                "salt": "tavonel-sem-risk-conf-01a-2026-08-31",
                "universe": "intersection of ori_pdfs and images at source_native_pre_deletion_revision",
                "ranking": "ascending sha256(salt + NUL + page_stem)",
                "exclude_development_stems": True,
                "ground_truth_used_for_selection": False,
            },
            "lane_b": {
                "name": "current_v1_6_failure_class_specialist",
                "sample_per_subset": 16,
                "subsets": ["v1.5", "equation_hard", "layout_hard", "table_hard"],
                "total_sample_size": 64,
                "salt": "tavonel-sem-risk-conf-01b-2026-08-31",
                "ranking": "within each declared subset, ascending sha256(salt + NUL + image_path)",
                "selection_metadata_whitelist": ["page_info.image_path", "page_info.page_attribute.subset"],
                "exclude_development_stems": True,
                "ground_truth_content_used_for_selection": False,
            },
        },
        "parser_roles": {
            "primary": "paddleocr-vl-1.6",
            "primary_repeats_lane_a": 1,
            "primary_repeats_lane_b": 3,
            "cheap_peer_lane_a": "native_document/pypdf deterministic source-native parser",
            "research_specialist": "mineru-3.4.4-vlm",
            "specialist_promotion_status": "research_comparator_only_license_review_required",
            "model_identity_binding": "exact candidate-registry.yaml entries at the frozen source hash plus run-summary model_revision/artifact_manifest_sha256",
            "formula_policy": (
                "Formula presence alone never routes away from Paddle because development-only aggregate evidence "
                "did not establish MinerU as a formula specialist."
            ),
        },
        "routing_policy": {
            "semantic_risk_policy_version": "sem-risk-conf-01-fixed-v1",
            "semantic_risk_escalation_threshold": 0.25,
            "cheap_peer_disagreement_threshold": 0.35,
            "threshold_origin": "predeclared semantic-risk band boundary / engineering prior, not fitted on development pages",
            "critical_token_disagreement": "Jaccard disagreement of date/version/quantity token sets participates as a non-averaged warning axis",
            "lane_a_error_signal": "independent source-native peer disagreement",
            "lane_b_error_signal": (
                "Paddle repeat instability across exactly 3 frozen inference repeats; repeat 1 is the primary output. "
                "Instability is measured without ground truth and is passed as parsing_uncertainty, not cross-model disagreement."
            ),
            "lane_b_instability_formula": (
                "max(mean pairwise normalized token-sequence disagreement, critical-token set instability) across repeats"
            ),
            "specialist_eligibility": "primary output indicates table or layout complexity; formula-only is excluded",
            "review_without_replacement": "high semantic risk with no eligible specialist retains primary output but is flagged for verification/review",
            "compiler_consequence_defaults": {
                "downstream_consumer_risk": 0.35,
                "dependency_blast_radius": 0.0,
                "authority_significance": 0.0,
                "entity_criticality": 0.0,
                "note": "benchmark has no real promoted-world dependency graph; nonzero graph consequences require a separate E2E fixture/experiment",
            },
        },
        "comparators": [
            "primary_only",
            "always_research_specialist",
            "cheap_peer_disagreement_then_specialist_lane_a",
            "semantic_risk_native_peer_then_failure_class_specialist_lane_a",
            "semantic_risk_repeat_instability_then_failure_class_specialist_lane_b",
        ],
        "evaluation": {
            "ground_truth_isolation": (
                "Inference outputs are frozen before the evaluator consumes annotation content. Selection code may "
                "read only the lane-B metadata whitelist and must not emit annotation text."
            ),
            "primary_metric": "custom_semantic_damage_v1_frozen_from_preconfirmatory_code",
            "primary_metric_components": {
                "content_sequence_error": 0.30,
                "ordered_content_error": 0.20,
                "critical_token_error_if_present": 0.30,
                "table_semantic_error_if_present": 0.35,
                "formula_semantic_error_if_present": 0.25,
                "normalization": "divide by active component weights per page",
            },
            "secondary_metrics": [
                "official_omnidocbench_text_edit",
                "official_omnidocbench_formula_edit",
                "official_omnidocbench_table_edit_or_teds",
                "official_omnidocbench_reading_order_edit",
                "critical_token_exact_recall",
                "date_quantity_version_loss",
                "escalation_rate",
                "false_safe_rate",
                "false_escalation_rate",
                "latency_seconds",
                "gpu_seconds",
                "estimated_cost_usd",
            ],
            "lane_a_signal_endpoint": {
                "high_primary_damage_definition": "primary semantic damage >= 0.20 OR primary critical-token error > 0",
                "report_auroc": True,
                "report_average_precision": True,
                "report_critical_token_disagreement_recall": True,
            },
            "routing_error_definitions": {
                "specialist_material_benefit": "eligible specialist reduces semantic damage by >= 0.05 OR lowers critical-token error by >= 0.25",
                "false_safe": "policy does not escalate despite specialist_material_benefit",
                "false_escalation": "policy escalates and specialist semantic damage exceeds primary semantic damage by > 0.02",
            },
        },
        "acceptance": {
            "integrity": [
                "protocol and selection manifests hash-verified",
                "all selected pages exclude development cohort",
                "inference workers receive no ground truth",
                "no output overwrite/resume ambiguity",
            ],
            "lane_a": {
                "minimum_evaluable_pages": 48,
                "peer_signal_auroc_min": 0.65,
                "critical_token_error_detection_recall_min": 0.80,
            },
            "routing": {
                "semantic_risk_mean_damage_must_not_exceed_primary": True,
                "semantic_risk_critical_token_error_must_not_exceed_primary": True,
                "semantic_risk_table_error_must_not_exceed_primary": True,
                "semantic_risk_escalation_rate_max": 0.75,
                "point_damage_reduction_required": True,
                "bootstrap_ci_report_required": True,
                "bootstrap_seed": 260831,
                "bootstrap_resamples": 10000,
            },
        },
        "cost": {
            "gpu_allowed_only_after_protocol_and_selection_seal_pass": True,
            "hard_cap_usd": 500.0,
            "lane_a_native_gpu_seconds": 0.0,
        },
        "source_hashes": source_hashes,
    }

    RECEIPTS.mkdir(parents=True, exist_ok=True)
    PROTOCOL.write_text(json.dumps(protocol, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt = {
        "protocol_sha256": _sha256_file(PROTOCOL),
        "development_exclusion_sha256": protocol["development_exclusion"]["sha256"],
        "dataset_current_revision": current_revision,
        "dataset_source_native_revision": source_native_revision,
        "source_hashes": source_hashes,
    }
    (RECEIPTS / "protocol-freeze.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"experiment_id": protocol["experiment_id"], "protocol_sha256": receipt["protocol_sha256"], "frozen": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
