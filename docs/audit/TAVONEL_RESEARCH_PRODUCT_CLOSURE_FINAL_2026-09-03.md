# TAVONEL — Research → Product closure, 2026-09-03

Answers `D:\TAVONEL_RESEARCH_TO_PRODUCTION_INTEGRATION_STATUS_MASTER_2026-09-03.md`.

**Overall: PARTIAL.** The revision compile chain is closed, including both
activations, and proven across a process boundary and a language boundary.
Activation of a revised world *in the Product* is blocked on a named gap in the
Core contract. SFIR10R4 is a live study on **frozen operational hold** — not
scored, no PASS, no FAIL. No public claim is unlocked.

Status words: IMPLEMENTED means code exists. TESTED means a test ran here and
passed. PROVEN means the criterion has an evidence pointer beyond "tests are
green". BLOCKED means an honest obstruction, named.

---

## 1. Typecheck — final result

`pdfjs-dist` was declared in `package.json` and present in `pnpm-lock.yaml` but
absent from `node_modules`, and it produced the only `tsc` error in the product
app — in `components/pdf-evidence-viewer.tsx`, a file this work never touched.
`pnpm install --frozen-lockfile` installed it: three packages, nothing
downloaded, **lockfile untouched**.

Re-run over the **whole product app**, not only the new code:

```
$ npx tsc --noEmit
TSC_EXIT=0
--- output ---
(no lines)
```

**TypeScript typecheck = 0 errors, exit code 0, zero output lines.** ✅

---

## 2. Repository, branch and push state

### Research — `D:\CodexProjects\ai-knowledge-compiler`

```
$ git status -sb
## research/source-faithful-kc-v1
 M .claude/launch.json
 M pyproject.toml
?? research/model_arena_20260903/

$ git status --short
 M .claude/launch.json
 M pyproject.toml
?? research/model_arena_20260903/

$ git log -n 10 --oneline
7b43a14 tools: write the scope artifact with LF, since its sha256 is cited
9a5c384 docs: re-run the full scope after the activation tests, and record what it says
9f5a130 core: perform the two activations the scenario claimed and no test carried out
e322229 docs: let the repository's own instrument say whether the repository is green
94f82a8 docs: re-run the suites under the project interpreter, and say why the first run did not count
7a1ec09 research(sfir10r4): attempt the seal, and record that the instrument refused
9010aa2 docs: the research-to-production closure, with the boundaries named
44c0c11 core: check that the witness chain survives the revision on both sides
d2686b8 research(sfir10r4): seal both census segments, and correct the record about how they got there
ab1a53e core: let a rebuilt artifact be raw content, not only a document
```

These three commands were run immediately before this document was written, so
the log above does not include the commit that adds the document itself.

The `git status -sb` branch line reads `## research/source-faithful-kc-v1` with
**no upstream after it**: the branch tracks nothing and has never been pushed.

### Product — `D:\CodexProjects\tavonel-saas-foundation`

```
$ git status -sb
## feature/revision-compile-v1

$ git status --short
(empty — the tree is clean)

$ git log -n 10 --oneline
f5eae03 product: a revision-compile route, stopping where honesty runs out
78b2157 product: an artifact body may be raw content
43ff89e product: verify the rebuilt bytes, not just the digests beside them
95901f4 product: the revision-compile client, bound to a Core the compiler actually ran
1429deb product(vkc): absorb the verified knowledge compiler contract work
e503bac Merge origin/main into feature/revision-compile-v1
e9951c1 chore: ignore machine-local agent and CLI state
fb860d7 evidence: production live operations audit, 2026-09-02
8392674 web: marketing and workspace surfaces as of 2026-09-01 22:23
6ace7e0 product(api): collection, upload and run-event routes as of 2026-09-01
```

**The product tree is completely clean**, and its branch line likewise carries no
upstream.

### Where the named commits actually live

| Commit | Repository | Branch | On a remote? |
|---|---|---|---|
| `ab1a53e` core: raw content artifacts | Research | `research/source-faithful-kc-v1` | **No** |
| `62c751c` core: return rebuilt bytes | Research | same | **No** |
| `c98cfc8` core: v3 endpoint + socket E2E | Research | same | **No** |
| `b08c71d` core: compose the revision compile | Research | same | **No** |
| `78b2157` product: raw content body | Product | `feature/revision-compile-v1` | **No** |
| `43ff89e` product: verify rebuilt bytes | Product | same | **No** |
| `95901f4` product: revision client | Product | same | **No** |

Checked with `git branch -r --contains <sha>` on every one of the seven:
**empty output for all of them.** Nothing this session produced exists on any
remote.

Research remotes: `origin` → `0ssol1620-byte/ai-knowledge-compiler`, `upstream` →
`phillipsoul/ai-knowledge-compiler`, `integration` → a local path.
Product remotes: `origin` → `0ssol1620-byte/tavonel-saas-foundation`.

