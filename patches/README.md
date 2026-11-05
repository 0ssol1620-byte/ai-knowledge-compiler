# Dependency compatibility patches

Every patch in this directory must preserve an upstream security fix, remain
covered by the locked dependency audit, and be removed once all direct
dependencies accept the secure upstream interface.

## `minimatch@3.1.5.patch`

Legacy ESLint plugins still load `brace-expansion` as a CommonJS function.
`brace-expansion` 5.0.9 fixes the bounded-expansion denial-of-service issue but
exports that function as `expand`. The patch adapts only that import shape; it
does not alter matching behavior or weaken the upstream expansion limits.

Validation:

- `pnpm lint` exercises the legacy consumer.
- `pnpm audit --audit-level high` must report no known vulnerabilities.
- `pnpm install --frozen-lockfile` verifies the committed patch integrity.

## `extract-zip@2.0.1.patch`

The upstream package has no release containing a fix for
`GHSA-jmr9-qjv8-65gv`. The patch resolves every symlink target against the
extraction root and rejects targets that escape it before creating the link.
Only that GHSA is ignored by the CI audit command, and the ignore is valid only
while the patch remains installed and its exploit regression passes.

Validation:

- `node scripts/verify-dependency-patches.mjs` builds a malicious symlink ZIP
  and requires extraction to reject it.
- `pnpm install --frozen-lockfile` verifies the committed patch integrity.
- Remove the patch and audit ignore together after a fixed upstream release.
