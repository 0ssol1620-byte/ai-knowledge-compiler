import { TavonelSymbol } from "@/components/brand/tavonel-symbol";

/**
 * Brand lockup — DESIGN_MASTER_V3 §8.2.
 *
 *   uppercase, weight 620 (or plan B's 590 stop), tracking +0.14em
 *   symbol-to-wordmark gap = symbol width × 0.5
 *   no gradient · no mono wordmark · symbol never rotates
 *
 * Four lockups are specified: horizontal, stacked, symbol-only, and KO
 * alongside. `compact` is the symbol-only lockup.
 *
 * The label carries translate="no" per §7.5 — a product name is not a phrase
 * for a browser to translate.
 */
export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="brand tv-brand" aria-label="TAVONEL" translate="no">
      <TavonelSymbol size={26} />
      {!compact && (
        <span className="brand-copy tv-brand-copy">
          <span>TAVONEL</span>
          <small>The Knowledge Compiler</small>
        </span>
      )}
    </span>
  );
}
