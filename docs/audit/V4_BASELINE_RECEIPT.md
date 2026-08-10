# V4 Baseline Receipt

*Masterplan v4.0 PHASE 0 deliverable. Measured 2026-08-10 KST.*

This is what the repository actually did when it was run, not what it is
believed to do. Every row below was executed at the commit named here.

```text
commit    5999baf8175288f34fb476b4e0b880037239c60c
branch    agent/folynta-trust-integration-v1
position  53 commits ahead of origin/main, 0 behind
host      win32 · Python 3.13.0 · Node 22.14.0 · pnpm 11.9.0 (corepack)
```

**Verdict: the repository is NOT green.** Python is entirely green. The web
application's code is green. **Two CI gates fail**, both pre-existing, both
characterised below. PHASE 0's exit gate accepts "existing green tests **or
documented known failures**" — these are documented, and neither is repaired
here, because PHASE 0 changes no behaviour.

---

## 1. Source of truth

| Document | sha256 | Role |
|---|---|---|
| `docs/north-star/TAVONEL_MASTERPLAN_v4.0.md` | `c996c372ca4702af1f11a67da61fee90c54c332b9238a89f0e1df7942d1b5e5a` | **North Star** |
| `docs/north-star/TAVONEL_MASTERPLAN_v3.1.md` | `cd69a8634520cc9f3a9be5e8ac3059c1fe2e445bea39e7ab9a99d81d28ba39fb` | superseded, preserved |
| `docs/north-star/TAVONEL_FINAL_NORTH_STAR_MASTERPLAN.md` | `6876ea389c41ad6b7b2dec47505a18138116531d51d514cab60204458e276619` | superseded, preserved |

v4.0 was copied into the repository at this commit; its hash matches the source
file byte for byte. `CLAUDE.md` is re-headed on v4.0 with v4's own precedence
ordering.

## 2. Repository shape

| | |
|---|---|
| Tracked files | 1,766 |
| Python files / test files | 709 / 266 |
| TypeScript+TSX files / test files | 259 / 53 |
| Python LOC (`packages` + `services` + `workers`) | 166,129 |
| Migrations | 33 revisions, **single head** `0032_accepted_block_invalidations` |
| Services | `api`, `scheduler`, `url-fetcher` |
| Workers | `cpu-document`, `cpu-export`, `gpu-common`, `gpu-hpd`, `gpu-knowledge`, `gpu-parser`, `gpu-unlimited` |
| Packages | `cir-python`, `contracts`, `domain-packs`, `exporters`, `native-parsers`, `parallel-runtime`, `quality`, `retrieval`, `router`, `security`, `telemetry` |
| Apps | `web` |
| CI workflows | 7 |
| ADRs | 6 |

## 3. Verification runs

### Green

| Check | Command | Result |
|---|---|---|
| Python lint (CI scope) | `ruff check packages services workers benchmark infra` | **PASS** — all checks passed |
| Python types | `mypy packages services` | **PASS** — no issues in 221 source files |
| Python tests (full testpaths) | `pytest` over `tests`, `packages`, `services`, `benchmark` | **PASS — 2,369 passed**, 0 failed, 674 s |
| Python tests (`tests/` only) | `pytest tests` | **PASS — 1,028 passed**, 73 s |
| Migration graph | `scripts/check_migration_chain.py` | **PASS** — single head over 33 revisions |
| Web lint | `pnpm -r lint` (eslint `--max-warnings=0` + tsc) | **PASS** |
| Web types | `pnpm -r typecheck` | **PASS** |
| Web tests | `pnpm -r test` (vitest) | **PASS — 259 tests in 53 files**, 252 s |
| Contracts build | `pnpm --filter @akc/contracts build` | **PASS** |
| Production build | `pnpm -r build` (Next.js, demo mode) | **PASS** — all routes compiled |
| Evidence hashes | recomputed sha256 of every claims-pack reference | **PASS — 14 / 14 match** |

### Failing

| Check | Result |
|---|---|
| `pnpm --filter @akc/web blueprint:check` | **FAIL** — see B-1 |
| `pnpm --filter @akc/web claims:check` | **FAIL** — see B-2 |

### Not run at this baseline

`storybook:build`, `lighthouse`, Playwright e2e, `security.yml`
(trivy / codeql / SBOM), `release-gates.yml`, `operational-drills.yml`,
`model-ci.yml`, and the live k6 scripts. They need a built app, a database, a
network or GitHub-hosted runners. **Nothing below claims they pass.**

### Outside CI's lint scope

`ruff check .` reports 2 errors that `ruff check packages services workers
benchmark infra` does not, both under `tools/`:

