"use client";

import { UserPlus, Warning, X } from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import type { FormEvent } from "react";

import { apiRequest, ApiError } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

type TeamRole =
  "owner" | "admin" | "editor" | "reviewer" | "viewer" | "billing";

interface TeamMember {
  user_id: string;
  email: string;
  display_name: string;
  role: TeamRole;
  email_verified: boolean;
  joined_at: string;
}

interface Invitation {
  id: string;
  email?: string | null;
  role: TeamRole;
  status: "pending" | "accepted" | "cancelled" | "expired";
  expires_at: string;
  created_at: string;
}

const allRoles: TeamRole[] = [
  "owner",
  "admin",
  "editor",
  "reviewer",
  "viewer",
  "billing",
];

export function TeamManagement() {
  const queryClient = useQueryClient();
  const roles = useAuthStore((state) =>
    state.roles.map((role) => role.toLowerCase()),
  );
  const currentEmail = useAuthStore((state) => state.email);
  const actorIsOwner = roles.includes("owner");
  const assignableRoles = actorIsOwner
    ? allRoles
    : allRoles.filter((role) => !["owner", "admin"].includes(role));
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState<TeamRole>("viewer");
  const [removeCandidate, setRemoveCandidate] = useState<TeamMember>();
  const [message, setMessage] = useState<string>();

  const members = useQuery({
    queryKey: ["team", "members"],
    queryFn: () =>
      apiRequest<{ items: TeamMember[] }>("/v1/team/members").then(
        (response) => response.items,
      ),
  });
  const invitations = useQuery({
    queryKey: ["team", "invitations"],
    queryFn: () =>
      apiRequest<{ items: Invitation[] }>("/v1/team/invitations").then(
        (response) => response.items,
      ),
  });

  function refreshTeam() {
    void queryClient.invalidateQueries({ queryKey: ["team"] });
  }

  const invite = useMutation({
    mutationFn: (payload: { email: string; role: TeamRole }) =>
      apiRequest<Invitation>("/v1/team/invitations", {
        method: "POST",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify(payload),
      }),
    onSuccess: () => {
      setInviteEmail("");
      setMessage("The invitation email has been queued.");
      refreshTeam();
    },
  });
  const cancelInvitation = useMutation({
    mutationFn: (invitationId: string) =>
      apiRequest<void>(`/v1/team/invitations/${invitationId}`, {
        method: "DELETE",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => {
      setMessage("The pending invitation has been canceled.");
      refreshTeam();
    },
  });
  const updateRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: TeamRole }) =>
      apiRequest<TeamMember>(`/v1/team/members/${userId}`, {
        method: "PATCH",
        idempotencyKey: crypto.randomUUID(),
        body: JSON.stringify({ role }),
      }),
    onSuccess: () => {
      setMessage("The member role has been updated.");
      refreshTeam();
    },
  });
  const removeMember = useMutation({
    mutationFn: (userId: string) =>
      apiRequest<void>(`/v1/team/members/${userId}`, {
        method: "DELETE",
        idempotencyKey: crypto.randomUUID(),
      }),
    onSuccess: () => {
      setRemoveCandidate(undefined);
      setMessage(
        "The member and their workspace API key access have been removed.",
      );
      refreshTeam();
    },
  });

  const mutationError =
    invite.error ??
    cancelInvitation.error ??
    updateRole.error ??
    removeMember.error;

  function submitInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(undefined);
    invite.reset();
    const email = inviteEmail.trim();
    if (!email) return;
    invite.mutate({ email, role: inviteRole });
  }

  if (members.isPending || invitations.isPending) {
    return (
      <div className="team-management honest-state compact" aria-busy="true">
        <span className="spinner" aria-hidden="true" />
        <p>Loading team permissions and invitations.</p>
      </div>
    );
  }
  if (members.isError || invitations.isError) {
    const error = members.error ?? invitations.error;
    return (
      <div className="team-management honest-state compact">
        <Warning size={20} aria-hidden="true" />
        <p>{teamErrorMessage(error)}</p>
        <button
          type="button"
          className="secondary-button compact"
          onClick={() => {
            void members.refetch();
            void invitations.refetch();
          }}
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="team-management">
      <form className="team-invite-form" onSubmit={submitInvitation}>
        <label>
          <span>Email address</span>
          <input
            type="email"
            autoComplete="email"
            required
            maxLength={320}
            value={inviteEmail}
            disabled={invite.isPending}
            onChange={(event) => setInviteEmail(event.target.value)}
          />
        </label>
        <label>
          <span>Role</span>
          <select
            value={inviteRole}
            disabled={invite.isPending}
            onChange={(event) => setInviteRole(event.target.value as TeamRole)}
          >
            {assignableRoles.map((role) => (
              <option key={role} value={role}>
                {role}
              </option>
            ))}
          </select>
        </label>
        <button
          className="secondary-button"
          type="submit"
          disabled={invite.isPending || !inviteEmail.trim()}
        >
          <UserPlus size={15} aria-hidden="true" />
          {invite.isPending ? "Sending invitation…" : "Invite member"}
        </button>
      </form>

      <div className="team-subsection">
        <h3>Members</h3>
        <div className="member-list">
          {members.data.map((member) => {
            const isCurrentUser =
              currentEmail?.toLowerCase() === member.email.toLowerCase();
            const actorCanManage =
              actorIsOwner || !["owner", "admin"].includes(member.role);
            return (
              <div className="member-row" key={member.user_id}>
                <span className="avatar" aria-hidden="true">
                  {(member.display_name || member.email)
                    .slice(0, 2)
                    .toUpperCase()}
                </span>
                <span>
                  <strong>
                    {member.display_name}
                    {isCurrentUser ? " (you)" : ""}
                  </strong>
                  <small>
                    {member.email} ·{" "}
                    {member.email_verified ? "Email verified" : "Not verified"}
                  </small>
                </span>
                <select
                  aria-label={`${member.display_name} role`}
                  value={member.role}
                  disabled={
                    isCurrentUser ||
                    !actorCanManage ||
                    updateRole.isPending ||
                    removeMember.isPending
                  }
                  onChange={(event) =>
                    updateRole.mutate({
                      userId: member.user_id,
                      role: event.target.value as TeamRole,
                    })
                  }
                >
                  {allRoles.map((role) => (
                    <option
                      key={role}
                      value={role}
                      disabled={
                        !assignableRoles.includes(role) && role !== member.role
                      }
                    >
                      {role}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="icon-button compact"
                  aria-label={`Remove ${member.display_name}`}
                  disabled={
                    isCurrentUser || !actorCanManage || removeMember.isPending
                  }
                  onClick={() => setRemoveCandidate(member)}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </div>
            );
          })}
        </div>
      </div>

      {invitations.data.some((item) => item.status === "pending") && (
        <div className="team-subsection">
          <h3>Pending invitations</h3>
          <div className="member-list">
            {invitations.data
              .filter((item) => item.status === "pending")
              .map((item) => (
                <div className="member-row" key={item.id}>
                  <span className="avatar" aria-hidden="true">
                    @
                  </span>
                  <span>
                    <strong>
                      {item.email ?? "Recipient details unavailable"}
                    </strong>
                    <small>
                      {item.role} · Expires{" "}
                      {new Date(item.expires_at).toLocaleString("en-US")}
                    </small>
                  </span>
                  <span className="status-badge neutral">pending</span>
                  <button
                    type="button"
                    className="icon-button compact"
                    aria-label={`Cancel invitation for ${item.email ?? "recipient"}`}
                    disabled={cancelInvitation.isPending}
                    onClick={() => cancelInvitation.mutate(item.id)}
                  >
                    <X size={14} aria-hidden="true" />
                  </button>
                </div>
              ))}
          </div>
        </div>
      )}

      {removeCandidate && (
        <div className="team-confirm" role="alert">
          <p>
            Remove workspace access and API keys for{" "}
            <strong>{removeCandidate.display_name}</strong>?
          </p>
          <div>
            <button
              type="button"
              className="secondary-button compact"
              onClick={() => setRemoveCandidate(undefined)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="danger-button compact"
              disabled={removeMember.isPending}
              onClick={() => removeMember.mutate(removeCandidate.user_id)}
            >
              {removeMember.isPending ? "Removing…" : "Remove member"}
            </button>
          </div>
        </div>
      )}

      <div className="team-feedback" role="status" aria-live="polite">
        {mutationError ? teamErrorMessage(mutationError) : message}
      </div>
    </div>
  );
}

function teamErrorMessage(error: Error | null | undefined): string {
  if (!error) return "Team information could not be loaded.";
  if (error instanceof ApiError) {
    const known: Record<string, string> = {
      LAST_OWNER_REQUIRED: "The last Owner cannot be reassigned or removed.",
      ROLE_ESCALATION_DENIED:
        "Your current role cannot grant or remove that role.",
      SELF_ROLE_CHANGE_DENIED: "You cannot change your own role.",
      SELF_REMOVAL_DENIED: "You cannot remove your own membership.",
      INVITATION_ALREADY_ACCEPTED: "This invitation has already been accepted.",
    };
    return (
      known[error.code] ??
      `The team action could not be completed: ${error.message}`
    );
  }
  return `The team action could not be completed: ${error.message}`;
}