**Intended integration path.** Each branch lands on its own repository's `main` by
pull request, and not before the qualification gate is met — which it is not,
because revised-world activation is blocked (§7). Merging or direct-pushing to
production `main` ahead of that gate is forbidden, so no merge was made. Pushing
the *work branches* is permitted and was not done: until someone pushes them, this
work exists only in these two working trees. That is a real single point of
failure and it is recorded here rather than left implicit.

---

## 3. Dirty tree — separated by author

Everything this session produced is committed. What remains belongs to a
**concurrent workstream**, and another worker's changes are preserved, never
absorbed and never deleted.

| Path | What it is | Disposition |
|---|---|---|
| `research/model_arena_20260903/` | A Model Arena implementation, ~355 KB, created today | **Preserved, uncommitted.** Committing it would claim authorship of code this session neither wrote nor verified. |
| `pyproject.toml` (modified) | Adds a `ruff` per-file-ignore (`S603`, `S607`) for that arena directory | **Preserved, uncommitted.** Belongs with the arena commit, not with this work. |
| `.claude/launch.json` (modified) | Adds a dev-server entry for `tavonel-launch-v3`, a different repository | **Preserved, uncommitted.** Machine-local tooling, unrelated. |

`p.json`, a 6 KB HuggingFace API dump for `PaddleOCR-VL-1.6` at the research repo
root, was present earlier in the session and is no longer on disk. **This session
never ran a delete**, so it was removed by whoever created it. It is recorded here
because a file that appears and disappears mid-session should be accounted for
rather than quietly dropped from the report.

Working `*.sqlite` databases under `research/tavonel_eval_v2/runtime/sfir10r4/`
are covered by an existing `.gitignore` rule. The science lives in the sealed
segment receipts, which **are** committed.

**No unrelated work was lost.**

---

## 4. The gap this session closed

The brief assumed a deployed Core named `tavonel-python-core-v2`. It existed as a
*client* in the Product and as *expectations* in that client's types. **The server
had no source in either repository.** Nothing could be shown to agree about
anything — not the signature, not the digest, not the shape of a refusal — because
one side of the contract was never written down.

`services/core-v3/` is that side, deliberately standard-library only: its value is
being cheap enough for a test to start, drive and stop.

That is why the end-to-end test drives it over a real loopback socket with real
HMAC. Calling `compile_revision` in-process would skip the thing under test.

---

## 5. Revision E2E — the seventeen claims, mapped to tests

Sixteen of seventeen are carried by a named test that ran here. One is PARTIAL and
is marked as such rather than rounded up.

| # | Claim | Status | The test that proves it |
|---|---|---|---|
| 1 | v1 compile | **PARTIAL** | World v1 is built by `Workspace.full_build(V1_CLAUSES)` — deterministic, but a fixture, not a compile service. See the note below. |
| 2 | v1 World | PASS | `_activated_world_v1` — manifest digest over artifact digests, units and shape, registered in `WorldStore` |
| 3 | v1 activation | PASS | `test_the_scenario_end_to_end_including_both_activations` — activated by a named reviewer with a stated reason |
| 4 | source revision | PASS | same test — `V2_CLAUSES`: payment 30 → 45 days, re-typeset onto a new bounding box |
| 5 | stable identity continuation | PASS | E2E `identityContinuity == "continued"`; unit `test_the_amended_clause_is_continued_and_semantic`, `test_a_case_and_punctuation_edit_keeps_identity_and_is_still_a_change` |
| 6 | material change detected | PASS | E2E `changeState == "semantic"` with `identityFingerprint != changeFingerprint`; mutants `test_legacy_predicate_erases_a_normalised_edit`, `test_assert_fingerprints_separated_catches_a_folded_fingerprint` |
| 7 | affected artifacts | PASS | E2E `impact.affectedArtifactIds`; unit `test_only_what_reads_the_amended_clause_is_rebuilt` |
| 8 | carried-forward artifacts | PASS | E2E set equality on `carriedForwardArtifactIds` plus digest equality against what the Product sent |
| 9 | selective rebuild | PASS | E2E rebuilt set = {`claim:payment`, `graph:relations`, `retrieval:payment`, `summary:contract`} |
| 10 | full rebuild equivalence | PASS | E2E `equivalence == "passed"` against an independently written oracle; unit `test_the_selective_state_equals_the_independent_full_rebuild` |
| 11 | source / provenance witness continuity | PASS | `test_the_witness_chain_survives_the_revision` — both halves, Python and Node |
| 12 | stale escape = 0 | PASS | E2E carried == oracle == prior; unit `test_no_stale_value_is_carried_forward` |
| 13 | work avoided > 0 | PASS | E2E `workAvoided` = 3 of 7; unit `test_work_avoided_is_positive_and_is_total_minus_rebuilt`, `test_false_invalidation_is_measured_not_hidden` |
| 14 | v2 candidate | PASS | E2E `lifecycle == "candidate"`, `candidatePromotion == false` |
| 15 | v2 activation | PASS | `test_the_scenario_end_to_end_including_both_activations` — activated against the manifest the actor read; v1 retained as `superseded` |
| 16 | Ask returns the revised fact | PASS | same test — read **through the active pointer**: "45 days" in, "30 days" out |
| 17 | revised evidence binding | PASS | same test — page 2, bbox `(120, 356, 880, 388)`, `evidenceId ev_ku_payment_p2`, asserted **not** the v1 box `(120, 340, 880, 372)` |

