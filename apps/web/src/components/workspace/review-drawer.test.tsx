import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewDrawer } from "@/components/workspace/review-drawer";
import type { ReviewItem, ReviewScopePreview } from "@/lib/types";

afterEach(cleanup);

const item: ReviewItem = {
  id: "review-1",
  severity: "high",
  category: "number_mismatch",
  message: "A measured value differs from the source.",
  page_id: "page-1",
  block_id: "block-1",
  status: "open",
  candidates: [
    { engine: "native", value: "1,000" },
    { engine: "ocr", value: "1,900" },
  ],
};

describe("ReviewDrawer", () => {
  it("supports source adoption and hash-bound document rule preview", async () => {
    const preview: ReviewScopePreview = {
      document_id: "document-1",
      category: "number_mismatch",
      item_count: 3,
      review_ids: ["review-1", "review-2", "review-3"],
      preview_sha256: "a".repeat(64),
      allowed_actions: ["accept", "adopt_source", "reject"],
    };
    const onResolve = vi.fn().mockResolvedValue(undefined);
    const onPreviewRule = vi.fn().mockResolvedValue(preview);
    const onApplyRule = vi.fn().mockResolvedValue(undefined);

    render(
      <ReviewDrawer
        items={[item]}
        open
        onClose={vi.fn()}
        onSelectEvidence={vi.fn()}
        onResolve={onResolve}
        onPreviewRule={onPreviewRule}
        onApplyRule={onApplyRule}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Adopt source" }));
    await waitFor(() =>
      expect(onResolve).toHaveBeenCalledWith(
        item,
        expect.objectContaining({ action: "adopt_source" }),
      ),
    );
  });

  it("applies only the previewed document scope hash", async () => {
    const preview: ReviewScopePreview = {
      document_id: "document-1",
      category: "number_mismatch",
      item_count: 3,
      review_ids: ["review-1", "review-2", "review-3"],
      preview_sha256: "b".repeat(64),
      allowed_actions: ["accept", "adopt_source", "reject"],
    };
    const onPreviewRule = vi.fn().mockResolvedValue(preview);
    const onApplyRule = vi.fn().mockResolvedValue(undefined);

    render(
      <ReviewDrawer
        items={[item]}
        open
        onClose={vi.fn()}
        onSelectEvidence={vi.fn()}
        onPreviewRule={onPreviewRule}
        onApplyRule={onApplyRule}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Preview matching items" }),
    );
    expect(await screen.findByText(/3 open/)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Approve all" }));
    await waitFor(() =>
      expect(onApplyRule).toHaveBeenCalledWith(
        item,
        "accept",
        preview.preview_sha256,
      ),
    );
  });
});
