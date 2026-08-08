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

This is a one-file interface and it already exists. The benchmark session writes
exactly one file:

```
apps/web/src/data/benchmark-public-snapshot.json
```

Nothing else. No React, no TSX, no component in `apps/web/src/components/`. The
site derives everything it shows from that file:

- `apps/web/src/lib/benchmark-public.ts` types it and formats it
- `homepageMetricRows()` builds the homepage metric table from it
- `/benchmarks` renders the datasets from it

The schema is `PublicBenchmarkSnapshot` in `benchmark-public.ts`. Its shape
matters in one respect above the rest:

**Every metric is `number | null`, and `null` means "not measured".** A metric
left null renders as `Not measured` with the reason it is missing. A metric with
a value renders as a percentage *and the corpus it came from* — the label and
document count travel with the figure, because §25.7 keeps unattributed numbers
off this page. Publishing a result is therefore filling in a field, and
withdrawing one is setting it back to null. Neither requires touching code.

`apps/web/src/lib/benchmark-public.test.ts` pins both directions: empty snapshot
stays at "Not measured", filled snapshot reports the value with its citation,
and a partially covered run reports only what it covered. Run it before handing
a snapshot over:

```
pnpm --filter @akc/web test -- benchmark-public
```

The rows also carry `evidence.score_records_sha256` and
`corpus_manifest_sha256`. `/benchmarks` shows them. They are the difference
between a benchmark and a claim, so a snapshot with metrics and empty digests
should not ship.

## Before pushing, either session

```
python -m uv run --extra dev python scripts/check_migration_chain.py
python -m uv run --extra dev python scripts/check_openapi_compat.py
pnpm --filter @akc/web blueprint:check
```

The first two are the silent-failure guards. The third holds the design layer
to the masterplan's `[확정]` items and ratchets the legacy sheets; it is listed
here because a backend change that adds CSS will trip it, and the fix is to
follow §7.3 and §20 rather than to raise the baseline.