Every test named above was confirmed to exist at the path given, not merely
cited: the fourteen `test_the_*` / `test_a_*` entries marked E2E are in
`tests/integration/test_revision_compile_e2e.py`, the unit entries in
`tests/unit/test_revision_compile.py`, and the Node-side halves in
`nextjs/lib/core-runtime-revision.test.ts`,
`nextjs/lib/core-runtime-revision.crosslang.test.ts` and
`nextjs/lib/collection-revision.test.ts`.

### What had to be corrected to reach that table

The end-to-end file opened by claiming World v1 was *"compiled, reviewed and
activated"* and that *"a human activates World v2"*. **Neither step was ever
performed.** Every test stopped at the candidate and asserted
`candidatePromotion == false`. That is the fail-closed half, and it was the only
half under test — a store that has never activated anything proves very little by
refusing.

`WorldStore` now models the part of the activation contract the compile path must
satisfy: activation is explicit rather than a consequence of compiling; it is bound
to the manifest the actor believed was current; a candidate carrying an open
finding cannot be activated at all; and the world being replaced is retained rather
than overwritten. Two refusals come with it, and they are worth more now that the
same store has been seen to say yes:

- `test_activation_is_refused_when_the_active_world_moved` — a second reviewer
  racing the first is refused on the expected-manifest check rather than resolved,
  because which of two worlds should survive is not a question code can answer.
- `test_a_candidate_with_an_open_finding_cannot_be_activated` — refused even
  though every digest in the response is internally consistent.

`WorldStore` is **not** PostgreSQL. Production activation is
`promote_foundation_candidate`, with an advisory transaction lock and `FOR UPDATE`,
tested in `supabase/tests/foundation_world_lifecycle.sql` — pgTAP, requiring a live
Postgres, **not executed in this session** and therefore not claimed green here.

### The one PARTIAL, and exactly what would close it

**Claim 1, "v1 compile."** In this chain World v1 is constructed by the same
deterministic builder the revision path uses, not produced by an initial-compile
service. The v3 endpoint refuses `initial_compile` by design
(`test_an_initial_compile_operation_class_is_refused_on_this_route`), and no
Python initial-compile service exists in source anywhere — the same absence that
made `services/core-v3/` necessary in the first place.

The initial-compile **client** path is separately covered and byte-unchanged (§6).
What would close claim 1 is an `initial_compile` service standing beside the
revision one, so the chain begins with a compile rather than with a fixture. That
is honest scope for a follow-up, and it is not closed by calling the current state
PASS.

---

## 6. `initial_compile` backward compatibility — a separate regression result

The revision work must not have disturbed the live path. This is recorded on its
own because a global "the tests pass" does not answer this question.

**Diff evidence, against `origin/main`:**

```
$ git diff --stat origin/main..HEAD -- nextjs/app/api/collections/ \
      nextjs/lib/core-runtime-v2.ts nextjs/lib/core-runtime.ts
 nextjs/app/api/collections/[id]/revise/route.ts | 263 ++++++++++++++++++++++++
 1 file changed, 263 insertions(+)
```

The revision work adds exactly one file under `app/api/collections/`. The compile
route, `core-runtime-v2.ts` and `core-runtime.ts` have **zero diff from
`origin/main`** — so the bytes the live `initial_compile` path signs are unchanged,
not merely believed to be.

**Test evidence:**

| Suite | Result |
|---|---|
| `lib/core-runtime.test.ts` (v1 path) | **2 passed** |
| `lib/core-runtime-v2.test.ts` (`initial_compile`) | **7 passed** |
| `core-runtime-revision.test.ts -t "initial_compile"` | **1 passed**, 41 skipped |

The third is a deliberate guard: it asserts the **exact key list** of
`buildProductCoreV2Request`'s envelope and its route, so a later attempt to unify
the two clients fails visibly rather than by quietly changing what production
signs.

**Regression result: no change to `initial_compile`, in bytes or in behaviour.** ✅

---

## 7. What is blocked, and by what

### Activation of a revised world, in the Product — BLOCKED

The route compiles, verifies and stores. It does **not** write a promotable
candidate.

