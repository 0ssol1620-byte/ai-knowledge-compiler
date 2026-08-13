import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountPage } from "@/components/account-page";
import { apiRequest } from "@/lib/api-client";
import { useAuthStore } from "@/lib/auth-store";

vi.mock("@/lib/api-client", () => ({
  apiRequest: vi.fn(),
}));

const replace = vi.fn();
const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh }),
}));

const mockedApiRequest = vi.mocked(apiRequest);

function renderAccount() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AccountPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  useAuthStore.setState({
    authenticated: true,
    tenantId: "tenant-1",
    userName: "Owner",
    email: "owner@example.com",
    emailVerified: true,
    roles: ["owner"],
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  useAuthStore.setState({
    authenticated: false,
    tenantId: undefined,
    userName: undefined,
    email: undefined,
    emailVerified: undefined,
    roles: [],
  });
});

describe("AccountPage", () => {
  it("renders the server-confirmed profile and never claims profile edits are saved", async () => {
    mockedApiRequest.mockImplementation(async (path) => {
      if (path === "/v1/auth/session") {
        return {
          tenant_id: "tenant-1",
          display_name: "Owner",
          email: "owner@example.com",
          email_verified: true,
          roles: ["owner"],
          workspace_name: "Acme workspace",
          credit_balance: 4200,
        };
      }
      if (path === "/v1/api-keys") return [];
      return {};
    });

    renderAccount();

    expect(await screen.findByText("Acme workspace")).toBeVisible();
    expect(screen.getByText("4,200")).toBeVisible();
    expect(
      screen.getByText(
        /Changing your display name or password is not backend-supported yet/,
      ),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /save/i }),
    ).not.toBeInTheDocument();
  });

  it("signs out through the real endpoint and clears local session state", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/auth/session") {
        return {
          tenant_id: "tenant-1",
          display_name: "Owner",
          roles: ["owner"],
        };
      }
      if (path === "/v1/auth/logout" && options?.method === "POST") {
        return undefined;
      }
      if (path === "/v1/api-keys") return [];
      return {};
    });

    renderAccount();
    fireEvent.click(await screen.findByRole("button", { name: /Sign out/ }));

    await vi.waitFor(() => {
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/auth/logout",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(useAuthStore.getState().authenticated).toBe(false);
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("hides API key management from members without owner/admin roles", async () => {
    useAuthStore.setState({ roles: ["member"] });
    mockedApiRequest.mockImplementation(async (path) => {
      if (path === "/v1/auth/session") {
        return {
          tenant_id: "tenant-1",
          display_name: "Member",
          roles: ["member"],
        };
      }
      return {};
    });

    renderAccount();
    await screen.findByText("Owner or admin access is required to manage API keys.");
    expect(
      screen.queryByRole("button", { name: /Create key/ }),
    ).not.toBeInTheDocument();
  });
});
