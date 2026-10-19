# Pre-registration seal index — decision D-10 (adopted 2026-10-17)

Decision register row **D-10** (source PHASE1-CRITIC D-10; aliases C-FD-6, KB-F5, KB-F9), class
`agent-now`, lane `PREREG-SEAL`. The register's adopted default: "초안대로 승인하고 실행 전에
봉인한다. 벤더 δ(§4.5), KB1 n ≥ 50·family ≥ 10, API arm은 model ID와 revision을 하나로 고정,
블라인드 비교는 Holm α 0.05". The adoption is the founder message of 2026-10-17, verbatim:
"파운더 결정은 모두 실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수
있도록해줘". It is cited as the adoption of that default only, not as a wording approval.

Sealed at 2026-10-19T01:09:27Z (UTC), by an agent, before any run, response or vendor call. Each
record below holds its draft byte for byte, between two marker lines, under a header that states
what is sealed, what was aligned at sealing, and what is still open. The drafts under `UX` were
read and not changed.

`UX` = `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017`

| Sealed record | Pre-registration | Lanes | Draft and its sha256 | What is sealed | May it run now? |
| --- | --- | --- | --- | --- | --- |
| [VENDOR-COMPARISON-PREREG-SEALED-2026-10-17.md](VENDOR-COMPARISON-PREREG-SEALED-2026-10-17.md) | `tavonel.vendor_comparison.v1` | P2-25 / AT-1 | `UX\VENDOR-COMPARISON-PREREG.json` `d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9` | Every δ (`COMPETITOR-PROTOCOL` §4.5), verdict rules and vectors, CI, repeats, multiplicity, ParseBench patch, denominators, publication rules | **No.** Vendor arms: D-34 hold. D-T-live: evaluation tenant (D-30, FH-01), AT-6 adapter. Three of the draft's four sealing requirements are still open (its section 3) |
| [KB1-PREREG-SEALED-2026-10-17.md](KB1-PREREG-SEALED-2026-10-17.md) | `tavonel.kb1_prereg.v1` | P2-27 / KB-A3 | `UX\KB1-PREREG.json` `cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff` | T1 (K1, K3, K4): confirm n ≥ 50 pages and ≥ 10 families per category, ≤ 5 pages per family; metrics; statistics with SA-1 and SA-2; publishable and comparison rules; API arm pinned to one exact model ID and revision | **No confirm run.** The run-ready revision `kb1-prereg-r2` must first fill the null data-binding fields (its section 3). D-32 (FH-11) is open |
| [BLIND-COMPARISON-PREREG-SEALED-2026-10-17.md](BLIND-COMPARISON-PREREG-SEALED-2026-10-17.md) | `TAVONEL-BLIND-PREREG-1` | P2-28, P2-38 | `UX\blind\PREREG.md` `1c1851096d555e22e5dedcae047bc678a26f632a212d57e0e0b41e8f87c87aa7` | The whole protocol: one-sided exact binomial, Holm α = 0.05 over seven comparisons, G-1 codebook with (c), 6/8, margin 0.25; G-1 arm A only (D-08 "G-1 8명") | **Not yet.** Needs the machine seal: install the reference bytes, sha256 `91c772471e29c5d63456153a749524738bfd33a61ace63e31efe2685444a7a84`, and re-pin `analyze.mjs` (its section 3). Then raters and consent text (D-08, FH-10) |

## Verify

```text
sha256sum -c SHA256SUMS.txt
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' VENDOR-COMPARISON-PREREG-SEALED-2026-10-17.md | sed '1d;$d' | sha256sum   # d68e0027…
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' KB1-PREREG-SEALED-2026-10-17.md | sed '1d;$d' | sha256sum                   # cb51fd44…
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' BLIND-COMPARISON-PREREG-SEALED-2026-10-17.md | sha256sum                    # 1c185109…
```

`SHA256SUMS.txt` carries the sha256 of the three records and of this index. No record contains its
own hash. **Do not run Prettier `--write` on this folder.** It would reformat the verbatim drafts
and break the byte identity that these checks prove. Core CI runs no formatter on `docs/`.

## Rules that hold for all three

- **Changes after sealing require a new version.** A sealed record is never edited. A change is a
  new file with a new version, registered before its first run. The blind comparison also needs a
  new id and fresh collection; KB1 also needs a fresh holdout after any confirm run.
- **Sealing is not calibration.** Every margin and threshold here is uncalibrated. Sealing fixes
  them before results. It does not show they are right.
- **Sealing is not permission.** Spending, vendor accounts, recruitment, consent text and
  publication each keep their own decision: D-34, D-30, D-32, D-08, D-09.
- **A number the founder must set is written FOUNDER-SET** with its question, in the record's own
  section. No value was invented to fill one.

## FOUNDER-SET across the three

- Vendor: the FD-2 per-vendor USD caps on the 384-pages-per-corpus basis, once D-34 is released.
- KB1: the API arm's exact model ID and revision (at execution approval); its inference
  configuration (maximum output tokens, effort/thinking, timeout, retry); which comparison arms
  run in T1; whether to keep the SA-1/SA-2 reading; whether 보호기간 만료 marking is allowed.
- Blind: none for the protocol. Recruitment route, reward and consent wording are D-08 (FH-10).
  Testing the B variant too needs 8 more G-1 raters and a new version.

## Recorded with this seal

| Record | Where | sha256 |
| --- | --- | --- |
| D-02 ICP decision | Foundation `docs/gtm/ICP_DECISION_2026-10-17.md` at `61189cd5` (branch `codex/records-20261017`, not pushed) | `5b83a743f26d07e0bd6ba80b1aaa0b08b4c48ed9790010256aae86f3f137ea66` |
| D-31 corpus rights policy | Core `docs/compliance/CORPUS_RIGHTS_POLICY_2026-10-17.md` at `4a583312` | `72aa489e61ceaef1945c6a552ae7adc733ea6ac8cbe9b0ac90ab5cb4cc601dba` |
| Decision register | `UX\DECISION-REGISTER-2026-10-17.md` / `.json` | `5935276d245d230857fa632dcb6555d25756470d37f404fc6c3c00dc71d7c6dc` / `86234c9397cec2d0ac8160276e525943857e7b2ec21e5e3a3b9891cc394120d3` |
| Lane receipt | `UX\records\PREREG-SEAL\PREREG-SEAL-RECEIPT.json` | in the lane result |
