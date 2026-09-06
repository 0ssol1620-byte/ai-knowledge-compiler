"""Bootstrap-mode start command, bootstrap template and bundle composition.

ARENA_CONTRACT section 11.3. These tests are the only thing between a typo in
a one-line ``dockerStartCmd`` and a pod that bills for a GPU while it fails to
find its own runtime, so they check the exact text, not its intent.
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from arena.constants import CAMPAIGN_ID, MODEL_KEYS, NAMESPACE_ROOT, REPO_ROOT
from arena.worker.bundle import (
    ARENA_BUNDLED_DIRS,
    ARENA_BUNDLED_FILES,
    BOOTSTRAP_NAME,
    BUNDLE_MANIFEST_NAME,
    BundleError,
    build_bundle,
    normalise_bundle_sha256,
    read_bundle,
    render_bootstrap,
    render_start_cmd,
)

MODEL_KEY = "paddleocr_vl_1_6"
SHA = "b" * 63 + "0"

# ARENA_CONTRACT 11.3(1) as amended by 11.5 D18 (curl -> wget -> apt-get, and
# only then the fetch), D29 (dockerEntrypoint ["/bin/bash", "-c"]: no login
# shell) and D54 (a non-root base image's USER cannot write /opt/arena, so the
# root is chosen at runtime: /opt/arena when writable, else $HOME/arena, else
# /tmp/arena, with a fail-closed stop when none of the three is). Frozen as
# literal text on purpose -- this one string is all that stands between a typo
# and a pod that bills for a GPU while it fails to find its own runtime.
EXPECTED_START_CMD = (
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
    '  { echo "reason=no writable arena root"; echo "at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"; } '
    "> /tmp/arena-bootstrap-fatal 2>/dev/null || true; "
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
    "apt-get update -qq && apt-get install -y --no-install-recommends curl ca-certificates; "
    "ARENA_FETCH=curl; ARENA_INSTALLED=curl,ca-certificates; "
    'else echo "[arena] image has no curl, no wget and no apt-get" >&2; exit 1; fi; '
    'echo "[arena] fetching the bundle with $ARENA_FETCH"; '
    'if [ "$ARENA_FETCH" = curl ]; then '
    'curl -fsSL --retry 5 --max-time 900 "$ARENA_BUNDLE_URL" -o /tmp/arena-bundle.tar.gz; '
    'elif [ "$ARENA_FETCH" = wget ]; then wget -q --tries=5 --timeout=900 '
    '-O /tmp/arena-bundle.tar.gz "$ARENA_BUNDLE_URL"; '
    'else "$ARENA_FETCH" -c "import sys, urllib.request; '
    'urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" '
    '"$ARENA_BUNDLE_URL" /tmp/arena-bundle.tar.gz; fi; '
    f'echo "{SHA}  /tmp/arena-bundle.tar.gz" | sha256sum -c -; '
    'tar -xzf /tmp/arena-bundle.tar.gz -C "$ARENA_ROOT"; '
    'printf "%s\\n" "ARENA_INSTALLED=$ARENA_INSTALLED" > "$ARENA_ROOT/bootstrap-installed.env"; '
    'exec bash "$ARENA_ROOT/bootstrap.sh"'
)


def _bash() -> str | None:
    """Absolute path to a usable bash (ARENA_CONTRACT 11.5 D30).

    ``shutil.which("bash")`` on Windows finds the WSL stub first, and that stub
    fails with an error that has nothing to do with the script under test. The
    Git-for-Windows bash is checked explicitly.
    """
    candidates = ["C:/Program Files/Git/usr/bin/bash.exe", "C:/Program Files/Git/bin/bash.exe"]
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("bash")
    if found is None:
        return None
    probe = subprocess.run(
        [found, "-c", "exit 0"], capture_output=True, text=True, check=False
    )
    return found if probe.returncode == 0 else None


# -- 11.3(1) start command ------------------------------------------------


def test_start_cmd_is_exactly_the_contract_line() -> None:
    assert render_start_cmd(MODEL_KEY, SHA) == EXPECTED_START_CMD
    assert "\n" not in render_start_cmd(MODEL_KEY, SHA)


def test_start_cmd_parses_as_bash(tmp_path: Path) -> None:
    """D29: it runs under ``/bin/bash -c``, so it must parse as one bash command."""
    bash = _bash()
    if bash is None:
        pytest.xfail("no usable bash on this machine (D30)")
    script = tmp_path / "start.sh"
    script.write_text(render_start_cmd(MODEL_KEY, SHA), encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [bash, "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


def test_start_cmd_probes_curl_then_wget_then_apt_before_the_hash_check() -> None:
    """D18: nvidia/cuda ships neither curl nor python3, and the hash still gates extraction."""
    command = render_start_cmd(MODEL_KEY, SHA)
    order = [
        "command -v curl",
        "command -v wget",
        "command -v python3",
        "command -v apt-get",
        "apt-get install -y --no-install-recommends curl ca-certificates",
        "sha256sum -c -",
        "tar -xzf",
        'exec bash "$ARENA_ROOT/bootstrap.sh"',
    ]
    positions = [command.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"


def test_start_cmd_fetches_with_python_before_it_would_need_apt_get() -> None:
    """D66: hpd_parsing's image (USER hpd) has neither curl nor wget, and apt-get
    cannot run as non-root; pods lht6n046kt7pio and lxuzn8dlhf9a5t restart-looped
    on "curl: command not found". Python is the fetcher every image has."""
    command = render_start_cmd(MODEL_KEY, SHA)
    order = [
        "command -v wget",
        "command -v python3 >/dev/null 2>&1; then ARENA_FETCH=python3",
        "command -v python >/dev/null 2>&1; then ARENA_FETCH=python",
        "command -v apt-get",
        'else "$ARENA_FETCH" -c "import sys, urllib.request; '
        'urllib.request.urlretrieve(sys.argv[1], sys.argv[2])" '
        '"$ARENA_BUNDLE_URL" /tmp/arena-bundle.tar.gz; fi; ',
        "sha256sum -c -",
    ]
    positions = [command.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"


def test_start_cmd_picks_a_writable_arena_root_before_touching_curl_or_wget() -> None:
    """D54: the root has to be chosen before anything gets extracted into it."""
    command = render_start_cmd(MODEL_KEY, SHA)
    order = [
        'if mkdir -p "/opt/arena" 2>/dev/null && [ -w "/opt/arena" ]; then',
        'elif [ -n "${HOME:-}" ] && mkdir -p "${HOME}/arena" 2>/dev/null',
        'elif mkdir -p "/tmp/arena" 2>/dev/null && [ -w "/tmp/arena" ]; then',
        'if [ -z "$ARENA_ROOT" ]; then',
        "sleep infinity",
        "export ARENA_ROOT",
        "command -v curl",
    ]
    positions = [command.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"


def test_start_cmd_still_prefers_opt_arena_first() -> None:
    """The fallback exists for a non-root image; a normal root image is untouched."""
    command = render_start_cmd(MODEL_KEY, SHA)
    assert command.index('"/opt/arena"') < command.index('"${HOME}/arena"')
    assert command.index('"${HOME}/arena"') < command.index('"/tmp/arena"')


def test_start_cmd_falls_back_off_opt_arena_when_it_is_not_writable() -> None:
    """D54 evidence: hpd-parsing-vllm and paddleocr-vl declare a non-root USER
    with no write access to /opt (mkdir -p /opt/arena; permission denied on
    real canaries jglzhcxtrph372 and cpl10cxsby0wum). The generated command must
    actually contain the $HOME and /tmp fallback branches, not just prefer
    /opt/arena when it happens to be writable."""
    command = render_start_cmd(MODEL_KEY, SHA)
    assert '"${HOME}/arena"' in command
    assert '"/tmp/arena"' in command
    assert 'export ARENA_ROOT' in command
    assert 'echo "[arena] ARENA_ROOT=$ARENA_ROOT"' in command


def test_start_cmd_fails_closed_when_no_arena_root_is_writable() -> None:
    """D54/D47: no writable candidate is a sticky stop, not a silent crash-loop."""
    command = render_start_cmd(MODEL_KEY, SHA)
    assert '[arena] FATAL no writable arena root' in command
    assert "sleep infinity" in command
    # Fails closed before ever reaching the fetch/extract logic.
    assert command.index("sleep infinity") < command.index("command -v curl")


def test_start_cmd_records_what_it_installed() -> None:
    """D18: what the start command had to install reaches the bootstrap receipt."""
    command = render_start_cmd(MODEL_KEY, SHA)
    assert "ARENA_INSTALLED=curl,ca-certificates" in command
    assert '"$ARENA_ROOT/bootstrap-installed.env"' in command
    script = render_bootstrap(MODEL_KEY)
    assert 'INSTALLED_ENV="$BUNDLE_ROOT/bootstrap-installed.env"' in script
    assert '. "$INSTALLED_ENV"' in script
    assert "installed_by_bootstrap=${ARENA_INSTALLED:-none}" in script


def test_start_cmd_fails_closed_when_the_image_can_fetch_nothing() -> None:
    command = render_start_cmd(MODEL_KEY, SHA)
    assert 'echo "[arena] image has no curl, no wget and no apt-get" >&2; exit 1' in command


def test_start_cmd_assumes_no_login_shell() -> None:
    """D29: dockerEntrypoint is ["/bin/bash", "-c"] -- nothing sources a profile."""
    command = render_start_cmd(MODEL_KEY, SHA)
    assert "source " not in command
    assert "/etc/profile" not in command
    assert "~/." not in command


def test_start_cmd_accepts_either_digest_form_and_never_emits_the_prefix() -> None:
    prefixed = render_start_cmd(MODEL_KEY, f"sha256:{SHA}")
    assert prefixed == EXPECTED_START_CMD
    assert "sha256:" not in prefixed, "sha256sum -c - reads a bare hex digest"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "sha256:",
        "b" * 63,
        "b" * 65,
        "B" * 64,
        "sha256:" + "g" * 64,
        "sha256:sha256:" + "b" * 64,
        "b" * 64 + " extra",
    ],
)
def test_start_cmd_refuses_a_digest_that_could_never_match(bad: str) -> None:
    with pytest.raises(BundleError, match="bundle_sha256"):
        render_start_cmd(MODEL_KEY, bad)


def test_start_cmd_refuses_an_unknown_model_key() -> None:
    with pytest.raises(BundleError, match="unknown model_key"):
        render_start_cmd("not_a_model", SHA)


def test_normalise_is_idempotent_over_every_model_key() -> None:
    assert normalise_bundle_sha256(f"  sha256:{SHA}  ") == SHA
    for model_key in MODEL_KEYS:
        assert render_start_cmd(model_key, SHA) == EXPECTED_START_CMD


# -- 11.3(3) bootstrap template -------------------------------------------


def test_template_symlinks_exports_and_delegates() -> None:
    script = render_bootstrap(MODEL_KEY)
    assert 'RUNTIME_SOURCE="$BUNDLE_ROOT/runtimes/$MODEL_KEY"' in script
    assert 'ln -sfn "$RUNTIME_SOURCE" "$BUNDLE_ROOT/runtime"' in script
    assert 'export PYTHONPATH="$BUNDLE_ROOT${PYTHONPATH:+:$PYTHONPATH}"' in script
    assert 'export ARENA_RUNTIME_DIR="$BUNDLE_ROOT/runtime"' in script
    assert 'RUNTIME_BOOTSTRAP="$ARENA_RUNTIME_DIR/bootstrap.sh"' in script
    assert 'if [ -f "$RUNTIME_BOOTSTRAP" ]; then' in script
    assert 'bash "$RUNTIME_BOOTSTRAP"' in script
    assert script.rstrip().endswith('exec "$PYTHON_BIN" -m arena.worker.server')
    assert CAMPAIGN_ID in script
    assert MODEL_KEY in script


def test_template_exports_arena_root_falling_back_to_bundle_root() -> None:
    """D54: a baked image's own ENTRYPOINT runs this script with no ARENA_ROOT
    already exported by the start command, so it must default to BUNDLE_ROOT
    (the directory the script actually lives in, /opt/arena for a baked image)."""
    script = render_bootstrap(MODEL_KEY)
    assert 'export ARENA_ROOT="${ARENA_ROOT:-$BUNDLE_ROOT}"' in script


def test_template_makes_a_failed_runtime_bootstrap_sticky_instead_of_restarting() -> None:
    """D54: a deterministic runtimes/<model>/bootstrap.sh failure (a missing
    system package, an unrecognised checkpoint architecture) used to `exec` the
    runtime bootstrap, so a non-zero exit killed the container and RunPod
    restarted it, re-running the whole apt/pip/download sequence on the paid pod
    (real evidence: mineru_pipeline pod 59kv17utzyhs9h and mineru_vlm pod
    lr7qqjnnsgvriz each restarted 7 times over a `pip install` failing because
    git was absent). It must instead run under `set +e`, and on a non-zero exit
    write the same sticky FATAL file + sleep infinity mechanism D47 already uses
    in every runtime's entrypoint.sh, so the driver condemns the pod once."""
    script = render_bootstrap(MODEL_KEY)
    delegate_start = script.index('if [ -f "$RUNTIME_BOOTSTRAP" ]; then')
    delegate_block = script[delegate_start:]
    assert "set +e" in delegate_block
    assert 'bash "$RUNTIME_BOOTSTRAP"' in delegate_block
    assert "RUNTIME_BOOTSTRAP_STATUS=$?" in delegate_block
    assert "set -e" in delegate_block
    assert 'if [ "$RUNTIME_BOOTSTRAP_STATUS" -ne 0 ]; then' in delegate_block
    assert 'BOOTSTRAP_FATAL_FILE="${ARENA_FATAL_FILE:-$ARENA_ROOT/FATAL}"' in delegate_block
    assert '"reason=bootstrap.sh exited $RUNTIME_BOOTSTRAP_STATUS"' in delegate_block
    assert '[arena] FATAL runtimes/$MODEL_KEY/bootstrap.sh exited' in delegate_block
    assert "sleep infinity" in delegate_block
    # The explicit FATAL paths D47 already wired up (e.g. entrypoint.sh's own
    # fatal_and_hold) are untouched -- this is a second, independent mechanism
    # around the install step, not a replacement.
    assert delegate_block.index("set +e") < delegate_block.index('bash "$RUNTIME_BOOTSTRAP"')
    assert delegate_block.index("sleep infinity") < delegate_block.index(
        'echo "[arena] runtimes/$MODEL_KEY/bootstrap.sh absent'
    )


