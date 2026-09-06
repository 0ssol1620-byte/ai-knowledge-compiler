# USKC — Founder decisions, RESOLVED (2026-09-06)

Status: **binding product decisions**, given by the founder in chat on 2026-09-06 after the orchestrator's
`FOUNDER_DECISIONS_2026-09-06.md` (kept as the historical record of what was open). Where the two files disagree,
this file wins. Agents do not re-ask these. The only remaining approvals are real-world acts — signing a licence,
paying, enabling customer data, deploying to production — and for those the agent reports whether the conditions
below are met and stops before the act.

Vocabulary for every status word in this campaign (founder §42): `PRODUCTION_MAIN` · `IMPLEMENTED_NOT_MERGED` ·
`RESEARCH_PROVEN` · `RESEARCH_IMPLEMENTED` · `SHADOW_READY` · `EXPERIMENTAL` · `PROPOSED` · `BLOCKED`.

## Product law (founder §0)

Native first → Visual second → Reconcile → Detect information loss → Selective recovery → Independent verification →
Preserve exact evidence → Canonical IR → Knowledge compilation → Dependency / Ontology / Temporal state → Verified
Compiled World. Source updates: SourceVersion N → N+1 → Alignment → Logical identity → Typed diff → Dependency
closure → Selective recompile → Verify → Promote / Refuse.

## A. Public positioning — resolved

| # | Decision | Applies to |
|---|---|---|
| A-1 | "evidence back to the page" / "page number and bounding box" are not the long-term public abstraction. Base wording: **"Every compiled fact stays traceable to its exact source location."** Per-source examples: PDF page+region · XLSX sheet+cell/range · PPTX slide+shape · Email message+attachment/MIME part · JSON/XML pointer/path · Code commit+file+symbol/span · CAD/BIM object/GUID · Media timestamp/frame. Do not imply unqualified locators; show them beside `/sources` capability. Change lands in the release that integrates EvidenceLocator v2. | Lane G (site copy), after Lane D lands; `brand-copy.test.ts` lock updated deliberately in the same commit. |
| A-2 | Hero: **"Your AI needs more than searchable files. It needs a current, traceable world."** Supporting copy says TAVONEL *compiles* sources into that world. Banned: 100% accurate · never hallucinates · every file supported · lossless for every format · fully autonomous truth (plus the existing barred list). | Lane G. |
| A-3 | `/sources` is a primary product surface in primary navigation; it is the deployment capability truth surface, not a roadmap. Six tiers; `VERIFIED_*` never without a qualification receipt; no roadmap formats shown. | Lane D (`site-navigation.ts` primary row), Lane G (nav wording). |
| A-4 | The homepage flat connector list is removed/restructured. Only code-backed, currently reachable connectors are shown, each as `qualified` / `beta` / `enterprise-assisted` / `unsupported`. SMB/NFS/SFTP (no adapter/qualified route) are not shown as generally supported. Google Drive / Dropbox / Microsoft are not called production-qualified on the strength of code existence. | Lane G. |
| A-5 | Subprocessors page: source providers ≠ TAVONEL subprocessors. Dropbox/Microsoft are **not** added because connector code exists; only after the production customer-data architecture delegates processing to them and legal review confirms. | No change. |
| A-6 | `/trust`: any evidence mention carries a directly checkable evidence/receipt/link. `/status`: no empty state value — show NOT CONFIGURED / CLOSED / DISABLED / NOT QUALIFIED. | Lane G. |

## B. Architecture and semantics — resolved

