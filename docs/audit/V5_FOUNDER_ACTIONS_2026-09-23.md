# Founder Actions — current, 2026-09-23

*What still needs a person. `V5_FOUNDER_ACTIONS.md` remains the Arena-phase
budget and credential record from 2026-08-11 and is not rewritten; this file is
the current open list and supersedes it where the two disagree.*

The fuller record behind this list — what was discussed, what was built, what
was measured and what went wrong — is
[`SESSION_RECORD_2026-09-23_ROUTER_AND_COPY.md`](SESSION_RECORD_2026-09-23_ROUTER_AND_COPY.md).

Every item here is one of the things `CLAUDE.md` reserves: what a public claim
says, irreversible production or destructive actions, customer data consent,
pricing, patent and publication timing, missing secrets and payment
credentials. The F-1 product defects discovered in the continuation are
tracked separately below.

---

## 0. Stop the line — CI has not run since 2026-09-22

**GitHub Actions is refusing to start any job on this repository.** Every check
on every branch fails in one to five seconds with the same annotation:

> The job was not started because recent account payments have failed or your
> spending limit needs to be increased. Please check the 'Billing & plans'
> section in your settings.

This is not specific to a branch. `main`'s own run on 2026-09-22 failed the
same way, and the Vercel check reports `Deployment was blocked` alongside it.

What that means in practice, and why nothing else in this file matters more:

- **No pull request can be verified.** A green tick is unavailable, and a red
  one currently says nothing about the code. PR #76's checks are red for this
  reason and this reason only; its tests pass locally.
- **Nothing can be merged on evidence.** `CLAUDE.md` makes a phase done only
  when the repository is green. There is no green to be had.
- **Nothing deploys.** `main` auto-deploys production, and the deploy path runs
  through the same account.

The authenticated billing screen now identifies the concrete cause: the
account has used all 2,000 included Actions minutes, its Actions budget is $0
with stop usage enabled, and it has no registered payment method. A payment
method must be added in **Billing & plans** on the `0ssol1620-byte` account;
only then can a nonzero Actions budget be effective. The public site repository
does run CI, so this block concerns the private compiler repository and PR #76.

Until it is fixed, treat every check result in this repository as *unknown*,
not as *failing*.

---

## 1. Blocked on a click or a credential — nothing else moves these

| # | Action | Where | Why it is yours |
|---|---|---|---|
| **F-0** | Settle GitHub Actions billing | account **Billing & plans** | §0 — blocks all CI and all deploys |
| **F-1** | Reset the `0ssol1620@gmail.com` workspace to empty | `https://tavonel.com/workspace/settings/usage` → "Start this workspace from empty" → type `DELETE TEST DATA` | Irreversible destructive action on live data |
| **F-2** | Insert the missing migration-ledger row | production SQL, below | Production database write |
| **F-3** | Decide whether `/benchmarks` publishes a TAVONEL result | §3 | What a public claim says |
| **F-4** | Reissue the DPA as v2 | §4 | A versioned legal document |

