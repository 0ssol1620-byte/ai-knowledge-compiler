import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WebhookManagement } from "@/components/webhook-management";
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
      <WebhookManagement />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WebhookManagement", () => {
  it("creates an HTTPS endpoint and reveals the signing secret once", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/webhooks" && !options) return [];
      if (path === "/v1/webhooks" && options?.method === "POST") {
        return {
          id: "hook-1",
          url: "https://hooks.example.com/akc",
          event_types: ["job.completed.v1"],
          active: true,
          created_at: "2026-07-30T00:00:00Z",
          signing_secret: "whsec_once_only",
        };
      }
      return [];
    });

    renderPanel();
    await screen.findByText("등록된 Webhook endpoint가 없습니다.");
    fireEvent.change(screen.getByLabelText("HTTPS endpoint"), {
      target: { value: "https://hooks.example.com/akc" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: "job.failed.v1" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "export.completed.v1" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Add endpoint" }));

    expect(await screen.findByText("whsec_once_only")).toBeVisible();
    const createCall = mockedApiRequest.mock.calls.find(
      ([path, options]) =>
        path === "/v1/webhooks" && options?.method === "POST",
    );
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      url: "https://hooks.example.com/akc",
      event_types: ["job.completed.v1"],
    });
  });

  it("loads delivery history and explicitly replays a dead letter", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/webhooks" && !options) {
        return [
          {
            id: "hook-1",
            url: "https://hooks.example.com/akc",
            event_types: ["job.completed.v1"],
            active: true,
            created_at: "2026-07-30T00:00:00Z",
          },
        ];
      }
      if (path === "/v1/webhooks/hook-1/deliveries" && !options) {
        return [
          {
            id: "delivery-1",
            event_type: "job.completed.v1",
            status: "dead_letter",
            attempts: 6,
            last_status_code: 503,
            last_error: "upstream unavailable",
            next_attempt_at: null,
            delivered_at: null,
          },
        ];
      }
      return {};
    });

    renderPanel();
    fireEvent.click(
      await screen.findByRole("button", { name: /Delivery log/ }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Replay" }));

    await waitFor(() =>
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/webhooks/hook-1/deliveries/delivery-1/replay",
        expect.objectContaining({
          method: "POST",
          idempotencyKey: expect.any(String),
        }),
      ),
    );
  });
});
