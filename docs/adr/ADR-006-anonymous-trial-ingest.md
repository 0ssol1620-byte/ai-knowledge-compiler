# ADR-006: Anonymous Trial Ingest

- Status: Accepted
- Date: 2026-08-07
- Accepted: 2026-08-08
- Owners: Platform, Security, Product

## Context

`DESIGN_MASTER_V3` §12.2 specifies a hero whose third state starts a real
compile from a document the visitor drops on the marketing page. §9.2 chose
that affordance over a 3D scene precisely because two of the three benchmark
sites lead with something that works, and because it is the only way to occupy
the first white space in §2.2 above the fold.

Every ingest path today is tenant scoped. `POST /v1/uploads/initiate` takes an
`EditorDep` principal, documents and objects are partitioned by tenant under
row-level security, and the marketing surface has no session. There is no way
to accept a visitor's file without a contract change.

W2 shipped what a browser can do alone: it reads the file, computes the same
SHA-256 the authenticated path uses for integrity, and states plainly that page
count and structure are measured server-side. That is honest but it is not
§12.2 — the visitor still cannot see their own document compiled.

An anonymous endpoint on a public marketing page is also the largest abuse
surface this system would have. This record decides whether to open it, and
under exactly what constraints.

## Decision

Open a **trial ingest** capability: anonymous, preflight-only, hard-capped,
short-lived, and disabled by default.

### Tenant scoping is preserved, not excepted

The non-negotiable invariant in `CONTRIBUTING.md` — every business query and
object key is tenant scoped — holds unchanged. Anonymous documents belong to a
**system trial tenant** provisioned by migration, with a reserved UUID and
`plan_code = "trial"`. There is no tenant-less row and no RLS bypass, so
`postgres-rls-and-role-boundaries` keeps its meaning.

A trial upload is attributed to a **trial session**: a server-issued opaque
identifier, stored as a project under the trial tenant, with no user, no
credentials, and no login. It is a project the visitor can read for as long as
it lives, and nothing else.

### The quarantine state machine is not shortened

ADR-004's intake path applies in full:

```text
UPLOADED → SECURITY_SCANNING → SECURITY_VERIFIED → PREFLIGHTING → PREFLIGHTED
```

Untrusted input from an anonymous visitor is *more* dangerous than untrusted
input from a paying tenant, not less. Every promotion condition in ADR-004 —
MIME and extension agreement, magic bytes, bounded archive expansion, malware
scan, encrypted-file policy, size and page and pixel limits, immutable scan
result — is required. No parser, preview generator, or exporter reads a
quarantined object.

### The path stops at PREFLIGHTED

Trial ingest never reaches `NATIVE_EXTRACTING`, `OCR_QUEUED`, knowledge
construction, or export. Preflight is CPU-bounded and produces exactly what the
hero needs to stop guessing: page count, detected structure, encryption state,
and the route the compiler would choose.

GPU compilation stays closed. It is the cost surface, and an anonymous caller
must not be able to spend it. `POST /v1/documents/{id}/compile` continues to
require a principal.

### Caps

```text
files per session      1
bytes per file         min(8 MiB, analysis_max_source_bytes)
pages inspected        10          truncated result is labelled as truncated
sessions per IP        governed by control="trial_ingest" below
lifetime               1 hour, then deleted through the ADR-004 retention path
```

The page cap is a product decision as much as a cost one: ten pages is enough
to show the compiler working and not enough to be a free tier.

A truncated preflight is reported as truncated. §25.7 rejects presenting a
partial measurement as a whole one.

### Abuse control

Reuses the existing machinery rather than adding a second one:

```text
control        "trial_ingest"
subject        _client_subject(request) — pseudonymised IP, existing hasher
escalation     CAPTCHA via enforce_captcha, as registration and login already do
metrics        record_abuse_control_decision, same counters
backend        Redis limiter; RateLimitBackendUnavailable fails closed (503)
```

Failing closed matters here. If the limiter is unavailable the endpoint refuses
service rather than accepting unbounded anonymous uploads.

### No credits, but usage is recorded

Trial ingest creates no credit entries — it is free, and the append-only credit
ledger must not carry entries no account owns. GPU cost is zero by
construction because GPU work is unreachable. Bytes and page counts are
recorded against the trial tenant for abuse observation only.

### Disabled by default

