# GPU or External Provider Outage

1. Confirm endpoint health, queue age, failure taxonomy, affected recipes, and
   provider region without submitting customer data manually.
2. Open the circuit breaker when error or queue-age thresholds trip. Stop
   automatic retry storms.
3. Keep native extraction running. Hold GPU pages with truthful status and an
   updated estimate.
4. Route only policy-approved work to a validated secondary adapter. Private
   jobs and jobs without external consent MUST NOT cross to an external API.
5. Preserve idempotency keys. A retry or provider duplicate MUST not consume a
   second credit.
6. When service returns, send a synthetic one-page smoke, validate exact model
   revision/checksum/cost cap, then canary held jobs.
7. Reconcile provider cost, credits, duplicate outputs, and delayed retention
   schedules. Attach the provider timeline and SLO impact to the incident.
