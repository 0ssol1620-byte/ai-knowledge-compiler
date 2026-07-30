import {
  ArrowRight,
  CheckCircle,
  Clock,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "활동" };

export default function ActivityPage() {
  return (
    <div className="simple-page activity-page">
      <p className="eyebrow">Processing activity</p>
      <h1>활동</h1>
      <p>진행 중인 작업, 검토 필요 항목과 최근 완료를 한곳에서 확인합니다.</p>
      <div className="activity-status-grid">
        <Link href="/workspace" className="panel">
          <Clock size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>처리 작업</strong>
            <small>페이지별 실제 상태와 이벤트 보기</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link href="/review" className="panel">
          <Warning size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>검토 스튜디오</strong>
            <small>위험도와 영향도 순으로 문제 해결</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
        <Link href="/home" className="panel">
          <CheckCircle size={20} weight="duotone" aria-hidden="true" />
          <span>
            <strong>최근 프로젝트</strong>
            <small>완료·내보내기 상태 확인</small>
          </span>
          <ArrowRight size={16} aria-hidden="true" />
        </Link>
      </div>
    </div>
  );
}
