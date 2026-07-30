# OpenDART benchmark source runbook

## Purpose

OpenDART is used as a difficult Korean document source, not as a financial
product claim. The acquisition lane proves that public business-report source
packages can be collected reproducibly and bound to immutable hashes. It does
not turn source documents into ground truth and it does not authorize a public
quality claim.

Official contracts verified on 2026-07-30:

- disclosure search: `GET https://opendart.fss.or.kr/api/list.json`
- original disclosure package: `GET https://opendart.fss.or.kr/api/document.xml`
- business report detail type: `A001`
- API key parameter: `crtfc_key`
- original document identifier: fourteen-digit `rcept_no`

## Credential boundary

Prefer `AKC_DART_API_KEY` in a local secret store. For this workstation, the
CLI may instead receive `--credential-file D:\Github_API.txt`; only a line
containing the label `DART` is eligible. The collector rejects zero or multiple
labeled candidates. It never prints the value.

Never:

- commit the credential file or generated corpus;
- put the key in `NEXT_PUBLIC_*`, a query log, CI argument, screenshot, or
  benchmark receipt;
- pass an arbitrary API origin;
- download more than the bounded `--maximum-filings` value;
- present an acquisition manifest as benchmark quality evidence.

## Acquire

```powershell
py -3 benchmark/acquire_dart.py `
  --begin-date 20260101 `
  --end-date 20260430 `
  --maximum-filings 10 `
  --credential-file D:\Github_API.txt `
  --confirm PUBLIC_DART_BENCHMARK_ONLY
```

The collector:

1. searches only final `A001` business reports;
2. validates corporation, receipt, and date identifiers;
3. downloads from the fixed OpenDART HTTPS origin;
4. caps compressed and expanded bytes and rejects traversal, encrypted
   members, excessive member counts, and suspicious compression ratios;
5. stores the original ZIP and only supported textual source members;
6. records SHA-256, byte size, media type, source member, and acquisition time;
7. writes `labels_present=false` and `eligible_for_quality_claims=false`.

## Prepare a benchmark split

Acquisition and annotation are separate operations. The release-owned corpus
bundle must add:

- source rights decision and retention policy;
- document/page inventory and immutable split hashes;
- annotator identity pseudonyms, rubric version, QA adjudication, and conflict
  records;
- hidden holdout isolation;
- page-level text, block, reading-order, table, formula, heading, number,
  date/unit, provenance, and unsupported-claim annotations where applicable;
- explicit exclusions and failed-page records.

Do not copy a source XML body into both candidate output and ground truth.
Candidate parsers must read the acquired source bytes independently.

## Publish results

Only score records with `claim_class=internal_result`, a licensed-corpus
manifest, immutable evaluator revision, exact provider/model/runtime evidence,
and an approved evidence bundle may feed the public Benchmark Lab. Synthetic
and acquisition-only records remain unavailable in the product UI.
