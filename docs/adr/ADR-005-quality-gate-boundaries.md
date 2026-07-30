# ADR-005: Quality Gate Boundaries and Precedence

- Status: Accepted
- Date: 2026-07-29
- Owners: Quality Platform, Routing, Product Trust
- Policy version: quality-gate-1.0.0

## Context

The initial quality table overlapped at 0.90 and did not define how numeric
discrepancies, repeated failures, or unreadable input interact with an overall
score. Different implementations could therefore accept the same page
differently.

## Decision

Terminal and critical conditions are evaluated before the aggregate score:

1. `FAIL`: unreadable, encrypted without a supplied password, corrupt, unsafe,
   or unsupported input.
2. `REVIEW_REQUIRED`: high-risk numeric mismatch, severe table error, evidence
   failure on a generated claim, or two exhausted processing attempts.
3. `ESCALATE`: engine-specific failure or overall score `< 0.82`.
4. `PASS_WITH_WARNINGS`: `0.82 <= score < 0.90`, no critical finding.
5. `PASS`: `score >= 0.90`, no critical finding.

Therefore exact 0.82 is warning-pass and exact 0.90 is pass. Scores are finite
numbers in 0–1; NaN, infinity, missing required metrics, and invalid
normalization become `ESCALATE`.

High-risk documents require numeric exact match 1.00. Cross-engine guidance is:

- text ≥ 0.95, numeric 1.00, structure ≥ 0.90: high agreement;
- text 0.85–<0.95 and numeric ≥ 0.95: warning candidate;
- text < 0.85 or numeric < 0.95: precision escalation;
- high-risk numeric < 1.00: review required.

Profile-, language-, or document-class overrides are permitted only through a
versioned policy record containing corpus version, approval, effective date,
and rollback target. UI confidence bands derive from this decision; they are
not unsupported accuracy claims.

## Consequences

- Boundaries are deterministic across languages and runtimes.
- A strong average cannot hide critical numeric, provenance, or safety errors.
- Threshold calibration remains possible without mutating historical policy.

## Verification

- Table-driven tests cover values immediately below, at, and above 0.82/0.90.
- Property tests cover all finite values in 0–1.
- Critical findings override every score, including 1.00.
- Router decisions persist the full metric snapshot and policy version.