A candidate world carries collection-level projections beside its files — the
ontology and the directory plan — and the revision contract does not return those.
They are not artifacts in the dependency graph, so the Core neither rebuilds nor
carries them forward. Producing them on the Product side would mean either
presenting pre-revision content as the revised world, or standing a second compiler
beside the one that signed the receipt.

So the result is stored as `revision-receipt.json` under the candidate manifest —
next to, but deliberately not at, the key the promote gate reads — carrying:

```json
{ "activation": "blocked",
  "activationBlockedReason": "COLLECTION_PROJECTIONS_NOT_RETURNED_BY_CORE" }
```

`collection-revision.test.ts` asserts that this receipt's `schemaVersion` is **not**
`tavonel.collection_candidate.v1`, because a receipt that identified itself as a
candidate world would be offered for activation by a gate with no way to know the
projections beside its files were never revised.

**What unblocks it:** the Core returns those projections as artifacts under
reserved ids, so they are rebuilt or carried forward like everything else. That is
a Core change, not a Product workaround.

### A production `SourceResolver` — BLOCKED

`RevisionService` requires a resolver to supply units, graph, artifacts and
builders. The E2E supplies one from a fixture. A production resolver over the real
corpus does not exist, because that *is* the Core compile pipeline.

---

## 8. Test evidence

The research figure is emitted by the repository's own instrument,
`tools/repro/run_test_scopes.py`, under the project interpreter — not by a pytest
invocation of mine.

| Suite | Result |
|---|---|
| Research, **full repository scope** | **3,199 collected, 3,131 passed, 0 failed, 68 skipped, exit 0** — `repository_green: true` |
| Product, `npx vitest run` | **819 passed, 122 files, 0 failed, exit 0** |
| `ruff check`, files this session wrote or changed | **clean** — "All checks passed!" |
| `ruff check`, the paths CI gates | ⚠️ **63 errors, none in files this session touched** — see below |
| `ruff format --check` | ⚠️ **not a CI gate here**, and not clean repo-wide — see below |
| `mypy` strict on `akc_core_v3` | clean |
| `eslint` on every new and changed file | clean, exit 0 |
| `tsc --noEmit`, whole product app | **0 errors, exit 0** |

### The lint row was wrong, and the correction is the point

An earlier draft of this table said `ruff check` / `ruff format --check` — clean.
That was true of the files this session wrote and false as a repository claim, so
it was the **same scope substitution** the section immediately below is about,
committed inside the document that describes it. What the commands actually say,
run here under `ruff 0.16.0` from `.venv`:

| command | result |
|---|---|
| `ruff check services/core-v3 tests/integration/test_revision_compile_e2e.py tests/unit/test_revision_compile.py tools/repro/run_test_scopes.py` | **All checks passed** |
| `ruff check packages services workers benchmark infra` (the `ci.yml` scope) | **62 errors** |
| `ruff check packages services workers benchmark infra tests` (the `release-gates.yml` scope) | **63 errors** |
| `ruff check .` (whole repository, including `research/`) | 1,822 errors |
| `ruff format --check .` | 976 files would be reformatted |

Grouped by file, all 63 are in `infra/runpod/v6/…` (37),
`packages/absorption/…` (10), `services/api/…` (3), `benchmark/…` (4) and a
handful of pre-existing tests. **None is in a file this session wrote or
touched**, which is the part that bears on this work — but "lint green" was still
not mine to say.

Two qualifications, so this is not overstated in the other direction. CI resolves
ruff through `uv run --locked --extra dev`, and the dependency is pinned only as
`>=0.12,<1`; a newer ruff adds rules, so these 63 may not be the number CI sees,
and CI was not run here. And `ruff format` appears in no workflow at all — the
repository does not gate on it, which is why the committed `run_test_scopes.py`
was already unformatted before this session edited it.

### Two guards in this repository caught this session

**Only the full scope may be called the repository.** `TEST_SCOPE_STATUS.json`
states it: *"A green 'unit' scope does not license the phrase; that substitution is
exactly what P18 recorded. […] absence of a run is not a pass."* An earlier draft
of this document reported `tests/unit` + `tests/integration` — 1,030 passed — in
the position where a repository claim belongs. The number was true; it was not the
number being asked for, against 3,199 collected in the full scope.

**A result from the wrong interpreter is not a result about this repository.**
`TEST_SCOPE_SELF_TEST.json` recorded `is_project_interpreter: false`: a run had used
system Python rather than `.venv`. The parser sandbox launches its child with `-I`,
so user site-packages are invisible to it, and that mismatch once produced 24
failures that looked like product defects. Everything was re-run under
`.venv\Scripts\python.exe`; both artifacts now record `is_project_interpreter: true`.

That guard also proves it can say no — it refuses an injected failure and accepts a
clean control on every run (`guard_is_live: true`). A scope-reporting guard that has
never refused anything is an assertion, not a check.

