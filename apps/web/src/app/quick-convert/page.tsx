import {
  CheckCircle,
  Clock,
  FileText,
  LockKey,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { UploadPanel } from "@/components/upload-panel";

export const metadata: Metadata = { title: "빠른 변환" };

export default function QuickConvertPage() {
  return (
    <div className="page-shell quick-convert-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Quick convert</p>
          <h1>문서를 검증 가능한 AI용 파일로</h1>
          <p>
            업로드 후 보안 검사와 문서 분석을 먼저 수행하고, 처리 범위와 최대
            크레딧을 확인한 뒤 시작합니다.
          </p>
        </div>
        <span className="policy-state safe">
          <LockKey size={14} weight="fill" aria-hidden="true" />
          외부 provider 기본 차단
        </span>
      </section>
      <div className="quick-convert-grid">
        <UploadPanel />
        <aside className="panel preflight-explainer">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Before processing</p>
              <h2>Preflight에서 확인하는 항목</h2>
            </div>
          </div>
          <ol>
            <li>
              <ShieldCheck size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>보안과 파일 무결성</strong>
                <small>해시, 악성 파일 검사, 지원 형식과 암호 여부</small>
              </span>
            </li>
            <li>
              <FileText size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>페이지별 처리 경로</strong>
                <small>Native, OCR, 복잡 표·수식 페이지를 분리</small>
              </span>
            </li>
            <li>
              <Clock size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>시간과 크레딧 범위</strong>
                <small>예상값과 예약 최대값, 미사용 예약 반환 정책</small>
              </span>
            </li>
            <li>
              <CheckCircle size={18} weight="duotone" aria-hidden="true" />
              <span>
                <strong>출력 목표</strong>
                <small>Markdown, Vault, RAG, Knowledge Graph</small>
              </span>
            </li>
          </ol>
        </aside>
      </div>
    </div>
  );
}
