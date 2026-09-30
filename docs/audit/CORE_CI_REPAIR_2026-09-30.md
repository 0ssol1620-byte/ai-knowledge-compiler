# Core CI repair evidence

Local isolated branch continues from `20a6ae06c7221f88a9a033b9f5923464516ef280`.
Storage maintenance is a separate preceding commit, `2da91ca239060f93ea8fe8a3313b237dc3853dfc`.
No push, visibility, billing, credential, deployment or live-data changes occurred.

## Python and migration baseline

Reproduced the Ruff failures in the CI scope and corrected undefined Calendar/Gmail
`Mapping`, imports, line lengths and dead code. Existing synthetic cache identifiers
keep SHA-1 with explicit `usedforsecurity=False`; no security check was disabled.
After Ruff cleared, full strict mypy exposed 49 errors in 16 files. Added real shape
checks and annotations, removed obsolete ignores and fixed two runtime defects:
no-op compiler results now deserialize persisted review records into `ReviewItem`,
and Drive polling copies the input cursor map rather than mutating its snapshot.
Regression fixtures exercise both. Desktop annotations preserve runtime behavior.

Migration 0038 now emits resolved fixed quoted table/role identifiers in one complete
GRANT statement inside the role-existence guard, avoiding literal `{_TABLE}` and
`TOakc_api_plane`. Two SQL-emission tests pass; actual PostgreSQL execution still
requires the integration-owned migration rehearsal. The IP guard workflow installs
its locked dev environment before invoking pytest. Windows Git-hook Python discovery
still prevented two local IP hook tests; Linux hosted acceptance is not inferred.

Validation during the repair wave (focused suites repeated after their changes):

- Full CI-scope Ruff and repository Ruff: passed.
- Strict `mypy packages services`: 319 source files, passed.
- Synthetic `tests/unit tests/contract packages`, excluding provider/integration/slow
  markers: 1966 passed, one existing TestClient deprecation warning, 122 seconds.
- Compiler/source/P0 focused acceptance: 79 passed; desktop focused acceptance: 27.
- SQL + maintenance + replay + scanner summary: 33 passed.
- Final JWT/OIDC, PDF and real P0 compatibility slice: 26 passed.
- Web qualification is recorded separately in `CORE_WEB_CI_QUALIFICATION_2026-09-30.md`.

## Vulnerability remediation and evidence

Exact security run `36719135361` dependency logs reported vulnerable pip 26.1.2,
PyJWT 2.13.0 and pypdf 6.15.0. Updated dependency floors and regenerated `uv.lock`
with targeted pins: pip 26.2.1 (dev tool), PyJWT 2.14.0, pypdf 6.16.1. A freshly
synced isolated locked dev environment passes dependency checks and pip-audit:
146 packages, zero known vulnerabilities, no advisory exceptions.

Primary release references:

- [PyJWT security changelog](https://pyjwt.readthedocs.io/en/stable/changelog.html)
- [pypdf security changelog](https://pypdf.readthedocs.io/en/stable/meta/CHANGELOG.html)
- [pip changelog](https://pip.pypa.io/en/stable/news/)

Trivy 0.70.0 reproduced the immutable `20a6` filesystem scan: nine HIGH/CRITICAL
lockfile findings (six PyJWT, two Next, one sharp); zero secret/IaC findings.
The final edited checkout scan with the same severity/settings reports zero
vulnerability/secret/misconfiguration/license findings. Generated local environments,
build outputs and Git internals are excluded as they are absent from a clean checkout.
This does not qualify licenses discovered only in installed dependencies. Workflow
now retains SARIF even when its gate fails and prints finding IDs/paths without
free-form matched-secret messages. It retains the existing scanner threshold and
narrow existing ignore file; no new vulnerability or secret allowlist was added.

API, scheduler and CPU-document runtime Dockerfiles install the exact signed Debian
security package `libpcre2-8-0=10.42-1+deb12u1`, retaining the pinned Python base.
[Debian's PCRE2 tracker](https://security-tracker.debian.org/tracker/source-package/pcre2)
confirms that bookworm-security version. All Python application dependencies still
come from the checked lockfile.

The newer public distroless digest `bb6b03d8...` was tested and still contains vulnerable
OpenSSL `3.5.7-1~deb13u2`: Trivy reports CVE-2026-75804 and CVE-2026-84782. The web
Dockerfile therefore stages actual `libssl3t64` and `openssl-provider-legacy` security
packages at `3.5.7-1~deb13u3` from a verified pinned Debian trixie image. Copies include
the packages' own files, dpkg status and genuine md5 manifests, preserving the final
distroless nonroot/shell-free runtime. Package versions are not merely relabeled.
[Debian's OpenSSL tracker](https://security-tracker.debian.org/tracker/source-package/openssl)
and signed security repository package metadata confirm both versions.

Public registry verified image index digests:

- Distroless: `sha256:bb6b03d81066993293a10feda7250e8e1cc034035fe9b61cfceededa7c8bf04d`.
- Debian trixie slim: `sha256:a99cfc517144bc59b1978475ec53b46ecabec7e43635402ee5b77cc54cd1b20a`.

Exact security package SHA-256 values from Debian metadata (amd64 evidence):

- libssl: `ff16bc048bcd7d1b256094450b79c77947d8e76fe2a24bd99b91021d591fa074`.
- provider: `c12e0266c4780749a4702b8959ac979689f4182e18eed85a8a5eb90ed0e16eab`.

Reports outside Git at `task-3`: `python-dependency-audit-fixed.json`,
`trivy-fs-baseline20a6.json`, `trivy-fs-final.json`, `trivy-distroless.json`, and
`scanner-tools/layer-inspection.txt` / `debian-openssl-packages.txt`.

## Remaining gates

Local Docker is unavailable; rebuilt candidate image scans and the multi-stage
OpenSSL overlay need actual hosted build/runtime/scanner acceptance. No built-image
pass is claimed. Full hosted coverage/API/security/PostgreSQL and both Python
versions require rerun after sequential integration. The real restored marketing
visual gate fails against its approved baseline; no screenshots/assertions were
weakened or blindly regenerated. Distributed journal fencing, retention expiry,
customer data and production activation remain separate qualification work.
