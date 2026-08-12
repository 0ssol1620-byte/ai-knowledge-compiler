# Structara v4 current-state audit

**Release status:** **Production Reject**

- Assessed: 2026-08-01 (Asia/Seoul)
- Authority: `D:\Structara_World_Class_Autonomous_Knowledge_Platform_FINAL_Completion_Masterplan_v4_KO_2026-07-31.md`
- Repository: `0ssol1620-byte/ai-knowledge-compiler`
- Branch: `agent/structara-ultra-premium-rebuild`
- Traceability: `V4_MASTERPLAN_TRACEABILITY.md`
- External gates: `docs/release/EXTERNAL_GATES.md`

## Decision

The current worktree is a **repository release candidate**. All locally
implementable v4 control-plane, product, contract, migration, security-policy,
browser, accessibility, and visual-evidence work has been implemented and
verified. The web product is publishable as an evidence-bounded reference/demo
surface.

It is not valid to claim `Production Ready`, `public benchmark complete`, or
`autonomous production proven`. Those claims require provider, managed cloud,
rights-cleared corpus, measured scale, independent security, commercial,
legal, and field evidence that cannot be manufactured from repository fixtures.
`promotion_authorized=false` therefore remains mandatory.

## Current local verification

| Area | Result |
| --- | --- |
| Python | 1,119 tests passed |
| Python quality | Ruff passed; mypy passed across 164 source files |
| Database | Alembic 0001→0030 upgrade, downgrade-to-base, and re-upgrade passed on a disposable database |
| Web unit/component | 38 Vitest files, 184 tests passed |
| Web static checks | ESLint zero warnings; strict TypeScript passed; production build passed |
| Browser E2E | 71 passed, 15 intentional project-scope skips, 0 failed |
| Browser matrix | 10/10 across seven widths, Chromium, Firefox, WebKit, and installed Edge |
| Live journey | 1/1 passed against real local API/database processes |
| Visual | 9/9 baselines; 532-image current-worktree capture contract |
| Accessibility | 4/4 automated projects; forced colors, 200% zoom, reduced motion, WCAG A/AA |
| Security | repository/deployment validators, production-source Bandit, dependency audits passed |
| Contracts | canonical type generation, OpenAPI v1 compatibility, scale profile, traceability validators passed |

The live journey covers registration, verification, upload, preflight,
external-processing consent, compile, duplicate idempotency, SSE,
source/provenance navigation, integrity resolution, export download, and
deletion/purge. The authority pipeline also materializes collection-wide
DART/SEC numeric geometry mappings, supersedes stale matches, revokes stale
verification, and fails closed for unverified source geometry.

## Local product and visual gates

The local Visual Quality Gate is approved at **94/100**, with A01–A06 scoring
94, 95, 97, 94, 96, and 95. Critical findings are 0 and High findings are 0.
The approval is bound to the actual-route capture manifest, build ID, Git
revision, tracked diff, untracked content, and worktree-status hashes.

Representative browser inspection found no horizontal overflow, broken image,
unnamed enabled action, console error, or warning. Bilingual switching,
truth/demo disclosures, source/proof navigation, Integrity, Knowledge Studio,
mobile navigation, reduced motion, and forced-color behavior remained intact.

This local approval does not convert lab/static evidence into field Core Web
Vitals, an independent assistive-technology sign-off, or legal clearance.

## Production blockers

The following external evidence must be bound to one immutable release revision:

1. protected repository governance and successful hosted CI/Security/Model CI;
2. managed PostgreSQL, queue/Redis, R2/object storage, workload identity,
   production secrets, RLS, and verified tenant isolation;
3. exact immutable model revisions, endpoint attestations, and signed images;
4. rights-cleared Public Core and private hard-set runs, three repetitions,
   immutable raw outputs, and a signed report;
5. the 5,000-file/10 GiB, 30,000-page, 1,000-SSE, 100-upload and related scale,
   fairness, chaos, alert, restore, canary, and rollback evidence;
6. production IdP, email sender, payment connector, invoice reconciliation,
   and deletion/retention drills;
7. independent penetration/IDOR/RLS/privacy assessment;
8. canonical field p75 LCP/INP/CLS and physical-device assistive-technology
   review; and
9. trademark, brand, dataset, model, runtime, notices, legal, and public-claim
   approvals.

Exact acceptance artifacts and accountable owners are maintained in
`docs/release/EXTERNAL_GATES.md`. Repository code, synthetic fixtures, a Vercel
`Ready` state, or a local benchmark smoke cannot close those gates.

## Publication boundary

The website may be pushed and published because it labels deterministic demos,
public fixtures, unavailable benchmark values, and production-evidence
boundaries explicitly. `/api/health` exposes a 40-character deployment revision
when the host provides `VERCEL_GIT_COMMIT_SHA` and fails closed to `null`
otherwise. Web publication proves only that the exact web surface is reachable;
it does not prove that the API control plane or external Production Gate is
closed.

The dated machine-readable file `docs/release/V4_DEPLOYMENT_MANIFEST.json`
remains the preceding fail-closed deployment snapshot for deployment
`dpl_2ucfqSmbUX1nN8yTmYgoKKRRaS1G`. The final publication
URL, immutable deployment URL, revision match, and HTTP probes are recorded in
the release handoff after deployment so the repository does not attempt the
impossible self-reference of embedding its own final commit SHA.
