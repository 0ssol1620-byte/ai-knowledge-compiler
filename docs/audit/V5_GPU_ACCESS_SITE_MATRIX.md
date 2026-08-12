# GPU worker access-site matrix — every `gpu_provider_invocations` path, under NOBYPASSRLS

*Measured 2026-08-12 on a throwaway PostgreSQL 17.2 cluster (own data directory,
port 55443, destroyed after) with the full migration tree applied to
`0037_gpu_post_claim_authorization`, `akc_gpu_worker` at **NOBYPASSRLS**, and the
real `GpuInvocationWorker` connected through a login principal holding that one
role. The machine's own `postgresql-x64-17` service and its `akc` database were
not touched.*

**One documented deviation, the same one every previous measurement in this
repository carries.** pgvector is not installed on this machine, so a *copy* of
the migration tree outside the repository substituted `vector(1024)` with
`real[]` and omitted the `hnsw` index, per `V5_PRIVILEGE_RECEIPT_FINDINGS.md`
§Method. The repository was not modified. The substitution's irrelevance is not
argued here — it is **measured**: before this change, the privilege receipt
generated from this cluster was byte-identical to the then-committed
`docs/audit/receipts/privilege-receipt-0037.json`, which is what the CI job
produces against `pgvector/pgvector:pg17`. That receipt is regenerated here
because the claim policies changed; the only lines that move are the four
`*_claim_binding` predicates, the revision name and the receipt hash — no role,
membership, grant or finding differs.

---

## 0. The four classifications

Every path below is exactly one of these. They are separated because they are
authorized by different mechanisms, and a proof that blurs them proves the wrong
thing.

| | what it is | what authorizes it |
|---|---|---|
| **DISCOVERY** | before any row is known | a declared control-plane purpose, through `akc_claim_gpu_invocation` |
| **ACTIVE CLAIM** | a lease is held | `enter_claim_context` — tenant, project, row, lease token |
| **CALLBACK / LEASE-INDEPENDENT** | no lease exists to hold | `enter_callback_context` — tenant, project, row |
| **OTHER** | observability | a declared purpose; counts only, no rows |

---

## 1. The matrix

`gpu_jobs.py` line numbers are as of this change. **Proof** names the case in
`infra/postgres/verify_gpu_nobypassrls.py` unless stated otherwise.

