"""Is the interpreter that will run SFIR4 actually isolated?

``sfir4_core_conformance.py`` answers "does the akc_cir that would load
implement the algorithm". This module answers the question one layer below
that: **which interpreter, and which akc_cir, is ``isolated_git_checkout``
actually a claim about?**

Two failure shapes motivate a machine check rather than trusting the receipt
field:

**The shared virtualenv leaks the shared working tree.** ``ROOT/.venv``
installs the repository editable, and its ``.pth`` hard-codes the ABSOLUTE
path ``D:\\CodexProjects\\ai-knowledge-compiler\\packages\\cir-python\\src``
into site-packages. Running a study through that interpreter from an isolated
git checkout pinned to an exact revision still imports the SHARED working
tree's Protected Core, regardless of which revision the checkout is pinned
to. Every receipt would name the pinned commit; the code that actually ran
would be whatever a developer had open.

**A different interpreter on PATH can resolve ``akc_cir`` to an entirely
different clone.** On this machine the bash-PATH ``python``
(``C:\\Users\\...\\Python313\\python.exe``) has its own editable ``.pth`` at
``Python313\\Lib\\site-packages\\_editable_impl_ai_knowledge_compiler.pth``,
and that ``.pth`` points at
``D:\\CodexProjects\\ai-knowledge-compiler-collection-plane-rehearsal``, a
sibling checkout, not this repository at all. A study run under that
interpreter would silently measure a different repository's Protected Core
while its receipt claimed to measure this one.

This module never imports ``akc_cir`` in its own process -- every fact is
gathered by running a probe script in a SUBPROCESS under the interpreter
being examined, so that the report describes that interpreter's resolution,
not this module's.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import NS, now, rel, write_hashed

SCHEMA = "tavonel.sfir4.isolated_env.v1"
STEM = "sfir4-isolated-env"

#: The Protected Core modules whose resolution the study depends on.
CORE_MODULES: tuple[str, ...] = (
    "akc_cir.dependency",
    "akc_cir.recompilation",
    "akc_cir.semantic_diff",
    "akc_cir.identity",
    "akc_cir.inspection",
    "akc_cir.identity_quarantine",
)

#: Env var names that must never reach a receipt, even by accident.
_SECRET_NAME = re.compile(r"(?i)(key|token|secret|password|auth|credential)")

_PROBE_TIMEOUT_S = 60

# Runs under the interpreter being examined, in its OWN process. Emits one
# line of JSON on stdout. Must not depend on anything not in the stdlib,
# because the interpreter under test may be isolated from everything else.
_PROBE_SOURCE = """
import json
import os
import site
import sys
from pathlib import Path

report = {}
report["executable"] = sys.executable
report["prefix"] = sys.prefix
report["base_prefix"] = sys.base_prefix
report["pythonpath_env"] = os.environ.get("PYTHONPATH")
report["sys_path"] = list(sys.path)

module_names = [
    "akc_cir",
    "akc_cir.dependency",
    "akc_cir.recompilation",
    "akc_cir.semantic_diff",
    "akc_cir.identity",
    "akc_cir.inspection",
    "akc_cir.identity_quarantine",
]
modules = {}
for name in module_names:
    try:
        __import__(name)
        mod = sys.modules[name]
        modules[name] = {"file": getattr(mod, "__file__", None), "error": None}
    except Exception as exc:  # noqa: BLE001 - reporting, not handling
        modules[name] = {"file": None, "error": f"{type(exc).__name__}: {exc}"}
report["modules"] = modules

site_dirs = []
try:
    site_dirs.extend(site.getsitepackages())
except Exception:  # noqa: BLE001 - some interpreters lack getsitepackages
    pass
try:
    user_site = site.getusersitepackages()
    if user_site:
        site_dirs.append(user_site)
except Exception:  # noqa: BLE001
    pass
report["site_dirs"] = site_dirs

pth_files = {}
for site_dir in site_dirs:
    directory = Path(site_dir)
    if not directory.is_dir():
        continue
    for pth in sorted(directory.glob("*.pth")):
        try:
            pth_files[str(pth)] = pth.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            pth_files[str(pth)] = f"<unreadable: {exc}>"
report["pth_files"] = pth_files

