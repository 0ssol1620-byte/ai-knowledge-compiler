# TAVONEL — Research → Product closure, 2026-09-03

Answers `D:\TAVONEL_RESEARCH_TO_PRODUCTION_INTEGRATION_STATUS_MASTER_2026-09-03.md`.

**Overall: PARTIAL.** The compile chain is closed and proven end to end across a
process and a language boundary. Activation of a *revised* world is blocked on a
named, specific gap in the Core contract. SFIR10R4 is a live study on
operational hold, not a result. No public claim is unlocked by this session.

Status words are used as defined by the session vocabulary: IMPLEMENTED means
code exists, TESTED means a test ran here and passed, PROVEN means each
acceptance criterion has an evidence pointer beyond "tests are green", BLOCKED
means an honest obstruction.

---

## 1. Repository state

| | Research | Product |
|---|---|---|
| Path | `D:\CodexProjects\ai-knowledge-compiler` | `D:\CodexProjects\tavonel-saas-foundation` |
| Branch | `research/source-faithful-kc-v1` | `feature/revision-compile-v1` |
| HEAD | `44c0c1110e7dd287646aed75b5fe3f21fa696c2c` | `f5eae034774124ed9763988e6a8d3aad4f040920` |
| Upstream | none set (work branch, unpushed) | none set (work branch, unpushed) |
| Remotes | `origin`, `upstream`, `integration` | `origin` |

Nothing was merged or pushed to any `main`. The full gate in §21 of the brief has
not been met, and §20 forbids it until then.

### Commits this session

Research, on `121d750..HEAD`:

```
44c0c11  core: check that the witness chain survives the revision on both sides
d2686b8  research(sfir10r4): seal both census segments, and correct the record
ab1a53e  core: let a rebuilt artifact be raw content, not only a document
62c751c  core: return the bytes a revision rebuilt, checked against its digest
c98cfc8  core: give the v3 revision endpoint a source, and run v1->v2 over a socket
b08c71d  core: compose the revision compile, and keep I and E apart
```

Product, on `e9951c1..HEAD`:

```
f5eae03  product: a revision-compile route, stopping where honesty runs out
78b2157  product: an artifact body may be raw content
43ff89e  product: verify the rebuilt bytes, not just the digests beside them
95901f4  product: the revision-compile client, bound to a Core the compiler ran
1429deb  product(vkc): absorb the verified knowledge compiler contract work
```

---

## 2. The gap this session actually closed

The brief assumed a deployed Core called `tavonel-python-core-v2` that the
Product spoke to. It exists as a *client* in the Product and as *expectations* in
that client's types. **The server had no source in either repository.** Nothing
could be shown to agree about anything — not the signature, not the digest, not
the shape of a refusal — because one side of the contract was not written down.

`services/core-v3/` is that side. It is standard library on purpose: its value is
being cheap enough for a test to start, drive and stop, and a framework would
trade that for configuration surface it has no use for.

That is why the E2E is an integration test over a real socket rather than a
function call. Calling `compile_revision` directly would skip the thing under
test.

---

## 3. Identity continuity is not change equivalence

The paper's central finding, enforced at import time rather than by review:

```python
FINGERPRINT_INPUTS = {
  "identity": ("normalized_text", "document_path", "anchor",
               "explicit_identifier", "geometry_style"),
  "change":   ("raw_text", "entities", "relationships", "authority",
               "temporal_fingerprint", "metadata_fingerprint",
               "visual_fingerprint", "evidence_id", "page_number1"),
}
_shared = set(FINGERPRINT_INPUTS["identity"]) & set(FINGERPRINT_INPUTS["change"])
if _shared:
    raise RuntimeError(...)
```

The two input sets are disjoint and the module refuses to import if that ever
stops being true. Identity reads *normalised* text so a clause survives a
re-typeset; change reads *raw* text so a re-typeset cannot hide an amendment.

`assert_fingerprints_separated` is the runtime half: if the raw text differs and
the change fingerprint does not, it raises rather than returning a plausible
answer.

**Status: PROVEN.** The mandatory regression fixture — same logical identity,
real material change, payment 30 → 45 days — is in
`tests/unit/test_revision_compile.py`, and two mutants prove the tests have
power:

