from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / ".."
    / "tools"
    / "release"
    / "provision_folynta_dedicated_recovery_pod.ps1"
).resolve()


def test_dedicated_recovery_provisioning_is_bounded_to_secure_4090_by_default() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")

    assert "cloudType = 'SECURE'" in source
    assert "[string]$GpuTypeId = 'NVIDIA GeForce RTX 4090'" in source
    assert "gpuTypeIds = @($GpuTypeId)" in source
    assert "[ValidateSet('NVIDIA GeForce RTX 4090', 'NVIDIA GeForce RTX 5090', 'NVIDIA A40')]" in source
    assert "pod-create-retry" in source
    assert "if ($rate -le 0 -or $rate -gt 1.05)" in source
    assert "supportPublicIp = $true" in source


def test_dedicated_recovery_provisioning_deletes_and_verifies_on_timeout() -> None:
    source = SCRIPT.read_text(encoding="utf-8-sig")

    assert "function Remove-BoundedPod" in source
    assert "-Method Delete -Uri \"https://rest.runpod.io/v1/pods/$PodId\"" in source
    assert "pod-delete-verified" in source
    assert "Remove-BoundedPod -PodId $podId -Reason 'ssh-readiness-timeout'" in source
