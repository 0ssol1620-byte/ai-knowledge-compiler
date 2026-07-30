import type {
  CanonicalBlock,
  PageSummary,
  PreflightEstimate,
  ProjectSummary,
  ReviewItem,
} from "@/lib/types";

const documentId = "doc_demo_research";
const versionId = "dver_demo_1";
const hash = "3f112ad9a0cfc4bf84d7b37678159c58aeb42c53d71497af88b5c30c9f1a73c2";

function source(pageIndex: number, bbox1000: [number, number, number, number]) {
  return [
    {
      document_id: documentId,
      document_version_id: versionId,
      page_index: pageIndex,
      page_number: pageIndex + 1,
      bbox1000,
      source_sha256: hash,
    },
  ];
}

export const demoBlocks: CanonicalBlock[] = [
  {
    id: "blk_title",
    order: 1,
    type: "title",
    source_text: "검색 증강 생성 시스템의 근거 충실도 평가",
    markdown: "# 검색 증강 생성 시스템의 근거 충실도 평가",
    origin: "native_extracted",
    content_layer: "structured",
    source_refs: source(7, [112, 94, 882, 158]),
    confidence: 0.99,
    quality_flags: [],
    revision: 1,
  },
  {
    id: "blk_heading",
    order: 2,
    type: "heading",
    source_text: "4.2 실험 결과",
    markdown: "## 4.2 실험 결과",
    origin: "rule_reconstructed",
    content_layer: "structured",
    source_refs: source(7, [106, 194, 452, 240]),
    confidence: 0.96,
    quality_flags: [],
    revision: 1,
  },
  {
    id: "blk_paragraph",
    order: 3,
    type: "paragraph",
    source_text:
      "근거 검증 단계를 적용한 구성은 기준 구성보다 unsupported claim 비율을 3.8%에서 1.1%로 감소시켰다. 모든 수치는 세 번의 독립 실행 평균이다.",
    markdown:
      "근거 검증 단계를 적용한 구성은 기준 구성보다 unsupported claim 비율을 **3.8%에서 1.1%로 감소**시켰다. 모든 수치는 세 번의 독립 실행 평균이다.",
    origin: "ocr_extracted",
    content_layer: "structured",
    source_refs: source(7, [108, 258, 892, 364]),
    confidence: 0.94,
    quality_flags: [],
    revision: 2,
  },
  {
    id: "blk_table",
    order: 4,
    type: "table",
    source_text:
      "구성 근거 충실도 Unsupported claim 기준 0.86 3.8% 검증 적용 0.94 1.1%",
    markdown:
      "| 구성 | 근거 충실도 | Unsupported claim |\n|---|---:|---:|\n| 기준 | 0.86 | 3.8% |\n| 검증 적용 | 0.94 | 1.1% |",
    origin: "ocr_extracted",
    content_layer: "structured",
    source_refs: source(7, [112, 402, 888, 644]),
    confidence: 0.89,
    quality_flags: ["numeric_cross_check_required"],
    revision: 1,
  },
  {
    id: "blk_summary",
    order: 5,
    type: "paragraph",
    source_text:
      "결과 기반 검증은 unsupported claim을 줄였으며, 개선 폭은 세 번의 실행 평균으로 교차 검증됐다.",
    markdown:
      "> [!summary] 검증 가능한 요약\n> 결과 기반 검증은 unsupported claim을 줄였으며, 개선 폭은 표 3의 세 번 실행 평균으로 뒷받침된다.",
    origin: "ai_summarized",
    content_layer: "knowledge",
    source_refs: source(7, [108, 258, 892, 644]),
    confidence: 0.92,
    quality_flags: [],
    revision: 1,
  },
];

export const demoPages: PageSummary[] = Array.from(
  { length: 18 },
  (_, index) => {
    const pageNumber = index + 1;
    const isReview = pageNumber === 8 || pageNumber === 14;
    return {
      id: `page_${pageNumber}`,
      page_number: pageNumber,
      status: isReview
        ? "needs_review"
        : pageNumber < 16
          ? "completed"
          : "ocr_running",
      route_profile:
        pageNumber % 5 === 0
          ? "parse_precision_v1"
          : pageNumber % 3 === 0
            ? "parse_balanced_v1"
            : "native_v1",
      route_label:
        pageNumber % 5 === 0
          ? "Precision"
          : pageNumber % 3 === 0
            ? "OCR"
            : "Native",
      quality_state: isReview ? "review" : "verified",
      blocks: pageNumber === 8 ? demoBlocks : [],
    };
  },
);

export const demoReviews: ReviewItem[] = [
  {
    id: "rev_numeric_8",
    severity: "high",
    category: "number_mismatch",
    message:
      "두 후보 결과에서 비율이 일치하지 않습니다. 원본 표를 확인해 주세요.",
    page_id: "page_8",
    block_id: "blk_table",
    status: "open",
    candidates: [
      { engine: "native", value: "1.1%" },
      { engine: "paddleocr-vl-1.6", value: "1.7%" },
    ],
  },
  {
    id: "rev_table_14",
    severity: "medium",
    category: "merged_cell",
    message: "병합 셀이 감지되어 HTML/CSV sidecar가 함께 생성됩니다.",
    page_id: "page_14",
    status: "open",
  },
];

export const demoEstimate: PreflightEstimate = {
  total_pages: 184,
  native_pages: 127,
  visual_pages: 49,
  precision_candidate_pages: 8,
  tables: 32,
  formulas: 18,
  figures: 41,
  credit_min: 263,
  credit_max: 318,
  third_party_model_api: false,
  expected_duration_min: 6,
  expected_duration_max: 11,
};

export const demoProjects: ProjectSummary[] = [
  {
    id: "project_research",
    name: "RAG 근거 충실도 연구",
    description: "논문 12개를 출처 추적이 가능한 Literature Vault로 컴파일",
    document_count: 12,
    review_count: 2,
    status: "processing",
    updated_at: "2026-07-29T06:42:00Z",
  },
  {
    id: "project_manual",
    name: "운영 매뉴얼 지식베이스",
    description: "제품 매뉴얼과 장애 대응 절차의 RAG 패키지",
    document_count: 38,
    review_count: 0,
    status: "ready",
    updated_at: "2026-07-28T10:12:00Z",
  },
  {
    id: "project_study",
    name: "통계학 학습 Vault",
    description: "강의자료와 교재를 개념·공식·예제로 재구성",
    document_count: 7,
    review_count: 5,
    status: "attention",
    updated_at: "2026-07-26T04:25:00Z",
  },
];