### Mutation evidence

The tests were shown to have power rather than assumed to:

- deleting the carry-forward digest check failed exactly **2 of 37** client tests;
  restoring it passed all 37;
- `test_legacy_predicate_erases_a_normalised_edit` and
  `test_assert_fingerprints_separated_catches_a_folded_fingerprint` fail if the two
  fingerprints are folded back together;
- `test_a_rebuilt_body_that_does_not_match_its_sealed_digest_is_refused` returns
  **v1's bytes** for the clause that changed, because a cache or a wrong key serving
  the previous revision is the realistic failure, not a corrupted byte.

---

## 9. Identity continuity is not change equivalence

Enforced at import time, not by review:

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

Disjoint by construction, and the module refuses to import if that stops being
true. Identity reads *normalised* text so a clause survives a re-typeset; change
reads *raw* text so a re-typeset cannot hide an amendment.
`assert_fingerprints_separated` is the runtime half.

In the E2E `ku_payment` is `continued` **and** `semantic` at the same time. That
pair is the ordinary case for an amended clause; a design that could not express it
would be wrong.

---

## 10. Selective recompilation, measured in three directions at once

| | |
|---|---|
| total artifacts | 7 |
| rebuilt | 4 |
| carried forward | 3 |
| work avoided | 3 |
| stale after revision | 0 |
| full-rebuild equivalence | passed |

Stale-avoidance alone is trivially satisfied by always rebuilding everything —
which would show `workAvoided = 0` and fail. False invalidation alone is trivially
satisfied by rebuilding nothing. The three are asserted together, which is the only
arrangement in which any of them means something.

Both sides check `workAvoided === total - rebuilt`, and the client additionally
requires that rebuilt, carried-forward, unresolved and quarantined sets
**partition** the total, with every carried-forward digest equal to the one the
Product sent.

---

## 11. Source-faithfulness

```python
FAIL_CLOSED_SOURCE_FACT_STATES = frozenset({UNREPRESENTED, UNRESOLVED})
```

`IGNORED_BY_PREDECLARED_POLICY` is excluded from the coverage denominator, so a
broad ignore policy cannot inflate the number.

Coverage crosses the wire as an **integer permille**. `JSON.stringify(1)` is `"1"`
where `json.dumps(1.0)` is `"1.0"`, so a float inside a digested body would make
the two sides disagree about a seal for a reason unrelated to the compile; the
Python canonicaliser refuses floats outright.

E2E: `sourceFaithful: true`, `failClosed: []`, `coveragePermille: 1000`. The
negative case introduces an `UNRESOLVED` fact that leaves `equivalence == "passed"`
and still forces review — the finding that "selective equals full rebuild" is not
sufficient on its own.

---

## 12. Cross-language agreement

The sealed response is validated in Node by the **real** client validator. Digest
agreement between `json.dumps(sort_keys=True, separators=(",",":"),
ensure_ascii=False)` and `canonicalizeRevision` is a result, not an assumption, and
now covers nested documents with strings, integers and arrays.

Two traps were closed before they bit:

- **`localeCompare` is ICU-locale dependent** and cannot be reproduced from Python.
  The revision client sorts by code point. The initial path was left alone
  precisely because changing it would alter what production signs.
- **Line endings.** `Path.write_text` emitted CRLF while git stored LF, and the
  product repo runs `core.autocrlf=true`; the digest binding would have failed on
  every fresh checkout. Fixed at the writer (`newline="\n"`) and pinned with
  `eol=lf` — the same failure `.gitattributes` there already records for the
  developer distribution.

The fixture copy is bound twice: by sha256 inside the test, and by `eol=lf` in git.

---

## 13. SFIR10R4 — frozen operational hold

```
STATUS:  FROZEN OPERATIONAL HOLD
         NOT SCORED
         NO PASS / NO FAIL
```

Untouched this session beyond the read-only seal attempt in §13.4. `segment-01`,
`segment-02`, the runtime state, the incident receipt and the incident correction
receipt are preserved as authoritative evidence and were not modified.

### 13.1 Instrument integrity

Verified, not trusted: the freeze digest recomputes, the protocol digest matches
the live protocol, and **all 15 frozen components are byte-identical** to their
recorded sha256. The roster is sealed at 50 entries under partition 4 (predecessor
3), drawn from 37,702,060 catalogue rows with 1,060 eligible in partition. The
spent-exclusion set is empty.

### 13.2 Authoritative numbers — sealed receipts only

Every figure below was re-read out of the sealed receipts for this document, and
each is labelled with the field it came from. Two of them are not what an earlier
draft assumed.

**Roster progress** — `operational_state.root_states`, a cumulative count of all
fifty roots at the moment each segment sealed:

| | segment-01 | segment-02 |
|---|---|---|
| `FRONTIER_EXHAUSTED` | **32** | **46** |
| `ACTIVE` | 1 (root 33) | 0 |
| `UNSTARTED` | 17 | 0 |
| `STOPPED_BEFORE_EXHAUSTION` | 0 | **4** — roots 33, 37, 45, 47 |
| roster total | 50 | 50 |
| `windows_used` | 1 | **2** (of 6 permitted) |
| `stop_reason` | `SEGMENT_COMPLETE_RATE_WINDOW` | **`ROSTER_TERMINAL`** |

These are cumulative, not per-segment: 46 is the whole study's exhausted count at
the second seal, of which 32 were already exhausted at the first. Segment 2
advanced 14 roots, not 46.

**Provider accounting** — `provider_reconciliation`:

| | segment-01 | segment-02 |
|---|---|---|
| `minimum_attributable_charges` | **1,973** | **1,665** |
| `per_response_unattributed_extra` | 103 | 23 |
| `accounting_is_conservative` | true | true |
| `exact_provider_cost_attribution` | **false** | **false** |
| `capacity_evidence_publishable` | true | true |
| `provider_cost_claim_publishable` | **false** | **false** |

**Cumulative minimum attributable charges: 3,638.**

**Receipt chain** — `segment_digest`, the instrument's chained content digest,
which is *not* the file's sha256 (§18 carries both):

| | |
|---|---|
| segment-01 `previous_segment_digest` | `GENESIS` |
| segment-01 `segment_digest` | `sha256:6710af56…2657e8` |
| segment-02 `previous_segment_digest` | `sha256:6710af56…2657e8` — links |
| segment-02 `segment_digest` | `sha256:14ce28d9…257639` |
| `freeze_digest`, both | `sha256:df6ca140…85cd2e` |
| `protocol_digest`, both | `sha256:44cadd61…4b5f59d` |
| `roster_seal`, both | `sha256:d48d5d28…c2dc00e3` |

The chain is intact: segment 2 names segment 1's digest as its predecessor, and
both name the same freeze, protocol and roster.

### 13.2a The thing the receipts refuse to say

Both sealed segments carry:

```json
"scientific_counts_disclosed": false
```

**No scientific count has been disclosed by either receipt.** The numbers above
are *operational* — roster progress and provider charges — and the instrument
deliberately separates them from the census the study exists to produce. So R4 is
unscored for two independent reasons, and the second is the stronger: the seal was
refused (§13.4), *and* even the sealed segments withhold the scientific counts by
design. There is no number here that could be read as a result even by someone
willing to misread one.

### 13.2b What this disproves

An earlier report of mine said segment 2 was killed by a harness teardown. The
sealed receipt says `stop_reason: "ROSTER_TERMINAL"` — segment 2 ended because it
reached the end of the fifty-root roster, which is the ordinary terminal condition,
not an incident. The premise is retracted on the receipt's own evidence, not on my
recollection.

`35 roots / 2,307 charges` also appeared in an earlier report. **It was never a
result** — a live read of `runtime/sfir10r4/state.json` taken while segment 2 was
still in flight. It is discarded. Console output is not evidence.

### 13.3 The incident, and its correction

`sfir10r4-incident-harness-teardown.json` (`sha256:89ecb962…2290`) records a
failure that **did not happen**. A harness task-status notice was treated as
evidence about an operating-system process. It is not. The runner was never killed:
it ran roughly forty minutes past that notice, completed the segment, sealed it,
unlinked its own active-segment marker and exited cleanly.

`sfir10r4-incident-correction.json` (`sha256:6a0dc595…ce31`) supersedes it. **The
wrong receipt is kept exactly as written** — an incident record quietly rewritten
once the facts improve is not evidence.

Two things were *not* done while that mistaken belief was held, and either would
have destroyed the study:

1. **The active-segment marker was not deleted.** The instrument treats a marker
   with no sealed receipt as terminal `MEASUREMENT_UNPROVEN`; deleting it would
   have been tampering, and the runner still needed it.
2. **The runner was not killed** to make the state match the report. During its
   sealing phase that would have manufactured precisely the `MEASUREMENT_UNPROVEN`
   outcome being reported as inevitable.

**There is no crash state, and therefore no reason to write
`MEASUREMENT_UNPROVEN`.** Forcing that label now would manufacture a failure the
study did not have — the mirror image of overwriting a failure with a success, and
wrong for the same reason. R4 is recorded as **not scored**, which is what it is.

### 13.4 The seal was attempted, and the instrument refused

With the marker consumed and every root terminal, `run-segment` routes to
`finalize()`, which reads root evidence from disk and **opens no socket** — the
no-further-scientific-requests constraint was met by the code path, not by a
promise.

It refused, and **wrote nothing**:

```
REFUSED  counted root carries no immutable revision snapshot
```