- `test_legacy_predicate_erases_a_normalised_edit` — the pre-separation predicate
  is shown to lose a real edit.
- `test_assert_fingerprints_separated_catches_a_folded_fingerprint` — a folded
  fingerprint is caught rather than tolerated.

In the E2E, `ku_payment` comes back `identityContinuity: "continued"` and
`changeState: "semantic"` simultaneously, with `identityFingerprint !=
changeFingerprint`. That pair is the ordinary case for an amended clause, and a
design that could not express it would be wrong.

---

## 4. Typed change classification

`ChangeChannel` covers unchanged, structural, locator, semantic, graph, temporal,
visual, metadata and unresolved; `ChangeKind` enumerates seventeen kinds.

Nothing unknown is silently dropped. `CANDIDATE_BLOCKING_CHANGE_STATES` contains
`UNRESOLVED`, and a unit in that state forces review rather than promotion.

The E2E amendment deliberately moves the clause down the page *as well as*
changing its words, because a real re-typeset does both and a locator change
travelling on the same channel as the meaning change would make the test easier
than reality.

**Status: TESTED.** All six change families and the unknown-state fail-closed
path have cases.

---

## 5. Dependency impact and selective recompilation

Exact artifact identity is preserved through the plan:
`affectedArtifactIds`, `carriedForwardArtifactIds`, `unresolvedArtifactIds`.

The receipt is machine-verifiable and the arithmetic is checked on both sides:

```
workAvoidedArtifacts === totalArtifacts - rebuiltArtifacts
```

The client additionally requires that rebuilt, carried-forward, unresolved and
quarantined sets **partition** the total — no overlap, no gap — and that every
carried-forward artifact is bound to a digest equal to the one the Product sent.

The E2E result, from the sealed fixture:

| | |
|---|---|
| total artifacts | 7 |
| rebuilt | 4 — `claim:payment`, `graph:relations`, `retrieval:payment`, `summary:contract` |
| carried forward | 3 — `claim:address`, `claim:law`, `claim:signatories` |
| work avoided | 3 |
| stale after revision | 0 |
| full-rebuild equivalence | passed |

**Both directions are measured, which is the point.** Stale-avoidance alone is
trivially satisfied by always rebuilding everything; that would show `workAvoided
= 0` here and the test would fail. False invalidation alone is trivially
satisfied by rebuilding nothing. The three numbers are asserted together.

**Status: PROVEN** for this fixture. `docs/evidence/artifacts/revision-compile-e2e-v1.json`,
sha256 `d8f3ce102effc6ef8497cd7ff360652fef5ee3d7ba013b304605ffec601ecaaa`.

---

## 6. Source-faithfulness

Four states. Only one may fail open:

```python
FAIL_CLOSED_SOURCE_FACT_STATES = frozenset({UNREPRESENTED, UNRESOLVED})
```

`IGNORED_BY_PREDECLARED_POLICY` is excluded from the coverage denominator, so a
broad ignore policy cannot inflate the number — a detail that matters because the
obvious implementation lets it.

Coverage crosses the wire as an **integer permille**, not a ratio.
`JSON.stringify(1)` is `"1"` where `json.dumps(1.0)` is `"1.0"`, so a float in a
digested body would make the two sides disagree about a seal for a reason with
nothing to do with the compile. The Python canonicaliser refuses floats outright.

**Status: PROVEN.** The E2E asserts `sourceFaithful: true`, `failClosed: []`,
`coveragePermille: 1000`. A negative test introduces an `UNRESOLVED` source fact
that leaves `equivalence == "passed"` and still forces `review_required` — which
is the finding that "selective equals full rebuild" is not sufficient.

---

## 7. Provenance continuity through a revision

`test_the_witness_chain_survives_the_revision` asks both halves:

- every carried-forward artifact is byte-identical to v1, evidence id, page and
  box included;
- every rebuilt artifact carries v2's coordinates for the unit that moved and
  **v1's, unchanged, for the units beside it that did not** — rebuilding an
  artifact is not a licence to recompute the provenance of everything in it.

The final assertion is about the evidence id rather than the box, because a
revision that moved a clause to another page and kept the old id would pass every
digest check in the file: internally consistent digests, wrong page.

**Status: PROVEN.**