def test_template_does_not_require_the_bundle_url() -> None:
    """11.3(3): the start command already fetched and verified the archive."""
    script = render_bootstrap(MODEL_KEY)
    assert "$ARENA_BUNDLE_URL" not in script
    assert "${ARENA_BUNDLE_URL" not in script
    assert "curl" not in script


def test_template_fails_closed_on_a_missing_runtime_directory() -> None:
    script = render_bootstrap(MODEL_KEY)
    assert 'if [ ! -d "$RUNTIME_SOURCE" ]; then' in script
    assert "exit 1" in script


def test_template_resolves_python3_then_python_then_installs_it() -> None:
    """D18: nvidia/cuda base images ship no python3 at all."""
    script = render_bootstrap(MODEL_KEY)
    order = [
        'if [ -z "${PYTHON_BIN:-}" ]; then',
        "command -v python3",
        "command -v python >/dev/null",
        "command -v apt-get",
        "apt-get install -y --no-install-recommends python3 ca-certificates",
        'echo "[arena] image has no python3, no python and no apt-get" >&2',
        "verifying bundle manifest",
    ]
    positions = [script.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"


def test_template_exports_the_prompt_registry_and_fails_closed_without_it() -> None:
    """D17: the worker resolves prompt_registry/<prompt_id>.txt or refuses to start."""
    script = render_bootstrap(MODEL_KEY)
    assert 'PROMPT_REGISTRY="$BUNDLE_ROOT/prompt_registry"' in script
    assert 'if [ ! -d "$PROMPT_REGISTRY" ]; then' in script
    assert 'export ARENA_PROMPT_REGISTRY_DIR="$PROMPT_REGISTRY"' in script


@pytest.mark.parametrize("model_key", list(MODEL_KEYS))
def test_template_parses_as_bash(model_key: str, tmp_path: Path) -> None:
    bash = _bash()
    if bash is None:
        # D30: xfail, not skip -- a machine with no usable bash has not proven
        # the template parses, and a green skip would say it had.
        pytest.xfail("no usable bash on this machine (D30)")
    script = tmp_path / f"bootstrap-{model_key}.sh"
    script.write_text(render_bootstrap(model_key), encoding="utf-8", newline="\n")
    completed = subprocess.run(
        [bash, "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert completed.returncode == 0, completed.stderr


# -- 11.3(2) bundle composition -------------------------------------------


def test_bundle_holds_exactly_the_contract_members(tmp_path: Path) -> None:
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    names = set(read_bundle(out))

    assert BOOTSTRAP_NAME in names
    assert BUNDLE_MANIFEST_NAME in names
    for expected in ARENA_BUNDLED_FILES:
        assert expected in names
    assert "arena/worker/server.py" in names
    assert f"runtimes/{MODEL_KEY}/runtime.json" in names
    assert f"runtimes/{MODEL_KEY}/adapter.py" in names

    # ARENA_CONTRACT 11.5 D17: the prompt registry travels with the pod, and
    # this model's own prompt file is in it.
    descriptor = json.loads(
        (NAMESPACE_ROOT / "runtimes" / MODEL_KEY / "runtime.json").read_text(encoding="utf-8")
    )
    assert f"prompt_registry/{descriptor['prompt_id']}.txt" in names

    allowed_prefixes = (
        *(f"{d}/" for d in ARENA_BUNDLED_DIRS),
        f"runtimes/{MODEL_KEY}/",
    )
    for name in names:
        if name in {BOOTSTRAP_NAME, BUNDLE_MANIFEST_NAME} or name in ARENA_BUNDLED_FILES:
            continue
        assert name.startswith(allowed_prefixes), f"{name} is not in the 11.3(2) member list"

    # Nothing else from the repo: no controller, no provider, no other model's
    # runtime, no caches.
    assert not any(name.startswith("arena/controller/") for name in names)
    assert not any(name.startswith("arena/provider/") for name in names)
    other = [key for key in MODEL_KEYS if key != MODEL_KEY]
    assert not any(name.startswith(f"runtimes/{key}/") for key in other for name in names)
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)


def test_bundle_carries_every_file_of_the_runtime_directory(tmp_path: Path) -> None:
    """A temporary namespace: exactly what is on disk, minus caches and tests."""
    root = tmp_path / "ns"
    (root / "arena" / "worker").mkdir(parents=True)
    (root / "arena" / "__init__.py").write_text("", encoding="utf-8")
    (root / "arena" / "constants.py").write_text("X = 1\n", encoding="utf-8")
    (root / "arena" / "worker" / "server.py").write_text("Y = 2\n", encoding="utf-8")

    (root / "prompt_registry").mkdir(parents=True)
    (root / "prompt_registry" / "fake_prompt_v1.txt").write_text("prompt\n", encoding="utf-8")

    runtime = root / "runtimes" / MODEL_KEY
    (runtime / "__pycache__").mkdir(parents=True)
    (runtime / "tests").mkdir()
    for name in ("adapter.py", "canonical.py", "bootstrap.sh", "entrypoint.sh"):
        (runtime / name).write_text("payload\n", encoding="utf-8")
    (runtime / "runtime.json").write_text(
        json.dumps({"prompt_id": "fake_prompt_v1"}), encoding="utf-8"
    )
    (runtime / "fetch_weights.py").write_text("payload\n", encoding="utf-8")
    (runtime / "__pycache__" / "adapter.cpython-313.pyc").write_bytes(b"\x00")
    (runtime / "adapter.pyc").write_bytes(b"\x00")
    (runtime / "tests" / "test_adapter.py").write_text("assert True\n", encoding="utf-8")

    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out, namespace_root=root)
    names = set(read_bundle(out))

    assert names == {
        BOOTSTRAP_NAME,
        BUNDLE_MANIFEST_NAME,
        "arena/__init__.py",
        "arena/constants.py",
        "arena/worker/server.py",
        "prompt_registry/fake_prompt_v1.txt",
        f"runtimes/{MODEL_KEY}/adapter.py",
        f"runtimes/{MODEL_KEY}/canonical.py",
        f"runtimes/{MODEL_KEY}/runtime.json",
        f"runtimes/{MODEL_KEY}/bootstrap.sh",
        f"runtimes/{MODEL_KEY}/entrypoint.sh",
        f"runtimes/{MODEL_KEY}/fetch_weights.py",
    }


def _minimal_namespace(tmp_path: Path) -> Path:
    root = tmp_path / "ns"
    (root / "arena" / "worker").mkdir(parents=True)
    (root / "arena" / "__init__.py").write_text("", encoding="utf-8")
    (root / "arena" / "constants.py").write_text("X = 1\n", encoding="utf-8")
    (root / "arena" / "worker" / "server.py").write_text("Y = 2\n", encoding="utf-8")
    (root / "prompt_registry").mkdir(parents=True)
    (root / "prompt_registry" / "fake_prompt_v1.txt").write_text("prompt\n", encoding="utf-8")
    return root


def test_bundle_refuses_a_namespace_without_the_runtime(tmp_path: Path) -> None:
    root = _minimal_namespace(tmp_path)
    with pytest.raises(BundleError, match="holds no bundleable file"):
        build_bundle(MODEL_KEY, tmp_path / "bundle.tar.gz", namespace_root=root)


def test_bundle_refuses_a_namespace_without_the_prompt_registry(tmp_path: Path) -> None:
    """D17: a bootstrap pod without the registry could never reach READY."""
    root = _minimal_namespace(tmp_path)
    shutil.rmtree(root / "prompt_registry")
    runtime = root / "runtimes" / MODEL_KEY
    runtime.mkdir(parents=True)
    (runtime / "adapter.py").write_text("payload\n", encoding="utf-8")
    (runtime / "runtime.json").write_text(
        json.dumps({"prompt_id": "fake_prompt_v1"}), encoding="utf-8"
    )
    with pytest.raises(BundleError, match="prompt_registry/ is empty or missing"):
        build_bundle(MODEL_KEY, tmp_path / "bundle.tar.gz", namespace_root=root)


def test_bundle_refuses_a_registry_without_this_models_prompt(tmp_path: Path) -> None:
    root = _minimal_namespace(tmp_path)
    runtime = root / "runtimes" / MODEL_KEY
    runtime.mkdir(parents=True)
    (runtime / "adapter.py").write_text("payload\n", encoding="utf-8")
    (runtime / "runtime.json").write_text(
        json.dumps({"prompt_id": "a_prompt_nobody_registered"}), encoding="utf-8"
    )
    with pytest.raises(BundleError, match="a_prompt_nobody_registered"):
        build_bundle(MODEL_KEY, tmp_path / "bundle.tar.gz", namespace_root=root)


def test_bundle_refuses_a_runtime_json_without_a_prompt_id(tmp_path: Path) -> None:
    root = _minimal_namespace(tmp_path)
    runtime = root / "runtimes" / MODEL_KEY
    runtime.mkdir(parents=True)
    (runtime / "adapter.py").write_text("payload\n", encoding="utf-8")
    (runtime / "runtime.json").write_text(json.dumps({"model_key": MODEL_KEY}), encoding="utf-8")
    with pytest.raises(BundleError, match="no string prompt_id"):
        build_bundle(MODEL_KEY, tmp_path / "bundle.tar.gz", namespace_root=root)


@pytest.mark.parametrize("model_key", list(MODEL_KEYS))
def test_every_campaign_model_bundles_with_its_prompt(model_key: str, tmp_path: Path) -> None:
    """Every model in the namespace can actually be packed for a bootstrap pod (D17)."""
    if model_key == "opus5_subscription":
        pytest.skip("the Opus lane runs on a subscription surface, not a pod")
    if not (NAMESPACE_ROOT / "runtimes" / model_key).is_dir():
        pytest.skip(f"runtimes/{model_key}/ does not exist")
    out = tmp_path / f"{model_key}.tar.gz"
    build_bundle(model_key, out)
    names = set(read_bundle(out))
    descriptor = json.loads(
        (NAMESPACE_ROOT / "runtimes" / model_key / "runtime.json").read_text(encoding="utf-8")
    )
    assert f"prompt_registry/{descriptor['prompt_id']}.txt" in names


# -- contract section 4: the pod is stdlib + pillow ------------------------

STDLIB_PLUS_PILLOW = frozenset(sys.stdlib_module_names) | {"PIL", "arena"}


def test_bundled_arena_modules_import_nothing_but_stdlib_pillow_and_arena(
    tmp_path: Path,
) -> None:
    """Static scan of every ``arena/`` module the bundle actually ships."""
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    offenders: list[str] = []
    for name, data in sorted(read_bundle(out).items()):
        if not name.startswith("arena/") or not name.endswith(".py"):
            continue
        tree = ast.parse(data.decode("utf-8"), filename=name)
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                roots = [node.module.split(".")[0]]
            offenders += [f"{name}: {root}" for root in roots if root not in STDLIB_PLUS_PILLOW]
    assert offenders == [], f"the on-pod worker must be stdlib + pillow only: {offenders}"


def test_worker_server_imports_in_a_stdlib_only_interpreter(tmp_path: Path) -> None:
    """Extract the bundle and import the server with site-packages removed."""
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    extracted = tmp_path / "opt-arena"
    extracted.mkdir()
    with tarfile.open(out, mode="r:gz") as tar:
        tar.extractall(extracted, filter="data")

    probe = (
        "import sys, sysconfig, json\n"
        f"root = {str(extracted)!r}\n"
        f"repo = {str(REPO_ROOT)!r}\n"
        "base = [p for p in sys.path "
        "if 'site-packages' not in p.replace('\\\\', '/') and not p.startswith(repo)]\n"
        "sys.path = [root, *base]\n"
        "import arena.worker.server as server\n"
        "assert server.SEMANTIC_ERROR_CLASSES\n"
        "third_party = {'pydantic', 'jsonschema', 'httpx', 'boto3', 'fastapi', 'yaml'}\n"
        "print(json.dumps(sorted(third_party & set(sys.modules))))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == []


def test_the_new_d17_d19_d20_code_runs_in_a_stdlib_only_interpreter(tmp_path: Path) -> None:
    """The second-pass additions are stdlib too, exercised not just imported.

    Prompt resolution (D17/D34), the connection-refused retry (D19) and the pod
    age fuse (D20) all run on the pod, where there is no pydantic, no requests
    and no jsonschema.
    """
    out = tmp_path / "bundle.tar.gz"
    build_bundle(MODEL_KEY, out)
    extracted = tmp_path / "opt-arena"
    extracted.mkdir()
    with tarfile.open(out, mode="r:gz") as tar:
        tar.extractall(extracted, filter="data")

    descriptor = json.loads(
        (extracted / "runtimes" / MODEL_KEY / "runtime.json").read_text(encoding="utf-8")
    )
    probe = (
        "import sys, json\n"
        f"root = {str(extracted)!r}\n"
        f"repo = {str(REPO_ROOT)!r}\n"
        "base = [p for p in sys.path "
        "if 'site-packages' not in p.replace('\\\\', '/') and not p.startswith(repo)]\n"
        "sys.path = [root, *base]\n"
        "import pathlib\n"
        "from arena.worker.config import WorkerEnv, load_runtime_config, resolve_prompt\n"
        "from arena.worker import server\n"
        "env = WorkerEnv.from_env({\n"
        "    'ARENA_WORKER_TOKEN': 'probe',\n"
        f"    'ARENA_MODEL_KEY': {MODEL_KEY!r},\n"
        f"    'ARENA_MODEL_REVISION': {str(descriptor['model_revision'])!r},\n"
        "    'ARENA_RUNTIME_MODE': 'bootstrap',\n"
        "    'ARENA_IMAGE_DIGEST': 'bootstrap:sha256:' + 'a' * 64,\n"
        f"    'ARENA_RUNTIME_DIR': root + '/runtimes/{MODEL_KEY}',\n"
        "    'ARENA_PROMPT_REGISTRY_DIR': root + '/prompt_registry',\n"
        "    'ARENA_STATE_DIR': root + '/state',\n"
        "    'ARENA_MAX_POD_AGE_HOURS': '2',\n"
        "})\n"
        "runtime = load_runtime_config(env)\n"
        "prompt = resolve_prompt(env, runtime)\n"
        "assert prompt.sha256.startswith('sha256:'), prompt\n"
        "calls = []\n"
        "def flaky():\n"
        "    calls.append(1)\n"
        "    if len(calls) < 2:\n"
        "        raise ConnectionRefusedError(111, 'not yet')\n"
        "    return 'up'\n"
        "assert server.retry_while_connection_refused(\n"
        "    flaky, what='probe', budget_seconds=5.0, poll_seconds=0.01) == 'up'\n"
        "exits = []\n"
        "server._exit_process = exits.append\n"
        "class Core:\n"
        "    active_jobs = 0\n"
        "    def drain(self): return {'stage': 'DRAINING'}\n"
        "    def stop(self): pass\n"
        "server.PodAgeWatchdog(Core(), max_age_seconds=1.0, drain_grace_seconds=0.0).expire()\n"
        "assert exits == [server.MAX_POD_AGE_EXIT_CODE], exits\n"
        "third_party = {'pydantic', 'jsonschema', 'httpx', 'boto3', 'fastapi', 'yaml',"
        " 'requests'}\n"
        "print(json.dumps(sorted(third_party & set(sys.modules))))\n"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(tmp_path),
    )
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout.strip()) == []


def test_bootstrap_routes_the_worker_state_dir_through_a_writable_root() -> None:
    """D67: /workspace/arena is root-owned on the RunPod volume; a non-root image
    (paddleocr_vl_1_6 pod zvfrug8rrsdsya, hpd_parsing pod 3lzp9czvko2ao3) reached
    a live model server and then died creating it. The probe runs before the
    model key is even set, and the export reaches the worker either way."""
    script = render_bootstrap(MODEL_KEY)
    order = [
        'export ARENA_ROOT="${ARENA_ROOT:-$BUNDLE_ROOT}"',
        'if [ -z "${ARENA_STATE_DIR:-}" ]; then',
        "mkdir -p /workspace/arena 2>/dev/null && [ -w /workspace/arena ]",
        'ARENA_STATE_DIR="$ARENA_ROOT/state"',
        "export ARENA_STATE_DIR",
        'MODEL_KEY="',
    ]
    positions = [script.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"


def test_bootstrap_re_roots_a_relocated_prompt_file_to_the_bundled_registry() -> None:
    """D70: the pod env pins ARENA_PROMPT_FILE under /opt/arena; a relocated bundle
    (D54) keeps the registry elsewhere. The re-root happens after the registry is
    exported and before the runtime bootstrap is delegated to."""
    script = render_bootstrap(MODEL_KEY)
    order = [
        'export ARENA_PROMPT_REGISTRY_DIR="$PROMPT_REGISTRY"',
        'if [ -n "${ARENA_PROMPT_FILE:-}" ] && [ ! -f "$ARENA_PROMPT_FILE" ]; then',
        'RELOCATED_PROMPT="$PROMPT_REGISTRY/$(basename "$ARENA_PROMPT_FILE")"',
        'export ARENA_PROMPT_FILE="$RELOCATED_PROMPT"',
        'RUNTIME_BOOTSTRAP="$ARENA_RUNTIME_DIR/bootstrap.sh"',
    ]
    positions = [script.index(fragment) for fragment in order]
    assert positions == sorted(positions), f"out of order: {order}"
