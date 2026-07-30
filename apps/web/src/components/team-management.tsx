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
      setMessage("초대 메일 전송이 예약되었습니다.");
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
      setMessage("대기 중인 초대를 취소했습니다.");
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
      setMessage("멤버 역할을 변경했습니다.");
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
      setMessage("멤버와 해당 워크스페이스의 API 키 접근을 제거했습니다.");
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
        <p>팀 권한과 초대를 불러오고 있습니다.</p>
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
          다시 시도
        </button>
      </div>
    );
  }

  return (
    <div className="team-management">
      <form className="team-invite-form" onSubmit={submitInvitation}>
        <label>
          <span>초대할 이메일</span>
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
          <span>역할</span>
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
          {invite.isPending ? "초대 중…" : "멤버 초대"}
        </button>
      </form>

      <div className="team-subsection">
        <h3>멤버</h3>
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
                    {isCurrentUser ? " (나)" : ""}
                  </strong>
                  <small>
                    {member.email} ·{" "}
                    {member.email_verified ? "이메일 확인됨" : "확인되지 않음"}
                  </small>
                </span>
                <select
                  aria-label={`${member.display_name} 역할`}
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
                  aria-label={`${member.display_name} 제거`}
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
          <h3>대기 중인 초대</h3>
          <div className="member-list">
            {invitations.data
              .filter((item) => item.status === "pending")
              .map((item) => (
                <div className="member-row" key={item.id}>
                  <span className="avatar" aria-hidden="true">
                    @
                  </span>
                  <span>
                    <strong>{item.email ?? "수신자 정보 복호화 불가"}</strong>
                    <small>
                      {item.role} ·{" "}
                      {new Date(item.expires_at).toLocaleString("ko-KR")} 만료
                    </small>
                  </span>
                  <span className="status-badge neutral">pending</span>
                  <button
                    type="button"
                    className="icon-button compact"
                    aria-label={`${item.email ?? "초대"} 취소`}
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
            <strong>{removeCandidate.display_name}</strong>의 워크스페이스
            접근과 API 키를 제거할까요?
          </p>
          <div>
            <button
              type="button"
              className="secondary-button compact"
              onClick={() => setRemoveCandidate(undefined)}
            >
              취소
            </button>
            <button
              type="button"
              className="danger-button compact"
              disabled={removeMember.isPending}
              onClick={() => removeMember.mutate(removeCandidate.user_id)}
            >
              {removeMember.isPending ? "제거 중…" : "제거 확인"}
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
  if (!error) return "팀 정보를 불러오지 못했습니다.";
  if (error instanceof ApiError) {
    const known: Record<string, string> = {
      LAST_OWNER_REQUIRED: "마지막 Owner는 역할을 바꾸거나 제거할 수 없습니다.",
      ROLE_ESCALATION_DENIED:
        "현재 역할로는 해당 역할을 부여하거나 제거할 수 없습니다.",
      SELF_ROLE_CHANGE_DENIED: "자신의 역할은 직접 변경할 수 없습니다.",
      SELF_REMOVAL_DENIED: "자신의 멤버십은 직접 제거할 수 없습니다.",
      INVITATION_ALREADY_ACCEPTED: "이미 수락된 초대입니다.",
    };
    return (
      known[error.code] ?? `팀 작업을 완료하지 못했습니다: ${error.message}`
    );
  }
  return `팀 작업을 완료하지 못했습니다: ${error.message}`;
}
