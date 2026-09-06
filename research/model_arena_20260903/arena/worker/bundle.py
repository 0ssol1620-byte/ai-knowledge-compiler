"""Worker bundle packaging (contract section 6.4, masterplan section 37).

A bundle is the bootstrap-mode alternative to a baked image: a tar.gz holding
the parts of the ``arena`` package the on-pod worker imports, one runtime
directory, the prompt registry, a manifest of sha256 hashes and a
``bootstrap.sh`` that verifies those hashes before it installs or runs
anything.

The prompt registry really is in there (ARENA_CONTRACT 11.5 D17): the worker
resolves ``/opt/arena/prompt_registry/<prompt_id>.txt`` and fails closed
without it. Until the second integration pass this docstring claimed a registry
the builder did not pack -- every bootstrap pod would have reached CRASHED.

The build is **deterministic**: no timestamps, fixed tar member metadata, gzip
mtime 0. That matters because the bundle hash becomes
``runtime_image_digest = "bootstrap:<runtime_bundle_sha256>"``, which is an
input to every ``inference_job_id``. A bundle whose hash moved on a rebuild
would silently invalidate work that has already been paid for.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import tarfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from arena.constants import CAMPAIGN_ID, MODEL_KEYS, NAMESPACE_ROOT
from arena.worker.util import atomic_write_bytes, atomic_write_json, sha256_label, utcnow

BUNDLE_MANIFEST_NAME: Final = "bundle-manifest.json"
BOOTSTRAP_NAME: Final = "bootstrap.sh"
RUNTIME_JSON_NAME: Final = "runtime.json"
BUNDLE_SCHEMA: Final = "tavonel.arena.bundle_manifest.v1"

EXCLUDED_DIR_NAMES: Final = frozenset(
    {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".git", "tests"}
)
EXCLUDED_SUFFIXES: Final = (".pyc", ".pyo", ".tmp", ".sqlite", ".sqlite-wal", ".sqlite-shm")

# ARENA_CONTRACT section 11.3(2): the bundle carries the parts of the ``arena``
# package the on-pod worker actually imports and nothing else from the repo.
# ``arena/core`` is deliberately absent: the worker imports only
# ``arena.constants`` and ``arena.worker.*`` (checked by
# tests/worker/test_bundle.py::test_bundle_has_no_third_party_dependency), and
# ``arena.core`` would drag pydantic/jsonschema onto a pod that has neither.
ARENA_BUNDLED_FILES: Final = ("arena/__init__.py", "arena/constants.py")
# ``prompt_registry`` joined the list in the second integration pass
# (ARENA_CONTRACT 11.5 D17): the worker resolves
# /opt/arena/prompt_registry/<prompt_id>.txt and fails closed without it, so a
# bootstrap pod that did not carry the registry could never reach READY.
ARENA_BUNDLED_DIRS: Final = ("arena/worker", "prompt_registry")

BUNDLE_ROOT_PATH: Final = "/opt/arena"
BUNDLE_TARBALL_PATH: Final = "/tmp/arena-bundle.tar.gz"  # noqa: S108 - pod-side path, not ours
PROMPT_REGISTRY_DIR_NAME: Final = "prompt_registry"
INSTALLED_ENV_BASENAME: Final = "bootstrap-installed.env"
INSTALLED_ENV_PATH: Final = f"{BUNDLE_ROOT_PATH}/{INSTALLED_ENV_BASENAME}"
FATAL_FILE_BASENAME: Final = "FATAL"
# Best-effort fallback location for the root-selection FATAL marker itself: this
# fires only when none of /opt/arena, $HOME/arena or /tmp/arena were writable, so
# the arena root the FATAL mechanism would normally live under does not exist.
NO_WRITABLE_ROOT_FATAL_PATH: Final = "/tmp/arena-bootstrap-fatal"  # noqa: S108
SHA256_HEX_RE: Final = re.compile(r"[0-9a-f]{64}")

# ARENA_CONTRACT 11.3(1) as amended by 11.5 D18, D29 and D54. One line, run under
# dockerEntrypoint ["/bin/bash", "-c"] on RunPod REST v1 -- not a login shell,
# so nothing here may assume a sourced profile or an image PATH that /etc/profile
# would have set.
#
# D18: some official base images (nvidia/cuda for unlimited_ocr) ship neither
# curl nor python3. The command probes curl, falls back to wget, and only then
# apt-get installs curl + ca-certificates, all *before* the sha256sum check --
# the pinned hash still gates extraction, so a tampered or stale bundle never
# starts. What it had to install is written to bootstrap-installed.env, which
# the template folds into the bootstrap receipt.
#
# D66: hpd_parsing's official image (USER hpd) ships neither curl nor wget, and
# the apt-get route above cannot run as non-root ("/var/lib/apt/lists/partial is
# missing - Permission denied"; pods lht6n046kt7pio and lxuzn8dlhf9a5t restart-
# looped on "curl: command not found"). Python is the one fetcher every image
# has -- the worker needs it moments later anyway -- so it is tried before
# apt-get, and apt-get is left for images that truly have nothing else.
#
# D54: hpd_parsing and paddleocr_vl_1_6's official base images declare a non-root
# USER (hpd / paddleocr respectively, both with a writable $HOME but no write
# access to /opt), so a hard-coded `mkdir -p /opt/arena` restart-loops the pod
# forever ("mkdir: cannot create directory '/opt/arena': Permission denied",
# observed on real canaries jglzhcxtrph372 and cpl10cxsby0wum). ARENA_ROOT is
# chosen once here -- /opt/arena when writable, else $HOME/arena, else
# /tmp/arena -- exported so bootstrap.sh and everything it hands off to read the
# variable instead of the literal, and printed once so the driver log shows which
# root was used. No writable candidate is a fail-closed stop (D47 sticky
# FATAL-file + sleep-infinity pattern), not a crash the pod would just restart.
START_CMD_TEMPLATE: Final = (
    "set -euo pipefail; "
    "export DEBIAN_FRONTEND=noninteractive; "
    "ARENA_INSTALLED=; "
    "ARENA_ROOT=; "
    'if mkdir -p "/opt/arena" 2>/dev/null && [ -w "/opt/arena" ]; then '
    '  ARENA_ROOT="/opt/arena"; '
    'elif [ -n "${HOME:-}" ] && mkdir -p "${HOME}/arena" 2>/dev/null '
    '&& [ -w "${HOME}/arena" ]; then '
    '  ARENA_ROOT="${HOME}/arena"; '
    'elif mkdir -p "/tmp/arena" 2>/dev/null && [ -w "/tmp/arena" ]; then '
    '  ARENA_ROOT="/tmp/arena"; '
    "fi; "
    'if [ -z "$ARENA_ROOT" ]; then '
    '  echo "[arena] FATAL no writable arena root (tried /opt/arena, '
    "\\${HOME:-<unset>}/arena, /tmp/arena)\" >&2; "
    f'  {{ echo "reason=no writable arena root"; echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; }} '
    f"> {NO_WRITABLE_ROOT_FATAL_PATH} 2>/dev/null || true; "
    "  sleep infinity; "
    "fi; "
    "export ARENA_ROOT; "
    'echo "[arena] ARENA_ROOT=$ARENA_ROOT"; '
    "if command -v curl >/dev/null 2>&1; then ARENA_FETCH=curl; "
    "elif command -v wget >/dev/null 2>&1; then ARENA_FETCH=wget; "
    "elif command -v python3 >/dev/null 2>&1; then ARENA_FETCH=python3; "
    "elif command -v python >/dev/null 2>&1; then ARENA_FETCH=python; "
    "elif command -v apt-get >/dev/null 2>&1; then "
    'echo "[arena] no curl and no wget; installing curl"; '
    "apt-get update -qq && "
    "apt-get install -y --no-install-recommends curl ca-certificates; "
    "ARENA_FETCH=curl; ARENA_INSTALLED=curl,ca-certificates; "
    'else echo "[arena] image has no curl, no wget and no apt-get" >&2; exit 1; fi; '
    'echo "[arena] fetching the bundle with $ARENA_FETCH"; '
    'if [ "$ARENA_FETCH" = curl ]; then '
    'curl -fsSL --retry 5 --max-time 900 "$ARENA_BUNDLE_URL" '
    f"-o {BUNDLE_TARBALL_PATH}; "
    f'elif [ "$ARENA_FETCH" = wget ]; then wget -q --tries=5 --timeout=900 '
    f'-O {BUNDLE_TARBALL_PATH} "$ARENA_BUNDLE_URL"; '
    'else "$ARENA_FETCH" -c "import sys, urllib.request; '
    'urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" '
    f'"$ARENA_BUNDLE_URL" {BUNDLE_TARBALL_PATH}; fi; '
    f'echo "@@BUNDLE_SHA256@@  {BUNDLE_TARBALL_PATH}" | sha256sum -c -; '
    f'tar -xzf {BUNDLE_TARBALL_PATH} -C "$ARENA_ROOT"; '
    f'printf "%s\\n" "ARENA_INSTALLED=$ARENA_INSTALLED" > "$ARENA_ROOT/{INSTALLED_ENV_BASENAME}"; '
    'exec bash "$ARENA_ROOT/bootstrap.sh"'
)

BOOTSTRAP_TEMPLATE: Final = """#!/usr/bin/env bash
# TAVONEL model arena worker bootstrap.
# campaign: @@CAMPAIGN_ID@@
# model:    @@MODEL_KEY@@
#
# Runs from the extracted bundle root (/opt/arena in bootstrap mode; the start
# command of ARENA_CONTRACT 11.3(1) put it there and already verified the
# archive hash). It resolves an interpreter (D18), verifies every bundled file
# against bundle-manifest.json, points /opt/arena/runtime at this model's
# runtime directory so baked and bootstrap pods use identical paths, exports the
# prompt registry location (D17), then hands over to the runtime's own
# bootstrap.sh when there is one. It never downloads the bundle and never needs
# ARENA_BUNDLE_URL. It never upgrades a package it was not told about.
set -euo pipefail

