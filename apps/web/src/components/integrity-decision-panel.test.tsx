import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { IntegrityDecisionPanel } from "@/components/integrity-decision-panel";
import { createCollectionIntegrityDecision } from "@/lib/collection-integrity-client";
import type {
  CollectionIntegrityDecision,
  CollectionIntegrityFinding,
} from "@/lib/collection-integrity-client";

vi.mock("@/lib/collection-integrity-client", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@/lib/collection-integrity-client",
  );
  return { ...actual, createCollectionIntegrityDecision: vi.fn() };
});

const collectionId = "00000000-0000-4000-8000-000000000001";
const targetId = "00000000-0000-4000-8000-000000000002";

const finding: CollectionIntegrityFinding = {
  target_type: "review_item",
  target_id: targetId,
  status: "open",
  category: "numeric_mismatch",
  severity: "medium",
  reason_code: "REVIEW_NUMERIC_MISMATCH",
  allowed_actions: ["exclude", "correct_source", "override"],
  created_at: "2026-08-01T00:00:00Z",
};

const decision: CollectionIntegrityDecision = {
  id: "00000000-0000-4000-8000-000000000003",
  collection_id: collectionId,
  target_type: "review_item",
  target_id: targetId,
  action: "exclude",
  reason_code: "EXCLUDED_FROM_OUTPUT",
  evidence_reference: null,
  previous_status: "open",
  resulting_status: "resolved",
  override_applied: false,
  actor_id: "00000000-0000-4000-8000-000000000004",
  created_at: "2026-08-01T00:00:00Z",
};

describe("IntegrityDecisionPanel", () => {
  beforeEach(() => {
    vi.mocked(createCollectionIntegrityDecision).mockReset();
  });

  afterEach(cleanup);

  it("records a structured decision without a free-text field", async () => {
    const onCommitted = vi.fn();
    vi.mocked(createCollectionIntegrityDecision).mockResolvedValue(decision);
    render(
      <IntegrityDecisionPanel
        locale="en"
        collectionId={collectionId}
        finding={finding}
        decisions={[]}
        onCommitted={onCommitted}
      />,
    );

    expect(screen.queryByRole("textbox", { name: /note/i })).toBeNull();
    fireEvent.click(
      screen.getByRole("button", { name: "Record audited decision" }),
    );

    await waitFor(() => expect(onCommitted).toHaveBeenCalledWith(decision));
    expect(createCollectionIntegrityDecision).toHaveBeenCalledWith(collectionId, {
      target_type: "review_item",
      target_id: targetId,
      action: "exclude",
      reason_code: "EXCLUDED_FROM_OUTPUT",
      evidence_reference: undefined,
      acknowledge_override: false,
    });
    expect(screen.getByRole("status")).toHaveTextContent(/immutable integrity ledger/);
  });

  it("requires structured evidence and explicit acknowledgement for override", () => {
    render(
      <IntegrityDecisionPanel
        locale="en"
        collectionId={collectionId}
        finding={finding}
        decisions={[]}
        onCommitted={vi.fn()}
      />,
    );

    fireEvent.change(screen.getByLabelText("Decision"), {
      target: { value: "override" },
    });
    const apply = screen.getByRole("button", { name: "Record audited decision" });
    expect(apply).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Evidence SHA-256"), {
      target: { value: "a".repeat(64) },
    });
    expect(apply).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox"));
    expect(apply).toBeEnabled();
  });

  it("keeps the reference surface visibly non-authoritative", () => {
    render(
      <IntegrityDecisionPanel
        locale="en"
        decisions={[]}
        onCommitted={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Record audited decision" }),
    ).toBeDisabled();
    fireEvent.click(screen.getByText("Optional customer decision"));
    expect(screen.getByText(/live open finding/)).toBeVisible();
  });
});
