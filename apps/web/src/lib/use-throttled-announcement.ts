"use client";

import { useEffect, useRef, useState } from "react";

export function useThrottledAnnouncement(
  message: string,
  intervalMs = 4_000,
): string {
  const [announcement, setAnnouncement] = useState("");
  const latestMessage = useRef(message);
  const hasAnnounced = useRef(false);
  const lastAnnouncedAt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => {
    latestMessage.current = message;
    if (!message) return;

    const now = Date.now();
    const elapsed = now - lastAnnouncedAt.current;
    const announce = () => {
      timer.current = undefined;
      hasAnnounced.current = true;
      lastAnnouncedAt.current = Date.now();
      setAnnouncement(latestMessage.current);
    };

    if (!hasAnnounced.current || elapsed >= intervalMs) {
      if (timer.current) clearTimeout(timer.current);
      announce();
      return;
    }

    if (!timer.current) {
      timer.current = setTimeout(announce, intervalMs - elapsed);
    }
  }, [intervalMs, message]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return announcement;
}
