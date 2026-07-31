import {
  FileText,
  LockKey,
  Receipt,
  ShieldCheck,
  Timer,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { UploadPanel } from "@/components/upload-panel";
import { getRequestLocale } from "@/lib/locale-server";

const COPY = {
  en: {
    title: "Quick convert",
    jobs: "Jobs",
    heading: "Start a new conversion",
    intro:
      "Add documents to run security checks and page analysis first. Processing does not begin until you review the time range and maximum credit reservation.",
    privateTitle: "Private route first",
    privateBody: "External providers require explicit workspace consent",
    after: "After you select files",
    preflight: "Review the preflight first",
    preflightBody:
      "Inspect the analysis, then choose the processing route and output formats yourself.",
    checks: [
      ["File safety", "Integrity, malware, encryption, and supported formats"],
      ["Page composition", "Native text, OCR, tables, and formula pages"],
      ["Processing time", "Estimated completion range and page-level routes"],
      [
        "Credit ceiling",
        "Estimated use, maximum reservation, and unused return",
      ],
    ],
  },
  ko: {
    title: "빠른 변환",
    jobs: "작업",
    heading: "새 변환 시작",
    intro:
      "먼저 문서를 추가해 보안 검사와 페이지 분석을 실행합니다. 예상 시간 범위와 최대 크레딧 예약량을 검토하기 전에는 처리를 시작하지 않습니다.",
    privateTitle: "비공개 처리 우선",
    privateBody: "외부 제공자 사용에는 워크스페이스의 명시적 동의가 필요합니다",
    after: "파일 선택 후",
    preflight: "사전 분석을 먼저 검토하세요",
    preflightBody:
      "분석 결과를 확인한 뒤 처리 경로와 출력 형식을 직접 선택합니다.",
    checks: [
      ["파일 안전성", "무결성, 악성 코드, 암호화와 지원 형식"],
      ["페이지 구성", "네이티브 텍스트, OCR, 표와 수식 페이지"],
      ["처리 시간", "예상 완료 범위와 페이지별 처리 경로"],
      ["크레딧 상한", "예상 사용량, 최대 예약량과 미사용 반환"],
    ],
  },
} as const;

export async function generateMetadata(): Promise<Metadata> {
  const locale = await getRequestLocale();
  return { title: COPY[locale].title };
}

export default async function QuickConvertPage() {
  const locale = await getRequestLocale();
  const copy = COPY[locale];
  const icons = [ShieldCheck, FileText, Timer, Receipt] as const;
  return (
    <div className="page-shell quick-convert-page" data-locale={locale}>
      <nav
        className="page-breadcrumb"
        aria-label={locale === "ko" ? "현재 위치" : "Breadcrumb"}
      >
        <span>{copy.jobs}</span>
        <span aria-hidden="true">/</span>
        <strong>{copy.title}</strong>
      </nav>
      <section className="quick-convert-intro">
        <div>
          <h1>{copy.heading}</h1>
          <p>{copy.intro}</p>
        </div>
        <div className="quick-convert-policy">
          <LockKey size={18} aria-hidden="true" />
          <span>
            <strong>{copy.privateTitle}</strong>
            <small>{copy.privateBody}</small>
          </span>
        </div>
      </section>
      <div className="quick-convert-workbench">
        <UploadPanel showPolicy={false} />
        <aside className="preflight-explainer">
          <header>
            <p>{copy.after}</p>
            <h2>{copy.preflight}</h2>
            <span>{copy.preflightBody}</span>
          </header>
          <ul>
            {copy.checks.map(([title, body], index) => {
              const Icon = icons[index]!;
              return (
                <li key={title}>
                  <Icon size={19} aria-hidden="true" />
                  <span>
                    <strong>{title}</strong>
                    <small>{body}</small>
                  </span>
                </li>
              );
            })}
          </ul>
        </aside>
      </div>
    </div>
  );
}
