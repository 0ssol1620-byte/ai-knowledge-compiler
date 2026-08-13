import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiKeyManagement } from "@/components/api-key-management";
import { apiRequest } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({
  apiRequest: vi.fn(),
}));

const mockedApiRequest = vi.mocked(apiRequest);

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ApiKeyManagement />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ApiKeyManagement", () => {
  it("shows the honest empty state when no keys exist", async () => {
    mockedApiRequest.mockResolvedValue([]);
    renderPanel();
    expect(
      await screen.findByText("No API keys have been created for this workspace."),
    ).toBeVisible();
  });

  it("disables create until a name is entered", async () => {
    mockedApiRequest.mockResolvedValue([]);
    renderPanel();
    await screen.findByText("No API keys have been created for this workspace.");
    expect(screen.getByRole("button", { name: /Create key/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "CI exporter" },
    });
    expect(screen.getByRole("button", { name: /Create key/ })).toBeEnabled();
  });

  it("creates a scoped key and reveals the raw value exactly once", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/api-keys" && !options) return [];
      if (path === "/v1/api-keys" && options?.method === "POST") {
        return {
          id: "key-1",
          name: "CI exporter",
          prefix: "akc_ci",
          key: "akc_ci_secretvalue",
          scopes: ["api:read"],
          created_at: "2026-08-13T00:00:00Z",
        };
      }
      return [];
    });

    renderPanel();
    await screen.findByText("No API keys have been created for this workspace.");
    fireEvent.change(screen.getByLabelText("Key name"), {
      target: { value: "CI exporter" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create key/ }));

    expect(await screen.findByText("akc_ci_secretvalue")).toBeVisible();
    const createCall = mockedApiRequest.mock.calls.find(
      ([path, options]) =>
        path === "/v1/api-keys" && options?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      name: "CI exporter",
      scopes: ["api:read"],
    });

    fireEvent.click(screen.getByRole("button", { name: "Stored" }));
    expect(screen.queryByText("akc_ci_secretvalue")).not.toBeInTheDocument();
  });

  it("revokes a key only after explicit confirmation", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/api-keys" && !options) {
        return [
          {
            id: "key-1",
            name: "CI exporter",
            prefix: "akc_ci",
            scopes: ["api:read"],
            created_at: "2026-08-13T00:00:00Z",
            last_used_at: null,
            revoked_at: null,
          },
        ];
      }
      return {};
    });

    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: /Revoke/ }));
    expect(
      screen.getByText(/Revoke this key immediately/),
    ).toBeVisible();
    expect(mockedApiRequest).not.toHaveBeenCalledWith(
      "/v1/api-keys/key-1",
      expect.objectContaining({ method: "DELETE" }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Confirm revoke" }));
    await vi.waitFor(() => {
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/api-keys/key-1",
        expect.objectContaining({
          method: "DELETE",
          idempotencyKey: expect.any(String),
        }),
      );
    });
  });
});
