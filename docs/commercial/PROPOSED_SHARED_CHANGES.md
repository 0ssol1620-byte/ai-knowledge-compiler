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

Proposal: add `{ href: "/account", label: "Account", icon: UserCircle }` and
`{ href: "/billing", label: "Billing", icon: CreditCard }` (or fold Billing
into the existing Usage entry once product decides whether `/usage` and
`/billing` should merge — see item 2).

**Why deferred:** `app-shell.tsx` is on the explicit freeze list
(global navigation).

## 2. Resolve the `/usage` vs `/billing` overlap

`apps/web/src/app/usage/page.tsx` already renders the same
`BillingManagement` component this change puts at `/billing`. Both are real
and both work; they are not in conflict, but having two routes for the same
capability is a product decision, not an implementation one. Options: keep
both (usage = credit consumption context, billing = payment context — they
could diverge in content later), redirect one to the other, or merge.
Not decided in this round; flagging for Surface Integration.

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
