import { beforeEach, describe, expect, it, vi } from "vitest";

const { fetchEventSourceMock } = vi.hoisted(() => ({
  fetchEventSourceMock: vi.fn(),
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: fetchEventSourceMock,
}));

import { parseJobEvent, streamJob } from "@/lib/api-client";

const baseEvent = {
  event_id: "evt_01",
  occurred_at: "2026-07-29T12:00:00Z",
  project_id: "project_01",
  job_id: "job_01",
  sequence: 1,
  schema_version: "1.0" as const,
  payload: {},
};

describe("processing-event wire contract", () => {
  it("accepts a job-level event when optional document and page ids are omitted", () => {
    expect(
      parseJobEvent({
        ...baseEvent,
        event_type: "job.completed.v1",
      }),
    ).toMatchObject({
      event_type: "job.completed.v1",
      job_id: "job_01",
    });
  });

  it("rejects null optional identifiers because the JSON Schema requires strings", () => {
    expect(
      parseJobEvent({
        ...baseEvent,
        event_type: "job.completed.v1",
        document_id: null,
        page_id: null,
      }),
    ).toBeUndefined();
  });
});

describe("streamJob activity", () => {
  beforeEach(() => {
    fetchEventSourceMock.mockReset();
  });

  it("treats both connection open and comment heartbeat messages as activity", async () => {
    fetchEventSourceMock.mockImplementationOnce(
      async (
        _input: unknown,
        callbacks: {
          onopen?: (response: Response) => Promise<void>;
          onmessage?: (message: {
            data: string;
            event: string;
            id: string;
            retry?: number;
          }) => void;
        },
      ) => {
        await callbacks.onopen?.(new Response(null, { status: 200 }));
        callbacks.onmessage?.({ data: "", event: "", id: "" });
      },
    );

    const onActivity = vi.fn();
    const onEvent = vi.fn();
    await streamJob(
      {
        jobId: "job_01",
        signal: new AbortController().signal,
      },
      {
        onActivity,
        onConnection: vi.fn(),
        onEvent,
      },
    );

    expect(onActivity).toHaveBeenCalledTimes(2);
    expect(onEvent).not.toHaveBeenCalled();
  });
});
