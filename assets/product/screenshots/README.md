# Canonical product captures

Run:

```powershell
pnpm --filter @akc/web exec node scripts/capture-product-assets.mjs
```

The script captures 18 deterministic T0 product-evidence views from the real
application at 1440 x 900. It uses reduced motion, stable fixture routes,
hidden cursor/caret, and WebP delivery. The capture manifest records the route,
viewport, locale, demo label, and capture time.

These images are evidence derivatives, not generated UI. They may be used in
marketing, documentation, and owner-approved sales materials but never as a
customer claim.
