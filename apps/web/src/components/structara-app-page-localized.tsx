import {
  ArrowRight,
  BracketsCurly,
  CheckCircle,
  FileArrowUp,
  FileText,
  Flask,
  FolderOpen,
  GearSix,
  Graph,
  Pulse,
  ShieldCheck,
  TreeStructure,
  WarningCircle,
} from "@phosphor-icons/react/dist/ssr";
import type { Route } from "next";
import Link from "next/link";

import { appActionHref } from "@/lib/app-action";
import type { StructaraLocale } from "@/lib/locale";

type Props = {
  route: string;
  title: string;
  description: string;
  action: string;
  locale: StructaraLocale;
};

const routeCopy: Record<
  string,
  {
    eyebrow: string;
    title: string;
    description: string;
    action: string;
    icon: typeof FileText;
    metrics: readonly [string, string, string][];
    sections: readonly { title: string; body: string; state: string }[];
  }
> = {
  home: {
    eyebrow: "운영 개요",
    title: "지식 컴파일 워크스페이스",
    description:
      "활성 작업, 검토 의무, 지식 상태와 사용량을 하나의 운영 화면에서 확인합니다.",
    action: "문서 업로드",
    icon: Pulse,
    metrics: [
      ["활성 작업", "2", "데모 fixture"],
      ["검토 필요", "3", "영향도 우선"],
      ["지식 노트", "852", "원본 연결"],
      ["원본 커버리지", "99.6%", "로컬 검증"],
    ],
    sections: [
      {
        title: "처리 현황",
        body: "실제 운영 모드에서는 작업 API의 최신 스냅샷과 순서가 보장된 이벤트를 표시합니다.",
        state: "연결 시 실데이터",
      },
      {
        title: "검토 큐",
        body: "숫자, 표와 누락 콘텐츠를 영향도 순으로 Review Studio에 전달합니다.",
        state: "Review 연결",
      },
      {
        title: "지식 상태",
        body: "노트, 관계, 원본 커버리지와 끊어진 링크를 동일한 provenance 계약으로 추적합니다.",
        state: "Knowledge 연결",
      },
    ],
  },
  jobs: {
    eyebrow: "운영",
    title: "작업 원장",
    description:
      "처리 단계, 재시도, 경로 기록, 크레딧 원장과 결과 manifest를 확인합니다.",
    action: "감사 기록 열기",
    icon: Pulse,
    metrics: [
      ["실행 중", "2", "지속 작업"],
      ["검토", "3", "영향도 높음"],
      ["실패", "0", "최근 24시간"],
      ["p95", "8분 42초", "Balanced 경로"],
    ],
    sections: [
      {
        title: "순서가 보장된 이벤트",
        body: "스냅샷과 SSE sequence를 조정해 중복 또는 누락된 상태 전이를 차단합니다.",
        state: "구현됨",
      },
      {
        title: "멱등 재시도",
        body: "요청 해시와 idempotency key로 중복 처리와 이중 과금을 방지합니다.",
        state: "구현됨",
      },
      {
        title: "실패 격리",
        body: "재시도 예산을 초과한 작업은 DLQ와 감사 이벤트로 이동합니다.",
        state: "운영 증거 필요",
      },
    ],
  },
  exports: {
    eyebrow: "내보내기",
    title: "검증 지식 패키지",
    description:
      "동일한 source map에서 Markdown, Obsidian, RAG JSONL, JSON-LD와 그래프 출력을 생성합니다.",
    action: "새 내보내기",
    icon: Flask,
    metrics: [
      ["준비 완료", "4", "checksum 검증"],
      ["패키징", "1", "Obsidian Vault"],
      ["끊어진 링크", "0", "최신 패키지"],
      ["원본 커버리지", "99.8%", "승인 블록"],
    ],
    sections: [
      {
        title: "결정적 manifest",
        body: "파일 목록, 해시, 계약 버전과 원본 커버리지를 패키지에 포함합니다.",
        state: "구현됨",
      },
      {
        title: "만료와 철회",
        body: "다운로드 URL은 짧은 TTL과 범위가 제한된 권한을 사용합니다.",
        state: "정책 적용",
      },
      {
        title: "이식성",
        body: "출력은 특정 모델 또는 지식 도구에 종속되지 않습니다.",
        state: "구현됨",
      },
    ],
  },
  benchmarks: {
    eyebrow: "품질",
    title: "벤치마크 연구소",
    description:
      "텍스트, 숫자, 표, 읽기 순서, 원본 커버리지, 지연 시간과 비용을 분리해 평가합니다.",
    action: "방법론 보기",
    icon: Graph,
    metrics: [
      ["공개 suite", "계약 검증", "실측 주장 아님"],
      ["원본 커버리지", "로컬 통과", "E2E"],
      ["실제 corpus", "대기", "권리 승인 필요"],
      ["승격 Gate", "Fail closed", "증거 필수"],
    ],
    sections: [
      {
        title: "정답 데이터",
        body: "데이터셋 revision, 권리, split hash와 평가기를 결과와 함께 고정합니다.",
        state: "실제 corpus 외부 Gate",
      },
      {
        title: "실패 사례",
        body: "평균 점수만 공개하지 않고 페이지 단위 차이와 실패 원인을 함께 제공합니다.",
        state: "구현됨",
      },
      {
        title: "승격 통제",
        body: "실측 근거가 없는 모델과 경로는 production 승격을 거부합니다.",
        state: "구현됨",
      },
    ],
  },
  api: {
    eyebrow: "개발자",
    title: "API 콘솔",
    description:
      "프로젝트, 업로드, 작업, 검토, 지식과 내보내기 계약을 확인합니다.",
    action: "API 문서 열기",
    icon: BracketsCurly,
    metrics: [
      ["계약 버전", "v1", "OpenAPI"],
      ["변경 작업", "멱등", "요청 해시"],
      ["이벤트", "순서 인식", "SSE + Webhook"],
      ["키", "범위 제한", "감사 대상"],
    ],
    sections: [
      {
        title: "타입 계약",
        body: "Canonical schema와 생성 타입을 CI에서 동기화합니다.",
        state: "구현됨",
      },
      {
        title: "Playground",
        body: "연결된 워크스페이스에서만 실제 요청을 실행하며 데모에서는 읽기 전용입니다.",
        state: "정직한 경계",
      },
      {
        title: "Webhook",
        body: "서명, 재전송, 재생 방지와 DLQ 상태를 운영 화면에서 확인합니다.",
        state: "구현됨",
      },
    ],
  },
  usage: {
    eyebrow: "사용량",
    title: "사용량과 비용 프로필",
    description:
      "페이지, 처리 경로, 크레딧, 저장소와 보존 정책이 비용에 미치는 영향을 확인합니다.",
    action: "요금 구조 보기",
    icon: Graph,
    metrics: [
      ["페이지", "1,284", "현재 기간"],
      ["Precision", "18%", "정책 라우팅"],
      ["저장소", "18.4 GB", "보존 포함"],
      ["크레딧", "58%", "상한 대비"],
    ],
    sections: [
      {
        title: "비용 투명성",
        body: "작업 전 최대 예약량과 실패 페이지의 자동 반환 정책을 표시합니다.",
        state: "구현됨",
      },
      {
        title: "정책 기반 라우팅",
        body: "정밀 처리는 페이지 품질과 승인 정책에 따라 선택됩니다.",
        state: "구현됨",
      },
      {
        title: "상용 가격",
        body: "통화, 초과 사용, 저장소와 연간 할인 값은 소유자 승인 전 공개하지 않습니다.",
        state: "외부 Gate",
      },
    ],
  },
  billing: {
    eyebrow: "결제",
    title: "결제와 크레딧 통제",
    description:
      "append-only 원장, 결제 제공자 이벤트와 환불·분쟁 상태를 추적합니다.",
    action: "사용량 보기",
    icon: Graph,
    metrics: [
      ["원장", "Append-only", "이중 기록"],
      ["Webhook", "서명 검증", "재생 방지"],
      ["환불", "상태 기반", "감사 이벤트"],
      ["결제 제공자", "미설정", "운영 Gate"],
    ],
    sections: [
      {
        title: "결제 무결성",
        body: "제공자 이벤트와 내부 원장을 조정하며 중복 이벤트를 멱등 처리합니다.",
        state: "구현됨",
      },
      {
        title: "Provider pending",
        body: "운영 결제 제공자가 없으면 checkout을 성공으로 가장하지 않습니다.",
        state: "정직한 상태",
      },
      {
        title: "가격 승인",
        body: "최종 가격표와 세금·환불 정책은 소유자와 법무 승인이 필요합니다.",
        state: "외부 Gate",
      },
    ],
  },
};

