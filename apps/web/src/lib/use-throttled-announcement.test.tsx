import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useThrottledAnnouncement } from "@/lib/use-throttled-announcement";

function AnnouncementProbe({ message }: { message: string }) {
  const announcement = useThrottledAnnouncement(message, 4_000);
  return <output>{announcement}</output>;
}

describe("useThrottledAnnouncement", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("announces immediately, then emits only the latest queued update", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-07-29T00:00:00Z"));
    const { rerender } = render(<AnnouncementProbe message="10 percent" />);
    expect(screen.getByText("10 percent")).toBeInTheDocument();

    rerender(<AnnouncementProbe message="11 percent" />);
    expect(screen.queryByText("11 percent")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    rerender(<AnnouncementProbe message="15 percent" />);
    act(() => {
      vi.advanceTimersByTime(1_999);
    });
    expect(screen.queryByText("15 percent")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText("15 percent")).toBeInTheDocument();
  });
});
