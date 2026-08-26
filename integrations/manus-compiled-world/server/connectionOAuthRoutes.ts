import type { Express, Request, Response } from "express";
import { encryptConnectorToken } from "./connectionCrypto";
import { getProjectForOwner, upsertConnection } from "./db";
import { exchangeAuthorizationCode, readExternalAccountId, scopeSummary, verifyConnectionState, type CloudProvider } from "./providerOAuth";
import { sdk } from "./_core/sdk";

function callbackRoute(provider: CloudProvider) {
  return provider === "google_drive" ? "/api/connections/google-drive/callback" : "/api/connections/sharepoint/callback";
}

function worldRedirect(provider: CloudProvider, outcome: "active" | "error") {
  return `/world?connector=${provider}&connection=${outcome}`;
}

async function handleCallback(provider: CloudProvider, req: Request, res: Response) {
  const stateValue = typeof req.query.state === "string" ? req.query.state : "";
  const code = typeof req.query.code === "string" ? req.query.code : "";
  const providerError = typeof req.query.error === "string" ? req.query.error : "";
  try {
    const state = verifyConnectionState(stateValue);
    if (state.provider !== provider) throw new Error("Connection provider does not match callback state.");
    const user = await sdk.authenticateRequest(req);
    if (user.id !== state.userId) throw new Error("Connection approval must finish in the same signed-in account.");
    await getProjectForOwner(user.id, state.projectId);
    if (providerError || !code) throw new Error(providerError || "Connection approval was cancelled.");
    const tokens = await exchangeAuthorizationCode(provider, code);
    const externalAccountId = await readExternalAccountId(provider, tokens.access_token);
    await upsertConnection({
      projectId: state.projectId,
      provider,
      status: "active",
      scopeSummary: scopeSummary(provider),
      externalAccountId,
      encryptedAccessToken: encryptConnectorToken(tokens.access_token),
      encryptedRefreshToken: tokens.refresh_token ? encryptConnectorToken(tokens.refresh_token) : null,
      lastSyncedAt: new Date(),
      lastError: null,
    });
    res.redirect(302, worldRedirect(provider, "active"));
  } catch (error) {
    console.warn(`[connections] ${provider} callback failed`, error instanceof Error ? error.message : error);
    try {
      const state = stateValue ? verifyConnectionState(stateValue) : null;
      if (state?.provider === provider) {
        await upsertConnection({ projectId: state.projectId, provider, status: "error", scopeSummary: scopeSummary(provider), lastError: "Approval could not be completed. No source was collected." });
      }
    } catch { /* state is not trusted; do not persist anything */ }
    res.redirect(302, worldRedirect(provider, "error"));
  }
}

export function registerConnectionOAuthRoutes(app: Express) {
  app.get(callbackRoute("google_drive"), (req, res) => void handleCallback("google_drive", req, res));
  app.get(callbackRoute("sharepoint"), (req, res) => void handleCallback("sharepoint", req, res));
}
