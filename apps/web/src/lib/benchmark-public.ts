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
  if (value === null) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatBenchmarkLatency(value: number | null): string {
  if (value === null) return "Not measured";
  return `${new Intl.NumberFormat("en-US").format(Math.round(value))} ms`;
}

export function formatBenchmarkCost(value: number | null): string {
  if (value === null) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(value);
}


/**
 * The homepage metric table, derived rather than transcribed.
 *
 * These four rows used to be a literal array inside marketing-landing.tsx with
 * "Not measured" typed in by hand. That made the snapshot and the homepage two
 * separate claims about the same thing, and it put the benchmark session in a
 * position where publishing a result meant editing a React component in
 * someone else's directory.
 *
 * Now the only thing anyone writes is
 * `apps/web/src/data/benchmark-public-snapshot.json`. A metric with a value
 * shows it and names the corpus it came from; a metric still at null keeps
 * saying "Not measured", which §25.7 requires and which stays true by
 * construction rather than by remembering to update it.
 *
 * Source coverage is not in the snapshot because it is not a benchmark score:
 * it is an end-to-end assertion in the Playwright suite, so it reports what
 * that suite establishes and says where.
 */
export interface HomepageMetricRow {
  metric: string;
  status: string;
  evidence: string;
}

export function homepageMetricRows(
  snapshot: PublicBenchmarkSnapshot = publicBenchmarkSnapshot,
): HomepageMetricRow[] {
  // The first dataset carrying a measurement is the one the homepage cites.
  // Naming it matters: an unattributed percentage is the kind of figure §25.7
  // exists to keep off this page.
  const measured = snapshot.datasets.find((dataset) =>
    Object.values(dataset.metrics).some((value) => value !== null),
  );

  const cite = (value: number | null, fallback: string): string =>
    value === null || measured === undefined
      ? fallback
      : `${measured.label} · ${measured.document_count ?? "?"} documents`;

  return [
    {
      metric: "Text fidelity",
      status: formatBenchmarkPercent(measured?.metrics.text ?? null),
      evidence: cite(measured?.metrics.text ?? null, "Dataset required"),
    },
    {
      metric: "Numeric preservation",
      status: formatBenchmarkPercent(measured?.metrics.numbers ?? null),
      evidence: cite(measured?.metrics.numbers ?? null, "Ground truth required"),
    },
    {
      metric: "Table structure",
      status: formatBenchmarkPercent(measured?.metrics.tables ?? null),
      evidence: cite(measured?.metrics.tables ?? null, "Comparator required"),
    },
    {
      metric: "Source coverage",
      status: "Verified locally",
      evidence: "Live source-link E2E",
    },
  ];
}
