"""Keep RED-family claim-level analysis out of version control.

Detailed claim-level analysis of a RED-classified patent family is prepared for
external counsel, not kept as repository content. `docs/ip/.gitignore` handles
the path half of that with a fail-closed allowlist. This script handles the
half a path rule cannot see: claim-level text inside a file that is *allowed*
to be tracked.

That failure mode is not hypothetical. The technology intake register — an
allowlisted file, and correctly so — carried

    claim 1 recites latency/precision/recall rather than confidence, and the
    "if not met" conditional is claim 4

in its `note:` field, and it reached history at c8de965 because no control was
looking inside allowlisted files. This one is.

WHAT COUNTS AS A VIOLATION

  1. A tracked or staged path under docs/ip/ that the allowlist does not name.
  2. Any PRIVILEGED:BEGIN block in tracked or staged content — those blocks are
     the extraction unit for the counsel packet and belong outside the repo.
  3. Claim-level language within WINDOW lines of a RED patent identifier. The
     window matters: the register's note never repeats the patent number, it
     sits four lines under the `reference:` field that does. A same-line rule
     would have missed exactly the case that motivated the script.

WHAT IS DELIBERATELY NOT A VIOLATION

  Naming a RED family, its status, and the design-around gate. That is the
  register's job and the founder instruction names it as permitted content.
  "claim chart" as the *name of a document* is likewise fine — several research
  files refer to the artifact without characterising anybody's claims.

  This distinction is why rule 3 pairs a patent identifier with claim-level
  language rather than flagging either alone. Flagging the identifier alone
  would condemn the register; flagging the language alone would condemn every
  file that mentions the phrase "claim chart".

USAGE

    python scripts/ip_privilege_guard.py              # whole tracked tree
    python scripts/ip_privilege_guard.py --staged     # pre-commit
    python scripts/ip_privilege_guard.py --history    # every commit, for a receipt

Exit 0 clean, 1 on violation. --history exits 0 even when it finds something:
history is a report, not a gate. Rewriting it is a founder decision and this
script never takes it.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _resolve_repo_root() -> Path:
    """The tree being committed, not the tree this file happens to live in.

    A copy of this script is installed into the git common directory so the hook
    still works on a branch that predates it. That copy sits outside every
    worktree, so its own location identifies nothing -- and deriving the root
    from ``__file__`` would make a commit in a linked worktree get checked
    against the MAIN worktree's index. The hook would pass, on the wrong tree,
    silently. Ask git where we are instead; hooks run at the worktree top level.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607 - git from PATH
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
        )
        top = proc.stdout.strip()
        if top:
            return Path(top)
    except (subprocess.CalledProcessError, OSError):
        pass
    return Path(__file__).resolve().parents[1]


REPO_ROOT = _resolve_repo_root()

#: Tracked content is permitted under docs/ip/ only for these. Kept in step with
#: docs/ip/.gitignore; test_ip_privilege_guard.py asserts the two agree, because
#: two lists that drift apart are worse than one list.
ALLOWLIST = frozenset(
    {
        "docs/ip/.gitignore",
        "docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml",
        "docs/ip/V4_DISCLOSURE_REGISTRY.yaml",
    }
)

#: Files whose subject *is* the boundary. They quote the forbidden shapes in
#: order to forbid them, so scanning them reports the guard on itself.
SELF_REFERENTIAL = frozenset(
    {
        "docs/ip/.gitignore",
        "scripts/ip_privilege_guard.py",
        "tests/security/test_ip_privilege_guard.py",
        ".githooks/pre-commit",
    }
)

#: A RED family is identified by patent number where it has one. The generic
#: `US\d{7,8}B\d` form catches a number nobody has classified yet -- a new RED
#: reference is a violation before the register learns about it, not after.
PATENT_REF = re.compile(r"\bUS\s?\d{7,8}\s?[AB]\d?\b")

