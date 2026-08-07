# Product motion loops

The capture script records ten required product interaction sequences directly from the real
deterministic demo routes. It does not generate UI, fake typing, or imply actual
processing latency. Every loop is labeled in the manifest as
`Sequence condensed for demonstration`.

Run:

```powershell
pnpm --filter @akc/web exec node scripts/capture-product-loops.mjs
```

WebM is the browser-recorded delivery master. The script also creates an H.264
MP4 derivative with FFmpeg for Safari, presentation, and sales channels. Set
`TAVONEL_FFMPEG` to the reviewed executable path.
