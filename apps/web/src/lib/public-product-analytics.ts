import { track } from "@vercel/analytics";

export type PublicProductEvent =
  | "landing_demo_started"
  | "landing_demo_completed"
  | "pricing_viewed"
  | "signup_started";

/** Public events are deliberately name-only: no content or visitor attributes. */
export function recordPublicProductEvent(event: PublicProductEvent): void {
  track(event);
}
