# W6 v4 transport amendment — frozen before any successful historical acquisition

`PATENT_FILING = NOT FILED`. `PAPER_SUBMISSION = NOT SUBMITTED`.

W6 v3 successfully froze an outcome-independent title universe **before** any
historical revision content was obtained:

- source category: `Category:Featured articles`
- candidate count: 6,987
- frozen manifest: `receipts/title-manifest-v3-2026-08-19.json`

Two identical v3 acquisition attempts then failed on the **first historical API
batch**, before a cohort result or acquisition receipt existed. MediaWiki returned
an API-level error envelope without a `query` member; v3 handled HTTP 429/503 but
not JSON `error` envelopes. No revision-sensitive yield, infobox value, question,
retrieval score, or model output was observed from either failed attempt.

This v4 amendment changes **transport handling only**. It does not select a new
candidate universe and does not change any scientific threshold.

## Frozen inheritance from v3

The following v3 bytes/rules are binding unchanged:

1. the exact v3 title-manifest file bytes and sha256;
2. title hash order and category membership;
3. before cutoff `2023-06-30T23:59:59Z`;
4. after cutoff `2026-06-30T23:59:59Z`;
5. minimum actual revision separation 1,095 days;
6. 750-title contiguous cohorts, maximum 6 cohorts;
7. stop only after a complete cohort reaches all availability requirements:
   - >=60 retained revision-sensitive structured facts,
   - >=20 distinct articles with retained revision-sensitive facts,
   - >=40 unchanged controls;
8. maximum 3 primary revision-sensitive attributes/article using the frozen hash
   ordering;
9. conservative infobox parser and all exclusions;
10. no model/RAG execution between cohorts;
11. no synthetic revisions, known-change title search, threshold lowering, or
    seventh cohort;
12. the v2/v3 leakage and Basic-RAG validity gates before any 3-arm model run.

The v3 acquisition implementation remains byte-for-byte unchanged because its hash
is pinned by the frozen title manifest.

## Sole v4 change: API error-envelope retry

A wrapper replaces only the network request function **at runtime**. For each
request it uses the same fixed English Wikipedia API and parameters as v3, but it
also treats MediaWiki JSON error codes `maxlag`, `ratelimited`, `readonly`, and
`internal_api_error_*` as retryable transport failures. It honours `Retry-After`
when present, otherwise uses bounded exponential backoff. HTTP 429/503 and transient
URL/timeout failures are likewise retried. Non-transient API error codes fail
closed.

The wrapper then calls the unchanged v3 `acquire()` function. That function still
verifies that the frozen manifest's protocol hash and **v3 acquisition-script
hash** match before reading historical data. Therefore v4 cannot silently alter
candidate order, cohort rules, extraction, stopping, or receipt construction.

## Seal

Before the first v4 request, record sha256 of:
- this amendment;
- the v4 wrapper;
- the frozen v3 manifest;
- the unchanged v3 acquisition script;
- v3 acquisition protocol.

If v4 fails transiently before a complete cohort result, bounded retries may use
the identical wrapper and manifest. If a complete cohort is observed, the frozen
v3 stopping rule governs; no transport failure permits changing the scientific
rules.

External GPU cost for acquisition remains `$0.00`.
