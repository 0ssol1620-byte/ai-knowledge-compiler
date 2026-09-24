"""Trivy DS-0002: every baked runtime image ends as a non-root user.

Static checks on the 12 Dockerfiles and their entrypoints, plus the two runtime
behaviours the non-root user depends on: boot-time weight verification must not
write into the root-owned weights directory, and the worker must fall back off a
``/workspace`` it cannot write. None of this proves an image boots -- that is the
GPU canary's job.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from types import ModuleType

import pytest
from arena.worker.config import resolve_state_dir

from research.model_arena_20260903.tests.runtimes.conftest import (
    RUNTIMES_ROOT,
    load_runtime_module,
)

MODEL_KEYS = sorted(p.parent.name for p in RUNTIMES_ROOT.glob("*/Dockerfile"))
MUTABLE_ENV = {
    "ARENA_FATAL_FILE": "/var/lib/arena/FATAL",
    "ARENA_MODEL_SERVER_LOG": "/var/lib/arena/model-server.log",
    "ARENA_STATE_FALLBACK_DIR": "/var/lib/arena/state",
}
ROOT_USERS = {"root", "0"}


def instructions(text: str) -> list[tuple[str, str]]:
    """(KEYWORD, logical line) pairs: continuations joined, comments and heredoc bodies dropped."""

    out: list[tuple[str, str]] = []
    lines = iter(text.splitlines())
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        while line.endswith("\\"):
            nxt = next(lines).strip()
            line = line[:-1] + (" " if nxt.startswith("#") else " " + nxt)
        heredoc = re.search(r"<<-?'?([A-Z]+)'?", line)
        if heredoc:
            for body in lines:
                if body.strip() == heredoc.group(1):
                    break
        out.append((line.split()[0].upper(), line))
    return out


def final_stage(model_key: str) -> list[tuple[str, str]]:
    parsed = instructions((RUNTIMES_ROOT / model_key / "Dockerfile").read_text(encoding="utf-8"))
    last_from = max(i for i, (kw, _) in enumerate(parsed) if kw == "FROM")
    return parsed[last_from:]


def env_values(stage: list[tuple[str, str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for kw, line in stage:
        if kw == "ENV":
            values.update(re.findall(r"(\w+)=(\S+)", line))
    return values


def test_all_twelve_runtimes_are_checked() -> None:
    assert len(MODEL_KEYS) == 12, MODEL_KEYS


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_model_key_is_supplied_by_pod_runtime_not_baked_in_image(model_key: str) -> None:
    # The controller supplies this public identifier at pod creation. Baking it
    # into ENV is redundant and Trivy mistakes the word KEY for a secret.
    assert "ARENA_MODEL_KEY" not in env_values(final_stage(model_key))


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_final_stage_ends_non_root_after_every_build_step(model_key: str) -> None:
    stage = final_stage(model_key)
    users = [i for i, (kw, _) in enumerate(stage) if kw == "USER"]
    assert users, f"{model_key}: final stage never sets USER"
    user = stage[users[-1]][1].split()[1]
    assert user.split(":")[0] not in ROOT_USERS, f"{model_key}: final USER is {user}"
    # Receipts, weights and code are all written as root, before the switch, so
    # they stay root-owned and their recorded contents are unchanged.
    after = {kw for kw, _ in stage[users[-1] + 1 :]}
    assert after <= {"EXPOSE", "WORKDIR", "ENTRYPOINT", "CMD", "ENV"}, (model_key, after)


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_build_stages_before_the_final_one_stay_root(model_key: str) -> None:
    parsed = instructions((RUNTIMES_ROOT / model_key / "Dockerfile").read_text(encoding="utf-8"))
    last_from = max(i for i, (kw, _) in enumerate(parsed) if kw == "FROM")
    assert all(kw != "USER" for kw, _ in parsed[:last_from]), model_key


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_only_the_mutable_directories_change_owner(model_key: str) -> None:
    stage = final_stage(model_key)
    runs = [line for kw, line in stage if kw == "RUN"]
    assert not any(re.search(r"\bchown\b", line) for line in runs), (
        f"{model_key}: chown would copy the weight layer and hand receipts to the runtime user"
    )
    owned = [line for line in runs if "install -d -o" in line]
    assert len(owned) == 1, f"{model_key}: expected one install -d -o line"
    targets = set(owned[0].split(" -m 0750 ")[1].split())
    assert targets == {"/var/lib/arena", "/var/lib/arena/state", "/workspace/arena"}, targets
    # A root-created /workspace dir is exactly what the non-root user cannot write.
    assert not any("mkdir" in line and "/workspace" in line for line in runs), model_key
    env = env_values(stage)
    for name, value in MUTABLE_ENV.items():
        assert env.get(name) == value, (model_key, name, env.get(name))
    assert "ARENA_STATE_DIR" not in env, f"{model_key}: a fixed state dir defeats the fallback"


@pytest.mark.parametrize("model_key", MODEL_KEYS)
def test_entrypoint_writes_where_the_image_says(model_key: str) -> None:
    text = (RUNTIMES_ROOT / model_key / "entrypoint.sh").read_text(encoding="utf-8")
    for var, env in (("FATAL_FILE", "ARENA_FATAL_FILE"), ("SERVER_LOG", "ARENA_MODEL_SERVER_LOG")):
        for assignment in re.findall(rf"^\s*{var}=(.*)$", text, flags=re.MULTILINE):
            assert assignment.startswith(f'"${{{env}:-'), (model_key, var, assignment)


# --------------------------------------------------------------------------- #
# boot-time weight verification is read-only
# --------------------------------------------------------------------------- #

FETCH_WEIGHTS_KEYS = sorted(p.parent.name for p in RUNTIMES_ROOT.glob("*/fetch_weights.py"))
REVISION = "a" * 40


def _prepared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, module: ModuleType, runtime: dict[str, object]
) -> Path:
    weights = tmp_path / "weights"
    weights.mkdir()
    (weights / "model.safetensors").write_bytes(b"weights")
    runtime_json = tmp_path / "runtime.json"
    runtime_json.write_text(json.dumps(runtime), encoding="utf-8")
    monkeypatch.setattr(module, "RUNTIME_JSON", runtime_json)
    return weights


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("model_key", FETCH_WEIGHTS_KEYS)
def test_cache_hit_verifies_without_rewriting_the_sidecar(
    model_key: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_runtime_module(model_key, "fetch_weights")
    weights = _prepared(
        tmp_path,
        monkeypatch,
        module,
        {
            "weights": {
                "repo": "o/r",
                "revision": REVISION,
                "largest_file": "model.safetensors",
                "largest_file_sha256": _digest(b"weights"),
            }
        },
    )
    sidecar = weights / module.SIDECAR_NAME
    built = json.dumps({"revision": REVISION, "files_manifest_sha256": "sha256:" + "1" * 64})
    sidecar.write_text(built, encoding="utf-8")

    assert module.main(["--weights-dir", str(weights)]) == 0
    assert sidecar.read_text(encoding="utf-8") == built
    assert sorted(p.name for p in weights.iterdir()) == sorted([sidecar.name, "model.safetensors"])

    (weights / "model.safetensors").write_bytes(b"tampered")
    assert module.main(["--weights-dir", str(weights)]) == 4
    sidecar.write_text(json.dumps({"revision": "b" * 40}), encoding="utf-8")
    assert module.main(["--weights-dir", str(weights)]) == 2


def test_glm_layout_cache_hit_verifies_without_rewriting_the_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_runtime_module("glm_ocr", "fetch_layout_model")
    layout = _prepared(
        tmp_path,
        monkeypatch,
        module,
        {
            "inference_config": {
                "layout_model_repo": "o/r",
                "layout_model_revision": REVISION,
                "layout_model_largest_file": "model.safetensors",
                "layout_model_largest_file_sha256": _digest(b"weights"),
                "layout_model_dir": str(tmp_path / "unused"),
            }
        },
    )
    sidecar = layout / module.SIDECAR_NAME
    built = json.dumps({"revision": REVISION})
    sidecar.write_text(built, encoding="utf-8")

    assert module.main(["--layout-dir", str(layout)]) == 0
    assert sidecar.read_text(encoding="utf-8") == built
    (layout / "model.safetensors").write_bytes(b"tampered")
    assert module.main(["--layout-dir", str(layout)]) == 4


# --------------------------------------------------------------------------- #
# worker state dir under a root-owned /workspace volume
# --------------------------------------------------------------------------- #


def test_explicit_state_dir_wins_without_probing(tmp_path: Path) -> None:
    default = tmp_path / "never" / "arena"
    env = {"ARENA_STATE_DIR": "/explicit", "ARENA_STATE_FALLBACK_DIR": str(tmp_path / "fb")}
    assert resolve_state_dir(env, default=default) == Path("/explicit")
    assert not default.exists()


def test_without_a_fallback_the_default_is_returned_unprobed(tmp_path: Path) -> None:
    default = tmp_path / "never" / "arena"
    assert resolve_state_dir({}, default=default) == default
    assert not default.exists()


def test_writable_default_is_kept(tmp_path: Path) -> None:
    default = tmp_path / "workspace" / "arena"
    env = {"ARENA_STATE_FALLBACK_DIR": str(tmp_path / "fb")}
    assert resolve_state_dir(env, default=default) == default
    assert default.is_dir() and list(default.iterdir()) == []


def test_unwritable_default_falls_back_and_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    blocker = tmp_path / "workspace"
    blocker.write_text("a file where the volume should be", encoding="utf-8")
    fallback = tmp_path / "var-lib-arena-state"
    env = {"ARENA_STATE_FALLBACK_DIR": str(fallback)}
    assert resolve_state_dir(env, default=blocker / "arena") == fallback
    assert f"ARENA_STATE_DIR={fallback}" in capsys.readouterr().err