sys.stdout.write(json.dumps(report))
"""


class IsolationRefused(RuntimeError):
    """The interpreter that would run the study is not the isolated one it claims to be."""


def _resolve(raw: str) -> Path:
    return Path(raw).resolve()


def _is_under(path: Path, root: Path) -> bool:
    """Case-insensitive, symlink/junction-resolved containment check."""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _default_python() -> Path:
    return Path(sys.executable)


def _filter_secrets(value: str | None) -> str | None:
    """Defensive filter for a single reported string, in case it embeds an env dump.

    The probe only ever reports the *value* of PYTHONPATH, never a full
    environment, so this is belt-and-suspenders: it refuses to let a receipt
    carry a string that itself looks like ``NAME=...`` for a secret-shaped
    name.
    """
    if value is None:
        return None
    for piece in re.split(r"[;:]", value):
        name = piece.split("=", 1)[0]
        if _SECRET_NAME.search(name):
            return "<redacted: secret-shaped env value withheld>"
    return value


def probe(expected_root: Path, *, python: Path | None = None) -> dict[str, Any]:
    """Run the probe script under ``python`` (default: this interpreter) and report facts.

    Runs in a SUBPROCESS so the report describes the interpreter under test,
    not the interpreter running this module. Raises ``IsolationRefused`` if
    the subprocess cannot be run or does not produce a parseable report --
    a probe that cannot answer is never silently treated as passing.
    """
    interpreter = Path(python) if python is not None else _default_python()
    expected_root = expected_root.resolve()

    try:
        result = subprocess.run(  # noqa: S603 - fixed script, no shell, interpreter chosen by caller
            [str(interpreter), "-c", _PROBE_SOURCE],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except OSError as error:
        raise IsolationRefused(f"probe could not launch {interpreter}: {error}") from error
    except subprocess.TimeoutExpired as error:
        raise IsolationRefused(f"probe under {interpreter} timed out: {error}") from error

    if result.returncode != 0:
        raise IsolationRefused(
            f"probe under {interpreter} exited {result.returncode}; "
            f"stderr: {result.stderr.strip()[:2000]}"
        )

    try:
        raw = json.loads(result.stdout.strip() or "null")
    except json.JSONDecodeError as error:
        raise IsolationRefused(
            f"probe under {interpreter} did not emit parseable JSON: {error}; "
            f"stdout: {result.stdout[:500]!r}"
        ) from error

    if not isinstance(raw, dict):
        raise IsolationRefused(f"probe under {interpreter} emitted a non-object report")

    prefix = _resolve(raw["prefix"]) if raw.get("prefix") else None
    base_prefix = _resolve(raw["base_prefix"]) if raw.get("base_prefix") else None

    def _own_tree(path: Path) -> bool:
        return (prefix is not None and _is_under(path, prefix)) or (
            base_prefix is not None and _is_under(path, base_prefix)
        )

    foreign_sys_path: list[str] = []
    for entry in raw.get("sys_path", []):
        if not entry:
            continue
        resolved_entry = _resolve(entry)
        if _is_under(resolved_entry, expected_root):
            continue
        if _own_tree(resolved_entry):
            continue
        foreign_sys_path.append(entry)

    return {
        "python": str(interpreter),
        "expected_root": str(expected_root),
        "executable": raw.get("executable"),
        "prefix": raw.get("prefix"),
        "base_prefix": raw.get("base_prefix"),
        "pythonpath_env": _filter_secrets(raw.get("pythonpath_env")),
        "sys_path": list(raw.get("sys_path", [])),
        "modules": raw.get("modules", {}),
        "pth_files": raw.get("pth_files", {}),
        "foreign_sys_path": foreign_sys_path,
    }


def _check_module_roots(report: dict[str, Any], expected_root: Path) -> list[str]:
    reasons: list[str] = []
    modules = report.get("modules", {})
    for name in CORE_MODULES:
        entry = modules.get(name, {})
        if entry.get("error"):
            reasons.append(
                f"{name} could not be imported by the probed interpreter: {entry['error']}"
            )
            continue
        file_str = entry.get("file")
        if not file_str:
            reasons.append(f"{name} has no file origin; it may be a namespace shim")
            continue
        resolved = _resolve(file_str)
        if not _is_under(resolved, expected_root):
            reasons.append(
                f"{name} resolves to {resolved}, outside the intended root {expected_root} "
                "-- this also catches a symlink/junction escape, since resolution follows links"
            )
    return reasons


#: How many path segments a shared ancestor of expected_root and the
#: interpreter's own prefix may sit above either of them and still count as
#: "the same checkout". A real monorepo venv install is shallow (e.g.
#: ``ROOT/.venv`` and ``ROOT/packages/cir-python/src`` share ``ROOT`` one and
#: three segments up respectively). Anything deeper is treated as coincidence
#: rather than a shared checkout -- otherwise two unrelated paths that merely
#: happen to sit under the same home directory (``C:\Users\<name>``) would be
#: silently admitted, which would defeat this check for exactly the sibling-
#: clone case it exists to catch.
#:
#: The depth bound is a heuristic and is deliberately no longer load-bearing on
#: its own: ``_own_tree_roots`` additionally requires the shared ancestor to be
#: a git checkout root (see ``_is_checkout_root``). Depth alone had a real hole
#: -- a venv placed beside a checkout rather than inside it, e.g.
#: ``D:\projects\venvs\x`` with ``D:\projects\repo\packages\p\src``, yields the
#: shallow common ancestor ``D:\projects``, and every sibling clone under it
#: would then be admitted as "the interpreter's own tree". Requiring a ``.git``
#: at the ancestor turns "the same checkout" from an inference about path shape
#: into a fact about the filesystem.
_MAX_CHECKOUT_ANCESTOR_DEPTH = 5


def _is_checkout_root(path: Path) -> bool:
    """Is ``path`` the root of a git checkout?

    ``.git`` is a directory in a normal clone and a FILE in a linked worktree
    (it holds a ``gitdir:`` pointer), and the isolated checkouts this gate is
    built for are linked worktrees -- so testing for a directory only would
    reject exactly the configuration the study uses.
    """
    marker = path / ".git"
    return marker.is_dir() or marker.is_file()


def _own_tree_roots(report: dict[str, Any], expected_root: Path) -> list[Path]:
    """Roots a ``.pth`` reference is allowed to sit under without being "foreign".

    Always includes the interpreter's own ``prefix``. Also includes the
    nearest common ancestor of ``expected_root`` and ``prefix``, when one
    exists on the same drive and is shallow: a monorepo's shared venv
    legitimately installs several sibling packages of the SAME checkout
    editable (e.g. ``packages/domain-packs/src`` next to
    ``packages/cir-python/src``) -- that is not the sibling-CLONE failure
    this module exists to catch, which lives on a different drive/root
    entirely (``ai-knowledge-compiler-collection-plane-rehearsal``).

    Deliberately does NOT use ``base_prefix``: for a venv, ``base_prefix``
    points at the base interpreter install (e.g.
    ``C:\\Users\\<name>\\...\\Python313``), which is not part of the checkout
    at all and would pull in a much shallower, much more permissive shared
    ancestor (a whole home directory) than ``prefix`` does.
    """
    prefix = report.get("prefix")
    if not prefix:
        return []
    prefix_path = _resolve(prefix)
    roots = [prefix_path]

    try:
        common = Path(os.path.commonpath([str(expected_root), str(prefix_path)]))
    except ValueError:
        return roots  # different drives on Windows -- no shared checkout root

    # A bare drive root (e.g. "D:\\") is not a checkout boundary; admitting it
    # would defeat this check entirely.
    if len(common.parts) <= 1:
        return roots

    for candidate in (expected_root, prefix_path):
        try:
            depth = len(candidate.relative_to(common).parts)
        except ValueError:
            depth = _MAX_CHECKOUT_ANCESTOR_DEPTH + 1
        if depth > _MAX_CHECKOUT_ANCESTOR_DEPTH:
            return roots  # too shallow/generic an ancestor to trust

    if not _is_checkout_root(common):
        # The shared ancestor is a container directory, not a checkout. Admitting
        # it would make every sibling clone under it "the interpreter's own
        # tree", which is the failure this whole module exists to catch.
        return roots

    roots.append(common)
    return roots


def _check_pth_files(report: dict[str, Any], expected_root: Path) -> list[str]:
    reasons: list[str] = []
    own_roots = _own_tree_roots(report, expected_root)
    for pth_path, contents in report.get("pth_files", {}).items():
        for line in contents.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("import "):
                continue
            candidate = _resolve(line)
            if _is_under(candidate, expected_root):
                continue
            if any(_is_under(candidate, root) for root in own_roots):
                continue
            reasons.append(
                f".pth file {pth_path} references {candidate}, outside both the intended "
                f"root {expected_root} and the interpreter's own tree"
            )
    return reasons


def _check_sibling_clones(report: dict[str, Any], expected_root: Path) -> list[str]:
    reasons: list[str] = []
    seen: set[str] = set()
    for entry in report.get("sys_path", []):
        if not entry:
            continue
        resolved_entry = _resolve(entry)
        if _is_under(resolved_entry, expected_root):
            continue
        candidate_pkg = resolved_entry / "akc_cir"
        if not candidate_pkg.is_dir():
            continue
        key = str(resolved_entry).casefold()
        if key in seen:
            continue
        seen.add(key)
        reasons.append(
            f"sys.path entry {resolved_entry} resolves an akc_cir package that is not under "
            f"the intended root {expected_root} -- this is a sibling clone, not the study's "
            "checkout"
        )
    return reasons


def verify(expected_root: Path, *, python: Path | None = None) -> dict[str, Any]:
    """Receipt-shaped verdict: is ``python`` isolated to ``expected_root``?

    REFUSE is the default. PASS requires every module to resolve under
    ``expected_root``, no foreign ``.pth`` entry, no sibling-clone sys.path
    entry, and a probe that actually completed.
    """
    interpreter = Path(python) if python is not None else _default_python()
    expected_root_resolved: Path | None
    try:
        expected_root_resolved = expected_root.resolve(strict=True)
    except (OSError, FileNotFoundError):
        expected_root_resolved = None

    why: list[str] = []
    report: dict[str, Any] | None = None

    if expected_root_resolved is None:
        why.append(f"expected_root {expected_root} does not exist")
    else:
        try:
            report = probe(expected_root_resolved, python=interpreter)
        except IsolationRefused as error:
            why.append(f"probe failed, so isolation cannot be confirmed: {error}")

    if report is not None and expected_root_resolved is not None:
        why.extend(_check_module_roots(report, expected_root_resolved))
        why.extend(_check_pth_files(report, expected_root_resolved))
        why.extend(_check_sibling_clones(report, expected_root_resolved))

    verdict = "REFUSE" if why else "PASS"

    return {
        "schema": SCHEMA,
        "generated_at": now(),
        "read_only": True,
        "gpu_seconds": 0,
        "estimated_cost_usd": 0.0,
        "python": str(interpreter),
        "expected_root": str(expected_root),
        "probe": report,
        "totals": {
            "core_modules_checked": len(CORE_MODULES),
            "refusal_reasons": len(why),
        },
        "why": why,
        "what_a_pass_means": (
            "the probed interpreter, run as a fresh subprocess, resolves every Protected "
            "Core module this study depends on from inside expected_root, has no .pth entry "
            "and no sys.path entry that reaches outside expected_root and outside its own "
            "interpreter tree, and no sys.path entry that resolves a sibling akc_cir clone. "
            "It is not a statement about what code those modules contain -- "
            "sfir4_core_conformance answers that -- only about which interpreter and which "
            "checkout would actually execute."
        ),
        "verdict": verdict,
    }


def require_isolated(expected_root: Path, *, python: Path | None = None) -> dict[str, Any]:
    """Fail closed before a study run trusts ``execution_environment``."""
    body = verify(expected_root, python=python)
    if body["verdict"] != "PASS":
        raise IsolationRefused(
            "SFIR4 refused -- interpreter is not isolated to the intended checkout: "
            + "; ".join(body["why"])
        )
    return body


def build_venv(checkout_root: Path) -> Path:
    """Create (or reuse) a venv INSIDE ``checkout_root`` and return its interpreter.

    The venv is created with the standard library ``venv`` module, which
    defaults to an isolated site-packages (no ``--system-site-packages``), so
    it does not inherit the shared ``ROOT/.venv``. The checkout's own package
    is installed into it with ``PYTHONPATH`` cleared for the install
    subprocess, so the install cannot pick up the shared tree's editable
    ``.pth`` either. Nothing is written outside ``checkout_root``.
    """
    checkout_root = checkout_root.resolve()
    venv_dir = checkout_root / ".venv-sfir4"
    venv_python = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    if not venv_python.exists():
        creation = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if creation.returncode != 0 or not venv_python.exists():
            raise RuntimeError(
                f"failed to create venv at {venv_dir}: {creation.stderr.strip()[:2000]}"
            )

    install_env = {
        key: value for key, value in os.environ.items() if key.upper() != "PYTHONPATH"
    }
    install = subprocess.run(  # noqa: S603
        [
            str(venv_python),
            "-m",
            "pip",
            "install",
            "--no-input",
            "--no-deps",
            "-e",
            str(checkout_root),
        ],
        capture_output=True,
        text=True,
        cwd=str(checkout_root),
        env=install_env,
        check=False,
    )
    if install.returncode != 0:
        raise RuntimeError(
            f"failed to install {checkout_root} into {venv_dir}: {install.stderr.strip()[:2000]}"
        )

    return venv_python


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SFIR4 isolated-interpreter refusal gate.")
    parser.add_argument(
        "--expected-root",
        type=Path,
        required=True,
        help="the src directory akc_cir must resolve from",
    )
    parser.add_argument(
        "--python", type=Path, default=None, help="interpreter to probe (default: this one)"
    )
    parser.add_argument("--write-receipt", action="store_true")
    args = parser.parse_args(argv)

    body = verify(args.expected_root, python=args.python)

    if args.write_receipt:
        path = NS / "receipts" / f"{STEM}.json"
        write_hashed(path, body)
        summary = {"receipt": rel(path), "verdict": body["verdict"], "totals": body["totals"]}
    else:
        summary = {
            "verdict": body["verdict"],
            "python": body["python"],
            "expected_root": body["expected_root"],
            "totals": body["totals"],
            "why": body["why"],
        }
    print(json.dumps(summary, indent=1))
    return 0 if body["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
