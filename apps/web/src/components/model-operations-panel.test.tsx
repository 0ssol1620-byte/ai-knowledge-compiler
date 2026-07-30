import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelOperationsPanel } from "@/components/model-operations-panel";
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
      <ModelOperationsPanel />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ModelOperationsPanel", () => {
  it("submits an evidence-bound promotion with optimistic generation", async () => {
    mockedApiRequest.mockImplementation(async (path, options) => {
      if (path === "/v1/admin/models" && !options) {
        return [
          {
            id: "model-candidate",
            endpoint: "knowledge",
            model_id: "compiler-9b",
            revision: "revision-2026-07-30",
            adapter_version: "1.4.0",
            enabled: true,
            canary_percent: 10,
            lifecycle_state: "candidate",
            generation: 7,
            promoted_from_id: null,
            benchmark_sha256: null,
            recipe_sha256: null,
          },
        ];
      }
      return {};
    });

    renderPanel();
    fireEvent.click(await screen.findByRole("button", { name: "Promote" }));

    const digest = `sha256:${"a".repeat(64)}`;
    fireEvent.change(screen.getByLabelText("Benchmark SHA-256"), {
      target: { value: digest },
    });
    fireEvent.change(screen.getByLabelText("Recipe SHA-256"), {
      target: { value: digest },
    });
    fireEvent.change(screen.getByLabelText("Approval reference"), {
      target: { value: "CAB-2026-0730" },
    });
    fireEvent.change(screen.getByLabelText("Operator reason"), {
      target: { value: "Promote the verified candidate." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Promote model" }));

    await waitFor(() =>
      expect(mockedApiRequest).toHaveBeenCalledWith(
        "/v1/admin/models/model-candidate/promote",
        expect.objectContaining({
          method: "POST",
          idempotencyKey: expect.any(String),
        }),
      ),
    );
    const promotionCall = mockedApiRequest.mock.calls.find(([path]) =>
      String(path).endsWith("/promote"),
    );
    expect(JSON.parse(String(promotionCall?.[1]?.body))).toEqual({
      expected_generation: 7,
      approval_ref: "CAB-2026-0730",
      reason: "Promote the verified candidate.",
      benchmark_sha256: digest,
      recipe_sha256: digest,
    });
  });
});
