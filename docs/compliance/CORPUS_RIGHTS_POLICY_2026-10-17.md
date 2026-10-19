# Corpus rights policy — 2026-10-17 (decision D-31)

Decision register row **D-31** (source PHASE1-CRITIC D-31; aliases KB-F2, KB-F8, T-F4), class
`agent-now`, lane `CORPUS-POLICY`. Written 2026-10-19 by an agent. This is a document only. It
changes no code, no test, no tool, no manifest, no pre-registration, no public sentence, no price
and no evidence artifact. It states which document sources TAVONEL may put into a measurement
corpus, which it may measure internally only, and which it refuses. It then maps each class to what
the two existing corpus tools accept or refuse today, and names every place where a tool disagrees
with this policy as a follow-up for that tool.

Short paths used below:

- `UX` = `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017`
- `KB` = `UX\KOREAN-BENCHMARK-DESIGN-2026-10-17.md`
- `REG` = `UX\DECISION-REGISTER-2026-10-17.md` (and its pair `.json`)

## Where this file lives

The row's `executesVia` asks for "docs/ip 아래 새 파일로". That directory cannot take a new file
without a code change. `docs/ip/` is a fail-closed allowlist for privileged IP work product.
`docs/ip/.gitignore` ignores everything except three named files. `scripts/ip_privilege_guard.py`
(`ALLOWLIST`, line 91; rule at line 220) reports any other tracked path under `docs/ip/` as a
violation, and `tests/security/test_ip_privilege_guard.py` asserts that the two lists agree. To put
this file there, the guard, the `.gitignore` and the test's expectation would all have to change.
This lane changes documents only. Widening a privilege allowlist for a non-privileged policy would
also run in the wrong direction.

So the file sits in `docs/compliance/`, next to `license-policy.yaml`, `license-register.yaml` and
`source-register.yaml`, which are the repository's other licence and source-rights records. The
other half of `executesVia` is kept: the LEGAL-HOLD rows of `docs/ip/TECHNOLOGY_INTAKE_REGISTER.yaml`
are not touched, and no corpus source appears in them.

## The decision

**The question**, register D-31 `question`, verbatim:

> 코퍼스 권리 정책

**The adopted default**, register D-31 `adoptedDefault`, verbatim (`REG:45`; identical in
`UX\PHASE1-CRITIC-2026-10-17.md:271`):

> 허용: 품목 단위 공공누리 0·1유형, 저작권법 제7조 자료, 미국 연방 저작물, ParseBench(NOTICE). 내부
> 측정만: OmniDocBench, 판결문, DART(법률 확인 뒤). 거절: AI Hub, NC·ND, licence 없는 HF 세트,
> `D:\#센서 고객사 제공 자료`. 고객 문서는 동의 절차 뒤에만 쓴다

**How it executes**, register D-31 `executesVia`, verbatim:

> [G9] NEW: CORPUS-POLICY — KB-A5 `rights_manifest.py`의 허용·내부전용·거절 목록을 이 정책으로
> 고정(DART는 counsel 확인 전 거절 상태), 표 레인 코퍼스도 같은 목록(C6). 정책 문서는 docs/ip 아래
> 새 파일로, intake register의 LEGAL-HOLD 행은 건드리지 않는다

**Prerequisites**, register D-31: `KB-A5 (구현됨)`.

**The table-lane half**, register conflict C6, verbatim (`REG:125`):

> D-31 채택: 표 레인 검증 코퍼스는 합성 + D-31 허용 목록, DART·SEC 공시는 counsel 전 사용 안 함

**Who decided.** The founder adopted every default in the decision register on 2026-10-17:
"파운더 결정은 모두 실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수
있도록해줘" (`REG` header, 근거). That message adopts D-31's default. It approves no wording. It is
not counsel's opinion. It consents to no customer data use. It does not clear DART, which the row
itself holds until a legal check. This record is written by an agent. It records the adoption and
approves nothing itself.

Register D-31 `statusToday` before this record: `도구 구현, 정책 미고정`. After it, the policy is
recorded here. Both tools still carry their earlier vocabularies. The gaps are named below and
were not fixed in this lane.

## What the three classes mean

