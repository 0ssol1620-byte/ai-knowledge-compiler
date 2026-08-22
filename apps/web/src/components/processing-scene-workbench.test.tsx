import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ProcessingSceneWorkbench } from "@/components/processing-scene-workbench";
import type { CollectionScene } from "@/lib/collection-runtime-client";
import { emptyProcessingScene } from "@/lib/processing-scene-model";

afterEach(cleanup);

const collectionId = "00000000-0000-4000-8000-000000000001";
const pageId = "00000000-0000-4000-8000-000000000002";
const proofId = "00000000-0000-4000-8000-000000000003";

function collectionScene(): CollectionScene {
  return {
    collection_id: collectionId,
    collection_status: "PROCESSING",
    manifest_revision: 1,
    sequence: 12,
    total_pages: 1,
    projected_page_count: 1,
    route_state_counts: { precision: 1 },
    clusters: [],
    pages: [
      {
        page_id: pageId,
        document_id: "00000000-0000-4000-8000-000000000004",
        document_version_id: "00000000-0000-4000-8000-000000000005",
        page_number: 1,
        status: "verified",
        route: "precision",
        preview_ref:
          "/v1/document-versions/00000000-0000-4000-8000-000000000005/pages/1/preview",
        finding_count: 1,
      },
    ],
    knowledge: {
      note_ids: [],
      entity_ids: [],
      relation_ids: [],
      package_ids: [],
      note_count: 0,
      entity_count: 0,
      relation_count: 0,
      package_count: 0,
    },
    integrity: {
      file_status_counts: {},
      verification_status_counts: { verified: 1 },
      authority_mapping_status_counts: {},
      package_status_counts: {},
      unresolved_count: 0,
      quarantined_count: 0,
      blocker_codes: [],
    },
    scene_hash: "a".repeat(64),
  };
}

describe("ProcessingSceneWorkbench proof surface", () => {
  it("renders the persisted page preview and tenant-authorized PII-masked proof crop", () => {
    const projection = emptyProcessingScene(collectionId);
    projection.pages.push({
      id: pageId,
      pageNumber1: 1,
      route: "precision",
      state: "authority_verified",
      regionIds: ["region-1"],
      blockIds: ["block-1"],
      tableIds: ["table-1"],
      proofIds: [proofId],
      lastSequence: 12,
    });

    render(
      <ProcessingSceneWorkbench
        scene={collectionScene()}
        projection={projection}
        locale="en"
        mobile
      />,
    );

    expect(
      screen.getByRole("img", {
        name: "Authenticated derived preview for page 1",
      }),
    ).toHaveAttribute(
      "src",
      expect.stringMatching(/\/v1\/document-versions\/.+\/pages\/1\/preview$/),
    );
    expect(
      screen.getByRole("img", {
        name: "PII-masked crop from the persisted verification record",
      }),
    ).toHaveAttribute(
      "src",
      expect.stringMatching(`/v1/proofs/${proofId}/crop$`),
    );
    expect(screen.getByText("Actual source proof")).toBeInTheDocument();
  });

  it("fails closed when an event projection carries a non-UUID proof identifier", () => {
    const projection = emptyProcessingScene(collectionId);
    projection.pages.push({
      id: pageId,
      state: "authority_verified",
      regionIds: [],
      blockIds: [],
      tableIds: [],
      proofIds: ["untrusted-proof-reference"],
      lastSequence: 12,
    });

    render(
      <ProcessingSceneWorkbench
        scene={collectionScene()}
        projection={projection}
        locale="en"
        mobile
      />,
    );

    expect(screen.queryByText("Actual source proof")).not.toBeInTheDocument();
  });
});
