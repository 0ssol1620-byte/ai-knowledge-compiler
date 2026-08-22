# AKC Parallel Runtime

This package is the persistence-agnostic domain core for Structara v6 parallel
document processing. It implements deterministic sharding and routing,
append-only attempt lineage, dual worker health, fail-closed validation and
arbitration, smallest-scope recovery, continuity-aware merging, fair scheduling,
hedging, and exactly-once credit settlement.

The core deliberately treats every model output as an untrusted candidate.
Transport success never implies semantic success, hard-gate failures are never
scored, unresolved conflicts remain non-billable, and duplicate compute is
recorded as telemetry but cannot produce duplicate user charges.

The package has no provider, database, or network dependency. Production
adapters persist the immutable records and domain events declared here. This
separation makes all safety and idempotency invariants deterministic and fully
testable without fabricating external infrastructure evidence.

## Contract map

| v6 concern | Module | Enforced invariant |
|---|---|---|
| Endpoint topology | `topology.py` | One model revision and runtime stack per pool; immutable worker membership |
| Adaptive sharding | `sharding.py` | Continuity groups stay atomic; each page has one owner; overlap is context-only |
| Adaptive routing | `routing.py` | Health/capability/policy filtering precedes deterministic quality-cost-latency ranking |
| Cascade and hedge | `routing.py`, `scheduling.py` | Early exit only creates an arbitration candidate; at most one hedge per logical attempt |
| Attempt lineage | `attempts.py` | Outputs and validation receipts are immutable; retry, recovery, and hedge are new children |
| Dual health | `health.py`, `failures.py` | Infrastructure and semantic failures use separate actions; canary reproduction can quarantine |
| Validation | `validation.py` | Required levels need immutable evidence; HTTP 200 alone can never pass |
| Arbitration | `arbitration.py` | Authority and native evidence outrank models; majority alone is not truth |
| Recovery | `recovery.py` | Cell-to-page-group escalation; base result and repair diff are preserved |
| Continuity | `continuity.py` | Ownership, provenance, rows, pages, headings, tables, captions, and footnotes are conserved |
| Credits | `credits.py` | Exactly one canonical charge per accepted logical work item; duplicate compute is telemetry only |
| Finalization | `finalization.py` | Unresolved work is manifested and non-billable; quarantined and failed work is excluded |
| Benchmark repeats | `benchmark.py` | Three repeats share one immutable environment and isolated artifact namespace |
| Persistence integration | `contracts.py` | Exact v6 table/event names and chronological idempotent event projection |

## Local verification

From the repository root:

```powershell
$env:PYTHONPATH='packages\parallel-runtime\src'
.venv\Scripts\python.exe -m pytest packages\parallel-runtime\tests -q
.venv\Scripts\python.exe -m ruff check packages\parallel-runtime
$env:MYPYPATH='packages\parallel-runtime\src'
.venv\Scripts\python.exe -m mypy --strict packages\parallel-runtime\src\akc_parallel_runtime
```

These checks prove the local domain core only. Provider capacity, real GPU
latency/cost, managed database durability, and public/private benchmark quality
remain external evidence gates and are intentionally not asserted here.
