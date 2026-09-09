# Source-bound projection candidate — 2026-09-09

Status: DEVELOPMENT CANDIDATE. Not a production promotion, not a fresh benchmark, not a customer-data approval.
Base: agent/apple-core-proof / Core PR #60.

## Defects corrected in the explicit source-bound profile

Claim, summary and ontology output bodies contain source provenance, but their legacy declarations omitted locator/visual sensitivity. The retrieval index also needs structural sensitivity when its membership changes. The historical directory problem is handled with an explicit PRECISE policy in the new composition, without silently changing the Protected Core default.

CanonicalUnit.snapshot did not expose bbox, region id and authority consistently. The candidate snapshot carries the observed authority and a canonical digest of unit.provenance in the visual facet, without injecting geometry into logical identity matching or inventing evidence ids.

The Protected Core facet list intentionally excluded VISUAL in the older incident fix. A new include_visual_facet=False keyword preserves that default; only the source-bound composition opts in. Authority changes are evaluated at GRAPH level. Deletion propagation uses the union of declared before/after dependency edges, while the candidate inventory contains only current artifacts.

The new compile_source_bound_update validates prior artifact binding, computes a declared selective rebuild, and compares it with a complete rebuild. It never fills a missed artifact from the complete-build oracle. Any mismatch refuses the candidate. Returned rebuilt/carried hash mappings are immutable.

## Compatibility

ProjectionPolicy.LEGACY remains the default. Existing body bytes and artifact identifiers are unchanged. SOURCE_BOUND changes the declared sensitivity graph, not the content definition. Existing Apple receipts and expected values were not rewritten.

## Execution evidence

- Changed code and tests: Ruff clean.
- projection_update.py and projections.py: strict mypy clean.
- Selected final suite: 86 passed, including 19 new synthetic candidate tests, existing semantic-diff/recompilation coverage, 13 frozen Apple reproduction tests, and two additional real-corpus candidate tests.
- Existing Apple receipt hashes reproduced byte-for-byte.
- Same five Apple filings, 290 pages, native parser + existing SEC adapter; source hashes checked before parsing.
- Chain A's four updates and Chain B's two updates: candidate artifacts equal a full rebuild, stale-left-behind zero in each step.
- New candidate receipts: .chatgpt2codex/source-bound-apple/chain-a.json and chain-b.json. These are separate from the frozen historical receipts.

## What this does not prove

This does not solve the stock SEC canonicaliser's source-fact coverage gap, resolve every ambiguous logical identity, deploy C-09, exercise customer authentication/ACL/export, qualify CDR, or establish general OCR or router superiority. Chain B retains the previous experiment's explicit lineage modelling assumption. The complete-build equivalence check is CPU work and is not evidence of end-to-end latency or cost savings.

No paid model, GPU, fresh holdout, customer document or external API inference was used.

## Promotion gate

The candidate is an explicit API rather than a default switch. It requires independent review, exact-SHA CI, source-fact/identity/ACL qualification, shadow comparison and bounded rollout before any live call site uses it. Core Actions access/billing and the parent PR's integration ladder remain separate gates. No main merge or global runtime-policy change is authorized by this document.
