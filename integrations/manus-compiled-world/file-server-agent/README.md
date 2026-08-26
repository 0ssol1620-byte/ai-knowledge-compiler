# TAVONEL File Server Agent — Enrollment Protocol

This package describes the **control-plane pilot** for a customer-managed file server agent. It does not contain a deployed binary and it does not enable file collection by itself.

## Safety contract

The customer first selects explicit root folders in TAVONEL and generates a one-time enrollment code. The code is shown once in the TAVONEL workspace, while only its SHA-256 hash is retained by the service. The agent makes outbound HTTPS requests to TAVONEL; no inbound customer firewall port is required. A heartbeat proves that an installed agent is reachable, but the current pilot endpoint rejects file content. Collection stays disabled until a separately reviewed content-ingestion contract is implemented.

## Minimal heartbeat request

Run this from a customer-controlled environment with Node.js 18 or later. Replace both placeholders with the one-time enrollment code and the TAVONEL public base URL.

```sh
curl -X POST "$TAVONEL_BASE_URL/api/file-server/heartbeat" \
  -H "Authorization: Bearer $TAVONEL_AGENT_ENROLLMENT_CODE" \
  -H "Content-Type: application/json" \
  -d '{"version":"0.1-control-plane"}'
```

The response reports `heartbeat_only`. It never accepts document bytes, never initiates a scan, and never changes customer files. The project owner can revoke the enrollment in TAVONEL, after which the same code is rejected.

## Before enabling content collection

The production agent must add a signed manifest, customer-controlled allow-list roots, file-size and MIME policy, resumable outbound uploads to the private object store, source-level provenance, and audit records for every collected item. It must not delete, move, rename, or deduplicate source files in the customer environment.
