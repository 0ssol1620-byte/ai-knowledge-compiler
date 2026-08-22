import type { Metadata } from "next";

import { AuthPage } from "@/components/auth-page";
import { getRequestLocale } from "@/lib/locale-server";

interface LoginPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({
  searchParams,
}: LoginPageProps): Promise<Metadata> {
  const params = await searchParams;
  const locale = await getRequestLocale();
  const registering = first(params.mode) === "register";
  return {
    title:
      locale === "ko"
        ? registering
          ? "워크스페이스 만들기"
          : "로그인"
        : registering
          ? "Create a workspace"
          : "Sign in",
  };
}

export default async function LoginPage({ searchParams }: LoginPageProps) {
  const params = await searchParams;
  const rawMode = first(params.mode);
  const rawNext = first(params.next);
  const nextPath =
    rawNext?.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/";

  return (
    <AuthPage
      mode={rawMode === "register" ? "register" : "login"}
      nextPath={nextPath}
    />
  );
}

function first(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
