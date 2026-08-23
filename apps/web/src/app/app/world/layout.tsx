"use client";

import { useMemo, type ReactNode } from "react";

import { SampleWorldBadge } from "@/components/world/sample-world-badge";
import { asSample } from "@/lib/data-boundary";
import { createSampleWorldSource } from "@/lib/demo-world-source";
import { ProductWorldProvider, useProductWorld } from "@/lib/product-world-context";

function WorldFrame({ children }: { children: ReactNode }) {
  const { mode, label } = useProductWorld();
  return (
    <div className="page-shell world-page">
      <SampleWorldBadge mode={mode} label={label} />
      {children}
    </div>
  );
}

/**
 * Owns the one `ProductEventSource` this whole WORLD/SOURCE/CHANGE/ASK
 * namespace shares, so navigating between the WORLD index and an object's
 * SOURCE/CHANGE/ASK tabs never resets the compiled world — it is one shared
 * state, browsed through four routes, exactly as the brief specifies.
 *
 * `useMemo` (not module scope) so the source — and the replay it drives —
 * is created fresh per mount of this layout, not shared across unrelated
 * page loads or leaked across users in a way that would matter once a real
 * source exists.
 */
export default function WorldLayout({ children }: { children: ReactNode }) {
  // The fixture source crosses the SAMPLE/LIVE data boundary here — the one
  // hand-off in the WORLD namespace. `asSample` attaches the SAMPLE badge the
  // frame below renders, and the type makes feeding this provider anything
  // unmarked a compile error, not a review note.
  const sample = useMemo(() => asSample(createSampleWorldSource()), []);
  return (
    <ProductWorldProvider source={sample.data}>
      <WorldFrame>{children}</WorldFrame>
    </ProductWorldProvider>
  );
}
