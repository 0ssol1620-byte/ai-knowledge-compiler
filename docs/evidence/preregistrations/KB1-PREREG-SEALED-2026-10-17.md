# KB1 Korean benchmark pre-registration `tavonel.kb1_prereg.v1` — SEALED (decision D-10)

Decision register row **D-10** (source PHASE1-CRITIC D-10; aliases C-FD-6, KB-F5, KB-F9), class
`agent-now`, lane `PREREG-SEAL`. Lanes bound: P2-27 (Korean KB-A3). Written by an agent. This is a
document only: it changes no code, no test, no harness, no draft, no price, no public sentence and
no evidence artifact.

| Field | Value |
| --- | --- |
| Status | **SEALED: thresholds and decision rules.** Not reached: the draft's run-ready seal (`seal_procedure` step 6, status `FOUNDER_APPROVED_SEALED`, `PRE:690-698`). The draft forbids that seal while any of its data-binding fields is null (`PRE:651`), and they are (section 3). **No confirm run may start on this version** |
| Decision | D-10, adopted default: "초안대로 승인하고 실행 전에 봉인한다. 벤더 δ(§4.5), KB1 n ≥ 50·family ≥ 10, API arm은 model ID와 revision을 하나로 고정, 블라인드 비교는 Holm α 0.05" (`REG.md:46`; `REG.json` row `D-10`). It answers KB-F5 ("KB1-PREREG 초안의 게시 기준(n ≥ 50, family ≥ 10)과 §5.9 문장표를 승인한다", `KB:327`) and KB-F9 ("실행 전 1개 ID와 revision으로 고정한다", `KB:331`) |
| Adoption | Founder message 2026-10-17, verbatim: "파운더 결정은 모두 실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수 있도록해줘" (`REG.md:3`). Cited as the adoption of the D-10 register default only. It is not a wording approval, not a claim approval, not a budget and not customer-data consent |
| Decision date | 2026-10-17 (the adoption; the date in this file's name) |
| Sealed at | 2026-10-19T01:09:27Z (UTC). The commit that adds this file is the timestamp of record |
| Draft | `UX\KB1-PREREG.json`, revision `kb1-prereg-draft-r1`, sha256 `cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff`, 65,771 bytes, 979 lines, LF. Matches its sidecar `UX\KB1-PREREG.json.sha256` and the KB-A1 key check (`UX\core-lanes\KB-A1\prereg-key-check.out.json`). The draft file is not changed |
| State at sealing | No KB1 run and no scoring (`PRE:9`); no annotator (register D-32 `statusToday` "주석자 0", `REG.md:67`) |
| Change rule | **Changes after sealing require a new version.** The run-ready revision (`kb1-prereg-r2`) may only fill the fields listed in section 3 and answer the FOUNDER-SET items; it names this file's sha256 as its parent. A changed threshold, metric, statistic or rule is a new pre-registration, and after any confirm run it also needs a fresh untouched holdout (`PRE:697`) |

Short paths: `UX` = `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017`;
`REG` = `UX\DECISION-REGISTER-2026-10-17`; `KB` = `UX\KOREAN-BENCHMARK-DESIGN-2026-10-17.md`;
`PRE` = the verbatim draft at the end of this file (line numbers are the draft's own).

## 1. Sealed parameters

Every value below is the draft's value, unchanged. None is calibrated (`PRE:11`); sealing fixes
them before results, it does not show they are right.

| Parameter | Sealed value | Draft lines |
| --- | --- | --- |
| Tier | **T1 only**: K1, K3, K4. T2 (K1–K6) is not adopted until the pilot measurement (register D-02 and D-32) | `PRE:35-61` |
| Pages per category (T1) | confirm 50, calibration 10 | `PRE:42-43` |
| Families (T1) | at least 10 families per category in confirm, at most 5 pages per family | `PRE:44-45` |
| Family and split | family = same institution's serial or revisions of one document, after exact and near-duplicate merge; no family overlap between calibration and confirm; split seed `tavonel-kb1-split-2026-10-17` | `PRE:25`, `PRE:72-81` |
| Normalization | NFC primary, NFKC secondary report, compatibility ideographs folded primary / raw secondary, PUA drafts discarded | `PRE:495-504` |
| Primary metric | M1 CER, micro per category; page distribution p50, p90 and "CER > 0.10 pages / all pages"; no output = CER 1.0; "1−CER" is never called accuracy | `PRE:506-517` |
| Secondary metrics | M1-s, M2, M3, M4 (TAVONEL: UNSUPPORTED, not averaged as 0), M5, M6, M7, M8, M9 with IoU ≥ 0.5 | `PRE:518-570` |
| CI | Family-cluster bootstrap, 95% percentile, 10,000 resamples, seed `tavonel-kb1-bootstrap-2026-10-17` | `PRE:577-581` |
| Paired comparison | **SA-1 and SA-2 adopted** (see the reading below): Δ = comparison-arm micro CER − TAVONEL micro CER on the same paired family-cluster resample; exact sign test over families; Holm over all pre-registered (comparison arm × category) pairs at family-wise α = 0.05; a superiority sentence needs Holm-adjusted p < 0.05 **and** a Δ 95% CI that excludes 0 | `PRE:582-596`, `PRE:613-621` |
| Same conditions | Rules 1–8, including rule 3: an API model is fixed to one exact model ID and one revision, the served model is checked per cell, and a mismatch is `UNEXPECTED_MODEL` | `PRE:433-474` |
| Publishable rule | All seven criteria must hold, including n ≥ 50 pages and ≥ 10 families per category, item-level rights for every page, and a seal timestamp earlier than the first confirm run | `PRE:600-612` |
| Denominators, fail-closed, gold, leakage | As drafted | `PRE:622-652` |
| Statement shapes | S0, S1, S2, S3 and the competitor-quote shape, as drafted. This seal publishes nothing; S0 is the only sayable state and it goes on `/sources` only (D-33, register conflict C1) | `PRE:653-683` |

**How "초안대로" was read for SA-1 and SA-2.** The draft marks both "proposed — D-10이 채택 여부를
정한다" (`PRE:586`, `PRE:592`), the same `proposed` status that every other threshold in the draft
carries (`PRE:11`). D-10's adopted default approves the draft as drafted, so this seal adopts both.
SA-2 is also the KB1 form of the Holm α 0.05 that D-10 names for the blind comparison
(`PRE:594`). Both make a superiority sentence harder to reach, not easier. If the founder reads
"초안대로" as the unamended design §5.5 text instead, that is a change, and it goes into
`kb1-prereg-r2` before any confirm run (question in section 4).

## 2. Alignment at sealing (binds over the draft text)

These decisions were adopted with the same 2026-10-17 message and recorded before this seal. Where
one disagrees with the draft, the line here governs.

1. **D-02 is decided.** The draft's `blocked_on` entry D-02 (`PRE:700-710`, status `OPEN`) is
   resolved by Foundation `docs/gtm/ICP_DECISION_2026-10-17.md` (commit `61189cd5` on branch
   `codex/records-20261017`, not pushed; repo-bytes sha256 `5b83a743f26d07e0bd6ba80b1aaa0b08b4c48ed9790010256aae86f3f137ea66`):
   ICP option 1, and KB1 starts at T1 (K1, K3, K4).
2. **D-10 is decided** by this file (`PRE:711-722`).
3. **D-31 is decided.** The draft's entry D-31 (`PRE:723-734`, `OPEN`) is resolved by Core
   `docs/compliance/CORPUS_RIGHTS_POLICY_2026-10-17.md` (commit `4a583312`, repo-bytes sha256
   `72aa489e61ceaef1945c6a552ae7adc733ea6ac8cbe9b0ac90ab5cb4cc601dba`). Three draft lines are
   superseded:
   - `PRE:96` lists "보호기간 만료 표시" as allowed. The adopted D-31 text does not name it, and
     the policy records it as not allowed (policy, "Sources the row does not name"). So the
     `kogl_type` value `expired` (`PRE:88`) is not admissible in a KB1 manifest until a decision
     names it. K5, its main supply, is not in T1, so T1 is not blocked.
   - `PRE:96` lists 판결문 and DART as internal-only. Per the policy, 제7조 3호 court decisions
     are internal only (row 6) and DART is **refused until counsel confirms** (row 7). The
     `rights_item_schema` enum has no internal-only value (`PRE:88`), so an internal-only item
     never enters `rights_by_item` for publishable results (policy follow-up KB-T2).
   - The policy's allowed rows 1–2 (공공누리 0·1 marked on the item; 제7조 1·2·4호) are the only
     sources a publishable KB1 page can come from.
4. **D-32 is still open** (`PRE:735-746`). It is `founder-hands` (FH-11): annotators, adjudicator,
   GPU cap USD 50 (`REG.md:67`, `REG.md:107`). The register adopted the direction; the contract
   and the rate are the founder's.
5. **The agent builds are further along than the draft says.** The draft lists KB-A1, KB-A4 and
   KB-A5 as `NOT_BUILT` (`PRE:747-767`). The register header records KB-A1/A2/A4/A5/A6 as
   implemented in worktrees, not merged, and labels that lane state a task assumption
   (`REG.md:8`, "과제 가정"). Nothing here depends on that difference.

## 3. Not sealed: fields the run-ready revision must fill

The draft forbids a run-ready seal while any of these is null (`PRE:651`). Each is filled by the
step the draft names (`PRE:690-698`), never estimated.

| Field (draft lines) | Filled by |
| --- | --- |
| `dataset.manifest_sha256`, `family_count_by_category`, `rights_by_item` (`PRE:21`, `PRE:63-71`, `PRE:84`) | KB-A5 item-level rights manifest, under the D-31 policy |
| `calibration_set_sha256`, `confirm_set_sha256` (`PRE:82-83`) | Family split with the sealed seed |
| TAVONEL arm `model_revision`, `runtime_image_digest`, `inference_config_sha256` (`PRE:118`, `PRE:127`, `PRE:132`) | Read from the endpoint at run time; the draft gives candidates only (`PRE:120-129`) |
| Comparison arms: which run, and each one's `runtime_image_digest` (`PRE:172` and the per-arm `UNRESOLVED` lines) | D-32 (budget) and D-10 (API arm); an arm without a digest is excluded with its reason |
| API arm `opus5_subscription` `model_revision` (`PRE:355`) and `inference_config_sha256` (`PRE:361-362`) | **Required field.** One exact model ID and one revision, fixed when the run is approved (KB-F9; register D-10 `executesVia`). The registry value "claude-opus-5 (confirm via lane D probe)" (`PRE:356`) is not an ID. FOUNDER-SET (section 4) |
| `normalization.allowlist_revision` (`PRE:498`), M6 character set (`PRE:550`), Korean prompt sha | Calibration pilot KB-A7, then frozen before confirm |

## 4. FOUNDER-SET, with the question

- **API arm model ID and revision** (KB-F9): which exact model ID and revision does the API arm
  run, if it runs at all? It is fixed at execution approval, never inferred from a name.
- **API arm inference configuration** (`PRE:362`): what maximum output tokens, effort/thinking
  setting, timeout and retry policy does the API arm use? The draft has no number for any of them.
- **Comparison arms** (D-32): which of the thirteen candidates run in T1? (`PRE:172`; Infinity
  Parser2 Pro was excluded for cost on 2026-09-04, `PRE:267`.)
- **SA-1 / SA-2 reading**: keep this seal's reading (adopted), or run the unamended design §5.5
  statistic? Only before the first confirm run.
- **보호기간 만료 marking**: should it be allowed as a KB1 source? (Carried from the D-31 record.)

## 5. Sources

| Path | sha256 |
| --- | --- |
| `UX\KB1-PREREG.json` (the draft) | `cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff` |
| `UX\DECISION-REGISTER-2026-10-17.md` | `5935276d245d230857fa632dcb6555d25756470d37f404fc6c3c00dc71d7c6dc` |
| `UX\DECISION-REGISTER-2026-10-17.json` | `86234c9397cec2d0ac8160276e525943857e7b2ec21e5e3a3b9891cc394120d3` |
| `UX\PHASE1-CRITIC-2026-10-17.md` (D-10 at line 250, P2-27 at 310) | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `UX\KOREAN-BENCHMARK-DESIGN-2026-10-17.md` (KB-F5 at 327, KB-F9 at 331) | `f7fa20afe1e80aa62e1fd753a31b1a84e320299af191c8ec619272dcfa137b7e` |
| `UX\SERVICE-DEFINITION-2026-10-17.md` (G9, line 364) | `c7783dd718713b7564697ce6df7e6abbad9ffc2489624b3ad3705e610b528dee` |
| Foundation `docs/gtm/ICP_DECISION_2026-10-17.md` at `61189cd5` | `5b83a743f26d07e0bd6ba80b1aaa0b08b4c48ed9790010256aae86f3f137ea66` |
| Core `docs/compliance/CORPUS_RIGHTS_POLICY_2026-10-17.md` at `4a583312` | `72aa489e61ceaef1945c6a552ae7adc733ea6ac8cbe9b0ac90ab5cb4cc601dba` |

## 6. The draft, byte for byte

Everything between the two marker lines below, minus the opening and closing fence lines, is the
draft's exact bytes. Its own `"status": "DRAFT_PROPOSED"`, `"sealed": false` and `OPEN` entries are
the draft's text; the header above is what is sealed. Check:

```text
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' KB1-PREREG-SEALED-2026-10-17.md | sed '1d;$d' | sha256sum
# expect cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff
```

<!-- BEGIN VERBATIM DRAFT: UX/KB1-PREREG.json, sha256 cb51fd44b8e9cb5fcd680d8dd75e5f0ae9166934275e4916c212612ce1fe1dff -->
```json
{
  "schema": "tavonel.kb1_prereg.v1",
  "status": "DRAFT_PROPOSED",
  "status_note_ko": "창업자 승인(D-10: KB-F5·KB-F9) 전에는 구속력 없음. 봉인되지 않았다. 이 파일을 근거로 공개 문장을 만들 수 없다.",
  "revision": "kb1-prereg-draft-r1",
  "created": "2026-10-17",
  "created_utc": "2026-10-17T02:30:10.413Z",
  "lane": "P2-27 (한국어 KB-A3), PHASE1-CRITIC-2026-10-17.md §5 lane 표",
  "results": "NONE — 이 파일을 쓴 시점에 KB1 실행·채점은 0건이다. 이 파일의 어떤 숫자도 측정 결과가 아니다",
  "sealed": false,
  "thresholds_status": "proposed — 모든 임계값(n ≥ 50, family ≥ 10, IoU 0.5, CER 0.10 등)은 보정되지 않은 제안값이다. 결과를 본 뒤 같은 confirm 세트에서 낮추지 않는다",
  "design_source": {
    "document": "KOREAN-BENCHMARK-DESIGN-2026-10-17.md",
    "section": "§5.5 사전등록 골격 (§5.1–§5.11을 펼쳐 적음)",
    "format_template": "gdp-20261015/K26-PREREG.json (tavonel.gdp_k26.v1)"
  },
  "question_ko": "고정한 한국어 공개 문서 세트에서, 고정한 조건으로, 범주별로 TAVONEL(그리고 같은 조건의 비교 모델)은 글자·표·읽기 순서·핵심 토큰을 얼마나 원문대로 옮기는가? 측정하지 않은 범주는 무엇인가?",
  "question_scope_ko": "이 벤치마크는 아키텍처가 옳다는 것을 증명하려는 실험이 아니다. 한국어에서 다른 경로가 더 낫다는 결과가 나오면 그 결과가 ADR의 입력이 된다(CLAUDE.md \"The Arena is an experiment to discover the architecture\").",
  "dataset": {
    "name": "KB1 Korean public document set",
    "manifest_sha256": null,
    "manifest_status": "NOT_BUILT — D-31(권리 정책) 승인과 KB-A5(품목 단위 권리 manifest 도구) 이전에는 만들 수 없다",
    "unit": "page",
    "cluster_unit": "document family",
    "family_definition_ko": "같은 기관의 같은 연속 간행물, 같은 문서의 개정판은 하나의 family다. 정확 해시와 근접 중복을 합친 뒤에 분할한다(b19 README \"near-duplicate analysis beyond exact-byte matching\").",
    "categories": {
      "K1": "born-digital 한글 본문 (보도자료·정책자료 PDF)",
      "K2": "한·영·숫자 혼합 (공시 본문·주석, 기술 문서)",
      "K3": "표 (통계표, 재무표, 공문서 병합 셀 표)",
      "K4": "스캔 공문서 (직인, 결재란, 기울기, 저해상도)",
      "K5": "세로쓰기·국한문 혼용 (근대 신문·관보·고서)",
      "K6": "법령·판결 (한자, 특수문자 ①·※·「」·〔〕·㈜, 조항 번호)",
      "KS": "합성 대조군. SYNTHETIC 표시. harness 검증용이며 headline에 넣지 않고 공개 수치로 쓰지 않는다"
    },
    "tiers": {
      "T1": {
        "categories": [
          "K1",
          "K3",
          "K4"
        ],
        "confirm_pages_per_category": 50,
        "calibration_pages_per_category": 10,
        "min_families_per_category_confirm": 10,
        "max_pages_per_family": 5
      },
      "T2": {
        "categories": [
          "K1",
          "K2",
          "K3",
          "K4",
          "K5",
          "K6"
        ],
        "confirm_pages_per_category": 100,
        "calibration_pages_per_category": 20,
        "min_families_per_category_confirm": 20,
        "max_pages_per_family": 5,
        "status": "D-32: 파일럿 실측 뒤 다시 판단"
      }
    },
    "family_count_by_category": {
      "K1": null,
      "K2": null,
      "K3": null,
      "K4": null,
      "K5": null,
      "K6": null
    },
    "family_count_status": "NOT_BUILT — manifest가 생긴 뒤 실제 값을 적는다. 최소 요구는 tiers에 있다",
    "split": {
      "kinds": {
        "calibration": "프롬프트·임계값·정규화 allowlist 조정 허용",
        "confirm": "봉인. 정책 동결 뒤 한 번만 연다"
      },
      "family_overlap_allowed": false,
      "basis": "v5 §8.3 \"Arena 1,000페이지를 prompt tuning에 사용하지 않는다\", \"final Arena case와 document family overlap 금지\" (TAVONEL_MASTERPLAN_v5.0.md:751-759)"
    },
    "split_seed": "tavonel-kb1-split-2026-10-17",
    "split_seed_status": "proposed",
    "calibration_set_sha256": null,
    "confirm_set_sha256": null,
    "rights_by_item": [],
    "rights_item_schema": {
      "item_id": "string",
      "url": "string",
      "kogl_type": "0|1|expired|copyright_act_art7|other",
      "marking_scope": "item|board|site",
      "retrieved_on": "YYYY-MM-DD",
      "sha256": "hex64 of the retrieved file",
      "family_id": "string"
    },
    "rights_rules_ko": [
      "marking_scope가 item이 아닌 페이지는 manifest에 넣지 않는다. board·site 수준 근거는 창업자 승인 전까지 제외(§5.10).",
      "권리 정책은 D-31을 따른다. 권고 기본값: 허용 = 품목 단위 공공누리 0·1유형, 보호기간 만료 표시, 저작권법 제7조 자료. 내부 측정만 = 판결문, DART(법률 확인 뒤). 거절 = AI Hub, NC·ND, licence 없는 HF 세트, D:\\#센서 고객사 제공 자료.",
      "어떤 데이터 허락도 모델 가중치나 제3자 특허에 대해서는 아무것도 정하지 않는다."
    ],
    "excluded_sources_ko": [
      "AI Hub — 약관 제4항(\"학습용으로만\"), 제5항(제3자 열람·제공 금지), 국외 반출 조항 (TERMS-QUOTES-20261017.json)",
      "NC·ND 조건이 붙은 세트, licence 필드가 없는 HF 세트 (HF-KOREAN-DATASETS-20261017.json)",
      "KoOCR-Bench 공개 페이지 — 웹에 이미 있어 학습에 섞였을 수 있으므로 confirm 세트에 쓰지 않는다(§5.11). 저들의 truth/·code/는 licence가 없어 재사용 불가",
      "D:\\#센서 고객사 제공 자료 — 고객 데이터 동의는 창업자 전용(KB-F8 → D-31). 열지 않았다"
    ],
    "not_measured_categories_ko": [
      "HWP/HWPX 원본 (capability UNSUPPORTED, LIVE-CAPABILITIES-20261017.json에 hwp 0회)",
      "손글씨",
      "사진 속 글자 (간판, 영수증 사진)",
      "5 MiB 또는 80쪽을 넘는 문서 (제품 한도 거절. \"제품 한도 거절 slice\"로 건수만 센다)",
      "수식"
    ]
  },
  "arms": [
    {
      "id": "tavonel_foundation_ocr_gpu",
      "role": "subject",
      "model_repo": "0ssol1620-byte/tavonel-saas-foundation:workers/foundation-ocr-gpu (rapidocr general + Korean 2-pass)",
      "model_revision": null,
      "model_revision_status": "CANDIDATE — 봉인 시점에 endpoint가 실제로 돌리는 이미지의 source commit으로 고정한다",
      "model_revision_candidates": {
        "last_receipted_endpoint_source_commit": "aa6b85dd3e3bb5691bd67499cb03aae7a0e3f679",
        "last_receipted_endpoint_source_commit_basis": "F5C-IMAGE-ROLLOUT-RECEIPT.json images.new.sourceCommit (그 lane은 orchestrator brief 값이라고 적었고 재검증하지 않았다)",
        "last_receipted_endpoint_source_commit_on_foundation_main": true,
        "foundation_main_head": "4c80bb3028fb73dc88e929c25baf0bec97bee4e7",
        "drift_ko": "Foundation main의 worker app.py blob d02c5e4b0df7e08276689baa1f184f0a95b0a1e4은 aa6b85dd의 blob 2ecd5baa15bdaeb68b21a6d648663063cffd3920와 다르다(main에 그 뒤 worker 경로 커밋이 있다). endpoint가 지금 어느 이미지를 돌리는지는 이 lane에서 다시 읽지 않았다."
      },
      "runtime_image_digest": null,
      "runtime_image_digest_candidate": "ghcr.io/0ssol1620-byte/tavonel-foundation-ocr-gpu@sha256:8e6f6fa777fd9949745ce67b25d04f0a1aa74dfbf791204baf2b6b16c3931bd8",
      "runtime_image_digest_candidate_basis": "F5C rollback.endpointImageAtEnd, endpoint release v21, 최종 읽기 2026-10-15T23:46:30Z",
      "prompt_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "prompt_note_ko": "OCR 엔진이라 프롬프트가 없다. Arena의 *_no_prompt 관례대로 빈 문자열의 sha256을 쓴다",
      "inference_config_sha256": null,
      "inference_config_status": "CANDIDATE — 봉인 시점에 아래 inference_config_candidate를 canonical JSON(sort_keys, compact, ensure_ascii)으로 직렬화해 sha256을 적는다(ARENA_CONTRACT.md:99-104 방식)",
      "inference_config_candidate": {
        "source": "Foundation 4c80bb30 workers/foundation-ocr-gpu/app.py:29,43,267-288, requirements.txt, materialize_models.py, Dockerfile",
        "render": {
          "library": "pypdfium2==4.30.0",
          "scale": 2
        },
        "engines": {
          "rapidocr": "3.9.2",
          "onnxruntime_gpu": "1.20.2",
          "base_image": "nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04@sha256:8aef630a54bc5c5146ae5ce68e6af5caa3df0fb690bb91544175c91f307e4356"
        },
        "weights_sha256": {
          "PP-OCRv6_det_small.onnx": "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f",
          "PP-OCRv6_rec_small.onnx": "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884",
          "korean_PP-OCRv5_rec_mobile.onnx": "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"
        },
        "korean_pass_options": {
          "use_cls": false
        },
        "prefer_korean_thresholds": {
          "min_korean_hangul": 2,
          "min_korean_confidence": 0.55,
          "han_vs_hangul_confidence_margin": 0.05,
          "clear_latin_line_confidence_margin": 0.02,
          "korean_alnum_retention_ratio": 0.8,
          "korean_confidence_win_margin": 0.05
        },
        "request_mode": "page (one-page PDF per POST)"
      },
      "calibration_status_ko": "UNCALIBRATED — _prefer_korean 값은 한국어 gold 없이 정해졌다. 설계 §0 2항·I-8은 0.55 / +0.05 / 0.8만 적었고 작업 사본(outputs/task12-…/worker/app.py:368-385)을 인용했다. critic V13에 따라 배포 소스 Foundation app.py:267-288을 인용한다. 배포 소스에는 최소 Hangul 2자(:269)와 +0.02 규칙(:286)도 있다. 임계값 조정은 calibration 분할에서만, 제품 반영은 shadow → benchmark → canary 사다리(§5.11)",
      "input_mode_ko": "한 쪽짜리 PDF를 POST하고 서버가 pypdfium2 4.30.0 scale 2.0으로 렌더한다. 서버 렌더는 관측할 수 없으므로, 로컬 재렌더가 다른 arm에 넣는 PNG와 픽셀 단위로 같은지 페이지마다 기록한다(F5 requests.pixelEquivalence 방식). 다른 arm은 같은 로컬 렌더 PNG(input_png_sha256)를 받는다",
      "product_path_note_ko": "이 arm은 OCR endpoint 직접 호출이다. upload → quarantine → CDR → OCR 제품 경로로 돌리면 D-30(평가 tenant·GPU 상한)이 적용되고, 제품 한도(5 MiB·80쪽, 85초 client timeout) 거절 slice가 생긴다",
      "table_structure": "UNSUPPORTED (capability no_table_or_formula_extraction) — M4는 이 arm에서 0으로 평균하지 않고 UNSUPPORTED로 표시한다",
      "determinism": "UNVERIFIED — §5.4 8항 반복 규칙 적용"
    },
    {
      "id": "deepseek_ocr2",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "deepseek-ai/DeepSeek-OCR-2",
      "model_revision": "aaa02f3811945a91062062994c5c4a3f4c0af2b0",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "deepseek_ocr2_grounding_markdown_v1",
      "prompt_sha256": "sha256:00a105b332827a249e76115332aef75dfdf7578e026c25fef1a35662a81efa32",
      "inference_config_sha256": "sha256:75d95fcd48a3493e40b02861327d7075bd9d439e1c24a3b8e0bab5588e474f72",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/deepseek_ocr2/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "glm_ocr",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "zai-org/GLM-OCR",
      "model_revision": "ca5d8b3e287e52589e37c28385d9655ee4372f9d",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "glm_ocr_official_sdk_task_prompts_v1",
      "prompt_sha256": "sha256:3d62ac2e6e72a4064fdbbc5d8b045111133f663fb774e9eb0483933f36cf5e67",
      "inference_config_sha256": "sha256:21a82ad3c1f14ca9d8b94c01d18e66e808e052b685beaf88e169f30958be8c56",
      "inference_config_status": "REGISTRY",
      "licence_field": "mit",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/glm_ocr/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(mit)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "hpd_parsing",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "PaddlePaddle/HPD-Parsing",
      "model_revision": "91de80054c23ab4238e3d7073fa2b83c2a7e301e",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "hpd_parsing_document_parsing_with_fork_v1",
      "prompt_sha256": "sha256:df8124c5dbc24b50ce15a23f84d4b277d6a79179a2522339cbabcb8e3eb9033d",
      "inference_config_sha256": "sha256:d120c42fc0901fbcc1a3340a3eda61c8ff8cfe4370e3ab56c4a9eb99b65c91ab",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/hpd_parsing/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "infinity_parser2_flash",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "infly/Infinity-Parser2-Flash",
      "model_revision": "cfddc4106b0abc4706f05575a164f7dd35d09c46",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "infinity_parser2_flash_doc2json_v1",
      "prompt_sha256": "sha256:a1c4c81e3bce7b2eb6534231962187ed766af7d450867c61fd474a5e897fcb2c",
      "inference_config_sha256": "sha256:c25a2cf807b2d12658f23e0c6e315201ffccf59ab20e88e65f454de321f42fe6",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/infinity_parser2_flash/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "infinity_parser2_pro",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "infly/Infinity-Parser2-Pro",
      "model_revision": "b27d470100514329fc6439aada8f16ccea5f9e2a",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "infinity_parser2_pro_doc2json_v1",
      "prompt_sha256": "sha256:a1c4c81e3bce7b2eb6534231962187ed766af7d450867c61fd474a5e897fcb2c",
      "inference_config_sha256": "sha256:c886a891fd7ad0114741127d7786a0abafa32884cbe9071e253c5eb58079ff87",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/infinity_parser2_pro/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항).",
        "2026-09-04 창업자가 Arena full run에서 비용 때문에 제외했다(FOUNDER_EXCLUDE_INFINITY_2026-09-04.md). KB1 재포함은 창업자 판단."
      ]
    },
    {
      "id": "mineru_pipeline",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "opendatalab/PDF-Extract-Kit-1.0",
      "model_revision": "ed6b654c018d742e65a17671e379c5e6ecc87ec9",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "mineru_pipeline_no_prompt",
      "prompt_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "inference_config_sha256": "sha256:baa12e342a87be9d81748c0c59db0fc9b4d055dbbb7c140cf2a8ab1b9805f481",
      "inference_config_status": "REGISTRY",
      "licence_field": "LicenseRef-MinerU-Open-Source-License",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/mineru_pipeline/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(LicenseRef-MinerU-Open-Source-License)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "mineru_vlm",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "opendatalab/MinerU2.5-Pro-2605-1.2B",
      "model_revision": "bff20d4ae2bf202df9f45284b4d43681555a97ed",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "mineru_vlm_no_prompt",
      "prompt_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "inference_config_sha256": "sha256:ef9f5e60ef5373f03207f2f3a8daf464660b62fc13319b9265a32277d1b5c705",
      "inference_config_status": "REGISTRY",
      "licence_field": "LicenseRef-MinerU-Open-Source-License",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/mineru_vlm/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(LicenseRef-MinerU-Open-Source-License)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "monkeyocrv2_b",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "zenosai/MonkeyOCRv2-B-Parsing",
      "model_revision": "de7a993bd0f39a97b122dac767e82ae04935bce4",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "monkeyocrv2_b_official_pipeline_prompts_v1",
      "prompt_sha256": "sha256:3384d4732fd91113b9f7989e488dba575f65225d745a30b797364e12df47dca4",
      "inference_config_sha256": "sha256:6780ddfde830c6fa003fc143b4a3c244bc19464f31559d7bc13e6125074a41f4",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/monkeyocrv2_b/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "olmocr2",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "allenai/olmOCR-2-7B-1025-FP8",
      "model_revision": "40bd7202494b8264ee17ada08b401b5aab7a9ce1",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "olmocr2_no_anchoring_v4_yaml_v1",
      "prompt_sha256": "sha256:c12f21aca8c6c5599cea6176edd974b7ea6a05cf451497abd6370dd449db3979",
      "inference_config_sha256": "sha256:85e43718ed46a748071c4f11fb88502efcc46f966e5360f8fd1375c9f3a027e2",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/olmocr2/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "opus5_subscription",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "api:claude-opus-5",
      "model_revision": null,
      "model_revision_registry_value": "claude-opus-5 (confirm via lane D probe)",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "NOT_APPLICABLE — hosted API arm. 대신 셀마다 응답의 실제 model ID를 기록한다(§5.4 3항)",
      "prompt_id": "opus5_transcription_v1",
      "prompt_sha256": "sha256:2a8741532324e1fb6be192253eb3a19301a3eb49ef0c8764bf97505382d263ee",
      "inference_config_sha256": null,
      "inference_config_status": "UNRESOLVED — max output tokens, effort/thinking, timeout, retry 정책을 D-10 뒤 숫자로 적고 sha 봉인(K26 same_conditions.token_budget_ko 방식)",
      "licence_field": "proprietary-anthropic-commercial-terms",
      "runtime_identity_file": null,
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(proprietary-anthropic-commercial-terms)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항).",
        "API arm. registry의 revision 값이 확정 ID가 아니다. D-10(KB-F9)에서 정확한 model ID와 revision 하나로 고정하기 전에는 실행할 수 없다. 셀마다 응답 모델을 확인하고 다르면 UNEXPECTED_MODEL(§5.4 3항). 비용은 실행 시점 가격 스냅샷 없이 추정하지 않는다."
      ]
    },
    {
      "id": "ovisocr2",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "ATH-MaaS/OvisOCR2",
      "model_revision": "1fc9221b7823a371d6e97f92d527cc847e24e107",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "ovisocr2_page_markdown_v1",
      "prompt_sha256": "sha256:de9617f877f6110d22adf1a6ba2a96221189dc246fb1fef161e408d37bff5267",
      "inference_config_sha256": "sha256:8a75f05dac58061962ec0a3b2b740d34f75083441987959d5be41e6343dfcd1d",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/ovisocr2/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "paddleocr_vl_1_6",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "PaddlePaddle/PaddleOCR-VL-1.6",
      "model_revision": "c5630abae1d940eafe0697512a0325494b02ab42",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "paddleocr_vl_1_6_pipeline_internal",
      "prompt_sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "inference_config_sha256": "sha256:9a44c6a46de0640999f9045df5048c867fc6f51c7170e74fa757bf78f778d05e",
      "inference_config_status": "REGISTRY",
      "licence_field": "apache-2.0",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/paddleocr_vl_1_6/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(apache-2.0)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    },
    {
      "id": "unlimited_ocr",
      "role": "comparison_candidate",
      "selection_status": "PENDING — 어느 arm을 돌릴지는 D-32(예산)와 D-10(API arm ID)이 정한다",
      "model_repo": "baidu/Unlimited-OCR",
      "model_revision": "07dea832e22aefee32ad281d4b80551282e1c168",
      "runtime_image_digest": null,
      "runtime_image_digest_status": "UNRESOLVED — registry container_digest null (lane F resolves the immutable image digest during the build phase). 봉인 전에 빌드 영수증의 digest로 채우지 못하면 이 arm은 제외한다",
      "prompt_id": "unlimited_ocr_document_parsing_v1",
      "prompt_sha256": "sha256:a210f5b991d35d2a9a7d6c6160f54165c0ae96e02fbfdd1bc38400232021c303",
      "inference_config_sha256": "sha256:4da41a17aed5e7d0ef09ecc90933ffa5b2299367f724fcc0b7b4f224bff94912",
      "inference_config_status": "REGISTRY",
      "licence_field": "mit",
      "runtime_identity_file": "research/model_arena_20260903/runtimes/unlimited_ocr/runtime.json",
      "notes_ko": [
        "이 목록에 있다는 것은 한국어 능력에 대한 어떤 주장도 아니다. 능력은 KB1 측정으로만 정해진다(이름·vendor로 추정 금지).",
        "licence 필드(mit)는 가중치/서비스 조건 하나다. 코드·가중치·데이터·API 약관은 서로 다른 네 licence이고 특허 FTO는 어느 것도 정하지 않는다.",
        "Arena 프롬프트는 한국어 전용이 아니다. 한국어 전용 프롬프트를 만들면 calibration에서만 다듬고 confirm 전 sha 동결(§5.4 5항)."
      ]
    }
  ],
  "same_conditions": [
    {
      "id": 1,
      "rule_ko": "작업 식별자 inference_job_id = canonical JSON {campaign_id, benchmark_revision, sample_id, source_sha256, model_repo, model_revision, runtime_image_digest, prompt_sha256, inference_config_sha256}의 sha256. 같은 식별자에 SUCCESS 영수증이 있으면 다시 실행하지 않는다",
      "source": "ARENA_CONTRACT.md:99-104"
    },
    {
      "id": 2,
      "rule_ko": "모델 고정: model_revision은 공식 API에서 확인한 정확한 commit sha, base_image는 digest, pip는 ==, 가중치는 revision과 sha256 검사. 모델의 공식 추론 경로와 공식 프롬프트",
      "source": "ARENA_CONTRACT.md:312-334"
    },
    {
      "id": 3,
      "rule_ko": "API 모델: 정확한 model ID와 revision 하나로 고정. 셀마다 응답의 실제 모델을 확인하고 다르면 UNEXPECTED_MODEL로 기록해 점수에서 빼고 격리 후 다시 실행. 이름이나 vendor로 한국어 능력을 추정하지 않는다",
      "source": "K26-PREREG.json same_conditions.model_ko"
    },
    {
      "id": 4,
      "rule_ko": "입력 고정: 모든 arm에 같은 렌더(pypdfium2 4.30.0, scale 2.0)의 같은 PNG. 페이지마다 input_png_sha256 기록. TAVONEL arm은 위 input_mode_ko의 픽셀 동치 기록으로 대신한다",
      "source": "F5 sameCondition.same, source_manifest.jsonl 필드"
    },
    {
      "id": 5,
      "rule_ko": "프롬프트·스키마: prompt_registry/에 sha256 기록. 한국어 전용 프롬프트는 calibration에서만 다듬고 confirm 전에 sha 동결",
      "source": "ARENA_CONTRACT.md:179-183"
    },
    {
      "id": 6,
      "rule_ko": "평가기 고정: {repository, main_pin, dataset_revision, dataset_manifest_sha256, license} 레코드, frozen: true 이후 변경 금지. 점수 provenance에 evaluator_revision과 normalization_revision. 평가기 실패는 {\"status\": \"EVALUATOR_BLOCKED\"}이고 0점이 아니다. KB1 harness도 같은 레코드로 등록",
      "source": "ARENA_CONTRACT.md:171-177, :201-208"
    },
    {
      "id": 7,
      "rule_ko": "가격 스냅샷: pod마다 price_snapshot_sha256과 billed seconds. API는 실행 시점 가격표 스냅샷을 해시와 함께",
      "source": "ARENA_CONTRACT.md:745-750"
    },
    {
      "id": 8,
      "rule_ko": "반복: 결정성이 확인되지 않은 arm은 confirm 페이지의 10%를 3회 실행해 분산 기록. 평가기 분산 σ=0은 평가기의 성질이며 파이프라인 분산 0을 가정하지 않는다",
      "source": "docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md:176-189"
    }
  ],
  "evaluators": {
    "kb1_harness": {
      "status": "NOT_BUILT (KB-A1)",
      "record_required": [
        "repository",
        "main_pin",
        "dataset_revision",
        "dataset_manifest_sha256",
        "license",
        "frozen"
      ]
    },
    "omnidocbench_cross_check": {
      "repository": "https://github.com/opendatalab/OmniDocBench.git",
      "main_pin": "193627ae9e97d89188468ed1ee3b7a856ff76044",
      "licence": "Apache-2.0 (평가기 코드 licence. OmniDocBench 데이터셋 licence와 별개이며 KB1은 그 데이터셋을 쓰지 않는다)",
      "arena_record_frozen": false,
      "role_ko": "교차 검증 전용(M4 TEDS, M5 reading order edit). clean_string이 \\w가 아닌 문자를 지우므로(①·※·「」·㈜ 소실) M1·M6 주 지표로 쓰지 않는다. KB-A4 어댑터가 KS에서 이 차이를 테스트로 고정한 뒤에만 쓴다"
    }
  },
  "normalization": {
    "unicode": "NFC",
    "whitespace": "removed_for_M1 (M2는 공백 위치를 그대로 잰다)",
    "allowlist_revision": null,
    "allowlist_status": "NOT_FROZEN — calibration 분할에서 정하고 confirm 전에 동결. 근거 후보: tests/unit/test_document_normalization.py:36-56 (한국어 줄 결합, 하이픈 보호)",
    "compat_ideograph": "folded_primary_raw_secondary (NFC는 호환 한자 U+F900–FAFF를 통합 한자로 접는다. NFC 기준을 주 지표, 원래 코드포인트 기준을 보조 지표로 함께 보고)",
    "nfkc_secondary_report": true,
    "nfkc_note_ko": "KoOCR-Bench는 NFKC를 쓴다. NFC와 NFKC CER을 함께 보고하되 우리 주 지표는 NFC다",
    "pua_rule_ko": "PUA(U+E000–F8FF) 코드포인트가 하나라도 있는 텍스트 레이어 초안은 버리고 사람이 전사한다"
  },
  "metrics": {
    "primary": {
      "id": "M1",
      "name_ko": "CER (글자 오류율)",
      "definition_ko": "공백을 지운 NFC 문자열의 Levenshtein 거리 / gold 글자 수",
      "aggregation": "micro per category (전체 편집 수 / 전체 gold 글자 수)",
      "page_distribution": "p50, p90, \"CER > 0.10인 페이지 수 / 전체 페이지 수\"",
      "rules_ko": [
        "출력이 없는 페이지는 CER 1.0으로 분모에 남긴다",
        "반복 폭주는 페이지 단위에서 1.0으로 자른다",
        "\"1−CER\"을 \"정확도\"라고 부르지 않는다"
      ]
    },
    "secondary": [
      {
        "id": "M1-s",
        "name_ko": "script별 CER",
        "definition_ko": "Hangul / Latin / 숫자 / 한자 / 기호 각각의 CER (K2에서 _prefer_korean이 어느 script를 망치는지)"
      },
      {
        "id": "M2",
        "name_ko": "띄어쓰기 F1",
        "definition_ko": "gold 공백 위치 대비 공백 삽입·누락의 F1"
      },
      {
        "id": "M3",
        "name_ko": "핵심 토큰 충실도",
        "definition_ko": "한국어 숫자 표기를 아는 토크나이저로 뽑은 토큰 class별 정확 일치 recall/precision. class: 숫자+단위, 한국식 날짜, 조항, 금액 기호, 퍼센트+조사, 사업자번호·전화번호",
        "rule_ko": "akc_quality.numeric은 쓰지 않는다(§2.3: 1,000원 → 1, 금 1,234,000원정 → 1,234). 토크나이저에 §2.3 사례를 실패 테스트로 둔다"
      },
      {
        "id": "M4",
        "name_ko": "표 TEDS / TEDS-struct",
        "definition_ko": "OmniDocBench pin 193627ae의 TEDS. 표를 내지 못하면 0점으로 분모에 남긴다",
        "tavonel_ko": "UNSUPPORTED (capability no_table_or_formula_extraction)로 표시하고 0으로 평균하지 않는다. 대신 표 영역 안 텍스트의 M1을 잰다"
      },
      {
        "id": "M5",
        "name_ko": "읽기 순서",
        "definition_ko": "gold 블록 순서와 출력 순서의 정규화 Kendall tau 거리. 세로쓰기는 오른쪽 열에서 왼쪽 열, 각 열은 위에서 아래"
      },
      {
        "id": "M6",
        "name_ko": "한자·특수문자 recall",
        "definition_ko": "사전등록한 문자 집합(한자 U+4E00–9FFF, U+3400–4DBF, 호환 한자 U+F900–FAFF; ①–⑳, ※, 「」, 『』, 〔〕, ㈜, ·, ․, ○, □)의 글자별 recall. 한자를 한글 독음으로 바꾼 경우는 오류",
        "character_set_status": "NOT_FROZEN — calibration 전 목록 확정 후 동결"
      },
      {
        "id": "M7",
        "name_ko": "직인 처리 (K4)",
        "definition_ko": "(a) 직인에 가려진 본문 글자의 CER, (b) 직인 글자가 본문에 섞인 비율(직인 글자 수 대비), (c) 결재란 표 인식 여부",
        "rule_ko": "합성 직인에는 실제 기관명을 쓰지 않는다. \"견본\" 표시와 가상의 기관명만"
      },
      {
        "id": "M8",
        "name_ko": "환각 삽입률",
        "definition_ko": "gold에 없는 글자 삽입 수 / gold 글자 수. 외국 문자(가나, 키릴 등) 삽입은 따로 센다. 가중 벌점 없음"
      },
      {
        "id": "M9",
        "name_ko": "근거 위치 충실도",
        "definition_ko": "gold 줄 가운데 같은 텍스트를 담은 출력 region과 IoU ≥ 0.5로 겹치는 줄의 비율. K1과 K4 하위집합에서만",
        "iou_threshold": 0.5,
        "iou_status": "proposed, uncalibrated"
      }
    ],
    "operational": {
      "completion": "출력이 있는 페이지 수 / 전체 페이지 수 — 정확도가 아니다(CLAUDE.md Evidence)",
      "latency": "p50 / p95",
      "cost": "영수증 기반 (가격 스냅샷 sha256 필수)"
    }
  },
  "statistics": {
    "ci": "family-cluster bootstrap 95% percentile",
    "resamples": 10000,
    "seed": "tavonel-kb1-bootstrap-2026-10-17",
    "seed_status": "proposed",
    "paired_comparison_design": "paired cluster bootstrap of per-page CER difference + exact sign test (설계 §5.5 원문)",
    "proposed_amendments": [
      {
        "id": "SA-1",
        "status": "proposed — D-10이 채택 여부를 정한다",
        "text_ko": "쌍 비교의 통계량을 주 지표와 맞춘다: Δ = (비교 arm micro CER) − (TAVONEL micro CER). 각 bootstrap 표본에서 family를 복원 추출하고 두 arm의 micro CER을 같은 표본에서 다시 계산한다(paired family-cluster bootstrap). exact sign test는 페이지가 아니라 family 단위(family별 micro CER 차이의 부호, 차이 0인 family는 제외하고 그 수를 보고)로 한다. 페이지별 CER 차이는 기술 통계로만 보고한다",
        "reason_ko": "설계 원문은 주 지표가 micro CER인데 쌍 비교는 페이지별 CER 차이라서 서로 다른 양을 검정한다. 또 같은 family 안의 페이지는 독립이 아니므로 페이지 단위 sign test는 p값을 과소 추정한다"
      },
      {
        "id": "SA-2",
        "status": "proposed — D-10이 채택 여부를 정한다",
        "text_ko": "다중 비교 보정: 사전등록한 (비교 arm × 범주) 쌍 전체에 Holm 보정을 적용하고 family-wise α = 0.05로 둔다. 우열 문장은 Holm 보정 sign test p < 0.05이고 동시에 Δ의 95% CI가 0을 포함하지 않을 때만 쓴다",
        "reason_ko": "T1에서 비교 후보 13개 × 범주 3개면 쌍이 39개다. 보정 없이 쌍마다 95% CI만 보면 우연한 우열 문장이 나올 확률이 커진다. D-10은 블라인드 비교에 Holm α 0.05를 이미 권고했다"
      }
    ],
    "precision_reference_ko": "페이지 단위 이진 비율의 최악 95% CI 반폭 1.96·√(0.25/n): n=50이면 ±13.9%p, n=100이면 ±9.8%p. family 군집 효과가 있으면 실제 CI는 더 넓다. T1은 범주별로 대략의 수준까지만 말할 수 있다(설계 §5.8)",
    "no_cherry_pick_ko": "여러 지표 중 좋은 것만 고르지 않는다. 주 지표 외 지표는 기술 통계로 모두 게시한다"
  },
  "publishable_rule": {
    "status": "proposed",
    "all_must_hold": true,
    "criteria_ko": [
      "이 사전등록의 승인·봉인 revision sha256이 첫 confirm 실행보다 이른 UTC 시각으로 기록되어 있다",
      "범주별 confirm n ≥ 50쪽 그리고 family ≥ 10 (family당 5쪽 이하)",
      "모든 (arm × confirm 페이지) 셀이 존재한다. 실패·시간 초과·제품 한도 거절도 셀로 남는다",
      "평가기 pin이 frozen: true로 동결되어 있다",
      "주석자 간 CER(판정 전, gold 잡음 하한)을 범주별로 함께 보고한다. 시스템 CER이 이 값보다 낮으면 \"측정 한계 이하\"로 표시하고 우열 문장을 쓰지 않는다",
      "manifest의 모든 페이지가 품목 단위(marking_scope = item) 권리 근거를 가진다",
      "모든 수치가 docs/evidence/artifacts/의 sha256 receipt에 바인딩된다(claims pack 생성기 경유)"
    ]
  },
  "comparison_rule": {
    "status": "proposed",
    "text_ko": "동일 조건(same_conditions 1–8 전부) + 쌍 차이 95% CI가 0을 포함하지 않을 때만 우열 문장. CI가 0을 포함하면 \"차이를 확인하지 못했습니다\". SA-2가 채택되면 Holm 조건을 더한다",
    "not_allowed_ko": [
      "다른 벤치마크의 vendor 점수와 나란히 놓기",
      "KoOCR-Bench 공개 수치를 재현했다고 주장하거나 우리 결과와 같은 표에 섞기",
      "범주 합산 headline"
    ]
  },
  "denominator_rules_ko": [
    "모든 비율에 \"분자 / 분모\"를 함께 적는다. 예: \"CER > 0.10인 페이지 7 / 100\"(형식 예시이며 측정값이 아니다)",
    "분모는 confirm 세트의 전체 페이지다. 실패, 시간 초과, 제품 한도 거절은 분모에서 빼지 않는다",
    "운영 실패(pod 사망, rate limit)는 격리 후 다시 실행하고 그 기록도 남긴다. 의미 실패(모델이 틀린 경우)는 다시 실행하지 않는다",
    "범주 평균을 합쳐 하나의 headline으로 만들지 않는다"
  ],
  "gold_protocol": {
    "source": "research/b19_holdout_gold/protocol.py:247-282 (_validate_label_record)",
    "rules_ko": [
      "주석은 정확히 2건, 서로 다른 reviewer_id, independent: true, saw_peer_label: false, evidence_refs 필수",
      "두 주석이 다른 글자는 주석자가 아닌 판정자가 원본 픽셀을 보고 정한다. 판정에도 evidence_refs",
      "gold를 봉인하고 추론 쪽에는 case, family, source identity, source hash만 담긴 blind manifest만 준다. 예측을 잠근 뒤에 gold를 연다",
      "born-digital 텍스트 레이어 초안은 사람 2명의 검증을 거쳐야 gold가 된다. 두 엔진의 동일 오답을 gold로 승격하지 않는다",
      "AI-judge 금지: 정답과 우열 판정은 사람이 한다. 모델 출력은 초안 후보로만",
      "주석자는 한국어 모국어 화자. K5·K6 한자 판독에는 한문 판독 가능자. 누가 할지는 D-32"
    ]
  },
  "leakage_controls_ko": [
    "_prefer_korean 임계값, 한국어 프롬프트, 정규화 allowlist, M6 문자 집합은 calibration 분할에서만 조정한다. confirm은 정책 동결 뒤 한 번만 연다",
    "임계값을 바꾼 버전은 shadow로만 돌리고 confirm에서 이전 버전보다 나쁘지 않을 때만 canary로 간다(Protected Core 사다리)",
    "KoOCR-Bench 공개 페이지는 confirm 세트에 쓰지 않는다"
  ],
  "fail_closed": [
    "측정하지 않은 범주는 \"측정 안 함\"으로 게시한다. 빈칸으로 두거나 생략하지 않는다",
    "게시 기준(n, family 수)에 못 미친 범주는 \"표본 부족 — 게시하지 않음\"으로 표시한다",
    "평가기가 실패하면 EVALUATOR_BLOCKED로 표시하고 0점이나 평균에 넣지 않는다",
    "capability가 지원하지 않는 지표(TAVONEL의 표 구조 등)는 UNSUPPORTED (capability)로 표시한다",
    "품목 단위 권리를 확인하지 못한 페이지는 manifest에 넣지 않는다. 권리 근거가 board·site 수준이면 창업자 승인 전까지 제외한다",
    "사전등록 sha가 결과보다 늦은 시각이면 그 실행 결과는 공개 문장의 근거가 될 수 없다",
    "이 파일에서 null인 필드(manifest_sha256, calibration/confirm_set_sha256, model_revision, runtime_image_digest, inference_config_sha256, allowlist_revision)가 하나라도 남아 있으면 봉인할 수 없다. null인 arm은 실행하지 않고 제외 사유를 기록한다"
  ],
  "public_statements": {
    "status_ko": "창업자 전용 문구 또는 2026-10-15 위임 규칙(모든 수치가 docs/evidence/ receipt에 묶인 문구). 아래는 설계 §5.9의 제안 원문이며 이 파일은 아무것도 게시하지 않는다",
    "location_ko": "D-33 권고: /ko 첫 화면이 아니라 /sources에 게시한다(critic §3.4: /ko는 hedge가 금지된 첫인상 표면, copy-trust-guard.test.ts:52-54)",
    "states": [
      {
        "state": "S0",
        "allowed_ko": "\"한국어 문서 품질은 아직 측정하지 않았습니다. 한국어 PDF는 BEST_EFFORT로 처리됩니다. HWP/HWPX는 지원하지 않습니다.\"",
        "barred_ko": "\"한국어 지원\", \"한국어에 강함\""
      },
      {
        "state": "S1",
        "allowed_ko": "S0 그대로. 내부 보고서만 작성한다",
        "barred_ko": "내부 수치를 공개 카피에 인용"
      },
      {
        "state": "S2",
        "allowed_ko": "\"[KB1 rev, 실행일] 공개 한국어 [범주] 문서 n쪽(문서 계열 m개)에서 TAVONEL의 글자 오류율(CER)은 x%(95% CI a–b)였습니다. 측정하지 않은 범주: [목록].\" 영수증 링크를 붙인다",
        "barred_ko": "범주 합산 headline, \"정확도 (1−CER)%\", 측정하지 않은 범주를 빼고 말하기"
      },
      {
        "state": "S3",
        "allowed_ko": "\"같은 조건(모델 ID·revision·프롬프트·렌더 고정)에서 [범주] CER은 TAVONEL x%, [model_repo@revision] y%였습니다(쌍 차이 95% CI c–d).\" CI가 0을 포함하면 \"차이를 확인하지 못했습니다\"",
        "barred_ko": "다른 벤치마크의 vendor 점수와 나란히 놓기"
      },
      {
        "state": "competitor_public",
        "allowed_ko": "\"schift-io가 KoOCR-Bench v1.2에서 공개한 수치(2026-10-05)\" 형식으로 인용만",
        "barred_ko": "재현했다고 주장, 우리 결과와 같은 표에 섞기"
      }
    ]
  },
  "sizing_reference": {
    "status": "PLANNING_ESTIMATE_NOT_A_RESULT",
    "receipt": "korean-benchmark-receipts/KO-BENCH-SIZING-20261017.json",
    "t1_ko": "K1·K3·K4 × (confirm 50 + calibration 10) = 180쪽, 사람 약 192시간(주석 분/쪽은 영수증 없는 가정), TAVONEL OCR 3회 상한 USD 0.64, Arena 1개 모델 USD 1.95, 13개 USD 25.40",
    "api_cost_ko": "API arm 비용은 실행 시점의 가격 스냅샷 없이 추정하지 않는다"
  },
  "seal_procedure_ko": [
    "1. 창업자가 blocked_on의 결정(D-02, D-10, D-31, D-32)을 내린다",
    "2. KB-A5 도구로 품목 단위 권리 manifest를 만들고 manifest_sha256, family_count_by_category, rights_by_item을 채운다",
    "3. split_seed로 family 단위 분할을 만들고 calibration_set_sha256, confirm_set_sha256을 채운다",
    "4. 실행할 arm을 정하고 각 arm의 model_revision, runtime_image_digest, prompt_sha256, inference_config_sha256을 채운다. 채우지 못한 arm은 제외 사유와 함께 뺀다",
    "5. calibration 파일럿(KB-A7) 뒤 allowlist_revision, M6 문자 집합, 한국어 프롬프트 sha를 동결한다",
    "6. status를 FOUNDER_APPROVED_SEALED로 바꾼 새 revision을 쓰고 그 sha256과 UTC 시각을 첫 confirm 실행 전에 receipt로 남긴다",
    "7. 봉인 뒤 기준을 바꾸려면 새 사전등록 버전과 새 holdout이 필요하다(b19 README \"failures require a new policy version and a fresh untouched holdout\")"
  ],
  "blocked_on": [
    {
      "id": "D-02",
      "kind": "founder_decision",
      "design_ids": [
        "KB-F1"
      ],
      "question_ko": "설계 대상 ICP와 한국어 벤치마크 착수",
      "recommended_default_ko": "안 1: 자주 바뀌는 문서 묶음을 가진 지식 소유 팀, 한국 조직 포함, 파일럿 구매. KB1 T1(K1·K3·K4)부터 시작한다",
      "blocks_ko": "벤치마크 착수 자체와 범주 tier 선택",
      "status": "OPEN"
    },
    {
      "id": "D-10",
      "kind": "founder_decision",
      "design_ids": [
        "KB-F5",
        "KB-F9"
      ],
      "question_ko": "사전 등록 임계값 승인과 봉인, API arm의 정확한 model ID",
      "recommended_default_ko": "초안대로 승인하고 실행 전에 봉인한다. KB1 n ≥ 50·family ≥ 10, API arm은 model ID와 revision을 하나로 고정",
      "blocks_ko": "publishable_rule, comparison_rule, statistics.proposed_amendments(SA-1, SA-2), public_statements 문장표, API arm",
      "status": "OPEN"
    },
    {
      "id": "D-31",
      "kind": "founder_decision",
      "design_ids": [
        "KB-F2",
        "KB-F8"
      ],
      "question_ko": "코퍼스 권리 정책",
      "recommended_default_ko": "허용: 품목 단위 공공누리 0·1유형, 저작권법 제7조 자료, 미국 연방 저작물, ParseBench(NOTICE). 내부 측정만: OmniDocBench, 판결문, DART(법률 확인 뒤). 거절: AI Hub, NC·ND, licence 없는 HF 세트, D:\\#센서 고객사 제공 자료. 고객 문서는 동의 절차 뒤에만",
      "blocks_ko": "dataset 전체(manifest, rights_by_item, 분할)",
      "status": "OPEN"
    },
    {
      "id": "D-32",
      "kind": "founder_decision",
      "design_ids": [
        "KB-F3",
        "KB-F4"
      ],
      "question_ko": "KB1 T1 예산과 주석자",
      "recommended_default_ko": "주석 약 192시간(추정)을 승인한다. 모국어 화자 2명 + 독립 판정자 1명, GPU 상한 USD 50. T2는 파일럿 실측 뒤 다시 판단한다",
      "blocks_ko": "gold 생성, 비교 arm 선택(실행 비용), 파일럿",
      "status": "OPEN"
    },
    {
      "id": "KB-A1",
      "kind": "agent_build",
      "question_ko": "오프라인 결정적 채점 harness (M1–M9, NFC, 한국어 숫자 토크나이저, cluster bootstrap, EVALUATOR_BLOCKED)",
      "blocks_ko": "evaluators.kb1_harness 레코드와 모든 지표 계산",
      "status": "NOT_BUILT — Core lane worktree와 Python이 필요해 phase 2에서 제외(critic §5 5항)"
    },
    {
      "id": "KB-A5",
      "kind": "agent_build",
      "question_ko": "품목 단위 권리 manifest 도구",
      "blocks_ko": "dataset.manifest_sha256, rights_by_item",
      "status": "NOT_BUILT — phase 2에서 제외(critic §5 5항)"
    },
    {
      "id": "KB-A4",
      "kind": "agent_build",
      "question_ko": "OmniDocBench pin 어댑터",
      "blocks_ko": "evaluators.omnidocbench_cross_check (교차 검증만; 주 지표는 막지 않는다)",
      "status": "NOT_BUILT — phase 2에서 제외(critic §5 5항)"
    }
  ],
  "related_decisions_not_blocking_draft": [
    {
      "id": "D-30",
      "note_ko": "TAVONEL arm을 OCR endpoint 직접 호출이 아니라 제품 경로(upload → CDR → OCR)로 돌릴 때만 적용(평가 tenant와 GPU 상한)"
    },
    {
      "id": "D-33",
      "design_ids": [
        "KB-F6",
        "KB-F7"
      ],
      "note_ko": "S0 문장의 게시 위치(/sources)와 HWP 표기. 실행이 아니라 게시를 막는다"
    }
  ],
  "critic_findings_applied": [
    {
      "id": "V13",
      "applied_ko": "TAVONEL arm의 _prefer_korean 인용을 작업 사본에서 배포 소스 Foundation workers/foundation-ocr-gpu/app.py:267-288로 바꿨다. 설계가 빠뜨린 :269(최소 Hangul 2자)와 :286(+0.02)도 적었다"
    },
    {
      "id": "V12",
      "applied_ko": "Arena 5,132쪽 중 한국어 1쪽(critic이 확인) — 기존 Arena 결과로는 한국어 주장을 할 수 없다는 전제를 유지했다"
    },
    {
      "id": "§3.4 KB-F6",
      "applied_ko": "public_statements.location_ko를 /sources로 적었다(D-33)"
    },
    {
      "id": "lane P2-27",
      "applied_ko": "blocked_on을 critic의 결정 번호(D-02·D-10·D-31·D-32)로 적고 설계의 KB-F1–F5(+F8, F9)를 design_ids로 연결했다. 파일 위치는 설계 §9의 research/kb1_korean_bench/가 아니라 receipts 폴더다"
    }
  ],
  "deviations_from_design_ko": [
    "파일 위치: 설계 §9 KB-A3는 research/kb1_korean_bench/를 적었다. phase 2 lane P2-27은 Core 저장소를 건드리지 않으므로 receipts 폴더에 둔다",
    "blocked_on: 설계는 KB-F1–F5, lane 수락 기준은 D-02·D-10·D-31·D-32다. 둘 다 적었다(design_ids). 에이전트 의존(KB-A1·A4·A5)도 kind: agent_build로 함께 적었다",
    "statistics: 원문 쌍 비교를 보존하고 SA-1(통계량·검정 단위), SA-2(Holm)를 제안 수정으로 따로 적었다. 채택은 D-10",
    "same_conditions 4항: TAVONEL arm은 PNG가 아니라 한 쪽 PDF를 받으므로(F5) 픽셀 동치 기록으로 대신한다고 적었다",
    "arms: 설계는 비교 arm을 특정하지 않았다. Arena model_registry.json의 13개를 후보로만 적었고 선택은 D-32·D-10이다"
  ],
  "not_claimable_ko": [
    "이 초안으로는 어떤 한국어 품질 문장도 쓸 수 없다(S0만 가능)",
    "Arena의 기존 수치로 한국어 품질을 말할 수 없다(한국어 1 / 5,132쪽)",
    "\"업계 1위\", \"한국어에 강함\", \"한국어 지원\" 같은 문장은 이 사전등록으로 주장할 수 없다"
  ],
  "inputs": {
    "core_head": "d5eabfa8789a88fe0a4f2b042870cb4e601d39cf",
    "foundation_head": "4c80bb3028fb73dc88e929c25baf0bec97bee4e7",
    "files": [
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\KOREAN-BENCHMARK-DESIGN-2026-10-17.md",
        "sha256": "f7fa20afe1e80aa62e1fd753a31b1a84e320299af191c8ec619272dcfa137b7e",
        "role": "design source (§5.5)"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\PHASE1-CRITIC-2026-10-17.md",
        "sha256": "667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81",
        "role": "lane P2-27, decisions D-02/D-10/D-31/D-32, V12/V13"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\PHASE2-LANES.json",
        "sha256": "205d979cc0e55f0bb3ab34baafb5a5485695e3f733b6b117cd6f2691d8bb6800",
        "role": "lane acceptance"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\korean-benchmark-receipts\\KO-BENCH-SIZING-20261017.json",
        "sha256": "af4850f3ea6b8d44f54b0f2a91bf8f9a1b455817683cebfd62bec42e66aa537d"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\korean-benchmark-receipts\\LIVE-CAPABILITIES-20261017.json",
        "sha256": "e1e5a4207fe2ec2a823fff74e5c67c1cbf4cc23ea6548c7db9955b3e428ef7a5"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\korean-benchmark-receipts\\TERMS-QUOTES-20261017.json",
        "sha256": "2f29a94901aa959261978be79c50a945deedf8983851fe81d24c62240acb5e7e"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\ux-program-20261017\\korean-benchmark-receipts\\HF-KOREAN-DATASETS-20261017.json",
        "sha256": "ea9569865aeecd5333d1072accc46b8e31f7d3ef7260039d56a638140f3af770"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\resume-20261015\\gdp-20261015\\K26-PREREG.json",
        "sha256": "f70d51c41d6b7f6580f172082d4b91d53dccfe0881ecd7874c54028aeab79b2f",
        "role": "format template"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\resume-20261015\\gdp-20261015\\F5-GPU-OCR-RECEIPT.json",
        "sha256": "142f1e9045a1783ac1a3aaae3cc4461f9e26569b71f96d9544036d2b6f915aaa"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\outputs\\tavonel-research-replan-20261013\\resume-20261015\\gdp-20261015\\F5C-IMAGE-ROLLOUT-RECEIPT.json",
        "sha256": "817db99ec9044af069888d323db9d687d93e318f7c7f39ae01ce87d3f8481399"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\ARENA_CONTRACT.md",
        "sha256": "81489e4e482b872f577b124f47ad1e144f2a3ad36ae872389c495148062d69de",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\model_registry.json",
        "sha256": "83152ef92e2792a7ab3b2ef25fa9774115adfea2ebcd45363f7207764f8ee693",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\evaluator_registry.json",
        "sha256": "668eaa0fb6fc7f823ac88cb20b692dc4d45a2c114fd4d7a6e0f5457b454a380b",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\prompt_registry\\sha256.json",
        "sha256": "137525f09f0d89d8d7998889d63066f2de0f7b56150d989ecaad9687930afb10",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\FOUNDER_EXCLUDE_INFINITY_2026-09-04.md",
        "sha256": "b778c8168e3c70cbadb14fe47dcb3744b4115d80fdbf1ada3a0334b72b0df131",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\b19_holdout_gold\\protocol.py",
        "sha256": "f7bd2afb569ef18495bc2dd42eec661c6de97ffbcee6163bcf4ab9855f992698",
        "git_state": "untracked"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\docs\\north-star\\TAVONEL_MASTERPLAN_v5.0.md",
        "sha256": "35e6bcec1ed5bab30b86478d8d44e20e66d71adb1bcf9f921804cf99f06b19b7",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\handoff-1002\\fnd-UX\\workers\\foundation-ocr-gpu\\app.py",
        "sha256": "3b0263ca5a5902602b78d1b50d9e786e2059024781cf12f617d11556ab096101",
        "git_state": "tracked_clean",
        "git_blob_at_head": "d02c5e4b0df7e08276689baa1f184f0a95b0a1e4"
      },
      {
        "path": "D:\\CodexProjects\\handoff-1002\\fnd-UX\\workers\\foundation-ocr-gpu\\requirements.txt",
        "sha256": "8486e4dfe1195fdf1497ede1df2cd06f5ab3589579573cb7e68b60f640ce402a",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\handoff-1002\\fnd-UX\\workers\\foundation-ocr-gpu\\materialize_models.py",
        "sha256": "f1c1ee1129812bc6feee861ee76fbb53c9faff43db7f0c57c29ba788d7d1225d",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\handoff-1002\\fnd-UX\\workers\\foundation-ocr-gpu\\Dockerfile",
        "sha256": "8d217aaaff34eab8625f60db7c59a0a8419d136ebabc3222c8264826343948cf",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\deepseek_ocr2\\runtime.json",
        "sha256": "05ca84b19a51b60837bcec88fc53057e39b2b23cbaf1c12a1994999e376781a4",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\glm_ocr\\runtime.json",
        "sha256": "4abaad93ad994588cdc3087b32fd8628aa2f468073bfb13549c5623cfe3ef7fb",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\hpd_parsing\\runtime.json",
        "sha256": "e86f89b3c4afa0038b2e9d919a13fc5e6dbc16db5400354035231da139e72da8",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\infinity_parser2_flash\\runtime.json",
        "sha256": "12b5a4ca39a3dfa0dd251dc663d123ce2016cef18d637f42fafafd39da10a223",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\infinity_parser2_pro\\runtime.json",
        "sha256": "a493f877023dedba96ed7cbc3c1aada058d1f788171bb889b2e9f7a37c66c230",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\mineru_pipeline\\runtime.json",
        "sha256": "1a06198fbf242b1dd148874944acd94ee7698e61637c10d845bbaf25a741aa4b",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\mineru_vlm\\runtime.json",
        "sha256": "7dbd9a12e04563b9cb8ca2a5551eddabb24535aee8e1404fc60c3ca5e698523b",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\monkeyocrv2_b\\runtime.json",
        "sha256": "30882fb646ec348ac64b2a5b00baab8db9b6f6a241038de247f8833137c866dd",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\olmocr2\\runtime.json",
        "sha256": "50b932929160be7dbbe0133ae8be6e6444209690d24c7b4ab11b71317ba81f41",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\ovisocr2\\runtime.json",
        "sha256": "e37d5c9919e6deb47db85c50f0547646c516f18a05f1782fbcbee6e54bbe2fcd",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\paddleocr_vl_1_6\\runtime.json",
        "sha256": "397e69a940d9fa571f833e28ec9e0b5f7c2b866da54b567296f23d31c0eac6bc",
        "git_state": "tracked_clean"
      },
      {
        "path": "D:\\CodexProjects\\ai-knowledge-compiler\\research\\model_arena_20260903\\runtimes\\unlimited_ocr\\runtime.json",
        "sha256": "d4ee33951e4f5045547cbaf5823fdc0c839b716d55784cb8d84c71eb5a5bcb47",
        "git_state": "tracked_clean"
      }
    ]
  }
}
```
<!-- END VERBATIM DRAFT -->