```text
tools/fonts/build_fonts.py:28:8              F401  `re` imported but unused
tools/release/test_render_folynta_portable_report.py:99:15  S603  subprocess call
```

CI is green because `tools/` is not in its lint path. `CLAUDE.md` says "`ruff`
and `mypy` clean" without qualification, so either the rule or the CI scope is
wrong. Recorded, not resolved — it is a one-line fix plus a CI-path decision,
and PHASE 0 makes neither.

---

## 4. Blocking findings

### B-1 — `blueprint:check`: two legacy ratchets rose

```text
V3 layer (src/styles)      clean across 22 stylesheets
font-size-below-12px       428 / 422   ROSE by 6
non-conformant-breakpoint   45 /  39   ROSE by 6
```

The design ratchet is allowed to fall and never to rise. The **V3 layer is
clean** — every violation is in the legacy sheets `src/app/globals.css` and
`src/app/enterprise-refresh.css`, which are exactly the surfaces v4 PART 15
replaces. Six sub-12px font sizes and six non-conformant breakpoints were added
since the ratchet was last set.

Severity: medium. It is a design-conformance regression in code scheduled for
replacement at Phase 13, not a correctness or safety defect. It must not be
resolved by raising the ratchet — `CLAUDE.md`'s rule that a ratchet is never
raised to make a build pass applies here in its plainest form.

### B-2 — `claims:check`: the site's claims data is stale and has lost its receipts

This is the finding that matters.

`apps/web/src/data/claims/public-claims-pack.json` (the render copy) has drifted
from `docs/evidence/folynta-public-claims-pack.json` (the delivered pack). Same
15 claims, same ids, same approved/conditional/withheld counts — but different
content:

| | Delivered | Render copy |
|---|---:|---:|
| Claims carrying `evidence_sha256` | **14 / 15** | **5 / 15** |
| Claims carrying `forbidden` phrasings | 8 | 6 |
| Claims carrying `must_say_en` | 15 | 10 |
| `receipt_sha256` | `82d5ec8b…` | `ecb69c75…` |

Three specific consequences:

1. **Ten of fifteen claims lose their sha256 receipt in the copy the site
   renders.** `CLAUDE.md`: *never publish a numerical claim without a receipt.*
2. **The render copy cites `benchmark/reports/generated/…`, which is git-ignored**
   (`.gitignore:52`). Those paths do not exist in a clone. The delivered pack was
   repaired for exactly this in commit `1699ebc` *"make every published claim
   verifiable from a clone"*; the render copy was never updated.
3. **A published weakness is missing.** The delivered
   `recovery-contribution-parsebench` carries
   `layout_micro_rule_pass_rate_with: 0.7566` against
   `…_without: 0.7704` — recovery made the layout micro-rule pass rate *worse*.
   The render copy omits both fields. `CLAUDE.md`: *weaknesses are published, not
   averaged away.*
4. **`corpus-scale` loses its `must_say` and `forbidden` guardrails entirely** in
   the render copy — the two rules that stop "5,132 documents" being restated as
   a throughput or customer-volume figure.

Direction of drift: the render copy is **stale, not tampered**. It was last
written in `786c387` and missed three later improvements to the delivered pack
(`708e361`, `1699ebc`, `cf53916`).

Severity: **high**. PART 22.3 lists "unsupported claim published" as a
stop-the-line condition. Nothing is published — the CI gate is doing its job and
blocking it — but the branch currently carries site data that would render claims
without receipts. The remedy is prescribed by the verifier itself: *copy the
delivered file over the render copy; do not reconcile them by hand.*

**Not applied here.** It changes what the marketing site renders, and published
claims are founder truth under PART 31, not an agent's call. It is a single file
copy and should be the first thing done after this gate.

---

## 5. Non-blocking findings

Detail in `docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md` and
`docs/audit/V4_FEATURE_FLAGS.md`.

| ID | Finding | Severity | Due |
|---|---|---|---|
| F-1 | `rollout_percent = 0` on an enabled flag enables it for **everyone** — and 0 is the first rung of v4's `0→5→25→50→100` router ladder | **High** | before the first `V4_*` flag row (Phase 1); hard-blocks Phase 4 |
| S-1 | `vllm/vllm-openai` digest used but absent from `verified-pins.json` | Medium | before any RunPod v6 image promotion |
| S-2 | Web builds and deploys on Node 24; CI tests on Node 22 | Medium | Phase 1 CI revision |
| S-5 | No image signing or cosign policy (SBOM and scanning exist) | Medium | Phase 17 |
| S-6 | Untracked `.env` present locally; no managed secret store | Medium | Phase 17 |
| S-3 | codeql pin recorded under a key the workflows do not use (SHA is correct) | Low | next pin revision |
| S-4 | `DEPENDENCY_LICENSES.md` stale on the 2026-08-09 3D reversal | Low | Phase 13 |
| — | `ruff` clean only within CI's path; `tools/` has 2 errors | Low | Phase 1 |