**Continuation, 2026-09-23:** The founder authorized these decisions and production writes.
F-2 is complete: the live schema already contained the source-deletion inventory
fix, and the missing `20260921110000` and `20260921120000` migration-ledger rows
were inserted transactionally and read back. F-3 has a source-linked R-01
candidate and F-4 has a versioned v2 draft in the isolated site
[PR #99](https://github.com/0ssol1620-byte/tavonel-saas-foundation/pull/99);
neither is live. F-1's authenticated dry run exposed two product defects:
the ledger `state` lacked its `prepared` default (fixed and verified in
production as migration `20260923034853`), and the API omitted the top-level
reset ID expected by the UI (fixed in PR #99). The reset has **not** executed.
F-0 is specific to the private compiler repository: the account has exhausted
its 2,000 included Actions minutes, its Actions budget is $0 with stop usage,
and no payment method is registered. The public site repository's PR #99 CI
does start and is running; the private compiler PR #76 cannot start jobs yet.

### F-1 — what is in there now

74 intake admissions, 71 compute reservations, 10 compile jobs, 1 job. All of
it is test data from build sessions. The control exists and is wired; it
deliberately refuses to fire without the typed confirmation.

### F-2 — the migration ledger

At the original handoff, production's ledger stopped at `20260921064244`,
although the schema change itself was already applied. The repository also
contained `20260921110000` and `20260921120000`; both ledger entries were
missing. They are now present in the production ledger after a transactional
insert and read-back. No source-deletion data row was changed.

```sql
insert into supabase_migrations.schema_migrations (version, name)
values
  ('20260921110000','source_deletion_inventory_attestation'),
  ('20260921120000','source_deletion_inventory_document_id_type_fix')
on conflict do nothing;
```

The original session's auto-mode classifier denied this production write. The
founder subsequently authorized production writes in the continuation, which
used the authenticated Supabase SQL tool and verified both ledger entries.

---

## 2. The parse router — what the founder has now cleared, and what is left

The work itself is on `agent/router-second-reader-20260923`
([PR #76](https://github.com/0ssol1620-byte/ai-knowledge-compiler/pull/76)) and
the decision record is
[`docs/adr/ADR-007`](../adr/ADR-007-element-aware-second-reader.md), whose
§Activation log carries the detail.

| Item | State |
|---|---|
| 1. Licence | **Cleared 2026-09-23.** Snapshots captured and hash-bound; see the three caveats below |
| 2. GPU serving | **Approved 2026-09-23.** Digests resolved for free; qualification run in progress |
| 3. `model_registry` rows | **Open — production database writes** |
| 4. No-regression benchmark of the pair | **Open — has not moved** |

### Three things the licence snapshots say that "approved" does not

1. **`mineru_vlm`'s runtime is not plain Apache-2.0.** MinerU adds a
   commercial-licence threshold at **100M MAU or USD 20M monthly revenue**, an
   online-service attribution obligation, and automatic termination on breach.
   Below those numbers nothing further is needed. Crossing either one requires a
   separate commercial licence *before* use continues. That is a business
   trigger and nothing in this repository watches for it.
2. **`mineru`'s model card declares no licence at all.** Readable is not
   reusable, so that row stays out of traffic.
3. **No dataset licence is published for any of them.** Code, weights, dataset
   and hosted-API terms are four separate licences. Two are cleared; the other
   two are not, and clearing one clears none of the others.

`ovisocr2`'s card also names `base_model: Qwen/Qwen3.5-0.8B`, whose own terms
the snapshot does not cover.

### Why item 4 has not moved, and why it is the one that matters

The rescue table ADR-007 is built on is an **oracle ceiling**: it was measured
by always picking the better of two pages. A shipped router does not know which
is better — it has to decide. The table bounds *how much there is to win*, not
how much a router wins. Until a same-condition benchmark of the pair exists,
`traffic_percent` stays 0 and every decision resolves to
`cross_check_peer_unavailable`, which is the designed fail-closed state rather
than a defect.

### What item 3 will need, when you get to it

Rows in the production `model_registry` table. `_binding` refuses a row without
an endpoint, a revision, a runtime image digest, a model id and an adapter
version, and `validate_registry_binding` additionally refuses one with no
benchmark report. Those refusals are the point; do not relax them to get a row
in.

---

## 3. F-3 — `/benchmarks` still publishes no TAVONEL number

The page quotes competitors and publishes none of our own results. The
strongest candidate already in the tree is **R-01** in
`nextjs/lib/evidence-record.ts`:

> olmOCR-Bench **80.6** with recovery against **53.7** with only that lane
> disabled, over 1,403 documents and 8,413 checks, with non-overlapping 95%
> confidence intervals.

It is ours, same-condition, and it has a receipt. Three rules bind whatever you
decide:

- It is a **recovery** result, not an accuracy claim, and the denominator
  travels with it.
- Competitor rows stay **quoted**, never restated as reproduced.
- The 36.9% low-quality-scan row and the *not supported* blind-quality
  hypothesis stay published. Weaknesses are not averaged away.

---

## 4. F-4 — the DPA carries an internal phrase

`nextjs/public/policy/TAVONEL_DPA_v1_2026-09-11.md` says "this deployment" at
lines 82, 167 and 195. Every other instance of that phrasing has been removed
from the site, but a DPA is a versioned legal document: editing v1 in place
would change a document customers may already hold under that name, and four
links pin its exact path.

So it needs a **v2 reissue** with a new filename and the four links moved, not
an edit. That is a legal-document decision, not a copy fix.

---

## 5. Still unanswered from your earlier message

**The "접근권한요청" buttons.** I could not find any such control in the
workspace — no component, route or string matches it anywhere in the site
repository. Either it is on a surface I have not been given, or the label is
being translated in your browser. An untranslated screenshot with the URL
visible would resolve it in one step.

---

## 6. Not a founder decision, recorded so it is not mistaken for one

- **The 24 red `services/api` tests on the development machine are a local
  Python install artifact**, not a code defect and not a live-service problem.
  The parser sandbox launches with `-I`, which deliberately ignores the user
  site-packages where `starlette` is installed, so the child process dies at
  import. Diff the `FAILED` list against `HEAD` before treating it as a
  regression.
- **19 Dependabot advisories on the default branch** (4 critical, 6 high, 9
  moderate) are reported on every push. Nobody has triaged them. This is
  ordinary work, not a decision — it only needs to be scheduled.