`trial_ingest_enabled` defaults to `false`, following the `url_ingest_enabled`
precedent in ADR-004 (C-04). A capability whose blast radius is the public
internet does not arrive switched on. Enabling it is a deployment decision with
the limiter and CAPTCHA provider configured.

### Retention and the visitor's copy

A trial session and its objects are deleted one hour after creation through the
existing `deletions.py` path. If the visitor signs up within that window the
session may be adopted into their tenant; adoption re-runs authorization and
does not move objects across tenant prefixes.

Nothing is retained for training, and the privacy notice the hero shows must
change when this ships: "not uploaded" stops being true the moment a byte
leaves the browser. The copy becomes explicit about what is sent, how long it
is kept, and that it is deleted.

## Consequences

**Enables** — §12.2 state ③ as specified. The visitor sees their own document
against the compiler's output, which is the argument §4.2 now has to make with
product fact rather than with the product name (see `decision.md` G-A).

**Costs** — a new public surface, a system tenant, a retention job, and a
schema addition. The endpoint is CPU-bounded and rate-limited, but it is
reachable by anyone.

**Risks accepted** — anonymous malware submission (mitigated by the unchanged
ADR-004 scan path), storage abuse (mitigated by caps, TTL, and the limiter),
and legal exposure from anonymous content (mitigated by the one-hour lifetime
and by never serving an uploaded object to anyone but its session).

**Rejected alternatives**

- *Bypass the tenant model with a nullable tenant column.* Breaks the invariant
  and the RLS check that enforces it, for no gain over a system tenant.
- *Skip security scanning for small files.* The scan exists because size does
  not predict danger.
- *Allow one free compile.* Opens GPU spend to anonymous callers. The preflight
  already shows the compiler working.
- *Leave §12.2 state ③ unbuilt.* Viable, and what W2 shipped, but it leaves
  §25.2's "does the hero work" axis answered with a partial yes.

## Schema and contract changes

```text
openapi-v1.json     POST /v1/trial/sessions      201 TrialSession
                    POST /v1/trial/sessions/{id}/uploads
                    GET  /v1/trial/sessions/{id}
migration           system trial tenant, trial session table, TTL index
client types        generated by scripts/generate_contract_types.py
feature flag        trial_ingest_enabled = false
```

## Verification

- Regression tests at the router layer for each cap and each rejection.
- An RLS test that a trial session cannot read another session's document.
- An abuse test that the limiter denial and the CAPTCHA escalation both return
  the documented error codes.
- A retention test that objects are unreachable after the TTL.
- `scripts/check.ps1`.

## Implementation status

Landed and verified:

```
migration 0023            system trial tenant, service user, trial_sessions, RLS, TTL index
settings                  flag off by default, caps, two guarding validators
schemas + OpenAPI v1      three paths, four schemas, published additively
abuse_controls.py         helpers extracted from main.py so this router can reuse them
trial_api.py              the three endpoints, exercised end to end
trial_retention.py        expiry sweep, wired into the scheduler pass
tests/security            17 boundary tests
apps/web                  hero wired to both modes, privacy copy corrected
```

**Not yet connected: the quarantine pipeline.** A completed trial upload does
not currently advance past `UPLOADED`, so no scan runs and no preflight is
produced. The UI reports this honestly — it shows "Queued for security
scanning…" and never a page count it does not have — but the capability is not
end to end, which is why `trial_ingest_enabled` staying `false` is load-bearing
rather than merely cautious.

What that step needs is deliberate work, not a small patch. The authenticated
`POST /v1/uploads/{id}/complete` handler carries the whole pipeline in **675
lines with 22 external dependencies** — object store, malware scanner, CDR,
metadata recovery, audit, and the `SECURITY_SCANNING → SECURITY_VERIFIED →
SECURITY_REJECTED` transitions. Trial ingest must run that exact path; this ADR
says so and says why.

Two ways to get there, and the choice belongs with a reviewer rather than with
whoever picks the task up:

```
extract    lift the pipeline into a shared function both routes call.
           Right architecture, one implementation, and the largest
           security-critical refactor in the repository.
delegate   have the trial completion route call the existing handler with a
           synthesized principal. Smaller diff, but it manufactures a principal
           on an anonymous path, which is the property this ADR was careful to
           avoid needing.
```

The first is almost certainly correct. It was deliberately not attempted at the
end of the session that wrote everything above: a hurried extraction of malware
scanning and quarantine promotion is how a check quietly stops running.
