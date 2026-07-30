import { useCallback, useEffect, useRef } from "react";

export const SSE_SILENCE_FALLBACK_MS = 60_000;

export function useSseSilenceFallback({
  active,
  onSilence,
  silenceMs = SSE_SILENCE_FALLBACK_MS,
}: {
  active: boolean;
  onSilence: () => void | Promise<void>;
  silenceMs?: number;
}): () => void {
  const activeRef = useRef(active);
  const onSilenceRef = useRef(onSilence);
  const timerRef = useRef<ReturnType<typeof globalThis.setTimeout> | undefined>(
    undefined,
  );

  useEffect(() => {
    onSilenceRef.current = onSilence;
  }, [onSilence]);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== undefined) {
      globalThis.clearTimeout(timerRef.current);
      timerRef.current = undefined;
    }
  }, []);

  const schedule = useCallback(() => {
    clearTimer();
    if (!activeRef.current) return;

    const pollWhileSilent = () => {
      if (!activeRef.current) return;
      void onSilenceRef.current();
      timerRef.current = globalThis.setTimeout(pollWhileSilent, silenceMs);
    };

    timerRef.current = globalThis.setTimeout(pollWhileSilent, silenceMs);
  }, [clearTimer, silenceMs]);

  useEffect(() => {
    activeRef.current = active;
    schedule();
    return clearTimer;
  }, [active, clearTimer, schedule]);

  return useCallback(() => {
    if (activeRef.current) schedule();
  }, [schedule]);
}
