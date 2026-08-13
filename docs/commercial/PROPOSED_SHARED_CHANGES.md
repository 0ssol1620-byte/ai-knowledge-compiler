# Proposed shared-surface changes — deferred to Surface Integration

Per the freeze list for this track, the files below were read for context
but not edited. These are proposals only.

## 1. Link `/account` and `/billing` from the global app shell nav

**File:** `apps/web/src/components/app-shell.tsx`
**What:** `/account` and `/billing` are real, working, session-gated routes
as of this change, but nothing links to them. `secondaryNavigation`
(around line 41) currently has:

```ts
const secondaryNavigation = [
  { href: "/app/api", label: "API", icon: BracketsCurly },
  { href: "/app/usage", label: "Usage", icon: CreditCard },
  { href: "/app/settings/security", label: "Security", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: GearSix },
] as const;
```

Proposal, now that item 2 below has resolved the `/usage`/`/billing`
overlap (`/usage` redirects to `/billing`): replace the `/app/usage` entry
rather than add a second one alongside it, and add `/account`:

```ts
const secondaryNavigation = [
  { href: "/app/api", label: "API", icon: BracketsCurly },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/app/settings/security", label: "Security", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: GearSix },
] as const;
```

`UserCircle` does not need to be added to the icon import for this array —
`/account` is reachable through the account menu (item 1a below), not
through `secondaryNavigation`, so no redundant sidebar entry is proposed
for it. (`UserCircle` is used by the new `AccountMenu` component itself,
which imports it locally.)

**Why deferred:** `app-shell.tsx` is on the explicit freeze list
(global navigation).

## 1a. Replace the topbar account link with the new `AccountMenu` dropdown

**Founder decision (this round):** the topbar "account-button" — currently a
plain `Link` to `/settings` with a decorative, non-functional `CaretDown` —
becomes a real dropdown with Account, Billing, and Sign out. Built this
round as a standalone component so it is testable and reviewable in
isolation:

- `apps/web/src/components/account-menu.tsx` — `AccountMenu` component.
  Props: `workspaceName`, `userRole`, `userInitials` — the exact three
  values `app-shell.tsx` already computes locally (lines 222–226) and
  currently passes inline into the `account-button` markup.
- `apps/web/src/components/account-menu.module.css` — scoped styles for the
  dropdown panel; reuses the existing global `.account-button`, `.avatar`,
  `.account-copy` classes for the trigger so it matches current chrome
  without touching `globals.css`.
- `apps/web/src/lib/use-logout.ts` — the sign-out mutation extracted out of
  `account-page.tsx` (same `POST /v1/auth/logout` → `clearSession()` →
  `router.replace("/login")` → `router.refresh()` sequence, now shared
  rather than duplicated). `account-page.tsx` was refactored to use this
  hook; behavior unchanged (its existing test still passes unmodified).

**Exact wiring for `app-shell.tsx` (not applied this round):**

```tsx
// import, alongside the other component imports:
import { AccountMenu } from "@/components/account-menu";

// replace lines 369–383 (the <Link className="account-button" href="/settings" ...>...</Link> block) with:
<AccountMenu
  workspaceName={workspaceName}
  userRole={userRole}
  userInitials={userInitials}
/>
```

No other change to `app-shell.tsx` is required for this — `AccountMenu` is
self-contained (owns its own open/close state, outside-click and Escape
handling) and renders its own trigger markup with the same
`account-button`/`avatar`/`account-copy` classes and `data-shell-action`
attribute the current `Link` used, so no CSS or test relying on that
attribute needs to change.

**Why built as a standalone component instead of edited directly into
`app-shell.tsx`:** `app-shell.tsx` is on the explicit freeze list for this
track (see `COMMERCIAL_SHELL_CURRENT_STATE.md` and
`COMMERCIAL_SHELL_INTEGRATION_REQUIREMENTS.md §3`), and that freeze has held
for every file in this doc so far. The founder's decision approves the
*design* of the dropdown (Account/Billing/Sign out, replacing the dead
`CaretDown`) — it is not, on its own, an explicit instruction to unfreeze
`app-shell.tsx` for direct edits. Rather than guess, this round ships the
new component fully built and tested, with the one-line integration above
ready for whichever session owns `app-shell.tsx` to apply.

## 2. `/usage` vs `/billing` overlap — resolved

**Founder decision (this round): `/billing` is canonical.**
`apps/web/src/app/usage/page.tsx` now does `redirect("/billing")` (Next.js
`redirect()` from `next/navigation`) instead of rendering
`BillingManagement` directly. The route file, and the `/usage` concept, are
kept — not deleted — because the founder wants `/usage` available again as a
distinct usage-analytics surface once that capability exists; today it has
no content that differs from `/billing`, so a redirect is the honest state
rather than a duplicate page. Test: `apps/web/src/app/usage/page.test.tsx`.

This is implemented already (not deferred) — listed here only so item 1's
nav proposal below reflects it: once `/billing` is added to
`secondaryNavigation`, `/app/usage`'s existing entry should be removed
rather than kept alongside a route that now just bounces to it.

## 3. `/pricing` register mismatch

`/pricing` already exists and is real (see
`docs/commercial/COMMERCIAL_SHELL_CURRENT_STATE.md`), served by the
marketing catch-all (`apps/web/src/app/[...slug]/page.tsx` →
`StructaraMarketingPage` → `PUBLIC_PAGES["/pricing"]` in
`apps/web/src/lib/structara-content.ts`). This track's design principle is
explicitly calm/functional, not cinematic marketing. Whether `/pricing`
should be rebuilt in the calm register, split into a public marketing page
plus a separate in-app plan-comparison view, or left as-is is a product
call, not something this track should decide unilaterally by editing the
marketing content system (`structara-marketing-page.tsx`,
`structara-content.ts`) — both adjacent to, and easy to confuse with, the
frozen surfaces. Not edited in this round.

## No package.json / pnpm-lock.yaml changes

No new dependency was added in this round (see the implementer's report for
the reasoning — the payment SDK question doesn't arise because the backend
already owns the provider abstraction and the frontend never talks to a
payment SDK directly, only to `/v1/billing/*`).
