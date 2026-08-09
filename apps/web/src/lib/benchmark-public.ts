import snapshot from "@/data/benchmark-public-snapshot.json";
import {
  claimFigure,
  type CorpusScale,
  type FidelityMetrics,
} from "@/lib/claims";

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
 * The homepage metric table, from the public claims pack.
 *
 * These four rows were a literal array with "Not measured" typed in by hand,
 * then briefly derived from benchmark-public-snapshot.json, which was never
 * filled. The measurements arrived instead as a claims pack — numbers with the
 * editorial constraints that make them defensible — so that is the source now.
 *
 * Two of the pack's rules shape this table specifically:
 *
 *   completion-rate is not on it. 99.98% is the share of documents that
 *   produced output, the pack forbids calling that accuracy, and a row in an
 *   accuracy table is exactly the position that would.
 *
 *   the 80.6% check pass rate and the 94.2% character match are different
 *   measures, and customer-facing-fidelity requires labelling which is which
 *   when both appear. This table carries the fidelity figures, which are the
 *   ones a reader can act on; the pass rate lives in the accuracy section with
 *   its own context.
 */
export interface HomepageMetricRow {
  metric: string;
  status: string;
  evidence: string;
}

export function homepageMetricRows(): HomepageMetricRow[] {
  const fidelity = claimFigure<FidelityMetrics>("customer-facing-fidelity");
  const corpus = claimFigure<CorpusScale>("corpus-scale");
  // Every ratio carries its denominator — the pack's first global rule.
  const corpusNote = `${corpus.numbers.documents.toLocaleString("en-US")} documents`;

  return [
    {
      metric: "Text fidelity",
      status: `${fidelity.numbers.text_character_match_percent}%`,
      evidence: `Character match · OmniDocBench · ${corpusNote}`,
    },
    {
      metric: "Table structure",
      status: `${fidelity.numbers.table_structure_percent}%`,
      evidence: `Structure accuracy · OmniDocBench · ${corpusNote}`,
    },
    {
      metric: "Reading order",
      status: `${fidelity.numbers.reading_order_match_percent}%`,
      evidence: `Order match · OmniDocBench · ${corpusNote}`,
    },
    {
      metric: "Source coverage",
      status: "Verified locally",
      evidence: "Live source-link E2E",
    },
  ];
}
