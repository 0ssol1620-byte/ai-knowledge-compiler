# W1 — Protected Core Activation Architecture Plan

**Status: `W1 PROTECTED CORE ACTIVATION PLAN READY`** — with a blocking
methodology finding that must be resolved before this plan is treated as
actionable against a specific branch. Research/design only. No Protected
Core code was modified. No migration was written. Worktree
`D:\CodexProjects\ai-knowledge-compiler-w1`, branch
`agent/tavonel-w1-protected-core-activation`, base `origin/main`@`185d04b`.

---

## Branch/worktree discrepancy — read this section first

**`OBSERVED`, independently reconfirmed by the orchestrator:** none of the
four target Protected Core modules (`authority.py`, `temporal.py`,
`dependency.py`, `world_state.py`) exist anywhere under
`packages/cir-python/src/akc_cir/` in this W1 worktree, in `origin/main`, or
in the `agent/tavonel-surface-integration` branch — the same branch W0
(`docs/integration/W0_WORLD_SEMANTIC_SOURCE_OF_TRUTH_RECONCILIATION.md`) is
committed on and claims to have read them from.

They exist **only** on `agent/folynta-trust-integration-v1` — the Security
worktree, which is also the branch this orchestrating session itself has
had checked out throughout. That branch diverges from `origin/main` at the
same commit (`185d04b`) W1 was created from, and is confirmed **not** an
ancestor of `origin/main` (`git merge-base --is-ancestor HEAD origin/main`
→ false from that worktree). The Protected Core files are real, and their
content matches what W0 described — but W0's own "read-only against the
Surface Integration worktree" framing was not accurate. The most likely
explanation, consistent with L1's independent same-day finding (see below),
is that the researcher who wrote W0 inspected the orchestrator's own
working directory (`D:\CodexProjects\ai-knowledge-compiler`, on
`agent/folynta-trust-integration-v1`) rather than the worktree it was
nominally scoped to.

**This is not an isolated W1 finding.** L1 (dispatched in the same round,
different worktree, no shared context) independently discovered the
identical pattern for a different capability: `Collection.manifest_revision`/
`discovered_files`/`duplicate_files` and `collection_events.py` — the basis
for W0's capability-1 `S1` classification — exist only on
`agent/folynta-trust-integration-v1` and sibling Security-lineage branches
(`tavonel-v5-cinematic`, `tavonel-cinematic-v2`, `tavonel-ip-research`,
`tavonel-absorption-research`), confirmed via `git merge-base
--is-ancestor d7a6b30 HEAD` returning false against both the L1 worktree
(based on the I3 integration candidate) and the Surface Integration branch.

**Net effect:** W0's matrix is accurate as a description of code that
exists on `agent/folynta-trust-integration-v1`, but that branch is not
integrated into `origin/main`, the Product App lineage, the Commercial
Shell lineage, the Surface Integration lineage, or the I3 integration
candidate L1 was told to build from. Every prior claim that W0 was
"independently spot-checked" against those lineages should be treated as
unverified for the actual target branches — the orchestrator's earlier
spot-checks were run from a working directory that happened to be checked
out to the one branch that does have this code, which produced false
confirmation. **This plan is written against the Protected Core modules'
real content (read via `git show agent/folynta-trust-integration-v1:<path>`,
read-only, no checkout, no worktree modified) and is valid as a design once
that branch's Protected Core commits are reconciled into whichever lineage
W1's implementation is meant to target — it is not yet actionable as-is
against the W1 worktree's own checked-out tree.**

Every claim below about "what exists in the W1 worktree" is `OBSERVED` as
absent; every claim about the algorithms themselves is sourced to
`agent/folynta-trust-integration-v1`, not to this worktree.

---

## Capability 3 — Authority / applicability

- **Source** (`OBSERVED`, `packages/cir-python/src/akc_cir/authority.py` on
  `agent/folynta-trust-integration-v1`): `ScopedClaim` (frozen dataclass:
  `claim_id, subject, value, authority: AuthorityClass, source_status,
  scope: dict[str,str], valid_from, valid_to, recorded_at,
  required_permission, evidence_id`), `ClaimContext` (`subject, as_of,
  object_id, customer_id, region, contract_id, permissions`),
  `rank_claims()` and `resolve_authority()`. Ranking is a fixed
  lexicographic tuple: `permission_visible → temporal_valid → scope_match →
  explicit_override → authority_rank → specificity → source_status →
  recency` — not a weighted score. Ties on every element with differing
  `value` produce `ResolutionStatus.CONFLICTED` with `required_review=True`
  — the module refuses to average or pick-newest.