| # | Decision | Applies to |
|---|---|---|
| B-1 | Final model is `Source ├ SourceVersion 1 ├ 2 ├ 3 …`. P0's `sourceId = documents.id`, one version per row, is a **compatibility shim**, not canonical. P1-A implements proper lineage using connector stable object id · canonical URI/provider object key · explicit replace/update operation · reliable lineage evidence. **Filename alone never identifies the same Source**; undecidable → new Source or unresolved identity. | Lane AB documents the shim as `IMPLEMENTED_NOT_MERGED` shim; P1-A. |
| B-2 | Tenant and Workspace are separate concepts (Tenant = organization/security/billing/policy; Workspace = working knowledge boundary). P0 does not migrate object keys, but the new domain model must not fuse `tenantId` and `workspaceId`. v2 key layout is a later migration + ADR. | Lane AB: distinct `tenant_id` and `workspace_id` columns/fields; no derivation of one from the other in code. |
| B-3 | EvidenceLocator v2 is a sibling of `SourceRef`; stored identity/hash compatibility preserved; new Canonical IR / Knowledge adopts v2 as primary evidence abstraction progressively. | Lane E (as contracted); P1-A propagation. |
| B-4 | Reader Registry (what representation can be read and how) and execution/model Provider Registry (where/how inference runs) stay separate abstractions; `akc_readers` orchestrates above the router/execution layer; adapters may connect them later. | Lane C (as contracted). |
| B-5 | Capability qualification and UI claim tone are separate axes, composed (e.g. `BEST_EFFORT` + `humanGate`; `VERIFIED_NATIVE` + `qualified`). | Lane D (as contracted). |
| B-6 | Canonical audit log for customer source/data security events = **`enterprise_audit_events`**. `foundation_developer_audit_events` stays for developer/API/configuration acts. No third table. | Lane F. |
| B-7 | Google Drive `trashed=false` deletion gap is **not** an acceptable production limitation. P0 records it; before any real-customer connector qualification, tombstone · delete · permission change · move/rename identity semantics are implemented and verified. Until then no connector is `VERIFIED`. | Lane F doc (status `BLOCKED` for connector qualification); P2. |
| B-8 | Original representation: pre-CDR bytes are the immutable original where available; the CDR-sanitized PDF is `normalized` (sanitized / rendered-derived), never `original`. Original is kept encrypted, isolated, non-executable, policy-controlled, access-audited. If retention deletes it, keep digest/tombstone/provenance and record that reprocessing capability for that Source is reduced. | Lane AB (representation kinds + doc); storage policy work in P1-A. |
| B-9 | Native Office readers are the first P1 product gap: **1 XLSX · 2 DOCX · 3 PPTX · 4 HWPX**. CDR/PDF conversion stays as security + rendered visual representation, **never as knowledge-extraction source truth**. | P1-B. |
| B-10 | `approved_customer_data = OFF`; no global activation. After tenant isolation · ACL snapshot · no ACL widening · connector permission semantics · encryption/storage · retention · deletion · audit · secret/token handling · incident/security controls · DPA/privacy disclosures · security suite · staging qualification are complete, enable for **allowlisted beta tenants** first; global availability is a separate later decision. | Lane F: gate decisions are per tenant/workspace (allowlist-shaped); activation flag stays false. |

## C. Third-party components — resolved

| # | Decision |
|---|---|
| C-1 | **PyMuPDF**: not adopted for the proprietary SaaS. Keep the permissive path (pypdf/pypdfium2). Re-list as a procurement candidate only if a benchmark shows a material gain and the commercial licence is economically justified. Never slipped in under AGPL. |
| C-2 | **MinerU — correction of the earlier register row.** Pin, as a receipt, the exact current revision's code licence, model-weight licence, additional terms and attribution requirement. Founder's reading: current official MinerU code is an Apache-2.0-based "MinerU Open Source License" with a large-commercial threshold and an online-service attribution condition; the `MinerU2.5-Pro-2604-1.2B` model card shows Apache-2.0. Therefore **MinerU is not excluded from production candidacy**; final use depends on Arena quality · latency · VRAM · cost · the pinned licence · required attribution. Poor Arena results → not used. Receipt: `research/MINERU_LICENCE_RECEIPT_2026-09-06.md` (orchestrator task, in flight). |
| C-3 | **HWP v5 (legacy binary)**: excluded from initial production support; manifest status `REVIEW_REQUIRED`; `pyhwp` not used; customers may be offered an HWPX/PDF conversion route. **HWPX**: `python-hwpx` is the default native-reader candidate; not `VERIFIED_NATIVE` without qualification; P1 verifies paragraph · table · styles · images · relationships · metadata preservation. |
| C-4 | **CAD**: ODA is not purchased now. Open formats first (IFC, STEP, IGES, open/native libraries), qualified before anything proprietary. `ReaderProvider` stays pluggable for a proprietary CAD adapter. ODA Sustaining + extensions are reconsidered only on evidence of a paid customer, a design partner or substantial pipeline demand — never for marketing breadth. |
| C-5 | **NeMo Retriever**: OSS parts usable as architecture reference, benchmark baseline, optional component. NVIDIA NIM is not a default production dependency; adoption only if an Arena/production benchmark shows a material gain for a specific component. OSS licence and NIM/container terms are not conflated. |
| C-6 | **Unstructured**: hosted Serverless API is not used for default ingestion (customer-data egress, third-party dependency, weakened evidence/control plane). Self-hosted `unstructured` OSS (Apache-2.0) may be evaluated as baseline/fallback after a dependency-graph and licence audit. |
| C-7 | **Google Document AI**: managed commercial baseline, external reference, optional enterprise fallback; not the default parser. Store the official price list with version/date as evidence; any customer-data route to Google needs its own privacy/subprocessor/tenant policy. Receipt: `research/GOOGLE_DOCAI_PRICING_RECEIPT_2026-09-06.md` (in flight). |

