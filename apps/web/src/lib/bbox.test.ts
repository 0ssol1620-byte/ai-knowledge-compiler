import { describe, expect, it } from "vitest";

import { bbox1000ToUnit, unitToBbox1000 } from "@/lib/bbox";

describe("bbox conversion", () => {
  it("round-trips canonical integer coordinates", () => {
    const bbox: [number, number, number, number] = [103, 244, 901, 777];
    expect(unitToBbox1000(bbox1000ToUnit(bbox))).toEqual(bbox);
  });

  it("rejects inverted boxes", () => {
    expect(() => unitToBbox1000([0.8, 0.1, 0.2, 0.9])).toThrow(
      "invalid_bbox1000",
    );
  });
});
