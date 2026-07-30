import {
  ArrowSquareOut,
  FileText,
  Scales,
  ShieldCheck,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "도움말·고지",
};

export default function NoticesPage() {
  return (
    <div className="simple-page notices-page">
      <h1>도움말·고지</h1>
      <p>
        사용한 기술, 데이터 처리 방식, 정확성 한계와 지원 절차를 숨기지
        않습니다.
      </p>
      <div className="notice-grid">
        <article className="panel notice-card" id="privacy">
          <ShieldCheck size={20} weight="fill" />
          <h2>보안·개인정보</h2>
          <p>
            외부 전송 opt-in, 보존·삭제, incident 대응과 subprocessor 정책을
            확인합니다.
          </p>
          <a href="#privacy">
            개인정보 처리 설명
            <ArrowSquareOut size={14} />
          </a>
        </article>
        <article className="panel notice-card" id="opensource">
          <Scales size={20} weight="fill" />
          <h2>Open Source Notices</h2>
          <p>
            모델 weight, 코드, runtime, 데이터셋 라이선스를 각각 기록합니다.
          </p>
          <a href="#opensource">
            의존성 고지
            <ArrowSquareOut size={14} />
          </a>
        </article>
        <article className="panel notice-card">
          <FileText size={20} weight="fill" />
          <h2>출력 정확성과 검토</h2>
          <p>
            합성 confidence 대신 실제 근거 연결과 숫자·표 경고를 제공합니다.
          </p>
          <a href="/workspace">
            Review UX 보기
            <ArrowSquareOut size={14} />
          </a>
        </article>
      </div>
    </div>
  );
}
