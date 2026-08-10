# v3.1 Phase Gap Matrix

*N41 Phase 0 deliverable — "current architecture gap matrix". Written 2026-08-10.*

Masterplan v3.1 changed the governing phase order. The §44 PHASE 0–11 numbering
this repository had been following is PART C, the lowest-precedence part of the
document; **N41's Phase 0–17 supersedes it**. This matrix maps what exists to the
new numbering and says plainly what does not exist.

The column that matters is the last one. "Built" means there is code with tests
that a reviewer can run. It does **not** mean measured, calibrated, or deployed —
where a threshold is a guess, the module says so in its own output.

---

## Phase map

| N41 Phase | Subject | State | Where |
|---|---|---|---|
| 0 | Freeze, inventory, legal/supply-chain gate | **Built** | `CLAUDE.md`, this file, `infra/supply-chain/verified-pins.json` |
| 1 | Deterministic contracts and test harness | **Partial** | `akc_cir` contracts exist; N13's IR v3 top-level shape not adopted |
| 2 | Secure ingest / preflight / R2 manifest | **Not built** | N3's per-format preflight (PDF/DOCX/archive) absent |
| 3 | Profiler / reference renderer / model registry | **Not built** | N4 features, N7 registry with `license_state` gate absent |
| 4 | Deterministic router / execution planner | **Partial** | `akc_parallel_runtime.routing` exists; N5's thresholds, abstention and route receipt absent |
| 5 | Parser adapters / RunPod commit protocol | **Partial** | campaign harness runs MinerU/PaddleOCR/DeepSeek; N28's R2-before-ACK and heartbeat contract not formalised |
| 6 | Inspector / failure taxonomy / recovery | **Built** | `akc_cir.inspection`, `akc_cir.recovery_policy` |
| 7 | Document Reconciler | **Built** | `akc_cir.reconciler` |
| 8 | IR / provenance / stable identity | **Built** | `akc_cir.identity` (N15-conformant) |
| 9 | Entity / authority / temporal / epistemic / security | **Partial** | authority (N17) and temporal (N18) built; **entity resolution (N16) absent**; injection labels (N19) built; review queue absent |
| 10 | Diff / dependency / impact | **Built** | `akc_cir.semantic_diff`, `akc_cir.dependency` |
| 11 | Selective recompile / world state | **Partial** | `akc_cir.recompilation` built; **atomic world-state publish (N22.3) absent** |
| 12 | Retrieval / API / MCP | **Not built** | N23 permission-first retrieval, N24 MCP contract absent |
| 13 | Health Scan / commercial core | **Not built** | N37, X11 billing absent |
| 14 | Product UI / website / cinematic / evidence | **Partial** | product surfaces and evidence page exist; §26–30 cinematic hero not built |
| 15 | Competitive / research publication | **Partial** | campaign evidence published; N34 same-condition competitor run not done |
| 16 | Enterprise hardening | **Not built** | SSO/RBAC/retention/audit export, restore drill absent |
| 17 | Decision replay / write MCP / simulation | **Not built** | gated on demand and governance by the masterplan itself |

## v3.1 closure sections (PART B2)

None of X1–X16 is built. Listed so the gap is named rather than implied:

| § | Subject | Note |
|---|---|---|
| X1 | Semantic Model Gateway | task taxonomy, structured-output contract, model cache keying |
| X2 | Embedding / reranking contract | needed before any retrieval claim |
| X3 | Structure-aware chunking | X17.1 forbids one fixed-token chunker for all documents |
| X4 | Office dual path | X17.1 forbids trusting native XML *or* visual render alone |
| X5 | Document identity / dedup / revision graph | rename vs copy vs branch |
| X6 | Connector change capture and ACL sync | X17.1 forbids letting a revoke wait for a background reindex |
| X7 | Multi-tenant scheduler / GPU residency | |
| X8 | End-to-end search / answer / citation evaluation | |
| X9 | Deterministic blueprint compiler and exports | |
| X10 | Public API / streaming / webhooks / SDK | |
| X11 | Credits / billing / unit economics | |
| X12 | Human review / feedback / active learning | |
| X13 | Zero-downtime schema / model / runtime release | |
| X14 | Competitive reality checklist | |
| X15 | GTM execution system | |
| X16 | Solo-founder critical path | |

---

## What changed in existing code because v3.1 outranks what it was built from

**Identity thresholds (N15.4).** The merge bar was 0.72 and is now 0.92; the
new-identity floor was 0.35 and is now 0.75. Invariant 10 is the reason — a false
merge rewrites a clause's history and no temporal query afterwards can detect it,
while a false split is two identities a reviewer can join. The four signals became
N15.2's seven.

**Missing signals stopped being zeros (N4.4).** This was not cosmetic. Most prose
carries no explicit clause identifier; scoring that signal zero caps such a unit at
0.85, permanently under the new 0.92 bar, so nothing would ever merge. Scores are
now renormalised over the signals that have values, absences carry a reason, and an
absent *critical* signal abstains instead of letting the rest renormalise into a
confident number.

**One-to-one assignment (N15.3).** Resolving each unit independently let two new
units both claim the same old one — each locally reasonable, together a history
that forked with nobody deciding to fork it.

---

## Deliberate non-claims

- **No threshold in this codebase is calibrated.** `CalibrationTable.calibrated`
  is `False` and refuses to be set true without naming a corpus. N9.9's targets
  (catastrophic recall 100%, failure recall ≥95%, false escalation ≤15%) are
  internal and, per the masterplan, not claimable before they are met.
- **The blind quality-detection hypothesis was not supported** by the campaign,
  and nothing here reverses that. The inspector deliberately has no scalar quality
  score.
- **Phases 2–5 being partial means the compiler core has no production front
  end.** The modules built here are exercised by tests and by the campaign
  harness, not by a live ingest path.