- **Allowed.** The source may go into a measurement corpus whose results can back a published
  sentence, under the evidence rules (a receipt, a denominator, a pre-registration sealed before
  the run). It may also go into a table-lane qualification corpus. The table design says such a
  corpus "권리가 정리된 것이어야 한다" (`UX\TABLE-EXTRACTION-AND-LIMITS-DESIGN-2026-10-17.md:285`).
  Allowed does **not** mean the original page may be shown publicly. Public display of an original
  crop has its own, narrower bar, the specimen `licenceBar` (`UX\specimen-candidates.json`; decisions
  D-05 and D-06). This policy does not widen that bar.
- **Internal measurement only.** `KB` §3 defines the class (`KB:107`): "우리 컴퓨터와 우리 처리 경로
  안에서 실행하고 채점한다. 결과 수치는 공개할 수 있지만, 원문 이미지나 원문 텍스트는 공개하지
  않는다." OmniDocBench is stricter than that definition: its numbers back no public claim at all
  (row 5 below).
- **Refused.** The source enters no corpus, internal or public. It is not fetched, opened or scored.

**Anything the row does not name is not allowed.** `docs/compliance/license-policy.yaml:2` sets
`default_action: deny`, and the KB1 tool rejects every unknown licence token (`KOGL_TYPE_UNKNOWN`).
This record keeps that direction. An unnamed source needs a decision that names it. The sources
the agent found unnamed are listed in "Sources the row does not name".