## D. Sequencing — resolved (founder §26, §27, §43)

1. **P0 (now):** finish the five lanes from their current diffs — existing-diff audit → contract comparison → missing
   work → implementation → targeted tests → full required tests → adversarial review → repair → rerun → evidence report.
2. **P0.5 Integration:** five lanes integrated; migrations/schema; capability truth surface; customer data stays
   disabled; full tests/build. Lane G (public positioning A-1…A-6) lands here, after D.
3. **P1-A:** proper SourceVersion lineage; compile-wire v2; SourceRepresentation propagation; EvidenceLocator v2
   propagation in the core.
4. **P1-B:** native readers XLSX → DOCX → PPTX → HWPX, each with a rendered visual companion.
5. **P1-C:** non-PDF evidence UI serializer; source-specific trace UI; qualification suite; first `VERIFIED_NATIVE`.
6. **P2:** connectors — `SourceConnector` contract, stable source ids, incremental sync, ACL capture, permission
   changes, tombstones, retention/deletion, connector qualification (B-7 is the gate).
7. **P3+:** adaptive ingestion/recovery productionization; broader source families.

## E. Research — resolved (founder §28–§40)

- The running Model Arena chain is not disturbed and runs to completion. No final model roles from partial results;
  offline complementarity analysis on existing outputs may continue. **Model selection only after the full Arena.**
- After Arena: build the quality (text, formula, table, TEDS, reading order, failure slices) · performance (median,
  p95, pages/hour, GPU/VRAM, parallel throughput) · economics (GPU-sec and API cost per 1k pages, effective infra cost)
  · complementarity (per pair: P(B correct | A wrong), P(B wrong | A wrong), joint failure, disagreement precision,
  continuous oracle gain) matrices. Then select roles by evidence: fast_primary · independent_peer · table_specialist ·
  formula_specialist · layout_specialist · degraded_scan_specialist · strong_resolver · external/reference ceiling.
  Second overall does not make a peer; what rescues the primary's failures does.
- Recovery research is promoted to core product R&D: FAST PRIMARY → LOSS DETECTOR → RECOVERY PLANNER → SPECIALIST /
  REGION RE-INFERENCE → INDEPENDENT VERIFIER → MERGE or UNRESOLVED. Existing development roles are preserved as
  historical decisions; no new confirmatory role freeze until Arena + complementarity results exist.
- Loss Detector looks for evidence that source information vanished or was transformed (native/visual mismatch,
  parser disagreement, region accounting, table topology, formula preservation, critical number/date/unit/currency,
  reading order, object coverage, chart data/label relation, comments/footnotes/track changes, witness coverage,
  authority/time, failure class) — never a single scalar blind-quality score. Recovery Planner chooses the cheapest
  reliable operation (crop, partial page, higher DPI, tiling, rotation, alternate parser/OCR, table/formula
  specialist, visual model, native parser, strong resolver) at Source → Unit/Page → Region/Object granularity.
  Recovery output is never auto-accepted; failed verification stays `UNRESOLVED`.
- KPIs: reliability (information retention, silent critical loss, semantic exactness, unresolved, evidence coverage,
  provenance) · recovery (rescue, false/missed escalation, strong invocations) · performance (p50/p95/p99, pages/hour,
  end-to-end latency) · economics (GPU-sec/1k, cost/1k, recovery overhead).
- Public benchmarks after Arena: consider PureDocBench, Dr.DocBench, Real5-OmniDocBench, OHR-Bench, then only needed
  slices. Native-structure GT generation for DOCX/XLSX/PPTX/HWPX/JSON/XML/HTML/Email; paired native → rendered PDF →
  scan → degraded scan → screenshot/photo to measure transformation loss.
- Research priority: **Tier A** Arena / complementarity / loss / recovery / routing / speed / cost · **Tier B** SFIR /
  evidence / identity / semantic preservation / dependency / selective recompilation / ontology · **Tier C** paper-only
  infrastructure (e.g. GitHub rate-window accounting, repeated seal mechanics) — never blocking product R&D.

## F. The evaluation order for any task (founder §41)

1. Does it reduce customer information loss? 2. Increase processing speed? 3. Reduce cost? 4. Safely widen supported
sources? 5. Improve knowledge freshness/traceability? 6. Strengthen TAVONEL's compiler moat? 7. Is it required for the
paper? None → lower priority.
