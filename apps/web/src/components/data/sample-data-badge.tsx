"use client";

import { Flask } from "@phosphor-icons/react";

import type { MarkedData } from "@/lib/data-boundary";
import { isSample } from "@/lib/data-boundary";

/**
 * The generic SAMPLE badge renderer for `lib/data-boundary.ts` envelopes on
 * app surfaces outside the WORLD namespace (which keeps its richer
 * `SampleWorldBadge`). The boundary contract: fixture data may reach the
 * screen only inside a `SampleMarked` envelope, and that envelope's badge has
 * to be visible — this component is where the badge becomes pixels.
 *
 * It reads the envelope rather than assuming demo mode, so live-marked data
 * renders nothing instead of lying. There is deliberately no way to render
 * the label without going through `marked.badge.label`, whose `"SAMPLE"`
 * literal is pinned by the type.
 */
export function SampleDataBadge<T>({ value }: { value: MarkedData<T> }) {
  if (!isSample(value)) return null;
  return (
    <div className="sample-data-badge" role="status">
      <Flask size={14} weight="duotone" aria-hidden="true" />
      <span>{value.badge.label}</span>
    </div>
  );
}