---

## 8. Activation and lifecycle

Nothing in this session weakened the activation gate, and nothing needed to: the
atomic lifecycle already exists and is tested in
`supabase/tests/foundation_world_lifecycle.sql` — advisory lock, expected current
manifest, single-active invariant, prior version retained as `superseded`,
rollback reactivation, append-only events.

**Status of that suite: IMPLEMENTED, not TESTED here.** It is pgTAP and needs a
live Postgres; it was not executed in this session and is not claimed as green on
my evidence.

Every Core response carries `candidatePromotion: false` and the client refuses a
`promotable` disposition that arrives with an open finding
(`CORE_V3_PROMOTABLE_WITH_OPEN_FINDING`). Activation remains a human act.

---

## 9. The end-to-end scenario

`tests/integration/test_revision_compile_e2e.py`, run over a loopback socket with
a real HMAC, signed exactly as `dispatchProductCoreRevision` signs it:

Contract v1 compiled and activated → payment clause amended 30 → 45 days and
re-typeset onto a new box → v2 compiled against World v1 → only what reads that
clause rebuilt → the rest carried forward → compared against an independently
written full rebuild → every source fact accounted for → human activates → *"What
is the payment term?"* answers **45 days**, citing page 2 and box
`(120, 356, 880, 388)` — asserted to be **not** the v1 box `(120, 340, 880, 372)`.

Six of the eleven cases are refusals, because a compile path that only ever
succeeds proves nothing: unsigned request, stale timestamp, digest/body mismatch,
wrong operation class, an unresolvable prior world, and a stale rebuilt body.

**Status: PROVEN.**

---

## 10. Cross-language agreement

The sealed response is written to an evidence artifact and validated in Node by
the **real** client validator, not a copy of it. The digest agreement between
`json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)` and
`canonicalizeRevision` is therefore a result rather than an assumption, and it
now covers nested documents with strings, integers and arrays — not just the flat
receipt.

Two traps were found and closed before they bit:

- **`localeCompare` is ICU-locale dependent** and cannot be reproduced from
  Python. The revision client sorts by code point instead. The initial path was
  left alone precisely because changing it would alter what production signs.
- **Line endings.** The artifact is bound by sha256 and copied into the product
  repo. `Path.write_text` emitted CRLF while git stored LF, and the product repo
  runs `core.autocrlf=true`; the digest binding would have failed on every fresh
  checkout. Fixed at the writer and pinned with `eol=lf` in `.gitattributes` —
  the same failure that file already records for the developer distribution.

The copy is bound twice: by sha256 in the test, and by `eol=lf` in git.

---

## 11. The Product route, and where it stops

`POST /api/collections/{id}/revise`. Deliberately not the compile route with a
flag: an initial compile has no predecessor and must keep working exactly as it
does.

`planRevisionInputs` refuses a document set that gained or lost a member. The
contract binds every changed document to its predecessor version, and a document
with no predecessor has none — writing one would be inventing a digest for a
version that never existed.

`assembleRevisedPackage` builds the next package: carried-forward files are the
previous objects untouched, rebuilt files are the returned bodies hashed **again**
against the sealed digest. The client checked what arrived; this checks what is
about to be written.

### The honest boundary — BLOCKED

The route does **not** write a promotable candidate.

A candidate world carries collection-level projections beside its files — the
ontology and the directory plan — and the revision contract does not return
those. They are not artifacts in the dependency graph, so the Core neither
rebuilds nor carries them forward. Producing them on the Product side would mean
either presenting pre-revision content as the revised world, or standing a second
compiler beside the one that signed the receipt.

So the result is stored as `revision-receipt.json` under the candidate manifest —
next to, but not at, the key the promote gate reads — carrying:

```json
{ "activation": "blocked",
  "activationBlockedReason": "COLLECTION_PROJECTIONS_NOT_RETURNED_BY_CORE" }
```

**What unblocks it:** the Core must return the collection-level projections as
artifacts, under reserved ids, so they are rebuilt or carried forward like
everything else. That is a Core-side change, not a Product workaround.

### Second known limitation

The reference `RevisionService` requires a `SourceResolver` to supply units,
graph, artifacts and builders. The E2E supplies one from a fixture. **A
production resolver over the real corpus does not exist** — that is the Core
compile pipeline itself. The Product half is complete and testable against any
Core v3 deployment that implements one.

