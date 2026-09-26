"""Runtime provenance collection (masterplan section 38).

Answers one question for every receipt: *what was actually running when this
page was parsed?* Anything that cannot be observed is reported as ``null`` with
a reason in ``unavailable`` — never as an empty string, a zero, or a guess.

Nothing here imports torch, transformers or vllm. Importing torch initialises
CUDA and costs seconds; versions come from installed-distribution metadata, and
CUDA/driver facts come from ``nvidia-smi`` plus whatever the adapter already
imported into ``sys.modules``.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any, Final

from arena.worker.util import redact, sha256_label, utcnow

OS_RELEASE_PATH: Final = Path("/etc/os-release")
TRACKED_PACKAGES: Final = (
    "torch",
    "torchvision",
    "transformers",
    "vllm",
    "flash_attn",
    "flash-attn",
    "accelerate",
    "paddlepaddle-gpu",
    "pillow",
)
_NVIDIA_SMI_TIMEOUT: Final = 15.0
_PIP_FREEZE_TIMEOUT: Final = 120.0
_DPKG_TIMEOUT: Final = 60.0


def _run(command: list[str], timeout: float) -> tuple[bool, str, str]:
    """Run a command; never raise. Returns ``(ok, stdout, reason)``."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, "", f"{command[0]} not found"
    except subprocess.TimeoutExpired:
        return False, "", f"{command[0]} timed out after {timeout:g}s"
    except OSError as exc:
        return False, "", redact(f"{command[0]} failed to start: {exc}")
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else ""
        return False, "", redact(f"{command[0]} exited {completed.returncode}: {tail}"[:400])
    return True, completed.stdout, ""


def _distribution_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in TRACKED_PACKAGES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
        except (ValueError, OSError):  # pragma: no cover - broken dist metadata
            versions[name] = None
    return versions


def _freeze_from_metadata() -> str:
    lines: list[str] = []
    for dist in metadata.distributions():
        name = dist.name
        if not name:
            continue
        lines.append(f"{name}=={dist.version}")
    return "\n".join(sorted(set(lines))) + "\n"


def _pip_freeze(*, run_subprocess: bool) -> tuple[str, str, str | None]:
    """Return ``(text, source, reason_if_degraded)``."""
    if run_subprocess:
        ok, out, reason = _run(
            [sys.executable, "-m", "pip", "freeze", "--disable-pip-version-check"],
            _PIP_FREEZE_TIMEOUT,
        )
        if ok:
            return out, "pip freeze", None
        return _freeze_from_metadata(), "importlib.metadata", reason
    return (
        _freeze_from_metadata(),
        "importlib.metadata",
        "pip freeze subprocess disabled by caller",
    )


def _os_release() -> tuple[dict[str, str] | None, str | None]:
    if not OS_RELEASE_PATH.is_file():
        return None, f"{OS_RELEASE_PATH} not present (non-Linux host)"
    try:
        text = OS_RELEASE_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:  # pragma: no cover - unreadable /etc
        return None, redact(f"{OS_RELEASE_PATH} unreadable: {exc}")
    parsed: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip().strip('"')
    return parsed, None


def _apt_snapshot() -> tuple[str | None, int | None, str | None]:
    if shutil.which("dpkg-query") is None:
        return None, None, "dpkg-query not found (non-Debian image)"
    ok, out, reason = _run(
        ["dpkg-query", "-W", "-f=${Package}\t${Version}\n"], _DPKG_TIMEOUT
    )
    if not ok:
        return None, None, reason
    lines = sorted(line for line in out.splitlines() if line.strip())
    joined = "\n".join(lines) + "\n"
    return sha256_label(joined.encode("utf-8")), len(lines), None


def _nvidia_smi() -> tuple[dict[str, Any], str | None]:
    if shutil.which("nvidia-smi") is None:
        return {}, "nvidia-smi not found on PATH"
    ok, out, reason = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,driver_version,memory.total,compute_cap",
            "--format=csv,noheader,nounits",
        ],
        _NVIDIA_SMI_TIMEOUT,
    )
    if not ok:
        return {}, reason
    gpus: list[dict[str, Any]] = []
    driver: str | None = None
    for line in out.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        driver = driver or parts[1]
        gpus.append(
            {
                "name": parts[0],
                "driver_version": parts[1],
                "memory_total_mib": int(parts[2]) if parts[2].isdigit() else None,
                "compute_capability": parts[3],
            }
        )
    if not gpus:
        return {}, "nvidia-smi returned no GPU rows"
    return {"gpus": gpus, "driver_version": driver}, None


def _torch_facts() -> tuple[dict[str, Any], str | None]:
    """Read CUDA facts from torch only if the adapter already imported it."""
    torch = sys.modules.get("torch")
    if torch is None:
        return {}, "torch is not imported in this process; not imported here on purpose"
    version_mod = getattr(torch, "version", None)
    cuda_mod = getattr(torch, "cuda", None)
    available: bool | None = None
    if cuda_mod is not None:
        try:
            available = bool(cuda_mod.is_available())
        except Exception:  # pragma: no cover - driver-level failure
            available = None
    return (
        {
            "torch_version": getattr(torch, "__version__", None),
            "torch_cuda_version": getattr(version_mod, "cuda", None),
            "torch_cudnn_version": getattr(version_mod, "cudnn", None),
            "torch_cuda_available": available,
        },
        None,
    )


def collect_provenance(
    *,
    image_digest: str | None = None,
    adapter_provenance: Mapping[str, Any] | None = None,
    run_pip_freeze: bool = True,
) -> dict[str, Any]:
    """Collect everything masterplan section 38 asks an image to record."""
    unavailable: dict[str, str] = {}

    os_release, os_reason = _os_release()
    if os_reason:
        unavailable["os_release"] = os_reason

    freeze_text, freeze_source, freeze_reason = _pip_freeze(run_subprocess=run_pip_freeze)
    if freeze_reason:
        unavailable["pip_freeze"] = freeze_reason

    apt_sha, apt_count, apt_reason = _apt_snapshot()
    if apt_reason:
        unavailable["apt_snapshot"] = apt_reason

    smi, smi_reason = _nvidia_smi()
    if smi_reason:
        unavailable["nvidia_smi"] = smi_reason

    torch_facts, torch_reason = _torch_facts()
    if torch_reason:
        unavailable["torch_runtime"] = torch_reason

    versions = _distribution_versions()

    return {
        "collected_at": utcnow(),
        "image_digest": image_digest,
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "compiler": platform.python_compiler(),
        },
        "os": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "os_release": os_release,
        },
        "versions": versions,
        "torch": torch_facts or None,
        "cuda": {
            "torch_cuda_version": torch_facts.get("torch_cuda_version"),
            "torch_cuda_available": torch_facts.get("torch_cuda_available"),
        },
        "driver": {"nvidia_smi_driver_version": smi.get("driver_version")},
        "gpus": smi.get("gpus"),
        "pip_freeze_text": freeze_text,
        "pip_freeze_sha256": sha256_label(freeze_text.encode("utf-8")),
        "pip_freeze_source": freeze_source,
        "apt_snapshot_sha256": apt_sha,
        "apt_package_count": apt_count,
        "adapter": dict(adapter_provenance) if adapter_provenance is not None else None,
        "unavailable": unavailable,
    }


__all__ = ["OS_RELEASE_PATH", "TRACKED_PACKAGES", "collect_provenance"]
