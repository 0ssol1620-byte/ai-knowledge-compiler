from pathlib import Path

ROOT = Path(__file__).parents[2]
CONTROLLER = ROOT / "tools" / "release" / "continue_folynta_preofficial_operational_deepseek.ps1"
ORCHESTRATOR = ROOT / "tools" / "release" / "orchestrate_folynta_deepseek_hybrid_recovery.ps1"


def test_hybrid_controller_binds_both_model_evidence_and_deletes_pod() -> None:
    source = CONTROLLER.read_text(encoding="utf-8-sig")
    assert "--paddle-layout-fallback-root" in source
    assert "--operational-failure-targets" in source
    assert "deepseek-pod-deleted" in source
    assert "Hybrid recovery did not achieve 5,132/5,132 coverage" in source
    assert "continue_folynta_official_evaluations.ps1" in source


def test_orchestrator_waits_for_provisioning_before_bootstrap() -> None:
    source = ORCHESTRATOR.read_text(encoding="utf-8-sig")
    wait_for_provisioning = source.index(
        "while(-not (Test-Path -LiteralPath $provisioning))"
    )
    assert wait_for_provisioning < source.index("$bootstrapScript=")
    assert "RemoteReceiptSlug 'deepseek-operational-r2'" in source
