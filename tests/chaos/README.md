# Safe local chaos drills

`compose_drill.py` performs only a bounded Docker Compose `pause`/`unpause` on
the exact `akc-dev` project and the allowlisted `api` or `postgres` service. It
always unpauses in `finally`, refuses non-loopback URLs and production
environments, caps the outage at 30 seconds, and records only status/timing
metadata.

Run it only after loading disposable synthetic data:

```powershell
py -3 tests/chaos/compose_drill.py `
  --target postgres `
  --outage-seconds 5 `
  --confirm AKC_DEV_SYNTHETIC_CHAOS
```

Acceptance requires an observed liveness/readiness failure appropriate to the
target and readiness recovery within 60 seconds. A local result is drill
scaffolding evidence only; it does not establish production RPO/RTO, failover,
PITR, queue recovery, provider behavior, or release approval.
