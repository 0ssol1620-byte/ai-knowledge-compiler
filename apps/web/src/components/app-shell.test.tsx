import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import { AuthenticatedShell } from "@/components/authenticated-shell";
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

let currentPathname = "/app/home";

vi.mock("next/navigation", () => ({
  usePathname: () => currentPathname,
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

/*
 * Two components, two levels of test, because `AppShell` was split for the §22
 * bundle ratchet: it is now only the route decision, and it reaches the real
 * chrome through `next/dynamic` (see app-shell.tsx).
 *
 * That dynamic boundary does not resolve under jsdom -- `next/dynamic` is a
 * CommonJS re-export (`module.exports = require('./dist/shared/lib/dynamic')`)
 * that Vite resolves straight to the internal module, so a `vi.mock` on the
 * "next/dynamic" specifier never reaches the component, and the configured
 * `loading: () => null` renders forever. Every assertion about sidebar markup
 * would therefore run against an empty document.
 *
 * Before the G0 merge this file hid that: the three cases only passed as a
 * group, each leaning on a previous case's warmed module state, and every one
 * of them failed when run alone with `-t`. Asserting chrome markup through the
 * lazy boundary is what made them order-dependent.
 *
 * So the chrome contract is asserted against `AuthenticatedShell` directly --
 * the component that actually renders it -- and `AppShell` keeps the assertion
 * that is genuinely its own: which routes get chrome and which do not.
 */

function renderChrome() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AuthenticatedShell>
        <div>content</div>
      </AuthenticatedShell>
    </QueryClientProvider>,
  );
}

function renderAppShell() {
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
  currentPathname = "/app/home";
});

describe("AuthenticatedShell", () => {
  it("renders WORLD as workspace primary navigation, separate from the account menu", async () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);

    renderChrome();

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

    renderChrome();

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

    renderChrome();

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

describe("AppShell route decision", () => {
  it("renders marketing routes bare, without loading the authenticated chrome", () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);
    currentPathname = "/product";

    renderAppShell();

    expect(screen.getByText("content")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    // A bare route must not even reach for the session.
    expect(mockedApiRequest).not.toHaveBeenCalled();
  });

  it("renders auth routes bare", () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);
    currentPathname = "/login";

    renderAppShell();

    expect(screen.getByText("content")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("routes workspace paths to the authenticated chrome instead of rendering them bare", () => {
    mockedApiRequest.mockResolvedValue(SESSION_RESPONSE);
    currentPathname = "/app/home";

    const { container } = renderAppShell();

    // The chrome arrives through a dynamic import that jsdom does not resolve,
    // so this asserts the decision, not the markup: a workspace route does NOT
    // take the bare-route path that returns `children` directly.
    expect(container.textContent).not.toContain("content");
  });
});
