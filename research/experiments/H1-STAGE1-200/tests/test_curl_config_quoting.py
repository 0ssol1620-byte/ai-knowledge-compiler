"""curl reads backslash escapes inside a quoted --config value.

A Windows destination path handed over raw is silently rewritten -- `\\run-abc`
becomes CR + "un-abc", `\\vllm.json` becomes VT + "llm.json", the drive letter
and every separator disappear -- and curl writes the download into the process
working directory under the mangled name. It reports success while doing it.

That is not a cosmetic problem. `fetch_and_validate_results` downloads the
200-document result archive through this path and then checks
`not result_archive.is_file()`, so the run fails *after* the GPU work is paid
for, and the 144 files it left in the repository root are the only trace.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPTS = ROOT / "research" / "experiments" / "H1-STAGE1-200" / "scripts"
SCRIPT = SCRIPTS / "run_stage1_v29_r2_v7_r2_verified.py"


@pytest.fixture(scope="module")
def base():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("stage1_v7_for_quoting", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_backslashes_survive_the_config(base) -> None:
    quoted = base._curl_config_quote(r"D:\CodexProjects\run-abc\vllm.json")
    assert quoted == r"D:\\CodexProjects\\run-abc\\vllm.json"


def test_a_quote_cannot_end_the_value_early(base) -> None:
    """An unescaped quote would terminate the value and turn the rest of the
    path into curl config directives."""
    assert base._curl_config_quote('a"b') == r"a\"b"


def test_a_path_with_no_escapes_is_unchanged(base) -> None:
    assert base._curl_config_quote("https://example.invalid/a.json") == (
        "https://example.invalid/a.json"
    )


def test_curl_itself_writes_to_the_path_it_was_given(base, tmp_path) -> None:
    """The regression, end to end, against real curl.

    `run-` and `vllm` are not arbitrary: \\r and \\v are the two escapes that
    actually appear in this campaign's own filenames.
    """
    destination = tmp_path / "run-abc" / "vllm-probe.json"
    destination.parent.mkdir()
    before = sorted(p.name for p in Path.cwd().iterdir())
    base.curl_get(
        "https://example.invalid.proxy.runpod.net/status.json",
        output=destination,
        timeout=5,
    )
    # The request fails -- the host does not resolve -- but where curl decided to
    # put its output file is settled by the config, not by the response.
    assert sorted(p.name for p in Path.cwd().iterdir()) == before, (
        "curl wrote into the working directory instead of the given path"
    )


def test_the_allowlist_still_rejects_a_non_proxy_url(base, tmp_path) -> None:
    """Quoting must not become a way to smuggle a URL past the allowlist."""
    with pytest.raises(RuntimeError, match="allowlist"):
        base.curl_get("https://example.com/a.json", output=tmp_path / "a.json")


def test_every_quoted_config_value_goes_through_the_escaper() -> None:
    """A future line added to the config without the escaper reopens this."""
    source = SCRIPT.read_text(encoding="utf-8")
    body = source.split("def curl_get(", 1)[1].split("\ndef ", 1)[0]
    for line in body.splitlines():
        stripped = line.strip()
        if '= "{' in stripped or '= \\"{' in stripped:
            assert "_curl_config_quote" in stripped, stripped


def test_curl_is_available_for_the_end_to_end_check() -> None:
    """Guards the test above from silently passing on a machine without curl."""
    curl = shutil.which("curl")
    assert curl is not None, "no curl on PATH; the end-to-end check proves nothing"
    completed = subprocess.run(  # noqa: S603
        [curl, "--version"], capture_output=True, check=False
    )
    assert completed.returncode == 0