BUNDLE_ROOT="${BUNDLE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
# D54: the start command already picked a writable ARENA_ROOT and exported it
# (falling back off /opt/arena for a non-root base image); when this script runs
# without that start command (a baked image's own ENTRYPOINT), there is no such
# export, so fall back to BUNDLE_ROOT -- the directory this script actually lives
# in, which is /opt/arena for every baked image.
export ARENA_ROOT="${ARENA_ROOT:-$BUNDLE_ROOT}"
# D67: the worker keeps its inputs/results/synthetic pages under ARENA_STATE_DIR
# (default /workspace/arena, the RunPod volume). A non-root image cannot create
# that (paddleocr_vl_1_6 pod zvfrug8rrsdsya and hpd_parsing pod 3lzp9czvko2ao3
# both reached a live model server and then died in WorkerCore.__init__ on
# PermissionError: /workspace). Probe it here, next to ARENA_ROOT, and fall back
# to a state dir under the arena root the start command already proved writable.
if [ -z "${ARENA_STATE_DIR:-}" ]; then
  if mkdir -p /workspace/arena 2>/dev/null && [ -w /workspace/arena ]; then
    ARENA_STATE_DIR="/workspace/arena"
  else
    ARENA_STATE_DIR="$ARENA_ROOT/state"
    mkdir -p "$ARENA_STATE_DIR"
    echo "[arena] /workspace/arena is not writable here; ARENA_STATE_DIR=$ARENA_STATE_DIR"
  fi
