"""D8 — secret/credential audit over every file new to the runtime
qualification round (D1-D7): the rq-01 lineage directory, the two new baked
image definitions, the confirmatory-images workflow, the two D6
anti-fabrication modules, and the D5/D7 test files.

The forbidden-pattern regex is reproduced verbatim from
``research/tavonel_recovery_eval_v1/runpod_qualification.py`` (``_redacted_json``,
lines ~225-229), read there and never imported or modified — that module has
no importable package boundary crossing into ``infra.runpod.v6``.

See ``infra/runpod/v6/qualification/rq-01/SECURITY_REVIEW.md`` for the full
narrative review this test file backs.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from infra.runpod.v6.build_runtime_qualification import (
    build_qualification_receipt,
    validate_and_write,
)
from infra.runpod.v6.runtime_smoke_baseline import build_and_seal_baseline

ROOT = Path(__file__).resolve().parents[3]

# The exact regex from research/tavonel_recovery_eval_v1/runpod_qualification.py
# _redacted_json (line ~227) -- reproduced, not imported, since that module is a
# standalone script with no package boundary.
FORBIDDEN_PATTERN = re.compile(r"(?i)(bearer\s+|runpod_b|api[_-]?key|authorization)")

D6_FORBIDDEN_MARKERS = (
    "os.environ",
    "getenv",
    "httpx",
    "requests",
    "RunPodPodClient",
    "PodCreateSpec(",
)

D6_MODULES = (
    ROOT / "infra/runpod/v6/runtime_smoke_baseline.py",
    ROOT / "infra/runpod/v6/build_runtime_qualification.py",
)

WORKFLOW_PATH = ROOT / ".github/workflows/baked-confirmatory-images.yml"

# This D8 round's own two deliverables are the audit's *output*, not part of
# what it audits -- excluded from the scanned set below. Both necessarily
# quote the forbidden pattern and the FAKE_API_KEY identifier by name (to
# document the regex and the one resolved false positive), so scanning them
# with their own regex would be a self-referential paradox, not a finding.
_SELF_PATHS = frozenset(
    {
        ROOT / "infra/runpod/v6/qualification/rq-01/SECURITY_REVIEW.md",
        Path(__file__).resolve(),
    }
)

# One narrowly-scoped, documented exemption: benchmark/tests/v6/
# test_confirmatory_pod_controller.py deliberately defines a fake credential
# constant (FAKE_API_KEY = "fake-test-key-not-a-real-runpod-credential") to
# exercise RunPodPodClient against an httpx.MockTransport, and two tests in
# that file assert the fake key never appears in a serialized receipt. The
# identifier name itself matches `api[_-]?key`, so its line numbers are
# exempted here -- but only after confirming (below, in
# test_pod_controller_api_key_matches_are_only_the_known_fake_constant) that
# every match in that file really is this fake constant, never a real secret.
_EXEMPT_FILE = "test_confirmatory_pod_controller.py"


def _new_files() -> list[Path]:
    """Every file newly introduced by this round, discovered by walking the
    directories/files this task named -- never a hardcoded filename list, so
    a file added later under any of these roots is picked up automatically.
    """

    files: list[Path] = []
    for rel_dir in (
        "infra/runpod/v6/qualification/rq-01",
        "infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8",
        "infra/runpod/v6/images/mineru-3.4.4-vlm-c1",
    ):
        files.extend(p for p in (ROOT / rel_dir).rglob("*") if p.is_file())

    files.append(WORKFLOW_PATH)
    files.extend(D6_MODULES)

    tests_dir = ROOT / "benchmark/tests/v6"
    for pattern in ("test_confirmatory_*.py", "test_runtime_qualification_*.py"):
        files.extend(sorted(tests_dir.glob(pattern)))
    files.append(tests_dir / "test_frozen_science_boundary.py")

    # De-duplicate while preserving order (D6 modules / this file's own glob
    # could not overlap, but keep this robust if the scoped roots ever do),
    # and drop this round's own audit deliverables (see _SELF_PATHS above).
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in files:
        resolved = path.resolve()
        if resolved in _SELF_PATHS:
            continue
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


NEW_FILES = _new_files()


def test_new_file_discovery_found_the_expected_shape() -> None:
    """Guards against the rglob/glob scoping above silently finding nothing."""

    assert len(NEW_FILES) >= 20, f"expected at least 20 new files, found {len(NEW_FILES)}"
    relative = {p.relative_to(ROOT).as_posix() for p in NEW_FILES}
    assert "infra/runpod/v6/qualification/rq-01/lineage.json" in relative
    assert "infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8/Dockerfile" in relative
    assert "infra/runpod/v6/images/mineru-3.4.4-vlm-c1/Dockerfile" in relative
    assert ".github/workflows/baked-confirmatory-images.yml" in relative
    assert "infra/runpod/v6/runtime_smoke_baseline.py" in relative
    assert "infra/runpod/v6/build_runtime_qualification.py" in relative
    # At least the 6 test files the task named, by their D5/D7 naming prefix.
    test_file_names = {
        p.name for p in NEW_FILES if p.suffix == ".py" and p.name.startswith("test_")
    }
    assert {
        "test_confirmatory_image_workflow.py",
        "test_confirmatory_pod_controller.py",
        "test_confirmatory_runtime_images.py",
        "test_frozen_science_boundary.py",
        "test_runtime_qualification_builder.py",
        "test_runtime_qualification_fixture.py",
        "test_runtime_qualification_lineage.py",
    }.issubset(test_file_names)


# --------------------------------------------------------------------------
# 1. No new file contains the forbidden credential-shaped pattern
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", NEW_FILES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_new_file_has_no_forbidden_credential_pattern(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # rq-01-smoke-001.png -- a binary fixture, not text. Scanned as raw
        # bytes instead: the pattern is ASCII, so a byte-level search is
        # equivalent and catches an embedded ASCII secret in binary content.
        raw = path.read_bytes()
        assert not FORBIDDEN_PATTERN.search(raw.decode("latin-1")), (
            f"forbidden credential-shaped pattern found in binary file {path}"
        )
        return

    matches = list(FORBIDDEN_PATTERN.finditer(text))
    if not matches:
        return

    if path.name == _EXEMPT_FILE:
        # Every match here must be tied to the documented fake constant --
        # verified in detail by the dedicated test below. This branch only
        # allows the file to pass past the blanket assertion.
        return

    line_numbers = sorted({text.count("\n", 0, m.start()) + 1 for m in matches})
    pytest.fail(
        f"forbidden credential-shaped pattern found in {path} at line(s) {line_numbers}"
    )


def test_pod_controller_api_key_matches_are_only_the_known_fake_constant() -> None:
    """Confirms the one exempted file's matches are exactly the documented
    fake credential, never a real secret slipped in alongside it.
    """

    path = ROOT / "benchmark/tests/v6/test_confirmatory_pod_controller.py"
    text = path.read_text(encoding="utf-8")

    fake_key_definition = re.search(
        r'FAKE_API_KEY\s*=\s*"([^"]+)"', text
    )
    assert fake_key_definition is not None, "FAKE_API_KEY constant definition not found"
    fake_key_value = fake_key_definition.group(1)
    assert fake_key_value == "fake-test-key-not-a-real-runpod-credential"

    lines = text.splitlines()
    for match in FORBIDDEN_PATTERN.finditer(text):
        line_no = text.count("\n", 0, match.start())
        line = lines[line_no]
        assert "FAKE_API_KEY" in line or "api_key=FAKE_API_KEY" in line, (
            f"unexpected forbidden-pattern match not tied to FAKE_API_KEY: {line!r}"
        )

    # And the file must actually assert the fake key is absent from receipts
    # (the security-positive tests SECURITY_REVIEW.md cites).
    assert "assert FAKE_API_KEY not in serialized" in text


# --------------------------------------------------------------------------
# 2. D6 anti-fabrication modules touch no environment, network, or client
# --------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", D6_MODULES, ids=lambda p: p.name)
def test_d6_module_has_no_environment_network_or_client_markers(module_path: Path) -> None:
    source = module_path.read_text(encoding="utf-8")
    for marker in D6_FORBIDDEN_MARKERS:
        assert marker not in source, f"{module_path.name} unexpectedly contains {marker!r}"


# --------------------------------------------------------------------------
# 3. The workflow references only secrets.GITHUB_TOKEN
# --------------------------------------------------------------------------


def test_workflow_references_only_secrets_github_token() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    secret_references = set(re.findall(r"secrets\.[A-Za-z0-9_]+", text))
    assert secret_references == {"secrets.GITHUB_TOKEN"}


def test_workflow_never_echoes_the_token_directly_to_a_log_line() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # The one legitimate use pipes it straight into docker login's stdin.
    assert 'echo "$GHCR_TOKEN" | docker login' in text
    # No standalone `echo "$GHCR_TOKEN"` (or the raw env expression) printed
    # on its own to a log line anywhere else in the file.
    for line in text.splitlines():
        stripped = line.strip()
        if "GHCR_TOKEN" not in stripped:
            continue
        assert stripped in (
            'env:',
            'GHCR_TOKEN: ${{ secrets.GITHUB_TOKEN }}',
            'run: echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin',
        ), f"unexpected GHCR_TOKEN usage: {line!r}"


def test_workflow_checkout_step_disables_persisted_credentials() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    checkout_index = text.index("actions/checkout@")
    following = text[checkout_index : checkout_index + 200]
    assert "persist-credentials: false" in following


# --------------------------------------------------------------------------
# 4. A real qualification receipt, built with synthetic evidence, leaks no
#    secret-shaped substring when serialized
# --------------------------------------------------------------------------


def _write_markdown_run(root: Path, *, case_id: str, content: str, repeat: int) -> Path:
    repeat_dir = root / f"markdown-repeat-{repeat}"
    repeat_dir.mkdir(parents=True, exist_ok=True)
    (repeat_dir / f"{case_id}.md").write_text(content, encoding="utf-8")
    return root


def _write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return path


def test_serialized_qualification_receipt_has_no_secret_shaped_substring(tmp_path: Path) -> None:
    image_digest = "ghcr.io/tavonel/test-image@sha256:" + "a" * 64
    weights_revision = "synthetic-weights-revision-0001"
    model_artifact_sha256 = "sha256:" + "5" * 64
    lineage_target = "synthetic-target"
    content = "# Case A\n\nSample smoke body text.\n"

    baseline_repeat_dirs = tuple(
        _write_markdown_run(
            tmp_path / f"baseline-repeat-{i}", case_id="case-a", content=content, repeat=i
        )
        for i in (1, 2, 3)
    )
    baseline_output = tmp_path / "baseline.json"
    build_and_seal_baseline(
        repeat_dirs=baseline_repeat_dirs,  # type: ignore[arg-type]
        pod_id="baseline-pod",
        started_at="2026-01-01T00:00:00+00:00",
        image_digest=image_digest,
        output_path=baseline_output,
        sealed_at="2026-01-01T00:10:00+00:00",
    )

    validation_dir = _write_markdown_run(
        tmp_path / "validation", case_id="case-a", content=content, repeat=1
    )
    smoke_input_path = tmp_path / "smoke-input.bin"
    smoke_input_path.write_bytes(b"synthetic smoke input bytes, not a real image")

    build_receipt_path = _write_json(
        tmp_path / "build-receipt.json",
        {
            "source_commit": "d" * 40,
            "source_tree_sha256": "sha256:" + "1" * 64,
            "dockerfile_sha256": "sha256:" + "2" * 64,
            "image_digest": image_digest,
            "sbom_sha256": "sha256:" + "3" * 64,
            "vulnerability_scan_sha256": "sha256:" + "4" * 64,
            "critical_vulnerability_count": 0,
            "model_revision": weights_revision,
            "model_artifact_sha256": model_artifact_sha256,
        },
    )
    runtime_identity_path = _write_json(
        tmp_path / "runtime-identity.json",
        {"gpu_type": "NVIDIA A40", "cuda_version": "12.4", "framework_version": "test-fw-1.0.0"},
    )
    lineage_path = _write_json(
        tmp_path / "lineage.json",
        {
            "targets": {
                lineage_target: {
                    "weights_revision": weights_revision,
                    "artifact_sha256": model_artifact_sha256,
                }
            }
        },
    )

    receipt = build_qualification_receipt(
        baseline_receipt_path=baseline_output,
        validation_run_id="validation-pod@2026-01-02T00:00:00+00:00",
        validation_started_at="2026-01-02T00:00:00+00:00",
        validation_image_digest=image_digest,
        validation_markdown_dir=validation_dir,
        smoke_input_path=smoke_input_path,
        build_receipt_path=build_receipt_path,
        runtime_identity_path=runtime_identity_path,
        lineage_path=lineage_path,
        lineage_target=lineage_target,
        baked_runtime_file_sha256="sha256:" + "6" * 64,
    )
    assert receipt["passed"] is True

    output_path = tmp_path / "qualification.json"
    validate_and_write(receipt, output_path)

    serialized = output_path.read_text(encoding="utf-8")
    assert not FORBIDDEN_PATTERN.search(serialized), (
        "serialized qualification receipt unexpectedly contains a secret-shaped substring"
    )
    # And the in-memory dict, re-serialized independently, agrees.
    assert not FORBIDDEN_PATTERN.search(json.dumps(receipt, sort_keys=True))
