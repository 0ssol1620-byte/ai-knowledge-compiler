import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import {
  COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS,
  type GeneratedJsonValue,
} from "@akc/contracts";

import { CollectionIntake } from "@/components/collection-intake";
import { CollectionProcessingTheater } from "@/components/collection-processing-theater";
import { IntegrityConsole } from "@/components/integrity-console";
import { IntegrityDecisionPanel } from "@/components/integrity-decision-panel";
import type { CollectionIntegrityFinding } from "@/lib/collection-integrity-client";
import type {
  CollectionEvent,
  CollectionEventSnapshot,
  CollectionProcessingRun,
} from "@/lib/collection-runtime-client";

type Surface =
  | "intake-empty-en"
  | "intake-empty-ko"
  | "theater-loading"
  | "theater-uploading"
  | "theater-running"
  | "theater-paused"
  | "theater-partial"
  | "theater-retry-cap"
  | "theater-retry-credit"
  | "theater-error"
  | "theater-completed"
  | "integrity-reference-en"
  | "integrity-reference-ko"
  | "integrity-decision-en";

const collectionId = "00000000-0000-4000-8000-000000000001";
const jobId = "00000000-0000-4000-8000-000000000002";
const architecturePlanId = "00000000-0000-4000-8000-000000000003";

const INTEGRITY_FINDING: CollectionIntegrityFinding = {
  target_type: "review_item",
  target_id: "00000000-0000-4000-8000-000000000006",
  status: "open",
  category: "numeric_mismatch",
  severity: "medium",
  reason_code: "REVIEW_NUMERIC_MISMATCH",
  allowed_actions: ["exclude", "correct_source", "override"],
  created_at: "2026-08-01T00:00:00Z",
};

const RUNNING_SNAPSHOT: CollectionEventSnapshot = {
  collection_id: collectionId,
  status: "KNOWLEDGE_COMPILING",
  manifest_revision: 1,
  latest_sequence: 9,
  upload: {
    upload_session_id: "00000000-0000-4000-8000-000000000004",
    manifest_revision: 1,
    resume_version: 1,
    status: "completed",
    total_files: 24,
    total_bytes: 84_223_104,
    completed_files: 22,
    active_files: 0,
    failed_files: 1,
    duplicate_files: 1,
    source_manifest_hash: "a".repeat(64),
    expires_at: "2026-08-01T06:00:00Z",
  },
  processing_job_id: jobId,
  processing_status: "running",
  processing_stage: "knowledge",
  total_tasks: 64,
  completed_tasks: 43,
  failed_tasks: 1,
  credits_reserved: "42",
  credits_consumed: "26.5",
  credit_hard_cap: "48",
  terminal_result_ids: [],
};

const RUNNING_RUN: CollectionProcessingRun = {
  run_id: architecturePlanId,
  job_id: jobId,
  architecture_plan_id: architecturePlanId,
  status: "running",
  task_counts: {
    total: 64,
    completed: 43,
    failed: 1,
    billable_pages: 986,
    unbillable_pages: 14,
  },
  credits_reserved: "42",
  credits_consumed: "26.5",
  credits_refunded: "0.5",
  credits_released: "0",
  hard_cap_credits: "48",
  overage_policy: "stop_at_cap",
  resume_token: "r".repeat(40),
};

const EVENTS: CollectionEvent[] = [
  event(1, "collection.upload.completed.v1", { total_files: 24 }),
  event(2, "collection.preflight.completed.v1", { sampled_pages: 48 }),
  event(3, "processing.started.v1", { task_count: 64 }),
  event(4, "page.route.selected.v1", { page_number: 42, route: "native" }),
  event(5, "block.completed.v1", { block_count: 118, evidence_bound: true }),
  event(6, "table.reconstructed.v1", { table_count: 6 }),
  event(7, "numeric.authority.verified.v1", { verified_facts: 12 }),
  event(8, "note.created.v1", { note_count: 38 }),
  event(9, "relation.created.v1", { relation_count: 17 }),
];

