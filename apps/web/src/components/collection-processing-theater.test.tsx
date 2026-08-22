import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { CollectionProcessingTheater } from "@/components/collection-processing-theater";
import type {
  CollectionEvent,
  CollectionEventSnapshot,
  CollectionProcessingRun,
} from "@/lib/collection-runtime-client";

afterEach(cleanup);

const collectionId = "00000000-0000-4000-8000-000000000001";
const jobId = "00000000-0000-4000-8000-000000000002";

function snapshot(totalTasks: number): CollectionEventSnapshot {
  return {
    collection_id: collectionId,
    status: "PROCESSING",
    manifest_revision: 1,
    latest_sequence: 17,
    upload: null,
    processing_job_id: jobId,
    processing_status: "running",
    processing_stage: "analysis",
    total_tasks: totalTasks,
    completed_tasks: 0,
    failed_tasks: 0,
    credits_reserved: "42",
    credits_consumed: "0",
    credit_hard_cap: "48",
    terminal_result_ids: [],
  };
}

const stalePointer: CollectionProcessingRun = {
  run_id: "00000000-0000-4000-8000-000000000003",
  job_id: jobId,
  architecture_plan_id: "00000000-0000-4000-8000-000000000003",
  status: "running",
  task_counts: {},
  credits_reserved: "42",
  credits_consumed: "0",
  credits_refunded: "0",
  credits_released: "0",
  hard_cap_credits: "48",
  overage_policy: "stop_at_cap",
};

describe("CollectionProcessingTheater task evidence", () => {
  it("uses authoritative snapshot counts instead of an unmeasured local pointer", () => {
    render(
      <CollectionProcessingTheater
        collectionId={collectionId}
        locale="en"
        live={false}
        initialSnapshot={snapshot(64)}
        initialRun={stalePointer}
      />,
    );

    expect(screen.getByText("Measured tasks").parentElement).toHaveTextContent(
      "64",
    );
  });

  it("renders an authoritative zero-task run as zero rather than unmeasured", () => {
    render(
      <CollectionProcessingTheater
        collectionId={collectionId}
        locale="en"
        live={false}
        initialSnapshot={snapshot(0)}
        initialRun={stalePointer}
      />,
    );

    expect(screen.getByText("Measured tasks").parentElement).toHaveTextContent(
      "0",
    );
    expect(screen.queryByText("Not measured")).not.toBeInTheDocument();
  });

  it("requires explicit higher-cap approval for a hard-cap recovery", () => {
    const failedSnapshot: CollectionEventSnapshot = {
      ...snapshot(64),
      status: "FAILED_RETRYABLE",
      processing_status: "failed",
      processing_stage: "analysis",
    };
    const failure: CollectionEvent = {
      event_id: "00000000-0000-4000-8000-000000000004",
      collection_id: collectionId,
      job_id: jobId,
      sequence: 18,
      event_type: "processing.failed.v1",
      timestamp: "2026-08-01T00:00:18Z",
      payload: {
        collection_id: collectionId,
        processing_job_id: jobId,
        error_code: "CREDIT_HARD_CAP_REACHED",
      },
      schema_version: "1.0",
    };
    render(
      <CollectionProcessingTheater
        collectionId={collectionId}
        locale="en"
        live={false}
        initialSnapshot={failedSnapshot}
        initialRun={stalePointer}
        initialEvents={[failure]}
      />,
    );

    const retry = screen.getByRole("button", { name: "Retry processing" });
    expect(retry).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New approved hard cap"), {
      target: { value: "49" },
    });
    expect(retry).toBeEnabled();
  });

  it("does not present an unsafe retry action for an unresolved state", () => {
    render(
      <CollectionProcessingTheater
        collectionId={collectionId}
        locale="en"
        live={false}
        initialSnapshot={{ ...snapshot(64), status: "UNRESOLVED" }}
        initialRun={stalePointer}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Retry processing" }),
    ).not.toBeInTheDocument();
  });
});
