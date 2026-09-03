from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"


def test_stage1_v6_uses_parent_control_plane_during_qualification() -> None:
    controller = (SCRIPTS / "run_stage1_v29_r2_v6_controlplane.py").read_text(encoding="utf-8")
    assert '"ports": ["8001/http", "8002/http"]' in controller
    assert '"stage1-error.json", control_token, port=8002' in controller
    assert '"stage1-status.json", control_token, port=8002' in controller
    assert '"qualifier-error-mirror.json", control_token, port=8002' in controller
    assert '"qualifier-status-mirror.json", control_token, port=8002' in controller
    assert "-8002.proxy.runpod.net/stage1-results.tar.gz" in controller
    assert "-8002.proxy.runpod.net/{filename}" in controller


def test_stage1_v3_preserves_qualifier_failure_evidence() -> None:
    driver = (SCRIPTS / "stage1_same_pod_driver_v3_controlplane.py").read_text(encoding="utf-8")
    assert 'write_json("qualifier-error-mirror.json", payload)' in driver
    assert 'write_json("qualifier-status-mirror.json", status)' in driver
    assert 'ROOT / "qualifier.stdout.log"' in driver
    assert 'ROOT / "qualifier.stderr.log"' in driver
    assert 'phase("qualification_child_started", child_pid=process.pid)' in driver
    assert "same-Pod assembly qualification failed: {error_type}: {message}" in driver