function ProductSurfaceCatalog({ surface }: { surface: Surface }) {
  switch (surface) {
    case "intake-empty-en":
      return <CollectionIntake locale="en" connected={false} />;
    case "intake-empty-ko":
      return <CollectionIntake locale="ko" connected={false} />;
    case "integrity-reference-en":
      return <IntegrityConsole locale="en" reference />;
    case "integrity-reference-ko":
      return <IntegrityConsole locale="ko" reference />;
    case "integrity-decision-en":
      return (
        <main className="integrity-console-page" style={{ maxWidth: 760 }}>
          <IntegrityDecisionPanel
            locale="en"
            collectionId={collectionId}
            finding={INTEGRITY_FINDING}
            decisions={[]}
            onCommitted={() => undefined}
          />
        </main>
      );
    case "theater-loading":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
        />
      );
    case "theater-error":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialError="Strict collection event contract rejected the snapshot."
        />
      );
    case "theater-uploading":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={{
            ...RUNNING_SNAPSHOT,
            status: "UPLOADING",
            processing_job_id: null,
            processing_status: null,
            processing_stage: "upload",
            total_tasks: 0,
            completed_tasks: 0,
            failed_tasks: 0,
            upload: {
              ...RUNNING_SNAPSHOT.upload!,
              status: "uploading",
              completed_files: 13,
              active_files: 4,
            },
          }}
          initialEvents={EVENTS.slice(0, 1)}
        />
      );
    case "theater-paused":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={{
            ...RUNNING_SNAPSHOT,
            status: "PAUSED",
            processing_status: "paused",
          }}
          initialRun={{ ...RUNNING_RUN, status: "paused" }}
          initialEvents={EVENTS}
        />
      );
    case "theater-partial":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={{
            ...RUNNING_SNAPSHOT,
            status: "PARTIAL",
            processing_status: "failed",
          }}
          initialRun={{ ...RUNNING_RUN, status: "failed" }}
          initialEvents={EVENTS}
        />
      );
    case "theater-retry-cap":
    case "theater-retry-credit": {
      const errorCode =
        surface === "theater-retry-cap"
          ? "CREDIT_HARD_CAP_REACHED"
          : "INSUFFICIENT_CREDITS_FOR_OVERAGE";
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={{
            ...RUNNING_SNAPSHOT,
            status: "FAILED_RETRYABLE",
            processing_status: "failed",
            processing_stage: "analysis",
            latest_sequence: 10,
          }}
          initialRun={{ ...RUNNING_RUN, status: "failed" }}
          initialEvents={[
            ...EVENTS,
            event(10, "processing.failed.v1", { error_code: errorCode }),
          ]}
        />
      );
    }
    case "theater-completed":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={{
            ...RUNNING_SNAPSHOT,
            status: "COMPLETED",
            processing_status: "completed",
            processing_stage: "package",
            latest_sequence: 11,
          }}
          initialRun={{
            ...RUNNING_RUN,
            status: "completed",
            credits_consumed: "39",
            credits_released: "3",
            task_counts: { ...RUNNING_RUN.task_counts, completed: 64 },
          }}
          initialEvents={[
            ...EVENTS,
            event(10, "package.validated.v1", { manifest_verified: true }),
            event(11, "processing.completed.v1", { terminal: true }),
          ]}
        />
      );
    case "theater-running":
      return (
        <CollectionProcessingTheater
          collectionId={collectionId}
          locale="en"
          live={false}
          initialSnapshot={RUNNING_SNAPSHOT}
          initialRun={RUNNING_RUN}
          initialEvents={EVENTS}
        />
      );
  }
}

const meta = {
  title: "Product/Autonomous knowledge surfaces/State matrix",
  component: ProductSurfaceCatalog,
  args: { surface: "intake-empty-en" },
  argTypes: {
    surface: {
      control: "select",
      options: [
        "intake-empty-en",
        "intake-empty-ko",
        "theater-loading",
        "theater-uploading",
        "theater-running",
        "theater-paused",
        "theater-partial",
        "theater-retry-cap",
        "theater-retry-credit",
        "theater-error",
        "theater-completed",
        "integrity-reference-en",
        "integrity-reference-ko",
        "integrity-decision-en",
      ],
    },
  },
  tags: ["autodocs", "state-matrix"],
} satisfies Meta<typeof ProductSurfaceCatalog>;

export default meta;
type Story = StoryObj<typeof meta>;

export const IntakeEmptyEnglish: Story = {};
export const IntakeEmptyKorean: Story = {
  args: { surface: "intake-empty-ko" },
};
export const TheaterLoadingUnavailable: Story = {
  args: { surface: "theater-loading" },
};
export const TheaterUploading: Story = {
  args: { surface: "theater-uploading" },
};
export const TheaterRunning: Story = { args: { surface: "theater-running" } };
export const TheaterPaused: Story = { args: { surface: "theater-paused" } };
export const TheaterPartial: Story = { args: { surface: "theater-partial" } };
export const TheaterRetryHardCap: Story = {
  args: { surface: "theater-retry-cap" },
};
export const TheaterRetryCreditBalance: Story = {
  args: { surface: "theater-retry-credit" },
};
export const TheaterContractError: Story = {
  args: { surface: "theater-error" },
};
export const TheaterCompleted: Story = {
  args: { surface: "theater-completed" },
};
export const TheaterMobile: Story = {
  args: { surface: "theater-running" },
  parameters: { viewport: { defaultViewport: "mobile1" } },
};
export const TheaterReducedMotion: Story = {
  args: { surface: "theater-running" },
  parameters: { chromatic: { prefersReducedMotion: "reduce" } },
};
export const IntegrityReferenceEnglish: Story = {
  args: { surface: "integrity-reference-en" },
};
export const IntegrityReferenceKorean: Story = {
  args: { surface: "integrity-reference-ko" },
};
export const IntegrityAuditedDecision: Story = {
  args: { surface: "integrity-decision-en" },
};

function event(
  sequence: number,
  eventType: CollectionEvent["event_type"],
  payload: CollectionEvent["payload"],
): CollectionEvent {
  const defaults: Record<string, GeneratedJsonValue> = {
    collection_id: collectionId,
    processing_job_id: jobId,
    architecture_plan_id: architecturePlanId,
    analysis_task_id: "00000000-0000-4000-8000-000000000005",
    task_count: 0,
    credits: "0",
    error_code: "STORY_FIXTURE",
  };
  const requiredPayload = Object.fromEntries(
    Object.keys(COLLECTION_EVENT_REQUIRED_PAYLOAD_FIELDS[eventType]).map(
      (key) => [key, defaults[key] ?? "STORY_FIXTURE"],
    ),
  );
  return {
    event_id: `00000000-0000-4000-8000-${String(sequence).padStart(12, "0")}`,
    collection_id: collectionId,
    job_id: jobId,
    sequence,
    event_type: eventType,
    timestamp: `2026-08-01T00:00:${String(sequence).padStart(2, "0")}Z`,
    payload: { ...requiredPayload, ...payload },
    schema_version: "1.0",
  };
}
