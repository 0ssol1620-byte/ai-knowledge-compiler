# Proposed shared-file changes — not made

Per the shared-file freeze for this round, the following would improve the
P1 WORLD/SOURCE/CHANGE/ASK slice but touch a frozen file, so they were not
made. Written here instead, for the owner of each file to pick up or reject.

## 1. A "World" entry in the primary sidebar navigation

**File:** `apps/web/src/components/app-shell.tsx` — the `navigation` array
(currently `Home`, `Projects`, `Documents`, `Knowledge`, `Jobs`, `Exports`).

**What:** An entry pointing at `/app/world`, e.g.
`{ href: "/app/world", label: "World", icon: Graph }` (the `Graph` icon from
`@phosphor-icons/react` is already imported elsewhere in the codebase, e.g.
`knowledge-studio.tsx`).

**Why deferred rather than done:** `app-shell.tsx` is explicitly on the
freeze list (global navigation). The new routes work and are reachable by
direct URL (`/app/world`, `/app/world/:entityId`, and its `/source`,
`/change`, `/ask` sub-routes) and by in-page links from the WORLD index and
object pages, but there is no sidebar entry pointing a visitor at
`/app/world` from elsewhere in the product shell. `Knowledge` (existing nav
item, `/app/knowledge-bases`) is the closest existing entry conceptually and
might be the right place to repoint, rather than adding a seventh item — that
product decision belongs to whoever owns the nav, not this slice.

## 2. Command palette entry

**File:** same freeze reason — the quick-navigation list inside
`app-shell.tsx`'s command palette (`Ctrl/Cmd K`) currently lists Upload,
Projects, Knowledge, Review, Benchmark, Settings, Product site. A `World`
entry pointing at `/app/world` would fit the same pattern
(`["/app/world", "Search the world", "W"]`).

## Not proposed here

Everything else this task needed was buildable without touching a frozen
file — `product-shell.css` (product-scoped, not on the freeze list) carries
all new styling, and `demo-workspace.ts`/`product-event.ts`/
`world-projection.ts` were consumed read-only via the rebase, never edited.
