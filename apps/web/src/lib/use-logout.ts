"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";

import { apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

/**
 * Real sign-out: POST /v1/auth/logout, then clear local session state and
 * return to /login. Extracted from AccountPage (C1) so every surface that
 * offers a sign-out control — the account page, the topbar account menu —
 * shares one mutation instead of each reimplementing it.
 */
export function useLogout() {
  const router = useRouter();
  const clearSession = useAuthStore((state) => state.clearSession);

  return useMutation({
    mutationFn: () => apiRequest("/v1/auth/logout", { method: "POST" }),
    onSuccess: () => {
      clearSession();
      router.replace("/login");
      router.refresh();
    },
  });
}
