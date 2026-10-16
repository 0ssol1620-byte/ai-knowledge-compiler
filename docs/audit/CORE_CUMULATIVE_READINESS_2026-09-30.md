# Core cumulative offline qualification — 2026-09-30

Frozen implementation head: `19e9d0a78c111b513f687cd48ac8f60edd8268e6`.
Requested base: `57e55037872d6df30857c83714452b23783b8dab`, based on the
productization branch rather than main. Branch: codex/core-grounding-qualification
in task-3/core-grounding. This report is a documentation-only follow-up.

## Final cumulative regression

Python 3.12.6 on Windows, existing locked isolated environment, synthetic inputs:

| Check on frozen implementation head                                                            | Exact result                         |
| ---------------------------------------------------------------------------------------------- | ------------------------------------ |
| `pytest tests/unit tests/contract packages -m 'not provider and not integration and not slow'` | 2000 passed, 0 failed, 97.17 seconds |
| Actual Foundation HTTP dispatch/projection against this Core head                              | 5 passed, 1 file, 3.39 seconds       |
| Ruff `packages services tests benchmark`                                                       | Passed                               |
| Strict mypy `packages services`                                                                | Passed, 320 source files             |
| Git whitespace / tracked working tree                                                          | Passed / clean before report         |

The five HTTP checks cover package hash projection, persisted restart replay,
incremental/full equivalence, authentication refusal and response-tamper refusal.
They import the actual unchanged Foundation adapter. The disposable harness only
updates the former missing-verification assertions to require the computed result.
No Foundation gate was relaxed. Source/version identity and evidence changes,
durable journal maintenance, fragment integrity and shared-span citations are
included in the 2000-test run; focused suite counts are overlapping, not additive.
One existing Starlette/httpx deprecation warning remains; no failed or skipped
invocation is represented as a passing check. No critical cumulative interaction
regression was found, so this batch adds no implementation change.

Machine evidence outside Git:

- task-3/core-cumulative-final.log
- task-3/core-cumulative-final.xml; SHA-256
  `2b3b7a2eab37975e2a7ad141bb02d8e895aaba91c3fc9b5fa1f1c5ad1238692b`

The earlier 11 Windows visual tests, 383 web unit tests, real PostgreSQL 0038
rehearsal and dependency/filesystem scans remain evidence from their documented
repair heads. They were not rerun or relabeled as fresh image/Linux evidence in
this Python-only cumulative qualification. Services/API infrastructure tests,
provider/slow/integration markers and the full configured pytest tree were not
claimed by this bounded command.

## K-item reconciliation

The exact K01–K31 IDs and remaining conditions below follow the integration owner's
read-only matrix at task/foundation-integration/docs/audit/
MASTERPLAN_IMPLEMENTATION_2026-09-30.md, section Engineering task reconciliation.
The Core masterplan's semantic acceptance details are in v4.0 sections 10.5,
12.4–12.8 and QUE-03. This is a Core-lane reconciliation, not a replacement for
the combined Foundation/customer/desktop acceptance ledger.

P = partial Core evidence; N = not newly qualified in this Core batch;
E = primary external input/release dependency. No entire K-item is closed.