---

## 12. Test evidence

Everything below was executed in this session.

The research verdict below is emitted by the repository's own instrument,
`tools/repro/run_test_scopes.py`, not by a pytest invocation of mine. Two notes
follow on why that distinction is not pedantry.

| Suite | Result |
|---|---|
| Research, **full repository scope** | **3,196 collected, 3,128 passed, 0 failed, 0 errors, 68 skipped**, `repository_green: true` |
| Product (`vitest run`) | **819 passed, 122 files, 0 failed** |
| `ruff check` / `ruff format --check` | clean |
| `mypy` (strict) on `akc_core_v3` | clean |
| `eslint` on all new/changed files | clean, exit 0 |
| `tsc --noEmit` | **clean, exit 0, zero errors** |

The 68 skips are legitimate: 66 in `test_superseded_receipt_contract.py`
("does not supersede anything") and 2 guarded by config freezes that make the
pre-freeze refusal unreachable.

### Only the full scope may be called the repository

`TEST_SCOPE_STATUS.json` (receipt `sha256:7477a55f…2e28`) states the rule:

> Only the 'full' scope may be called the repository. A green 'unit' scope does
> not license the phrase; that substitution is exactly what P18 recorded. When
> the full scope was not run, `repository_green` is False and
> `repository_green_evaluated` is False — **absence of a run is not a pass.**

An earlier draft of this document reported `tests/unit` + `tests/integration`
(1,030 passed) in the position where a repository claim belongs. That is a narrow
scope offered in place of the repository — the precise substitution the guard was
built to refuse. The number was true; it was not the number being asked for.

The full scope is 3,196 collected against that 1,030. The instrument was run,
and `repository_green: true` is its output rather than my summary of it.

The guard also proves it can say no: it refuses an injected failure and accepts a
clean control on every run (`guard_is_live: true`). A scope-reporting guard that
has never refused anything is an assertion, not a check.

### The interpreter guard caught this session too

The first research run was made with the system Python rather than the project
venv. `docs/repro/TEST_SCOPE_SELF_TEST.json` recorded
`is_project_interpreter: false`, and that file states the rule plainly:

> The parser sandbox launches its child with `-I`, which excludes user
> site-packages. […] **A result from the wrong interpreter is not a result about
> this repository.**

So the first "1,018 passed" was not admissible evidence, and everything was
re-run under `.venv\Scripts\python.exe`. Both artifacts now record
`is_project_interpreter: true`, and the verdict above is from that interpreter.

The totals happen to agree, which is worth saying rather than hiding: the wrong
interpreter did not change the outcome here. It changed whether the claim was
allowed to count, and the guard was right to stop it. That guard exists because
this exact mistake once produced 24 failures that looked like product defects.

**One pre-existing error was found and closed.**
`components/pdf-evidence-viewer.tsx(38,34): Cannot find module 'pdfjs-dist'` was
the only `tsc` error in the entire product app, in a file this work never
touched: the package was declared in `package.json` and present in
`pnpm-lock.yaml` but absent from `node_modules`. `pnpm install
--frozen-lockfile` installed it — three packages, nothing downloaded, **lockfile
untouched** — and the typecheck now exits 0.

### Mutation evidence

Tests were shown to have power rather than assumed to:

- deleting the carry-forward digest check failed exactly 2 of 37 client tests;
  restoring it passed all 37;
- `test_legacy_predicate_erases_a_normalised_edit` and
  `test_assert_fingerprints_separated_catches_a_folded_fingerprint` on the
  research side;
- `test_a_rebuilt_body_that_does_not_match_its_sealed_digest_is_refused` returns
  **v1's bytes** for the clause that changed, because a cache or a wrong key
  serving the previous revision is the realistic failure, not a corrupted byte.

---

## 13. SFIR10R4 — a live study on operational hold, not a result

**Status: BLOCKED (frozen operational hold), by owner instruction.**

### Instrument integrity

Verified directly rather than trusted: the freeze digest recomputes, the protocol
digest matches the live protocol, and **all 15 frozen components are byte-identical**
to their recorded sha256. The roster is sealed at 50 entries under partition 4
(predecessor 3), drawn from 37,702,060 catalogue rows with 1,060 eligible in
partition; the spent-exclusion set is empty.

