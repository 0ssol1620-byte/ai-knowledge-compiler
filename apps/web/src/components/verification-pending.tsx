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
          <p className="eyebrow">One secure step remains</p>
          <h1>Verify the address that owns this workspace.</h1>
          <p>
            Free processing credits stay locked until the email address is
            verified. Verification links are single-use and expire
            automatically.
          </p>
        </div>
      </section>
      <main className="login-form-wrap">
        <section className="login-form verification-card" aria-live="polite">
          <EnvelopeSimple size={36} weight="duotone" aria-hidden="true" />
          <div>
            <p className="eyebrow">Check your inbox</p>
            <h2 ref={heading} tabIndex={-1}>
              Verification email requested
            </h2>
            <p>
              If an eligible account exists for <strong>{email}</strong>, a
              verification link will arrive shortly.
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
                  setNotice(
                    "If the address is eligible, a fresh verification link has been queued.",
                  );
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
            {sending ? "Requesting…" : "Resend verification"}
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
      return "Additional verification is required. Wait briefly, then try again.";
    }
    if (error.status === 429) {
      return "Too many requests. Please wait before requesting another link.";
    }
    return error.message;
  }
  return "The request could not be completed. Please try again later.";
}
