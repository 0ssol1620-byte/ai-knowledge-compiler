import { describe, expect, it } from "vitest";

import {
  homepageMetricRows,
  publicBenchmarkSnapshot,
  type PublicBenchmarkSnapshot,
} from "./benchmark-public";

/**
 * The handoff between the benchmark work and this site.
 *
 * The benchmark session writes one file — data/benchmark-public-snapshot.json —
 * and nothing else. These tests pin what happens at both ends of that file so
 * neither side has to read the other's code to know what will render.
 *
 * The empty case is the one that matters most. §25.7 forbids publishing a
 * figure nothing measured, and the previous version of this table typed
 * "Not measured" in by hand — true only for as long as somebody remembered to
 * keep it true.
 */

const EMPTY = publicBenchmarkSnapshot;

const MEASURED: PublicBenchmarkSnapshot = {
  ...EMPTY,
  status: "available",
  generated_at: "2026-08-08T00:00:00Z",
  datasets: [
    {
      id: "ko-dart",
      label: "KO DART",
      source: "OpenDART",
      status: "available",
      document_count: 120,
      page_count: 4310,
      metrics: {
        text: 0.981,
        numbers: 0.994,
        tables: 0.912,
        provenance: 1,
        p95_latency_ms: 8400,
        cost_per_page_usd: 0.0031,
      },
      evidence: {
        case_count: 120,
        hard_failure_count: 0,
        score_records_sha256: "a".repeat(64),
        corpus_manifest_sha256: "b".repeat(64),
      },
    },
    ...EMPTY.datasets.filter((dataset) => dataset.id !== "ko-dart"),
  ],
};

describe("homepage metric table", () => {
  it("says Not measured while the snapshot is empty", () => {
    const rows = homepageMetricRows(EMPTY);
    const scored = rows.filter((row) => row.metric !== "Source coverage");

    expect(scored).toHaveLength(3);
    for (const row of scored) {
      expect(row.status).toBe("Not measured");
      // The evidence column says what is missing, not a percentage.
      expect(row.evidence).toMatch(/required$/);
    }
  });

  it("reports the measurement and names the corpus once one exists", () => {
    const rows = homepageMetricRows(MEASURED);
    const text = rows.find((row) => row.metric === "Text fidelity");

    expect(text?.status).toBe("98.1%");
    // A percentage with no corpus behind it is the figure §25.7 keeps off the
    // page, so the citation travels with the number.
    expect(text?.evidence).toBe("KO DART · 120 documents");
  });

  it("leaves a metric the run did not cover at Not measured", () => {
    const partial: PublicBenchmarkSnapshot = {
      ...MEASURED,
      datasets: [
        {
          ...MEASURED.datasets[0]!,
          metrics: { ...MEASURED.datasets[0]!.metrics, tables: null },
        },
        ...MEASURED.datasets.slice(1),
      ],
    };

    const rows = homepageMetricRows(partial);
    expect(rows.find((row) => row.metric === "Table structure")?.status).toBe(
      "Not measured",
    );
    expect(rows.find((row) => row.metric === "Text fidelity")?.status).toBe(
      "98.1%",
    );
  });

  it("keeps source coverage out of the benchmark claim", () => {
    // It is an end-to-end assertion in the Playwright suite, not a score, so
    // it must not start reporting a percentage when the snapshot fills in.
    for (const snapshot of [EMPTY, MEASURED]) {
      const row = homepageMetricRows(snapshot).find(
        (candidate) => candidate.metric === "Source coverage",
      );
      expect(row?.status).toBe("Verified locally");
      expect(row?.evidence).toBe("Live source-link E2E");
    }
  });
});