**The four-licence rule applies to every row.** A data permission says nothing about model weights,
code, hosted-API terms or third-party patents (`KB:113`, the FTO principle; CLAUDE.md "Code, model
weights, dataset and hosted-API terms are four separate licences"). Clearing a corpus clears no
model.

## The policy

| #   | Class                                                      | Source                                                                                              | Basis (path:line)                                                                                                                                                                                                                                           | Conditions the sources attach                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| --- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Allowed                                                    | 공공누리 제0·1유형, marked **on the item**                                                          | `KB:117` C1, `KB:118` C2; `KB:282` (§5.10)                                                                                                                                                                                                                  | The marking must be on the item page itself. A board- or site-level statement is not item evidence (`KB:117` 비고, `KB:282`, specimen `koreanRule`). Type 1 needs attribution and forbids any implied sponsorship (`KB:117`). An AI type marked next to type 0 or 1 follows that type. AI type alone is outside this row (`KB:121` C5). Photos on korea.kr are excluded (`KB:123` C7)                                                                                                     |
| 2   | Allowed                                                    | 저작권법 제7조 materials: 1호 statutes, 2호 고시·공고·훈령, 4호 their compilations and translations | `KB:126` C10, `KB:128` C12; quote from easylaw.go.kr, current act per WebSearch "법률 제20358호" (`KB:126`)                                                                                                                                                 | 3호 court decisions are row 6, not this row. The 관보 also prints items outside 제7조, so each gazette item is checked one by one (`KB:128`). The 제7조 quote has not been checked against law.go.kr. That site's terms were not read either (`KB:126`)                                                                                                                                                                                                                                   |
| 3   | Allowed                                                    | US federal government works (17 U.S.C. §105)                                                        | `UX\SPECIMEN-CANDIDATES-2026-10-17.md:27`; specimen F1 `:390`                                                                                                                                                                                               | The status abroad is not separately assessed. D-05 accepted that risk for specimens, with attribution, no logos, seals or emblems in a crop, and `jurisdiction` "status abroad not separately assessed" (`REG:32`). SEC filings are issuers' works, not federal works, so they are not in this row (`REG:125`)                                                                                                                                                                            |
| 4   | Allowed                                                    | ParseBench, with its NOTICE                                                                         | `UX\COMPETITOR-PROTOCOL-2026-10-17.md:125`, `:352`; Arena `evaluator_registry.json` `parsebench` (see Sources), `dataset_license` "Apache-2.0", `dataset_redistribution` "license_permits_with_notice", revision `2805a1d940f95a203e0ae4b88be9934f7765b3fc` | Keep the NOTICE. Label it as a benchmark made by a competitor (LlamaIndex) every time (`COMPETITOR-PROTOCOL:125`). Who holds copyright in the original documents is unclear (same line), and a dataset licence is not a document licence (specimen `licenceBar` `rejected`), so no ParseBench page is shown as a crop. Leaderboard rows are quoted, never claimed as reproduced (CLAUDE.md). Its Korean slice is n=1 (`KB:136` C20). Nothing goes to a vendor while D-34 holds (`REG:84`) |
| 5   | Internal only                                              | OmniDocBench                                                                                        | Arena `evaluator_registry.json` `omnidoc`: `dataset_license` "research-only-non-commercial", `dataset_redistribution` "prohibited_without_separate_rights_review", revision `aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec`; `TABLE-EXTRACTION…:155`, `:354`     | Internal research diagnosis only. Its numbers back no public claim and no commercial qualification (`TABLE-EXTRACTION…:155`, `:354`). It is never sent to a vendor (`COMPETITOR-PROTOCOL:352`). The data is never redistributed                                                                                                                                                                                                                                                           |
| 6   | Internal only                                              | Court decisions (저작권법 제7조 3호)                                                                | `KB:127` C11                                                                                                                                                                                                                                                | No original image or text is published. A personal-information risk remains even after de-identification (`KB:127`)                                                                                                                                                                                                                                                                                                                                                                       |
| 7   | Internal only, after a legal check. **Refused until then** | DART filings (dart.fss.or.kr, opendart.fss.or.kr)                                                   | `KB:129` C13 and its note D; `SPECIMEN-CANDIDATES:258`; `executesVia` "DART는 counsel 확인 전 거절 상태"                                                                                                                                                    | The OpenDART terms neither grant nor forbid redistribution. The rights holder looks like the filing company (`KB:129`). Until counsel confirms, DART is refused everywhere, the table lane included (`REG:125`). After counsel it becomes internal-only, and never a crop (`SPECIMEN-CANDIDATES:258`)                                                                                                                                                                                     |
| 8   | Refused                                                    | AI Hub (aihub.or.kr)                                                                                | `KB:130` C14; `korean-benchmark-receipts\TERMS-QUOTES-20261017.json` `aihub-usage-policy`                                                                                                                                                                   | "학습용으로만". Paragraph 5 forbids letting a third party view the data. Taking it abroad needs a separate agreement, and a foreign GPU or API counts as abroad (`KB:130`)                                                                                                                                                                                                                                                                                                                |
| 9   | Refused                                                    | Anything NC or ND, including 공공누리 제2·3·4유형                                                   | `KB:119` C3, `KB:120` C4, `KB:135` C19                                                                                                                                                                                                                      | C3 notes that a separate licence from the holder is possible. That would be a new decision, not this row. C4 left internal use of type 3 to the founder, and this row settles it: refused                                                                                                                                                                                                                                                                                                 |
| 10  | Refused                                                    | Hugging Face sets with no licence                                                                   | `KB:133` C17, `KB:134` C18; `korean-benchmark-receipts\HF-KOREAN-DATASETS-20261017.json`                                                                                                                                                                    | Readable is not reusable (CLAUDE.md). The same rule covers KoOCR-Bench's own `truth/` and `code/`, which carry no licence (`KB:131` C15). Its KOGL 1 and 관보 originals may be fetched again from the government source, and then they fall under row 1 or 2 on their own evidence (KB-F2, `KB:324`). Published KoOCR-Bench pages stay out of the KB1 confirm set (`KB:289`)                                                                                                              |
| 11  | Refused                                                    | `D:\#센서 고객사 제공 자료`                                                                         | `KB:72` I-19, `KB:137` C21, KB-F8 `KB:330`                                                                                                                                                                                                                  | It looks like customer material. It has not been opened, and this lane did not open it                                                                                                                                                                                                                                                                                                                                                                                                    |
| 12  | After consent only                                         | Customer documents                                                                                  | `adoptedDefault`; register D-12 (`REG:42`)                                                                                                                                                                                                                  | Customer documents enter a corpus only after the consent procedure. Today `activationPolicy.customerData.enabled` is `false` on Foundation main `4c80bb30` (D-12 `statusToday`). The FD-15 record says a public-domain fixture run is not customer data. It turns nothing on (Foundation `docs/CUSTOMER_DATA_GATE_2026-09-06.md` §11, branch `codex/records-20261017` commit `e615f0ea`, not yet on main)                                                                                 |

**The table lane uses the same list** (register C6). Its validation corpus is synthetic tables plus
rows 1–4. T-F4 recommended "합성 + 공시 문서" (`TABLE-EXTRACTION…:382`). Under this policy the
filing half is DART (row 7, refused until counsel) and SEC filings (not row 3). So the table lane
starts from synthetic tables and rows 1–4 only. OmniDocBench stays the table lane's internal
diagnosis (row 5) and is never its qualification corpus.

## Sources the row does not name

These stay **not allowed** under the default-deny rule until a decision names them. Each is listed
because a source document raised it.

| Source                                                           | What the sources say                                                                                                                                                                | Effect today                                                                                                                                              |
| ---------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 저작권 보호기간 만료 marking                                     | KB-F2 recommended accepting it (`KB:324`, `KB:118` C2). The adopted D-31 text leaves it out. `UX\KB1-PREREG.json:96` (`rights_rules_ko`) still lists it as allowed                  | Not allowed. Founder question (founderHands). It is the main supply for K5 (`KB:152`), which is not in T1 (K1·K3·K4, register D-02), so T1 is not blocked |
| CC0, CC BY, other public-domain statements                       | The specimen `licenceBar` accepts them for specimen display (`SPECIMEN-CANDIDATES:27`). D-31 is silent on them as corpora                                                           | Not a corpus source. Founder question                                                                                                                     |
| olmOCR-bench                                                     | Arena registry `olmocr`: `dataset_license` "license-review-required", `dataset_redistribution` "prohibited_until_license_review". FD-3: counsel decides (`COMPETITOR-PROTOCOL:352`) | Not a corpus source under this policy                                                                                                                     |
| GDP.pdf                                                          | FD-3 keeps F1 and does not send it until Surge's rights are confirmed (`COMPETITOR-PROTOCOL:352`)                                                                                   | Not a corpus source under this policy                                                                                                                     |
| `junyeong-nero/synthetic-ocr-images-ko-1M` (cc-by-sa-3.0)        | "합성 대조군으로만 가능" (`KB:132` C16)                                                                                                                                             | Not named. Not used                                                                                                                                       |
| SEC filings                                                      | Issuers' works, not in the allowed list. Not used before counsel (`REG:125`)                                                                                                        | Not used                                                                                                                                                  |
| 정보공개포털 open.go.kr; the 국가기록원 current copyright policy | The policy pages returned 404 (`KB:138` C22, `KB:124` C8)                                                                                                                           | An item from these sites may enter only under row 1, with its own item-level marking                                                                      |
| Our own synthetic pages                                          | The table lane may use them (`REG:125`). KB1's KS set is a harness check only, "headline에 넣지 않고 공개 수치로도 쓰지 않는다" (`KB:154`)                                          | Allowed as synthetic, labelled `SYNTHETIC`, never a public number                                                                                         |

## What the tools accept today

Neither tool was edited. Both were read at their pull-request heads.

### KB1 `research/kb1_korean_bench/rights_manifest.py` — Core PR #109

Read at the head of PR #109 (merged 2026-10-19 as `f421895`, head `559aad61`), `559aad611e76369d12e8e32f5dfc6a096344ee87` (branch `agent/kb1-korean-bench-20261017`,
worktree `D:\CodexProjects\handoff-1002\core-KB`). The file's sha256 is in Sources. The tool reads a
person's per-item input (`item_id`, `url`, `kogl_type`, `marking_scope`, `retrieved_on`, `sha256`,
`family_id`, line 115) and gives each item a verdict of accept or reject. There is no third
verdict.

