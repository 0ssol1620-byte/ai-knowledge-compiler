import { describe, expect, it, vi } from "vitest";

import { hasUsableWebGL2 } from "./structara-hero";

describe("hasUsableWebGL2", () => {
  it("releases a successfully created probe context", () => {
    const loseContext = vi.fn();
    const canvas = {
      getContext: vi.fn(() => ({
        getExtension: vi.fn(() => ({ loseContext })),
      })),
    } as unknown as HTMLCanvasElement;

    expect(hasUsableWebGL2(canvas)).toBe(true);
    expect(loseContext).toHaveBeenCalledOnce();
  });

  it("fails closed when WebGL2 is unavailable or blocked", () => {
    const unavailable = {
      getContext: vi.fn(() => null),
    } as unknown as HTMLCanvasElement;
    const blocked = {
      getContext: vi.fn(() => {
        throw new Error("blocked by browser policy");
      }),
    } as unknown as HTMLCanvasElement;

    expect(hasUsableWebGL2(unavailable)).toBe(false);
    expect(hasUsableWebGL2(blocked)).toBe(false);
  });
});
