import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DispatchDlqPanel } from "@/components/dispatch-dlq-panel";
import { apiRequest } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiRequest: vi.fn() }));
const mockedApiRequest = vi.mocked(apiRequest);

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <DispatchDlqPanel />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DispatchDlqPanel", () => {
  it("requires reviewed state evidence before creating a fallback", async () => {
    const stateSha = "a".repeat(64);
    mockedApiRequest.mockImplementation(async (path) => {
      if (String(path).startsWith("/v1/admin/dispatch-dlq?")) {
        return [
          {
            original_event_id: "event-1",
            original_job_id: "job-1",
            attempts: 5,
            last_error: "DISPATCH_ATTEMPTS_EXHAUSTED",
            dead_lettered_at: "2026-07-30T00:00:00Z",
            disposition: null,
            state_sha256: stateSha,
          },
        ];
      }
      return {};
    });
    renderPanel();

    fireEvent.click(
      await screen.findByRole("button", { name: "Preview recovery" }),
    );
    fireEvent.click(screen.getByLabelText("fallback"));
    fireEvent.change(screen.getByLabelText("Operator note"), {
      target: { value: "Provider outage requires native-only recovery." },
    });
    fireEvent.click(
      screen.getByLabelText(/I reviewed the event, job, state hash/),
    );
    fireEvent.click(screen.getByRole("button", { name: "Confirm fallback" }));

    await waitFor(() =>
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/admin/dispatch-dlq/event-1/fallback",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    const call = mockedApiRequest.mock.calls.find(([path]) =>
      String(path).endsWith("/fallback"),
    );
    expect(JSON.parse(String(call?.[1]?.body))).toEqual(
      expect.objectContaining({
        expected_state_sha256: stateSha,
        fallback_route_profile: "parse_private_v1",
        reason_code: "manual_recovery",
      }),
    );
  });
});
