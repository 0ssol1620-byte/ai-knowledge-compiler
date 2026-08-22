import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { prepareConnectedCollection } from "@/lib/collection-client";
import { uploadSourceFile } from "@/lib/upload-client";

vi.mock("@/lib/upload-client", async () => {
  const actual = await vi.importActual<Record<string, unknown>>(
    "@/lib/upload-client",
  );
  return { ...actual, uploadSourceFile: vi.fn() };
});

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(uploadSourceFile).mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

function folderFile(path = "vault/note.md"): File {
  const file = new File(["source"], path.split("/").at(-1) ?? "note.md", {
    type: "text/markdown",
    lastModified: 42,
  });
  Object.defineProperty(file, "webkitRelativePath", { value: path });
  return file;
}

const collection = {
  id: "collection-1",
  status: "UPLOADING",
  manifest_revision: 1,
};
const uploadBase = {
  upload_session_id: "00000000-0000-4000-8000-000000000011",
  manifest_revision: 1,
  resume_version: 1,
  status: "uploading",
  total_files: 1,
  total_bytes: 6,
  completed_files: 0,
  active_files: 1,
  failed_files: 0,
  duplicate_files: 0,
  source_manifest_hash: "b".repeat(64),
  expires_at: "2026-08-01T01:00:00Z",
};
const plannedFile = {
  id: "file-1",
  source_root_id: "source-root-1",
  source_file_id: null,
  relative_path: "vault/note.md",
  display_name: "note.md",
  size_bytes: 6,
  expected_mime: "text/markdown",
  sha256: "a".repeat(64),
  status: "planned",
  error_code: null,
  upload_required: true,
  upload_endpoint: "/v1/uploads/initiate",
};
const verifiedFile = {
  ...plannedFile,
  source_file_id: "source-file-1",
  status: "verified",
  upload_required: false,
  upload_endpoint: null,
};
const completedUpload = {
  ...uploadBase,
  status: "completed",
  completed_files: 1,
  active_files: 0,
};
const preflight = {
  id: "preflight-1",
  status: "complete",
  input_manifest_hash: "b".repeat(64),
  output_sha256: "c".repeat(64),
  limitations: ["No processing job was requested."],
  estimate: {
    status: "sampled_ready",
    basis: "repository_rule_v1",
    p50_credits: "12.5",
    p95_credits: "18.75",
    duration_p50_seconds: 60,
    duration_p95_seconds: 120,
    route_mix: { native_pages: 8 },
    reserve_ceiling: "18.75",
    confidence: "0.86",
    confidence_band: "high",
    known_pages: 8,
    sampled_pages: 8,
    billable_pages: 8,
    duplicate_pages: 0,
    unbillable_pages: 0,
    unestimated_files: 0,
    predictor_revision: "sampled_router_v1",
    estimate_sha256: "d".repeat(64),
    calibration_required: false,
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
    warnings: [
      "Repository-rule estimate is not a calibrated production quantile model.",
    ],
  },
};