| ID  | Status | Verified Core contribution; condition still required for full item                                                                              |
| --- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| K01 | P      | Local CI baseline, typing and dependency repairs; hosted Linux/image/deployment configuration qualification                                     |
| K02 | P      | Effective-anchor uniqueness and retained logical/source-version identities; existing-data identity migration                                    |
| K03 | N      | No centralized inventory/policy/tombstone reconciliation qualification                                                                          |
| K04 | P      | Real signed HTTP parent/revision adapter projection and computed immutable reference binding; deployed compatibility                            |
| K05 | P      | Deterministic document fragments/global reducer, integrity and existing 13-document fixtures; deployment/customer shard and scale qualification |
| K06 | P      | No-op and derived-input invalidation, full/selective oracle and retained rejection tests; representative comprehensive corpus                   |
| K07 | P      | Opt-in single-host journal, fragment checkpoint/restart replay and key/release binding; concurrent distributed orchestration/publication        |
| K08 | N      | Watcher-to-publication and operational liveness remain other-lane acceptance                                                                    |
| K09 | N      | Auth/tamper refusals remain tested; complete proof/ACL/cache audit not newly qualified                                                          |
| K10 | N      | Synthetic real HTTP boundary is not actual private customer-path acceptance                                                                     |
| K11 | P      | Distinct native anchor citations survive shared span digests; universal parser/anchor contracts                                                 |
| K12 | P      | Existing native Office/PDF fidelity regressions pass; proposed format/corpus qualification                                                      |
| K13 | P      | Existing synthetic XLSX fidelity checks pass; locked representative spreadsheet golden corpus                                                   |
| K14 | E      | No paid OCR run or new provider quality/security qualification                                                                                  |
| K15 | P      | Existing resolver and stable identity regressions pass; locked holdout and production resolver integration                                      |
| K16 | P      | Evidence/authority/OCR invalidation and unchanged-unit reuse; comprehensive merge/split propagation                                             |
| K17 | P      | Evidence-bound rule semantics and shared entity lineage regressions; multilingual/version quality evaluation                                    |
| K18 | N      | No ontology migration/breaking-change acceptance; existing ontology tests are regression evidence only                                          |
| K19 | P      | Actual Foundation consumer adapter verifies Core package hashes; identical-context MCP/API/CLI consumer proof                                   |
| K20 | P      | Existing bounded request/input checks retained; full reservation/settlement and cost qualification                                              |
| K21 | P      | Verified journal backup/new-path restore, corruption refusal and deterministic compaction; deletion/derived-cache/backup policy coverage        |
| K22 | P      | Digest/reference and tampered fragment/journal refusals retained; complete parser/archive/injection audit                                       |
| K23 | N      | No new operational dashboards/SLO/liveness qualification                                                                                        |
| K24 | N      | No desktop install/upgrade/rollback acceptance in this lane                                                                                     |
| K25 | P      | Existing 13-document global reduction fixtures retained; 10k-document/hot-entity/load acceptance                                                |
| K26 | E      | No customer/competitor model evaluation or performance superiority claim                                                                        |
| K27 | N      | No HWP/HWPX feasibility qualification                                                                                                           |
| K28 | E      | No live OAuth grants or new connector qualification                                                                                             |
| K29 | P      | Reproducible local audit/test evidence; full operational evidence bundle                                                                        |
| K30 | E      | Publication, merge/deploy and production activation require separate release authority                                                          |
| K31 | N      | No new comprehensive adaptive native/OCR routing qualification                                                                                  |

Whole-item totals: **0 complete, 18 partial, 9 not newly qualified, 4 primarily
external**. These unweighted counts are not completion percentages or effort
estimates. Completed local subcriteria include single-host replay/corruption
refusal, verified offline journal copy, deterministic cleanup, computed reference
binding, derived-input invalidation and native citation preservation under the
specific synthetic cases documented. Shared storage fencing is a disabled
protocol plus reference tests, not an implemented distributed backend.

## Minimum remaining gates

For the integration owner's next stable batch:

1. Cherry-pick the ordered local implementation commits through 19e9d0a and rerun
   exact-head hosted Python/security/web gates. No pushes are performed by this lane.
2. Build and scan the candidate images on a supported container host. Local Docker
   and Podman are absent and WSL enumeration returned E_ACCESSDENIED; no machine
   security changes were attempted. Verify the pinned OpenSSL overlay at runtime.
3. Rehearse the entire unchanged Core migration chain on PostgreSQL with pgvector.
   The isolated installed PostgreSQL 17.2 passed 0001–0023 and actual 0038
   upgrade/repeat/downgrade; 0024 lacks vector.control. No local compiler exists
   to build pgvector. This is a tool blocker, not full migration acceptance.
4. Qualify current TAVONEL Linux visual reference captures. Current committed
   references are Windows-only; archived FOLYNTA Linux images are not substitutes.
5. Assign a new compiler release digest for any deployment of changed behavior.
   Stored receipts are immutable and journal keys refuse cross-release reuse.

For full masterplan acceptance, tools alone are insufficient: a selected shared
transactional fencing backend and deployment conformance, ACL/revocation/deletion/
restore/cost and merge/split scenarios, locked format/semantic holdouts and scale
fixtures remain engineering work. Representative customer data, model comparisons,
live OAuth and production activation require the explicit inputs/authority named
by K14/K26/K28/K30. No benchmark claim or delivery date is manufactured.

This lane is ready for sequential integration and pauses for feedback. Original
integration and prior offline checkouts are retained. No publication, visibility,
billing, credentials, security settings, paid compute or production flags changed.
