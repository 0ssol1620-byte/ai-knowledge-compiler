# Structara v4 visual capture runbook

This runbook produces the current-worktree route evidence required by masterplan
§44.3 and the fail-closed policy in `VISUAL_QUALITY_GATES.yml`. It does not turn
a deterministic demo into customer, benchmark, production, or field-performance
evidence.

## Capture contract

- Routes: `/`, `/product`, `/benchmarks`, `/security`, `/pricing`, `/intake`,
  `/workspace`, `/integrity`, `/knowledge-bases`, `/demo/dart`, and `/demo/sec`.
- A05/A06 signature support: `/app/projects/project_research/graph` and
  `/app/projects/project_research/exports`.
- Widths: 1920, 1440, 1280, 1024, 768, 390, and 360 pixels.
- Languages: English and Korean.
- Motion: default and reduced-motion.
- Scenes: actual above-fold route crops plus separate A01–A06 homepage element
  captures; component mockups are not accepted.
- Total: 532 hash-pinned WebP captures.

The capture runner records the current Git revision, dirty-worktree status and
diff fingerprints, Next build ID, response status, language, horizontal
overflow, visible broken images, console errors, lab cumulative layout shift,
visible text below 12px, core-control text below 14px, clipped core copy, and
core target sizes (24px desktop / 44px mobile). Signature crops repeat those
checks inside the actual A01–A06 element and require a bound truth class,
nonempty text, and measured crop dimensions. Any automated blocking finding
makes the command fail.

## Deterministic reference capture

Build demo mode explicitly. The top-of-app disclosure must remain visible and
must state that no customer processing or credits are represented.

```powershell
$env:NEXT_PUBLIC_AKC_DEMO_MODE = "true"
$env:NEXT_PUBLIC_AKC_API_URL = "http://127.0.0.1:8000"
pnpm --filter @akc/web build
$env:HOSTNAME = "127.0.0.1"
$env:PORT = "3100"
pnpm --filter @akc/web start:e2e:standalone
```

In a second terminal:

```powershell
$env:STRUCTARA_CAPTURE_URL = "http://127.0.0.1:3100"
pnpm --filter @akc/web brand:capture:v4
.venv\Scripts\python.exe infra\release\validate_v4_visual_capture.py --require-current-build --require-current-worktree
```

Evidence is written to ignored local storage under
`artifacts/v4-brand-captures/`. `capture-manifest.json` and `hashes.sha256`
bind every image to the run. The runner clears that exact evidence directory
before capture so stale screenshots cannot survive a new run. The validator
decodes every WebP, checks above-fold and signature dimensions, rejects reused
or extra filenames, requires nonempty `main` content and an explicit truth
boundary, and requires the hash index to match the manifest byte-for-byte. Do
not copy old captures into this directory or edit the manifest after capture.

## Human inspection

Automated approval only proves the matrix and machine-detectable invariants.
Review every route family and all six A01–A06 signature assets for:

1. Korean and English line breaks, crop, hierarchy, and key-text legibility.
2. Product and public-proof truth labels, unavailable states, and source links.
3. Keyboard focus visibility and obstruction, 200% text scaling, forced colors,
   reduced-motion information parity, and non-color status semantics.
4. The exact §45 weighted visual rubric, with Critical and High findings both
   zero and no forbidden pattern.

Record scores only after current captures, Storybook state coverage, automated
accessibility, and lab performance have passed. Field Core Web Vitals, real
device and screen-reader review, legal/brand clearance, and production evidence
remain separate release gates.
