import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ParallelProcessingTheater, type V6VersionedEvent } from "./index";

afterEach(cleanup);

function event(
  sequence: number,
  eventType: string,
  payload: Record<string, unknown> = {},
): V6VersionedEvent {
  return {
    schema_version: "1.0",
    event_id: `event-${sequence}`,
    event_type: eventType,
    sequence,
    occurred_at: `2026-08-01T00:00:${String(sequence).padStart(2, "0")}Z`,
    job_id: "job-v6",
    payload,
  };
}

const productEvents: V6VersionedEvent[] = [
  event(1, "shard.planned.v1", {
    page_ids: ["page-1", "page-2", "page-3"],
  }),
  event(2, "attempt.started.v1", {
    attempt_id: "attempt-1",
    attempt_number: 1,
    root_attempt_id: "attempt-1",
    shard_id: "shard-1",
    page_id: "page-1",
    page_number1: 1,
    worker_pool_id: "pool-mineru",
    worker_id: "worker-a",
    route: "mineru_precision",
  }),
  event(3, "attempt.started.v1", {
    attempt_id: "attempt-2",
    attempt_number: 1,
    root_attempt_id: "attempt-2",
    shard_id: "shard-2",
    page_id: "page-2",
    page_number1: 2,
    worker_pool_id: "pool-paddle",
    worker_id: "worker-b",
    route: "paddle_vl",
  }),
  event(4, "recovery.region.requested.v1", {
    page_id: "page-2",
    page_number1: 2,
    region_id: "table-12",
    reason_code: "row_omission",
  }),
  event(5, "attempt.accepted.v1", {
    attempt_id: "attempt-1",
    page_id: "page-1",
    page_number1: 1,
    verification_state: "verified",
    worker_pool_id: "pool-mineru",
    worker_id: "worker-a",
    validator_status: "pass",
    gpu_seconds: 4.25,
    provider_cost_usd: 0.12,
    cost_source: "provider_invoice",
    billable: true,
  }),
  event(6, "page.unresolved.v1", {
    page_id: "page-3",
    page_number1: 3,
    reason_code: "authority_conflict",
  }),
  event(7, "worker.quarantined.v1", {
    worker_pool_id: "pool-paddle",
    worker_id: "worker-b",
    reason_code: "semantic_canary_failed",
  }),
  event(8, "architecture.folder.created.v1", {
    folder_path: "knowledge/financial-statements",
  }),
];

describe("ParallelProcessingTheater", () => {
  it("shows event-backed parallel page, recovery, and verified states without fake progress", () => {
    render(
      <ParallelProcessingTheater events={productEvents} connection="live" />,
    );

    expect(
      screen.getByRole("heading", { name: "Processing Theater" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Page 1")).toBeInTheDocument();
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByText("Page 3")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Recovering")).toBeInTheDocument();
    expect(screen.getAllByText("Unresolved").length).toBeGreaterThan(0);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByText(/\d+%/)).not.toBeInTheDocument();
    expect(screen.getByText("Directory created")).toBeInTheDocument();
    expect(
      screen.getByText("knowledge/financial-statements"),
    ).toBeInTheDocument();
  });

  it("presents integrity evidence and policy credit impact instead of a manual review queue", () => {
    render(<ParallelProcessingTheater events={productEvents} />);

    expect(
      screen.getByRole("heading", { name: "Integrity state" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Automatic recovery").length).toBeGreaterThan(0);
    expect(screen.getByText("Unresolved output")).toBeInTheDocument();
    expect(screen.getAllByText("Not billable").length).toBeGreaterThan(0);
    expect(screen.getByText(/event:event-6#6/)).toBeInTheDocument();
    expect(screen.queryByText(/manual review/i)).not.toBeInTheDocument();
  });

  it("renders the optional technical view with measured pool, attempt, validator, and cost telemetry", () => {
    render(
      <ParallelProcessingTheater events={productEvents} defaultTechnicalOpen />,
    );

    expect(screen.getByText("Advanced technical view")).toBeInTheDocument();
    expect(screen.getAllByText("pool-mineru").length).toBeGreaterThan(0);
    expect(screen.getAllByText("attempt-1").length).toBeGreaterThan(0);
    expect(screen.getByText("provider_invoice")).toBeInTheDocument();
    expect(screen.getAllByText("4.25").length).toBeGreaterThan(0);
    expect(screen.getByText("0.12")).toBeInTheDocument();
  });

  it("provides an independently written Korean product surface", () => {
    render(
      <ParallelProcessingTheater
        events={productEvents.slice(0, 3)}
        locale="ko"
        connection="replaying"
      />,
    );

    expect(
      screen.getByRole("heading", { name: "프로세싱 시어터" }),
    ).toBeInTheDocument();
    expect(screen.getByText("영속 이벤트 재생 중")).toBeInTheDocument();
    expect(screen.getByText("병렬 페이지 상태")).toBeInTheDocument();
    expect(screen.getByText("고급 기술 보기")).toBeInTheDocument();
  });

  it("surfaces replay gaps and malformed event evidence as a fail-closed warning", () => {
    const malformed: V6VersionedEvent = {
      ...event(4, "attempt.accepted.v1", {
        attempt_id: "attempt-v2",
        page_id: "page-4",
      }),
      schema_version: "2.0",
    };
    render(
      <ParallelProcessingTheater
        events={[event(2, "shard.planned.v1"), malformed]}
        baselineSequence={0}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Event evidence is incomplete",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "unsupported or malformed",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("missing sequence");
  });
});
