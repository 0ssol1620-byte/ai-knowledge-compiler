"""Controls for the fail-closed isolated-interpreter check.

``sfir4_isolated_env.py`` exists because ``execution_environment:
isolated_git_checkout`` can be written into a receipt while the interpreter
that actually ran imports a completely different Protected Core -- either the
shared working tree (via the shared venv's absolute-path ``.pth``) or an
unrelated sibling clone (via a different interpreter's own editable
install). Every test here is a control against that specific failure shape,
not a general-purpose smoke test: each one names the exact condition that
must REFUSE and proves the code actually reaches that branch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

NS = Path(__file__).resolve().parents[1]
ROOT = NS.parents[1]

sys.path.insert(0, str(NS / "tools"))

import common  # noqa: E402
import sfir4_isolated_env as iso  # noqa: E402

SHARED_VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
CIR_SRC = ROOT / "packages" / "cir-python" / "src"

# The bash-PATH interpreter this study's brief identified as resolving a
# sibling clone (not this repository) via its own editable .pth. Located the
# same way `which python` in a bash shell would find it. Tests that need it
# skip cleanly when it is not present, per the brief.
BASH_PATH_PYTHON = Path(
    r"C:\Users\yspow\AppData\Local\Programs\Python\Python313\python.exe"
)


def _secret_shaped(text: str) -> bool:
    import re

    return bool(re.search(r"(?i)\b\w*(key|token|secret|password|auth|credential)\w*\s*[=:]", text))


class TestSharedVenvIsolatedToItsOwnCheckout:
    """Pins today's true happy path: the shared venv against its own src root."""

    def test_verify_passes(self) -> None:
        if not SHARED_VENV_PYTHON.exists():
            pytest.skip("shared venv interpreter not present at expected path")
        body = iso.verify(CIR_SRC, python=SHARED_VENV_PYTHON)
        assert body["verdict"] == "PASS", body["why"]
        assert body["why"] == []

    def test_require_isolated_does_not_raise(self) -> None:
        if not SHARED_VENV_PYTHON.exists():
            pytest.skip("shared venv interpreter not present at expected path")
        result = iso.require_isolated(CIR_SRC, python=SHARED_VENV_PYTHON)
        assert result["verdict"] == "PASS"

    def test_probe_reports_all_six_core_modules_under_expected_root(self) -> None:
        if not SHARED_VENV_PYTHON.exists():
            pytest.skip("shared venv interpreter not present at expected path")
        report = iso.probe(CIR_SRC, python=SHARED_VENV_PYTHON)
        expected_root = CIR_SRC.resolve()
        assert set(iso.CORE_MODULES) <= set(report["modules"].keys())
        for name in iso.CORE_MODULES:
            entry = report["modules"][name]
            assert entry["error"] is None, f"{name}: {entry['error']}"
            resolved = Path(entry["file"]).resolve()
            assert iso._is_under(resolved, expected_root), (
                f"{name} resolved outside {expected_root}"
            )


class TestBashPathPythonResolvesASiblingCloneAndRefuses:
    """The newly-observed failure: a different interpreter, a different repo entirely."""

    def test_verify_refuses_naming_the_sibling_clone(self) -> None:
        if not BASH_PATH_PYTHON.exists():
            pytest.skip("bash-PATH python not present on this machine")
        body = iso.verify(CIR_SRC, python=BASH_PATH_PYTHON)
        assert body["verdict"] == "REFUSE"
        assert body["why"], "expected at least one refusal reason"
        combined = " ".join(body["why"]).lower()
        assert "sibling clone" in combined or "outside" in combined
        # It must specifically implicate the sibling checkout, not just fail vaguely.
        assert "collection-plane-rehearsal" in combined

    def test_require_isolated_raises(self) -> None:
        if not BASH_PATH_PYTHON.exists():
            pytest.skip("bash-PATH python not present on this machine")
        with pytest.raises(iso.IsolationRefused):
            iso.require_isolated(CIR_SRC, python=BASH_PATH_PYTHON)


