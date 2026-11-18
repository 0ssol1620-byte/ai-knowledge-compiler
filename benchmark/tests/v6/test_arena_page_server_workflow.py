"""WO-D10-0K: the arena page-server image workflow, checked without running it."""

from __future__ import annotations

import os
import posixpath
import re
import shutil
import subprocess
import sys
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
    assert set(checkout[0]["with"]) == {
        "persist-credentials",
        "sparse-checkout",
        "sparse-checkout-cone-mode",
    }
    assert checkout[0]["with"]["persist-credentials"] is False
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


# WO-D10-0K3: C1's listing step, on a log shaped like step #13 of the failed job of run
# 44139687530 (its marker lines; the package lines are synthetic).

_C1_DOCKERFILE = ROOT / "infra/runpod/v6/images/paddleocr-vl-akc/Dockerfile"
_C1_PROGRESS = [
    "#13 1.368 Successfully installed uv-0.13.4",
    "#13 1.509 Using CPython 3.12.3 interpreter at: /usr/bin/python3",
    "#13 1.509 Creating virtual environment at: .venv",
    "#13 2.458 Installed 100 packages in 440ms",
    "#13 2.458  + example-a==1.0.0",
    "#13 227.6 Installed 22 packages in 24.85s",
    "#13 230.9 Installed 57 packages in 1.14s",
    "#13 231.6 Checked 178 packages in 48ms",
    "#13 232.9 All installed packages are compatible",
    "#13 233.0 example-a==1.0.0",
]


def _c1_listing_run() -> str:
    """The RUN that holds C1's listing marker, joined the way BuildKit prints its header."""
    marker = _entry("c1")["listing_marker"]
    joined = re.sub(r"\\\r?\n", "", _C1_DOCKERFILE.read_text(encoding="utf-8"))
    (run,) = [line for line in joined.splitlines() if line.startswith("RUN ") and marker in line]
    return run


def _c1_commands() -> list[str]:
    return [command.strip() for command in _c1_listing_run().removeprefix("RUN ").split("&&")]


def test_c1_listing_runs_only_uv_after_the_environment_is_made_by_uv() -> None:
    # A uv-created environment has no pip, so `python -m pip …` through it fails (the cause of
    # the failed job). The class: any listing command that needs a module the venv lacks.
    commands = _c1_commands()
    after = commands[[command.split()[:2] for command in commands].index(["uv", "sync"]) + 1 :]
    assert after
    for command in after:
        assert command.startswith(("uv pip ", "echo ")), command
    assert "uv pip freeze --python /app/.venv/bin/python" in after


def test_c1_unverified_listing_command_is_last_and_named_by_the_line_before_it() -> None:
    *_, marker, last = _c1_commands()
    assert last == "uv pip list --python /app/.venv/bin/python --format json"
    assert marker.startswith("echo ") and "uv pip list --format json" in marker
    assert "UNVERIFIED" in marker


def test_c1_listing_step_keeps_the_whole_uv_step(tmp_path: Path) -> None:
    header = f"#13 [5/8] {_c1_listing_run()}"
    step = [
        header,
        *_C1_PROGRESS,
        f"#13 233.1 {_c1_commands()[-2].removeprefix('echo ').strip(chr(34))}",
        '#13 233.2 [{"name":"example-a","version":"1.0.0"}]',
        "#13 DONE 240.0s",
    ]
    log = [
        "#1 [internal] load build definition from Dockerfile",
        "#12 [4/8] COPY workers/gpu-common/pyproject.toml workers/gpu-common/uv.lock ./",
        "#12 DONE 0.1s",
        *step,
        "#14 [6/8] COPY infra/runpod/v6/images/mineru-pipeline-akc/mineru_akc_server.py",
        "#14 DONE 0.1s",
    ]
    result = _run_listing_step(tmp_path, log, marker=_entry("c1")["listing_marker"])
    assert result.returncode == 0, result.stderr
    listing = (tmp_path / "package-listing.log").read_text(encoding="utf-8").splitlines()
    assert listing == step


