"use client";

import { ArrowRight, Check, LockKey, ShieldCheck } from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { VerificationPending } from "@/components/verification-pending";
import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { normalizeSessionResponse } from "@/lib/session";

export function AuthPage({
  mode,
  nextPath,
}: {
  mode: "login" | "register";
  nextPath: string;
}) {
  const router = useRouter();
  const setSession = useAuthStore((state) => state.setSession);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [pendingEmail, setPendingEmail] = useState<string>();
  const registering = mode === "register";
  const nextQuery =
    nextPath === "/" ? "" : `&next=${encodeURIComponent(nextPath)}`;
  const loginHref =
    nextPath === "/" ? "/login" : `/login?next=${encodeURIComponent(nextPath)}`;
  const registerHref = `/login?mode=register${nextQuery}`;

  if (pendingEmail) {
    return <VerificationPending email={pendingEmail} loginHref={loginHref} />;
  }

  return (
    <div className="login-page">
      <section className="login-story">
        <BrandMark />
        <div className="login-story-copy">
          <h1>AI 결과를 믿으라고 요구하지 않습니다.</h1>
          <p>
            원본 페이지와 좌표, 처리 경로, 수정 이력까지 직접 확인할 수
            있습니다.
          </p>
          <ul>
            <li>
              <Check size={15} weight="bold" aria-hidden="true" />
              Source → block → knowledge provenance
            </li>
            <li>
              <Check size={15} weight="bold" aria-hidden="true" />
              Portable Markdown · Obsidian · RAG
            </li>
            <li>
              <Check size={15} weight="bold" aria-hidden="true" />
              외부 모델 API 기본 비활성화
            </li>
          </ul>
        </div>
        <div className="login-security">
          <ShieldCheck size={17} weight="fill" aria-hidden="true" />
          인증 정보는 브라우저 저장소가 아닌 보안 쿠키로 전달합니다. 문서 학습
          사용은 명시적으로 동의한 경우에만 허용됩니다.
        </div>
      </section>
      <main className="login-form-wrap">
        <form
          className="login-form"
          aria-busy={loading}
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setLoading(true);
            setError(undefined);
            const payload = registering
              ? {
                  tenant_name: textValue(form, "tenant_name"),
                  display_name: textValue(form, "display_name"),
                  email: textValue(form, "email"),
                  password: textValue(form, "password"),
                }
              : {
                  email: textValue(form, "email"),
                  password: textValue(form, "password"),
                };
            void apiRequest<unknown>(
              registering ? "/v1/auth/register" : "/v1/auth/login",
              {
                method: "POST",
                ...(registering ? { idempotencyKey: crypto.randomUUID() } : {}),
                body: JSON.stringify(payload),
              },
            )
              .then(normalizeSessionResponse)
              .then((result) => {
                if (result.emailVerified === false) {
                  setPendingEmail(result.email ?? String(payload.email));
                  return;
                }
                setSession({
                  tenantId: result.tenantId,
                  userName: result.displayName,
                  email: result.email,
                  emailVerified: result.emailVerified,
                  roles: result.roles,
                });
                router.replace(nextPath as Route);
                router.refresh();
              })
              .catch((reason: unknown) => {
                setError(authErrorMessage(reason, registering));
              })
              .finally(() => setLoading(false));
          }}
        >
          <div>
            <h2>
              {registering ? "워크스페이스 만들기" : "워크스페이스 로그인"}
            </h2>
            <p>
              {registering
                ? "소유자 계정과 첫 워크스페이스를 안전하게 생성합니다."
                : "처리 중인 프로젝트와 검토 대기열을 이어서 확인하세요."}
            </p>
          </div>

          {registering && (
            <>
              <label className="field">
                <span>워크스페이스 이름</span>
                <input
                  type="text"
                  name="tenant_name"
                  autoComplete="organization"
                  minLength={1}
                  maxLength={200}
                  required
                />
              </label>
              <label className="field">
                <span>표시 이름</span>
                <input
                  type="text"
                  name="display_name"
                  autoComplete="name"
                  minLength={1}
                  maxLength={200}
                  required
                />
              </label>
            </>
          )}

          <label className="field">
            <span>이메일</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
            />
          </label>
          <label className="field">
            <span>비밀번호</span>
            <input
              type="password"
              name="password"
              autoComplete={registering ? "new-password" : "current-password"}
              minLength={12}
              required
              aria-describedby="password-help"
              placeholder="12자 이상"
            />
            <small id="password-help" className="field-help">
              최소 12자를 입력하세요. 비밀번호는 화면이나 브라우저 저장소에
              보관하지 않습니다.
            </small>
          </label>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button
            className="primary-button login-submit"
            type="submit"
            disabled={loading}
          >
            {loading ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <LockKey size={16} weight="fill" aria-hidden="true" />
            )}
            {loading
              ? registering
                ? "생성 중…"
                : "안전하게 확인 중…"
              : registering
                ? "워크스페이스 만들기"
                : "로그인"}
            {!loading && <ArrowRight size={15} aria-hidden="true" />}
          </button>
          <p className="login-register">
            {registering ? "이미 계정이 있나요? " : "아직 계정이 없나요? "}
            <Link href={(registering ? loginHref : registerHref) as Route}>
              {registering ? "로그인" : "워크스페이스 만들기"}
            </Link>
          </p>
        </form>
      </main>
    </div>
  );
}

function textValue(form: FormData, key: string): string {
  const value = form.get(key);
  return typeof value === "string" ? value : "";
}

function authErrorMessage(error: unknown, registering: boolean): string {
  if (error instanceof ApiError) {
    const messages: Record<string, string> = {
      INVALID_CREDENTIALS: "이메일 또는 비밀번호가 올바르지 않습니다.",
      EMAIL_EXISTS:
        "이미 등록된 이메일입니다. 로그인하거나 다른 이메일을 사용하세요.",
      REGISTER_CONFLICT: "같은 정보의 워크스페이스가 이미 존재합니다.",
      NO_TENANT_MEMBERSHIP: "이 계정에 연결된 워크스페이스가 없습니다.",
      CSRF_ORIGIN_DENIED:
        "허용되지 않은 출처의 요청입니다. 공식 서비스 주소에서 다시 시도하세요.",
    };
    return messages[error.code] ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return registering
    ? "워크스페이스를 만들지 못했습니다."
    : "로그인에 실패했습니다.";
}
