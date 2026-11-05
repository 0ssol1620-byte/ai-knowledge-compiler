# Dependency compatibility patches

Every patch in this directory must preserve an upstream security fix, remain
covered by the locked dependency audit, and be removed once all direct
dependencies accept the secure upstream interface.

## `minimatch@3.1.5.patch`

Legacy ESLint plugins still load `brace-expansion` as a CommonJS function.
`brace-expansion` 5.0.8 fixes the bounded-expansion denial-of-service issue but
exports that function as `expand`. The patch adapts only that import shape; it
does not alter matching behavior or weaken the upstream expansion limits.

Validation:

- `pnpm lint` exercises the legacy consumer.
- `pnpm audit --audit-level high` must report no known vulnerabilities.
- `pnpm install --frozen-lockfile` verifies the committed patch integrity.
