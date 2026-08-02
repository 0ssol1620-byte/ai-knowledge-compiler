import type { StructaraPage, StructaraSection } from "@/lib/structara-content";

const page = (
  path: string,
  family: StructaraPage["family"],
  label: string,
  title: string,
  intro: string,
  thesis: string,
  sections: readonly StructaraSection[],
  primaryAction: StructaraPage["primaryAction"] = {
    label: "지식 시스템 구축하기",
    href: "/signup",
  },
  secondaryAction?: StructaraPage["secondaryAction"],
): StructaraPage => ({
  path,
  family,
  label,
  title,
  intro,
  thesis,
  sections,
  primaryAction,
  secondaryAction,
});

export const PUBLIC_PAGES_KO: Record<string, StructaraPage> =
  Object.fromEntries(
    [
      page(
        "/product",
        "product",
        "제품",
        "원본 파일을 지능형 지식 시스템으로 전환합니다.",
        "하나의 추적 가능한 워크플로에서 지식을 이해하고, 검증하고, 연결하고, 활용합니다.",
        "분리된 도구 모음이 아니라 처음부터 끝까지 이어지는 하나의 컴파일러입니다.",
        [
          {
            title: "수집",
            body: "파일, 폴더, 배치 또는 API 작업을 정책이 적용된 프로젝트로 가져옵니다.",
            items: ["파일과 폴더", "배치와 API", "보존 정책"],
          },
          {
            title: "구조화",
            body: "레이아웃, 표, 수식, 그림과 읽기 순서를 복원합니다.",
            items: ["네이티브 추출", "OCR 라우팅", "문서 계층 구조"],
          },
          {
            title: "검증",
            body: "중요한 모든 결과를 원본 페이지, 블록, 바운딩 박스로 되돌아가 확인할 수 있게 합니다.",
            items: ["원본 링크", "무결성 항목", "숫자 차이"],
          },
          {
            title: "컴파일",
            body: "지식 노트, 엔티티, 관계, 콘텐츠 맵과 이식 가능한 패키지를 생성합니다.",
            items: ["지식 노트", "엔티티 그래프", "콘텐츠 맵"],
          },
          {
            title: "활용",
            body: "동일한 검증 지식을 사람과 AI의 워크플로로 전달합니다.",
            items: ["Markdown", "Obsidian", "RAG와 JSON-LD"],
          },
        ],
        { label: "Convert 살펴보기", href: "/product/convert" },
        { label: "전체 데모 보기", href: "/demo/dart" },
      ),
      page(
        "/product/convert",
        "product",
        "변환",
        "정돈된 Markdown은 끝이 아니라 시작입니다.",
        "문서 계층, 표, 그림과 원본 위치를 보존하면서 PDF, 스캔, Office 파일과 이미지를 변환합니다.",
        "가능하면 네이티브로, 페이지가 요구할 때는 정밀하게 처리합니다.",
        [
          {
            title: "가능하면 네이티브로",
            body: "이미 텍스트가 포함된 문서는 불필요한 OCR 없이 원래 구조를 유지합니다.",
          },
          {
            title: "필요할 때 정밀하게",
            body: "스캔, 왜곡, 복잡한 표는 자동으로 정밀 처리 경로로 이동합니다.",
          },
          {
            title: "출력 계층",
            body: "Raw, Structured, Knowledge 계층은 서로 구분되며 각각 확인할 수 있습니다.",
            items: [
              "제목",
              "문단",
              "목록",
              "표",
              "그림",
              "수식",
              "각주",
              "인용",
            ],
          },
        ],
        { label: "샘플 변환하기", href: "/demo/dart" },
        { label: "지원 형식 보기", href: "/developers/docs" },
      ),
      page(
        "/product/verify",
        "product",
        "검증",
        "추출 결과를 믿지 말고 검증하세요.",
        "Markdown 문장, 지표 또는 표 셀에서 언제든 그 결과를 만든 원본으로 돌아갈 수 있습니다.",
        "Evidence는 제품의 핵심 화면입니다.",
        [
          {
            title: "원본 추적성",
            body: "페이지, 블록, 바운딩 박스와 원본 해시가 출력과 함께 이동합니다.",
          },
          {
            title: "자율 무결성",
            body: "숫자, 날짜, 단위, 표와 누락 콘텐츠를 영향도에 따라 우선 처리합니다.",
          },
          {
            title: "복수 후보",
            body: "블록을 승인하기 전에 처리 경로별 결과를 비교하거나 직접 수정합니다.",
          },
          {
            title: "감사 가능성",
            body: "변경 전후, 작업자, 시각, 처리 경로와 근거를 보존합니다.",
          },
        ],
        { label: "Proof 데모 살펴보기", href: "/demo/dart" },
        { label: "평가 방법론 읽기", href: "/benchmarks" },
      ),
      page(
        "/product/knowledge",
        "product",
        "지식",
        "파일을 더 만들지 말고 지식 시스템을 구축하세요.",
        "긴 문서를 속성, 백링크, 콘텐츠 맵과 근거를 갖춘 의미 있는 노트로 바꿉니다.",
        "사람과 AI 모두가 읽을 수 있는 이식 가능한 시스템입니다.",
        [
          {
            title: "의미 기반 경계",
            body: "임의의 토큰 길이가 아니라 섹션, 개념 또는 엔티티를 기준으로 나눕니다.",
          },
          {
            title: "속성",
            body: "제목, 별칭, 원본, 상태, 태그와 무결성 메타데이터를 명시적으로 유지합니다.",
          },
          {
            title: "연결",
            body: "관련 노트, 백링크, 엔티티 언급과 근거가 탐색 가능한 맥락을 만듭니다.",
          },
          {
            title: "Obsidian 호환",
            body: "폴더, 콘텐츠 맵, Wikilink와 에셋을 일관된 Vault로 제공합니다.",
          },
        ],
        { label: "샘플 Vault 열기", href: "/demo/research-paper" },
        { label: "지식 프로젝트 만들기", href: "/signup" },
      ),
      page(
        "/product/graph",
        "product",
        "그래프",
        "문서는 사실을 담고, 그래프는 관계를 드러냅니다.",
        "모든 관계에 근거를 연결한 상태에서 작고 관련성 높은 서브그래프부터 탐색합니다.",
        "보여주기보다 검색을, 추론보다 근거를 우선합니다.",
        [
          {
            title: "관점",
            body: "Document, Entity, Risk, Timeline, Evidence 관점으로 중요한 정보를 구분합니다.",
          },
          {
            title: "검색 중심 탐색",
            body: "회사, 위험, 지표, 데이터셋 또는 근거가 부족한 노트를 검색합니다.",
          },
          {
            title: "모든 관계의 근거",
            body: "관계를 선택하면 근거 목록과 정확한 원본 위치를 확인할 수 있습니다.",
          },
          {
            title: "온톨로지 내보내기",
            body: "JSON-LD와 Neo4j CSV를 내보냅니다. RDF와 SHACL은 로드맵 항목입니다.",
          },
        ],
        { label: "DART 그래프 살펴보기", href: "/demo/dart" },
        { label: "온톨로지 스키마 보기", href: "/developers/docs" },
      ),
      page(
        "/product/connect",
        "product",
        "연결",
        "지식은 한 번 컴파일하고 어디서나 연결하세요.",
        "하나의 검증된 지식 코어를 AI 프로젝트, 지식 도구, RAG 시스템과 개발 워크플로에 맞게 패키징합니다.",
        "연결은 로고를 나열하지 않고 목적에 따라 구분합니다.",
        [
          {
            title: "AI 프로젝트",
            body: "지원되는 AI 워크스페이스에서 사용할 수 있는 이식 가능한 프로젝트 패키지를 준비합니다.",
          },
          {
            title: "지식 도구",
            body: "Obsidian과 GitHub로 내보냅니다. 추가 커넥터는 로드맵으로 명확히 표시합니다.",
          },
          {
            title: "RAG와 검색",
            body: "pgvector, Qdrant, Pinecone과 Elasticsearch용 원본 연결 데이터를 생성합니다.",
          },
          {
            title: "개발자",
            body: "API, Webhook, SDK를 사용하며 MCP 연동은 향후 제공합니다.",
          },
        ],
        { label: "API 문서 보기", href: "/developers/docs" },
        { label: "연동 요청하기", href: "/company/contact" },
      ),
      page(
        "/solutions/individuals",
        "solution",
        "개인",
        "흩어진 파일을 하나의 지식으로 연결합니다.",
        "노트, PDF와 강의 자료를 직접 소유하고 재사용할 수 있는 연결된 지식으로 전환합니다.",
        "개인 파일에서 오래 유지되고 검증 가능한 기억 시스템으로 발전합니다.",
        [
          {
            title: "원본 가져오기",
            body: "개인 노트, 책, 강의와 참고 PDF를 업로드합니다.",
          },
          {
            title: "시스템 만들기",
            body: "연결된 노트, 속성과 수정 가능한 콘텐츠 맵을 생성합니다.",
          },
          {
            title: "통제권 유지",
            body: "이식 가능한 Markdown을 사용하고 보존 및 처리 정책을 직접 선택합니다.",
          },
        ],
        { label: "무료로 시작하기", href: "/signup" },
        { label: "샘플 Vault 받기", href: "/demo/course-material" },
      ),
      page(
        "/solutions/research",
        "solution",
        "연구",
        "원본을 잃지 않고 연구 속도를 높입니다.",
        "논문의 구조, 그림, 수식, 방법, 데이터셋, 결과, 한계와 인용을 보존합니다.",
        "다섯 편의 논문을 서로 분리된 요약이 아니라 추적 가능한 문헌 시스템으로 만듭니다.",
        [
          {
            title: "논문 구조화",
            body: "방법, 데이터셋, 결과와 한계를 서로 구분해 유지합니다.",
          },
          {
            title: "인용 추적",
            body: "주장과 인용 문헌을 정확한 원본 위치에 연결합니다.",
          },
          {
            title: "근거 비교",
            body: "공통 데이터셋, 방법과 상충되는 결과를 함께 탐색합니다.",
          },
        ],
        { label: "연구 데모 살펴보기", href: "/demo/research-paper" },
      ),
      page(
        "/solutions/teams",
        "solution",
        "팀",
        "사람과 AI가 공유하는 하나의 기준 정보를 만듭니다.",
        "공유 프로젝트, 선택적 결정 권한, 버전 기록, 지식 업데이트와 감사 이벤트로 팀의 기준을 일치시킵니다.",
        "자율 검증이 불확실성을 격리하며 선택적 재정의는 감사 기록으로 남습니다.",
        [
          {
            title: "함께 작업",
            body: "프로젝트 접근 권한, 선택적 결정 권한과 공유 지식 소유권을 지정합니다.",
          },
          {
            title: "변경 승인",
            body: "전체 원본을 다시 읽지 않고 영향이 큰 불확실성을 해결합니다.",
          },
          {
            title: "모든 결정 추적",
            body: "버전과 감사 이벤트로 지식이 변경된 과정을 보존합니다.",
          },
        ],
        { label: "팀 워크스페이스 시작하기", href: "/signup" },
        { label: "영업팀 문의", href: "/company/contact" },
      ),
      page(
        "/solutions/developers",
        "solution",
        "개발자",
        "파싱 부채 없이 문서 지능을 구축합니다.",
        "비동기 API, 타입 계약, Webhook, 원본 맵, 결정적 내보내기와 운영 가시성을 사용합니다.",
        "요청, 이벤트, 검증 패키지로 이어지는 명확한 계약입니다.",
        [
          {
            title: "비동기 우선",
            body: "작업을 만들고 지속 이벤트를 관찰하며 중단 지점부터 결과를 가져옵니다.",
          },
          {
            title: "타입이 지정된 출력",
            body: "버전이 관리되는 Canonical Document와 Export 계약을 사용합니다.",
          },
          {
            title: "운영 사실",
            body: "처리 경로, 재시도, 비용 원장, 원본 커버리지와 실패를 확인합니다.",
          },
        ],
        { label: "빠른 시작 읽기", href: "/developers" },
        { label: "문서 열기", href: "/developers/docs" },
      ),
      page(
        "/solutions/enterprise",
        "solution",
        "엔터프라이즈",
        "기업을 위한 신뢰 가능한 지식 인프라입니다.",
        "프로젝트, 워커, 데이터 리전, 보존, 외부 제공자와 감사 전반에 조직 정책을 적용합니다.",
        "문서 처리가 시작되기 전부터 통제 체계가 문서를 둘러쌉니다.",
        [
          {
            title: "정책과 ID",
            body: "조직 역할, SSO/MFA 통제와 명확한 SCIM 로드맵을 제공합니다.",
          },
          {
            title: "데이터 통제",
            body: "리전, 보존, 외부 제공자 정책과 프라이빗 배포 옵션을 선택합니다.",
          },
          {
            title: "운영 보증",
            body: "감사, 사고 대응, 지원 통제와 명시적 서비스 약속을 제공합니다.",
          },
        ],
        { label: "엔터프라이즈 문의", href: "/company/contact" },
        { label: "보안 아키텍처 보기", href: "/security" },
      ),
      page(
        "/demo",
        "demo",
        "데모",
        "문서가 지식으로 바뀌는 과정을 확인하세요.",
        "공시, 연구 논문과 강의 자료 워크플로를 동일한 원본 연결 계약으로 살펴봅니다.",
        "원본을 선택하고 구조, 근거, 지식과 내보내기까지 따라가세요.",
        [
          {
            title: "한국 DART",
            body: "장문 텍스트, 재무 표, 지표와 정정 공시 관계를 포함한 한국 공시입니다.",
          },
          {
            title: "미국 SEC EDGAR",
            body: "10-K, 10-Q, 8-K, Inline XBRL, 위험 요인과 원본 연결 엔티티를 다룹니다.",
          },
          {
            title: "연구 논문",
            body: "방법, 데이터셋, 결과, 한계, 수식, 그림과 인용을 다룹니다.",
          },
          {
            title: "강의 자료",
            body: "슬라이드, 배포 자료와 강의 노트를 개념 및 학습 그래프로 컴파일합니다.",
          },
        ],
        { label: "DART 데모 열기", href: "/demo/dart" },
      ),
      page(
        "/demo/dart",
        "demo",
        "공개 공시 데모",
        "한국 DART 지식 시스템",
        "한국어 장문 텍스트, 표, 숫자, 노트, 그래프 관계와 평가 근거를 보여주는 원본 연결 공개 공시 데모입니다.",
        "Original → Markdown → Vault → Graph → Proof",
        [
          {
            title: "Original",
            body: "보고서 목차, 페이지 렌더링과 타입이 지정된 블록 오버레이를 탐색합니다.",
          },
          {
            title: "Markdown",
            body: "원본 연결 문장, 표와 생성 출처 레이블을 확인합니다.",
          },
          {
            title: "Vault",
            body: "회사, 공시, 지표, 사업 부문, 위험, 종속회사와 정정 내역을 탐색합니다.",
          },
          {
            title: "Graph와 Benchmark",
            body: "검증되지 않은 점수를 제시하지 않고 XML/XBRL 정답 데이터와 비교합니다.",
          },
        ],
        {
          label: "인터랙티브 Proof 열기",
          href: "/documents/sample-dart/processing",
        },
        { label: "제한 사항 읽기", href: "/benchmarks" },
      ),
      page(
        "/demo/sec",
        "demo",
        "공개 공시 데모",
        "미국 SEC EDGAR 지식 시스템",
        "10-K, 10-Q, 8-K, Inline XBRL, 첨부 문서, 사업 부문, 재무 사실과 위험 요인에 동일한 원본 연결 시스템을 적용합니다.",
        "국가별 장식 팔레트 없이 관할권을 가로지르는 하나의 온톨로지를 사용합니다.",
        [
          {
            title: "엔티티",
            body: "회사, 공시, 사업 부문, 재무 사실, 위험 요인과 첨부 문서를 구조화합니다.",
          },
          {
            title: "근거",
            body: "추출된 모든 사실을 해당 공시와 정확한 원본 위치로 연결합니다.",
          },
          {
            title: "관할권 간 비교",
            body: "DART 사업보고서와 SEC 10-K, 사건 공시와 8-K를 비교합니다.",
          },
        ],
        { label: "공시 Proof 열기", href: "/demo/sec" },
      ),
      page(
        "/demo/research-paper",
        "demo",
        "연구 데모",
        "논문을 문헌 지식 시스템으로 전환합니다.",
        "초록, 방법, 데이터셋, 결과, 한계, 그림, 수식과 인용이 노트와 작은 근거 그래프로 이어지는 과정을 확인합니다.",
        "Paper → Structured Markdown → Concept Notes → Literature Graph → Evidence",
        [
          {
            title: "논문",
            body: "그림, 캡션, 수식과 인용 오버레이가 포함된 원본 페이지를 읽습니다.",
          },
          {
            title: "개념 노트",
            body: "방법, 데이터, 결과와 한계를 중심으로 원자 단위 노트를 만듭니다.",
          },
          {
            title: "문헌 그래프",
            body: "인용 논문과 공통 데이터셋을 원본 근거와 함께 연결합니다.",
          },
        ],
        {
          label: "샘플 살펴보기",
          href: "/documents/research-sample/processing",
        },
      ),
      page(
        "/demo/course-material",
        "demo",
        "강의 자료 데모",
        "강의를 학습 시스템으로 전환합니다.",
        "슬라이드, 배포 자료와 강의 노트를 정의, 예시, 개념 노트와 선택형 연습 문제로 바꿉니다.",
        "학습 자료는 언제나 원래 페이지와 강의에 연결됩니다.",
        [
          {
            title: "입력",
            body: "슬라이드, 배포 자료와 강의 노트를 사용합니다.",
          },
          {
            title: "출력",
            body: "개념 노트, 정의, 예시와 탐색 가능한 학습 그래프를 생성합니다.",
          },
          {
            title: "이식 가능한 학습",
            body: "Obsidian에서 바로 사용할 수 있는 샘플 Vault를 제공합니다.",
          },
        ],
        { label: "샘플 Vault 받기", href: "/app/exports" },
      ),
      page(
        "/benchmarks",
        "proof",
        "벤치마크",
        "문서 안에서 실제로 중요한 것을 평가합니다.",
        "텍스트만으로는 충분하지 않습니다. 숫자, 표, 계층 구조, 읽기 순서, 원본 추적성, 지연 시간과 비용을 각각 측정합니다.",
        "정확도는 선언이 아니라 근거로 증명해야 합니다.",
        [
          {
            title: "정답 데이터",
            body: "모든 결과에 데이터셋 리비전, 샘플 수, 처리 경로 버전, 평가기와 날짜를 함께 제공합니다.",
          },
          {
            title: "결정적 지표",
            body: "텍스트, 숫자, 표, 읽기 순서와 원본 커버리지를 분리해 측정합니다.",
          },
          {
            title: "페이지 비교기",
            body: "정답 데이터, 운영 결과, 도전자 결과와 차이를 페이지 단위로 확인합니다.",
          },
          {
            title: "증명하지 못하는 것",
            body: "어떤 벤치마크도 모든 고객 문서, 언어 또는 의미 기반 사용 사례를 대표하지 않습니다.",
          },
        ],
        { label: "최신 리포트 보기", href: "/app/benchmarks" },
        { label: "방법론 읽기", href: "/research" },
      ),
      page(
        "/research",
        "editorial",
        "연구",
        "원본 연결 지식 시스템을 위한 연구",
        "문서 파싱, provenance, 컴파일과 온톨로지를 위한 엔지니어링 노트, 평가 산출물과 방법을 제공합니다.",
        "기술 저널의 엄밀함을 갖춘 제품 연구소입니다.",
        [
          {
            title: "AI-ready 지식은 추출 텍스트가 아닙니다",
            body: "검색 이전에 구조, 맥락, 관계와 근거가 필요한 이유를 설명합니다.",
          },
          {
            title: "DART 기반 한국 문서 벤치마크",
            body: "정답 데이터 구축, 한계와 재현 가능한 평가 방법을 설명합니다.",
          },
          {
            title: "원본 연결 Markdown 측정",
            body: "커버리지와 충실도가 표면 유사도와 어떻게 다른지 설명합니다.",
          },
          {
            title: "문서에서 온톨로지로",
            body: "블록에서 노트, 엔티티와 관계로 이어지는 이식 가능한 경로를 설명합니다.",
          },
        ],
        { label: "벤치마크 살펴보기", href: "/benchmarks" },
      ),
      page(
        "/security",
        "proof",
        "보안",
        "고객의 지식은 고객에게 남습니다.",
        "획득하지 않은 인증을 내세우지 않고, 기본 비공개, 정책 통제와 설계 단계의 추적성을 제공합니다.",
        "Browser → Signed Upload → Private Storage → Controlled Worker → Derived Knowledge → Scheduled Purge",
        [
          {
            title: "암호화와 격리",
            body: "전송 및 저장 데이터를 보호하고 테넌트와 프로젝트 경계를 강제합니다.",
          },
          {
            title: "보존과 삭제",
            body: "원본, 파생물, 내보내기와 감사 데이터의 생명주기를 명확히 합니다.",
          },
          {
            title: "외부 처리",
            body: "정책에 따라 외부 제공자를 비활성화하거나 허용하거나 사전 승인을 요구합니다.",
          },
          {
            title: "현재 제공과 로드맵",
            body: "현재 통제와 SSO, SCIM, 리전, VPC 또는 온프레미스 로드맵을 구분합니다.",
          },
        ],
        { label: "보안 자료 요청", href: "/company/contact" },
        { label: "데이터 원칙 읽기", href: "/legal/privacy" },
      ),
      page(
        "/pricing",
        "proof",
        "요금",
        "문서에서 시작해 지식 인프라로 확장합니다.",
        "처리 깊이와 운영 통제 수준에 따라 선택합니다. 크레딧, 페이지 범위, 정밀 처리 비용, 보존과 상한을 명확히 표시합니다.",
        "요금제 구조 예시이며 최종 상용 가격은 소유자 승인이 필요합니다.",
        [
          {
            title: "Free와 Personal",
            body: "기본 변환, 정돈된 Markdown, 기본 Obsidian 출력과 짧은 보존 기간을 제공합니다.",
          },
          {
            title: "Pro와 Team",
            body: "정밀 처리, 원본 비교, 지식 노트, 그래프, 무결성 원장과 API를 제공합니다.",
          },
          {
            title: "Business와 Enterprise",
            body: "더 높은 한도, 정책 통제, 역할, 지원, 리전과 프라이빗 배포를 제공합니다.",
          },
          {
            title: "견적이 아닌 추정",
            body: "월간 페이지, 스캔 비율, 정밀 처리 비율과 지식 출력을 바탕으로 범위가 제한된 추정치를 제공합니다.",
          },
        ],
        { label: "무료로 시작하기", href: "/signup" },
        { label: "영업팀 문의", href: "/company/contact" },
      ),
      page(
        "/customers",
        "editorial",
        "근거 사례",
        "추천사보다 근거를 먼저 제시합니다.",
        "승인된 고객과 성과가 확보되기 전까지 공개 엔지니어링 사례, 샘플 내보내기와 벤치마크 리포트를 제공합니다.",
        "가짜 로고, 꾸며낸 인용, 장식용 증거를 사용하지 않습니다.",
        [
          {
            title: "DART 엔지니어링 사례",
            body: "복잡한 공개 공시가 원본 연결 지식 시스템으로 전환되는 과정을 설명합니다.",
          },
          {
            title: "SEC 온톨로지 연구",
            body: "공시 유형, 사실, 위험과 첨부 문서를 공유 스키마에 매핑하는 방법을 설명합니다.",
          },
          {
            title: "샘플 내보내기",
            body: "이식 가능한 패키지의 파일, 링크, 에셋, 커버리지와 한계를 확인합니다.",
          },
        ],
        { label: "DART 사례 살펴보기", href: "/demo/dart" },
      ),
      page(
        "/developers",
        "docs",
        "개발자",
        "검증된 문서 지식 위에 제품을 구축하세요.",
        "업로드하고, 작업을 생성하고, 이벤트를 수신하고, 원본 맵을 확인하고, 결정적 패키지를 다운로드합니다.",
        "API 키에서 검증 출력까지 이어지는 다섯 단계입니다.",
        [
          {
            title: "1. 프로젝트 생성",
            body: "정책, 출력 프로필과 idempotency key를 선택합니다.",
          },
          {
            title: "2. 업로드와 처리",
            body: "서명된 멀티파트 업로드와 비동기 작업을 사용합니다.",
          },
          {
            title: "3. 관찰",
            body: "스냅샷, 순서 인식 SSE와 Webhook을 따라갑니다.",
          },
          {
            title: "4. 확인과 내보내기",
            body: "Canonical Block, 원본 맵, 무결성 항목과 manifest를 확인합니다.",
          },
        ],
        { label: "문서 열기", href: "/developers/docs" },
        { label: "API 콘솔 열기", href: "/app/api" },
      ),
      page(
        "/developers/docs",
        "docs",
        "문서",
        "검증된 지식을 컴파일하는 데 필요한 모든 내용을 제공합니다.",
        "버전이 관리되는 가이드를 검색하고 예제를 복사하며 API 계약, 한도와 보안 동작을 확인합니다.",
        "시작하기 · 핵심 개념 · 업로드 · 처리 · 무결성 · 지식 · 내보내기 · API · Webhook",
        [
          {
            title: "시작하기",
            body: "자격 증명과 프로젝트를 만들고 업로드한 뒤 첫 작업을 실행합니다.",
          },
          {
            title: "핵심 개념",
            body: "Project, Document, Job, Route, CIR, Evidence와 Export를 설명합니다.",
          },
          {
            title: "운영",
            body: "이벤트, 재시도, 멱등성, Webhook, 한도와 오류를 설명합니다.",
          },
          {
            title: "보안",
            body: "Scope, 보존, 외부 제공자, 리전과 삭제를 설명합니다.",
          },
        ],
        { label: "API 레퍼런스 열기", href: "/developers/api" },
      ),
      page(
        "/developers/api",
        "docs",
        "API 레퍼런스",
        "원본 연결 지식을 위한 타입 계약",
        "버전이 관리되는 엔드포인트가 인증, 프로젝트, 업로드, 작업, 무결성, 지식, 내보내기와 운영을 다룹니다.",
        "요청은 비동기이며 변경 작업은 멱등적이고 이벤트는 순서를 인식합니다.",
        [
          {
            title: "프로젝트와 문서",
            body: "정책이 적용된 컨테이너와 변경 불가능한 원본 버전을 생성합니다.",
          },
          {
            title: "작업과 이벤트",
            body: "작업을 시작하고 SSE를 따라가며 스냅샷을 조정하고 재시도를 처리합니다.",
          },
          {
            title: "무결성과 지식",
            body: "후보를 해결하고 원본 연결 노트, 엔티티와 관계에 접근합니다.",
          },
          {
            title: "내보내기",
            body: "패키지를 요청하고 manifest와 checksum을 검증합니다.",
          },
        ],
        { label: "API 콘솔 열기", href: "/app/api" },
      ),
      page(
        "/developers/sdk",
        "docs",
        "SDK",
        "계약을 숨기지 않고 연동합니다.",
        "작고 타입이 지정된 클라이언트가 작업, 이벤트, 무결성과 내보내기 동작을 명시적으로 유지합니다.",
        "Python과 TypeScript를 우선 지원하며 cURL은 이식 가능한 기준 예제로 유지합니다.",
        [
          {
            title: "Python",
            body: "타입 요청, 이벤트 순회, 재시도 경계와 내보내기 다운로드를 제공합니다.",
          },
          {
            title: "TypeScript",
            body: "명시적 자격 증명 경계를 가진 브라우저와 서버 런타임을 지원합니다.",
          },
          {
            title: "cURL",
            body: "SDK 추상화 없이 복사 가능한 프로토콜 예제를 제공합니다.",
          },
        ],
        { label: "빠른 시작 읽기", href: "/developers/docs" },
      ),
      page(
        "/developers/changelog",
        "editorial",
        "변경 기록",
        "제품 동작을 명확하게 설명합니다.",
        "Product, API, Models and Quality, Security, Design 변경을 스크린샷과 마이그레이션 노트와 함께 제공합니다.",
        "모델 변경은 처리 경로 동작과 품질 영향으로 설명하고 기술 세부 정보도 제공합니다.",
        [
          {
            title: "2026.08 — FOLYNTA 기반",
            body: "새로운 카테고리, 원본에서 지식으로 이어지는 내러티브, 경로 시스템과 차분한 제품 Shell을 구축했습니다.",
          },
          {
            title: "2026.07 — Evidence 워크플로",
            body: "처리 및 무결성 화면에서 결과를 페이지와 블록 근거에 연결했습니다.",
          },
          {
            title: "2026.07 — 공개 Proof",
            body: "DART, SEC, 벤치마크와 제한 사항을 독립적인 핵심 경로로 제공했습니다.",
          },
        ],
        { label: "문서 읽기", href: "/developers/docs" },
      ),
      page(
        "/company/about",
        "editorial",
        "회사 소개",
        "문서와 AI 사이의 지식 계층을 구축합니다.",
        "AI 워크플로에서 문서는 여전히 구조와 원본 관계를 잃습니다. 이식 가능하고 근거가 연결된 지식이 그 사이를 채웁니다.",
        "확신보다 근거, 장식보다 구조, 종속보다 이식성을 우선합니다.",
        [
          {
            title: "문서가 실패하는 이유",
            body: "페이지에는 일반 텍스트 추출이 평면화할 수 있는 레이아웃, 계층, 표, 그림과 맥락이 담겨 있습니다.",
          },
          {
            title: "원본이 중요한 이유",
            body: "사람이 결과를 검증하고 시스템이 provenance를 보존할 수 있을 때 결과가 유용해집니다.",
          },
          {
            title: "이식성이 중요한 이유",
            body: "지식은 사람, 도구, 모델과 미래 시스템 사이를 이동할 수 있어야 합니다.",
          },
        ],
        { label: "원칙 읽기", href: "/company/principles" },
      ),
      page(
        "/company/principles",
        "editorial",
        "원칙",
        "컴파일러를 만든 의사결정 원칙",
        "여섯 가지 운영 원칙이 제품 동작과 직접 연결됩니다.",
        "생성보다 원본을 먼저 봅니다.",
        [
          {
            title: "생성보다 원본",
            body: "추출, 추론, 편집 콘텐츠를 눈에 띄게 구분합니다.",
          },
          {
            title: "확신보다 근거",
            body: "점수를 믿으라고 요청하기 전에 결과의 출처를 보여줍니다.",
          },
          {
            title: "지능보다 구조",
            body: "지식을 파생하기 전에 문서를 복원합니다.",
          },
          {
            title: "자동화보다 통제",
            body: "무인 처리보다 동의와 무결성 경계를 먼저 설정합니다.",
          },
          {
            title: "종속보다 이식성",
            body: "개방적이고 확인 가능한 내보내기를 사용합니다.",
          },
          {
            title: "도입보다 벤치마크",
            body: "모든 주장과 함께 방법과 한계를 공개합니다.",
          },
        ],
        { label: "제품 보기", href: "/product" },
      ),
      page(
        "/company/careers",
        "editorial",
        "채용",
        "AI가 세상의 문서를 이해하도록 돕는 인프라를 만듭니다.",
        "파싱, provenance, 지식 시스템, 벤치마크, 제품 완성도와 신뢰 가능한 인프라를 다루는 작은 팀에 합류하세요.",
        "꾸며낸 조직 문화 사진이 아니라 실제 제품과 연구 작업을 보여줍니다.",
        [
          {
            title: "미션",
            body: "복잡한 원본의 불확실성과 출처를 숨기지 않으면서 활용 가능하게 만듭니다.",
          },
          {
            title: "업무 방식",
            body: "작은 범위, 측정 가능한 품질, 지속 가능한 의사결정과 직접적인 제품 근거를 중시합니다.",
          },
          {
            title: "채용 공고",
            body: "회사 소유자의 승인을 받은 직무만 게시합니다.",
          },
        ],
        { label: "팀 문의", href: "/company/contact" },
      ),
      page(
        "/company/contact",
        "editorial",
        "문의",
        "보유한 지식이 어떤 형태가 되어야 하는지 알려주세요.",
        "문서 규모, 핵심 요구와 보안 조건을 공유하세요. 이 양식에는 민감한 문서를 업로드하지 마세요.",
        "지식 설계자가 요청을 검토하며 응답 기한은 운영 정책 승인 후 확정합니다.",
        [
          {
            title: "포함할 내용",
            body: "회사, 역할, 문서 규모, 원본 유형, 목표 출력과 보안 요구를 포함하세요.",
          },
          {
            title: "보안 검토",
            body: "승인된 후속 채널을 통해 아키텍처 및 정책 자료를 공유할 수 있습니다.",
          },
          {
            title: "원본 업로드 금지",
            body: "이 문의 경로는 고객 문서를 요청하지 않습니다.",
          },
        ],
        { label: "문의 양식 열기", href: "mailto:sales@example.invalid" },
      ),
      page(
        "/legal/privacy",
        "legal",
        "법적 고지",
        "개인정보 처리 원칙",
        "이 저장소는 제품 통제를 설명합니다. 외부 공개 전 최종 정책 문구에 대한 법무 승인이 필요합니다.",
        "적게 수집하고, 목적을 설명하고, 정책에 따라 보존하고, 완전히 삭제합니다.",
        [
          {
            title: "데이터 범주",
            body: "계정, 프로젝트, 원본, 파생물, 운영, 결제와 감사 데이터를 구분합니다.",
          },
          {
            title: "처리",
            body: "작업 시작 전에 목적, 제공자 경계, 리전과 보존 기간을 표시합니다.",
          },
          {
            title: "권리와 삭제",
            body: "내보내기, 정정, 삭제와 지원 절차에는 운영 환경의 공식 연락처가 필요합니다.",
          },
        ],
        { label: "개인정보 문의", href: "/company/contact" },
      ),
      page(
        "/legal/terms",
        "legal",
        "법적 고지",
        "서비스 이용약관",
        "최종 이용약관, 운영 법인, 관할, 결제 조건과 서비스 약속에는 소유자와 법률 자문 승인이 필요합니다.",
        "이 경로는 구현 준비용 법적 문서 구조이며 공개된 법률 자문이 아닙니다.",
        [
          {
            title: "서비스",
            body: "계정, 허용 사용, 원본 권리, 출력과 API 동작을 다룹니다.",
          },
          {
            title: "상업 조건",
            body: "요금제, 크레딧, 환불, 세금, 정지와 해지를 다룹니다.",
          },
          {
            title: "위험",
            body: "보증, 책임 제한, 면책과 분쟁 절차를 다룹니다.",
          },
        ],
        { label: "법무 문의", href: "/company/contact" },
      ),
      page(
        "/legal/subprocessors",
        "legal",
        "법적 고지",
        "하위 처리업체와 인프라",
        "운영 제공자, 목적, 데이터 범주, 리전과 변경 고지는 배포 선택이 승인된 후에만 게시합니다.",
        "로컬 개발 설정만으로 어떤 제공자도 실제 운영 중이라고 표시하지 않습니다.",
        [
          {
            title: "인프라",
            body: "호스팅, 저장소, 데이터베이스, 관측, 이메일과 결제 제공자를 다룹니다.",
          },
          {
            title: "처리",
            body: "외부 모델 또는 OCR 제공자는 정확한 정책 범위와 함께 표시합니다.",
          },
          {
            title: "변경 통제",
            body: "중대한 변경에는 날짜가 포함된 고지와 소유자 승인이 필요합니다.",
          },
        ],
        { label: "현재 목록 요청", href: "/company/contact" },
      ),
      page(
        "/legal/third-party-notices",
        "legal",
        "법적 고지",
        "제3자 고지",
        "런타임 패키지, 라이선스, 저작자 표시, 에셋, 폰트와 공개 데이터 출처를 출시 전에 기록합니다.",
        "저장소의 라이선스 레지스터가 구현 기준 정보입니다.",
        [
          {
            title: "소프트웨어",
            body: "확인된 라이선스와 함께 오픈소스 런타임 및 빌드 패키지를 기록합니다.",
          },
          {
            title: "에셋",
            body: "폰트, 텍스처, 이미지, 영상, 3D와 생성 에셋의 provenance를 기록합니다.",
          },
          {
            title: "공개 데이터",
            body: "DART와 SEC 원본 이용 조건 및 필수 고지를 기록합니다.",
          },
        ],
        { label: "저장소 고지 보기", href: "/notices" },
      ),
    ].map((definition) => [definition.path, definition]),
  );
