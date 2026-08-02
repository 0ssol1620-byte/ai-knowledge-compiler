from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_builder(tmp_path: Path, *, status: str, evidence: list[dict[str, str]]):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "proof.txt").write_text("proof", encoding="utf-8")
    index = {
        "source": {"sha256": "abc", "path": "masterplan.md"},
        "headings": [{"line": 10, "text": "Requirement"}],
        "checkboxes": [],
        "normative_lines": [],
    }
    overrides = {
        "source_sha256": "abc",
        "requirements": {"H-0010": {"status": status, "evidence": evidence, "blocker": ""}},
    }
    index_path = root / "index.json"
    override_path = root / "overrides.json"
    output_path = root / "ledger.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    override_path.write_text(json.dumps(overrides), encoding="utf-8")
    script = Path(__file__).with_name("build_folynta_v2_traceability.py")
    completed = subprocess.run(  # noqa: S603 - fixed local interpreter and script
        [
            sys.executable,
            str(script),
            str(index_path),
            str(override_path),
            str(output_path),
            "--repo-root",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed, output_path


def test_unmapped_rows_fail_closed(tmp_path: Path) -> None:
    completed, output = run_builder(tmp_path, status="OPEN", evidence=[])
    assert completed.returncode == 0
    ledger = json.loads(output.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["status"] == "OPEN"
    assert ledger["counts"]["total"] == 1


def test_done_requires_existing_evidence(tmp_path: Path) -> None:
    completed, _ = run_builder(
        tmp_path,
        status="DONE",
        evidence=[{"path": "missing.txt", "claim": "missing"}],
    )
    assert completed.returncode != 0
    assert "DONE evidence missing" in completed.stderr


def test_done_accepts_existing_evidence(tmp_path: Path) -> None:
    completed, output = run_builder(
        tmp_path,
        status="DONE",
        evidence=[{"path": "proof.txt", "claim": "exists"}],
    )
    assert completed.returncode == 0
    ledger = json.loads(output.read_text(encoding="utf-8"))
    assert ledger["requirements"][0]["evidence"][0]["exists"] == "true"
