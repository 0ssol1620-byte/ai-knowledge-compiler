# Known unpatchable npm advisories — 2026-08-23

`pnpm audit` reports three high-severity advisories whose "patched" versions do
not exist on the npm registry as of this date. They cannot be fixed by an
override without pinning a version that was never published:

| Package | Advisory range | Registry latest | Claimed patch |
| --- | --- | --- | --- |
| `extract-zip` | <= 2.0.1 | **2.0.1** (no newer release) | >= 2.0.2 |
| `image-size` | <= 2.0.2 | **2.0.2** (no newer release) | >= 2.0.3 |

## Exposure assessment

- `extract-zip@2.0.1` arrives only through `playwright-core > @puppeteer/browsers`
  — a dev/test dependency used by the E2E suite, not shipped to production
  bundles (`apps/web` build output contains no `extract-zip`).
- `image-size` arrives through build-time tooling paths; same reasoning applies.
- Neither is reachable from runtime request handling.

## Disposition

1. Keep `pnpm-workspace.yaml` overrides for `nanoid ^3.3.18` and `uuid ^11.1.1`
   (both applied successfully; their advisories are closed).
2. Re-run `pnpm audit` after any dependency bump — the moment patched releases
   appear on the registry, drop them in via the same override mechanism.
3. If either package becomes runtime-reachable before a patch ships, escalate
   to the founder: that changes the exposure assessment above.

This note exists so the audit findings are on the record with their real fix
status instead of silently red or silently ignored (project evidence rule).
