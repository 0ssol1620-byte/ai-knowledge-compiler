"use client";

import {
  ArrowRight,
  Check,
  GoogleLogo,
  LockKey,
  ShieldCheck,
} from "@phosphor-icons/react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { BrandMark } from "@/components/brand-mark";
import { useStructaraLocale } from "@/components/locale-provider";
import { VerificationPending } from "@/components/verification-pending";
import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import type { StructaraLocale } from "@/lib/locale";
import { normalizeSessionResponse } from "@/lib/session";

const AUTH_COPY = {
  en: {
    registerHero: "Build knowledge your AI can use.",
    loginHero: "Return to your knowledge workspace.",
    heroBody:
      "Structure documents, verify every important result, and keep the source attached as knowledge moves into people and AI workflows.",
    benefits: [
      "Source → block → knowledge provenance",
      "Portable Markdown · Obsidian · RAG",
      "Processing and retention controlled by policy",
    ],
    security:
      "Credentials are carried in secure cookies, not browser storage. Training and provider policies are never implied by the interface.",
    createTitle: "Create your account",
    signInTitle: "Sign in",
    createIntro: "Start with your name, email, and a secure password.",
    signInIntro: "Continue with active projects and the integrity ledger.",
    displayName: "Display name",
    email: "Email",
    password: "Password",
    passwordPlaceholder: "At least 12 characters",
    passwordHelp:
      "Use at least 12 characters. Passwords are not stored in the page or browser storage.",
    creating: "Creating…",
    checking: "Checking securely…",
    createWorkspace: "Create workspace",
    signIn: "Sign in",
    continueGoogle: "Continue with Google",
    connectingGoogle: "Connecting securely…",
    googleUnavailable:
      "Google sign-in is not configured for this environment. Continue with email or contact your administrator.",
    emailDivider: "or continue with email",
    already: "Already have an account? ",
    need: "Need an account? ",
    workspaceSuffix: "workspace",
  },
  ko: {
    registerHero: "AI가 활용할 수 있는 지식을 구축하세요.",
    loginHero: "지식 워크스페이스로 돌아오세요.",
    heroBody:
      "문서를 구조화하고 중요한 모든 결과를 검증하며, 지식이 사람과 AI 워크플로로 이동해도 원본 연결을 유지합니다.",
    benefits: [
      "원본 → 블록 → 지식 provenance",
      "이식 가능한 Markdown · Obsidian · RAG",
      "정책으로 통제되는 처리와 보존",
    ],
    security:
      "자격 증명은 브라우저 저장소가 아닌 보안 쿠키로 전달됩니다. 학습 및 외부 제공자 정책을 화면만으로 암시하지 않습니다.",
    createTitle: "계정 만들기",
    signInTitle: "로그인",
    createIntro: "이름, 이메일과 안전한 비밀번호로 시작하세요.",
    signInIntro: "활성 프로젝트와 무결성 원장을 이어서 확인하세요.",
    displayName: "표시 이름",
    email: "이메일",
    password: "비밀번호",
    passwordPlaceholder: "12자 이상 입력",
    passwordHelp:
      "12자 이상을 사용하세요. 비밀번호는 페이지나 브라우저 저장소에 저장되지 않습니다.",
    creating: "생성 중…",
    checking: "안전하게 확인 중…",
    createWorkspace: "워크스페이스 만들기",
    signIn: "로그인",
    continueGoogle: "Google로 계속하기",
    connectingGoogle: "안전하게 연결 중…",
    googleUnavailable:
      "이 환경에는 Google 로그인이 구성되지 않았습니다. 이메일로 계속하거나 관리자에게 문의하세요.",
    emailDivider: "또는 이메일로 계속",
    already: "이미 계정이 있나요? ",
    need: "계정이 필요한가요? ",
    workspaceSuffix: "워크스페이스",
  },
} as const;

