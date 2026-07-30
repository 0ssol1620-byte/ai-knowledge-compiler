import { describe, expect, it } from "vitest";

import {
  initialLiveJobState,
  reduceJobEvent,
  resolveJobPresentationStatus,
  weightedOverallProgress,
} from "@/lib/event-reducer";
import type { JobEvent, JobEventType } from "@/lib/types";

function event(
  sequence: number,
  type: JobEventType,
  payload: unknown = {},
): JobEvent {
  return {
    event_id: `evt_${sequence}`,
    event_type: type,
    occurred_at: "2026-07-29T00:00:00Z",
    project_id: "project",
    job_id: "job",
    sequence,
    schema_version: "1.0",
    payload,
  };
}

function permutations<T>(values: readonly T[]): T[][] {
  if (values.length <= 1) return [Array.from(values)];
  return values.flatMap((value, index) =>
    permutations(values.filter((_, candidate) => candidate !== index)).map(
      (suffix) => [value, ...suffix],
    ),
  );
}

describe("reduceJobEvent", () => {
  it("buffers gaps, drains in order, and ignores duplicates", () => {
    const buffered = reduceJobEvent(
      initialLiveJobState,
      event(2, "job.stage.progress.v1", {
        stage: "preflight",
        done: 1,
        total: 2,
      }),
    );
    expect(buffered.lastSequence).toBe(0);
    expect(buffered.needsReplay).toBe(true);
    expect(buffered.gapFrom).toBe(1);

    const drained = reduceJobEvent(
      buffered,
      event(1, "job.stage.progress.v1", { stage: "upload", done: 1, total: 1 }),
    );
    expect(drained.lastSequence).toBe(2);
    expect(drained.needsReplay).toBe(false);
    expect(drained.stageProgress.preflight).toEqual({ done: 1, total: 2 });
    expect(reduceJobEvent(drained, event(2, "job.completed.v1"))).toBe(drained);
  });

  it("tracks terminal state", () => {
    const state = reduceJobEvent(
      initialLiveJobState,
      event(1, "job.completed.v1"),
    );
    expect(state.terminalStatus).toBe("completed");
    expect(state.connection).toBe("closed");
    expect(resolveJobPresentationStatus("running", state.terminalStatus)).toBe(
      "completed",
    );
  });

  it("clears an unrecoverable replay gap at a persisted snapshot sequence", () => {
    const buffered = reduceJobEvent(
      initialLiveJobState,
      event(9, "job.stage.progress.v1", {
        stage: "extract",
        done: 2,
        total: 10,
      }),
    );
    const reset = reduceJobEvent(buffered, {
      kind: "snapshot.reset",
      lastSequence: 12,
    });
    expect(reset.lastSequence).toBe(12);
    expect(reset.pendingEvents).toEqual({});
    expect(reset.needsReplay).toBe(false);
  });

  it("normalizes the masterplan block-completed payload", () => {
    const state = reduceJobEvent(
      initialLiveJobState,
      event(1, "page.block.completed.v1", {
        block_id: "block_1",
        block_type: "table",
        markdown: "| A | B |",
        source_text: "A B",
        origin_type: "ocr_extracted",
        content_layer: "extracted",
        warnings: ["merged_cell_detected"],
      }),
    );
    expect(state.blockPatches.block_1).toMatchObject({
      id: "block_1",
      type: "table",
      source_text: "A B",
      origin: "ocr_extracted",
      quality_flags: ["merged_cell_detected"],
    });
  });

  it("preserves source evidence when a markdown-only event follows", () => {
    const completed = reduceJobEvent(
      initialLiveJobState,
      event(1, "page.block.completed.v1", {
        block_id: "block_1",
        block_type: "paragraph",
        markdown: "Initial",
        source_text: "Original source",
        origin_type: "native_extracted",
        content_layer: "extracted",
        source_refs: [{ page_number: 1 }],
        order: 2,
        revision: 1,
      }),
    );
    const updated = reduceJobEvent(
      completed,
      event(2, "page.markdown.updated.v1", {
        block_id: "block_1",
        markdown: "Edited",
        revision: 2,
      }),
    );

    expect(updated.blockPatches.block_1).toMatchObject({
      type: "paragraph",
      markdown: "Edited",
      source_text: "Original source",
      source_refs: [{ page_number: 1 }],
      revision: 2,
    });
  });

  it("converges for every arrival permutation and duplicate replay", () => {
    const events = [
      event(1, "job.stage.progress.v1", {
        stage: "upload",
        done: 1,
        total: 1,
      }),
      event(2, "job.stage.progress.v1", {
        stage: "extract",
        done: 2,
        total: 3,
      }),
      event(3, "job.stage.progress.v1", {
        stage: "normalize",
        done: 3,
        total: 3,
      }),
    ] as const;

    for (const arrivalOrder of permutations(events)) {
      const reduced = [...arrivalOrder, events[1], events[0]].reduce(
        reduceJobEvent,
        initialLiveJobState,
      );
      expect(reduced.lastSequence).toBe(3);
      expect(reduced.needsReplay).toBe(false);
      expect(reduced.pendingEvents).toEqual({});
      expect(reduced.stageProgress).toMatchObject({
        upload: { done: 1, total: 1 },
        extract: { done: 2, total: 3 },
        normalize: { done: 3, total: 3 },
      });
    }
  });
});

describe("weightedOverallProgress", () => {
  it("uses only measured stage progress", () => {
    expect(
      weightedOverallProgress({
        upload: { done: 1, total: 1 },
        security_scan: { done: 1, total: 1 },
        preflight: { done: 1, total: 1 },
      }),
    ).toBe(13);
  });

  it("reaches 100 when every stage is complete", () => {
    const complete = Object.fromEntries(
      [
        "upload",
        "security_scan",
        "preflight",
        "extract",
        "normalize",
        "knowledge",
        "validate",
        "package",
      ].map((stage) => [stage, { done: 1, total: 1 }]),
    );
    expect(weightedOverallProgress(complete)).toBe(100);
  });
});
