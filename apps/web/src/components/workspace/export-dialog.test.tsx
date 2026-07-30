import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ExportDialog,
  type VaultMergePreview,
} from "@/components/workspace/export-dialog";

afterEach(cleanup);

describe("ExportDialog Vault merge preview", () => {
  it("keeps the imported Vault read-only and requires preview before download", async () => {
    const onExport = vi.fn().mockResolvedValue({
      exportId: "export-1",
      downloadUrl: "/v1/exports/export-1/download",
    });
    const preview: VaultMergePreview = {
      policy: "rename_incoming",
      existing_file_count: 12,
      incoming_file_count: 7,
      output_file_count: 19,
      conflict_count: 1,
      unresolved_conflict_count: 0,
      broken_link_count: 1,
      safe_to_apply: true,
      plan_sha256: "a".repeat(64),
      conflicts: [
        {
          existing_path: "Notes/Overview.md",
          incoming_path: "Notes/Overview.md",
          reason: "path_collision",
          resolution: "rename_incoming",
          resolved_path: "Notes/Overview (AKC).md",
        },
      ],
      broken_links: [
        {
          source_path: "MOC.md",
          target: "Missing note",
          resolved_path: null,
          reason: "target_missing",
        },
      ],
    };
    const onVaultPreview = vi.fn().mockResolvedValue(preview);
    render(
      <ExportDialog
        open
        onClose={vi.fn()}
        onExport={onExport}
        onVaultPreview={onVaultPreview}
      />,
    );

    expect(screen.getByText("원본 Vault는 변경하지 않음")).toBeVisible();
    const vault = new File(["PK\u0003\u0004fixture"], "vault.zip", {
      type: "application/zip",
    });
    fireEvent.change(screen.getByLabelText("Existing Vault ZIP (optional)"), {
      target: { files: [vault] },
    });
    fireEvent.change(screen.getByLabelText("Collision policy"), {
      target: { value: "rename_incoming" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "생성하고 충돌 미리보기" }),
    );

    await waitFor(() =>
      expect(onVaultPreview).toHaveBeenCalledWith(
        "export-1",
        vault,
        "rename_incoming",
      ),
    );
    expect(
      await screen.findByText("선택한 정책으로 안전하게 병합 가능"),
    ).toBeVisible();
    expect(screen.getByText("Notes/Overview.md")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "검토 후 패키지 다운로드" }),
    ).toBeVisible();
  });
});
