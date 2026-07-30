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
      ? "Checking your one-time verification link…"
      : "The verification link is invalid or has expired.",
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
        setMessage("The verification link is invalid or has expired.");
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
        setMessage(
          "Your email is verified and free credits are now available.",
        );
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
          <h1>Only verified account owners can process documents.</h1>
          <p>
            Verification links are checked once. Raw tokens are never stored,
            and a verified link cannot be used again.
          </p>
        </div>
      </section>
      <main id="main-content" className="login-form-wrap">
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
                ? "Verifying email"
                : state === "verified"
                  ? "Email verified"
                  : "Request a new link"}
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
              Open workspace
            </Link>
          )}
          {state === "invalid" && (
            <Link
              className="primary-button login-submit"
              href={"/login" as Route}
            >
              Sign in to request a new link
            </Link>
          )}
        </section>
      </main>
    </div>
  );
}

function verificationError(error: unknown): string {
  if (error instanceof ApiError && error.status === 429) {
    return "Too many verification attempts. Request a new link shortly.";
  }
  return "The verification link is invalid, expired, or already used.";
}
