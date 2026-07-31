import { describe, expect, it } from "vitest";

import {
  partitionFilesBySize,
  QUICK_CONVERT_MAX_FILE_BYTES,
  QUICK_CONVERT_MAX_FILE_LABEL,
} from "@/lib/upload-policy";

describe("quick-convert upload policy", () => {
  it("keeps the visible limit and accepted byte boundary aligned", () => {
    expect(QUICK_CONVERT_MAX_FILE_LABEL).toBe("50 MB");
    expect(QUICK_CONVERT_MAX_FILE_BYTES).toBe(50 * 1024 * 1024);

    const boundary = {
      name: "boundary.pdf",
      size: QUICK_CONVERT_MAX_FILE_BYTES,
    };
    const oversized = {
      name: "oversized.pdf",
      size: QUICK_CONVERT_MAX_FILE_BYTES + 1,
    };

    expect(partitionFilesBySize([boundary, oversized])).toEqual({
      accepted: [boundary],
      rejected: [oversized],
    });
  });
});
