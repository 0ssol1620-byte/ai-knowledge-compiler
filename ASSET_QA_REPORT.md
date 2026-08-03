# FOLYNTA v1 asset QA report

## Current verdict

**Local asset gate: PASS. Overall release gate: PRODUCTION-REJECT.**

The active v1 actual-source asset is the official DART JTC 2026 Q1 filing PDF:

- repository path: `apps/web/public/proof-sources/dart-jtc-2026-q1.pdf`
- source class: T0 public authority proof
- size: 2,276,931 bytes and 121 pages
- SHA-256: `fb998430db82774afc0d69090383650421ab9a14e6e37c7f32821aa1c6a32eee`
- rendered location: actual page 30 through PDF.js 6.2.108
- provenance receipt: `assets/public-proof/dart/source-evidence/jtc-2026q1-pdf-receipt.json`
- use boundary: public-fixture product demonstration only; never a benchmark,
  customer, accuracy, security, certification, or commercial-performance claim

`pnpm assets:validate` passes 12 manifest assets, 137 registered names, and 30
verified derivatives. No generated media is used by the v1 homepage.

## Historical v4 signature-scene review

The six signature scenes were reviewed against the v4 weighted asset rubric on
the current release candidate. The evidence set is the actual-route matrix in
`artifacts/v4-brand-captures/capture-manifest.json`: 532 deterministic WebP
captures covering 13 routes plus A01–A06 named scenes, seven viewports, English
and Korean, and default and reduced-motion modes. The capture validator rejects
overflow, clipped core text, sub-12px visible text, sub-14px control text,
undersized targets, broken images, locale drift, console errors, CLS above 0.1,
missing truth labels, stale worktree hashes, and stale build IDs.

| Signature asset            | Truth class                      | Selected composition       | Score | Critical | High | Decision |
| -------------------------- | -------------------------------- | -------------------------- | ----: | -------: | ---: | -------- |
| A01 Drop Everything        | T1 with subordinate T2           | B — Proof-First Product    |    94 |        0 |    0 | Approved |
| A02 Source to Structure    | T1                               | A — Editorial Source       |    95 |        0 |    0 | Approved |
| A03 Proof Link             | T0 public proof                  | B — Proof-First Product    |    97 |        0 |    0 | Approved |
| A04 Knowledge Architecture | T1                               | C — Knowledge Architecture |    94 |        0 |    0 | Approved |
| A05 Graph with Evidence    | T0 public proof + first-party UI | C — Knowledge Architecture |    96 |        0 |    0 | Approved |
| A06 Deployable Package     | T1                               | B — Proof-First Product    |    95 |        0 |    0 | Approved |

## Scoring record

The 100-point asset rubric is Brand fit 15, Message clarity 15, Product truth
15, Ownability 12, Composition 10, Typography/material 8, Responsive 7,
Accessibility 5, Performance 6, and Provenance/license 7. The score is a local
design-quality decision, not a field-performance, legal, customer, or production
attestation.

| Asset | Brand | Clarity | Truth | Ownability | Composition | Type/material | Responsive | A11y | Perf | Provenance | Total |
| ----- | ----: | ------: | ----: | ---------: | ----------: | ------------: | ---------: | ---: | ---: | ---------: | ----: |
| A01   |    14 |      15 |    15 |         11 |           9 |             8 |          7 |    5 |    3 |          7 |    94 |
| A02   |    14 |      15 |    15 |         11 |          10 |             8 |          7 |    5 |    3 |          7 |    95 |
| A03   |    15 |      15 |    15 |         12 |          10 |             8 |          7 |    5 |    3 |          7 |    97 |
| A04   |    14 |      15 |    15 |         11 |           9 |             8 |          7 |    5 |    3 |          7 |    94 |
| A05   |    15 |      15 |    15 |         11 |          10 |             8 |          7 |    5 |    3 |          7 |    96 |
| A06   |    14 |      15 |    15 |         11 |          10 |             8 |          7 |    5 |    3 |          7 |    95 |

Performance is deliberately scored 3/6: static-first and responsive asset
contracts pass locally, while current canonical field Core Web Vitals require
real traffic and remain external evidence.

## Truth and provenance decisions

- A01 exposes deterministic collection, classification, and dedupe state. The
  first-party 3D object remains visibly illustrative and subordinate.
- A02 binds the raw and compiled representations to one source identity and
  keeps an ordered nonvisual equivalent.
- A03 uses the hash-pinned OpenDART public filing fixture, exact authority and
  source cell, and an explicit no-quality-claim boundary.
- A04 renders the deterministic directory, MOC, note, entity, and relation
  architecture rather than a decorative graph.
- A05 binds a selected relation to adjacent source evidence and exposes a table
  alternative for nonvisual navigation.
- A06 renders the package tree and ties ready/downloadable state to deterministic
  package metadata; it does not fabricate a signed production package.

All six records use first-party deterministic UI/SVG or registered public proof.
No generated media is used as product, benchmark, customer, security,
certification, or public-document evidence.

## Non-blocking limitations

Three evidence limitations remain outside this local asset approval:

1. canonical-domain field LCP/INP/CLS requires real traffic;
2. physical-device screen-reader and mobile browser sign-off requires an
   independent device session; and
3. final trademark, public-claim, dataset, model, and license approval remains
   with the responsible external owners.

These limitations keep the overall Production Gate open; they do not invalidate
the current-worktree local asset measurement.
