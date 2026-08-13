"use client";

import {
  CheckCircle,
  Key,
  SignOut,
  UserCircle,
  Warning,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";

import { ApiKeyManagement } from "@/components/api-key-management";
import { apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";
import { normalizeSessionResponse } from "@/lib/session";
import { useLogout } from "@/lib/use-logout";

/**
 * Real account surface: server-confirmed profile, real sign-out, and real
 * (previously unexposed) API key management. Profile editing (display name,
 * password change) has no backend endpoint as of this change — see the
 * honest-state note below rather than a disabled form pretending to work.
 */
export function AccountPage() {
  const roles = useAuthStore((state) => state.roles);

  const session = useQuery({
    queryKey: ["auth", "session"],
    queryFn: async () =>
      normalizeSessionResponse(await apiRequest<unknown>("/v1/auth/session")),
  });

  const logout = useLogout();

  const canManageKeys = roles.some((role) =>
    ["owner", "admin"].includes(role.toLowerCase()),
  );

  return (
    <div className="simple-page account-page">
      <h1>Account</h1>
      <p>Your profile, session, and API access for this workspace.</p>

      <section className="settings-section" id="profile">
        <header>
          <div>
            <h2>Profile</h2>
            <p>Server-confirmed identity for the active session.</p>
          </div>
          <UserCircle size={20} aria-hidden="true" />
        </header>
        <div className="account-profile-body">
          {session.isPending ? (
            <div className="honest-state compact" aria-busy="true">
              <span className="spinner" aria-hidden="true" />
              <p>Loading your profile.</p>
            </div>
          ) : session.isError ? (
            <div className="honest-state compact" role="alert">
              <Warning size={20} aria-hidden="true" />
              <p>Profile could not be loaded: {session.error.message}</p>
              <button
                type="button"
                className="secondary-button compact"
                onClick={() => void session.refetch()}
              >
                Try again
              </button>
            </div>
          ) : (
            <dl className="account-profile-grid">
              <div>
                <dt>Name</dt>
                <dd>{session.data.displayName}</dd>
              </div>
              <div>
                <dt>Email</dt>
                <dd>
                  {session.data.email ?? "—"}
                  {session.data.emailVerified === true && (
                    <span className="status-badge green">
                      <CheckCircle size={12} weight="fill" aria-hidden="true" />
                      Verified
                    </span>
                  )}
                  {session.data.emailVerified === false && (
                    <span className="status-badge amber">Unverified</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd>{session.data.workspaceName ?? session.data.tenantId}</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>{session.data.roles.join(", ") || "member"}</dd>
              </div>
              <div>
                <dt>Credit balance</dt>
                <dd>
                  {session.data.creditBalance !== undefined
                    ? session.data.creditBalance.toLocaleString()
                    : "—"}
                </dd>
              </div>
            </dl>
          )}

          <div className="honest-state compact" id="profile-editing-note">
            <Warning size={20} aria-hidden="true" />
            <p>
              Changing your display name or password is not backend-supported
              yet — there is no profile-update endpoint in this environment.
              This page will not pretend to save an edit it cannot persist.
            </p>
          </div>

          <button
            className="secondary-button"
            type="button"
            disabled={logout.isPending}
            onClick={() => logout.mutate()}
          >
            <SignOut size={15} aria-hidden="true" />
            {logout.isPending ? "Signing out…" : "Sign out"}
          </button>
          {logout.isError && (
            <p className="form-error" role="alert">
              Sign-out failed: {logout.error.message}
            </p>
          )}
        </div>
      </section>

      {canManageKeys ? (
        <section className="settings-section" id="api-keys">
          <header>
            <div>
              <h2>API keys</h2>
              <p>
                Owner and admin roles can create and revoke keys scoped to
                this workspace.
              </p>
            </div>
            <Key size={20} aria-hidden="true" />
          </header>
          <div className="account-profile-body">
            <ApiKeyManagement />
          </div>
        </section>
      ) : (
        <section className="settings-section" id="api-keys">
          <header>
            <div>
              <h2>API keys</h2>
              <p>Owner or admin access is required to manage API keys.</p>
            </div>
            <Key size={20} aria-hidden="true" />
          </header>
        </section>
      )}
    </div>
  );
}
