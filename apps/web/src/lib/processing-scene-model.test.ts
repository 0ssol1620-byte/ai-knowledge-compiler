import { describe, expect, it } from "vitest";

import type { CollectionEvent } from "@/lib/collection-runtime-client";
import {
  emptyProcessingScene,
  projectProcessingScene,
} from "@/lib/processing-scene-model";

const collectionId = "collection-0001";

function event(
  sequence: number,
  eventType: CollectionEvent["event_type"],
  payload: Record<string, unknown> = {},
  eventId = `event-${sequence}`,
): CollectionEvent {
  return {
    event_id: eventId,
    collection_id: collectionId,
    job_id: "job-0001",
    sequence,
    event_type: eventType,
    timestamp: `2026-08-02T05:${String(sequence).padStart(2, "0")}:00Z`,
    payload: { collection_id: collectionId, ...payload },
    schema_version: "1.0",
  } as CollectionEvent;
}

describe("ProcessingSceneModel projection", () => {
  it("projects actual persisted events into a deterministic user scene", () => {
    const events = [
      event(1, "collection.files.planned.v1", {
        total_files: 42,
        total_bytes: 9_200_000,
        status: "uploading",
      }),
      event(2, "preflight.cluster.created.v1", {
        preflight_id: "cluster-reports",
        category: "reports",
        member_files: 12,
        feature_records: 31,
      }),
      event(3, "estimate.final.ready.v1", {
        estimate_run_id: "estimate-1",
        detail_ref: "estimate:estimate-1",
      }),
      event(4, "processing.started.v1", { processing_job_id: "job-0001" }),
      event(5, "page.route.selected.v1", {
        page_id: "page-13",
        page_number1: 13,
        route: "precision-table",
        worker_lane_id: "lane-precision",
      }),
      event(6, "region.route.selected.v1", {
        page_id: "page-13",
        region_id: "region-table-2",
      }),
      event(7, "block.completed.v1", {
        page_id: "page-13",
        block_id: "block-revenue",
      }),
      event(8, "table.reconstructed.v1", {
        page_id: "page-13",
        table_id: "table-income",
      }),
      event(9, "verification.failed.v1", {
        page_id: "page-13",
        integrity_id: "integrity-1",
        reason_codes: ["row-omission"],
      }),
      event(10, "repair.started.v1", {
        page_id: "page-13",
        repair_id: "repair-1",
        target_id: "region-table-2",
      }),
      event(11, "repair.completed.v1", {
        page_id: "page-13",
        repair_id: "repair-1",
        target_id: "region-table-2",
      }),
      event(12, "numeric.authority.verified.v1", {
        page_id: "page-13",
        proof_id: "proof-revenue",
      }),
      event(13, "note.created.v1", { note_id: "note-revenue", note_count: 1 }),
      event(14, "entity.resolved.v1", {
        entity_id: "entity-jtc",
        entity_count: 1,
      }),
      event(15, "relation.created.v1", {
        relation_id: "relation-reported",
        relation_count: 1,
      }),
      event(16, "architecture.folder.created.v1", {
        folder_id: "folder-financials",
        folder_count: 1,
      }),
      event(17, "package.validated.v1", {
        package_manifest_id: "package-1",
        detail_ref: "package:package-1",
      }),
      event(18, "package.signed.v1", {
        package_manifest_id: "package-1",
        signature_status: "signed",
      }),
    ];

    const first = projectProcessingScene(collectionId, events);
    const replay = projectProcessingScene(collectionId, [...events].reverse());

    expect(first.scene.sceneHash).toBe(replay.scene.sceneHash);
    expect(first.scene.connection).toBe("complete");
    expect(first.scene.collection.files).toBe(42);
    expect(first.scene.clusters[0]).toMatchObject({
      id: "cluster-reports",
      fileCount: 12,
    });
    expect(first.scene.pages[0]).toMatchObject({
      id: "page-13",
      pageNumber1: 13,
      route: "precision-table",
      state: "authority_verified",
      regionIds: ["region-table-2"],
      blockIds: ["block-revenue"],
      tableIds: ["table-income"],
      proofIds: ["proof-revenue"],
    });
    expect(first.scene.knowledge.notes[0]?.id).toBe("note-revenue");
    expect(first.scene.knowledge.relations[0]?.id).toBe("relation-reported");
    expect(first.scene.integrity.resolved[0]?.id).toBe("repair-1");
    expect(first.scene.milestones.map((item) => item.kind)).toContain(
      "package-signed",
    );
  });

  it("deduplicates event IDs without changing the scene hash", () => {
    const source = event(1, "file.hash.progress.v1", { hashed_files: 2 });
    const once = projectProcessingScene(collectionId, [source]);
    const duplicated = projectProcessingScene(collectionId, [source, source]);

    expect(duplicated.scene.sceneHash).toBe(once.scene.sceneHash);
    expect(duplicated.diagnostics.duplicateEventIds).toEqual([source.event_id]);
  });

  it("sorts out-of-order delivery before projection", () => {
    const one = event(1, "file.hash.progress.v1", { hashed_files: 2 });
    const two = event(2, "file.upload.progress.v1", { completed_files: 1 });

    const ordered = projectProcessingScene(collectionId, [one, two]);
    const shuffled = projectProcessingScene(collectionId, [two, one]);

    expect(shuffled.scene.sceneHash).toBe(ordered.scene.sceneHash);
    expect(shuffled.scene.collection.uploadState).toBe("uploading");
  });

  it("pauses at a sequence gap and exposes pending sequences for reconciliation", () => {
    const projection = projectProcessingScene(collectionId, [
      event(1, "file.hash.progress.v1"),
      event(3, "file.upload.progress.v1"),
    ]);

    expect(projection.scene.sequence).toBe(1);
    expect(projection.scene.connection).toBe("replaying");
    expect(projection.diagnostics.gapAfter).toBe(1);
    expect(projection.diagnostics.pendingSequences).toEqual([3]);
  });

  it("reports conflicting sequences and applies one canonical event", () => {
    const projection = projectProcessingScene(collectionId, [
      event(1, "file.hash.progress.v1", {}, "event-a"),
      event(1, "file.upload.progress.v1", {}, "event-b"),
    ]);

    expect(projection.diagnostics.conflictingSequences).toEqual([1]);
    expect(projection.scene.collection.uploadState).toBe("hashing");
  });

  it("continues deterministically from a reconciled snapshot", () => {
    const baseline = projectProcessingScene(collectionId, [
      event(1, "file.hash.progress.v1"),
      event(2, "file.upload.progress.v1"),
    ]).scene;
    const resumed = projectProcessingScene(
      collectionId,
      [event(3, "collection.upload.completed.v1")],
      baseline,
    );

    expect(resumed.scene.sequence).toBe(3);
    expect(resumed.scene.collection.uploadState).toBe("verifying");
    expect(resumed.scene.connection).toBe("live");
  });

  it("ignores unsupported event versions without leaking payload content", () => {
    const unsupported = {
      ...event(1, "file.hash.progress.v1", { raw_customer_text: "secret" }),
      schema_version: "0.9",
    } as unknown as CollectionEvent;
    const projection = projectProcessingScene(collectionId, [unsupported]);

    expect(projection.scene).toEqual(emptyProcessingScene(collectionId));
    expect(JSON.stringify(projection.scene)).not.toContain("secret");
    expect(projection.diagnostics.unsupportedEventIds).toEqual(["event-1"]);
  });
});