def test_c1_listing_step_refuses_the_failed_jobs_shape(tmp_path: Path) -> None:
    log = [
        f"#13 [5/8] {_c1_listing_run()}",
        *_C1_PROGRESS,
        "#13 233.1 /app/.venv/bin/python3: No module named pip",
        '#13 ERROR: process "/bin/sh -c python3 -m pip install" did not complete successfully',
    ]
    result = _run_listing_step(tmp_path, log, marker=_entry("c1")["listing_marker"])
    assert result.returncode != 0
    assert "step #13 did not finish" in result.stderr


# WO-D10-0K2: the jobs check out only what the builds read, and a guard names a missing path.

GUARD_STEP = "Check that every COPY source of the Dockerfile was checked out"
# Anchored at the root, no wildcard and no negation: the only sparse forms _covered models.
_SPARSE_LINE = re.compile(r"/[A-Za-z0-9._/-]+")


def _sparse_patterns() -> list[str]:
    checkout = next(step for step in _steps() if "actions/checkout@" in str(step.get("uses")))
    assert checkout["with"]["sparse-checkout-cone-mode"] is False
    lines = str(checkout["with"]["sparse-checkout"]).splitlines()
    patterns = [line.strip() for line in lines if line.strip()]
    assert patterns
    for pattern in patterns:
        assert _SPARSE_LINE.fullmatch(pattern) and ".." not in pattern.split("/"), pattern
    return patterns


def _covered(path: str, patterns: list[str]) -> bool:
    """Non-cone sparse match: "/a/b/" covers everything under a/b, "/a/b.txt" that file only."""
    anchored = "/" + path
    return any(
        anchored == pattern.rstrip("/") or (pattern.endswith("/") and anchored.startswith(pattern))
        for pattern in patterns
    )


def _copy_sources(dockerfile: str) -> list[str]:
    """The context paths COPY/ADD read: continuations joined, --flags dropped, --from= skipped."""
    sources: list[str] = []
    for line in re.sub(r"\\\r?\n", " ", dockerfile).splitlines():
        words = line.split()
        if not words or words[0].upper() not in {"COPY", "ADD"}:
            continue
        if any(word.startswith("--from=") for word in words[1:]):
            continue
        args = [word for word in words[1:] if not word.startswith("--")]
        assert len(args) >= 2, line
        sources.extend(args[:-1])
    return sources


def _read_paths(context: str, dockerfile: str) -> list[str]:
    paths = []
    for source in _copy_sources(dockerfile):
        assert not source.startswith("/") and ".." not in source.split("/"), source
        assert not set(source) & set('*?[<"$'), source
        paths.append(posixpath.normpath(posixpath.join(context, source)))
    return paths


def _entries() -> list[dict[str, Any]]:
    return list(_workflow()["jobs"]["build"]["strategy"]["matrix"]["include"])


def _entry(slot: str) -> dict[str, Any]:
    return next(entry for entry in _entries() if entry["slot"] == slot)


def _paths_each_job_reads() -> dict[str, list[str]]:
    # The Dockerfile (the bind step greps it, the build reads it) and every COPY source.
    return {
        entry["slot"]: [
            entry["dockerfile"],
            *_read_paths(
                entry["context"], (ROOT / entry["dockerfile"]).read_text(encoding="utf-8")
            ),
        ]
        for entry in _entries()
    }


def test_sparse_checkout_holds_every_path_each_job_reads() -> None:
    patterns = _sparse_patterns()
    for slot, paths in _paths_each_job_reads().items():
        assert len(paths) > 1, slot
        for path in paths:
            assert (ROOT / path).exists(), (slot, path)
            assert _covered(path, patterns), (slot, path)


def test_every_sparse_line_holds_a_path_a_job_reads() -> None:
    read = {path for paths in _paths_each_job_reads().values() for path in paths}
    for pattern in _sparse_patterns():
        assert any(_covered(path, [pattern]) for path in read), pattern


@pytest.mark.parametrize(
    ("added", "outside"),
    [
        ("COPY docs/notes.md /opt/akc/\n", ["docs/notes.md"]),
        (
            "COPY --chown=10001:10001 infra/runpod/v6/images/paddleocr-vl-akc/Dockerfile \\\n"
            "     assets/3d/master/hero-master.blend /opt/akc/\n",
            ["assets/3d/master/hero-master.blend"],
        ),
        ("ADD workers/gpu-common/README.md /app/\n", ["workers/gpu-common/README.md"]),
    ],
)
def test_a_copy_from_outside_the_sparse_list_is_caught(added: str, outside: list[str]) -> None:
    patterns = _sparse_patterns()
    entry = _entry("c1")
    dockerfile = (ROOT / entry["dockerfile"]).read_text(encoding="utf-8") + added
    read = _read_paths(entry["context"], dockerfile)
    assert [path for path in read if not _covered(path, patterns)] == outside