function resolveKoreanSpec(route: string) {
  const top = route.split("/")[0] ?? "home";
  if (top === "projects") {
    return {
      eyebrow: "프로젝트 운영",
      title: route.split("/").length > 1 ? "프로젝트 상세" : "프로젝트",
      description:
        "문서, 검토, 지식, 원본 커버리지와 내보내기를 프로젝트 경계 안에서 관리합니다.",
      action: "문서 업로드",
      icon: FolderOpen,
      metrics: [
        ["문서", "33", "승인 원본"],
        ["지식 노트", "852", "원본 연결"],
        ["검토 필요", "4", "영향도 높음"],
        ["끊어진 링크", "0", "오늘 확인"],
      ] as const,
      sections: [
        {
          title: "라이브 데이터",
          body: "연결된 운영 모드에서는 프로젝트 API의 실제 소유자, 문서 수와 상태를 표시합니다.",
          state: "API 연결",
        },
        {
          title: "데모 데이터",
          body: "데모 모드의 샘플 수치는 명확한 fixture 레이블과 함께 제공됩니다.",
          state: "데모 전용",
        },
        {
          title: "테넌트 경계",
          body: "모든 프로젝트 조회와 객체 키에 tenant scope를 강제합니다.",
          state: "RLS 검증",
        },
      ] as const,
    };
  }
  if (top === "settings") {
    return {
      eyebrow: "조직 정책",
      title: "설정",
      description:
        "보존, 외부 처리, ID, 역할과 감사 정책을 변경 전 영향 미리보기와 함께 관리합니다.",
      action: "변경 검토",
      icon: GearSix,
      metrics: [
        ["외부 처리", "정책 적용", "명시적 동의"],
        ["보존", "프로젝트별", "삭제 receipt"],
        ["ID", "OIDC/MFA", "SCIM 로드맵"],
        ["감사", "불변 이벤트", "내보내기"],
      ] as const,
      sections: [
        {
          title: "변경 미리보기",
          body: "영향 범위와 재인증 요구를 확인한 뒤 정책 변경을 적용합니다.",
          state: "구현됨",
        },
        {
          title: "운영 제공자",
          body: "SSO, 이메일, 결제와 외부 모델 제공자는 실제 설정 전 활성 상태로 표시하지 않습니다.",
          state: "외부 Gate",
        },
        {
          title: "감사",
          body: "작업자, 이전 값, 이후 값, 시각과 승인 근거를 기록합니다.",
          state: "구현됨",
        },
      ] as const,
    };
  }
  if (top === "admin") {
    return {
      eyebrow: "관리자 운영",
      title: "관리 센터",
      description:
        "작업, DLQ, 감사, 모델, 분석과 삭제 요청을 최소 권한으로 관리합니다.",
      action: "감사 기록 열기",
      icon: ShieldCheck,
      metrics: [
        ["실패 작업", "0", "최근 24시간"],
        ["DLQ", "0", "운영 확인"],
        ["삭제 요청", "0", "SLO 내"],
        ["관리 작업", "감사", "단계 상승 인증"],
      ] as const,
      sections: [
        {
          title: "최소 권한",
          body: "대량 내보내기와 삭제는 단계 상승 인증 및 이중 승인을 요구합니다.",
          state: "구현됨",
        },
        {
          title: "운영 증거",
          body: "실제 배포 환경의 사고 대응, 복구와 삭제 훈련은 별도 증거가 필요합니다.",
          state: "외부 Gate",
        },
        {
          title: "데모 통제",
          body: "데모 모드에서는 쓰기처럼 보이는 관리자 작업을 실행할 수 없습니다.",
          state: "Fail closed",
        },
      ] as const,
    };
  }
  if (route.startsWith("document/")) {
    return {
      eyebrow: "문서 워크스페이스",
      title: route.includes("sources")
        ? "원본 provenance"
        : route.includes("versions")
          ? "문서 버전"
          : "구조화 문서",
      description:
        "블록, 원본 위치, 편집 이력과 지식 영향을 비파괴 방식으로 확인합니다.",
      action: route.includes("versions") ? "버전 비교" : "내보내기",
      icon: FileText,
      metrics: [
        ["페이지", "421", "원본 버전"],
        ["승인 블록", "1,284", "원본 연결"],
        ["검토 필요", "3", "영향도 높음"],
        ["버전", "4", "비파괴"],
      ] as const,
      sections: [
        {
          title: "원본 계층",
          body: "페이지, 블록, bbox와 source hash를 편집 결과와 함께 유지합니다.",
          state: "구현됨",
        },
        {
          title: "버전 비교",
          body: "원본, Markdown과 지식 영향 차이를 적용 전에 확인합니다.",
          state: "구현됨",
        },
        {
          title: "라이브 연결",
          body: "실제 document ID가 없으면 샘플 결과를 가장하지 않고 빈 상태 또는 오류를 표시합니다.",
          state: "정직한 상태",
        },
      ] as const,
    };
  }
  return routeCopy[top] ?? routeCopy.home!;
}