| #   | Policy class                         | What the tool does today (line)                                                                                                                                                                                            | Agrees?                                                                                                    | Follow-up    |
| --- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- | ------------ |
| 1   | Allowed: 공공누리 0·1, item-level    | Accepts `kogl_type` "0" or "1" (142) only with `marking_scope` "item" (219). Board or site scope gives `MARKING_SCOPE_NOT_ITEM`                                                                                            | Yes                                                                                                        | —            |
| 2   | Allowed: 제7조 1·2·4호               | `copyright_act_art7` gives `FOUNDER_DECISION_PENDING` (153). The docstring adds that a statute carries no marking, so `marking_scope` does not fit it                                                                      | **No.** It refuses an allowed class                                                                        | KB-T1        |
| 3   | Allowed: US federal works            | No token for it. Any other value gives `KOGL_TYPE_UNKNOWN` (217)                                                                                                                                                           | **No**, but refusing is the safe direction. KB1 is a Korean corpus                                         | KB-T4        |
| 4   | Allowed: ParseBench                  | No token gives `KOGL_TYPE_UNKNOWN`. Its URL on huggingface.co also gives `ITEM_URL_NOT_ORIGINAL_SOURCE` (157)                                                                                                              | **No**, but refusing is the safe direction. ParseBench is governed by the Arena registry, not by this tool | KB-T4        |
| 5   | Internal only: OmniDocBench          | No token gives `KOGL_TYPE_UNKNOWN`                                                                                                                                                                                         | Refusing is the safe direction. The tool has no internal-only verdict                                      | KB-T2        |
| 6   | Internal only: court decisions       | No token. Entered as `copyright_act_art7`, it gives `FOUNDER_DECISION_PENDING`                                                                                                                                             | Refusing is the safe direction. K6 cannot use them yet                                                     | KB-T1, KB-T2 |
| 7   | Refused until counsel: DART          | No token gives a reject. **But no host rule:** a dart.fss.or.kr URL with a claimed `kogl_type` "1" and `marking_scope` "item" would be accepted. `DENIED_HOSTS` names only aihub.or.kr, huggingface.co and hf.co (155-159) | **Partly.** It depends on the person's label                                                               | KB-T3        |
| 8   | Refused: AI Hub                      | `ai_hub` token, and any aihub.or.kr host or subdomain in any spelling, gives `AI_HUB_TERMS` (156)                                                                                                                          | Yes                                                                                                        | —            |
| 9   | Refused: NC·ND                       | KOGL 2, 3, 4 and `nc` and `nd` give their own codes (143-149). `ai_only` gives `KOGL_AI_TYPE_ONLY`                                                                                                                         | Yes                                                                                                        | —            |
| 10  | Refused: unlicensed HF sets          | `unlicensed` gives `UNLICENSED`. Every huggingface.co or hf.co URL gives `ITEM_URL_NOT_ORIGINAL_SOURCE`                                                                                                                    | Yes, and stricter: no HF-hosted item passes                                                                | —            |
| 11  | Refused: `D:\#센서 고객사 제공 자료` | No path field. A local path or `file:` URL fails the http(s) rule as `ITEM_URL_INVALID` (187)                                                                                                                              | Yes, by construction. A copy put on a web host could not be told apart; a person controls that (KB-F8)     | —            |
| 12  | Customer documents after consent     | Same as row 11. The tool has no consent field                                                                                                                                                                              | Outside the tool. The customer-data gate governs it                                                        | —            |
| —   | 보호기간 만료 (unnamed)              | `expired` gives `FOUNDER_DECISION_PENDING` (152)                                                                                                                                                                           | Yes, while the founder question is open                                                                    | —            |
| —   | Every manifest                       | `POLICY_STATUS` (106) says "PROPOSED_NOT_FOUNDER_ACCEPTED: KB-F2 / D-31 undecided"                                                                                                                                         | Stale since 2026-10-17. But it is truer than a claim of alignment while rows 2 and 7 still disagree        | KB-T5        |

