"""Focused offline Core contract/compile check with fictional OCR observations."""
from __future__ import annotations

import copy
import json

from akc_product_core.compiler import ProductCoreCompiler
from akc_product_core.contracts import ProductCoreCompileRequest
from pydantic import ValidationError

SHA = "sha256:" + "a" * 64
REVISION = "sha256:" + "b" * 64
BINDING = "sha256:" + "c" * 64
MODELS = {
    "general-ppocrv6": "sha256:6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
    "korean-ppocrv5": "sha256:cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b",
}
POLYGON = [[20, 40], [100, 40], [100, 80], [20, 80]]
CONFLICT = {
    "sourceSha256": SHA,
    "regionId": "fictional-label-1",
    "pageIndex0": 0,
    "bbox1000": [10, 20, 120, 50],
    "candidates": [
        {"engineId": "general-ppocrv6", "modelSha256": MODELS["general-ppocrv6"],
         "text": "LABEL-A", "confidence": 0.71, "polygon": POLYGON},
        {"engineId": "korean-ppocrv5", "modelSha256": MODELS["korean-ppocrv5"],
         "text": "LABEL-B", "confidence": 0.69, "polygon": POLYGON},
    ],
}
BASE = {
    "requestId": "synthetic-request-1", "idempotencyKey": "synthetic-key-1",
    "tenantId": "synthetic-tenant", "workspaceId": "synthetic-workspace",
    "collectionId": "synthetic-collection", "requestedAt": "2026-10-14T00:00:00Z",
    "route": {"operationClass": "initial_compile", "qualityRequirement": "high_assurance",
              "maxCostCredits": 10, "maxLatencyMs": 90000,
              "privacyPolicy": "foundation_synthetic_only"},
    "documents": [{
        "nativeId": "synthetic-document", "connectorType": "foundation-r2",
        "immutableObjectKey": "synthetic/source.pdf", "ocrObjectKey": "synthetic/ocr.json",
        "contentSha256": SHA, "title": "Fictional label", "sourceFilename": "fictional.pdf",
        "pageCount": 1, "readerRevision": REVISION, "readerBindingSha256": BINDING,
        "recognitionConflictCount": 1,
        "regions": [{"regionId": "fictional-label-1", "pageIndex0": 0, "pageNumber1": 1,
                     "order": 0, "blockType": "paragraph", "text": "LABEL-A",
                     "bbox1000": [10, 20, 120, 50], "confidence": 0.71,
                     "authority": "unknown", "recognitionConflict": CONFLICT}],
    }],
}


def reject(label: str, mutate) -> None:
    item = copy.deepcopy(BASE)
    mutate(item)
    try:
        ProductCoreCompileRequest.model_validate(item)
    except ValidationError:
        return
    raise AssertionError(f"Core accepted {label}")




def test_fictional_ocr_v3_review_and_invalid_contracts() -> None:
    request = ProductCoreCompileRequest.model_validate(BASE)
    assert request.documents[0].regions[0].recognition_conflict.candidates[1].text == "LABEL-B"
    compiler = ProductCoreCompiler(core_release_digest="sha256:" + "d" * 64)
    response = compiler.compile(request, input_sha256="sha256:" + "e" * 64)
    assert response.status == response.candidate.lifecycle == "review_required"
    assert response.receipt.candidate_promotion is False
    assert any(reason.startswith("OCR_RECOGNITION_CONFLICT:") for reason in response.candidate.review_reasons)
    assert response.candidate.canonical_documents[0]["blocks"][0]["rawText"] == "LABEL-A"

    bad_cases = {
        "wrong source hash": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"].update(sourceSha256="sha256:" + "f" * 64),
        "wrong region": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"].update(regionId="other"),
        "wrong bbox": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"].update(bbox1000=[11, 20, 120, 50]),
        "wrong model": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"]["candidates"][0].update(modelSha256=MODELS["korean-ppocrv5"]),
        "duplicate engines": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"]["candidates"][1].update(engineId="general-ppocrv6"),
        "bad polygon": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"]["candidates"][0].update(polygon=[[1, 2], [3, 4]]),
        "selected mismatch": lambda x: x["documents"][0]["regions"][0].update(text="CORRECTED-LABEL"),
        "confidence mismatch": lambda x: x["documents"][0]["regions"][0].update(confidence=0.70),
        "unknown conflict field": lambda x: x["documents"][0]["regions"][0]["recognitionConflict"].update(unreviewedExtra=True),
        "missing reader revision": lambda x: x["documents"][0].pop("readerRevision"),
        "missing reader binding": lambda x: x["documents"][0].pop("readerBindingSha256"),
        "missing conflict count": lambda x: x["documents"][0].pop("recognitionConflictCount"),
        "deleted conflict count mismatch": lambda x: x["documents"][0]["regions"][0].pop("recognitionConflict"),
    }
    for name, mutation in bad_cases.items():
        reject(name, mutation)

    many = copy.deepcopy(BASE)
    first = many["documents"][0]["regions"][0]
    many["documents"][0]["regions"] = []
    many["documents"][0]["recognitionConflictCount"] = 129
    for index in range(129):
        row = copy.deepcopy(first)
        row["regionId"] = f"fictional-label-{index}"
        row["order"] = index
        row["recognitionConflict"]["regionId"] = row["regionId"]
        many["documents"][0]["regions"].append(row)
    try:
        ProductCoreCompileRequest.model_validate(many)
    except ValidationError:
        pass
    else:
        raise AssertionError("Core accepted >128 conflicts")

    clean = copy.deepcopy(BASE)
    del clean["documents"][0]["regions"][0]["recognitionConflict"]
    clean["documents"][0]["recognitionConflictCount"] = 0
    clean_v3_result = compiler.compile(ProductCoreCompileRequest.model_validate(clean),
                                       input_sha256="sha256:" + "e" * 64)
    assert not any(reason.startswith("OCR_RECOGNITION_CONFLICT:") for reason in clean_v3_result.candidate.review_reasons)
    clean_source_file = next(item for item in clean_v3_result.candidate.package.files
                             if item.path == "source/collection-files.json")
    clean_source_row = json.loads(clean_source_file.content)[0]
    assert clean_source_row["ocrSchemaVersion"] == "tavonel.ocr_result.v3"
    assert clean_source_row["readerRevision"] == REVISION
    assert clean_source_row["readerBindingSha256"] == BINDING
    assert clean_source_row["recognitionConflictCount"] == 0
    assert clean_source_row["sourceSha256"] == SHA
    del clean["documents"][0]["readerRevision"]
    del clean["documents"][0]["readerBindingSha256"]
    del clean["documents"][0]["recognitionConflictCount"]
    clean_result = compiler.compile(ProductCoreCompileRequest.model_validate(clean), input_sha256="sha256:" + "e" * 64)
    assert not any(reason.startswith("OCR_RECOGNITION_CONFLICT:") for reason in clean_result.candidate.review_reasons)
    legacy_source_file = next(item for item in clean_result.candidate.package.files
                              if item.path == "source/collection-files.json")
    assert "ocrSchemaVersion" not in json.loads(legacy_source_file.content)[0]
    print(json.dumps({"v3Status": response.status, "promotion": response.receipt.candidate_promotion,
                      "negativeCases": len(bad_cases) + 1, "v2DefaultRetained": True}))
