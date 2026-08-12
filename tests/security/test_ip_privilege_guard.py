"""The commit block on RED-family claim-level analysis, tested by trying to break it.

Two controls are under test and they fail in different ways, so both are
exercised separately and both get a positive control:

  docs/ip/.gitignore   -- fail-closed allowlist. Stops `git add -A`.
  the pre-commit hook  -- runs scripts/ip_privilege_guard.py over the index.
                          Stops `git add -f`, and stops claim-level text inside
                          a file the allowlist permits.

WHY THE REAL `git add -A` RUNS IN A THROWAWAY REPOSITORY

  The obvious test -- `git add -A` in this repository, then look at the index --
  stages every uncommitted change in the working tree as a side effect. Agents
  work in these worktrees concurrently. A test that quietly stages somebody's
  half-finished work is a worse outcome than the bug it is checking for, so the
  destructive form runs against a repository built for the purpose, and the live
  tree is checked with `--dry-run`.

EVERY NEGATIVE TEST HERE HAS A POSITIVE CONTROL

  "The privileged file was not staged" is also what you observe when the file
  was never created, when git ignored the whole directory for an unrelated
  reason, or when the command silently failed. Each test therefore also proves
  the same setup DOES stage the file once the control is removed. Without that,
  the test passes on a repository where nothing works at all.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "ip_privilege_guard.py"
IP_GITIGNORE = REPO_ROOT / "docs" / "ip" / ".gitignore"
HOOK = REPO_ROOT / ".githooks" / "pre-commit"

#: Stand-in for a claim chart. Deliberately not a real analysis -- the test only
#: needs the shape that must never be committed.
PRIVILEGED_BODY = """\
# Claim chart -- Family A

<!-- PRIVILEGED:BEGIN id=A-RED-01 red=tech_ibm_sequential_inference -->
US11605028B2 claim 1 recites a comparison against a quality-of-service
threshold, and the accused arrangement reads onto it element-by-element.
<!-- PRIVILEGED:END id=A-RED-01 -->
"""

#: The failure the register actually had: claim-level text in an ALLOWLISTED
#: file, where no path rule can see it.
REGISTER_WITH_CLAIM_TEXT = """\
red:
  - id: tech_ibm_sequential_inference
    reference: "IBM US11605028B2"
    status: DESIGN_AROUND
    note: >-
      Our reading found claim 1 recites latency rather than confidence, and the
      conditional is claim 4.
"""

#: The same register written to the boundary: names the family, its status and
#: the design-around gate, and characterises nobody's claims.
REGISTER_REDACTED = """\
red:
  - id: tech_ibm_sequential_inference
    reference: "IBM US11605028B2"
    status: DESIGN_AROUND
    avoid: >-
      The broad sequential-inference shape. Avoid expressions that read onto it.
    note: >-
      The blueprint's summary understates the scope, so the design-around is
      drawn wider. The reading behind that belongs in the counsel packet.
"""


def git(*args: str, cwd: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed invocation, paths from tmp_path
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def staged_paths(cwd: Path) -> set[str]:
    out = git("diff", "--cached", "--name-only", cwd=cwd).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A repository carrying the same two controls, safe to run `git add -A` in."""
    repo = tmp_path / "sandbox"
    (repo / "docs" / "ip").mkdir(parents=True)
    (repo / "scripts").mkdir()

    git("init", "-q", cwd=repo)
    git("config", "user.email", "test@example.invalid", cwd=repo)
    git("config", "user.name", "guard test", cwd=repo)
    git("config", "commit.gpgsign", "false", cwd=repo)

    shutil.copy(IP_GITIGNORE, repo / "docs" / "ip" / ".gitignore")
    shutil.copy(GUARD, repo / "scripts" / "ip_privilege_guard.py")

    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    shutil.copy(HOOK, hooks / "pre-commit")
    (hooks / "pre-commit").chmod(0o755)

    (repo / "README.md").write_text("sandbox\n", encoding="utf-8")
    return repo


# ---------------------------------------------------------------------------
# The allowlist, against `git add -A`
# ---------------------------------------------------------------------------


def test_git_add_all_does_not_stage_a_claim_chart(sandbox: Path) -> None:
    chart = sandbox / "docs" / "ip" / "CLAIM_CHART_FAMILY_A.md"
    chart.write_text(PRIVILEGED_BODY, encoding="utf-8")

    git("add", "-A", cwd=sandbox)

    assert "docs/ip/CLAIM_CHART_FAMILY_A.md" not in staged_paths(sandbox)
    # and the command did something, so the absence above means the rule worked
    assert "README.md" in staged_paths(sandbox)