- **Do not confuse with**: `services/api/src/akc_api/collection_authority.py`
  + `AuthorityMapping`/`AuthorityFact` in `models.py` — a numeric-fact ↔
  source-region matcher for verified external data (e.g. DART XBRL
  ingestion), already wired into `services/api`. Same name-collision
  pattern W0/I1.5 already documented elsewhere. This plan does not touch it.
- **Invocation point** (`PROPOSED`): a claim becomes a `ScopedClaim` at the
  moment a knowledge unit is compiled from a scope-bearing source (explicit
  applicability language — "this policy applies to...", a defined term, a
  contract party). The natural real hook is the existing per-document
  compile step that already produces `Block`/knowledge-unit rows.
  `resolve_authority()` runs on read — a query/ASK path calling it when it
  needs "what applies here," not a batch job. **Dependency worth naming
  explicitly:** there is no existing ASK/query path in this repo (E0
  independently confirmed capability 8 as `S4`/absent) — authority
  resolution has no consumer to attach to until ASK exists at all.
- **Persistence** (`PROPOSED`, minimal): one `scoped_claims` table mirroring
  the dataclass 1:1. No separate resolution-cache table — `resolve_authority()`
  is a cheap in-memory tuple sort over a handful of candidate claims per
  subject; do not build a cache before it's shown to be needed.
- **Transaction boundary** (`PROPOSED`): commits in the same transaction as
  the compiler's existing knowledge-unit write — `session.add()` + flush
  inside the caller's existing transaction, following the same pattern
  `_emit_collection_event` already uses.