| # | site | class | mechanism | measured | proof |
|---|---|---|---|---|---|
| 1 | `_claim` ORM queue scan · `gpu_jobs.py:954` | DISCOVERY | none — cross-tenant `SELECT` | **0 of 3 claimable rows** | `discovery:before-path-claim-scan-sees-nothing` |
| 2 | `_claim` → `enter_tenant_context` → `_claim_from_row` · `:971` | ACTIVE CLAIM | tenant only | unreachable: site 1 returns nothing | — (blocked upstream) |
| 3 | `_claim_via_broker` broker call · `:1010` | DISCOVERY | `enter_control_plane_context('claim')` + definer function | grants a claim | `discovery:broker-grants-a-claim-to-a-disarmed-worker` |
| 4 | `_claim_via_broker` scoped reread · `:1024` | ACTIVE CLAIM | `enter_claim_context` | 1 row | `after:only-the-claimed-row-is-rereadable` |
| 5 | `_claim_from_row` lease stamp + transition + commit · `:1076`–`:1155` | ACTIVE CLAIM | claim context from site 4 | writes commit | `claim:run-one-submits-and-releases-the-lease` |
| 6 | `_locked_invocation` · `:1282` | ACTIVE CLAIM | **`enter_claim_context`** (was `enter_tenant_context`) | 1 row; 0 rows with tenant only | `claim:locked-invocation-reads-its-row`, `claim:tenant-only-binding-still-sees-nothing` |
| 7 | `_record_submission` · `:1315` | ACTIVE CLAIM | via site 6 | status `submitted`, lease released; a *lapsed* lease still reads 0 | `claim:run-one-submits-and-releases-the-lease`, `claim:a-released-row-is-not-readable-without-its-token`, `claim:a-lapsed-lease-is-refused-where-a-released-one-is-admitted` |
| 8 | `_record_poll_wait` · `:1360` | ACTIVE CLAIM | via site 6 | status `running`, lease released | `claim:run-one-records-a-poll-wait` |
| 9 | `_admit_result` (poll) · `:1553` | ACTIVE CLAIM | via site 6 | status `completed` + manifest | `claim:run-one-admits-a-terminal-result` |
| 10 | `_admit_result` (callback, `require_lease=False`) · `:1553` | CALLBACK | `enter_callback_context` | status `completed`, source `callback` | `callback:admit-callback-completes-a-leaseless-row` |
| 11 | `_schedule_failure` · `:1702` | ACTIVE CLAIM | via site 6 | status `failed`, code recorded | `claim:run-one-records-a-failure` |
| 12 | `_lineage_state` parent chain · `:616` | ACTIVE CLAIM | via site 6 | **0 rows — GAP** | `gap:lineage-parent-row-is-unreadable` |
| 13 | `_create_transition` child `INSERT` · `:824` | ACTIVE CLAIM | via site 6 | **`42501` permission denied — GAP** | `gap:transition-child-insert-is-denied` |
| 14 | `_finish_cancel` · `:1835` | ACTIVE CLAIM | via site 6 | status `cancelled` | `claim:run-one-finishes-a-cancellation` |
| 15 | `_retry_cancel` · `:1908` | ACTIVE CLAIM | via site 6 | shares the release write of 14 | covered by 14 |
| 16 | `admit_callback` invocation lookup · `:2141` | CALLBACK | **`akc_resolve_gpu_callback` + `enter_callback_context`** (was an unscoped read by id) | 0 rows unscoped; 1 row bound | `callback:the-old-read-by-id-sees-nothing`, `callback:binding-reaches-one-row-and-no-other` |
| 17 | `_observe_poll` → `claim_backlog` · `:1984` | OTHER | `enter_control_plane_context` + two definer probes | backlog 2, claimable 2 | `other:the-backlog-probes-still-see-the-queue` |

**Sites outside `akc_gpu_worker`.** `akc_api.collection_api`, `akc_api.deletions`,
`akc_api.document_versions`, `akc_api.gpu_jobs` and `akc_api.main` also read or
write this table. They run as `akc_api_plane` (human plane) or
`akc_deletion_worker`, neither of which canary B touches, and both keep
`BYPASSRLS` or their own membership policies. They are out of scope here and
**not proven** by this matrix.

---

## 2. The two gaps, and what they are not

Both are asserted as failures in the proof, so fixing either turns
`verify_gpu_nobypassrls.py` red rather than letting this document go stale.

**GAP-1 — `_create_transition` cannot insert its child row.**
`akc_gpu_worker` holds `SELECT` and twenty-one column-level `UPDATE` grants on
`gpu_provider_invocations`, and **no `INSERT`**. Measured `42501 permission
denied for table gpu_provider_invocations` **with `BYPASSRLS` on and with it
off** — `BYPASSRLS` bypasses row-level security, not table privileges. This is a
pre-existing defect that canary B neither causes nor fixes: the OOM-reduction and
invalid-output-fallback transitions have never been able to run as this role.
Granting `INSERT` is a privilege decision and is not taken here.

**GAP-2 — `_lineage_state` cannot read a parent invocation.**
The claim binding admits exactly the claimed row, and the lineage walk reads
`parent_invocation_id`. A transitioned (child) invocation reaching
`_schedule_failure` would raise `gpu_invocation_lineage_parent_missing`.
Unreachable today *because* GAP-1 means no child row is ever written; recorded so
that granting `INSERT` does not quietly turn a permission error into a lineage
error.

---

## 3. What changed to make the rest green

**`_Claim` gained `project_id` and `lease_expires_at`**, populated from the
claimed row on both paths — the broker path additionally refuses when the
broker's project disagrees with the row's (`claim_broker_project_mismatch`).
`lease_token` and `lease_expires_at` became optional, and are `None` on the
callback path, because a callback has no lease. The previous code wrote
`invocation.lease_token or uuid.uuid4()`, minting a token whenever the row had
none — which is every ordinary callback.