#: Claim-level language: characterising what a claim covers, or whether
#: something falls inside it.
#:
#: A claim NUMBER is the bright line. "Avoid the sequential-inference shape" is
#: a design-around gate and carries no claim-level information; "claim 1 recites
#: latency/precision/recall" is an analysis of somebody's claim scope. The
#: founder instruction permits the first and excludes the second, and the claim
#: number is what separates them reliably enough to automate.
CLAIM_LEVEL = re.compile(
    r"""
      \bclaims?\s+\d+                # claim 1, claims 5-7
    | \breads?\s+onto\b
    | \binfring
    | \banticipat
    | \bdoctrine\s+of\s+equivalents\b
    | \bliteral\s+infringement\b
    | \belement[- ]by[- ]element\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: "reads onto" is dual-use and the ambiguity is not resolvable from the phrase
#: alone. As a *conclusion* -- "our router reads onto US11605028B2" -- it is
#: exactly what must not be committed. As a *prohibition* -- "avoid expressions
#: that read onto it" -- it is the design-around gate the founder instruction
#: requires source control to keep. Prohibitive framing on the same line excuses
#: it, and nothing else.
#:
#: This excuse is deliberately narrow. It never applies to a claim number, to
#: infringement or to anticipation: no design-around instruction needs to recite
#: which claim it is designing around, so a claim number in a "do not" sentence
#: is still claim-level analysis wearing a prohibition.
EXCUSABLE = re.compile(r"\breads?\s+onto\b", re.IGNORECASE)
PROHIBITIVE_FRAMING = re.compile(
    r"\b(avoid|avoids|avoiding|must\s+not|do\s+not|does\s+not|don't|never|"
    r"shall\s+not|design[-\s]around|no\s+expression)\b",
    re.IGNORECASE,
)

PRIVILEGED_BLOCK = re.compile(r"PRIVILEGED:BEGIN")

#: POSIX ERE equivalents, for `git grep -E`, which is not Python's engine: it has
#: no \b, \s or \d. Handing it PATENT_REF.pattern matches nothing and the history
#: scan then reports "clean" -- a false negative indistinguishable from a pass,
#: which is the worst failure a control of this kind can have. These are
#: deliberately broader than the Python patterns; over-matching only costs a few
#: `git show` calls, and the Python rule makes the actual decision.
ERE_PREFILTER = ("US ?[0-9]{7,8} ?[AB]?[0-9]?", "PRIVILEGED:BEGIN")

#: Lines either side of a patent identifier that claim-level language is read
#: as attaching to. Sized from the register's own YAML block: `reference:` and
#: the `note:` it belongs to sat four lines apart.
WINDOW = 12

BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".woff", ".woff2", ".zip", ".ico", ".svg"}
)


class Violation:
    __slots__ = ("detail", "line", "path", "rule")

    def __init__(self, path: str, line: int, rule: str, detail: str) -> None:
        self.path = path
        self.line = line
        self.rule = rule
        self.detail = detail

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"  {where}\n      [{self.rule}] {self.detail}"


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Always decode git output as UTF-8.

    `text=True` decodes with the locale encoding. On a Windows console that is
    cp949 here, and the first em dash in a document raises UnicodeDecodeError
    inside subprocess's reader thread -- where it does not propagate as a normal
    exception, so the call returns empty and the scan reports clean on content
    it never read. Repository content is UTF-8 regardless of console locale, so
    it is named explicitly; `replace` keeps a stray byte from blinding the scan
    rather than merely inconveniencing it.
    """
    return subprocess.run(  # noqa: S603 - argument list is built here, never from repo content
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def _git(*args: str) -> str:
    return _run(["git", *args]).stdout


def _scannable(path: str) -> bool:
    return Path(path).suffix.lower() not in BINARY_SUFFIXES


def check_paths(paths: list[str]) -> list[Violation]:
    out = []
    for p in paths:
        if p.startswith("docs/ip/") and p not in ALLOWLIST:
            out.append(
                Violation(
                    p,
                    0,
                    "path",
                    "under docs/ip/ and not allowlisted -- privileged by default",
                )
            )
    return out


def check_content(path: str, text: str) -> list[Violation]:
    if path in SELF_REFERENTIAL:
        return []

    lines = text.splitlines()
    out = []

    for i, line in enumerate(lines, 1):
        if PRIVILEGED_BLOCK.search(line):
            out.append(
                Violation(path, i, "privileged-block", "PRIVILEGED:BEGIN in tracked content")
            )

    patent_lines = [i for i, line in enumerate(lines) if PATENT_REF.search(line)]
    if not patent_lines:
        return out

    for i, line in enumerate(lines):
        excused_here = PROHIBITIVE_FRAMING.search(line) is not None
        # Every match on the line, not the first: "do not write anything that
        # reads onto claim 1" opens with an excusable phrase and closes with a
        # claim number. Stopping at the first match excuses the whole line and
        # lets the claim number through -- which is how a rule meant to protect
        # design-around wording turns into a way to smuggle analysis past it.
        for m in CLAIM_LEVEL.finditer(line):
            phrase = m.group(0).strip()
            if excused_here and EXCUSABLE.fullmatch(phrase):
                continue
            near = next((p for p in patent_lines if abs(p - i) <= WINDOW), None)
            if near is None:
                continue
            out.append(
                Violation(
                    path,
                    i + 1,
                    "claim-level",
                    f'"{phrase}" within {WINDOW} lines of the patent '
                    f"reference on line {near + 1} -- counsel packet, not the repository",
                )
            )
    return out


def scan_worktree() -> list[Violation]:
    paths = [p for p in _git("ls-files").splitlines() if p]
    violations = check_paths(paths)
    for p in paths:
        if not _scannable(p):
            continue
        f = REPO_ROOT / p
        try:
            violations += check_content(p, f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return violations


def scan_staged() -> list[Violation]:
    paths = [
        p for p in _git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p
    ]
    violations = check_paths(paths)
    for p in paths:
        if not _scannable(p):
            continue
        blob = _git("show", f":{p}")
        if blob:
            violations += check_content(p, blob)
    return violations


def scan_history() -> list[Violation]:
    """Report, never gate. Rewriting history is a founder decision.

    Reading every blob of every commit is 167 x 1,801 subprocess calls here and
    finishes some time next week. `git grep` searches across revisions natively,
    so it narrows the field to the handful of (commit, path) pairs that mention
    a patent identifier at all, and only those get the windowed rule applied.
    Same answer, three orders of magnitude fewer processes.
    """
    revs = [r for r in _git("rev-list", "--all").splitlines() if r]
    if not revs:
        return []

    violations: list[Violation] = []

    # Paths that were ever added under docs/ip/ -- the path rule, over history.
    ever_added = {
        p
        for p in _git(
            "log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A", "--", "docs/ip/"
        ).splitlines()
        if p.strip()
    }
    for p in sorted(ever_added - set(ALLOWLIST)):
        violations.append(Violation(p, 0, "path", "was tracked at some point under docs/ip/"))

    # Candidate blobs: anything mentioning a patent identifier, plus any
    # privileged block, anywhere in history.
    candidates: set[tuple[str, str]] = set()
    for pattern in ERE_PREFILTER:
        proc = _run(["git", "grep", "-l", "-I", "-E", pattern, *revs])
        # 0 = matched, 1 = no match, anything else = git could not run the
        # search. Treating an error as "no match" is how a broken pattern turns
        # into a clean bill of health, so it stops the scan instead.
        if proc.returncode > 1:
            raise RuntimeError(
                f"git grep failed on prefilter {pattern!r} (exit {proc.returncode}): "
                f"{proc.stderr.strip()}"
            )
        for line in proc.stdout.splitlines():
            rev, _, path = line.partition(":")
            if path and _scannable(path):
                candidates.add((rev, path))

    for rev, path in sorted(candidates):
        blob = _git("show", f"{rev}:{path}")
        if not blob:
            continue
        for v in check_content(path, blob):
            violations.append(Violation(f"{rev[:9]}:{v.path}", v.line, v.rule, v.detail))

    return violations


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="scan the index (pre-commit)")
    mode.add_argument("--history", action="store_true", help="scan every commit; reports only")
    args = ap.parse_args()

    if args.history:
        found = scan_history()
        if found:
            print(f"IP privilege guard -- {len(found)} occurrence(s) in history:\n")
            for v in found:
                print(v)
            print(
                "\nReported, not blocked. History is not rewritten without a founder\n"
                "decision; the receipt records what is there."
            )
        else:
            print("IP privilege guard -- history clean.")
        return 0

    found = scan_staged() if args.staged else scan_worktree()
    if not found:
        print("IP privilege guard -- clean.")
        return 0

    scope = "staged" if args.staged else "tracked"
    print(f"IP privilege guard -- {len(found)} violation(s) in {scope} content:\n")
    for v in found:
        print(v)
    print(
        "\nRED-family claim-level analysis does not enter version control.\n"
        "Extract it with research/scripts/export_privileged_packet.py and keep the\n"
        "packet outside the repository. Source-controlled documents carry the\n"
        "register ID, the status and the design-around gate -- nothing further."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
