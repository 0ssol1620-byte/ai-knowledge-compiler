"use client";

import {
  CheckCircle,
  EnvelopeSimple,
  WarningCircle,
} from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { ApiError, apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { normalizeSessionResponse } from "@/lib/session";

type VerificationState = "verifying" | "verified" | "invalid";

export function VerifyEmailPage({
  token,
  expectToken,
}: {
  token?: string;
  expectToken: boolean;
}) {
  const started = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const setSession = useAuthStore((state) => state.setSession);
  const [state, setState] = useState<VerificationState>(
    expectToken ? "verifying" : "invalid",
  );
  const [message, setMessage] = useState(
    expectToken
      ? "일회용 확인 링크를 검사하고 있습니다…"
      : "확인 링크가 올바르지 않거나 만료되었습니다.",
  );

  useEffect(() => {
    const fragmentToken = new URLSearchParams(
      window.location.hash.slice(1),
    ).get("token");
    const verificationToken = token ?? fragmentToken;
    window.history.replaceState(null, "", "/verify-email");
    heading.current?.focus();
    if (!verificationToken) {
      queueMicrotask(() => {
        setState("invalid");
        setMessage("확인 링크가 올바르지 않거나 만료되었습니다.");
      });
      return;
    }
    if (started.current) return;
    started.current = true;
    void apiRequest<unknown>("/v1/auth/verify-email", {
      method: "POST",
      body: JSON.stringify({ token: verificationToken }),
    })
      .then(normalizeSessionResponse)
      .then((session) => {
        setSession({
          tenantId: session.tenantId,
          userName: session.displayName,
          email: session.email,
          emailVerified: session.emailVerified,
          roles: session.roles,
        });
        setState("verified");
        setMessage("이메일 확인을 마쳤으며 무료 크레딧을 사용할 수 있습니다.");
      })
      .catch((reason: unknown) => {
        setState("invalid");
        setMessage(verificationError(reason));
      });
  }, [setSession, token]);

  return (
    <div className="login-page">
      <section className="login-story">
        <BrandMark />
        <div className="login-story-copy">
          <h1>소유권을 확인한 계정만 문서를 처리할 수 있습니다.</h1>
          <p>
            확인 링크는 한 번만 검사합니다. 토큰 원문은 서버에 저장하지 않으며
            확인을 마친 링크는 다시 사용할 수 없습니다.
          </p>
        </div>
      </section>
      <main className="login-form-wrap">
        <section
          className="login-form verification-card"
          aria-busy={state === "verifying"}
          aria-live="polite"
        >
          {state === "verifying" && (
            <EnvelopeSimple size={36} weight="duotone" aria-hidden="true" />
          )}
          {state === "verified" && (
            <CheckCircle size={36} weight="fill" aria-hidden="true" />
          )}
          {state === "invalid" && (
            <WarningCircle size={36} weight="fill" aria-hidden="true" />
          )}
          <div>
            <h2 ref={heading} tabIndex={-1}>
              {state === "verifying"
                ? "이메일 확인 중"
                : state === "verified"
                  ? "이메일 확인 완료"
                  : "새 링크를 요청해 주세요"}
            </h2>
            <p>{message}</p>
          </div>
          {state === "verifying" && (
            <div className="verification-progress" aria-hidden="true">
              <span className="spinner" />
            </div>
          )}
          {state === "verified" && (
            <Link
              className="primary-button login-submit"
              href={"/home" as Route}
            >
              워크스페이스 열기
            </Link>
          )}
          {state === "invalid" && (
            <Link
              className="primary-button login-submit"
              href={"/login" as Route}
            >
              로그인 후 새 링크 요청하기
            </Link>
          )}
        </section>
      </main>
    </div>
  );
}

function verificationError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "확인 시도가 너무 많습니다. 잠시 후 새 링크를 요청해 주세요.";
  }
  return "확인 링크가 올바르지 않거나, 만료되었거나, 이미 사용되었습니다.";
}
