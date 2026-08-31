"""Static checks on the D3/D4 baked confirmatory image definitions.

These tests read the Dockerfile / verify-runtime.sh content only. They never
invoke Docker, never download a model, and never touch a GPU.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PADDLE_DIR = ROOT / "infra/runpod/v6/images/paddleocr-vl-1.6-fastdeploy-c8"
MINERU_DIR = ROOT / "infra/runpod/v6/images/mineru-3.4.4-vlm-c1"
POD_CLIENT = ROOT / "infra/runpod/v6/pod_client.py"

PADDLE_WEIGHTS_REVISION = "66317acc4c9fc17bd154591ce650735cd2855f3e"
PADDLE_ARTIFACT_SHA256 = (
    "40ca2a90af83f79a9adf2d5ddb7e32187e6956e45e5730119595be7305e06a53"
)
MINERU_SOURCE_REVISION = "79d6d8d79fb8f3ddba5cc34c07a16f0ec36f56c7"
MINERU_WEIGHTS_REVISION = "bff20d4ae2bf202df9f45284b4d43681555a97ed"

_FROM_DIGEST_RE = re.compile(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\s*$", re.MULTILINE)
_FROM_LINE_RE = re.compile(r"^FROM\s+(\S+)\s*$", re.MULTILINE)


def _runtime_install_markers() -> tuple[str, ...]:
    text = POD_CLIENT.read_text(encoding="utf-8")
    match = re.search(r"_RUNTIME_INSTALL_MARKERS\s*=\s*\((.*?)\)\n", text, re.DOTALL)
    assert match, "could not locate _RUNTIME_INSTALL_MARKERS in pod_client.py"
    markers = tuple(re.findall(r'"([^"]+)"', match.group(1)))
    assert markers, "_RUNTIME_INSTALL_MARKERS parsed to an empty tuple"
    return markers


def test_neither_verify_runtime_script_contains_a_forbidden_install_marker() -> None:
    markers = _runtime_install_markers()
    for image_dir in (PADDLE_DIR, MINERU_DIR):
        script_text = (image_dir / "verify-runtime.sh").read_text(encoding="utf-8").lower()
        for marker in markers:
            assert marker not in script_text, (
                f"{image_dir.name}/verify-runtime.sh contains forbidden install marker "
                f"{marker!r}"
            )


def test_neither_verify_runtime_script_checks_the_receipt_object_hash_as_a_file_hash() -> None:
    # The F-8 antipattern: comparing FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256 (the
    # canonical hash of the whole qualification-receipt OBJECT) against a file
    # hash via `sha256sum --check`. Both scripts must only ever read/log it.
    for image_dir in (PADDLE_DIR, MINERU_DIR):
        script_text = (image_dir / "verify-runtime.sh").read_text(encoding="utf-8")
        for line in script_text.splitlines():
            if "sha256sum --check" in line or "sha256sum -c" in line:
                assert "FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256" not in line, (
                    f"{image_dir.name}/verify-runtime.sh checks the receipt-object hash "
                    f"as a file hash: {line!r}"
                )
        # It must still be referenced (read for logging) somewhere in the script.
        assert "FOLYNTA_BAKED_RUNTIME_RECEIPT_SHA256" in script_text


def test_paddle_dockerfile_contains_exact_pinned_identity_verbatim() -> None:
    text = (PADDLE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert PADDLE_WEIGHTS_REVISION in text
    assert PADDLE_ARTIFACT_SHA256 in text


def test_mineru_dockerfile_contains_exact_pinned_identities_verbatim_and_never_swapped() -> None:
    text = (MINERU_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert MINERU_SOURCE_REVISION in text
    assert MINERU_WEIGHTS_REVISION in text
    assert MINERU_SOURCE_REVISION != MINERU_WEIGHTS_REVISION

    # git clone/checkout RUN block only ever references the source revision.
    match = re.search(r"RUN git clone.*?(?=\n\n|\nRUN )", text, re.DOTALL)
    assert match, "expected a git clone/checkout RUN block in the MinerU Dockerfile"
    checkout_block = match.group(0)
    assert "SOURCE_REVISION" in checkout_block
    assert MINERU_WEIGHTS_REVISION not in checkout_block

    # snapshot_download() call block only ever references the weights revision
    # -- not the comment near the top of the file that merely mentions the
    # word "snapshot_download" in prose.
    heredoc_blocks = re.findall(r"RUN python3 - <<'PY'\n(.*?)\nPY", text, re.DOTALL)
    call_blocks = [block for block in heredoc_blocks if "snapshot_download(" in block]
    assert call_blocks, "expected a snapshot_download(...) call block in the MinerU Dockerfile"
    for block in call_blocks:
        assert "MODEL_REVISION" in block
        assert MINERU_SOURCE_REVISION not in block


def test_both_dockerfiles_use_an_immutable_from_digest_never_a_floating_tag() -> None:
    for image_dir in (PADDLE_DIR, MINERU_DIR):
        text = (image_dir / "Dockerfile").read_text(encoding="utf-8")
        from_lines = _FROM_LINE_RE.findall(text)
        assert from_lines, f"{image_dir.name}/Dockerfile has no FROM line"
        for from_ref in from_lines:
            assert re.fullmatch(r"\S+@sha256:[0-9a-f]{64}", from_ref), (
                f"{image_dir.name}/Dockerfile FROM is not an immutable digest: {from_ref!r}"
            )


def test_mineru_dockerfile_and_readme_carry_agpl_research_only_labeling() -> None:
    dockerfile_text = (MINERU_DIR / "Dockerfile").read_text(encoding="utf-8")
    readme_text = (MINERU_DIR / "README.md").read_text(encoding="utf-8")

    for text, label in ((dockerfile_text, "Dockerfile"), (readme_text, "README.md")):
        lowered = text.lower()
        assert "agpl" in lowered, f"MinerU {label} is missing AGPL labeling"
        assert "research" in lowered, f"MinerU {label} is missing research-only labeling"
        assert "commercial" in lowered, (
            f"MinerU {label} is missing a no-commercial-promotion statement"
        )

    assert 'org.opencontainers.image.licenses="AGPL-3.0-or-upstream-current"' in dockerfile_text
    assert 'folynta.commercial_promotion="forbidden"' in dockerfile_text


def test_paddle_dockerfile_carries_no_agpl_research_only_labeling() -> None:
    # Sanity control: the Apache-licensed Paddle image must not accidentally
    # inherit the MinerU research-only restriction.
    text = (PADDLE_DIR / "Dockerfile").read_text(encoding="utf-8")
    assert "AGPL" not in text
    assert "research_comparator_only" not in text
