# Security policy

## Reporting

Do not open a public issue for a suspected vulnerability or exposed customer
data. Use the repository's private security advisory channel. Until a dedicated
security contact is configured, repository owners must keep reports private and
acknowledge them through GitHub's security-advisory workflow.

Do not include source documents, credentials, presigned URLs, personal
information, or exploit payloads in a report. Use identifiers and redacted
evidence.

## Supported versions

Only the default branch and the most recent production release receive security
updates during private beta.

## Security boundaries

- Uploaded files are untrusted.
- Parsed text and model output are untrusted.
- Model code and weights are supply-chain artifacts that require revision,
  checksum, license, and runtime review.
- Browser-supplied tenant identifiers are never authorization evidence.
- A presigned URL is a bearer credential and must be short-lived and scoped.
- Customer content is not training data without explicit, revocable consent.

See `docs/security/threat-model.md` and `docs/runbooks/incident-response.md` for
the operational controls and response process.
