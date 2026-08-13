# Commercial shell — current-state inventory (Phase C0)

Scope: `apps/web` (Next.js 16 / React 19) frontend + `services/api` (FastAPI)
backend, as they existed on branch `agent/tavonel-commercial-shell` at the
start of this work (base `main` @ `7ac5098`). This is a factual inventory,
not a design proposal.

## Headline finding

**The commercial shell is substantially more real than "unclear" implied.**
Auth, session handling, and a real (if provider-less) payment/credit ledger
already exist and are wired end-to-end. What is actually missing is not
backend capability but two dedicated route surfaces (`/account`, `/billing`)
and the front-end wiring for one already-real backend capability (API keys,
and session logout). `/pricing` already exists as real, non-fabricated
content, but on the cinematic marketing stack rather than the calm
commercial-shell register.

## Auth / login / signup / session

**Real, not stubbed.** Backend: `services/api/src/akc_api/auth_api.py` +
`main.py` (`POST /v1/auth/register`, `POST /v1/auth/login`,
`GET /v1/auth/session`, `POST /v1/auth/logout`, `POST /v1/auth/verify-email`,
MFA enrollment/challenge, OIDC authorize/callback). Session is an HttpOnly
cookie — the frontend never touches a token.

Frontend:
- `apps/web/src/app/login/page.tsx` + `apps/web/src/components/auth-page.tsx`
  — real login/register form, posts to `/v1/auth/login` or
  `/v1/auth/register`, maps server error codes
  (`INVALID_CREDENTIALS`, `EMAIL_EXISTS`, `REGISTER_CONFLICT`,
  `NO_TENANT_MEMBERSHIP`, `CSRF_ORIGIN_DENIED`) to copy, routes into email
  verification (`VerificationPending`) when `emailVerified === false`.
- `apps/web/src/app/signup/page.tsx` — thin wrapper around the same
  `AuthPage` component in `register` mode, `nextPath="/onboarding"`.
- `apps/web/src/lib/session.ts` — `normalizeSessionResponse`, defensive
  parsing of both the flat and nested session shapes, throws rather than
  inventing a display name or tenant id. Has unit tests
  (`lib/session.test.ts`).
- `apps/web/src/lib/auth-store.ts` — Zustand store, display metadata only
  (`tenantId`, `userName`, `email`, `emailVerified`, `roles`). It is not the
  source of truth for auth — the HttpOnly cookie is — this store is UI state.
- `apps/web/src/components/app-shell.tsx` (frozen, read-only this round) —
  on every non-public route it calls `GET /v1/auth/session`; a 401/403
  redirects to `/login?next=...`. This is the actual route guard, not a
  client-only illusion.
- `apps/web/src/app/forgot-password/page.tsx` — deliberately, visibly
  disabled: "Recovery delivery becomes available after the production email
  service is configured." Already follows the exact honesty pattern this
  track is asked to produce elsewhere.
- `apps/web/src/app/verify-email/page.tsx` +
  `components/verify-email-page.tsx` — real, consumes `/v1/auth/verify-email`
  with a token from the query string.

**Gap found and fixed in C1:** nothing in the frontend ever calls
`POST /v1/auth/logout` or `clearSession()` — grepped, zero references before
this change. The backend endpoint exists; there was no way to sign out from
the UI.

## Account management (profile, settings)

**Partially real, partially absent.**
- `apps/web/src/app/settings/page.tsx` +
  `apps/web/src/components/settings-live.tsx` — real, backed by
  `GET/PATCH /v1/settings`: privacy/processing policy, retention, member
  list, webhooks (owner/admin gated), credits & billing (embeds
  `BillingManagement`). Role gating comes from `useAuthStore` roles, cross-
  checked against `settings.data.canManagePolicy` from the server (matches
  `principal.roles.isdisjoint({"owner","admin"})` in
  `services/api/src/akc_api/main.py:6697`).
- **No profile editing exists anywhere** — no display-name change, no
  password change/reset. Confirmed by reading `auth_api.py` and the
  `/v1/auth/*` and `/v1/settings` routes in `main.py`: there is no
  `PATCH` on a user/profile resource, only tenant-level `/v1/settings`.
  `forgot-password` is the only password-adjacent surface and is explicitly
  disabled pending email delivery.
- **API keys are real on the backend and had zero frontend surface.**
  `POST /v1/api-keys`, `GET /v1/api-keys`, `DELETE /v1/api-keys/{id}` all
  exist in `services/api/src/akc_api/main.py` (`AdminDep` = owner/admin
  only), backed by a real `ApiKey` model. Grepped the whole `apps/web/src`
  tree for `api-keys` / `ApiKey` before this change: no matches. This is a
  real, unexposed capability, not a fabrication risk — built the UI for it
  in C1.
- No dedicated `/account` route existed before this change.

## Team / org membership

**Real.** `services/api/src/akc_api/team_api.py`, `team_models.py`, and
`apps/web/src/components/team-management.tsx`, embedded in the "Members &
roles" section of `/settings`. Out of scope for this round — not touched.

## Pricing page / pricing data model

**Content is real; treatment is the cinematic marketing stack, not the
calm commercial register this track is scoped to build.**
- `/pricing` already resolves through the public marketing catch-all route
  `apps/web/src/app/[...slug]/page.tsx` → `StructaraMarketingPage` →
  `PUBLIC_PAGES["/pricing"]` in `apps/web/src/lib/structara-content.ts`.
  The copy is explicit that it is "Illustrative plan structure; final
  commercial values require owner approval" — it does not fabricate a
  price book, so it already satisfies the no-fabrication rule.
  `apps/web/src/components/app-shell.tsx` treats `/pricing` as a
  `marketingRoute` and renders it chrome-free.
