import type { Metadata } from "next";

import { VerifyEmailPage } from "@/components/verify-email-page";

export const metadata: Metadata = {
  title: "Verify email",
};

interface VerificationPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function VerificationPage({
  searchParams,
}: VerificationPageProps) {
  const params = await searchParams;
  const value = params.token;
  const token = Array.isArray(value) ? value[0] : value;
  const verification = Array.isArray(params.verification)
    ? params.verification[0]
    : params.verification;

  return (
    <VerifyEmailPage
      token={token}
      expectToken={Boolean(token) || verification === "1"}
    />
  );
}
