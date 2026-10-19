# Human blind comparison pre-registration `TAVONEL-BLIND-PREREG-1` — SEALED (decision D-10)

Decision register row **D-10** (source PHASE1-CRITIC D-10; aliases C-FD-6, KB-F5, KB-F9), class
`agent-now`, lane `PREREG-SEAL`. Lanes bound: P2-28 (preparation) and P2-38 (execution). Written by
an agent. This is a document only: it changes no code, no test, no analysis script, no draft, no
consent wording, no public sentence and no evidence artifact.

| Field | Value |
| --- | --- |
| Status | **SEALED.** Scope: the whole protocol below, with the one parameter set in section 2. The analysis script still pins the draft and refuses real responses until the machine seal in section 3 is installed |
| Decision | D-10, adopted default: "초안대로 승인하고 실행 전에 봉인한다. 벤더 δ(§4.5), KB1 n ≥ 50·family ≥ 10, API arm은 model ID와 revision을 하나로 고정, 블라인드 비교는 Holm α 0.05" (`REG.md:46`; `REG.json` row `D-10`). It answers the draft's own question for D-10 (`PRE:257`): the thresholds and the G-1 codebook's trust marker (c) |
| Adoption | Founder message 2026-10-17, verbatim: "파운더 결정은 모두 실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수 있도록해줘" (`REG.md:3`). Cited as the adoption of the D-10 register default (and, for section 2, the D-08 default) only. It is not a wording approval, not consent wording, not a reward and not a decision to publish |
| Decision date | 2026-10-17 (the adoption; the date in this file's name) |
| Sealed at | 2026-10-19T01:09:27Z (UTC). The same instant is written into the machine-sealed bytes (section 3). The commit that adds this file is the timestamp of record |
| Draft | `UX\blind\PREREG.md`, sha256 `1c1851096d555e22e5dedcae047bc678a26f632a212d57e0e0b41e8f87c87aa7`, 25,172 bytes, 290 lines, LF. Matches `UX\blind\SHA256SUMS.txt` and `PREREG_SHA256` in `UX\blind\analyze.mjs` (line 17). The draft file is not changed |
| State at sealing | No response collected (`PRE:5`; register D-08 `statusToday` "평가자 0", `REG.md:73`) |
| Change rule | **Changes after sealing require a new version.** After any response, a changed criterion, rule or script is a new prereg with a new id, and collection starts again (`PRE:27`) |

Short paths: `UX` = `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017`;
`REG` = `UX\DECISION-REGISTER-2026-10-17`; `PRE` = the verbatim draft at the end of this file (line
numbers are the draft's own).

## 1. Sealed parameters

Every value below is the draft's value, unchanged, except the G-1 arms (section 2).

| Parameter | Sealed value | Draft lines |
| --- | --- | --- |
| Primary endpoint | Forced choice, H against each of A–G (7 comparisons), k of 20 raters choosing H | `PRE:129-137` |
| Test | One-sided exact binomial, H0 π = 1/2, H1 π > 1/2, computed as exact fractions | `PRE:138` |
| Multiplicity | Holm step-down, family-wise **α = 0.05**; ties in p broken by key order; Holm-adjusted p reported | `PRE:139-142`, `PRE:272` |
| Outcomes | `ALL_SIGNIFICANT` / `SUBSET_SIGNIFICANT` / `NONE_SIGNIFICANT` with the allowed and barred sentences; publishing is decision D-09 (hold) | `PRE:162-168` |
| Comparison panel | n = 20; at least 10 from the ICP; no interest in TAVONEL or A–G; no tavonel.com visit in 90 days (self-reported) | `PRE:71-76`, `PRE:271` |
| G-1 codebook | `IN` only when the answer names all three of (a) documents in, (b) knowledge, context or data for AI or agents out, (c) a trust marker (evidence, source, citation, location in the original, or verification). The draft left (c) open for D-10 (`PRE:94`); D-10 adopts it as drafted, so (c) is required | `PRE:89-94` |
| G-1 pass rule | at least 6 of 8 `IN` per arm; two blind coders, a third resolves | `PRE:95`, `PRE:172`, `PRE:273` |
| Ratings | 1–5 on c1–c8, trend (higher is better), clutter (lower is better); equivalence margin **0.25**; internal diagnostic only | `PRE:111-127`, `PRE:175-180`, `PRE:274-287` |
| Stimuli and capture | Same-day capture of all eight sites under `captures/MANIFEST.json` `conditions`; `capture.cjs` sha256 `736fc73de813adfde6616441959e4f6792d8a8e087aafc5fc269797af76851b5`; H from production with deployment SHA and Vercel deployment ID; masking rule | `PRE:45-62` |
| Assignment | 8×8 Williams rows for ratings, 7×7 cyclic Latin square for pairs, H on the left 10 of 20 times per opponent (70/140); the table is derived deterministically with the sealed file's sha256 as seed | `PRE:62-67` |
| Missing data and refusals | Complete data only; dropouts replaced before anyone sees a count; refusal list as drafted | `PRE:184-189` |

## 2. Parameter set at sealing: G-1 runs arm A only

- **The question.** The draft asks the founder (`PRE:77-80`): D-08 says "G-1 8명", but two arms
  of 8 need 16 people. The draft defaults to 8 per arm, and says: "8명만 모집하기로 하면, 봉인
  전에 §12의 `g1.arms`를 `["A"]`로 바꾼다" (`PRE:80`).
- **What was adopted.** The same 2026-10-17 message adopted D-08's default "실행한다(G-1 8명 +
  강제 선택 20명)" (`REG.md:73`). The register's founder step for it reads "28명(G-1 8 + 강제 선택
  20) 모집" (FH-10, `REG.md:106`). That is the "8명만" branch.
- **So:** `g1.arms` = `["A"]`, `nPerArm` = 8, `passMin` = 6. The B variant (`PRE:57`) is not
  tested. The H1 rule (`PRE:173`) can then only return `KEEP_A`, the current production H1. The
  draft names the cost: one input to the H1 decision (`PRE:80`). The other parameters keep the
  draft's values.
- Testing B as well means recruiting 8 more G-1 raters (36 people). That is a change, so it is a
  new version, sealed before the first response.

## 3. The machine seal (not installed by this lane)

`analyze.mjs` refuses real responses unless the prereg it reads has `status` `SEALED` and hashes to
its pinned `PREREG_SHA256` (`PRE:24`, `PRE:26`; `analyze.mjs` lines 17 and 162). This lane changes no
script, so the draft procedure (`PRE:25`) is prepared here and left for the lane that runs P2-38.

- **Exact bytes.** The draft with exactly three edits:
  1. §12: `"status": "DRAFT_PROPOSED",` becomes `"status": "SEALED",`
  2. §12: `"g1": { "arms": ["A", "B"],` becomes `"g1": { "arms": ["A"],`
  3. §0: one line appended after item 5, giving the seal time:
     `6. **봉인 일시(UTC)**: 2026-10-19T01:09:27Z. …` (the full line is in the reference file)
- **Reference file.** `UX\records\PREREG-SEAL\blind-PREREG.machine-sealed.md`.
- **Its sha256:** `91c772471e29c5d63456153a749524738bfd33a61ace63e31efe2685444a7a84`. The bytes
  are fixed by this record, so the assignment seed (`PRE:67`) is fixed now, and nobody can choose
  it later.
- **Checked in a scratch copy.** A copy of `analyze.mjs` pinned to that sha256 read the
  reference file. On the synthetic CSV with the B-arm G-1 rows removed it exited 0, with
  `"status": "SEALED"`, G-1 arm A only and `h1Decision` `KEEP_A`. On the full synthetic CSV it
  exited 3 with `arm="B" is not one of A`. The pinned original `analyze.mjs` refused the
  reference file with exit 2. All three are the designed behaviour. No repository script was
  changed.
- **To install** (lane P2-38 or a dedicated code lane, before the first response):
  - copy the reference file to `UX\blind\PREREG.md`;
  - set `PREREG_SHA256` in `analyze.mjs` to the sha256 above;
  - regenerate `UX\blind\SHA256SUMS.txt`;
  - re-run `node --test analyze.test.mjs`;
  - report the three sha256 values (`PREREG.md`, `analyze.mjs`, `SHA256SUMS.txt`) to the founder
    before the first response (`PRE:25`).

## 4. What this seal does not do

- It recruits nobody and writes no consent text. D-08 is `founder-hands`. FH-10 covers the
  recruitment route, the reward and the consent wording (`REG.md:73`, `REG.md:106`).
- It publishes nothing. D-09 is `hold`: the competitor-name tests stay. A comparison sentence is
  allowed only from a receipted result, and only as a pre-registered template (`REG.md` row D-09).
- The ICP that the "10 of 20" rule uses is Foundation `docs/gtm/ICP_DECISION_2026-10-17.md`
  (commit `61189cd5`, branch `codex/records-20261017`, not pushed; repo-bytes sha256
  `5b83a743f26d07e0bd6ba80b1aaa0b08b4c48ed9790010256aae86f3f137ea66`), which records D-02. That
  closes the draft's D-02 question (`PRE:258`).
- `capture.cjs` is copied into `blind/` and checked against its sha256 by P2-38, before capture
  (`PRE:55`).

## 5. Sources

| Path | sha256 |
| --- | --- |
| `UX\blind\PREREG.md` (the draft) | `1c1851096d555e22e5dedcae047bc678a26f632a212d57e0e0b41e8f87c87aa7` |
| `UX\blind\analyze.mjs` | `ee473b1285346f0416227799ed81a42e2c44a16f74a246cb45822123571aa8e7` |
| `UX\records\PREREG-SEAL\blind-PREREG.machine-sealed.md` (reference, section 3) | `91c772471e29c5d63456153a749524738bfd33a61ace63e31efe2685444a7a84` |
| `UX\DECISION-REGISTER-2026-10-17.md` | `5935276d245d230857fa632dcb6555d25756470d37f404fc6c3c00dc71d7c6dc` |
| `UX\DECISION-REGISTER-2026-10-17.json` | `86234c9397cec2d0ac8160276e525943857e7b2ec21e5e3a3b9891cc394120d3` |
| `UX\PHASE1-CRITIC-2026-10-17.md` (D-08, D-10 at 250, P2-38 at 321) | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `UX\SERVICE-DEFINITION-2026-10-17.md` (G12, line 367) | `c7783dd718713b7564697ce6df7e6abbad9ffc2489624b3ad3705e610b528dee` |
| Foundation `docs/gtm/ICP_DECISION_2026-10-17.md` at `61189cd5` | `5b83a743f26d07e0bd6ba80b1aaa0b08b4c48ed9790010256aae86f3f137ea66` |

## 6. The draft, byte for byte

Everything between the two marker lines below is the draft's exact bytes. Its own "상태:
`DRAFT_PROPOSED`" lines and its §12 block are the draft's text; the header above is what is
sealed, and section 3 gives the machine form. Check:

```text
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' BLIND-COMPARISON-PREREG-SEALED-2026-10-17.md | sha256sum
# expect 1c1851096d555e22e5dedcae047bc678a26f632a212d57e0e0b41e8f87c87aa7
```

<!-- BEGIN VERBATIM DRAFT: UX/blind/PREREG.md, sha256 1c1851096d555e22e5dedcae047bc678a26f632a212d57e0e0b41e8f87c87aa7 -->
# 사람 블라인드 비교 사전 등록 — TAVONEL-BLIND-PREREG-1 (초안)

- **상태**: `DRAFT_PROPOSED`. 아직 봉인하지 않았다. 봉인하려면 창업자 결정 D-10(임계값 승인)이 필요하다. 실행하려면 D-08(모집, 보상, 동의서)과 D-02(ICP 정의)도 필요하다.
- **lane**: P2-28. UX-L11 가운데 준비 부분이고, PHASE1-CRITIC의 BL-1에 해당한다. 실행은 P2-38이 맡는다.
- **작성일**: 2026-10-17. 응답은 아직 하나도 없다. 이 문서의 숫자는 모두 공식으로 계산한 설계값이다(§5, §9). 측정값은 없고, 공개 문장에 쓸 수 있는 숫자도 없다.
- **근거 문서** (읽은 시점의 sha256):

| 문서 | 이 문서가 가져온 것 | sha256 |
|---|---|---|
| `../UX-PLAN-2026-10-17.md` §7.1–7.4, §2.3 | 절차, 과제, 통과 규칙, 허용 문장, A안·B안 문장 | `f51bce9b9e8761e476f3f99ded841a36443a8eff73e817fc8c8a51616f7b8c42` |
| `../PHASE1-CRITIC-2026-10-17.md` §4.1, D-02, D-08, D-09, D-10 | BL-1 범위, `/ko` 390 판독 과제 추가, 결정 항목 | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `../../resume-20261015/competitive-20261015/REDESIGN-BRIEF-2026-10-15.md` §6 | 같은 캡처, 블라인드, 동등·우위 판정 규칙(§6.5) | `e42cebca380fb5c63aa87c710513c1d7ffd97ccb92b3f1039677a98b9dddd094` |
| `../../resume-20261015/competitive-20261015/COMPETITIVE-GAP-REPORT-2026-10-15.md` §1.2 | c1–c8, 트렌디함, 산만함의 정의와 방향 | `f1d487be3e2588c4bd21155e2a532073edd2d9338b4c11b7409104db02ec2c8e` |
| `../../resume-20261015/competitive-20261015/captures/MANIFEST.json` `conditions`, `runs` | 캡처 조건, 사이트 키 A–H | `d4f521c3f5543e66a02caddfbc6cd7b861db5b6e9b3d7dc5eea621f63f431243` |
| `design-system/tavonel/DESIGN_MASTER_V3.md` §25.1 | G-1: 8명, 10초, 6/8, 실패 응답 예 | `026a594dde27bfd8f15d7ad1dd3f81ae38b234d93d8a774d01990d03e9076840` |

- **이 문서가 정하지 않는 것**(창업자 전용): 모집 경로, 보상, 참여 동의서 문구, ICP 정의(D-02), 결과를 공개할지와 그 문장(D-09). 공개 비교 문장의 틀은 UX §7.4에 있다. `analyze.mjs`는 그 틀을 채우지 않는다.
- **사람이 판정한다.** 블라인드 범주 시험과 강제 비교는 사람이 한다(CLAUDE.md "Self-approval"). AI 심사는 계속 돌려도 되지만 내부 진단으로만 쓴다. 이 문서의 어떤 판정에도 AI 점수는 들어가지 않는다.

---

## 0. 봉인 규칙

1. 이 파일 바이트(UTF-8, LF)의 sha256을 `analyze.mjs`의 `PREREG_SHA256`에 고정한다. 해시가 다르면 `analyze.mjs`는 exit 2로 거부하고, 아무 결과도 쓰지 않는다. 한 바이트를 바꾼 사본과 줄끝을 CRLF로 바꾼 사본도 거부된다(`analyze.test.mjs`).
2. **봉인 절차.** D-10 승인을 받으면 §12의 `status`를 `SEALED`로 바꾸고, 이 절에 봉인 일시(UTC)를 한 줄 적는다. 그러면 sha256이 바뀐다. 새 값을 `analyze.mjs`의 `PREREG_SHA256`에 넣고 `SHA256SUMS.txt`를 다시 만든다. 첫 응답을 받기 전에 세 파일의 sha256을 창업자에게 보고한다.
3. `status`가 `SEALED`가 아니면 `analyze.mjs`는 실제 응답(`synthetic=0`)을 거부한다. 초안 상태에서는 합성 자료만 분석할 수 있다.
4. 결과를 본 뒤에는 기준, 규칙, 스크립트를 바꾸지 않는다. 바꾸면 새 id를 단 새 prereg가 되고, 수집부터 다시 한다(UX §7.1).
5. `analyze.mjs`의 sha256은 이 파일에 적지 않는다. 적으면 두 파일이 서로의 해시를 담는 순환이 생긴다. 그 값은 `SHA256SUMS.txt`에 두고, 봉인 보고에 함께 넣는다.

## 1. 대상

키 A–H는 `captures/MANIFEST.json` `runs`의 키를 그대로 쓴다. 이름은 내부 문서에만 적는다(§11-4).

| 키 | 사이트 | URL |
|---|---|---|
| A | Reducto | https://reducto.ai/ |
| B | LlamaParse | https://www.llamaindex.ai/llamaparse |
| C | Unstructured | https://unstructured.io/ |
| D | LandingAI | https://landing.ai/ |
| E | Firecrawl | https://www.firecrawl.dev/ |
| F | Browserbase | https://www.browserbase.com/ |
| G | Parallel | https://parallel.ai/ |
| H | TAVONEL | https://tavonel.com/ (production) |

## 2. 자극물

1. **같은 날, 한 번의 실행으로 8곳을 모두 캡처한다.** H만 새로 찍어 경쟁사의 옛 캡처와 비교하지 않는다(브리프 §6.1).
2. **캡처 조건**은 `MANIFEST.json` `conditions`를 그대로 쓴다.
   - 1440×900 @1x(데스크톱 UA), 390×844 @2x(isMobile, hasTouch, Android Chrome UA)
   - 사이트·뷰포트마다 새 컨텍스트, 첫 방문, en-US, light, reduced-motion 없음
   - `networkidle`, 내비게이션 시작부터 최대 20 s
   - 쿠키 배너가 첫 화면의 30%를 넘을 때만 거절·닫기
   - 0.8 뷰포트 단위 스크롤 → 맨 위로 복귀 1.5 s → 전체 캡처, 긴 페이지는 이어 붙이기
   - 브라우저 빌드는 실행 당일 값을 기록한다. 2026-10-15 실행은 Chrome 155.0.8059.40 headless, Playwright 1.62.0이었다.
3. **캡처 스크립트**는 `capture.cjs`(sha256 `736fc73de813adfde6616441959e4f6792d8a8e087aafc5fc269797af76851b5`, 394행)다. 이 파일은 지금 세션 scratchpad의 `competitive/` 폴더에만 있다. P2-38은 캡처 전에 이 파일을 `blind/`로 복사하고 sha256이 같은지 확인한다. 다르면 캡처하지 않는다.
4. **H는 공용 production URL에서 찍는다.** 배포 SHA와 Vercel deployment ID를 기록한다(UX §7.2).
5. **G-1 자극물**은 H의 1440 top 캡처 두 벌(A안, B안)이다. UX §2.3 표의 EN H1과 support만 다르고 레이아웃과 데이터는 같다. 운영은 A안이다. B안은 운영에 올리지 않은 별도 빌드에서 같은 조건으로 찍는다. B는 진술 단위 전수 보장 시험 전에는 공개하지 않는다(UX §2.3).
6. **마스킹**
   - 로고, 워드마크, 도메인, 화면 글자 속 브랜드명을 같은 단색 회색 막대(#808080, 테두리 없음)로 가린다. 8곳 모두 같은 규칙이다.
   - 좌표, 마스킹 전·후 PNG의 sha256, 판독 과제의 원문 문자열(캡처 시점 DOM에서 추출)을 `mask-manifest.json`에 남긴다.
   - 사이트 고유의 스타일까지 가릴 수는 없다. 이 한계는 결과에 적는다(§10).
7. **키와 순서**
   - 평가자에게 보이는 키는 A–H와 무관한 무작위 키로 다시 배정한다. 표시 키와 A–H의 대응은 `mask-manifest.json`에 둔다. 분석 CSV의 `site` 열에는 되돌린 A–H 문자를 쓴다.
   - 척도 평가의 사이트 제시 순서: 8×8 Williams 설계(1차 이월 균형)의 행을 평가자 R01–R20에 순서대로 돌려 배정한다. 20 = 8 + 8 + 4라서 마지막 네 행 몫은 균형이 불완전하다(§10).
   - 강제 선택 7쌍의 순서: 7×7 순환 라틴 방격의 행을 같은 방식으로 배정한다.
   - 좌우: 상대 사이트마다 20명 중 10명은 H를 왼쪽에서 보고, 10명은 오른쪽에서 본다. 그래서 전체 140회 중 H가 왼쪽인 횟수는 70회다. `analyze.mjs`는 70/140이 아니면 `sideBalance: DEVIATION`이라고 표시한다.
   - 배정표는 봉인된 이 파일의 sha256을 시드로 결정적으로 만든다. 봉인 뒤에는 아무도 시드를 고를 수 없다. 배정표와 그 sha256은 수집 전에 `mask-manifest.json`에 남긴다(P2-38).

## 3. 평가자

1. **비교 패널 n = 20.** 같은 20명이 폰 판독, 척도 평가, 강제 선택을 모두 한다(UX §7.3).
2. **자격**(UX §7.3, 창업자 F-6/D-08)
   - 20명 중 10명 이상이 ICP에 속한다. ICP 정의는 D-02다. 결정표 권고안은 "자주 바뀌는 문서 묶음을 가진 지식 소유 팀, 한국 조직 포함"이다.
   - TAVONEL이나 §1의 경쟁사와 이해관계가 없다.
   - 최근 90일 안에 tavonel.com을 본 적이 없다(자기 보고).
   - ICP 여부는 CSV `profile` 행으로 남긴다. `analyze.mjs`는 ICP가 10명 미만이면 거부한다.
3. **G-1 패널**은 비교 패널과 겹치지 않는다. 팔(A안, B안)마다 8명이다.
   - **창업자 확인 필요.** D-08 표에는 "G-1 8명"이라고 적혀 있다. 그런데 UX §7.3은 A안과 B안을 두 조로 나눠 시험하고, 통과 규칙은 "8명 중 6명"이다. 8명을 4 + 4로 나누면 이 규칙을 팔마다 적용할 수 없다.
   - 그래서 이 초안은 **팔마다 8명(G-1 16명, 전체 36명)**으로 둔다.
   - 8명만 모집하기로 하면, 봉인 전에 §12의 `g1.arms`를 `["A"]`로 바꾼다. 그러면 B안은 시험하지 않는다. B는 어차피 공개하지 않으므로, 잃는 것은 H1 결정 근거 하나뿐이다.
4. **신원 정보.** 원응답에는 개인 식별 정보를 넣지 않는다. 평가자 id는 무작위 코드(R01…, G01…)다. 신원 대조표는 이 폴더 밖에 두고 창업자가 보관한다. 동의 범위는 창업자가 정한다.

## 4. 과제

### 4.1 G-1 카테고리 (G-1 패널)

- 노출: 마스킹한 1440 top 캡처, 10초. 다시 보여 주지 않는다.
- 질문: "이 회사는 무엇을 하는가?" 자유 응답이다.
- **코드북.** 아래 세 가지를 모두 말하면 `IN`, 하나라도 빠지면 `OUT`이다.
  - (a) 입력: 문서(문서, 파일, PDF, 스캔, 계약서, 보고서 등)
  - (b) 출력: AI나 에이전트가 쓰는 지식, 맥락, 데이터
  - (c) 신뢰 표지: 근거, 출처, 인용, 원문 위치, 검증 가운데 하나
  - (a)–(c)는 UX §7.3 통과 문장 "문서를 근거가 붙은, AI가 쓰는 지식으로 바꾸는 제품"과 DESIGN_MASTER §25.1 "문서를 구조화·검증된 지식으로 바꾸는 제품"을 합친 것이다. 실패 응답 예는 "AI 도구", "데이터 분석", "문서 관리"다(§25.1).
  - (c)를 빼면 더 느슨한 범주 시험이 된다. 이 선택은 D-10에서 봉인 전에 정한다(§11).
- **코딩.** 사람 코더 두 명이 독립으로 판정한다. 코더는 응답이 어느 팔(A안·B안)에서 나왔는지 모르고, 응답은 섞어서 받는다. 두 코드가 다르면 세 번째 사람이 정한다. CSV에는 `coder1`, `coder2`, 최종 코드(`value`)를 남긴다. 두 코더가 일치했는데 최종 코드가 다르면 `analyze.mjs`가 거부한다.

### 4.2 비교 패널 과제 순서

한 평가자는 ① 폰 판독 → ② 척도 평가 → ③ 강제 선택 순서로 한다. 1차 종결점(강제 선택)을 마지막에 둔다. 그래야 모든 평가자가 여덟 곳을 같은 만큼 본 뒤에 고른다.

### 4.3 폰 판독 (c2 보조 과제)

- 자극물: 사이트마다 마스킹한 390 top 캡처. CSS 390 px 폭(@2x PNG의 100%)으로 보여 주거나 실기기로 보여 준다.
- 과제: "데모에서 읽을 수 있는 첫 문장을 그대로 적어 주세요."
- 판정: `mask-manifest.json`의 원문 문자열과 대조한다. 비교 전에 NFC 정규화, 공백 접기, 문장부호 제거를 하고, EN은 소문자로 바꾼다.
  - `EXACT`: 정규화한 결과가 원문 문장과 같다.
  - `PARTIAL`: 원문 단어의 절반 이상이 같은 순서로 나온다.
  - `NONE`: 그 밖의 경우, 또는 "읽을 수 없음"이다.
- **`/ko` 390 (PHASE1-CRITIC §4.1-3).** H의 `/ko` 390 top 캡처로 같은 과제를 한 번 더 한다. 한국어를 읽을 수 있다고 스스로 답한 패널 평가자만 한다. 분모는 그 인원수이고, 0명이면 0/0으로 그대로 적는다.

### 4.4 척도 평가 (기술 통계)

- 자극물: 사이트마다 마스킹한 1440·390 top/full 캡처. 순서는 §2-7을 따른다.
- 척도: 1–5. 정의와 방향은 갭 보고서 §1.2를 그대로 쓴다.

| 코드 | 기준 | 방향 |
|---|---|---|
| c1 | 첫 5초 안에 제품을 이해하는가 | 높을수록 좋음 |
| c2 | 데모·영상 속 실제 텍스트를 읽을 수 있는가 | 높을수록 좋음 |
| c3 | 첫 화면 CTA가 인지되는가 | 높을수록 좋음 |
| c4 | 근거·실데이터와 데모가 구분되는가 | 높을수록 좋음 |
| c5 | 모바일 조작 | 높을수록 좋음 |
| c6 | 키보드·대비·확대 | 높을수록 좋음 |
| c7 | 페이지 안 일관성 | 높을수록 좋음 |
| c8 | 부하·레이아웃 안정성 | 높을수록 좋음 |
| trend | 트렌디함·감각 | 높을수록 좋음 |
| clutter | 산만함 | **낮을수록 좋음** |

### 4.5 강제 선택 (1차 종결점)

- 자극물: H와 상대 사이트(A–G 각각)의 마스킹한 1440 top·full 캡처를 같은 폭으로 줄여 나란히 놓는다. 좌우와 순서는 §2-7을 따른다. 시간 제한은 없다.
- 질문: "전반적으로 어느 쪽 제품을 더 믿고 쓰시겠습니까?"
- 동률과 건너뛰기는 허용하지 않는다. 7쌍 모두 답해야 한다.

## 5. 1차 종결점과 판정 규칙 (사전 고정)

1. **비교 7개**: H 대 A, B, C, D, E, F, G. 비교마다 k = 20명 중 H를 고른 사람 수다.
2. **검정**: 단측 정확 이항검정. 귀무가설은 π = 1/2, 대립가설은 π > 1/2다. p = P(X ≥ k) = Σ_{i=k}^{20} C(20, i) / 2^20 이다. `analyze.mjs`는 이 값을 BigInt 분수로 정확히 계산하고, 판정에 부동소수점을 쓰지 않는다.
3. **다중 비교 보정**: Holm step-down, 가족 오류율 α = 0.05다.
   - p가 작은 순서로 정렬한다. 같으면 키 알파벳 순서다.
   - 순위 i의 기준은 α / (7 − i + 1)이다. 기준을 처음 넘는 비교에서 멈추고, 그 비교와 그 뒤의 비교는 모두 기각하지 않는다.
   - Holm 보정 p값(순위 j ≤ i에 대한 max(min(1, (7 − j + 1) · p_j)))도 함께 낸다.
4. **설계값** [계산]

| H를 고른 수 k / 20 | p = P(X ≥ k) | 소수 |
|---|---|---|
| 13 | 137980/1048576 | 0.131588 |
| 14 | 60460/1048576 | 0.057659 |
| 15 | 21700/1048576 | 0.020695 |
| 16 | 6196/1048576 | 0.005909 |
| 17 | 1351/1048576 | 0.001288 |
| 18 | 211/1048576 | 0.000201 |
| 19 | 21/1048576 | 0.000020 |
| 20 | 1/1048576 | 0.000001 |

| Holm 순위 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| 기준 α/(7−i+1) | 0.007143 | 0.008333 | 0.010000 | 0.012500 | 0.016667 | 0.025000 | 0.050000 |

   - 따라서 16/20 이상이면 어느 순위에서든 기각된다(UX §7.3의 "16/20 이상(P=0.0059)"). 15/20은 순위 6과 7에서만 기각된다(같은 절의 "15/20(P=0.0207)"). 14/20은 어느 순위에서도 기각되지 않는다.
   - **일곱 비교가 모두 유의하려면** 모든 비교가 15/20 이상이어야 하고, 정확히 15/20인 비교는 두 개까지만 허용된다. 나머지는 16/20 이상이어야 한다.
5. **결과와 허용 문장** (UX §7.4를 그대로 옮긴다. 공개는 언제나 창업자 결정 D-09다)

| `outcome` | 뜻 | 허용 | 금지 |
|---|---|---|---|
| `ALL_SIGNIFICANT` | 7개 모두 Holm 기각 | UX §7.4의 템플릿 문장이 claims pack **후보**가 된다. receipt는 `docs/evidence/artifacts/`에 sha256과 함께 둔다 | "best", "#1", "industry-leading"(BARRED), 기준을 바꿔 고른 부분 결과 |
| `SUBSET_SIGNIFICANT` | 일부만 기각 | 유의한 비교만 이름 없이 적는다("preferred to {m} of seven"). 불리한 결과도 같은 곳에 싣는다 | 유의한 것만 골라 쓰기 |
| `NONE_SIGNIFICANT` | 하나도 기각 못 함 | 공개 비교 문장은 없다. 실패한 가설로 `/research/notes`에 실을 수 있고, 시점은 창업자가 정한다 | "comparable", "on par" |

## 6. 2차·기술 분석 (공개 근거가 아니다)

1. **G-1.** 팔마다 `IN` 수 / 8을 내고, 6 이상이면 통과다. 코더 일치 수 / 8도 낸다.
   - H1 결정 규칙: B안이 통과하고 A안이 통과하지 못했을 때만 `SWITCH_TO_B`다. 그 밖에는 `KEEP_A`다(현행 유지, D-01 권고).
   - G-1 결과는 내부 결정 근거로만 쓰고, 공개 숫자로 쓰지 않는다(UX §7.4).
2. **척도.** 기준마다 사이트별 평균(n = 20, 소수 둘째 자리)을 낸다. 그리고 브리프 §6.5 규칙으로 기준마다 판정한다.
   - 최고 경쟁사: A–G 가운데 평균이 가장 높은 곳이다(산만함은 가장 낮은 곳). 동률이면 동률인 곳 모두를 최고로 보고, 아래 조건을 그 모두에 대해 만족해야 한다.
   - `EQUIVALENT`(동등): H 평균 ≥ 최고 평균 − 0.25이고, H에게 최고 사이트 이상의 점수를 준 평가자가 과반(> 10)이다.
   - `AHEAD`(우위): H 평균 > 최고 평균이고, H에게 더 높은 점수를 준 평가자가 과반이고, 강제 선택의 H 대 최고 사이트 비교에서도 H를 고른 수가 과반이다.
   - 둘 다 아니면 `NOT_SUPPORTED`(지원되지 않음)다. 산만함은 부등호 방향을 뒤집는다.
   - 이 판정은 내부 진단이다. 척도 결과만으로 공개 문장을 만들지 않는다(UX §7.3).
3. **폰 판독.** 사이트마다 `EXACT`, `PARTIAL`, `NONE`의 수를 분모와 함께 낸다. H의 `/ko` 390도 따로 낸다.
4. **좌우 균형.** H가 왼쪽에 놓인 횟수 / 140을 계획값 70/140과 함께 낸다.

## 7. 결측, 이탈, 편차

1. 분석은 완전한 자료에서만 돈다. 비교 패널 20명은 한 사람마다 판독 8개, 척도 80개, 강제 선택 7개를 모두 채워야 한다. G-1은 팔마다 정확히 8명이다.
2. 중간에 그만둔 평가자의 응답은 버린다. 같은 자격의 새 평가자를 모집해 채운다. 이 일은 누구도 집계를 보기 전에 끝낸다. 이탈 수는 결과 receipt에 적는다(P2-38).
3. `analyze.mjs`가 거부하는 경우는 다음과 같다(exit 3). 헤더·열·값 형식 오류, 중복 응답, 빠진 응답, 패널이 20명이 아닌 경우, ICP 10명 미만, G-1과 비교 패널의 중복, 코더 일치와 최종 코드의 모순, 합성·실제 행의 혼합, 봉인 전 prereg에 실제 응답을 넣은 경우.
4. 편차(캡처 조건 차이, 좌우 균형 깨짐 등)는 결과 receipt에 그대로 적는다. 편차를 핑계로 결과를 골라 보고하지 않는다.

## 8. 분석 스크립트와 원응답 형식

| 파일 | 역할 |
|---|---|
| `PREREG.md` | 이 문서. §12가 기계가 읽는 매개변수다 |
| `analyze.mjs` | 분석. `PREREG_SHA256`이 맞을 때만 실행한다 |
| `analyze.test.mjs` | 수락 시험(`node --test`). 합성 자료 생성기 `makeSynthetic()`도 이 파일에 있다 |
| `synthetic-responses.csv` | 합성 원응답. 사람이 낸 응답이 아니다 |
| `synthetic-result.expected.json` | 합성 원응답의 기대 결과. 바이트 단위 비교 기준이다 |
| `SHA256SUMS.txt` | 위 파일 전부의 sha256 |

```text
node analyze.mjs <responses.csv> [--prereg <PREREG.md>] [--out <result.json>]
exit 0 결과 JSON 출력 · 1 사용법 오류 · 2 prereg 해시 불일치 · 3 응답이 prereg를 만족하지 않음
```

- 결과를 파일로 남길 때는 `--out`을 쓴다. PowerShell의 `>`는 UTF-16으로 다시 써서 바이트가 달라진다.
- 출력 스키마는 `tavonel.blind_comparison_result.v1`이다. prereg sha256과 원응답 sha256을 담기 때문에 결과가 입력에 묶인다. 같은 입력이면 같은 바이트가 나온다. 시각이나 환경 값은 출력에 넣지 않는다.
- **CSV 형식.** UTF-8이고, 헤더는 정확히 `synthetic,task,rater,arm,site,item,value,coder1,coder2,h_side,text`다. RFC 4180 따옴표 규칙을 따르고, 줄끝은 LF 또는 CRLF다. 아래 표에 없는 열은 비워 둔다.

| task | 행 단위 | 필수 열과 허용 값 |
|---|---|---|
| `profile` | 비교 패널 1명 | `item=icp`, `value=Y\|N` |
| `g1` | G-1 평가자 1명 | `arm=A\|B`, `site=H`, `item=category`, `value`·`coder1`·`coder2`=`IN\|OUT`, `text`=자유 응답 |
| `reading` | 평가자 × 사이트 × 판 | `site=A–H`, `item=en390\|ko390`(ko390은 H만), `value=EXACT\|PARTIAL\|NONE`, `text`=적은 문장 |
| `rating` | 평가자 × 사이트 × 기준 | `site=A–H`, `item=c1…c8\|trend\|clutter`, `value=1–5` |
| `forced` | 평가자 × 상대 사이트 | `site=A–G`, `item=prefer`, `value=H\|OPP`, `h_side=L\|R`(H가 놓인 쪽) |

- `synthetic` 열은 `1`(합성) 또는 `0`(실제)이고, 한 파일 안에서 섞을 수 없다. 합성 자료의 결과에는 `"data": "SYNTHETIC: …"`가 찍힌다.
- **합성 자료.** `makeSynthetic()`가 고정 공식으로 만든다. 난수도 사람도 없다. 강제 선택 수(A 18, B 16, C 15, D 16, E 14, F 17, G 15 / 20)는 Holm이 순위 5에서 멈추는 경우를 시험하려고 고른 값이다. 예측이 아니다. 이 자료에서 C(15/20, p = 0.020695)는 보정 전이라면 0.05 아래지만 Holm 순위 5의 기준 0.016667을 넘는다. 그래서 C와 그 뒤의 G, E는 기각되지 않고, 결과는 `SUBSET_SIGNIFICANT` 4/7이다.
- **재현**: `blind/` 폴더에서 `node --test analyze.test.mjs`를 실행한다.

## 9. 설계 계산 — 이 표본 크기로 무엇을 볼 수 있는가 [계산, 미측정]

모든 비교에서 H를 고를 참 확률이 π로 같고, 일곱 비교가 서로 독립이라고 가정한다. 실제로는 같은 20명이 일곱 쌍을 모두 보므로 비교끼리 상관이 있다. 그래서 아래 값은 근사다.

- 한 비교가 16/20 이상일 확률: a = P(Bin(20, π) ≥ 16)
- 정확히 15/20일 확률: b = P(Bin(20, π) = 15)
- 일곱 비교가 모두 Holm 유의할 확률: Σ_{j=0}^{2} C(7, j) · b^j · a^(7−j) (§5-4의 조건)

| π | P(k ≥ 16) | P(k ≥ 15) | P(일곱 비교 모두 유의) |
|---|---|---|---|
| 0.60 | 0.0510 | 0.1256 | < 0.0001 |
| 0.70 | 0.2375 | 0.4164 | 0.0008 |
| 0.75 | 0.4148 | 0.6172 | 0.0199 |
| 0.80 | 0.6296 | 0.8042 | 0.1787 |
| 0.85 | 0.8298 | 0.9327 | 0.5935 |
| 0.90 | 0.9568 | 0.9887 | 0.9229 |

G-1(팔마다 8명, 6명 이상 통과)에서 참 `IN` 비율이 π일 때 통과할 확률은 P(Bin(8, π) ≥ 6)이다. π가 0.50이면 0.1445, 0.60이면 0.3154, 0.75이면 0.6785, 0.90이면 0.9619다.

**읽는 법.** n = 20은 강하고 고른 선호만 잡아낸다. 평가자 넷 중 셋이 H를 고르는 정도(π = 0.75)로는 일곱 비교가 모두 유의할 확률이 약 2%다. G-1의 6/8 규칙은 참 비율이 절반(π = 0.50)이어도 약 14% 확률로 통과한다. n을 늘릴지는 비용이 걸린 D-08의 일이다. 이 초안은 계획의 n을 바꾸지 않았다.

## 10. 한계

1. 마스킹은 로고와 이름만 가린다. 고유한 스타일이나 일러스트는 남는다. 평가자가 사이트를 알아봤는지는 재지 않는다.
2. 캡처는 한 시점의 첫 방문이다. 2026-10-15 실행에서 E와 F는 같은 날 방문마다 H1이 달랐다(A/B 실험으로 추정, MANIFEST `summary[].notes`). 실행 당일의 H1 문자열을 `mask-manifest.json`에 남긴다.
3. 평가자는 정지 캡처를 본다. c5(모바일 조작), c6(키보드·대비·확대), c8(부하·안정성)은 정지 화면으로 판단한 인상이다. 실제 조작을 잰 값이 아니다.
4. 자격 조건(ICP, 이해관계, 90일 미방문)은 자기 보고다.
5. 척도 평가 순서의 Williams 균형은 20명 가운데 16명 몫에서만 완전하다.
6. 폰 판독의 `PARTIAL` 판정에는 사람의 판단이 들어간다. 판정자는 사이트를 알 수 있다.
7. 결과는 "우리 조건에서 이 평가자들이 내린 판단"이다. 경쟁사 자체 지표와 섞지 않는다(CLAUDE.md "Competitor leaderboard rows are quoted"). QA 통과 수와 같은 문장에 두지 않는다(브리프 §6.7).

## 11. 창업자 결정 (이 초안이 기다리는 것)

1. **D-08** 모집 경로, 보상, 동의서 문구. 그리고 G-1 인원: 팔마다 8명(16명)으로 할지, 8명으로 A안만 시험할지(§3-3).
2. **D-10** 임계값(Holm α = 0.05, 단측 정확 이항, 6/8, 동등 여유 0.25)과 G-1 코드북의 신뢰 표지 (c)를 승인하고 봉인한다(§0-2).
3. **D-02** ICP 정의. 패널 자격 "10/20 이상 ICP"가 이 정의를 쓴다.
4. **D-09** 결과 공개 여부와 문장. 참고로 공개 문구 가드의 경쟁사 이름 정규식(Foundation `nextjs/lib/prohibited-phrases.test.ts:102`, main `4c80bb30`)에는 이 비교의 상대 가운데 Reducto, LlamaParse, Unstructured만 들어 있다. LandingAI, Firecrawl, Browserbase, Parallel은 없다. 비교 문장을 허용하기 전에 이 목록을 함께 봐야 한다.

## 12. 기계 판독 매개변수

`analyze.mjs`는 이 파일에서 아래 json 블록 하나만 읽는다. 이 파일에 json 블록은 이것 하나뿐이어야 한다.

```json
{
  "id": "TAVONEL-BLIND-PREREG-1",
  "status": "DRAFT_PROPOSED",
  "blockedOn": ["D-02", "D-08", "D-10"],
  "target": "H",
  "panel": { "n": 20, "icpMin": 10 },
  "forcedChoice": { "opponents": ["A", "B", "C", "D", "E", "F", "G"], "alpha": "0.05" },
  "g1": { "arms": ["A", "B"], "nPerArm": 8, "passMin": 6 },
  "ratings": {
    "equivalenceMargin": "0.25",
    "items": [
      { "id": "c1", "better": "higher" },
      { "id": "c2", "better": "higher" },
      { "id": "c3", "better": "higher" },
      { "id": "c4", "better": "higher" },
      { "id": "c5", "better": "higher" },
      { "id": "c6", "better": "higher" },
      { "id": "c7", "better": "higher" },
      { "id": "c8", "better": "higher" },
      { "id": "trend", "better": "higher" },
      { "id": "clutter", "better": "lower" }
    ]
  }
}
```
<!-- END VERBATIM DRAFT -->
