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
schemas + OpenAPI v1      five paths, four schemas, published additively
abuse_controls.py         helpers extracted from main.py so this router can reuse them
quarantine_screening.py   the ADR-004 gauntlet, called by both routes
trial_api.py              five endpoints, driven end to end by real bytes
trial_retention.py        expiry sweep, wired into the scheduler pass
tests/security            23 boundary tests
apps/web                  hero wired to both modes, privacy copy corrected
```

### How the pipeline was connected

The choice above was **extract**, and it turned out smaller than the 675-line
figure suggested, because most of those lines are not screening. Screening is
about the object — validate the bytes against the declared filename and MIME,
compare the digest, scan, disarm. The rest is bookkeeping that differs per
caller: which document row this belongs to, whose audit log records it, whether
a duplicate is billable. Cutting at that seam produced
`services/api/src/akc_api/quarantine_screening.py`, which knows nothing about
principals, sessions, or audit rows, and which both routes now call.

Two consequences of the seam are decisions, recorded here because a later reader
will otherwise read them as omissions:

```
QuarantineUnavailable   scanner and CDR outages raise rather than return a
                        verdict. Nothing was concluded about the file, so it is
                        neither promoted nor marked SECURITY_REJECTED. The
                        exception carries the audit action name so the two
                        callers cannot drift on what they record.
after_validation        the free-tier duplicate check is billing policy, not
                        screening. It stays with the authenticated route, but
                        keeps its position in the sequence — after the digest,
                        before the scan — because that ordering exists to avoid
                        spending a scan on a file about to be refused anyway.
```

The authenticated route's 242-test suite passed unchanged before and after the
extraction, which is the evidence that behaviour was preserved.

### Where the trial stops, and how

A trial document now runs the same gauntlet and then preflights, reaching
`PREFLIGHTED`. The stop is enforced by not enqueueing anything: no processing
job is created, so no worker can pick the document up and no GPU is reachable
from an anonymous request. `test_completion_stops_at_preflighted` asserts the
job, task, and invocation tables are empty afterwards.

**Preflight runs inline rather than being queued.** This departs from the
authenticated route and is deliberate. That route hands preflight to the
document worker because the file it accepts can be hundreds of megabytes and
hundreds of pages; a trial file cannot, because `trial_ingest_max_bytes` and
`trial_ingest_max_pages` exist precisely to bound it. Preflight itself is page
geometry and text statistics — no OCR, no model, no network. The alternative
would make the first thing a visitor sees depend on worker infrastructure being
up, and would create a queue entry from an unauthenticated request, which is the
cost surface this ADR keeps behind a principal.

`document.page_count` stores the document's real length, not the number of pages
inspected. Storing the truncated figure would make `truncated` compute false
forever and report a partial measurement as a whole one, which §25.7 forbids.

### One defect this closed that reading would not have found

The presigned URL handed to an anonymous visitor pointed at
`PUT /v1/uploads/{id}/content`, which requires an authenticated editor. Outside
production — where the store is S3 and the URL is a genuine presign — the trial
flow could not upload at all, and the security path could not be exercised by a
test. `PUT /v1/trial/sessions/{id}/uploads/{id}/content` now serves that case,
authorized by trial session rather than by principal. `TrialUploadAccepted` also
gained `upload_id`, without which a client had no way to name the upload it had
just made.

`trial_ingest_enabled` still defaults to `false`. It is now a rollout control
rather than a guard against an incomplete capability.
