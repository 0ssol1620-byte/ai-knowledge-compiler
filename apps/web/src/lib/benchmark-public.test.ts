import { describe, expect, it } from "vitest";

import { homepageMetricRows } from "./benchmark-public";
import { claimFigure, claimsPack, documentTypeRows } from "./claims";

/**
 * What the site is allowed to say, checked against the pack that says it.
 *
 * The pack carries editorial constraints beside its numbers, and the ones below
 * are the constraints that a component could plausibly violate by accident.
 * `scripts/verify-claims.mjs` covers the greppable half — forbidden phrasings
 * and withheld figures. These cover the half that is about structure.
 */

describe("the claims pack", () => {
  it("refuses to hand over a withheld claim", () => {
    // quality-retry-improvement has no measurement yet, and blind-quality-
    // detection was measured and rejected. Reaching for either is a mistake in
    // the calling code, so it throws rather than returning something empty that
    // would render as a blank.
    expect(() => claimFigure("quality-retry-improvement")).toThrow(/withheld/);
    expect(() => claimFigure("blind-quality-detection")).toThrow(/withheld/);
  });

  it("carries the mandatory context with every figure it publishes", () => {
    /*
     * Asserted against the requirement, not against a field name. The first
     * version of this counted `must_say_en ? 1 : 0` — the same expression the
     * implementation used — so when five approved claims turned out to ship a
     * Korean must_say with no English twin, the sentence vanished from the page
     * and this test agreed that nothing was owed. A test that mirrors the
     * implementation cannot catch the implementation.
     */
    const published = claimsPack.claims.filter(
      (claim) => claim.status !== "withheld",
    );
    for (const claim of published) {
      const figure = claimFigure(claim.id);
      const requiresContext =
        Boolean(claim.must_say) ||
        Boolean(claim.must_say_en) ||
        (claim.conditions?.length ?? 0) > 0;
      if (requiresContext) {
        expect(
          figure.context.length,
          `${claim.id} requires context but exposes none`,
        ).toBeGreaterThan(0);
      }
      for (const entry of figure.context) {
        expect(entry.text.length).toBeGreaterThan(0);
        expect(["en", "ko"]).toContain(entry.lang);
      }
    }
  });

  it("falls back to the Korean must_say when no English twin exists", () => {
    // Five approved claims are in this state. Surfacing the Korean is worse
    // than an English sentence and far better than silence, which is what the
    // page was doing.
    const figure = claimFigure("recovery-contribution-olmocr");
    expect(figure.context).toHaveLength(1);
    expect(figure.context[0]!.lang).toBe("ko");
    expect(figure.context[0]!.text).toContain("단일 변수");
  });

  it("gives conditional claims their conditions", () => {
    // The pack allows these only when the conditions are shown with them.
    for (const id of ["leaderboard-position", "cost-per-page"]) {
      expect(claimFigure(id).context.length).toBeGreaterThan(0);
    }
  });
});

describe("accuracy by document type", () => {
  it("keeps the low-quality scan row", () => {
    // Removing it is forbidden outright: the spread runs 99.0% to 36.9%, and a
    // table without the bottom row promises something the product does not do
    // for degraded scans.
    const rows = documentTypeRows();
    const worst = rows.at(-1);
    expect(rows).toHaveLength(8);
    expect(worst?.accuracy_percent).toBe(36.9);
    expect(worst?.label_en).toBe("Low-quality scans");
  });

  it("orders worst last so the spread is the last thing read", () => {
    const rows = documentTypeRows();
    const accuracies = rows.map((row) => row.accuracy_percent);
    expect(accuracies).toEqual([...accuracies].sort((a, b) => b - a));
  });

  it("every row states its denominator", () => {
    for (const row of documentTypeRows()) {
      expect(row.checks_total).toBeGreaterThan(0);
      expect(row.checks_passed).toBeLessThanOrEqual(row.checks_total);
    }
  });
});

describe("homepage metric table", () => {
  it("reports the fidelity measurements with their corpus", () => {
    const rows = homepageMetricRows();
    const text = rows.find((row) => row.metric === "Text fidelity");

    expect(text?.status).toBe("94.2%");
    // An unattributed percentage is the figure §25.7 keeps off this page, and
    // the pack's first global rule is that every ratio carries its denominator.
    expect(text?.evidence).toContain("5,132 documents");
    expect(text?.evidence).toContain("OmniDocBench");
  });

  it("keeps the completion rate off the accuracy table", () => {
    // 99.98% is the share that produced output. Calling it accuracy is listed
    // as forbidden, and a row here is exactly the position that would.
    const rows = homepageMetricRows();
    for (const row of rows) {
      expect(row.status).not.toContain("99.98");
      expect(row.metric).not.toMatch(/completion/i);
    }
  });

  it("keeps the check pass rate off it too", () => {
    // 80.6% measures something different from 94.2%, and the pack requires
    // labelling which is which when both appear. They are kept apart instead.
    for (const row of homepageMetricRows()) {
      expect(row.status).not.toContain("80.6");
    }
  });

  it("keeps source coverage out of the benchmark claim", () => {
    const row = homepageMetricRows().find(
      (candidate) => candidate.metric === "Source coverage",
    );
    // An end-to-end assertion, not a score. It must not start reporting a
    // percentage just because the surrounding rows do.
    expect(row?.status).toBe("Verified locally");
    expect(row?.evidence).toBe("Live source-link E2E");
  });
});
