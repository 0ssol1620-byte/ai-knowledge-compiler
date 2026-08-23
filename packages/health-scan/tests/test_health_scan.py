"""Health Scan analyzer tests — synthetic corpus with planted issues.

Each §5.2 section gets a planted defect it must catch, plus negative
controls (valid links/dates/clean pairs) it must NOT flag. An empty
directory must scan cleanly to all-zero "healthy" output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from akc_health_scan import HealthReport, HealthScanConfig, scan  # noqa: E402

SECTION_NAMES = (
    "sources",
    "duplicates",
    "identity_collisions",
    "conflicting_candidates",
    "stale_references",
    "unresolved_dates",
    "sensitive_exposure",
    "projection_readiness",
    "estimated_compile_work",
)

DUP_TEXT = "# Shared\n\n" + (
    "The compiler preserves provenance for every chunk it ingests.\n" * 8
)
NEAR_BASE = "Weekly sync notes.\n" + (
    "We agreed to ship the parser on Friday and review the latency numbers.\n" * 6
)


def build_corpus(root: Path) -> Path:
    """Create a synthetic knowledge corpus with one planted issue per section."""
    corpus = root / "corpus"
    for sub in ("alpha", "beta", "proj", "archive", "secrets"):
        (corpus / sub).mkdir(parents=True)

    # (2a) exact duplicates: identical content, different locations
    #      (write_bytes so Windows newline translation cannot alter sizes)
    (corpus / "alpha" / "doc.md").write_bytes(DUP_TEXT.encode("utf-8"))
    (corpus / "beta" / "doc.md").write_bytes(DUP_TEXT.encode("utf-8"))

    # (2b) near duplicates: one-word difference stays above the threshold;
    #      an unrelated file is the below-threshold negative control.
    (corpus / "alpha" / "near_a.md").write_text(NEAR_BASE, encoding="utf-8")
    (corpus / "alpha" / "near_b.md").write_text(
        NEAR_BASE.replace("Friday", "Monday"), encoding="utf-8"
    )
    (corpus / "alpha" / "unrelated.md").write_text(
        "Completely other topic: quantum knitting patterns and yarn tension.\n" * 6,
        encoding="utf-8",
    )

    # (3) identity collision: distinct raw titles, same normalized title
    (corpus / "proj" / "Setup Guide.md").write_text(
        "# Setup guide v2\ncontainer-based steps", encoding="utf-8"
    )
    (corpus / "beta" / "setup_guide.md").write_text(
        "legacy bare-metal setup notes", encoding="utf-8"
    )

    # (4) conflicting candidates: same stem, different content hashes
    (corpus / "proj" / "report.md").write_text(
        "# Report\nfresh quarterly numbers: 42", encoding="utf-8"
    )
    (corpus / "archive" / "report.md").write_text(
        "# Report\nstale draft from last year", encoding="utf-8"
    )

    # (5) stale references: two broken targets, one healthy control
    (corpus / "alpha" / "real.md").write_text("link target that exists", encoding="utf-8")
    (corpus / "alpha" / "links.md").write_text(
        "[ghost](./missing.md)\n\n"
        "[healthy](./real.md)\n\n"
        "[orphan-ref]: ./also_missing.md\n",
        encoding="utf-8",
    )

    # (6) unresolved dates: impossible calendar dates planted; valid controls
    (corpus / "alpha" / "diary.md").write_text(
        "---\n"
        "created: 2026-02-30\n"
        "updated: 2026-08-23\n"
        "---\n\n"
        "On 2026-13-05 something happened.\n"
        "Earlier entry dated 2025-11-30 was fine.\n",
        encoding="utf-8",
    )

    # (7) sensitive exposure: filename rules + a content pattern whose VALUE
    #     must never appear anywhere in the report.
    (corpus / "secrets" / "api_key.txt").write_text("placeholder", encoding="utf-8")
    (corpus / ".env").write_text("PLACEHOLDER_ONLY=1\n", encoding="utf-8")
    (corpus / "secrets" / "creds.md").write_text(
        "config uses password: hunter2 today\n", encoding="utf-8"
    )

    # excluded directory: must be invisible to every section
    junk = corpus / "node_modules" / "pkg"
    junk.mkdir(parents=True)
    (junk / "junk.md").write_text("never scanned", encoding="utf-8")

    return corpus


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    return build_corpus(tmp_path)


@pytest.fixture
def report(corpus: Path) -> HealthReport:
    return scan(corpus)


# ---------------------------------------------------------------- empty tree


def test_empty_directory_is_healthy_zero(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    rep = scan(empty)
    assert rep.sources["discovered_files"] == 0
    assert rep.sources["by_extension"] == {}
    assert rep.duplicates["exact_duplicate_clusters"] == []
    assert rep.duplicates["near_duplicate_pairs"] == []
    assert rep.identity_collisions["collisions"] == []
    assert rep.conflicting_candidates["groups"] == []
    assert rep.stale_references["stale"] == []
    assert rep.unresolved_dates["unresolved"] == []
    assert rep.sensitive_exposure["findings"] == []
    assert rep.projection_readiness["discovered_files"] == 0
    assert rep.projection_readiness["markdown_file_ratio"] == 0.0
    assert rep.estimated_compile_work["markdown_bytes"] == 0
    assert rep.estimated_compile_work["estimated_tokens"] == 0


# ------------------------------------------------------------ (1) inventory


def test_inventory_counts_by_extension_and_skips_excluded_dirs(report) -> None:
    src = report.sources
    # 13 planted .md files + 1 .txt + 1 dotfile ".env"; node_modules ignored
    assert src["by_extension"][".md"] == 13
    assert src["by_extension"][".txt"] == 1
    assert src["by_extension"][".env"] == 1
    assert src["discovered_files"] == 15
    assert src["artifact_count"] == 15
    dumped = json.dumps(src)
    assert "node_modules/pkg/junk.md" not in dumped


# ------------------------------------------------------- (2) duplicate scan


def test_exact_duplicates_clustered_by_sha256(report) -> None:
    clusters = report.duplicates["exact_duplicate_clusters"]
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["digest"].startswith("sha256:")
    assert set(cluster["paths"]) == {"alpha/doc.md", "beta/doc.md"}
    assert cluster["size_bytes"] == len(DUP_TEXT.encode("utf-8"))


def test_near_duplicate_pair_above_threshold_and_control_below(report) -> None:
    dups = report.duplicates
    assert dups["threshold"] == pytest.approx(0.85)
    pair_paths = {
        (p["a"], p["b"]) if p["a"] < p["b"] else (p["b"], p["a"])
        for p in dups["near_duplicate_pairs"]
    }
    assert ("alpha/near_a.md", "alpha/near_b.md") in pair_paths
    for p in dups["near_duplicate_pairs"]:
        assert {p["a"], p["b"]} != {"alpha/near_a.md", "alpha/unrelated.md"}
        assert p["jaccard"] >= dups["threshold"]
    # the identical-copy pair surfaces here with a perfect score
    doc_pair = next(
        p
        for p in dups["near_duplicate_pairs"]
        if {p["a"], p["b"]} == {"alpha/doc.md", "beta/doc.md"}
    )
    assert doc_pair["jaccard"] == pytest.approx(1.0)
    near_pair = next(
        p
        for p in dups["near_duplicate_pairs"]
        if {p["a"], p["b"]} == {"alpha/near_a.md", "alpha/near_b.md"}
    )
    assert near_pair["jaccard"] >= dups["threshold"]


def test_near_duplicate_threshold_configurable(corpus) -> None:
    strict = scan(corpus, HealthScanConfig(near_duplicate_threshold=0.995))
    loose = scan(corpus, HealthScanConfig(near_duplicate_threshold=0.30))
    strict_pairs = strict.duplicates["near_duplicate_pairs"]
    loose_pairs = loose.duplicates["near_duplicate_pairs"]
    assert all(p["jaccard"] >= 0.995 for p in strict_pairs)
    assert len(loose_pairs) >= len(strict_pairs) > 0


# ------------------------------------------- (3)+(4) identity and conflicts


def test_identity_collision_on_normalized_titles(report) -> None:
    collisions = {
        c["normalized_title"]: c["paths"]
        for c in report.identity_collisions["collisions"]
    }
    assert set(collisions["setupguide"]) == {
        "proj/Setup Guide.md",
        "beta/setup_guide.md",
    }


def test_conflicting_candidates_same_stem_different_hash(report) -> None:
    groups = {g["stem"]: g for g in report.conflicting_candidates["groups"]}
    assert "report" in groups
    g = groups["report"]
    digests = {m["sha256"] for m in g["members"]}
    assert len(digests) == 2
    assert g["severity"] == "warn"
    # identical copies are duplicates, not conflicts: stem 'doc' must not fire
    assert "doc" not in groups


# ------------------------------------------------------ (5) stale references


def test_stale_relative_links_flagged_healthy_link_not(report) -> None:
    st = report.stale_references
    stale_targets = {s["target"] for s in st["stale"]}
    assert "./missing.md" in stale_targets
    assert "./also_missing.md" in stale_targets
    assert "./real.md" not in stale_targets
    assert all(s["file"] == "alpha/links.md" for s in st["stale"])
    assert st["checked_links"] >= 3


# --------------------------------------------------------- (6) date parsing


def test_impossible_dates_flagged_valid_dates_silent(report) -> None:
    findings = report.unresolved_dates["unresolved"]
    tokens = {f["token"] for f in findings}
    contexts = {f["context"] for f in findings}
    assert "2026-02-30" in tokens
    assert "2026-13-05" in tokens
    assert "2026-08-23" not in tokens
    assert "2025-11-30" not in tokens
    assert contexts == {"frontmatter-field", "body-token"}
    assert all(f["file"] == "alpha/diary.md" for f in findings)


# ---------------------------------------------------- (7) sensitive exposure


def test_sensitive_findings_report_rules_only_never_values(report) -> None:
    sens = report.sensitive_exposure
    rules = {(f["path"], f["rule_id"]) for f in sens["findings"]}
    assert ("secrets/api_key.txt", "secret-named-file") in rules
    assert (".env", "dotenv-filename") in rules
    assert any(r == "credential-assignment-pattern" for _, r in rules)
    dumped = json.dumps(report.to_dict(), ensure_ascii=False)
    # the captured secret VALUE must never leak into the report
    assert "hunter2" not in dumped
    assert "PLACEHOLDER_ONLY" not in dumped
    assert "values are never captured" in sens["policy"]


# ------------------------------------------------------- (8)+(9) projections


def test_projection_readiness_ratios(report) -> None:
    pr = report.projection_readiness
    assert pr["markdown_files"] == 13
    assert pr["markdown_with_frontmatter"] == 1  # only diary.md
    assert 0.0 <= pr["frontmatter_rate_among_markdown"] <= 1.0
    assert pr["markdown_file_ratio"] == pytest.approx(13 / 15)


def test_estimate_tracks_bytes_per_token_coefficient(corpus) -> None:
    base = scan(corpus).estimated_compile_work
    fast = scan(corpus, HealthScanConfig(bytes_per_token=7.2)).estimated_compile_work
    assert base["estimated_tokens"] > 0
    assert base["coefficients"]["bytes_per_token"] == pytest.approx(3.6)
    assert base["coefficients"]["chunk_target_tokens"] == 800
    assert base["estimated_compile_calls"] == base["estimated_chunks"]
    assert fast["estimated_tokens"] == pytest.approx(base["estimated_tokens"] / 2, rel=0.01)


# ------------------------------------------------------------------ policy


def test_every_section_is_heuristic_labeled(report) -> None:
    for name in SECTION_NAMES:
        section = getattr(report, name)
        assert section["label"] == "heuristic", f"{name} missing heuristic label"
    assert "no network" in report.label_policy


def test_package_has_no_network_imports() -> None:
    banned = re.compile(
        r"^\s*(?:from|import)\s+(requests|httpx|urllib|socket|aiohttp|ftplib|smtplib|telnetlib|xmlrpc)\b",
        re.MULTILINE,
    )
    for py in sorted((SRC_DIR / "akc_health_scan").rglob("*.py")):
        assert not banned.search(py.read_text(encoding="utf-8")), py.name


# ---------------------------------------------------------------------- CLI


def _cli_env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{existing}" if existing else str(SRC_DIR)
    return env


def test_cli_writes_json_report(corpus, tmp_path: Path) -> None:
    out = tmp_path / "health.json"
    proc = subprocess.run(  # noqa: S603 - fixed interpreter, test-authored argv
        [sys.executable, "-m", "akc_health_scan", str(corpus), "--json", str(out)],
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    for name in SECTION_NAMES:
        assert name in data
        assert data[name]["label"] == "heuristic"
    assert data["engine"] == "akc-health-scan"


def test_cli_rejects_missing_path(tmp_path: Path) -> None:
    proc = subprocess.run(  # noqa: S603 - fixed interpreter, test-authored argv
        [sys.executable, "-m", "akc_health_scan", str(tmp_path / "nope")],
        env=_cli_env(),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