function resolveEnglishSpec(route: string) {
  const top = route.split("/")[0] ?? "home";
  if (top === "projects") {
    return {
      eyebrow: "Project operations",
      title: route.split("/").length > 1 ? "Project detail" : "Projects",
      description:
        "Manage documents, review obligations, knowledge, source coverage, and exports inside one project boundary.",
      action: "Upload documents",
      icon: FolderOpen,
      metrics: [
        ["Documents", "33", "accepted sources"],
        ["Knowledge notes", "852", "source-linked"],
        ["Review required", "4", "high impact"],
        ["Broken links", "0", "checked today"],
      ] as const,
      sections: [
        {
          title: "Live data",
          body: "Connected production mode reads owner, document counts, and status from the project API.",
          state: "API connected",
        },
        {
          title: "Demo data",
          body: "Sample values in demo mode remain visibly labeled as deterministic fixtures.",
          state: "Demo only",
        },
        {
          title: "Tenant boundary",
          body: "Every project lookup and object key carries tenant scope and RLS enforcement.",
          state: "RLS verified",
        },
      ] as const,
    };
  }
  if (top === "settings") {
    return {
      eyebrow: "Organization policy",
      title: "Settings",
      description:
        "Manage retention, external processing, identity, roles, and audit policy with an impact preview before change.",
      action: "Review changes",
      icon: GearSix,
      metrics: [
        ["External processing", "Policy controlled", "explicit consent"],
        ["Retention", "Per project", "deletion receipt"],
        ["Identity", "OIDC/MFA", "SCIM roadmap"],
        ["Audit", "Immutable events", "exportable"],
      ] as const,
      sections: [
        {
          title: "Change preview",
          body: "Inspect affected projects and reauthentication requirements before applying policy.",
          state: "Implemented",
        },
        {
          title: "Production providers",
          body: "SSO, email, payment, and external-model providers are never shown as active before real configuration.",
          state: "External gate",
        },
        {
          title: "Audit",
          body: "Actor, old value, new value, time, and approval evidence are retained.",
          state: "Implemented",
        },
      ] as const,
    };
  }
  if (top === "admin") {
    return {
      eyebrow: "Administrative operations",
      title: "Admin center",
      description:
        "Operate jobs, DLQ, audit, models, analytics, and deletion requests under least privilege.",
      action: "Open audit trail",
      icon: ShieldCheck,
      metrics: [
        ["Failed jobs", "0", "last 24 hours"],
        ["DLQ", "0", "operational view"],
        ["Deletion requests", "0", "within SLO"],
        ["Admin actions", "Audited", "step-up auth"],
      ] as const,
      sections: [
        {
          title: "Least privilege",
          body: "Mass export and deletion require step-up authentication and dual approval.",
          state: "Implemented",
        },
        {
          title: "Operating evidence",
          body: "Incident, restore, and deletion drills require evidence from the deployed environment.",
          state: "External gate",
        },
        {
          title: "Demo controls",
          body: "Write-looking administration actions remain disabled in deterministic demo mode.",
          state: "Fail closed",
        },
      ] as const,
    };
  }
  if (route.startsWith("document/")) {
    return {
      eyebrow: "Document workspace",
      title: route.includes("sources")
        ? "Source provenance"
        : route.includes("versions")
          ? "Document versions"
          : "Structured document",
      description:
        "Inspect blocks, source locations, edit history, and knowledge impact without mutating the original.",
      action: route.includes("versions") ? "Compare versions" : "Export",
      icon: FileText,
      metrics: [
        ["Pages", "421", "source version"],
        ["Accepted blocks", "1,284", "source-linked"],
        ["Review required", "3", "high impact"],
        ["Versions", "4", "non-destructive"],
      ] as const,
      sections: [
        {
          title: "Source layer",
          body: "Page, block, bbox, and source hash remain attached to every edited result.",
          state: "Implemented",
        },
        {
          title: "Version comparison",
          body: "Review source, Markdown, and knowledge-impact differences before applying a revision.",
          state: "Implemented",
        },
        {
          title: "Live boundary",
          body: "When an exact document ID is unavailable, the product shows an empty or error state instead of fabricated output.",
          state: "Honest state",
        },
      ] as const,
    };
  }
  return routeCopy[top] ?? routeCopy.home!;
}

