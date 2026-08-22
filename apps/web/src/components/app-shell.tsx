"use client";

import dynamic from "next/dynamic";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

/*
 * The route decision, and nothing else.
 *
 * This component used to be the whole application chrome: sidebar, command
 * palette, session check, twenty Phosphor icons and the API client. It already
 * knew it was on a marketing route and returned `children` untouched there --
 * but it is imported by the root layout, so every one of those dependencies
 * shipped with the homepage anyway. Runtime branching does not remove code from
 * a bundle.
 *
 * Measured on /product, the heaviest of the four URLs the §22 ratchet watches:
 * zod arrived through api-client at 21 KB gzip, the icon set at 16 KB, for a
 * page that renders none of it and never calls the API.
 *
 * Splitting it means the chrome is a chunk the marketing routes never request.
 * The dynamic import keeps server rendering (no `ssr: false`), so authenticated
 * routes behave exactly as before -- they simply fetch the chunk they were
 * always going to use.
 */

const MARKETING_PREFIXES = [
  "/product",
  "/solutions",
  "/demo",
  "/research",
  "/security",
  "/pricing",
  "/customers",
  "/developers",
  "/company",
  "/legal",
] as const;

const AuthenticatedShell = dynamic(
  () =>
    import("@/components/authenticated-shell").then(
      (module) => module.AuthenticatedShell,
    ),
  { loading: () => null },
);

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();

  const marketingRoute =
    pathname === "/" ||
    pathname === "/benchmarks" ||
    MARKETING_PREFIXES.some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
    );
  const authRoute =
    pathname === "/login" ||
    pathname === "/signup" ||
    pathname === "/onboarding" ||
    pathname.startsWith("/forgot-password") ||
    pathname.startsWith("/sso");
  // W1 comp gallery — renders a bare design comp with no shell so the three
  // variants can be captured under identical conditions (§25.1). Removed once
  // decision.md records the chosen direction.
  const designRoute = pathname.startsWith("/design/");
  const bareRoute =
    marketingRoute ||
    authRoute ||
    designRoute ||
    pathname === "/verify-email" ||
    pathname.startsWith("/notices");

  if (bareRoute) {
    return children;
  }

  return <AuthenticatedShell>{children}</AuthenticatedShell>;
}
