"use client";

import {
  ArrowRight,
  EnvelopeSimple,
  PaperPlaneTilt,
} from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { ApiError, apiRequest } from "@/lib/api-client";

export function VerificationPending({
  email,
  loginHref,
}: {
  email: string;
  loginHref: string;
}) {
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
  }, []);

  return (
    <div className="login-page">
      <section className="login-story">
        <BrandMark />
        <div className="login-story-copy">
          <h1>워크스페이스 소유 이메일을 확인하세요.</h1>
          <p>
            이메일 확인 전에는 무료 처리 크레딧을 사용할 수 없습니다. 확인
            링크는 한 번만 사용할 수 있으며 일정 시간이 지나면 만료됩니다.
          </p>
        </div>
      </section>
      <main className="login-form-wrap">
        <section className="login-form verification-card" aria-live="polite">
          <EnvelopeSimple size={36} weight="duotone" aria-hidden="true" />
          <div>
            <h2 ref={heading} tabIndex={-1}>
              확인 메일을 요청했습니다
            </h2>
            <p>
              <strong>{email}</strong> 주소로 등록 가능한 계정이 확인되면 잠시
              후 링크가 도착합니다.
            </p>
          </div>

          {notice && <p className="form-success">{notice}</p>}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}

          <button
            className="primary-button login-submit"
            type="button"
            disabled={sending}
            onClick={() => {
              setSending(true);
              setError(undefined);
              setNotice(undefined);
              void apiRequest("/v1/auth/resend-verification", {
                method: "POST",
                body: JSON.stringify({ email }),
              })
                .then(() => {
                  setNotice("새 확인 링크 발송을 요청했습니다.");
                })
                .catch((reason: unknown) => {
                  setError(resendError(reason));
                })
                .finally(() => setSending(false));
            }}
          >
            {sending ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <PaperPlaneTilt size={16} weight="fill" aria-hidden="true" />
            )}
            {sending ? "요청 중…" : "확인 메일 다시 보내기"}
          </button>
          <Link className="verification-secondary" href={loginHref as Route}>
            로그인으로 돌아가기
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </section>
      </main>
    </div>
  );
}

function resendError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "CAPTCHA_REQUIRED") {
      return "추가 확인이 필요합니다. 잠시 후 다시 시도해 주세요.";
    }
    if (error.status === 429) {
      return "요청 횟수가 너무 많습니다. 잠시 후 다시 시도해 주세요.";
    }
    return error.message;
  }
  return "요청을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}