export function StructaraAppPageLocalized(props: Props) {
  const korean = props.locale === "ko";
  const spec = korean
    ? resolveKoreanSpec(props.route)
    : resolveEnglishSpec(props.route);
  const Icon = spec.icon;
  return (
    <div className="st-app-page st-app-page-localized">
      <header className="st-app-context">
        <div>
          <p>
            {korean ? "샘플 워크스페이스" : "Sample workspace"} /{" "}
            {props.route.replaceAll("/", " / ")}
          </p>
          <h1>{spec.title}</h1>
          <span>{spec.description}</span>
        </div>
        <Link
          href={appActionHref(props.route) as Route}
          className="st-app-primary"
          data-app-header-action
        >
          {spec.action}
          <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </header>

      <section className="st-localized-operating-hero">
        <div>
          <Icon size={24} aria-hidden="true" />
          <p>{spec.eyebrow}</p>
          <h2>{spec.title}</h2>
          <span>{spec.description}</span>
        </div>
        <aside>
          <WarningCircle size={18} aria-hidden="true" />
          <strong>{korean ? "증거 경계" : "Evidence boundary"}</strong>
          <p>
            {korean
              ? "표시된 샘플 수치는 데모 fixture이며 실제 운영 데이터, 품질 점수 또는 서비스 수준 주장이 아닙니다."
              : "Displayed sample values are deterministic demo fixtures, not production data, quality scores, or service-level claims."}
          </p>
        </aside>
      </section>

      <section
        className="st-localized-metrics"
        aria-label={korean ? "운영 지표" : "Operating metrics"}
      >
        {spec.metrics.map(([label, value, note]) => (
          <article key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
            <small>{note}</small>
          </article>
        ))}
      </section>

      <section className="st-localized-operating-grid">
        {spec.sections.map((section, index) => (
          <article key={section.title}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div>
              <h2>{section.title}</h2>
              <p>{section.body}</p>
            </div>
            <strong>
              <CheckCircle size={14} aria-hidden="true" />
              {section.state}
            </strong>
          </article>
        ))}
      </section>

      <section className="st-localized-next-actions">
        <div>
          <h2>{korean ? "다음 작업" : "Next actions"}</h2>
          <p>
            {korean
              ? "실제 데이터가 필요한 작업은 연결된 워크스페이스에서만 실행되며 데모에서는 읽기 전용 또는 비활성 상태를 유지합니다."
              : "Actions that require real data run only in a connected workspace and remain read-only or disabled in demo mode."}
          </p>
        </div>
        <div>
          <Link href="/quick-convert">
            <FileArrowUp size={16} />
            {korean ? "문서 업로드" : "Upload documents"}
          </Link>
          <Link href="/app/projects">
            <FolderOpen size={16} />
            {korean ? "프로젝트 열기" : "Open projects"}
          </Link>
          <Link href="/app/knowledge-bases">
            <TreeStructure size={16} />
            {korean ? "지식 탐색" : "Explore knowledge"}
          </Link>
        </div>
      </section>
    </div>
  );
}
