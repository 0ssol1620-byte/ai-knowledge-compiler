# Derived-input incremental invalidation — 2026-09-30

Masterplan v4.0 sections 12.4–12.8 require evidence/authority propagation,
selective rebuild equivalence and priority treatment of false-negative impact.
The existing compiler passed source-byte hashes directly to CIR semantic diff.
Its intentional identical-byte fast path suppressed supplied OCR, citation and
authority changes when the original source bytes stayed fixed. Full-rebuild
equivalence then rejected the otherwise valid revision instead of rebuilding it.

Core now computes an internal diff input digest over source hash and resolved
unit text, logical identity, path, anchor, evidence, page and authority. CIR's
public diff semantics and source/version identities remain unchanged. This
represents compilation-input change, not source-byte change. Stable input
ordering avoids invalidation caused solely by enumeration order.

Three synthetic regressions independently change authority, citation geometry
and OCR text with a fixed source digest. Each passes equivalence, retains logical
and source-version identities, rebuilds four aggregates and three affected unit
artifacts, and preserves the three unaffected unit artifact hashes. The existing
two no-op revision tests continue to reuse their three unit artifacts.

This is bounded deterministic compiler qualification, not an extraction accuracy
benchmark, OCR provenance attestation or external generalization claim. Source
byte verification and OCR derivation remain intake responsibilities. No new
Foundation contract, provider, shared storage, credential or live activation is
introduced. A changed compiler must use a new release digest at deployment;
previously stored receipts are not rewritten.

Work was performed in task-3/core-offline on codex/core-offline-qualification,
starting at a5e007480448792ebc0965fb04b7fc6dbe9793ab. The integration checkout
task-3/core-work was retained unchanged. Tests use the existing isolated Python
environment with PYTHONPATH pointing to this worktree's package sources.

## Acceptance

- All 95 Product Core unit tests passed, including durable journal/replay,
  maintenance, fencing, immutable input rejection and incremental equivalence.
- A focused 77-test run also included CIR semantic diff compatibility coverage.
- All three new regressions failed with the original two source-hash arguments
  restored temporarily, and passed with the fix. The fixed file was restored
  byte-for-byte before subsequent verification.
- Product Core Ruff, strict compiler mypy and Git whitespace checks passed.
- Original checkout HEAD remains a5e007480448792ebc0965fb04b7fc6dbe9793ab;
  its pre-existing disposable qualification directory remains untouched.

PowerShell reproduction, from core-offline:

```powershell
$env:PYTHONPATH = ((Get-ChildItem packages -Directory | ForEach-Object {
  Join-Path $_.FullName 'src'
}) -join ';')
$tests = @(Get-ChildItem tests/unit/test_product_core*.py | ForEach-Object {
  $_.FullName
})
..\core-work\.venv\Scripts\python.exe -m pytest @tests -q --basetemp ..\pytest-derived-repeat
```

Full migration/image/Linux qualification still requires the previously documented
external tools and platform evidence; this slice does not remove those blockers.
