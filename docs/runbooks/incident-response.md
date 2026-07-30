# Incident Response Runbook

## Declare

Open an incident record with UTC timestamps, severity, commander, operations
lead, communications lead, affected tenants/regions, detection source, and the
last known good application/model/configuration revisions. Preserve evidence;
do not copy customer content into chat or tickets.

Severity:

- SEV-0: confirmed cross-tenant exposure, credential compromise, or destructive
  integrity event.
- SEV-1: material security/privacy risk, broad data unavailability, or corrupt
  exports.
- SEV-2: provider outage, major queue delay, or degraded processing with a
  safe workaround.
- SEV-3: limited defect without security or data-integrity impact.

## Contain

1. Disable the narrowest feature flag or route.
2. Set affected provider traffic to zero and stop new retries if retries amplify
   impact.
3. Revoke scoped grants and rotate suspected secrets.
4. Preserve audit, deployment, model manifest, queue, and object-access records.
5. Use tenant-wide suspension or mass deletion only with incident-commander and
   security approval.

## Investigate

- Reconstruct state from immutable job events and ledger entries.
- Verify application commit, image digest, model revision, route policy, and
  feature flags.
- Identify the first affected request and exact exposure window.
- Separate confirmed facts, internal measurements, estimates, and hypotheses.
- Never use production documents for ad hoc debugging outside approved access.

## Recover

Restore from a known-good configuration or image, replay idempotent work, verify
source/result hashes, reconcile credits, and canary before restoring traffic.
Run tenant-isolation, export-integrity, and deletion checks appropriate to the
incident.

## Communicate and close

Use the approved breach/customer workflow. Record impact, timeline, root cause,
corrective actions, affected data, credit adjustments, notification decisions,
and follow-up owners/dates. Close only after monitoring is stable and evidence
is attached.
