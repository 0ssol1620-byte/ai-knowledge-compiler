# FOLYNTA website v3 deployment receipt

Deployment date: 2026-08-02

## Immutable source

- Branch: `agent/folynta-website-total-reset-v3`
- Source commit: `c601126e93f2adbdf9bf74112eaf49cda31abbd1`
- Commit subject: `feat: rebuild FOLYNTA website from v3 masterplan`
- Deployment input: a clean `git archive` of the source commit; unrelated
  working-tree files were excluded

## Vercel production release

- Project: `structara-knowledge-compiler`
- Project ID: `prj_09FfzMvNd6UhRU1FYGd2F1S1V17X`
- Deployment ID: `dpl_BDPvffVp7W28BPeCWf52XZAhBRT2`
- Deployment URL:
  `https://structara-knowledge-compiler-h8cg6c6c8.vercel.app`
- Production alias: `https://structara-knowledge-compiler.vercel.app`
- Final state: `READY`
- Alias error: none

## Live verification

The following requests returned HTTP 200 from the production alias:

- `/`
- `/product/compile`
- `/signup`
- `/demo/dart`
- `/demo/sec`
- `/api/health`

Production HTML verification passed for:

- exact scene order: `01-hero -> 02-processing -> 03-proof ->
04-transformation -> 05-knowledge -> 06-trust-security -> 07-final`
- EN default SEC/Apple evidence
- KO default DART receipt `20260730000413`
- canonical Compile narrative
- Google-centered signup action
- Content Security Policy and Strict Transport Security headers
- zero grouped Vercel runtime errors in the post-deployment verification window

This receipt establishes successful deployment and live route health. It does
not replace the external legal, independent human review, production-provider,
or field-performance gates listed in `VISUAL_QA_REPORT.md`.
