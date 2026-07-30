import snapshot from "@/data/benchmark-public-snapshot.json";

export type PublicBenchmarkStatus =
  "available" | "source_adapter_ready" | "evidence_required";

export interface PublicBenchmarkMetrics {
  text: number | null;
  numbers: number | null;
  tables: number | null;
  provenance: number | null;
  p95_latency_ms: number | null;
  cost_per_page_usd: number | null;
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
    score_records_sha256: string;
    corpus_manifest_sha256: string;
  };
}

export interface PublicBenchmarkSnapshot {
  schema_version: "1.0";
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
  if (value === null) return "측정 전";
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatBenchmarkLatency(value: number | null): string {
  if (value === null) return "측정 전";
  return `${new Intl.NumberFormat("ko-KR").format(Math.round(value))} ms`;
}

export function formatBenchmarkCost(value: number | null): string {
  if (value === null) return "측정 전";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(value);
}
