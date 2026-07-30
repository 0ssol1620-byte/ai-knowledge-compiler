import {
  Buildings,
  Check,
  CreditCard,
  Database,
  Key,
  LockKey,
  ShieldCheck,
  UsersThree,
} from "@phosphor-icons/react/dist/ssr";
import type { Metadata } from "next";

import { SettingsLive } from "@/components/settings-live";

export const metadata: Metadata = {
  title: "설정",
};

export default function SettingsPage() {
  if (process.env.NEXT_PUBLIC_AKC_DEMO_MODE !== "true") {
    return <SettingsLive />;
  }
  return <DemoSettingsPage />;
}

function DemoSettingsPage() {
  return (
    <div className="simple-page settings-page">
      <p className="eyebrow">Workspace policy</p>
      <h1>설정</h1>
      <p>
        데이터 보존, 외부 처리, 역할과 크레딧 정책을 워크스페이스 단위로
        관리합니다.
      </p>

      <div className="settings-layout">
        <nav className="settings-nav" aria-label="설정 섹션">
          <a href="#privacy" className="active">
            <ShieldCheck size={16} weight="fill" />
            개인정보·처리
          </a>
          <a href="#retention">
            <Database size={16} />
            보존·삭제
          </a>
          <a href="#members">
            <UsersThree size={16} />
            멤버·역할
          </a>
          <a href="#api">
            <Key size={16} />
            API·Webhook
          </a>
          <a href="#billing">
            <CreditCard size={16} />
            플랜·크레딧
          </a>
        </nav>

        <div className="settings-content">
          <section className="settings-section" id="privacy">
            <header>
              <div>
                <h2>외부 처리 정책</h2>
                <p>
                  모델 제공자에게 페이지를 전송하는 기능은 기본적으로 꺼져
                  있습니다.
                </p>
              </div>
              <span className="policy-state safe">
                <LockKey size={13} weight="fill" />
                Private default
              </span>
            </header>
            <label className="setting-row">
              <span>
                <strong>외부 모델 API fallback</strong>
                <small>
                  내부 parser가 실패한 최소 페이지에만 사용하며 매번 사전
                  고지합니다.
                </small>
              </span>
              <input type="checkbox" className="switch" />
            </label>
            <label className="setting-row">
              <span>
                <strong>제품 개선 데이터 제공</strong>
                <small>
                  명시적 opt-in 전에는 어떤 문서나 수정 내용도 학습 pool에
                  들어가지 않습니다.
                </small>
              </span>
              <input type="checkbox" className="switch" />
            </label>
            <label className="setting-row">
              <span>
                <strong>미리보기에서 감지된 비밀정보 마스킹</strong>
                <small>
                  원본은 보존하고 화면과 외부 전송 후보에서만 가립니다.
                </small>
              </span>
              <input type="checkbox" className="switch" defaultChecked />
            </label>
          </section>

          <section className="settings-section" id="retention">
            <header>
              <div>
                <h2>보존·삭제</h2>
                <p>원본과 파생 데이터의 생명주기를 분리합니다.</p>
              </div>
            </header>
            <div className="retention-grid">
              <label>
                <span>검증된 원본</span>
                <select defaultValue="7">
                  <option value="1">24시간</option>
                  <option value="7">7일</option>
                  <option value="30">30일</option>
                  <option value="project">프로젝트 기간</option>
                </select>
              </label>
              <label>
                <span>Raw model response</span>
                <select defaultValue="7">
                  <option value="1">24시간</option>
                  <option value="7">7일</option>
                  <option value="30">30일</option>
                </select>
              </label>
              <label>
                <span>최종 export</span>
                <select defaultValue="30">
                  <option value="7">7일</option>
                  <option value="30">30일</option>
                  <option value="project">프로젝트 기간</option>
                </select>
              </label>
            </div>
            <div className="deletion-assurance">
              <Check size={15} weight="bold" />
              삭제 시 source, render, crop, raw response, export, vector index와
              cache를 모두 확인한 뒤 content 없는 deletion receipt를 발급합니다.
            </div>
          </section>

          <section className="settings-section" id="members">
            <header>
              <div>
                <h2>워크스페이스</h2>
                <p>역할별로 프로젝트·검토·billing 권한을 분리합니다.</p>
              </div>
              <button type="button" className="secondary-button compact">
                <Buildings size={14} />
                멤버 초대
              </button>
            </header>
            <div className="member-row">
              <span className="avatar">YS</span>
              <span>
                <strong>Workspace owner</strong>
                <small>you@example.com</small>
              </span>
              <span className="status-badge neutral">Owner</span>
            </div>
          </section>

          <div className="settings-save">
            <span>변경 내용은 감사 로그에 기록됩니다.</span>
            <button className="primary-button" type="button">
              설정 저장
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
