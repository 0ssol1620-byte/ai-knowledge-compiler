# Worker Authorization — Phase 0 Spike Results

*Measured 2026-08-11 on a throwaway PostgreSQL 17.2 cluster (port 55440, own
data directory, destroyed after). Settles the assumption the recommended
architecture rests on, before anyone builds on it.*

The design in `docs/audit/V5_WORKER_PRIVILEGE_BOUNDARY.md` and its successor
plan named one load-bearing assumption it could not verify from the repository,
and said plainly that the recommendation collapses without it:

> A policy that does not apply to the current role is not planned, so the tables
> its expression references are not ACL-checked.

**It holds.** Two further facts came out of the same experiment, one of which
constrains the design.

---

## The model

A data table (`docs`) whose policy consults a membership table the service role
has no grant on — the exact shape of the 27 tables where the real blocker lives.

```sql
GRANT SELECT ON docs TO svc_worker;   -- worker can read docs
--   (deliberately no grant on memberships)
ALTER TABLE docs ENABLE ROW LEVEL SECURITY;
ALTER TABLE docs FORCE ROW LEVEL SECURITY;
CREATE POLICY docs_human ON docs AS RESTRICTIVE FOR ALL TO PUBLIC
  USING (EXISTS (SELECT 1 FROM memberships m WHERE m.tenant_id = docs.tenant_id));
```

## A — the blocker reproduces in isolation

```
SET ROLE svc_worker; SELECT count(*) FROM docs;
  ERROR: permission denied for table memberships
```

Not zero rows. An error, exactly as observed against the real schema. The policy
is `TO PUBLIC`, so it applies to the worker, so its subquery is planned, so the
worker needs SELECT on `memberships`.

## B — retargeting removes the requirement — **the assumption holds**

```sql
ALTER POLICY docs_human ON docs TO human_plane;   -- worker is not a member
```
```
SET ROLE svc_worker; SELECT count(*) FROM docs;
  rows_visible = 1
```

No error, no membership grant, row visible. **A policy that does not apply to
the current role costs nothing — not even an ACL check on what it references.**

This is the door the recommended architecture walks through, and it is open.

## C — a RESTRICTIVE policy alone grants nothing

An `INHERIT` member of `human_plane` still saw **0 rows** after retargeting,
even with a matching membership row present. RLS needs at least one applicable
**PERMISSIVE** policy; `RESTRICTIVE` only subtracts. Adding
`docs_human_allow ... AS PERMISSIVE TO human_plane` produced `1`.

This is the same property that makes the 31 collection-family tables
default-deny for any non-BYPASSRLS role. **Retargeting the RESTRICTIVE policies
to a human plane is not sufficient on its own** — the human plane needs its
permissive grant policy too, on every table where no `*_tenant_isolation`
PERMISSIVE already covers it.

## D — `polroles` does not reach a NOINHERIT member — **this constrains the design**

```
NOINHERIT member of human_plane, with table grants applied directly:
  SELECT count(*) FROM docs;   ->   0
INHERIT member of human_plane:
  SELECT count(*) FROM docs;   ->   1
```

Policy applicability follows role membership the same way privileges do, so a
`NOINHERIT` role does not pick up a policy targeted at a group it belongs to.

**Why it matters here.** Every runtime login role in this repository is
`NOINHERIT` and reaches its worker identity through `SET ROLE`
(`infra/postgres/init/010-scheduler-runtime.sql`). That is fine for the service
plane — after `SET ROLE akc_url_fetcher` the current user *is*
`akc_url_fetcher`, so a policy `TO akc_url_fetcher` matches directly. It is not
fine for group targeting.

Two rules follow:

1. **Service policies target worker roles directly.** Never a group.
2. **`akc_human_plane` only works for members that INHERIT.** If a future API
   role is created `NOINHERIT` and assumes the plane by `SET ROLE`, it will not
   match — it must be granted the plane with inheritance, or the policies must
   target it directly.

Rule 2 is the kind of thing that is invisible until an API role exists and
silently sees nothing. Recorded here so it is a decision rather than a surprise.

## E — the two planes are genuinely independent

With `docs_human` targeted at the plane and a service policy at the worker:

| | membership row present | membership row deleted |
|---|---:|---:|
| human plane member | 1 | **0** |
| service worker | 1 | **1** |

Revoking a person's membership removes that person's access and leaves the
worker's untouched. That is the property the whole exercise exists to produce:
**the worker is not borrowing anybody's authority.**

---

## Consequences for the plan

| Plan assumption | Status |
|---|---|
| Policies not applicable to the current role cost no ACL check | **Confirmed (B)** |
| Service policies must be per (table × role), not one policy with role branches | **Still required** — B confirms the mechanism, not a licence to merge them |
| `polroles` × NOINHERIT interaction needs checking before committing to group targeting | **Answered (D)** — direct targeting only |
| Retargeting RESTRICTIVE policies to a human plane preserves human semantics | **Partly** — needs an accompanying PERMISSIVE policy where none exists (C) |

Alternative 2 (plane separation with claim-derived service authorization) is
viable. Alternative 3 (SECURITY DEFINER function layer) is not forced.

## Census correction

The plan's re-count of membership-referencing policy tables (56) does not
reproduce. Counting from the receipt gives **63**, matching
`V5_WORKER_PRIVILEGE_BOUNDARY.md`. The figures that do reproduce and matter:

| | |
|---|---:|
| Tables with a membership-referencing policy | **63** |
| Tables with any RESTRICTIVE policy | **61** |
| Tables granted to a worker role | **63** |
| **Worker-granted ∩ membership-policy** | **27** |

27 is the number the work is sized against, and all three sources agree on it.
The plan already requires the migration to re-derive its table list from the
live catalog rather than hardcode one, which is the right mitigation regardless
of which census is right.

## Also confirmed

**No API role exists in the cluster.** The receipt lists seven worker roles and
`pgowner`, nothing else. Combined with workers holding `BYPASSRLS` and `pgowner`
being superuser, **RLS is currently effective against nobody.** Policy changes
therefore land inert, and arming happens only when `BYPASSRLS` is removed —
which is exactly why the staged, role-by-role disarm sequence is the safe shape.

## Method

Throwaway cluster, own port and data directory, destroyed after the run. The
machine's `postgresql-x64-17` service and its `akc` database were not touched.
No repository file was modified to run this.
