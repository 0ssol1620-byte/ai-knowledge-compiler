"""WO-D10-0K: the arena page-server image workflow, checked without running it."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from infra.security.validate_repository import validate_supply_chain_pins

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github/workflows/build-arena-page-servers.yml"
PRECEDENT = ROOT / ".github/workflows/build-ovis-runtime.yml"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)", re.MULTILINE)
LISTING_STEP = "Save the build log section that holds the package listing"


def _workflow() -> dict[Any, Any]:
    parsed = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict)
    return parsed


def _steps() -> list[dict[str, Any]]:
    return list(_workflow()["jobs"]["build"]["steps"])


def test_references_only_actions_pinned_by_the_ovis_runtime_workflow() -> None:
    used = set(USES.findall(WORKFLOW.read_text(encoding="utf-8")))
    pinned = set(USES.findall(PRECEDENT.read_text(encoding="utf-8")))
    assert used
    assert used <= pinned, sorted(used - pinned)


def test_repository_pin_check_accepts_the_workflow() -> None:
    errors: list[str] = []
    validate_supply_chain_pins(errors)
    assert [error for error in errors if "build-arena-page-servers" in error] == []


def test_triggers_permissions_and_credentials_are_the_narrow_ones() -> None:
    parsed = _workflow()
    text = WORKFLOW.read_text(encoding="utf-8")
    triggers = parsed[True]  # PyYAML reads the bare key `on` as True
    assert set(triggers) == {"workflow_dispatch", "push"}
    assert triggers["workflow_dispatch"] == {}
    assert triggers["push"] == {
        "branches": ["codex/v34-c-arena-build"],
        "paths": [
            ".github/workflows/build-arena-page-servers.yml",
            "infra/runpod/v6/images/mineru-pipeline-akc/**",
            "infra/runpod/v6/images/paddleocr-vl-akc/**",
            "workers/gpu-common/pyproject.toml",
            "workers/gpu-common/uv.lock",
        ],
    }
    assert parsed["permissions"] == {"contents": "read", "packages": "write"}
    assert set(parsed["jobs"]) == {"build"}
    assert set(re.findall(r"secrets\.(\w+)", text)) == {"GITHUB_TOKEN"}
    checkout = [step for step in _steps() if "actions/checkout@" in str(step.get("uses"))]
    assert len(checkout) == 1
    assert checkout[0]["with"] == {"persist-credentials": False}
    assert "maximize-build-space@" in text
    for absent in ("actions/cache", "cache-from", "cache-to", "type=gha", "type=registry"):
        assert absent not in text


def test_matrix_builds_each_slot_from_its_dockerfile_and_context() -> None:
    entries = _workflow()["jobs"]["build"]["strategy"]["matrix"]["include"]
    by_slot = {entry["slot"]: entry for entry in entries}
    assert set(by_slot) == {"c0", "c3", "c1"}
    mineru = "infra/runpod/v6/images/mineru-pipeline-akc"
    assert by_slot["c0"]["context"] == mineru
    assert by_slot["c3"]["context"] == mineru
    assert by_slot["c1"]["context"] == "."
    assert by_slot["c1"]["dockerfile"] == "infra/runpod/v6/images/paddleocr-vl-akc/Dockerfile"
    for slot, entry in by_slot.items():
        dockerfile = (ROOT / entry["dockerfile"]).read_text(encoding="utf-8")
        assert entry["image"].startswith("arena-") and entry["image"] == entry["image"].lower()
        if entry["target"]:
            assert f" AS {entry['target']}" in dockerfile, slot
        else:
            assert " AS " not in dockerfile, slot
        bases = re.findall(r"^FROM \S+@sha256:[0-9a-f]{64}(?: |$)", dockerfile, re.MULTILINE)
        assert len(bases) == 1, slot
        # The step the listing is cut from is in this Dockerfile.
        assert entry["listing_marker"] in dockerfile, slot


def test_digest_is_read_back_from_the_registry_and_compared() -> None:
    steps = {step["name"]: step for step in _steps() if "name" in step}
    readback = steps["Read the manifest digest back from the registry"]["run"]
    assert "docker buildx imagetools inspect" in readback
    assert '"$registry_digest" != "$BUILD_DIGEST"' in readback
    build = steps["Build and push the amd64 image"]["run"]
    assert "--provenance=false" in build and "--sbom=false" in build
    assert "--progress=plain" in build and "--push" in build
    names = list(steps)
    assert names.index("Read the manifest digest back from the registry") < names.index(
        "Write the build receipt and the job summary"
    )
    upload = steps["Upload the build receipt, log and package listing"]["with"]
    assert upload["if-no-files-found"] == "error"


# The listing step's own script, run by bash on synthetic BuildKit plain logs.

_HEADER = "#12 [c0 4/8] RUN python -m pip install --require-hashes --no-deps -r x"
_OTHER = "#13 [c0 5/8] COPY weights-manifest.json /opt/akc/"


def _run_listing_step(
    tmp_path: Path, log_lines: list[str], marker: str = "--require-hashes"
) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to run the workflow step"
    script = next(step["run"] for step in _steps() if step.get("name") == LISTING_STEP)
    (tmp_path / "build.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8", newline="\n")
    return subprocess.run(
        [bash, "--noprofile", "--norc", "-c", script],
        env={
            **os.environ,
            "PATH": str(Path(bash).parent) + os.pathsep + os.environ.get("PATH", ""),
            "RUNNER_TEMP": tmp_path.as_posix(),
            "LISTING_MARKER": marker,
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_listing_step_keeps_every_line_of_each_matching_step_only(tmp_path: Path) -> None:
    log = [
        "#1 [internal] load build definition from Dockerfile",
        _HEADER,
        _OTHER,
        "#12 3.1 Collecting mineru==3.4.4",
        "#13 DONE 0.1s",
        "#12 40.2 Successfully installed mineru-3.4.4 torch-2.8.0",
        "#20 [c3 2/3] RUN python -m pip install --require-hashes -r /opt/akc/requirements-c3.lock",
        "#20 5.0 Successfully installed accelerate-1.14.0 psutil-7.2.2",
        "#20 DONE 6.0s",
        "#12 DONE 45.0s",
        "#121 [c0 9/9] RUN useradd --system akc",
        "#121 DONE 0.2s",
    ]
    result = _run_listing_step(tmp_path, log)
    assert result.returncode == 0, result.stderr
    listing = (tmp_path / "package-listing.log").read_text(encoding="utf-8").splitlines()
    assert listing == [line for line in log if line.split(" ", 1)[0] in {"#12", "#20"}]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ([_OTHER, "#13 DONE 0.1s"], "no build step ran a command containing"),
        (
            [_HEADER, "#12 3.1 a", "#12 [output clipped, log limit 2MiB reached]", "#12 DONE 9s"],
            "clipped",
        ),
        ([_HEADER, "#12 CACHED"], "came from cache"),
        (
            [_HEADER, "#12 3.1 Collecting a", "#12 ERROR: process did not complete"],
            "did not finish",
        ),
    ],
)
def test_listing_step_refuses_a_missing_clipped_cached_or_unfinished_listing(
    tmp_path: Path, lines: list[str], message: str
) -> None:
    result = _run_listing_step(tmp_path, lines)
    assert result.returncode != 0
    assert message in result.stderr
