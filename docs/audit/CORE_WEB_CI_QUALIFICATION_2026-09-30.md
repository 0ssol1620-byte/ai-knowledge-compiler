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

## Visual qualification correction

The initial restored configuration selected archived FOLYNTA screenshots from
August 3 and a 1440 viewport. Actual screenshots and Git history identify these
as superseded by the current TAVONEL design and snapshots refreshed in commit
3a4319d on August 30. The current snapshots use the default Playwright location
and Desktop Chrome 1280 by 720 viewport. Correcting those two configuration
choices makes all 11 Windows visual tests pass without changing any screenshot,
assertion, threshold or product rendering.

Fresh production demo captures at widths 1920, 1440, 1280, 1024, 768, 390 and 360
returned HTTP 200, one primary heading, no horizontal overflow and no browser
exceptions. Evidence lives outside Git in task-3/core-visual-qualification.
This classifies the large marketing failure as stale test configuration.

Current TAVONEL snapshots are Windows-only. Linux CI still needs reviewable
current Linux reference captures; archived FOLYNTA Linux snapshots cannot prove
acceptance. Missing snapshots remain a failing gate. No blanket update was made.
Firefox, WebKit, Lighthouse and rebuilt image scan acceptance remain outstanding.
No push, deploy, visibility, credential or billing changes were made.
