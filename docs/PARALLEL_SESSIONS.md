# Working in parallel without colliding

Two sessions are on this repository at once: one on the web and design surface,
one on the backend and the real benchmark runs. Neither can see the other's
working tree. This is what keeps that from turning into a bad merge.

## The hazard that is not a merge conflict

Git is good at telling you when two branches edited the same lines. The two
worst collisions here are ones it will merge silently.

**Alembic heads.** Revisions form a chain through `down_revision`. If both
branches add a revision off `0023_trial_ingest`, git sees two new files that
touch none of each other's lines and merges them without a word. Alembic then
refuses every `upgrade head` because "head" is ambiguous, and the fix is a
hand-written merge revision at the worst possible moment.

`scripts/check_migration_chain.py` runs in CI on every branch and fails the
moment a second head exists, naming the parent both revisions claimed. Before
writing a migration, run it:

```
python -m uv run --extra dev python scripts/check_migration_chain.py
```

**Lockfiles.** `uv.lock` and `pnpm-lock.yaml` conflict as one enormous hunk that
cannot be resolved by reading it. Whoever rebases second regenerates rather than
merges: `uv lock` / `pnpm install --lockfile-only`, then re-run the checks.

## Who owns what

Ownership is about who edits a path, not who may read it.

```
apps/web/           design session
design-system/

services/           backend session
workers/
packages/           (except contracts, below)
migrations/
benchmark/
infra/

packages/contracts/openapi/   shared — see below
uv.lock  pnpm-lock.yaml       shared — regenerate, never merge
pyproject.toml                shared — additive edits only
.github/workflows/            shared — additive steps only
```

The one crossing already in flight is PR #34, which is a backend feature
(anonymous trial ingest) written from the design session. It touches
`services/api/src/akc_api/main.py`, and the touch is not small: the ADR-004
quarantine pipeline moved into `quarantine_screening.py` so the trial route and
the authenticated route run the same checks. **If the backend session has edits
in `complete_upload`, that is the one place to expect a real conflict.** It is
also the reason for the merge order below.

## Merge order

1. **#33 and #34 land in `main` first.** Both are green and reviewed, and every
   hour they wait, the rebase gets worse. #34 in particular carries the
   `main.py` refactor and migration `0023`; landing it makes both a fixed point
   rather than a moving one.
2. **The backend session rebases onto `main` once.** One well-defined rebase
   against a known base beats an open-ended divergence.
3. **After that, ownership above holds** and rebases stay small.

## The OpenAPI contract

`packages/contracts/openapi/openapi-v1.json` is a frozen baseline, not a
generated file. `scripts/check_openapi_compat.py` fails on a breaking change.

Do not regenerate it wholesale. Re-serialising reflows keys that nobody touched
and turns an additive change into a hundred-line diff — this happened once
already. Insert the new paths and schema properties as text, keep the file's
existing formatting (short arrays stay on one line), and confirm the diff is
additive before committing.

## Benchmark results reaching the website

One file, regenerated upstream, committed here verbatim:

```
apps/web/src/data/claims/public-claims-pack.json
```

Its human-readable twin lives at `docs/claims/PUBLIC_CLAIMS_2026-08-08.md`. The
site reads only the JSON.

**Numbers are never edited in that file.** To change one, regenerate the
receipt that produced it and hand over a new pack. `verify-claims.mjs` checks
`claim_count` and `counts_by_status` against the array, so a hand-edit that
adjusts a figure without regenerating shows up as a mismatch.

### The rules are enforced, not reviewed

The pack ships more than numbers. Nearly every claim carries a `must_say`, and
several carry `forbidden` phrasings. Those are the difference between a
defensible figure and a misleading one, and they are the part most likely to be
lost when someone writes a headline quickly. Two mechanisms hold them:

```
verify-claims.mjs   forbidden phrasings and withheld figures, scanned across
  (CI, per branch)  the web source. Fails the build.

lib/claims.ts       claimFigure() returns the numbers and the mandatory
  (structural)      context in one object, so a component takes both.
                    Dropping the sentence takes deliberate effort rather than
                    forgetfulness. It throws outright for a withheld claim.
```

`benchmark-public.test.ts` pins the specifics that matter most: the low-quality
scan row stays in the document-type table (removing it is forbidden), the 99.98%
completion rate never appears in an accuracy table (calling it accuracy is
forbidden), and the 80.6% check pass rate is kept away from the 94.2% character
match unless both are labelled.

### When the next pack arrives

Replace the JSON, run `pnpm --filter @akc/web claims:check` and
`pnpm --filter @akc/web test -- benchmark-public`, and read the diff of
`counts_by_status`. A claim moving from `withheld` to `approved` is the
interesting case: `quality-retry-improvement` unblocks when the retry and
no-regression gate finish, and at that point its numbers may be published for
the first time.

The older `apps/web/src/data/benchmark-public-snapshot.json` still types the
`/benchmarks` dataset view. It was the earlier contract and was never filled;
the claims pack supersedes it for anything the marketing surface states.

## Before pushing, either session

```
python -m uv run --extra dev python scripts/check_migration_chain.py
python -m uv run --extra dev python scripts/check_openapi_compat.py
pnpm --filter @akc/web blueprint:check
pnpm --filter @akc/web claims:check
```

The first two are the silent-failure guards. The third holds the design layer
to the masterplan's `[확정]` items and ratchets the legacy sheets; it is listed
here because a backend change that adds CSS will trip it, and the fix is to
follow §7.3 and §20 rather than to raise the baseline.
