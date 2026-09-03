# Submission package index — 2026-08-19

Every deliverable, its role, and its hash at index time. **`PATENT_FILING = NOT
FILED` and no paper is submitted.** This is an inventory of what is ready to hand
over, not a record of a handover.

Regenerate with `python tools/ip/build_submission_index.py`. Hashes change
whenever a document is edited; a stale hash here means the index was not rebuilt,
not that a document was tampered with.

## PATENT

| role | path | sha256 | bytes |
|---|---|---|---|
| filing README | `docs/ip/FILING_README_2026-08-20.md` | `24210bd274cb…` | 6,040 |
| filing review draft (built PDF) | `docs/ip/TAVONEL_PATENT_FILING_REVIEW_DRAFT.pdf` | `61fe72d2fb31…` | 1,137,532 |
| drawing sheets, combined (built PDF) | `docs/ip/drawings/TAVONEL_PATENT_DRAWINGS.pdf` | `264300906950…` | 1,037,461 |
| claim set | `docs/ip/PATENT_CLAIM_SET_v1_2026-08-19.md` | `9471726fca74…` | 37,047 |
| abstract and drawings | `docs/ip/PATENT_ABSTRACT_AND_DRAWINGS_2026-08-20.md` | `312682387580…` | 11,043 |
| specification | `docs/ip/PATENT_SPECIFICATION_v1_2026-08-19.md` | `0bf9840017f4…` | 32,345 |
| claim-evidence matrix (generated) | `docs/ip/CLAIM_EVIDENCE_MATRIX.md` | `b4dc770ac23b…` | 75,883 |
| claim-evidence registry (source) | `docs/ip/claim-evidence-matrix.yaml` | `8ffc1e28bdf0…` | 82,734 |
| prior-art and narrowing memo | `docs/ip/PRIOR_ART_AND_NARROWING_MEMO_2026-08-19.md` | `52fbd6da3fd2…` | 11,865 |
| examiner red team | `docs/ip/EXAMINER_RED_TEAM_2026-08-19.md` | `7afdc45276f9…` | 17,816 |
| examiner red team, statutory (101/102/103/112) | `docs/ip/EXAMINER_RED_TEAM_STATUTORY_2026-08-20.md` | `7d9908531f2f…` | 15,491 |
| examiner red team, W6 disposition | `docs/ip/W6_V8_EXAMINER_RED_TEAM_2026-08-20.md` | `3461726ec7a9…` | 8,692 |
| claim amendment register | `docs/ip/CLAIM_AMENDMENTS.yaml` | `87f499384d54…` | 15,462 |
| element-level support bindings | `docs/ip/ELEMENT_SUPPORT_BINDINGS.yaml` | `3ecba3317794…` | 23,541 |
| element support matrix (receipt) | `docs/ip/receipts/element-support-matrix-2026-08-19.json` | `c9e757429d48…` | 42,309 |
| assertion registry | `docs/ip/ASSERTION_REGISTRY.yaml` | `bd0dbef84316…` | 9,262 |
| withdrawn-term registry | `docs/ip/WITHDRAWN_TERMS.yaml` | `0a9c65df2fb6…` | 5,034 |
| counsel flags (generated) | `docs/ip/COUNSEL_FLAGS_2026-08-20.md` | `f93c34da22c5…` | 9,875 |
| unsupported-breadth ledger (generated) | `docs/ip/UNSUPPORTED_BREADTH_LEDGER_2026-08-20.md` | `88d41a9b8a32…` | 3,611 |
| technology intake register (FTO) | `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml` | `8c52a31bc2bb…` | 9,586 |
| disclosure registry | `docs/ip/V4_DISCLOSURE_REGISTRY.yaml` | `1f0fbf505cac…` | 19,734 |

## PAPER

| role | path | sha256 | bytes |
|---|---|---|---|
| manuscript | `docs/paper/MANUSCRIPT_v1_2026-08-19.md` | `a981d5a164e4…` | 83,954 |
| manuscript, generic build (built PDF) | `docs/paper/TAVONEL_MANUSCRIPT_GENERIC.pdf` | `989f0c4b7de3…` | 1,950,698 |
| figures | `docs/paper/FIGURES_2026-08-19.md` | `fb4765c23570…` | 14,689 |
| rendered figure registry | `docs/paper/figures/FIGURE_REGISTRY.json` | `be61128b9b0d…` | 17,879 |
| tables | `docs/paper/TABLES_2026-08-19.md` | `dbd99a484bd4…` | 11,892 |
| reviewer red team | `docs/audit/REVIEWER_RED_TEAM_2026-08-19.md` | `234a62ac420b…` | 15,640 |
| reviewer red team, W6 disposition | `docs/audit/W6_V8_REVIEWER_RED_TEAM_2026-08-20.md` | `bd82038e3720…` | 9,187 |

