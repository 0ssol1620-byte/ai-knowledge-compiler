from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def run_builder(tmp_path: Path, *, status: str, evidence: list[dict[str, str]]):
    root = tmp_path / "repo"
    root.mkdir(exist_ok=True)
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
    assert ledger["requirements"][0]["masterplan_state"] == "TARGET-DESIGN"
    assert ledger["requirements"][0]["execution_scope"] == "NON_DESIGN"
    assert ledger["requirements"][0]["traceability_role"] == "SECTION_ANCHOR"
    assert ledger["counts"]["total"] == 1
    assert ledger["actionable_counts"]["total"] == 0


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
    assert ledger["requirements"][0]["masterplan_state"] == "EVIDENCED"


def test_ledger_hash_ignores_volatile_generation_time(tmp_path: Path) -> None:
    completed, output = run_builder(tmp_path, status="OPEN", evidence=[])
    assert completed.returncode == 0
    first = json.loads(output.read_text(encoding="utf-8"))
    completed, output = run_builder(tmp_path, status="OPEN", evidence=[])
    assert completed.returncode == 0
    second = json.loads(output.read_text(encoding="utf-8"))
    assert first["generated_at"] != second["generated_at"]
    assert first["ledger_sha256"] == second["ledger_sha256"]


def test_checkbox_can_inherit_explicit_heading_evidence(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "proof.txt").write_text("proof", encoding="utf-8")
    index = {
        "source": {"sha256": "abc", "path": "masterplan.md"},
        "headings": [{"line": 10, "text": "Requirement"}],
        "checkboxes": [{"line": 20, "text": "Acceptance"}],
        "normative_lines": [],
    }
    overrides = {
        "source_sha256": "abc",
        "requirements": {
            "H-0010": {
                "status": "DONE",
                "evidence": [{"path": "proof.txt", "claim": "exists"}],
            },
            "C-0020": {"inherits": "H-0010"},
        },
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
    assert completed.returncode == 0, completed.stderr
    ledger = json.loads(output_path.read_text(encoding="utf-8"))
    checkbox = next(row for row in ledger["requirements"] if row["kind"] == "checkbox")
    assert checkbox["status"] == "DONE"
    assert checkbox["inherited_from"] == "H-0010"
    assert checkbox["evidence"][0]["exists"] == "true"
