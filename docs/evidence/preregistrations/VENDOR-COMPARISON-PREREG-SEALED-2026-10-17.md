# Vendor comparison pre-registration `tavonel.vendor_comparison.v1` — SEALED (decision D-10)

Decision register row **D-10** (source PHASE1-CRITIC D-10; aliases C-FD-6, KB-F5, KB-F9), class
`agent-now`, lane `PREREG-SEAL`. Lanes bound: P2-25 (competitive AT-1). Written by an agent. This
is a document only: it changes no code, no test, no self-check script, no draft, no price, no
public sentence and no evidence artifact.

| Field | Value |
| --- | --- |
| Status | **SEALED.** Scope: every threshold, margin, decision rule, statistic, denominator rule and publication rule in the draft below, as drafted. Not in scope: permission to run anything (see "What this seal does not do") |
| Decision | D-10, adopted default: "초안대로 승인하고 실행 전에 봉인한다. 벤더 δ(§4.5), KB1 n ≥ 50·family ≥ 10, API arm은 model ID와 revision을 하나로 고정, 블라인드 비교는 Holm α 0.05" (`REG.md:46`; `REG.json` row `D-10`). For this file the operative part is "벤더 δ(§4.5)", which answers C-FD-6 / FD-6 (`CP:355`) |
| Adoption | Founder message 2026-10-17, verbatim: "파운더 결정은 모두 실서비스에서 업계 1위 될 수 있도록 너가 추천한 방향으로 진행해서 완료할 수 있도록해줘" (`REG.md:3`). Cited as the adoption of the D-10 register default only. It is not a wording approval, not a claim approval, not a spend approval and not vendor permission |
| Decision date | 2026-10-17 (the adoption; the date in this file's name) |
| Sealed at | 2026-10-19T01:09:27Z (UTC). The commit that adds this file is the timestamp of record |
| Draft | `UX\VENDOR-COMPARISON-PREREG.json`, sha256 `d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9`, 56,223 bytes, 1,272 lines, LF. Matches its sidecar `UX\VENDOR-COMPARISON-PREREG.json.sha256`. The draft file is not changed |
| State at sealing | No vendor, model or judge call; no account; no terms accepted (draft `measured_numbers`, line 12; register D-34 `statusToday`, "벤더 계정·약관 수락·키 0", `REG.md` row D-34) |
| Change rule | **Changes after sealing require a new version.** A changed margin, rule, metric or corpus is `tavonel.vendor_comparison.v2`, registered as a new file before its first run; this file stays as it is (draft `sealing.rule_ko`, line 23) |
| Header correction | 2026-10-19, before the file was first pushed (independent review finding N-5): section 3 cited the FD-2 caps as `CP:350`; the FD-2 row is `CP:351`. Header text only. The verbatim draft, its sha256 and every sealed value are unchanged |

Short paths: `UX` = `D:\CodexProjects\ai-knowledge-compiler\outputs\tavonel-research-replan-20261013\ux-program-20261017`;
`REG` = `UX\DECISION-REGISTER-2026-10-17`; `CP` = `UX\COMPETITOR-PROTOCOL-2026-10-17.md`;
`PRE` = the verbatim draft at the end of this file (line numbers are the draft's own).

## 1. Sealed parameters

Every value below is the draft's value, unchanged. The δ values are the ones `CP` §4.5 proposes
(`CP:179-183`); the draft carries them per metric.

| Parameter | Sealed value | Draft lines |
| --- | --- | --- |
| δ, olmOCR-Bench `overall_macro_type_mean` (higher is better) | 2 points (0–100) | `PRE:97-107` |
| δ, OmniDocBench `text_edit` / `reading_order_edit` (lower is better) / `table_teds` (higher is better) | 0.01 / 0.02 / 0.02 | `PRE:157-188` |
| δ, ParseBench `tables`, `charts`, `content_faithfulness`, `semantic_formatting`, `visual_grounding`, `overall` | 2 points each (0–100); `overall` only as evaluator `1d460294` reports it, never computed by us | `PRE:226-291` |
| Co-reported metrics, no verdict | olmOCR `micro_check_pass_rate`, `per_type_pass_rate` (per-type is mandatory, absent checks pass on empty output) | `PRE:108-123` |
| D-axis verdict | Δ = TAVONEL − vendor (sign flipped for lower-is-better). Order BEHIND > AHEAD > WITHIN > INCONCLUSIVE. BEHIND `ci_upper < 0`; AHEAD `ci_lower > delta`; WITHIN `ci_lower >= -delta && ci_upper <= delta`; else INCONCLUSIVE. The nine boundary vectors are part of the rule | `PRE:506`, `PRE:517-607` |
| D-axis CI | Paired document-cluster bootstrap, percentile, 10,000 resamples, level 0.95, seed `tavonel-vendor-comparison-v1-bootstrap-2026-10-17`. An evaluator aggregate that does not decompose by document gets a point estimate only and INCONCLUSIVE | `PRE:507-515` |
| Repeats | Registry lock policy: one full run + 3 stratified audit runs of 128 documents per suite; any escalation trigger means 3 full runs; an arm named in a public comparison sentence counts as a finalist | `PRE:516`, `PRE:40-57` |
| A-axis verdict (A-T vs A-V-x) | AHEAD `point >= +5pp && ci_lower > 0 && exact_mcnemar_p < 0.05`; WITHIN CI inside ±5pp; BEHIND `ci_upper < 0`; else INCONCLUSIVE; pdf_sha256 cluster bootstrap 95% CI, 10,000; epoch aggregation as K26-PREREG; six vectors. A-T vs A-native keeps the F6 eight rules | `PRE:608-688` |
| Multiplicity | Per-metric 95% CI, no family-wise correction; a general "better than competitors" sentence needs AHEAD on every primary metric × every vendor arm run (intersection-union); every metric published in the same place. The draft left this to FD-6 (`PRE:689`); D-10 adopts it as drafted | `PRE:689` |
| ParseBench evaluator patch | Tracked patch `sha256:2a9f2ea7f01901effc247894d9bf4a4f210d6b1ebc22e907d0b851db27cabb67` applied identically to every arm, its sha written next to the evaluator revision in any sentence. The draft left "run without the patch" open for FD-6 (`PRE:221`); D-10 adopts the drafted choice (with patch) | `PRE:214-222` |
| Corpora, evaluators, N | As locked in `benchmark/v6/dataset-registry.lock.yaml` sha256 `aab092066d215782504933039f92e41fe4f71ebdf2b085912cc260f8f575a790`; N = 1,403 / 1,651 / 2,078 documents | `PRE:35-293` |
| Fixed conditions, denominators | Seven-day window, same retry rule, no contamination; denominator is every document provided, rejections and empty output scored as empty predictions; completion is never called accuracy | `PRE:490-503` |
| Latency | Answer stage only; parse and compile latency diagnostic only | `PRE:697-701` |
| Publication rules | Quoted vs same-condition separation, no cross-difference, sentence shapes, forbidden list. Publishing any sentence stays under D-09 (hold) | `PRE:1010-1037` |

## 2. Alignment at sealing (binds over the draft text)

These come from decisions adopted with the same 2026-10-17 message and recorded before this seal.
Where one disagrees with the draft, the line here governs.

1. **Corpus rights, D-31.** Record: Core `docs/compliance/CORPUS_RIGHTS_POLICY_2026-10-17.md`
   (commit `4a583312`, repo-bytes sha256 `72aa489e61ceaef1945c6a552ae7adc733ea6ac8cbe9b0ac90ab5cb4cc601dba`).
   - ParseBench: allowed, with its NOTICE (policy row 4). Consistent with `PRE:223-224`.
   - OmniDocBench: internal measurement only, and its numbers back no public claim at all (policy
     row 5). This is stricter than `PRE:154` ("공개 비교 문장에는 별도 권리 검토가 필요하다"), so
     no D-T-live OmniDocBench result may back a public sentence.
   - olmOCR-Bench: "Not a corpus source under this policy" (policy, "Sources the row does not
     name"). So the D-T-live olmOCR-Bench cell does not run until a decision names this corpus.
     Its δ stays sealed, so a later decision cannot reopen the margin.
2. **D-T-live GPU cap.** The draft calls it a founder decision (`PRE:326`). Register D-30 and
   conflict rule C8 set it: T7, specimen and D-T-live together at most USD 25, D-T-live alone at
   most USD 20 (`REG.md:59`, `REG.md:127`). D-30 is `founder-hands` (FH-01, the evaluation tenant),
   so the cap applies only once that tenant exists.

## 3. What this seal does not do

The draft lists four sealing requirements (`PRE:17-22`). This seal meets the first only.

| Draft requirement | State |
| --- | --- |
| "FD-6 δ·판정 규칙·다중성 처리 승인" | **Met** by the D-10 adoption (above) |
| "독립 리뷰(구현한 세션은 자기 결과를 승인하지 않는다)" | **Open.** An independent reviewer with no implementation context confirms this file against the draft before the first vendor call |
| "cost_estimate 재계산으로 FD-2 상한 갱신" | **Open.** The draft already recomputed the rows on the lock's 384 audit pages per corpus (`PRE:705-710`); the FD-2 caps (USD 130 / 165 / 390, `CP:351`) were set on a 768-page basis and must be reset. New caps are FOUNDER-SET (question below) |
| "실행 7일 이내 가격·약관 snapshot(AT-3)" | **Open by construction.** It can only be taken once an execution date exists |

- **No vendor arm may run.** `vendor_execution_allowed` stays `false` (`PRE:26`); register D-34 is
  `hold`: no vendor account, no terms accepted, no key, until counsel review and written vendor
  permission (FH-20) (`REG.md` row D-34, `REG.md:116`).
- **The machine-readable draft is not edited.** Its `status`, `sealing.sealed`, `sealed_at`,
  `sealed_sha256` and every `delta.status` still read as a draft, and
  `UX\VENDOR-COMPARISON-PREREG.selfcheck.js` (sha256 `f7d6d50eeac8d904d6e0040b932e7f87e3ffb8b81b3d74c08aa7c048b52cced7`)
  asserts exactly that (lines 82-83, 130-132). Writing a sealed JSON v1 and its self-check is a
  code step for the lane that next touches AT-1/P2-21; it must carry the values sealed here and
  nothing else.
- **δ is not calibrated** (`PRE:1091`). Sealing fixes it before results; it does not show it is
  the right margin. `predicted_outcomes_ko` (`PRE:691-695`) are predictions, not results.

FOUNDER-SET, with the question:

- **FD-2 vendor spend caps**: what is the per-vendor USD cap on the 384-pages-per-corpus basis
  (and with the finalist three-run scenario), once D-34 is released?

## 4. Sources

| Path | sha256 |
| --- | --- |
| `UX\VENDOR-COMPARISON-PREREG.json` (the draft) | `d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9` |
| `UX\DECISION-REGISTER-2026-10-17.md` | `5935276d245d230857fa632dcb6555d25756470d37f404fc6c3c00dc71d7c6dc` |
| `UX\DECISION-REGISTER-2026-10-17.json` | `86234c9397cec2d0ac8160276e525943857e7b2ec21e5e3a3b9891cc394120d3` |
| `UX\PHASE1-CRITIC-2026-10-17.md` (D-10 at line 250) | `667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81` |
| `UX\COMPETITOR-PROTOCOL-2026-10-17.md` (§4.5 at 175-198, FD-6 at 355) | `f40eb532eb4a16dd4608e9afbbe01ab0e65e1a4dc90105f9446ef13ea49ae2e1` |
| `UX\SERVICE-DEFINITION-2026-10-17.md` (G9, line 364) | `c7783dd718713b7564697ce6df7e6abbad9ffc2489624b3ad3705e610b528dee` |
| `UX\VENDOR-COMPARISON-PREREG.selfcheck.js` | `f7d6d50eeac8d904d6e0040b932e7f87e3ffb8b81b3d74c08aa7c048b52cced7` |
| Core `docs/compliance/CORPUS_RIGHTS_POLICY_2026-10-17.md` at `4a583312` | `72aa489e61ceaef1945c6a552ae7adc733ea6ac8cbe9b0ac90ab5cb4cc601dba` |

## 5. The draft, byte for byte

Everything between the two marker lines below, minus the opening and closing fence lines, is the
draft's exact bytes. Its own `"status": "DRAFT_PROPOSED"` and `"sealed": false` are the draft's
text; the header above is what is sealed. Check:

```text
awk '/^<!-- END VERBATIM DRAFT/{f=0} f; /^<!-- BEGIN VERBATIM DRAFT/{f=1}' VENDOR-COMPARISON-PREREG-SEALED-2026-10-17.md | sed '1d;$d' | sha256sum
# expect d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9
```

<!-- BEGIN VERBATIM DRAFT: UX/VENDOR-COMPARISON-PREREG.json, sha256 d68e0027e8c43fbcbe5c7bdfb77a27ee6ebf6ba5292b8ef992cde0c6354916c9 -->
```json
{
  "schema": "tavonel.vendor_comparison.v1",
  "status": "DRAFT_PROPOSED",
  "created": "2026-10-17",
  "lane": "P2-25 (경쟁 AT-1)",
  "thresholds_status": "proposed — FD-6(창업자, critic D-10) 승인 전에는 구속력이 없다. 승인하면 봉인한 뒤에 벤더를 실행한다",
  "question_ko": {
    "d_axis": "같은 문서와 같은 평가기에서 TAVONEL 라이브 제품 경로는 각 벤더 API의 기본 설정보다 어떤 지표에서 앞서고 어떤 지표에서 뒤지는가?",
    "a_axis": "같은 subject 모델이 같은 질문을 같은 예산으로 풀 때, PDF에 TAVONEL compiled context를 붙인 경우와 벤더 parse를 붙인 경우 중 어느 쪽이 rubric을 전부 통과하는 과제가 더 많은가?"
  },
  "separation_ko": "sealed four-arm GDP 프로토콜(FND eval/gdp-pdf/protocol.json)과 K26 결과를 이 비교와 섞지 않는다(PERFORMANCE-RESEARCH-PLAN.md:46)",
  "measured_numbers": "none — 이 파일에 새 측정값은 없다. 모델·judge·벤더 API 호출 0건, 계정·약관 수락 0건",
  "sealing": {
    "sealed": false,
    "sealed_at": null,
    "sealed_sha256": null,
    "requires": [
      "FD-6 δ·판정 규칙·다중성 처리 승인",
      "독립 리뷰(구현한 세션은 자기 결과를 승인하지 않는다)",
      "cost_estimate 재계산으로 FD-2 상한 갱신",
      "실행 7일 이내 가격·약관 snapshot(AT-3)"
    ],
    "rule_ko": "결과를 본 뒤에 δ를 고르면 사전등록이 아니다. 봉인한 뒤에 바꾸려면 v2로 새로 등록하고 v1을 보존한다"
  },
  "execution": {
    "vendor_execution_allowed": false,
    "reason_ko": "critic D-34: 실행하지 않는다. counsel 검토 뒤 네 벤더에 benchmarking 서면 허가를 요청하고, 그 전까지 벤더 수치는 인용만 한다",
    "requires_before_any_vendor_call": [
      "FD-1 서면 허가 또는 counsel 판단 receipt",
      "FD-2 키와 지출 상한(secret 값은 에이전트가 다루지 않는다)",
      "FD-3 corpus 권리",
      "봉인(sealing.requires 전부)"
    ]
  },
  "registry_lock": {
    "path": "benchmark/v6/dataset-registry.lock.yaml",
    "sha256": "aab092066d215782504933039f92e41fe4f71ebdf2b085912cc260f8f575a790",
    "schema_version": "6.0.0",
    "locked_at": "2026-08-01T00:00:00Z",
    "policy": {
      "inference_ground_truth_access": "forbidden",
      "evaluator_only_ground_truth_mount": "required",
      "prediction_freeze_before_evaluation": "required",
      "immutable_dataset_manifest": "required",
      "public_core_repetitions": 3,
      "adaptive_repeat_policy": {
        "initial_full_runs": 1,
        "stratified_audit_runs": 3,
        "escalation_full_runs": 3,
        "escalation_triggers": [
          "finalist",
          "prediction_hash_drift",
          "score_drift",
          "runtime_failure"
        ]
      },
      "private_data_redistribution": "forbidden"
    },
    "not_in_scope_ko": "robustness(real5-omnidocbench, mdpbench-korean)와 private_hard_sets는 revision·manifest가 null이라 이 비교의 corpus가 아니다"
  },
  "corpora": [
    {
      "id": "olmocr-bench",
      "lock_copy": {
        "id": "olmocr-bench",
        "required": true,
        "evaluator_repository": "https://github.com/jina-ai/olmocr-bench.git",
        "evaluator_commit": "cfa88c1eb1c2ec4495c84d6820ffe85d33b7408c",
        "evaluator_declared_version": "2026-02-19",
        "dataset_repository": "allenai/olmOCR-bench",
        "dataset_revision": "54a96a6fb6a2bd3b297e59869491db4d3625b711",
        "dataset_manifest_sha256": "sha256:55f347b01850aec77d457f6b3b2b54ddf5adce6f451ed501e59995ec0e9bff15",
        "license_status": "review_required",
        "redistribution": "prohibited_until_license_review",
        "repetitions": 3,
        "repeat_mode": "adaptive_with_finalist_exact_three"
      },
      "N": 1403,
      "N_unit": "documents",
      "N_source": {
        "path": "research/model_arena_20260903/reports/full_compare_20260905/corpus_coverage_5132.json",
        "key": "olmocr",
        "field": "sample_count"
      },
      "evaluator_tracked_patch": {
        "sha256": "sha256:e93e8b7ba7f730d416def8629cd54dfd1f3925c8814bc72aaeb5fa4f20b2e734",
        "purpose_ko": "Windows에서 후보 상대 경로를 POSIX 구분자로 바꾼다(evaluator_portability_patch). 채점 로직은 바꾸지 않는다",
        "source_artifact": {
          "path": "docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__olmocr-bench__evaluation-summary.json",
          "sha256": "4d75ae96e70c7c1c425b991df0f1c356ec6393e73914aaed27f5f54b0048a559"
        },
        "applies_to_ko": "모든 arm에 같은 patch를 적용한다"
      },
      "vendor_arm_eligibility": "pending_counsel",
      "rights_ko": "ODC-BY-1.0, \"intended for research and educational use\". lock은 review_required. 원본 PDF의 제3자 저작권은 ODC-BY가 다루지 않는다. 벤더 제출은 FD-3 counsel 판단 뒤에만",
      "metrics": [
        {
          "id": "overall_macro_type_mean",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "문서 유형 8개 통과율의 단순 평균(분모: 유형 8개, 유형별 검사 수를 병기). 80.6이 이 정의다(검사 기준 아님)",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "micro_check_pass_rate",
          "role": "co_reported",
          "direction": "higher",
          "unit": "percent",
          "definition_ko": "통과 검사 수 / 전체 검사 수. 판정 없이 같은 자리에 게시",
          "delta": null
        },
        {
          "id": "per_type_pass_rate",
          "role": "co_reported",
          "direction": "higher",
          "unit": "percent",
          "definition_ko": "유형 8개 각각. absent 검사는 빈 문서에서 저절로 통과하므로(FOLYNTA_CAMPAIGN_RESULTS.md:150-154) 유형별 결과를 반드시 같이 낸다",
          "delta": null
        }
      ]
    },
    {
      "id": "omnidocbench",
      "lock_copy": {
        "id": "omnidocbench",
        "required": true,
        "evaluator_repository": "https://github.com/opendatalab/OmniDocBench.git",
        "evaluator_commit": "193627ae9e97d89188468ed1ee3b7a856ff76044",
        "evaluator_declared_version": "v1.7",
        "dataset_repository": "opendatalab/OmniDocBench",
        "dataset_revision": "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec",
        "dataset_manifest_sha256": "sha256:1902d23db1b0e409d774f1420306f9e9e82d1aa8638050f0fc8fd6b94c58aa99",
        "license_status": "research_only_non_commercial",
        "redistribution": "prohibited_without_separate_rights_review",
        "repetitions": 3,
        "repeat_mode": "adaptive_with_finalist_exact_three"
      },
      "N": 1651,
      "N_unit": "documents",
      "N_source": {
        "path": "research/model_arena_20260903/reports/full_compare_20260905/corpus_coverage_5132.json",
        "key": "omnidoc",
        "field": "sample_count"
      },
      "evaluator_tracked_patch": {
        "sha256": null,
        "null_reason_ko": "metric-result artifact에 patch 기록 필드가 없다. 실행 전에 평가기 worktree가 깨끗한지(또는 patch sha)를 receipt에 남긴다"
      },
      "vendor_arm_eligibility": "excluded",
      "rights_ko": "\"research purposes only and not for commercial use\". 벤더 arm에서 제외(FD-3 권고, critic D-31 '내부 측정만'). D-T-live 내부 측정은 가능하지만 공개 비교 문장에는 별도 권리 검토가 필요하다",
      "metrics": [
        {
          "id": "text_edit",
          "role": "primary",
          "direction": "lower",
          "unit": "normalized_edit_distance_0_1",
          "definition_ko": "평가기 193627ae가 계산한 text block Edit",
          "delta": {
            "value": 0.01,
            "status": "proposed"
          }
        },
        {
          "id": "reading_order_edit",
          "role": "primary",
          "direction": "lower",
          "unit": "normalized_edit_distance_0_1",
          "definition_ko": "평가기가 계산한 reading-order Edit",
          "delta": {
            "value": 0.02,
            "status": "proposed"
          }
        },
        {
          "id": "table_teds",
          "role": "primary",
          "direction": "higher",
          "unit": "score_0_1",
          "definition_ko": "평가기가 계산한 table TEDS",
          "delta": {
            "value": 0.02,
            "status": "proposed"
          }
        }
      ]
    },
    {
      "id": "parsebench",
      "lock_copy": {
        "id": "parsebench",
        "required": true,
        "evaluator_repository": "https://github.com/run-llama/ParseBench.git",
        "evaluator_commit": "1d460294b3b9c57fb3fa944dc17a9c044c24d1e5",
        "evaluator_declared_version": "2026-07-27",
        "dataset_repository": "llamaindex/ParseBench",
        "dataset_revision": "2805a1d940f95a203e0ae4b88be9934f7765b3fc",
        "dataset_manifest_sha256": "sha256:9e3a722a5db9e8e23273176827c06a30fe6a58a983850329db917fabcff6c30e",
        "license_status": "approved_with_notice",
        "redistribution": "license_permits_with_notice",
        "repetitions": 3,
        "repeat_mode": "adaptive_with_finalist_exact_three"
      },
      "N": 2078,
      "N_unit": "documents",
      "N_source": {
        "path": "research/model_arena_20260903/reports/full_compare_20260905/corpus_coverage_5132.json",
        "key": "parsebench",
        "field": "sample_count"
      },
      "evaluator_tracked_patch": {
        "sha256": "sha256:2a9f2ea7f01901effc247894d9bf4a4f210d6b1ebc22e907d0b851db27cabb67",
        "purpose_ko": "watchdog 정책: \"punctuation-only formatting queries are recorded as conservative evaluator failures\". 채점에 닿는 patch다(경쟁 문서 §4.3은 olmOCR patch만 적었다)",
        "source_artifact": {
          "path": "docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__parsebench__evaluation-summary.json",
          "sha256": "22cf5bf183ef875338de8442a6d3c5c3dca89ae52346b7f36a07b9332471a228"
        },
        "applies_to_ko": "모든 arm에 같은 patch를 적용하고, 게시 문장의 평가기 revision 옆에 patch sha를 적는다. patch 없이 돌릴지는 FD-6에서 함께 정한다"
      },
      "vendor_arm_eligibility": "proposed_allowed",
      "rights_ko": "Apache-2.0, NOTICE 필요. 경쟁사(LlamaIndex)가 만든 benchmark라는 라벨을 의무로 붙인다. 원본 문서의 저작권은 불명확하다",
      "metrics": [
        {
          "id": "tables",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "평가기 1d460294의 Tables dimension",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "charts",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "Charts dimension",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "content_faithfulness",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "Content Faithfulness dimension",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "semantic_formatting",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "Semantic Formatting dimension",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "visual_grounding",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "Visual Grounding dimension",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        },
        {
          "id": "overall",
          "role": "primary",
          "direction": "higher",
          "unit": "points_0_100",
          "definition_ko": "평가기 1d460294가 직접 내는 Overall만 쓴다. 평가기가 내지 않으면 not_reported로 두고 우리가 집계식을 만들지 않는다(우리 캠페인은 Overall을 계산한 적이 없다, FOLYNTA_CAMPAIGN_RESULTS.md:106-110)",
          "delta": {
            "value": 2,
            "status": "proposed"
          }
        }
      ]
    }
  ],
  "arms": {
    "d_axis": [
      {
        "id": "D-T-live",
        "system_under_test": "tavonel_live",
        "corpora": [
          "olmocr-bench",
          "omnidocbench",
          "parsebench"
        ],
        "status": "blocked",
        "blocked_on": [
          "FD-10 평가 tenant와 GPU 상한",
          "AT-6 평가기 입력 adapter",
          "FD-6 봉인"
        ],
        "definition_ko": "intake → CDR → foundation_ocr_gpu_v1 → Core v2. 라이브 제품 한도(5,242,880 bytes / 80쪽)를 적용한다. 출력은 제품이 노출하는 page·paragraph_text·bbox1000이고, 고정된 adapter(digest 기록)로 평가기 입력 markdown으로 바꾼다",
        "product_limits": {
          "max_source_bytes": 5242880,
          "max_pages": 80,
          "source": "live_capabilities: at_most_5_mib_per_source, at_most_80_pages_per_source"
        },
        "pins_required": [
          "foundation_deployment_id",
          "cdr_revision_and_digest",
          "ocr_image_digest(실행 시점 endpoint에서 읽는다)",
          "core_v2_revision",
          "adapter_digest",
          "evaluation_tenant_id"
        ],
        "ocr_image_note_ko": "경쟁 문서 §4.2는 F5의 sha256:0e916aa6…4101을 적었지만, F5C receipt에 따르면 2026-10-15T23:37Z(endpoint version 21)에 sha256:8e6f6fa777fd9949745ce67b25d04f0a1aa74dfbf791204baf2b6b16c3931bd8로 바뀌었고 0e916aa6은 rollback 대상이다. 그래서 digest를 미리 고정하지 않고 실행 시점 값을 receipt에 남긴다",
        "gpu_cap_ko": "FD-10 제안은 D-T-live USD 20, critic D-30 제안은 T7·specimen·D-T-live 합계 USD 25. 창업자 결정. 내부 지출이며 게시하지 않는다"
      },
      {
        "id": "D-T-hist",
        "system_under_test": "tavonel_research",
        "corpora": [],
        "status": "historical_only",
        "definition_ko": "R-01 연구 파이프라인(MinerU 3.4.4 + recovery). 다시 실행하지 않는다. '제품'이나 'TAVONEL이 벤더보다' 문장에 쓰지 않고, 벤더 행 옆에 두지 않는다(FD-8)"
      },
      {
        "id": "D-V-reducto",
        "system_under_test": "vendor",
        "corpora": [
          "parsebench"
        ],
        "status": "blocked",
        "blocked_on": [
          "FD-1",
          "FD-2",
          "FD-3"
        ],
        "config_ko": "/parse 기본값, 옵션 없음, 동기 호출(배치 할인 없음)",
        "pins_required": [
          "request_json_digest",
          "response_model_and_version_fields",
          "date"
        ],
        "terms_snapshot": {
          "file": "competitor-protocol-receipts/web/reducto-terms.html",
          "url": "https://reducto.ai/terms",
          "sha256": "919f09b87a532f6b55a95d32aceaba2d2fd8ef79c98d6ab4777f3a48981ea062",
          "downloaded_utc": "2026-10-17T01:24:51.540Z"
        },
        "price_snapshot": {
          "file": "competitor-protocol-receipts/web/reducto-pricing.html",
          "url": "https://reducto.ai/pricing",
          "sha256": "db2496594aabf5e779eec25e7826be12d8fbd359aba55f4672ff9498d264e667",
          "downloaded_utc": "2026-10-17T01:24:50.789Z"
        },
        "unknown_ko": "/parse의 기본 모델을 docs가 '기본값'이라고 명시하지 않는다(경쟁 §9)"
      },
      {
        "id": "D-V-llamaparse",
        "system_under_test": "vendor",
        "corpora": [
          "parsebench"
        ],
        "status": "blocked",
        "blocked_on": [
          "FD-1",
          "FD-2",
          "FD-3"
        ],
        "config_ko": "tier: agentic, version: 실행 전 공개된 날짜 값으로 고정. API에 기본값이 없다(\"tier and version are both required\"). 48시간 캐시는 끄거나 첫 parse 결과만 기록한다",
        "pins_required": [
          "tier",
          "version",
          "cache_state",
          "credits_reported"
        ],
        "terms_snapshot": {
          "file": "competitor-protocol-receipts/web/llamaindex-terms.html",
          "url": "https://www.llamaindex.ai/legal/terms-of-service",
          "sha256": "fa5926b82bb89924b6eb63a224ef7e66c3147ca2a6b3e3a8731f7fd949a056c4",
          "downloaded_utc": "2026-10-17T01:24:52.374Z"
        },
        "price_snapshot": {
          "file": "competitor-protocol-receipts/web/llamaparse-docs-pricing.html",
          "url": "https://developers.llamaindex.ai/llamaparse/general/pricing/",
          "sha256": "2eabf853344060b989e7a6740447a18ef6ddbcf63bada2eeeb371a6511717d8b",
          "downloaded_utc": "2026-10-17T01:25:48.240Z"
        },
        "conflict_ko": "ParseBench는 LlamaIndex가 만든 benchmark다. 이 arm의 결과에는 그 라벨을 붙인다"
      },
      {
        "id": "D-V-unstructured",
        "system_under_test": "vendor",
        "corpora": [],
        "status": "blocked",
        "blocked_on": [
          "FD-1",
          "FD-3: Platform Terms 3.2(a)의 영구 학습 라이선스 — enterprise 계약으로 빼지 않으면 어떤 corpus도 보낼 수 없다"
        ],
        "config_ko": "API 기본 partition 전략(응답에서 전략·버전을 pin)",
        "terms_snapshot": {
          "file": "competitor-protocol-receipts/web/unstructured-platform-terms.html",
          "url": "https://unstructured.io/platform-terms-of-service",
          "sha256": "ff78dc866b7e4b1e835e307fe224af0171e3909c84e1cbdf9b8e3c3f88b224e4",
          "downloaded_utc": "2026-10-17T01:26:59.741Z"
        },
        "price_snapshot": {
          "file": "competitor-protocol-receipts/web/unstructured-pricing.html",
          "url": "https://unstructured.io/pricing",
          "sha256": "dcf420b91189d7ed0e14ecd5cbc9e3899721dffb643a3ea8480339396870d8bf",
          "downloaded_utc": "2026-10-17T01:24:55.572Z"
        }
      },
      {
        "id": "D-V-landingai",
        "system_under_test": "vendor",
        "corpora": [
          "parsebench"
        ],
        "status": "blocked",
        "blocked_on": [
          "FD-1",
          "FD-2",
          "FD-3"
        ],
        "config_ko": "DPT-3 Pro, 동기 호출(priority tier)",
        "pins_required": [
          "metadata.total_credits",
          "service_tier",
          "model_version"
        ],
        "terms_snapshot": {
          "file": "competitor-protocol-receipts/web/landingai-terms.html",
          "url": "https://landing.ai/terms-of-service",
          "sha256": "da40a0c2c96b640c9da65038b5e09cfcce7be0d975c1d5e6dc404d782a939be5",
          "downloaded_utc": "2026-10-17T01:24:59.579Z"
        },
        "price_snapshot": {
          "file": "competitor-protocol-receipts/web/landingai-pricing.html",
          "url": "https://landing.ai/pricing-agentic-apis",
          "sha256": "a8cf10851a3622a3f3c8578edba63a8b832c275788046426f05dd7d2c716a084",
          "downloaded_utc": "2026-10-17T01:24:58.435Z"
        },
        "unknown_ko": "ADE 전용 약관을 찾지 못했다(경쟁 §9)"
      },
      {
        "id": "D-S-sensitivity",
        "system_under_test": "vendor",
        "corpora": [
          "parsebench"
        ],
        "status": "blocked",
        "headline": false,
        "definition_ko": "LlamaParse agentic_plus, Reducto agentic 옵션, LandingAI standard tier. 사전등록하지만 헤드라인이 아니다. 각각 따로 보고하고 헤드라인 판정에 섞지 않는다"
      }
    ],
    "a_axis": [
      {
        "id": "A-native",
        "definition_ko": "K26 arm A native_pdf",
        "governed_by": "k26_prereg + k26_dev_lock"
      },
      {
        "id": "A-T",
        "definition_ko": "K26 arm B compiled_context_pdf(v3 packet + PDF). 라벨은 '연구용 compiled-context arm'. 제품 Ask는 evidence excerpts만 돌려주고 LLM 답변 경로가 없다(ask/route.ts:80)",
        "limits_ko": "F7은 18 MiB/80쪽 arm. 이 arm은 'worker 한도 연구 arm'이고, '제품' 문장에는 5 MiB arm(AT-5)이 필요하다(FD-4, critic D-35)"
      },
      {
        "id": "A-V-x",
        "status": "blocked",
        "blocked_on": [
          "F1: GDP 원문은 이 기계 밖으로 보내지 않는다(프로토콜이 이미 하는 모델 호출만 예외)",
          "Surge 권리 확인",
          "FD-1",
          "FD-2"
        ],
        "definition_ko": "PDF + 벤더 parse markdown. subject·judge·epoch·예산·timeout은 A-T와 같다"
      }
    ]
  },
  "fixed_conditions": {
    "time_window_days": 7,
    "time_window_ko": "모든 벤더 arm을 7일 안에 실행한다. 가격·약관 snapshot은 실행 7일 이내에 받은 것이어야 한다(WEB-RECEIPTS-MANIFEST 형식). 오늘의 snapshot(2026-10-17)은 실행일이 정해지면 다시 받는다",
    "order_and_retry_ko": "arm마다 문서 순서를 seed로 섞는다. 동시성은 벤더 권장값. 재시도는 모든 arm이 같다: 429/5xx만 최대 2회, 운영 실패로 따로 기록",
    "contamination_ko": "한 arm의 출력이 다른 arm의 입력이 되지 않는다. 정답과 rubric은 어떤 arm의 입력에도 쓰지 않는다. lock policy: inference_ground_truth_access forbidden, evaluator_only_ground_truth_mount required, prediction_freeze_before_evaluation required",
    "evaluator_ko": "corpora[].lock_copy의 평가기 commit과 corpora[].evaluator_tracked_patch만 쓴다. 채점 로직을 arm마다 다르게 두지 않는다"
  },
  "denominators": {
    "primary_ko": "1차 분모는 제공한 전체 문서 수 N이다(corpora[].N, lock과 같은 manifest의 receipt). 제품 한도 거절, CDR 거절, OCR timeout(85 s), 벤더의 크기 거절·오류·timeout, 빈 출력은 모두 빈 예측으로 채점기에 들어간다",
    "completion_rate_ko": "완료율 = 출력이 비어 있지 않은 문서 / N. '정확도'라고 부르지 않는다",
    "attempted_only_ko": "'시도된 문서만' 단면은 자기 분모를 붙여 함께 게시하되 헤드라인으로 쓰지 않는다",
    "failure_split_ko": "운영 실패(worker 사망, 429/5xx, timeout)와 의미 실패(틀린 출력)를 따로 센다",
    "same_documents_ko": "모든 arm이 같은 문서 목록을 받는다. 어떤 arm에서만 문서를 빼지 않는다. 벤더에는 같은 sha의 원본 바이트를 보낸다"
  },
  "statistics": {
    "status": "proposed",
    "delta_definition_ko": "같은 문서 위의 짝 차이 Δ = TAVONEL − 벤더. lower 지표는 Δ = 벤더 − TAVONEL로 부호를 뒤집어, 양수가 언제나 TAVONEL 우위다",
    "ci": {
      "method": "paired_document_cluster_bootstrap_percentile",
      "resamples": 10000,
      "level": 0.95,
      "seed": "tavonel-vendor-comparison-v1-bootstrap-2026-10-17",
      "seed_status": "proposed",
      "resample_unit_ko": "문서. 한 번 뽑은 문서 다중집합을 두 arm에 동시에 적용하고, 통계량은 평가기 자신의 집계식으로 다시 계산한다",
      "undecomposable_ko": "평가기 집계가 문서별로 분해되지 않으면 CI를 만들지 않고 점추정만 게시한다. 그 지표의 판정은 INCONCLUSIVE다(우리가 집계식을 새로 만들지 않는다)"
    },
    "repeats_ko": "lock policy를 그대로 따른다: 전체 1회 + suite마다 128문서 층화 감사 3회. escalation trigger(finalist, prediction_hash_drift, score_drift, runtime_failure)가 걸리면 전체 3회. 제안: 공개 비교 문장에 나오는 arm은 finalist로 본다. 전체 3회가 있으면 문서별 점수 = 3회 평균으로 판정하고 회차별 결과를 같이 게시한다. 1회뿐이면 1회차로 판정하고 감사 회차는 분산 보고에만 쓴다",
    "d_axis_verdict": {
      "status": "proposed",
      "asymmetry_ko": "앞선다는 판정에는 margin을 요구하고, 뒤진다는 판정은 쉽게 내린다",
      "order": [
        "BEHIND",
        "AHEAD",
        "WITHIN",
        "INCONCLUSIVE"
      ],
      "rules": {
        "BEHIND": "ci_upper < 0",
        "AHEAD": "ci_lower > delta",
        "WITHIN": "ci_lower >= -delta && ci_upper <= delta",
        "INCONCLUSIVE": "otherwise"
      },
      "precedence_reason_ko": "경쟁 문서 §4.5의 규칙은 WITHIN과 BEHIND가 겹친다(예: CI [−1.5, −0.2], δ 2). 위 순서로 BEHIND가 먼저다. AHEAD는 다른 둘과 겹치지 않는다. P2-21(AT-4) 판정 함수는 이 순서와 아래 벡터를 그대로 따라야 한다",
      "test_vectors": [
        {
          "ci": [
            2.01,
            5
          ],
          "delta": 2,
          "expected": "AHEAD"
        },
        {
          "ci": [
            2,
            5
          ],
          "delta": 2,
          "expected": "INCONCLUSIVE"
        },
        {
          "ci": [
            -2,
            2
          ],
          "delta": 2,
          "expected": "WITHIN"
        },
        {
          "ci": [
            -0.5,
            0
          ],
          "delta": 2,
          "expected": "WITHIN"
        },
        {
          "ci": [
            -1.5,
            -0.2
          ],
          "delta": 2,
          "expected": "BEHIND"
        },
        {
          "ci": [
            -5,
            -3
          ],
          "delta": 2,
          "expected": "BEHIND"
        },
        {
          "ci": [
            -2.5,
            1
          ],
          "delta": 2,
          "expected": "INCONCLUSIVE"
        },
        {
          "ci": [
            0.5,
            2.5
          ],
          "delta": 2,
          "expected": "INCONCLUSIVE"
        },
        {
          "ci": [
            0.011,
            0.03
          ],
          "delta": 0.01,
          "expected": "AHEAD"
        }
      ]
    },
    "a_axis_verdict": {
      "status": "proposed",
      "scope_ko": "A-T 대 A-V-x만 정한다. A-T 대 A-native는 F6의 8개 기준(창업자가 구속 규칙으로 채택, F-DECISIONS F6)을 그대로 쓴다",
      "epoch_aggregation_ko": "K26-PREREG statistics와 같다: 과제별 점수 = 5 epoch all_pass 평균(macro), McNemar 이진값 = 과제별 다수결(5 중 3 이상), 실패 epoch는 0. epoch는 독립 표본이 아니다",
      "ci_ko": "pdf_sha256 cluster bootstrap 95% percentile CI, 10,000회",
      "order": [
        "BEHIND",
        "AHEAD",
        "WITHIN",
        "INCONCLUSIVE"
      ],
      "rules": {
        "BEHIND": "ci_upper < 0",
        "AHEAD": "point >= +5pp && ci_lower > 0 && exact_mcnemar_p < 0.05",
        "WITHIN": "ci_lower >= -5pp && ci_upper <= +5pp",
        "INCONCLUSIVE": "otherwise"
      },
      "margin_source": "PERFORMANCE-RESEARCH-PLAN.md:61 (+5pp)",
      "test_vectors": [
        {
          "point": 6,
          "ci": [
            1,
            11
          ],
          "p": 0.03,
          "margin_pp": 5,
          "expected": "AHEAD"
        },
        {
          "point": 6,
          "ci": [
            1,
            11
          ],
          "p": 0.06,
          "margin_pp": 5,
          "expected": "INCONCLUSIVE"
        },
        {
          "point": 4,
          "ci": [
            0.5,
            8
          ],
          "p": 0.01,
          "margin_pp": 5,
          "expected": "INCONCLUSIVE"
        },
        {
          "point": -2,
          "ci": [
            -4,
            -0.5
          ],
          "p": 0.04,
          "margin_pp": 5,
          "expected": "BEHIND"
        },
        {
          "point": 1,
          "ci": [
            -3,
            4.5
          ],
          "p": 0.5,
          "margin_pp": 5,
          "expected": "WITHIN"
        },
        {
          "point": 5,
          "ci": [
            0.2,
            5
          ],
          "p": 0.04,
          "margin_pp": 5,
          "expected": "AHEAD"
        }
      ]
    },
    "multiplicity_ko": "지표별 95% CI이고 family-wise 보정은 하지 않는다. 대신 (1) 모든 지표를 같은 자리에 게시하고 골라내지 않는다. (2) 일반 '경쟁사보다 낫다'는 모든 1차 지표 × 실행된 모든 벤더 arm에서 AHEAD여야 하는 교집합 규칙(intersection-union)이라, 그 주장의 오류율은 개별 검정의 수준을 넘지 않는다. (3) 지표 하나의 문장은 그 지표·corpus·날짜로 범위를 한정한다. 지표가 많아 우연한 BEHIND가 나올 수 있는데, 이는 우리에게 불리한 쪽의 오류라 받아들인다. 보정 여부는 FD-6에서 δ와 함께 승인한다",
    "power_warning_ko": "A축: 역사 실행의 불일치 쌍은 18/100이었다. confirm은 70과제이고 epoch는 독립 표본이 아니다. INCONCLUSIVE가 가장 그럴듯한 결과다",
    "predicted_outcomes_ko": [
      "D-T-live는 ParseBench Tables·Charts와 OmniDocBench table TEDS에서 BEHIND로 예측한다. 라이브 capabilities가 no_table_or_formula_extraction이고 리더가 모든 region을 paragraph로 낸다(critic V16·V21)",
      "Content Faithfulness·Visual Grounding·text Edit·reading order는 예측하지 않는다(근거 없음)",
      "A축 A-T 대 A-V-x는 INCONCLUSIVE로 예측한다(위 검정력 경고)"
    ]
  },
  "latency": {
    "headline_ko": "답변 단계만 잰다(A축 subject 요청부터 최종 응답까지 wall time). 셀별 p50/p95. 같은 기계, 동시성 1, 같은 region",
    "diagnostic_only_ko": "parse·compile 지연은 진단용으로만 기록한다. 헤드라인에도 벤더 간 속도 비교에도 쓰지 않는다(벤더 queue·tier, LlamaParse 48시간 캐시)",
    "quoted_ko": "Reducto의 \"120s to 111s\"는 인용이다. 우리 결과와 같은 열에 두지 않는다"
  },
  "cost_estimate": {
    "label_ko": "[계산] list price × 쪽수. 측정값이 아니고 무료 크레딧은 반영하지 않았다. 0.5센트는 올림",
    "pages_assumption_ko": "문서 1개 = 1쪽으로 둔다(경쟁 문서 §5와 같은 가정). ParseBench는 README가 \"~2,000 pages\"라고 적어 실제 쪽수와 다를 수 있다",
    "audit_documents_per_corpus": 384,
    "scenarios_ko": {
      "base": "전체 1회 + 128문서 × 감사 3회",
      "finalist_exact_three": "전체 3회(첫 회 포함) + 감사 3회. escalation이 걸리거나 arm이 finalist일 때"
    },
    "correction_ko": "경쟁 문서 §5의 '반복 감사 128 × 2 × 3 suite = 768쪽'은 lock의 stratified_audit_runs 3과 다르다. 이 파일은 lock을 따라 corpus당 384쪽으로 계산했다. FD-2의 벤더별 상한(Reducto $130, LlamaParse $165, LandingAI $390)은 768쪽 기준이고 finalist 3회를 넣지 않았으므로 봉인 전에 다시 구해야 한다",
    "vendor_scope_ko": "FD-3 권고대로면 벤더 arm은 ParseBench만 돈다(olmOCR은 counsel 뒤). OmniDocBench 행은 D-T-live 내부 측정 참고용이고 벤더 비용으로 쓰지 않는다",
    "tavonel_ko": "TAVONEL에는 list price가 없다(가격은 창업자 소관). 내부 원가는 벤더 가격 옆에 두지 않는다(FOLYNTA_CAMPAIGN_RESULTS.md:413)",
    "subject_judge_ko": "token × price snapshot. 지금 snapshot은 claude-opus-5, 2026-09-03 수집이라 7일 규칙을 넘는다. 실행 전에 실제 응답 model ID로 다시 받는다(이름으로 같은 모델이라고 가정하지 않는다). cache token이 있으면 cost_complete=false",
    "vendor_usage_ko": "응답이 사용량을 알려 주면(LandingAI total_credits, LlamaParse credits) 그것도 기록하고 둘 중 큰 값을 쓴다",
    "price_receipts": [
      {
        "price_point": "reducto_parse_default",
        "usd": 10,
        "snapshot": {
          "file": "competitor-protocol-receipts/web/reducto-pricing.html",
          "url": "https://reducto.ai/pricing",
          "sha256": "db2496594aabf5e779eec25e7826be12d8fbd359aba55f4672ff9498d264e667",
          "downloaded_utc": "2026-10-17T01:24:50.789Z"
        }
      },
      {
        "price_point": "llamaparse_agentic",
        "usd": 12.5,
        "snapshot": {
          "file": "competitor-protocol-receipts/web/llamaparse-docs-pricing.html",
          "url": "https://developers.llamaindex.ai/llamaparse/general/pricing/",
          "sha256": "2eabf853344060b989e7a6740447a18ef6ddbcf63bada2eeeb371a6511717d8b",
          "downloaded_utc": "2026-10-17T01:25:48.240Z"
        }
      },
      {
        "price_point": "unstructured_default",
        "usd": 15,
        "snapshot": {
          "file": "competitor-protocol-receipts/web/unstructured-pricing.html",
          "url": "https://unstructured.io/pricing",
          "sha256": "dcf420b91189d7ed0e14ecd5cbc9e3899721dffb643a3ea8480339396870d8bf",
          "downloaded_utc": "2026-10-17T01:24:55.572Z"
        }
      },
      {
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "usd": 10,
        "snapshot": {
          "file": "competitor-protocol-receipts/web/landingai-pricing.html",
          "url": "https://landing.ai/pricing-agentic-apis",
          "sha256": "a8cf10851a3622a3f3c8578edba63a8b832c275788046426f05dd7d2c716a084",
          "downloaded_utc": "2026-10-17T01:24:58.435Z"
        }
      },
      {
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "usd": 30,
        "snapshot": {
          "file": "competitor-protocol-receipts/web/landingai-credit-consumption.html",
          "url": "https://docs.landing.ai/dpt3/credit-consumption",
          "sha256": "64a6eeedb1339919031867b415ebef1bc9bec92f902e4700db273687e8254db8",
          "downloaded_utc": "2026-10-17T01:27:20.821Z"
        }
      }
    ],
    "rows": [
      {
        "corpus": "olmocr-bench",
        "price_point": "reducto_parse_default",
        "scenario": "base",
        "pages": 1787,
        "usd_per_1000_pages": 10,
        "usd": 17.87
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "reducto_parse_default",
        "scenario": "finalist_exact_three",
        "pages": 4593,
        "usd_per_1000_pages": 10,
        "usd": 45.93
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "llamaparse_agentic",
        "scenario": "base",
        "pages": 1787,
        "usd_per_1000_pages": 12.5,
        "usd": 22.34
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "llamaparse_agentic",
        "scenario": "finalist_exact_three",
        "pages": 4593,
        "usd_per_1000_pages": 12.5,
        "usd": 57.41
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "unstructured_default",
        "scenario": "base",
        "pages": 1787,
        "usd_per_1000_pages": 15,
        "usd": 26.81
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "unstructured_default",
        "scenario": "finalist_exact_three",
        "pages": 4593,
        "usd_per_1000_pages": 15,
        "usd": 68.9
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "base",
        "pages": 1787,
        "usd_per_1000_pages": 10,
        "usd": 17.87
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "finalist_exact_three",
        "pages": 4593,
        "usd_per_1000_pages": 10,
        "usd": 45.93
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "base",
        "pages": 1787,
        "usd_per_1000_pages": 30,
        "usd": 53.61
      },
      {
        "corpus": "olmocr-bench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "finalist_exact_three",
        "pages": 4593,
        "usd_per_1000_pages": 30,
        "usd": 137.79
      },
      {
        "corpus": "omnidocbench",
        "price_point": "reducto_parse_default",
        "scenario": "base",
        "pages": 2035,
        "usd_per_1000_pages": 10,
        "usd": 20.35
      },
      {
        "corpus": "omnidocbench",
        "price_point": "reducto_parse_default",
        "scenario": "finalist_exact_three",
        "pages": 5337,
        "usd_per_1000_pages": 10,
        "usd": 53.37
      },
      {
        "corpus": "omnidocbench",
        "price_point": "llamaparse_agentic",
        "scenario": "base",
        "pages": 2035,
        "usd_per_1000_pages": 12.5,
        "usd": 25.44
      },
      {
        "corpus": "omnidocbench",
        "price_point": "llamaparse_agentic",
        "scenario": "finalist_exact_three",
        "pages": 5337,
        "usd_per_1000_pages": 12.5,
        "usd": 66.71
      },
      {
        "corpus": "omnidocbench",
        "price_point": "unstructured_default",
        "scenario": "base",
        "pages": 2035,
        "usd_per_1000_pages": 15,
        "usd": 30.53
      },
      {
        "corpus": "omnidocbench",
        "price_point": "unstructured_default",
        "scenario": "finalist_exact_three",
        "pages": 5337,
        "usd_per_1000_pages": 15,
        "usd": 80.06
      },
      {
        "corpus": "omnidocbench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "base",
        "pages": 2035,
        "usd_per_1000_pages": 10,
        "usd": 20.35
      },
      {
        "corpus": "omnidocbench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "finalist_exact_three",
        "pages": 5337,
        "usd_per_1000_pages": 10,
        "usd": 53.37
      },
      {
        "corpus": "omnidocbench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "base",
        "pages": 2035,
        "usd_per_1000_pages": 30,
        "usd": 61.05
      },
      {
        "corpus": "omnidocbench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "finalist_exact_three",
        "pages": 5337,
        "usd_per_1000_pages": 30,
        "usd": 160.11
      },
      {
        "corpus": "parsebench",
        "price_point": "reducto_parse_default",
        "scenario": "base",
        "pages": 2462,
        "usd_per_1000_pages": 10,
        "usd": 24.62
      },
      {
        "corpus": "parsebench",
        "price_point": "reducto_parse_default",
        "scenario": "finalist_exact_three",
        "pages": 6618,
        "usd_per_1000_pages": 10,
        "usd": 66.18
      },
      {
        "corpus": "parsebench",
        "price_point": "llamaparse_agentic",
        "scenario": "base",
        "pages": 2462,
        "usd_per_1000_pages": 12.5,
        "usd": 30.78
      },
      {
        "corpus": "parsebench",
        "price_point": "llamaparse_agentic",
        "scenario": "finalist_exact_three",
        "pages": 6618,
        "usd_per_1000_pages": 12.5,
        "usd": 82.73
      },
      {
        "corpus": "parsebench",
        "price_point": "unstructured_default",
        "scenario": "base",
        "pages": 2462,
        "usd_per_1000_pages": 15,
        "usd": 36.93
      },
      {
        "corpus": "parsebench",
        "price_point": "unstructured_default",
        "scenario": "finalist_exact_three",
        "pages": 6618,
        "usd_per_1000_pages": 15,
        "usd": 99.27
      },
      {
        "corpus": "parsebench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "base",
        "pages": 2462,
        "usd_per_1000_pages": 10,
        "usd": 24.62
      },
      {
        "corpus": "parsebench",
        "price_point": "landingai_dpt3pro_priority_floor_0chars",
        "scenario": "finalist_exact_three",
        "pages": 6618,
        "usd_per_1000_pages": 10,
        "usd": 66.18
      },
      {
        "corpus": "parsebench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "base",
        "pages": 2462,
        "usd_per_1000_pages": 30,
        "usd": 73.86
      },
      {
        "corpus": "parsebench",
        "price_point": "landingai_dpt3pro_priority_4000chars",
        "scenario": "finalist_exact_three",
        "pages": 6618,
        "usd_per_1000_pages": 30,
        "usd": 198.54
      }
    ]
  },
  "publication": {
    "status": "proposed",
    "quoted_ko": "벤더나 제3자 보드의 숫자는 인용이다. URL·수집 UTC·저장 페이지 sha256·그들의 분모와 조건·비교 한계를 함께 적고(folynta-published-leaderboard-context 형식) '인용, 재현 아님'으로 표시한다. 우리 결과와 같은 열에 두지 않는다",
    "same_condition_ko": "우리가 같은 조건으로 돌린 결과만 해당한다. validateBenchmarkReceipt(record, \"result\")를 통과해야 하고, AT-4 필드(armId, systemUnderTest, vendorTermsSnapshotDigest)를 더한다",
    "no_cross_difference_ko": "인용과 우리 실행 사이의 차이는 계산하지도 게시하지도 않는다(예: 'TAVONEL 80.6 대 Reducto 72.97'은 corpus와 평가기가 달라 금지)",
    "third_party_board_ko": "ParseBench 등재 조건은 \"a self-serve API that any user can sign up for\"다. 오늘 selfService:false라서 등재 대상이 아니다",
    "competitor_names_ko": "공개 페이지의 경쟁사 이름은 지금 테스트가 막는다(prohibited-phrases.test.ts:102 외 3곳). 바꾸는 것은 FD-7·critic D-09이다. 이 파일은 그 테스트를 바꾸지 않는다",
    "sentence_templates_status": "proposed — FD-7 승인 전에는 어떤 문장도 게시하지 않는다",
    "sentence_templates_ko": {
      "AHEAD": "〈corpus@rev, 평가기 rev(+patch sha), N문서〉에서 TAVONEL 제품 경로(배포 〈ID〉, 〈날짜〉)는 〈벤더 구성, 날짜〉보다 M이 Δ(95% CI a–b) 높았다. — 같은 자리에 다른 모든 지표를 함께 싣는다",
      "WITHIN": "…에서 M의 차이는 ±δ 범위 안이었다(Δ, CI).",
      "BEHIND": "…에서 M이 Δ(CI) 낮았다. — 표·수식이 원인이면 '현재 제품은 표·수식을 추출하지 않는다(capabilities no_table_or_formula_extraction)'를 덧붙인다. 반드시 게시한다",
      "INCONCLUSIVE": "이 조건에서 차이는 입증되지 않았다.",
      "completion": "제공한 N개 중 n개가 출력을 냈다(완료율).",
      "quoted": "〈벤더〉는 〈날짜〉 〈출처〉에서 …라고 발표했다(분모, 조건; 우리가 재현하지 않음).",
      "general_better": "해당 축의 사전등록 1차 지표에서 실행된 모든 벤더 arm에 대해 AHEAD이고, BEHIND를 포함한 모든 지표를 같은 자리에 게시하고, corpus와 날짜로 범위를 한정하고, FD-7 승인을 받은 경우에만"
    },
    "forbidden_ko": [
      "더 정확하다",
      "업계 최고",
      "범위를 생략한 '경쟁사보다 낫다'",
      "동등하거나 더 낫다",
      "점 추정치만 내세우기",
      "완료율을 정확도라 부르기",
      "인용을 우리 결과와 빼거나 나누기",
      "BEHIND 숨기기·평균에 묻기"
    ]
  },
  "registry_mapping": {
    "target": "Foundation nextjs/lib/benchmark-registry.ts RECEIPT_FIELDS(21개) + AT-4(P2-21) 확장 필드",
    "at4_fields": {
      "armId": "arms.d_axis[].id 또는 arms.a_axis[].id",
      "systemUnderTest": "tavonel_live | tavonel_research | vendor",
      "vendorTermsSnapshotDigest": "arms.d_axis[].terms_snapshot.sha256 (벤더 arm만)"
    },
    "per_field_ko": {
      "datasetName": "corpora[].lock_copy.dataset_repository",
      "datasetVersion": "corpora[].lock_copy.dataset_revision",
      "corpusDigest": "corpora[].lock_copy.dataset_manifest_sha256",
      "denominator": "corpora[].N(문서) — 지표별 자기 분모 병기",
      "modelId": "D-T-live: OCR image digest와 reader id. 벤더: 응답에 나온 모델·버전 필드. 응답이 주지 않으면 채울 수 없다 → result 레코드를 만들지 않는다(이름으로 추정 금지). AT-4에서 notApplicable 허용 여부 결정",
      "modelRevision": "같은 원칙",
      "inputMode": "PDF 원본 바이트",
      "promptDigest": "벤더·D-T-live: notApplicable 후보(프롬프트 없음). A축: K26 prompt template sha",
      "configDigest": "요청 JSON digest(벤더) / 배포 구성 digest(D-T-live)",
      "compilerVersion": "D-T-live: Core v2 revision. 벤더: notApplicable",
      "worldDigest": "D-T-live: 컴파일된 world digest. 벤더: notApplicable",
      "hardware": "벤더: vendor_hosted",
      "gpu": "D-T-live: RunPod GPU 종류. 벤더: vendor_hosted",
      "runtime": "D-T-live: CDR·OCR·Core 버전. 벤더: API 버전",
      "priceSnapshot": "arms[].price_snapshot.sha256",
      "rawResultDigest": "평가기 입력 markdown 묶음의 sha256",
      "runReceiptDigest": "실행 receipt sha256",
      "date": "실행일",
      "metrics": "corpora[].metrics 전부",
      "comparisonBasis": "same_condition",
      "publishedFailures": "운영·의미 실패 전부"
    }
  },
  "corrections_vs_protocol_ko": [
    "§4.3 반복 '전체 1회 후 128문서 2회 더' → lock의 stratified_audit_runs 3을 따른다(FOLYNTA §5도 128 × 3회). §5 비용표의 768쪽 행과 FD-2 상한이 바뀐다",
    "§4.3 '채점 로직은 바꾸지 않는다' + olmOCR patch만 기재 → ParseBench 평가기에도 tracked patch 2a9f2ea7(watchdog: 구두점만 있는 서식 질의를 보수적 실패로 기록)이 있다. 모든 arm에 같게 적용하고 게시 문장에 patch sha를 적는다",
    "§4.5 판정 규칙의 WITHIN·BEHIND 겹침 → 순서 BEHIND > AHEAD > WITHIN > INCONCLUSIVE와 경계 벡터를 고정했다",
    "§4.2 D-T-live OCR image digest 0e916aa6 → F5C 기준 2026-10-15T23:37Z부터 8e6f6fa7이다. 미리 고정하지 않고 실행 시점에 읽는다(경쟁 §9의 미확인 항목 하나가 풀렸다)",
    "§4.7 subject·judge 가격 snapshot은 2026-09-03 claude-opus-5라 7일 규칙을 넘는다. 실행 전에 다시 받는다",
    "registry 필드 modelId는 '이름이 아닌 정확한 모델'을 요구한다. 벤더 응답이 모델·버전을 주지 않으면 same_condition 레코드를 만들 수 없다 → AT-4에서 처리해야 한다",
    "corpus N(1,403 / 1,651 / 2,078)은 lock과 같은 dataset_manifest_sha256을 적은 Arena coverage receipt에서 가져왔다. FOLYNTA 평가 artifact의 source_manifest_sha256은 lock 값과 다르다(다른 종류의 manifest로 보이며 확인하지 않았다)"
  ],
  "blocked_on": [
    "FD-1 약관",
    "FD-2 키·상한",
    "FD-3 corpus 권리",
    "FD-4 제품 arm 한도(A축)",
    "FD-6 δ·판정 규칙 승인과 봉인",
    "FD-7 경쟁사 이름·비교 문장",
    "FD-10 평가 tenant·GPU 상한",
    "AT-2·AT-3·AT-6·AT-7 harness(Core lane, phase 2 제외)",
    "P2-21(AT-4) registry 확장"
  ],
  "not_proven_ko": [
    "어떤 성능 우위나 열위도 측정하지 않았다",
    "δ 값은 보정되지 않았다. 경쟁 문서 §4.5의 제안값이고 근거가 된 corpus 측정이 없다",
    "벤더 기본 구성(Reducto /parse 기본 모델, Unstructured 기본 전략)이 무엇인지 확인하지 않았다",
    "약관 해석은 법률 의견이 아니다",
    "벤더 결과의 비결정성 크기"
  ],
  "sources": [
    {
      "id": "registry_lock",
      "kind": "file",
      "path": "benchmark/v6/dataset-registry.lock.yaml",
      "sha256": "aab092066d215782504933039f92e41fe4f71ebdf2b085912cc260f8f575a790",
      "use_ko": "corpus·평가기 revision의 단일 근거. self-check가 필드 단위로 대조한다"
    },
    {
      "id": "competitor_protocol",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/COMPETITOR-PROTOCOL-2026-10-17.md",
      "sha256": "f40eb532eb4a16dd4608e9afbbe01ab0e65e1a4dc90105f9446ef13ea49ae2e1",
      "use_ko": "이 파일이 기계 판독형으로 옮기는 원문(§4.2–4.9, FD-1–FD-10)"
    },
    {
      "id": "phase1_critic",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/PHASE1-CRITIC-2026-10-17.md",
      "sha256": "667010c53a226f980241fc61b3581112cabae954867affc35e24eebf3f8efa81",
      "use_ko": "lane P2-25 정의, 결정 D-09·D-10·D-30·D-31·D-34"
    },
    {
      "id": "performance_plan",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/PERFORMANCE-RESEARCH-PLAN.md",
      "sha256": "15b759fd42156b23bd34eeb7990ac0d2973346029aeadbb1f4749b485a718108",
      "use_ko": "vendor_comparison.v1 이름과 A축 +5pp 목표의 출처(:44-61)"
    },
    {
      "id": "web_receipts_manifest",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/competitor-protocol-receipts/WEB-RECEIPTS-MANIFEST.json",
      "sha256": "8b095f3801a545ce534ceef1ba3b4128e2b10032869a4d865bf1aeae384bb37c",
      "use_ko": "벤더 가격·약관·공개 주장 페이지 26개의 sha256과 수집 UTC"
    },
    {
      "id": "live_capabilities",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/competitor-protocol-receipts/live-capabilities-2026-10-17.json",
      "sha256": "e1e5a4207fe2ec2a823fff74e5c67c1cbf4cc23ea6548c7db9955b3e428ef7a5",
      "use_ko": "라이브 제품 한도 5 MiB / 80쪽, no_table_or_formula_extraction, readerPlan"
    },
    {
      "id": "gdp_limit_fit",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/competitor-protocol-receipts/GDP-LIMIT-FIT-2026-10-17.json",
      "sha256": "218c196c802572b13612cdeb9c4ce12b5638553d39c578491c29d0e4db45e4b4",
      "use_ko": "GDP 과제의 5 MiB·18 MiB 한도 적합 수"
    },
    {
      "id": "k26_prereg",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/K26-PREREG.json",
      "sha256": "f70d51c41d6b7f6580f172082d4b91d53dccfe0881ecd7874c54028aeab79b2f",
      "use_ko": "A축 A-native·A-T 정의와 epoch 집계 규칙"
    },
    {
      "id": "k26_dev_lock",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/K26-DEV-LOCK.json",
      "sha256": "b47603d4facbe0ee439e16f7082c1a9ab99ca93eb19a4dab4a4c7943e96bfa7e",
      "use_ko": "A축 subject·judge surface와 prompt template sha"
    },
    {
      "id": "f_decisions",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/F-DECISIONS-20261015.md",
      "sha256": "0489fe78f8eadd3eafcbb1088ad535fa7bf3260c3c1c4b881240bb62ffbb1be6",
      "use_ko": "F1(GDP 외부 전송 금지), F6(8개 기준 구속), F7(18 MiB arm)"
    },
    {
      "id": "gdp_paid_receipt",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/GDP-PAID-20261015-RECEIPT.md",
      "sha256": "d461b46a18ad02736e3488accc1305d52cc468a7077d6d9666fbfdfecf1f854c",
      "use_ko": "F6 8개 기준의 원문(§2)"
    },
    {
      "id": "f5c_image_rollout",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/resume-20261015/gdp-20261015/F5C-IMAGE-ROLLOUT-RECEIPT.json",
      "sha256": "817db99ec9044af069888d323db9d687d93e318f7c7f39ae01ce87d3f8481399",
      "use_ko": "OCR endpoint image가 0e916aa6에서 8e6f6fa7로 바뀐 기록(2026-10-15T23:37Z, version 21)"
    },
    {
      "id": "folynta_results",
      "kind": "file",
      "path": "docs/evidence/FOLYNTA_CAMPAIGN_RESULTS.md",
      "sha256": "850058579de3caccb88b123fd43cfb05d348bf104dfee31528cb97384c249ebb",
      "use_ko": "corpus 문서 수, 반복 감사 128×3, absent 검사 경고(:150-154)"
    },
    {
      "id": "arena_corpus_coverage",
      "kind": "file",
      "path": "research/model_arena_20260903/reports/full_compare_20260905/corpus_coverage_5132.json",
      "sha256": "44321d2dbadb0e855e76e8c49dd443a2f91c612968fd2da6e18a7b4eef1f427a",
      "use_ko": "corpus별 sample_count를 lock과 같은 dataset_manifest_sha256에 묶는 receipt"
    },
    {
      "id": "olmocr_eval_summary",
      "kind": "file",
      "path": "docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__olmocr-bench__evaluation-summary.json",
      "sha256": "4d75ae96e70c7c1c425b991df0f1c356ec6393e73914aaed27f5f54b0048a559",
      "use_ko": "olmOCR 평가기 tracked patch e93e8b7b와 80.6 정의(유형 8개 평균)"
    },
    {
      "id": "parsebench_eval_summary",
      "kind": "file",
      "path": "docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__parsebench__evaluation-summary.json",
      "sha256": "22cf5bf183ef875338de8442a6d3c5c3dca89ae52346b7f36a07b9332471a228",
      "use_ko": "ParseBench 평가기 tracked patch 2a9f2ea7과 watchdog 정책"
    },
    {
      "id": "omnidoc_metric_result",
      "kind": "file",
      "path": "docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__omnidocbench__repeat-1__metric-result.json",
      "sha256": "bab2df526db11fbcd87b1a026a223d8b8a7ce03ba1b4f99a9899b4c34f4c731a",
      "use_ko": "OmniDocBench 결과. 평가기 patch 기록 필드가 없다"
    },
    {
      "id": "leaderboard_context_format",
      "kind": "file",
      "path": "docs/evidence/artifacts/folynta-published-leaderboard-context-2026-08-08.json",
      "sha256": "5ca45e22fb737840860da3a8d202937b88a4c8ff18ef405cf2da50110ca65d84",
      "use_ko": "인용(quoted) receipt 형식"
    },
    {
      "id": "opus_price_snapshot",
      "kind": "file",
      "path": "research/model_arena_20260903/arena/opus/price_snapshot.json",
      "sha256": "dc228bec91f8fcf84fcc5a200fe015a89e75daf2c5abe210d66019156104e2d2",
      "use_ko": "subject·judge token 가격 snapshot(claude-opus-5, 2026-09-03)"
    },
    {
      "id": "selfcheck_script",
      "kind": "file",
      "path": "outputs/tavonel-research-replan-20261013/ux-program-20261017/VENDOR-COMPARISON-PREREG.selfcheck.js",
      "sha256": "f7d6d50eeac8d904d6e0040b932e7f87e3ffb8b81b3d74c08aa7c048b52cced7",
      "use_ko": "이 파일의 수락 시험"
    },
    {
      "id": "foundation_benchmark_registry",
      "kind": "git_ref",
      "repo": "D:/CodexProjects/handoff-1002/fnd-UX",
      "commit": "4c80bb3028fb73dc88e929c25baf0bec97bee4e7",
      "path": "nextjs/lib/benchmark-registry.ts",
      "blob_sha256": "e4d4d6e0dcf570dee01e38c6f65efa9e2689f8b52c3e503110677d32cb3e255f",
      "verified_by": "git show 4c80bb30:nextjs/lib/benchmark-registry.ts | sha256sum (2026-10-17)",
      "use_ko": "RECEIPT_FIELDS 21개와 comparisonBasis. self-check는 git을 쓰지 않으므로 바이트 검증 대상이 아니다"
    },
    {
      "id": "foundation_registry_records",
      "kind": "git_ref",
      "repo": "D:/CodexProjects/handoff-1002/fnd-UX",
      "commit": "4c80bb3028fb73dc88e929c25baf0bec97bee4e7",
      "path": "nextjs/lib/benchmark-registry.records.json",
      "use_ko": "records: [] (오늘 registry 행 0개)"
    }
  ],
  "self_check": {
    "script": "VENDOR-COMPARISON-PREREG.selfcheck.js",
    "command": "node VENDOR-COMPARISON-PREREG.selfcheck.js",
    "checks_ko": [
      "schema·status DRAFT_PROPOSED·미봉인·벤더 실행 불가",
      "sidecar sha 일치",
      "lock 파일 sha와 public_core 3개 corpus의 모든 필드·policy 일치",
      "N이 lock과 같은 manifest를 적은 receipt와 일치",
      "평가기 patch가 lock commit의 artifact와 일치",
      "δ가 전부 proposed",
      "판정 벡터가 규칙과 일치",
      "비용 행 재계산",
      "file 출처 바이트 불변",
      "음성 시험 11건이 각자의 코드로 거절됨"
    ]
  }
}
```
<!-- END VERBATIM DRAFT -->