export function AuthPage({
  mode,
  nextPath,
}: {
  mode: "login" | "register";
  nextPath: string;
}) {
  const { locale } = useStructaraLocale();
  const copy = AUTH_COPY[locale];
  const router = useRouter();
  const setSession = useAuthStore((state) => state.setSession);
  const [loading, setLoading] = useState(false);
  const [oidcLoading, setOidcLoading] = useState(false);
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
    <div className="login-page" data-locale={locale}>
      <section className="login-story">
        <BrandMark />
        <div className="login-story-copy">
          <h1>{registering ? copy.registerHero : copy.loginHero}</h1>
          <p>{copy.heroBody}</p>
          <ul>
            {copy.benefits.map((benefit) => (
              <li key={benefit}>
                <Check size={15} weight="bold" aria-hidden="true" />
                {benefit}
              </li>
            ))}
          </ul>
        </div>
        <div className="login-security">
          <ShieldCheck size={17} weight="fill" aria-hidden="true" />
          {copy.security}
        </div>
      </section>
      <main id="main-content" className="login-form-wrap">
        <form
          className="login-form"
          aria-busy={loading}
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            setLoading(true);
            setError(undefined);
            const displayName = textValue(form, "display_name");
            const payload = registering
              ? {
                  tenant_name: `${displayName || (locale === "ko" ? "내" : "My")} ${copy.workspaceSuffix}`,
                  display_name: displayName,
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
                setError(authErrorMessage(reason, registering, locale));
              })
              .finally(() => setLoading(false));
          }}
        >
          <div>
            <h2>{registering ? copy.createTitle : copy.signInTitle}</h2>
            <p>{registering ? copy.createIntro : copy.signInIntro}</p>
          </div>

          <button
            className="login-google"
            type="button"
            disabled={loading || oidcLoading}
            onClick={() => {
              setOidcLoading(true);
              setError(undefined);
              void apiRequest<{ authorization_url: string }>(
                "/v1/auth/oidc/authorize",
              )
                .then(({ authorization_url: authorizationUrl }) => {
                  const destination = new URL(authorizationUrl);
                  if (destination.protocol !== "https:") {
                    throw new Error("OIDC authorization URL must use HTTPS");
                  }
                  window.location.assign(destination.href);
                })
                .catch(() => {
                  setError(copy.googleUnavailable);
                  setOidcLoading(false);
                });
            }}
          >
            {oidcLoading ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <GoogleLogo size={18} weight="bold" aria-hidden="true" />
            )}
            {oidcLoading ? copy.connectingGoogle : copy.continueGoogle}
          </button>

          <div className="login-divider" aria-hidden="true">
            <span>{copy.emailDivider}</span>
          </div>

          {registering && (
            <label className="field">
              <span>{copy.displayName}</span>
              <input
                type="text"
                name="display_name"
                autoComplete="name"
                minLength={1}
                maxLength={200}
                required
              />
            </label>
          )}

          <label className="field">
            <span>{copy.email}</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
            />
          </label>
          <label className="field">
            <span>{copy.password}</span>
            <input
              type="password"
              name="password"
              autoComplete={registering ? "new-password" : "current-password"}
              minLength={12}
              required
              aria-describedby="password-help"
              placeholder={copy.passwordPlaceholder}
            />
            <small id="password-help" className="field-help">
              {copy.passwordHelp}
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
            disabled={loading || oidcLoading}
          >
            {loading ? (
              <span className="spinner" aria-hidden="true" />
            ) : (
              <LockKey size={16} weight="fill" aria-hidden="true" />
            )}
            {loading
              ? registering
                ? copy.creating
                : copy.checking
              : registering
                ? copy.createWorkspace
                : copy.signIn}
            {!loading && <ArrowRight size={15} aria-hidden="true" />}
          </button>
          <p className="login-register">
            {registering ? copy.already : copy.need}
            <Link href={(registering ? loginHref : registerHref) as Route}>
              {registering ? copy.signIn : copy.createWorkspace}
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

function authErrorMessage(
  error: unknown,
  registering: boolean,
  locale: StructaraLocale,
): string {
  const korean = locale === "ko";
  if (error instanceof ApiError) {
    const messages: Record<string, string> = korean
      ? {
          INVALID_CREDENTIALS: "이메일 또는 비밀번호가 올바르지 않습니다.",
          EMAIL_EXISTS:
            "이미 등록된 이메일입니다. 로그인하거나 다른 이메일을 사용하세요.",
          REGISTER_CONFLICT: "동일한 정보의 워크스페이스가 이미 존재합니다.",
          NO_TENANT_MEMBERSHIP: "이 계정에 연결된 워크스페이스가 없습니다.",
          CSRF_ORIGIN_DENIED:
            "승인되지 않은 출처의 요청입니다. 공식 서비스 주소에서 다시 시도하세요.",
        }
      : {
          INVALID_CREDENTIALS: "The email or password is incorrect.",
          EMAIL_EXISTS:
            "This email is already registered. Sign in or use another email.",
          REGISTER_CONFLICT:
            "A workspace with the same information already exists.",
          NO_TENANT_MEMBERSHIP: "No workspace is connected to this account.",
          CSRF_ORIGIN_DENIED:
            "This request came from an unapproved origin. Try again from the official service URL.",
        };
    return (
      messages[error.code] ??
      (korean
        ? `요청을 완료할 수 없습니다. 오류 코드: ${error.code || error.status}`
        : error.message)
    );
  }
  if (!korean && error instanceof Error) return error.message;
  return korean
    ? registering
      ? "워크스페이스를 만들 수 없습니다."
      : "로그인에 실패했습니다."
    : registering
      ? "The workspace could not be created."
      : "Sign-in failed.";
}