def test_the_allowlist_is_what_stops_it(sandbox: Path) -> None:
    """Positive control. Remove the rule and the same file stages."""
    (sandbox / "docs" / "ip" / ".gitignore").unlink()
    chart = sandbox / "docs" / "ip" / "CLAIM_CHART_FAMILY_A.md"
    chart.write_text(PRIVILEGED_BODY, encoding="utf-8")

    git("add", "-A", cwd=sandbox)

    assert "docs/ip/CLAIM_CHART_FAMILY_A.md" in staged_paths(sandbox)


def test_allowlist_is_fail_closed_for_a_file_nobody_anticipated(sandbox: Path) -> None:
    """A new privileged file is ignored by default -- the point of an allowlist."""
    (sandbox / "docs" / "ip" / "FREEDOM_TO_OPERATE_MEMO_2027.md").write_text(
        "anything at all\n", encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)
    assert not any(p.startswith("docs/ip/FREEDOM") for p in staged_paths(sandbox))


def test_the_two_registers_remain_trackable(sandbox: Path) -> None:
    """The allowlist must not block the documents that are meant to be public."""
    ip = sandbox / "docs" / "ip"
    (ip / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(REGISTER_REDACTED, encoding="utf-8")
    (ip / "V4_DISCLOSURE_REGISTRY.yaml").write_text("families: []\n", encoding="utf-8")

    git("add", "-A", cwd=sandbox)
    staged = staged_paths(sandbox)

    assert "docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml" in staged
    assert "docs/ip/V4_DISCLOSURE_REGISTRY.yaml" in staged
    assert "docs/ip/.gitignore" in staged


# ---------------------------------------------------------------------------
# The hook, against the two things the allowlist cannot see
# ---------------------------------------------------------------------------


def test_hook_blocks_a_force_added_claim_chart(sandbox: Path) -> None:
    chart = sandbox / "docs" / "ip" / "CLAIM_CHART_FAMILY_A.md"
    chart.write_text(PRIVILEGED_BODY, encoding="utf-8")

    git("add", "-f", "docs/ip/CLAIM_CHART_FAMILY_A.md", cwd=sandbox)
    assert "docs/ip/CLAIM_CHART_FAMILY_A.md" in staged_paths(sandbox)  # -f beat the allowlist

    result = git("commit", "-m", "should not land", cwd=sandbox, check=False)

    assert result.returncode != 0
    assert git("log", "--oneline", cwd=sandbox, check=False).returncode != 0  # no commits


def test_hook_blocks_claim_level_text_inside_an_allowlisted_file(sandbox: Path) -> None:
    """The register's own failure mode. No path rule can catch this one."""
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        REGISTER_WITH_CLAIM_TEXT, encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)

    result = git("commit", "-m", "register with claim numbers", cwd=sandbox, check=False)

    assert result.returncode != 0
    assert "claim 1" in (result.stdout + result.stderr)


def test_hook_permits_the_redacted_register(sandbox: Path) -> None:
    """Positive control for the hook: the boundary-compliant register commits."""
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        REGISTER_REDACTED, encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)

    result = git("commit", "-m", "redacted register", cwd=sandbox, check=False)

    assert result.returncode == 0, result.stdout + result.stderr


def test_hook_refuses_when_the_guard_is_missing(sandbox: Path) -> None:
    """Fail closed. A control that vanishes must not read as a pass."""
    (sandbox / "scripts" / "ip_privilege_guard.py").unlink()
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        REGISTER_REDACTED, encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)

    result = git("commit", "-m", "guard deleted", cwd=sandbox, check=False)

    assert result.returncode != 0
    assert "not found" in (result.stdout + result.stderr)


# ---------------------------------------------------------------------------
# The guard's own rules
# ---------------------------------------------------------------------------


def test_design_around_wording_is_not_a_violation() -> None:
    """The instruction to avoid a shape is exactly what source control keeps."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from ip_privilege_guard import check_content

    permitted = (
        'reference: "IBM US11605028B2"\n'
        "avoid: Avoid expressions that read onto the sequential-inference shape.\n"
        "rule: Family A must not read onto IBM US11605028B2's shape.\n"
    )
    assert check_content("docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml", permitted) == []


def test_a_claim_number_is_not_excused_by_prohibitive_framing() -> None:
    """The excuse covers "reads onto" only. A claim number never needs saying."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from ip_privilege_guard import check_content

    disguised = (
        'reference: "IBM US11605028B2"\n'
        "avoid: Do not write anything that reads onto claim 1 of that patent.\n"
    )
    found = check_content("docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml", disguised)
    assert [v.rule for v in found] == ["claim-level"]


