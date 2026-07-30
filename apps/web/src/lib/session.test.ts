import { describe, expect, it } from "vitest";

import { normalizeSessionResponse } from "@/lib/session";

describe("normalizeSessionResponse", () => {
  it("normalizes the current flat API response", () => {
    expect(
      normalizeSessionResponse({
        user_id: "user-1",
        tenant_id: "tenant-1",
        email: "owner@example.com",
        display_name: "Owner",
        roles: ["owner"],
      }),
    ).toEqual({
      tenantId: "tenant-1",
      userId: "user-1",
      email: "owner@example.com",
      displayName: "Owner",
      roles: ["owner"],
      emailVerified: undefined,
      workspaceName: undefined,
      creditBalance: undefined,
      externalProcessingEnabled: undefined,
    });
  });

  it("normalizes a richer nested response without inventing missing values", () => {
    expect(
      normalizeSessionResponse({
        tenant_id: "tenant-2",
        workspace_name: "Research",
        credit_balance: 125.5,
        external_processing_enabled: false,
        user: {
          id: "user-2",
          email: "editor@example.com",
          display_name: "Editor",
          role: "editor",
        },
      }),
    ).toEqual({
      tenantId: "tenant-2",
      userId: "user-2",
      email: "editor@example.com",
      displayName: "Editor",
      roles: ["editor"],
      emailVerified: undefined,
      workspaceName: "Research",
      creditBalance: 125.5,
      externalProcessingEnabled: false,
    });
  });

  it("preserves the server's email verification gate", () => {
    expect(
      normalizeSessionResponse({
        user_id: "user-1",
        tenant_id: "tenant-1",
        email: "owner@example.com",
        display_name: "Owner",
        roles: ["owner"],
        email_verified: false,
      }).emailVerified,
    ).toBe(false);
  });

  it("rejects a response without identity fields", () => {
    expect(() => normalizeSessionResponse({ tenant_id: "tenant-1" })).toThrow(
      "required user information",
    );
  });
});
