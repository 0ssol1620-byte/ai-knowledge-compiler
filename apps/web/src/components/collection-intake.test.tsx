import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CollectionIntake } from "@/components/collection-intake";
import { listProjects } from "@/lib/api-client";
import { prepareConnectedCollection } from "@/lib/collection-client";

const navigation = vi.hoisted(() => ({ push: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push }),
}));

vi.mock("@/lib/api-client", async () => {
  const actual =
    await vi.importActual<Record<string, unknown>>("@/lib/api-client");
  return { ...actual, listProjects: vi.fn() };
});

vi.mock("@/lib/collection-client", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@/lib/collection-client",
  );
  return { ...actual, prepareConnectedCollection: vi.fn() };
});

beforeEach(() => {
  navigation.push.mockReset();
  vi.mocked(listProjects).mockReset();
  vi.mocked(prepareConnectedCollection).mockReset();
});

afterEach(cleanup);

function folderFile(path: string, contents = "same content"): File {
  const name = path.split("/").at(-1) ?? path;
  const file = new File([contents], name, {
    type: "text/markdown",
    lastModified: 42,
  });
  Object.defineProperty(file, "webkitRelativePath", {
    configurable: true,
    value: path,
  });
  return file;
}

describe("CollectionIntake", () => {
  it("builds a folder-aware manifest and keeps processing fail-closed", () => {
    render(<CollectionIntake locale="en" connected={false} />);

    const folderInput = screen.getByLabelText("Selected folder files");
    expect(folderInput).toHaveAttribute("webkitdirectory", "");
    expect(folderInput).toHaveAttribute("directory", "");

    fireEvent.change(folderInput, {
      target: {
        files: [
          folderFile("research/current/note.md"),
          folderFile("research/archive/note.md"),
        ],
      },
    });

    expect(screen.getByText("research/current/note.md")).toBeVisible();
    expect(screen.getByText("research/archive/note.md")).toBeVisible();
    expect(
      screen.getByText("Possible duplicates").parentElement,
    ).toHaveTextContent("1");
    expect(screen.getByText(/content checksum must confirm/i)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Pause intake" }));
    expect(screen.getByText("Intake is paused")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Prepare server preflight" }),
    ).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Resume intake" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Prepare server preflight" }),
    );
    expect(screen.getByText("Local preflight request is ready")).toBeVisible();
    expect(screen.getByText(/No API call, upload, job/)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Start processing" }),
    ).toBeDisabled();
  });

  it("shows authenticated upload completion separately from sampled and signed reservation evidence", async () => {
    vi.mocked(listProjects).mockResolvedValue([
      {
        id: "project-1",
        name: "Research",
        updated_at: "2026-07-31T00:00:00Z",
      },
    ]);
    vi.mocked(prepareConnectedCollection).mockImplementation(async (input) => {
      input.onProgress?.({
        stage: "uploading",
        completedFiles: 1,
        totalFiles: 1,
        currentFile: "vault/note.md",
      });
      return {
        collectionId: "collection-1",
        sourceRootId: "source-root-1",
        upload: {
          upload_session_id: "00000000-0000-4000-8000-000000000011",
          manifest_revision: 1,
          resume_version: 1,
          status: "completed",
          total_files: 1,
          total_bytes: 6,
          completed_files: 1,
          active_files: 0,
          failed_files: 0,
          duplicate_files: 0,
          source_manifest_hash: "b".repeat(64),
          expires_at: "2026-08-01T01:00:00Z",
        },
        plannedFiles: [],
        limitations: [],
        preflight: {
          id: "preflight-1",
          status: "complete",
          input_manifest_hash: "b".repeat(64),
          output_sha256: "c".repeat(64),
          limitations: [],
          estimate: {
            status: "fast_ready",
            basis: "repository_rule_v1",
            p50_credits: "12.5",
            p95_credits: "18.75",
            duration_p50_seconds: 60,
            duration_p95_seconds: 120,
            route_mix: {},
            reserve_ceiling: "18.75",
            confidence: "0.4",
            confidence_band: "low",
            known_pages: 8,
            sampled_pages: 0,
            billable_pages: 8,
            duplicate_pages: 0,
            unbillable_pages: 0,
            unestimated_files: 0,
            predictor_revision: "repository_rule_v1",
            estimate_sha256: "d".repeat(64),
            calibration_required: true,
            knowledge_blueprint_id: "general_knowledge_base",
            knowledge_blueprint_registry_sha256: `sha256:${"e".repeat(64)}`,
            knowledge_blueprint_module_sha256: `sha256:${"f".repeat(64)}`,
            knowledge_blueprint_candidates: [
              {
                id: "general_knowledge_base",
                module_sha256: `sha256:${"f".repeat(64)}`,
              },
            ],
            knowledge_blueprint_rationale_codes: ["GENERAL_FALLBACK"],
            output_modules: [
              "source_index",
              "document_catalog",
              "knowledge_notes",
              "entities",
              "relations",
              "integrity",
              "export_manifest",
            ],
            warnings: ["Not a calibrated production quantile."],
          },
        },
      };
    });

    render(<CollectionIntake locale="en" connected />);
    await screen.findByRole("option", { name: "Research" });
    fireEvent.change(screen.getByLabelText("Selected folder files"), {
      target: { files: [folderFile("vault/note.md", "source")] },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Upload collection and prepare preflight",
      }),
    );

    await waitFor(() =>
      expect(prepareConnectedCollection).toHaveBeenCalledTimes(1),
    );
    expect(
      await screen.findByText("Repository preflight completed"),
    ).toBeVisible();
    expect(screen.getByText("Repository rule v1")).toBeVisible();
    expect(
      screen.getByText("Not a calibrated production quantile."),
    ).toBeVisible();
    expect(screen.getByText("Sampled P50").parentElement).toHaveTextContent(
      "Not measured",
    );
    expect(
      screen.getByText("Maximum reservation").parentElement,
    ).toHaveTextContent("Not reserved");
    expect(
      screen.getByRole("button", { name: "Start processing" }),
    ).toBeDisabled();
  });
});