class TestNonexistentExpectedRootRefuses:
    def test_verify_refuses(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist" / "src"
        body = iso.verify(missing)
        assert body["verdict"] == "REFUSE"
        assert any("does not exist" in reason for reason in body["why"])

    def test_probe_is_never_attempted_against_a_missing_root(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist" / "src"
        with patch.object(iso, "probe") as mock_probe:
            body = iso.verify(missing)
        mock_probe.assert_not_called()
        assert body["verdict"] == "REFUSE"


class TestFabricatedForeignPthRefuses:
    """Injects a broken environment rather than requiring a real one to exist."""

    def _fake_report(self, expected_root: Path, foreign_pth_target: Path) -> dict[str, Any]:
        root_str = str(expected_root)
        return {
            "python": str(iso._default_python()),
            "expected_root": root_str,
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "pythonpath_env": None,
            "sys_path": [root_str],
            "modules": {
                name: {"file": str(expected_root / (name.split(".")[-1] + ".py")), "error": None}
                for name in iso.CORE_MODULES
            },
            "pth_files": {
                r"C:\fake\site-packages\_editable_impl_fake.pth": str(foreign_pth_target),
            },
            "foreign_sys_path": [],
        }

    def test_verify_refuses_on_foreign_pth(self, tmp_path: Path) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)
        for name in iso.CORE_MODULES:
            (expected_root / (name.split(".")[-1] + ".py")).write_text("# stub\n")

        foreign = tmp_path / "sibling-clone" / "packages" / "cir-python" / "src"
        foreign.mkdir(parents=True)

        fake_report = self._fake_report(expected_root, foreign)
        with patch.object(iso, "probe", return_value=fake_report):
            body = iso.verify(expected_root)

        assert body["verdict"] == "REFUSE"
        combined = " ".join(body["why"])
        assert ".pth" in combined
        assert str(foreign.resolve()) in combined or "outside both the intended" in combined

    def test_verify_passes_when_pth_only_references_expected_root_or_own_tree(
        self, tmp_path: Path
    ) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)
        for name in iso.CORE_MODULES:
            (expected_root / (name.split(".")[-1] + ".py")).write_text("# stub\n")

        fake_report = self._fake_report(expected_root, expected_root)
        with patch.object(iso, "probe", return_value=fake_report):
            body = iso.verify(expected_root)

        assert body["verdict"] == "PASS", body["why"]


class TestFailedProbeRefusesRatherThanPasses:
    def test_probe_that_raises_causes_refuse_not_pass(self, tmp_path: Path) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)

        with patch.object(iso, "probe", side_effect=iso.IsolationRefused("probe exploded")):
            body = iso.verify(expected_root)

        assert body["verdict"] == "REFUSE"
        assert any("probe failed" in reason for reason in body["why"])

    def test_probe_raises_on_nonzero_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A real interpreter, but the probe script itself fails -- must refuse
        # on the subprocess's nonzero exit, distinct from an unusable
        # interpreter path (OSError, covered below) or bad JSON.
        monkeypatch.setattr(iso, "_PROBE_SOURCE", "raise SystemExit(3)\n")
        with pytest.raises(iso.IsolationRefused):
            iso.probe(ROOT, python=Path(sys.executable))

    def test_probe_raises_on_unusable_interpreter_path(self, tmp_path: Path) -> None:
        bogus = tmp_path / "not-a-real-interpreter.exe"
        with pytest.raises(iso.IsolationRefused):
            iso.probe(tmp_path, python=bogus)

    def test_require_isolated_raises_when_probe_fails(self, tmp_path: Path) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)
        with (
            patch.object(iso, "probe", side_effect=iso.IsolationRefused("boom")),
            pytest.raises(iso.IsolationRefused),
        ):
            iso.require_isolated(expected_root)


