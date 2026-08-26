import { describe, expect, it } from "vitest";
import { decryptConnectorToken, encryptConnectorToken } from "./connectionCrypto";
import { authorizationUrl, createConnectionState, verifyConnectionState } from "./providerOAuth";

describe("customer approval OAuth contract", () => {
  it("signs a short-lived project-scoped state and rejects tampering", () => {
    const state = createConnectionState({ provider: "google_drive", projectId: 9, userId: 4 });
    expect(verifyConnectionState(state)).toMatchObject({ provider: "google_drive", projectId: 9, userId: 4 });
    expect(() => verifyConnectionState(`${state}x`)).toThrow("Connection state");
  });

  it("encrypts provider tokens before a database helper can persist them", () => {
    const token = "provider-access-token-that-never-belongs-in-sql-plaintext";
    const encrypted = encryptConnectorToken(token);
    expect(encrypted).not.toContain(token);
    expect(decryptConnectorToken(encrypted)).toBe(token);
  });

  it("requests only the declared Google Drive read-only scope", () => {
    const url = new URL(authorizationUrl("google_drive", createConnectionState({ provider: "google_drive", projectId: 9, userId: 4 })));
    expect(url.origin).toBe("https://accounts.google.com");
    expect(url.searchParams.get("scope")).toContain("drive.readonly");
    expect(url.searchParams.get("scope")).not.toContain("drive.file");
    expect(url.searchParams.get("redirect_uri")).toBe("https://tavoknowledg-rm8cmlar.manus.space/api/connections/google-drive/callback");
  });
});
