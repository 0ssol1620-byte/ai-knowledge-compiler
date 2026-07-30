# Team collaboration

The Phase 9 team API keeps every session and API key bound to exactly one
workspace while allowing a verified user to belong to more than one tenant.

## API surface

- `POST /v1/team/invitations` creates an invitation (`owner`, `admin`).
- `GET /v1/team/invitations` lists the tenant's invitations.
- `DELETE /v1/team/invitations/{id}` cancels a pending invitation.
- `POST /v1/team/invitations/accept` accepts an emailed, one-time token.
- `GET /v1/team/members` lists current members.
- `PATCH /v1/team/members/{user_id}` changes a role.
- `DELETE /v1/team/members/{user_id}` removes a member and revokes that
  member's API keys in the tenant.

All authenticated mutations support the global `Idempotency-Key` contract.
Invitation acceptance is instead serialized by its one-time token row: a
successful token can never mutate membership twice.

## Invitation security

The token format carries only an untrusted tenant UUID hint and random entropy.
The database stores a domain-separated HMAC-SHA-256 digest, never plaintext.
The email address and plaintext token exist durably only inside the existing
Fernet-encrypted delivery outbox. The outbox authenticates its tenant,
invitation ID, recipient pseudonym, digest, expiry, and purpose before sending.

`AKC_TEAM_INVITATION_TTL_SECONDS` defaults to seven days and is bounded from
five minutes to thirty days. It reuses the independently configured
`AKC_VERIFICATION_HMAC_SECRET` and
`AKC_VERIFICATION_DELIVERY_ENCRYPTION_KEY`, but uses a separate HMAC domain.
Production therefore retains the existing fail-closed secret and Resend
provider checks. A disabled provider records a retry/dead-letter state and
never claims delivery.

Public acceptance collapses malformed, unknown, expired, cancelled, consumed,
wrong-email, inactive-user, unverified-existing-user, and wrong-password
failures to `INVALID_OR_EXPIRED_INVITATION`. Existing users must already be
verified and authenticate with their password. A new user proves email
ownership with the invitation token, supplies a strong password and display
name, and is created as verified.

## Role invariants

- Owners may invite and manage every role.
- Admins may invite and manage only `editor`, `reviewer`, `viewer`, and
  `billing`.
- No caller can change or remove their own membership through these endpoints.
- Admins cannot mutate owners or peer admins.
- Role changes and removals lock the tenant row and target memberships in one
  transaction. A final-owner check runs under that lock.
- Membership removal revokes tenant API keys immediately; stateless sessions
  are rejected on their next request because authentication re-reads the
  membership.

PostgreSQL RLS is forced on both invitation tables. All writes add append-only
audit events without storing email or token plaintext in audit metadata.

## Multi-workspace login

The original login behavior is unchanged for a user with exactly one
membership. A user with multiple memberships must send `tenant_slug`; omission
returns `WORKSPACE_SELECTION_REQUIRED`, and an unavailable slug returns
`WORKSPACE_NOT_AVAILABLE` only after the user's password is verified. The
issued cookie session contains one tenant ID. API keys are also created with,
embed a hint for, and authenticate against one immutable tenant ID.

## Verification

Run:

```powershell
.\.venv\Scripts\pytest.exe services/api/tests/test_team_collaboration.py -q
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
```

The focused suite covers encrypted-at-rest token/email evidence, exact
idempotency replay, generic public failures, one-time acceptance, new and
existing users, role escalation, self-protection, credential revocation,
concurrent owner removal, audit writes, and explicit workspace selection.
