from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/baked-model-image.yml"


def test_workflow_builds_only_the_frozen_ovis_image_and_never_allocates_gpu() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(text)
    assert parsed[True]["workflow_dispatch"] == {}
    assert parsed[True]["push"]["branches"] == [
        "agent/folynta-trust-integration-v1"
    ]
    assert parsed[True]["push"]["paths"] == [
        ".github/workflows/baked-model-image.yml",
        "benchmark/runpod_eval/bootstrap_ovisocr2_m1.sh",
        "infra/runpod/v6/image_build_receipt.py",
        "infra/runpod/v6/images/ovisocr2-m1/**",
    ]
    assert parsed["permissions"] == {"contents": "read", "packages": "write"}
    assert "infra/runpod/v6/images/ovisocr2-m1/Dockerfile" in text
    assert "65c619d374b55d4152e85150fc1b003700bc1f0c" in text
    assert "sha256:847f485bc71908a70075fe6b0d76609f52bc7f1e730c03670c764da56da08c9a" in text
    assert "runtime_qualification_required" not in text
    assert "image_build_receipt" in text
    assert "api.runpod.ai" not in text.lower()
    assert "pod_client" not in text.lower()
    assert "run_provider_smoke" not in text.lower()
    assert "readonly targets=" in text
    assert "/usr/local/lib/android" in text
    assert "/usr/share/dotnet" in text
    assert "/opt/ghc" in text
    assert "/opt/hostedtoolcache/CodeQL" in text
    assert "refusing unexpected cleanup target" in text


def test_workflow_publishes_content_bound_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--metadata-file" in text
    assert "--driver docker-container" in text
    assert "docker buildx inspect --bootstrap" in text
    assert "source-tree.sha256" in text
    assert "ovisocr2-m1.spdx.json" in text
    assert "ovisocr2-m1.trivy.json" in text
    assert "ovisocr2-m1.build-receipt.json" in text
    assert "severity: CRITICAL" in text
    assert "exit-code: \"1\"" in text
    assert "retention-days: 30" in text