## AUDIT

| role | path | sha256 | bytes |
|---|---|---|---|
| hostile review | `docs/audit/HOSTILE_REVIEW_2026-08-19.md` | `93420f8b05de…` | 80,333 |
| ablation coverage | `docs/audit/ABLATION_COVERAGE_2026-08-19.md` | `361080680f19…` | 12,162 |
| failed and superseded ledger | `docs/evidence/FAILED_AND_SUPERSEDED_LEDGER.md` | `daa87f0ac0ab…` | 18,231 |
| receipt-overwrite incident | `research/experiments/H1-A12-01/INCIDENT_RECEIPT_OVERWRITE_2026-08-19.md` | `7d709bd6c25e…` | 4,687 |
| submission readiness checklist | `docs/SUBMISSION_READINESS_CHECKLIST_2026-08-19.md` | `b9216647f491…` | 9,577 |
| convergence protocol (frozen) | `docs/audit/CONVERGENCE_PROTOCOL_2026-08-19.md` | `b274c43dc518…` | 22,375 |
| convergence round 2 (not clean) | `docs/audit/convergence-rounds/round-02.json` | `e93d1134a08b…` | 4,708 |
| W6 final state | `research/experiments/H1-W6-SAME-INTELLIGENCE-01/W6_V8_FINAL_STATE_2026-08-20.md` | `44dc1b4570fe…` | 8,584 |
| standing bounds registry | `docs/audit/STANDING_BOUNDS.yaml` | `bd001595238a…` | 4,553 |

## REPRO

| role | path | sha256 | bytes |
|---|---|---|---|
| experiment manifest | `docs/repro/EXPERIMENT_MANIFEST.json` | `951e887b3805…` | 189,456 |
| execution index | `docs/repro/EXECUTION_INDEX_2026-08-19.json` | `d39dbf387eff…` | 153,667 |
| historical drift register | `docs/repro/HISTORICAL_DRIFT_REGISTER.yaml` | `30d2e78df32c…` | 2,217 |
| exclusion rules | `docs/repro/EXCLUSION_RULES_2026-08-19.md` | `4ac7f15697f2…` | 10,112 |
| session execution log | `docs/repro/SESSION_EXECUTION_LOG_2026-08-19.md` | `d45c99e08f7a…` | 6,826 |
| test scope and interpreter status | `docs/repro/TEST_SCOPE_STATUS.json` | `0c12365dcf85…` | 3,929 |
| full-suite failure triage | `docs/repro/FULL_SUITE_TRIAGE.json` | `c08e6aaaf05d…` | 14,061 |

## HUMAN_REVIEW

| role | path | sha256 | bytes |
|---|---|---|---|
| pass A packet (human read) | `docs/submission/HUMAN_PASS_A_PACKET.md` | `cd9c5b6ed5fa…` | 10,030 |
| inventor / founder review checklist | `docs/ip/INVENTOR_REVIEW_CHECKLIST_2026-08-20.md` | `8af5bb0defee…` | 5,606 |
| final external actions | `docs/submission/FINAL_EXTERNAL_ACTIONS.md` | `00822af2f8ff…` | 9,098 |

## STATUS

| role | path | sha256 | bytes |
|---|---|---|---|
| program status | `research/PROGRAM_STATUS_2026-08-19.md` | `a0e140ca3544…` | 78,249 |

## Not in this package

- **W6 same-intelligence comparative result** — the confirmatory run executed on 2026-08-20 and stopped at its pre-arm baseline validity gate. No arm ran; the comparative endpoint is NOT_MEASURED. The cohort is spent and is development data from this point forward.
- **A12 cause-conditioned recovery** — blocked external — no container runtime on this host, so no image digest.
- **cross-source equivalence** — no second source family with explicit amendment relationships exists offline.
- **rendered figure assets** — figures are specified as mermaid and tables, not exported to images.
- **a convergence claim** — pass A is a human read and has not been performed. Rounds record `agent_convergence_complete` for passes B-K separately, and that field is not convergence and may not be reported as one.
- **four claim recitals supported only by implementation** — A4, A5, B7 and B9 are RESERVED continuation material, held out of the filing core by a recorded decision rather than measured.

Each is listed so its absence is a stated state rather than an omission.
