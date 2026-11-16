# D01A baseline triage, 2026-11-16

Base: `main` @ `6b3a27bf3d7d600f1cdd252b7414f2df6a0f1fed`. Nothing here closes a gate;
EG-01 stays OPEN until a hosted run on the release commit is recorded.

## 1. Cancelled CI (run 42811569207, job visual-and-browser-matrix)
- Cause: `playwright install --with-deps` ran 28 min because apt fetched at 69.1 kB/s; the job hit
  its 35 min limit after all tests passed. Forced-colors/200% step never ran on that commit.
  Same job finished in 8-10 min on 2026-11-15 runs (43753458780, 43752524548, 43751590631,
  43752094813): infrastructure flake, not a test failure.
- Change: Playwright browsers cached (`~/.cache/ms-playwright`, key = Playwright version);
  `install-deps` and the browser download are separate steps, each with a 6 min per-attempt
  `timeout`, 3 attempts, 20 min step cap. Job timeout NOT raised.

## 2. Web image scan (Security run 42811569301, zlib1g CVE-2026-76844 / CVE-2026-85091)
- Cause: digest-pinned distroless base carried zlib1g `1:1.3.dfsg+really1.3.1-1+b1`.
- Change: `apps/web/Dockerfile` pin `b8cec4b2...` -> `6abfcb367ebc291572c774c1592a986be2ab26a2486f73093401327495a5962a`
  (`Docker-Content-Digest` of `gcr.io/v2/distroless/nodejs24-debian13/manifests/nonroot`, OCI index,
  fetched 2026-11-16 with a gcr.io anonymous pull token and the OCI index Accept header).
- Registry-metadata check: the amd64 image's `var/lib/dpkg/status.d/zlib1g` is
  `1:1.3.dfsg+really1.3.1-1+deb13u1` in the new digest and `...-1+b1` in the old one. This meets the
  fixed version. Image `created` is epoch (reproducible build), so the date cannot be used.
- Not verified locally: no docker/Trivy here. The Security workflow on the PR is the verification.

## 3. soupsieve (CVE-2026-126190..126193)
- Cause: `uv.lock` pinned 2.9.1, transitive via beautifulsoup4 4.15.0 (no upper bound on soupsieve).
- Change: `uv lock --upgrade-package soupsieve` -> 4.1.1 (>= 4.0.0). Lock `revision` kept at 5
  (local uv 0.12.9 rewrites it to 3; reverted by hand, `uv lock --check` passes).
- Local tests ran against locally installed soupsieve 2.8 / bs4 4.14.3, not the lock:
  `tests/unit/test_nonpdf_structured_parsers.py` + `test_native_parser_fidelity.py` = 17 passed.
  CI is the lockfile-faithful run for 4.1.1 (a major bump).

## 4. contracts: live GitHub API fetch
- `benchmark/public_suite.py verify-registry --online` fetches `api.github.com/.../olmocr-bench/commits/<sha>`
  unauthenticated (runs 43752524548, 43751590631 failed; 43753458780 passed).
- Change (workflow only): the step retries 4 times with backoff; the assertion is unchanged.
- Outside scope, proposed: `_get_json` in `benchmark/public_suite.py` should add
  `Authorization: Bearer $GITHUB_TOKEN` for `api.github.com` when set, and the step should pass
  `env: GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}`.

## Needs a hosted run to prove
CI on this branch (visual matrix time, contracts), Security on the PR (web image, pip-audit,
filesystem-and-iac, api/scheduler/cpu-document images), and a green `CI` run on the release commit for EG-01.