**`_locked_invocation` binds the claim**, or, when `require_lease=False`, the
callback. Both are the existing mechanism in `akc_security.tenant_context`;
`enter_callback_context` is new and sits beside `enter_claim_context` with the
same fail-closed discipline and no lease field to forge.

**The lease is released by clearing its expiry, not by nulling the token.** This
was forced by a measurement, and the measurement is worth keeping. Five shapes
were built on a scratch table and run; four are rejected:

```
A  release UPDATE, claim policy admitting `lease_token IS NULL` in WITH CHECK only
     -> 42501, while the WITH CHECK expression evaluates TRUE against the row
        PostgreSQL just rejected
B  release UPDATE, same disjunct in USING and WITH CHECK
     -> OK, but a worker then reads an unleased row it never claimed: 1 row
C  release UPDATE, policy split into FOR SELECT (strict) + FOR UPDATE (+release)
     -> 42501, identically
D  release = `lease_token = app.lease_token AND lease_expires_at <= now()`
     -> OK; unclaimed-row read 0 rows; but a session naming its OWN expired
        lease reads its row -> shadow_validate_dual_plane [claim:expired-lease]
        FAILED, "expired-lease yields no rows"
E  release = `lease_token = app.lease_token AND lease_expires_at IS NULL`
     -> OK; unclaimed-row read 0 rows; expired-lease read 0 rows
```

An `UPDATE`'s new row has to satisfy the *read* side of an `ALL` policy, so the
release cannot live in `WITH CHECK` alone (A, C). Admitting a token-less row
leaves the predicate holding only a tenant and an id, which makes every unleased
row in the tenant readable **and writable** to a worker that knows its id (B).

D and E both keep the token in the predicate, so releasing gives up an authority
instead of acquiring one — but D also erases the difference between a lease
*given up* and a lease that *lapsed*, and a lapsed lease is the one case the
binding exists to refuse: that worker has been superseded and another may hold
the job. `shadow_validate_dual_plane.py` asserts exactly that, by name, and went
red on D. **That gate was not edited.** E clears the expiry instead, which is
already what "not leased" means everywhere in this schema — no sentinel value is
introduced, `lease_expires_at IS NULL` is what every claim predicate here already
accepts as claimable, and a re-claim overwrites the token.

The released/lapsed distinction is now asserted on `gpu_provider_invocations`
too, on one row and one token a single statement apart
(`claim:a-lapsed-lease-is-refused-where-a-released-one-is-admitted`). Re-running
the rehearsal against a policy that admits both shapes fails that one case and no
other — the check was demonstrated to fail before it was trusted.

**`0037` is deterministic and flips no role attribute.** It rewrites the four
`*_claim_binding` policies at one predicate shape and adds the callback resolver.
Its upgrade and downgrade both assert that no `akc_*` role's `rolbypassrls`
changed. The canary disarm moved to `infra/postgres/canary_b_disarm.py`.

---

## 4. Canary A is a precondition of canary B

`GpuWorkerPolicy.use_claim_broker` still defaults to `false`, which selects the
ORM scan at site 1. Measured at **0 of 3 claimable rows** under NOBYPASSRLS: a
disarmed worker on the shipped default claims nothing at all. Gate 1A *would*
catch that one — `claimed=False` with a non-zero backlog is the starvation
signature — but it is a precondition, not a fallback, and the proof asserts it by
name so the ordering cannot be lost.

---

## 5. What is still not proven

- **Gate 1B, real workload observation.** Unchanged, still pending.
- **The API-plane and deletion-worker sites** in §1's footnote. Out of canary B's
  blast radius, and not measured.
- **`admit_callback` has no production caller.** No HTTP route in this repository
  invokes it; the signature validation and the "the HTTP boundary must validate
  the callback signature" contract in its docstring are unenforced by anything
  here. The authorization boundary this change adds is real and measured; the
  thing that is supposed to authenticate the caller is not in the tree.
- **The canary itself has not been run.** Everything above is a rehearsal:
  `canary_b_disarm.py` without `--leave-disarmed` disarms, proves, receipts and
  rolls back inside one command. `BYPASSRLS` is 7/7 at the end of every run in
  this document, and canary B remains BLOCKED.
