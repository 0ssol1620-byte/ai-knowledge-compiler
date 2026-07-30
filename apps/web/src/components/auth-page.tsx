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
          <h1>AI output should never require blind trust.</h1>
          <p>
            Inspect the source page and coordinates, processing route, and
            complete edit history yourself.
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
              External model APIs off by default
            </li>
          </ul>
        </div>
        <div className="login-security">
          <ShieldCheck size={17} weight="fill" aria-hidden="true" />
          Credentials are carried in secure cookies, not browser storage.
          Documents are used for training only with explicit consent.
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
            <h2>{registering ? "Create workspace" : "Sign in to workspace"}</h2>
            <p>
              {registering
                ? "Create the owner account and first workspace securely."
                : "Continue with active projects and the review queue."}
            </p>
          </div>

          {registering && (
            <>
              <label className="field">
                <span>Workspace name</span>
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
                <span>Display name</span>
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
            <span>Email</span>
            <input
              type="email"
              name="email"
              autoComplete="email"
              required
              placeholder="you@company.com"
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              type="password"
              name="password"
              autoComplete={registering ? "new-password" : "current-password"}
              minLength={12}
              required
              aria-describedby="password-help"
              placeholder="At least 12 characters"
            />
            <small id="password-help" className="field-help">
              Use at least 12 characters. Passwords are not stored in the page
              or browser storage.
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
                ? "Creating…"
                : "Checking securely…"
              : registering
                ? "Create workspace"
                : "Sign in"}
            {!loading && <ArrowRight size={15} aria-hidden="true" />}
          </button>
          <p className="login-register">
            {registering ? "Already have an account? " : "Need an account? "}
            <Link href={(registering ? loginHref : registerHref) as Route}>
              {registering ? "Sign in" : "Create workspace"}
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
      INVALID_CREDENTIALS: "The email or password is incorrect.",
      EMAIL_EXISTS:
        "This email is already registered. Sign in or use another email.",
      REGISTER_CONFLICT:
        "A workspace with the same information already exists.",
      NO_TENANT_MEMBERSHIP: "No workspace is connected to this account.",
      CSRF_ORIGIN_DENIED:
        "This request came from an unapproved origin. Try again from the official service URL.",
    };
    return messages[error.code] ?? error.message;
  }
  if (error instanceof Error) return error.message;
  return registering
    ? "The workspace could not be created."
    : "Sign-in failed.";
}
