import pack from "@/data/claims/public-claims-pack.json";

/**
 * The public claims pack — what may be said on this site, with its evidence.
 *
 * Produced by the benchmark session from campaign receipts and committed here
 * verbatim. `apps/web/src/data/claims/public-claims-pack.json` is generated
 * output: a number is corrected by regenerating the receipt upstream, never by
 * editing the file. Its own instructions say so, and the receipt hash is what
 * makes that checkable.
 *
 * The reason this is a module rather than four numbers pasted into components
 * is the part of the pack that is not numbers. Nearly every claim arrives with
 * a `must_say` — a sentence that has to appear wherever the figure appears —
 * and several arrive with `forbidden` phrasings. Those are not review notes.
 * They are the difference between a defensible number and a misleading one:
 *
 *   completion-rate            99.98% is the share that produced output. It is
 *                              not accuracy, and calling it accuracy is listed
 *                              as forbidden.
 *   benchmark-accuracy         80.6% is a pass rate over 8,413 adversarial
 *                              checks. The top published system scores 83.1,
 *                              so the reference point is not 100, and 72.3% of
 *                              documents carry at least one failure.
 *   accuracy-by-document-type  the spread runs 99.0% to 36.9%. Omitting the
 *                              low-quality scan row is forbidden outright.
 *
 * So `claimFigure()` returns the number and its mandatory context together, and
 * the components that render it take both. Splitting them requires deliberately
 * dropping a field rather than merely forgetting one.
 *
 * The pack is written in the pre-rename vocabulary — its schema id and evidence
 * paths say FOLYNTA. Those strings are producer identifiers and stay untouched;
 * nothing in them reaches the screen.
 */

export type ClaimStatus = "approved" | "conditional" | "withheld";

export interface Claim {
  id: string;
  status: ClaimStatus;
  headline_ko?: string;
  headline_en?: string;
  numbers?: unknown;
  must_say?: string;
  must_say_en?: string;
  forbidden?: string[];
  conditions?: string[];
  evidence?: string;
  evidence_sha256?: string;
  why_withheld?: string;
  unblocks_when?: string;
}

export interface ClaimsPack {
  schema: string;
  receipt_sha256: string;
  claim_count: number;
  counts_by_status: Record<ClaimStatus, number>;
  global_rules: string[];
  how_to_use: string[];
  purpose: string;
  claims: Claim[];
}

export const claimsPack = pack as unknown as ClaimsPack;

const BY_ID = new Map(claimsPack.claims.map((claim) => [claim.id, claim]));

/**
 * A claim ready to render: the numbers, and the context that must travel with
 * them.
 *
 * Throws for a withheld claim rather than returning something empty. A withheld
 * claim reaching a component is a mistake in the calling code — `withheld` means
 * the measurement does not exist or the hypothesis failed — and a build that
 * stops is the correct response to publishing an unmeasured figure.
 */
export interface ClaimContext {
  text: string;
  /** BCP-47 tag, so the renderer can mark up and typeset it correctly. */
  lang: "en" | "ko";
}

export interface ClaimFigure<T = unknown> {
  id: string;
  numbers: T;
  /** Renders beside the number. Never optional at the call site. */
  context: ClaimContext[];
  evidence?: string;
  evidenceDigest?: string;
}

export function claimFigure<T = unknown>(id: string): ClaimFigure<T> {
  const claim = BY_ID.get(id);
  if (!claim) {
    throw new Error(`claims: no claim with id "${id}"`);
  }
  if (claim.status === "withheld") {
    throw new Error(
      `claims: "${id}" is withheld and must not be rendered. ` +
        (claim.why_withheld ?? ""),
    );
  }

  /*
   * Every mandatory sentence, in whatever language the pack supplies it.
   *
   * The first version of this read must_say_en only. Five approved claims ship
   * a Korean must_say with no English twin — completion-rate, recovery-rate,
   * both recovery counterfactuals, and compilation-guarantees — so their
   * mandatory sentence silently vanished and the figures rendered bare. That is
   * exactly the failure this module exists to prevent, and it shipped because
   * the check tested for the English field rather than for the requirement.
   *
   * The Korean is surfaced rather than translated here. The pack is generated
   * evidence and its constraint text is part of it; writing an English version
   * in this file would be authoring the constraint instead of carrying it. The
   * gap is reported upstream so the next regeneration can include must_say_en.
   *
   * A conditional claim's conditions are as mandatory as an approved claim's
   * must_say — the pack's instruction is that it may be used "only when the
   * conditions are shown with it".
   */
  const context: ClaimContext[] = [
    ...(claim.must_say_en
      ? [{ text: claim.must_say_en, lang: "en" as const }]
      : claim.must_say
        ? [{ text: claim.must_say, lang: "ko" as const }]
        : []),
    ...(claim.conditions ?? []).map((text) => ({ text, lang: "ko" as const })),
  ];

  if ((claim.must_say || claim.conditions?.length) && context.length === 0) {
    throw new Error(
      `claims: "${id}" requires context that could not be resolved`,
    );
  }

  return {
    id: claim.id,
    numbers: claim.numbers as T,
    context,
    evidence: claim.evidence,
    evidenceDigest: claim.evidence_sha256,
  };
}

export function claimStatus(id: string): ClaimStatus | undefined {
  return BY_ID.get(id)?.status;
}

/* ── shapes for the claims this site renders ─────────────────────────────── */

export interface BenchmarkAccuracy {
  benchmark: string;
  overall_percent: number;
  confidence_interval_95: [number, number];
  checks_passed: number;
  checks_total: number;
  documents_with_at_least_one_failure_percent: number;
}

export interface FidelityMetrics {
  text_character_match_percent: number;
  reading_order_match_percent: number;
  table_structure_percent: number;
  table_full_percent: number;
}

export interface DocumentTypeRow {
  label_en: string;
  label_ko: string;
  accuracy_percent: number;
  checks_passed: number;
  checks_total: number;
  /** An internal evaluator filename. The pack forbids showing it. */
  benchmark_slice: string;
}

export interface CorpusScale {
  documents: number;
  benchmarks: string[];
  per_benchmark: Record<string, number>;
}

/**
 * Accuracy per document type, worst last.
 *
 * Sorted rather than filtered, and that is the point: `accuracy-by-document-type`
 * forbids "a partial table with the low-quality scan row removed". Ordering by
 * accuracy puts 36.9% at the bottom where a reader ends, instead of letting it
 * be lost in the middle of eight rows.
 */
export function documentTypeRows(): DocumentTypeRow[] {
  const figure = claimFigure<DocumentTypeRow[]>("accuracy-by-document-type");
  return [...figure.numbers].sort(
    (a, b) => b.accuracy_percent - a.accuracy_percent,
  );
}