**49 of 50 roots pass the evidence gate. Root 45 alone fails** — stopped before
exhaustion, zero candidates, no snapshot recorded. `_validate_root_evidence`
requires that a root counted as exhausted or stopped carry one, because sealing
otherwise lets a root with nothing behind it contribute to the capacity
disposition.

The seal-attempt receipt records the state it read, and those fields were
re-verified for this document:

| field | value |
|---|---|
| `roots_passing_evidence_gate` | 49 |
| `roots_failing_evidence_gate` | 1 |
| `failing_root_ordinal` | 45 |
| `failing_root_status` | `STOPPED_BEFORE_EXHAUSTION` |
| `failing_root_candidates` | 0 |
| `failing_root_snapshot` | `null` |
| `measurement_unproven` | **false** |
| `segment_chain_head` | `sha256:14ce28d9…257639` — segment-02's digest |
| `windows_used` / `windows_permitted` | 2 / 6 |
| `stopped_roots` | 33, 37, 45, 47 |

`measurement_unproven: false` is the instrument's own reading, not mine.

Outcome: `SEAL_REFUSED_BY_INSTRUMENT_EVIDENCE_GATE`, recorded in
`sfir10r4-seal-attempt.json` (`sha256:d453a3c5…a03d`). No census, no score, no
acceptance and no terminal-unproven receipt exists; runtime state is unchanged.

Three ways to clear the gate were available, and all three are tampering, so none
was taken: `root-045.sqlite` was not touched; root 45 was not reclassified to
`REPOSITORY_IDENTITY_REFUSED`, because relabelling a stop as a refusal is a
different scientific claim; no protocol constant was changed.

**The only legitimate path** is a third segment replaying the four stopped roots —
four of six permitted windows are unused. It sends cohort requests, so it is the
owner's decision, and it was not taken.

### 13.5 Predecessors