class TestModuleOutsideExpectedRootRefuses:
    def test_verify_refuses_when_a_core_module_resolves_elsewhere(self, tmp_path: Path) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()

        modules: dict[str, Any] = {
            name: {
                "file": str(elsewhere / (name.split(".")[-1] + ".py"))
                if name == "akc_cir.identity"
                else str(expected_root / (name.split(".")[-1] + ".py")),
                "error": None,
            }
            for name in iso.CORE_MODULES
        }
        fake_report: dict[str, Any] = {
            "python": str(iso._default_python()),
            "expected_root": str(expected_root),
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "pythonpath_env": None,
            "sys_path": [str(expected_root)],
            "modules": modules,
            "pth_files": {},
            "foreign_sys_path": [],
        }
        for name in iso.CORE_MODULES:
            path = Path(modules[name]["file"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# stub\n")

        with patch.object(iso, "probe", return_value=fake_report):
            body = iso.verify(expected_root)

        assert body["verdict"] == "REFUSE"
        combined = " ".join(body["why"])
        assert "akc_cir.identity" in combined
        assert "outside the intended root" in combined


class TestSiblingCloneOnSysPathRefusesEvenIfModulesLookFine:
    def test_verify_refuses_on_sibling_akc_cir_dir_in_sys_path(self, tmp_path: Path) -> None:
        expected_root = tmp_path / "expected" / "src"
        expected_root.mkdir(parents=True)
        for name in iso.CORE_MODULES:
            (expected_root / (name.split(".")[-1] + ".py")).write_text("# stub\n")

        sibling_src = (
            tmp_path
            / "ai-knowledge-compiler-collection-plane-rehearsal"
            / "packages"
            / "cir-python"
            / "src"
        )
        (sibling_src / "akc_cir").mkdir(parents=True)
        (sibling_src / "akc_cir" / "__init__.py").write_text("# stub\n")

        fake_report: dict[str, Any] = {
            "python": str(iso._default_python()),
            "expected_root": str(expected_root),
            "executable": sys.executable,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
            "pythonpath_env": None,
            "sys_path": [str(expected_root), str(sibling_src)],
            "modules": {
                name: {"file": str(expected_root / (name.split(".")[-1] + ".py")), "error": None}
                for name in iso.CORE_MODULES
            },
            "pth_files": {},
            "foreign_sys_path": [str(sibling_src)],
        }

        with patch.object(iso, "probe", return_value=fake_report):
            body = iso.verify(expected_root)

        assert body["verdict"] == "REFUSE"
        combined = " ".join(body["why"])
        assert "sibling clone" in combined


class TestReceiptCarriesNoSecretShapedValues:
    def test_verify_receipt_json_has_no_secret_shaped_strings(self) -> None:
        if not SHARED_VENV_PYTHON.exists():
            pytest.skip("shared venv interpreter not present at expected path")
        body = iso.verify(CIR_SRC, python=SHARED_VENV_PYTHON)
        text = json.dumps(body)
        assert not _secret_shaped(text), text

    def test_pythonpath_env_value_is_redacted_when_secret_shaped(self) -> None:
        redacted = iso._filter_secrets("AWS_SECRET_ACCESS_KEY=abc123")
        assert redacted is not None
        assert "abc123" not in redacted
        assert "redacted" in redacted

    def test_pythonpath_env_value_passes_through_when_benign(self) -> None:
        value = r"C:\some\path;D:\another\path"
        assert iso._filter_secrets(value) == value

    def test_none_pythonpath_stays_none(self) -> None:
        assert iso._filter_secrets(None) is None


class TestCliWritesAReceipt:
    def test_main_write_receipt_writes_a_receipt_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if not SHARED_VENV_PYTHON.exists():
            pytest.skip("shared venv interpreter not present at expected path")
        fake_ns = tmp_path / "ns"
        (fake_ns / "receipts").mkdir(parents=True)
        monkeypatch.setattr(iso, "NS", fake_ns)
        # `rel()` (used by main() when writing a receipt) resolves paths relative
        # to common.ROOT; point it at tmp_path so the fake receipt location is
        # actually relative to something, without touching the real ROOT.
        monkeypatch.setattr(common, "ROOT", tmp_path)

        rc = iso.main(
            [
                "--expected-root",
                str(CIR_SRC),
                "--python",
                str(SHARED_VENV_PYTHON),
                "--write-receipt",
            ]
        )
        assert rc == 0
        receipt_path = fake_ns / "receipts" / f"{iso.STEM}.json"
        assert receipt_path.exists()
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert payload["verdict"] == "PASS"
        assert "receipt_sha256" in payload
