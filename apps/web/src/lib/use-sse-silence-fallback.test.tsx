import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  SSE_SILENCE_FALLBACK_MS,
  useSseSilenceFallback,
} from "@/lib/use-sse-silence-fallback";

afterEach(() => {
  vi.useRealTimers();
});

describe("useSseSilenceFallback", () => {
  it("does not poll before sixty seconds of SSE silence", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();
    renderHook(() => useSseSilenceFallback({ active: true, onSilence }));

    act(() => {
      vi.advanceTimersByTime(SSE_SILENCE_FALLBACK_MS - 1);
    });
    expect(onSilence).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onSilence).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(SSE_SILENCE_FALLBACK_MS);
    });
    expect(onSilence).toHaveBeenCalledTimes(2);
  });

  it("resets the silence deadline after an event or heartbeat", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();
    const { result } = renderHook(() =>
      useSseSilenceFallback({ active: true, onSilence }),
    );

    act(() => {
      vi.advanceTimersByTime(45_000);
      result.current();
      vi.advanceTimersByTime(SSE_SILENCE_FALLBACK_MS - 1);
    });
    expect(onSilence).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onSilence).toHaveBeenCalledTimes(1);
  });

  it("stops the fallback after the job becomes terminal", () => {
    vi.useFakeTimers();
    const onSilence = vi.fn();
    const { rerender } = renderHook(
      ({ active }) => useSseSilenceFallback({ active, onSilence }),
      { initialProps: { active: true } },
    );

    rerender({ active: false });
    act(() => {
      vi.advanceTimersByTime(SSE_SILENCE_FALLBACK_MS * 2);
    });
    expect(onSilence).not.toHaveBeenCalled();
  });
});
