import snapshot from "@/data/benchmark-public-snapshot.json";

export type PublicBenchmarkStatus =
  "available" | "source_adapter_ready" | "evidence_required";

export interface PublicBenchmarkMetrics {
  text_edit_companion: number | null;
  formula_edit_companion: number | null;
  table_teds: number | null;
  table_structure_teds: number | null;
  table_edit_companion: number | null;
  reading_order_companion: number | null;
  mean_latency_ms: number | null;
  cost_per_page_usd: number | null;
  exact_repeat_ratio: number | null;
}

export interface PublicBenchmarkDataset {
  id: string;
  label: string;
  source: string;
  status: PublicBenchmarkStatus;
  document_count: number | null;
  page_count: number | null;
  metrics: PublicBenchmarkMetrics;
  evidence?: {
    case_count: number;
    hard_failure_count: number;
    repeat_count: number;
    evidence_summary_sha256: string;
    inference_run_summary_sha256: string;
    ground_truth_sha256: string;
  };
}

export interface PublicBenchmarkSnapshot {
  schema_version: "1.1";
  status: "available" | "unavailable";
  generated_at: string | null;
  evaluator_version: string;
  evidence_bundle_sha256: string | null;
  corpus_revision: string | null;
  model_revision: string | null;
  hardware_profile: string | null;
  datasets: PublicBenchmarkDataset[];
}

export const publicBenchmarkSnapshot = snapshot as PublicBenchmarkSnapshot;

export function formatBenchmarkPercent(value: number | null): string {
  if (value === null) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatBenchmarkLatency(value: number | null): string {
  if (value === null) return "Not measured";
  if (value >= 1_000) return `${(value / 1_000).toFixed(3)} s`;
  return `${new Intl.NumberFormat("en-US").format(Math.round(value))} ms`;
}

export function formatBenchmarkCost(value: number | null): string {
  if (value === null) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 0.01 ? 6 : 4,
    maximumFractionDigits: value < 0.01 ? 6 : 4,
  }).format(value);
}