def test_guard_step_runs_between_the_checkout_and_the_bind_step() -> None:
    names = [step.get("name") for step in _steps()]
    guard = names.index(GUARD_STEP)
    assert guard == names.index("Check out the pushed commit") + 1
    assert guard < names.index("Bind the source commit, the image tag and the base image")


# The guard step's own script, run by bash on a tree that holds only the sparse list.


def _sparse_tree(tmp_path: Path) -> Path:
    tree = tmp_path / "workspace"
    for pattern in _sparse_patterns():
        source, target = ROOT / pattern.strip("/"), tree / pattern.strip("/")
        if pattern.endswith("/"):
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    return tree


def _run_guard(tree: Path, entry: dict[str, Any]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to run the workflow step"
    script = next(step["run"] for step in _steps() if step.get("name") == GUARD_STEP)
    # A file, not `-c`: on Windows the command line collapses the awk regex's `\\` to `\`.
    script_path = tree.parent / "guard-step.sh"
    script_path.write_text(script, encoding="utf-8", newline="\n")
    return subprocess.run(
        [bash, "--noprofile", "--norc", script_path.as_posix()],
        cwd=tree,
        env={
            **os.environ,
            "PATH": str(Path(bash).parent) + os.pathsep + os.environ.get("PATH", ""),
            "DOCKERFILE": entry["dockerfile"],
            "BUILD_CONTEXT": entry["context"],
        },
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("slot", ["c0", "c3", "c1"])
def test_guard_passes_on_the_sparse_tree_and_checks_what_the_dockerfile_copies(
    tmp_path: Path, slot: str
) -> None:
    result = _run_guard(_sparse_tree(tmp_path), _entry(slot))
    assert result.returncode == 0, result.stderr
    prefix = "COPY source present: "
    checked = [
        posixpath.normpath(line.removeprefix(prefix))
        for line in result.stdout.splitlines()
        if line.startswith(prefix)
    ]
    assert checked == _paths_each_job_reads()[slot][1:]


_MINERU = "infra/runpod/v6/images/mineru-pipeline-akc"


@pytest.mark.parametrize(
    ("slot", "removed", "named"),
    [
        ("c1", "workers/gpu-common/uv.lock", "./workers/gpu-common/uv.lock"),
        (
            "c1",
            f"{_MINERU}/recipes/c1-layout-weights-manifest.json",
            f"./{_MINERU}/recipes/c1-layout-weights-manifest.json",
        ),
        ("c3", f"{_MINERU}/requirements-c3.lock", f"{_MINERU}/requirements-c3.lock"),
        ("c0", f"{_MINERU}/recipes", f"{_MINERU}/recipes/"),
        ("c0", f"{_MINERU}/Dockerfile", f"{_MINERU}/Dockerfile (the Dockerfile itself)"),
    ],
)
def test_guard_fails_naming_the_missing_path(
    tmp_path: Path, slot: str, removed: str, named: str
) -> None:
    tree = _sparse_tree(tmp_path)
    target = tree / removed
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    result = _run_guard(tree, _entry(slot))
    assert result.returncode != 0
    assert f"missing from the checkout: {named}" in result.stderr


def test_guard_refuses_a_dockerfile_with_no_copy(tmp_path: Path) -> None:
    tree = tmp_path / "workspace"
    tree.mkdir()
    (tree / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    result = _run_guard(tree, {"dockerfile": "Dockerfile", "context": "."})
    assert result.returncode != 0
    assert "no COPY source found in Dockerfile" in result.stderr


# WO-D10-0U: each stage imports what its recipe reaches by the first page, right after its
# install. The class: a module the recipe's path imports that the image does not install, which
# `pip check` cannot see when the vendor does not declare it (MinerU 3.4.4 and six).

_IMAGES = ROOT / "infra/runpod/v6/images"


def _stages(dockerfile: Path) -> dict[str, list[str]]:
    """Instructions per build stage, continuation lines joined; an unnamed stage is ``""``."""
    stages: dict[str, list[str]] = {}
    current = None
    joined = re.sub(r"\\\r?\n", " ", dockerfile.read_text(encoding="utf-8"))
    for raw in joined.splitlines():
        line = " ".join(raw.split())
        if line.startswith("FROM "):
            words = line.split()
            current = words[3] if len(words) == 4 and words[2].upper() == "AS" else ""
            stages[current] = []
        elif current is not None and line and not line.startswith("#"):
            stages[current].append(line)
    return stages


def _gate_run(dockerfile: Path, stage: str) -> str:
    (run,) = [s for s in _stages(dockerfile)[stage] if s.startswith("RUN ") and ' -c "' in s]
    return run


def _gate(dockerfile: Path, stage: str) -> str:
    return _gate_run(dockerfile, stage).split(' -c "', 1)[1].split('"', 1)[0]


# A shared library loaded by name (WO-D10-0U r3: C1's libgomp.so.1, the library libpaddle.so
# failed on at the first launch), in the form a gate inside `-c "..."` can carry.
_LIBRARY = re.compile(r"ctypes\.CDLL\('([\w.+-]+)'\)")


def _gate_statements(code: str) -> tuple[list[tuple[str, list[str]]], list[str]]:
    """(module, names) per import, and the libraries loaded by name; anything else fails."""
    imports: list[tuple[str, list[str]]] = []
    libraries: list[str] = []
    for statement in (s.strip() for s in code.split(";")):
        if statement.startswith("import "):
            imports += [(module.strip(), []) for module in statement[7:].split(",")]
            continue
        library = _LIBRARY.fullmatch(statement)
        if library:
            libraries.append(library[1])
            continue
        match = re.fullmatch(r"from ([\w.]+) import ([\w, ]+)", statement)
        assert match, f"not an import or a library load: {statement!r}"
        imports.append((match[1], [name.strip() for name in match[2].split(",")]))
    return imports, libraries


def _names(code: str) -> set[str]:
    """What the code imports and loads: each module, each name taken from a module as
    module.name, and each library loaded by name."""
    imports, libraries = _gate_statements(code)
    return (
        {m for m, names in imports if not names}
        | {f"{m}.{n}" for m, names in imports for n in names}
        | set(libraries)
    )


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


# Each stage's gate is exactly this list, which is also the README's table (closing round: a
# name dropped from a gate, or a table that says more than the gate runs, fails). C1's gate
# checks what a CPU build runner can check (WO-D10-0U r3, lead decision A): `import paddle`
# needs libcuda.so.1, the driver library the NVIDIA runtime injects on a GPU host, so paddle
# and paddleocr are imported by the pod preflight instead (_GPU_ONLY).
_GATES = [
    (
        _IMAGES / "mineru-pipeline-akc/Dockerfile",
        "c0",
        "pip install",
        {
            "cv2",
            "onnxruntime",
            "mineru.cli.client",
            "mineru.cli.fast_api",
            "mineru.backend.pipeline.pipeline_analyze",
            "mineru.backend.pipeline.batch_analyze",
            "mineru.backend.pipeline.pipeline_middle_json_mkcontent",
        },
    ),
    (
        _IMAGES / "mineru-pipeline-akc/Dockerfile",
        "c3",
        "pip install",
        {
            "accelerate",
            "mineru.utils.table_merge",
            "mineru_vl_utils.vlm_client.transformers_client",
            "mineru_vl_utils.post_process.cross_page_table",
            "transformers.AutoProcessor",
            "transformers.Qwen2VLForConditionalGeneration",
        },
    ),
    (
        _IMAGES / "paddleocr-vl-akc/Dockerfile",
        "",
        "uv pip install",
        {"ctypes", "libgomp.so.1", "cv2", "sentencepiece.sentencepiece_model_pb2"},
    ),
]
# What only a GPU host can import, so the pod's preflight imports it and the build does not
# (lead decision B): C1's service import and the paddle core it loads.
_GPU_ONLY = {"c0": set[str](), "c3": set[str](), "": {"paddle", "paddleocr.PaddleOCRVL"}}
_README = _IMAGES / "mineru-pipeline-akc/README.md"
_README_ROW = {"c0": "| `c0` |", "c3": "| `c3` |", "": "| C1 (`../paddleocr-vl-akc`) |"}


def _readme_cells(stage: str) -> list[str]:
    (row,) = [
        line
        for line in _README.read_text(encoding="utf-8").splitlines()
        if line.startswith(_README_ROW[stage])
    ]
    return row.split("|")


def _preflight(stage: str) -> str:
    """The pod preflight the README's row gives the lead (the "Pod preflight" column)."""
    commands: list[str] = re.findall(r"`([^`]+)`", _readme_cells(stage)[3])
    (command,) = commands
    return command


# `[VAR=value ...] <python> -c "<code>"` and nothing after it.
_COMMAND = re.compile(r'((?:[A-Z_]+=\S+ )*)(\S+) -c "([^"]*)"')


@pytest.mark.parametrize(("dockerfile", "stage", "install", "required"), _GATES)
def test_each_stage_imports_its_recipes_path_after_its_install(
    dockerfile: Path, stage: str, install: str, required: set[str]
) -> None:
    steps = _stages(dockerfile)[stage]
    installs = [i for i, s in enumerate(steps) if s.startswith("RUN ") and install in s]
    gates = [i for i, s in enumerate(steps) if s.startswith("RUN ") and ' -c "' in s]
    assert installs and len(gates) == 1 and gates[0] > max(installs), (stage, steps)
    assert _names(_gate(dockerfile, stage)) == required


@pytest.mark.parametrize(("dockerfile", "stage", "install", "required"), _GATES)
def test_the_readme_table_lists_exactly_what_each_gate_imports(
    dockerfile: Path, stage: str, install: str, required: set[str]
) -> None:
    imported = _readme_cells(stage)[2]  # the "Imported at build" column
    assert set(re.findall(r"`([\w.]+)`", imported)) == required


@pytest.mark.parametrize(("dockerfile", "stage"), [(g[0], g[1]) for g in _GATES])
def test_the_pod_preflight_is_the_build_gate_plus_only_what_needs_a_gpu(
    dockerfile: Path, stage: str
) -> None:
    """Lead decision B: the README gives each slot a preflight the launch script runs before
    the weights. It is the build gate's own line, verbatim and first, under the same
    interpreter, plus only the GPU-only imports (none for C0 and C3); the build gate holds none
    of those."""
    match = _COMMAND.fullmatch(_preflight(stage))
    assert match, _preflight(stage)
    gate_code = _gate(dockerfile, stage)
    gate_python = _gate_run(dockerfile, stage).split(' -c "', 1)[0].split()[-1]
    assert match[2] == gate_python
    assert match[3].startswith(gate_code)
    assert _names(match[3]) == _names(gate_code) | _GPU_ONLY[stage]
    assert _names(gate_code).isdisjoint(_GPU_ONLY[stage])
    if not _GPU_ONLY[stage]:
        assert match[3] == gate_code


@pytest.mark.parametrize(("dockerfile", "stage"), [(g[0], g[1]) for g in _GATES])
def test_each_gate_keeps_no_cache_in_a_layer(dockerfile: Path, stage: str) -> None:
    """HOME points at a directory the same RUN removes, after the import succeeded."""
    run = _gate_run(dockerfile, stage)
    assert run.startswith("RUN HOME=/tmp/akc-import-gate "), run
    assert run.endswith(" && rm -rf /tmp/akc-import-gate"), run


# How a broken module fails: an import of a module nobody installs (C0's six), generated
# protobuf code whose runtime check raises (C1's sentencepiece_model_pb2: not an ImportError),
# and the module itself not installed (C1's cv2 in r3's list).
_BREAKAGES = {
    "absent": (
        "import akc_gate_test_absent_module\n",
        "No module named 'akc_gate_test_absent_module'",
    ),
    "gencode": (
        "class VersionError(Exception):\n    pass\n"
        "raise VersionError('Detected incompatible Protobuf Gencode/Runtime versions')\n",
        "VersionError: Detected incompatible Protobuf Gencode/Runtime versions",
    ),
    "missing": ("", "No module named '{module}'"),
}


def _fake_tree(
    root: Path, imports: list[tuple[str, list[str]]], broken: str | None, how: str = "absent"
) -> None:
    """Each module the gate names as a package (the standard library's own are left to the
    interpreter); ``broken`` fails the way ``how`` names."""
    own = [(m, names) for m, names in imports if not _is_stdlib(m)]
    for module, _ in own:
        parts = module.split(".")
        for depth in range(1, len(parts) + 1):
            package = root.joinpath(*parts[:depth])
            package.mkdir(exist_ok=True)
            (package / "__init__.py").touch()
    for module, names in own:
        body = "".join(f"{name} = None\n" for name in names)
        if module == broken:
            body = _BREAKAGES[how][0] + body
        (root.joinpath(*module.split(".")) / "__init__.py").write_text(body, encoding="utf-8")
    if broken is not None and how == "missing":
        shutil.rmtree(root.joinpath(*broken.split(".")))


def _loader_stand_in(present: list[str]) -> str:
    """Code that makes ctypes.CDLL load exactly ``present`` and refuse any other name the way
    the dynamic loader does; the build runner's loader is not this machine's."""
    return (
        "import ctypes\n"
        "def _akc_load(name, *args, **kwargs):\n"
        f"    if name not in {present!r}:\n"
        "        raise OSError(\n"
        "            name + ': cannot open shared object file: No such file or directory')\n"
        "ctypes.CDLL = _akc_load\n"
    )


def _codes() -> list[Any]:
    """Every gate, and every pod preflight, as code the class tests run."""
    out = []
    for dockerfile, stage, _, _ in _GATES:
        out.append(pytest.param(_gate(dockerfile, stage), id=f"build-{stage or 'c1'}"))
        match = _COMMAND.fullmatch(_preflight(stage))
        assert match, stage
        out.append(pytest.param(match[3], id=f"preflight-{stage or 'c1'}"))
    return out


def _run_code(code: str, tree: Path, present: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ``code`` where only the standard library and ``tree`` can be imported (``-S``: no
    site-packages, so a module this host happens to have installed cannot stand in for one the
    tree leaves out)."""
    prefix = f"import sys\nsys.path.insert(0, {str(tree)!r})\n" + _loader_stand_in(present)
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", prefix + code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("how", sorted(_BREAKAGES))
@pytest.mark.parametrize("code", _codes())
def test_the_gate_fails_on_a_missing_import_inside_any_module_it_names(
    tmp_path: Path, code: str, how: str
) -> None:
    """The gate's own code (and each preflight's), on a synthetic tree of the modules it
    names: it passes when every module imports and every library loads, and exits non-zero
    when any one module imports an absent module, raises a non-ImportError at import, or is
    not installed (a check that only looks a module up, such as ``find_spec``, would pass the
    first two), and when any library it names cannot be loaded."""
    imports, libraries = _gate_statements(code)

    def run(broken: str | None, missing_library: str | None = None) -> Any:
        tree = tmp_path / f"{broken or 'whole'}-{missing_library or 'all'}"
        tree.mkdir()
        _fake_tree(tree, imports, broken, how)
        return _run_code(code, tree, [lib for lib in libraries if lib != missing_library])

    whole = run(None)
    assert whole.returncode == 0, whole.stderr
    for module, _ in imports:
        if _is_stdlib(module):
            continue
        result = run(module)
        assert result.returncode != 0, module
        assert _BREAKAGES[how][1].format(module=module) in result.stderr, module
    for library in libraries:
        result = run(None, library)
        assert result.returncode != 0, library
        assert f"{library}: cannot open shared object file" in result.stderr, library


def test_the_c1_gate_fails_through_the_real_loader_on_a_library_it_cannot_find(
    tmp_path: Path,
) -> None:
    """The C1 gate's library line through the real ctypes and the real loader of this machine
    (no stand-in), with the name swapped for one nobody ships: the gate exits non-zero naming
    it. libgomp.so.1 itself is not asserted absent here: on a Linux test host it exists."""
    code = _gate(_IMAGES / "paddleocr-vl-akc/Dockerfile", "")
    imports, libraries = _gate_statements(code)
    assert libraries == ["libgomp.so.1"]
    absent = "libakc_gate_test_absent.so.1"
    _fake_tree(tmp_path, imports, None)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-S",
            "-c",
            f"import sys; sys.path.insert(0, {str(tmp_path)!r}); "
            + code.replace("'libgomp.so.1'", repr(absent)),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode != 0
    assert absent in result.stderr
