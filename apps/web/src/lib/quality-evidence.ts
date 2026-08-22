export interface MeasuredQualityMetric {
  key: string;
  label: string;
  score: number;
}

export interface MeasuredQualityBreakdown {
  overall?: number;
  metrics: MeasuredQualityMetric[];
}

const metricLabels: Record<string, string> = {
  text_fidelity: "Character agreement",
  numeric_fidelity: "Number agreement",
  layout_fidelity: "Layout agreement",
  table_fidelity: "Table consistency",
  hierarchy_validity: "Schema validity",
  provenance_coverage: "Source coverage",
  repetition_safety: "Repetition safety",
  language_consistency: "Language consistency",
  markdown_validity: "Markdown schema validity",
  native_ocr_agreement: "Source / visual-route agreement",
  review_count: "Integrity finding count",
};

function finiteScore(value: unknown): number | undefined {
  if (typeof value !== "number" || !Number.isFinite(value)) return undefined;
  if (value < 0) return undefined;
  if (value <= 1) return Math.round(value * 1000) / 10;
  if (value <= 100) return Math.round(value * 10) / 10;
  return undefined;
}

function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined;
}

/**
 * Returns only measurements already present in the durable quality payload.
 * Missing values are omitted: the UI must never backfill a synthetic score.
 */
export function measuredQualityBreakdown(
  quality: Record<string, unknown> | null | undefined,
): MeasuredQualityBreakdown {
  if (!quality) return { metrics: [] };
  const evaluation =
    record(quality.evaluation_payload) ?? record(quality.evaluation) ?? quality;
  const vector = record(evaluation.vector) ?? record(quality.vector) ?? {};
  const overall = finiteScore(
    evaluation.overall_score ?? quality.overall_score,
  );
  const metrics = Object.entries(metricLabels).flatMap(([key, label]) => {
    const raw =
      vector[key] ??
      evaluation[key] ??
      quality[key] ??
      record(quality.metrics)?.[key];
    const score = finiteScore(raw);
    return score === undefined ? [] : [{ key, label, score }];
  });
  return { overall, metrics };
}