def test_allowlist_matches_the_gitignore() -> None:
    """Two lists that drift apart are worse than one list."""
    import sys

    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from ip_privilege_guard import ALLOWLIST

    negations = {
        m.group(1)
        for m in re.finditer(
            r"^!(.+)$", IP_GITIGNORE.read_text(encoding="utf-8"), flags=re.MULTILINE
        )
    }
    assert {f"docs/ip/{n}" for n in negations} == set(ALLOWLIST)


def test_guard_inspects_the_tree_it_is_run_in_not_the_one_it_lives_in(
    sandbox: Path,
) -> None:
    """The installed copy sits in the git common dir, outside every worktree.

    Resolving the repository from ``__file__`` would make a commit in a linked
    worktree get checked against the main worktree's index -- a pass on the
    wrong tree, which is worse than a failure. Run the guard from elsewhere and
    it must still see the sandbox's violation.
    """
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        REGISTER_WITH_CLAIM_TEXT, encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)

    result = subprocess.run(  # noqa: S603 - the guard, run the way CI runs it
        ["python", str(GUARD), "--staged"],  # noqa: S607 - the interpreter from PATH
        cwd=sandbox,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "claim 1" in result.stdout


def test_staged_scan_reads_non_ascii_content(sandbox: Path) -> None:
    """`text=True` decodes with the locale encoding, and this content is UTF-8.

    Under cp949 the em dash below raises inside subprocess's reader thread,
    where it does not surface as an exception -- the call just returns nothing
    and the file reads as clean. Every fixture in this module was ASCII until
    this one, which is why the bug survived the first eleven tests.
    """
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        'reference: "IBM US11605028B2"\n'
        "note: >-\n"
        "  A dash — and a claim 1 recitation — in one UTF-8 document.\n",
        encoding="utf-8",
    )
    git("add", "-A", cwd=sandbox)

    result = subprocess.run(  # noqa: S603 - the guard, run the way CI runs it
        ["python", str(GUARD), "--staged"],  # noqa: S607 - the interpreter from PATH
        cwd=sandbox,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "claim 1" in result.stdout


def test_history_scan_finds_a_planted_commit(sandbox: Path) -> None:
    """Positive control for --history.

    The scan pre-filters with `git grep -E`, which is POSIX ERE and has no \\b,
    \\s or \\d. Handing it the Python pattern matched nothing and printed
    "history clean" over a repository that was not -- so the mode needs a test
    that fails when the pre-filter stops matching, not just one that passes on
    a clean history.
    """
    (sandbox / "docs" / "ip" / "TECHNOLOGY_INTAKE_REGISTER.yaml").write_text(
        REGISTER_WITH_CLAIM_TEXT, encoding="utf-8"
    )
    git("add", "-A", cwd=sandbox)
    git("commit", "-m", "planted", "--no-verify", cwd=sandbox)

    result = subprocess.run(  # noqa: S603 - the guard, run the way CI runs it
        ["python", str(GUARD), "--history"],  # noqa: S607 - the interpreter from PATH
        cwd=sandbox,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "history reports, never gates"
    assert "claim 1" in result.stdout
    assert "clean" not in result.stdout


def test_every_self_exemption_names_a_real_file() -> None:
    """An exemption list is a hole in the control, so it has to be exact.

    These four files quote the forbidden shapes in order to forbid them, so they
    are skipped. A path that no longer exists -- this list said `tests/ip/` while
    the test lived in `tests/security/` -- exempts nothing and scans a file that
    was meant to be exempt, or worse, silently exempts nothing at all while
    reading as protection.
    """
    from ip_privilege_guard import SELF_REFERENTIAL

    missing = sorted(p for p in SELF_REFERENTIAL if not (REPO_ROOT / p).exists())
    assert missing == []


def test_live_repository_is_clean() -> None:
    """The tracked tree, right now. This is the check CI runs."""
    result = subprocess.run(  # noqa: S603 - the guard, run the way CI runs it
        ["python", str(GUARD)],  # noqa: S607 - the interpreter from PATH
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
