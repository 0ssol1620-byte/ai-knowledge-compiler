from pathlib import Path


SCRIPT = Path(__file__).with_name("remote_bootstrap_paddle_recovery.sh")
CONTROLLER = (
    Path(__file__).parents[1]
    / ".."
    / "tools"
    / "release"
    / "continue_folynta_preofficial_operational_paddle.ps1"
).resolve()


def test_paddle_bootstrap_freezes_protobuf_compatibility_dependency() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "pip install 'protobuf==6.33.6'" in source
    assert '"protobuf": "6.33.6"' in source
    assert source.index("pip install 'protobuf==6.33.6'") < source.index(
        'patch_file="$venv/lib/python3.11/site-packages/fastdeploy/input/text_processor.py"'
    )


def test_preofficial_controller_uses_native_exit_code_not_stderr_as_failure() -> None:
    source = CONTROLLER.read_text(encoding="utf-8-sig")

    assert "$ErrorActionPreference = 'Continue'" in source
    assert "$exitCode = $LASTEXITCODE" in source
    assert 'if ($exitCode -ne 0)' in source
    assert "folynta-composite-r3-paddle-op-2026-08-06" in source
    assert "folynta-merged-r3-paddle-op-2026-08-06" in source
    assert "paddle-collection-resume" in source
