import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import type * as apiClientModule from "@/lib/api-client";
import { apiRequest } from "@/lib/api-client";

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<typeof apiClientModule>("@/lib/api-client");
  return {
    ...actual,
    apiRequest: vi.fn(),
  };
});

const mockedApiRequest = vi.mocked(apiRequest);

const mockRouterReplace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/home",
  useRouter: () => ({ replace: mockRouterReplace, refresh: vi.fn() }),
}));

const SESSION_RESPONSE = {
  tenant_id: "tenant-1",
  display_name: "Ada",
  email: "ada@example.com",
  email_verified: true,
  roles: ["owner"],
  workspace_name: "Sample workspace",
  external_processing_enabled: false,
  credit_balance: 100,
};

function renderShell() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AppShell>
        <div>content</div>
      </AppShell>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AppShell", () => {
  it("renders WORLD as workspace primary navigation, separate from the account menu", async () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);

    renderShell();

    const primaryNav = await screen.findByRole("navigation", {
      name: "Primary navigation",
    });
    const worldLink = within(primaryNav).getByRole("link", { name: "World" });
    expect(worldLink).toHaveAttribute("href", "/app/world");

    // The account affordance is a separate control, not part of the
    // workspace nav list.
    const accountTrigger = screen.getByRole("button", {
      name: /Sample workspace/i,
    });
    expect(primaryNav).not.toContainElement(accountTrigger);
  });

  it("labels the billing entry Billing, pointing at /billing, not the old Usage entry", async () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);

    renderShell();

    const adminNav = await screen.findByRole("navigation", {
      name: "Workspace administration",
    });
    const billingLink = within(adminNav).getByRole("link", {
      name: "Billing",
    });
    expect(billingLink).toHaveAttribute("href", "/billing");
    expect(
      within(adminNav).queryByRole("link", { name: "Usage" }),
    ).not.toBeInTheDocument();
  });

  it("opens the AccountMenu dropdown with Account, Billing and Sign out", async () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);

    renderShell();

    const accountButton = await screen.findByRole("button", {
      name: /Sample workspace/i,
    });
    accountButton.click();

    expect(
      await screen.findByRole("menuitem", { name: /account/i }),
    ).toHaveAttribute("href", "/account");
    expect(screen.getByRole("menuitem", { name: /billing/i })).toHaveAttribute(
      "href",
      "/billing",
    );
    expect(
      screen.getByRole("menuitem", { name: /sign out/i }),
    ).toBeInTheDocument();
  });
});