describe("prepareConnectedCollection", () => {
  it("uploads required bytes, binds the verified receipt, and only then requests preflight", async () => {
    vi.mocked(uploadSourceFile).mockResolvedValue({
      uploadId: "upload-1",
      sourceFileId: "source-file-1",
      documentId: "document-1",
      documentVersion: 1,
      status: "SECURITY_VERIFIED",
      sha256: "a".repeat(64),
    });
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ ...collection, status: "CREATED" }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "source-root-1",
          collection_id: collection.id,
          source_type: "local",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection,
          upload: uploadBase,
          browser_resume_token: "r".repeat(40),
          files: [plannedFile],
          limitations: ["Verified upload receipt required."],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection: { ...collection, status: "INGESTED" },
          upload: completedUpload,
          accepted_receipts: 1,
          duplicate_reuses: 0,
          unresolved_files: 0,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection: { ...collection, status: "INGESTED" },
          upload: completedUpload,
          files: [verifiedFile],
          offset: 0,
          limit: 500,
          next_offset: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(preflight));
    vi.stubGlobal("fetch", fetchMock);

    const file = folderFile();
    const result = await prepareConnectedCollection({
      projectId: "project-1",
      name: "Research vault",
      files: [file],
      hashBlob: vi.fn().mockResolvedValue("a".repeat(64)),
    });

    expect(uploadSourceFile).toHaveBeenCalledWith(
      file,
      "project-1",
      "a".repeat(64),
      { signal: undefined },
    );
    expect(fetchMock.mock.calls.map(([url]) => String(url))).toEqual([
      "http://localhost:8000/v1/collections",
      "http://localhost:8000/v1/collections/collection-1/sources/local",
      "http://localhost:8000/v1/collections/collection-1/files/plan",
      "http://localhost:8000/v1/collections/collection-1/upload/complete",
      "http://localhost:8000/v1/collections/collection-1/upload?offset=0&limit=500",
      "http://localhost:8000/v1/collections/collection-1/preflight",
    ]);
    const receiptRequest = fetchMock.mock.calls[3]?.[1];
    const planRequest = fetchMock.mock.calls[2]?.[1];
    const plannedPayload = JSON.parse(String(planRequest?.body));
    expect(plannedPayload.files[0]).toEqual(
      expect.objectContaining({
        sha256: "a".repeat(64),
        quick_fingerprint: expect.stringMatching(/^qv1:\d+:[0-9a-f]{64}$/),
      }),
    );
    expect(JSON.parse(String(receiptRequest?.body))).toEqual({
      receipts: [
        {
          file_id: "file-1",
          outcome: "completed",
          source_file_id: "source-file-1",
        },
      ],
    });
    expect(result.blocker).toBeUndefined();
    expect(result.preflight?.estimate.basis).toBe("repository_rule_v1");
  });

  it("reuses an already verified source without uploading bytes", async () => {
    const duplicateFile = {
      ...verifiedFile,
      status: "duplicate",
    };
    const duplicateUpload = { ...completedUpload, duplicate_files: 1 };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ ...collection, status: "CREATED" }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "source-root-1",
          collection_id: collection.id,
          source_type: "local",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection: { ...collection, status: "INGESTED" },
          upload: duplicateUpload,
          browser_resume_token: "r".repeat(40),
          files: [duplicateFile],
          limitations: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection: { ...collection, status: "INGESTED" },
          upload: duplicateUpload,
          files: [duplicateFile],
          offset: 0,
          limit: 500,
          next_offset: null,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(preflight));
    vi.stubGlobal("fetch", fetchMock);

    const result = await prepareConnectedCollection({
      projectId: "project-1",
      name: "Research vault",
      files: [folderFile()],
      hashBlob: vi.fn().mockResolvedValue("a".repeat(64)),
    });

    expect(uploadSourceFile).not.toHaveBeenCalled();
    expect(fetchMock).toHaveBeenCalledTimes(5);
    expect(result.preflight?.estimate.known_pages).toBe(8);
  });

  it("returns a resumable collection blocker after a source transfer interruption", async () => {
    vi.mocked(uploadSourceFile).mockRejectedValue(
      new Error("Network transfer interrupted."),
    );
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ ...collection, status: "CREATED" }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "source-root-1",
          collection_id: collection.id,
          source_type: "local",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection,
          upload: uploadBase,
          browser_resume_token: "r".repeat(40),
          files: [plannedFile],
          limitations: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection,
          upload: uploadBase,
          files: [plannedFile],
          offset: 0,
          limit: 500,
          next_offset: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await prepareConnectedCollection({
      projectId: "project-1",
      name: "Research vault",
      files: [folderFile()],
      hashBlob: vi.fn().mockResolvedValue("a".repeat(64)),
    });

    expect(result.blocker).toEqual(
      expect.objectContaining({
        code: "SOURCE_UPLOAD_INTERRUPTED",
        requiredFiles: 1,
      }),
    );
    expect(result.blocker?.message).toMatch(/same files to resume/i);
    expect(result.preflight).toBeUndefined();
  });

  it("persists a verified receipt and rebinds it without uploading the file again", async () => {
    vi.mocked(uploadSourceFile).mockResolvedValue({
      uploadId: "upload-1",
      sourceFileId: "source-file-1",
      documentId: "document-1",
      documentVersion: 1,
      status: "SECURITY_VERIFIED",
      sha256: "a".repeat(64),
    });
    const plannedStatus = {
      collection,
      upload: uploadBase,
      files: [plannedFile],
      offset: 0,
      limit: 500,
      next_offset: null,
    };
    const verifiedStatus = {
      collection: { ...collection, status: "INGESTED" },
      upload: completedUpload,
      files: [verifiedFile],
      offset: 0,
      limit: 500,
      next_offset: null,
    };
    const fetchMock = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ ...collection, status: "CREATED" }))
      .mockResolvedValueOnce(
        jsonResponse({
          id: "source-root-1",
          collection_id: collection.id,
          source_type: "local",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          collection,
          upload: uploadBase,
          browser_resume_token: "r".repeat(40),
          files: [plannedFile],
          limitations: [],
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: "OBJECT_STORE_UNAVAILABLE",
              message: "Receipt binding was interrupted.",
              retryable: true,
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(jsonResponse(plannedStatus))
      .mockResolvedValueOnce(jsonResponse(plannedStatus))
      .mockResolvedValueOnce(
        jsonResponse({
          collection: { ...collection, status: "INGESTED" },
          upload: completedUpload,
          accepted_receipts: 1,
          duplicate_reuses: 0,
          unresolved_files: 0,
        }),
      )
      .mockResolvedValueOnce(jsonResponse(verifiedStatus))
      .mockResolvedValueOnce(jsonResponse(verifiedStatus))
      .mockResolvedValueOnce(jsonResponse(preflight));
    vi.stubGlobal("fetch", fetchMock);
    const file = folderFile();
    const hashBlob = vi.fn().mockResolvedValue("a".repeat(64));

    const interrupted = await prepareConnectedCollection({
      projectId: "project-1",
      name: "Research vault",
      files: [file],
      hashBlob,
    });
    expect(interrupted.blocker?.code).toBe(
      "COLLECTION_RECEIPT_BINDING_INTERRUPTED",
    );

    const resumed = await prepareConnectedCollection({
      projectId: "project-1",
      name: "Research vault",
      files: [file],
      hashBlob,
      resume: {
        collectionId: interrupted.collectionId,
        sourceRootId: interrupted.sourceRootId,
      },
    });

    expect(uploadSourceFile).toHaveBeenCalledTimes(1);
    expect(resumed.blocker).toBeUndefined();
    expect(resumed.preflight?.status).toBe("complete");
    const reboundBody = JSON.parse(
      String(fetchMock.mock.calls[6]?.[1]?.body),
    ) as { receipts: Array<Record<string, string>> };
    expect(reboundBody.receipts).toEqual([
      {
        file_id: "file-1",
        outcome: "completed",
        source_file_id: "source-file-1",
      },
    ]);
  });

  it("rejects unsafe paths before creating server records", async () => {
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      prepareConnectedCollection({
        projectId: "project-1",
        name: "Unsafe vault",
        files: [folderFile("../secret.md")],
        hashBlob: vi.fn().mockResolvedValue("a".repeat(64)),
      }),
    ).rejects.toMatchObject({ code: "UNSAFE_RELATIVE_PATH" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
