# Vercel Deployment Fix — `outputDirectory` Duplication (P0-K)

## Status

- **Fix applied in repo:** `vercel.json` no longer sets `outputDirectory` (Option A).
- **Human check required:** one-time verification of **Root Directory** in the Vercel dashboard (see checklist below). This cannot be verified or changed from the repository side.

## Symptom

Vercel production builds failed while locating the build output:

```
Error: The output directory "apps/web/.next" was not found at
"/vercel/path0/apps/web/apps/web/.next".
```

The doubled segment (`apps/web/apps/web/`) shows that Vercel resolved the
`outputDirectory` value from `vercel.json` **relative to the effective Root
Directory**, which during those builds was already `apps/web` — whether pinned
via the dashboard *Root Directory* setting or derived by platform monorepo
detection. The two configurations were therefore duplicated:

| Layer | Value | Effective location |
| --- | --- | --- |
| Dashboard Root Directory | `apps/web` (effective) | `/vercel/path0/apps/web` |
| `vercel.json` → `outputDirectory` | `apps/web/.next` | `/vercel/path0/apps/web/apps/web/.next` ❌ |

## Fix applied (repo side)

Removed the `outputDirectory` key from `vercel.json`. Before → after:

```diff
 {
   "$schema": "https://openapi.vercel.sh/vercel.json",
   "framework": "nextjs",
   "installCommand": "pnpm install --frozen-lockfile",
-  "buildCommand": "pnpm --filter @akc/web build",
-  "outputDirectory": "apps/web/.next"
+  "buildCommand": "pnpm --filter @akc/web build"
 }
```

Why this is sufficient: with `"framework": "nextjs"`, Vercel uses the Next.js
framework preset, which knows that a production build emits `.next` **inside the
app directory** (i.e. `<Root Directory>/.next`) and picks it up automatically.
No explicit `outputDirectory` is needed — and any relative value is joined onto
the Root Directory, which is exactly what caused the duplication.

`buildCommand` (`pnpm --filter @akc/web build`) is kept: pnpm resolves the
workspace root upward from the current directory, so the filtered build works
whether commands are executed from the repo root or from `apps/web`.

## Required human checklist (Vercel dashboard)

1. Open **Vercel Dashboard → `<project>` → Settings → General → Build &
   Development Settings**.
2. **Root Directory** — verify the current value:
   - Expected: `apps/web`, or empty/unset if relying on platform defaults.
   - The failure signature above proves the *effective* root during builds was
     already `apps/web`; whatever the dashboard shows, keep it as-is for this
     fix and record it here after checking. Do **not** change Root Directory
     together with this fix (that would move the problem).
3. **Build Command / Output Directory / Install Command** — ensure none of them
   has a manual dashboard override that reintroduces the duplicated path:
   - Expected: all three left on their defaults (dashboard inherits
     `vercel.json`), and **Output Directory empty/unset** everywhere.
4. Redeploy Production and confirm the build reaches "Generating static pages"
   and completes.

## Related app configuration (no change needed)

- `apps/web/next.config.ts` sets `distDir: process.env.NEXT_DIST_DIR || ".next"`
  — the default output location stays `.next` inside the app directory, which
  is what the framework preset expects. If anyone ever sets `NEXT_DIST_DIR` in
  Vercel Environment Variables, these expectations change; leave it unset.
- `next.config.ts` also sets `output: "standalone"` (used by
  `apps/web/Dockerfile` for self-hosted deploys). This does not move `.next`
  and does not affect the Vercel build; do not "fix" it here.

## Local verification performed for this fix

Clean production build of the app succeeds and emits `.next`:

```sh
pnpm --filter @akc/web build   # run from the repository root
ls apps/web/.next/BUILD_ID    # exists after a successful build
```

(Exact command output recorded in the evidence header of the commit that
introduced this fix.)