### What was executed

Two segments were run and sealed. Both digests recompute and both bind the same
roster seal.

| | segment-01 | segment-02 |
|---|---|---|
| digest | `sha256:6710af56…2657e8` | `sha256:14ce28d9…257639` |
| `FRONTIER_EXHAUSTED` at seal | **32** | **46** |
| minimum attributable charges | **1,973** | **1,665** |
| unattributed extra | 103 | 23 |
| `accounting_is_conservative` | true | true |
| `capacity_evidence_publishable` | true | true |
| `provider_cost_claim_publishable` | **false** | **false** |

Cumulative minimum attributable charges: **3,638**. Windows used **2 of 6**.
Roots 33, 37, 45 and 47 are `STOPPED_BEFORE_EXHAUSTION` and would be replayed by
a third segment.

**No census, score or acceptance receipt exists. Nothing here may be read as PASS
or FAIL, and `scientific_counts_disclosed` is false in both segments.**

### Number reconciliation

Two different figures for segment 1 were reported mid-session from console
samples. Reconciled against the sealed receipts:

- **32 roots / 1,973 charges** is segment 1 at its seal. Authoritative.
- **35 roots / 2,307 charges** was **never a result.** It was a live read of
  `runtime/sfir10r4/state.json` taken while segment 2 was mid-flight. Discarded.

Neither figure is a cumulative total. Console output is not evidence.

### The incident, and the correction

`sfir10r4-incident-harness-teardown.json` (`sha256:89ecb962…2290`) records a
failure that **did not happen**. The agent harness reported the segment-2
background task stopped, and that notice was treated as evidence about the
operating system process. It is not. The runner was never killed: it ran roughly
forty minutes past that notice, completed the segment, sealed it, unlinked its own
active-segment marker and exited cleanly.

`sfir10r4-incident-correction.json` (`sha256:6a0dc595…ce31`) supersedes it. The
wrong receipt is kept exactly as written — an incident record quietly rewritten
once the facts improve is not evidence.

Two things were **not** done while that mistaken belief was held, and both would
have destroyed the study:

1. **The active-segment marker was not deleted.** The frozen instrument treats a
   marker with no sealed receipt as terminal `MEASUREMENT_UNPROVEN`. Deleting it
   would have let the runner continue — and would have been exactly the tampering
   the freeze exists to prevent. It turned out the runner still needed it.
2. **The runner was not killed to make the state match the report.** Killing it
   during its sealing phase would have manufactured precisely the
   `MEASUREMENT_UNPROVEN` outcome being reported as inevitable.

### The seal was attempted, and the instrument refused

Sealing was attempted under the owner's direction, by the frozen instrument under
its own rules. With the active-segment marker already consumed and every root in a
terminal state, `run-segment` routes to `finalize()`, which reads root evidence
from disk and opens no socket — the no-further-requests constraint was satisfied
by the code path itself rather than by a promise.

**It refused, and wrote nothing:**

```
REFUSED  counted root carries no immutable revision snapshot
```

Diagnosis: **49 of 50 roots pass the evidence gate. Root 45 alone fails** — it is
`STOPPED_BEFORE_EXHAUSTION` with zero candidates and no immutable revision
snapshot, having been stopped before it recorded anything. `_validate_root_evidence`
requires that any root counted as exhausted or stopped carry a snapshot, because
sealing otherwise lets a root with nothing behind it contribute to the capacity
disposition.

No census, score, acceptance or terminal-unproven receipt exists. Runtime state is
unchanged. This is a guard firing, not a partial seal.

**This is neither PASS nor FAIL nor MEASUREMENT_UNPROVEN.** It is
`SEAL_REFUSED_BY_INSTRUMENT_EVIDENCE_GATE`, recorded in
`sfir10r4-seal-attempt.json` (`sha256:d453a3c5…a03d`).

Three things were not done to clear the gate: `root-045.sqlite` was not touched,
because fabricating a snapshot invents evidence for a root that produced none;
root 45 was not reclassified to `REPOSITORY_IDENTITY_REFUSED`, because relabelling
a stop as a refusal is a different scientific claim; and no protocol constant was
changed.

