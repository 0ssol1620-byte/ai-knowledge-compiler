"use client";

import { create } from "zustand";

interface AuthState {
  tenantId?: string;
  userName?: string;
  email?: string;
  emailVerified?: boolean;
  roles: string[];
  authenticated: boolean;
  setSession: (session: {
    tenantId: string;
    userName: string;
    email?: string;
    emailVerified?: boolean;
    roles?: string[];
  }) => void;
  clearSession: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  authenticated: false,
  roles: [],
  setSession: (session) =>
    set({
      ...session,
      roles: session.roles ?? [],
      authenticated: true,
    }),
  clearSession: () =>
    set({
      authenticated: false,
      tenantId: undefined,
      userName: undefined,
      email: undefined,
      emailVerified: undefined,
      roles: [],
    }),
}));