R1 and R2 died at `windows_used 0` ("per-response provider delta is 2; exclusive
attribution is not established"); R3 at `windows_used 0` ("provider reset epoch
changed mid-segment"). **R4 is the first attempt to clear the accounting preflight
and measure the cohort at all.**

### 13.6 Operational correction for any successor

A frozen segment must run as a **detached process with its own PID file, log and
heartbeat**, independent of any agent session — not because the runner was fragile,
it was not, but because the supervising agent could not tell whether it was, and
acted on that uncertainty. Recoverability must be defined before the run, not
inferred after it. Scientific criterion, threshold and cohort-selection logic must
not change; only execution infrastructure may.

---

## 14. GPU and RunPod

**No GPU provisioned. No GPU cost incurred. No idle GPU to terminate.**

SFIR10R4 is a provider-metadata census over the GitHub REST API — network and CPU
work. The frozen protocol grants no GPU execution authority, and using GPU the
protocol does not authorise would be bypassing a gate.

The `infra/runpod/v6` lane is intact and untouched. Its rule stands: build
integrity is not runtime qualification; a paid pod may claim
`qualification_state: READY` only against a complete `baked_runtime_qualification`
whose sha256 matches, and `BakedImageBuildReceipt` rejects any build-only receipt
that tries to waive the GPU smoke test.

---

## 15. OCR and recovery lane

The brief anticipated broken OCR recovery tests. **That premise does not hold.**
`test_recovery_policy.py` and `test_cause_conditioned_recovery.py` run green — 49
tests — and the full research scope has zero failures. There was nothing to repair,
and inventing a repair would have been worse than reporting that.

---

## 16. Claims discipline

**No public claim is unlocked.** These five phrasings remain forbidden:

> "Always stays current" · "Only changed slices recompile" · "No stale knowledge" ·
> "Automatically keeps itself correct" · "Every source update is fully propagated"

What may honestly be said internally: a revision compile has been demonstrated end
to end on a deterministic fixture, across a process boundary and a language
boundary, including both activations, with a machine-verifiable receipt. That is a
laboratory result on one fixture — not a production behaviour — and the Product
activation path for a revised world is blocked.

Both sealed SFIR10R4 segments say `provider_cost_claim_publishable: false`.
**No cost figure from that study may be published.**

---

## 17. IP

No patent action was taken, proposed or prepared. Filing and publication timing are
the founder's to decide; nothing was disclosed publicly.

The identity/change separation and the source-fact state machine are the
technically novel parts here and are the natural candidates for a
disclosure-registry review against the existing KR filing — a founder decision, not
an agent's.

---

## 18. Evidence index

Receipts carry an internal content digest *and* have a file sha256, and the two are
different numbers. An earlier draft printed the internal digest in a column headed
"sha256", which would send anyone trying to verify the file to the wrong value.
Both are given.

| Artifact | Internal digest | File sha256 |
|---|---|---|
| `research/tavonel_eval_v2/receipts/sfir10r4-segments/segment-01.json` | `segment_digest` `sha256:6710af56…2657e8` | `c6e25e78…daa318c` |
| `research/tavonel_eval_v2/receipts/sfir10r4-segments/segment-02.json` | `segment_digest` `sha256:14ce28d9…257639` | `f7302439…88dbab85` |
| `research/tavonel_eval_v2/receipts/sfir10r4-incident-harness-teardown.json` | `incident_digest` `sha256:89ecb962…f22290` | `43f73b17…2b3b15b3` |
| `research/tavonel_eval_v2/receipts/sfir10r4-incident-correction.json` | `correction_digest` `sha256:6a0dc595…94ce31` | `fd25457c…97e70feca` |
| `research/tavonel_eval_v2/receipts/sfir10r4-seal-attempt.json` | `attempt_digest` `sha256:d453a3c5…6a3a03d` | `9f26d95d…6423877df` |
| `nextjs/lib/__fixtures__/revision-compile-e2e-v1.json` | — | `d8f3ce10…601ecaaa` |
| `docs/repro/TEST_SCOPE_STATUS.json` (repository verdict) | — | `e6c08b70…ba87f6e0` |

`sfir10r4-incident-correction.json` names its predecessor explicitly —
`supersedes: "receipts/sfir10r4-incident-harness-teardown.json"` with
`supersedes_digest` equal to that receipt's `incident_digest` — so the superseding
is recorded in the evidence, not only in prose.

---

## 19. Declaration

**PARTIAL.**

Against the completion checklist, item by item:

| Condition | Result |
|---|---|
| full Product tests green | ✅ 819 passed, 122 files, 0 failed, exit 0 |
| full Research tests green | ✅ full scope, `repository_green: true`, 3,131 passed, 0 failed |
| typecheck green | ✅ `tsc --noEmit`, whole app, 0 errors, exit 0 |
| lint green | ⚠️ **clean for this session's files; not clean repository-wide** — 63 pre-existing `ruff check` errors at the CI-gated scope, none in a file this work touched (§8) |
| revision E2E green | ⚠️ 16 of 17 claims PASS; **claim 1, "v1 compile", is PARTIAL** — World v1 is fixture-built, not produced by an initial-compile service |
| provenance carry-forward green | ✅ both halves, Python and Node |
| no unrelated work lost | ✅ three concurrent-workstream items preserved uncommitted |
| intended trees clean | ✅ product tree empty; research tree clean of this session's work |
| commits recorded | ✅ §2 |
| push status recorded | ✅ §2 — **nothing is pushed to any remote** |
| R4 status accurately recorded | ✅ §13 — frozen operational hold, not scored, no PASS/FAIL |

**The blockers that prevent COMPLETE, stated exactly:**

1. **"v1 compile" is not a compile.** No initial-compile service exists in source,
   so the demonstrated chain begins with a fixture-built world. Closing it means
   writing that service beside the revision one.
2. **Revised-world activation is blocked in the Product** on
   `COLLECTION_PROJECTIONS_NOT_RETURNED_BY_CORE`. The route stores a receipt that
   says so rather than a candidate that looks promotable.
3. **No production `SourceResolver`** exists over the real corpus.
4. **SFIR10R4 is unscored**, and its seal is refused by its own evidence gate until
   a third segment gives root 45 a revision snapshot. That segment sends cohort
   requests and is the owner's call.
5. **Neither work branch is pushed**, and neither may merge to `main` before the
   qualification gate, which blockers 1–3 prevent.
6. **The repository is not lint-clean at the scope CI gates** — 63 pre-existing
   `ruff check` errors under ruff 0.16.0, none of them in a file this session
   wrote or changed. Not caused by this work and not fixed by it; recorded
   because "lint green" was claimed before it was checked.

Two further corrections were made while writing this document, and both belong
in it rather than in a silent edit. The receipt digests printed under a heading
reading "sha256" were the receipts' *internal* content digests, which are not
the files' sha256 — anyone verifying them would have been sent to the wrong
number, so §18 now carries both. And the tool that writes the repository's own
green verdict wrote it with CRLF while git stored LF, so its cited digest never
reproduced on a fresh checkout; that is fixed in `7b43a14`, the same defect and
the same fix as the cross-language fixture in §12.

One process note, since it touches a rule this work is bound by: a `git stash`
was used to compare a file against `HEAD`, which is not how that comparison
should be made when another worker's uncommitted changes are in the tree. It
round-tripped cleanly and was verified immediately afterwards — stash list
empty, all twenty-two `research/model_arena_20260903/` entries present, both
concurrent modifications intact — so nothing was lost. It should not have been
the method, and `git show HEAD:<path>` was used for every comparison after it.

Nothing above was rounded up. Six times this session a reported figure or premise
of mine was wrong, and each time one of the repository's own instruments — the
process table, the sealed receipts, the interpreter guard and the scope guard —
refused it before it reached this document. Those refusals are recorded here beside
the corrections rather than replaced by them.