### Table lane `research/table_lane_shadow/run_shadow.py` — Core PR #112

Read at the head of PR #112 (merged 2026-10-19 as `4b8f89d`, head `ab149f5c`), `4390083b1105d870ed77bb3fe9c96f5ad8ccb140` (branch `agent/table-lane-20261017`, worktree
`D:\CodexProjects\handoff-1002\core-TB`, whose unpushed tip `ab149f5` has the same rights set). The
harness takes a corpus-level label, `RIGHTS_STATUSES` = `synthetic`, `research_only_non_commercial`,
`rights_to_confirm`, `customer_consented` (lines 66-67). It refuses one run that mixes rights statuses
(`SHADOW_CORPUS_RIGHTS_MIXED`, 452-460). It judges no source itself.

| Status                         | Policy                                                                       | Agrees?                                                                                                              | Follow-up |
| ------------------------------ | ---------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------- |
| `synthetic`                    | Allowed for the table lane (C6)                                              | Yes                                                                                                                  | —         |
| `research_only_non_commercial` | OmniDocBench, internal only (row 5)                                          | Yes, as a label. A receipt with this status backs no public claim                                                    | TB-T2     |
| `rights_to_confirm`            | Would cover DART or SEC filings, which are refused until counsel (row 7, C6) | **No.** The harness accepts such a run                                                                               | TB-T1     |
| `customer_consented`           | Row 12                                                                       | **Partly.** It is accepted on the manifest's word, with nothing tied to a consent record, while customer data is off | TB-T1     |
| (none)                         | Rows 1–4, the allowed public classes                                         | **No status exists**, so a qualification corpus from the allowed list cannot be labelled                             | TB-T2     |

