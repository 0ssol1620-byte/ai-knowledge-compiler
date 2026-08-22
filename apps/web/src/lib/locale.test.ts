import { describe, expect, it } from "vitest";

import {
  DEFAULT_STRUCTARA_LOCALE,
  normalizeStructaraLocale,
} from "@/lib/locale";

describe("locale authority", () => {
  it("defaults unknown and absent locale values to Korean", () => {
    expect(DEFAULT_STRUCTARA_LOCALE).toBe("ko");
    expect(normalizeStructaraLocale(undefined)).toBe("ko");
    expect(normalizeStructaraLocale("fr")).toBe("ko");
  });

  it("preserves both supported explicit locale values", () => {
    expect(normalizeStructaraLocale("ko")).toBe("ko");
    expect(normalizeStructaraLocale("en")).toBe("en");
  });
});
