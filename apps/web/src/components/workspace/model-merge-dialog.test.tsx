import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ModelMergeDialog } from "@/components/workspace/model-merge-dialog";
import { ApiError } from "@/lib/api-client";
import type { BlockModelMergeResponse, CanonicalBlock } from "@/lib/types";

const block: CanonicalBlock = {
  id: "block-1",
  order: 1,
  type: "paragraph",
  markdown: "User version",
  source_text: "Source version",
  origin: "user_edited",
  content_layer: "structured",
  source_refs: [],
  quality_flags: [],
  revision: 4,
};

const conflict: BlockModelMergeResponse = {
  block_id: block.id,
  status: "conflict",
  base_revision: 3,
  current_revision: 4,
  applied: false,
  user_locked: true,
  base: "Base version",
  user: "User version",
  new_model: "Model version",
  merged: null,
  conflict_count: 1,
  etag: '"revision-4"',
};

afterEach(cleanup);

function fillComparison() {
  fireEvent.change(screen.getByLabelText("Base revision"), {
    target: { value: "3" },
  });
  fireEvent.change(screen.getByLabelText("Model revision"), {
    target: { value: "model@2" },
  });
  fireEvent.change(screen.getByLabelText("New model Markdown"), {
    target: { value: "Model version" },
  });
}

describe("ModelMergeDialog", () => {
  it("shows all three conflict panes and applies only an explicit choice", async () => {
    const onPreview = vi.fn().mockResolvedValue(conflict);
    const onApply = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <ModelMergeDialog
        block={block}
        open
        onClose={onClose}
        onPreview={onPreview}
        onApply={onApply}
        onStale={vi.fn()}
      />,
    );

    fillComparison();
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));

    expect(
      await screen.findByRole("listbox", { name: "Choose a revision result" }),
    ).toBeVisible();
    const panes = screen.getAllByRole("option");
    expect(panes).toHaveLength(3);
    expect(panes[0]).toHaveTextContent("Base version");
    expect(panes[1]).toHaveTextContent("User version");
    expect(panes[2]).toHaveTextContent("Model version");
    expect(
      screen.getByRole("button", { name: "Apply selected result" }),
    ).toBeDisabled();

    panes[0]!.focus();
    fireEvent.keyDown(panes[0]!, { key: "ArrowRight" });
    expect(panes[1]).toHaveFocus();

    fireEvent.click(panes[2]!);
    expect(screen.getByLabelText("Resolved Markdown")).toHaveValue(
      "Model version",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Apply selected result" }),
    );
    await waitFor(() => expect(onApply).toHaveBeenCalledOnce());
    expect(onApply.mock.calls[0]?.[2]).toBe("Model version");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("refreshes and blocks apply when the ETag is stale", async () => {
    const onStale = vi.fn();
    const onPreview = vi
      .fn()
      .mockRejectedValue(
        new ApiError("Revision conflict", 412, "REVISION_CONFLICT", false),
      );
    render(
      <ModelMergeDialog
        block={block}
        open
        onClose={vi.fn()}
        onPreview={onPreview}
        onApply={vi.fn()}
        onStale={onStale}
      />,
    );

    fillComparison();
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "changed after the comparison opened",
    );
    expect(onStale).toHaveBeenCalledOnce();
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("reuses the idempotency key when an identical preview is retried", async () => {
    const onPreview = vi
      .fn()
      .mockRejectedValueOnce(new Error("Temporary failure"))
      .mockResolvedValueOnce(conflict);
    render(
      <ModelMergeDialog
        block={block}
        open
        onClose={vi.fn()}
        onPreview={onPreview}
        onApply={vi.fn()}
        onStale={vi.fn()}
      />,
    );

    fillComparison();
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Temporary failure",
    );
    fireEvent.click(screen.getByRole("button", { name: "Compare revisions" }));
    await screen.findByRole("listbox");

    expect(onPreview).toHaveBeenCalledTimes(2);
    expect(onPreview.mock.calls[0]?.[2]).toBe(onPreview.mock.calls[1]?.[2]);
  });
});
