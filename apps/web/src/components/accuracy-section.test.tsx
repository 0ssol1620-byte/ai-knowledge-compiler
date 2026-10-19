import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AccuracySection } from "@/components/accuracy-section";
import { claimsPack, type BenchmarkAccuracy } from "@/lib/claims";

afterEach(cleanup);

/**
 * The captions under the headline figure are the one place this section says
 * in its own words what 80.6 is, so they are held to the pack's sentence.
 *
 * They used to pair "80.6%" with "7,137 of 8,413 checks", which reads as 80.6%
 * of 8,413 checks. It is not: 80.6 is the unweighted mean of the eight per-type
 * pass rates, and counted check by check the rate is 7,137/8,413 (84.8%). The
 * pack's must_say says exactly that and forbids the pairing.
 */
describe("accuracy figure", () => {
  it("labels the figure the way the shipped pack's must_say does", () => {
    const claim = claimsPack.claims.find((c) => c.id === "benchmark-accuracy");
    const mustSay = claim?.must_say_en ?? "";
    const numbers = claim?.numbers as BenchmarkAccuracy;
    expect(mustSay, "benchmark-accuracy ships no must_say_en").not.toBe("");

    const { container } = render(<AccuracySection />);
    const captions = Array.from(
      container.querySelectorAll(".tv-accuracy-figure span"),
      (span) => span.textContent ?? "",
    );

    // The first caption names what the headline number is.
    const meaning = (captions[0] ?? "").split(" · ").at(-1);
    expect(mustSay).toContain(`${numbers.overall_percent} is the ${meaning}`);

    // The check count appears only as the check-level rate the pack states.
    const total = numbers.checks_total.toLocaleString("en-US");
    const counted = captions.filter((caption) => caption.includes(total));
    expect(counted).toHaveLength(1);
    expect(mustSay).toContain(counted[0]);
  });
});