fi
export ARENA_STATE_DIR
MODEL_KEY="@@MODEL_KEY@@"
RECEIPT="${ARENA_BOOTSTRAP_RECEIPT:-$BUNDLE_ROOT/bootstrap-receipt.txt}"
INSTALLED_ENV="$BUNDLE_ROOT/@@INSTALLED_ENV_BASENAME@@"

# What the start command already had to install, if anything (D18).
ARENA_INSTALLED=""
if [ -f "$INSTALLED_ENV" ]; then
  # shellcheck disable=SC1090
  . "$INSTALLED_ENV"
fi

# ARENA_CONTRACT 11.5 D18: nvidia/cuda base images ship no python3. Resolve
# python3, then python, then install python3 where apt-get exists. Never guess:
# an image with no interpreter and no package manager stops here rather than
# failing later with a confusing traceback from a missing binary.
if [ -z "${PYTHON_BIN:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  elif command -v apt-get >/dev/null 2>&1; then
    echo "[arena] no python3 and no python in this image; installing python3"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y --no-install-recommends python3 ca-certificates
    PYTHON_BIN="$(command -v python3)"
    ARENA_INSTALLED="${ARENA_INSTALLED:+$ARENA_INSTALLED,}python3"
  else
    echo "[arena] image has no python3, no python and no apt-get" >&2
    exit 1
  fi
fi
export PYTHON_BIN
export ARENA_INSTALLED
printf '%s\\n' "ARENA_INSTALLED=$ARENA_INSTALLED" > "$INSTALLED_ENV"
echo "[arena] PYTHON_BIN=$PYTHON_BIN installed=${ARENA_INSTALLED:-none}"

echo "[arena] verifying bundle manifest under $BUNDLE_ROOT"
"$PYTHON_BIN" - "$BUNDLE_ROOT" <<'PYVERIFY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest = json.loads((root / "bundle-manifest.json").read_text(encoding="utf-8"))
problems = []
for entry in manifest["files"]:
    target = root / entry["path"]
    if not target.is_file():
        problems.append("missing " + entry["path"])
        continue
    digest = "sha256:" + hashlib.sha256(target.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        problems.append("hash mismatch " + entry["path"])
if problems:
    print("[arena] bundle verification FAILED", file=sys.stderr)
    for problem in problems:
        print("  " + problem, file=sys.stderr)
    raise SystemExit(1)
print("[arena] bundle verification OK (%d files)" % len(manifest["files"]))
PYVERIFY

# ARENA_CONTRACT 11.3(3): /opt/arena/runtime -> /opt/arena/runtimes/<model_key>.
RUNTIME_SOURCE="$BUNDLE_ROOT/runtimes/$MODEL_KEY"
if [ ! -d "$RUNTIME_SOURCE" ]; then
  echo "[arena] runtime directory missing: $RUNTIME_SOURCE" >&2
  exit 1
fi
ln -sfn "$RUNTIME_SOURCE" "$BUNDLE_ROOT/runtime"
export PYTHONPATH="$BUNDLE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export ARENA_RUNTIME_DIR="$BUNDLE_ROOT/runtime"
echo "[arena] ARENA_RUNTIME_DIR=$ARENA_RUNTIME_DIR -> $RUNTIME_SOURCE"

# ARENA_CONTRACT 11.5 D17: the worker reads prompt_registry/<prompt_id>.txt and
# refuses to start without it. The bundle carries the registry; a baked image
# copies it to the same path.
PROMPT_REGISTRY="$BUNDLE_ROOT/prompt_registry"
if [ ! -d "$PROMPT_REGISTRY" ]; then
  echo "[arena] prompt registry missing: $PROMPT_REGISTRY" >&2
  exit 1
fi
export ARENA_PROMPT_REGISTRY_DIR="$PROMPT_REGISTRY"
echo "[arena] ARENA_PROMPT_REGISTRY_DIR=$ARENA_PROMPT_REGISTRY_DIR"
# D70: the controller puts ARENA_PROMPT_FILE=/opt/arena/prompt_registry/<id>.txt
# in the pod env (arena/controller/prompts.py POD_PROMPT_DIR), which is right
# for every root image and wrong for a bundle that D54 relocated (hpd_parsing
# pod prjumbgggb0e33 warmed up under /home/hpd/arena and died on "prompt file
# not found"). The registry that actually travelled with this bundle is the
# one above; when the env path does not exist but the same file does exist
# there, point the worker at the file it was meant to read, and say so. A
# prompt that exists nowhere still fails closed in the worker (D17).
if [ -n "${ARENA_PROMPT_FILE:-}" ] && [ ! -f "$ARENA_PROMPT_FILE" ]; then
  RELOCATED_PROMPT="$PROMPT_REGISTRY/$(basename "$ARENA_PROMPT_FILE")"
  if [ -f "$RELOCATED_PROMPT" ]; then
    echo "[arena] ARENA_PROMPT_FILE $ARENA_PROMPT_FILE absent; using bundled $RELOCATED_PROMPT"
    export ARENA_PROMPT_FILE="$RELOCATED_PROMPT"
  fi
fi

RUNTIME_BOOTSTRAP="$ARENA_RUNTIME_DIR/bootstrap.sh"
if [ -f "$RUNTIME_BOOTSTRAP" ]; then
  echo "[arena] delegating install to runtimes/$MODEL_KEY/bootstrap.sh"
  # D54: this used to `exec` the runtime bootstrap.sh, so a deterministic
  # install-time failure (a missing system package, a checkpoint the pinned
  # framework does not recognise) exited the container and RunPod restarted it --
  # the whole apt/pip/download sequence re-running on the paid pod every time
  # (mineru_pipeline pod 59kv17utzyhs9h and mineru_vlm pod lr7qqjnnsgvriz each
  # restarted 7 times re-running apt-get update + a failing pip install because
  # git was absent). Run it instead, and on a non-zero exit make the failure
  # sticky with the same FATAL-file + sleep-infinity mechanism D47 already uses
  # in every runtime's entrypoint.sh, so the driver's log watch condemns the pod
  # once instead of restart-looping it.
  set +e
  bash "$RUNTIME_BOOTSTRAP"
  RUNTIME_BOOTSTRAP_STATUS=$?
  set -e
  if [ "$RUNTIME_BOOTSTRAP_STATUS" -ne 0 ]; then
    BOOTSTRAP_FATAL_FILE="${ARENA_FATAL_FILE:-$ARENA_ROOT/FATAL}"
    mkdir -p "$(dirname "$BOOTSTRAP_FATAL_FILE")" 2>/dev/null || true
    {
      echo "model_key=$MODEL_KEY"
      echo "reason=bootstrap.sh exited $RUNTIME_BOOTSTRAP_STATUS"
      echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    } > "$BOOTSTRAP_FATAL_FILE" 2>/dev/null || true
    echo "[arena] FATAL runtimes/$MODEL_KEY/bootstrap.sh exited $RUNTIME_BOOTSTRAP_STATUS" >&2
    sleep infinity
  fi
  exit "$RUNTIME_BOOTSTRAP_STATUS"
fi

echo "[arena] runtimes/$MODEL_KEY/bootstrap.sh absent - installing nothing"
mkdir -p "$(dirname "$RECEIPT")"
{
  echo "campaign_id=@@CAMPAIGN_ID@@"
  echo "model_key=$MODEL_KEY"
  echo "bundle_root=$BUNDLE_ROOT"
  echo "runtime_dir=$ARENA_RUNTIME_DIR"
  echo "prompt_registry_dir=$ARENA_PROMPT_REGISTRY_DIR"
  echo "recorded_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "python_bin=$PYTHON_BIN"
  echo "installed_by_bootstrap=${ARENA_INSTALLED:-none}"
  echo "python=$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
  echo "--- pip freeze (sorted) ---"
  "$PYTHON_BIN" -m pip freeze --disable-pip-version-check | LC_ALL=C sort
} > "$RECEIPT"
echo "[arena] bootstrap receipt written to $RECEIPT"

exec "$PYTHON_BIN" -m arena.worker.server
"""


class BundleError(RuntimeError):
    """The bundle cannot be built or does not verify."""


@dataclass(frozen=True, slots=True)
class BundleVerification:
    ok: bool
    file_count: int
    problems: tuple[str, ...]


def _require_model_key(model_key: str) -> str:
    if model_key not in MODEL_KEYS:
        raise BundleError(f"unknown model_key {model_key!r}; expected one of {list(MODEL_KEYS)}")
    return model_key


def normalise_bundle_sha256(bundle_sha256: str) -> str:
    """Return the bare 64-hex digest, accepting either ``sha256:<hex>`` or ``<hex>``.

    Fail closed: a digest that is not exactly 64 lowercase hex characters would
    produce a start command whose ``sha256sum -c -`` line can never match, and
    the pod would burn GPU minutes discovering that.
    """
    if not isinstance(bundle_sha256, str):  # pragma: no cover - typing guard
        raise BundleError("bundle_sha256 must be a string")
    candidate = bundle_sha256.strip()
    if candidate.startswith("sha256:"):
        candidate = candidate[len("sha256:") :]
    if not SHA256_HEX_RE.fullmatch(candidate):
        raise BundleError(
            "bundle_sha256 must be 64 lowercase hex characters "
            f"(optionally prefixed 'sha256:'), got {bundle_sha256!r}"
        )
    return candidate


def render_start_cmd(model_key: str, bundle_sha256: str) -> str:
    """The RunPod REST v1 ``dockerStartCmd`` for a bootstrap-mode pod.

    ARENA_CONTRACT 11.3(1) as amended by 11.5 D18 and D29: one line, run under
    ``dockerEntrypoint: ["/bin/bash", "-c"]`` -- no login shell, so nothing in
    it may rely on a sourced profile. ``ARENA_BUNDLE_URL`` is a presigned GET
    the controller puts in the pod environment; the bundle hash is pinned into
    the command itself, so a tampered or stale bundle stops the pod before any
    model code runs.
    """
    _require_model_key(model_key)
    return START_CMD_TEMPLATE.replace("@@BUNDLE_SHA256@@", normalise_bundle_sha256(bundle_sha256))


def render_bootstrap(model_key: str) -> str:
    """``/opt/arena/bootstrap.sh`` for one model (ARENA_CONTRACT 11.3(3), 11.5 D17/D18)."""
    _require_model_key(model_key)
    return (
        BOOTSTRAP_TEMPLATE.replace("@@MODEL_KEY@@", model_key)
        .replace("@@CAMPAIGN_ID@@", CAMPAIGN_ID)
        .replace("@@INSTALLED_ENV_BASENAME@@", INSTALLED_ENV_BASENAME)
    )


def _include(path: Path) -> bool:
    if path.name.endswith(EXCLUDED_SUFFIXES):
        return False
    return not any(part in EXCLUDED_DIR_NAMES for part in path.parts)


def _collect(root: Path, arc_prefix: str) -> list[tuple[str, bytes]]:
    if not root.is_dir():
        return []
    members: list[tuple[str, bytes]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if not _include(relative):
            continue
        arcname = f"{arc_prefix}/{relative.as_posix()}"
        members.append((arcname, path.read_bytes()))
    return members


def _make_tar_gz(members: Sequence[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            info.type = tarfile.REGTYPE
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0)


def _require_prompt_file(model_key: str, members: Sequence[tuple[str, bytes]]) -> str:
    """Fail the build when the model's own prompt file is not in the archive (D17).

    The pod-side failure is worse than this one: the worker resolves
    ``prompt_registry/<prompt_id>.txt``, fails closed, and the pod bills a GPU
    while it sits in CRASHED. Catching it at build time costs nothing.
    """
    runtime_name = f"runtimes/{model_key}/{RUNTIME_JSON_NAME}"
    payload = next((data for name, data in members if name == runtime_name), None)
    if payload is None:
        raise BundleError(f"bundle would be incomplete: {runtime_name} not found")
    try:
        descriptor = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleError(f"{runtime_name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(descriptor, dict) or not isinstance(descriptor.get("prompt_id"), str):
        raise BundleError(f"{runtime_name} declares no string prompt_id (ARENA_CONTRACT 11.5 D16)")
    prompt_id = str(descriptor["prompt_id"])
    expected = f"{PROMPT_REGISTRY_DIR_NAME}/{prompt_id}.txt"
    if not any(name == expected for name, _ in members):
        raise BundleError(
            f"bundle would be incomplete: {expected} is missing, so the worker could never "
            f"resolve prompt_id {prompt_id!r} (ARENA_CONTRACT 11.5 D17)"
        )
    return prompt_id


def build_bundle(
    model_key: str, out_path: Path, *, namespace_root: Path = NAMESPACE_ROOT
) -> str:
    """Build the bundle and return its ``sha256:<hex>`` (the runtime bundle hash)."""
    _require_model_key(model_key)

    arena_root = namespace_root / "arena"
    if not arena_root.is_dir():
        raise BundleError(f"arena package not found under {namespace_root}")

    # ARENA_CONTRACT 11.3(2) with 11.5 D17: bootstrap.sh, bundle-manifest.json,
    # the arena package parts the worker imports, the prompt registry, and this
    # model's runtime directory. Nothing else from the repo.
    members: list[tuple[str, bytes]] = []
    for relative in ARENA_BUNDLED_FILES:
        source = namespace_root / relative
        if not source.is_file():
            raise BundleError(f"bundle would be incomplete: {relative} not found")
        members.append((relative, source.read_bytes()))
    for relative in ARENA_BUNDLED_DIRS:
        collected = _collect(namespace_root / relative, relative)
        if not collected:
            raise BundleError(f"bundle would be incomplete: {relative}/ is empty or missing")
        members.extend(collected)

    runtime_members = _collect(namespace_root / "runtimes" / model_key, f"runtimes/{model_key}")
    if not runtime_members:
        raise BundleError(
            f"runtimes/{model_key}/ holds no bundleable file under {namespace_root}"
        )
    members.extend(runtime_members)
    members.append((BOOTSTRAP_NAME, render_bootstrap(model_key).encode("utf-8")))
    members.sort(key=lambda member: member[0])

    if not any(name == "arena/worker/server.py" for name, _ in members):
        raise BundleError("bundle would not contain arena/worker/server.py")
    _require_prompt_file(model_key, members)

    manifest: dict[str, Any] = {
        "schema": BUNDLE_SCHEMA,
        "campaign_id": CAMPAIGN_ID,
        "model_key": model_key,
        "deterministic": True,
        "file_count": len(members),
        "files": [
            {"path": name, "sha256": sha256_label(data), "size": len(data)}
            for name, data in members
        ],
    }
    manifest_bytes = (
        json.dumps(manifest, sort_keys=True, ensure_ascii=True, indent=2).encode("utf-8") + b"\n"
    )
    members.append((BUNDLE_MANIFEST_NAME, manifest_bytes))
    members.sort(key=lambda member: member[0])

    archive = _make_tar_gz(members)
    bundle_sha = sha256_label(archive)
    atomic_write_bytes(out_path, archive)
    atomic_write_json(
        out_path.parent / f"{out_path.name}.manifest.json",
        {
            "schema": "tavonel.arena.bundle_receipt.v1",
            "campaign_id": CAMPAIGN_ID,
            "model_key": model_key,
            "bundle_path": str(out_path),
            "bundle_bytes": len(archive),
            "runtime_bundle_sha256": bundle_sha,
            "runtime_image_digest": f"bootstrap:{bundle_sha}",
            "manifest_sha256": sha256_label(manifest_bytes),
            "file_count": manifest["file_count"],
            "built_at": utcnow(),
        },
    )
    return bundle_sha


def read_bundle(tar_path: Path) -> dict[str, bytes]:
    """Read every regular member of the bundle. Rejects unsafe member names."""
    contents: dict[str, bytes] = {}
    with tarfile.open(tar_path, mode="r:gz") as tar:
        for info in tar.getmembers():
            if not info.isfile():
                raise BundleError(f"bundle contains a non-regular member: {info.name}")
            name = info.name
            if name.startswith(("/", "\\")) or ".." in Path(name).parts:
                raise BundleError(f"unsafe member path in bundle: {name}")
            handle = tar.extractfile(info)
            if handle is None:  # pragma: no cover - isfile() already guarantees this
                raise BundleError(f"cannot read bundle member: {name}")
            contents[name] = handle.read()
    return contents


def read_bundle_manifest(tar_path: Path) -> dict[str, Any]:
    contents = read_bundle(tar_path)
    if BUNDLE_MANIFEST_NAME not in contents:
        raise BundleError(f"{tar_path} has no {BUNDLE_MANIFEST_NAME}")
    manifest = json.loads(contents[BUNDLE_MANIFEST_NAME].decode("utf-8"))
    if not isinstance(manifest, dict):
        raise BundleError(f"{BUNDLE_MANIFEST_NAME} is not a JSON object")
    return manifest


def verify_bundle(tar_path: Path) -> BundleVerification:
    """Check every manifest entry against the bytes actually in the archive."""
    contents = read_bundle(tar_path)
    manifest = read_bundle_manifest(tar_path)
    entries = manifest.get("files")
    if not isinstance(entries, list):
        return BundleVerification(ok=False, file_count=0, problems=("manifest has no file list",))

    problems: list[str] = []
    listed: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            problems.append(f"malformed manifest entry: {entry!r}")
            continue
        name = str(entry.get("path"))
        listed.add(name)
        data = contents.get(name)
        if data is None:
            problems.append(f"missing from archive: {name}")
            continue
        digest = sha256_label(data)
        if digest != entry.get("sha256"):
            problems.append(f"hash mismatch: {name}")
        elif entry.get("size") != len(data):
            problems.append(f"size mismatch: {name}")

    for name in sorted(contents):
        if name != BUNDLE_MANIFEST_NAME and name not in listed:
            problems.append(f"present in archive but absent from the manifest: {name}")

    return BundleVerification(
        ok=not problems, file_count=len(listed), problems=tuple(problems)
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.worker.bundle",
        description="Build the bootstrap-mode worker bundle for one model.",
    )
    parser.add_argument("--model", required=True, help="model_key from arena.constants.MODEL_KEYS")
    parser.add_argument("--out", required=True, type=Path, help="output .tar.gz path")
    parser.add_argument(
        "--namespace-root",
        type=Path,
        default=NAMESPACE_ROOT,
        help="campaign namespace root (default: this checkout)",
    )
    parser.add_argument(
        "--verify", action="store_true", help="re-read the archive and verify every hash"
    )
    args = parser.parse_args(argv)

    bundle_sha = build_bundle(args.model, args.out, namespace_root=args.namespace_root)
    report: dict[str, Any] = {
        "model_key": args.model,
        "bundle_path": str(args.out),
        "runtime_bundle_sha256": bundle_sha,
        "runtime_image_digest": f"bootstrap:{bundle_sha}",
    }
    if args.verify:
        verification = verify_bundle(args.out)
        report["verified"] = verification.ok
        report["verified_file_count"] = verification.file_count
        report["problems"] = list(verification.problems)
        if not verification.ok:
            print(json.dumps(report, indent=2, sort_keys=True))
            return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())


__all__ = [
    "ARENA_BUNDLED_DIRS",
    "ARENA_BUNDLED_FILES",
    "BOOTSTRAP_NAME",
    "BUNDLE_MANIFEST_NAME",
    "FATAL_FILE_BASENAME",
    "INSTALLED_ENV_BASENAME",
    "INSTALLED_ENV_PATH",
    "NO_WRITABLE_ROOT_FATAL_PATH",
    "PROMPT_REGISTRY_DIR_NAME",
    "BundleError",
    "BundleVerification",
    "build_bundle",
    "main",
    "normalise_bundle_sha256",
    "read_bundle",
    "read_bundle_manifest",
    "render_bootstrap",
    "render_start_cmd",
    "verify_bundle",
]
