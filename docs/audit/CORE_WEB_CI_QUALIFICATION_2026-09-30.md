# Core web CI qualification — 2026-09-30

## Scope

Restored real `storybook:build`, `test:e2e:visual`, `test:e2e:matrix`, and
`start:e2e:standalone` package entry points already required by CI/configuration.
The visual config compares the existing platform-specific approved baselines at
1440 × 900 against a production demo build. It never updates snapshots.
Visual artifacts use a separate output directory to survive the matrix run.

Pinned Next.js and its ESLint config to 16.3.3; upgraded the existing workspace
sharp override to 0.35.4 and regenerated the pnpm lockfile through pnpm 11.9.0.
The old override would otherwise force Next's optional sharp dependency back to
the vulnerable version. No Dockerfile or operating-system package changes here.

Generated `storybook-static` output is excluded from ESLint. The new Next rule
has one documented exception for locale route-handler navigation: it must set
the locale cookie and perform a document redirect so server components rerender.
There is no blanket lint or security suppression.

## Advisory evidence

The npm registry security advisory bulk endpoint, queried with the old versions,
reported:

- [GHSA-p293-qw3h-jr36](https://github.com/advisories/GHSA-p293-qw3h-jr36):
  critical Windows-hosted unauthenticated RCE; Next >=16.0.0 <16.3.3.
- [GHSA-2xp9-vwfh-vxw4](https://github.com/advisories/GHSA-2xp9-vwfh-vxw4):
  critical AVIF image optimization unauthenticated RCE; same Next range.
- [GHSA-rgj7-g3m4-5g8c](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c):
  high sharp/libheif issues; sharp <0.35.4.

After the update, `pnpm audit --prod --json` reports zero vulnerabilities.
This is dependency advisory evidence, not a replacement for an image Trivy scan.

## Local acceptance

Windows, Node 22.14.0, pnpm 11.9.0, synthetic demo data only:

- Frozen lockfile installation: passed.
- Web ESLint and TypeScript: passed.
- Web unit suite: 67 files / 383 tests passed (334 seconds).
- Contracts test (TypeScript contract check): passed.
- Storybook production build: passed (5053 modules); existing bundle size and
  ignored `use client` directive warnings remain informational.
- Next 16.3.3 production build: passed both default and exact CI demo environment.
- Interaction, blueprint, claims checks: passed; existing interaction advisory
  lists 110 disabled controls without availability text, zero blocking findings.
- Visual discovery: 11 actual screenshot tests. Matrix discovery: nine browser
  and viewport projects.
- Real Chromium 1440 production demo browser matrix: passed.
- Prettier and whitespace checks: passed.

## Remaining acceptance blocker

The restored real marketing-home visual check fails against the committed
Windows baseline even with the correct production demo configuration:
expected 1440 × 7791, received 1440 × 16317; approximately 50% pixel difference.
The test gate is functioning and snapshots/assertions are unchanged. A UI owner
must inspect the approved design/baseline versus current rendering before either
changing the product or approving a new baseline. No full visual, Firefox,
WebKit, Lighthouse, or Linux image scan pass is claimed by this slice.

Local failure evidence is under `apps/web/test-results/visual/` (actual, diff,
error context, trace), ignored by Git. Full hosted CI remains integration-owner
work; no push, deploy, visibility, credential, or billing changes were made.