- **Idempotency** (`PROPOSED`): `UniqueConstraint(collection_id, logical_id,
  source_content_sha256)` — a re-run on unchanged content is a no-op,
  mirroring `collection_events`'s existing `UniqueConstraint(collection_id,
  sequence)`.
- **Tenant/security boundary** (`OBSERVED` pattern to reuse):
  `packages/security/src/akc_security/tenant_context.py` — RLS already
  enforced on 106 tables via `app.tenant_id` set with `SET LOCAL` inside
  `enter_tenant_context`, fail-closed on missing/mismatched tenant.
  `scoped_claims` needs `tenant_id NOT NULL` under the same RLS policy
  family — no bespoke boundary.
- **Versioning** (`PROPOSED`): claims are append-only — a policy amendment
  is a new row with its own `valid_from`/`recorded_at`, superseding rather
  than overwriting, falling directly out of the dataclass's existing
  bitemporal fields.
- **Eventization** (`PROPOSED`): no event on ingestion alone — a claim
  existing is not user-visible product state. `authority.claim.recorded.v1`
  is a candidate, deferred until ASK gives it a real consumer. Do not
  invent a consumer to justify the event.
- **Failure semantics** (`PROPOSED`): claim persistence and compile output
  share one transaction — no partial-claim state possible.
- **Backfill** (`PROPOSED`): idempotent re-run of the (to-be-built) claim
  extraction step over already-compiled collections, keyed by the same
  uniqueness constraint — safe to re-run repeatedly.
- **Performance path** (`PROPOSED`): extraction in the existing background
  compile worker (same cost class as identity resolution, which already
  runs there); `resolve_authority()` in the synchronous query path once ASK
  exists.
- **Algorithm challenge**: none found — the CONFLICTED-not-average behavior
  and fixed tuple order match the module's own cited masterplan sections
  verbatim; no test/code evidence the algorithm itself needs changing.

## Capability 4 — Temporal state

- **Source** (`OBSERVED`, `temporal.py`): `TemporalFact` (bitemporal:
  `valid_from/valid_to` = reality axis, `recorded_at/superseded_at` =
  system-knowledge axis, `temporal_source: EXPLICIT/INFERRED/UNKNOWN`),
  `TemporalTimeline.as_of(valid_at=, known_at=, logical_id=, policy=)`.
  `__post_init__` refuses to construct a fact claiming
  `temporal_source=EXPLICIT` with no date (raises `ValueError`) — a
  fail-closed guard already in the algorithm, consistent with `CLAUDE.md`'s
  "no fabricated/inferred date stored as fact."
- **Do not confuse with**: `FileVersion.status`
  (`candidate/active/superseded/rejected/purged`) — file-version grain, not
  knowledge-unit grain. Same name-collision W0 flagged; not repurposed here.
- **Invocation point** (`PROPOSED`): same compile step as capability 3, for
  any unit whose source states or implies a validity window. Natural real
  trigger: `FileVersion` transitioning `candidate` → `active` (the closest
  real "a new revision was committed" lifecycle signal already in the
  schema). `as_of()` is a read-path query, same posture as
  `resolve_authority()`.
- **Persistence** (`PROPOSED`, minimal): `temporal_facts` table 1:1 with the
  dataclass. Indexes on `(tenant_id, logical_id)` and `(tenant_id,
  valid_from, valid_to)` only, until query volume says otherwise.
- **Transaction boundary** (`PROPOSED`): commits with the `FileVersion`
  status transition / compile output that produced it, one transaction.
- **Idempotency** (`PROPOSED`): `UniqueConstraint(logical_id, valid_from,
  recorded_at)` or a deterministic content hash of the fact tuple.
- **Tenant/security boundary**: identical to capability 3.
- **Versioning**: this capability *is* versioning — `superseded_at` retains
  prior facts by design; nothing additional needed.
- **Eventization** (`PROPOSED`): deferred for the same no-consumer reason as
  capability 3. If a "temporal state changed" UI surface is built later,
  emit only after the row is durably committed.
- **Failure semantics**: same reasoning as capability 3 — one transaction,
  no partial state.
- **Backfill** (`PROPOSED`): idempotent re-run over existing `FileVersion`
  rows keyed by the uniqueness constraint above.
- **Performance path** (`PROPOSED`): extraction in the background compile
  worker; `as_of()` query in the synchronous read path once a consumer
  exists.
- **Algorithm challenge**: none found — the `EXPLICIT`-without-a-date guard
  is stricter than a naive implementation would be, evidence the algorithm
  is already conservative in the right direction.

## Capability 6 — Semantic change impact (required special focus)

### What `impact_of()` actually requires as input

`OBSERVED` (`dependency.py` on `agent/folynta-trust-integration-v1`):
`DependencyGraph.__init__(edges: Iterable[DependencyEdge] = ())` builds the
graph **entirely in memory** from an iterable of `DependencyEdge(source_id,
target_id, edge_type, valid_from=None, valid_to=None)` — no loader, no DB
call, no lazy-fetch anywhere in the class. The class docstring states this
plainly: *"Postgres is where this lives in production (§15 names an
adjacency table and a recursive CTE). This is the same semantics in
memory."*

`impact_of(changed: Sequence[str], *, max_depth=None, as_of=None) ->
ImpactReport` — `changed` is a plain sequence of logical IDs. The module's
own docstring names `semantic_diff.SemanticDiff.changed_logical_ids` as the
intended seed-set producer; that function explicitly excludes
`IDENTITY_UNRESOLVED` changes — *"Marking artifacts stale from an identity
nobody established would spread a guess across the graph."* Traversal is
breadth-first over adjacency dicts built purely from whatever edges were
passed to `__init__`; direction per-`EdgeType` follows a fixed
`Propagation` mapping (`DEPENDS_ON`/`DERIVED_FROM`→UPSTREAM,
`SUPPORTS`/`CONSUMED_BY`/`EXPORTS_TO`/`INVALIDATES`→DOWNSTREAM,
`REFERENCES`/`SUPERSEDES`→INERT, never propagates). `ImpactReport` carries
`changed`, `affected: tuple[ImpactPath,...]` (node_id/depth/via),
`truncated_at_depth`, `cycles_detected`, `unknown_nodes`. `by_kind(kinds:
dict[str,str])` produces per-kind counts — the caller supplies the `kinds`
mapping; the module has zero opinion on what a "knowledge unit" vs. "AI
context" is.

### Why persisted edges are absent today

`OBSERVED`: grepping `services/api`/`services/scheduler` (on
`agent/folynta-trust-integration-v1`) for imports of `akc_cir.dependency`,
`.authority`, `.temporal`, `.world_state`, `.semantic_diff`, `.reconciler`,
`.recompilation` returns zero matches. No migration or model defines any
`DependencyEdge`/adjacency table. `INFERRED`: this is structural, not a
bug — nothing in the running system ever constructs a `DependencyEdge`,
because nothing calls `DependencyGraph.add()`. The class was built and
unit-tested (`tests/unit/test_dependency.py`, present in the tree) entirely
against synthetic edges the test file constructs itself. There is no "edges
exist but aren't persisted" state — there is no code path anywhere that
produces an edge from real compiled content.

### Minimal trustworthy path (the design)

```
semantic change detected (semantic_diff.diff_documents at revision commit)
  -> SemanticDiff.changed_logical_ids  (seed set, already excludes unresolved identity)
  -> dependency edges for the changed collection loaded from `dependency_edges`
     table into an in-memory DependencyGraph  (edges populated by the compiler
     at the SAME step that already resolves identity/builds knowledge units)
  -> DependencyGraph.impact_of(seeds)   -> ImpactReport
  -> durable `impact_reports` row persisted (changed ids, affected ids+paths,
     truncated flag, cycles, unknown_nodes, kind-counts against the kind
     mapping the compiler already has)
  -> ProductEvent (`change.impact.computed.v1`) emitted, referencing the
     impact_reports row id -- only after that row is durably committed
  -> CHANGE UI polls/receives the event and renders the REAL by_kind() counts
