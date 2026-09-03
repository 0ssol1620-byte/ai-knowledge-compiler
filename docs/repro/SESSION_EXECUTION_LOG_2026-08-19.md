# Exact local execution log — 2026-08-19 continuation

This file records exact commands executed in the current continuation for newly created evidence. It is written after the executions as a reproducibility aid; it is **not** retroactive proof of older experiment invocations and does not replace receipt/code/source hashes.

Working directory for all commands below:

`D:\CodexProjects\ai-knowledge-compiler`

Interpreter environment: repository `.venv`.

## H1-E2 — tie/path dependence

Pre-seal validation:

```text
.venv\Scripts\python.exe -m py_compile research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\scripts\tie_path_dependence.py
.venv\Scripts\ruff.exe check research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\scripts\tie_path_dependence.py
```

The first sealed run failed during result-path serialization and produced no endpoint receipt. The failure and permitted serialization-only change are retained in `AMENDMENT_1_2026-08-19.md`.

Authoritative amended seal/run:

```text
.venv\Scripts\python.exe research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\scripts\tie_path_dependence.py freeze --output research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\receipts\seal-amend1-2026-08-19.json
.venv\Scripts\python.exe research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\scripts\tie_path_dependence.py run --seal research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\receipts\seal-amend1-2026-08-19.json --output research\experiments\H1-E2-TIE-PATH-DEPENDENCE-01\receipts\path-dependence-amend1-2026-08-19.json
```

## H1-F — all-stored natural revision regression

Pre-seal validation:

```text
.venv\Scripts\python.exe -m py_compile research\experiments\H1-F-REAL-CORPUS-EQUIV-01\scripts\run_real_corpus_equivalence.py
.venv\Scripts\ruff.exe check research\experiments\H1-F-REAL-CORPUS-EQUIV-01\scripts\run_real_corpus_equivalence.py
```

Authoritative seal/run:

```text
.venv\Scripts\python.exe research\experiments\H1-F-REAL-CORPUS-EQUIV-01\scripts\run_real_corpus_equivalence.py freeze --output research\experiments\H1-F-REAL-CORPUS-EQUIV-01\receipts\seal-2026-08-19.json
.venv\Scripts\python.exe research\experiments\H1-F-REAL-CORPUS-EQUIV-01\scripts\run_real_corpus_equivalence.py run --seal research\experiments\H1-F-REAL-CORPUS-EQUIV-01\receipts\seal-2026-08-19.json --output research\experiments\H1-F-REAL-CORPUS-EQUIV-01\receipts\all-stored-real-corpus-2026-08-19.json
```

## H1-A12 — local readiness audit only

These commands reproduce the local **readiness audit**, not the unexecuted 48-case GPU intervention arm.

```text
.venv\Scripts\python.exe -m py_compile research\experiments\H1-A12-01\scripts\audit_runtime_readiness.py
.venv\Scripts\ruff.exe check research\experiments\H1-A12-01\scripts\audit_runtime_readiness.py
.venv\Scripts\pytest.exe -q research\experiments\H1-A12-01\tests\test_analyze_policy_divergence.py benchmark\tests\v6\test_identity_and_registry.py
.venv\Scripts\python.exe research\experiments\H1-A12-01\scripts\audit_runtime_readiness.py
```

The targeted tests passed 11/11. The audit refused provider preflight/spend because earlier preregistered immutable-runtime and exact same-family-recipe gates were false.

## Claim/repro synchronization

```text
.venv\Scripts\python.exe -m py_compile tools\ip\sync_20260819_new_evidence.py tools\ip\build_claim_evidence_matrix.py
.venv\Scripts\ruff.exe check tools\ip\sync_20260819_new_evidence.py tools\ip\build_claim_evidence_matrix.py
.venv\Scripts\python.exe tools\ip\sync_20260819_new_evidence.py
.venv\Scripts\python.exe tools\ip\build_claim_evidence_matrix.py
.venv\Scripts\python.exe tools\repro\build_experiment_manifest.py
```

No command in this file should be used to infer the exact historical invocation of experiments not listed above.

---

## 2026-08-19 continuation — H1-I, H1-J, H1-K, H1-L, W6 recovery fixture

Each of these takes **no arguments**, so the invocation is fully determined and
is recorded as exact rather than as a template. Working directory as above.

```text
python research/experiments/H1-I-GATE-ORDERING-01/scripts/permute_gate_order.py
python research/experiments/H1-J-GOVERNANCE-FILTER-ABLATION-01/scripts/ablate_governance_filters.py
python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/probe_legacy_invariants.py
python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/audit_candidates_semanticity.py
python research/experiments/H1-K-LEGACY-INVARIANT-EXTRACTION-01/scripts/audit_pruning_ceiling_lemma.py
python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/run_exactness.py
python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/run_h1e_topologies.py
python research/experiments/H1-W6-SAME-INTELLIGENCE-01/scripts/recovery_fixture.py
```

Several of these were run more than once, because earlier runs were **VOID** or
were superseded. The command listed is the one that produced the authoritative
receipt; the superseded receipts are retained beside it and named in the relevant
amendment. Specifically:

- `permute_gate_order.py` — attempt 1 void (fidelity gate), attempt 2 non-separating.
- `ablate_governance_filters.py` — attempt 1 superseded by Amendment 1.
- `audit_pruning_ceiling_lemma.py` — attempt 1 mischaracterised the mechanism.
- `run_exactness.py` — attempt 1 VOID under protocol §6.

Because each script writes to a fixed output path, re-running reproduces the
current receipt, not the superseded ones. The superseded receipts were copied
aside before each correction and are the only record of those runs.

Package-level verification commands:

```text
python tools/ip/build_claim_evidence_matrix.py
python tools/repro/build_experiment_manifest.py --fail-on-drift
python tools/repro/build_execution_index.py
python tools/ip/audit_cross_document_consistency.py
python tools/ip/audit_manuscript_numbers.py
python -m pytest tests/unit/ -q
```

The W6 v6 acquisition is network-bound and is recorded separately in
`v6-launch-record-2026-08-19.json`; it is not reproducible offline.

## 2026-08-19 continuation, second pass — H1-L contract closure

```text
python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/run_future_path.py
python research/experiments/H1-L-CERTIFIED-SPARSE-MATCHER-01/scripts/run_full_contract.py
```

Both take no arguments. They exist because a red-team pass over our own work
found that the exactness harness did not compute every facet the frozen contract
lists — see `AMENDMENT_1_2026-08-19.md` §"Amendment 2" and hostile finding P15.

Package audits added in this pass:

```text
python tools/ip/audit_cross_document_consistency.py
python tools/ip/audit_manuscript_numbers.py
python tools/ip/build_submission_index.py
```
