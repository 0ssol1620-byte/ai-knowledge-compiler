# 웹사이트 게시용 클레임 팩

이 문서는 캠페인 증거 영수증에서 자동 생성됩니다. 수치를 여기서 직접 고치지 마십시오.

## 사용법

- status가 approved인 항목은 numbers를 그대로 사용합니다.
- conditional 항목은 conditions를 함께 표기할 때만 사용합니다.
- withheld 항목은 게시하지 않습니다. why_withheld가 이유입니다.
- must_say와 forbidden은 문구 검토 기준입니다.
- 수치를 바꾸려면 이 파일이 아니라 근거 영수증을 다시 생성하십시오.

## 공통 규칙

- 완주율과 정확도를 같은 지표처럼 제시하지 않습니다.
- 모든 비율에는 분모를 함께 표기합니다.
- 우리가 실행하지 않은 경쟁 제품의 수치는 인용임을 명시합니다.
- 원가와 판매 가격을 혼용하지 않습니다.

## 게시 가능 (11건)

### 공개 벤치마크 3종, 5,132개 문서를 공식 평가기로 측정

`corpus-scale` — 5,132 documents across three public benchmarks, scored by the official evaluators

```json
{
  "documents": 5132,
  "benchmarks": [
    "olmocr-bench",
    "omnidocbench",
    "parsebench"
  ],
  "per_benchmark": {
    "olmocr-bench": 1403,
    "omnidocbench": 1651,
    "parsebench": 2078
  }
}
```

**반드시 함께 표기**: 5,132은 평가한 문서 수이며 처리 용량이나 고객 처리량이 아닙니다. 세 벤치마크는 공개 데이터셋이고 각 벤치마크의 문서 수를 함께 표기하십시오.

**Must accompany the number**: 5,132 is the number of documents evaluated, not a capacity or a customer throughput figure. Name the three public benchmarks and their individual counts alongside the total.

- 금지 표현: 5,132개 문서를 처리할 수 있습니다 (규모를 처리 용량으로 환언하는 표현)
- 금지 표현: 고객 문서 5,132건 (공개 벤치마크를 고객 실적으로 제시하는 표현)

근거: `docs/evidence/artifacts/folynta-campaign-completion-ledger-2026-08-08.json`

### 처리 완주율 99.98%

`completion-rate` — 99.98% of documents produced output

```json
{
  "resolved": 5131,
  "planned": 5132,
  "unresolved": 1,
  "completion_fraction": 0.9998051441932969
}
```

**반드시 함께 표기**: 완주율은 출력이 생성된 비율이며 정확도가 아닙니다. 두 수치를 같은 문장에 쓸 때는 반드시 구분해 표기하십시오.

**Must accompany the number**: This is the share of documents that produced output. It is not accuracy. Where both figures appear, label which is which.

- 금지 표현: 정확도 99.98%
- 금지 표현: 정확도 100%에 가까움
- 금지 표현: 완주율을 정확도로 환언하는 모든 표현

근거: `docs/evidence/artifacts/folynta-campaign-completion-ledger-2026-08-08.json`

### 실제로 실패한 문서 중 99.94%를 복구

`recovery-rate` — 99.94% of documents that actually failed were recovered

```json
{
  "needed_recovery": 1797,
  "recovered": 1796,
  "rate": 0.9994435169727324,
  "attempted_but_never_recovered": 1,
  "unresolved_and_never_attempted": 0,
  "required_more_than_one_round": 11
}
```

**반드시 함께 표기**: 분모는 전체 코퍼스가 아니라 실제로 실패한 문서 수입니다. 분모를 밝히지 않으면 완주율과 혼동됩니다.

**Must accompany the number**: The denominator is the documents that actually failed, not the whole corpus. Without the denominator this reads as the completion rate.


근거: `docs/evidence/artifacts/folynta-campaign-completion-ledger-2026-08-08.json`

### 복구 레인을 끄면 동일 파이프라인의 공식 점수가 80.6에서 53.7로 떨어집니다

`recovery-contribution-olmocr` — Disabling only the recovery lane drops the same pipeline from 80.6 to 53.7

```json
{
  "benchmark": "olmOCR-Bench",
  "with_recovery": 80.6,
  "without_recovery": 53.7,
  "with_recovery_ci95": [
    79.62,
    81.57
  ],
  "without_recovery_ci95": [
    52.62,
    54.93
  ],
  "rule_failures_with": 1276,
  "rule_failures_without": 3818
}
```

**반드시 함께 표기**: 모델, 평가기 리비전, 코퍼스, 설정을 고정하고 복구 산출물만 제거한 단일 변수 비교입니다.