```

- **Where edges come from** (`PROPOSED`, the actual missing layer): must be
  derived by the compiler as a side effect of the existing
  identity/reconciliation/knowledge-unit-build step
  (`collection_semantic_runtime.py:19-29` calls
  `akc_cir.knowledge_model.build_knowledge_object` in production, per W0).
  A chunk built from a clause is a `DERIVED_FROM` edge; a RAG chunk consumed
  by an agent workflow is `CONSUMED_BY`. This derivation logic does not
  exist today at any grain — it is new work, not activation, unlike
  capabilities 3/4/7 which have a fully-formed algorithm sitting idle.
- **Persistence** (`PROPOSED`, minimal): two tables — `dependency_edges`
  (mirrors `DependencyEdge` 1:1, plus `tenant_id`/`collection_id`) and
  `impact_reports` (one row per computed impact, referencing the triggering
  `change_id`, storing `ImpactReport` fields plus flattened `by_kind`
  counts). Not one table — an edge is ongoing graph state, a report is a
  point-in-time computation result; conflating them would mean every edge
  mutation invalidates stored reports, complexity this capability doesn't
  need yet.
- **Transaction boundary** (`PROPOSED`): edge writes commit with the compile
  step that derived them. `impact_reports` + triggering event commit
  together in a separate transaction, at revision-commit time, after
  `impact_of()` runs against the now-durable edges.
- **Idempotency** (`PROPOSED`): `dependency_edges` gets
  `UniqueConstraint(source_id, target_id, edge_type)` (an edge is a fact,
  re-deriving it is a no-op). `impact_reports` gets
  `UniqueConstraint(change_id)`, matching `SemanticDiff.change_id`.
- **Tenant/security boundary**: `tenant_id`/`collection_id` on both tables,
  same RLS regime.
- **Versioning** (`PROPOSED`): edges use the dataclass's existing
  `valid_from`/`valid_to` — a closed, not deleted, edge — mirroring
  `impact_of`'s own `as_of` parameter. `impact_reports` rows are themselves
  append-only history.
- **Eventization** (`PROPOSED`): `change.impact.computed.v1` fires strictly
  after the `impact_reports` row commits — never compute-then-announce-then-
  persist. If persistence fails, nothing fires.
- **Failure semantics** (`PROPOSED`): `impact_of()` success with a failed
  `impact_reports` insert rolls back and shows nothing — recomputation is
  cheap since `impact_of()` is pure. If the insert succeeds but eventization
  fails, the existing outbox pattern (`infra/postgres/*`, a real
  `outbox_events` table with RLS-gated `published_at`) is the precedent:
  write the event row in the same transaction as `impact_reports`, let a
  separate poller mark it published — "computed but never announced" cannot
  happen, only "announced but not yet delivered," a transport problem, not
  a truth problem.
- **Backfill** (`PROPOSED`): background job re-running the new edge-derivation
  logic over already-compiled knowledge units, idempotent via the
  `UniqueConstraint` above.
- **Fixture-number warning explicitly honored**: the design makes
  `by_kind()`'s real output — computed from whatever edges actually exist
  for that tenant's collection, very likely not "7" and "3" — the only
  source of the UI's numbers. The CHANGE UI must render the actual counts,
  including zero, without a floor or ceiling tied to any demo number.
- **Performance path** (`PROPOSED`): edge derivation in the background
  compile worker (same cost class as identity resolution). `impact_of()` is
  a bounded BFS — cheap per call — but belongs in a background/deferred
  step triggered by revision-commit, not the synchronous request path,
  since a revision commit is a write the committer's HTTP request shouldn't
  block on for a traversal whose size isn't bounded here.

## Capability 7 — World activation/state

- **Source** (`OBSERVED`, `world_state.py`): `WorldStateRegistry` —
  `stage()` builds a `CANDIDATE` state alongside (never replacing) the
  current one; `publish()` requires a `ValidationReceipt.passed`
  (checksums + permission + integrity + optional equivalence-vs-full-rebuild)
  before the pointer swap. `PublicationManifest` is a sorted,
  order-independent sha256 hash of `{compiler_version, artifact_hashes}` —
  a citable manifest hash, not a timestamp. Only one `ACTIVE` state per
  workspace is the invariant (`WorldStateStatus`:
  `BUILDING/CANDIDATE/ACTIVE/SUPERSEDED/REJECTED/ROLLED_BACK`). Docstring,
  verbatim: *"In production this is Postgres: §73.10's table with a unique
  partial index on `status = 'ACTIVE'` per workspace... This is the same
  semantics in memory."*
- **Do not confuse with**: `ArchitecturePlan` — has `plan_version` (an
  incrementing counter) and a plain `status` string, but no swap protocol,
  no unique-partial-ACTIVE-index, no manifest-hash-verified equivalence
  check. It records that a compile happened; it does not enforce "exactly
  one world is ever live." A new table is correct — repurposing this one
  would bolt the invariant onto a table never designed to hold it.
- **Invocation point** (`PROPOSED`): `stage()` at the point a full or
  selective recompile completes and produces artifact hashes (the step that
  today writes `ArchitecturePlan` rows is the closest existing analog).
  `publish()` at the point validation passes — the module's own required
  order (verify before swap, outbox write inside the same transaction as
  the swap) must be honored exactly as written.
- **Persistence** (`PROPOSED`, minimal — as the docstring already
  specifies): a `world_states` table matching `WorldState` 1:1
  (`world_state_id, tenant_id/workspace_id, status, compiler_version,
  built_at, parent_world_state_id, change_set_id, activated_at,
  manifest_hash, validation_receipt_id`) with a unique partial index `WHERE
  status = 'ACTIVE'` per workspace — the module names this exact mechanism
  as what makes concurrent publishes impossible; do not substitute an
  application-level lock.
- **Transaction boundary** (`PROPOSED`, per the docstring's stated rule):
  the pointer swap (old `ACTIVE`→`SUPERSEDED`, new `CANDIDATE`→`ACTIVE`)
  and the outbox event write happen in the same serializable transaction —
  required explicitly by the module docstring: *"An event written after the
  commit can be lost between them, and an event written before it can
  announce a publish that then rolls back."*
- **Idempotency** (`PROPOSED`): `publish()` re-reads the candidate's status
  before swapping (already the in-memory implementation's behavior per its
  docstring) — a retried publish on an already-`ACTIVE` target is a no-op;
  the unique partial index is the backstop if application logic ever races.
- **Tenant/security boundary**: `tenant_id`/`workspace_id` column, same RLS
  regime — highest-stakes of the four (an incorrectly-scoped `ACTIVE`
  pointer would expose one tenant's world as another's); reuse
  `enter_tenant_context`/`enter_claim_context` verbatim, no bespoke lock.
- **Versioning**: `SUPERSEDED`/`ROLLED_BACK` statuses plus
  `parent_world_state_id` already carry full history by design.
- **Eventization** (`PROPOSED`): `world_state.activated.v1`
  (`world_state_id, previous_world_state_id`) — the docstring's own
  outbox-inside-transaction rule already is the "never fire before durable
  state exists" guarantee; this capability needs the least translation of
  the four since it was written with that exact constraint in mind.
- **Failure semantics** (`PROPOSED`): `publish()` raising `PublishRefused`
  on a failed `ValidationReceipt` means no swap, no event — fails closed by
  construction, more so than the other three capabilities.
- **Backfill** (`PROPOSED`): every existing collection needs one synthetic
  `world_states` row marked `ACTIVE` reflecting its current compiled state,
  created once per workspace as a low-risk, idempotent bootstrap (`INSERT
  ... ON CONFLICT DO NOTHING` against the partial unique index) — additive,
  doesn't touch existing `ArchitecturePlan` rows.
- **Performance path** (`PROPOSED`): `stage()`/`publish()` in the background
  compile worker, same lifecycle as today's `ArchitecturePlan` write —
  inherently batch/deferred (a full or selective recompile), never
  synchronous.
- **Algorithm challenge**: none found — this module is the strongest match
  between "what the docstring says production needs" and "what the class
  already does in memory." `V4_MIGRATION_MATRIX.md` (cited by W0, not
  independently re-read this pass — flagged unverified) classifies it
  `IMPLEMENTED_NOT_PROVEN` with gap "atomic publish + rollback gates to
  add," consistent with everything found here.

---

## Recommended implementation order

1. **World activation/state (capability 7) — strongest candidate for the
   next-smallest vertical slice after L1.** (a) the module's own docstring
   already specifies the exact Postgres shape needed — least design
   interpretation required of the four; (b) cleanest, most bounded
   persistence surface (one table, one index, no new derivation algorithm,
   unlike capability 6); (c) an existing near-analog (`ArchitecturePlan`)
   to backfill from without inventing a new compile trigger; (d) provable
   end-to-end the same way L1 is proving capability 1 — stage→publish→event
   →UI reading a real `world_state_id`, no fixture numbers, binary
   pass/fail.
2. **Temporal state (capability 4)** — small self-contained persistence, no
   new derivation algorithm beyond hooking into the existing `FileVersion`
   status transition, does not require ASK to exist to be provably real (an
   `as_of()` query is directly testable against a stored `TemporalFact`
   without a chat surface).
3. **Authority (capability 3)** — same persistence shape as temporal state,
   but its practical value depends on a real query surface calling
   `resolve_authority()`; without ASK, this capability's read path has no
   consumer and risks landing as more unwired code under a different name.
4. **Change impact (capability 6)** — last, despite being the most
   product-visible. It's the only one requiring genuinely new derivation
   logic (edge production from real compiled content) that doesn't exist
   anywhere today — everything else here is pure activation of an
   already-complete algorithm. Highest risk of silently regressing to
   fixture numbers if edge coverage is thin; needs an explicit "UI must
   render zero honestly" acceptance test before shipping.

---

## Not verified this pass

- Whether `test_dependency.py`, `test_world_state.py`, `test_authority.py`,
  `test_temporal.py` currently pass — read, not executed.
- The exact transaction scope of the production compile/knowledge-unit-build
  pipeline relative to `FileVersion.status` transitions — one call site
  (`_emit_collection_event`) read, full worker pipeline not traced.
- `V4_MIGRATION_MATRIX.md`'s exact cited wording — carried from W0, not
  independently re-read this pass.
- Whether `agent/folynta-trust-integration-v1`'s more recent commits
  (`89847e9`, `ae378ba`, `4d214cc`) contain a more directly reusable claim-
  persistence pattern for capability 3 than `tenant_context.py` alone — not
  checked, time-boxed out.

## Contradictions / uncertainty

- W0's file:line citations for `dependency.py` (`172-270`) differ somewhat
  from the range this pass found for the same function in the same file on
  the same branch — likely a different revision read, or a different
  counting convention. Not a substantive disagreement about behavior; W0's
  exact line numbers should be re-verified before being cited further.
- **The central finding of this entire task**: the four target modules are
  not present anywhere in the W1 worktree or in `origin/main` — see the
  branch/worktree discrepancy section above. This design is sound against
  the modules' real content, but is not actionable against W1's own
  checked-out tree until that branch's Protected Core commits are
  reconciled into whichever lineage becomes the implementation target.

**Status: `W1 PROTECTED CORE ACTIVATION PLAN READY`**
