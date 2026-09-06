# W6 v5 single-title transport amendment — frozen before historical results

W6 v3 froze 6,987 Featured-Article titles in outcome-independent hash order before
historical content. v3/v4 acquired **zero successful historical page results**.
v4 exposed the deterministic root cause: MediaWiki rejects `rvstart`/`rvend` when
`prop=revisions` is requested for multiple `titles` in one query
(`invalidparammix`). This is an API batching defect, not a data result.

v5 preserves the exact v3 manifest and every v3 scientific rule. Its only change
is how the already-requested revision lookup is transported: each title in a v3
batch is queried individually with the same cutoff, revision fields, redirect
handling, and main-slot wikitext request. Results are returned to unchanged v3
`acquire()` in the same input-title mapping shape.

Binding unchanged rules:
- exact v3 title-manifest bytes/order/category;
- 2023-06-30 and 2026-06-30 UTC cutoffs;
- >=1,095-day actual separation;
- 750-title contiguous cohorts, max 6;
- stop only at >=60 retained changed facts across >=20 articles and >=40 controls;
- max 3 changed attributes/article, frozen hash order;
- same conservative infobox parser/exclusions;
- no model run between cohorts;
- no known-change page search, synthetic primary, threshold changes, or extra cohort;
- v2/v3 leakage and Basic-RAG validity gates remain binding before model inference.

Transport handling:
- one title per `prop=revisions` request;
- API-level `maxlag`, `ratelimited`, `readonly`, `internal_api_error_*`, HTTP
  429/503, URL/timeout and JSON transport failures receive bounded retry/backoff;
- permanent API errors fail closed;
- redirects are resolved exactly as in v3;
- no semantic filtering occurs in the transport wrapper.

Before the first request, pin this protocol, v5 wrapper, v3 manifest, unchanged v3
script and v3 protocol hashes. GPU cost remains `$0.00`.