**Must accompany the number**: A single-variable comparison: model, evaluator revision, corpus and settings are identical, and only the recovery output was removed.


근거: `docs/evidence/artifacts/folynta-recovery-accuracy-counterfactual-olmocr-2026-08-08.json`

### 복구가 없으면 ParseBench 규칙 위반이 2.1배로 늘어납니다

`recovery-contribution-parsebench` — Without recovery, ParseBench rule failures more than double

```json
{
  "rule_failures_with": 39413,
  "rule_failures_without": 82163,
  "content_faithfulness_with": 0.8376,
  "content_faithfulness_without": 0.5243,
  "table_grits_with": 0.9017,
  "table_grits_without": 0.5321,
  "layout_micro_rule_pass_rate_with": 0.7566,
  "layout_micro_rule_pass_rate_without": 0.7704,
  "layout_rules_evaluated_with": 40287.0,
  "layout_rules_evaluated_without": 23025.0
}
```

**반드시 함께 표기**: 절대 위반 건수로 표기하십시오. 레이아웃 그룹의 통과율은 복구를 끄면 오히려 올라가는데(0.757 → 0.770), 내용이 없는 문서는 채점할 요소 자체가 없어 분모가 40,287에서 23,025로 줄기 때문입니다. 비율만 인용하면 복구를 끄는 편이 나아 보입니다.

**Must accompany the number**: Quote the absolute failure counts. The layout group's pass rate actually rises when recovery is removed (0.757 to 0.770) because an empty document has no elements to score, shrinking the denominator from 40,287 to 23,025. A rate quoted alone makes no-recovery look better.

- 금지 표현: 레이아웃 통과율을 복구 효과의 근거로 인용하는 표현
- 금지 표현: 규칙 위반 감소를 비율로만 제시하고 분모 변화를 생략하는 표현

근거: `['docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__parsebench__evaluation-summary.json', 'docs/evidence/artifacts/folynta-counterfactual-no-recovery-parsebench-2026-08-08__evaluation-summary.json']`

### 복구가 없으면 OmniDocBench 본문 편집거리가 4.5배로 악화됩니다

`recovery-contribution-omnidocbench` — Without recovery, OmniDocBench text edit distance degrades 4.5x

```json
{
  "text_edit_distance_with": 0.0583,
  "text_edit_distance_without": 0.264,
  "reading_order_with": 0.1408,
  "reading_order_without": 0.3286,
  "table_teds_with": 0.9257,
  "table_teds_without": 0.7136
}
```

**반드시 함께 표기**: 편집거리는 낮을수록 좋고, TEDS는 높을수록 좋습니다.

**Must accompany the number**: Lower edit distance is better; higher TEDS is better.


근거: `['docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__omnidocbench__repeat-1__metric-result.json', 'docs/evidence/artifacts/folynta-counterfactual-no-recovery-omnidocbench-2026-08-08__repeat-1__metric-result.json']`

### 공식 벤치마크 정확도 80.6%

`benchmark-accuracy` — 80.6% on the official benchmark

```json
{
  "benchmark": "olmOCR-Bench",
  "overall_percent": 80.6,
  "confidence_interval_95": [
    79.62,
    81.57
  ],
  "checks_passed": 7137,
  "checks_total": 8413,
  "documents_with_at_least_one_failure_percent": 72.3
}
```

**반드시 함께 표기**: 이 점수는 적대적으로 설계된 개별 검사 8,413개의 통과율이며, 공개 리더보드 최상위도 83.1입니다. 비교 기준은 100이 아닙니다. 문서의 72.3%에는 최소 하나의 오류가 있으므로 무결성을 암시해서는 안 됩니다.

**Must accompany the number**: This is the pass rate over 8,413 adversarially chosen checks; the top published system scores 83.1, so the reference point is not 100. 72.3% of documents carry at least one failure, so nothing here should imply flawless output.

- 금지 표현: 정확도 100% / 무오류 / 완벽한 추출
- 금지 표현: 80.6%를 단독 헤드라인으로 제시하고 유형별 편차를 생략하는 구성

근거: `docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__olmocr-bench__evaluation-summary.json`

### 본문 문자 일치율 94.2%, 표 구조 정확도 95.5%

`customer-facing-fidelity` — 94.2% character-level text fidelity, 95.5% table structure accuracy

```json
{
  "text_character_match_percent": 94.2,
  "reading_order_match_percent": 85.9,
  "table_structure_percent": 95.5,
  "table_full_percent": 92.6
}
```

