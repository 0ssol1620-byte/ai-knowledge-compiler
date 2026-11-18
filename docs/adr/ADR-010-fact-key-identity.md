# ADR-010: Identity by connector-declared fact key, decided per key pair, Protected Core unchanged

- Status: **proposed — benchmark-reachable only**. Legacy matching stays authoritative. No
  production connector is declared. The served app and API cannot select the keyed path.
- Date: 2026-11-18
- Work order: WO-D12-12 (lane `codex/v34-c-d12-12`); design `receipts/plan-20261117/d12-12-design.md`
  (PART A, mechanism) as corrected by `receipts/plan-20261117/d12-12-critique.md` (the critique
  wins where they differ); decisions D12-D11, D12-D12, D12-D12a, D12-D12b in
  `workorders/core-semantic.md`.
- Scope: `akc_product_core.fact_keys` (new), `akc_product_core.compiler` (constructor kwargs, a
  branch in `_compile_document`, labels), `akc_product_core.contracts` (receipt literal).
- Protected Core: `packages/cir-python/**` byte-identical. `knowledge_model.py` not edited. No
  threshold, weight or band moved.
- Changes digests of existing compiles: **no**. `fact_key_mode="off"` (the default) runs no new
  code, with or without declarations, and every pinned id/digest test is unchanged.

## Context

- **F-D12-4 / WO-D12-11** (`receipts/WO-D12-11/crosskey.json`, sha256 `95704a03…0aff`): on the
  100 U06 SEC pairs today's matcher pairs a current unit with a previous unit of a *different*
  fact key 5,808 times (70 pairs); 86% are the same tag at another period. Each scored
  `0.75 + 0.25·J` (only `source_continuity`, `structural_path` and the text similarity J are
  present), so the 0.92 bar is J ≥ 0.68 alone. The diff reported 5,481 of them as
  MODIFIED_CLAIM: a reader of the Change Center sees "value changed" where one period's row left
  and another period's row arrived.
- **D12-D10**: the key passed as a weighted identifier released 4 of 58 holds and left
  roll-overs ambiguous; rejected.
- **D12-D11**: keyed identity. Where a connector declares that its regions carry a
  source-assigned fact key, those units are decided by key and are not offered to fuzzy
  matching. Fuzzy matching stays for text without a declared key.
