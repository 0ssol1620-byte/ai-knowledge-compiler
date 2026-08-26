import { createHmac, randomBytes, timingSafeEqual } from "crypto";
import { ENV } from "./_core/env";

export type CloudProvider = "google_drive" | "sharepoint";

type ConnectionState = {
  provider: CloudProvider;
  projectId: number;
  userId: number;
  nonce: string;
  expiresAt: number;
};

type ProviderTokenResponse = {
  access_token?: string;
  refresh_token?: string;
  error?: string;
  error_description?: string;
};

const GOOGLE_SCOPE = "openid email profile https://www.googleapis.com/auth/drive.readonly";
const MICROSOFT_SCOPE = "openid profile offline_access User.Read Files.Read.All Sites.Read.All";

function signature(payload: string) {
  if (!ENV.cookieSecret) throw new Error("OAuth state signing is unavailable.");
  return createHmac("sha256", ENV.cookieSecret).update(payload).digest("base64url");
}

function configFor(provider: CloudProvider) {
  if (provider === "google_drive") {
    return { clientId: ENV.googleOAuthClientId, clientSecret: ENV.googleOAuthClientSecret, scope: GOOGLE_SCOPE };
  }
  return { clientId: ENV.microsoftOAuthClientId, clientSecret: ENV.microsoftOAuthClientSecret, scope: MICROSOFT_SCOPE };
}

export function isProviderConfigured(provider: CloudProvider) {
  const config = configFor(provider);
  return Boolean(config.clientId && config.clientSecret);
}

export function callbackUrl(provider: CloudProvider) {
  const path = provider === "google_drive" ? "google-drive" : "sharepoint";
  return `${ENV.publicAppUrl.replace(/\/$/, "")}/api/connections/${path}/callback`;
}

export function createConnectionState(input: Omit<ConnectionState, "nonce" | "expiresAt">) {
  const body = Buffer.from(JSON.stringify({ ...input, nonce: randomBytes(18).toString("base64url"), expiresAt: Date.now() + 10 * 60 * 1000 })).toString("base64url");
  return `${body}.${signature(body)}`;
}

export function verifyConnectionState(value: string): ConnectionState {
  const [body, receivedSignature] = value.split(".");
  if (!body || !receivedSignature) throw new Error("Connection state is malformed.");
  const expectedSignature = signature(body);
  const received = Buffer.from(receivedSignature);
  const expected = Buffer.from(expectedSignature);
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) throw new Error("Connection state is invalid.");
  const parsed = JSON.parse(Buffer.from(body, "base64url").toString("utf8")) as ConnectionState;
  if (!parsed.provider || !Number.isInteger(parsed.projectId) || !Number.isInteger(parsed.userId) || parsed.expiresAt < Date.now()) throw new Error("Connection state has expired.");
  return parsed;
}

export function authorizationUrl(provider: CloudProvider, state: string) {
  const config = configFor(provider);
  if (!config.clientId || !config.clientSecret) throw new Error("Service registration is required before customers can approve this connection.");
  const url = provider === "google_drive"
    ? new URL("https://accounts.google.com/o/oauth2/v2/auth")
    : new URL("https://login.microsoftonline.com/common/oauth2/v2.0/authorize");
  url.search = new URLSearchParams({
    client_id: config.clientId,
    redirect_uri: callbackUrl(provider),
    response_type: "code",
    scope: config.scope,
    state,
    ...(provider === "google_drive" ? { access_type: "offline", prompt: "consent", include_granted_scopes: "true" } : {}),
  }).toString();
  return url.toString();
}

export async function exchangeAuthorizationCode(provider: CloudProvider, code: string) {
  const config = configFor(provider);
  if (!config.clientId || !config.clientSecret) throw new Error("Service registration is required before customers can approve this connection.");
  const tokenUrl = provider === "google_drive"
    ? "https://oauth2.googleapis.com/token"
    : "https://login.microsoftonline.com/common/oauth2/v2.0/token";
  const body = new URLSearchParams({
    client_id: config.clientId,
    client_secret: config.clientSecret,
    redirect_uri: callbackUrl(provider),
    grant_type: "authorization_code",
    code,
    ...(provider === "sharepoint" ? { scope: config.scope } : {}),
  });
  const response = await fetch(tokenUrl, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body });
  const payload = await response.json() as ProviderTokenResponse;
  if (!response.ok || !payload.access_token) throw new Error(payload.error_description || payload.error || "Provider token exchange failed.");
  return payload as Required<Pick<ProviderTokenResponse, "access_token">> & ProviderTokenResponse;
}

export async function readExternalAccountId(provider: CloudProvider, accessToken: string) {
  const url = provider === "google_drive" ? "https://openidconnect.googleapis.com/v1/userinfo" : "https://graph.microsoft.com/v1.0/me?$select=id";
  const response = await fetch(url, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (!response.ok) return null;
  const payload = await response.json() as { sub?: string; id?: string };
  return payload.sub ?? payload.id ?? null;
}

export function scopeSummary(provider: CloudProvider) {
  return provider === "google_drive" ? "Google Drive read-only" : "Microsoft Graph Files/Sites read-only";
}
