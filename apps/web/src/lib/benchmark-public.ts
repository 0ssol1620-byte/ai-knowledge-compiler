import snapshot from "@/data/benchmark-public-snapshot.json";
import {
  claimFigure,
  type CorpusScale,
  type FidelityMetrics,
} from "@/lib/claims";

export type PublicBenchmarkStatus =
  "available" | "source_adapter_ready" | "evidence_required";

/*
 * Two generations of this snapshot exist and they are not a version apart.
 *
 * 1.0 was written before anything had been measured: every dataset carried
 * text / numbers / tables / provenance / p95_latency_ms, all null. 1.1 is what
 * the OmniDocBench run actually emits, and its fields are the metrics that run
 * computes -- edit-distance companions, TEDS, mean latency.
 *
 * The two are not renames of each other. p95 latency and mean latency are
 * different statistics, and nothing measured a provenance score, so mapping one
 * set onto the other would be inventing numbers. The measured fields are
 * required; the 1.0 fields stay optional and nullable, which is exactly what
 * they always were, so a component still reading them renders "Not measured"
 * rather than a figure nobody produced.
 */
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
  /** 1.0 only, and never populated. */
  text?: number | null;
  numbers?: number | null;
  tables?: number | null;
  provenance?: number | null;
  p95_latency_ms?: number | null;
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

export function formatBenchmarkPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function formatBenchmarkLatency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not measured";
  if (value >= 1_000) return `${(value / 1_000).toFixed(3)} s`;
  return `${new Intl.NumberFormat("en-US").format(Math.round(value))} ms`;
}

export function formatBenchmarkCost(value: number | null | undefined): string {
  if (value === null || value === undefined) return "Not measured";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: value < 0.01 ? 6 : 4,
    maximumFractionDigits: value < 0.01 ? 6 : 4,
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