## Follow-ups for the tools

These were not done here. PR #109 and PR #112 were not edited. Each is a code change with its own
failing test, under the usual review.

- **KB-T1 (PR #109 tool).** Accept 제7조 1·2·4호 items with an evidence field that names the 호 and
  quotes the statute, instead of a KOGL marking. Route 3호 court decisions to the internal-only
  verdict. Keep the item-by-item check for gazette items.
- **KB-T2 (PR #109 tool).** Add a third verdict, internal-only. Write it to its own list, never to
  `rights_by_item` for publishable results, so an internal-only item can never feed a crop.
  OmniDocBench additionally backs no public claim.
- **KB-T3 (PR #109 tool).** Add dart.fss.or.kr and opendart.fss.or.kr to `DENIED_HOSTS` with a
  dedicated code (for example `DART_COUNSEL_PENDING`) until counsel confirms. Then route DART to
  internal-only, not to accept.
- **KB-T4 (PR #109 tool).** Say in the docstring that the tool covers the Korean KOGL and 제7조
  corpus only. US federal works and ParseBench are allowed by this policy but recorded elsewhere:
  ParseBench in the Arena evaluator registry, federal works in the specimen or table-lane receipt.
  That is the smallest correct change. Add tokens only if KB1 ever takes such an item.
- **KB-T5 (PR #109 tool).** Change `POLICY_STATUS` to cite this record **in the same change** that
  closes KB-T1 and KB-T3. Never change it earlier, so the string never claims an alignment the code
  does not have.
- **TB-T1 (PR #112 harness).** Refuse `rights_to_confirm` for any qualification run, and refuse
  `customer_consented` while the customer-data gate is off, or require it to name a consent record.
- **TB-T2 (PR #112 harness).** Add a status for corpora made from rows 1–4, and mark
  `research_only_non_commercial` receipts as never backing a public claim.
- **PREREG (handed to lane PREREG-SEAL, decision D-10).** The KB1 pre-registration still restates
  the proposal: `rights_rules_ko` lists 보호기간 만료 as allowed (`KB1-PREREG.json:96`), the
  `rights_item_schema` enum has no internal-only value (`:88`), and `blocked_on` D-31 is `OPEN`
  (`:724-733`). The file is fixed by sha256 `cb51fd44…` and is only rewritten as a new revision, so
  PREREG-SEAL aligns it with this record in the same new revision it already owes for D-02 and D-10.
  It was not edited here.

## What this record does not change

- No code, test, tool, manifest, pre-registration, evidence artifact, public sentence, price or
  licence string. `docs/ip/` and the intake register's LEGAL-HOLD rows are untouched.
- The specimen bar, D-05 and D-06, which decide what original content may be shown, still governs
  display. This policy decides corpus use only.
- D-34 still holds. No corpus goes to any vendor.
- It is not legal advice. The terms quotes were extracted by WebFetch with a small model. They are
  re-read on the live page before anyone relies on them legally
  (`TERMS-QUOTES-20261017.json` `method`; `KB:111`).

## Founder hands

- **Counsel on DART** (row 7): whether DART filings may be measured internally. Until counsel
  answers in writing, DART stays refused.
- **보호기간 만료 marking**: should it join row 1? The question is KB-F2's recommendation against
  the adopted D-31 text, which leaves it out.
- **CC0, CC BY and other public-domain statements as corpora**: should they join the allowed list?
  Today they are allowed for specimen display only.
- **Before any legal reliance**: counsel re-reads the live terms pages behind rows 2, 7, 8 and 9.
  The quotes here were extracted automatically.

## Sources

Every path below was read for this record. The sha256 is of the bytes as read.

| Source                                                                                                                                                                                                                | sha256                                                             |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `UX\DECISION-REGISTER-2026-10-17.md` (D-31 `:45`, C6 `:125`, D-05 `:32`, D-12 `:42`, D-34 `:84`)                                                                                                                      | `5935276d245d230857fa632dcb6555d25756470d37f404fc6c3c00dc71d7c6dc` |
| `UX\DECISION-REGISTER-2026-10-17.json` (row `D-31`)                                                                                                                                                                   | `86234c9397cec2d0ac8160276e525943857e7b2ec21e5e3a3b9891cc394120d3` |
| `UX\PHASE1-CRITIC-2026-10-17.md` (`:245`, `:271`)                                                                                                                                                                     | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `UX\KOREAN-BENCHMARK-DESIGN-2026-10-17.md` (§3 `:103-142`, §4 `:144-154`, §5.10-5.11 `:276-289`, §8 `:319-331`)                                                                                                       | `f7fa20afe1e80aa62e1fd753a31b1a84e320299af191c8ec619272dcfa137b7e` |
| `UX\TABLE-EXTRACTION-AND-LIMITS-DESIGN-2026-10-17.md` (`:155`, `:285`, `:354`, `:382`)                                                                                                                                | `09e20ffed8904fa0cea70c3454604b836df00a47df5c5cffe795dd22ba77c132` |
| `UX\COMPETITOR-PROTOCOL-2026-10-17.md` (`:125`, `:321`, `:352`)                                                                                                                                                       | `f40eb532eb4a16dd4608e9afbbe01ab0e65e1a4dc90105f9446ef13ea49ae2e1` |
| `UX\SPECIMEN-CANDIDATES-2026-10-17.md` (`:27`, `:258`, `:390`)                                                                                                                                                        | `ebc63763565857897104ea5f527b7b85df6bc9212a38fb5f186d46bd7027bb94` |
| `UX\specimen-candidates.json` (`licenceBar`)                                                                                                                                                                          | `dd25271bfc3d9c4be53bdf0e5ddcde051edbe38860b207ba56594ea1e91e290f` |
| `UX\SERVICE-DEFINITION-2026-10-17.md` (§5 G9 `:364`)                                                                                                                                                                  | `c7783dd718713b7564697ce6df7e6abbad9ffc2489624b3ad3705e610b528dee` |
| `UX\KB1-PREREG.json` (`:85-104`, `:724-733`)                                                                                                                                                                          | `cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff` |
| `UX\korean-benchmark-receipts\TERMS-QUOTES-20261017.json`                                                                                                                                                             | `2f29a94901aa959261978be79c50a945deedf8983851fe81d24c62240acb5e7e` |
| `UX\korean-benchmark-receipts\HF-KOREAN-DATASETS-20261017.json`                                                                                                                                                       | `ea9569865aeecd5333d1072accc46b8e31f7d3ef7260039d56a638140f3af770` |
| `UX\core-lanes\KB-A5\KB-A5-RECEIPT.json`                                                                                                                                                                              | `7ef927b3bc725dceb7fe36eb44a1af540b19963fbc53fed762225b6b4ff56c86` |
| `research/kb1_korean_bench/rights_manifest.py` at `559aad61` (PR #109 head)                                                                                                                                           | `9beaa0c95d18998a3c4e57243433f363ae3756b139e788d29a54cc26a353a287` |
| `research/table_lane_shadow/run_shadow.py` at `4390083b` (PR #112 head)                                                                                                                                               | `1a6aeaa047b5b5486a5e616848d6be096e8c3423f97acc1d5f101941651c8f2d` |
| `research/model_arena_20260903/evaluator_registry.json` at `d9db24c1` (Arena branches, for example `research/source-faithful-kc-v1`; not on this branch) (`olmocr` `:6-9`, `omnidoc` `:49-54`, `parsebench` `:79-85`) | `668eaa0fb6fc7f823ac88cb20b692dc4d45a2c114fd4d7a6e0f5457b454a380b` |
| `scripts/ip_privilege_guard.py` (this branch)                                                                                                                                                                         | `86321dbc507b3c061877c23dc40c3f722acf65f32863b0e400fb4ea015a983f1` |
| `docs/ip/.gitignore` (this branch)                                                                                                                                                                                    | `79e4c7184f9fdab1f8dfc2c1568d0976891aec0479a9849b75d9cc1c81875585` |
| `docs/compliance/license-policy.yaml` (this branch)                                                                                                                                                                   | `2ffb4e0cb6a855722c98b317d22e39bff38947e2cf3a4b7b703bdd90dc772510` |