**반드시 함께 표기**: 이 수치는 벤치마크 검사 통과율(80.6%)과 다른 척도입니다. 같은 화면에 둘 다 실을 때는 무엇을 재는 값인지 구분해 표기하십시오.

**Must accompany the number**: These are a different measure from the 80.6% check pass rate. If both appear on one page, label what each one measures.


근거: `docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__omnidocbench__repeat-1__metric-result.json`

### 문서 유형별 정확도를 공개합니다

`accuracy-by-document-type` — Accuracy published per document type, not as one blended average

```json
[
  {
    "label_ko": "표준 디지털 문서",
    "label_en": "Standard digital documents",
    "accuracy_percent": 99.0,
    "checks_passed": 1380,
    "checks_total": 1394,
    "benchmark_slice": "baseline"
  },
  {
    "label_ko": "머리말·꼬리말이 있는 문서",
    "label_en": "Documents with headers and footers",
    "accuracy_percent": 95.0,
    "checks_passed": 722,
    "checks_total": 760,
    "benchmark_slice": "headers_footers.jsonl"
  },
  {
    "label_ko": "표 중심 문서",
    "label_en": "Table-heavy documents",
    "accuracy_percent": 88.5,
    "checks_passed": 904,
    "checks_total": 1022,
    "benchmark_slice": "table_tests.jsonl"
  },
  {
    "label_ko": "학술 논문 (수식 포함)",
    "label_en": "Academic papers with equations",
    "accuracy_percent": 85.6,
    "checks_passed": 2505,
    "checks_total": 2927,
    "benchmark_slice": "arxiv_math.jsonl"
  },
  {
    "label_ko": "다단 레이아웃",
    "label_en": "Multi-column layouts",
    "accuracy_percent": 81.2,
    "checks_passed": 718,
    "checks_total": 884,
    "benchmark_slice": "multi_column.jsonl"
  },
  {
    "label_ko": "작은 글씨의 장문 문서",
    "label_en": "Long documents in small type",
    "accuracy_percent": 79.4,
    "checks_passed": 351,
    "checks_total": 442,
    "benchmark_slice": "long_tiny_text.jsonl"
  },
  {
    "label_ko": "오래된 스캔본 (수식 포함)",
    "label_en": "Old scans containing equations",
    "accuracy_percent": 79.3,
    "checks_passed": 363,
    "checks_total": 458,
    "benchmark_slice": "old_scans_math.jsonl"
  },
  {
    "label_ko": "저품질 스캔본",
    "label_en": "Low-quality scans",
    "accuracy_percent": 36.9,
    "checks_passed": 194,
    "checks_total": 526,
    "benchmark_slice": "old_scans.jsonl"
  }
]
```

**반드시 함께 표기**: 유형별 편차가 99.0%에서 36.9%까지 벌어집니다. 단일 평균만 제시하면 저품질 스캔본 고객에게 잘못된 기대를 심습니다. 저품질 스캔 구간은 반드시 함께 표기하십시오.

**Must accompany the number**: The spread runs from 99.0% to 36.9%. Publishing only the average sets the wrong expectation for anyone processing degraded scans, so the low-quality scan row must always be shown.

- 금지 표현: benchmark_slice 값(old_scans.jsonl 등)을 화면에 그대로 노출
- 금지 표현: 저품질 스캔 행을 뺀 부분 표

근거: `docs/evidence/artifacts/folynta-mineru344-public-core-official-evaluations-r1-2026-08-04__olmocr-bench__evaluation-summary.json`

### 추출에서 끝나지 않고 지식 아키텍처까지 컴파일합니다

`product-pipeline` — The pipeline does not stop at extraction; it compiles a knowledge architecture

```json
{
  "stages": [
    "사전 분류·난이도 판정",
    "경로 선택",
    "추출",
    "정규 중간표현",
    "아키텍처 설계",
    "내보내기"
  ],
  "stages_en": [
    "preflight classification",
    "route selection",
    "extraction",
    "canonical intermediate representation",
    "architecture planning",
    "export"
  ],
  "builtin_blueprints": [
    "corporate-filings",
    "course-materials",
    "generic-mixed-corpus",
    "legal-contracts",
    "personal-knowledge",
    "research-library",
    "technical-documentation"
  ],
  "export_targets": [
    "obsidian",
    "ontology",
    "neo4j",
    "rag"
  ]
}
```

**반드시 함께 표기**: 이 단계들은 코드로 구현돼 있으나, 추출 단계와 달리 공개 벤치마크 점수가 존재하지 않습니다. 정확도 수치를 이 단계에 붙이지 마십시오. 제시 가능한 근거는 compilation-guarantees의 구조적 보증입니다.

