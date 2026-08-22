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
import { useStructaraLocale } from "@/components/locale-provider";
import { ApiError, apiRequest } from "@/lib/api-client";
import type { StructaraLocale } from "@/lib/locale";

const COPY = {
  en: {
    hero: "Verify your workspace email.",
    heroBody:
      "Free processing credits remain locked until your email is verified. Each verification link works once and expires after a limited time.",
    requested: "Verification email requested",
    eligiblePrefix: "If an eligible account exists for",
    eligibleSuffix: "the link will arrive shortly.",
    requestedAgain: "A new verification link has been requested.",
    requesting: "Requesting…",
    resend: "Resend verification email",
    return: "Return to sign in",
  },
  ko: {
    hero: "워크스페이스 이메일을 인증하세요.",
    heroBody:
      "이메일 인증 전에는 무료 처리 크레딧이 잠금 상태로 유지됩니다. 인증 링크는 한 번만 사용할 수 있으며 제한된 시간 후 만료됩니다.",
    requested: "인증 이메일 요청 완료",
    eligiblePrefix: "인증 가능한 계정이",
    eligibleSuffix: "주소로 존재하면 링크가 곧 도착합니다.",
    requestedAgain: "새 인증 링크를 요청했습니다.",
    requesting: "요청 중…",
    resend: "인증 이메일 다시 보내기",
    return: "로그인으로 돌아가기",
  },
} as const;

export function VerificationPending({
  email,
  loginHref,
}: {
  email: string;
  loginHref: string;
}) {
  const { locale } = useStructaraLocale();
  const copy = COPY[locale];
  const [sending, setSending] = useState(false);
  const [notice, setNotice] = useState<string>();
  const [error, setError] = useState<string>();
  const heading = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    heading.current?.focus();
  }, []);

  return (
    <div className="login-page" data-locale={locale}>
      <section className="login-story">
        <BrandMark />
        <div className="login-story-copy">
          <h1>{copy.hero}</h1>
          <p>{copy.heroBody}</p>
        </div>
      </section>
      <main id="main-content" className="login-form-wrap">
        <section className="login-form verification-card" aria-live="polite">
          <EnvelopeSimple size={36} weight="duotone" aria-hidden="true" />
          <div>
            <h2 ref={heading} tabIndex={-1}>
              {copy.requested}
            </h2>
            <p>
              {copy.eligiblePrefix} <strong>{email}</strong>{" "}
              {copy.eligibleSuffix}
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
                  setNotice(copy.requestedAgain);
                })
                .catch((reason: unknown) => {
                  setError(resendError(reason, locale));
                })
                .finally(() => setSending(false));
            }}
          >
            {sending ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <PaperPlaneTilt size={16} weight="fill" aria-hidden="true" />
            )}
            {sending ? copy.requesting : copy.resend}
          </button>
          <Link className="verification-secondary" href={loginHref as Route}>
            {copy.return}
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
        </section>
      </main>
    </div>
  );
}

function resendError(error: unknown, locale: StructaraLocale): string {
  const korean = locale === "ko";
  if (error instanceof ApiError) {
    if (error.code === "CAPTCHA_REQUIRED") {
      return korean
        ? "추가 인증이 필요합니다. 잠시 후 다시 시도하세요."
        : "Additional verification is required. Please try again shortly.";
    }
    if (error.status === 429) {
      return korean
        ? "요청이 너무 많습니다. 잠시 후 다시 시도하세요."
        : "Too many requests. Please try again shortly.";
    }
    return korean
      ? `요청을 완료할 수 없습니다. 오류 코드: ${error.code || error.status}`
      : error.message;
  }
  return korean
    ? "요청을 완료할 수 없습니다. 잠시 후 다시 시도하세요."
    : "The request could not be completed. Please try again shortly.";
}
