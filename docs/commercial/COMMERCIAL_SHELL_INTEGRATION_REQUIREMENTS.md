# Commercial Shell — integration requirements for the Surface Integration pass

Status: **requirements only, not implemented.** Every shared file referenced
below (`app-shell.tsx` and anything else under the freeze list) was read for
this document and not edited. C1 (`/account`, `/billing`, API key management,
logout) is done, merged into this worktree, and out of scope to change here.

Tagging follows the same discipline as the Surface Integration track's own
`I0`/`I1`/`I2` docs: `observed` (read directly from source), `proven` (traced
end-to-end), `inferred` (reasoned from observed facts, not directly read),
`proposed` (this document's recommendation, not decided).

---

## 1. Global route wiring

**Routes that exist in this worktree**, each a real Next.js route with its
own `page.tsx` (`observed`):

| Route | File | Component |
|---|---|---|
| `/login` | `apps/web/src/app/login/page.tsx` | `AuthPage` (mode `login`) |
| `/signup` | `apps/web/src/app/signup/page.tsx` | `AuthPage` (mode `register`, `nextPath="/onboarding"`) |
| `/pricing` | resolved by `apps/web/src/app/[...slug]/page.tsx` (catch-all) → `StructaraMarketingPage` → `PUBLIC_PAGES["/pricing"]` in `apps/web/src/lib/structara-content.ts` | not a dedicated route file |
| `/billing` | `apps/web/src/app/billing/page.tsx` | `BillingManagement` |
| `/account` | `apps/web/src/app/account/page.tsx` | `AccountPage` |

**The shared file that gates and links routes:**
`apps/web/src/components/app-shell.tsx`. Three things in it matter for this
integration, all `observed` directly:

### 1a. Route classification (lines 74–106)

```ts
const marketingRoute =
  pathname === "/" ||
  [
    "/product", "/solutions", "/demo", "/research", "/security",
    "/pricing", "/customers", "/developers", "/company", "/legal",
  ].some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)) ||
  pathname === "/benchmarks";
const authRoute =
  pathname === "/login" ||
  pathname === "/signup" ||
  pathname === "/onboarding" ||
  pathname.startsWith("/forgot-password") ||
  pathname.startsWith("/sso");
```

`/account` and `/billing` fall into **neither** bucket, and are not in
`publicRoute` either (line 101–106: `marketingRoute || authRoute ||
designRoute || pathname === "/verify-email" || pathname.startsWith("/notices")`).
That means they already, correctly, hit the default branch: session-gated,
full `AppShell` chrome (sidebar, topbar, credit chip). **No classification
change is needed for `/account` or `/billing` to be reachable and
session-gated** — they behave like `/settings` or `/app/usage` today. This
is the one piece of "global route wiring" that requires **zero** edits.

### 1b. Nav arrays — this is what actually needs to change

`secondaryNavigation`, lines 41–46:

```ts
const secondaryNavigation = [
  { href: "/app/api", label: "API", icon: BracketsCurly },
  { href: "/app/usage", label: "Usage", icon: CreditCard },
  { href: "/app/settings/security", label: "Security", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: GearSix },
] as const;
```

**Proposed literal addition** (exact shape, matching the existing tuple
pattern — `href`/`label`/`icon` from `@phosphor-icons/react`, already
imported in this file for `CreditCard`/`GearSix`/`ShieldCheck`; `UserCircle`
is not yet imported and must be added to the import block at lines 3–21):

```ts
const secondaryNavigation = [
  { href: "/app/api", label: "API", icon: BracketsCurly },
  { href: "/app/usage", label: "Usage", icon: CreditCard },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/account", label: "Account", icon: UserCircle },
  { href: "/app/settings/security", label: "Security", icon: ShieldCheck },
  { href: "/settings", label: "Settings", icon: GearSix },
] as const;
```

(`/billing` reuses the `CreditCard` icon already imported for `/app/usage` —
see §4 for why these two are adjacent and the overlap this raises. `Billing`
placement before `/account` follows the read order of the current list; this
is a suggestion, not a hard requirement — Surface Integration owns final
ordering.)

This array drives the `sidebar-secondary` `<nav>` at lines 290–325, which
`.map()`s it directly — no other file needs to change for the desktop
sidebar entry.

### 1c. Mobile nav (lines 389–411) is a **separate, hardcoded** array

```tsx
<nav className="mobile-app-nav" aria-label="Mobile navigation">
  {(
    [
      { href: "/home", label: "Overview", icon: House },
      { href: "/projects", label: "Projects", icon: FolderOpen },
      { href: "/activity", label: "Activity", icon: Pulse },
      { href: "/settings", label: "Account", icon: GearSix },
    ] as const
  ).map(...)}
</nav>
```

This is **not** `secondaryNavigation` — it's an inline literal, independently
hardcoded, and it already labels the `/settings` entry "Account" (confusingly
— that's the tenant-settings page, not the new `/account` profile page).
Adding `/account`/`/billing` to `secondaryNavigation` does **not** surface
them on mobile. Surface Integration must decide separately whether to: (a)
leave mobile nav as-is (4-slot budget, already full), (b) swap the existing
`/settings` → "Account" mobile entry to point at `/account` instead now that
a real account page exists, or (c) extend the mobile nav's icon budget. Not
decided here — flagging because silently doing nothing here means `/account`
is desktop-only reachable, which may or may not be intended.

### 1d. `COMMAND_ENTRIES` (lines 50–58) — the Ctrl+K palette

```ts
const COMMAND_ENTRIES = [
  ["/quick-convert", "Upload documents", "U"],
  ["/projects", "Open projects", "P"],
  ["/knowledge-bases", "Search entities", "E"],
  ["/review", "Open Review Studio", "R"],
  ["/benchmarks", "Run benchmark", "B"],
  ["/settings", "Workspace settings", "S"],
  ["/", "Product site", "H"],
] as const satisfies ReadonlyArray<readonly [string, string, string]>;
```

Neither `/account` nor `/billing` is in the command palette. Optional
addition, e.g. `["/account", "Account settings", "A"]` and
`["/billing", "Billing", "B"]` — note `"B"` collides with the existing
`/benchmarks` entry's `"B"` key, so a palette addition needs a different
mnemonic (e.g. `"L"` for billing) or accepts that these are label-matched
only, not single-key accelerators. Not required for reachability — the
palette only filters a fixed list, it does not do fuzzy route search — but
listed here for completeness since the task asked for exact entries.

---

## 2. Auth navigation

**What currently handles unauthenticated routing (`observed`, already real,
already correct — no gap here):**

`app-shell.tsx` lines 108–146: on every non-public route (i.e. not
`marketingRoute`, not `authRoute`, not `designRoute`, not `/verify-email`,
not `/notices*`), a `useEffect` calls `GET /v1/auth/session`
(`apiRequest<unknown>("/v1/auth/session", ...)`) on mount/pathname change. On
a 401/403 (`ApiError` with that status) it does:

```ts
setSessionState("denied");
router.replace(`/login?next=${encodeURIComponent(pathname)}`);
```

This already covers `/account` and `/billing` automatically, because they
are not classified as public/auth/marketing routes (§1a) — **no change is
required** to make `/account`/`/billing` redirect a signed-out user to
`/login?next=/account` or `/login?next=/billing`. This is the actual
protected-route guard; there is no separate per-page auth check.

**What handles the return trip after login (`observed`, `auth-page.tsx`
lines 17–32, 114):**

```ts
const registerHref = `/login?mode=register${nextQuery}`;
// nextQuery = nextPath === "/" ? "" : `&next=${encodeURIComponent(nextPath)}`
...
router.replace(nextPath as Route);
```

`AuthPage` reads `nextPath` as a prop (from the `/login` page's own query
param parsing — not read directly in this pass, but the `next=` query
convention used by `app-shell.tsx`'s redirect matches what `AuthPage`
expects to receive and replay after a successful login). This round-trip
already works for any protected route, `/account` and `/billing` included,
because it is generic on `pathname`/`nextPath` — **no route-specific
handling exists or is needed.**

**Gap (`observed`, carried over unchanged from C0/C1, not fixed in this
document):** signup's `nextPath` is hardcoded to `/onboarding`
(`apps/web/src/app/signup/page.tsx` — `nextPath="/onboarding"`), so a
signed-out user who lands on `/account` or `/billing`, is redirected to
`/login?next=/account`, and switches to the register tab instead of logging
in, will be sent to `/onboarding` rather than back to `/account`. This is
pre-existing behavior unrelated to C1's new routes and not something this
task should change — noted so Surface Integration doesn't mistake it for a
new regression.

**Nothing else currently reacts to auth state for these two routes.** There
is no separate `ProtectedRoute` wrapper component, no route-level
`getServerSideProps`/middleware auth check — the single `useEffect` in
`AppShell` is the entire mechanism (`proven` — grepped for `middleware.ts`
under `apps/web/src/`, none exists at the app-shell/route level relevant to
this check).

---

## 3. Account entry

**Existing pattern to extend (`observed`, `app-shell.tsx` lines 369–383):**

```tsx
<Link
  className="account-button"
  href="/settings"
  aria-label="Open account settings"
  data-shell-action="account"
>
  <span className="avatar" aria-hidden="true">{userInitials}</span>
  <span className="account-copy">
    <strong>{workspaceName ?? "Workspace"}</strong>
    <small>{userRole ?? "Member"}</small>
  </span>
  <CaretDown size={14} aria-hidden="true" />
</Link>
```

This is the topbar avatar/workspace chip — the only existing "account entry"
pattern in the shell. It is a plain `Link`, not a dropdown menu (the
`CaretDown` icon is decorative — clicking it does not open a menu, it
navigates directly to `/settings`, confirmed by reading the full component:
there is no `onClick`, no menu state, no `aria-expanded` on this element).
**There is no avatar dropdown/user menu anywhere in this shell to extend** —
the task brief's "avatar dropdown, settings icon — whatever pattern already
exists" resolves to: **there is no dropdown pattern; this is a direct link.**

**Two ways to surface `/account`, not decided here:**

1. **Repoint the existing avatar link** from `/settings` to `/account` (this
   would make the topbar avatar go to the new personal-profile/API-keys page
   instead of tenant settings — a real behavior change to an existing,
   working link, and a judgment call about which destination a workspace
   avatar "should" mean).
2. **Turn the plain `Link` into an actual dropdown** (`CaretDown` already
   implies one visually, misleadingly) with two entries — "Account" →
   `/account`, "Workspace settings" → `/settings` — which resolves the
   `CaretDown` affordance mismatch (a chevron on a plain link that does not
   open anything is close to the "no dead controls" rule this repo's
   `AGENTS.md`/`design-system` conventions call out, though this file is
   frozen and not this track's call to fix).

This document does not pick between them — both are shared-file changes to
`app-shell.tsx`, both belong to Surface Integration.

Separately, `/account` is already reachable via `secondaryNavigation` once
§1b lands, and via direct URL — this section is specifically about the
topbar avatar affordance, which is the one place a signed-in user would
plausibly expect "my account" to live.

---

## 4. Billing entry

**Where it should be surfaced — lay out the options, not a decision, per
task instructions.**

### The overlap (`observed`, confirmed by reading both files directly)

`apps/web/src/app/usage/page.tsx`:
```tsx
export const metadata: Metadata = { title: "Usage & billing" };
export default function UsagePage() {
  return (
    <div className="simple-page usage-page">
      <h1>Usage and credits</h1>
      <p>Review credits by processing method, storage, and purchases against the verified ledger.</p>
      <BillingManagement />
    </div>
  );
}
```

`apps/web/src/app/billing/page.tsx` (C1, this round):
```tsx
export const metadata: Metadata = { title: "Billing" };
export default function BillingPage() {
  return (
    <div className="simple-page billing-page">
      <h1>Billing</h1>
      <p>Credit packs, checkout, and your server-confirmed payment history for this workspace.</p>
      <BillingManagement />
    </div>
  );
}
```

Both render the exact same `BillingManagement` component
(`apps/web/src/components/billing-management.tsx`) with **no props** — same
data, same checkout flow, same `PAYMENTS_UNAVAILABLE` honesty branch,
different `<h1>`/intro copy only. `/app/usage` is already linked from
`secondaryNavigation` today (line 43); `/billing` is not linked from
anywhere yet (that's item §1b above).

### Options for Surface Integration to choose from (`proposed`, none selected)

**Option A — keep both, as independent surfaces.**
Nav keeps `/app/usage` ("Usage") and adds `/billing` ("Billing") as two
separate `secondaryNavigation` entries (as drafted in §1b). Product argument:
"usage" (credit consumption, processing method breakdown) and "billing"
(purchases, payment history, credit packs) are conceptually different
questions even though today's `BillingManagement` answers both in one
component — this option bets that they diverge in content later (e.g. usage
gets a consumption chart, billing stays purchase/invoice-focused) and having
two routes now avoids a route-rename migration later. Cost: two nav entries
pointing at visually near-identical pages today, which reads as a
duplicate/broken IA until the components actually diverge.

**Option B — `/usage` redirects to `/billing` (or vice versa).**
Pick one canonical route, make the other a client or server redirect (Next.js
`redirect()` in the losing page, or a `next.config` rewrite). Product
argument: there is exactly one component and one capability today, so one
canonical URL avoids the duplicate-IA problem in Option A. Which direction to
redirect is itself a call — `/app/usage` is the older, already-linked route
(less link rot if it stays canonical and `/billing` becomes an alias for
anyone who types the more obvious marketing-adjacent URL), or `/billing` is
the more conventional SaaS URL a user would guess or that marketing/pricing
CTAs would link to (making it worth being canonical instead). Cost: whichever
one becomes the alias needs its `secondaryNavigation` entry removed to avoid
double-listing a redirect.

**Option C — merge into one page, retire the other.**
Delete one route's `page.tsx`, keep a single nav entry. Same effective
outcome as Option B without the redirect indirection, but is a harder commit
than B if the product wants to keep the option to diverge them later (B
preserves the URL even if the content doesn't diverge yet; C requires
recreating the route from scratch if divergence is later wanted).

This document's own recommendation-shaped position, offered but not decided:
Option B (redirect) is the smallest change that removes the duplicate-IA
problem without foreclosing Option A's future-divergence story, since the
redirect can be deleted later if the pages actually diverge. But this is a
product call per the task brief and per `CLAUDE.md`'s "what is not an
agent's call" list touching pricing-adjacent product decisions — Surface
Integration or the founder should pick.

### Nav placement, independent of the A/B/C choice above

Regardless of which option is chosen, `/billing` (or whichever route wins)
belongs in `secondaryNavigation` next to `/app/api`/`/app/usage`/`/settings`
— it is workspace administration, not primary product navigation
(`navigation`, lines 32–39, is document/project/knowledge-base work, and
`/billing` does not belong there structurally). No case was found for also
duplicating it under `/account` as a sub-tab — `AccountPage`
(`apps/web/src/components/account-page.tsx`, `observed`) does not currently
have a tab/sub-nav structure to embed a billing link into; it's a single
scrolling page (profile summary, sign-out, API keys). Adding billing there
would be new information architecture this document is not proposing.

---

## 5. Signed-in / signed-out shell behavior

**Current conditional rendering (`observed`, exhaustive — this is every
auth-state branch in `app-shell.tsx`):**

1. **`marketingRoute || designRoute`** (line 180–182): returns `children`
   directly, no `AppShell` chrome at all, regardless of auth state. `/pricing`
   is in this bucket.
2. **`authRoute || pathname === "/verify-email"`** (line 184–186): same,
   bare `children`, no chrome. `/login`, `/signup` are in this bucket.
3. **`!publicRoute && sessionState !== "ready"`** (lines 188–220): renders a
   dedicated `session-gate` `<main>` with a spinner ("Checking your
   session"), a "Redirecting to sign in" message during the 401 redirect
   window, or an error state with a "Try again" retry button. No sidebar, no
   topbar — this is the only state a signed-out user visiting `/account` or
   `/billing` will see before the redirect in §2 fires.
4. **Default / signed-in** (lines 228 onward): full chrome — sidebar
   (`navigation` + `secondaryNavigation`), demo-mode banner if
   `NEXT_PUBLIC_AKC_DEMO_MODE === "true"`, topbar with credit chip
   (`profile.creditBalance`), notifications link, the account-button
   described in §3, mobile nav.

**What this means for `/account`/`/billing` specifically:** they inherit
default/signed-in chrome automatically (§1a already established they are
correctly classified) — **there is no route-specific chrome variant to
build.** The only thing a signed-out visitor to either route sees is the
generic session-gate spinner/redirect in state 3, same as any other
protected route (`/settings`, `/app/usage`, etc.) — this is existing,
correct, shared behavior, not something new this integration needs to add.

**Nothing currently changes shell chrome based on *role* (owner/admin vs.
member) at the shell level** — `app-shell.tsx` reads `profile.roles[0]` only
to display it as text (`userRole`, line 223, shown as `<small>{userRole ??
"Member"}</small>`) and does not gate any nav entry on role. Role-gating for
admin-only capability (API keys, team management) happens inside the
destination pages themselves (`AccountPage`'s API-key section,
`settings-live.tsx`'s webhook section — both `observed`, out of scope here).
If Surface Integration wants `/billing` or `/account` nav entries themselves
to be role-gated (e.g. hide "Billing" from non-owner/admin members), that
would be a new pattern — no precedent for it exists in `secondaryNavigation`
today; every entry currently renders unconditionally once signed in.

**DEMO_MODE** (`NEXT_PUBLIC_AKC_DEMO_MODE === "true"`, lines 48, 65–66,
109–111, 222–226, 230–233): when set, `sessionState` starts `"ready"`
immediately (no `/v1/auth/session` call at all — line 66), a banner reads
"Demo workspace · No documents are processed and no credits are used.", and
`workspaceName`/`userRole`/`userInitials`/`creditBalance` all fall back to
hardcoded demo strings (`"Sample workspace"`, `"Demo"`, `"DE"`, the
`"Demo"` credit-chip label at line 353–354) rather than reading `profile`.
`/billing`'s real `BillingManagement` component was not checked in this pass
for whether it independently handles `DEMO_MODE` (it makes its own
`GET /v1/billing/payments` calls regardless of shell demo state) — flagging
as an open question rather than asserting either way: **does `/billing`
under `DEMO_MODE` make a real backend call and potentially show real
payment data inside an otherwise-fake demo shell?** This needs a check
against `billing-management.tsx`'s own demo-mode awareness (or lack of it)
before `/billing` is linked into nav for any demo-mode deployment — noted
as a follow-up, not resolved here since it required reading a file (
`billing-management.tsx`) beyond what this document already grounded from
C1's own report, and doing so would be scope creep into re-auditing C1's own
work rather than documenting integration requirements.

---

## Summary of exact shared-file edits this unlocks (for Surface Integration)

All in `apps/web/src/components/app-shell.tsx`, none made in this round:

1. Add `UserCircle` to the `@phosphor-icons/react` import (line 3–21).
2. Add two entries to `secondaryNavigation` (§1b).
3. Decide and implement one of §1c's three mobile-nav options.
4. Optionally add two entries to `COMMAND_ENTRIES` with a non-colliding key
   (§1d).
5. Decide and implement one of §3's two account-entry options (repoint
   `/settings` → `/account`, or build an actual dropdown).
6. Decide and implement one of §4's three `/usage`-vs-`/billing` options
   (Option A/B/C), then reflect that choice in the `secondaryNavigation`
   entry from item 2.
7. Before shipping `/billing` in nav under any `DEMO_MODE` deployment,
   check `billing-management.tsx` for real-backend-call-under-demo-mode
   behavior (§5, flagged not resolved).

No other shared file requires changes for these five routes to be fully
integrated — `auth-page.tsx`, `session.ts`, `auth-store.ts`, and the
`/v1/auth/session` redirect mechanism in `app-shell.tsx` already generalize
correctly to `/account` and `/billing` with no route-specific code (§2).