- `apps/web/src/components/structara-pricing-planner.tsx` is a separate,
  real (no backend calls, self-contained estimator) interactive component —
  audience toggle (Individuals/Teams/Enterprise), page/scan/precision
  sliders, and a bounded credit estimate. It explicitly says "This planning
  model exposes scan, Precision, and knowledge-output overhead. It is an
  estimate, not a quote." It has its own test file
  (`structara-pricing-planner.test.tsx`).
- **There is no backend plan/price-book data model.** `plan_code` exists on
  `Tenant` (`services/api/src/akc_api/models.py`) and gates real behavior
  (`_plan_tier`, `_plan_upload_limit`, `queue_priority_for_plan`,
  `is_free_plan` in `main.py` / `free_tier.py`), but there is no priced
  plan catalog, no plan-upgrade endpoint, and no way for a tenant to change
  its own `plan_code` from the UI.

**Decision made in C1 (documented here, not silently done):** `/pricing`
already exists, is real, and is a route the marketing/cinematic system
owns (`structara-marketing-page.tsx`, `structara-content.ts`, both outside
this track's scope and adjacent to the frozen surfaces). Duplicating it
under the calm register was not possible without either colliding with the
existing route or editing the marketing system this track was told not to
touch. `/pricing` was left untouched. See "What was not built" below.

## Billing / subscription / entitlement state

**Real backend, real honest-degrade frontend component, but no payment
provider is actually connected, and no dedicated route existed.**
- `services/api/src/akc_api/payments.py` — `PaymentProvider` protocol with
  three implementations: `FakePaymentProvider` (test-only),
  `MerchantHandoffPaymentProvider`, `DisabledPaymentProvider`. Which one is
  wired depends on environment configuration, not on anything in this
  worktree's frontend.
- `services/api/src/akc_api/payment_routes.py` — `GET /v1/billing/credit-
  packs`, `POST /v1/billing/checkouts`, `GET /v1/billing/checkouts/{id}`.
  Returns `PAYMENTS_UNAVAILABLE` (HTTP, via `payment_routes.py:121`) when no
  provider is connected — this is a real, typed error code, not a generic
  500.
- `services/api/src/akc_api/models.py` — real `Payment` and `PaymentEvent`
  tables; this is ledger truth, not a mock.
- `apps/web/src/components/billing-management.tsx` — **already implements
  the exact honesty contract this track asks for**: on
  `ApiError.code === "PAYMENTS_UNAVAILABLE"` it renders "No verified payment
  provider is connected to this environment. Credit purchases remain
  unavailable rather than simulated." instead of a fake checkout. It shows
  real payment history from `GET /v1/billing/payments` and a real (never
  fabricated) empty state.
- This component was already embedded in `/settings` (Credits & billing
  section) and `/usage`. **No dedicated `/billing` route existed.**

## Existing routes under /login, /signup, /pricing, /billing, /account

| Route | File | Status before this change |
|---|---|---|
| `/login` | `app/login/page.tsx` | Real, complete |
| `/signup` | `app/signup/page.tsx` | Real, complete (wraps same `AuthPage`) |
| `/pricing` | `app/[...slug]/page.tsx` (catch-all) | Real content, cinematic marketing treatment |
| `/billing` | *(none)* | Missing — capability existed only inside `/settings` and `/usage` |
| `/account` | *(none)* | Missing — no profile/API-key surface existed at all |

Other adjacent, pre-existing real routes: `/forgot-password` (honestly
disabled), `/verify-email`, `/settings`, `/usage`, `/onboarding`, `/sso`.

## Global/shared surfaces observed but not editable this round

Read for context only, per the freeze list in the task:
- `apps/web/src/app/layout.tsx` — root layout, imports 4 global CSS files
  (`globals.css`, `product-shell.css`, `enterprise-refresh.css`,
  `structara.css`) and mounts `Providers` + `AppShell`.
- `apps/web/src/components/app-shell.tsx` — global app shell: sidebar nav
  (`navigation`, `secondaryNavigation` arrays), topbar, session gate,
  command palette, public/marketing/auth route classification. New routes
  added in C1 are **not yet linked from this nav** (see
  `PROPOSED_SHARED_CHANGES.md`) because editing it is out of scope.
- Root `package.json`, `pnpm-lock.yaml` — not touched; no new dependency
  was needed for C1 (see report).
- No `ProductEvent`/`LiveEventAdapter`/`WorldProjection` contract files,
  global auth middleware, or global CSP/security policy file were touched
  or needed.

## What C1 actually builds

Given the above, C1 adds exactly two new route-local surfaces and reuses
existing real infrastructure rather than re-implementing it:
1. `/account` — new. Real session profile (name, email, workspace, roles,
   credit balance) via `GET /v1/auth/session`; real sign-out via
   `POST /v1/auth/logout`; real, previously-unexposed API key management
   (`GET/POST/DELETE /v1/api-keys`, owner/admin gated); an explicit, visible
   note that profile editing (display name / password change) is not
   backend-supported, because it is not.
2. `/billing` — new. Thin, calm-register page wrapping the already-real,
   already-honest `BillingManagement` component. No new backend surface,
   no fabricated plan/payment state beyond what that component already
   honestly renders.
3. `/login`, `/signup` — verified real and complete; not modified.
4. `/pricing` — verified real; not modified, decision documented above.