**Must accompany the number**: These stages are implemented, but unlike extraction they have no public benchmark score. Do not attach an accuracy figure to them; the supportable evidence is the structural guarantees claim.

- 금지 표현: 이 단계들에 대한 정확도·품질 백분율 표기

근거: `['packages/domain-packs/src/akc_domain_packs/blueprints.py', 'packages/exporters/src/akc_exporters/vault.py', 'packages/exporters/src/akc_exporters/knowledge_package.py', 'docs/evidence/artifacts/folynta-knowledge-compilation-properties-2026-08-08.json']`

### 산출물의 구조적 보증: 재현 가능한 아키텍처, 미해결 링크 0건, 병합 시 무손실

`compilation-guarantees` — Structural guarantees: reproducible architecture, no unresolved links, no silent loss on merge

```json
{
  "documents_exercised": 1000,
  "blueprints": 7,
  "architecture_repeats": 5,
  "broken_links_in_output": 0,
  "merge_policies_tested": 5,
  "files_lost_silently": 0
}
```

**반드시 함께 표기**: 이 보증은 산출물의 구조에 관한 것이며 추출된 텍스트의 정확성과는 별개 지표입니다.

**Must accompany the number**: These guarantees describe the structure of the compiled output. They are a separate measure from whether the extracted text is correct.


근거: `docs/evidence/artifacts/folynta-knowledge-compilation-properties-2026-08-08.json`


## 조건부 게시 (2건)

### 공개 리더보드 상위권

`leaderboard-position` — Competitive on the public leaderboard

```json
{
  "our_score": 80.6,
  "published_top": 83.1,
  "published_reference_rows": {
    "Chandra OCR 0.1.0": 83.1,
    "olmOCR v0.4.0": 82.4,
    "PaddleOCR-VL": 80.0,
    "Mistral OCR API": 72.0
  }
}
```

- 조건: 리더보드 행은 공개 자료 인용이며 우리가 재현 검증한 값이 아닙니다.
- 조건: 우리가 실행한 기반 모델의 버전이 리더보드에 실린 행과 다릅니다. 특정 경쟁 제품을 몇 점 이겼다는 문장은 사용할 수 없습니다.
- 조건: 평가기 체크아웃이 공식 저장소의 포크이며 Windows 경로 정규화 패치가 적용돼 있습니다. 채점 로직은 변경되지 않았습니다.
- 금지 표현: 우리가 <경쟁사>보다 N점 높습니다
- 금지 표현: 업계 1위 / 최고 정확도

근거: `docs/evidence/artifacts/folynta-published-leaderboard-context-2026-08-08.json`

### 1,000페이지당 GPU 원가 $1.23

`cost-per-page` — $1.23 of GPU cost per 1,000 pages

```json
{
  "gpu_cost_per_1000_pages_healthy": 1.23,
  "gpu_cost_per_1000_pages_including_failures": 5.92,
  "throughput_pages_per_pod_hour": 600
}
```

- 조건: 이것은 GPU 원가이며 판매 가격이 아닙니다. 엔지니어링, 오케스트레이션, 스토리지, 전송, 지원, 마진이 포함돼 있지 않습니다.
- 조건: 경쟁사의 소매가와 나란히 놓으면 성립하지 않는 비교가 됩니다.
- 금지 표현: 경쟁사 대비 N배 저렴 (원가와 소매가를 비교하는 모든 표현)

근거: `docs/evidence/artifacts/folynta-measured-gpu-cost-2026-08-08.json`


## 게시 불가 (2건)

### (측정 미완료) 대상 지정 품질 재시도의 정확도 개선폭

`quality-retry-improvement` — (not yet measured) accuracy gain from the targeted quality retry

**게시 불가 사유**: 재시도와 무회귀 수용 게이트가 아직 실행되지 않았습니다. 측정 전에는 어떤 개선 수치도 웹사이트에 실을 수 없습니다.

**해제 조건**: quality retry + official re-evaluation + no-regression gate complete

### (기각됨) 정답지 없이 저품질 문서를 자동 선별

`blind-quality-detection` — (rejected) selecting low-quality documents without ground truth

```json
{
  "hypothesis_supported": false,
  "corpus_cases": 5116
}
```

**게시 불가 사유**: 구현하고 같은 코퍼스에서 측정한 결과, 무작위 선택보다 낮은 실패 질량을 회수했고 예측 길이만으로 정렬하는 무탐지 기준선보다도 낮았습니다. 제품 기능으로 광고할 근거가 없습니다.


근거: `docs/evidence/artifacts/folynta-blind-quality-detection-2026-08-08.json`

