export interface SessionProfile {
  tenantId: string;
  userId?: string;
  email?: string;
  displayName: string;
  roles: string[];
  emailVerified?: boolean;
  workspaceName?: string;
  creditBalance?: number;
  externalProcessingEnabled?: boolean;
}

type UnknownRecord = Record<string, unknown>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0
    ? value
    : undefined;
}

function optionalBoolean(value: unknown): boolean | undefined {
  return typeof value === "boolean" ? value : undefined;
}

function optionalNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is string => typeof item === "string" && item.length > 0,
      )
    : [];
}

/**
 * Accepts both the API's compact flat session response and the richer nested
 * profile used by hosted deployments. Authentication still relies exclusively
 * on the HttpOnly session cookie; this object contains display metadata only.
 */
export function normalizeSessionResponse(payload: unknown): SessionProfile {
  if (!isRecord(payload)) {
    throw new Error("세션 응답 형식이 올바르지 않습니다.");
  }

  const nestedUser = isRecord(payload.user) ? payload.user : undefined;
  const tenantId = optionalString(payload.tenant_id);
  const displayName =
    optionalString(nestedUser?.display_name) ??
    optionalString(payload.display_name);

  if (!tenantId || !displayName) {
    throw new Error("세션 응답에 필수 사용자 정보가 없습니다.");
  }

  const nestedRoles = stringList(nestedUser?.roles);
  const flatRoles = stringList(payload.roles);
  const singularRole =
    optionalString(nestedUser?.role) ?? optionalString(payload.role);
  const roles = [
    ...new Set(
      nestedRoles.length > 0
        ? nestedRoles
        : flatRoles.length > 0
          ? flatRoles
          : singularRole
            ? [singularRole]
            : [],
    ),
  ];

  return {
    tenantId,
    userId:
      optionalString(nestedUser?.id) ??
      optionalString(nestedUser?.user_id) ??
      optionalString(payload.user_id),
    email: optionalString(nestedUser?.email) ?? optionalString(payload.email),
    displayName,
    roles,
    emailVerified:
      optionalBoolean(nestedUser?.email_verified) ??
      optionalBoolean(payload.email_verified),
    workspaceName: optionalString(payload.workspace_name),
    creditBalance: optionalNumber(payload.credit_balance),
    externalProcessingEnabled: optionalBoolean(
      payload.external_processing_enabled,
    ),
  };
}
