import { Flask } from "@phosphor-icons/react";

/**
 * The visible "this is not real data" label every WORLD/SOURCE/CHANGE/ASK
 * surface renders while fed by `DemoFixtureEventSource`.
 *
 * A code comment or a `mode` field nobody reads is not a label — this has to
 * appear in the rendered page. It reads `mode` rather than assuming demo, so
 * the day a live source is attached this renders nothing instead of lying.
 */
export function SampleWorldBadge({
  mode,
  label,
}: {
  mode: "demo" | "live";
  label: string;
}) {
  if (mode !== "demo") return null;
  return (
    <div className="sample-world-badge" role="status">
      <Flask size={16} weight="duotone" aria-hidden="true" />
      <div>
        <strong>SAMPLE WORLD</strong>
        <span>{label} · invented data, not a live workspace</span>
      </div>
    </div>
  );
}
