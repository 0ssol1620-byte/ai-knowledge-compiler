# Lint scope — what "lint clean" has meant, and what it has not

`ruff check` has been run this programme on the files each change touched. P20
and P21 both came from widening it once. Widening it to `tools/` and
`research/experiments/` together reports **17 errors**, none of them in any file
created or modified this session.

## Classification, with the evidence for each

**Two are attributable, by git.** These files are tracked and unmodified in the
working tree, so they carry these errors from before this session:

| file | rule |
|---|---|
| `tools/fonts/build_fonts.py` | `F401` `re` imported but unused |
| `tools/release/test_render_folynta_portable_report.py` | `S603` subprocess call |

**Fifteen are unattributable.** They live in files git reports as **untracked** —
`research/experiments/H1-STAGE1-200/`, `research/experiments/DIAG-B-01/scripts/`,
`tools/ci/check_promotion_gate_contract.py`. An untracked file has no prior
revision, so nothing in this repository distinguishes "arrived with these errors"
from "acquired them later". They are recorded as **UNATTRIBUTED**, and the word
*pre-existing* is not used for them — the standing rule is that the word requires
git or history evidence, and here there is none to have.

Rules involved: `E501` line length (9), `S112` try/except/continue (2), `SIM102`
nested if (1), `SIM300` Yoda condition (2), `RUF100` unused noqa (1).

## Not repaired in this session, deliberately

Four are `--fix`-able and all are cosmetic. They were not applied because a
full-repository scope measurement was executing at the time, and editing the tree
mid-run produces a receipt that describes a state that never existed. A ruff
autofix on `research/experiments/H1-STAGE1-200/tests/test_controlplane_contract.py`
earlier this session is why the full suite was re-measured rather than reusing an
earlier count.

## What this bounds

Any statement that this repository is "lint clean" is scoped to the files a
change touched, and has never meant `tools/` and `research/experiments/` as a
whole. That is a scope, not a defect, and it is written down here so the scope is
not silently widened by a reader.