- The hard point (design A3): the semantic diff re-runs `assign_one_to_one` over every unit of a
  document. A compiler-only change disagrees with it (WO-D12-10's 57 rejected pairs). Only one
  arrangement agrees without a Protected Core change: per-key 1x1 calls on both sides.

### Step 0 (measured, no repository change)

| item | sha256 |
|---|---|
| `receipts/WO-D12-12/step0/keyed.json` | `292ee657498e850785acda46e464f7f24e2d47936bf0d533689d5f0ee00dd83c` |
| `receipts/WO-D12-12/step0/PREREGISTERED.md` | `d8aed0bb653221710017a50460f1f7fd3b216288b7f3aa346efb326729b3273d` |
| `receipts/WO-D12-12/step0/keyed_probe.py` | `9663e65c4ebf17b520669204107e634bf12e83ffa2908a0366903d86a60cc774` |
| `receipts/WO-D12-12/step0/per_pair.jsonl` | `da7725c8db1c6ee9d708e6763c26302bbb4cb63307200f45ca5771d456733368` |

Arm K-unit (the one built): 15 HOLD / 85 EQUAL against L's 58 / 42; 0 DIVERGED verdicts, 0
phantom, 0 compile errors, 0 rejected, 0 EQUIVALENCE_FAILED; compiler/diff agreement 24,821 of
24,821 keyed units and 7,839 of 7,839 gone keys; all 15,753 same-key matches preserved; holds not
worse in any stratum × date basis; cross-key MODIFIED_CLAIM 5,481 → 0 (true by construction);
280 REMOVED+ADDED pairs with identical text (re-keys). These were produced by wrapping the
compiler's calls, so they are an **estimate for WO-D12-13 to reproduce through this code**, not a
gate result, and none of them is identity accuracy: "same key = same fact" is the SEC adapter's
own definition.

## Decision

### 1. Declaration (`FactKeyDeclaration`)

`FactKeyDeclaration(connector_type, key_pattern, collision_suffix, evidence_ref, evidence_sha256)`,
frozen. Construction refuses an empty or non-Identifier `connector_type`, an empty or invalid
`key_pattern`, an invalid `collision_suffix`, an empty `evidence_ref`, an `evidence_sha256` that
is not 64 lowercase hex, and any `key_pattern` that full-matches one of the positional probes
(`docx-body-p-000001`, `html-body-1-p-3`, `pdf-page-0-text-<20 hex>`, `xlsx-sheet-0000-cell-A1`,
`pptx-slide-0001`, `srt-cue-000001`, `1.1_p0`, …; each a valid Identifier). The probe check is a
lint against an over-broad pattern, **not evidence** that a key is source-assigned: a positional
scheme that is not listed (say `^row-\d+$`) passes it (critique N2).

Declarations are passed only to the `ProductCoreCompiler` constructor. There is no registry, no
environment variable, and nothing is derived from a connector's name, a request field, document
content or the presence of `native_object_id`. `create_product_core_app`, `ProductCoreService`
and `__main__.py` take no such parameter (tested).

**Pinned SEC pattern (D12-D12b).** Step 0 ran `[A-Za-z0-9._:-]+-\d{8}m-\d+-[A-Za-z0-9._:-]+`
with collision suffix `-l\d+$` (`keyed.json` `key_pattern`, `collision_suffix`). That pattern
accepts `Revenues-20240331m-1-USD-dup`, the U06 `duplicate_region_text` fault's suffix
(`faults.py`), so the last group is tightened:

    SEC_FSDS_KEY_PATTERN      = [A-Za-z0-9._:-]+-\d{8}m-\d+-[A-Za-z0-9._:-]+(?<!-dup)
    SEC_FSDS_COLLISION_SUFFIX = -l\d+$

It still takes `…-USD-shares-l12`. It is a pinned constant, not a declaration: nothing is keyed
until a benchmark passes a declaration that names it (WO-D12-13).

### 2. Modes

`ProductCoreCompiler(..., fact_key_mode="off" | "candidate", fact_key_declarations=())`.
- `off` (default): no keyed code runs; output byte-identical with and without declarations.
- `candidate`: the keyed result is published and labelled `fact_key_v1` in
  `validation.matchingPolicy`, each canonical document's `metadata.matchingPolicy`,
  `validation/report.json` and `receipt.matchingPolicy`. Without a declaration it is a
  `ValueError`. An unknown mode or a connector declared twice is a `ValueError`.
- There is no shadow mode, sink or counts DTO (critique S2). The benchmark's two arms are the
  ladder's shadow rung; served shadow is WO-D12-14.

### 3. Which documents take the keyed path

A document takes the keyed path only if the mode is `candidate`, its `connector_type` is declared,
it has previous units, and its `content_sha256` differs from theirs (an unchanged document keeps
today's single diff call, which returns CONTENT_UNCHANGED). Then document-level detectors may keep
it on today's path; each refusal adds the review reason
`IDENTITY_FACT_KEY_REFUSED:{source}:{detector}`:
- **D-MISSING**: a current region without `native_object_id`, or a current key or previous anchor
  that is not an Identifier or does not full-match `key_pattern` (a mixed document included;
  previous anchors are unbounded `str` on the wire and are held to the Identifier shape before
  they decide identity or appear in a review reason).
- **D-DUP**: two keys of one version (either side) equal under the identity fold
  (`normalize_text_for_identity`) or equal after stripping `collision_suffix` and folding; or a
  current key that folds to a previous key while differing from it raw (critique N1).

Eligibility is all-or-nothing per document; a document with keyed and unkeyed regions is a legacy
document.

### 4. Compiler decisions for a keyed document

- Current key k with a previous unit P(k) (same folded key): one **unchanged**
  `assign_one_to_one([fp(C)], [fp(P)])`. The outcome is used as is: MATCHED inherits P's logical
  id; AMBIGUOUS goes down the existing hold path (`ku_unresolved`, `IDENTITY_AMBIGUOUS`); NEW
  keeps the seed and the diff reports P removed.
- Current key with no previous unit: `assign_one_to_one([fp(C)], [])` — NEW with today's seed
  `logical_id_seed(source, path, k)`.
- Previous key gone: no current unit; the diff reports UNIT_REMOVED.
- Keyed units are never offered to the document-wide matching, so no unit is paired across keys.
- **D-SEED**: a keyed NEW unit whose seed equals any previous unit's logical id is held like an
  ambiguous one (legacy history can hand one key's seed id to another key's unit). This extends
  F-D12-2's rule, which counts only current holders.
- **D-RELOC, per unit, counted, never refusing (D12-D12, arm K-unit)**: a current unit whose
  folded text is unique in its version and stands, unique, under another key in the previous
  version adds `IDENTITY_FACT_KEY_RELOCATED:{source}:{previous key}->{current key}`. This is how
  the re-key events (Step 0: 280 REMOVED+ADDED with identical text) are told apart from real
  removals. D-CHURN is not a separate detector: with a shared unique text it is D-RELOC on every
  such unit (critique B1).

### 5. Semantic diff for a keyed document (Protected Core byte-identical)

The single `diff_documents` call is replaced by unchanged calls whose changes are concatenated:
one STRUCTURAL call with the document shapes (exactly the structural prefix of today's call); one
GRAPH call per current unit in region order with `[P(k)]` or `[]` against `[unit]`; one per gone
previous key with `[P]` against `[]`. Each per-key call runs inside the diff the same 1x1 matcher
call the compiler ran (same fingerprints, same lineage, default resolver), so the diff's
`changed_logical_ids` name the units the compiler produced and `verify_equivalence` sees the same
plan. Ordering differs from one call in one place: a NEW split emits its UNIT_REMOVED inline, and
gone keys come last (candidate output only).

**Runtime agreement invariant (critique S3).** After each per-key call: MATCHED emits no
UNIT_ADDED, UNIT_REMOVED or IDENTITY_UNRESOLVED, and every change names P's id; AMBIGUOUS emits
exactly one IDENTITY_UNRESOLVED naming P and no add/remove; NEW emits exactly one UNIT_ADDED on
the unit's id and a UNIT_REMOVED of P iff P exists; a gone key emits exactly one UNIT_REMOVED of
P. Any mismatch raises `FactKeyDisagreement` (a `ValueError`) carrying source id, key, decision
and change kinds — ids only, never text. It holds by construction today; it guards a future
resolver default change or a caller that passes a resolver to one side only.

### D12-D12a — the narrowing, as a decision

D12-D11 said "same key → MATCHED". What is built is narrower: a same-key pair is MATCHED only
when the unchanged band accepts that pair alone, so same-key identity is bounded by **text and by
path**:
- text no longer similar (J low, or a short row such as `Revenues: 1000 USD.` → `1200`) → held;
- page move with identical text (structural path 2/3) → AMBIGUOUS, held;
- block-type change → AMBIGUOUS, held;
- title change → NEW (score 0.667): every keyed fact of the document is split into REMOVED+ADDED.

No SEC run can show the path cases (one page, constant title per statement); they are pinned by
tests here, and a production declaration must measure them. Forcing MATCHED on key equality alone
is a Protected Core contract change (`diff_documents(assigned=…)`), not scheduled (WO-D12-15).

### D12-D12b — repeated text under a declared key

For declared documents the U06 fault `duplicate_region_text` is expected `equal_or_hold` instead
of `hold`: distinct keys separate identical text. D12-D8's hold stays for undeclared documents.
With the pinned pattern the fault's `…-dup` region is not a key, so the faulted document is
refused (D-MISSING) and stays on today's path, which holds (tested).

### 6. Logical ids and existing worlds

- NEW keyed units use today's seed formula; MATCHED units inherit the previous id. Cold compiles
  are identical in both modes except the label (tested).
- No id of an existing world is rewritten. A world whose lineage was built by legacy cross-key
  merges keeps those ids; the keyed path continues each id under its current key (tested with an
  off → off → candidate chain, critique S6). Earlier merges are history and are not undone.
- A keyed MATCH to a previously held unit inherits its `ku_unresolved_*` id and marks it
  matched — as legacy does; it is now decided by key (critique N5).
- The only contract edit is the receipt literal `matching_policy: Literal["legacy","fact_key_v1"]`.

## What changes for a reader (costs, stated)

- A text-identical re-key shows REMOVED+ADDED where legacy showed nothing (critique N4); each is
  recorded by `IDENTITY_FACT_KEY_RELOCATED`.
- Rotated keys (a wrong declaration's signature) are decided per key against each key's own past;
  similar table rows pass the band and are merged under the key, visible as MODIFIED_CLAIM plus
  the relocation reasons. The detector records, it does not refuse (D12-D12).
- Renumbering *with* edits is invisible to D-RELOC (exact-text evidence only).
- Review reasons (refusals, relocations) move a candidate world to `review_required`; the U06
  judge does not read review reasons.

## Deviations from the Step 0 emulation (for WO-D12-13 to measure)

- D-DUP across versions by fold (N1) was not a refusal in Step 0, which matched 2 key pairs equal
  only after folding; those documents now take today's path with `IDENTITY_FACT_KEY_REFUSED:…:D-DUP`.
- The pinned pattern rejects keys ending in `-dup`; Step 0's did not.
- Step 0 added no review reasons; the build adds refusal and relocation reasons.

## Not in scope

- `packages/compiler-runtime/src/akc_compiler_runtime/pipeline.py:353` and `:705` are a second
  matcher + diff path; it keeps legacy (critique N6).
- `api.py:105` (`/health` `matchingPolicy: "legacy"`) and
  `packages/product-core/scripts/verify_deployment.py:123` stay "legacy". They are correct while
  candidate is unreachable from the served app; a served change must update them (critique N8).
- `benchmark/**` (WO-D12-13: harness passthrough, SEC declaration, arms report), served shadow and
  any production declaration (WO-D12-14), the Protected Core contract (WO-D12-15), F-D12-6
  (unkeyed text keeps `0.75 + 0.25·J`).

## Production declaration requirements (before any canary)

An ADR amendment and an independent reviewer, with evidence that (i) the source's key definition
is pinned by sha256; (ii) a stability receipt shows the detectors and the D12-D12a path cases on
that connector's real version pairs; (iii) Foundation assigns `connector_type` on the server and a
tenant cannot choose it; (iv) previous units' `anchor` round-trips unchanged through Foundation
storage — it decides identity here, while today it is not scored.

## Rollout and rollback

Ladder: contract (this ADR, WO-D12-12) → shadow and benchmark (WO-D12-13, off vs candidate on
one commit) → canary needs a production declaration; none exists, so the ladder stops at the
benchmark. Rollback: mode `off` (the default) or drop the declaration. No new contract field
exists, so a world compiled under candidate is readable by an off compiler; its next off compile
uses legacy matching again (roll-overs return as MODIFIED_CLAIM). `matchingPolicy` records which
policy produced each version.

## Residual risks

- SEC keys omit the FSDS taxonomy `version`; a plain key can denote another (namespace, tag)
  fact in the next filing, and a similar text passes the band. The fix belongs in the adapter key.
- A source that reuses a key for similar content (J ≥ 0.68) is merged, visible only as
  MODIFIED_CLAIM.
- `connector_type` and previous anchors are request data; under this ADR an anchor decides
  identity.
- The 0.75/0.92 bands still bound the keyed path, and they are uncalibrated.
- `IDENTITY_AMBIGUOUS` and the new review reasons carry keys (ids), as today's carry anchors.
