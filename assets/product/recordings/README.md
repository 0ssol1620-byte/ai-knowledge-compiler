# Product motion loops

The capture script records eight product sequences directly from the real
deterministic demo routes. It does not generate UI, fake typing, or imply actual
processing latency. Every loop is labeled in the manifest as
`Sequence condensed for demonstration`.

Run:

```powershell
pnpm --filter @akc/web exec node scripts/capture-product-loops.mjs
```

WebM is the primary delivery master in this repository. MP4 derivatives are
created only for a deployment target that requires them and after a licensed
H.264 encoding tool is available.
