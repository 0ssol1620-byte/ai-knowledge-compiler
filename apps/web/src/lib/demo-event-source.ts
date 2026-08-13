import type { ScheduledEvent } from "@/lib/demo-workspace";
import type { ProductEvent, ProductEventSource } from "@/lib/product-event";

/**
 * `DemoFixtureEventSource` — one half of the source abstraction.
 *
 * Replays a frozen schedule through the same `ProductEventSource` interface
 * the SSE client implements, so the components downstream cannot tell which
 * one they are attached to. That is the requirement: no demo-only UI.
 *
 * Three properties it has that a naive `setInterval` walker does not:
 *
 *   deterministic   the schedule is data. Same input, same order, same
 *                   sequence numbers — which is what makes the Playwright
 *                   baselines stable and the fixture reviewable.
 *   compressible    `speed` scales the clock. A visitor who has already
 *                   watched the compile does not watch it again at 1×.
 *   collapsible     `finish()` emits every remaining event at once. This is
 *                   how `prefers-reduced-motion` and the replay control both
 *                   reach the final frame with zero information lost —
 *                   §10.4's requirement, met by delivering the events rather
 *                   than by skipping to a hardcoded end state.
 *
 * Timers are `setTimeout` per event rather than one interval: an interval
 * would have to poll, and a poll that fires when nothing is due is the
 * "permanent animation" §10.4 bans.
 */
export class DemoFixtureEventSource implements ProductEventSource {
  readonly mode = "demo" as const;
  readonly label = "Sample workspace · replay";

  private readonly schedule: readonly ScheduledEvent[];
  private readonly speed: number;
  private readonly listeners = new Set<(event: ProductEvent) => void>();
  private readonly timers: ReturnType<typeof setTimeout>[] = [];
  private cursor = 0;
  private running = false;

  constructor(
    schedule: readonly ScheduledEvent[],
    options: { speed?: number } = {},
  ) {
    this.schedule = schedule;
    this.speed = options.speed && options.speed > 0 ? options.speed : 1;
  }

  subscribe(listener: (event: ProductEvent) => void): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    for (let index = this.cursor; index < this.schedule.length; index += 1) {
      const scheduled = this.schedule[index];
      if (!scheduled) continue;
      const delay = scheduled.atMs / this.speed;
      this.timers.push(
        setTimeout(() => {
          this.cursor = index + 1;
          this.emit(scheduled.event);
        }, delay),
      );
    }
  }

  stop(): void {
    this.running = false;
    for (const timer of this.timers) clearTimeout(timer);
    this.timers.length = 0;
  }

  /**
   * Deliver everything still pending, immediately and in order.
   *
   * Reduced motion is attenuation, not removal: the visitor gets the same
   * events and therefore the same final screen, just without the seven
   * seconds of staging.
   */
  finish(): void {
    this.stop();
    for (let index = this.cursor; index < this.schedule.length; index += 1) {
      const scheduled = this.schedule[index];
      if (!scheduled) continue;
      this.emit(scheduled.event);
    }
    this.cursor = this.schedule.length;
  }

  seek(sequence: number): void {
    this.stop();
    this.cursor = Math.max(
      0,
      this.schedule.findIndex((entry) => entry.event.sequence >= sequence),
    );
  }

  private emit(event: ProductEvent): void {
    for (const listener of this.listeners) listener(event);
  }
}