**The only legitimate path forward** is a third segment replaying the four stopped
roots — four of six permitted windows are unused. That sends cohort requests,
which the current instruction forbids, so it is the owner's decision.

### Why MEASUREMENT_UNPROVEN was not written

The owner instructed that R4 be sealed `MEASUREMENT_UNPROVEN` at the end of
closure. **That instruction rests on a premise that is false.** There is no crash
condition: the marker was consumed, both segments are sealed, and the instrument
will not produce a terminal-unproven receipt on this state. Forcing that label
would manufacture a failure the study did not have — the mirror image of
overwriting a failure with a success, and forbidden for the same reason.

R4 is therefore left exactly as it stands: no further cohort requests, no marker
edits, no resume bypass, no PASS/FAIL interpretation — and, as recorded above, no
seal, because the instrument itself declined to write one.

### Predecessor context

R1 and R2 died at `windows_used 0` ("per-response provider delta is 2; exclusive
attribution is not established"); R3 at `windows_used 0` ("provider reset epoch
changed mid-segment"). **R4 is the first attempt to clear the accounting
preflight and measure the cohort at all.**

### The operational correction stands anyway

A frozen segment must run as a **detached process with its own PID file, log and
heartbeat**, independent of any agent session — not because the runner was
fragile, it was not, but because the supervising agent could not tell whether it
was and acted on that uncertainty. Recoverability has to be defined before the
run rather than inferred after it.

---

## 14. GPU and RunPod

**No GPU was provisioned and no GPU cost was incurred in this session.**

SFIR10R4 is a provider-metadata census over the GitHub REST API. It is
network-and-CPU work; the frozen protocol grants no GPU execution authority, and
§17 forbids bypassing a gate to use GPU that the protocol does not authorise.

The `infra/runpod/v6` lane is intact and its qualification protocol is explicit:
build integrity is not runtime qualification, a paid pod may claim
`qualification_state: READY` only against a complete `baked_runtime_qualification`
object whose sha256 matches, and `BakedImageBuildReceipt` rejects any build-only
receipt that tries to waive the GPU smoke. Nothing in this session touched it.

**No idle GPU exists to terminate.**

---

## 15. OCR and recovery lane

The brief anticipated broken OCR recovery tests. **That premise does not hold in
the current tree.** `test_recovery_policy.py` and
`test_cause_conditioned_recovery.py` run green (49 tests), and the full research
unit suite has zero failures. There was nothing to repair here, and inventing a
repair would have been worse than reporting that.

---

## 16. Working-tree disposition

### Research repo — clean of this session's work

All work committed. Three items remain untracked or modified and are **not
mine**; per §3.2 another worker's changes are preserved, never absorbed:

| Path | What it is | Disposition |
|---|---|---|
| `research/model_arena_20260903/` | A Model Arena implementation (355 KB), created today by a concurrent workstream | **Preserved, uncommitted.** Committing it would claim authorship of code this session neither wrote nor verified. |
| `pyproject.toml` (modified) | Adds a ruff per-file-ignore for that arena directory | **Preserved, uncommitted.** Belongs with the arena commit. |
| `.claude/launch.json` (modified) | Adds a dev-server entry for `tavonel-launch-v3`, a different repository | **Preserved, uncommitted.** Machine-local tooling, unrelated to this work. |
| `p.json` | A HuggingFace API dump for `PaddlePaddle/PaddleOCR-VL-1.6` (6 KB) at repo root | **Preserved, uncommitted.** Provenance uncertain; §3.2 forbids deleting on a guess. Recommend the owner confirm it is scratch before removal. |

Root `*.sqlite` working databases under `research/tavonel_eval_v2/runtime/sfir10r4/`
are covered by an existing `.gitignore` rule. The science is in the sealed segment
receipts, which **are** committed (4.4 MB) as scientific provenance.

### Product repo — clean

`git status --short` is empty. `nextjs/lib/core-runtime-v2.ts` has a **zero-line
diff**: the live `initial_compile` HMAC payload bytes are untouched, and a test
asserts the exact key list of `buildProductCoreV2Request`'s envelope so a later
attempt to unify the two clients breaks visibly rather than by changing what
production signs.

---

## 17. Claims discipline

**No public claim is unlocked by this session.** The five phrasings forbidden
until a production revision E2E completes remain forbidden:

> "Always stays current" · "Only changed slices recompile" · "No stale knowledge" ·
> "Automatically keeps itself correct" · "Every source update is fully propagated"

What may honestly be said internally: a revision compile has been demonstrated
end to end on a deterministic fixture, across a process boundary and a language
boundary, with a machine-verifiable receipt. That is a laboratory result on one
fixture. It is not a production behaviour, and the activation path for a revised
world is explicitly blocked.

Both sealed SFIR10R4 segments say `provider_cost_claim_publishable: false` on
their own account. **No cost figure from this study may be published.**

---

## 18. IP

No patent action was taken, proposed or prepared. §23 reserves filing and
publication timing to the founder, and nothing here was disclosed publicly.

The identity/change separation and the source-fact state machine are the
technically novel parts of this session's work and are the natural candidates for
a disclosure-registry review against the existing KR filing — **as a founder
decision, not an agent one.**

---

## 19. What is done, what is not

**Closed and proven**

- Core v3 revision endpoint, with a source, over a real socket
- Identity/change fingerprint separation, guarded at import and at runtime
- Typed change classification with fail-closed unknown handling
- Dependency impact preserving exact artifact identity
- Selective recompilation, measured in all three directions
- Source-fact accounting with a coverage denominator that cannot be gamed
- Provenance continuity across a revision, both halves
- Full-rebuild equivalence oracle
- Cross-language digest agreement, including nested documents
- Product revision client with 16 named refusal codes
- Product revision route and package assembly
- Both working trees clean of this session's work
- Product `tsc --noEmit` fully clean, including a pre-existing error closed in passing
- Repository green established by the repository's own instrument over the full
  scope — 3,128 passed of 3,196 collected, zero failures — not by a narrow scope
  offered in its place

**Blocked, with the obstruction named**

- Activation of a revised world — Core does not return collection-level
  projections as artifacts
- A production `SourceResolver` over the real corpus — that is the Core compile
  pipeline
- SFIR10R4 — seal attempted and **refused by the instrument's evidence gate**
  (root 45 carries no revision snapshot). A third segment is the only
  legitimate path and needs owner authorisation, since it sends cohort requests.
- `foundation_world_lifecycle.sql` — pgTAP, needs a live Postgres, not run here

**Not started**

- Any GPU work. Nothing in scope authorised it.
- Push of either work branch. §20 forbids it before the full gate.

---

## 20. Evidence index

| Artifact | Digest |
|---|---|
| `docs/evidence/artifacts/revision-compile-e2e-v1.json` | `d8f3ce10…1ecaaa` |
| `research/tavonel_eval_v2/receipts/sfir10r4-segments/segment-01.json` | `sha256:6710af56…2657e8` |
| `research/tavonel_eval_v2/receipts/sfir10r4-segments/segment-02.json` | `sha256:14ce28d9…257639` |
| `research/tavonel_eval_v2/receipts/sfir10r4-incident-harness-teardown.json` | `sha256:89ecb962…2290` (superseded, retained) |
| `research/tavonel_eval_v2/receipts/sfir10r4-incident-correction.json` | `sha256:6a0dc595…ce31` |
| `research/tavonel_eval_v2/receipts/sfir10r4-seal-attempt.json` | `sha256:d453a3c5…a03d` |
| `docs/repro/TEST_SCOPE_STATUS.json` (repository verdict) | `sha256:7477a55f…2e28` |

---

## 21. Declaration

**PARTIAL.**

The research→product compile chain is closed and proven on a deterministic
fixture across a process and a language boundary. Two obstructions are named
precisely rather than worked around, and both are Core-side. One frozen study is
alive and held, not concluded: its seal was attempted and the instrument refused,
because one root of fifty carries no evidence and it would not count a root that
had none. No claim was unlocked, no threshold was moved, no
receipt was overwritten, and one incident record was corrected by supersession
rather than by edit.

The single most important thing in this document is section 13: a failure was
reported that had not occurred, and the two actions that would have made it real
were not taken. The instrument's own refusal to be resumed after a crash is what
made the mistake survivable.
