import {
  FileText,
  LockKey,
  Receipt,
  ShieldCheck,
  Timer,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { UploadPanel } from "@/components/upload-panel";

export const metadata: Metadata = { title: "빠른 변환" };

export default function QuickConvertPage() {
  return (
    <div className="page-shell quick-convert-page">
      <nav className="page-breadcrumb" aria-label="현재 위치">
        <span>작업</span>
        <span aria-hidden="true">/</span>
        <strong>빠른 변환</strong>
      </nav>
      <section className="quick-convert-intro">
        <div>
          <h1>새 변환 시작</h1>
          <p>
            문서를 추가하면 보안 검사와 페이지 분석을 먼저 실행합니다. 처리
            시간과 최대 크레딧을 확인하기 전에는 변환을 시작하지 않습니다.
          </p>
        </div>
        <div className="quick-convert-policy">
          <LockKey size={18} aria-hidden="true" />
          <span>
            <strong>외부 API 꺼짐</strong>
            <small>현재 워크스페이스의 기본 정책</small>
          </span>
        </div>
      </section>
      <div className="quick-convert-workbench">
        <UploadPanel showPolicy={false} />
        <aside className="preflight-explainer">
          <header>
            <p>파일을 선택한 다음</p>
            <h2>변환 전에 먼저 확인합니다</h2>
            <span>
              분석 결과를 검토하고 처리 방식과 출력 형식을 직접 선택할 수
              있습니다.
            </span>
          </header>
          <ul>
            <li>
              <ShieldCheck size={19} aria-hidden="true" />
              <span>
                <strong>파일 안전성</strong>
                <small>무결성, 악성 파일, 암호 및 지원 형식</small>
              </span>
            </li>
            <li>
              <FileText size={19} aria-hidden="true" />
              <span>
                <strong>페이지 구성</strong>
                <small>일반 텍스트, OCR, 표·수식 페이지 구분</small>
              </span>
            </li>
            <li>
              <Timer size={19} aria-hidden="true" />
              <span>
                <strong>처리 시간</strong>
                <small>예상 완료 시간과 페이지별 처리 경로</small>
              </span>
            </li>
            <li>
              <Receipt size={19} aria-hidden="true" />
              <span>
                <strong>크레딧 상한</strong>
                <small>예상 사용량, 예약 최대값, 미사용분 반환</small>
              </span>
            </li>
          </ul>
        </aside>
      </div>
    </div>
  );
}
