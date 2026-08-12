import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "@/lib/api-client";
import {
  CollectionIntegrityContractError,
  createCollectionIntegrityDecision,
  getCollectionIntegrityDecisions,
  getCollectionIntegrityFindings,
} from "@/lib/collection-integrity-client";

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<Record<string, unknown>>("@/lib/api-client");
  return { ...actual, apiRequest: vi.fn() };
});

const collectionId = "00000000-0000-4000-8000-000000000001";
const targetId = "00000000-0000-4000-8000-000000000002";
const decisionId = "00000000-0000-4000-8000-000000000003";
const actorId = "00000000-0000-4000-8000-000000000004";

function decisionResponse() {
  return {
    id: decisionId,
    collection_id: collectionId,
    target_type: "quarantine_item",
    target_id: targetId,
    action: "exclude",
    reason_code: "EXCLUDED_FROM_OUTPUT",
    evidence_reference: null,
    previous_status: "open",
    resulting_status: "rejected",
    override_applied: false,
    actor_id: actorId,
    created_at: "2026-08-01T00:00:00Z",
  };
}

const createInput = {
  target_type: "quarantine_item" as const,
  target_id: targetId,
  action: "exclude" as const,
  reason_code: "EXCLUDED_FROM_OUTPUT" as const,
  acknowledge_override: false,
};

describe("collection integrity customer-decision contract", () => {
  beforeEach(() => {
    vi.mocked(apiRequest).mockReset();
    window.localStorage.clear();
  });

  it("accepts only a PII-free finding envelope correlated to the collection", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      items: [
        {
          target_type: "quarantine_item",
          target_id: targetId,
          status: "open",
          category: "source_integrity",
          severity: "high",
          reason_code: "SOURCE_CORRUPTION",
          allowed_actions: ["keep_quarantined", "exclude", "correct_source"],
          created_at: "2026-08-01T00:00:00Z",
        },
      ],
      next_cursor: null,
    });

    const response = await getCollectionIntegrityFindings(collectionId);

    expect(response.items[0]).toEqual(
      expect.objectContaining({ target_id: targetId, severity: "high" }),
    );
    expect(apiRequest).toHaveBeenCalledWith(
      `/v1/collections/${collectionId}/integrity/findings?limit=200`,
      { signal: undefined },
    );
  });

  it.each([
    {
      collection_id: "00000000-0000-4000-8000-000000000099",
      items: [],
      next_cursor: null,
    },
    {
      collection_id: collectionId,
      items: [
        {
          target_type: "quarantine_item",
          target_id: targetId,
          status: "open",
          category: "source_integrity",
          severity: "high",
          reason_code: "SOURCE_CORRUPTION",
          allowed_actions: ["exclude"],
          created_at: "2026-08-01T00:00:00Z",
          relative_path: "must-not-cross-the-contract.pdf",
        },
      ],
      next_cursor: null,
    },
  ])("fails closed for cross-collection or extra finding metadata", async (payload) => {
    vi.mocked(apiRequest).mockResolvedValue(payload);
    await expect(getCollectionIntegrityFindings(collectionId)).rejects.toBeInstanceOf(
      CollectionIntegrityContractError,
    );
  });

  it("validates every immutable decision-history item", async () => {
    vi.mocked(apiRequest).mockResolvedValue({
      collection_id: collectionId,
      items: [decisionResponse()],
      next_cursor: null,
    });

    await expect(getCollectionIntegrityDecisions(collectionId)).resolves.toEqual(
      expect.objectContaining({
        collection_id: collectionId,
        items: [expect.objectContaining({ id: decisionId })],
      }),
    );
  });

  it("reuses the persisted idempotency key after an ambiguous mutation", async () => {
    vi.mocked(apiRequest)
      .mockRejectedValueOnce(new TypeError("connection reset"))
      .mockResolvedValueOnce(decisionResponse());

    await expect(
      createCollectionIntegrityDecision(collectionId, createInput),
    ).rejects.toThrow("connection reset");
    await expect(
      createCollectionIntegrityDecision(collectionId, createInput),
    ).resolves.toEqual(expect.objectContaining({ id: decisionId }));

    const firstOptions = vi.mocked(apiRequest).mock.calls[0]?.[1];
    const secondOptions = vi.mocked(apiRequest).mock.calls[1]?.[1];
    expect(firstOptions?.idempotencyKey).toBe(secondOptions?.idempotencyKey);
    expect(window.localStorage.length).toBe(0);
  });

  it("drops a pending key after a definitive client error", async () => {
    vi.mocked(apiRequest)
      .mockRejectedValueOnce(
        new ApiError("invalid reference", 422, "REFERENCE_INVALID", false),
      )
      .mockResolvedValueOnce(decisionResponse());

    await expect(
      createCollectionIntegrityDecision(collectionId, createInput),
    ).rejects.toMatchObject({ status: 422 });
    await createCollectionIntegrityDecision(collectionId, createInput);

    const firstOptions = vi.mocked(apiRequest).mock.calls[0]?.[1];
    const secondOptions = vi.mocked(apiRequest).mock.calls[1]?.[1];
    expect(firstOptions?.idempotencyKey).not.toBe(secondOptions?.idempotencyKey);
  });

  it("rejects mismatched action and free-form fields before any request", async () => {
    await expect(
      createCollectionIntegrityDecision(collectionId, {
        ...createInput,
        reason_code: "ACCEPTED_QUARANTINE",
        note: "free-form source text is forbidden",
      } as never),
    ).rejects.toBeInstanceOf(CollectionIntegrityContractError);
    expect(apiRequest).not.toHaveBeenCalled();
  });
});
