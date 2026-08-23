import { describe, expect, it } from "vitest";

import {
  asLive,
  asSample,
  dataSourceOf,
  isLive,
  isSample,
  markedValue,
  SAMPLE_BADGE_LABEL,
  type MarkedData,
  type SampleMarked,
} from "@/lib/data-boundary";

describe("data-boundary asSample", () => {
  it("wraps fixture data with the sample source and a forced SAMPLE badge", () => {
    const marked = asSample({ term: "2 years" });

    expect(marked.source).toBe("sample");
    expect(marked.badge.label).toBe(SAMPLE_BADGE_LABEL);
    expect(marked.badge.label).toBe("SAMPLE");
    expect(marked.data).toEqual({ term: "2 years" });
  });

  it("attaches the badge unconditionally — there is no badge-free sample", () => {
    for (const payload of [null, [], "fixture", 0, { nested: true }]) {
      const marked = asSample(payload);
      expect(marked.badge).toEqual({ label: "SAMPLE" });
    }
  });

  it("freezes the envelope so the badge cannot be stripped after construction", () => {
    const marked = asSample([1, 2, 3]);

    expect(Object.isFrozen(marked)).toBe(true);
    expect(Object.isFrozen(marked.badge)).toBe(true);
  });

  it("keeps the original payload reference reachable via .data and markedValue", () => {
    const payload = { id: "u_warranty_2026" };
    const marked = asSample(payload);

    expect(marked.data).toBe(payload);
    expect(markedValue(marked)).toBe(payload);
  });
});

describe("data-boundary isLive guard", () => {
  it("narrows live-marked data to the live branch", () => {
    const value: MarkedData<string> = asLive("from the backend");

    expect(isLive(value)).toBe(true);
    if (isLive(value)) {
      expect(value.source).toBe("live");
      expect(value.data).toBe("from the backend");
    }
  });

  it("rejects sample-marked data — that branch owes the SAMPLE badge", () => {
    const value: MarkedData<string> = asSample("from the fixture");

    expect(isLive(value)).toBe(false);
    expect(isSample(value)).toBe(true);
    if (isSample(value)) {
      // The badge is present exactly when the data is not live.
      expect(value.badge.label).toBe("SAMPLE");
    }
  });

  it("reports the boundary side as data via dataSourceOf", () => {
    expect(dataSourceOf(asLive(1))).toBe("live");
    expect(dataSourceOf(asSample(1))).toBe("sample");
  });
});

describe("data-boundary type contract (compile-time)", () => {
  it("forbids constructing SampleMarked without asSample", () => {
    // A literal has no access to the module-private brand key, so this must
    // not type-check. The `@ts-expect-error` below is verified by
    // `pnpm --filter @akc/web typecheck`; if someone ever relaxes the brand,
    // tsc flags the unused suppression here.
    // @ts-expect-error SampleMarked is only constructible via asSample()
    const forged: SampleMarked<number> = {
      source: "sample",
      badge: { label: "SAMPLE" },
      data: 42,
    };
    // Runtime can still lie (the brand is compile-time); the guard catches
    // the shape, which is why every consumer narrows through isLive/isSample.
    expect(forged.data).toBe(42);
    expect(isLive(forged)).toBe(false);
  });

  it("accepts only real envelopes in MarkedData positions", () => {
    const envelopes: MarkedData<readonly string[]>[] = [
      asSample(["fixture"]),
      asLive(["backend"]),
    ];

    expect(envelopes.map(dataSourceOf)).toEqual(["sample", "live"]);
    expect(envelopes.map((envelope) => isLive(envelope))).toEqual([
      false,
      true,
    ]);
  });
});
