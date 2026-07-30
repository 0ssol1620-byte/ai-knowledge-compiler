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
          <h1>Verify your workspace email.</h1>
          <p>
            Free processing credits remain locked until your email is verified.
            Each verification link works once and expires after a limited time.
          </p>
        </div>
      </section>
      <main id="main-content" className="login-form-wrap">
        <section className="login-form verification-card" aria-live="polite">
          <EnvelopeSimple size={36} weight="duotone" aria-hidden="true" />
          <div>
            <h2 ref={heading} tabIndex={-1}>
              Verification email requested
            </h2>
            <p>
              If an eligible account exists for <strong>{email}</strong>, the
              link will arrive shortly.
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
                  setNotice("A new verification link has been requested.");
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
            {sending ? "Requesting…" : "Resend verification email"}
          </button>
          <Link className="verification-secondary" href={loginHref as Route}>
            Return to sign in
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
      return "Additional verification is required. Please try again shortly.";
    }
    if (error.status === 429) {
      return "Too many requests. Please try again shortly.";
    }
    return error.message;
  }
  return "The request could not be completed. Please try again shortly.";
}