F-1 is worth restating because it inverts a safety mechanism: a
`V4_SHADOW_ROUTER` row created at `rollout_percent = 0` to mean *"recorded for
nobody yet"* would route **every** request through the new router. Reproduced at
this baseline; see `docs/audit/V4_FEATURE_FLAGS.md`.

---

## 6. Evidence integrity

Every artifact referenced by the delivered claims pack was re-hashed and
compared. **14 references, 14 matches, 0 mismatches, 0 missing files.**

```text
OK  folynta-blind-quality-detection-2026-08-08.json
OK  folynta-campaign-completion-ledger-2026-08-08.json
OK  folynta-counterfactual-no-recovery-omnidocbench-2026-08-08__repeat-1__metric-result.json
OK  folynta-counterfactual-no-recovery-parsebench-2026-08-08__evaluation-summary.json
OK  folynta-knowledge-compilation-properties-2026-08-08.json
OK  folynta-measured-gpu-cost-2026-08-08.json
OK  folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__olmocr-bench__evaluation-summary.json
OK  folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__omnidocbench__repeat-1__metric-result.json
OK  folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__parsebench__evaluation-summary.json
OK  folynta-published-leaderboard-context-2026-08-08.json
OK  folynta-recovery-accuracy-counterfactual-olmocr-2026-08-08.json
OK  packages/domain-packs/src/akc_domain_packs/blueprints.py
OK  packages/exporters/src/akc_exporters/knowledge_package.py
OK  packages/exporters/src/akc_exporters/vault.py
```

`docs/evidence/artifacts/folynta-measured-model-evaluation-snapshot-2026-08-02.json`
sits on disk unreferenced by the pack. It is older campaign data, not a broken
link.

**No evidence was rewritten, regenerated or renamed in this phase.** The FOLYNTA
artifact names, hashes and evaluator revisions are unchanged, as the absolute
preservation rule requires.

---

## 7. Protected Core — present and tested

Every module on v4's protected list exists at this commit and is covered by the
2,369-test run:

`akc_cir.inspection` · `akc_cir.recovery_policy` · `akc_cir.reconciler` ·
`akc_cir.identity` · `akc_cir.semantic_diff` · `akc_cir.dependency` ·
`akc_cir.recompilation` · `akc_cir.world_state` · `authority.py` · `entity.py` ·
`temporal.py` · `trust.py`

All are classified `IMPLEMENTED_NOT_PROVEN`. Tests prove the code does what its
author intended. **No threshold in any of them is calibrated** —
`CalibrationTable.calibrated` is `False` and refuses to be set true without
naming a corpus. The identity merge bar (0.92) and new-identity floor (0.75) are
reasoned, not measured.

The campaign evidence measures MinerU 3.4.4 plus the recovery runtime on public
corpora. It does not measure the modules above.

---

## 8. Licence gate

**No production-blocked licence component is silently active.** All 16 model
registry entries sit at `traffic_percent: 0` with `*_unverified` status. The
validator requires an exact revision pin and full attestation before traffic can
be non-zero, so an unresolved licence cannot reach a request. Detail and the six
supply-chain findings are in `docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md`.

---

## 9. Exit gate

| PHASE 0 exit criterion | Status |
|---|---|
| existing green tests **or documented known failures** | **MET** — Python 2,369 pass; web code green; B-1 and B-2 documented |
| evidence hashes match | **MET** — 14/14 |
| protected core list accepted in repo docs | **MET** — `CLAUDE.md` + `V4_MIGRATION_MATRIX.md` |
| no production-blocked licence component silently active | **MET** — 16/16 at zero traffic |
| rollback / tag verified | **see below** |

Deliverables produced:

```text
docs/audit/V4_BASELINE_RECEIPT.md          this file
docs/audit/V4_MIGRATION_MATRIX.md          module actions + PROVEN/PARTIAL/… status
docs/audit/V4_LICENSE_AND_SUPPLY_CHAIN.md  licence + pin inventory, S-1…S-6
docs/audit/V4_FEATURE_FLAGS.md             15 v4 flag keys, F-1
docs/ip/V4_DISCLOSURE_REGISTRY.yaml        10 IP items, 7 frozen, 4 founder decisions
CLAUDE.md                                  re-headed on v4.0
infra/supply-chain/verified-pins.json      pre-existing; S-1/S-3 recorded against it
```

**Phase 1 must not start until B-2 is resolved**, because Phase 1 locks the v4
contract language and a claims pack without receipts is precisely the contract
v4 exists to enforce.
