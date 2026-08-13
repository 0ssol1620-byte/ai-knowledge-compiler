import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccountMenu } from "@/components/account-menu";
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

function renderMenu() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AccountMenu workspaceName="Acme workspace" userRole="Owner" userInitials="AC" />
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

describe("AccountMenu", () => {
  it("renders closed, with no menu in the document", () => {
    renderMenu();
    expect(screen.getByRole("button", { name: /Acme workspace/ })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("opens on trigger click and shows Account, Billing, and Sign out", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Acme workspace/ }));

    const menu = screen.getByRole("menu", { name: "Account menu" });
    expect(menu).toBeVisible();

    const accountLink = screen.getByRole("menuitem", { name: /Account/ });
    expect(accountLink).toHaveAttribute("href", "/account");

    const billingLink = screen.getByRole("menuitem", { name: /Billing/ });
    expect(billingLink).toHaveAttribute("href", "/billing");

    expect(screen.getByRole("menuitem", { name: /Sign out/ })).toBeInTheDocument();
  });

  it("closes when the trigger is clicked again", () => {
    renderMenu();
    const trigger = screen.getByRole("button", { name: /Acme workspace/ });
    fireEvent.click(trigger);
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.click(trigger);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes on outside click", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Acme workspace/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes on Escape", () => {
    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Acme workspace/ }));
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("signs out through the real endpoint, clears session, and redirects to /login", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/auth/logout" && options?.method === "POST") {
        return undefined;
      }
      return {};
    });

    renderMenu();
    fireEvent.click(screen.getByRole("button", { name: /Acme workspace/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Sign out/ }));

    await vi.waitFor(() => {
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/auth/logout",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(useAuthStore.getState().authenticated).toBe(false);
    expect(replace).toHaveBeenCalledWith("/login");

    // Clicking Sign out also closes the menu immediately.
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});
